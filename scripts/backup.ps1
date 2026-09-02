<#
.SYNOPSIS
    P0.6-MIN - nightly logical backup of the quant_model database. Closes TG4.

.DESCRIPTION
    Dumps the live database to a timestamped custom-format file, verifies the dump is
    readable, copies it to a second location, prunes old copies, and records the run as a
    `connector_runs` row so the freshness monitor sees backups stop, not only data stop.

    Sources:
      docs/02_INFRASTRUCTURE.md         section 8               - the shell original this replaces
      docs/10_PRE_BUILD_CORRECTIONS.md  5.1, 5.2, 5.3, 5.6, 6.1 - the corrections applied

    WHY THIS IS POWERSHELL AND NOT backup.sh
      docs/10 section 5.6: "backup.sh must become backup.ps1; pg_dump is not on PATH when
      Postgres is in the container." On this machine there is no pg_dump, no psql, no gpg
      and no rclone at all.

    WHY pg_dump RUNS IN DOCKER, AND WHY THE IMAGE TAG IS 18
      There is no local PostgreSQL client, so pg_dump is invoked from the postgres:18
      image. THE CLIENT MAJOR VERSION MUST BE >= THE SERVER'S. The server is Neon
      PostgreSQL 18.6; a pg_dump older than the server aborts with

          server version: 18.6; pg_dump version: 17.x
          aborting because of server version mismatch

      and it will not dump a single row. If you ever see that, the fix is the image tag in
      $PgImage below, not the server. Bump this when the server's major version moves.

    HOW THE CONNECTION STRING IS PASSED
      Never on a command line. `docker run -e PGCONN` (name only, no value) copies the
      value out of this process's environment into the container, so the URL never appears
      in the host process list, in `docker ps`, or in PowerShell history. Inside the
      container a shell expands it, so it never appears in this repository either.

    WHAT THIS SCRIPT DELIBERATELY DOES NOT DO
      * It does not `rclone sync` anything. docs/10 section 5.1: sync makes the destination
        match the source BY DELETING, so ransomware or a bad re-extract propagates off-site
        and destroys the only copy of PDFs whose source URLs have rotated. The off-site
        tier, when built, uses `rclone copy --immutable` only.
      * It does not encrypt. docs/10 section 6.1 defers the gpg/rclone/R2 chain to P3
        entry, and docs/10 section 5.2 warns that an encryption path whose private key
        lives only on this laptop is worse than none. See Invoke-OffsiteHook below - it is
        an unimplemented, clearly-marked hook, not a stub that pretends to work.

.PARAMETER SecondaryDir
    Second location for the dump. Defaults to $env:BACKUP_SECONDARY_DIR, then to
    "$env:USERPROFILE\quant_model_backups".

    READ THIS: this machine has ONE physical disk (C:). A second directory on C: protects
    against DROP DATABASE, a bad migration, and an rm -rf of the repo. It does NOT protect
    against disk failure, theft or ransomware, and it is NOT the "two kinds of media, one
    off-site" of docs/02 section 8's 3-2-1 rule. The script says so at the end of every
    run, on purpose, until an external drive or a bucket is configured.

.PARAMETER RetainDays
    Delete dumps older than this from both locations. Default 30.

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File scripts\backup.ps1
#>

[CmdletBinding()]
param(
    [string] $SecondaryDir,
    [int]    $RetainDays = 30,
    [string] $PgImage    = 'postgres:18',
    [switch] $SkipSecondary
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$RepoRoot  = Split-Path -Parent $PSScriptRoot
$BackupDir = Join-Path $RepoRoot 'backups'
$LogDir    = Join-Path $RepoRoot 'logs'
$StartedAt = (Get-Date).ToUniversalTime()
$Stamp     = $StartedAt.ToString('yyyyMMddTHHmmssZ')

function Write-Step { param([string]$Message) Write-Host "==> $Message" }
function Write-Note { param([string]$Message) Write-Host "    $Message" }
function Write-Warn { param([string]$Message) Write-Warning $Message }

# ---------------------------------------------------------------------------------------
# 0. Environment
# ---------------------------------------------------------------------------------------
# .env is git-ignored and holds the real values. It is read here and never echoed.
function Import-DotEnv {
    param([string] $Path)
    if (-not (Test-Path $Path)) { return }
    foreach ($line in Get-Content -LiteralPath $Path) {
        $trimmed = $line.Trim()
        if ($trimmed -eq '' -or $trimmed.StartsWith('#')) { continue }
        $idx = $trimmed.IndexOf('=')
        if ($idx -lt 1) { continue }
        $key = $trimmed.Substring(0, $idx).Trim()
        $val = $trimmed.Substring($idx + 1).Trim()
        if ($val.Length -ge 2 -and (
                ($val.StartsWith('"') -and $val.EndsWith('"')) -or
                ($val.StartsWith("'") -and $val.EndsWith("'")))) {
            $val = $val.Substring(1, $val.Length - 2)
        }
        # A value already in the process environment wins, so a caller can override.
        if (-not [Environment]::GetEnvironmentVariable($key)) {
            [Environment]::SetEnvironmentVariable($key, $val)
        }
    }
}

Import-DotEnv (Join-Path $RepoRoot '.env')

$DatabaseUrl = [Environment]::GetEnvironmentVariable('DATABASE_URL')
if ([string]::IsNullOrWhiteSpace($DatabaseUrl)) {
    throw 'DATABASE_URL is not set. Copy .env.example to .env and fill it in. (No value is ever printed by this script.)'
}

if (-not $SecondaryDir) { $SecondaryDir = [Environment]::GetEnvironmentVariable('BACKUP_SECONDARY_DIR') }
if (-not $SecondaryDir) { $SecondaryDir = Join-Path $env:USERPROFILE 'quant_model_backups' }

# docs/10 section 5.6: the scaffold creates neither data/ nor backups/, so the original
# backup.sh failed on its first line, silently, at 02:00. Create them here.
foreach ($d in @($BackupDir, $LogDir,
                 (Join-Path $RepoRoot 'data\documents'),
                 (Join-Path $RepoRoot 'data\raw'),
                 (Join-Path $RepoRoot 'data\interim'))) {
    if (-not (Test-Path $d)) { New-Item -ItemType Directory -Path $d -Force | Out-Null }
}

$LogFile = Join-Path $LogDir 'backup.log'
function Write-BackupLog {
    param([string] $Status, [string] $Detail)
    $ts = (Get-Date).ToUniversalTime().ToString('yyyy-MM-ddTHH:mm:ssZ')
    Add-Content -LiteralPath $LogFile -Value "$ts`t$Status`t$Detail" -Encoding utf8
}

# ---------------------------------------------------------------------------------------
# 1. Preconditions
# ---------------------------------------------------------------------------------------
Write-Step 'Checking prerequisites'
if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
    throw "docker not found on PATH. pg_dump is not installed on this machine; the dump runs inside the $PgImage image."
}
& docker version --format '{{.Server.Version}}' | Out-Null
if ($LASTEXITCODE -ne 0) {
    throw 'The Docker daemon is not reachable. Start Docker Desktop and re-run. A backup that cannot run is exactly the failure this task exists to prevent - do not ignore this.'
}
Write-Note "docker OK; using $PgImage for pg_dump (client major must be >= server major 18)"

# ---------------------------------------------------------------------------------------
# 2. Dump
# ---------------------------------------------------------------------------------------
$DumpName = "quant_$Stamp.dump"
$DumpPath = Join-Path $BackupDir $DumpName

Write-Step "Dumping the live database to backups\$DumpName"
$env:PGCONN = $DatabaseUrl
try {
    # -e PGCONN with no '=' copies this process's value in; the URL is never an argv entry.
    # --format=custom   : the only format pg_restore can filter and reorder
    # --no-owner/--no-acl: the restore target is a different database with a different
    #                      owner; ownership statements would fail there and prove nothing
    # Every value the container needs travels in the environment and the `sh -c` body is
    # SINGLE-quoted and static, with no embedded double quotes and no PowerShell
    # interpolation. That is not style: Windows PowerShell 5.1 rewrites the quoting of
    # arguments to a native executable and strips inner double quotes, so `-c "$VAR"`
    # arrives at `sh` unquoted and gets word-split on spaces. `set -f` disables globbing,
    # which matters because the URL contains `?sslmode=require`.
    $env:DUMP_NAME = $DumpName
    & docker run --rm `
        -e PGCONN `
        -e DUMP_NAME `
        -v "${BackupDir}:/backup" `
        $PgImage `
        sh -c 'set -f; pg_dump --dbname=$PGCONN --format=custom --no-owner --no-acl --file=/backup/$DUMP_NAME'
    $dumpExit = $LASTEXITCODE
}
finally {
    $env:PGCONN = $null
    $env:DUMP_NAME = $null
}

if ($dumpExit -ne 0) {
    Write-BackupLog -Status 'FAIL' -Detail "pg_dump exit $dumpExit"
    throw "pg_dump failed with exit code $dumpExit. NOTHING WAS BACKED UP."
}
if (-not (Test-Path $DumpPath)) {
    Write-BackupLog -Status 'FAIL' -Detail 'dump file missing after a zero exit code'
    throw "pg_dump reported success but $DumpPath does not exist."
}

$DumpBytes = (Get-Item $DumpPath).Length
Write-Note ('wrote {0:N0} bytes' -f $DumpBytes)

# ---------------------------------------------------------------------------------------
# 3. Verify the dump is a dump
# ---------------------------------------------------------------------------------------
# Silent-failure 19 in docs/10 section 5.5 is "a file that looks like a backup". A byte
# count is not evidence. `pg_restore --list` parses the archive table of contents and fails
# on a truncated or corrupt file - the cheapest real check short of a restore.
Write-Step 'Verifying the archive is readable (pg_restore --list)'
$TocPath = Join-Path $BackupDir "$DumpName.toc.txt"
$env:DUMP_NAME = $DumpName
& docker run --rm -e DUMP_NAME -v "${BackupDir}:/backup" $PgImage `
    sh -c 'set -f; pg_restore --list /backup/$DUMP_NAME' | Set-Content -LiteralPath $TocPath -Encoding utf8
if ($LASTEXITCODE -ne 0) {
    Write-BackupLog -Status 'FAIL' -Detail 'pg_restore --list could not read the archive'
    throw 'The dump was written but pg_restore cannot read it. Treat it as no backup at all.'
}
$TocEntries = @(Get-Content -LiteralPath $TocPath | Where-Object { $_ -and -not $_.StartsWith(';') }).Count
Write-Note "archive readable; $TocEntries restorable objects in the table of contents"
if ($TocEntries -eq 0) {
    Write-Warn 'The archive contains zero restorable objects. Expected ONLY if no migration has been applied yet (alembic upgrade head). A red flag at any other time.'
}

# ---------------------------------------------------------------------------------------
# 4. Second location
# ---------------------------------------------------------------------------------------
if ($SkipSecondary) {
    Write-Warn '-SkipSecondary was passed. One copy exists. That is not a backup.'
} else {
    Write-Step "Copying to the second location: $SecondaryDir"
    if (-not (Test-Path $SecondaryDir)) { New-Item -ItemType Directory -Path $SecondaryDir -Force | Out-Null }
    $SecondaryPath = Join-Path $SecondaryDir $DumpName
    Copy-Item -LiteralPath $DumpPath -Destination $SecondaryPath -Force
    $CopyBytes = (Get-Item $SecondaryPath).Length
    if ($CopyBytes -ne $DumpBytes) {
        Write-BackupLog -Status 'FAIL' -Detail "second-copy size $CopyBytes != $DumpBytes"
        throw "The copy in $SecondaryDir differs in size from the original. Do not trust it."
    }
    Write-Note ('copy verified, {0:N0} bytes' -f $CopyBytes)
}

# ---------------------------------------------------------------------------------------
# 5. Retention
# ---------------------------------------------------------------------------------------
Write-Step "Pruning dumps older than $RetainDays days"
$Cutoff = (Get-Date).AddDays(-$RetainDays)
foreach ($dir in @($BackupDir, $SecondaryDir)) {
    if (-not (Test-Path $dir)) { continue }
    Get-ChildItem -LiteralPath $dir -Filter 'quant_*.dump*' -File -ErrorAction SilentlyContinue |
        Where-Object { $_.LastWriteTime -lt $Cutoff } |
        ForEach-Object {
            Write-Note "removing $($_.FullName)"
            Remove-Item -LiteralPath $_.FullName -Force -Confirm:$false
        }
}

# ---------------------------------------------------------------------------------------
# 6. Off-site tier - NOT IMPLEMENTED. Deferred to P3 entry per docs/10 section 6.1.
# ---------------------------------------------------------------------------------------
function Invoke-OffsiteHook {
    <#
      DELIBERATELY UNIMPLEMENTED. Do not fill this in halfway.

      What P3 entry must build, in order (docs/02 section 8; docs/10 sections 5.1, 5.2, 5.4):

        1. A gpg key pair whose PRIVATE key and revocation certificate are escrowed in the
           password manager AND on a printed offline copy held off-premises, BEFORE the
           first encrypted backup runs. docs/10 section 5.2: the default today is the
           laptop keyring, so the laptop dying takes both the live database and the ability
           to decrypt every off-site backup. Until a restore has been performed on a
           machine that has never held the key, the off-site tier is decorative.
        2. A Backblaze B2 / Cloudflare R2 bucket with Object Lock in governance mode and
           versioning ON, and application credentials scoped writeFiles + listFiles with NO
           deleteFiles (docs/10 section 5.1). That makes the destructive mistake
           structurally impossible rather than merely discouraged.
        3. gpg --encrypt --recipient $env:BACKUP_GPG_ID <dump>
           rclone copy <dump>.gpg b2:quant-backups/db/ --immutable --checksum
        4. Documents:
           rclone copy data/documents b2:quant-docs-prod/documents/ --immutable --checksum
           NEVER `rclone sync`. docs/10 section 5.1 and audit finding 5: sync makes the
           destination match the source by DELETING. One bad re-extract and the off-site
           copy of every 2013 annual report whose source URL has rotated is gone.

      Neither gpg nor rclone is installed on this machine and no B2/R2 account exists.
      docs/02 section 8 calls this "ten minutes"; docs/10 section 1 corrects that to half a
      day plus an account. It is P0.11 / P3-entry work, not P0.6-MIN.
    #>
    if ($env:BACKUP_OFFSITE_ENABLED -eq '1') {
        throw 'BACKUP_OFFSITE_ENABLED=1 but the off-site tier is not implemented (deferred to P3 entry, docs/10 section 6.1). Refusing to report success for a backup that never left this machine.'
    }
}
Invoke-OffsiteHook

# ---------------------------------------------------------------------------------------
# 7. Record the run
# ---------------------------------------------------------------------------------------
# docs/02 section 8: recording the backup as a connector_runs row means the freshness
# monitor alerts when BACKUPS stop, not only when data stops. Best effort - before
# P0.4-SPINE is migrated the table does not exist, and that must not fail the backup.
Write-Step 'Recording the run in connector_runs (best effort)'
$FinishedAt = (Get-Date).ToUniversalTime()
$env:PGCONN = $DatabaseUrl
try {
    # The SQL travels in the environment, exactly like the connection string, and the
    # `sh -c` body is SINGLE-quoted so PowerShell interpolates nothing into it. The
    # previous version built the statement into a double-quoted shell string through two
    # layers of escaping; psql received a truncated statement and failed with
    # "syntax error at end of input" while the dump itself was perfectly fine. Keeping
    # both values in env also keeps them out of the host process list.
    $env:BACKUP_SQL =
        "INSERT INTO connector_runs (connector_name, started_at, finished_at, status, rows_written) " +
        "VALUES ('backup', '$($StartedAt.ToString('yyyy-MM-dd HH:mm:ss'))+00', " +
        "'$($FinishedAt.ToString('yyyy-MM-dd HH:mm:ss'))+00', 'ok', 1);"
    # The statement goes in on stdin (`-f -`), not as `-c "$VAR"`: see the note at the
    # pg_dump call. With `-c` the statement arrived word-split and psql failed with
    # "syntax error at end of input" having received only the word INSERT, while the dump
    # itself was fine — a backup that reports success and records nothing.
    $env:BACKUP_SQL | & docker run --rm -i -e PGCONN $PgImage `
        sh -c 'set -f; psql --dbname=$PGCONN -v ON_ERROR_STOP=1 -q -f -' 2>&1 | Out-Null
    if ($LASTEXITCODE -eq 0) {
        Write-Note 'connector_runs row written'
    } else {
        Write-Warn 'Could not write the connector_runs row (table not migrated yet?). The dump itself is fine. Re-check once P0.4-SPINE has run - without that row nothing detects backups that stopped (docs/10 section 5.3).'
    }
}
finally {
    $env:PGCONN = $null
    $env:BACKUP_SQL = $null
}

# ---------------------------------------------------------------------------------------
# 8. Dead-man ping - docs/10 section 5.3
# ---------------------------------------------------------------------------------------
# "A local check cannot report that the local machine is dead." If HEALTHCHECK_PING_URL is
# set (a free healthchecks.io check, grace 26h), ping it. Unset = no-op, no failure.
if ($env:HEALTHCHECK_PING_URL) {
    Write-Step 'Pinging the dead-man check'
    try {
        Invoke-WebRequest -Uri $env:HEALTHCHECK_PING_URL -Method Get -TimeoutSec 15 -UseBasicParsing | Out-Null
        Write-Note 'ping sent'
    } catch {
        Write-Warn "Dead-man ping failed: $($_.Exception.Message). The backup itself succeeded."
    }
} else {
    Write-Note 'HEALTHCHECK_PING_URL is not set - nothing will notice if this script stops running (docs/10 section 5.3). Set one up: it is free, and it is the only thing that emails you when the laptop is stolen.'
}

# ---------------------------------------------------------------------------------------
# 9. Summary
# ---------------------------------------------------------------------------------------
Write-BackupLog -Status 'OK' -Detail "$DumpName $DumpBytes bytes, $TocEntries objects"
$Elapsed = [int]($FinishedAt - $StartedAt).TotalSeconds

Write-Host ''
Write-Step 'BACKUP OK'
Write-Note "file    : $DumpPath"
Write-Note ('size    : {0:N0} bytes' -f $DumpBytes)
Write-Note "objects : $TocEntries"
if (-not $SkipSecondary) { Write-Note "copy 2  : $(Join-Path $SecondaryDir $DumpName)" }
Write-Note "elapsed : ${Elapsed}s"
Write-Host ''
Write-Warn '3-2-1 STATUS: 2 copies, 1 medium, 0 off-site. This machine has one physical disk (C:), so both copies share a single failure. Disk failure, theft, fire or ransomware still costs the dataset. The off-site tier is P3-entry work - see Invoke-OffsiteHook in this file.'
Write-Host ''
Write-Note 'A backup is not a backup until it has been restored: run scripts\restore.ps1.'

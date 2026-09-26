<#
.SYNOPSIS
    P0.6-MIN - the restore drill. Restores a dump into a SEPARATE database and proves the
    restored copy matches the source. Closes TG4 / TG18. This is P0 check 14.

.DESCRIPTION
    docs/03 P0.6: "An untested backup is not a backup - it is a file you believe is a
    backup, and the distinction is only visible on the day it matters."

    This script fixes the three defects docs/10 section 5.5 found in the original
    restore.sh:

      1. THE SUCCESS CRITERION DID NOT TEST THE DATA. The original counted rows in
         information_schema.tables and US-006 asserted "the same table count as live" - so
         a restore containing zero business rows passed. That is silent-failure 19 ("a file
         that looks like a backup") reproduced inside the check meant to catch it.
         This script compares the ROW COUNT OF EVERY TABLE, source against restored, and
         calls out source_documents, statement_line_items and price_history by name, each
         required within 1% of live.

      2. THE SCRIPT ABORTED ON EVERY RUN AFTER THE FIRST. `set -euo pipefail` plus
         `createdb` with no prior drop gives "database already exists" -> exit 1, under
         time pressure, so the drill gets skipped. This script drops first, with FORCE.

      3. CADENCE CONTRADICTION. OPERATIONS.md 2.1 said monthly; docs/02 section 8 said
         quarterly. docs/10 section 5.5 settles it: QUARTERLY, first Monday of
         Jan/Apr/Jul/Oct. The register that tracks it is docs/REVIEW_CADENCE.md, and the
         result of each drill is recorded there.

    NEVER OVER THE LIVE DATABASE. That is enforced below by Assert-SafeRestoreTarget, not
    by a comment. The target database name is compared against the live and test database
    names parsed from DATABASE_URL / TEST_DATABASE_URL and against a denylist; any match
    aborts before a single statement is sent.

    As with backup.ps1: there is no local psql or pg_restore, so both run inside the
    postgres:18 image. The client major version must be >= the server's (Neon 18.6) or
    pg_restore aborts with a server version mismatch. Connection strings are passed by
    `docker run -e PGCONN` (name only), never as an argument.

.PARAMETER DumpPath
    The dump to restore. Defaults to the newest backups\quant_*.dump.

.PARAMETER RestoreDb
    Target database. docs/10 section 5.5: "Standardise on quant_restore_test."

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File scripts\restore.ps1
#>

[CmdletBinding()]
param(
    [string] $DumpPath,
    [string] $RestoreDb = 'quant_restore_test',
    [string] $PgImage   = 'postgres:18',
    [switch] $DropWhenDone
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$RepoRoot  = Split-Path -Parent $PSScriptRoot
$BackupDir = Join-Path $RepoRoot 'backups'
$SqlDir    = Join-Path $BackupDir 'sql'

function Write-Step { param([string]$Message) Write-Host "==> $Message" }
function Write-Note { param([string]$Message) Write-Host "    $Message" }
function Write-Warn { param([string]$Message) Write-Warning $Message }

# ---------------------------------------------------------------------------------------
# 0. Environment
# ---------------------------------------------------------------------------------------
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
$TestDatabaseUrl = [Environment]::GetEnvironmentVariable('TEST_DATABASE_URL')

# ---------------------------------------------------------------------------------------
# 1. URL surgery - the database name only. No credential is ever printed or logged.
# ---------------------------------------------------------------------------------------
# postgres://user:pass@host/dbname?params  ->  the dbname segment, and a URL with it swapped.
$UrlPattern = '^(?<scheme>[a-zA-Z0-9+]+://)(?<authority>[^/]+)/(?<db>[^/?#]+)(?<rest>[?#].*)?$'

function Get-DbName {
    param([string] $Url)
    if ($Url -match $UrlPattern) { return $Matches['db'] }
    throw 'A connection URL is not in the expected scheme://authority/dbname form. Fix .env. (The value itself is deliberately not shown.)'
}

function Set-DbName {
    param([string] $Url, [string] $NewDb)
    if ($Url -match $UrlPattern) {
        $rest = if ($Matches['rest']) { $Matches['rest'] } else { '' }
        return "$($Matches['scheme'])$($Matches['authority'])/$NewDb$rest"
    }
    throw 'A connection URL is not in the expected scheme://authority/dbname form. Fix .env.'
}

$LiveDb = Get-DbName $DatabaseUrl
$TestDb = if ($TestDatabaseUrl) { Get-DbName $TestDatabaseUrl } else { $null }

# ---------------------------------------------------------------------------------------
# 2. THE GUARD. Never over the live database - enforced, not documented.
# ---------------------------------------------------------------------------------------
function Assert-SafeRestoreTarget {
    param([string] $Target, [string] $Live, [string] $Test)

    if ([string]::IsNullOrWhiteSpace($Target)) {
        throw 'GUARD: the restore target database name is empty.'
    }
    if ($Target -notmatch '^[A-Za-z_][A-Za-z0-9_]*$') {
        throw "GUARD: '$Target' is not a plain identifier. Refusing to interpolate it into DDL."
    }
    if ($Target -ieq $Live) {
        throw "GUARD: the restore target '$Target' IS the live database. A restore over live destroys the only copy of everything written since the dump. Refusing. (docs/03 P0.6: restore into a SEPARATE database, never over the live one.)"
    }
    if ($Test -and $Target -ieq $Test) {
        throw "GUARD: the restore target '$Target' is the test database used by the CI/pytest suite. Refusing - a restore would silently replace whatever the test suite expects to find."
    }
    $denied = @('postgres', 'template0', 'template1', 'neondb', 'quant', 'quant_dev', 'quant_prod')
    if ($denied -contains $Target.ToLowerInvariant()) {
        throw "GUARD: '$Target' is on the denylist of databases this script will never write to. docs/10 section 5.5 standardises the drill on 'quant_restore_test'."
    }
    if ($Target -notlike '*restore*') {
        throw "GUARD: '$Target' does not contain 'restore'. Every database this script may drop and recreate must say so in its name, so that a typo cannot resolve to something precious."
    }
}

Assert-SafeRestoreTarget -Target $RestoreDb -Live $LiveDb -Test $TestDb
Write-Step 'Guard passed'
Write-Note "live database   : $LiveDb  (read-only in this script)"
if ($TestDb) { Write-Note "test database   : $TestDb  (untouched)" }
Write-Note "restore target  : $RestoreDb  (dropped and recreated)"

# ---------------------------------------------------------------------------------------
# 3. Locate the dump
# ---------------------------------------------------------------------------------------
if (-not $DumpPath) {
    $newest = Get-ChildItem -LiteralPath $BackupDir -Filter 'quant_*.dump' -File -ErrorAction SilentlyContinue |
              Sort-Object LastWriteTime -Descending | Select-Object -First 1
    if (-not $newest) {
        throw "No dump found in $BackupDir. Run scripts\backup.ps1 first."
    }
    $DumpPath = $newest.FullName
}
if (-not (Test-Path $DumpPath)) { throw "Dump not found: $DumpPath" }
$DumpFile  = Split-Path -Leaf $DumpPath
$DumpBytes = (Get-Item $DumpPath).Length
Write-Step "Restoring $DumpFile"
Write-Note ('size : {0:N0} bytes' -f $DumpBytes)

if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
    throw "docker not found on PATH. pg_restore is not installed on this machine; the restore runs inside the $PgImage image."
}
& docker version --format '{{.Server.Version}}' | Out-Null
if ($LASTEXITCODE -ne 0) { throw 'The Docker daemon is not reachable. Start Docker Desktop and re-run.' }

# ---------------------------------------------------------------------------------------
# 4. Helpers - run SQL in the container. SQL goes in a mounted file, so nothing has to be
#    quoted through two shells and no connection string is ever an argv entry.
# ---------------------------------------------------------------------------------------
if (-not (Test-Path $SqlDir)) { New-Item -ItemType Directory -Path $SqlDir -Force | Out-Null }

function Invoke-Psql {
    param(
        [string] $Url,
        [string] $Sql,
        [string] $Name,
        [switch] $Quiet
    )
    # Output formatting is set with psql meta-commands INSIDE the .sql file, never with
    # `-t -A -F"|"` on the command line. Windows PowerShell 5.1 rewrites the quoting of
    # arguments to a native executable and drops inner double quotes, so `-F"|"` reached
    # `sh` as a bare `|` — a pipe — and the quiet query silently produced nothing to
    # compare. Meta-commands in the file are parsed by psql, where no shell can reach them.
    $file = Join-Path $SqlDir "$Name.sql"
    $body = if ($Quiet) {
        "\pset format unaligned`n\pset fieldsep '|'`n\pset tuples_only on`n" + $Sql
    } else {
        $Sql
    }
    Set-Content -LiteralPath $file -Value $body -Encoding utf8
    $env:PGCONN = $Url
    $env:SQL_NAME = "$Name.sql"
    # `$ErrorActionPreference = 'Stop'` (line 59) plus `2>&1` on a NATIVE command is a trap
    # specific to Windows PowerShell 5.1: every stderr line is wrapped in an ErrorRecord,
    # so a harmless psql NOTICE — "database ... does not exist, skipping" from a
    # `DROP DATABASE IF EXISTS` — becomes a terminating error and kills the drill on its
    # first step, with exit 0 from the command that supposedly failed. Exit codes are the
    # truth here; stderr is commentary. `$LASTEXITCODE` is still checked by every caller.
    $prevEap = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    try {
        # Single-quoted, static, no embedded double quotes; `set -f` because the URL
        # carries `?sslmode=require` and would otherwise be a glob pattern.
        $out = & docker run --rm -e PGCONN -e SQL_NAME -v "${BackupDir}:/backup" $PgImage `
                 sh -c 'set -f; psql --dbname=$PGCONN -q -v ON_ERROR_STOP=1 -f /backup/sql/$SQL_NAME' 2>&1
        $script:PsqlExit = $LASTEXITCODE
        return $out
    }
    finally {
        $ErrorActionPreference = $prevEap
        $env:PGCONN = $null
        $env:SQL_NAME = $null
    }
}

# Row counts for every base table in the public schema, in one query.
# query_to_xml runs a count(*) per table without needing a procedural loop or a second
# round trip; this is what makes "compare the DATA, not the table count" cheap enough to
# actually run every quarter.
$RowCountSql = @'
SELECT table_name,
       (xpath('/row/c/text()', xml_count))[1]::text::bigint AS n
FROM (
  SELECT table_name,
         query_to_xml(format('SELECT count(*) AS c FROM %I.%I', table_schema, table_name),
                      false, true, '') AS xml_count
  FROM information_schema.tables
  WHERE table_schema = 'public' AND table_type = 'BASE TABLE'
) t
ORDER BY table_name;
'@

function Get-RowCounts {
    param([string] $Url, [string] $Name)
    $lines = Invoke-Psql -Url $Url -Sql $RowCountSql -Name $Name -Quiet
    if ($script:PsqlExit -ne 0) {
        Write-Host ($lines -join [Environment]::NewLine)
        throw "Could not read row counts from the $Name database."
    }
    $map = @{}
    foreach ($line in $lines) {
        $s = "$line".Trim()
        if (-not $s -or $s -notmatch '\|') { continue }
        $parts = $s.Split('|')
        if ($parts.Count -ne 2) { continue }
        $map[$parts[0]] = [int64]$parts[1]
    }
    return $map
}

# ---------------------------------------------------------------------------------------
# 5. Snapshot the source BEFORE the restore
# ---------------------------------------------------------------------------------------
Write-Step 'Reading table and row counts from the live database'
$SourceCounts = Get-RowCounts -Url $DatabaseUrl -Name 'source_counts'
Write-Note "live: $($SourceCounts.Count) base tables in schema public"

# ---------------------------------------------------------------------------------------
# 6. Drop and recreate the restore target
# ---------------------------------------------------------------------------------------
# docs/10 section 5.5 defect 3: "Add dropdb --if-exists first." WITH (FORCE) terminates
# leftover sessions, which is the other reason the second run of the original failed.
Write-Step "Dropping and recreating $RestoreDb"
$ddl = "DROP DATABASE IF EXISTS $RestoreDb WITH (FORCE);"
$out = Invoke-Psql -Url $DatabaseUrl -Sql $ddl -Name 'drop_restore_db'
if ($script:PsqlExit -ne 0) {
    Write-Host ($out -join [Environment]::NewLine)
    throw "Could not drop $RestoreDb."
}
$out = Invoke-Psql -Url $DatabaseUrl -Sql "CREATE DATABASE $RestoreDb;" -Name 'create_restore_db'
if ($script:PsqlExit -ne 0) {
    Write-Host ($out -join [Environment]::NewLine)
    throw "Could not create $RestoreDb. On a managed host the role may not be permitted to CREATE DATABASE - see docs/adr/0008-neon-managed-postgres.md."
}
Write-Note "$RestoreDb created"

$RestoreUrl = Set-DbName -Url $DatabaseUrl -NewDb $RestoreDb

# ---------------------------------------------------------------------------------------
# 7. Restore
# ---------------------------------------------------------------------------------------
Write-Step 'Running pg_restore'
$env:PGCONN = $RestoreUrl
try {
    $env:DUMP_FILE = $DumpFile
    # See the note in Invoke-Psql: native stderr must not be terminating here either.
    $prevEap = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    $restoreOut = & docker run --rm -e PGCONN -e DUMP_FILE -v "${BackupDir}:/backup" $PgImage `
        sh -c 'set -f; pg_restore --dbname=$PGCONN --no-owner --no-privileges --exit-on-error /backup/$DUMP_FILE' 2>&1
    $restoreExit = $LASTEXITCODE
}
finally {
    $ErrorActionPreference = $prevEap
    $env:PGCONN = $null
    $env:DUMP_FILE = $null
}

if ($restoreOut) { Write-Host ($restoreOut -join [Environment]::NewLine) }
if ($restoreExit -ne 0) {
    throw "pg_restore failed with exit code $restoreExit. THE BACKUP IS NOT RESTORABLE. Stop and fix this before writing anything else to the live database."
}
Write-Note 'pg_restore exited 0'

# ---------------------------------------------------------------------------------------
# 8. Compare - the part that is the actual drill
# ---------------------------------------------------------------------------------------
Write-Step 'Comparing the restored copy against the source'
$RestoredCounts = Get-RowCounts -Url $RestoreUrl -Name 'restored_counts'

$failures = New-Object System.Collections.Generic.List[string]
$rows     = New-Object System.Collections.Generic.List[object]

# 8a. Table count.
if ($SourceCounts.Count -ne $RestoredCounts.Count) {
    $failures.Add("table count: live $($SourceCounts.Count) vs restored $($RestoredCounts.Count)")
}

# Append-only operational tables that are GUARANTEED to grow between the dump and this
# comparison, so an exact match is the wrong assertion for them:
#   connector_runs - backup.ps1 writes its own completion row AFTER pg_dump has finished,
#                    so live is ahead by at least one row every single time. Asserting
#                    equality here fails the drill on a perfect restore, which trains the
#                    operator to ignore a red drill - the exact habit docs/10 section 5.5
#                    is trying to prevent.
#   audit_log      - any HTTP request served between the dump and the drill adds rows.
# For these the meaningful assertion is that the restore LOST nothing: restored <= live,
# and non-empty whenever live is non-empty. Growth is drift; shrinkage is data loss.
$DriftExpected = @('connector_runs', 'audit_log')

# 8b. Every table's row count, within 1% (docs/10 section 5.5).
foreach ($table in ($SourceCounts.Keys | Sort-Object)) {
    $src = $SourceCounts[$table]
    if (-not $RestoredCounts.ContainsKey($table)) {
        $failures.Add("$table : present in live, MISSING from the restored copy")
        $rows.Add([pscustomobject]@{ Table = $table; Live = $src; Restored = 'MISSING'; Verdict = 'FAIL' })
        continue
    }
    $dst = $RestoredCounts[$table]
    if ($DriftExpected -contains $table) {
        $ok = ($dst -le $src) -and (($src -eq 0) -or ($dst -gt 0))
        if (-not $ok) {
            $failures.Add("$table : live $src vs restored $dst - the restored copy LOST rows")
        }
        $verdict = if (-not $ok) { 'FAIL' } elseif ($dst -eq $src) { 'ok' } else { "ok (+$($src - $dst) since dump)" }
        $rows.Add([pscustomobject]@{ Table = $table; Live = $src; Restored = $dst; Verdict = $verdict })
        continue
    }
    $tolerance = [Math]::Max(0, [Math]::Floor($src * 0.01))
    $ok = [Math]::Abs($src - $dst) -le $tolerance
    if (-not $ok) { $failures.Add("$table : live $src vs restored $dst (outside 1%)") }
    $rows.Add([pscustomobject]@{ Table = $table; Live = $src; Restored = $dst; Verdict = $(if ($ok) { 'ok' } else { 'FAIL' }) })
}
foreach ($table in ($RestoredCounts.Keys | Sort-Object)) {
    if (-not $SourceCounts.ContainsKey($table)) {
        $failures.Add("$table : present in the restored copy but NOT in live - the dump is older than you think")
    }
}

if ($rows.Count -gt 0) { $rows | Format-Table -AutoSize | Out-String | Write-Host }

# 8c. The three tables docs/10 section 5.5 names explicitly.
Write-Step 'Named success criterion (docs/10 section 5.5)'
$named = @('source_documents', 'statement_line_items', 'price_history')
$namedPresent = 0
foreach ($t in $named) {
    if ($SourceCounts.ContainsKey($t)) {
        $namedPresent++
        $src = $SourceCounts[$t]
        $dst = if ($RestoredCounts.ContainsKey($t)) { $RestoredCounts[$t] } else { 'MISSING' }
        Write-Note "$t : live $src, restored $dst"
    } else {
        Write-Note "$t : not in the schema yet (P0.4-SPINE / P1 / P2 create it) - cannot be checked"
    }
}

# ---------------------------------------------------------------------------------------
# 9. Verdict, stated honestly
# ---------------------------------------------------------------------------------------
Write-Host ''
if ($failures.Count -gt 0) {
    Write-Step 'RESTORE DRILL FAILED'
    foreach ($f in $failures) { Write-Note "- $f" }
    Write-Host ''
    throw 'The restored copy does not match the source. Do not record this drill as passed.'
}

Write-Step 'RESTORE DRILL PASSED'
Write-Note "dump      : $DumpFile"
Write-Note "restored  : $RestoreDb"
Write-Note "tables    : $($SourceCounts.Count) compared, all row counts within 1%"

if ($SourceCounts.Count -eq 0) {
    Write-Host ''
    Write-Warn 'ZERO TABLES WERE COMPARED. The source schema is empty, so this run proves the MECHANISM (dump -> drop -> create -> restore -> compare) and nothing about the DATA. That is the correct thing to do in P0 while the database is empty - docs/03 P0.6: "It goes in P0, when the database is empty, for one reason: the restore is the part that fails, and you want to discover that while there is nothing to lose." Re-run it, and record the result, once migrations and the first real rows exist.'
}
if ($namedPresent -lt $named.Count) {
    Write-Warn "Only $namedPresent of $($named.Count) named business tables exist yet, so docs/10 section 5.5's full success criterion is not yet satisfiable. Two further clauses of it are also still outstanding: the known-answer suite must run against the restored copy (tests/known_answer, from P2), and one PDF fetched from storage_key must re-hash to its stored sha256 (from P1's document store)."
}

Write-Host ''
Write-Note "Record this drill in docs/REVIEW_CADENCE.md with today's date and the counts above."
if ($DropWhenDone) {
    Write-Step "Dropping $RestoreDb"
    $null = Invoke-Psql -Url $DatabaseUrl -Sql "DROP DATABASE IF EXISTS $RestoreDb WITH (FORCE);" -Name 'drop_restore_db_final'
    Write-Note 'dropped'
} else {
    Write-Note "$RestoreDb was left in place for inspection. The next run drops it first; or pass -DropWhenDone."
}

# 02 — Infrastructure

**What this document is for.** Everything in this project that is not application code lives
here: where the code runs, what the database is and how it is migrated, where the original PDFs
are kept forever, how secrets are handled, what the automated build pipeline checks before a
change is allowed in, how the data is backed up and proven restorable, how you find out that a
scraper quietly stopped working, what the LLM spend ceiling is and what happens when it is hit,
what to do at 11pm when something breaks, and what the whole thing costs at each phase. If a
question starts with "where does it run", "how does it stay alive", or "what does it cost", the
answer is in this file. If it starts with "how is the code organised" or "what does this module
return", it is in [01_ARCHITECTURE.md](01_ARCHITECTURE.md) or
[08_DATA_CONTRACTS.md](08_DATA_CONTRACTS.md).

**Written for one person on a Windows 11 machine building with AI agents.** Not for a platform
team. Every recommendation here is chosen because one person can operate it without a second
person on call, and every command is written to be pasted into a real terminal on Windows.

> **Status check before you read anything else.** Nothing in this document has been built. As of
> today the repository contains six markdown files, an empty `package.json`, and a `node_modules`
> folder. There is no `.git`, no Python environment, no database, no code. Every section below
> describes what to create, in the order to create it. Phase **P0** has not started.

---

## Table of contents

| Section | What it answers |
|---|---|
| [0. How to read this document](#0-how-to-read-this-document) | Risk markers, phase map, citation style |
| [1. Environments](#1-environments) | Local vs staging vs production; what must never differ |
| [2. Local development on Windows 11](#2-local-development-on-windows-11) | Python, uv, Postgres on Windows, literal commands |
| [3. Database](#3-database) | PostgreSQL, TimescaleDB, sizing arithmetic, pooling, Alembic |
| [4. Object storage for source documents](#4-object-storage-for-source-documents) | Where PDFs live forever, naming, immutability |
| [5. Hosting](#5-hosting) | The P9 decision, Railway vs Render vs VPS, what P12 changes |
| [6. Secrets management](#6-secrets-management) | `.env` hygiene, pre-commit scanning, rotation, broker keys |
| [7. CI/CD](#7-cicd) | The GitHub Actions pipeline, job by job, with YAML |
| [8. Backup and disaster recovery — gap G4](#8-backup-and-disaster-recovery--gap-g4) | RPO/RTO, 3-2-1, the restore drill you actually run |
| [9. Observability](#9-observability) | Silent scraper failure, freshness alerts, logging, errors |
| [10. LLM cost control](#10-llm-cost-control) | Per-principal caps, content-hash cache, model routing |
| [11. Runbook](#11-runbook) | Concrete incidents: symptom, diagnosis, fix, prevention |
| [12. Cost table by phase](#12-cost-table-by-phase) | Grounded in DATA_FOUNDATION 8.1 and SPEC PART 6 |
| [13. Gaps surfaced by this document](#13-gaps-surfaced-by-this-document) | G4 restated, plus new G7–G11 |
| [14. Infrastructure checklist by phase](#14-infrastructure-checklist-by-phase) | What infra work belongs to P0…P13 |
| [15. Appendices](#15-appendices) | Full file contents: compose, workflow, `.env.example`, scripts |

---

## 0. How to read this document

### 0.1 The three risk markers

Every significant recommendation carries one of these. They are honest ratings, not decoration.
A document where everything is green would be useless.

| Marker | Means | What you do about it |
|---|---|---|
| 🟢 **SOLID** | Well understood, low variance, proven. If it fails, the failure is obvious and cheap to fix. | Nothing. Stop worrying about this one. |
| 🟡 **WATCH** | It will work, but it has a known failure mode, a cost that can move, or a dependency outside your control. | Note the early-warning signal named in the item. Check it when you see that signal. |
| 🔴 **FRAGILE** | Genuinely likely to go wrong, or the estimate could be off by multiples. | Read the three approaches given. Every 🔴 item in this document carries at least three distinct approaches with trade-offs and a recommendation, because you should never be cornered into one option on something this uncertain. |

A running index of every marker across all nine documents is in
[06_RISK_REGISTER.md](06_RISK_REGISTER.md).

### 0.2 The phase map

This document uses the project's canonical phases. Never renumber them.

| Phase | Name | Spec version | Infrastructure that lands here |
|---|---|---|---|
| **P0** | Foundation & Rails | pre-v0.1 | git, uv, Postgres, Alembic, CI, secrets, backups, object storage |
| **P1** | Macro Backdrop | v0.1 | Scheduler, connector-health table, freshness view |
| **P2** | US Company Data | v0.2 | EDGAR rate limiting, raw document cache |
| **P3** | Nigerian Manual Analyzer | v0.3 | PDF object storage in real use |
| **P4** | Nigerian Automated Ingestion | v0.4 | LLM spend ledger and caps, cost alerts |
| **P5** | News, Sentiment & Daily Brief | v0.5 | Telegram alert channel doubles as the ops channel |
| **P6** | Scenarios & Indicators | v0.6–v0.7 | Compute sizing; indicator table growth |
| **P7** | Backtesting — THE GATE | v0.8 | Deterministic run reproducibility, seeds pinned |
| **P8** | ML Signals | v0.9 | Model artefact storage and versioning |
| **P9** | Memos & Hosted Web App | v1.0 | **First hosted production**: hosting, managed Postgres, uptime, error tracking |
| **P10** | Portfolio & Alerts | v1.2 | Per-principal alert delivery, idempotency store |
| **P11** | Paper Trading | v1.5 | Nothing structurally new |
| **P12** | Public Beta | v2.0 | Rate limits, abuse controls, real-user data handling, scaling |
| **P13** | Personal Execution | v2.5 | Broker credential isolation, out-of-band kill switch |

**T15 (compliance middleware) is not a phase.** Its core lands in P0 and it is hardened in every
phase through P12 (SPEC.md 4.2 marks it "front-loaded, all versions"). Infrastructure's job for
T15 is to make the compliance test suite a build blocker from the first commit — see
[§7](#7-cicd).

### 0.3 Citations and unverified numbers

- A claim taken from a source document is cited inline, like `(OPERATIONS.md 2.1)`.
- A number I could not verify from the source documents is marked **[NEEDS VERIFICATION]** with
  a note on exactly what to check and where. **Treat those as placeholders, not facts.** Prices
  of third-party services move, and the source docs already warn that several vendor prices in
  them were assembled from secondary sources (DATA_FOUNDATION.md Caveats).
- Durations are effort ranges ("2–4 hours"), never dates. You set the pace.

### 0.4 One deviation from the source specs, declared up front

**DATA_FOUNDATION.md 4.1 recommends DuckDB or SQLite for v0.x and PostgreSQL only from v1.0.
This document recommends PostgreSQL from P0.** That is a deliberate deviation and it must be
recorded as an ADR before you act on it. The full argument, including what you give up, is in
[§3.1](#31-the-database-decision--postgres-from-p0). It parallels the deviation the architecture
already makes by standing FastAPI up in P0 rather than P9. Both deviations exist for the same
reason: multi-user and server-derived mode are mandated from day one (PROJECT_CONTEXT.md 4,
CLAUDE.md), and the cheap single-user shortcuts do not survive that.

OPERATIONS.md 3.1 already lists "DuckDB before Postgres" as an item on the ADR backlog — meaning
the source documents themselves treat this as an open decision to be written down, not a settled
one. This document supplies the argument; you make the call and record it.

---

## 1. Environments

An "environment" is one complete running copy of the system: a database, a set of secrets, a
place the code runs, and a set of external accounts it talks to. The reason to have more than
one is simple — you need somewhere to be wrong that does not destroy the thing you cannot
rebuild.

### 1.1 The three environments, and which of them actually exist when

| Environment | What it is | Exists from |
|---|---|---|
| **local** | Your Windows 11 machine. Postgres in a container, Python running natively, Streamlit on `localhost:8501`, API on `localhost:8000`. | P0 |
| **staging** | A throwaway copy that looks like production but holds nothing precious. Used to prove a migration and a deploy work before they touch the real thing. | P9 (optional before then — see 1.4) |
| **production** | The copy that holds the dataset you cannot rebuild and that other people depend on. | **P0** — see the warning below |

> ### ⚠️ The thing that surprises people: production exists from P0, and it is your laptop.
>
> There is no *hosted* production until P9 (SPEC.md 4.2, T16). But "production" does not mean
> "hosted" — it means *the copy whose loss is unrecoverable*. From the moment you enter the
> first hand-corrected line item in P3, or the first extracted statement in P4, the database on
> your laptop **is** production. PROJECT_CONTEXT.md 9.3 calls that dataset the moat.
> OPERATIONS.md 2.1 calls it "genuinely irreplaceable" and says to build backups "in week one,
> before v0.1 has any data worth losing."
>
> Everything in [§8 Backup and DR](#8-backup-and-disaster-recovery--gap-g4) therefore applies
> from P0, not from P9. This is the single most common way a project like this dies quietly.

### 1.2 What differs between environments

Only these things are allowed to differ. If something else differs, it is a bug waiting to be
found in the worst possible place.

| Dimension | local | staging | production |
|---|---|---|---|
| **Data volume** | A seeded fixture set: 3 companies, 2 macro series, 5 PDFs | Restored from the newest production backup, or the same fixtures | Everything |
| **Secrets** | Real read-only API keys (FRED, EDGAR) + a **separate, low-limit** Anthropic key | Its own keys, never production's | Its own keys |
| **LLM spend cap** | Low, e.g. $5/month hard stop | Low | The real monthly ceiling ([§10](#10-llm-cost-control)) |
| **Default `MODE`** | `public` (fail-safe, per SPEC.md 4.1 invariant 6) | `public` | `public` |
| **Outbound writes** | Telegram sends to a *test* chat; broker adapters run in paper mode only | Same | Real |
| **Log level** | `DEBUG` | `INFO` | `INFO` |
| **Scheduler** | Off by default; you run connectors by hand | Off | On |
| **Object storage bucket** | `quant-docs-dev` | `quant-docs-staging` | `quant-docs-prod` |

### 1.3 What must **never** differ

These are the things that, if they drift, cause "works on my machine" — the failure mode
OPERATIONS.md 2.6 exists to prevent.

- [ ] **Database engine and major version.** Postgres 16 everywhere (or whichever you pin). Not
      SQLite here and Postgres there. Not 15 here and 16 there.
- [ ] **Schema.** Applied only by Alembic migrations, never by hand-editing a `schema.sql`
      (OPERATIONS.md 2.4). `alembic current` must report the same revision hash in all three.
- [ ] **Python version.** Pinned in `.python-version` to 3.12 (OPERATIONS.md 2.6).
- [ ] **Every package version.** From a committed `uv.lock`. Installs use `uv sync --frozen`,
      which fails rather than silently resolving something new.
- [ ] **Timezone.** Every process runs with `TZ=UTC` and every timestamp column is `TIMESTAMPTZ`.
      See [gap G9](#g9--clock-and-timezone-discipline-is-undefined-new) — this one is a genuine
      hole in the source specs and it produces off-by-one-day errors that look like data errors.
- [ ] **Mode resolution logic.** The code path that turns an authenticated principal into
      `personal` or `public` is identical everywhere, with no environment-conditional branches.
      An `if ENV == "local": mode = "personal"` shortcut is the exact defect CLAUDE.md's hard
      rules exist to prevent.
- [ ] **The compliance test suite.** Runs and passes in CI regardless of environment (SPEC.md 1.2
      mechanism 5).
- [ ] **Canonical chart of accounts and `canonical_key` values.** Pinned early; changing them
      mid-build is named as the main source of agent drift (DATA_FOUNDATION.md 7.6).

### 1.4 The honest position: you will collapse staging into local

🟡 **WATCH — collapsing staging into local.**

A solo builder does not run three environments. You will run two: your laptop and, from P9, the
hosted one. That is a reasonable choice and I am not going to pretend otherwise. But be clear
about what it costs, because the cost is not zero.

**What you lose by not having staging:**

1. **The first time a migration runs against production data is in production.** A migration
   that works on 40 seeded rows can time out, or fail a `NOT NULL` constraint, on 400,000 real
   ones. Adding a `NOT NULL` column with no default to a large table locks it while it rewrites.
2. **The first time the deploy configuration is exercised is in production.** Missing environment
   variable, wrong port, wrong database URL, missing TimescaleDB extension — you discover it
   while the thing is down.
3. **You cannot rehearse a restore realistically.** Restoring into your dev database means
   overwriting your dev database, which you will be reluctant to do, which means you will skip
   the drill, which means you do not actually have backups (see
   [§8](#8-backup-and-disaster-recovery--gap-g4)).

**What buys most of it back for very little money or effort:**

- [ ] **Migration dry-run in CI against a restored backup.** OPERATIONS.md 2.4 asks for exactly
      this: "migrations run in CI against a restored backup." This is the single highest-value
      substitute for staging and it costs nothing but a GitHub Actions job. Covered in
      [§7.6](#76-job-6--migration-dry-run).
- [ ] **A scratch database on the same machine, used only for restore drills.** Not a full
      environment — one database name, `quant_restore_drill`, created and dropped by a script.
      This is what makes the monthly restore drill in §8 something you actually do rather than
      something you feel guilty about.
- [ ] **A preview/staging service on the host from P9.** Railway and Render both support a second
      service pointed at the same repo on a different branch. **[NEEDS VERIFICATION]** — confirm
      current plan limits and whether a second Postgres instance is included or billed
      separately; DATA_FOUNDATION.md 8.1 budgets hosting at $20–40/mo total at v1.0, which does
      not obviously cover two databases.

**Early-warning signal that you needed staging:** the first time you fix something in production
by editing it live rather than by deploying a change. That is the moment to spend the extra
~$10/mo.

### 1.5 How a mistake in one environment is stopped from reaching another

This is a set of specific, mechanical guards. Not policy — code.

**Guard 1 — the production database URL is never on the laptop.**
Before P9 this is trivially satisfied (the laptop *is* production). From P9, the hosted database
credentials live only in the host's secret store and in your password manager. They are not in
any `.env` file on your machine. If you need production data locally, you get it by restoring a
backup, not by connecting to production.

**Guard 2 — the environment is loud and visible.**
Every surface states which environment it is. Streamlit shows a coloured banner. The API returns
an `X-Environment` header on every response. The Telegram bot prefixes messages with `[DEV]`
unless production.

```python
# packages/common/env.py — the one place environment is determined
import os
from enum import Enum

class Env(str, Enum):
    LOCAL = "local"
    STAGING = "staging"
    PRODUCTION = "production"

ENV = Env(os.environ.get("APP_ENV", "local"))
IS_PRODUCTION = ENV is Env.PRODUCTION

# Streamlit banner colours — so you cannot mistake one for another at a glance
BANNER = {
    Env.LOCAL:      ("#1f6feb", "LOCAL — seeded fixtures, safe to break"),
    Env.STAGING:    ("#9e6a03", "STAGING — restored copy, safe to break"),
    Env.PRODUCTION: ("#8b1a1a", "PRODUCTION — this is the real dataset"),
}
```

**Guard 3 — destructive scripts refuse to run in production.**
Any script that drops, truncates, re-seeds, or bulk-deletes starts with the same call.

```python
# scripts/_guard.py
from packages.common.env import IS_PRODUCTION

def refuse_in_production(action: str) -> None:
    if IS_PRODUCTION:
        raise SystemExit(
            f"REFUSED: '{action}' is destructive and APP_ENV=production. "
            f"If you truly mean it, run it against a restored copy first."
        )
```

Call it at the top of `seed_dev.py`, `reset_db.py`, `reextract_all.py`, and anything similar.
The reason this is worth the four lines: the realistic accident is not malice, it is a terminal
window you thought was pointed somewhere else.

**Guard 4 — database names are visibly different.**
`quant_dev`, `quant_staging`, `quant_prod`, `quant_restore_drill`. Never plain `quant` in more
than one place. When you are reading a connection string at speed, the name is the only thing
you actually check.

**Guard 5 — separate API keys per environment, with separate spend caps.**
A runaway loop in dev burning the production Anthropic budget is a real and boring way to lose a
month of extraction budget. Two keys, two caps ([§10](#10-llm-cost-control)).

**Guard 6 — the `MODE` default is `public` in every environment.**
SPEC.md 4.1 invariant 6. There is no environment in which the default flips. Personal mode is
reached by authenticating as a principal that holds the entitlement, never by being on
localhost. See [01_ARCHITECTURE.md](01_ARCHITECTURE.md) for the mode gate itself.

🟢 **SOLID — the environment model.** Two environments plus a restore-drill database, with the
six guards above, is a well-trodden setup. Nothing here is novel or clever, which is the point.

---

---

## 2. Local development on Windows 11

### 2.1 Python

**Use Python 3.11 or 3.12.** Not 3.13 yet: `pandas-ta-classic` declares pandas 3.0 compatibility
([SPEC.md 2A](../SPEC.md)) but the wider scientific stack on Windows still lags on the newest
release, and you do not want to be debugging a wheel build in week one.

**Use `uv` as the package manager.** 🟢 **SOLID.** It resolves and installs an order of magnitude
faster than pip, handles virtual environments, and — the reason that matters here —
[SPEC.md 2A](../SPEC.md) specifically notes `pandas-ta-classic` supports "uv+pip". Fast installs
matter more than usual on this project because AI agents will recreate environments repeatedly.

```powershell
winget install --id=astral-sh.uv -e
uv python install 3.12
cd C:\quant_model
uv venv
.venv\Scripts\Activate.ps1
uv pip install -e ".[dev]"
```

*Alternative considered:* Poetry — mature and widely used, but slower and its lockfile handling
adds friction with no benefit at this scale.

### 2.2 Postgres on Windows 11 — the decision that unblocks P0

🔴 **FRAGILE — this is friction on day one, and day-one friction is where projects die.** Three
approaches:

**1. Docker Desktop with a `compose.yaml` (recommended).**
*For:* One command up, one command down. The exact same image locally and in production. Trivial
to reset to a clean database when a migration goes wrong. TimescaleDB comes as an image, so you
never install an extension by hand.
*Against:* Docker Desktop on Windows needs WSL2, wants several GB of RAM, and is a background
service you will occasionally have to restart.

**2. Native Windows Postgres installer (EDB).**
*For:* No Docker, no WSL2, starts with Windows, lower memory.
*Against:* Installing the TimescaleDB extension on Windows natively is fiddly; resetting to a
clean state means dropping and recreating by hand; and your local setup then differs from
production in a way that will eventually bite.

**3. Postgres inside WSL2 directly.**
*For:* Native Linux performance, no Docker layer.
*Against:* Networking between Windows-side Python and WSL-side Postgres is one more thing to get
wrong, and file paths become confusing across the boundary.

**Recommendation: 1.** The reset-to-clean capability alone pays for it — you will run
`alembic downgrade base` and `upgrade head` many times in P0, and doing that against a container
you can destroy is far less nerve-racking than against an install you configured by hand.

```yaml
# compose.yaml
services:
  db:
    image: timescale/timescaledb:latest-pg16
    environment:
      POSTGRES_USER: quant
      POSTGRES_PASSWORD: ${POSTGRES_PASSWORD}
      POSTGRES_DB: quant
    ports: ["5432:5432"]
    volumes: ["pgdata:/var/lib/postgresql/data"]
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U quant"]
      interval: 5s
volumes: { pgdata: }
```

```powershell
docker compose up -d
uv run alembic upgrade head
uv run python scripts/seed_dev.py       # a principal, entitlements, data_sources rows
```

### 2.3 Running the stack

The processes, as built (corrected 2026-09-14 — an earlier draft named a `Home.py` and a
`packages.scheduler.run` module that never existed; corrected again 2026-09-25 for the API
launcher and the web app):

```powershell
.venv\Scripts\python.exe scripts\run_api.py                                      # the API, :8000
npm --prefix apps\web run dev                                                    # the web app, :3000
.venv\Scripts\python.exe -m streamlit run apps\streamlit\company_page.py --server.port 8501
.venv\Scripts\python.exe -m streamlit run apps\streamlit\macro_dashboard.py --server.port 8502
.venv\Scripts\python.exe -m streamlit run apps\streamlit\operations_page.py --server.port 8503
.venv\Scripts\python.exe scripts\run_scheduler.py                                # runs forever
```

**Start the API with `scripts\run_api.py`, not `python -m uvicorn` directly.** On Windows the
plain command runs on the Proactor event loop, and CPython's Proactor closes the *listening*
socket the first time a client resets a connection mid-accept (`WinError 64`). The process
stays up and never answers again. The web app resets connections by design - every fetch
that outruns its budget is aborted - so under normal use the plain command dies within
minutes. Reproduced 2026-09-25: the default loop stopped answering after one burst of 400
reset connections; the launcher, which selects the Selector loop, answered after five. If
you must run uvicorn by hand, pass `--loop asyncio:SelectorEventLoop`.

`run_scheduler.py --once` runs every job now and exits (non-zero on any failure, so it is
usable as a scheduled task whose exit code is the alert); `--once --job edgar:KO` runs one.
The operations page at :8503 is where a job that never ran becomes visible.

**The scheduler is a process, not a schedule.** Nothing fires at 03:00 unless
`run_scheduler.py` is running at 03:00. On a laptop that means: as long as the lid is up.
The durable form on Windows 11 is a Task Scheduler entry that starts it at logon and
restarts it if it dies — one command, run once, as the user who owns `.env`:

```powershell
schtasks /Create /TN "quant_model scheduler" /SC ONLOGON /RL LIMITED `
  /TR "C:\quant_model\.venv\Scripts\python.exe C:\quant_model\scripts\run_scheduler.py"
```

(and `schtasks /Run /TN "quant_model scheduler"` to start it without logging out;
`schtasks /Delete /TN "quant_model scheduler"` to remove it). A machine that sleeps at
03:00 still misses the run; the jobs are idempotent, so `--once` the next morning catches
up, and the operations page says which ones were missed. A host that is always on is §5.

Streamlit talks to `http://localhost:8000`, never to the database (ADR-0006). If you ever find
yourself putting a connection string into `apps/streamlit/`, that is the defect.

### 2.4 Seeding a dev database

`scripts/seed_dev.py` creates: one owner principal with `personal_tier=true`, one family
principal with `personal_tier=true`, one public principal with `personal_tier=false`, and the
`data_sources` rows with real licence values. **Three principals from day one** — it is the
cheapest possible guard against single-user assumptions creeping in (ADR-0007), because every
manual test you run naturally exercises more than one.

---

## 3. Database

### 3.1 PostgreSQL, and whether you need TimescaleDB on day one

**TimescaleDB in plain terms:** a Postgres extension that turns a normal table into a
"hypertable" — transparently partitioned by time. Queries and inserts on large time-series
tables get faster, and old data can be compressed automatically. You use it the same way you use
any table; the partitioning is invisible.

**Do you need it on day one?** No. **Should you use the image anyway?** Yes. Installing the
extension later is an easy migration, but *starting* with the image costs nothing and removes a
future decision. Convert `price_history`, `macro_observations`, `indicators` and `ml_features`
to hypertables when either exceeds a few million rows — realistically around P6.

### 3.2 Sizing — the arithmetic

Worth doing once, because the intuition ("financial data is huge") is wrong at this scale.

| Table | Rows | Est. bytes/row | Total |
|---|---|---|---|
| `price_history` — 200 securities × 10 yrs × 252 days | 504,000 | ~120 | ~60 MB |
| `statement_line_items` — 200 cos × 10 yrs × 4 periods × 150 items | 1,200,000 | ~250 | ~300 MB |
| `indicators` — 200 × 2,520 days × 6 indicators × 2 params | 6,048,000 | ~60 | ~360 MB |
| `ml_features` — 200 × 2,520 × 50 features | 25,200,000 | ~60 | ~1.5 GB |
| `news_items` + sentiment | ~200,000 | ~2,000 | ~400 MB |
| Indexes and overhead | | | ~1.5× the above |
| **Total, realistic** | | | **~6–7 GB** |

**Source PDFs are the bigger number** and they live in object storage, not the database: 200
companies × 10 years × ~8 MB ≈ **16 GB**.

🟢 **SOLID.** Both figures are small. This fits on a laptop and on the cheapest paid tier of any
host. Do not architect for scale you will not have.

### 3.3 Connection pooling

Use SQLAlchemy's built-in pool locally (`pool_size=5, max_overflow=10`). Add PgBouncer only if
P12 shows connection exhaustion under real load — not before.

### 3.4 Migrations — Alembic

🟢 **SOLID.** The standard tool, and it does what is needed here.

**Three rules:**
1. **One concern per revision.** Six revisions in P0 rather than one, so a later problem points
   at a specific concern.
2. **Every migration must be reversible**, and CI proves it with `upgrade → downgrade → upgrade`.
3. **Never edit a migration that has been applied anywhere but your laptop.** Write a new one.

---

## 4. Object storage for source documents

The provenance rule ([CLAUDE.md](../CLAUDE.md)) means every original document must be retrievable
**forever** — including after the source website has been redesigned or has vanished, which
[TEAM_BRIEF.md Part 3](../TEAM_BRIEF.md) item 3 warns is a live risk for the Nigerian sources.

| Option | Cost | Verdict |
|---|---|---|
| **Local disk + backup** | £0 | P0–P8. Simple, and it is what you are backing up anyway. |
| **Cloudflare R2** | ~$0.015/GB/mo, **zero egress** | **Recommended from P9.** ~16 GB ≈ $0.25/mo. Zero egress fees matter because you will re-read documents for re-parsing. |
| **AWS S3** | ~$0.023/GB/mo + egress | Works; egress charges are the annoyance. |
| **Backblaze B2** | ~$0.006/GB/mo | Cheapest; smaller ecosystem. |

**Rules, regardless of backend:**
- **Key by content hash**, not by name: `documents/sha256/<hash>.pdf`. Deduplication is automatic
  and the key proves the file never changed.
- **Write once. Never overwrite, never delete.** A reissued report is a new object.
- **Enable versioning and object lock** where the provider offers it — it turns "never overwrite"
  from a discipline into a guarantee.
- **Store the metadata in `source_documents`**, the bytes in storage.

---

## 5. Hosting

Nothing is hosted before P9. Until then, production is your laptop (§1).

| Option | Monthly | For | Against |
|---|---|---|---|
| **Railway** | ~$5–20 | Simplest deploy; managed Postgres; good DX | Costs scale up quickly with usage |
| **Render** | ~$7–25 | Similar; free tier for static; predictable | Cold starts on lower tiers |
| **Fly.io** | ~$5–15 | Regions close to Lagos; cheap | More configuration |
| **A plain VPS (Hetzner/DO)** | ~$5–10 | Cheapest, full control | You own OS patching, backups, TLS |

**Recommendation: Railway for P9**, on the strength of the managed Postgres and the deploy
experience — a solo builder's time is the scarce resource. Reassess at P12 when real load and
real users arrive.

**What changes at P12** ([DATA_FOUNDATION.md 6.6](../DATA_FOUNDATION.md)): real user load, rate
limiting and abuse protection become mandatory, auth becomes mandatory, and **if you host
outside Nigeria you need documented adequate safeguards for cross-border personal-data transfer**
under NDPA.

---

## 6. Secrets management

[OPERATIONS.md 2.5](../OPERATIONS.md).

**What is a secret here:** FRED API key, LLM API key, Telegram bot token, database password,
object-storage credentials, and — from P13 — **broker API keys, which can move money.**

| Phase | Mechanism |
|---|---|
| P0–P8 | `.env`, git-ignored, never committed. `.env.example` with empty values **is** committed. |
| P9+ | The host's secret store (Railway/Render environment variables). Never in the image. |
| P13 | Broker keys in a separate store with tighter access; **use paper-trading endpoints first, always.** |

**The pre-commit guard — install it in P0, not later:**

```yaml
# .pre-commit-config.yaml
repos:
  - repo: https://github.com/gitleaks/gitleaks
    rev: v8.18.0
    hooks: [{ id: gitleaks }]
```

> **Once a secret reaches a remote it is compromised, permanently.** Rotate it. Do not
> force-push and hope — assume it was captured. This is why the guard runs *before* the commit
> rather than in CI after it.

**Rotation:** every key at P12, and immediately on any suspicion. Record the rotation date. Keys
that can move money (P13) rotate on a schedule regardless.

---

## 7. CI/CD

```yaml
# .github/workflows/ci.yml
name: CI
on: [push, pull_request]

jobs:
  quality:
    runs-on: ubuntu-latest
    services:
      postgres:
        image: timescale/timescaledb:latest-pg16
        env: { POSTGRES_USER: quant, POSTGRES_PASSWORD: test, POSTGRES_DB: quant_test }
        options: >-
          --health-cmd pg_isready --health-interval 5s --health-retries 10
        ports: ["5432:5432"]
    env:
      DATABASE_URL: postgresql://quant:test@localhost:5432/quant_test
    steps:
      - uses: actions/checkout@v4
      - uses: astral-sh/setup-uv@v3
      - run: uv python install 3.12
      - run: uv pip install -e ".[dev]"

      - name: Lint
        run: uv run ruff check . && uv run ruff format --check .
      - name: Types
        run: uv run mypy packages services
      - name: Import direction (ADR-0006)
        run: uv run lint-imports

      - name: Migrations apply, reverse, reapply
        run: |
          uv run alembic upgrade head
          uv run alembic downgrade base
          uv run alembic upgrade head

      - name: Unit + known-answer
        run: uv run pytest tests/unit tests/known_answer -q

      - name: INVARIANTS (never skippable)
        run: uv run pytest -m invariant -q --strict-markers

      - name: COMPLIANCE (blocks merge)
        run: uv run pytest tests/compliance -q

      - name: Synthetic backtest — is the engine lying?
        run: uv run pytest tests/synthetic -q

      - name: Golden extraction (subset)
        run: uv run pytest tests/golden -q -m "not slow"

      - name: Secret scan
        uses: gitleaks/gitleaks-action@v2
```

**The rule:** a red **invariant** or **compliance** job blocks the merge with no override.
Everything else can be triaged. See [07_TEST_STRATEGY.md](07_TEST_STRATEGY.md) §10.

Branch protection on `main`, requiring this workflow, is what makes
[CLAUDE.md](../CLAUDE.md)'s "one task, one PR, tests required" real rather than aspirational.

---

## 8. Backup and disaster recovery — gap G4

**This is TG4. No task in [SPEC.md 4.2](../SPEC.md) schedules it**, and
[OPERATIONS.md 2.1](../OPERATIONS.md) calls the dataset "genuinely irreplaceable" and says to
build backups "in week one, before v0.1 has any data worth losing."

**Why it outranks almost everything:** every other failure in this project costs time. This one
costs the asset. [PROJECT_CONTEXT.md 9.3](../PROJECT_CONTEXT.md) makes the dataset the thing that
makes the company acquirable; [TEAM_BRIEF.md Part 3](../TEAM_BRIEF.md) lists "losing the data" —
months of extraction living on one laptop — among the quiet risks, and prescribes a restore drill
"because a backup nobody has restored is not a backup."

### RPO and RTO, in plain words

- **RPO (Recovery Point Objective)** — how much work you are willing to lose. **Target: 24 hours.**
  A day of re-typing is painful; a month is fatal.
- **RTO (Recovery Time Objective)** — how long you are willing to be down. **Target: 4 hours.**

### The 3-2-1 rule, applied concretely

**Three** copies, on **two** kinds of media, with **one** off-site.

| Copy | Where | How |
|---|---|---|
| 1 — live | Laptop Postgres volume + local `data/` | — |
| 2 — local backup | External drive or a second internal disk | Nightly `pg_dump` + document sync |
| 3 — **off-site** | Cloudflare R2 / B2 bucket, **separate credentials** | Nightly encrypted upload |

**Separate credentials on copy 3 is the point.** If the laptop is compromised or ransomware runs,
a backup reachable with the same credentials is not a backup.

```bash
# scripts/backup.sh
set -euo pipefail
STAMP=$(date -u +%Y%m%dT%H%M%SZ)
pg_dump --format=custom --file="backups/quant_${STAMP}.dump" "$DATABASE_URL"
gpg --encrypt --recipient "$BACKUP_GPG_ID" "backups/quant_${STAMP}.dump"
rclone copy "backups/quant_${STAMP}.dump.gpg" "r2:quant-backups/db/"
rclone sync data/documents "r2:quant-backups/documents/"
psql "$DATABASE_URL" -c "INSERT INTO connector_runs
  (connector_name, started_at, finished_at, status, rows_written)
  VALUES ('backup', now(), now(), 'ok', 1);"
```

Recording the backup as a `connector_runs` row means the freshness monitor (§9) alerts you when
**backups** stop, not only when data stops.

### The restore drill — the part that is actually the backup

```bash
# scripts/restore.sh  — restores into a SEPARATE database. Never over the live one.
set -euo pipefail
createdb quant_restore_test
gpg --decrypt "$1" | pg_restore --dbname=quant_restore_test --clean --if-exists
psql quant_restore_test -c "SELECT count(*) FROM information_schema.tables
                            WHERE table_schema='public';"
```

**Schedule:** run it **in P0 while the database is empty**, then **quarterly**, and always after
any schema change large enough to worry you. Record the date and the row counts each time.

> 🔴 **FRAGILE until proven, 🟢 SOLID afterwards.** An untested backup is a file you *believe* is a
> backup, and the distinction only becomes visible on the day it matters. Ten minutes in P0
> eliminates the single unrecoverable failure in this project. Three approaches if the full
> drill feels heavy: (1) full drill quarterly plus automated nightly dumps — recommended;
> (2) automated restore-verification in CI against a scrubbed dump — stronger but more to build;
> (3) rely on the host's managed backups from P9 — necessary but **not sufficient**, because it
> covers nothing before P9 and does not cover the object store.

---

## 9. Observability

### 9.1 The failure that matters most: a scraper that succeeds at nothing

The page loads. The parser runs. The selector matches nothing. `status = 'ok'`, HTTP 200, zero
rows, no exception. Nothing alerts, and you discover it weeks later when a chart has a flat line.

**The detector** ([OPERATIONS.md 2.3](../OPERATIONS.md)):

```sql
-- alert when a connector "succeeds" but writes nothing on a day data was expected
SELECT connector_name, started_at
FROM   connector_runs
WHERE  status = 'ok' AND rows_written = 0
  AND  started_at > now() - interval '2 days';
```

`rows_written` is the single most important operational column in the schema.

### 9.2 Freshness monitoring

[OPERATIONS.md 2.2](../OPERATIONS.md) — making [CLAUDE.md](../CLAUDE.md)'s "staleness is visible"
rule executable. Each `macro_series` declares `expected_lag_days`; a daily job flags anything past
it, the dashboard renders the flag visibly (not subtle grey), and repeated overdue triggers an
alert.

### 9.3 Logging, metrics, errors

| Concern | P0–P8 | P9+ |
|---|---|---|
| Logs | `structlog` JSON to file | Ship to the host's log view |
| Errors | Console + a `errors` table | **Sentry free tier** — 🟢 SOLID, generous, minimal setup |
| Metrics | `connector_runs`, `audit_log`, `llm_spend` — SQL is enough | Add a dashboard only if SQL stops being enough |
| Uptime | — | UptimeRobot free tier on `/health` |

Resist adding Prometheus and Grafana. At this scale a handful of SQL queries answers every
question those would, and they are one more thing to keep alive.

---

## 10. LLM cost control

[SPEC.md 3.5](../SPEC.md) and [SPEC.md 2E](../SPEC.md). This is the one operating cost that can
run away silently, because a loop that retries a failed extraction is a loop that spends money.

**Four mechanisms, all required:**

1. **Per-principal spend caps.** `entitlements.llm_spend_cap_usd`, checked before every call,
   recorded in `llm_spend`. Multi-user from day one means caps are per user, never global
   ([PROJECT_CONTEXT.md 4](../PROJECT_CONTEXT.md)).
2. **Content-hash caching.** Key on the hash of the input bundle. The same document with the same
   prompt version must never be paid for twice. This is also what makes P9's memos affordable.
3. **Model routing / tiering.** [SPEC.md 2E](../SPEC.md): a cheap Haiku-class model for ticker
   tagging and bulk sentiment; an expensive Sonnet- or Opus-class model only for the arbitrator
   and memo synthesis. In P4, the cheap deterministic tools read the document and the LLM only
   reconciles — that is what keeps extraction cost bounded
   ([DATA_FOUNDATION.md 3.1](../DATA_FOUNDATION.md)).
4. **A hard monthly ceiling with alerting.** At 80% of the cap, alert. At 100%, **halt** — do not
   degrade silently, and do not continue billing.

**The metric to watch:** *cost per document* should **fall** over time as the cache warms and
few-shot examples reduce retries. If it is flat or rising, something is wrong — usually cache
misses from a prompt that changes on every run.

🟡 **WATCH.** *Early-warning signal:* cost per document not falling week over week in P4.

---

## 11. Runbook

[OPERATIONS.md 3.3](../OPERATIONS.md). Symptom → diagnosis → fix → prevention.

### A connector stopped returning data
**Symptom:** `rows_written = 0` with `status = 'ok'`, or a stale-flagged series.
**Diagnose:** fetch the URL by hand; compare against the stored raw fixture; check for a site
redesign or a robots/rate-limit change.
**Fix:** repair the parser against the new structure; re-run for the missed window from cached raw
where possible. **Escalate to the manual CSV path so data keeps flowing while you fix it.**
**Prevent:** structural-change detection by hashing the listing page.

### A bad extraction reached production
**Diagnose:** find the `extraction_job_id`; determine whether it is one figure or a systematic
batch error.
**Fix:** correct via the **versioned** path — new row, `superseded_by`, `corrected_by`,
`correction_reason`. **Never `UPDATE`** ([CLAUDE.md](../CLAUDE.md)). For a systematic error,
invalidate the whole batch by `extraction_job_id` — which is why that column exists.
**Prevent:** add the case to the golden set; add a validation rule if arithmetic could have caught
it.

### The database is lost or corrupted
1. Do not panic; do not write to the damaged database.
2. `./scripts/restore.sh <latest .gpg>` into `quant_restore_test`.
3. Verify table and row counts against the last recorded drill.
4. Promote only after verification.
5. Re-run ingestion for the gap between the backup and now.
**Prevent:** §8, and actually running the quarterly drill.

### A secret leaked
1. **Rotate immediately.** Assume capture.
2. Check `audit_log` and provider logs for use.
3. Purge from history if feasible — but rotation is the fix, not purging.
**Prevent:** the pre-commit gitleaks hook (§6).

### LLM spend spiked
**Diagnose:** `SELECT principal_id, sum(cost_usd) FROM llm_spend WHERE ts > now() - interval '7 days' GROUP BY 1;`
Look for a retry loop or a cache-key change.
**Fix:** halt the job, fix the loop, lower the cap.
**Prevent:** the four mechanisms in §10.

### An NGX source vanished
**Diagnose:** confirm it is gone, not merely down.
**Fix:** switch to the documented paid fallback (EODHD `.XNSA`). **You keep everything already
fetched, because raw responses were cached permanently** — this is the entire reason for that
rule.
**Prevent:** [TEAM_BRIEF.md Part 3](../TEAM_BRIEF.md) item 3 — write the fallback connector before
you need it, so switching is a decision rather than a scramble.

---

## 12. Cost table by phase

Grounded in [DATA_FOUNDATION.md 8.1](../DATA_FOUNDATION.md) and
[SPEC.md PART 6](../SPEC.md); this document's own additions are marked
**[NEEDS VERIFICATION]** and should be confirmed against current provider pricing before you
budget on them.

| Phase | Infra | LLM | Data | Est. monthly |
|---|---|---|---|---|
| P0–P3 | £0 (laptop) | ~$0–5 | £0 (free sources) | **~$0–5** |
| P4 | £0 + ~$1 storage | **$20–100+** — the variable one | £0 | **~$25–105** |
| P5–P6 | £0 | ~$10–30 | £0 | **~$10–30** |
| P7–P8 | £0 | ~$5–20 | Possibly EODHD if gate G-A taken | **~$5–20** (+feed) |
| P9 | ~$15–30 hosting + storage | ~$20–60 memos | | **~$35–90** |
| P10–P11 | ~$15–30 | ~$20–60 | | **~$35–90** |
| P12 | ~$30–80 (load, monitoring) | ~$30–100 | **Licensed data if redistributing** | **~$60–180+** |
| P13 | ~$30–80 | ~$30–100 | Broker fees are per-trade, not monthly | **~$60–180** |

**The number to watch is P4's LLM spend.** It is the only line that can run away, and §10 exists
for it. Everything else here is small and predictable — which, given how much of this project is
genuinely uncertain, is worth noticing.

---

## 13. Gaps surfaced by this document

**TG4 restated:** backup and DR is unscheduled in [SPEC.md 4.2](../SPEC.md) and belongs in **P0**,
not P9, because production is your laptop from the first hand-entered figure (§1).

New:

| ID | Gap | Consequence |
|---|---|---|
| **TG17** | **No task owns object storage.** The provenance rule requires source documents retrievable forever, but no task creates the bucket, the naming scheme, or the immutability policy. | Documents accumulate on a laptop with no off-site copy, and the "forever" promise quietly fails. **Belongs in P0.** |
| **TG18** | **Nothing defines the restore-drill cadence.** [OPERATIONS.md 2.1](../OPERATIONS.md) requires a drill; no schedule exists. | Drills happen once and then never. **Quarterly, recorded, proposed in §8.** |
| **TG19** | **No environment-parity check.** Nothing prevents local and production diverging on Postgres version or extensions. | A migration that works locally fails on deploy. **Pin the image tag in both; assert the version in `/health`.** |
| **TG20** | **`system_config` has no owner for regulatory effective-dates.** The NGX movement rule and Nigerian CGT both changed during planning ([TEAM_BRIEF.md Part 3](../TEAM_BRIEF.md)), and both are encoded as thresholds. | A stale threshold silently produces wrong costs or wrong tax. **Quarterly regulatory review, recorded as ADRs.** |

---

## 14. Infrastructure checklist by phase

**P0** — [ ] Docker Postgres running · [ ] `uv` env · [ ] Alembic, migrations reversible ·
[ ] `.env` + `.env.example` + gitleaks pre-commit · [ ] CI green with invariant and compliance
jobs · [ ] **backup script written and a restore actually performed** · [ ] object storage bucket
with content-hash keys (TG17) · [ ] three seeded principals · [ ] `/health` reports DB and
migration head

**P1** — [ ] scheduler running · [ ] `connector_runs` populated · [ ] zero-row alert firing ·
[ ] freshness flags on the dashboard

**P4** — [ ] LLM spend caps enforced · [ ] content-hash cache working · [ ] model tiering ·
[ ] cost-per-document tracked and falling

**P9** — [ ] host chosen and deployed · [ ] staging environment · [ ] secrets in the host store ·
[ ] Sentry · [ ] uptime monitoring · [ ] managed backups **in addition to** your own

**P12** — [ ] rate limiting · [ ] all secrets rotated · [ ] cross-border transfer safeguards
documented · [ ] breach-notification runbook walked through (72 hours, NDPA)

**P13** — [ ] broker keys segregated · [ ] paper endpoints first · [ ] kill switch rehearsed
under load

---

## 15. Appendices

### A — `.env.example` (committed; values empty)

```bash
DATABASE_URL=postgresql://quant:CHANGE_ME@localhost:5432/quant
POSTGRES_PASSWORD=
ENVIRONMENT=local                 # local | staging | production
FRED_API_KEY=
ANTHROPIC_API_KEY=
LLM_MONTHLY_CAP_USD=50
TELEGRAM_BOT_TOKEN=
R2_ACCESS_KEY_ID=
R2_SECRET_ACCESS_KEY=
R2_BUCKET=quant-documents
BACKUP_GPG_ID=
SEC_USER_AGENT="Your Name your@email.com"   # EDGAR requires name + email
```

### B — `pyproject.toml` skeleton

```toml
[project]
name = "quant-model"
requires-python = ">=3.11,<3.13"
dependencies = [
  "fastapi", "uvicorn[standard]", "sqlalchemy", "alembic", "psycopg[binary]",
  "pydantic", "structlog", "httpx", "apscheduler",
  "pandas", "numpy", "pandas-ta-classic",
  "pdfplumber", "pymupdf", "anthropic",
  "streamlit", "python-telegram-bot",
]

[project.optional-dependencies]
dev = ["pytest", "pytest-cov", "hypothesis", "ruff", "mypy",
       "import-linter", "pre-commit"]

[tool.pytest.ini_options]
markers = [
  "invariant: SPEC 4.1 invariants — NEVER skip",
  "slow: excluded from the fast loop",
  "live: touches the network — excluded from CI",
  "gate: phase-gate only",
]

[tool.importlinter]
root_package = "packages"

[[tool.importlinter.contracts]]
name = "packages must not import apps or services (ADR-0006)"
type = "forbidden"
source_modules = ["packages"]
forbidden_modules = ["apps", "services"]
```

### C — Scripts index

| Script | Purpose | From |
|---|---|---|
| `scripts/backup.sh` | `pg_dump` + encrypt + off-site sync + health row | P0 |
| `scripts/restore.sh` | Restore into `quant_restore_test`, **never over live** | P0 |
| `scripts/seed_dev.py` | Three principals, entitlements, `data_sources` | P0 |
| `scripts/check_freshness.py` | Flag series past `expected_lag_days` | P1 |
| `scripts/check_connectors.py` | The `rows_written = 0` silent-failure query | P1 |
| `scripts/llm_spend_report.py` | Spend by principal and by job | P4 |

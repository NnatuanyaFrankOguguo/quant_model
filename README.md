# quant_model

A centralised financial data hub for Nigerian and US listed companies: statements, history,
macro backdrop, news, and user-driven valuation tools. The hard, valuable part is turning
Nigerian financial PDFs into clean, queryable, provenance-tracked data.

**Status: P0 (Foundation & Rails).** The spine exists — a running API that already knows who is
asking and what mode they get, a migrated database, a compliance suite, and a backup that has
actually been restored. No financial logic yet, by design.

Private repository. The access model is *build everything to public standard, restrict who can
log in* — see [CLAUDE.md](CLAUDE.md).

## Where the plan lives

**[docs/00_START_HERE.md](docs/00_START_HERE.md)** — read it first, every session. §5 is the
P0–P13 phase map, §6 is the live progress tracker, §8 the decisions already taken.
[docs/10_PRE_BUILD_CORRECTIONS.md](docs/10_PRE_BUILD_CORRECTIONS.md) has the highest precedence
in the set. Decisions are recorded in [docs/adr/](docs/adr/README.md).

## Setup on a fresh Windows machine

```powershell
winget install --id astral-sh.uv -e      # then restart the shell: it edits PATH
uv python install 3.12                   # NOT 3.13+; pyproject pins >=3.11,<3.13
uv venv
uv pip install -e ".[dev]"
Copy-Item .env.example .env              # then fill in DATABASE_URL and TEST_DATABASE_URL
.venv\Scripts\pre-commit.exe install     # the secret guard — do not skip
.venv\Scripts\python.exe -m alembic upgrade head
.venv\Scripts\python.exe scripts\seed_dev.py
.venv\Scripts\python.exe -m uvicorn services.api.main:app --reload
```

**The database is Neon-hosted PostgreSQL 18, not a local server** ([ADR-0008](docs/adr/0008-neon-managed-postgres.md)).
There is nothing to install and nothing to start, but you need the network to work, and
`DATABASE_URL` in `.env` is a live credential. `TEST_DATABASE_URL` must point at a **different**
database: the suite drops and recreates its schema, and `tests/conftest.py` hard-fails if the two
resolve to the same place.

There is no `psql` or `pg_dump` on this machine. Where a Postgres client is genuinely needed
(the backup path) it runs from the `postgres:18` Docker image, and the client major version must
be ≥ the server's.

## Running things

```powershell
.venv\Scripts\python.exe -m pytest tests/unit tests/compliance -v   # the suite
.venv\Scripts\python.exe -m pytest -m invariant                     # SPEC §4.1 invariants
.venv\Scripts\python.exe -m ruff check . ; .venv\Scripts\python.exe -m mypy packages services
.venv\Scripts\lint-imports.exe                                      # the one-way import rule
.\scripts\backup.ps1 ; .\scripts\restore.ps1                        # needs Docker running
.venv\Scripts\python.exe scripts\mint_token.py --principal <id> --label laptop
```

Compliance tests may never be skipped or `xfail`ed ([docs/07 §4](docs/07_TEST_STRATEGY.md)).

## The P0 test checkpoint, as it runs on this machine

[docs/03 P0](docs/03_ROADMAP_PART1_PHASES_0-6.md) lists 17 checks against a local Postgres and
unversioned API paths. Two things differ here, both deliberate: the database is Neon, and **every
API path is versioned** — `/v1/public/*` and `/v1/personal/*`, per
[docs/10 §6.5](docs/10_PRE_BUILD_CORRECTIONS.md), which calls versioning "the cheapest high-value
fix in this audit". `/health` stays unversioned.

```powershell
# 1-2  migrations apply from empty, and reverse
$env:QUANT_DB_TARGET='test'; .venv\Scripts\python.exe -m alembic upgrade head
.venv\Scripts\python.exe -m alembic downgrade base
.venv\Scripts\python.exe -m alembic upgrade head

# 3-9  the service, the mode gate, and entitlement
curl.exe -s localhost:8000/health
curl.exe -s localhost:8000/v1/public/ping                              # {"mode":"public"}
curl.exe -s -H "X-Mode: personal" localhost:8000/v1/public/ping        # still public
curl.exe -s "localhost:8000/v1/public/ping?mode=personal"              # still public
curl.exe -s -o nul -w "%{http_code}" localhost:8000/v1/personal/ping   # 403 anonymous
curl.exe -s -H "Authorization: Bearer $OWNER" localhost:8000/v1/personal/ping

# 10-12  suites, import direction, secrets
.venv\Scripts\python.exe -m pytest tests/compliance -v
.venv\Scripts\lint-imports.exe
docker run --rm -v "${PWD}:/repo" zricethezav/gitleaks:latest detect --source=/repo --no-git --config=/repo/.gitleaks.toml

# 14  the backup actually restores
.\scripts\backup.ps1 ; .\scripts\restore.ps1

# 16  read the audit log yourself — every request above should have a row
```

Check 16 is worth doing by eye rather than trusting a test: if a request is missing from
`audit_log`, some route escaped the middleware, and that route will one day carry something that
matters.

## Layout

```
apps/          streamlit (P1+), bot (P5+), web (P9+) — thin clients only
services/api/  FastAPI: /health, /v1/public/*, /v1/personal/*; principal and mode resolved HERE
packages/      common, compliance, ingestion, scheduler — see packages/README.md
db/migrations/ Alembic; one concern per revision
tests/         unit, compliance (never skipped), golden/synthetic/known_answer (later phases)
scripts/       backup, restore, seed_dev, mint_token
docs/          the build plan and the ADR log
```

`packages/*` must never import from `apps/*` or `services/*` — enforced by `lint-imports`.

## The rules that override everything

Full list in [PROJECT_CONTEXT.md §10](PROJECT_CONTEXT.md); the ones that bite daily:

- **Mode is server-derived.** Never trust a client-supplied mode. Default `public`.
- **Never expose personal-mode output to a non-family user pre-licence.** Access control in
  code, not policy. The only line with real legal risk.
- **Provenance on every figure** — source document, page, as-of date.
- **Never infer missing financial data.** Absent line items are null, never estimated.
- **Point-in-time only.** Features respect `known_as_of`.
- **No silent overwrites.** Corrections are versioned and attributed.
- **One task, one PR**, tests required.

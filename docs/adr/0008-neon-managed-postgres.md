# ADR-0008 — Neon managed PostgreSQL, not local Docker Postgres

- **Status:** ACCEPTED
- **Date:** 2026-09-01
- **Amends:** [ADR-0001](0001-storage-engine-postgresql.md). That ADR chose the *engine*; this
  one chooses the *host*, which nobody had recorded.
- **Touches:** TG19 (environment parity), TG4 (backup/DR), and the TimescaleDB note in
  [docs/02_INFRASTRUCTURE.md](../02_INFRASTRUCTURE.md) §3.1
- **Sources:** [docs/03_ROADMAP_PART1_PHASES_0-6.md](../03_ROADMAP_PART1_PHASES_0-6.md) §P0.3;
  [docs/02_INFRASTRUCTURE.md](../02_INFRASTRUCTURE.md) §2.2, §3.1, §1.3, §1.4, §8

## Context

ADR-0001 settled PostgreSQL. It did not say where the PostgreSQL runs, and
[docs/02](../02_INFRASTRUCTURE.md) §2.2 assumed the answer was local Docker Desktop with a
`compose.yaml` — an assumption that reaches into the backup script, the CI design, the
TimescaleDB note, and the environment-parity gap TG19.

On 2026-09-01 the owner provisioned a **Neon** instance (managed, serverless PostgreSQL) and put
its URL in `.env`. That is a real architectural decision arriving as a configuration change,
which is exactly the kind that goes unrecorded and is then re-litigated in six months.

Verified directly against the instance on 2026-09-01:

| Fact | Value |
|---|---|
| Server version | **PostgreSQL 18.6** (the documents assumed 16) |
| Host | `ep-square-river-b1okmrt5.c-5.eu-central-1.aws.neon.tech` (AWS `eu-central-1`) |
| TLS | `sslmode=require`, non-negotiable |
| Databases | `neondb` (dev), `quant_test` (created for this phase), `postgres` |
| `CREATE DATABASE` | permitted as `neondb_owner` |
| Installed extensions | `plpgsql` only |
| Available, not installed | `timescaledb`, `pgcrypto`, `uuid-ossp`, `pg_stat_statements`, `btree_gist` |

## Decision

**Neon is the database for local development, and the intended host for production.** Local
Docker Postgres is not installed and `compose.yaml` is not written.

**CI does not use Neon.** It uses a throwaway `postgres:18` service container, so the pipeline
needs no production credential and can never touch real data. This is a deliberate divergence
from "local and production must never differ" ([docs/02](../02_INFRASTRUCTURE.md) §1.3) and it
is the right one: a CI job that can reach the real database is a worse risk than a minor version
difference between a container and a managed instance.

## Consequences

**What it buys.**

- P0.3's day-one friction — *"perhaps two hours of setup, and it is friction on day one when
  momentum matters most"* — disappears entirely. No Docker Desktop, no WSL2, no 4 GB of RAM held
  by a background service.
- No local `psql`/`pg_dump`/`createdb` is needed for ordinary work, which matters because
  [docs/10](../10_PRE_BUILD_CORRECTIONS.md) §1 flagged their absence as blocking for P0 checks 1,
  14 and 16. SQLAlchemy and Alembic cover checks 1 and 16; only the backup path still needs a
  client, and it gets one through Docker.
- One engine everywhere, which was the point of ADR-0001.
- Managed point-in-time recovery and branching exist without us building them.

**What it costs, and what changes.**

- **Local development now depends on the network.** There is no offline loop and no aeroplane
  work. [docs/02](../02_INFRASTRUCTURE.md) §1.4 ("you will collapse staging into local") assumed
  a local engine; that paragraph is now wrong in its mechanics, though not in its conclusion.
- **Connection handling is not optional.** Neon closes idle connections and the free tier scales
  to zero, so the first query after an idle period pays a cold start. `pool_pre_ping=True` in
  [packages/common/db.py](../../packages/common/db.py) is load-bearing, not hygiene — remove it
  and you get intermittent `OperationalError` on the first request after lunch.
- **The `pg_dump` client must be version ≥ the server.** The server is 18.6, so the backup script
  pins the `postgres:18` image. An older client refuses a newer server outright, and it is an
  hour lost to a message nobody reads carefully the first time.
- **TG19 (environment parity) now reads differently, and worse.** The gap used to mean "local and
  production drift". It now means **dev and production may be the same instance**, separated by
  nothing but a database name. Today the separation is: `neondb` for development, `quant_test`
  for tests, and *no production database exists yet*. `ENVIRONMENT=local` in `.env` is a label,
  not a boundary — nothing enforces it. **Before P9 puts a family member in front of this, dev
  and production must be separated by a Neon branch or a separate Neon project, and
  [packages/common/db.py](../../packages/common/db.py) must refuse to start when `ENVIRONMENT`
  and the target database disagree.** Recorded here rather than in a backlog because the failure
  mode — a migration or a `seed_dev.py` run against production — is silent and immediate.
  *[NEEDS VERIFICATION]* whether the current Neon plan includes branching.
- **Managed backups do not discharge TG4.** Neon's PITR is one copy, held by one provider, tied
  to one account, and it disappears with the account — billing lapse, credential loss, provider
  incident. [OPERATIONS.md](../../OPERATIONS.md) §2.1's 3-2-1 rule is not satisfied by it, and
  [PROJECT_CONTEXT.md](../../PROJECT_CONTEXT.md) §9.3 calls the dataset the asset. `pg_dump` to a
  second physical location stays mandatory, and so does actually restoring from it.
- The dataset now lives on third-party infrastructure in the EU. That is a data-residency and
  processor question for NDPA compliance at P12, not a P0 one, but it is cheaper to note now than
  to discover during the P12 legal work.

**TimescaleDB — reopened, not settled.**

[docs/02](../02_INFRASTRUCTURE.md) §3.1 said to start from the Timescale image because doing so
"costs nothing and removes a future decision", with `price_history`, `macro_observations`,
`indicators` and `ml_features` becoming hypertables around P6. That reasoning assumed a Docker
image we control. On Neon, `timescaledb` appears in `pg_available_extensions` but is **not
installed**, and a managed provider's build of it need not match the image's — typically the
Apache-licensed subset, without the compression and continuous-aggregate features that made it
attractive. **This is a live question for P6, not a settled one.** *[NEEDS VERIFICATION]* which
TimescaleDB version and licence tier this Neon plan actually offers, and whether
`CREATE EXTENSION timescaledb` succeeds. The P6 entry criteria should carry it. Note that the
sizing arithmetic in [docs/02](../02_INFRASTRUCTURE.md) §3.2 (~6–7 GB total) means plain
PostgreSQL is sufficient on the merits; hypertables are an optimisation, not a dependency.

## Alternatives rejected

**Local Docker Postgres** ([docs/02](../02_INFRASTRUCTURE.md) §2.2 approach 1, the previous
recommendation). *For:* offline; identical image locally and in production; trivial reset to a
clean database; TimescaleDB by image rather than by extension request; no credential in `.env`
that is also a production credential. *Against:* Docker Desktop plus WSL2 plus several GB of RAM
as a permanent background cost, and it reintroduces exactly the day-one friction that ADR-0001
flagged as its own main cost. The deciding factor is that the instance already exists and works;
re-deciding it would cost a day and buy an offline loop the owner has not asked for.

**Native Windows Postgres (EDB installer)** (approach 2). *For:* no Docker, starts with Windows,
lower memory. *Against:* TimescaleDB on Windows natively is fiddly, resetting means dropping and
recreating by hand, and local then differs from production in a way that eventually bites.

**Both remain available.** Nothing in the schema, the migrations or the application code is
Neon-specific — the only coupling is a connection string and `pool_pre_ping`. Reversing this ADR
costs an afternoon, which is the main reason it was safe to accept it as quickly as it arrived.

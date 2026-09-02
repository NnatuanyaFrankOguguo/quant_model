# ADR-0001 — Storage engine: PostgreSQL from day one

- **Status:** ACCEPTED
- **Date:** 2026-08-30 (closed during the pre-build audit)
- **Closes:** TG9
- **Sources:** [docs/01_ARCHITECTURE.md](../01_ARCHITECTURE.md) §9 ADR-0001 (text below is
  copied from there); [docs/03_ROADMAP_PART1_PHASES_0-6.md](../03_ROADMAP_PART1_PHASES_0-6.md)
  §P0.3 (the three approaches)
- **Amended by:** [ADR-0008](0008-neon-managed-postgres.md), which chooses *where* the
  PostgreSQL runs. This ADR chose the engine; 0008 chose the host.

## Context

The source documents contradicted each other and nobody had picked. This had to be decided
before the DDL was written, because the DDL is written in one dialect or the other.

| Document | Says |
|---|---|
| [DATA_FOUNDATION.md](../../DATA_FOUNDATION.md) §4.1 | DuckDB/SQLite for v0.x |
| [SPEC.md](../../SPEC.md) §3.2 | DDL uses `SERIAL`, `JSONB`, `TIMESTAMPTZ`, `BIGSERIAL` — all Postgres |
| [OPERATIONS.md](../../OPERATIONS.md) §2.4 | Requires the DuckDB→Postgres migration to be a scripted step |

🔴 FRAGILE — a rework risk, and the first real decision of the project. It was the one open
decision that P0.4 could not start without.

## Decision

**PostgreSQL 16+ in every environment and every phase**, with TimescaleDB as an available
extension (see the note below and ADR-0008). Write the DDL exactly as SPEC.md §3.2 has it.
Never migrate.

## Consequences

- There is **no SQLite/DuckDB variant of this schema and no migration to write.**
- The DDL may use `SERIAL`, `JSONB`, `TIMESTAMPTZ`, plpgsql triggers, partial unique indexes
  and `btree_gist` exclusion constraints freely. Several correctness guarantees in
  [08_DATA_CONTRACTS.md](../08_DATA_CONTRACTS.md) depend on exactly those — the no-overlapping-
  identifiers exclusion constraint (§2.11), the `forbid_update()` trigger (§2.14) and the
  partial unique index that makes "the current version" a single guaranteed row.
- Local and production run the same engine, which removes an entire class of "works on my
  machine" bug.
- The cost is day-one friction: Postgres must exist before a single test runs. ADR-0008
  records how that friction was actually resolved.
- **Supersedes:** [06_RISK_REGISTER.md](../06_RISK_REGISTER.md) §3.15, which rated
  "DuckDB/SQLite for the local phases" 🟢 SOLID, and
  [08_DATA_CONTRACTS.md](../08_DATA_CONTRACTS.md) §1.2's claim that the same schema runs on
  SQLite/DuckDB in P0–P8. Both are withdrawn.

## Alternatives rejected

**Approach 2 — DuckDB now, Postgres at P9.**
*For:* zero install; it is a Python package and a file. Genuinely excellent for the analytical
queries this project makes; DATA_FOUNDATION.md §4.1 recommends it.
*Against:* the DDL gets written twice and the migration once, and the migration must be
*tested*, which means owning a second code path for the life of the project. Every
Postgres-specific type in SPEC's DDL needs a DuckDB equivalent chosen now and re-chosen later.
The multi-user concurrency story is weak, and multi-user is mandated from day one (ADR-0007).

**Approach 3 — SQLAlchemy with an engine-agnostic schema.**
*For:* defers the decision; swap by changing a connection string.
*Against:* this is the trap. "Engine-agnostic" means no `JSONB`, no Timescale hypertables and
no Postgres-specific constraints — you give up the features you chose Postgres for, and you
still test against two engines. It costs more than either commitment.

**Why 1 won:** the two hours of Postgres setup buys back more than that on the first migration
you do not have to write. Recorded here so that when it feels slow in week one you can re-read
why.

## Note on TimescaleDB

[docs/02_INFRASTRUCTURE.md](../02_INFRASTRUCTURE.md) §3.1: not needed on day one, but starting
from the Timescale image "costs nothing and removes a future decision"; convert
`price_history`, `macro_observations`, `indicators` and `ml_features` to hypertables around
P6. That reasoning assumed a local Docker image. It no longer holds unchanged — see
[ADR-0008](0008-neon-managed-postgres.md), where TimescaleDB is recorded as a **live question
for P6, not a settled one**.

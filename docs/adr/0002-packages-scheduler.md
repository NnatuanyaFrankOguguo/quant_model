# ADR-0002 — `/packages/scheduler` added to the monorepo

- **Status:** ACCEPTED
- **Date:** 2026-08-30
- **Closes:** TG8
- **Source:** [docs/01_ARCHITECTURE.md](../01_ARCHITECTURE.md) §9 ADR-0002. The Context /
  Decision / Consequence text below is copied verbatim from there; only the Alternatives
  section and the operating note are expanded, from
  [docs/10_PRE_BUILD_CORRECTIONS.md](../10_PRE_BUILD_CORRECTIONS.md) §5.6.

## Context

[SPEC.md](../../SPEC.md) §3.1's layout has no scheduler, though
[DATA_FOUNDATION.md](../../DATA_FOUNDATION.md) §3.5 names APScheduler and
[OPERATIONS.md](../../OPERATIONS.md) §2.3 requires connector health tracking. This is **TG8**.

## Decision

Add it. A connector nobody runs fails silently, and health rows need an owner.

## Consequences

- One more package; job scheduling never leaks into connector code.
- `packages/scheduler` is one of the four packages created in P0.2 (`common`, `compliance`,
  `ingestion`, `scheduler`) per [docs/10](../10_PRE_BUILD_CORRECTIONS.md) §6.1. The other ten
  package names from SPEC.md §3.1 are a reserved namespace, created on first use.
- **Operating note, from [docs/10](../10_PRE_BUILD_CORRECTIONS.md) §5.6:** APScheduler is
  in-process and nothing in the document set said what starts it on Windows. Register
  `pythonw.exe -m packages.scheduler.run` as a Scheduled Task at logon with "wake the
  computer" ticked; `max_instances=1, coalesce=True, misfire_grace_time=3600`, plus a Postgres
  advisory lock per connector (advisory locks die with the connection, so a killed process
  self-heals); `ON CONFLICT DO NOTHING` for idempotency; and a **retry ceiling of 3** — P4.8
  specifies exponential backoff with no ceiling, which is the runaway-spend loop the LLM cost
  controls exist to prevent.
- **Non-request surfaces are the scheduler's compliance obligation, not an afterthought**
  ([docs/10](../10_PRE_BUILD_CORRECTIONS.md) §4.1): every outbound message is composed inside
  a `DeliveryContext(principal_id)` that resolves mode through the same
  `resolve_mode_for_principal(principal)` the middleware calls. No job may branch on mode
  itself. A composer that reads `signals` without a `DeliveryContext` in scope is a build
  failure.

## Alternatives rejected

- **Cron / Windows Task Scheduler invoking one script per connector, with no scheduler
  package.** Rejected: the connector-health rows in `connector_runs` then have no owner, and
  the "a job that stopped running writes no row, which is indistinguishable from healthy"
  failure ([docs/10](../10_PRE_BUILD_CORRECTIONS.md) §5.3) has nowhere to live.
- **Scheduling logic inside each connector.** Rejected: it is the same "one router with an
  `if`" pattern the compliance design forbids elsewhere — scheduling policy smeared across
  thirteen call sites, none of which can be tested as a unit.
- **A hosted job runner (Temporal, Prefect, cloud cron).** Rejected for P0–P8: an external
  dependency and a bill for a system whose scheduler is off in local development anyway
  ([docs/02](../02_INFRASTRUCTURE.md) §1.2). Reconsider at P9 when there is a host.

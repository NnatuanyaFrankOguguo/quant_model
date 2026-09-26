# ADR-0005 — FastAPI stands up in P0, not P9

- **Status:** ACCEPTED
- **Date:** 2026-08-30
- **Also known as:** AD-2
- **Source:** [docs/01_ARCHITECTURE.md](../01_ARCHITECTURE.md) §9 ADR-0005 — copied verbatim,
  with the API-versioning note added from
  [docs/10_PRE_BUILD_CORRECTIONS.md](../10_PRE_BUILD_CORRECTIONS.md) §6.5.

## Context

[SPEC.md](../../SPEC.md) §4.2 places the API at T16 (v1.0). But T15 is marked "front-loaded,
all versions" with files `/compliance`, `/api`, and [SPEC.md](../../SPEC.md) §4.1 requires mode
to be server-derived. A Streamlit-only application has no server from which to derive it.

## Decision

The API exists from P0. **This is a deliberate, documented deviation from SPEC.md's literal
task ordering**, not an oversight.

## Consequences

- P0 is longer and produces nothing visible. Every later surface is a client of a gate that
  already works.
- This is one of the three places where `docs/` deliberately overrides SPEC.md's ordering (with
  [ADR-0001](0001-storage-engine-postgresql.md) and [ADR-0002](0002-packages-scheduler.md)).
  Per [CLAUDE.md](../../CLAUDE.md), an accepted ADR **is the answer** to such a conflict, not a
  reason to stop and ask.

**API versioning, added 2026-08-30** ([docs/10](../10_PRE_BUILD_CORRECTIONS.md) §6.5):
[PROJECT_CONTEXT.md](../../PROJECT_CONTEXT.md) §9.4 requires the API be *"versioned from the
first release"* and [05_USER_STORIES.md](../05_USER_STORIES.md) names its absence an
abandonment trigger. Every path in [08_DATA_CONTRACTS.md](../08_DATA_CONTRACTS.md) §7 is
therefore `/v1/public/*` and `/v1/personal/*`. **The P0 endpoints are `/health`,
`/v1/public/ping` and `/v1/personal/ping`** — not the unversioned paths still shown in
[docs/03](../03_ROADMAP_PART1_PHASES_0-6.md) §P0.5 and its test checkpoint. It is free today
and a breaking change later; docs/10 calls it "the cheapest high-value fix in this audit".

## Alternatives rejected

- **Streamlit-only v0.1, API at v1.0 as SPEC.md orders it.** Rejected: there is no server from
  which to derive `mode`, so the single hard rule with real legal risk — *never expose
  personal-mode output to a non-family user* — would be enforced by client-side discipline
  until P9. Every endpoint built before the gate exists would then have to be re-hosted behind
  it.
- **A thin auth shim now, the real API at P9.** Rejected: the shim *is* the API's hard part
  (principal resolution, mode derivation, response-type assertion, audit). Building it twice
  costs more than building it once.

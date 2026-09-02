# ADR-0007 — Multi-user from day one

- **Status:** ACCEPTED
- **Date:** 2026-08-30
- **Also known as:** AD-4
- **Source:** [docs/01_ARCHITECTURE.md](../01_ARCHITECTURE.md) §9 ADR-0007 — copied verbatim,
  with the seeding and non-deferrable notes added from
  [docs/02_INFRASTRUCTURE.md](../02_INFRASTRUCTURE.md) §2.4 and
  [docs/10_PRE_BUILD_CORRECTIONS.md](../10_PRE_BUILD_CORRECTIONS.md) §2.15.

## Context

Today the system has one user. [CLAUDE.md](../../CLAUDE.md) names assuming that as *the
expensive shortcut to avoid*: "a single-user trading layer is a full rewrite to open up."
[PROJECT_CONTEXT.md](../../PROJECT_CONTEXT.md) §4 and [SPEC.md](../../SPEC.md) §1.2 say the
same. The distinction that settles it is in the documents themselves: *adding an owner column
to eleven tables later is a data **migration**; adding a principal concept to logic that never
had one is a **redesign**.*

## Decision

Everything user-scoped is keyed by principal from the first migration. Position sizing takes
equity as a parameter.

## Consequences

- Slightly more schema and signature noise while there is one user. **No rewrite when there
  are three.**
- Portfolios, watchlists, risk limits, alerts, spend caps and audit rows are all keyed by
  principal. `alerts` carries `principal_id NOT NULL` (SPEC.md's version had no owner column
  at all, so every alert belonged to everyone); `audit_log` carries `principal_id` plus a
  denormalised `principal_label` so history survives a rename.
- **`scripts/seed_dev.py` creates three principals from day one**
  ([docs/02](../02_INFRASTRUCTURE.md) §2.4): an owner with `personal_tier=true`, a family
  member with `personal_tier=true`, and a public principal with `personal_tier=false`. That is
  the cheapest possible guard against single-user assumptions creeping in, because every manual
  test naturally exercises more than one.
- **This is on the do-not-defer list** ([docs/10](../10_PRE_BUILD_CORRECTIONS.md) §2.15). P0
  defers ~35 empty tables, but `principal_id` on every user-scoped table is not deferrable,
  because each of those is a redesign rather than a migration later.

## Alternatives rejected

**Single-user now, multi-user at P9.** Named in [CLAUDE.md](../../CLAUDE.md) as the expensive
shortcut. It is also the P0.5 approach-3 shortcut rejected in
[ADR-0003](0003-auth-hashed-bearer-tokens.md): with no `principals` table, nothing downstream
is keyed by it, and P9 becomes a redesign rather than a swap.

**A single "owner" flag on rows instead of a principal FK.** Rejected: entitlements,
`licence_status` and the personal/public mode gate all resolve *from the principal*. A boolean
cannot express "family member with the personal tier but no execution entitlement", which is
the exact case the access model requires.

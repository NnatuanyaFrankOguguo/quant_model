# ADR-0003 — Authentication: hashed bearer tokens in Postgres now, a hosted IdP at P9

- **Status:** ACCEPTED
- **Date:** 2026-08-30 (closed during the pre-build audit)
- **Partially closes:** TG3 — the *mechanism* is now specified; the second-factor half is
  still open, see below.
- **Sources:** [docs/01_ARCHITECTURE.md](../01_ARCHITECTURE.md) §9 ADR-0003 (copied);
  [docs/03_ROADMAP_PART1_PHASES_0-6.md](../03_ROADMAP_PART1_PHASES_0-6.md) §P0.5 (the three
  approaches); [docs/10_PRE_BUILD_CORRECTIONS.md](../10_PRE_BUILD_CORRECTIONS.md) §2.4 (the
  `principal_tokens` DDL)

## Context

P0.5 — the FastAPI skeleton with the mode gate — cannot be written while the credential
mechanism is open, and the recommendation had no competing option worth deliberating.
Authentication is **TG3**: it has no task in the source spec and it is the piece most likely to
be done badly under time pressure.

Note that [08_DATA_CONTRACTS.md](../08_DATA_CONTRACTS.md) §2.0's table 43 is named `sessions`,
which is misleading: it is a hashed bearer token, not a session, and naming it `sessions`
invites cookie semantics this design does not want. The table is `principal_tokens`.

## Decision

**A token table in Postgres now; a hosted identity provider at P9.** A `principals` table, a
SHA-256-hashed token, a `Bearer` header, checked by middleware. The DDL is in
[docs/10](../10_PRE_BUILD_CORRECTIONS.md) §2.4 and the mint path is `scripts/mint_token.py`.

The `principals` table and the middleware contract are what matter; the credential mechanism
on top is swappable **because** the contract exists.

## Consequences

- Roughly half a day of work, no third party, and it works identically for Streamlit, the
  Telegram bot and the later Next.js frontend.
- Password reset, session expiry and rotation are ours to own until P9.
- Mode is derived from the resolved principal's entitlements plus `licence_status`, never from
  the request (SPEC.md §4.1). Anonymous resolves to `public`.
- **Still open, deliberately:** [SPEC.md](../../SPEC.md) §1.2 mechanism 1 requires *"the owner
  principal **+ a second factor**"*, and the P0 design has none. Either restore it on
  `/v1/personal/*` or record its deferral to P9's identity provider as a future ADR — but do
  not let a stated requirement lapse silently. This is the open remainder of TG3, and it is
  tracked in [docs/REVIEW_CADENCE.md](../REVIEW_CADENCE.md).

## Alternatives rejected

**2 — A hosted identity provider now (Auth0, Clerk, Supabase Auth).**
*For:* sessions, resets, MFA and social login solved properly; it is the right answer at P9.
*Against:* an external dependency, a config surface and a bill, for a system with two users who
are both the owner. It also couples the local dev loop to a network service.

**3 — No auth in P0; a hardcoded single principal.**
*For:* fastest to something working.
*Against:* precisely the shortcut [CLAUDE.md](../../CLAUDE.md) names as the expensive one. The
`principals` table would not exist, so nothing downstream would be keyed by it, and P9 becomes
a redesign rather than a swap. See [ADR-0007](0007-multi-user-from-day-one.md).

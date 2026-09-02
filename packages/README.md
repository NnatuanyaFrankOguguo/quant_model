# `/packages` — the Python packages

`SPEC.md` §3.1 lists fourteen packages. **P0 creates four of them**, per
[docs/10_PRE_BUILD_CORRECTIONS.md](../docs/10_PRE_BUILD_CORRECTIONS.md) §6.1: creating ten empty
directories is ceremony, and the argument for building P0 first was never about the *existence*
of empty things — it was about concepts that cannot be retrofitted.

## Created in P0

| Package | Holds | Owned since |
|---|---|---|
| `common` | config, database session, models, timezone discipline, dated system config | P0 |
| `compliance` | the mode gate, auth, response-type registry, banned-phrase scanner (T15) | P0 |
| `ingestion` | connector base class and the source connectors | P0 (empty until P1) |
| `scheduler` | the job runner and `connector_runs` health (ADR-0002, closes TG8) | P0 (empty until P1) |

## Reserved — created by the phase that first writes to it

`normalize` (P2) · `valuation` (P2) · `indicators` (P6) · `ml` (P8) · `backtest` (P7) ·
`agents` (P9) · `sentiment` (P5) · `alerts` (P10) · `portfolio` (P10) · `execution` (P13)

These names are reserved, not optional. When a phase needs one, create it here with the same
name — do not invent a synonym, and do not put its code somewhere else because the directory
was missing.

## The one rule with teeth

**Import direction is one-way.** `apps/*` and `services/api` may import from `packages/*`.
`packages/*` must **never** import from `apps/*` or `services/*` (ADR-0006). This is what keeps
the Streamlit surface disposable when Next.js replaces it at P9. `import-linter` enforces it in
CI from the phase where both directories have real code in them.

"""Normalization: source labels → the canonical chart of accounts, periods → statements. P2.

Reserved in `packages/README.md` for P2; first written 2026-09-12. Three concerns:

* `periods` — what period a fact describes. The fiscal year and the period type (`FY`, `Q1`,
  `H1`, `YTD`) are derived from the period's own dates and the company's fiscal-year-end
  month, never from a filing's reporting context.
* `chart` — the versioned vocabulary and the source-label mappings, loaded from the tables
  migration 0011 seeds, with alternates resolved by priority.
* `statements` — the versioned writer: a period first reported is version 1; a period
  re-reported unchanged is the same version; a period re-reported with a different figure
  is a restatement, a new version, with the old one's `superseded_by` set.
"""

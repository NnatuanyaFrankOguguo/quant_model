# CLAUDE.md

## Read first

- **[PROJECT_CONTEXT.md](PROJECT_CONTEXT.md)** — the *why*: what this is, who it serves, the
  B2B/acquisition thesis, and the non-negotiable rules. Read before proposing architecture,
  data models, or user-facing copy.
- **[SPEC.md](SPEC.md)** — the *what and how*: unified build specification (Doc A + Doc B
  merged). Version roadmap v0.1→v2.5, monorepo layout, DDL, the compliance mode-gate design,
  the backtest gate, and the T1–T21 task decomposition with acceptance criteria. **Load its
  §4.1 invariants on every build task.**
- **[DATA_FOUNDATION.md](DATA_FOUNDATION.md)** — "Doc A": verified data-source inventory
  (NGX, EDGAR, FRED, NBS, CBN, DMO), the PDF→LLM extraction pipeline, the base schema, and
  the ISA 2025 / NDPA / redistribution research. SPEC.md's "per Doc A" references point here.
- **[OPERATIONS.md](OPERATIONS.md)** — correctness gaps the other docs miss (corporate
  actions, trading calendar, FX, identity history), plus backup/DR, freshness, connector
  health, secrets, and long-term hygiene.
- **[TEAM_BRIEF.md](TEAM_BRIEF.md)** — onboarding: the vision, the manual-work task list with
  roles and buy-vs-build alternatives, the bottlenecks and how to beat them, and the stage
  gates that define success.

### The executable plan — `docs/` (read before starting any phase)

The five documents above are the *source material*. The ten in `docs/` are the *plan built
from them*, and they are what you actually work from.

- **[docs/00_START_HERE.md](docs/00_START_HERE.md)** — §5 the canonical P0–P13 phase map,
  §6 the live progress tracker (**which phase we are actually in**), §8 the architecture
  decisions already taken, §9 the TG gap register. Start here every session.
- **[docs/10_PRE_BUILD_CORRECTIONS.md](docs/10_PRE_BUILD_CORRECTIONS.md)** — corrections
  from the pre-build audit of 2026-08-30. **Highest precedence in the set** (see below).
- The other eight — [01 architecture](docs/01_ARCHITECTURE.md),
  [02 infrastructure](docs/02_INFRASTRUCTURE.md),
  [03 roadmap P0–P6](docs/03_ROADMAP_PART1_PHASES_0-6.md),
  [04 roadmap P7–P13](docs/04_ROADMAP_PART2_PHASES_7-13.md),
  [05 user stories](docs/05_USER_STORIES.md), [06 risks](docs/06_RISK_REGISTER.md),
  [07 tests](docs/07_TEST_STRATEGY.md), [08 data contracts](docs/08_DATA_CONTRACTS.md),
  [09 glossary](docs/09_GLOSSARY.md) — are indexed from `00`.

**Precedence when documents disagree:** `docs/10_PRE_BUILD_CORRECTIONS` → ADRs in
[docs/01_ARCHITECTURE.md](docs/01_ARCHITECTURE.md) §9 → PROJECT_CONTEXT → the rest of
`docs/` → SPEC → DATA_FOUNDATION → OPERATIONS.

Two consequences worth stating outright, because both are easy to get wrong:

- **`docs/` deliberately deviates from SPEC.md's task ordering, and the deviations win.**
  ADR-0001 puts **PostgreSQL** in P0 (not DuckDB), ADR-0005 stands **FastAPI up in P0**
  (SPEC.md §4.2 places it at T16/v1.0), ADR-0002 adds `/packages/scheduler`. A Streamlit-only
  v0.1 has no server to derive `mode` from, which is why the API cannot wait.
- **"Stop and ask on a conflict with SPEC.md" means *check for an ADR first*.** An accepted
  ADR is the answer, not a reason to halt. Only conflicts with no ADR need asking.

Doc A's "never generate recommendations" rules are scoped to the **public data tier** only;
see the editorial headers in SPEC.md and DATA_FOUNDATION.md.

**The standard task loop:** read the one phase task from `docs/03` or `docs/04` → read the
module/table contract from `docs/08` (as corrected by `docs/10`) → load the invariants below
→ branch → implement with tests → PR, where the task's acceptance criteria are the checklist
→ CI green before merge. One task, one PR. Do not load more of the plan than the task needs.

## One-line summary

A centralized financial data hub for Nigerian and US listed companies: statements, history,
macro backdrop, news, and user-driven valuation tools. The hard, valuable part is turning
Nigerian financial PDFs into clean, queryable, provenance-tracked data.

## Access model — build scope ≠ access control

**Build everything to public standard. Restrict who can log in, not what it can do.**

|  | Build scope | Who can reach it |
|---|---|---|
| Now | Everything — public-grade, general-purpose, **multi-user** | Owner + family only |
| After the SEC licence | Unchanged | + the public |

Today the system **may** say BUY/SELL, output price targets, and surface ML model conviction
— it is our own capital. Do not add public-facing disclaimers or strip advice features on the
assumption this is a regulated product; it is not. Restricted access is a staging decision,
not a ceiling on the product.

The advice tier opens to the public when the owner obtains SEC registration (both the adviser
and fund-manager categories are intended). Gate on **entitlements + `licence_status`** so that
day is a config + disclosure change, never a rewrite.

**The expensive shortcut to avoid: never assume a single user.** Portfolios, watchlists, risk
limits, alerts, spend caps, and audit rows are keyed by principal; position sizing takes
equity as a per-user parameter. A single-user trading layer is a full rewrite to open up.
See PROJECT_CONTEXT.md §4 and SPEC.md §1.2.

## Hard rules (full list in PROJECT_CONTEXT.md §10)

- **Advice is mode-gated, not absent** — free in personal mode, gated in public mode until
  licensed. Gate with `MODE=personal|public`, never two codebases.
- **Never expose personal-mode output to a non-family user** pre-licence. Access control in
  code, not policy. This is the only line with real legal risk.
- **Show the work in every mode** — even a BUY carries its assumptions, inputs, and as-of
  dates.
- **Provenance on every figure** — source document, page, as-of date. Non-negotiable.
- **No silent overwrites** — corrections are versioned, attributed, and noted.
- **Staleness is visible** — every series shows its as-of date and flags when overdue.
- **Data licensing before ingestion** — confirm redistribution rights before a source enters
  the dataset. (Distinct from the SEC licence above.)
- **Data layer has priority** when time is scarce.

Build-time invariants (SPEC.md §4.1) — load on every coding task:

- **Backtest gate before capital** — no signal trades without a passing recorded
  `backtest_run` (DSR, net-of-cost after the full NGX cost stack, beats logreg + buy-and-hold).
- **Never infer missing financial data** — absent line items are null, never estimated.
- **Point-in-time only** — features respect `known_as_of`; restated financials use the
  version known at the decision date.
- **Mode is server-derived** — never trust a client-supplied `mode`. Default `public`.
- **One task, one PR**, tests required.

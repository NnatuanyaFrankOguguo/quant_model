# 10 — Pre-Build Corrections

> **Audit date: 2026-08-30. Status of the build: P0 not started, no code written.**
>
> This document is the output of a seven-reviewer audit run across all sixteen planning
> documents immediately before P0. It exists because the audit found defects that would have
> stopped the first migration from running, made two gates unfalsifiable, and left four
> compliance bypass paths open.
>
> **Precedence: this file wins.** Where it corrects another document, it is authoritative and
> the other document is stale until amended. It ranks above the ADRs in
> [01_ARCHITECTURE](01_ARCHITECTURE.md) §9 only for the items listed here; everything not
> mentioned is unchanged and the normal precedence in [CLAUDE.md](../CLAUDE.md) applies.
>
> **This is a work list, not a critique.** Every item is either applied already (marked
> ✅ APPLIED) or is a specific edit with the exact text to write (marked 🔧 TO APPLY). Items
> needing the owner's judgement rather than an editor are in §8 and are marked ⏸️ DECIDE.

---

## Table of contents

- [0. What the audit found, in one page](#0-what-the-audit-found-in-one-page)
- [1. Machine prerequisites — blocking, checked on this machine](#1-machine-prerequisites--blocking-checked-on-this-machine)
- [2. Schema corrections — P0.4 cannot run without these](#2-schema-corrections--p04-cannot-run-without-these)
- [3. The numbers that were never written down](#3-the-numbers-that-were-never-written-down)
- [4. Compliance — the four bypass paths the five mechanisms do not cover](#4-compliance--the-four-bypass-paths-the-five-mechanisms-do-not-cover)
- [5. Durability — the moat can currently be destroyed](#5-durability--the-moat-can-currently-be-destroyed)
- [6. New and changed tasks](#6-new-and-changed-tasks)
- [6.6 Valuation multiples are absent](#66-valuation-multiples-are-absent-from-the-entire-document-set)
- [6.7 The entity graph](#67-the-entity-graph--the-bloomberg-terminal-panels-and-which-of-them-are-nearly-free)
- [7. Document-set hygiene](#7-document-set-hygiene)
- [8. Decisions only the owner can make](#8-decisions-only-the-owner-can-make)
- [9. What the audit found genuinely sound](#9-what-the-audit-found-genuinely-sound)

---

## 0. What the audit found, in one page

The plan is unusually good. The reasoning in `06_RISK_REGISTER` §6, the type-level compliance
design in `01_ARCHITECTURE` §3, and the honesty in `SPEC.md` Part 2 are better than most
funded projects produce. The defects are concentrated and they cluster into one pattern:

> **Gaps discovered while writing `02_INFRASTRUCTURE`, `07_TEST_STRATEGY` and
> `08_DATA_CONTRACTS` were recorded in those documents' own "gaps surfaced" appendices and
> never written back into `03`/`04`, which are the only documents containing build tasks.**

Work that nobody scheduled does not get done. That single mechanism accounts for seven of the
twenty gaps being unscheduled, for object storage being required by P3 and owned by nobody,
and for the backup drill having a cadence but no task.

The five findings that would have cost the most:

| # | Finding | Cost if not fixed |
|---|---|---|
| 1 | **Six foreign keys point at tables that have no DDL anywhere.** `alembic upgrade head` fails on the first run. | P0.4 stops on day one; an agent invents the missing tables, and the inventions become the schema. |
| 2 | **`period_type` and `statement_type` appear zero times in `08_DATA_CONTRACTS`.** | MTN's Q4-2024 and FY-2024 revenue collide on one key. Every ratio, growth feature and backtest label built on it is silently wrong, recoverable only by re-extraction. |
| 3 | **`backtest_runs.k_trials` is caller-supplied.** | The backtest gate — the mechanism protecting real capital — passes by writing a small number. |
| 4 | **Scheduled pushes (the 07:00 brief, alerts) have no request, so no mode gate runs.** | A system-generated BUY reaches a non-family principal with no middleware, no type check, and no audit row. This is the one line with real legal risk. |
| 5 | **`rclone sync` on `data/documents`** in `02 §8`'s backup script. | Local corruption propagates off-site and deletes the only copy of PDFs whose source URLs have rotated. `sync` deletes to match; the dumps correctly use `copy`. |

---

## 1. Machine prerequisites — blocking, checked on this machine

Checked 2026-08-30 on the build machine. No document verifies these, and two of them stop P0
before the first commit.

| Prerequisite | Docs require | Actual | Action |
|---|---|---|---|
| **Python** | `>=3.11,<3.13`, pinned 3.12 (`02 §15B`, `02 §1.3`) | **3.14.3 only** | 🔧 `uv python install 3.12` then `uv python pin 3.12`. The pin is not cosmetic — `pandas-ta-classic`, TA-Lib and the boosted-tree stack are verified against 3.11/3.12 in `02 §2`. |
| **Git repo** | P0.1 task 1 | **not initialised** | 🔧 P0.1 as written is correct; it is genuinely task one. |
| **uv** | `02 §2.1`; `uv sync --frozen` is a hard rule in `02 §1.3` | **not installed** | 🔧 `winget install astral-sh.uv` |
| **PostgreSQL client** | P0 checks 1, 14, 16 run `psql`, `createdb`, `dropdb`, `pg_dump` | **not on PATH** | 🔧 Either `winget install PostgreSQL.PostgreSQL.16 --override "/client-only"`, or rewrite every such command as `docker compose exec -T db psql -U quant …`. Pick one and use it consistently — the docs currently assume the client exists while recommending Docker. |
| **Docker** | `02 §2.2` compose | ✅ 29.6.1 | none |
| **Node** | P9 frontend — **never mentioned in any document** | ✅ v24.14.0 | 🔧 add to P9 entry criteria so it is not discovered at P9. |
| **gpg, rclone** | `02 §8` backup chain, described as "ten minutes now" | **neither installed** | See §5 — the ten-minute claim is wrong; it is half a day and it needs a Backblaze/R2 account. |
| **BitLocker** | `OPERATIONS.md` §2.5 names an unencrypted laptop in its threat model | **no task anywhere enables it** | 🔧 `manage-bde -on C: -RecoveryPassword`, recovery key into the password manager **and** printed. A key stored only on the encrypted drive is not a key. |

**Also blocking, and cheap:** `pyproject.toml` in `02 §15B` has **no `[build-system]` and no
package discovery**. With top-level `apps/`, `packages/`, `services/`, `db/`, `tests/`,
`scripts/`, an editable install fails with *"Multiple top-level packages discovered in a
flat-layout"*. Add:

```toml
[build-system]
requires = ["setuptools>=69"]
build-backend = "setuptools.build_meta"

[tool.setuptools]
packages = ["packages", "services"]
```

And P0.2's scaffold loop creates `packages/<name>/__init__.py` but never `packages/__init__.py`
or `services/__init__.py`, which `[tool.importlinter] root_package = "packages"` requires.

---

## 2. Schema corrections — ✅ APPLIED TO THE CONTRACT 2026-08-30

> **All of §2 is now in [08_DATA_CONTRACTS](08_DATA_CONTRACTS.md) — build from there, not from
> here.** The missing tables are §2.15, the entity graph and share count are §2.14, the
> structural constraints are §2.16, and the fixes to `statement_line_items`, `price_history`,
> `adjustment_factors`, `indicators` and `ml_features` are in place in §2.1–2.7. Verified: **52
> tables defined, 21 foreign-key targets, zero unresolved.** The first `alembic upgrade head`
> can now succeed.
>
> The text below is kept as the record of what was wrong and why it mattered.

`03` P0.4 says *"Exact column definitions are in `08_DATA_CONTRACTS.md` §2. Do not invent them
here; that document is the contract."* §2.0 maps **49 tables**; §2 gives DDL for **33**. The
instruction and the document contradict each other, and an agent told not to invent will
invent anyway.

**First, a precedence line to add to `08_DATA_CONTRACTS.md` §1.1** 🔧

> Where `SPEC.md` §3.2 and this document define the same table differently, **this document
> wins**; `SPEC.md` §3.2 is superseded for every table restated here. Where a table is mapped
> in §2.0 but has no DDL below, its DDL is in
> [10_PRE_BUILD_CORRECTIONS](10_PRE_BUILD_CORRECTIONS.md) §2 or is written by the phase that
> first creates it — never invented at the point of use.

### 2.1 The six broken foreign keys

These reference tables that exist in no document. The first migration fails on them.

```
companies.industry_id             → industries(id)      -- no such table
securities.exchange_id            → exchanges(id)       -- no such table
trading_calendar.exchange_id      → exchanges(id)       -- no such table
statement_line_items.statement_id → statements(id)      -- no such table
signals.ml_model_id               → ml_models(id)       -- SPEC only, not in §2
alert_deliveries.alert_id         → alerts(id)          -- SPEC only, not in §2
```

### 2.2 An invalid foreign key — Postgres rejects it outright

`08 §2.3` line ~420 declares `canonical_key TEXT NOT NULL REFERENCES chart_of_accounts(canonical_key)`
against a composite primary key `(canonical_key, chart_version)` at line ~477. Postgres:
`ERROR: there is no unique constraint matching given keys for referenced table`.

The tempting fix — dropping the FK — silently permits line items whose canonical key exists in
no chart version, defeating TG7 entirely. The correct fix makes `chart_version` load-bearing:

```sql
  canonical_key TEXT NOT NULL,
  chart_version TEXT NOT NULL,
  FOREIGN KEY (canonical_key, chart_version)
    REFERENCES chart_of_accounts (canonical_key, chart_version),
```

### 2.3 The missing `statements` table — the most expensive omission

`period_type` and `statement_type` appear **zero times** in `08_DATA_CONTRACTS.md`. Without
`period_type`, MTN's Q4-2024 revenue and FY-2024 revenue both arrive as `period_end =
2024-12-31` on the same `canonical_key`. They are different numbers. `period_start` is
nullable and Nigerian quarterly filings routinely omit it, so nothing distinguishes them. Every
ratio, every year-on-year growth feature and every backtest label built on that key is wrong,
and the only recovery is re-extraction — the months-long cost this whole audit exists to avoid.
`OPERATIONS.md` §1.5's fiscal-alignment columns also have no home, making the ±92-day
comparability rule unimplementable.

```sql
CREATE TABLE statements (
  id                      BIGSERIAL PRIMARY KEY,
  filing_id               BIGINT REFERENCES filings(id),
  company_id              INT NOT NULL REFERENCES companies(id),
  statement_type          TEXT NOT NULL,   -- 'income'|'balance'|'cashflow'|'equity'
  period_type             TEXT NOT NULL,   -- 'FY'|'H1'|'Q1'|'Q2'|'Q3'|'Q4'|'YTD'
  period_start            DATE,
  period_end              DATE NOT NULL,
  fiscal_year             INT NOT NULL,    -- OPERATIONS §1.5
  calendar_year           INT NOT NULL,
  period_label            TEXT NOT NULL,   -- 'FY2024', 'Q3-2025', as the company labels it
  presentation_currency   CHAR(3) NOT NULL,
  presentation_multiplier INT NOT NULL DEFAULT 1,   -- the document header's scale
  is_audited              BOOLEAN NOT NULL DEFAULT false,
  is_consolidated         BOOLEAN NOT NULL DEFAULT true,  -- NG filings carry both; never mix
  statement_template      TEXT NOT NULL,   -- see 2.7; belongs here, not on companies
  chart_version           TEXT NOT NULL,
  version                 INT NOT NULL DEFAULT 1,
  superseded_by           BIGINT REFERENCES statements(id),
  restatement_flag        BOOLEAN NOT NULL DEFAULT false,
  known_as_of             DATE NOT NULL,
  source_document_id      BIGINT NOT NULL REFERENCES source_documents(id),
  created_at              TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (company_id, statement_type, period_type, period_end, is_consolidated, version)
);
```

`period_type` must also join `statement_line_items`' point-in-time index, or the `DISTINCT ON`
in §2.9 below stays broken.

### 2.4 The other missing P0 tables

```sql
CREATE TABLE exchanges (
  id              SERIAL PRIMARY KEY,
  code            TEXT NOT NULL UNIQUE,   -- 'NGX','NASDAQ','NYSE'
  name            TEXT NOT NULL,
  country         CHAR(2) NOT NULL,
  timezone        TEXT NOT NULL,          -- 'Africa/Lagos' — TG21 needs this
  settlement_days SMALLINT NOT NULL       -- NGX 3; never hardcode T+3
);

CREATE TABLE industries (
  id                 SERIAL PRIMARY KEY,
  scheme             TEXT NOT NULL,       -- 'ngx_sector'|'gics'|'sic'
  code               TEXT NOT NULL,
  name               TEXT NOT NULL,
  statement_template TEXT NOT NULL,
  UNIQUE (scheme, code)
);

-- TG20 + the licence_status half of the mode gate. Dated, because the NGX movement
-- rule and the Nigerian CGT thresholds BOTH moved during planning. A backtest over
-- 2024 must read the 2024 value.
CREATE TABLE system_config (
  key            TEXT NOT NULL,
  value          JSONB NOT NULL,
  effective_from DATE NOT NULL,
  effective_to   DATE,                    -- NULL = currently in force
  set_by         TEXT NOT NULL,
  reason         TEXT NOT NULL,
  source_url     TEXT,
  adr_ref        TEXT,
  created_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
  PRIMARY KEY (key, effective_from)
);

-- TG3. `sessions` in §2.0 row 43 is misnamed — the P0 design is a hashed bearer
-- token, not a session. Naming it `sessions` invites cookie semantics nobody wants.
CREATE TABLE principal_tokens (
  id           BIGSERIAL PRIMARY KEY,
  principal_id INT NOT NULL REFERENCES principals(id),
  token_sha256 CHAR(64) NOT NULL UNIQUE,
  label        TEXT NOT NULL,
  created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
  expires_at   TIMESTAMPTZ,
  last_used_at TIMESTAMPTZ,
  revoked_at   TIMESTAMPTZ
);

-- TG11
CREATE TABLE watchlists (
  id           SERIAL PRIMARY KEY,
  principal_id INT NOT NULL REFERENCES principals(id),
  name         TEXT NOT NULL,
  created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (principal_id, name)
);
CREATE TABLE watchlist_items (
  watchlist_id INT NOT NULL REFERENCES watchlists(id) ON DELETE CASCADE,
  security_id  INT NOT NULL REFERENCES securities(id),
  added_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
  PRIMARY KEY (watchlist_id, security_id)
);

CREATE TABLE llm_spend (
  id                BIGSERIAL PRIMARY KEY,
  principal_id      INT REFERENCES principals(id),   -- NULL = scheduler / system
  ts                TIMESTAMPTZ NOT NULL DEFAULT now(),
  job_kind          TEXT NOT NULL,   -- 'extraction'|'sentiment'|'memo'|'tagging'
  model             TEXT NOT NULL,
  prompt_version    TEXT,
  input_tokens      INT NOT NULL,
  output_tokens     INT NOT NULL,
  cost_usd          NUMERIC NOT NULL,
  cache_hit         BOOLEAN NOT NULL DEFAULT false,
  source_document_id BIGINT REFERENCES source_documents(id),
  request_id        UUID
);
CREATE INDEX ON llm_spend (principal_id, ts);
CREATE INDEX ON llm_spend (ts);

-- `01_ARCHITECTURE` §8 lists both as owner-keyed; neither existed anywhere.
CREATE TABLE scenarios (
  id           BIGSERIAL PRIMARY KEY,
  principal_id INT NOT NULL REFERENCES principals(id),
  security_id  INT NOT NULL REFERENCES securities(id),
  name         TEXT NOT NULL,
  assumptions  JSONB NOT NULL,       -- the complete user-supplied input set
  inputs_as_of DATE NOT NULL,        -- US-060: must reproduce identical output
  code_version TEXT NOT NULL,
  created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (principal_id, security_id, name)
);

-- SPEC §2D mandates six limits; entitlements held two. Defaults chosen so ten
-- concurrent max-size positions is fully invested, ten simultaneous stop-outs cost
-- 6%, and the live halt (15%) trips well before the backtest tolerance (25%).
CREATE TABLE risk_limits (
  principal_id               INT PRIMARY KEY REFERENCES principals(id),
  max_position_pct           NUMERIC NOT NULL DEFAULT 0.10,
  max_sector_pct             NUMERIC NOT NULL DEFAULT 0.25,
  max_portfolio_heat_pct     NUMERIC NOT NULL DEFAULT 0.06,
  max_pairwise_corr          NUMERIC NOT NULL DEFAULT 0.70,
  max_daily_loss_pct         NUMERIC NOT NULL DEFAULT 0.03,
  max_drawdown_halt_pct      NUMERIC NOT NULL DEFAULT 0.15,
  kelly_fraction             NUMERIC NOT NULL DEFAULT 0.25,
  min_calibrated_prob_margin NUMERIC NOT NULL DEFAULT 0.05,
  human_confirm_required     BOOLEAN NOT NULL DEFAULT true,
  effective_from             DATE NOT NULL DEFAULT CURRENT_DATE
);
```

`alerts` gains `principal_id INT NOT NULL REFERENCES principals(id)` — `SPEC.md`'s version has
**no owner column at all**, so every alert belongs to everyone. `alert_deliveries`'
`idempotency_hash TEXT UNIQUE` must become `UNIQUE (alert_id, idempotency_hash)`, or the second
recipient of an identical alert is silently suppressed. `audit_log.principal TEXT` becomes
`principal_id INT REFERENCES principals(id)` plus a denormalised `principal_label TEXT`, so the
history survives a rename and can be joined to entitlements.

### 2.5 Point-in-time keys — four one-line changes now, a full backtest re-run later

Each of these tables carries `known_as_of` **outside** its primary key, which means a
recomputation *updates* the row and destroys the earlier vintage — the exact silent overwrite
`01_ARCHITECTURE` §6 forbids, in the tables most responsible for preventing it.

```sql
-- ml_features: a restatement must produce a SECOND row, not overwrite the first
PRIMARY KEY (security_id, date, feature, known_as_of)
-- plus computed_at TIMESTAMPTZ NOT NULL, code_version TEXT NOT NULL

-- price_history: exchanges restate settlement prices; scrapers get re-run
PRIMARY KEY (security_id, date, known_as_of)

-- indicators: add the vintage AND record which price series was used, so US-061's
-- "compute from adjusted, never raw" rule is auditable in data, not only by lint
known_as_of  DATE NOT NULL,
price_series TEXT NOT NULL,      -- 'adjusted'|'raw'
computed_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
code_version TEXT NOT NULL,
PRIMARY KEY (security_id, date, name, param_hash, known_as_of)
```

### 2.6 TG12 — the adjustment leak, which `08` regressed rather than introduced

`OPERATIONS.md` §1.1 already had the correct table, including `known_as_of` and `action_id`.
`08_DATA_CONTRACTS` renamed it `adjustment_factors`, **dropped both columns**, then flagged the
resulting hole as a new gap deferred to P3. The fix predates the gap.

The second half is worse. `price_history.close_adj` + `adj_computed_at` are a *stored* adjusted
price — a single global vintage embedding every action known at `adj_computed_at`, including
actions announced after the decision date. `OPERATIONS.md` §1.1 hard rule 2 requires adjusted
series be *"computed on read, applying only adjustments with `known_as_of <= decision_date`"*,
and `05_USER_STORIES` US-061 then mandates that indicators compute exclusively from `close_adj`.
So the recommended path feeds a non-point-in-time column straight into the ML feature matrix and
through the backtest gate. P7 check 19 (*"adjustment reflects only actions before the decision
date"*) is unsatisfiable against the current DDL.

**Raise TG12 from 🟡 to 🔴, move it from P3 to P0, and adopt OPERATIONS' DDL:**

```sql
CREATE TABLE adjustment_factors (
  id          BIGSERIAL PRIMARY KEY,
  security_id INT  NOT NULL REFERENCES securities(id),
  ex_date     DATE NOT NULL,
  action_id   INT  NOT NULL REFERENCES corporate_actions(id),
  factor      NUMERIC NOT NULL,
  known_as_of DATE NOT NULL,     -- TG12: when this factor became knowable
  UNIQUE (security_id, ex_date, action_id, known_as_of)
);
-- price_history: DROP close_adj, DROP adj_computed_at.
-- Adjusted prices come from a function, never a column:
--   adjusted_close(security_id, date, decision_date)
-- A call without decision_date is a TypeError, not a default.
```

### 2.7 Insurers break the statement-template enum

`companies.statement_template` allows `'financial' | 'non_financial'`. NGX lists insurers
(AIICO, Custodian, NEM) whose statements are neither — gross premium written, net claims
incurred, technical reserves, no "gross earnings". `TEAM_BRIEF`'s warning *"a schema built on
MTN will not survive a bank"* applies a second time, and the enum has no room for it.

🔧 Widen to `'non_financial'|'bank'|'insurance'|'both'`, and **move the column from `companies`
to `statements`** — GTCO is the document set's own example of a company that restructured into
a holdco, and when the template changes, historical statements keep the old shape while the
company row says otherwise.

Also add the crosswalk that makes `chart_version` do what §10 claims. Today, if v2 splits
`revenue` into `revenue_goods`/`revenue_services`, a five-year revenue query spanning both
versions returns nothing for the v2 years — `chart_version` records *that* things changed, not
*how*:

```sql
CREATE TABLE chart_version_map (
  from_version TEXT NOT NULL,
  from_key     TEXT NOT NULL,
  to_version   TEXT NOT NULL,
  to_key       TEXT,              -- NULL = retired with no successor
  relation     TEXT NOT NULL,     -- 'identical'|'renamed'|'split'|'merged'|'retired'
  weight       NUMERIC,           -- for apportionable splits; NULL = not apportionable
  note         TEXT NOT NULL,
  PRIMARY KEY (from_version, from_key, to_version)
);
```

### 2.8 Unit-scale errors become unauditable — three columns

`08 §1.4`'s own null-rule table uses a column called `as_printed` holding `"3,360,000"`. The DDL
has `as_printed_label` — the row *label*, not the value. Doc A had both. Also dropped:
`needs_review`, which §1.4 explicitly requires and which routes the entire human-review queue.

`OPERATIONS.md` §1.6 names the 1,000× silent error as the headline unit risk, and Nigerian
statements report in ₦'000 *inconsistently, sometimes varying within one document*. With only
the post-scaling `value` and a `unit_multiplier` the extractor may have got wrong, nothing
distinguishes a correct ₦3.36tn from a misread ₦3.36bn without reopening the PDF.

```sql
  as_printed_label  TEXT,          -- keep: the row label, 'Gross earnings'
  as_printed_value  TEXT,          -- ADD: the numeral exactly as printed, '3,360,000'
  as_printed_scale  TEXT,          -- ADD: 'thousands'|'millions'|'units' as declared
  needs_review      BOOLEAN NOT NULL DEFAULT false,   -- ADD
```

### 2.9 The canonical point-in-time query returns one row per security for all of history

`01_ARCHITECTURE` §5's snippet — the template `packages/common/pit.py` will be copied from —
uses `DISTINCT ON (security_id, canonical_key)`, which collapses **every period** to a single
row. FY2023 and FY2024 revenue cannot both be returned, so no growth feature can be built.

```sql
SELECT DISTINCT ON (sli.security_id, sli.canonical_key, s.period_type, s.period_end)
       sli.security_id, sli.canonical_key, s.period_type, s.period_end,
       sli.value, sli.currency, sli.known_as_of, sli.version
FROM   statement_line_items sli
JOIN   statements s ON s.id = sli.statement_id
WHERE  sli.known_as_of <= :decision_date
  AND  s.is_consolidated = :consolidated
ORDER  BY sli.security_id, sli.canonical_key, s.period_type, s.period_end,
          sli.known_as_of DESC, sli.version DESC;
```

### 2.10 Correction versus restatement — an undefined rule that bakes typos in permanently

`03` P3.5 and `08 §10` both say a correction inserts a new version with `superseded_by`,
`corrected_by` and `correction_reason`. Neither says **what `known_as_of` the new row gets**,
and the two cases are opposite:

- **Restatement** — the company republished. New `known_as_of` = the restatement's publication
  date. Both figures are historically true.
- **Correction** — *we* misread or mistyped. The market always had the right number, so the
  corrected row must carry the **original** `known_as_of`. Otherwise every point-in-time query
  with a decision date before the correction returns the typo **forever**, baked into every
  backtest.

🔧 Add `correction_type TEXT NOT NULL DEFAULT 'none'` — `'none'|'restatement'|'transcription'|'extraction'`
— so the choice is recorded rather than inferred, state the rule in `08 §10`, and add a golden
test for each branch.

### 2.11 Identity — three defects that reintroduce the bug the table exists to prevent

`UNIQUE (id_type, id_value, valid_from)` does **not** prevent overlapping validity windows: two
securities can both hold `GTCO` over overlapping dates provided `valid_from` differs by a day.
That is precisely the NGX ticker-reuse merge `OPERATIONS.md` §1.4 was written to stop. It is
also not exchange-scoped, so an NGX and a US ticker of the same string collide, and `cik`/`lei`/`figi`
were dropped from the `id_type` list while `companies.cik` remains a mutable scalar outside
identity history.

```sql
CREATE EXTENSION IF NOT EXISTS btree_gist;
ALTER TABLE security_identifiers
  ADD COLUMN exchange_id INT REFERENCES exchanges(id),   -- NULL for ISIN/LEI/CIK
  ADD COLUMN is_primary BOOLEAN NOT NULL DEFAULT false,
  ADD CONSTRAINT no_overlapping_ids EXCLUDE USING gist (
    id_type WITH =, id_value WITH =, exchange_id WITH =,
    daterange(valid_from, COALESCE(valid_to, 'infinity'::date), '[)') WITH &&
  );
-- id_type: 'ticker'|'isin'|'cusip'|'sedol'|'cik'|'lei'|'figi'
-- DROP companies.cik; migrate it into the identity table.
```

The exclusion constraint is the only mechanism that makes
`resolve_security(id_type, value, as_of_date)` provably single-valued.

### 2.12 FX conflates the market with the rate basis, and `convert()` has no decision date

`rate_type TEXT -- 'nfem_official'|'parallel'|'closing'|'period_average'` mixes two orthogonal
dimensions. `OPERATIONS.md` §1.3 requires IAS 21 translation at the **closing** rate for the
balance sheet and the **period-average** rate for the income statement, both on the *official
NFEM market*. This enum cannot express "NFEM period average". Translating a whole statement at
one rate produces a balance sheet that does not balance, which trips your own validation and
sends clean extractions to human review.

```sql
CREATE TABLE fx_rates (
  base_currency      CHAR(3) NOT NULL,
  quote_currency     CHAR(3) NOT NULL,
  market             TEXT NOT NULL,   -- 'nfem_official'|'parallel'|'cbn_official'
  rate_basis         TEXT NOT NULL,   -- 'closing'|'period_average'|'opening'
  as_of_date         DATE NOT NULL,
  rate               NUMERIC NOT NULL,
  data_source_id     INT NOT NULL REFERENCES data_sources(id),
  source_document_id BIGINT REFERENCES source_documents(id),
  known_as_of        DATE NOT NULL,
  PRIMARY KEY (base_currency, quote_currency, market, rate_basis, as_of_date, known_as_of)
);
```

And `convert(amount, to_currency, *, as_of, known_by, market, basis)` — `known_by` mandatory,
same rationale as the point-in-time accessor. Without it a backtest picks up FX rates revised
after its own decision date.

### 2.13 Provenance is mandatory on line items and optional everywhere else

`CLAUDE.md` says provenance on **every** figure. But `corporate_actions.source_document_id` and
`macro_observations.source_document_id` are nullable, `price_history` has no such column at all,
and `page` is nullable. Prices are the sharpest case: `08 §5` marks the NGX scraper 🔴 *"no
contract, can vanish — cache every raw response permanently"*, and no column links a row to the
cached response that justifies it.

```sql
ALTER TABLE corporate_actions
  ALTER COLUMN source_document_id SET NOT NULL,
  ADD COLUMN subscription_price NUMERIC,   -- restored: rights issues need it for TERP
  ADD COLUMN confidence NUMERIC,
  ADD COLUMN needs_review BOOLEAN NOT NULL DEFAULT false;
ALTER TABLE macro_observations ALTER COLUMN source_document_id SET NOT NULL;
ALTER TABLE price_history
  ADD COLUMN source_document_id BIGINT NOT NULL REFERENCES source_documents(id);
ALTER TABLE statement_line_items
  ADD CONSTRAINT page_required_unless_structured
  CHECK (extraction_method = 'xbrl' OR page IS NOT NULL);
```

That last CHECK is what makes P3 check 2 (`SELECT count(*) … WHERE page IS NULL` → 0)
structurally true rather than hopefully true.

### 2.14 The no-silent-overwrite rule has no enforcement, while the backtest gate has two

The gate got a CHECK **and** a trigger, with the excellent rationale that *"application code
can be bypassed at 1am by a person who is sure this one is fine."* The no-overwrite rule —
ranked equally non-negotiable — got *"enforce it in review, and by not providing an update
method."* The same 1am person has `psql`.

```sql
CREATE FUNCTION forbid_update() RETURNS TRIGGER AS $$
BEGIN RAISE EXCEPTION 'UPDATE forbidden on %; insert a new version', TG_TABLE_NAME; END;
$$ LANGUAGE plpgsql;
-- apply to: statement_line_items, price_history, macro_observations,
--           corporate_actions, fx_rates, adjustment_factors
CREATE TRIGGER no_update BEFORE UPDATE ON statement_line_items
  FOR EACH ROW EXECUTE FUNCTION forbid_update();

ALTER TABLE statement_line_items
  ADD CONSTRAINT pit_sanity CHECK (known_as_of >= period_end);
CREATE UNIQUE INDEX one_current_version ON statement_line_items
  (statement_id, canonical_key) WHERE superseded_by IS NULL;
```

The partial unique index is what makes "the current value" a *guaranteed* single row rather
than whatever the `ORDER BY` happens to pick.

### 2.15 Defer these — cheap to add later, and one is actively harmful

Building 49 empty tables in P0 buys nothing an empty table can buy. There is no data to
retrofit, and the columns are better enforced by a convention test (§6.1) that also governs
P7's and P10's tables, which P0 cannot.

| Item | Verdict |
|---|---|
| `price_history.close_adj`, `adj_computed_at` | **Delete, don't defer** — §2.6; actively harmful |
| `positions` | Derivable from `transactions`; three overlapping representations of one holding, the middle one a cache that will disagree. A view until P10 proves otherwise |
| `tax_lots` | P10, with the Nigeria Tax Act 2025 logic |
| `extraction_examples` | Derivable: `WHERE corrected_by IS NOT NULL`. Drop the table, keep the idea |
| `adr_log` | Self-described as an "optional mirror of `docs/adr/`". Two sources of truth for one file. Drop |
| `memo_citations`, `agent_runs`, `agent_messages`, `memos` | All P9; `memo_citations` duplicates `agent_messages.citations`. Pick one representation, build it in P9 |
| `backtest_trades` | P7 — also avoids materialising `SPEC.md`'s `DOUBLE PRECISION` money columns, which violate `08 §1.6` |
| `bbox JSONB` | P4, when the extractor can produce coordinates. `page` satisfies provenance today |
| The other ~30 tables | The phase that first writes to them |

**Do not defer**, because each is a redesign rather than a migration later: `principal_id` on
every user-scoped table, the mode middleware, `known_as_of` on every table *at the moment it is
created*, provenance columns, `version`/`superseded_by`, surrogate `security_id` with retained
delisted rows, `chart_version`, content-hash write-once document policy, `account_equity` as a
sizing parameter, and `rows_written` on `connector_runs`.

---

## 3. The numbers that were never written down

Two gates in this project are described in prose and cannot be failed as written. A gate you
cannot fail is decoration. These are the numbers; change them if you disagree, but change them
**now, in writing, dated** — never after seeing the first result.

### 3.1 P4.0 — the extraction accuracy metric and thresholds (closes TG13)

Three unrelated 0.85s currently sit within a page of each other in P4, and the pass bar equals
the abandon floor, which means clearing "abandon" reads as passing.

**The metric matters more than the number:**

- **Unit:** one `canonical_key` per statement per company-year.
- **Denominator:** every line item present in the golden JSON. A key the extractor omitted
  counts as wrong. A key correctly returned `null` counts as right.
- **Match:** numeric equality after unit conversion, tolerance ±0.5% or ±₦1,000, whichever is
  larger. Sign must match exactly.
- **Always two numbers:** pre-review (what the pipeline produced) and post-review (what the
  reviewer approved). **The gate is on pre-review.**

| `system_config` key | Value | Meaning |
|---|---|---|
| `extraction_target_headline` | **95%** | The ~25 materiality-weighted headline keys (revenue, PAT, total assets/liabilities/equity, cash-flow subtotals). P4 does not exit below this. |
| `extraction_target_all_items` | **90%** | All keys, pre-review. Matches Doc A §3.1's "~60% → 90%+" claim for the hybrid pipeline. |
| `extraction_abandon_floor` | **85%** | Gate G-A. Below this after two weeks → buy EODHD. **A floor, not a target.** |
| `extraction_confidence_route` | **0.85** | Per-extraction review routing (P4.3). **Unrelated to the three above — do not conflate.** |

### 3.2 The backtest gate (closes TG23, and makes the gate falsifiable)

Written down today: DSR ≥ 0.95, `net_return > 0`. Everything else is prose. The participation
cap appears as the literal character **`X`** nine times across four documents.

| Missing number | Set it to | Why |
|---|---|---|
| **Participation cap** | ≤ **10%** of that day's actual volume **and** ≤ 25% of trailing-20-day median volume | 10% is the standard institutional assumption; the median leg stops one spike day authorising a fictional fill |
| **Liquidity floor** | median daily value traded over trailing 60 sessions ≥ **₦25m** and traded on ≥ **80%** of the last 60 sessions, evaluated at the *decision date* | Also mitigates the stale-price Sharpe inflation below |
| **Max drawdown** | ≤ **25%** on the OOS path, ≤ **35%** on the worst CPCV path | At 0.25-Kelly with a real edge, 2-year expected MaxDD ≈ 15–20% |
| **CPCV stability** | N=6, K=2 → 15 combinations; require ≥ **70%** of paths net-positive, 5th-percentile path Sharpe > 0, and `cpcv_sharpe_std ≤ 0.5 × cpcv_sharpe_mean` | `cpcv_sharpe_std` is recorded today and constrained by nothing |
| **Minimum trades** | ≥ **100** closed round trips in the OOS period | Below ~100 the standard error on Sharpe exceeds the effect size claimed |
| **OOS length** | ≥ **24** contiguous months, entirely after the last training observation, entirely within one FX regime (so starting ≥ 2023-07-01) | `MinTRL` is named once in `SPEC.md` and never used — it is exactly the tool for this |
| **Embargo** | **10** trading days, and enforce `embargo_days ≥ vertical_barrier_days`; make the column `NOT NULL` | Currently nullable with no value |
| **"Beats buy-and-hold"** | equal-weight buy-and-hold of the *same pre-registered universe*, same window, charged one entry and one exit through the same cost model, beaten by ≥ **3pp** annualised net | Both baselines are undefined in 14,000 lines; their glossary anchors are dead |
| **"Beats logreg"** | identical folds and features, beaten by ≥ **2pp** annualised net — **and its tuning runs count toward K** | |
| **CUSUM threshold `h`** | **1.0 ×** trailing 20-day EWM daily vol, point-in-time | CUSUM appears **once** in the entire set and is absent from P8's build. Without it every day gets labelled, uniqueness collapses, and the effective sample is overstated ~5× |
| **Barrier multiples** | upper/lower = **2.0 ×** trailing-20-day EWM daily σ × √horizon, σ strictly point-in-time | |
| **Trade threshold on calibrated probability** | never a constant — compute `p* = 0.5 + c/(2b)` per trade from the live cost model and actual barrier width, plus a **0.05** margin | A hardcoded 0.6 is wrong in both directions depending on horizon |

**Two structural fixes without which the numbers do not bite:**

```sql
-- TG23: k_trials becomes derived. It is currently caller-supplied, so DSR is
-- decorative: k_trials = 3 after 300 variants passes every check.
ALTER TABLE backtest_runs ADD COLUMN strategy_family TEXT NOT NULL;
ALTER TABLE backtest_runs ADD COLUMN parent_run_id INT REFERENCES backtest_runs(id);
CREATE FUNCTION set_k_trials() RETURNS TRIGGER AS $$
BEGIN
  NEW.k_trials := (SELECT count(*) + 1 FROM backtest_runs
                   WHERE strategy_family = NEW.strategy_family
                     AND universe = NEW.universe);
  RETURN NEW;
END; $$ LANGUAGE plpgsql;
CREATE TRIGGER k_trials_derived BEFORE INSERT ON backtest_runs
  FOR EACH ROW EXECUTE FUNCTION set_k_trials();
REVOKE UPDATE (k_trials) ON backtest_runs FROM app_user;
```

with the rule that makes it real: **`run_backtest()` is the only code path that may compute a
Sharpe, and it writes a `backtest_runs` row before it returns — always, including failures and
including exploratory `vectorbt` triage runs, which is where hundreds of trials will actually
be burned.**

```sql
-- The one-touch holdout is named five times and defined zero times. Willpower is
-- not a control for a solo builder.
CREATE TABLE holdouts (
  id SERIAL PRIMARY KEY,
  universe TEXT NOT NULL,
  start_date DATE NOT NULL, end_date DATE NOT NULL,
  locked_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  locked_by TEXT NOT NULL,
  content_sha256 CHAR(64) NOT NULL,   -- corrections WILL change holdout data silently
  touched_at TIMESTAMPTZ,
  touched_by_run_id INT REFERENCES backtest_runs(id)
);
CREATE UNIQUE INDEX one_touch ON holdouts (id) WHERE touched_at IS NOT NULL;
```

The point-in-time accessor refuses rows dated `>= holdout.start_date` unless handed a token
issuable once; issuing it stamps `touched_at`. **Period: the most recent 24 months, locked
before the first line of P8, recorded in an ADR.**

Extend the gate CHECK to cover the criteria currently living only in prose:

```sql
CONSTRAINT gate CHECK (
  passed = false OR (
        dsr >= 0.95
    AND net_return_annualised > rf_annualised
    AND max_drawdown >= -0.25
    AND cpcv_worst_path_drawdown >= -0.35
    AND cpcv_sharpe_std <= 0.5 * cpcv_sharpe_mean
    AND cpcv_positive_path_fraction >= 0.70
    AND n_trades >= 100
    AND oos_months >= 24
    AND beats_logreg AND beats_buy_hold
    AND holdout_id IS NOT NULL
  ));
```

### 3.3 `net_return > 0` is the wrong hurdle for Nigeria

The canonical *passing* example in two documents is `net_return_after_costs: 0.061` — 6.1% in
Naira, against **33.24% CPI** and a policy rate in the high twenties, both of which this system
ingests in P1 and displays on its own macro dashboard. That strategy loses roughly a quarter of
its real value per year and the gate marks it `passed = true`. `backtest_runs` also has no
currency column, and "Sharpe = mean excess return / σ" never says excess *over what* — default
zero, which every library does, inflates every NGX Sharpe by roughly 1.5–2.0 units.

🔧 Add `base_currency CHAR(3) NOT NULL`, `risk_free_series_id INT NOT NULL`,
`rf_annualised NUMERIC NOT NULL`, `benchmark_return NUMERIC NOT NULL`, plus `n_trades`,
`n_observations`, `oos_start`, `oos_end`, `random_seed`, `data_snapshot_id`,
`participation_cap`, `holdout_id`, `skew`, `kurtosis`, `cpcv_sharpe_mean`,
`pct_zero_return_days`, `cost_model_params_hash CHAR(64)`. Without skew, kurtosis and track
length, a recorded DSR can never be independently verified — only trusted.

Replace the criterion `net_return > 0` with **`net_return_annualised > rf_annualised`**, where
rf is the 364-day NTB stop rate already in the macro layer, and report a real
(inflation-adjusted) return alongside nominal using the NBS CPI series already ingested.

### 3.4 The arithmetic nobody in the document set has done

Both inputs are in `SPEC.md`; they are never multiplied. For a symmetric triple-barrier trade
with barrier width `b` and round-trip cost `c`, break-even hit rate is `p* = 0.5 + c/(2b)`:

| barrier `b` | ≈ horizon | p\* at c=3.0% | p\* at c=4.5% |
|---|---|---|---|
| 5% | 6 days | 0.80 | 0.95 |
| 9% | 20 days | 0.67 | 0.75 |
| 20% | 100 days | 0.575 | 0.61 |
| 30% | ~225 days | 0.55 | 0.575 |

Read against this project's own two stated constants — realistic ceiling **52–55%**, and
**">60% OOS accuracy is a leak"** — this says:

> **At NGX costs, the only strategies that can clear the gate hold positions for roughly 9–12
> months.** Every horizon shorter than ~100 trading days requires a hit rate the project itself
> defines as evidence of a bug.

Nothing in P8 reflects this; triple-barrier is specified with no horizon at all, and the
default a reader carries from every textbook example is 5–20 days, which is in the impossible
band. 🔧 Pre-register the vertical barrier at **≥60 trading days, 120 default**, assert
`b ≥ c / (2·(p_target − 0.5))` with `p_target = 0.55` **in the labelling code, not a comment**,
and add a gate criterion of **turnover ≤ 2.0** round trips per position per year.

**The highest-value action in the entire trading plan is a phone call:** brokerage is the one
negotiable component, and moving from 1.35% to 0.5% roughly halves the minimum viable holding
period. Move that task ahead of P7.

### 3.5 Costs the NGX model omits, on the market where they are largest

The fee stack is modelled down to the ₦4 alert fee — genuinely excellent — but **bid-ask spread
is not a fee and is not in the model**, and there is no market-impact term. Meanwhile the *US*
cost model, on a market with sub-penny spreads, is the one that models spread. That is
backwards, and it makes every NGX backtest optimistic by more than all the enumerated fees.

🔧 Add `half_spread_bps` (default **150 bps** each way for names passing the liquidity floor,
**300** near it, `[NEEDS VERIFICATION]` until measured from your own contract notes) and a
linear impact term `impact_bps = k × (order_qty / ADV_20)` with `k = 1000`. Then the P7 test
should assert a round-trip cost at the participation cap lands in **5.5%–8%**, not the 2–4%
fees-only figure currently written — otherwise the test locks in the omission.

Three more that are individually small and jointly decisive:

- **Triple-barrier labels assume the stop fills.** On a limit-down halt the lower barrier is
  *touched* and the position cannot be exited. The standard implementation labels that as
  `−b`, truncating a loss that gapped much further — every label biased toward the barrier, in
  the flattering direction. 🔧 On a halted day, the exit price is the next unhalted day.
  **On NGX a stop-loss is not an executable instrument; position size is the risk control.**
- **Stale prices inflate Sharpe.** A non-trading day carries the close forward, manufacturing a
  zero-return day; that depresses σ and induces positive autocorrelation, inflating Sharpe by
  30–50% on genuinely illiquid names — and it flows straight into PSR and DSR. 🔧 Gate on
  unsmoothed (Geltner / Blundell–Ward) returns and warn when `zero_return_days / total > 0.15`.
- **Meta-labelling leaks by default.** The secondary model must train on the primary's
  **out-of-fold** predictions. Trained on in-sample predictions — the obvious implementation —
  it learns where the primary overfits, which looks like excellent precision. 🔧 State it, and
  test that in-sample primary predictions are never passed to the meta-model fit.

---

## 4. Compliance — the four bypass paths the five mechanisms do not cover

The five mechanisms are sound *where they were designed*. Every genuine hole is at a **seam
they do not reach**: a cache key, a nullable field, a scheduled job with no request, a byte
stream with no payload, and an exception raised before a response exists.

### 4.1 🔴 Scheduled pushes have no request, so no mechanism runs

Every mechanism begins with a request and a credential. The 07:00 brief is produced by the
scheduler: `resolve_mode(request)` cannot run, no response object exists to type-assert, and no
`audit_log` row is written. `SPEC.md` §2F's *"(personal only) fired signals"* describes an
`if personal:` branch inside a job — the "one router with an `if`" that mechanism 2 exists to
forbid, reintroduced on a surface nothing watches.

🔧 **Add to `01_ARCHITECTURE` §3 as "Non-request surfaces":**

> Every outbound message is composed inside a `DeliveryContext(principal_id)` that resolves
> mode through the same `resolve_mode_for_principal(principal)` the middleware calls. No job
> may branch on mode itself. A composer that reads `signals` without a `DeliveryContext` in
> scope is a build failure.

`alert_deliveries` gains `mode TEXT NOT NULL`, `body_sha256 CHAR(64) NOT NULL`, `body TEXT NOT
NULL`, `compliance_checked_at TIMESTAMPTZ NOT NULL`, plus a CHECK that a `signal_fired` alert
cannot have a delivery row with `mode='public'`. P5 check 9 currently reads *"no advice
phrasing in the brief"* — the weak linter; replace with *"a principal with `personal_tier=false`
receives a brief containing zero signal sections, asserted structurally."*

**And the pre-licence scenario nothing addresses:** a family member forwards the 07:00 brief —
*"GTCO BUY · calibrated probability 0.61 · size 4% of equity"* — to a WhatsApp group. No
document covers onward disclosure. `alert_deliveries` stores a hash, a channel and a status,
**not the body**, so "did advice reach non-family?" is unanswerable. 🔧 Personal-mode briefs
carry a footer naming the recipient principal: *"Personal-mode output for &lt;name&gt;. Not for
redistribution."* Free, and it makes the question answerable.

### 4.2 🔴 The memo cache key omits mode

`SPEC.md` §3.5 caches by content hash of the input bundle, and the bundle contains no
principal. Tuesday the owner generates a personal GTCO memo with
`verdict = {"action":"BUY","target":450}`. Wednesday a public user requests GTCO; the handler
computes the same hash, gets the personal row, and builds a `PublicMemo` from it. **Every
mechanism passes** — mode resolved correctly, router correct, response type allow-listed. The
CHECK constraint fires only on write. Only the banned-phrase linter is left, and if the verdict
is a JSON object rather than prose it may not even look.

🔧 Cache key becomes `sha256(mode ‖ prompt_version ‖ input_bundle)`. Add
`UNIQUE (mode, input_bundle_hash)` on `memos`, and the rule: *any cache key for content that
differs by mode must include the mode; a content hash alone is a cross-mode leak.*

### 4.3 🔴 `PublicMemo.verdict` exists as a nullable field

`SPEC.md` §1.2 mechanism 2 requires the public model have **no fields named** `signal`,
`recommendation`, `entry`, `stop_loss`, `target`, `position_size` — a type-level guarantee that
serialising advice into a public response is *impossible*. A nullable `verdict` on the public
type downgrades that to a runtime convention defended by one CHECK on the write path. Every
other path — cache hit, restore from dump, backfill, manual `psql`, a `mode` typo — is
undefended.

🔧 Two types, not one nullable field: `PublicMemo` with **no `verdict` attribute at all**, and
`PersonalMemo(PublicMemo)` adding it. Then the test that makes it self-enforcing:

```python
BANNED_PUBLIC_FIELD_NAMES = {
    "signal","recommendation","verdict","entry","stop_loss","target",
    "price_target","fair_value","position_size","conviction",
    "calibrated_prob","probability","score","rank","rating","grade","percentile",
}

@pytest.mark.invariant
@pytest.mark.parametrize("model", sorted(PUBLIC_LEGAL_TYPES, key=str))
def test_public_types_carry_no_advice_shaped_field(model):
    for name in walk_field_names(model):        # recursive, including nested models
        assert name not in BANNED_PUBLIC_FIELD_NAMES, f"{model.__name__}.{name}"
```

### 4.4 🔴 Bulk export bypasses three of five mechanisms — and is scheduled nowhere (TG22)

An export is a stream over a `SELECT`. No Pydantic payload, so `assert_legal` has nothing to
check. Columns come from SQL, not from `PublicAnalysis`, so field-name discipline never
applies. The body is a stream, so response linting cannot run without buffering the file.

**Concretely:** `/public/export/companies.parquet` runs `SELECT * FROM v_company_facts`. Six
months later someone widens that view with `latest_signal_direction` for an internal dashboard.
Advice is now in a Parquet file on a stranger's laptop, unrevocable, with no record of what it
contained. It is simultaneously the sharpest redistribution exposure — a bulk dump of
NGX-derived prices is exactly "re-serving raw", which Doc A §6.3 says the NGX agreement forbids.

🔧 Exports are generated from a named, versioned **`ExportView`** — an explicit column
allow-list declared in code. Never `SELECT *`; never a database view another feature can widen.
Each declares `mode_allowed`, its column list and its `source_ids`; generation asserts every
source is `redistribution_allowed = true` or the column is derived; every export writes an
`exports` row (`principal_id`, `view_name`, `view_version`, `row_count`, `sha256`,
`generated_at`, `expires_at`, `source_ids`) which *is* the audit record; URLs are signed and
expire. CI fails if any `ExportView` column is not in the public column allow-list.

### 4.5 The route-coverage test is tautological in the recommended configuration

`07 §2` Layer 6's `test_every_registered_route_is_gate_covered` asserts
`route_has_mode_middleware(route)`. But `01 §3` recommends **global** middleware, under which
that predicate is true for every route by construction — including `/openapi.json`, `/docs`,
and any router mounted outside both trees next month. The test the docs call *"the important
one"* passes trivially in exactly the configuration the docs recommend, **and it is not in P0's
checkpoint at all** — it appears only in `07` and in P12.

🔧 Replace coverage with an explicit **manifest**, as P0 checkpoint item 18 and invariant I13:

```python
# services/api/route_manifest.py
MANIFEST = {
  "GET /health":               RouteClass.INFRA,
  "GET /v1/public/ping":       RouteClass.PUBLIC_DATA,
  "GET /v1/personal/signals":  RouteClass.PERSONAL_ADVICE,
  ...
}

@pytest.mark.invariant
def test_route_manifest_is_exhaustive_and_exact():
    registered = {f"{m} {r.path}" for r in app.routes for m in r.methods}
    assert registered == set(MANIFEST), (
        f"unclassified: {registered - set(MANIFEST)}; stale: {set(MANIFEST) - registered}")
```

A new route fails CI on the first line, naming its own path. Include `/openapi.json` and
`/docs` deliberately — FastAPI's auto-schema publishes the entire `/personal/*` route list and
`PersonalSignal`'s field names to anonymous callers. Recommend `docs_url=None, redoc_url=None,
openapi_url=None` in production, with a separately served public-only schema.

### 4.6 Fail-open paths in `resolve_mode`, and a licence flag with no storage

`03` P0.5's `resolve_mode` reads only `principal.entitlements.personal_tier` — `licence_status`
appears as a **code comment**, and its home (`system_config`) had no DDL. `PROJECT_CONTEXT` §4
and §10 both say "entitlements **+** `licence_status`". So the real gate is one boolean, with
no cross-check against `principals.kind` and no defined behaviour when the entitlements lookup
raises. At P9 the IdP swap maps groups to entitlements; one wrong mapping grants `personal_tier`
to a public signup, and nothing else stops them.

🔧 Absence must mean unlicensed, and every failure path must fail closed:

```python
async def resolve_mode(request) -> Mode:
    try:
        principal = await resolve_principal(request)
        if principal is None or principal.disabled_at is not None:
            return Mode.PUBLIC
        ent = await get_entitlements(principal.id)
        if not ent.personal_tier:
            return Mode.PUBLIC
        if not licence.is_licensed() and principal.kind not in ("owner", "family"):
            return Mode.PUBLIC          # pre-licence: entitlement alone is not enough
        return Mode.PERSONAL
    except Exception:                   # entitlements down, DB error, anything
        audit_compliance_error(request) # fail CLOSED, loudly, but closed
        return Mode.PUBLIC
```

Plus a trigger: `entitlements.personal_tier = true` requires `principals.kind IN ('owner','family')`
while unlicensed. **Invariant I11:** pre-licence, a principal with `kind='public'` cannot
resolve to personal mode however entitlements are set.

Related, and unrecorded: `SPEC.md` §1.2 mechanism 1 requires *"the owner principal **+ a second
factor**"*. P0.5, ADR-0003 and the P0 checks have a plain bearer token and no second factor. 🔧
Either restore it on `/personal/*` or write an ADR deliberately deferring it to P9's IdP — but
do not let a stated requirement evaporate unrecorded.

### 4.7 Smaller, still real

- **Raw `Response` returns bypass mechanisms 2, 3 and 4.** A handler returning `FileResponse`,
  `StreamingResponse` or a bare `dict` has no payload to type-check. This is how you serve a
  CSV, a memo PDF or a chart PNG — at least three of which are planned. 🔧 *In public mode a
  handler **must** return a Pydantic model from `PUBLIC_LEGAL_TYPES`; returning a bare Response
  is a **build failure**.* Enforce with an AST check over `services/api/routers/public/**` plus
  a runtime content-type assertion.
- **Error bodies, logs and Sentry sit outside every mechanism.** The middleware lints
  *responses*; an exception is raised before one exists. A traceback carrying a repr of a local
  `PersonalMemo(verdict=…)` goes into the 500 body, into structlog on disk, and to **Sentry**, a
  US-hosted third party — which is simultaneously an NDPA cross-border transfer that no document
  connects to Sentry. 🔧 Public-mode errors become a fixed vocabulary: `not_found`,
  `invalid_request` (field *name* only, never the value), `rate_limited`, `internal` +
  `request_id`. Nothing else. Plus a Sentry `before_send` scrubber.
- **`GET /public/memos/{id}` is a sequential integer over a table containing personal memos.**
  No document states the handler filters `WHERE mode='public'`. 🔧 State the rule — *every
  public read is scoped by an explicit predicate, never by an id being unguessable* — and test
  that a personal memo's id returns **404**, not 403 (403 confirms existence).
- **No row-level authorization anywhere.** The gate is a *tier* gate; nothing says
  `/personal/portfolio` filters to the calling principal. Invisible with three principals,
  standard IDOR at P12. 🔧 Postgres RLS with `SET LOCAL app.principal_id` per request is the
  cheap total answer.
- **`principals.kind = 'service'`** appears once, in the DDL, with no policy. The obvious future
  consumer is the P9 frontend's server-side token — and if that holds `personal_tier`, every
  SSR render runs in personal mode. 🔧 *A service principal may never hold `personal_tier`;
  server components authenticate as the end user, never as the application.*
- **Advice without advice words.** Every mechanism targets words or field names. A ranked
  screener is invisible to all of them, and a default sort order over securities **is** a
  recommendation. 🔧 *A public response may not order securities by any system-computed
  composite, and may not carry a scalar that ranks or scores a security.*
- **The banned-phrase list has no file, no format, no owner, and one unusable seed term**
  (`"should"`). 🔧 The better answer is to invert the default: a public memo's
  `bull_case`/`bear_case`/`risks` are **claim + citation objects, never free paragraphs**, so
  there is no free text to lint. P9.5's output JSON is *already* shaped this way — promote it
  from example to rule. Keep the denylist as a secondary net at
  `packages/compliance/banned_phrases.yml`, whole-word case-insensitive, public free-text only,
  reviewed quarterly, with the false-positive battery ("share buyback", "buy-side", "buying
  power") that no test file currently owns.

---

## 5. Durability — the moat can currently be destroyed

Ranked by how much irreplaceable data each failure destroys.

### 5.1 🔴 `rclone sync` propagates local destruction off-site

`02 §8`'s backup script uses `rclone sync data/documents` — and `sync` makes the destination
match the source **by deleting**. Ransomware, a bad `reextract_all.py`, or bad sectors, and the
next 02:00 run deletes the off-site copy of every Nigerian PDF, including 2013 annual reports
whose source URLs have rotated. The dumps on the line above correctly use `copy`.

```bash
rclone copy data/documents "b2:quant-docs-prod/documents/" \
  --immutable --checksum --transfers 8 --log-file logs/rclone.log
```

Plus, at bucket creation: Object Lock in governance mode, versioning on, and application
credentials scoped `writeFiles + listFiles` with **no `deleteFiles`** — which makes the mistake
structurally impossible rather than merely discouraged.

### 5.2 🔴 The backup encryption key has no escrow

`BACKUP_GPG_ID` is an empty field in `.env.example`. Nothing states where the **private** key
and revocation certificate live. Default: the laptop's keyring — so the laptop dying takes both
the live database and the ability to decrypt every off-site backup.

🔧 Before the first backup runs: export the secret key and a revocation certificate, store them
in the password manager **and** on a printed offline copy held off-premises, then add to P0's
checkpoint: *restore a backup on a machine that has never held the key.* Until that has been
done once, the off-site tier is decorative.

### 5.3 🔴 Nothing detects a job that stopped running

The observability design keys off `connector_runs` and alerts on `status='ok' AND
rows_written=0`. That query only sees runs that **happened**. A connector the scheduler stopped
launching writes no row, and the query returns empty — indistinguishable from healthy. `02 §8`
claims the freshness monitor covers this; it does not, because that monitor is defined over
`macro_series.expected_lag_days`. A search for "heartbeat", "dead man" or "last_success" across
all sixteen documents returns **zero hits**.

Windows Update reboots the laptop, the scheduled task is left disabled, backups stop, and the
named detector cannot notice. This is the chain that ends with *"months of extraction, last
good backup in March."*

```sql
ALTER TABLE data_sources ADD COLUMN expected_run_interval_hours INT;
```
```sql
-- scripts/check_heartbeat.py — hourly; alert on any row returned
SELECT ds.source_name, max(cr.finished_at) AS last_ok
FROM   data_sources ds
LEFT JOIN connector_runs cr
       ON cr.connector_name = ds.source_name AND cr.status = 'ok'
GROUP BY ds.source_name, ds.expected_run_interval_hours
HAVING max(cr.finished_at) IS NULL
    OR max(cr.finished_at) < now() - (ds.expected_run_interval_hours * interval '1 hour');
```

A *local* check cannot report that the local machine is dead. 🔧 Add the one piece of external
infrastructure this project genuinely needs: a free **healthchecks.io** ping at the end of the
backup script, grace 26h. That is the only thing that emails you when the laptop is stolen.

### 5.4 🔴 TG17 — object storage is required by P3 and owned by nobody

Four index tables say TG17 "lands in P0". P0's ten tasks, seventeen checks and exit criteria
contain no bucket task; a search for `TG17` across both roadmaps, the user stories and the test
strategy returns nothing. Meanwhile `02 §4` says local disk is fine for P0–P8 while `02 §8` and
`02 §14` assume an off-site content-hash bucket from P0 — so under one reading the entire
P3/P4 extraction campaign sits on one Windows laptop.

🔧 **New task P0.11.** Backblaze B2 (~$0.006/GB/mo; 16 GB ≈ $0.10/mo). Buckets
`quant-docs-prod` / `-dev`. Keys exactly as `02 §4` already specifies:
`documents/sha256/<64-hex>.pdf` — flat, content-addressed. Object Lock on, versioning on, no
expiry rule ever. `source_documents.sha256 CHAR(64) NOT NULL UNIQUE` already gives the
content-address; add `scripts/verify_documents.py` to re-hash every object against its row,
run quarterly with the restore drill.

### 5.5 The restore drill: three defects in one mechanism

- **Cadence contradiction** — `OPERATIONS.md` §2.1 says *monthly*; `02 §8` says *quarterly*.
- **The success criterion does not test the data.** `restore.sh` counts rows in
  `information_schema.tables` and US-006 asserts *"the same table count as live"* — **a restore
  with zero business rows passes both.** This is silent-failure #19 (*"a file that looks like a
  backup"*) reproduced inside the check meant to catch it.
- **The script aborts on every run after the first** — `set -euo pipefail` plus `createdb` with
  no prior drop → `database already exists` → exit 1, under time pressure, so it gets skipped.

🔧 Named success criterion, into US-006 and P0.6: *`source_documents`, `statement_line_items`
and `price_history` row counts are each within 1% of live, the known-answer suite passes
against the restored copy, and one PDF fetched from `storage_key` re-hashes to its stored
`sha256`.* Cadence **quarterly**, first Monday of Jan/Apr/Jul/Oct, recorded in `docs/adr/` with
the four counts. Add `dropdb --if-exists` first. Standardise on `quant_restore_test`.

### 5.6 The rest, briefly

- **`git add -A` will commit the database dump.** P0.1's `.gitignore` covers `data/raw/` and
  `data/interim/` but not `backups/`, `*.dump`, `*.gpg`, or `data/documents/` — the paths the
  backup script actually writes. gitleaks will not flag a binary dump. 🔧 Add `data/`,
  `backups/`, `*.dump`, `*.gpg`, `*.sql.gz`. And P0.2's scaffold creates neither `data/` nor
  `backups/`, so `backup.sh` fails on its first line, silently, at 02:00. Add
  `mkdir -p data/documents data/raw data/interim backups logs`.
- **Nothing actually runs jobs on Windows.** APScheduler is in-process; nothing says what
  starts it. `02 §1.2` says the scheduler is *off* in local — and local *is* production until
  P9. 🔧 Register `pythonw.exe -m packages.scheduler.run` as a Scheduled Task at logon with
  "wake the computer" ticked; `max_instances=1, coalesce=True, misfire_grace_time=3600` plus a
  Postgres advisory lock per connector (they die with the connection, so a killed process
  self-heals); `ON CONFLICT DO NOTHING` for idempotency; **retry ceiling of 3** — P4.8 currently
  specifies exponential backoff with no ceiling, which is the runaway-spend loop §10 exists to
  prevent. `backup.sh` must become `backup.ps1`; `pg_dump` is not on PATH when Postgres is in
  the container.
- **No alert reaches the owner until P5.** P1's exit criterion is *"a zero-row run is flagged"*
  — on a dashboard nobody has open. Telegram lands at P5. 🔧 Pull bot creation into P0 (five
  minutes, the token line already exists) and ship `packages/alerts/ops.py` with one function
  in P1.
- **Freshness exists only for macro series.** `data_sources` has no cadence field, so NGX
  prices, EDGAR, RSS and the extraction pipeline have **no overdue concept at all**.
  `connector_runs` also dropped `rows_expected`, so `OPERATIONS.md` §2.3's *">50% drop versus
  trailing median"* alert has no baseline and only the crude `= 0` case survives — but "3 rows
  instead of 150" is the likelier failure. 🔧 Restore `rows_expected` and `bytes_fetched`; add
  `stale_after_days`; alert when `rows_written < 0.5 × median(last 10 successful runs)`.
- **No policy governs a destructive migration against the irreplaceable database.** CI's
  `upgrade → downgrade → upgrade` runs against an **empty** database and therefore proves
  nothing about a downgrade that must discard real columns. 🔧 Three rules: `migrate_prod.ps1`
  backs up first and aborts if the dump is <90% of the previous one; **forward-only in
  production**; no destructive DDL in one step — dropping a column is three revisions across
  three phases (stop writing → archive and verify → drop).
- **LLM caps contradict themselves** — `02 §10` says *"per user, never global"* and eight lines
  later *"a hard monthly ceiling"*; `.env.example` sets a global $50 while `02 §12` estimates P4
  at $20–100+, so the default halts the moat-building phase. The check is also racy
  (check-then-call across parallel workers). 🔧 Both caps apply, whichever binds first; global
  default **$150**; reserve the estimated cost before the call and reconcile after; fail closed.
  Add `max_agent_turns=12`, `job_timeout=600s`, `max_concurrent_llm_jobs=4`.
- **`02 §12`'s cost table is 5–8× below the documents it cites.** P9 is $35–90 there versus
  $70–200 in `SPEC.md` Part 6; P12 is $60–180 versus $300–1,500+. The P12 row names licensed
  data in its Data column and never adds it to the total, though Doc A prices it at
  $85–1,040/mo. 🔧 Restate both, and show licensing as its own line — the optimistic version is
  what makes a licensing decision look affordable when it is not.
- **The laptop→host cutover at P9 is the riskiest data movement in the project and is entirely
  unspecified.** 🔧 Add P9.6: freeze writes, final backup, restore into the hosted DB, parity
  check green, row counts equal, document verification green, and **the laptop database is
  renamed and kept read-only for 30 days, not dropped**.

---

## 6. New and changed tasks

### 6.1 P0 is not 5–9 days — split it

Counted honestly, P0 as written is **10–15 working days** (3–6 calendar weeks solo) producing
nothing visible. That contradicts the risk register's own top mitigation for its own top risk
(*"ship something real early — v0.1 in a weekend"*), and `05 §7` already admits P0's observable
change is *"Nothing visible."* **P0 has become the phase most likely to kill the project.**

The stated justification is that four things cannot be retrofitted without a rewrite. Read
carefully, that argument is about **columns on tables that hold data** and **logic that has no
principal concept** — not about the *existence* of 49 empty tables. The documents say so
themselves: *"adding an owner column to eleven tables later is a data **migration**; adding a
principal concept to logic that never had one is a **redesign**."*

**Keep the concepts, defer the tables**, and replace the ceremony with one test that keeps
working forever and also governs P7's and P10's tables, which P0 cannot:

```python
# tests/unit/test_schema_conventions.py  — @pytest.mark.invariant
# Introspect information_schema for EVERY table:
#   - user-scoped tables (allow-list by name) MUST have principal_id
#   - figure tables MUST have source_document_id NOT NULL, page, as_of_date
#   - model-readable tables MUST have known_as_of AND a business date
# Fails the build the day a phase creates a table that breaks the rule.
```

**P0 keeps:** P0.1 repo; P0.2 scaffold (**4 packages, not 14** — `common`, `compliance`,
`ingestion`, `scheduler`; the rest are a reserved namespace created on first use) with a fixed
`pyproject.toml`; P0.3 ADR-0001 + Docker Postgres; **P0.4-SPINE** — one migration of ~14 tables
(`principals`, `entitlements`, `principal_tokens`, `system_config`, `data_sources`,
`source_documents`, `macro_series`, `macro_observations`, `connector_runs`, `audit_log`,
`watchlists`, `watchlist_items`, `llm_spend`, `exchanges`) plus the convention test; P0.5
FastAPI + auth + mode + audit + **a token-mint script** + `seed_dev.py`; P0.8 compliance tests;
**P0.7-MIN** CI (ruff, mypy, unit + compliance, `alembic upgrade head`, gitleaks pre-commit);
**P0.6-MIN** backup (`pg_dump` to a second physical location + one restore, performed once);
P0.9 ADRs — 0002 and 0004–0007 are **already written** in `01 §9`, so copying them is twenty
minutes, not half a day.

**P0 defers:** the other ~35 tables to the phase that first writes to them; migration
reversibility to P3 (before P3 the reset is `docker compose down -v`); the gpg/rclone/R2 chain
to P3 entry; import-linter and the golden/synthetic CI jobs to when the directories exist;
banned-phrase list *design* to P4 (keep a no-op call site).

**Result: P0 in a week, and P1's visible macro dashboard by the end of week two.**

### 6.2 New tasks to add

| Task | Phase | What it closes |
|---|---|---|
| **P0.11 — Object storage and the immutability policy** | P0 | TG17 |
| **P0.12 — Dated regulatory config** (`system_config` DDL, seeded with `licence_status`, the NGX fee stack, the ±10% band, the movement rule, T+3, CGT, and P4.0's thresholds) | P0 | TG20 |
| **P0.13 — The standing-review register** (`docs/REVIEW_CADENCE.md`: banned-phrase list, restore drill, regulatory sweep, data-source terms — each with a cadence, an owner and a "last done" date) | P0 | TG16, TG18 |
| **P0.14 — Timezone discipline** (`TZ=UTC` everywhere, `TIMESTAMPTZ` everywhere, NGX session boundaries in `trading_calendar`) | P0 | TG21 |
| **P1.0 — The document store** (`StorageBackend` interface, local disk `documents/sha256/<hash>`, write-once; R2/B2 backend at P9) | P1 | unblocks P1.1 |
| **P1.7 — The manual CSV fallback** (R-02's own recommended mitigation, scheduled nowhere) | P1 | R-02 |
| **P3.6 — Point-in-time adjustment factors** | P3 → **move to P0 schema** | TG12 |
| **P3.7 — Freeze chart of accounts v1** | P3 | TG7 |
| **P4.0 — Define the accuracy metric and set the thresholds** | before P4.1 | TG13 |
| **P7.0 — Pre-registration** (`docs/PREREGISTRATION.md` committed before the first backtest: universe including delisted names, window, holdout dates, every threshold from §3.2; `backtest_runs.preregistration_sha`) | P7 | makes "pre-registered" checkable |
| **P11.1 — One cost-model instance, constructed once** | P11 | TG15 — see below |
| **P12.1–P12.4** — data-subject rights; the public-mode kill switch; rate limiting; legal instruments | P12 | P12 currently has **no build section at all** |

**TG15 is specified as the wrong test.** The gap says the paper trader and backtester must share
a cost-model **instance**; the acceptance criteria in `05` US-110 and P11 check 1 test that they
*"import the same class"*. `NGXCostModel(brokerage=0.0135)` and `NGXCostModel(brokerage=0.005)`
pass an import-identity test and differ by more than the entire edge. 🔧 Expose a cached
singleton `get_ngx_cost_model()`, make the constructor private, and assert
`paper_session.cost_model.params_hash() == run.cost_model_params_hash` against the authorising
`backtest_run` — resolve the paper trader's cost model *from that row*, so divergence is
impossible rather than merely tested for.

**P12 has tests and exit criteria but no tasks.** Its checkpoint asserts data-subject access and
erasure work end to end, a 72-hour breach runbook exists, and public endpoints survive hostile
input — none of which anything builds. NDPC registration and a DPO appointment have lead times
in weeks. 🔧 Add to P12 entry criteria: *P12.4 started at least six weeks ago — NDPC
registration is not a launch-week task.*

### 6.3 Three 🔴 mitigations recommended in prose and scheduled nowhere

| Risk | Its own recommendation | Where it must land |
|---|---|---|
| **R-30** backtester subtly optimistic | *"cross-validate against `vectorbt`/`backtrader` with costs disabled; gross results must agree"* | P7 checkpoint + P13 entry criterion |
| **R-21** lookahead via restatement | *"mandatory-argument accessor **+ a lint rule banning raw SQL in `ml`/`backtest`**"* | P0.7's CI stages — the rule is asserted by a P8 test but **no task configures it**, and `/packages/backtest` is never covered |
| **R-02** government sites redesign | *"manual CSV fallback wired from day one"* | P1 (see P1.7 above) |

### 6.4 Two exit criteria that cannot be met as written

- **P0: "`git log` shows the work in reviewed PRs."** GitHub does not allow you to approve your
  own PR. 🔧 *`main` protected with **required status checks**; all work merged via PR, no
  direct pushes; required approvals OFF while solo — turn on at the first collaborator.* Fix
  invariant I5, which tests for it.
- **`07 §4`'s universal gate — "all ten invariants, zero skips, every phase."** At P0, seven of
  the ten are untestable: no data, no tables, no code. 🔧 Add a switch-on column: I4/I5/I10
  from P0; I6/I7 from P2; I2/I3 from P3; I8 from P6; I1 from P7. *Zero skips among the
  invariants that have switched on.*

### 6.5 Missing at product level — required by `PROJECT_CONTEXT`, delivered by no phase

| Missing | Required by | Cost of adding now |
|---|---|---|
| **Entity graph — board, major shareholders, subsidiaries, auditor, related parties, index membership** | `PROJECT_CONTEXT` §9.1 places this project in Bloomberg's category; §9.3 names an unreplicable dataset as the moat | **Missing entirely — see §6.7.** Five of the six are already inside the PDFs P4 parses |
| **Valuation multiples — P/E, PEG, P/B, EV/EBITDA, dividend yield** | Every persona in `05`; it is what an investor opens a stock page to see | **Missing entirely — see §6.6 below.** `compute_ratios()` cannot produce one as specified |
| **API versioning** | §9.4: *"versioned from the first release"*; `05` names its absence an abandonment trigger | **Free today, a breaking change later.** Change every path in `08 §7` to `/v1/public/*` and `/v1/personal/*` **before P0.5 is written.** The cheapest high-value fix in this audit |
| **Family onboarding / self-explaining UI** | §7: *"or only one person will ever use it"* — and it is what P9's stage gate (*"family log in unprompted"*) actually depends on | Small if designed into P9; a retrofit onto a finished app otherwise. Add a P9 task: term tooltips sourced from the glossary, and a "why did this move" panel |
| **Bulk export** | §9.4; see §4.4 | Cheap later; design now, build P12 |
| **Data dictionary** | §9.4 — and `09_GLOSSARY` explicitly says it is *not* one, handing the requirement to nobody | Cheap — generate from `08 §2` + `information_schema`. P12 |
| **Coverage metrics page** | §9.4; `OPERATIONS.md` §3.2 defines the calculation | Cheap, and it is also how you evidence the P4 gate. Add to P4 exit |
| **Uptime tracking** | §9.4: *"from the day anyone but the owner depends on it"* | Cheap. P9 |
| **Search and a company page** | Implied by every persona; **not mentioned once in any document** | Moderate. Must be in P9.5's decomposition |
| **Responsive web** | US-091 (*"a family member on a phone"*) — a v1.0 gate | Cheap if stated in P9, expensive as a retrofit |
| **User management** (invite a family member, disable a principal) | Multi-user from day one | `seed_dev.py` is currently the only way a principal comes into existence, in any phase |

**P9.5 is an entire Next.js product — navigation, company pages, search, session handling,
responsive layout, deploy, TLS, IdP migration — in one paragraph** inside a 4–6 week phase
shared with multi-agent memos. 🔧 Decompose and re-estimate.

---

### 6.6 Valuation multiples are absent from the entire document set

Raised by the owner, 2026-08-30, and confirmed. Across all seventeen documents: **P/E appears
once** — only as an example of a null-handling rule — **PEG appears zero times, and "forward
P/E" appears zero times.** The ratio list, wherever it is enumerated, is *"margins, ROE, ROA,
leverage, liquidity, per-share"*: profitability and balance-sheet ratios only.

**The contract makes them structurally impossible:**

```python
# 08_DATA_CONTRACTS.md §6 — packages/valuation/ratios.py
def compute_ratios(items: dict[str, Decimal | None]) -> dict[str, Decimal | None]:
```

`items` is statement line items. **No price is passed in, so no price-based multiple can come
out.** This is the class of ratio an investor opens a stock page to see, and every persona in
`05` implicitly needs it. It is also what a B2B buyer means by "fundamentals".

**Three tiers, and only the third is hard:**

| Tier | Ratios | Inputs | Status |
|---|---|---|---|
| **1 — trailing, computable today** | P/E, P/B, P/S, EV/EBITDA, EV/Sales, dividend yield, earnings yield, FCF yield | price + line items + **shares outstanding as of that date** | Blocked only by the signature and by share count |
| **2 — historical growth** | PEG (trailing), revenue/earnings CAGR | tier 1 + prior periods | Free once tier 1 exists |
| **3 — forward-looking** | Forward P/E, forward PEG | **next year's earnings** | 🔴 **No free analyst consensus exists for NGX.** See below |

**Tier 1's real dependency is share count, not price.** A P/E needs the shares outstanding
**as of the price date**, and NGX companies issue bonus shares frequently — a bonus issue
changes the denominator without any cash changing hands. Using today's share count against a
2023 price silently produces a wrong P/E, in the same class of error as the adjusted-price sin
in §2.6. There is no `shares_outstanding` time series anywhere in the schema.

```sql
CREATE TABLE shares_outstanding (
  security_id  INT  NOT NULL REFERENCES securities(id),
  as_of_date   DATE NOT NULL,
  shares       NUMERIC NOT NULL,
  share_class  TEXT NOT NULL DEFAULT 'ordinary',
  basic_or_diluted TEXT NOT NULL,        -- 'basic'|'diluted'
  known_as_of  DATE NOT NULL,
  source_document_id BIGINT NOT NULL REFERENCES source_documents(id),
  PRIMARY KEY (security_id, as_of_date, share_class, basic_or_diluted, known_as_of)
);
```

And the signature must take price and a decision date, or every multiple it returns is
silently non-point-in-time:

```python
def compute_ratios(
    items: dict[str, Decimal | None],
    *,
    price: Decimal | None = None,
    shares: Decimal | None = None,
    decision_date: date,          # mandatory — same rule as the PIT accessor
) -> dict[str, Decimal | None]:
    """Any ratio with a null input returns None. Never 0, never inf.
    A multiple computed without `price` returns None rather than being omitted,
    so the caller can tell 'not applicable' from 'we forgot'."""
```

**Tier 3 is a data problem, not a coding problem.** Forward P/E needs forecast earnings. For US
names a consensus estimate is purchasable. **For NGX no free analyst consensus is available** —
there is no I/B/E/S-equivalent to scrape, and this is a genuine coverage limit of the market,
not an oversight. Three options:

1. **User-supplied forecast.** The user types next year's earnings; the system computes the
   multiple from it and shows the assumption alongside the answer. **Recommended** — it is
   exactly Doc A §1.4's *"you provide the instrument, they provide the judgment"*, it works in
   public mode, and it needs data you do not have to buy.
2. **System-forecast earnings.** More useful, but a system-generated forward multiple is
   functionally a price target. **Personal mode only until the licence** — it must live on
   `PersonalAnalysis`, never `PublicAnalysis`.
3. **Buy estimates for US names only**, and use option 1 for NGX. Reasonable later; not a v0.2
   decision.

**A compliance line worth drawing now, because it will recur:** a P/E is a *fact* and ships in
both modes. *"PEG below 1, therefore undervalued"* is a **verdict** — and `undervalued` is
already on the banned-phrase list. The number is public; the interpretation is personal. Same
rule for a screener sorted by P/E ascending, which is a recommendation wearing a sort order
(§4.7).

**Where this lands:** tier 1 and tier 2 into **P2.4**, which is where `compute_ratios` is
already built and where US price history (TG1-US) already arrives — so the only new work is the
share-count series and the signature. Tier 3 into **P6**, alongside the scenario engine, where
user-supplied assumptions already have a home. Add `shares_outstanding` to the P2 migration,
not P0.

---

### 6.7 The entity graph — the Bloomberg-terminal panels, and which of them are nearly free

Raised by the owner, 2026-08-30, from a description of the Bloomberg Terminal's company view:
suppliers on the left, customers on the right, index membership, competitors, major holders,
analyst coverage, and the board.

**Confirmed absent.** Across all eighteen documents: `index membership` — **zero mentions**.
`auditor` — **zero**. `related party` — **zero**. `shareholder` — **one**, in passing, in the
risk register. `subsidiary` — **one**. The plan models a company's *numbers* thoroughly and its
*relationships* not at all.

#### Why this is not scope creep, and why the schema decision is due now

`PROJECT_CONTEXT` §9.1 already places this project in the market-data category alongside
Bloomberg, LSEG and FactSet, and §9.3 names the moat as *"a proprietary dataset that is
expensive to replicate."* An entity graph for NGX is that same thesis, extended — and for
Nigeria it is arguably a **stronger** moat than the financials, because nobody publishes it in
any form and it cannot be bought.

The decision is due now for the usual reason: **relationships are a graph, and retrofitting a
graph onto a flat schema is a redesign, not a migration.** Same logic already accepted for
multi-user keying and provenance in §2.15. Empty tables cost nothing.

#### The finding that changes the economics

**Five of Bloomberg's panels are already inside the PDFs P4 is already collecting and already
parsing.** Nigerian annual reports contain, by CAMA and NGX listing-rule requirement:

| Bloomberg panel | Where it already is |
|---|---|
| **Who is on the board** | The Directors' Report — full board, roles, appointment and resignation dates |
| **Big holders of the stock** | The shareholding analysis / substantial-shareholders schedule (holders above 5%) |
| **Subsidiaries and group structure** | Notes to the accounts |
| **Auditor** | The audit report, on its own page |
| **Related parties** | The related-party transactions note — a genuine relationship edge, disclosed |

The marginal cost is **a new extraction target on documents already in hand**, not a new data
source, a new connector, a new licence, or a new manual collection task. That makes it the
cheapest high-value feature available to this project, and it is invisible today because the
extraction spec only ever looks at the three financial statements.

#### Index membership is not new scope — it is an existing gap

A point-in-time index-membership table is **already required** by P7 check 11 (*"a universe as
of 2020 includes companies delisted in 2022"*) and by the survivorship-bias defence in
`UNIVERSE.md` §2. Without it, "the NGX 30 as of 2020" is not answerable, and every backtest
universe is hand-maintained. NGX publishes constituents for the NGX 30 and the sector indices.
**Build it for the backtest; the Bloomberg panel is a free by-product.**

#### What to decline, and why

| Panel | Verdict |
|---|---|
| **Livestreams from 300 exchanges** | **No.** Real-time market data is the single most expensive thing on any exchange's price list — `DATA_FOUNDATION` §Key Findings prices NGX Quotes at **$12,500/yr** alone. And nothing in this system needs sub-daily data: daily bars, T+3 settlement, daily-frequency backtests, a ±10% band that halts for the whole day. Real-time would cost more than everything else combined and change no answer. |
| **Oil tanker positions** | **No.** Satellite AIS data, expensive, and irrelevant to NGX equities. Bloomberg carries it because physical commodity traders pay for it — a different customer than any persona in `05`. |
| **Curated tweets** | **Already planned, better.** P5 is news + sentiment via RSS. X/Twitter API pricing makes the tweet feed specifically a poor trade; Nigerian financial coverage (Nairametrics, Proshare, BusinessDay) is on RSS and is higher signal. |
| **Analyst coverage** | **Defer.** Nigerian broker research (Meristem, CardinalStone, Chapel Hill, ARM) has no consolidated feed and mostly sits behind client relationships. Low value, high effort. Revisit if a buyer asks. |
| **Full supply-chain graph** (who supplies GM, who buys from GM) | **Partial, deferred.** Bloomberg builds this from disclosures plus large-scale manual research. The free slice is IFRS customer-concentration and segment disclosures, which name major customers where they exceed a materiality threshold — genuinely useful, genuinely incomplete. Take the disclosed edges in P4; do not attempt the full graph. |

#### The one panel Nigeria makes *more* interesting than the US

**Interlocking directorates.** Nigeria's listed-company elite is small, and the same individuals
sit on several boards at once. Once `entity_roles` is populated from documents you are already
parsing, "which other listed companies does this director also sit on?" becomes a single query
— and that graph:

- exists in **no** commercial product for NGX, at any price;
- is a genuine governance and concentration-risk signal, not a novelty;
- is exactly the kind of thing `PROJECT_CONTEXT` §9.2's media, research and university buyers
  cite, and cannot get elsewhere;
- is **excellent content**, which §7's channel angle values directly.

This is the part that is not a Bloomberg imitation. It is something Bloomberg does not have.

#### DDL — ✅ NOW IN THE CONTRACT

> **Applied 2026-08-30.** These five tables plus `shares_outstanding` are now
> [08_DATA_CONTRACTS](08_DATA_CONTRACTS.md) **§2.14**, rows 49–54 of the table map, with the
> P2/P3/P4 checklists updated in its Appendix B. **08 is the contract; the DDL below is kept
> only as the record of what was added and why.** Build from 08.

Empty until P4, but the shape must be right before anything writes to it.

```sql
-- People. Nigerian names carry many spellings and honorifics ("Dr.", "Alhaji",
-- "Chief"); normalised_name is what matching joins on, full_name is what displays.
CREATE TABLE persons (
  id              BIGSERIAL PRIMARY KEY,
  full_name       TEXT NOT NULL,
  normalised_name TEXT NOT NULL,
  created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX ON persons (normalised_name);

-- Board seats and executive roles. Dated, because "who was on the board when this
-- decision was made" is the whole point.
CREATE TABLE entity_roles (
  id                 BIGSERIAL PRIMARY KEY,
  person_id          BIGINT NOT NULL REFERENCES persons(id),
  company_id         INT NOT NULL REFERENCES companies(id),
  role               TEXT NOT NULL,   -- 'chairman'|'ceo'|'cfo'|'executive'|'ned'
                                      -- |'independent_ned'|'company_secretary'
  valid_from         DATE NOT NULL,
  valid_to           DATE,
  known_as_of        DATE NOT NULL,
  source_document_id BIGINT NOT NULL REFERENCES source_documents(id),
  page               INT,
  confidence         NUMERIC,
  needs_review       BOOLEAN NOT NULL DEFAULT false
);

-- The "big holders" panel. holder_company_id is set when the holder is itself a
-- company you track, which is what makes cross-holdings queryable.
CREATE TABLE shareholdings (
  id                 BIGSERIAL PRIMARY KEY,
  company_id         INT NOT NULL REFERENCES companies(id),
  holder_name        TEXT NOT NULL,
  holder_type        TEXT NOT NULL,   -- 'person'|'company'|'government'|'fund'|'nominee'
  holder_person_id   BIGINT REFERENCES persons(id),
  holder_company_id  INT REFERENCES companies(id),
  units              NUMERIC,
  pct_held           NUMERIC,
  as_of_date         DATE NOT NULL,
  known_as_of        DATE NOT NULL,
  source_document_id BIGINT NOT NULL REFERENCES source_documents(id),
  page               INT,
  needs_review       BOOLEAN NOT NULL DEFAULT false
);

-- One generic edge table rather than five specific ones. to_name carries the
-- counterparty when it is not a company you track, which is the common case.
CREATE TABLE company_relationships (
  id                 BIGSERIAL PRIMARY KEY,
  from_company_id    INT NOT NULL REFERENCES companies(id),
  to_company_id      INT REFERENCES companies(id),
  to_name            TEXT,
  relation           TEXT NOT NULL,   -- 'parent'|'subsidiary'|'associate'|'joint_venture'
                                      -- |'auditor'|'related_party'|'major_customer'|'supplier'
  ownership_pct      NUMERIC,
  valid_from         DATE,
  valid_to           DATE,
  known_as_of        DATE NOT NULL,
  source_document_id BIGINT NOT NULL REFERENCES source_documents(id),
  page               INT,
  CHECK (to_company_id IS NOT NULL OR to_name IS NOT NULL)
);

-- Point-in-time index constituents. Required by P7 check 11 regardless of the
-- Bloomberg panel: "the NGX 30 as of 2020" must be answerable, or every backtest
-- universe is survivorship-contaminated.
CREATE TABLE index_membership (
  index_code         TEXT NOT NULL,   -- 'NGX30'|'NGXBNK'|'NGXCNSMR'|'NGXASI'|'SP500'
  security_id        INT NOT NULL REFERENCES securities(id),
  valid_from         DATE NOT NULL,
  valid_to           DATE,
  weight             NUMERIC,
  known_as_of        DATE NOT NULL,
  source_document_id BIGINT NOT NULL REFERENCES source_documents(id),
  PRIMARY KEY (index_code, security_id, valid_from, known_as_of)
);
```

**Peers and competitors need no table** — they derive from `industries.scheme + code`, which
§2.4 already adds. A peer set is a query, not stored data, and storing it would immediately
drift from the classification.

#### Sequencing — this is deliberately not P0 work

| When | What | Effort |
|---|---|---|
| **P2 migration** | The six tables above, empty | ~1 hour |
| **P3** | Index membership backfilled by hand for the universe — it is a small table and it unblocks the P7 survivorship check | ~half a day |
| **P4** | Board, shareholders, subsidiaries, auditor and related parties added as **extraction targets on documents already being parsed**. Same PDF, same pipeline, same review queue, new sections | Meaningful but marginal — the document is already open |
| **P9** | The company page that actually shows the graph — this is the Bloomberg-looking part, and it needs the Next.js frontend to exist | Part of P9.5's decomposition (§6.5) |

**Do not pull any of this forward into P0.** `PROJECT_CONTEXT` §8 warns that this project is
already *"three things that could each be a full-time job"*, and P0 is already over-scoped
(§6.1). The schema is the only part that is expensive to defer; everything else waits for the
phase that can absorb it.

#### The honest note on the $8bn

Bloomberg's revenue is 325,000 terminals × ~$25,000 — that is **distribution and forty years of
workflow lock-in**, not the data. `PROJECT_CONTEXT` §9.5 already states the transferable
version plainly: Nigerian market-data buyers are price-sensitive and the addressable
institutional market is *"perhaps a few dozen serious accounts."* The revenue model does not
carry across; the **product shape** does, and for a fraction of the cost, because the hard
input — the documents — is already being collected for another reason entirely.

---

## 7. Document-set hygiene

Lower stakes, but each one costs someone an hour eventually.

| Issue | Fix |
|---|---|
| **51 stale `G<n>` references in prose** across 8 of 10 docs, while the registers use `TG`. `04 §0.3` announces TG numbering and then uses `### G1`, `### G2`… for its own headings | Mechanical `G<n>` → `TG<n>` in prose, skipping the `G-A`…`G-L` decision gates. A reader grepping `TG2` currently misses the three sections that say what to do about it |
| **`G9` means three different things** (clock/timezone in `02`, corrections table in `06`, glossary gaps in `09`); `G-` prefixes both gaps and decision gates | Retire `G`/`AD-` numbering entirely; `09 §"four numbering systems"` actually lists five and covers none of the gap schemes — retitle to seven and add TG, G-A, R, US, ADR |
| **`TEAM_BRIEF.md §2.1-C` was cited 14 times and is the wrong section** — §2.1 is *The roles*; the lettered task list is §2.2. Two blockers (TG6, TG14) rest on it | ✅ **APPLIED** — global `§2.1-` → `§2.2-` across 9 files. Zero legitimate `§2.1-X` references existed |
| **TG14's premise is mis-cited.** No root document requires a second person; the nearest text is about *accountability*, not a second reviewer | Correct the citation in all three places, and force the decision in P3: either name the second person and the date, or record that none was available and raise production sampling to weekly for P4's first two months. There is no third option |
| **ADRs have three homes** — `docs/adr/`, `docs/decisions/` (`OPERATIONS.md` §3.1), and inline in `01 §9` | Pick `docs/adr/`; amend `OPERATIONS.md` §3.1 and `03` line 186 |
| **102 dead internal anchors** — 60 in the glossary, 17 in the risk register (every `#r-nn` link in §2, its marquee section, because R-numbers are table rows not headings), 4 in `04` (two appendices that do not exist) | Promote R-numbers to `#### R-nn — title` sub-headings; write or drop `04`'s appendices; wire a markdown link-check into P0's CI — a ten-line step, and this will re-break otherwise |
| **Line numbers cited as section numbers** — "`TEAM_BRIEF.md` §254", "SPEC.md 524" | Substitute real section titles; these rot the moment anyone edits a root doc by one line |
| **Regulatory facts duplicated in 9 places with no canonical owner** — the NGX movement rule appears in 11 locations, and the tiered replacement was postponed the day before rollout, two weeks ago | Designate `SPEC.md` §2C the single owner with a dated "last verified" marker; reduce the other mentions to pointers; the live values live in `system_config` with effective dates |
| **`00 §8` presents open decisions as made** — lists AD-1…AD-5, omits ADR-0001/0002/0003, two of which were `Status: open`, while its diagram renders PostgreSQL as settled | Renumber to ADR ids, retitle *"settled and open"*, add the three missing rows with honest status ✅ *(ADR-0001 is now closed by this audit)* |
| **13 vs 14 packages** — `01 §2` enumerates 14, `01 §9` ADR-0004 says 13, `00 §8`'s diagram says 13 | ✅ **APPLIED** to ADR-0004; `00 §8`'s diagram still says 13 |
| **17 user-story IDs referenced and never defined** (US-014, 017, 025, 026, 047, 048, 055–059, 069, 078, 079, 093, 096, 098) — including all four cited for "family shared visibility" and both cited for coverage metrics | Write them or replace the ranges. As-is, `05 §2.7` hides real coverage holes behind phantom IDs |
| **`06 §2`'s five headline risks link to risks that do not exist** — R-26 is referenced and undefined; R-31/R-32/R-40 descriptions do not match §4's numbering | Renumber §2's links against §4 |
| **Golden set: 3 filings or 10?** The manual calendar budgets 2–3 days for **3**; P3 exit and P4 entry demand **10** — straight-line 7–10 days, in the phase already carrying 20–40 hours of typing, with attrition rated 🔴 | Split explicitly: **3 to start P4** (MTN FY2024, a bank, a clean industrial), **10 to exit P4**, of which **3 are sealed in `tests/golden/locked/`** and chosen at random *before* any extractor output is seen |
| **The locked golden subset is specified in six places and created by no task**, and P4's gate command runs `pytest tests/golden` — the whole set, including the pairs you tuned against | Split the set on the day you build it; P4 check 1 must invoke `tests/golden/locked` |
| **`SPEC.md §4.2`'s heading says "v0.1 → v2.0"** but the list runs to T21/v2.5 | Cosmetic, but it is cited ~40 times as the definitive task list |

---

## 8. Decisions only the owner can make

These are not editorial. Each changes what gets built, and none should be defaulted silently.

> **Four of five were answered by the owner on 2026-08-30 and are recorded below as resolved.**
> D5 is not a decision to make today — it is one the P7 arithmetic will make for you.

### ✅ D1 — RESOLVED 2026-08-30: one paid month, everything pulled at once

**Owner's decision:** apply for a student discount, subscribe for **one month**, and pull all
required history inside that month.

**This is the right shape, and it inverts the sequencing risk — read the order carefully.** The
subscription is not the hard part; the *fetcher being ready before the clock starts* is.
Subscribing and then spending three weeks writing a downloader wastes the month.

**Sequence — do not reorder:**

1. **Verify the universe tickers** ([UNIVERSE.md](UNIVERSE.md) §1–2). A wrong ticker is a
   company you silently never downloaded, discovered at P7.
2. **Write and dry-run the bulk fetcher against the free tier or trial first.** It must handle
   pagination, rate limits, resume-after-failure, and write **raw responses to object storage
   permanently, content-addressed** — you cannot re-download after cancelling, so an
   unparsed-but-saved response is recoverable and a parse error on a discarded response is not.
3. **Then subscribe.** Pull, verify counts, *then* let it lapse.

**What to pull — all four, in this order of importance:**

| What | Why it is easy to forget |
|---|---|
| **Daily OHLCV + volume**, full available history, every ticker in the universe | The obvious one |
| **The 3 delisted tickers** (UNIVERSE §2) | A "current constituents" export silently omits every one, and they are the only reason P7 check 11 can pass. **Request them by name.** |
| **Corporate actions** — splits, bonus issues, dividends, rights issues with subscription price | TG2 and TG12. Without these every adjusted price is wrong, and Nigerian bonus issues are frequent |
| **Fundamentals**, if the tier includes them | A free cross-check against your own PDF extraction — a second opinion on accuracy, for nothing |

**⚠️ The licensing question, which is not optional and is bigger than the month.**
`CLAUDE.md`'s hard rule is *"data licensing before ingestion — confirm redistribution rights
before a source enters the dataset."* Two different questions with two different answers:

- **May you keep and use the data after the subscription lapses?** Usually yes for internal
  use — but **read the terms, do not assume.**
- **May you *redistribute* it — serve it on the public tier, or to a B2B client?** **Almost
  certainly not**, on any consumer-priced tier. `PROJECT_CONTEXT` §9.3 calls clean
  redistribution rights *"the one that kills deals"*: an acquirer's lawyers ask exactly this
  question, and a dataset assembled from a lapsed personal subscription is a liability rather
  than an asset.

**This does not block anything; it shapes where the data may be used.** Record the source in
P0.10's licensing register as `ingestion_allowed = true`, `redistribution_allowed = false`,
`derived_only = true`. That is fully sufficient for personal mode, for the backtest gate, and
for everything through P11. It means the *raw vendor series* cannot be served publicly at P12
without a redistribution licence — a P9 decision, not a P4 one, and the same decision already
flagged for the free NGX scraper.

**Student discount availability is [NEEDS VERIFICATION]** — ask the vendor directly. If none
exists, the entry EOD tier is roughly $20–30 for the month, which is the same plan at full
price.

**One thing to be clear-eyed about:** one month is enough for *history*, not for *staying
current*. A lapsed subscription stops updating, so from P4 onward NGX daily prices come from
your own scraper. That is the intended design — the paid month buys **the past**, the scraper
buys **the present**, and you need both.

### ✅ D2 — RESOLVED 2026-08-30: own capital and family capital, no fee

**Owner's statement:** *"Nobody is paying me. I just want to handle my money first and family
money, and I am not collecting a fee from anybody yet."*

That is exactly the condition `SPEC.md` §1.2 relies on, so **the personal tier is on solid
ground today** and no change to the access model is needed.

**Record it in the schema, so it stays true by construction rather than by memory:**

```sql
ALTER TABLE principals
  ADD COLUMN relationship  TEXT,     -- 'self'|'spouse'|'parent'|'sibling'|'child'
  ADD COLUMN fee_charged   BOOLEAN NOT NULL DEFAULT false,
  ADD COLUMN funds_pooled  BOOLEAN NOT NULL DEFAULT false,
  ADD COLUMN attested_by   TEXT,
  ADD COLUMN attested_on   DATE;

-- The legal basis, enforced rather than remembered.
CREATE FUNCTION assert_no_fee_while_unlicensed() RETURNS TRIGGER AS $$
BEGIN
  IF (NEW.fee_charged OR NEW.funds_pooled) AND NOT licence_is_active() THEN
    RAISE EXCEPTION
      'Personal tier requires no fee and no pooled funds while unlicensed (SPEC 1.2)';
  END IF;
  RETURN NEW;
END; $$ LANGUAGE plpgsql;
```

**Cap: `family_tier_max_principals = 6`**, seeded into `system_config` and enforced by a
trigger on `entitlements`. Six covers a household plus first-degree relatives with room to
spare. **The cap is not a limit on your family — it is a tripwire.** Adding a seventh fails
loudly and makes you decide on purpose, instead of arriving at eleven people by accident.

**On the word "yet".** *"Not collecting a fee from anybody **yet**"* is honest and accurate,
and it is exactly why the two flags above are worth the ten minutes they cost. The day someone
offers to cover the server bill, the system declines and says why — rather than that day
passing unnoticed, which is the realistic failure mode. Nothing to act on now; the mechanism
just exists.

**Add to `PROJECT_CONTEXT` §4**, so the definition lives beside the access model:

> **What "family" means here.** Members of the owner's household and first-degree relatives
> whose capital the owner already accounts for. Capped at six principals. **No fee is charged
> to any of them and no funds are pooled under the owner's control** — those two conditions are
> what make the personal tier lawful without SEC registration (`SPEC.md` §1.2), and both are
> enforced in the database. If either ever becomes untrue, the personal tier closes until the
> licence exists.

### ✅ D3 — RESOLVED 2026-08-30: thresholds accepted as proposed

**Owner's decision:** adopt §3.1's proposal unchanged.

| `system_config` key | Value |
|---|---|
| `extraction_target_headline` | **95%** — the ~25 materiality-weighted headline keys. P4 does not exit below this |
| `extraction_target_all_items` | **90%** — all keys, pre-review |
| `extraction_abandon_floor` | **85%** — gate G-A. Below this after two weeks, buy the data and move on |
| `extraction_confidence_route` | **0.85** — per-extraction review routing. Unrelated to the three above |

Seed as dated rows in P0.12. **TG13 is closed.** Amend `TEAM_BRIEF.md` Part 4's stage gate from
"≥85%" to "≥95% headline / ≥90% all items", leaving Part 3's 85% as the abandon trigger it was
always meant to be.

### ✅ D4 — RESOLVED 2026-08-30: universe chosen — see [UNIVERSE.md](UNIVERSE.md)

**22 live + 3 delisted = 25.** Five banks, two insurers, two telecoms, three cement, four
consumer, two oil and gas, two agriculture, two other — chosen for liquidity, sector spread (so
the chart of accounts is proven against every statement shape rather than one), and audience
interest.

Two properties of the list worth knowing:

- **Airtel Africa and Seplat are dual-listed on the LSE**, so they publish the same financial
  year twice. That is a **free, independent ground truth** for extraction accuracy on two whole
  companies — use it as the first accuracy check in P4, before spending days hand-keying the
  golden set.
- **The three delisted names are the only reason P7 check 11 can pass**, and the free scraper
  cannot fetch them by definition. They must be named explicitly in D1's paid pull.

**One task remains before collection starts:** every ticker and delisting date in UNIVERSE.md
is marked **[NEEDS VERIFICATION]** against NGX's listing directory. Half a day, once. A wrong
ticker is a company you silently never downloaded.

### ⏸️ D5 — Whether the trading track happens at all

Worth stating plainly, because §3.4's arithmetic points at it and the documents predict it in
prose without ever quantifying it: with the gate made genuinely falsifiable (§3.2), the honest
expected outcome is that **nothing passes it**. That is not a reason to weaken the gate —
decision gates G-D and G-E already contemplate exactly this and prescribe the right response.
It is a reason to do §3.4's arithmetic with your own broker's rate and your universe's measured
volatility *before* spending 6–10 weeks on P7 and P8. It is a day's work, and it may tell you
to keep the data product, skip the signal layer, and stop — which `SPEC.md` Part 6 already
predicts (*"expect a thin, fragile edge at best, especially on NGX"*).

The data layer's value does not depend on the answer.

---

## 9. What the audit found genuinely sound

Knowing where **not** to spend effort is half the value of an audit.

- **The mode gate's injection resistance.** Four vectors (body, header, query, cookie) tested in
  three places, promoted to an invariant, plus two scheduled adversarial sessions. *"Never
  consulted from the request"* is stated in five documents. **Stop testing injection** — the
  residual risk is derivation and non-request surfaces, not injection.
- **Mechanism 3's shape** — allow-list not deny-list, **500 not 403**, with the reasoning
  written out in three documents. Correct and correctly argued.
- **The router split as physical module trees** (*"not one router with an `if`"*), backed by a
  one-way import-linter rule. Right call, cheap, well-specified.
- **The Streamlit-reads-the-database hole is genuinely closed** — ADR-0003 plus `02 §2.3`:
  *"if you ever find yourself putting a connection string into `apps/streamlit/`, that is the
  defect"*, enforced by import-linter and a CI grep. `02 §1.3` separately forbids
  `if ENV == "local": mode = "personal"` — a specific real mistake, named and banned.
- **The instinct to push guarantees into database constraints** — `signals.backtest_run_id NOT
  NULL` plus a trigger, `redistribution_allowed NOT NULL`, the `memos` CHECK — with the
  rationale that *"application code can be bypassed at 1am by a person who is sure this one is
  fine."* Most of §2 above is simply applying that instinct in the places it was not yet applied.
- **The phase ↔ version ↔ task map is consistent in all four places it appears.** P0–P13,
  pre-v0.1→v2.5 and the T-assignments agree row for row. The strongest part of the set.
- **The DSR ≥ 0.95 threshold is consistent across six documents.** No drift.
- **`06 §6`'s twenty-row silent-failure catalogue** is better operational thinking than most
  production systems have.
- **`SPEC.md` is unusually honest** — Kirtac & Germano's Sharpe 3.05 is explicitly flagged as
  US-market and *"not a net-of-cost tradable edge on NGX"*; TradingAgents is flagged for likely
  leakage. Three claims escaped the discipline: FinBERT's "~85–87% F1" needs the same caveat;
  the "52–55% ceiling for liquid markets" never says NGX's is likely lower; and the DSR
  2.0→0.30 illustration is labelled illustrative in one place and repeated as fact in four.
- **`portfolios.account_equity` carries the comment `-- per-user parameter, NEVER a config
  constant`, and `size_position` takes equity as a keyword argument.** The multi-user sizing
  requirement — the expensive shortcut the whole plan warns about — is correctly specified. It
  is the *limits* around it that were missing (§2.4).
- **Zero secrets committed.** A regex sweep across every `.md`, `.json`, `.yaml` and `.env*`
  found no key, token, private key or credential.
- **Zero broken file links** across all sixteen documents (as distinct from anchors).

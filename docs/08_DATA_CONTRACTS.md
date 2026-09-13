# 08 — Data Contracts

**What this document is for.** The owner asked for "the expected inputs and outputs." This is
the precise answer. For every table, every module, every connector, and every HTTP endpoint in
the system, this document states exactly what goes in and exactly what comes out — the column
types, the units, the nullability, the failure modes, and a literal worked example. The other
documents in this set describe *what to build and when*; this one is the reference you open
mid-build when you need to know whether `value` is in naira or kobo, whether `known_as_of` may
be null, or what a `/public/*` endpoint is allowed to return. Where the roadmap documents give
an example, this document gives the definitive contract. Nothing here has been built yet — the
repo today contains only the six planning `.md` files, so treat every schema and signature
below as a specification to implement, not a description of code.

**Cross-links:** [00 START HERE](00_START_HERE.md) · [01 Architecture](01_ARCHITECTURE.md) ·
[02 Infrastructure](02_INFRASTRUCTURE.md) ·
[03 Roadmap P0–P6](03_ROADMAP_PART1_PHASES_0-6.md) ·
[04 Roadmap P7–P13](04_ROADMAP_PART2_PHASES_7-13.md) ·
[05 User Stories](05_USER_STORIES.md) · [06 Risk Register](06_RISK_REGISTER.md) ·
[07 Test Strategy](07_TEST_STRATEGY.md) · [09 Glossary](09_GLOSSARY.md)

---

## Table of contents

1. [How to read a contract here](#1-how-to-read-a-contract-here)
2. [The complete data model](#2-the-complete-data-model)
   - [2.0 Table map — every table, one line each](#20-table-map--every-table-one-line-each)
   - [2.1 Identity and reference tables](#21-identity-and-reference-tables)
   - [2.2 Source and extraction tables](#22-source-and-extraction-tables)
   - [2.3 Financial statement tables](#23-financial-statement-tables)
   - [2.4 Market data tables](#24-market-data-tables)
   - [2.5 Macro tables](#25-macro-tables)
   - [2.6 News and event tables](#26-news-and-event-tables)
   - [2.7 Indicator, feature and model tables](#27-indicator-feature-and-model-tables)
   - [2.8 Backtest tables](#28-backtest-tables)
   - [2.9 Signal, agent and memo tables](#29-signal-agent-and-memo-tables)
   - [2.10 Portfolio and transaction tables](#210-portfolio-and-transaction-tables)
   - [2.11 Alert tables](#211-alert-tables)
   - [2.12 Compliance, audit and identity tables](#212-compliance-audit-and-identity-tables)
   - [2.13 Operations tables](#213-operations-tables)
3. [The provenance record](#3-the-provenance-record)
4. [The canonical chart of accounts](#4-the-canonical-chart-of-accounts)
5. [Connector contract](#5-connector-contract)
6. [Module contracts](#6-module-contracts)
7. [The HTTP API contract](#7-the-http-api-contract)
8. [The signal and backtest_run contracts](#8-the-signal-and-backtest_run-contracts)
9. [Units, currency and rounding policy](#9-units-currency-and-rounding-policy)
10. [Contract change policy](#10-contract-change-policy)
11. [Appendix A — gaps surfaced by this document](#appendix-a--gaps-surfaced-by-this-document)
12. [Appendix B — implementation checklists by phase](#appendix-b--implementation-checklists-by-phase)

---

## 1. How to read a contract here

> **Precedence, set by the pre-build audit of 2026-08-30.** Where [SPEC.md §3.2](../SPEC.md)
> and this document define the same table differently, **this document wins**; SPEC.md §3.2 is
> superseded for every table restated here. Where a table is named in §2.0 but has no DDL
> below, its DDL is in [10_PRE_BUILD_CORRECTIONS](10_PRE_BUILD_CORRECTIONS.md) §2 — **never
> invented at the point of use.** The audit found six foreign keys pointing at tables that had
> no DDL in any document; an agent told not to invent them will invent them anyway, and the
> invention becomes the schema.

### 1.1 The four labels on every table

Every table in section 2 carries one of these labels. It tells you where the table comes from
and how much authority it has.

| Label | Meaning |
|---|---|
| **[Doc A §4.2]** | Defined in [DATA_FOUNDATION.md §4.2](../DATA_FOUNDATION.md) as a prose sketch. This document expands it to full DDL. Column names follow Doc A. |
| **[SPEC §3.2]** | Defined as literal DDL in [SPEC.md §3.2](../SPEC.md). Reproduced faithfully, then annotated. Where I add a column I say so explicitly. |
| **[OPERATIONS §1.x]** | Defined as literal DDL in [OPERATIONS.md](../OPERATIONS.md) Part 1. Reproduced faithfully, then annotated. These are the correctness tables that currently have **no task number** — gap **G2**. |
| **[PROPOSED]** | Does not exist in any source document. I am proposing it to close a gap. Style matches SPEC §3.2. Nothing downstream should assume it is settled until the owner accepts it — treat each as a decision to make, not a decision made. |

### 1.2 Column notation

Each table is presented as (a) the DDL, then (b) a column table with five columns:

| Column | What it tells you |
|---|---|
| **Column** | The exact column name. Always `snake_case`. |
| **Type** | The PostgreSQL type. **PostgreSQL 16 + TimescaleDB is the engine in every environment and every phase** ([ADR-0001](01_ARCHITECTURE.md), accepted 2026-08-30). There is no SQLite/DuckDB variant of this schema and no migration path to write — several correctness guarantees below depend on plpgsql triggers, partial unique indexes and `btree_gist` exclusion constraints, none of which have file-database equivalents. |
| **Null?** | `NOT NULL` means the row cannot exist without it. `NULL ok` means absence is meaningful — and section 1.4 defines exactly what that absence means. |
| **Unit** | The unit of measure. `—` where the column is not a quantity. This column exists because a number without a unit is the most common silent bug in a financial system ([OPERATIONS.md §1.6](../OPERATIONS.md)). |
| **Meaning** | Plain words. Written for someone reading this in six months having forgotten why the column exists. |

### 1.3 Date and time semantics — the six kinds of date

This is the part people get wrong, and getting it wrong produces a system that looks correct
and lies. There are six distinct date concepts here and they are **not** interchangeable.

| Name | The question it answers | Example |
|---|---|---|
| `date` / `ts` / `period_end` | *What point in time is this fact ABOUT?* | MTN Nigeria's FY2024 revenue is about `period_end = 2024-12-31`. |
| `as_of_date` | *As of what date is this value the current truth?* Usually equals the period the value describes. Used on display: "Revenue ₦3.36tn **as of 31 Dec 2024**". | `2024-12-31` |
| `known_as_of` | *From what date could a person outside the company have KNOWN this?* This is the point-in-time guard. MTN's FY2024 revenue was not knowable on 31 Dec 2024 — it became knowable when the audited statement was published. | If the annual financial statement published on 2025-03-14, then `known_as_of = 2025-03-14`. |
| `release_date` / `vintage` | The macro equivalent of `known_as_of`. NBS publishes January CPI in mid-February, so the January figure has `ts = 2025-01-31` and `release_date ≈ 2025-02-18`. A **vintage** is a snapshot of what a series looked like at a given release — revisions create a new vintage and never overwrite the old one ([DATA_FOUNDATION.md §4.2](../DATA_FOUNDATION.md); this is what FRED's ALFRED does). | `ts=2025-01-31`, `release_date=2025-02-18` |
| `retrieved_at` | *When did WE fetch this?* Provenance and cache invalidation only. Never used in a feature join. | `2026-08-14T22:04:11Z` |
| `valid_from` / `valid_to` | *Over what window was this attribute true?* Used for time-bounded attributes such as tickers and name aliases ([OPERATIONS.md §1.4](../OPERATIONS.md)). `valid_to IS NULL` means "still current". | GTBank became GTCO in 2021: ticker `GTB` valid until the changeover, ticker `GTCO` valid from it. **[NEEDS VERIFICATION]** — take the exact changeover date from the NGX announcement, never from memory. |

**The one rule that follows from this table, and the only one you must never break:**

> Any feature, label, indicator or backtest input joins on `known_as_of <= decision_date`.
> Never on `date <= decision_date`. ([SPEC.md §4.1](../SPEC.md) invariant 5.)

Joining on `date` instead of `known_as_of` is **look-ahead bias** — using information the
trader could not have had at the moment of the decision. It is the most common way a backtest
reports a profitable strategy that loses money live. It does not raise an error. It just makes
you rich on paper.

**Time zone rule.** Every `TIMESTAMPTZ` is stored in **UTC**, without exception. Display
converts to `Africa/Lagos` (West Africa Time, UTC+1, no daylight saving). Every plain `DATE`
column is a **calendar date in the market's own local time** — an NGX trading date is a Lagos
date, a NYSE trading date is a New York date. This matters: a US market close at 16:00 New York
time is already the next calendar day in UTC for part of the year, so deriving US bar dates
from UTC timestamps would shift half the year's bars by one day.

### 1.4 The null rule — absent means absent

From [SPEC.md §4.1](../SPEC.md) invariant 4 and
[DATA_FOUNDATION.md §3.2](../DATA_FOUNDATION.md):

> **Never infer missing financial data.** An absent line item is `NULL`. It is never `0`, never
> a carried-forward prior value, never an interpolation, and never a model estimate.

Concretely, in `statement_line_items`:

| Situation | `value` | `as_printed` | Why |
|---|---|---|---|
| The statement prints "Revenue 3,360,000" (in thousands) | `3360000000000` | `"3,360,000"` | Present, scaled exactly once (§9). |
| The statement prints "Revenue —" or a dash | `NULL` | `"—"` | The company reported nothing there. We record nothing. |
| The line item does not appear at all | no row at all, or a row with `value = NULL` and `as_printed = NULL` | | Either is acceptable; be consistent per statement template. |
| The extractor could not read the number | `NULL`, `needs_review = TRUE`, low `confidence` | the raw OCR string if any | Absence of *knowledge*, not absence of *fact* — flagged for a human. |
| The statement prints "0" | `0` | `"0"` | Zero is a value. It is not the same as missing. |

The distinction between `NULL` (unknown or absent) and `0` (reported as zero) has to survive
every layer. A ratio engine that treats `NULL` as `0` will publish a debt-to-equity of 0.0 for a
company whose debt line simply was not extracted. That is a wrong number presented with exactly
the same confidence as a right one, which is the failure this entire project exists to avoid.

**Enforcement:** `/packages/valuation` and `/packages/ml` raise on `NULL` inputs rather than
coerce them. See §6.3 and §6.5.

### 1.5 Currency and units — the short version

The full policy is §9. Three rules are enough to read section 2:

1. **Every monetary column stores a fully-scaled value in the *major* unit of its currency** —
   naira, not kobo; dollars, not cents. `3360000000000` means ₦3.36 trillion.
2. **Every monetary value has a currency**, either through a `currency` column on its own row or
   inherited from a named parent row (the column table states which).
3. **Scaling happens exactly once**, in the extractor, at write time
   ([OPERATIONS.md §1.6](../OPERATIONS.md)). `unit_multiplier` is retained for provenance and
   audit, **not** for anyone downstream to multiply by again.

### 1.6 Types on the Python side

Every boundary in the system is a **Pydantic v2 model** ([DATA_FOUNDATION.md §7.3](../DATA_FOUNDATION.md)).
Pydantic is a Python library that validates data against a declared type at runtime; "at every
boundary" means data is checked the moment it enters or leaves a module, not deep inside it. The
mapping from SQL type to Python type is fixed:

| SQL | Python | Note |
|---|---|---|
| `NUMERIC` | `decimal.Decimal` | **Money is always `Decimal`, never `float`.** In binary floating point `0.1 + 0.2 != 0.3`; a portfolio that accumulates float rounding drifts away from the broker's contract notes and you will never find out why. |
| `DOUBLE PRECISION` | `float` | Statistical values only — indicator values, model scores, Sharpe ratios. Precision loss is irrelevant there; speed is not. |
| `DATE` | `datetime.date` | Never a string, never a datetime. |
| `TIMESTAMPTZ` | `datetime.datetime` with `tzinfo=UTC` | Naive datetimes are rejected at the boundary. |
| `TEXT` with a fixed set of values | `enum.StrEnum` | e.g. `ActionType`, `StatementType`. A free-text status column is a bug waiting to happen. |
| `JSONB` | a typed Pydantic model, serialised | Never `dict[str, Any]` in a signature. If it is JSON in the database it still has a schema in Python. |
| `BOOLEAN` | `bool` | |

### 1.7 Risk markers

Applied to contracts likely to churn, per the convention shared across this document set:

- 🟢 **SOLID** — well understood, low variance. Failure is obvious and cheap to fix. No reason
  to worry here.
- 🟡 **WATCH** — will work, but has a known failure mode, a cost curve, or a dependency that can
  move. Each one states the early-warning signal to watch for.
- 🔴 **FRAGILE** — genuinely likely to go wrong, or the design could take multiples of the
  expected effort. **Every 🔴 item gives three distinct approaches with trade-offs and a
  recommendation.**

A contract with no marker is unremarkable — standard, and not worth your attention.

### 1.8 Honesty note about the sample rows

Every table in section 2 has a sample row. **The shapes are contracts; most of the numbers are
illustrative.** Where a figure comes from the planning documents I mark it `[sourced]` and cite
it. Everything else — prices, volumes, share counts, specific filing dates — is invented to show
the shape of a row and **must never be treated as real market data**. Real tickers (MTNN, GTCO,
DANGCEM, AAPL) appear because abstract placeholders make contracts harder to read, not because
the attached numbers are real.

Figures that *are* sourced and that you can rely on:

| Figure | Value | Source |
|---|---|---|
| MTN Nigeria FY2024 revenue | ₦3.36 trillion (up 36%) | [DATA_FOUNDATION.md §3.3](../DATA_FOUNDATION.md) |
| MTN Nigeria FY2024 loss after tax | ₦400.44 billion | [DATA_FOUNDATION.md §3.3](../DATA_FOUNDATION.md) |
| MTN Nigeria FY2024 net FX losses | ₦925.36 billion, from ₦740.43bn in 2023 | [DATA_FOUNDATION.md §3.3](../DATA_FOUNDATION.md) |
| NGN/USD end-2023 to end-2024 | ₦907.1 to ₦1,535 | [DATA_FOUNDATION.md §3.3](../DATA_FOUNDATION.md) |
| Nigeria headline CPI Jan 2025 | 24.48% y/y (all-items index 110.7 on 2024=100); Dec 2024 was 34.80% | [DATA_FOUNDATION.md Key Findings](../DATA_FOUNDATION.md) |
| FRED series `FPCPITOTLZGNGA`, 2024 | 33.24% | [DATA_FOUNDATION.md Key Findings](../DATA_FOUNDATION.md) |
| Dividend withholding tax, Nigeria | 10% | [SPEC.md §2H](../SPEC.md) |
| NGX settlement | T+3 | [SPEC.md §2C, §2H](../SPEC.md) |
| NGX daily price band | ±10%, **halts** the stock for the day when hit | [SPEC.md §2C](../SPEC.md) |

---

## 2. The complete data model

### 2.0 Table map — every table, one line each

Tables marked **[proposed]** do not exist in any source document. They close a gap (TG-number
given) and their DDL here is this document's proposal, written in the same style as
[SPEC.md §3.2](../SPEC.md). Everything else derives from
[SPEC.md §3.2](../SPEC.md) or [DATA_FOUNDATION.md §4.2](../DATA_FOUNDATION.md).

| # | Table | Purpose | Phase | Source |
|---|---|---|---|---|
| 1 | `companies` | The legal entity | P2 | Doc A |
| 2 | `securities` | A tradeable instrument; **retains delisted rows** | P2 | Doc A |
| 3 | `security_identifiers` | Ticker history, time-bounded | P3 | **[proposed]** TG2 |
| 4 | `exchanges` | NGX, NASDAQ, NYSE | P2 | Doc A |
| 5 | `trading_calendar` | Which days each exchange was open | P3 | **[proposed]** TG2 |
| 6 | `industries` | Sector classification; drives the statement template | P2 | Doc A |
| 7 | `data_sources` | Licensing register — the redistribution gate | P0 | **[proposed]** TG5 |
| 8 | `source_documents` | Every raw file ever fetched, immutable | P1 | Doc A |
| 9 | `extraction_jobs` | One run of the pipeline over one document | P4 | Doc A |
| 10 | `extraction_examples` | Corrections recycled as few-shot examples | P4 | **[proposed]** |
| 11 | `filings` | A regulatory filing (10-K, annual report) | P2 | Doc A |
| 12 | `statements` | One statement within a filing, versioned | P2 | Doc A |
| 13 | `statement_line_items` | **The core table.** One figure, with provenance | P2 | Doc A |
| 14 | `chart_of_accounts` | Canonical keys, versioned | P2 | **[proposed]** TG7 |
| 15 | `account_mappings` | Source label → canonical key | P2 | **[proposed]** TG7 |
| 16 | `price_history` | Daily OHLCV, raw and adjusted | P2/P4 | **[proposed]** TG1 |
| 17 | `corporate_actions` | Splits, bonuses, rights, dividends | P3 | **[proposed]** TG2 |
| 18 | `adjustment_factors` | Point-in-time price adjustment series | P3 | **[proposed]** TG2 |
| 19 | `fx_rates` | Rates as a first-class dated table | P3 | **[proposed]** TG2 |
| 20 | `macro_series` | Series definitions | P1 | Doc A |
| 21 | `macro_observations` | Values, with vintages | P1 | Doc A |
| 22 | `news_items` | Articles from RSS | P5 | Doc A |
| 23 | `news_tags` | Article → security | P5 | Doc A |
| 24 | `news_sentiment` | Scores, with model and version | P5 | Doc A |
| 25 | `security_aliases` | "GTBank" → `security_id` | P3 | Doc A |
| 26 | `indicators` | Per (security, date, name, param_hash) | P6 | [SPEC.md §3.2](../SPEC.md) |
| 27 | `ml_features` | Point-in-time feature store | P8 | [SPEC.md §3.2](../SPEC.md) |
| 28 | `ml_models` | Trained model registry | P8 | [SPEC.md §3.2](../SPEC.md) |
| 29 | `backtest_runs` | Every run, with K and DSR | P7 | [SPEC.md §3.2](../SPEC.md) |
| 30 | `backtest_trades` | Per-trade blotter | P7 | **[proposed]** |
| 31 | `signals` | **Cannot exist without a passing backtest** | P8 | [SPEC.md §3.2](../SPEC.md) |
| 32 | `memos` | Multi-agent research output | P9 | **[proposed]** |
| 33 | `memo_citations` | Every claim → source document + page | P9 | **[proposed]** |
| 34 | `portfolios` | Owned by a principal | P10 | [SPEC.md §3.2](../SPEC.md) |
| 35 | `positions` | Current holdings | P10 | [SPEC.md §3.2](../SPEC.md) |
| 36 | `transactions` | Buy, sell, dividend, corporate action | P10 | Doc A |
| 37 | `tax_lots` | For CGT and the rolling 12-month test | P10 | **[proposed]** |
| 38 | `watchlists` / `watchlist_items` | Per principal | P0 | **[proposed]** TG11 |
| 39 | `alerts` | Rules, per principal | P10 | [SPEC.md §3.2](../SPEC.md) |
| 40 | `alert_deliveries` | Idempotency by content hash | P10 | [SPEC.md §3.2](../SPEC.md) |
| 41 | `principals` | Who can authenticate | P0 | **[proposed]** TG3 |
| 42 | `entitlements` | What tier each principal reaches | P0 | **[proposed]** TG3 |
| 43 | `principal_tokens` | Hashed bearer tokens (was `sessions` — renamed §2.15) | P0 | **[proposed]** TG3 |
| 44 | `system_config` | `licence_status` and other dated config | P0 | **[proposed]** |
| 45 | `audit_log` | Every request | P0 | [SPEC.md §3.2](../SPEC.md) |
| 46 | `connector_runs` | Health — the silent-failure detector | P1 | [OPERATIONS.md §2.3](../OPERATIONS.md) |
| 47 | `llm_spend` | Per-principal cost tracking | P4 | **[proposed]** |
| 48 | `adr_log` | Optional mirror of `docs/adr/` | P0 | [OPERATIONS.md §3.1](../OPERATIONS.md) |
| 49 | `shares_outstanding` | Share count as of a date — **without it every P/E is wrong** | P2 | **[proposed]** §2.14 |
| 50 | `persons` | Directors and officers | P2 (empty) / P4 | **[proposed]** §2.14 |
| 51 | `entity_roles` | Board seats and executive roles, dated | P2 (empty) / P4 | **[proposed]** §2.14 |
| 52 | `shareholdings` | Substantial shareholders (>5%) | P2 (empty) / P4 | **[proposed]** §2.14 |
| 53 | `company_relationships` | Parent, subsidiary, auditor, related party, major customer | P2 (empty) / P4 | **[proposed]** §2.14 |
| 54 | `index_membership` | Point-in-time index constituents — **required by P7 check 11** | P2 (empty) / P3 | **[proposed]** §2.14 |

### 2.1 Identity and reference tables

**Why a surrogate key.** Everything joins on `security_id`, never on a ticker string. Tickers get
reused and companies rename; keying on the ticker silently merges two unrelated companies'
histories ([OPERATIONS.md §1.4](../OPERATIONS.md)). This is not defensive over-engineering — it
is the difference between a correct series and a plausible wrong one.

> **Order matters in this section.** `exchanges` and `industries` are declared first because
> `companies` and `securities` reference them. Both were referenced by six foreign keys and
> defined in no document until the pre-build audit of 2026-08-30 — the first `alembic upgrade
> head` failed on them.

```sql
CREATE TABLE exchanges (
  id              SERIAL PRIMARY KEY,
  code            TEXT NOT NULL UNIQUE,        -- 'NGX','NASDAQ','NYSE','LSE'
  name            TEXT NOT NULL,
  country         CHAR(2) NOT NULL,
  timezone        TEXT NOT NULL,               -- 'Africa/Lagos' — TG21 depends on this
  settlement_days SMALLINT NOT NULL            -- NGX = 3. Never hardcode T+3 in code.
);

CREATE TABLE industries (
  id                 SERIAL PRIMARY KEY,
  scheme             TEXT NOT NULL,            -- 'ngx_sector'|'gics'|'sic'
  code               TEXT NOT NULL,
  name               TEXT NOT NULL,
  statement_template TEXT NOT NULL,            -- default template for the sector
  UNIQUE (scheme, code)
);

CREATE TABLE companies (
  id              SERIAL PRIMARY KEY,
  legal_name      TEXT NOT NULL,
  country         CHAR(2) NOT NULL,            -- ISO 3166-1: 'NG', 'US'
  industry_id     INT REFERENCES industries(id),
  statement_template TEXT NOT NULL,            -- DEFAULT ONLY — the authoritative value lives
                                               -- on statements.statement_template (§2.3).
                                               -- 'non_financial'|'bank'|'insurance'|'both'.
                                               -- Insurers are a THIRD shape: gross premium
                                               -- written, net claims incurred, technical
                                               -- reserves — neither a bank nor a normal
                                               -- company. See §4.
  fiscal_year_end SMALLINT NOT NULL,           -- month, 1-12. NOT every company is December.
  cik             TEXT,                        -- US only, zero-padded to 10
  rc_number       TEXT,                        -- Nigerian CAC registration
  created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE securities (
  id            SERIAL PRIMARY KEY,
  company_id    INT NOT NULL REFERENCES companies(id),
  exchange_id   INT NOT NULL REFERENCES exchanges(id),
  currency      CHAR(3) NOT NULL,              -- 'NGN', 'USD'
  listed_date   DATE,
  delisted_date DATE,                          -- NOT NULL means delisted. NEVER delete the row.
  is_active     BOOLEAN GENERATED ALWAYS AS (delisted_date IS NULL) STORED
);
```

> **`delisted_date` is the survivorship-bias defence.** [SPEC.md §2C](../SPEC.md) requires
> delisted securities in backtests. Deleting a delisted row makes survivorship bias structurally
> unavoidable and silently inflates every historical result.

```sql
-- [proposed] TG2 — OPERATIONS §1.4
CREATE TABLE security_identifiers (
  id           SERIAL PRIMARY KEY,
  security_id  INT NOT NULL REFERENCES securities(id),
  id_type      TEXT NOT NULL,                  -- 'ticker' | 'isin' | 'cusip' | 'sedol'
  id_value     TEXT NOT NULL,
  valid_from   DATE NOT NULL,
  valid_to     DATE,                           -- NULL = still current
  UNIQUE (id_type, id_value, valid_from)
);
CREATE INDEX ON security_identifiers (id_type, id_value, valid_from, valid_to);
```

Sample — a rename, correctly modelled:

| id | security_id | id_type | id_value | valid_from | valid_to |
|---|---|---|---|---|---|
| 1 | 44 | ticker | GUARANTY | 1996-01-01 | 2021-07-31 |
| 2 | 44 | ticker | GTCO | 2021-08-01 | NULL |

Both rows point at `security_id` 44. The price history never splits.

```sql
-- [proposed] TG2 — OPERATIONS §1.2
CREATE TABLE trading_calendar (
  exchange_id INT NOT NULL REFERENCES exchanges(id),
  date        DATE NOT NULL,
  is_open     BOOLEAN NOT NULL,
  session_note TEXT,                           -- 'public holiday: Eid al-Fitr'
  PRIMARY KEY (exchange_id, date)
);
```

Without this, a missing price row is ambiguous — closed market or failed scraper? You cannot
alert on one without false-alarming on the other.

### 2.2 Source and extraction tables

```sql
-- [proposed] TG5 — the licensing gate. CLAUDE.md hard rule.
CREATE TABLE data_sources (
  id                     SERIAL PRIMARY KEY,
  source_name            TEXT NOT NULL UNIQUE,
  base_url               TEXT,
  licence_type           TEXT NOT NULL,
  redistribution_allowed BOOLEAN NOT NULL,     -- NOT NULL is the whole mechanism
  attribution_required   BOOLEAN NOT NULL,
  attribution_text       TEXT,
  terms_url              TEXT,
  terms_reviewed_on      DATE NOT NULL,
  reviewed_by            TEXT NOT NULL,
  rate_limit_per_sec     NUMERIC,
  notes                  TEXT
);
```

> **Why `redistribution_allowed` is `NOT NULL`.** It forces an answer at registration time. A
> connector whose source row is absent or incomplete **cannot be enabled** — the base class
> raises. [PROJECT_CONTEXT.md §9.3](../PROJECT_CONTEXT.md) calls the redistribution question
> "the one that kills deals"; this column is that question, asked once per source, permanently
> recorded. See [04_ROADMAP_PART2_PHASES_7-13.md](04_ROADMAP_PART2_PHASES_7-13.md) §P12.

| id | source_name | licence_type | redistribution_allowed | attribution_required | terms_reviewed_on |
|---|---|---|---|---|---|
| 1 | SEC EDGAR | public domain | true | false | 2026-08-28 |
| 2 | FRED | public, attribution | true | true | 2026-08-28 |
| 3 | NGX market data | Data Agreement | **false** | true | 2026-08-28 |

Row 3 is the one that matters: NGX data may be used internally and **may not be re-served raw**
([DATA_FOUNDATION.md §6.3](../DATA_FOUNDATION.md)). Derived analytics only.

```sql
CREATE TABLE source_documents (
  id            BIGSERIAL PRIMARY KEY,
  data_source_id INT NOT NULL REFERENCES data_sources(id),
  url           TEXT,
  storage_key   TEXT NOT NULL,                 -- object-storage path; immutable
  sha256        CHAR(64) NOT NULL UNIQUE,      -- dedupe; proves the file never changed
  media_type    TEXT NOT NULL,                 -- 'application/pdf'
  page_count    INT,
  retrieved_at  TIMESTAMPTZ NOT NULL,
  http_status   INT,
  etag          TEXT,                          -- avoids re-fetching unchanged documents
  last_modified TIMESTAMPTZ
);
```

**A reissued report is a new row, never an edit.** The `sha256` unique constraint enforces it.
Every extracted figure points at a page in *this exact file*, forever — including after the
source website is gone.

```sql
CREATE TABLE extraction_jobs (
  id                 BIGSERIAL PRIMARY KEY,
  source_document_id BIGINT NOT NULL REFERENCES source_documents(id),
  method             TEXT NOT NULL,            -- 'manual' | 'llm_hybrid' | 'xbrl'
  model_name         TEXT,
  prompt_version     TEXT,
  status             TEXT NOT NULL,            -- 'pending'|'stored'|'needs_review'|'corrected'|'failed'
  confidence         NUMERIC,
  validation_failures JSONB NOT NULL DEFAULT '[]',
  token_cost_usd     NUMERIC,
  started_at         TIMESTAMPTZ NOT NULL,
  finished_at        TIMESTAMPTZ,
  reviewed_by        TEXT,
  reviewed_at        TIMESTAMPTZ
);
```

`prompt_version` matters: when extraction quality shifts, the first question is what changed, and
the prompt is usually the answer.

### 2.3 Financial statement tables — the core

> **`statements` is the most expensive omission the pre-build audit found.** Without
> `period_type`, MTN's Q4-2024 revenue and its FY-2024 revenue both arrive as
> `period_end = 2024-12-31` on the same `canonical_key`. They are different numbers.
> `period_start` is nullable and Nigerian quarterly filings routinely omit it, so nothing
> distinguishes them. Every ratio, every year-on-year growth feature and every backtest label
> built on that key would be wrong — and the only recovery is re-extraction.

```sql
CREATE TABLE filings (
  id                 BIGSERIAL PRIMARY KEY,
  company_id         INT NOT NULL REFERENCES companies(id),
  filing_type        TEXT NOT NULL,            -- '10-K'|'10-Q'|'annual_report'|'interim'
  filing_date        DATE NOT NULL,            -- when the regulator/company published it
  period_end         DATE NOT NULL,
  accession_no       TEXT,                     -- EDGAR only
  source_document_id BIGINT NOT NULL REFERENCES source_documents(id),
  known_as_of        DATE NOT NULL,
  created_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (company_id, filing_type, period_end, filing_date)
);

CREATE TABLE statements (
  id                      BIGSERIAL PRIMARY KEY,
  filing_id               BIGINT REFERENCES filings(id),
  company_id              INT NOT NULL REFERENCES companies(id),
  statement_type          TEXT NOT NULL,       -- 'income'|'balance'|'cashflow'|'equity'
  period_type             TEXT NOT NULL,       -- 'FY'|'H1'|'Q1'|'Q2'|'Q3'|'Q4'|'YTD'
  period_start            DATE,
  period_end              DATE NOT NULL,
  fiscal_year             INT NOT NULL,        -- OPERATIONS §1.5 fiscal alignment
  calendar_year           INT NOT NULL,        -- the calendar year containing period_end
  period_label            TEXT NOT NULL,       -- 'FY2024','Q3-2025' as the company labels it
  presentation_currency   CHAR(3) NOT NULL,
  presentation_multiplier INT NOT NULL DEFAULT 1,  -- the document header's declared scale
  is_audited              BOOLEAN NOT NULL DEFAULT false,
  is_consolidated         BOOLEAN NOT NULL DEFAULT true,  -- NG filings carry BOTH. Never mix.
  statement_template      TEXT NOT NULL,       -- authoritative here, not on companies:
                                               -- GTCO restructured into a holdco, so the
                                               -- template changed while old statements kept
                                               -- their original shape
  chart_version           TEXT NOT NULL,
  version                 INT NOT NULL DEFAULT 1,
  superseded_by           BIGINT REFERENCES statements(id),
  restatement_flag        BOOLEAN NOT NULL DEFAULT false,
  known_as_of             DATE NOT NULL,
  source_document_id      BIGINT NOT NULL REFERENCES source_documents(id),
  created_at              TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (company_id, statement_type, period_type, period_end, is_consolidated, version)
);

CREATE TABLE statement_line_items (
  id                 BIGSERIAL PRIMARY KEY,
  statement_id       BIGINT NOT NULL REFERENCES statements(id),
  security_id        INT NOT NULL REFERENCES securities(id),
  canonical_key      TEXT NOT NULL,
  chart_version      TEXT NOT NULL,            -- TG7: which vocabulary version
  -- COMPOSITE, because chart_of_accounts has a composite PK. A single-column FK is
  -- invalid SQL here and Postgres rejects it; dropping the FK instead would silently
  -- permit line items whose key exists in no chart version, defeating TG7 entirely.
  FOREIGN KEY (canonical_key, chart_version)
    REFERENCES chart_of_accounts (canonical_key, chart_version),
  as_printed_label   TEXT,                     -- the ROW LABEL, e.g. 'Gross earnings'
  as_printed_value   TEXT,                     -- the NUMERAL exactly as printed: '3,360,000'
  as_printed_scale   TEXT,                     -- 'thousands'|'millions'|'units', as declared
  needs_review       BOOLEAN NOT NULL DEFAULT false,  -- routes the HITL queue (Doc A §4.2)
  value              NUMERIC,                  -- NULL = absent. NEVER 0 for missing.
  currency           CHAR(3) NOT NULL,
  unit_multiplier    INT NOT NULL DEFAULT 1,   -- 1000 if reported in thousands
  period_start       DATE,
  period_end         DATE NOT NULL,            -- the as-of date
  known_as_of        DATE NOT NULL,            -- when it became public
  version            INT NOT NULL DEFAULT 1,
  superseded_by      BIGINT REFERENCES statement_line_items(id),
  restatement_flag   BOOLEAN NOT NULL DEFAULT false,
  -- provenance, per CLAUDE.md
  source_document_id BIGINT NOT NULL REFERENCES source_documents(id),
  page               INT,
  bbox               JSONB,                    -- coordinates where available
  extraction_job_id  BIGINT REFERENCES extraction_jobs(id),
  extraction_method  TEXT NOT NULL,
  confidence         NUMERIC,
  reviewed_by        TEXT,
  corrected_by       TEXT,
  corrected_at       TIMESTAMPTZ,
  correction_reason  TEXT,
  created_at         TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX ON statement_line_items (security_id, canonical_key, known_as_of DESC, version DESC);
```

**Four rules encoded in this one table:**

| Rule | Column | Consequence of getting it wrong |
|---|---|---|
| Never infer missing data ([SPEC.md §4.1](../SPEC.md)) | `value` nullable | A zero flows into every ratio as a real figure |
| Provenance on every figure ([CLAUDE.md](../CLAUDE.md)) | `source_document_id` **NOT NULL**, `page` | Unverifiable numbers |
| Point-in-time ([SPEC.md §4.1](../SPEC.md)) | `known_as_of` separate from `period_end` | Lookahead bias; a backtest that lies |
| No silent overwrites ([CLAUDE.md](../CLAUDE.md)) | `version`, `superseded_by` | History destroyed; point-in-time impossible |

Sample — a restatement, correctly modelled. **Both rows live forever:**

| id | security_id | canonical_key | value | period_end | known_as_of | version | superseded_by | reason |
|---|---|---|---|---|---|---|---|---|
| 5001 | 12 | revenue | 100000000000 | 2024-12-31 | 2025-03-14 | 1 | 5188 | NULL |
| 5188 | 12 | revenue | 85000000000 | 2024-12-31 | 2025-09-02 | 2 | NULL | FY24 restated |

A backtest with a decision date of 2025-06-01 must return **row 5001** — ₦100bn, the figure the
market actually had. See [01_ARCHITECTURE.md](01_ARCHITECTURE.md) §5 for the query pattern.

```sql
-- [proposed] TG7 — the canonical vocabulary, versioned
CREATE TABLE chart_of_accounts (
  canonical_key   TEXT NOT NULL,
  chart_version   TEXT NOT NULL,
  statement       TEXT NOT NULL,               -- 'income'|'balance'|'cashflow'
  template        TEXT NOT NULL,               -- 'financial'|'non_financial'|'both'
  display_name    TEXT NOT NULL,
  sign_convention TEXT NOT NULL,               -- 'positive'|'negative'|'either'
  is_required     BOOLEAN NOT NULL DEFAULT false,
  PRIMARY KEY (canonical_key, chart_version)
);

CREATE TABLE account_mappings (
  id            SERIAL PRIMARY KEY,
  chart_version TEXT NOT NULL,
  source_system TEXT NOT NULL,                 -- 'us_gaap_xbrl'|'ng_ifrs_label'
  source_label  TEXT NOT NULL,
  canonical_key TEXT NOT NULL,
  template      TEXT NOT NULL,
  priority      SMALLINT NOT NULL DEFAULT 100, -- added P2.1: resolution order among
                                               -- alternate labels for one key; lowest wins
  confidence    NUMERIC NOT NULL DEFAULT 1.0,
  added_by      TEXT NOT NULL,
  FOREIGN KEY (canonical_key, chart_version)
    REFERENCES chart_of_accounts (canonical_key, chart_version),
  UNIQUE (chart_version, source_system, source_label, template)
);
```

> **Why mappings are a table, not a Python dict.** A human edits this many times, and a table
> gives versioning, an audit trail, and the ability to see what changed — for free. TG7's real
> danger is that changing the chart after the extractor has run over 200 company-years means
> **re-extracting all of them**. `chart_version` turns that catastrophe into a migration.

> **An alternate label must name the *same* measure** (added 2026-09-13, from P2.1). XBRL offers
> several tags for one concept and a filer uses one, so `revenue` maps from `Revenues`,
> `RevenueFromContractWithCustomerExcludingAssessedTax` and `SalesRevenueNet` in `priority`
> order. What must **not** be admitted is an alternate whose value can legitimately differ from
> the primary's — `CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalents` beside
> `CashAndCashEquivalentsAtCarryingValue`, `ProfitLoss` beside `NetIncomeLoss`, `LongTermDebt`
> beside `LongTermDebtNoncurrent`. A later filing that carries only the alternate then resolves
> the same period to a different number, and the writer records a restatement that never
> happened. Apple's 10-Q comparatives produced six false restatements of cash before a single
> real one. A company that reports only the excluded tag gets a NULL, which is honest.

### 2.4 Market data tables

```sql
-- [proposed] TG1 — no SPEC task creates this, yet T9 and T11 both require it
CREATE TABLE price_history (
  security_id  INT NOT NULL REFERENCES securities(id),
  date         DATE NOT NULL,
  open_raw     NUMERIC, high_raw NUMERIC, low_raw NUMERIC,
  close_raw    NUMERIC NOT NULL,               -- AS TRADED. Never overwrite.
  volume       BIGINT,                         -- required: participation caps need it
  vwap         NUMERIC,
  -- NO close_adj COLUMN. A stored adjusted price is a single global vintage: it
  -- embeds every corporate action known at the time it was computed, INCLUDING
  -- actions announced after the decision date. Adjusted prices are computed on
  -- read -- adjusted_close(security_id, date, decision_date) -- per OPERATIONS
  -- §1.1 hard rule 2. See the note below.
  halted       BOOLEAN NOT NULL DEFAULT false, -- NGX ±10% band hit: HALTS for the day
  data_source_id INT NOT NULL REFERENCES data_sources(id),
  source_document_id BIGINT NOT NULL REFERENCES source_documents(id),
  known_as_of  DATE NOT NULL,
  -- known_as_of IS IN THE KEY. Exchanges restate settlement prices and scrapers get
  -- re-run; without it a re-run UPDATEs and the original bar is gone -- a silent
  -- overwrite on the most-read table in the system.
  PRIMARY KEY (security_id, date, known_as_of)
);
```

> **`close_raw` and `close_adj` are separate columns and raw is never overwritten.**
> [SPEC.md §2C](../SPEC.md) names the "adjusted-price sin" as a distinct bias: *"store raw prices
> + a separate adjustment-factor series; reconstruct point-in-time adjusted prices only up to the
> decision date; never mix."* An adjustment you have destroyed cannot be recomputed when you
> discover the corporate action was recorded wrong.
>
> **Which to use:** anything analysing a price series calls
> `adjusted_close(security_id, date, decision_date)`, which applies only the adjustment factors
> whose `known_as_of <= decision_date`. Anything reporting an actual historical trade price
> reads `close_raw`. They are never interchangeable.
>
> **Corrected 2026-08-30.** This document previously specified a stored `close_adj` column plus
> `adj_computed_at`, and US-061 mandated that indicators read it. That is the adjusted-price sin
> the paragraph above forbids: one stored column is one global vintage, so a corporate action
> announced late silently rewrites history a backtest has already consumed, and P7 check 19
> ("adjustment reflects only actions before the decision date") could never pass. The column is
> removed; the function replaces it.

```sql
-- [proposed] TG2 — OPERATIONS §1.1, "the highest-priority gap"
CREATE TABLE corporate_actions (
  id            SERIAL PRIMARY KEY,
  security_id   INT NOT NULL REFERENCES securities(id),
  action_type   TEXT NOT NULL,       -- 'split'|'bonus'|'rights'|'dividend'|'consolidation'
  announcement_date DATE,
  ex_date       DATE NOT NULL,       -- the date that matters for adjustment
  record_date   DATE,
  pay_date      DATE,
  ratio_from    NUMERIC,             -- split 1:2 -> from 1, to 2
  ratio_to      NUMERIC,
  cash_amount   NUMERIC,             -- dividends, per share, gross
  subscription_price NUMERIC,        -- rights issues: required for the TERP calculation
  currency      CHAR(3),
  -- NOT NULL: OPERATIONS §1.1 rule 4 gives corporate actions the same provenance
  -- treatment as line items, and hand-collected NGX actions are the hardest data in
  -- the system to re-source.
  source_document_id BIGINT NOT NULL REFERENCES source_documents(id),
  confidence    NUMERIC,
  needs_review  BOOLEAN NOT NULL DEFAULT false,
  known_as_of   DATE NOT NULL,
  UNIQUE (security_id, ex_date, action_type)
);

-- TG12 -- raised to BLOCKER and moved to P0 by the pre-build audit. OPERATIONS §1.1
-- already had known_as_of and action_id; an earlier draft of THIS document dropped
-- them, then logged the resulting hole as a new gap. The fix predates the gap.
CREATE TABLE adjustment_factors (
  id          BIGSERIAL PRIMARY KEY,
  security_id INT  NOT NULL REFERENCES securities(id),
  ex_date     DATE NOT NULL,
  action_id   INT  NOT NULL REFERENCES corporate_actions(id),
  factor      NUMERIC NOT NULL,      -- cumulative multiplier applied to prices BEFORE ex_date
  known_as_of DATE NOT NULL,         -- when this factor became knowable. A corporate action
                                     -- CAN be announced after its own ex-date -- that is
                                     -- exactly the leak this column closes.
  UNIQUE (security_id, ex_date, action_id, known_as_of)
);
```

The worked example, because it is the bug that costs most: a 2-for-1 split on a ₦100 stock leaves
every holder exactly as wealthy, but raw prices show ₦100 → ₦50 — a 50% crash. RSI reads deeply
oversold, volatility doubles, and a backtest books a catastrophic loss that never happened.
**Nothing raises an error.** See [01_ARCHITECTURE.md](01_ARCHITECTURE.md) §7.1.

```sql
-- [proposed] TG2 — OPERATIONS §1.3
CREATE TABLE fx_rates (
  base_currency  CHAR(3) NOT NULL,
  quote_currency CHAR(3) NOT NULL,
  rate_type      TEXT NOT NULL,       -- 'nfem_official'|'parallel'|'closing'|'period_average'
  as_of_date     DATE NOT NULL,
  rate           NUMERIC NOT NULL,
  data_source_id INT NOT NULL REFERENCES data_sources(id),
  known_as_of    DATE NOT NULL,
  PRIMARY KEY (base_currency, quote_currency, rate_type, as_of_date)
);
```

| base | quote | rate_type | as_of_date | rate | note |
|---|---|---|---|---|---|
| USD | NGN | nfem_official | 2023-12-29 | 907.1 | `[sourced]` |
| USD | NGN | nfem_official | 2024-12-31 | 1535.0 | `[sourced]` |

**That is a 69% move in twelve months** ([DATA_FOUNDATION.md §3.3](../DATA_FOUNDATION.md)).
Converting a 2023 Naira figure at the 2024 rate is not a rounding error — it is wrong by a large
multiple. **Every conversion takes a date.** A conversion function without a date parameter is a
defect ([OPERATIONS.md §1.3](../OPERATIONS.md)).

### 2.5 Macro tables

```sql
CREATE TABLE macro_series (
  id                SERIAL PRIMARY KEY,
  code              TEXT NOT NULL UNIQUE,      -- 'NG_CPI_YOY', 'FEDFUNDS'
  name              TEXT NOT NULL,
  data_source_id    INT NOT NULL REFERENCES data_sources(id),
  unit              TEXT NOT NULL,             -- 'percent'|'index'|'ngn_billions'
  frequency         TEXT NOT NULL,
  expected_lag_days INT NOT NULL,              -- drives the staleness flag
  base_period       TEXT,                      -- 'CPI 2024=100' — rebasing changes history
  seasonal_adjustment TEXT
);

CREATE TABLE macro_observations (
  series_id   INT NOT NULL REFERENCES macro_series(id),
  as_of_date  DATE NOT NULL,                   -- the period described
  known_as_of DATE NOT NULL,                   -- when published (FRED: realtime_start)
  value       NUMERIC,
  revision    INT NOT NULL DEFAULT 1,
  source_document_id BIGINT REFERENCES source_documents(id),
  PRIMARY KEY (series_id, as_of_date, known_as_of)
);
```

**`known_as_of` in the primary key is what makes vintages work.** Nigerian CPI for August is
published mid-September; a model deciding in early September must see the July figure, not
August's. FRED's ALFRED endpoints supply both dates directly — most sources will not, and you
must record the publication date yourself.

`base_period` matters because Nigerian CPI was rebased to a 2024 base and GDP to 2019
([DATA_FOUNDATION.md §B](../DATA_FOUNDATION.md)). **Rebasing changes past values.** Store
revisions; never overwrite.

### 2.6 News and event tables

```sql
CREATE TABLE news_items (
  id           BIGSERIAL PRIMARY KEY,
  data_source_id INT NOT NULL REFERENCES data_sources(id),
  url          TEXT NOT NULL UNIQUE,
  headline     TEXT NOT NULL,
  body         TEXT,
  published_at TIMESTAMPTZ NOT NULL,
  retrieved_at TIMESTAMPTZ NOT NULL,
  content_hash CHAR(64) NOT NULL
);

CREATE TABLE news_tags (
  news_id     BIGINT NOT NULL REFERENCES news_items(id),
  security_id INT NOT NULL REFERENCES securities(id),
  method      TEXT NOT NULL,          -- 'alias'|'fuzzy'|'llm'
  confidence  NUMERIC NOT NULL,
  PRIMARY KEY (news_id, security_id)
);

CREATE TABLE news_sentiment (
  news_id      BIGINT NOT NULL REFERENCES news_items(id),
  model        TEXT NOT NULL,         -- 'finbert'|'vader'|'claude-...'
  model_version TEXT NOT NULL,
  score        NUMERIC NOT NULL,      -- -1..1
  label        TEXT NOT NULL,
  scored_at    TIMESTAMPTZ NOT NULL,
  PRIMARY KEY (news_id, model, model_version)
);

CREATE TABLE security_aliases (
  id          SERIAL PRIMARY KEY,
  security_id INT NOT NULL REFERENCES securities(id),
  alias       TEXT NOT NULL,
  alias_type  TEXT NOT NULL,          -- 'legal'|'brand'|'former'|'colloquial'
  UNIQUE (alias, security_id)
);
```

Aliases are the difference between a useful tagger and an untrusted one — "GTCO", "Guaranty
Trust", and "GTBank" are one company ([DATA_FOUNDATION.md §D](../DATA_FOUNDATION.md)). Note
`model_version` in the primary key of `news_sentiment`: re-scoring with a new model adds rows
rather than destroying the old scores, so you can compare.

### 2.7 Indicator, feature and model tables

```sql
-- SPEC.md §3.2 verbatim
CREATE TABLE indicators (
  security_id INT NOT NULL REFERENCES securities(id),
  date DATE NOT NULL,
  name TEXT NOT NULL,                 -- 'rsi14','macd_hist'
  param_hash TEXT NOT NULL,
  value DOUBLE PRECISION,
  price_series TEXT NOT NULL,         -- 'adjusted'|'raw'. Makes US-061's rule auditable
                                      -- in the DATA, not only by a lint rule that cannot
                                      -- see rows already written.
  known_as_of DATE NOT NULL,
  computed_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  code_version TEXT NOT NULL,
  PRIMARY KEY (security_id, date, name, param_hash, known_as_of)
);

CREATE TABLE ml_features (
  security_id INT NOT NULL REFERENCES securities(id),
  date DATE NOT NULL,
  feature TEXT NOT NULL,
  value DOUBLE PRECISION,
  known_as_of DATE NOT NULL,          -- point-in-time guard -- IN THE KEY
  computed_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  code_version TEXT NOT NULL,
  -- known_as_of belongs in the PK: a restatement must produce a SECOND row, not
  -- overwrite the first. With it outside the key, recomputing features after a
  -- restatement destroys the pre-restatement vintage -- the exact silent overwrite
  -- 01_ARCHITECTURE §6 forbids, in the table most responsible for preventing it.
  PRIMARY KEY (security_id, date, feature, known_as_of)
);
```

> **`param_hash` is not decoration.** RSI-14 and RSI-21 are different features. Without the hash
> in the key, one silently overwrites the other and your P8 feature matrix contains whichever ran
> last. Hash the full parameter dict, not just the period.

### 2.8 Backtest tables — where the gate lives

```sql
CREATE TABLE backtest_runs (
  id                SERIAL PRIMARY KEY,
  strategy_name     TEXT NOT NULL,
  strategy_params   JSONB NOT NULL,
  universe          TEXT NOT NULL,          -- pre-registered
  universe_as_of    DATE NOT NULL,
  start_date        DATE NOT NULL,
  end_date          DATE NOT NULL,
  cv_method         TEXT NOT NULL,          -- 'purged_kfold'|'cpcv'|'walk_forward'
  embargo_days      INT,
  k_trials          INT NOT NULL,           -- honest count. DSR is meaningless without it.
  cost_model        TEXT NOT NULL,          -- 'NGXCostModel'|'USCostModel'
  cost_model_params JSONB NOT NULL,
  -- results
  gross_return NUMERIC, net_return NUMERIC,
  sharpe NUMERIC, sortino NUMERIC, calmar NUMERIC,
  max_drawdown NUMERIC, hit_rate NUMERIC, profit_factor NUMERIC, turnover NUMERIC,
  psr NUMERIC, dsr NUMERIC NOT NULL,
  cpcv_path_count INT, cpcv_sharpe_std NUMERIC,
  beats_logreg   BOOLEAN NOT NULL,
  beats_buy_hold BOOLEAN NOT NULL,
  passed         BOOLEAN NOT NULL,
  code_version   TEXT NOT NULL,
  run_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
  CONSTRAINT gate CHECK (
    passed = false OR (dsr >= 0.95 AND net_return > 0
                       AND beats_logreg AND beats_buy_hold)
  )
);
```

> **The `gate` CHECK constraint is the invariant made physical.** [SPEC.md §4.1](../SPEC.md)'s
> backtest gate is enforced by the database, not by application code, because application code
> can be bypassed at 1am by a person who is sure this one is fine.

### 2.9 Signal, agent and memo tables

```sql
CREATE TABLE signals (
  id               BIGSERIAL PRIMARY KEY,
  security_id      INT NOT NULL REFERENCES securities(id),
  principal_id     INT NOT NULL REFERENCES principals(id),   -- multi-user from day one
  signal_date      DATE NOT NULL,
  direction        TEXT NOT NULL,             -- 'long'|'short'|'flat'
  calibrated_prob  NUMERIC NOT NULL CHECK (calibrated_prob BETWEEN 0 AND 1),
  ml_model_id      INT NOT NULL REFERENCES ml_models(id),
  backtest_run_id  INT NOT NULL REFERENCES backtest_runs(id),  -- NOT NULL is the gate
  features_snapshot JSONB NOT NULL,           -- show the work
  features_as_of   DATE NOT NULL,
  created_at       TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE FUNCTION assert_backtest_passed() RETURNS TRIGGER AS $$
BEGIN
  IF NOT (SELECT passed FROM backtest_runs WHERE id = NEW.backtest_run_id) THEN
    RAISE EXCEPTION 'signal % references a FAILING backtest run %',
                    NEW.id, NEW.backtest_run_id;
  END IF;
  RETURN NEW;
END; $$ LANGUAGE plpgsql;

CREATE TRIGGER signals_require_passing_backtest
  BEFORE INSERT OR UPDATE ON signals
  FOR EACH ROW EXECUTE FUNCTION assert_backtest_passed();
```

Two mechanisms, deliberately: `NOT NULL` means a signal cannot exist without *a* backtest; the
trigger means it cannot exist without a **passing** one.

```sql
-- [proposed]
CREATE TABLE memos (
  id BIGSERIAL PRIMARY KEY,
  security_id INT NOT NULL REFERENCES securities(id),
  mode TEXT NOT NULL,                          -- 'public'|'personal'
  input_bundle_hash CHAR(64) NOT NULL,         -- content-hash cache key
  bull_case JSONB NOT NULL, bear_case JSONB NOT NULL,
  risks JSONB NOT NULL, what_to_verify JSONB,
  verdict JSONB,                               -- MUST be NULL when mode='public'
  token_cost_usd NUMERIC,
  generated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  CONSTRAINT public_memos_have_no_verdict
    CHECK (mode <> 'public' OR verdict IS NULL)
);
```

That CHECK constraint is [SPEC.md §2E](../SPEC.md)'s "public mode: no verdict" rule made
structural. A bug cannot violate it.

### 2.10 Portfolio and transaction tables

```sql
CREATE TABLE portfolios (
  id SERIAL PRIMARY KEY,
  principal_id INT NOT NULL REFERENCES principals(id),
  name TEXT NOT NULL,
  base_currency CHAR(3) NOT NULL,
  account_equity NUMERIC,      -- per-user parameter, NEVER a config constant
  is_paper BOOLEAN NOT NULL DEFAULT true
);

CREATE TABLE transactions (
  id BIGSERIAL PRIMARY KEY,
  portfolio_id INT NOT NULL REFERENCES portfolios(id),
  security_id  INT NOT NULL REFERENCES securities(id),
  txn_type TEXT NOT NULL,      -- 'buy'|'sell'|'dividend'|'split'|'bonus'|'rights'
  trade_date DATE NOT NULL,
  settle_date DATE,            -- NGX: trade_date + 3 business days
  quantity NUMERIC, price NUMERIC, gross_amount NUMERIC,
  commission NUMERIC, sec_fee NUMERIC, ngx_fee NUMERIC, cscs_fee NUMERIC,
  stamp_duty NUMERIC, vat NUMERIC, alert_fee NUMERIC,   -- the full NGX stack, itemised
  withholding_tax NUMERIC,     -- dividends: 10% [sourced]
  net_amount NUMERIC NOT NULL,
  contract_note_ref TEXT
);

-- [proposed] — the rolling 12-month CGT test needs lot-level detail
CREATE TABLE tax_lots (
  id BIGSERIAL PRIMARY KEY,
  portfolio_id INT NOT NULL REFERENCES portfolios(id),
  security_id INT NOT NULL REFERENCES securities(id),
  acquired_date DATE NOT NULL,
  quantity_remaining NUMERIC NOT NULL,
  cost_basis_per_unit NUMERIC NOT NULL,
  disposed_date DATE, disposal_proceeds NUMERIC, chargeable_gain NUMERIC
);
```

**Fees are itemised, not netted.** At a ~4.5% NGX round-trip break-even
([SPEC.md §2C](../SPEC.md)) you must be able to reconcile every line against a real contract
note, and a single `fees` column makes that impossible.

**The CGT rule this supports** (Nigeria Tax Act 2025, effective 1 January 2026, per
[SPEC.md §2H](../SPEC.md)): gains are not chargeable where disposal proceeds in aggregate are
**less than ₦150,000,000** and the chargeable gain **does not exceed ₦10,000,000 in any 12
consecutive months**, or where proceeds are reinvested in the same year of assessment. For
individuals CGT is **no longer a flat 10%** — gains fold into progressive personal income tax
bands (0%–25%). The rolling window is computed **per principal**, which is one of the clearest
reasons single-user was never viable.

### 2.11–2.13 Alerts, compliance, operations

```sql
CREATE TABLE alert_deliveries (
  id BIGSERIAL PRIMARY KEY,
  alert_id INT NOT NULL REFERENCES alerts(id),
  principal_id INT NOT NULL REFERENCES principals(id),
  idempotency_hash CHAR(64) NOT NULL,
  channel TEXT NOT NULL, delivered_at TIMESTAMPTZ, status TEXT NOT NULL,
  UNIQUE (alert_id, idempotency_hash)          -- the same alert never sends twice
);

-- [proposed] TG3
CREATE TABLE principals (
  id SERIAL PRIMARY KEY,
  external_id TEXT UNIQUE, display_name TEXT NOT NULL, email TEXT UNIQUE,
  kind TEXT NOT NULL,                          -- 'owner'|'family'|'public'|'service'
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(), disabled_at TIMESTAMPTZ
);

CREATE TABLE entitlements (
  principal_id INT PRIMARY KEY REFERENCES principals(id),
  personal_tier BOOLEAN NOT NULL DEFAULT false,   -- gates advice
  data_tier BOOLEAN NOT NULL DEFAULT true,
  llm_spend_cap_usd NUMERIC NOT NULL DEFAULT 0,
  max_position_size NUMERIC, max_daily_loss NUMERIC,
  granted_by TEXT NOT NULL, granted_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE audit_log (
  id BIGSERIAL PRIMARY KEY,
  ts TIMESTAMPTZ NOT NULL DEFAULT now(),
  principal TEXT,                              -- 'anonymous' when unauthenticated
  mode TEXT NOT NULL, method TEXT NOT NULL, endpoint TEXT NOT NULL,
  response_type TEXT, http_status INT NOT NULL,
  request_id UUID NOT NULL, latency_ms INT, error TEXT
);

CREATE TABLE connector_runs (
  id BIGSERIAL PRIMARY KEY,
  connector_name TEXT NOT NULL,
  started_at TIMESTAMPTZ NOT NULL, finished_at TIMESTAMPTZ,
  status TEXT NOT NULL,
  rows_written INT NOT NULL DEFAULT 0,         -- THE silent-failure detector
  http_status INT, error TEXT
);
```

> **`rows_written` is the single most important operational column in the schema.** The classic
> scraper failure is not a crash — the page still loads, the parser still runs, the selector
> matches nothing, and `status` is `'ok'` with zero rows. Alert on **`status='ok' AND
> rows_written=0` on a date the source was expected to publish**
> ([OPERATIONS.md §2.3](../OPERATIONS.md)).

---

### 2.15 Tables named in §2.0 that had no DDL

Added 2026-08-30. Every table below was listed in the table map, referenced by other documents,
and defined nowhere — including two that other tables hold foreign keys to. `08` told the reader
*"do not invent them here; that document is the contract"*, and then did not contain them.

```sql
-- 39. Referenced by alert_deliveries.alert_id. SPEC.md §3.2's version has NO owner
-- column at all, which means every alert belongs to everyone.
CREATE TABLE alerts (
  id           BIGSERIAL PRIMARY KEY,
  principal_id INT NOT NULL REFERENCES principals(id),
  type         TEXT NOT NULL,        -- 'price'|'signal_fired'|'staleness'|'connector_health'
  security_id  INT REFERENCES securities(id),
  condition    JSONB NOT NULL,
  channel      TEXT NOT NULL,        -- 'telegram'|'email'
  active       BOOLEAN NOT NULL DEFAULT true,
  created_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- 28. Referenced by signals.ml_model_id.
CREATE TABLE ml_models (
  id                       BIGSERIAL PRIMARY KEY,
  name                     TEXT NOT NULL,
  algorithm                TEXT NOT NULL,     -- 'xgboost'|'lightgbm'|'logreg'
  params                   JSONB NOT NULL,
  trained_at               TIMESTAMPTZ NOT NULL,
  train_start              DATE NOT NULL,
  train_end                DATE NOT NULL,
  feature_list             JSONB NOT NULL,
  calibration_method       TEXT,              -- 'sigmoid'|'isotonic'|NULL if uncalibrated
  n_calibration_effective  INT,               -- uniqueness-weighted. Below ~1000, isotonic
                                              -- overfits: default to sigmoid.
  brier_test               NUMERIC,
  ece_test                 NUMERIC,
  code_version             TEXT NOT NULL,     -- git SHA
  backtest_run_id          INT REFERENCES backtest_runs(id),
  UNIQUE (name, trained_at)
);

-- 44. TG20 + the licence_status half of the mode gate. `licence_status` appears 22
-- times across the document set and had no storage. DATED, because the NGX movement
-- rule and the Nigerian CGT thresholds BOTH moved during planning -- a backtest over
-- 2024 must read the 2024 value, not today's.
CREATE TABLE system_config (
  key            TEXT NOT NULL,
  value          JSONB NOT NULL,
  effective_from DATE NOT NULL,
  effective_to   DATE,                        -- NULL = currently in force
  set_by         TEXT NOT NULL,
  reason         TEXT NOT NULL,
  source_url     TEXT,
  adr_ref        TEXT,
  created_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
  PRIMARY KEY (key, effective_from)
);
-- Seeded in P0: licence_status, family_tier_max_principals (6), the NGX fee stack,
-- the ±10% band, the movement threshold, settlement days, Nigerian CGT, and the four
-- extraction thresholds from 10_PRE_BUILD_CORRECTIONS §3.1.
-- A missing, NULL or unparseable licence_status row resolves to UNLICENSED.

-- 43. Replaces the misleadingly-named `sessions` in §2.0. The P0 design is a hashed
-- bearer token, not a session; calling it `sessions` invites cookie semantics this
-- design does not want. Swapped for a hosted identity provider at P9 (ADR-0003).
CREATE TABLE principal_tokens (
  id           BIGSERIAL PRIMARY KEY,
  principal_id INT NOT NULL REFERENCES principals(id),
  token_sha256 CHAR(64) NOT NULL UNIQUE,      -- never the token itself
  label        TEXT NOT NULL,
  created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
  expires_at   TIMESTAMPTZ,
  last_used_at TIMESTAMPTZ,
  revoked_at   TIMESTAMPTZ
);

-- 38. TG11.
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

-- 47. 02_INFRASTRUCTURE §9.3 queries this table; it existed nowhere.
-- principal_id IS NULL means the scheduler -- which is exactly the spend the global
-- cap must cover, and which a per-principal cap alone would never stop.
CREATE TABLE llm_spend (
  id                 BIGSERIAL PRIMARY KEY,
  principal_id       INT REFERENCES principals(id),
  ts                 TIMESTAMPTZ NOT NULL DEFAULT now(),
  job_kind           TEXT NOT NULL,           -- 'extraction'|'sentiment'|'memo'|'tagging'
  model              TEXT NOT NULL,
  prompt_version     TEXT,
  input_tokens       INT NOT NULL,
  output_tokens      INT NOT NULL,
  cost_usd           NUMERIC NOT NULL,
  cache_hit          BOOLEAN NOT NULL DEFAULT false,
  source_document_id BIGINT REFERENCES source_documents(id),
  request_id         UUID
);
CREATE INDEX ON llm_spend (principal_id, ts);
CREATE INDEX ON llm_spend (ts);

-- 01_ARCHITECTURE §8 lists both of these as owner-keyed; neither existed.
CREATE TABLE scenarios (
  id           BIGSERIAL PRIMARY KEY,
  principal_id INT NOT NULL REFERENCES principals(id),
  security_id  INT NOT NULL REFERENCES securities(id),
  name         TEXT NOT NULL,                 -- 'bear', 'base', 'bull'
  assumptions  JSONB NOT NULL,                -- the complete user-supplied input set
  inputs_as_of DATE NOT NULL,                 -- US-060: must reproduce identical output
  code_version TEXT NOT NULL,
  created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (principal_id, security_id, name)
);

-- SPEC §2D mandates six limits; entitlements carried two. Defaults chosen so that ten
-- concurrent max-size positions is fully invested, ten simultaneous stop-outs cost 6%,
-- and the live drawdown halt (15%) trips well before the backtest tolerance (25%).
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

**`principals` carries the legal basis of the personal tier**, settled 2026-08-30
([PROJECT_CONTEXT §4](../PROJECT_CONTEXT.md)):

```sql
ALTER TABLE principals
  ADD COLUMN relationship  TEXT,               -- 'self'|'spouse'|'parent'|'sibling'|'child'
  ADD COLUMN fee_charged   BOOLEAN NOT NULL DEFAULT false,
  ADD COLUMN funds_pooled  BOOLEAN NOT NULL DEFAULT false,
  ADD COLUMN attested_by   TEXT,
  ADD COLUMN attested_on   DATE;
```

Personal mode is lawful without SEC registration **because no fee is charged and no funds are
pooled** (`SPEC.md` §1.2). Those two conditions are enforced by a trigger rather than
remembered, because the realistic failure is not an intruder — it is drift from three relatives
to eleven acquaintances, one of whom offers to cover the server bill. Every technical permission
check would still pass on that day.

### 2.16 Structural enforcement — the constraints that outlive good intentions

The backtest gate got a CHECK **and** a trigger, with the stated reason that *"application code
can be bypassed at 1am by a person who is sure this one is fine."* The no-silent-overwrite rule
— ranked equally non-negotiable in `CLAUDE.md` — got only *"enforce it in review."* The same
person at 1am has `psql`.

```sql
CREATE FUNCTION forbid_update() RETURNS TRIGGER AS $$
BEGIN RAISE EXCEPTION 'UPDATE forbidden on %; insert a new version', TG_TABLE_NAME; END;
$$ LANGUAGE plpgsql;

-- Apply to every table holding an extracted or observed figure:
CREATE TRIGGER no_update BEFORE UPDATE ON statement_line_items
  FOR EACH ROW EXECUTE FUNCTION forbid_update();
-- ... and price_history, macro_observations, corporate_actions,
--     fx_rates, adjustment_factors.

-- known_as_of can never precede the period it describes.
ALTER TABLE statement_line_items
  ADD CONSTRAINT pit_sanity CHECK (known_as_of >= period_end);

-- Exactly one current version per fact. This is what makes "the current value" a
-- GUARANTEED single row rather than whatever the ORDER BY happens to return.
CREATE UNIQUE INDEX one_current_version ON statement_line_items
  (statement_id, canonical_key) WHERE superseded_by IS NULL;

-- Provenance is mandatory on every figure, not only line items (CLAUDE.md).
ALTER TABLE macro_observations ALTER COLUMN source_document_id SET NOT NULL;
ALTER TABLE statement_line_items
  ADD CONSTRAINT page_required_unless_structured
  CHECK (extraction_method = 'xbrl' OR page IS NOT NULL);

-- Non-overlapping identity windows. UNIQUE(id_type, id_value, valid_from) does NOT
-- prevent two securities holding 'GTCO' over overlapping dates -- which is precisely
-- the NGX ticker-reuse merge OPERATIONS §1.4 exists to stop. This is the only
-- mechanism that makes resolve_security(type, value, as_of) provably single-valued.
CREATE EXTENSION IF NOT EXISTS btree_gist;
ALTER TABLE security_identifiers
  ADD COLUMN exchange_id INT REFERENCES exchanges(id),   -- NULL for ISIN/LEI/CIK
  ADD CONSTRAINT no_overlapping_ids EXCLUDE USING gist (
    id_type WITH =, id_value WITH =, exchange_id WITH =,
    daterange(valid_from, COALESCE(valid_to, 'infinity'::date), '[)') WITH &&
  );
```

**Correction versus restatement — the rule, because getting it wrong is permanent.**
Both insert a new version. They differ in `known_as_of`, and the difference is the opposite way
round in each case:

| Case | `known_as_of` on the new row | Why |
|---|---|---|
| **Restatement** — the company republished | The restatement's publication date | Both figures are historically true. The market believed the old one until that date. |
| **Correction** — *we* misread or mistyped | **The original `known_as_of`** | The market always had the right number. Give it today's date and every point-in-time query with an earlier decision date returns the typo **forever**, baked into every backtest. |

```sql
ALTER TABLE statement_line_items
  ADD COLUMN correction_type TEXT NOT NULL DEFAULT 'none';
  -- 'none'|'restatement'|'transcription'|'extraction' -- recorded, never inferred
```

---

### 2.14 Valuation inputs and the entity graph

Added 2026-08-30. Two groups of tables that the first draft of this document omitted entirely,
found by the pre-build audit and by the owner. Rationale, alternatives and the sequencing
argument are in [10_PRE_BUILD_CORRECTIONS](10_PRE_BUILD_CORRECTIONS.md) §6.6 and §6.7; **this
section is the contract.**

#### Why they are here

`compute_ratios()` as originally specified took statement line items only — **no price went in,
so no price-based multiple could come out.** P/E, P/B, EV/EBITDA and dividend yield, the ratios
an investor actually opens a stock page to see, were absent from all eighteen documents. P/E
appeared once, as an example of a null-handling rule.

Separately, the model described a company's *numbers* thoroughly and its *relationships* not at
all: `index membership`, `auditor` and `related party` had zero mentions anywhere;
`shareholder` had one. Five of these six tables are populated from **sections of PDFs that P4
is already collecting and already parsing** — the Directors' Report, the substantial-shareholders
schedule, the notes to the accounts, the audit report, and the related-party note — so the
marginal cost is a new extraction target, not a new source, connector or licence.

#### 49. `shares_outstanding` — without this, every P/E is silently wrong

A P/E needs the share count **as of the price date**. NGX companies issue bonus shares
frequently, which changes the denominator without any cash changing hands, so using today's
count against a 2023 price produces a wrong multiple with no error — the same class of bug as
the adjusted-price sin in [10 §2.6](10_PRE_BUILD_CORRECTIONS.md).

```sql
CREATE TABLE shares_outstanding (
  security_id        INT  NOT NULL REFERENCES securities(id),
  as_of_date         DATE NOT NULL,
  shares             NUMERIC NOT NULL,
  share_class        TEXT NOT NULL DEFAULT 'ordinary',
  basic_or_diluted   TEXT NOT NULL,          -- 'basic'|'diluted'
  known_as_of        DATE NOT NULL,
  source_document_id BIGINT NOT NULL REFERENCES source_documents(id),
  page               INT,
  PRIMARY KEY (security_id, as_of_date, share_class, basic_or_diluted, known_as_of)
);
```

| Column | Type | Null? | Unit | Meaning |
|---|---|---|---|---|
| `security_id` | INT | NOT NULL | — | The instrument, never a ticker string |
| `as_of_date` | DATE | NOT NULL | — | The date this count was true of |
| `shares` | NUMERIC | NOT NULL | shares | Never `INT` — bonus issues produce large counts |
| `share_class` | TEXT | NOT NULL | — | `'ordinary'` unless the company has more than one class |
| `basic_or_diluted` | TEXT | NOT NULL | — | Both are published; a P/E must say which it used |
| `known_as_of` | DATE | NOT NULL | — | Point-in-time guard, in the PK — a restated count inserts, never updates |

#### 50–54. The entity graph

```sql
-- 50. Nigerian names carry many spellings and honorifics ('Dr.', 'Alhaji',
-- 'Chief'). normalised_name is what matching joins on; full_name is what displays.
CREATE TABLE persons (
  id              BIGSERIAL PRIMARY KEY,
  full_name       TEXT NOT NULL,
  normalised_name TEXT NOT NULL,
  created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX ON persons (normalised_name);

-- 51. Board seats and executive roles, dated — 'who sat on this board when the
-- decision was made' is the whole point, and it is what makes the interlocking-
-- directorate query possible.
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

-- 52. The 'big holders' panel. holder_company_id is set when the holder is itself
-- a company we track, which is what makes cross-holdings queryable rather than
-- just readable.
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

-- 53. One generic edge table rather than five specific ones. to_name carries the
-- counterparty when it is not a company we track, which is the common case.
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

-- 54. Point-in-time index constituents. Required by P7 check 11 regardless of any
-- product feature: 'the NGX 30 as of 2020' must be answerable, or every backtest
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

**Peers and competitors get no table.** They derive from `industries.scheme + code`. A peer set
is a query, not stored data — storing it would immediately drift from the classification that
defines it.

**All five carry `known_as_of` and `source_document_id NOT NULL`**, so they obey the same
provenance and point-in-time rules as any financial figure. A board membership is a fact
extracted from a page of a document, and it is corrected the same way a revenue figure is
(§10). `entity_roles`, `shareholdings` and `company_relationships` carry `needs_review` so they
route through P4's existing human-review queue rather than needing a second one.

**Population order.** `index_membership` is hand-populated in **P3** for the initial universe —
it is a small table and it unblocks P7's survivorship check. The other four fill in **P4** as
extraction targets on documents already open. All six tables are created empty in the **P2**
migration.

---

## 3. The provenance record

The exact fields that accompany every extracted figure
([DATA_FOUNDATION.md §3.6](../DATA_FOUNDATION.md), [CLAUDE.md](../CLAUDE.md)):

| Field | Type | Required | Meaning |
|---|---|---|---|
| `source_document_id` | bigint | **yes** | The immutable stored file |
| `page` | int | yes where applicable | Page within it |
| `bbox` | jsonb | no | Coordinates, when the extractor gives them |
| `retrieved_at` | timestamptz | **yes** | Distinguishes "source was wrong" from "we parsed wrong" |
| `extraction_job_id` | bigint | yes when automated | Lets you invalidate a whole batch |
| `extraction_method` | text | **yes** | `manual`, `llm_hybrid`, `xbrl` |
| `confidence` | numeric | yes when automated | Routes review; flags weak figures downstream |
| `as_of_date` / `period_end` | date | **yes** | What the value describes |
| `known_as_of` | date | **yes** | When it became knowable |
| `version` | int | **yes** | Incremented on restatement |
| `reviewed_by` | text | when reviewed | Attribution |

**Derived values carry the union of their inputs' provenance**, plus their own computation
record. The `known_as_of` of a derived value is the **latest** of its inputs — a ratio is only
knowable once its last input is. Reversing that is a subtle lookahead bug.

```json
{"metric":"gross_margin","value":0.4686,
 "as_of_date":"2025-09-27","known_as_of":"2025-10-31",
 "computed_from":[
   {"canonical_key":"revenue","value":416161000000,"document_id":883,"page":31},
   {"canonical_key":"cost_of_sales","value":221161000000,"document_id":883,"page":31}],
 "computation":{"formula":"(revenue - cost_of_sales) / revenue",
                "code_version":"valuation@1.4.0"}}
```

---

## 4. The canonical chart of accounts

**What normalization means, concretely.** Three Nigerian companies describe the same idea three
ways. One internal key ties them together:

| Company | Statement label as printed | Canonical key | Template |
|---|---|---|---|
| Dangote Cement | "Revenue" | `revenue` | non_financial |
| MTN Nigeria | "Revenue" | `revenue` | non_financial |
| **GTCO (bank)** | **"Gross earnings"** | **`gross_earnings`** | **financial** |

> **Note what did *not* happen in row 3.** "Gross earnings" is **not** mapped to `revenue`. It is
> a different concept — it includes interest income and fee income and is not comparable to a
> manufacturer's revenue. [TEAM_BRIEF.md Part 3](../TEAM_BRIEF.md) item 2 warns: *"GTCO's income
> statement has no 'revenue' line… A schema built on MTN will not survive a bank."* Mapping them
> together produces a number that looks comparable and is not — a silent error no test catches.

Hence **two templates** ([DATA_FOUNDATION.md §3.4](../DATA_FOUNDATION.md)): `non_financial` and
`financial`, with the bank chart covering gross earnings, net interest income, impairments and
deposits.

Mappings from [DATA_FOUNDATION.md §3.4](../DATA_FOUNDATION.md):

| Canonical key | US GAAP XBRL | Nigerian IFRS labels |
|---|---|---|
| `revenue` | `Revenues`, `RevenueFromContractWithCustomerExcludingAssessedTax` | "Revenue", "Turnover" |
| `operating_profit` | `OperatingIncomeLoss` | "Results from operating activities" |
| `profit_after_tax` | `NetIncomeLoss` | "Profit/(loss) for the year" |
| `total_assets` | `Assets` | "Total assets" |
| `total_equity` | `StockholdersEquity` | "Total equity" |
| `cash_from_ops` | `NetCashProvidedByUsedInOperatingActivities` | "Net cash from operating activities" |
| `gross_earnings` | — | "Gross earnings" (banks only) |
| `net_interest_income` | — | "Net interest income" (banks only) |
| `fx_loss_net` | — | "Net foreign exchange loss" |

`fx_loss_net` is its own key deliberately: [DATA_FOUNDATION.md §3.3](../DATA_FOUNDATION.md)
requires FX loss captured as a **distinct line**, because post-float Nigerian year-on-year
comparisons are distorted by devaluation and must be annotated as such.

**Building this is a manual, accounting-knowledge task** — [TEAM_BRIEF.md §2.2-G](../TEAM_BRIEF.md)
budgets ~2 days. Draft it in P2 against XBRL; **freeze v1 in P3** once Nigerian statements have
shown what it is missing.

---

## 5. Connector contract

Every data source implements one interface
([DATA_FOUNDATION.md §4.3](../DATA_FOUNDATION.md), OpenBB-inspired).

```python
class Connector(ABC):
    name: str
    rate_limit_per_sec: float          # declared, not remembered
    politeness_delay_sec: float        # 1 req / 2-5s per domain for scraping

    @abstractmethod
    def declare_licence(self) -> DataSourceLicence:
        """MUST return redistribution rights. Raises at registration if absent."""

    @abstractmethod
    def fetch(self, **params) -> RawResponse:
        """Return the raw bytes/text. Writes to object storage BEFORE parsing."""

    @abstractmethod
    def parse(self, raw: RawResponse) -> list[NormalizedRecord]:
        """Pure function. Deterministic. Re-parseable without re-fetching."""

    def run(self, **params) -> ConnectorRunResult:
        """fetch -> store raw -> parse -> write -> connector_runs row."""
```

**Four rules the interface enforces:**

1. **`declare_licence()` is abstract** — you cannot ship a connector without answering the
   redistribution question (TG5).
2. **`fetch` and `parse` are separate.** Raw is stored before parsing, so a parser bug six months
   from now is fixable without re-fetching — and works after the source disappears.
3. **`parse` is pure and deterministic.** Same raw input, same output, byte for byte. This is what
   makes it testable.
4. **`run()` always writes a `connector_runs` row**, including `rows_written`.

Per-source specifics, from [DATA_FOUNDATION.md PART 2](../DATA_FOUNDATION.md):

| Source | Format | Cadence | Hard constraints |
|---|---|---|---|
| **SEC EDGAR** | JSON (XBRL) | Continuous | **Zero-pad CIK to 10 digits. Descriptive User-Agent with name+email required. ≤10 req/s (~0.12s delay). 403/429 + ~10-min IP block if exceeded.** Prefer nightly `companyfacts.zip` for bulk. |
| **FRED** | JSON | Varies | Free key. ALFRED endpoints give true vintages — use them. |
| **CBN** | HTML + Excel export | FX daily; MPR per MPC | **No REST API.** Scrape. |
| **NBS** | HTML → PDF/XLSX | CPI ~mid-month for prior month; GDP quarterly | **No REST API.** CPI rebased to 2024 base; GDP rebased to 2019. |
| **DMO** | PDF (docman) | Monthly | **No REST API.** PDF parsing. |
| **NGX prices** | Scrape (afx.kwayisi.org) | Daily | 🔴 No contract, can vanish. Cache every raw response permanently. Paid fallback: EODHD `.XNSA`. |
| **News RSS** | XML | Continuous | Nairametrics, Proshare, BusinessDay, Punch. **Paid news APIs do not meaningfully cover Nigeria.** |

---

## 6. Module contracts

Selected signatures; the full set lives with the code. The pattern matters more than any one
entry: **compute functions take data and return data, and do no I/O of their own** — which is what
makes them testable with hand-computed vectors.

```python
# packages/common/units.py — THE ONLY conversion point (OPERATIONS §1.6)
def to_base_units(value: Decimal, multiplier: int, currency: str) -> Money: ...
def convert(amount: Money, to_currency: str, *, as_of: date,
            rate_type: str = "nfem_official") -> Money:
    """as_of is MANDATORY. A conversion without a date is a defect."""

# packages/common/pit.py — the point-in-time accessor
def get_facts_as_known(security_id: int, keys: list[str], *,
                       decision_date: date) -> dict[str, Fact]:
    """decision_date is MANDATORY — no default. Forgetting it is a TypeError,
    not a wrong number. See 01_ARCHITECTURE.md §5."""

# packages/valuation/ratios.py
def compute_ratios(
    items: dict[str, Decimal | None],
    *,
    price: Decimal | None = None,
    shares: Decimal | None = None,      # from shares_outstanding, as of the price date
    decision_date: date,                # MANDATORY — multiples must be point-in-time too
) -> dict[str, Decimal | None]:
    """Any ratio with a null input returns None. Never 0, never inf.

    Takes price and share count so it can return VALUATION MULTIPLES (P/E, P/B,
    P/S, EV/EBITDA, dividend yield, earnings yield) alongside the profitability and
    balance-sheet ratios. Without them it returns the balance-sheet ratios only,
    and every multiple as None — never omitted, so a caller can distinguish
    'not applicable' from 'we forgot to pass a price'.

    `shares` MUST be the count as of the price date (2.14 #49), never today's:
    NGX bonus issues change the denominator with no cash moving, and today's count
    against a 2023 price is a silently wrong multiple.

    Forward P/E is NOT computed here. It needs forecast earnings, and no free
    analyst consensus exists for NGX — the user supplies the forecast through the
    P6 scenario engine, or a system-generated forecast makes the output
    PersonalAnalysis (see 10_PRE_BUILD_CORRECTIONS 6.6)."""

# packages/backtest/costs.py
class NGXCostModel:
    def round_trip_cost(self, notional: Decimal, shares: int) -> CostBreakdown:
        """Itemised. Must reconcile to a real contract note to the naira.
        Round trip commonly ~2%-4%; break-even ~4.5% (SPEC §2C)."""
    def can_fill(self, order, bar) -> FillDecision:
        """False at the +/-10% band (HALT, not pause). False above the
        participation cap. False if daily volume < movement threshold."""

# packages/ml/calibration.py
def calibrate(model, X, y, *, method: Literal["sigmoid","isotonic"]) -> Calibrated:
    """Compare both by Brier score; record which won and why (SPEC §2B)."""
```

---

## 7. The HTTP API contract

Routers are physically separate module trees, not one router with an `if`
([SPEC.md §1.2](../SPEC.md)). Mode is derived from the principal, never from the request.

### `/public/*` — data only, no verdicts

| Endpoint | Phase | Returns |
|---|---|---|
| `GET /health` | P0 | Liveness + DB + migration head |
| `GET /public/ping` | P0 | `{"mode":"public"}` |
| `GET /public/macro/series` | P1 | Series with as-of dates and staleness flags |
| `GET /public/macro/series/{id}/observations` | P1 | Observations |
| `GET /public/companies/{ticker}/statements` | P2 | Normalized statements + provenance |
| `GET /public/companies/{ticker}/ratios` | P2 | Ratios; nulls where inputs are null |
| `POST /public/companies/{ticker}/scenario` | P6 | User assumptions → DCF. **No auto targets.** |
| `GET /public/news` | P5 | Tagged news + sentiment |
| `GET /public/memos/{id}` | P9 | Memo with `verdict: null` |

### `/personal/*` — requires `entitlements.personal_tier`

| Endpoint | Phase | Returns |
|---|---|---|
| `GET /personal/ping` | P0 | `{"mode":"personal"}` or 403 |
| `GET /personal/signals` | P8 | Calibrated signals with `backtest_run_id` |
| `GET /personal/memos/{id}` | P9 | Memo **with** recommendation and sizing |
| `GET /personal/portfolio` | P10 | Positions, P&L, tax position |
| `POST /personal/execution/ticket` | P13 | NGX order ticket; requires human confirm |

**Response-type assertion** ([SPEC.md §3.3](../SPEC.md)):

```python
PUBLIC_LEGAL_TYPES = {DataSeries, StatementView, RatioSet, ScenarioResult,
                      NewsItem, PublicMemo}

def assert_legal(mode: Mode, payload) -> None:
    if mode is Mode.PUBLIC and type(payload) not in PUBLIC_LEGAL_TYPES:
        raise HTTPException(500, "response type illegal for public mode")
```

An **allow-list**, not a deny-list — a deny-list needs updating every time an advice-shaped type
is added, and the one you forget is the one that leaks. **500, not 403**: a public request
receiving a personal payload is our bug, not the caller's error, and must be impossible to
mistake for normal operation.

---

## 8. The signal and backtest_run contracts

A signal is valid only with a passing `backtest_run_id` ([SPEC.md §4.1](../SPEC.md)). Enforced
three ways: `NOT NULL` foreign key, the `gate` CHECK on `backtest_runs`, and the trigger in §2.9.

```json
GET /personal/signals/3
{"security":"GTCO","direction":"long","calibrated_prob":0.61,
 "model":{"id":12,"name":"xgb_meta","version":"2.1.0","brier":0.211,
          "calibration":"isotonic"},
 "authorised_by_backtest":{
    "run_id":44,"dsr":0.96,"k_trials":34,
    "net_return_after_costs":0.061,"cost_model":"NGXCostModel",
    "beats_logreg":true,"beats_buy_and_hold":true,
    "cv_method":"cpcv","cpcv_path_count":45},
 "features_as_of":"2026-08-26",
 "show_the_work":{"rsi14":62.4,"vol_20d":0.31,"revenue_growth_yoy":0.18}}
```

`k_trials: 34` is the honest count of every parameter and variant tried. Under-reporting it
inflates DSR and deceives only yourself.

---

## 9. Units, currency and rounding policy

**One conversion point.** `packages/common/units.py` and nothing else
([OPERATIONS.md §1.6](../OPERATIONS.md)). If three modules each convert, they will eventually
disagree, and the disagreement will be silent.

| Rule | Detail |
|---|---|
| **Storage type** | `NUMERIC`, never float, for money. Floats lose pennies and the loss compounds. |
| **Naira and kobo** | Store Naira with decimals. 100 kobo = ₦1. |
| **Scale** | Nigerian statements report in thousands or millions, **inconsistently, sometimes varying within one document**. Capture `unit_multiplier` at extraction and store the **base** value. |
| **Currency** | Every monetary column carries its currency. No implicit currency, ever. |
| **FX** | `convert()` requires an `as_of` date and a `rate_type`. USD/NGN moved ₦907.1 → ₦1,535 during 2024 `[sourced]` — the wrong date is wrong by a large multiple. |
| **Rounding** | Round only at display. Never round intermediate values. Ratios keep full precision. |
| **Percentages** | Store as decimals (0.4686), format as percent at display. |
| **Dates** | `DATE` for business dates, `TIMESTAMPTZ` for events. All timestamps UTC; render in WAT. |
| **Nulls** | A missing financial value is `NULL`, never 0. `fillna(0)` anywhere in the financial path is a defect ([SPEC.md §4.1](../SPEC.md)). |

---

## 10. Contract change policy

| Change | How |
|---|---|
| **Add a nullable column** | Alembic migration. Safe. |
| **Add a NOT NULL column** | Three steps: add nullable → backfill → set NOT NULL. |
| **Change a financial value** | **Never `UPDATE`.** Insert a new version, set `superseded_by`, record `corrected_by` and `correction_reason` ([CLAUDE.md](../CLAUDE.md)). |
| **Change the chart of accounts** | New `chart_version`. Old mappings stay valid for old rows. This is what stops a vocabulary change from forcing a re-extraction (TG7). |
| **Change an API response shape** | Additive only within a version. Removing or retyping a field requires a new path version. |
| **Change a cost-model parameter** | New `cost_model_params` on the run. Historical `backtest_runs` are never retro-fitted — they record what was believed at the time. |
| **Change a regulatory threshold** | Dated configuration in `system_config`, never a constant. The NGX movement rule and Nigerian CGT both moved during planning ([TEAM_BRIEF.md Part 3](../TEAM_BRIEF.md)). |

**The rule underneath all of them:** a contract change that silently alters the meaning of stored
data is the most expensive kind of change in this project, because every derived value must be
recomputed and you may not be able to tell which ones were affected.

---

## Appendix A — gaps surfaced by this document

Confirmed from the shared gap register, with the schema work each requires:

| Gap | Schema consequence | Phase |
|---|---|---|
| **TG1** | `price_history` exists in no source DDL, yet T9 and T11 both require it | P2 (US), P4 (NGX) |
| **TG2** | `security_identifiers`, `trading_calendar`, `corporate_actions`, `adjustment_factors`, `fx_rates` — all proposed here | P0 schema, P3 data |
| **TG3** | `principals`, `entitlements`, `sessions` — proposed here | P0 |
| **TG5** | `data_sources` with `redistribution_allowed NOT NULL` | P0 |
| **TG7** | `chart_of_accounts` + `account_mappings`, both versioned | P2 draft, P3 freeze |
| **TG11** | `watchlists`, `watchlist_items` | P0 |

**New this document — TG12:** *No table records **which** `adjustment_factors` were known at a
given date.* [SPEC.md §2C](../SPEC.md) requires reconstructing point-in-time adjusted prices
"only up to the decision date", but a corporate action can be *announced* after its ex-date, or
recorded late. `corporate_actions.known_as_of` (included above) is necessary but not sufficient —
`adjustment_factors` needs its own point-in-time dimension, or P7's adjusted-price handling has a
subtle leak. Flagged for resolution in P3.

---

## Appendix B — implementation checklists by phase

**P0** — [ ] all tables created (including ones empty until P8) · [ ] every user-scoped table has
`principal_id` · [ ] every extracted-figure table has provenance columns · [ ] every
model-readable table has `known_as_of` · [ ] `data_sources.redistribution_allowed` is NOT NULL ·
[ ] `backtest_runs` gate CHECK present · [ ] signals trigger present · [ ] migrations reversible

**P2** — [ ] `chart_of_accounts` drafted and versioned · [ ] `price_history` with raw **and**
adjusted columns · [ ] EDGAR CIK zero-padding, User-Agent, ≤10 req/s · [ ] `shares_outstanding`
populated for the universe — **no P/E is correct without it** · [ ] the five entity-graph tables
(§2.14) created empty · [ ] `compute_ratios` takes `price`, `shares` and `decision_date`

**P3** — [ ] all TG2 tables populated for the initial universe · [ ] chart v1 **frozen** ·
[ ] TG12 resolved · [ ] correction versioning working · [ ] `index_membership` hand-populated
for the universe — this is what makes P7 check 11 (survivorship) answerable

**P4** — [ ] board, substantial shareholders, subsidiaries, auditor and related parties extracted
from the same documents as the financials (§2.14) · [ ] they route through the existing review queue

**P7** — [ ] cost model reconciles to a real contract note · [ ] gate enforced in the database

**P12** — [ ] every served figure's source has `redistribution_allowed = true`, or is derived

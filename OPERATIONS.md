# Operations & Engineering Foundations

*What the three planning documents do not cover: correctness gaps in the data model, and what it takes to run this reliably for years.*

> **Companion to** [PROJECT_CONTEXT.md](PROJECT_CONTEXT.md) (why) · [DATA_FOUNDATION.md](DATA_FOUNDATION.md) (Doc A — sources, PDF pipeline, base schema) · [SPEC.md](SPEC.md) (full build, trading layers, task pack).
>
> **Nothing here contradicts those documents — it is strictly additive.** Everything below is either (a) a gap whose absence produces silently wrong numbers, or (b) infrastructure a multi-year solo project needs and none of the three specs mention.

---

## How to read this

**Part 1 is urgent.** Six data-model gaps that cause *silently wrong answers* — the worst failure mode for a data product, because nothing crashes and you trust the output. Five of the six are cheap now and painful to retrofit.

**Part 2 is what keeps the project alive** — backup, freshness, connector health. The Nigerian dataset is described in PROJECT_CONTEXT.md as "genuinely irreplaceable." Nothing currently protects it.

**Part 3 is long-horizon hygiene** — the things that stop a multi-year, agent-assisted build from drifting.

---

# PART 1 — DATA-MODEL COMPLETIONS (CORRECTNESS)

These are additive to [DATA_FOUNDATION.md §4.2](DATA_FOUNDATION.md) and [SPEC.md §3.2](SPEC.md).

## 1.1 Corporate actions and price adjustment — **the highest-priority gap**

**The problem.** [SPEC.md §2C](SPEC.md) states the rule correctly — *"store raw prices + a separate adjustment-factor series; reconstruct point-in-time adjusted prices only up to the decision date; never mix adjusted and raw"* — but **no table in either schema implements it.** `price_history` stores raw OHLCV with no adjustment factor, and there is no `corporate_actions` table anywhere.

**Why it matters more on NGX than on US markets.** Nigerian listed companies issue **bonus shares** frequently — a 1-for-4 bonus drops the price ~20% overnight with no economic loss. Rights issues at a discount do the same. Without adjustment:

- Every backtest return spanning a bonus issue records a fake ~20% single-day loss. The backtester will confidently report a losing strategy that actually won, or trigger stop-losses that never happened.
- Every per-share metric (EPS, DPS, book value/share) is discontinuous across the action, so 5-year per-share charts in Screen A are wrong.
- Momentum and volatility indicators ([SPEC §2A](SPEC.md)) read the gap as a real move and generate garbage features.

This silently corrupts the ML layer, the backtest gate, and the public analytics tier simultaneously.

```sql
CREATE TABLE corporate_actions (
  id            SERIAL PRIMARY KEY,
  security_id   INT NOT NULL REFERENCES securities(id),
  action_type   TEXT NOT NULL,      -- 'cash_dividend','bonus_issue','rights_issue',
                                    -- 'split','reverse_split','capital_reduction','delisting'
  announce_date DATE,
  ex_date       DATE NOT NULL,      -- the date the adjustment applies from
  record_date   DATE,
  pay_date      DATE,
  -- ratio actions: 1-for-4 bonus => ratio_from=4, ratio_to=5 (5 shares for every 4 held)
  ratio_from    NUMERIC,
  ratio_to      NUMERIC,
  cash_amount   NUMERIC,            -- per share, in currency
  currency      TEXT,
  subscription_price NUMERIC,       -- rights issues only
  source_document_id INT REFERENCES source_documents(id),
  confidence    NUMERIC,
  needs_review  BOOLEAN DEFAULT FALSE,
  UNIQUE (security_id, action_type, ex_date)
);

-- Point-in-time adjustment factors. NEVER mutate price_history.
CREATE TABLE price_adjustments (
  security_id   INT NOT NULL REFERENCES securities(id),
  ex_date       DATE NOT NULL,
  factor        NUMERIC NOT NULL,   -- multiply prices BEFORE ex_date by this
  action_id     INT REFERENCES corporate_actions(id),
  known_as_of   DATE NOT NULL,      -- when the action became public — for point-in-time
  PRIMARY KEY (security_id, ex_date, action_id)
);
```

**Hard rules:**
1. `price_history` stores **raw as-traded prices only**. Never back-adjust it in place — that destroys the ability to reconstruct what a trader actually saw.
2. Adjusted series are **computed on read**, applying only adjustments with `known_as_of <= decision_date`.
3. Every backtest and indicator computation declares which series it uses. Mixing them is a correctness bug, not a style issue.
4. Corporate actions get the same provenance treatment as line items: source document, confidence, `needs_review`.

**Sources:** NGX corporate disclosures (Doc A §D lists these); the paid NGX "News & Corporate Actions" product ($2,500/yr) is the licensed path; company IR announcements; EODHD `.XNSA` carries actions if you take the paid fallback.

**Build it in DATA_FOUNDATION T8** (alongside `AfxKwayisiConnector`), not later. Backfilling actions for a 5-year price history you have already modelled on is a full re-run of every backtest.

## 1.2 Trading calendar

**The problem.** T+3 settlement ([SPEC §2H](SPEC.md)), the ±10% band-halt logic, staleness detection, and every backtest date-shift all assume knowledge of which days NGX actually trades. Nothing defines it.

Nigeria has ~11 public holidays, and **the Islamic ones (Eid al-Fitr, Eid al-Adha, Maulid) move each year and are frequently announced only days in advance** by the Federal Government. Half-days and unscheduled closures happen. A hardcoded weekday rule will put settlements and rebalances on days the exchange was shut.

```sql
CREATE TABLE trading_calendar (
  exchange    TEXT NOT NULL,        -- 'NGX','NYSE','NASDAQ','LSE'
  date        DATE NOT NULL,
  is_open     BOOLEAN NOT NULL,
  session     TEXT,                 -- 'full','half','closed'
  note        TEXT,                 -- e.g. 'Eid al-Fitr (announced 2026-03-18)'
  PRIMARY KEY (exchange, date)
);
```

**Seed NGX from observed trading days** in the `afx.kwayisi` price history (a day with no price list is a day the exchange did not trade) and correct forward from NGX announcements. For US exchanges use `pandas-market-calendars`. Every date arithmetic function in `/backtest`, `/portfolio`, and `/execution` takes the calendar as a dependency — never `timedelta(days=3)`.

## 1.3 FX rates as a first-class table

**The problem.** Seplat Energy and Airtel Africa report in **USD**; MTN Nigeria, GTCO, and Dangote Cement report in **NGN**. Portfolios have a `base_ccy`. Comps tables put these companies side by side. Doc A has FX inside `macro_series` — fine for *displaying* a chart, wrong for *translating* statements, because IAS 21 requires different rates for different items:

- **Income statement and cash flow:** average rate for the period
- **Balance sheet:** closing rate at period end
- **Equity:** historical rate at transaction date

Using one rate for everything produces a balance sheet that does not balance after translation, which then trips your own validation rules ([Doc A §3.2](DATA_FOUNDATION.md)) and sends clean extractions to human review for no reason.

```sql
CREATE TABLE fx_rates (
  base_ccy    TEXT NOT NULL,        -- 'USD'
  quote_ccy   TEXT NOT NULL,        -- 'NGN'
  date        DATE NOT NULL,
  rate        NUMERIC NOT NULL,     -- 1 base = rate quote
  rate_type   TEXT NOT NULL,        -- 'closing','period_average','parallel'
  source      TEXT NOT NULL,        -- 'CBN_NFEM','FRED','parallel_market'
  known_as_of DATE NOT NULL,
  PRIMARY KEY (base_ccy, quote_ccy, date, rate_type, source)
);
```

**Rules:** store the **official CBN NFEM rate** as the accounting rate; store parallel-market rates separately and never silently substitute one for the other — label which is in use on every translated figure. Any translated value carries a flag that it is a **derived** number, not an as-printed one, so it is visually distinct from extracted data.

## 1.4 Stable identity and ticker history

**The problem.** [PROJECT_CONTEXT.md §9.4](PROJECT_CONTEXT.md) names stable entity IDs as an acquirability requirement. But Doc A models identity as `companies.ngx_ticker` (a scalar) and `securities UNIQUE(exchange, ticker)` — which assumes a ticker never changes. It does: **Guaranty Trust Bank became GTCO in 2021** under a holdco restructure, and Nigerian corporate reorganisations are common. When a ticker is reused or reassigned, a scalar column silently joins one company's new prices onto another company's old history.

```sql
CREATE TABLE security_identifiers (
  security_id  INT NOT NULL REFERENCES securities(id),
  id_type      TEXT NOT NULL,       -- 'ticker','isin','cik','lei','figi'
  id_value     TEXT NOT NULL,
  valid_from   DATE NOT NULL,
  valid_to     DATE,                -- NULL = current
  source       TEXT,
  PRIMARY KEY (security_id, id_type, id_value, valid_from)
);
CREATE INDEX idx_secid_lookup ON security_identifiers (id_type, id_value, valid_from, valid_to);
```

**Rules:** `securities.id` is the permanent internal key and **never changes or is reused** — it is the thing that makes the dataset an asset. Tickers, ISINs, and CIKs are time-bounded attributes. All ticker resolution goes through a single `resolve_security(id_type, value, as_of_date)` function; no `WHERE ticker = ?` anywhere else in the codebase. Delisted securities keep their rows (Doc A already does this for survivorship) with the delisting recorded as a corporate action.

## 1.5 Fiscal period alignment

**The problem.** Doc A stores `fiscal_year_end` per company but never says how to compare a December-FY company to a March-FY one. Screening ("show all NGX names with ROE > 20%"), comps tables, and cross-sectional ML features all silently mix periods that end nine months apart — which, during a currency collapse, compares two different economies.

**Decide and record now:**

```sql
ALTER TABLE financial_statements
  ADD COLUMN fiscal_year   INT,      -- the company's own FY label
  ADD COLUMN calendar_year INT,      -- calendar year containing period_end
  ADD COLUMN period_label  TEXT;     -- 'FY2024','Q3-2025' as the company labels it
```

**Rule:** cross-company comparisons align on **`period_end` within a tolerance window** (default ±92 days), never on fiscal-year label. Any comps table or screen displays each company's actual `period_end` next to its figure, and flags when the spread across the comparison set exceeds the window. Never silently align `FY2024` to `FY2024`.

## 1.6 One conversion point for units

**The problem.** Doc A correctly stores `unit_multiplier` (statements printed in thousands or millions). The risk is not the field — it is that the multiplication has no single home. If the extractor stores raw-as-printed, the ratio engine multiplies, and a chart multiplies again, you get a silent 1,000× error that looks plausible on a log axis.

**Rule:** `statement_line_items.value` stores the **fully scaled value in base currency units** — the multiplication happens exactly once, in the extractor, at write time. `as_printed` preserves the original string for provenance display. Add a validation rule that flags any figure more than 3 orders of magnitude from that company's own trailing median for the same `canonical_key`. This catches the class of error that no balance-sheet tie-out will.

---

# PART 2 — RUNNING IT FOR YEARS

## 2.1 Backup and disaster recovery

[PROJECT_CONTEXT.md §7](PROJECT_CONTEXT.md) names this as a gap and calls the dataset "genuinely irreplaceable." Nothing currently implements it. **Do this in week one, before v0.1 has any data worth losing.**

**What is actually irreplaceable, in priority order:**

| Asset | Why it cannot be rebuilt |
|---|---|
| **HITL corrections** | Human judgment calls made once. Re-deriving means re-reviewing every filing by hand. |
| **Raw source-document cache** (PDFs) | Sources disappear. `africanfinancials` and `afx.kwayisi` have no uptime contract (Doc A §8.2). Once a 2013 annual report is gone from the web, your cached copy is the only copy. |
| **Extracted + validated line items** | Months of LLM spend and review time. |
| **Corporate actions** | Historical announcements are the hardest data to re-source retroactively. |
| Prices, macro, news | Re-fetchable, given the sources still exist. Lowest priority. |

**Minimum viable policy (3-2-1):** three copies, two media, one off-site.

1. **Nightly `pg_dump`** (or DuckDB file copy at v0.x) → local, retained 7 days.
2. **Weekly encrypted upload** of the dump **plus the raw document cache** to object storage (Backblaze B2 or Cloudflare R2 — both are single-digit dollars/month at this scale). Encrypt client-side; the key lives in your password manager, not in the repo.
3. **Monthly restore drill.** Restore the newest backup into a scratch database and run the test suite against it. **A backup you have never restored is not a backup.** Put it on the calendar.

**Retention:** keep monthly snapshots for 12 months. Restatements mean the *history of what you believed* has analytical value — that is the same reason SPEC requires point-in-time integrity.

## 2.2 Freshness monitoring — make the staleness rule executable

[PROJECT_CONTEXT.md](PROJECT_CONTEXT.md) rule 6 requires every series to show its as-of date and flag when overdue. Nothing currently defines *overdue*.

```sql
ALTER TABLE macro_series
  ADD COLUMN expected_cadence   TEXT,   -- 'daily','monthly','quarterly','per_mpc'
  ADD COLUMN expected_lag_days  INT,    -- typical publish delay after period end
  ADD COLUMN stale_after_days   INT;    -- overdue threshold
```

Reference values from Doc A §B: **NBS CPI** monthly, published ~mid-month for the prior month (`expected_lag_days ≈ 18`, stale after ~35). **NBS GDP** quarterly, long lag. **CBN MPR** per MPC, roughly bi-monthly. **CBN FX** each trading day. **DMO auctions** monthly. Company filings: quarterly UFS and annual AFS, **frequently late** — treat lateness itself as a signal worth surfacing, not an error.

Build one `data_freshness` view driving both a dashboard banner and a daily alert. **Overdue is information, not just a warning** — "NBS CPI is 9 days late" is genuinely useful to a Nigerian investor and is exactly the kind of thing the public data tier can say without touching advice.

## 2.3 Connector health — catching silent failure

The realistic failure mode is not a crash. It is `afx.kwayisi` changing its HTML, the scraper returning HTTP 200, the parser matching nothing, and **zero rows landing with no error raised.** You notice weeks later when a chart has a flat line.

```sql
CREATE TABLE connector_runs (
  id            SERIAL PRIMARY KEY,
  connector     TEXT NOT NULL,
  started_at    TIMESTAMPTZ NOT NULL,
  finished_at   TIMESTAMPTZ,
  status        TEXT NOT NULL,      -- 'ok','degraded','failed'
  rows_expected INT,
  rows_written  INT,
  bytes_fetched BIGINT,
  error         TEXT
);
```

**Every connector asserts a plausible row count before committing.** The NGX daily price list has ~150 rows; if a run writes 3, that is a failure regardless of HTTP status. Alert on: zero rows where rows were expected, a >50% drop versus the trailing median, three consecutive failures, or a source whose response hash has not changed in longer than its cadence (a frozen page).

Wire these into the same Telegram channel as the daily brief ([SPEC §2G](SPEC.md)) — one place to look.

## 2.4 Schema evolution

Doc A ships `schema.sql`. Over a multi-year build the schema will change dozens of times, and Part 1 of this document alone adds six tables.

Adopt **Alembic** from DATA_FOUNDATION T2, before there is production data. Rules: every schema change is a migration, never a hand-edited `schema.sql`; every migration has a tested downgrade; migrations run in CI against a restored backup. When Postgres arrives at v1.0, the DuckDB→Postgres migration is itself a scripted, re-runnable step — not a one-off you perform manually at 2am.

## 2.5 Secrets and security

No document currently mentions secret handling, and the personal tier will eventually hold **broker credentials** ([SPEC §2I](SPEC.md)) — a materially different risk class from an API key.

**Now:** `.env` excluded by `.gitignore`, `.env.example` committed with keys blank. A pre-commit hook running `gitleaks` or `detect-secrets`. Keys to manage: FRED, Anthropic, Telegram bot token, EODHD (if bought), Alpaca/IBKR (v2.5).

**At v1.0 hosting:** platform secret store (Railway/Render/Fly), never environment variables baked into an image. Rotate on any suspicion.

**Trading-tier specifics (v2.5):** broker credentials are **never** stored alongside application data; use a broker-issued API key with the narrowest scope available and **withdrawal permissions disabled**. The kill switch in SPEC §2I must be operable without the application running — a manual broker-side action you have rehearsed.

**Threat model, honestly stated:** the realistic risks are a leaked key in a git commit, a compromised laptop with an unencrypted database, and a dependency supply-chain attack. Full-disk encryption on the machine, secret scanning in CI, and a lockfile address all three.

## 2.6 Reproducibility

An agent-assisted build spanning months across many sessions needs a pinned environment or "works on my machine" becomes unfalsifiable.

Use **uv** with a committed `uv.lock`; pin Python to 3.12 in `.python-version`; add a `Dockerfile` at v1.0 (not before — it slows v0.x iteration for no gain). Pin the LLM model **id and version** used for extraction in `ml_models` / `extraction_jobs`: a model upgrade changes extraction behaviour, and you must be able to answer "which model produced this number?" That question is a provenance question, and provenance is the product.

---

# PART 3 — LONG-TERM PROJECT HYGIENE

## 3.1 Decision log (ADRs)

The dominant failure mode in long agent-assisted builds is **re-litigating settled decisions** — a new session proposes replacing DuckDB with Postgres at v0.2, or swapping the canonical chart of accounts, because it cannot see why the current choice was made.

Keep `docs/decisions/NNNN-short-title.md`, one page each: context, decision, alternatives rejected, consequences, date. Write one for every choice that is expensive to reverse. **The backlog from the existing documents:** DuckDB before Postgres; `pandas-ta-classic` over TA-Lib; own backtester before vectorbt; CrewAI prototype → LangGraph production; the canonical chart of accounts; the personal/public access model; the ±10% band and participation-cap assumptions; the EODHD buy-vs-build threshold.

An ADR is also the honest place to record *"we chose this while uncertain, and here is what would change our mind"* — which is exactly the sunk-cost discipline [PROJECT_CONTEXT.md §8](PROJECT_CONTEXT.md) asks for.

## 3.2 Coverage metrics — make §9.4 real

[PROJECT_CONTEXT.md §9.4](PROJECT_CONTEXT.md) requires "coverage metrics quotable to a buyer: N companies, M years, X% extraction accuracy." Compute them continuously rather than assembling them the week a buyer asks:

| Metric | Definition |
|---|---|
| **Companies covered** | Distinct companies with ≥1 validated annual statement |
| **Depth** | Median years of history per covered company |
| **Completeness** | % of expected filing-periods present per company (expected derived from listing date + fiscal calendar) |
| **Extraction accuracy** | % of line items passing validation with no human correction, measured against the golden set |
| **Correction rate** | % of extracted items a human changed — the honest quality number |
| **Freshness** | % of series within their `stale_after_days` window |
| **Provenance completeness** | % of stored figures with a resolvable source document and page — **must be 100%** |

Snapshot monthly into a `coverage_metrics` table. This is a due-diligence answer, an internal progress signal, and the honest way to know whether the moat is actually widening.

## 3.3 Runbook

One file, `docs/RUNBOOK.md`, answering the questions you will face at an inconvenient hour: a connector has failed three nights running; the LLM spend cap tripped; a restatement arrived for a company already in the database; extraction confidence collapsed after a model upgrade; you need to restore from backup; a source has permanently disappeared and you are switching to the paid fallback; the trading kill switch must be pulled.

Each entry: symptom → diagnosis → fix → how to prevent recurrence. Write entries **as incidents happen**, not in advance — a runbook written speculatively is fiction.

## 3.4 Review gates

Two are already implied across the documents but tracked nowhere.

**Legal review** — [Doc A Recommendation 5](DATA_FOUNDATION.md) requires a Nigerian securities and data-protection lawyer to sign off before public launch. Make it a dated checklist item with a named person, covering: ISA 2025 positioning of the public tier, NGX/vendor **redistribution rights** for anything served publicly, NDPC/DCPMI registration, and the licence path for the advice tier. **Book this before you need it** — the answer shapes the v2.0 architecture, and finding out late is the expensive version.

**Quarterly regulatory drift review** — the ground has moved repeatedly during planning alone: the ±10% band and 100,000-share movement rule are under active revision (SEC-approved June 2026, postponed the day before its August 2026 rollout); SEC Circular 26-1 restructured capital requirements with a June 2027 deadline; the Nigeria Tax Act 2025 changed share CGT from January 2026; the FRC reassesses IAS 29 annually. Each affects code — cost models, tax computations, statement handling. One hour a quarter re-checking NGX, SEC, NDPC, FRC, and FIRS, with findings recorded as ADRs.

## 3.5 The document map

| File | Authority over | Status |
|---|---|---|
| [PROJECT_CONTEXT.md](PROJECT_CONTEXT.md) | Purpose, audiences, access model, B2B thesis, standing rules | Current |
| [DATA_FOUNDATION.md](DATA_FOUNDATION.md) | Data sources, PDF pipeline, base schema, regulatory research | Doc A, Aug 2026 |
| [SPEC.md](SPEC.md) | Build order, layering, trading stack, DDL additions, T1–T21 | Merged Doc A+B, Aug 2026 |
| [OPERATIONS.md](OPERATIONS.md) | Correctness gaps, infrastructure, project hygiene | This file |
| [CLAUDE.md](CLAUDE.md) | Session entry point — index + invariants | Current |

**Precedence when they disagree:** PROJECT_CONTEXT (access model and standing rules) → SPEC (build order and trading) → DATA_FOUNDATION (sources and base schema) → OPERATIONS (everything above). Two known reconciliations are already recorded as editorial notes in the SPEC.md and DATA_FOUNDATION.md headers; if a new conflict appears, resolve it in the higher-precedence document and note it in the lower one rather than leaving both standing.

---

## Priority order

**Before writing schema code:** §1.1 corporate actions, §1.4 identity, §1.6 units, §2.4 Alembic. These four are cheap now and structurally painful later.

**Before v0.1 holds real data:** §2.1 backup, §2.5 secrets.

**With the first connector:** §2.3 connector health, §2.2 freshness.

**Before v0.7 indicators:** §1.2 trading calendar, §1.3 FX. Both are prerequisites for a backtest that is not fiction.

**Ongoing:** §3.1 ADRs from the first irreversible decision; §3.3 runbook from the first incident; §3.4 legal review booked early, drift review quarterly.

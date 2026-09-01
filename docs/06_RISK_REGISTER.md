# 06 — Risk Register

**What this document is for.** You asked to be told where the lapses are, so you can pay strong
attention to them and find several approaches to each — and equally, which parts are strong
enough that worrying about them is wasted effort. This document is that answer. It lists every
way this project can fail that I can find in the six source documents, plus the ones the source
documents do not name, rates each one honestly, and for every genuinely fragile item gives you
at least three distinct approaches with a recommendation. It also contains a deliberately long
section on the parts that are **safe** — because anxiety spent on EDGAR ingestion, or on whether
FastAPI is the right framework, is anxiety not spent on the PDF extractor, which is the thing
that actually decides whether this project works.

Nothing here has been built yet. The repository today contains six markdown files, an empty
`package.json`, and `node_modules/`. There is no `.git`, no Python, no database, no code. Every
risk below is therefore still *preventable* — which is the entire point of writing this now
rather than in month four.

> **Sibling documents:** [00_START_HERE.md](00_START_HERE.md) ·
> [01_ARCHITECTURE.md](01_ARCHITECTURE.md) · [02_INFRASTRUCTURE.md](02_INFRASTRUCTURE.md) ·
> [03_ROADMAP_PART1_PHASES_0-6.md](03_ROADMAP_PART1_PHASES_0-6.md) ·
> [04_ROADMAP_PART2_PHASES_7-13.md](04_ROADMAP_PART2_PHASES_7-13.md) ·
> [05_USER_STORIES.md](05_USER_STORIES.md) · **06_RISK_REGISTER.md** (this file) ·
> [07_TEST_STRATEGY.md](07_TEST_STRATEGY.md) · [08_DATA_CONTRACTS.md](08_DATA_CONTRACTS.md) ·
> [09_GLOSSARY.md](09_GLOSSARY.md)
>
> **Source documents cited inline:** `CLAUDE.md`, `PROJECT_CONTEXT.md`, `SPEC.md`,
> `DATA_FOUNDATION.md` (called "Doc A" inside SPEC), `OPERATIONS.md`, `TEAM_BRIEF.md`.
> Precedence when they disagree: PROJECT_CONTEXT → SPEC → DATA_FOUNDATION → OPERATIONS.

---

## Table of contents

1. [How to read this](#1-how-to-read-this)
2. [THE SHORT LIST — the five things most likely to kill or maim this project](#2-the-short-list--the-five-things-most-likely-to-kill-or-maim-this-project)
3. [Things you do not need to worry about (SOLID)](#3-things-you-do-not-need-to-worry-about-solid)
4. [The full register](#4-the-full-register)
   - [4.1 Data & Sources — R-01 to R-08](#41-data--sources)
   - [4.2 Extraction & Quality — R-10 to R-17](#42-extraction--quality)
   - [4.3 Correctness & Silent Corruption — R-20 to R-27](#43-correctness--silent-corruption)
   - [4.4 Modelling & Overfitting — R-30 to R-36](#44-modelling--overfitting)
   - [4.5 Legal & Regulatory — R-40 to R-45](#45-legal--regulatory)
   - [4.6 Operational & Continuity — R-50 to R-58](#46-operational--continuity)
   - [4.7 Cost — R-60 to R-63](#47-cost)
   - [4.8 Product & Adoption — R-70 to R-73](#48-product--adoption)
   - [4.9 Execution & Capital — R-80 to R-83](#49-execution--capital)
   - [4.10 People & Capacity — R-90 to R-94](#410-people--capacity)
   - [4.11 Technical Debt — R-100 to R-105](#411-technical-debt)
5. [The known spec gaps (TG1–TG20)](#5-the-known-spec-gaps)
6. [Silent-failure catalogue](#6-silent-failure-catalogue)
7. [Risk-by-phase matrix](#7-risk-by-phase-matrix)
8. [Decision gates](#8-decision-gates)
9. [The honest verdict](#9-the-honest-verdict)

---

## 1. How to read this

### 1.1 The marker system

Three markers, used consistently, exactly as defined in the shared agent brief:

| Marker | Meaning | What it obliges |
|---|---|---|
| 🟢 **SOLID** | Well-understood, low variance, proven approach. When it fails, the failure is loud and cheap to fix. | Nothing. Stop worrying about it. Section 3 explains why, one item at a time. |
| 🟡 **WATCH** | It will work, but it has a known failure mode, a cost curve that can bend, or a dependency that can move under you. | At least one mitigation, plus an **explicit escalation trigger** — the observable event that turns this yellow item red. |
| 🔴 **FRAGILE** | Genuinely likely to go wrong, or the effort/cost estimate could be off by multiples, or the damage is silent. | **At least three distinct approaches**, each with its trade-off, plus an explicit recommendation. This three-approaches rule is your own instruction and it is honoured for every red item below. |

### 1.2 What a rating is, and what it is not

These ratings are **judgements**, not measurements. They are grounded in the source documents'
own honest assessments — `DATA_FOUNDATION.md` §8.2 ("Top 10 things most likely to go wrong"),
§8.3 ("Where estimates are most wrong"), §8.5 ("Honest feasibility verdict"), `SPEC.md` PART 6
("Top risks" and "The honest verdict"), and `TEAM_BRIEF.md` PART 3 ("The big five") — and they
extend those assessments rather than contradict them. Where I have gone beyond the source
documents, I say so in the entry.

Three things a rating does **not** mean:

- 🔴 **FRAGILE does not mean "this will fail."** It means the variance is high and the downside
  is real. Every red item below has been solved by someone before; several can be solved by
  paying money instead of spending months.
- 🟢 **SOLID does not mean "this cannot fail."** It means that when it fails you will *know*
  immediately, and the fix is hours, not weeks. A green item that failed silently would not be
  green — silence is the property that makes a thing dangerous.
- **A rating is not a priority.** A 🔴 item in P13 (personal execution, the last phase) matters
  less right now than a 🟡 item in P0 that becomes unfixable once real data exists. Priority
  lives in the [risk-by-phase matrix](#7-risk-by-phase-matrix) in section 7.

### 1.3 The shape of every register entry

| Field | What it gives you |
|---|---|
| **ID · Title · Category · Marker · Phases** | The handle. Cite the ID in commit messages and ADRs (Architecture Decision Records — the one-page "we chose X because Y, and here is what would change our mind" notes described in `OPERATIONS.md` §3.1). |
| **What it is, in plain words** | Assumes no prior knowledge. Every term defined on first use. |
| **How it actually shows up** | The concrete thing you would *observe*. Not "data quality degrades" but "the 5-year revenue chart for GTCO shows a 1,000× spike in FY2022". |
| **Why it matters / what it costs** | Including, explicitly, whether the damage is **silent**. Silent damage is the worst class, because a corrupted backtest looks exactly like a good backtest. |
| **Early-warning signals** | Specific, checkable things: a number you can query, a log line you can grep, a chart that looks wrong. |
| **Approaches** | Three or more for 🔴 items, with trade-offs and a recommendation. One or more mitigations for 🟡 items, plus the trigger that escalates it to red. |
| **Residual risk after mitigation** | What is left over. Some risk does not go away, and pretending otherwise is how people get surprised. |
| **Who/what decides** | The measurable threshold that forces a decision, and who makes it. Where a source document already sets a threshold, it is quoted. |

### 1.4 The honesty contract

If every entry here were red you could not prioritise, and the document would be noise. If every
entry were green the document would be a lie. The distribution below is roughly **22 red, 36
yellow, 16 green**, plus 14 scheduling gaps. That ratio was not engineered — it is what fell out
of reading the source documents closely. The reds cluster in exactly two places: **Nigerian PDF
extraction** and **the trading/backtest layer**. Almost everything US-facing, everything
FRED-facing, and the entire technology-stack choice are green. That clustering is itself the most
useful finding in this document, and it matches `DATA_FOUNDATION.md` §8.3 word for word:

> *"PDF extraction (bank statements especially — different chart of accounts) and the
> FastAPI/Next.js migration (auth + data migration always overrun). Everything FRED/EDGAR-based
> is fast and predictable."*

---

## 2. THE SHORT LIST — the five things most likely to kill or maim this project

If you read only one section of this document, read this one. These five are ranked by
**expected damage × probability**, not by how alarming they sound. Each gets three sentences.

### 1. 🔴 Nigerian PDF extraction takes 2–3× longer than planned and stalls below usable accuracy

→ [R-10](#r-10--pdf-extraction-accuracy-stalls-below-the-85-gate) ·
[R-11](#r-11--banks-break-a-schema-built-for-industrials) ·
[G6](#g6--no-task-covers-the-golden-test-set)

Turning badly-formatted Nigerian annual-report PDFs into clean numbers is the entire moat, and
every planning document independently says to budget two to three times your estimate for it
(`DATA_FOUNDATION.md` §8.2 item 1; `TEAM_BRIEF.md` Part 3 item 1). Rules-based extraction alone
lands around 60% accuracy on messy borderless tables, and the hybrid pipeline that lifts it to
roughly 90% depends entirely on a golden test set that currently has no task assigned to build
it. This is the one risk where the correct response is pre-decided: **if accuracy is below ~85%
on 10 filings after two weeks of honest effort, buy EODHD `.XNSA` (~$60/mo) and move on** — the
threshold `DATA_FOUNDATION.md` §318 item 4 calls "the single most important cost/effort decision
in the project."

### 2. 🔴 Silent data corruption makes everything downstream confidently wrong

→ [R-20](#r-20--corporate-actions-missing-so-every-price-series-is-wrong) ·
[R-26](#r-26--restatements-corrupt-the-point-in-time-view) ·
[G2](#g2--operationsmd-part-1-has-no-t-numbers) ·
[§6 silent-failure catalogue](#6-silent-failure-catalogue)

Nigerian companies issue bonus shares often; a 1-for-4 bonus drops the price about 20% overnight
with no economic loss, and without a corporate-actions table every backtest spanning that date
records a fake crash (`OPERATIONS.md` §1.1, which calls this "the highest-priority gap"). Nothing
crashes, no error is logged, and the numbers are simply wrong — which corrupts the indicator
layer, the ML features, the backtest gate, and the public analytics tier at the same time. Six
correctness tables in `OPERATIONS.md` Part 1 fix this and **none of them has a task number in
`SPEC.md` T1–T21**, which is gap G2 and the single highest-value scheduling fix you can make
before writing any schema code.

### 3. 🔴 The trading layer produces a fictional edge: overfitting plus impossible NGX fills

→ [R-30](#r-30--overfitting-and-data-snooping) ·
[R-31](#r-31--ngx-illiquidity-the-price-band-and-the-movement-rule-make-fills-fictional) ·
[R-32](#r-32--the-backtester-itself-is-wrong)

`SPEC.md` PART 6 names overfitting and data-snooping as "the #1 killer", and separately notes
that NGX's ±10% daily price band *halts* a stock for the day when hit, that a 100,000-share
movement rule gates whether a price can move at all, and that round-trip costs run 2–4% — so a
backtest that assumes it filled at the closing price is describing a market that does not exist.
The failure is silent and self-flattering: you get a beautiful equity curve, you believe it, and
then real capital meets real fills. The defence is already specified — Deflated Sharpe Ratio with
the trial count recorded, purged and combinatorial cross-validation, the full NGX cost stack, a
participation cap, band-halt logic, and a hard **backtest gate** that no signal passes without a
recorded `backtest_run` — and it must exist *before* the ML layer, which is exactly why P7
precedes P8.

### 4. 🔴 Attrition — three products, one builder, no shared finish line

→ [R-90](#r-90--attrition-the-project-dies-in-the-middle) ·
[R-92](#r-92--three-products-one-builder-no-shared-finish-line)

`TEAM_BRIEF.md` Part 3 item 4 states the realistic six-month failure plainly: a data pipeline, an
analytics product, and a trading system all half-built — because the data pipeline is done when
it is reliable, the analytics product is done when someone uses it weekly, and the trading system
is never done. Attrition is called out separately as "rarely stated, most common": multi-year
projects die in the middle, when the novelty is gone and the PDFs are still badly formatted. The
counter is structural, not motivational — sequence rather than parallelise, ship P1 in a weekend
so something real exists early, and hold the standing rule from `PROJECT_CONTEXT.md` §8: **if
everything is half-done, finish the data layer completely and let the rest wait.**

### 5. 🔴 Losing the dataset, or losing the right to redistribute it

→ [R-50](#r-50--losing-the-dataset) ·
[R-40](#r-40--redistribution-licensing-blocks-the-public-tier) ·
[G4](#g4--backupdr-operationsmd-21-is-unscheduled) ·
[G5](#g5--the-data-licensing-gate-has-no-task)

Two different ways to lose the same asset. Months of human-corrected extractions living on one
laptop with no off-machine backup is the only *unrecoverable* failure in the project
(`OPERATIONS.md` §2.1: the human-in-the-loop corrections and the raw PDF cache cannot be rebuilt,
because the sources themselves disappear). The other way is legal — `PROJECT_CONTEXT.md` §9.3
says redistribution rights are "the one that kills deals", because an acquirer's lawyers ask
exactly one hard question and a dataset built by scraping sources whose terms prohibit
redistribution "is a lawsuit, not an asset." Both have no task number today (G4, G5), and both
are cheap to fix in P0 and expensive to fix once there is data worth losing.

### The one-line version

> **The data layer is where the value is and where the danger is. The trading layer is where the
> self-deception is. The middle of the project is where the motivation goes. Everything
> US-facing, everything FRED-facing, and the whole technology stack are fine — do not spend
> worry there.**

---

## 3. Things you do not need to worry about (SOLID)

This section is long on purpose. You asked for the strong parts — "the ones that are very
strong, with no reasons to worry about" — and they deserve the same care as the risks, because
misplaced worry is a real cost. It slows decisions, it causes re-litigation of settled choices
(which `OPERATIONS.md` §3.1 names as the dominant failure mode in long agent-assisted builds),
and it steals attention from the two red clusters.

For each item: **what it is**, **why it is genuinely low-risk**, **the worst realistic case**,
and **why that case is cheap**.

---

### 3.1 🟢 US company data via SEC EDGAR

**What it is.** EDGAR is the US Securities and Exchange Commission's filing system. Every 10-K
(annual report) and 10-Q (quarterly report) from every US listed company is published there as
**XBRL** — eXtensible Business Reporting Language, a format where each number carries a machine
-readable tag such as `Revenues` or `NetIncomeLoss`. You call
`https://data.sec.gov/api/xbrl/companyfacts/CIK0000320193.json` and get Apple's entire history of
tagged financial facts as JSON. It is free, needs no API key, and is explicitly designed for
automated access.

**Why it is genuinely low-risk.** Four independent reasons. (1) It is a **government mandate**,
not a commercial product — it cannot be discontinued for business reasons, its terms cannot turn
against you, and there is no vendor to negotiate with. (2) The data is **already structured** —
there is no parsing, no layout guessing, no LLM in the path, which removes the entire class of
risk that makes Nigerian extraction hard. (3) The access rules are published and simple: a
descriptive `User-Agent` header containing your name and email, and no more than 10 requests per
second (`DATA_FOUNDATION.md` §2C). (4) There is a **bulk path** — nightly `companyfacts.zip` and
`submissions.zip` — so if rate limiting ever became annoying you download the whole thing once a
night instead.

**Worst realistic case.** You forget the `User-Agent` header or exceed 10 requests per second,
and SEC returns HTTP 403 or 429 and blocks your IP for roughly ten minutes
(`DATA_FOUNDATION.md` §2C). Or a company changes which XBRL tag it uses for revenue, and one
company's revenue series shows a null where a number should be.

**Why that case is cheap.** The rate-limit block is **loud** — you get an HTTP error code, in
the same request, immediately, and it clears itself in ten minutes. The fix is a `time.sleep(0.12)`
between requests, which is one line and is already specified in the sample prompt in
`DATA_FOUNDATION.md` §7.5. The tag-drift case is handled by the canonical map trying alternates
(`Revenues` → `RevenueFromContractWithCustomerExcludingAssessedTax`), which is also already
specified. And critically: **a missing US number is a missing number, not a wrong number** —
`SPEC.md` §4.1 invariant 4 forbids inferring it, so it shows as null and you can see it.

**Verdict: build P2 with confidence.** `DATA_FOUNDATION.md` §8.3 says the same: "Everything
FRED/EDGAR-based is fast and predictable."

---

### 3.2 🟢 FRED and World Bank macro data

**What it is.** FRED (Federal Reserve Economic Data, run by the St. Louis Fed) is a free API
serving tens of thousands of economic time series, including roughly 94 World-Bank Nigeria series
— for example `FPCPITOTLZGNGA`, Nigeria's annual CPI inflation, which read 33.24% for 2024
(`DATA_FOUNDATION.md` Key Finding 4). It needs a free API key. The World Bank's own WDI catalogue
(~1,600 indicators) is reachable through the `wbgapi` Python package with no key at all.

**Why it is genuinely low-risk.** It is a public-good API with a stable contract, decades of
continuity, an enormous user base that would notice a breaking change instantly, and — uniquely
valuable for this project — **ALFRED vintages**. A "vintage" is the value of a series *as it was
published on a given date*, before later revisions. That is precisely what you need for
point-in-time correctness in the ML layer (`SPEC.md` §2B: "macro (vintage-aware)"), and FRED
gives it to you for free rather than requiring you to build a revision-history store yourself.

**Worst realistic case.** FRED's Nigeria coverage is **annual, not monthly**, so it cannot track
Nigerian inflation month to month. That is not a failure — it is a documented limitation
(`DATA_FOUNDATION.md` Key Finding 4: "Annual/low-frequency — fine for context, not monthly
tracking"). The other realistic case is an API key rotation or a brief outage.

**Why that case is cheap.** The limitation is known before you start, so P1 is scoped around it:
FRED and World Bank give you the automatic backbone, and one manual CBN/NBS CSV covers the
monthly detail (`DATA_FOUNDATION.md` PART 5, v0.1). An outage is loud, self-resolving, and hits a
context chart rather than a decision. **This is the reason P1 can genuinely ship in a weekend** —
it is the only phase in the whole roadmap whose data dependencies are all first-class free APIs.

---

### 3.3 🟢 The ratio and DCF mathematics

**What it is.** The valuation engine: margins, ROE (return on equity — profit divided by
shareholders' equity), ROA, leverage and liquidity ratios, per-share figures, discounted cash
flow (projecting future cash flows and discounting them back to today at a rate the user chooses),
comparables tables, and sensitivity grids. `DATA_FOUNDATION.md` §4.5 specifies it as a stateless
service behind `POST /analysis/*` where **all assumptions arrive in the request body from the
user**.

**Why it is genuinely low-risk.** This is arithmetic with a century of settled convention. There
is no ambiguity about what a current ratio is. It is **deterministic** — the same inputs always
produce the same outputs — which means it is perfectly testable with known-answer tests
(hand-computed vectors, mandated by `SPEC.md` §4.4). It is **stateless**, so it cannot corrupt
stored data. And the design already removes the one genuine risk in valuation work: the engine
"NEVER stores a 'fair value' as a fact or emits a recommendation" (`DATA_FOUNDATION.md` §4.5), so
a wrong assumption produces a visibly wrong scenario the user chose, not a false fact in the
database.

**Worst realistic case.** A formula is coded wrong — say, ROE computed on average equity when you
intended closing equity — and every company's ROE is off by a few percent.

**Why that case is cheap.** A known-answer test with a hand-computed vector catches it before
merge, and if one slips through, the fix is a single function plus a recomputation; nothing is
stored that has to be migrated. Compare that to a wrong number in `statement_line_items`, which
propagates into features, models, and memos. **The valuation layer is downstream of the data
layer, and downstream-only components are cheap to fix.**

**One caveat that keeps this green rather than yellow:** the *inputs* to these ratios come from
extraction, which is red. The math is safe; the numbers fed into it are the risk. Do not read
"ratios are solid" as "the ratios on screen are right."

---

### 3.4 🟢 Technical indicator computation

**What it is.** RSI, MACD, Bollinger Bands, ATR, OBV, Stochastic — arithmetic transformations of
a price series, defined by published formulas that `SPEC.md` §2A reproduces exactly (for example
RSI = 100 − 100/(1+RS), where RS is average gain over average loss with Wilder smoothing).

**Why it is genuinely low-risk.** The formulas are fixed and public. The library landscape was
verified for 2026 and has a clear maintained default — `pandas-ta-classic`, first released Aug
2025 and actively developed (v0.6.52, June 2026), with 224+ indicators, no C dependency, and
optional numba acceleration (`SPEC.md` §2A). TA-Lib now installs from official PyPI wheels, so
the historical compile pain is gone. Storage is specified as `(security_id, date, name,
param_hash, value)`, which makes every computed value reproducible and point-in-time. And
`SPEC.md` §4.2 T9 requires **known-answer tests against hand-computed values**, which is the
correct and complete test for deterministic math.

**Worst realistic case.** You pick a library whose RSI uses simple smoothing where you expected
Wilder smoothing, and every RSI value is slightly different from a reference implementation.

**Why that case is cheap.** The known-answer test fails on the first run and you either switch
library or set the parameter. Total cost: an afternoon. Nothing is silently wrong, because the
test compares against a number you computed by hand.

**The caveat that is *not* about the computation:** `SPEC.md` §2A is blunt that the *evidence for
technical analysis as a source of profit* is "mixed-to-negative and heavily contaminated by
data-snooping", citing Park & Irwin (2007). That is a modelling risk (R-30), not a computation
risk. Computing RSI correctly is green. Believing RSI predicts returns is red. Keep those
separate — which is exactly why the roadmap treats indicators as **features, not signals**, and
puts the backtest gate (P7) between them and any capital.

---

### 3.5 🟢 The Python / FastAPI / PostgreSQL stack choice

**What it is.** Python 3.12 everywhere except the P9 Next.js frontend; FastAPI as the API layer;
PostgreSQL 16 with TimescaleDB (a Postgres extension that makes time-series tables fast) in
**every environment from P0** ([ADR-0001](01_ARCHITECTURE.md), accepted 2026-08-30 — there is no
DuckDB/SQLite phase and no migration to perform).

**Why it is genuinely low-risk.** Every one of these is a default choice with a very large user
base, meaning documentation, examples, and AI-agent familiarity are all deep — which matters
enormously when the build is agent-assisted. `DATA_FOUNDATION.md` §4.1 gives the reasoning:
FastAPI is async, generates OpenAPI documentation automatically, and its Pydantic-typed
request/response models fit the connector pattern the ingestion layer needs. Postgres is the most
conservative database choice available for financial data; Timescale is an extension of it, not a
replacement, so adopting it is additive and reversible. There is no exotic component anywhere in
the stack.

**Worst realistic case.** You outgrow one piece — for instance, Timescale hypertables turn out to
be unnecessary at your data volume, or FastAPI's async model complicates a library you want to
use.

**Why that case is cheap.** Timescale hypertables are created with a single function call
(`create_hypertable('price_history','ts')`) and the table remains a normal Postgres table if you
never call it — the decision is one line, in both directions. FastAPI's sync/async boundary is a
per-endpoint decision, not a global one. And `TEAM_BRIEF.md` Part 5 already classifies hosting
and model choice as **"cheap to change later"** while listing the genuinely expensive decisions
separately (canonical chart of accounts, entity identity model, provenance structure, multi-user
assumption, point-in-time discipline). The stack is not on the expensive list, and that
classification is correct.

**Note the one deliberate deviation.** `SPEC.md` places the API at T16/v1.0, but this document
set stands FastAPI up in **P0** instead. That is a documented, deliberate deviation from
`SPEC.md`'s literal task ordering, driven by `SPEC.md` §4.1 invariant 6 ("Mode is server-derived
— never trust a client-supplied mode"): a Streamlit-only application has no server from which to
derive mode. See [01_ARCHITECTURE.md](01_ARCHITECTURE.md). The deviation *reduces* risk rather
than adding it — but it must be written as an ADR so no future agent "corrects" it back
(see [R-104](#r-104--the-fastapi-in-p0-deviation-is-re-litigated)).

---

### 3.6 🟢 Streamlit as the P1–P8 interface

**What it is.** Streamlit turns a Python script into a web page with charts and tables, with no
HTML, CSS, or JavaScript. It is the local user interface for the early phases.

**Why it is genuinely low-risk.** It is deliberately disposable. The architectural decision
already recorded is that **Streamlit is a thin client and never a place logic lives** — it renders
what the FastAPI API returns, and business logic in a Streamlit callback is a defect. That single
rule converts the P9 migration to Next.js from a rewrite into a presentation change.
`DATA_FOUNDATION.md` §4.1 puts it plainly: "a one-user data explorer needs charts + tables, not a
web framework; Streamlit ships Screens A/B in days."

**Worst realistic case.** Streamlit becomes slow with a large table, or its re-run-the-whole-
script execution model makes some interaction awkward.

**Why that case is cheap.** The affected surface is one page, the data is unaffected, and the
replacement (Next.js) is already scheduled for P9 regardless. The worst case is an ugly page for
a few weeks — an inconvenience, not a risk. **The only way Streamlit becomes a real risk is if
the thin-client rule is broken** and logic accumulates inside it; that specific failure is
tracked as [R-101](#r-101--business-logic-leaks-into-streamlit).

---

### 3.7 🟢 The monorepo layout

**What it is.** One repository with `/apps` (web, streamlit, bot), `/services/api`,
`/packages/*` (ingestion, normalize, valuation, indicators, ml, backtest, agents, sentiment,
alerts, portfolio, execution, compliance, common), `/db`, `/tests` — specified in `SPEC.md` §3.1.

**Why it is genuinely low-risk.** The package boundaries map one-to-one onto the conceptual layers
in `SPEC.md` §1.1, which means the layout itself teaches the architecture. A single repository
avoids cross-repo version skew, which is the main cost of splitting early. Moving a package later
is a directory rename plus an import update — mechanical, and exactly the kind of change an agent
does well. There is no distributed-systems complexity to get wrong.

**Worst realistic case.** A package boundary turns out slightly wrong — for example, cost models
sit in `/backtest` but are also needed by `/execution` (they are: `SPEC.md` T19 and T21 both
consume them).

**Why that case is cheap.** Shared code moves to `/packages/common`, or `/execution` imports from
`/backtest`. Either is a small mechanical change with tests to catch breakage. **The layout is
already specified in enough detail that agents will not invent their own**, which is the actual
risk this decision was made to remove.

---

### 3.8 🟢 The DDL design

**What it is.** The database schema: `companies`, `securities`, `source_documents`,
`financial_statements`, `statement_line_items`, `price_history`, `macro_series`,
`macro_observations`, `news_items`, `extraction_jobs` from `DATA_FOUNDATION.md` §4.2, plus
`indicators`, `ml_features`, `ml_models`, `ml_predictions`, `backtest_runs`, `backtest_trades`,
`signals`, `agent_runs`, `agent_messages`, `memos`, `portfolios`, `positions`, `transactions`,
`alerts`, `alert_deliveries`, `audit_log` from `SPEC.md` §3.2.

**Why it is genuinely low-risk.** The hard parts are already right, and they are the parts that
are expensive to retrofit:

- **Provenance is structural, not optional.** `statement_line_items` carries `page`, `confidence`,
  `needs_review`; `financial_statements` carries `source_document_id`; `source_documents` carries
  `url` and `file_hash`. You cannot store a number without being able to say where it came from.
- **Versioning is built in.** `financial_statements` has `version`, `superseded_by`, and
  `restatement`, with a unique key that includes `version` — so a restatement creates a new row
  rather than overwriting one, satisfying `PROJECT_CONTEXT.md` rule 5.
- **Point-in-time is built in.** `macro_observations` has `release_date` and `vintage` in its
  primary key; `ml_features` has `known_as_of`.
- **Multi-user is built in.** `portfolios.owner`, `positions.portfolio_id`, `audit_log.principal`
  — `SPEC.md`'s own editorial header notes this explicitly and warns "do not regress it into
  single-tenant convenience during v0.9–v1.5."
- **The backtest gate is enforced by a foreign key.** `signals.backtest_run_id` references
  `backtest_runs(id)`. A signal that never passed a backtest has nothing to point at. That is the
  strongest possible form of an invariant: the database refuses.

**Worst realistic case.** You need a column that is not there, or a type is wrong.

**Why that case is cheap.** Adopting **Alembic** (a Python database-migration tool that versions
schema changes as code) from the very first schema commit, as `OPERATIONS.md` §2.4 requires,
makes every schema change a reviewable, reversible, testable migration. Adding a column is then a
five-minute operation.

**The honest qualification that keeps this green rather than yellow.** The DDL as written is
**incomplete**, not wrong: `OPERATIONS.md` Part 1 adds six tables it is missing
(`corporate_actions`, `price_adjustments`, `trading_calendar`, `fx_rates`,
`security_identifiers`, plus the fiscal-period columns), and this document adds a corrections
table (G9) and a coverage-metrics table (G10). The *design* is sound; the *coverage* has holes,
and those holes are tracked as gaps rather than as design flaws. Fix them in P0 and the DDL is
genuinely a strength.

---

### 3.9 🟢 LLM availability and capability

**What it is.** The Claude API is used for three things: mapping extracted PDF text to the
canonical chart of accounts (P4), sentiment and entity tagging on news (P5), and the multi-agent
research memos (P9).

**Why it is genuinely low-risk.** Every use is **grounded and validated**, never trusted raw. The
extraction prompt in `DATA_FOUNDATION.md` §3.2 says "Extract ONLY numbers present in the source;
never infer/estimate/fill gaps… If absent, use null", and every output passes deterministic
validation afterwards (balance sheet balances, cash flow ties out, cross-year opening equals
prior closing, magnitude sanity). Memos are RAG-grounded with mandatory citations and a
banned-phrase linter. Costs are bounded by design: cache by document hash so the same PDF is
never extracted twice, tier models (cheap for tagging, expensive only for synthesis), and enforce
a monthly spend cap with an alert at 80% (`SPEC.md` §3.5). The market has multiple capable
vendors, so vendor risk is a swap, not a wall.

**Worst realistic case.** A model version upgrade changes extraction behaviour, and accuracy on
your golden set moves without you changing any code. Or per-token pricing rises.

**Why that case is cheap — with one condition.** `OPERATIONS.md` §2.6 already requires pinning
the **model id and version** in `ml_models` / `extraction_jobs`, because "a model upgrade changes
extraction behaviour, and you must be able to answer 'which model produced this number?'" With
that pin plus the golden set, a behaviour change is detected by a failing test on the next run,
not by a wrong number reaching a chart. **The condition is that the golden set exists** — which
is gap G6. Without it this item is not green, it is red. The rating here assumes G6 is closed in
P0/P3 as recommended.

---

### 3.10 🟢 Deployment on Railway or Render

**What it is.** Managed hosting platforms that run a container and a managed Postgres database
for roughly $20–$60/month at starter scale (`SPEC.md` PART 6; `DATA_FOUNDATION.md` §8.1). Arrives
at P9.

**Why it is genuinely low-risk.** It is a commodity with several equivalent competitors
(Railway, Render, Fly.io, plus Supabase for managed Postgres with auth). The application is a
standard Python container plus a Postgres connection string, which is the single most portable
deployment shape that exists. Postgres is Postgres everywhere — moving providers is `pg_dump`
and `pg_restore`. The cost is small and predictable at family scale, and rises only with users
(which would mean the product is working).

**Worst realistic case.** A provider raises prices, changes its free tier, or has an outage
during a family demo.

**Why that case is cheap.** Migration is a dump, a restore, and a DNS change — hours, not weeks —
*provided* the backup discipline in `OPERATIONS.md` §2.1 exists, because the same `pg_dump` that
backs you up is the same one that migrates you. An outage at family scale is an inconvenience.
`TEAM_BRIEF.md` Part 5 lists hosting explicitly under "cheap to change later" and that is right.

**One thing to keep loud:** hosting outside Nigeria is a **cross-border personal-data transfer**
under NDPA 2023 once you hold third parties' personal data, which needs documented safeguards
(`DATA_FOUNDATION.md` §6.2). That is a P12 legal item ([R-42](#r-42--ndpa--dcpmi-obligations-at-public-launch)),
not a hosting-reliability item.

---

### 3.11 🟢 The connector / adapter pattern

**What it is.** Every data source is a small module with the same three methods — `discover()`
finds new documents or series, `fetch()` retrieves one, `parse()` turns it into canonical records
(`DATA_FOUNDATION.md` §4.3). `EdgarConnector`, `FredConnector`, `AfxKwayisiConnector`,
`NbsCpiConnector` and the rest all look the same from the outside.

**Why it is genuinely low-risk.** It is a well-worn pattern (the document notes it echoes OpenBB's
`Fetcher` design), it is easy for agents to implement repeatedly, and it is the single decision
that converts "a source disappeared" from a crisis into a file swap. `DATA_FOUNDATION.md` §4.3
calls it "the single most important extensibility decision" and `TEAM_BRIEF.md` Part 3 item 3
relies on it as the answer to free-source fragility. Each connector gets a `parse()` test against
a saved raw fixture, so parsing is tested without network access.

**Worst realistic case.** A source's shape does not fit the interface — for instance, a source
that needs pagination state or a login.

**Why that case is cheap.** The interface is a Protocol, not an inheritance hierarchy; a
connector can hold whatever internal state it needs as long as it presents the three methods.
Worst case you add a fourth optional method. **The pattern's value is asymmetric: it costs almost
nothing to adopt and it is the main thing standing between you and [R-01](#r-01--a-free-nigerian-source-changes-layout-or-disappears).**

---

### 3.12 🟢 Telegram as the delivery channel

**What it is.** A Telegram bot pushes the daily brief and alerts (P5 onward), using
`python-telegram-bot` v22.x, verified current at v22.8 as of Aug 2026 (`SPEC.md` §2G).

**Why it is genuinely low-risk.** The library is current and maintained, the API is stable and
well documented, delivery is push-first (which `SPEC.md` §2F notes "beats dashboards for
adherence" — you read what arrives, you forget to open what does not), and idempotency is already
designed: `alert_deliveries` has a unique `idempotency_hash` so the same alert cannot send twice.
Setup cost is a bot token from BotFather, which is minutes.

**Worst realistic case.** Telegram is unavailable, or a bot token is revoked, and a brief does not
arrive one morning.

**Why that case is cheap.** A missed brief is a missed convenience; the data is unaffected and the
brief regenerates. Email via SendGrid/Resend/SMTP is the documented alternative and the alert
layer is channel-agnostic by design (`alerts.channel` is a column). **This is also where
connector-health and freshness alerts should land** (`OPERATIONS.md` §2.3: "one place to look"),
which makes the channel worth setting up early.

---

### 3.13 🟢 The compliance mode-gate *design*

**What it is.** Five mechanisms, all required together (`SPEC.md` §1.2): (1) mode derived
server-side from the authenticated principal, defaulting to `public`; (2) separate Pydantic
output schemas, where `PublicAnalysis` has no fields named `signal`, `recommendation`, `entry`,
`stop_loss`, `target`, or `position_size`; (3) separate `/public/*` and `/personal/*` routers;
(4) middleware that blocks any `PersonalSignal`-typed body on a public response and lints free
text against a banned-phrase list; (5) a dedicated `tests/compliance/` suite that CI must pass.

**Why the design is genuinely low-risk.** It is defence in depth where each layer fails
independently, and the second mechanism is the strong one: if the public serializer only accepts
`PublicAnalysis`, then serializing a `PersonalSignal` into a public response is not "discouraged",
it is **impossible** — a type error, caught at the boundary, in every code path, forever. That is
a far stronger guarantee than a policy or a code review. `SPEC.md` Key Finding 2 puts it well:
"The public product must be architecturally incapable of emitting advice."

**Worst realistic case for the design.** A new endpoint is added that returns a dict instead of a
typed model, bypassing the schema check.

**Why that case is cheap — and where the yellow lives.** The compliance test suite exercises "the
full public surface", so a new untyped endpoint is exactly what it is written to catch, and CI
fails the build. **The design is green; the discipline of never weakening it is
[R-41](#r-41--advice-tier-output-reaches-a-non-family-principal), which is red** — because
`CLAUDE.md` calls this "the only line with real legal risk", and a red rating there reflects
consequence, not design weakness. Trust the architecture; do not trust yourself to remember the
rule without CI enforcing it.

---

### 3.14 🟢 The test approach (golden files, known answers, synthetic backtests)

**What it is.** Four test types are already specified in `SPEC.md` §4.4: golden-file tests (a
fixed PDF must produce an exact expected JSON), known-answer tests (hand-computed vectors for
valuation and indicator math), synthetic-data tests for the backtester (a known-profitable series
must report the right Sharpe; a pure random walk must report roughly zero edge net of costs), and
the compliance suite.

**Why it is genuinely low-risk.** Each test type is matched correctly to what it is testing, which
is rarer than it sounds. Deterministic math gets known answers. Extraction, which is
non-deterministic, gets frozen ground truth. The backtester — the component whose failure mode is
"it lies to you" — gets a test that can actually detect lying, because you know the right answer
in advance for a synthetic series. That third one is the most valuable single test in the project
and it is already mandated. See [07_TEST_STRATEGY.md](07_TEST_STRATEGY.md) for the full plan.

**Worst realistic case.** Tests are written but not maintained, and golden files drift out of date.

**Why that case is cheap — with a condition.** CI running them on every PR keeps them honest, and
the one-task-one-PR rule (`SPEC.md` §4.1 invariant 7) gives every change a natural place to update
them. The condition, again, is that the **golden set exists** (G6) — the test *approach* is green,
but one of its inputs is currently unscheduled.

---

### 3.15 🟢 One database engine, no migration to perform

> **WITHDRAWN AND REPLACED, 2026-08-30.** This section previously rated "DuckDB / SQLite for
> the local phases" 🟢 SOLID and argued the DuckDB→Postgres migration was cheap. That is no
> longer the plan. **[ADR-0001](01_ARCHITECTURE.md) accepted PostgreSQL 16 + TimescaleDB in
> every environment from P0**, closing TG9. The section was the only place in the document set
> that green-lit the rejected option, which made it a trap: a reader arriving here would have
> concluded the decision was both made and safe, in the opposite direction to the three
> documents that actually decided it.

**What it is now.** PostgreSQL 16 + TimescaleDB in local, CI, and production, from P0.

**Why it is genuinely low-risk.** The migration risk this section used to discuss no longer
exists, because there is no second engine to migrate to. Postgres in Docker Compose is one
`compose.yaml` and one `docker compose up -d`; Alembic expresses the schema as migrations from
day one either way. The cost is a container running on the laptop; the thing bought is that
plpgsql triggers, partial unique indexes and `btree_gist` exclusion constraints — which
[08_DATA_CONTRACTS.md](08_DATA_CONTRACTS.md) relies on for the backtest gate, the
no-silent-overwrite rule and non-overlapping ticker identity — work on day one rather than
being deferred behind a rewrite.

**Worst realistic case.** Docker Desktop misbehaves on Windows 11 and costs an afternoon.

**Why that case is cheap.** It is a well-trodden path with abundant documentation, and the
fallback (a native Windows Postgres install) is a supported installer. Neither outcome touches
the schema. **R-102 is closed by ADR-0001** — the migration it tracked will not happen.

---

### 3.16 🟢 The point-in-time and provenance discipline as a *concept*

**What it is.** Two rules that appear in every source document: every figure carries source
document, page, and as-of date; and every feature respects `known_as_of`, so a model trained on
2022 data can only see what was actually knowable in 2022.

**Why the concept is genuinely low-risk.** It is unambiguous, it is testable, and it is already
encoded in the schema (`known_as_of`, `vintage`, `release_date`, `version`, `superseded_by`).
`PROJECT_CONTEXT.md` §9.3 identifies it as "the single most enterprise-grade feature" and the
thing institutional buyers pay premiums for. It costs almost nothing when designed in and is
close to impossible to retrofit, which is why it belongs in P0.

**Worst realistic case for the concept.** None, really — this is one of the few items where the
idea itself carries no downside.

**Where the risk actually lives.** In *enforcement*: a single join that forgets
`WHERE known_as_of <= decision_date` reintroduces look-ahead bias silently. That is
[R-26](#r-26--restatements-corrupt-the-point-in-time-view) and the silent-failure catalogue,
and it is red. **The principle is settled; the vigilance is the work.**

---

### 3.17 A summary of where *not* to spend worry

| Area | Marker | One-line reason |
|---|---|---|
| SEC EDGAR ingestion | 🟢 | Government-mandated, structured XBRL, free, loud failures |
| FRED / World Bank macro | 🟢 | Public-good API, stable for decades, free vintages |
| Ratio / DCF math | 🟢 | Deterministic arithmetic, known-answer testable, stateless |
| Indicator computation | 🟢 | Fixed formulas, maintained library, hand-checkable |
| Python / FastAPI / Postgres | 🟢 | Boring, deep documentation, on the "cheap to change" list |
| Streamlit for P1–P8 | 🟢 | Deliberately disposable, thin client by rule |
| Monorepo layout | 🟢 | Mirrors the architecture; moving a package is mechanical |
| DDL design | 🟢 | Provenance, versioning, point-in-time, multi-user all structural |
| LLM availability | 🟢 | Grounded, validated, cached, capped, multi-vendor |
| Railway / Render hosting | 🟢 | Commodity; migration is a dump and a restore |
| Connector pattern | 🟢 | Cheap to adopt, converts source loss into a file swap |
| Telegram delivery | 🟢 | Current library, idempotent by schema design |
| Compliance gate *design* | 🟢 | Type system makes leakage impossible, not merely discouraged |
| Test approach | 🟢 | Right test type matched to each failure mode |
| Storage engine | 🟢 | One engine everywhere from P0 (ADR-0001); no migration to perform |
| Point-in-time *concept* | 🟢 | Unambiguous, testable, already in the schema |

**Read that table when the project feels overwhelming.** Sixteen substantial components carry
low risk. The genuine danger is concentrated in the Nigerian extraction pipeline and the trading
layer, and both have pre-decided exit routes.

---

## 4. The full register

Every risk, grouped by category. Read the marker first, then the failure mode. **Every 🔴 carries
three approaches with a recommendation**, because a risk you cannot act on is just anxiety.

### 4.1 Data & Sources

**R-01 🔴 Free Nigerian price sources vanish**
*What it is.* NGX daily prices come from `afx.kwayisi.org` / `africanfinancials.com` — scraped,
with no contract and no uptime guarantee ([TEAM_BRIEF.md Part 3](../TEAM_BRIEF.md) item 3).
*How it shows up.* One morning the connector returns 200 OK and zero rows, or the domain stops
resolving.
*Cost.* You lose the daily feed and, worse, you cannot backfill history you never fetched. P6 and
P7 stall.
*Early warning.* `connector_runs` with `status='ok' AND rows_written=0`; layout changes; slower
responses.
*Approaches.* **(1) Cache every raw response permanently from day one** — you keep everything ever
fetched even if the site disappears; near-zero cost. **(2) Subscribe to EODHD `.XNSA` now** —
contractual and backfillable, but paying before you know your coverage needs. **(3) Write the paid
fallback connector but do not subscribe** — [TEAM_BRIEF.md](../TEAM_BRIEF.md)'s own advice, so
switching is "a decision, not a scramble".
***Recommendation: 1 + 3.*** Start fetching on day one of P4; every delayed day is history you may
never buy back cheaply.
*Residual.* You still lose the free feed eventually. The mitigation makes that an inconvenience
rather than a loss.

**R-02 🔴 Government sites (CBN/NBS/DMO) redesign without notice**
*How it shows up.* Silent — the page loads, the selector matches nothing.
*Approaches.* **(1) Manual CSV fallback wired from day one** (Collector task H, ~30 min/month) —
recommended, and it doubles as P3's upload path. **(2) Use FRED/World Bank mirrors** — stable but
they lag and carry no MPR, T-bill or DMO auction data. **(3) Commercial macro vendor** — expensive
for data that is free.
***Recommendation: 1***, with mirrors as a cross-check.

**R-03 🟡 Paid news APIs do not cover Nigeria**
Already established, not discovered later: [DATA_FOUNDATION.md D](../DATA_FOUNDATION.md) checked
and found *"None explicitly confirm Nigerian-source coverage."* RSS-first is the design, not a
budget compromise. *Warning sign:* a vendor's sales page claiming NGX coverage — verify against
actual returned articles before paying.

**R-04 🟡 NGX corporate-action announcements are inconsistent**
Backfill is manual ([TEAM_BRIEF.md 2.2-E](../TEAM_BRIEF.md), 2–3 days). *Warning:* a price series
with an unexplained overnight move above ~20%.

### 4.2 Extraction & Quality

**R-10 🔴 Extraction accuracy plateaus below target — "the one that eats months"**
*What it is.* Nigerian annual reports use borderless tables, inconsistent layouts, occasional
scans. Rules-based extraction alone reaches ~60% ([DATA_FOUNDATION.md 3.1](../DATA_FOUNDATION.md)).
**Every planning document says budget 2–3× your estimate.**
*Cost.* This is the single most likely way the project dies — not by failing, but by consuming all
available time.
*Early warning.* Accuracy improving by less than a point a week; correction rate flat.
*Approaches.* **(1) Hybrid pipeline + permanent human review + 15–25 companies, not 150** —
[TEAM_BRIEF.md](../TEAM_BRIEF.md)'s prescription; lifts ~60% → 90%+. **(2) Buy EODHD and skip the
pipeline** — instant coverage, ongoing cost, and you give up the moat. **(3) Narrow to 5–10
companies you care about most** — accuracy per company rises sharply; coverage becomes a
liability at P12.
***Recommendation: 1, with gate G-A held honestly*** — below 85% after two weeks, take approach 2.
*Residual.* Even at 90%+, one figure in ten needs a human. That is the design, not a defect.

**R-11 🔴 Banks break a schema built for industrials**
*"GTCO's income statement has no 'revenue' line"* ([TEAM_BRIEF.md Part 3](../TEAM_BRIEF.md)).
*Approaches.* **(1) Parallel financial-institution chart of accounts, built before P4**
([DATA_FOUNDATION.md 3.4](../DATA_FOUNDATION.md)) — recommended. **(2) One chart with nullable
bank fields** — simpler, but it invites mapping "gross earnings" to `revenue`, which is a silent
category error. **(3) Exclude banks** — indefensible; banks are a large share of NGX
capitalisation.
***Recommendation: 1***, and include a bank in the first five companies. *"Discovering this in week
two costs a day; discovering it in month four costs a re-extraction."*

**R-12 🟡 LLM fabricates a plausible figure**
Prompt forbids inference; deterministic validation catches identity breaks; sampling (§8.2 of
[07_TEST_STRATEGY.md](07_TEST_STRATEGY.md)) catches the rest. *Warning:* a figure that passes
validation but fails a by-eye check.

**R-13 🟡 Review capacity becomes the ceiling**
~20 corrections/filing × 25 companies × 4 filings ≈ **2,000 corrections/year**
([TEAM_BRIEF.md Part 3](../TEAM_BRIEF.md) item 5). *Warning:* queue depth growing week over week.
*Mitigation:* corrections feed back as few-shot examples so accuracy compounds; prioritise the
queue by materiality. *Escalation trigger:* if correction rate is not falling, the feedback loop
is broken — diagnose immediately.

### 4.3 Correctness & Silent Corruption

**R-20 🔴 Corporate actions not applied — "the highest-priority gap"**
*How it shows up.* It does not. A 2-for-1 split shows as a 50% crash; RSI reads oversold;
volatility doubles; the backtest books a loss that never happened. **No error is raised.**
*Approaches.* **(1) Build all six correctness tables in P3 before any price series is consumed** —
recommended. **(2) Schema now, populate lazily** — you must then track which securities are
adjusted, and that check gets forgotten exactly once. **(3) Defer to P6** — by then you have
months of derived values to recompute, under pressure to start the interesting part. This is how
it gets skipped.
***Recommendation: 1, with volume scoped to the initial universe***, so adding a company later is
a bounded task rather than a project.

**R-21 🔴 Lookahead bias via restatements**
*Symptom: success.* The strategy appears prescient because it used figures nobody had.
*Approaches.* **(1) Mandatory-argument point-in-time accessor + a lint rule banning raw SQL in
`ml`/`backtest`** — forgetting the date becomes a `TypeError`, not a wrong number; recommended.
**(2) Database views embedding the filter** — strong, but parameterised as-of views are awkward in
Postgres. **(3) Convention and code review** — not a mechanism; listed so it is visibly rejected.
***Recommendation: 1***, proved by invariant test I3.

**R-22 🔴 Unit-multiplier errors (thousands vs millions)**
Nigerian statements vary *within a single document*. A figure 1,000× wrong among forty line items
is not visually obvious.
*Approaches.* **(1) `unit_multiplier` captured at extraction + one conversion function in
`common`** — recommended. **(2) Post-hoc magnitude checks** — catches gross errors, misses a
plausible one. **(3) Human review of every figure** — does not scale.
***Recommendation: 1***, backed by the cross-year identity check, which catches a 1,000× error
instantly because it will not tie to last year's closing balance.

**R-23 🟡 Ticker reuse merges two companies**
Surrogate `security_id`; ticker time-bounded ([OPERATIONS.md 1.4](../OPERATIONS.md)). *Warning:* a
price series with an inexplicable discontinuity years back.

**R-24 🟡 FX applied at the wrong date**
USD/NGN moved ₦907.1 → ₦1,535 during 2024. *Mitigation:* `convert()` requires an `as_of` date;
a conversion function without one is a defect.

**R-25 🟡 Fiscal-period mismatch**
Comparing a June year-end to a December year-end. *Mitigation:* `fiscal_year_end` + a
comparability flag rather than silent alignment.

### 4.4 Modelling & Overfitting

**R-30 🔴 The backtester is subtly optimistic**
*Why it dominates:* every bias inflates returns. None makes a strategy look worse. A buggy
backtester is therefore not a coin flip — it is systematically wrong in the expensive direction.
*Approaches.* **(1) Roll your own + mandatory synthetic tests** ([SPEC.md 2C](../SPEC.md)'s
recommendation) — you control the NGX specifics; synthetic tests are a genuinely strong check.
**(2) Cross-validate against `vectorbt`/`backtrader` with costs disabled** — catches blind spots
your synthetic tests did not imagine. **(3) Use an off-the-shelf engine** — fewer core bugs, but
you inherit fill semantics that are wrong for the NGX; no engine models a ±10% halt or a
100,000-share movement threshold.
***Recommendation: 1 for the build, 2 once before any capital moves.***

**R-31 🔴 Overfitting through iteration**
You will run hundreds of variants. *Approaches.* **(1) Honest K + DSR + a genuinely one-touch
holdout** — recommended. **(2) CPCV for a distribution across paths** — strengthens (1); adopt
both. **(3) Pre-registration of strategy hypotheses before testing** — strongest, hardest to
sustain solo.
***Recommendation: 1 + 2***, and record K even when it is embarrassing.

**R-32 🔴 Cost model too optimistic**
At ~4.5% break-even, a 1% error flips losers into winners.
*Approaches.* **(1) Reconcile to a real contract note, to the naira** — recommended, ~2 hours.
**(2) Use published rate cards** — ranges vary by broker; yours is what matters. **(3) Add a
conservative buffer** — hides the error rather than fixing it.
***Recommendation: 1.***

**R-33 🟡 Uncalibrated probabilities drive position sizing**
Kelly takes a probability as input; miscalibration over-bets systematically. *Mitigation:*
`CalibratedClassifierCV`, Brier comparison, reliability diagram read by eye.

**R-34 🟡 Regime change**
Nigerian markets post-2023 float are not the prior regime. *Warning:* out-of-sample performance
decaying with time rather than randomly.

**R-35 🟡 Indicators treated as standalone signals**
Park & Irwin: of 95 studies, 56 positive, 20 negative, 19 mixed, nearly all contaminated by data
snooping ([SPEC.md 2C](../SPEC.md)). *Structural defence:* P7 exists and P8 is gated by it.

### 4.5 Legal & Regulatory

**R-40 🔴 Advice reaches a non-family user pre-licence**
[CLAUDE.md](../CLAUDE.md): *"the only line with real legal risk."*
*Approaches.* **(1) All five enforcement mechanisms + exhaustive route-coverage test** —
recommended; this is the architecture. **(2) A public-mode kill switch that disables advice code
paths entirely at P12** — a strong belt-and-braces addition. **(3) Separate deployments per mode**
— [CLAUDE.md](../CLAUDE.md) explicitly forbids two codebases.
***Recommendation: 1, plus 2 as a P12 addition.***

**R-41 🔴 Redistributing licensed data**
NGX market data is governed by a Data Agreement restricting redistribution
([DATA_FOUNDATION.md 6.3](../DATA_FOUNDATION.md)); [PROJECT_CONTEXT.md 9.3](../PROJECT_CONTEXT.md)
calls it the question that kills deals.
*Approaches.* **(1) `data_sources.redistribution_allowed NOT NULL` enforced at connector
registration** — recommended, one hour in P0. **(2) Serve only derived analytics publicly** — the
safe default, and compatible with (1). **(3) License redistribution from NGX or a vendor** — the
answer if raw data must be served.
***Recommendation: 1 + 2***, with 3 only if a customer requires raw feeds.

**R-42 🟡 NDPA / DCPMI registration missed**
Threshold: personal data of **more than 200 data subjects in six months**; fines up to **2% of
annual gross revenue or ₦10 million, whichever is greater**
([DATA_FOUNDATION.md 6.2](../DATA_FOUNDATION.md)). *Warning:* user count approaching 200.

**R-43 🟡 Regulatory drift**
It moved three times during planning alone: the NGX movement rule approved then postponed a day
before rollout; SEC capital requirements restructured (full-scope fund managers ₦150m → **₦5bn**,
deadline 30 June 2027); share CGT changed January 2026. *Mitigation:* dated configuration, never
constants; a quarterly one-hour review across NGX, SEC, NDPC, FRC, FIRS, recorded as ADRs.

### 4.6 Operational & Continuity

**R-50 🔴 Losing the dataset**
Months of extraction on one laptop. The only unrecoverable failure.
*Approaches.* **(1) 3-2-1 with a quarterly restore drill** — recommended; ten minutes in P0.
**(2) Managed host backups from P9** — necessary but not sufficient; covers nothing before P9 and
not the object store. **(3) Continuous replication to a second machine** — stronger, more to
maintain.
***Recommendation: 1***, adding 2 at P9. **An untested backup is not a backup.**

**R-51 🟡 Silent connector failure** — `rows_written = 0` with `status='ok'`.

**R-52 🟡 Scheduler ownership (TG8)** — a connector nobody runs fails invisibly.

### 4.7 Cost

**R-60 🟡 LLM spend runs away in P4** — the one line that can escape. *Warning:* cost per document
flat or rising rather than falling as the cache warms. *Mitigation:* per-principal caps,
content-hash cache, model tiering, hard ceiling that halts rather than degrades.

**R-61 🟢 Infrastructure cost** — ~$0–5/month through P8, ~$35–90 at P9. Small and predictable.

### 4.8 Product & Adoption

**R-70 🟡 Nobody uses it, including you** — [TEAM_BRIEF.md Part 4](../TEAM_BRIEF.md)'s stage gate
is *"family members log in unprompted."* *Warning:* you stop reading the daily brief.

**R-71 🟡 The brief becomes noise** — an editorial failure, not a technical one. Fewer, better
items.

**R-72 🟡 Memos read as plausible and say nothing** — the characteristic LLM failure.

### 4.9 Execution & Capital

**R-80 🔴 A safety assertion is missing or bypassable**
*Approaches.* **(1) Test every assertion by deliberate violation, not by reading code** —
recommended. **(2) Fail-closed defaults** — any assertion that errors blocks the order. **(3)
Human confirmation on every order** — [SPEC.md 2I](../SPEC.md) requires it in personal mode
anyway.
***Recommendation: all three.*** This is the only place in the project where a bug moves money.

**R-81 🔴 The backtest was optimistic after all** — why P11 exists. *Mitigation:* one month of
paper trading reconciled against backtest expectation; start with capital you can lose entirely.

**R-82 🟡 Emotional override** — the quietest risk. *Warning:* overriding a size, or trading a
name the system did not surface.

**R-83 🟡 NGX manual ticket transcription error** — human in the loop is the design and also a
failure mode. Reconcile every fill.

### 4.10 People & Capacity

**R-90 🔴 Attrition — the most common quiet killer**
[TEAM_BRIEF.md Part 3](../TEAM_BRIEF.md): *"Multi-year projects die in the middle, when novelty is
gone and the PDFs are still badly formatted."*
*Approaches.* **(1) Ship something real early and keep shipping** — v0.1 in a weekend; visible
progress. **(2) Sequence, never parallelise** — one finish line at a time. **(3) Reframe the
boring part as the moat** — *"every week on extraction accuracy is a week nobody else is
spending."*
***Recommendation: all three.*** They are the same discipline seen from three angles.

**R-91 🔴 Three products, one team, no shared finish line**
*"Six months in, the realistic failure is all three half-built."*
***Recommendation:*** **when time is scarce, the data layer wins.** If everything is half-done,
finish the data layer completely and let the rest wait — it is the only piece valuable regardless
of what happens to the other two.

**R-92 🟡 No second reviewer for the golden set** (TG14) — a solo builder either recruits one or
accepts the set encodes one person's assumptions, and says so.

### 4.11 Technical Debt

**R-100 🟡 Single-user assumptions creep in** — *warning:* any module-level constant describing a
person (equity figure, chat ID, email).

**R-101 🟡 Logic migrates into Streamlit** — *warning:* any `SELECT` or arithmetic in
`apps/streamlit/`.

**R-102 🟡 Agent drift on a long spec** — coding agents re-litigate settled decisions and quietly
add advice-shaped fields. *Mitigation:* SPEC as law, one task per PR, CI enforcing invariants.

---

## 5. The known spec gaps

Twenty gaps, found by mapping [SPEC.md 4.2](../SPEC.md)'s T1–T21 against the other documents.
**Work nobody scheduled does not get done.** The canonical register lives in
[00_START_HERE.md](00_START_HERE.md) §9; this section gives the risk framing.

| ID | Gap | Marker | Lands in |
|---|---|---|---|
| **TG1** | Price-history ingestion has no task, yet T9 and T11 both require it | 🔴 blocker | P2, P4 |
| **TG2** | All six [OPERATIONS.md](../OPERATIONS.md) Part 1 correctness tables unscheduled | 🔴 silent corruption | P0 schema, P3 data |
| **TG3** | Auth/identity is one word inside T16, yet mode derives from the principal in P0 | 🔴 legal exposure | P0 |
| **TG4** | Backup/DR unscheduled — the only unrecoverable failure | 🔴 unrecoverable | P0 |
| **TG5** | The data-licensing gate has no enforcing task | 🟡 deal-killer later | P0 |
| **TG6** | Nothing builds the golden set, though T4's acceptance assumes it | 🔴 blocks P4's gate | P3 |
| **TG7** | Chart of accounts has no owning task and no versioning story | 🔴 expensive to change | P2→P3 |
| **TG8** | Nothing owns the scheduler / job runner | 🟡 silent failure | P1→P4 |
| **TG9** | Storage-engine decision contradictory and unscheduled | 🟡 rework risk | P0 |
| **TG10** | Manual override / correction path has no task | 🟡 trust erosion | P3 |
| **TG11** | No `watchlists` table, though T7's brief pulls watchlist moves | 🟡 cheap now | P0 |
| **TG12** | `adjustment_factors` has no point-in-time dimension | 🟡 subtle leak | P3 |
| **TG13** | **No task defines the extraction accuracy *threshold*** — T4 says "≥ threshold" and never sets it | 🔴 unfalsifiable gate | Before P4 |
| **TG14** | Nothing specifies who double-checks the golden set | 🟡 single-perspective | P3 |
| **TG15** | No test asserts paper trader and backtester share a cost-model *instance* | 🟡 drift | P11 |
| **TG16** | The banned-phrase list has no owner or review cadence | 🟡 ages badly | P0, quarterly |
| **TG17** | No task owns object storage for source documents | 🟡 provenance promise fails | P0 |
| **TG18** | No restore-drill cadence defined | 🟡 drills happen once | P0, quarterly |
| **TG19** | No environment-parity check | 🟡 deploy surprises | P0 |
| **TG20** | `system_config` has no owner for regulatory effective-dates | 🟡 stale thresholds | P0, quarterly |

**TG13 deserves specific attention.** It is the only gap that makes another gate meaningless:
until a number is written down, "extraction accuracy ≥ threshold" cannot be passed or failed, and
gate G-A's 85% is an *abandon* trigger, not a target. **Set the target before P4 starts.**

---

## 6. Silent-failure catalogue

Every way this system can be wrong while appearing correct. This is the table to re-read whenever
a result looks good.

| # | Silent failure | What you would see | What actually detects it |
|---|---|---|---|
| 1 | Un-adjusted prices through a split | A clean 50% "crash" | Plot raw vs adjusted across a known ex-date |
| 2 | Lookahead via restatement | An unusually good backtest | Invariant I3: query a restatement before it happened |
| 3 | Survivorship bias | Returns that beat reality | Assert a 2020 universe contains 2022 delistings |
| 4 | Scraper returns 200 with no data | A chart that stops updating | `status='ok' AND rows_written=0` |
| 5 | Missing value became zero | A ratio that looks plausible | Unit test: null in → null out |
| 6 | LLM fabricated a figure | A number with valid provenance | Random sampling against the PDF (§8.2) |
| 7 | Unit multiplier wrong by 1,000× | One line item among forty | Cross-year identity: opening ≠ prior closing |
| 8 | FX at the wrong date | A Naira figure off by ~70% | `convert()` requires `as_of`; spot-check a 2023 figure |
| 9 | Fiscal-period mismatch | A confident comparison | `fiscal_year_end` comparability flag |
| 10 | Ticker reuse merged two companies | A long clean history | Surrogate key + `security_id` continuity check |
| 11 | "Gross earnings" mapped to `revenue` | A comparable-looking number | **A human who understands bank accounting.** No automated test catches this. |
| 12 | Backtester filled at a halted price | A profitable strategy | Blotter inspection line by line (§8.4 of [07_TEST_STRATEGY.md](07_TEST_STRATEGY.md)) |
| 13 | Fill exceeded daily volume | Smooth equity curve | Participation-cap assertion |
| 14 | Same-day round trip under T+3 | Higher turnover than possible | Settlement-lock assertion |
| 15 | Uncalibrated probability | A confident model | Reliability diagram read by eye |
| 16 | `param_hash` omitted | Indicators that change on re-run | Composite primary key |
| 17 | Stale regulatory threshold | Wrong costs or wrong tax | Dated config + quarterly review |
| 18 | Advice as prose in a legal response type | A helpful-sounding sentence | Banned-phrase linter — a net, not a wall |
| 19 | Backup never restorable | A file that looks like a backup | Actually running the restore |
| 20 | Golden set contaminated by tuning | Rising accuracy that is not real | A locked holdout subset |

**Rows 11 and 20 have no automated defence.** They are why [07_TEST_STRATEGY.md](07_TEST_STRATEGY.md)
§8's manual scripts exist, and why "green CI" is not the same as "correct".

---

## 7. Risk-by-phase matrix

Where the danger concentrates. Read down a column before starting that phase.

| Risk | P0 | P1 | P2 | P3 | P4 | P5 | P6 | P7 | P8 | P9 | P10 | P11 | P12 | P13 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| R-01 free NG price source | | | | | 🔴 | | 🟡 | 🟡 | | | | | | |
| R-02 govt site redesign | | 🔴 | | | 🟡 | | | | | | | | | |
| R-10 extraction plateau | | | | 🟡 | 🔴 | | | | | | | | | |
| R-11 banks break schema | | | 🟡 | 🔴 | 🔴 | | | | | | | | | |
| R-13 review capacity | | | | 🟡 | 🔴 | | | | | | | | | |
| R-20 corporate actions | 🟡 | | 🟡 | 🔴 | | | 🔴 | 🔴 | 🔴 | | 🔴 | | | |
| R-21 lookahead | 🟡 | | | 🟡 | | | 🟡 | 🔴 | 🔴 | | | | | |
| R-22 unit multiplier | | | | 🔴 | 🔴 | | | | | | | | | |
| R-30 optimistic backtester | | | | | | | | 🔴 | 🔴 | | | 🔴 | | 🔴 |
| R-31 overfitting | | | | | | | | 🔴 | 🔴 | | | | | |
| R-32 cost model | | | | | | | | 🔴 | | | | 🟡 | | 🟡 |
| R-40 advice leak | 🔴 | | | | | 🟡 | | | 🟡 | 🔴 | | | 🔴 | |
| R-41 redistribution | 🟡 | 🟡 | | | | | | | | | | | 🔴 | |
| R-50 losing the dataset | 🔴 | | | 🔴 | 🔴 | | | | | | | | | |
| R-80 safety assertions | | | | | | | | | | | | | | 🔴 |
| R-90 attrition | | | | 🟡 | 🔴 | | | 🟡 | | | | | | |
| R-91 three half-products | | | | | 🔴 | | | | | 🟡 | | | | |

**The concentration is obvious and worth naming: P3–P4 and P7–P8.** P3–P4 is where data
correctness and human capacity collide; P7–P8 is where self-deception is cheapest. Those four
phases deserve disproportionate care; the rest are ordinary engineering.

---

## 8. Decision gates

The points where stopping, buying, or abandoning is the correct call — with the measurable trigger
for each. Written in advance because the moment you need them is the moment you will least want to
honour them. Full detail in
[04_ROADMAP_PART2_PHASES_7-13.md](04_ROADMAP_PART2_PHASES_7-13.md).

| # | Gate | Trigger | Correct call |
|---|---|---|---|
| **G-A** | Extraction accuracy | < 85% on the golden set after **two weeks** | Buy EODHD and move on. A purchase, not a failure. |
| **G-B** | P4 timebox | Three weeks with no other phase touched | Ship what works; return later |
| **G-C** | Backtester integrity | A random walk shows an edge | **Stop everything.** Every result is void. |
| **G-D** | Cost reality | Profitable gross, losing net of the ~4.5% round trip | Information, not defeat. Pivot to lower turnover, or keep the data product and drop systematic NGX trading. |
| **G-E** | Backtest gate | DSR < 0.95, or fails to beat logreg or buy-and-hold | Stays in research. **Do not lower the threshold.** |
| **G-F** | Suspicious accuracy | OOS accuracy > ~60% | Assume a leak; find it before believing it |
| **G-G** | Paper vs backtest | Material divergence over a month | Do not proceed to P13 |
| **G-H** | Review capacity | Queue growing and correction rate not falling | Cut the universe, not the review |
| **G-I** | Cost | Over cap two months running | Re-tier models, widen cache, cut coverage |
| **G-J** | Compliance | Any public route can emit advice | **Do not launch.** No exceptions. |
| **G-K** | Licensing | A served source cannot state redistribution rights | Derived analytics only, or license it |
| **G-L** | Attrition | Months with no progress | **Finish the data layer.** It is valuable regardless. |

---

## 9. The honest verdict

Synthesising [DATA_FOUNDATION.md 8.5](../DATA_FOUNDATION.md), [SPEC.md PART 6](../SPEC.md) and
[TEAM_BRIEF.md](../TEAM_BRIEF.md)'s "honest floor".

**Is this achievable?** The data platform: **yes, with high confidence.** US ingestion, macro,
ratios, DCF, scenarios, the web app, portfolio tracking — all well-trodden. The Nigerian
extraction pipeline is hard but demonstrably tractable at 15–25 companies with a human in the
loop, and it is the part nobody else has done, which is exactly why it is worth doing.

**The trading layer is a different proposition.** [SPEC.md PART 6](../SPEC.md) is blunt: expect *a
thin, fragile edge at best, especially on NGX*. A ~4.5% round-trip break-even is a severe
handicap; Harvey, Liu & Zhu argue most published factor findings are false; and the honest
possibility — which the architecture is deliberately built to *detect* rather than hide — is that
P7 tells you there is no edge. **That is a successful outcome for P7**, not a failure. Discovering
it in a backtester costs weeks. Discovering it with capital costs the capital.

**The three conditions under which this succeeds:**

1. **Sequence, do not parallelise.** One finish line at a time. R-91 is the most likely structural
   failure.
2. **Honour the gates.** Especially G-A and G-E, and especially when you do not want to.
3. **Treat the data layer as the deliverable.** [PROJECT_CONTEXT.md 272](../PROJECT_CONTEXT.md):
   the thing that makes it acquirable is the same thing that makes it useful — a dataset nobody
   else has. Everything else is optional upside.

**The honest floor** ([TEAM_BRIEF.md 234](../TEAM_BRIEF.md)): even if the ML signals never clear
the gate, even if the public product never launches, even if the trading layer is abandoned
entirely — **a clean, provenance-tracked dataset of Nigerian company financials is a real asset
that did not exist before, and it is useful the day it exists.** That floor is high enough to
justify starting, and it is reachable by P4.

The risk is not that this fails. The risk is that it becomes three half-built things. The
sequencing in these documents exists to prevent exactly that.

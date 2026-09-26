# 09 — Glossary

**What this document is for.** This is the plain-language dictionary for the whole project. The
owner's instruction was: *"make sure every corner and piece of what the app will be about is
entailed in pure detail lower understandable terms so i can see to. I dont want to build this
blind."* This file is the safety net for that instruction. Any term that appears anywhere in
the six source documents (`CLAUDE.md`, `PROJECT_CONTEXT.md`, `SPEC.md`, `DATA_FOUNDATION.md`,
`OPERATIONS.md`, `TEAM_BRIEF.md`) or the eight sibling planning documents, and that a
competent generalist would not instantly know, is defined here. Every entry starts in plain
words before it gets precise, says why the term matters *in this specific build* rather than
in a textbook, and gives a concrete example with real numbers or a real ticker wherever one
exists. Read it front to back once so you know what is in it; after that, use it as a lookup.

**How entries are laid out.**

| Field | What it gives you |
|---|---|
| **Plain words** | The first sentence assumes no finance and no machine-learning background. |
| **Precisely** | The exact definition, where it differs from the plain one. Skip it if the plain one was enough. |
| **Why it matters here** | The decision, table, phase, or risk in *this* build that the term attaches to. |
| **Example** | Real ticker, real number, real file path, real SQL where possible. |
| **Common misunderstanding** | The thing people reliably get wrong. Only present where one exists. |
| **See also** | Related entries and the sibling document that owns the topic. |

**Risk markers.** Some entries carry a marker, using the same system as the rest of the
document set:

- 🟢 **SOLID** — well understood, low variance, failure is obvious and cheap to fix. Stop worrying about it.
- 🟡 **WATCH** — it will work, but there is a known failure mode, a cost curve, or a dependency that can move. The entry names the early-warning signal.
- 🔴 **FRAGILE** — genuinely likely to go wrong, or the estimate could be off by multiples. Every FRAGILE entry gives **three distinct approaches** with trade-offs and a recommendation.

Markers appear only where the term names something that carries real project risk. Most
glossary entries are just definitions and carry no marker. The full risk treatment lives in
[06_RISK_REGISTER.md](06_RISK_REGISTER.md); markers here are pointers, not a substitute.

**Citation convention.** Facts sourced from the planning documents are cited inline as
`(SPEC.md §2C)`, `(OPERATIONS.md §1.1)`, and so on, so you can verify any claim in one step.
Anything not stated in the source documents and not known with confidence is marked
**[NEEDS VERIFICATION]** with a note on what to check and where.

**Current build position: P0 has not started.** As of writing, `c:\quant_model\` contains the
six planning markdown files, an empty `package.json`, and `node_modules/`. There is no `.git`,
no Python, and no application code. Nothing in this glossary describes something that exists
yet — it describes what the terms will mean once built.

---

## Table of contents

- [How to use this document](#how-to-use-this-document)
- [The four numbering systems — read this before anything else](#the-four-numbering-systems--read-this-before-anything-else)
- [Section 1 — Project-specific terms](#section-1--project-specific-terms)
- [Section 2 — Finance and accounting](#section-2--finance-and-accounting)
- [Section 3 — Nigerian market specifics](#section-3--nigerian-market-specifics)
- [Section 4 — US market and data sources](#section-4--us-market-and-data-sources)
- [Section 5 — Quant, statistics and machine learning](#section-5--quant-statistics-and-machine-learning)
- [Section 6 — Technical indicators](#section-6--technical-indicators)
- [Section 7 — Engineering and infrastructure](#section-7--engineering-and-infrastructure)
- [Section 8 — Acronym quick-reference table](#section-8--acronym-quick-reference-table)
- [Section 9 — Gaps this document surfaces](#section-9--gaps-this-document-surfaces)
- [Section 10 — Terms deliberately not defined here](#section-10--terms-deliberately-not-defined-here)

> ## ⚠️ THIS FILE IS INCOMPLETE — read this before using the contents above
>
> **Only Section 1 exists.** Sections 2–10 were never written; the file ends at an
> `<!-- APPEND-HERE -->` marker where a generation run stopped. **Every link in the table of
> contents above except Section 1 is dead**, along with roughly 50 "See also" cross-references
> inside Section 1 pointing at entries in the missing sections. Found by the pre-build audit,
> 2026-08-30.
>
> **What this means in practice:**
>
> - Terms outside Section 1's project-specific vocabulary — DSR, CPCV, triple-barrier, IAS 29,
>   WHT, hypertable, embargo, and the finance/accounting, Nigerian-market, quant and
>   engineering vocabularies generally — are **not defined here**. Use the source document
>   cited inline instead.
> - **Section 9 does not exist, so gaps `G7`–`G11` were never defined.** They are referenced
>   from this file and from [02_INFRASTRUCTURE.md](02_INFRASTRUCTURE.md) §1.3 as though they
>   were. Treat the `G` numbering as **retired**: the canonical gap register is
>   [00_START_HERE.md](00_START_HERE.md) §9 (`TG1`–`TG23`), and the one G-gap whose subject
>   was known — clock and timezone discipline — is now **TG21** there.
> - **Do not route a cold reader here.** `00_START_HERE.md` §4's reading routes send newcomers
>   to this file for term lookup; until Sections 2–10 exist, that route half-works.
>
> **Fixing it is optional and low-priority.** Nothing in P0–P13 is blocked by a missing
> glossary. Finish the sections when a term actually costs you time, or delete the phantom
> entries from the TOC. What is *not* optional is that no other document may cite Section 9 as
> the definition of a gap — that citation is what turned a missing glossary into an
> unauditable gap register.

---

## How to use this document

Three ways.

**1. Lookup.** You hit a word in another document and don't know it. Use your editor's find on
the term. Every entry is an `###` heading, so the term is on its own line.

**2. Onboarding sweep.** Read Section 1 (project-specific terms) end to end. Those terms are
the private vocabulary of this build — nobody outside this project uses "mode gate" or "the
backtest gate" to mean exactly what we mean. Everything else in the glossary is standard
industry vocabulary you could also look up elsewhere; Section 1 is not.

**3. Family onboarding.** [PROJECT_CONTEXT.md §7](../PROJECT_CONTEXT.md) names family
onboarding as a practical gap: *"The owner will understand every number; family will not."*
Sections 2 (finance) and 6 (indicators) are written so a family member with no finance
background can read them. Point them at those two sections plus
[05_USER_STORIES.md](05_USER_STORIES.md), not at `SPEC.md`.

**What this document is not.** It is not a **data dictionary**. A data dictionary documents
every column of every table — its type, its allowed values, its nullability, its foreign keys.
That belongs in [08_DATA_CONTRACTS.md](08_DATA_CONTRACTS.md), and
[PROJECT_CONTEXT.md §9.4](../PROJECT_CONTEXT.md) lists a data dictionary as a cheap thing to
add early for acquirability. This file defines *words*; that one defines *fields*. See
[Section 9, gap G9](#section-9--gaps-this-document-surfaces).

---

## The four numbering systems — read this before anything else

This is the single most common source of confusion in the source documents, and it will bite
you within a week. There are **four** parallel numbering schemes in play, and two of them use
the identical string `T2` to mean two completely different pieces of work.

| Scheme | Looks like | Defined in | What it counts |
|---|---|---|---|
| **Phases** | `P0` … `P13` | The `docs/` planning set (this set) | The delivery sequence you actually work through |
| **Versions** | `v0.1` … `v2.5` | [SPEC.md §1.3](../SPEC.md) | The product milestone each phase ships |
| **SPEC tasks** | `T1` … `T21` | [SPEC.md §4.2](../SPEC.md) | Build tasks for the *whole* system including the trading half |
| **Doc A tasks** | `T1` … `T16` | [DATA_FOUNDATION.md §7.4](../DATA_FOUNDATION.md) | An *older, separate* task list for the v0.1→v1.0 data layer only |
| **Doc B levels** | `Level 1` … `Level 4` | Document B (merged into SPEC.md; **the file itself is not in the repo**) | The four intelligence layers: intel, signals, agents, execution |

`DATA_FOUNDATION.md §7.4` says so itself: *"these T-numbers are Doc A's own and are **distinct
from SPEC.md §4.2's T1–T21**. When assigning agent work, cite the document explicitly
('DATA_FOUNDATION T9', 'SPEC T11') to avoid collision."*

**The trap in practice.** [OPERATIONS.md §1.1](../OPERATIONS.md) says corporate actions should
be built "in **DATA_FOUNDATION T8**" (the `AfxKwayisiConnector` task). [OPERATIONS.md
§2.4](../OPERATIONS.md) says adopt Alembic "from **DATA_FOUNDATION T2**" (the schema task).
Neither of those is SPEC T8 (scenario engine) or SPEC T2 (EDGAR connector). If you or a coding
agent read those as SPEC numbers, you will schedule the work into the wrong phase.

**The rule for this document set: an unqualified `T<n>` always means SPEC.md §4.2.** Doc A task
numbers are always written out in full as `DATA_FOUNDATION T<n>`. Never write a bare `T8`
meaning Doc A.

**The full mapping.**

| Phase | Name | Version | SPEC tasks | Doc B level |
|---|---|---|---|---|
| **P0** | Foundation & Rails | (pre-v0.1) | repo init, monorepo (SPEC §3.1), full DDL, FastAPI skeleton, mode middleware (T15 core), CI, test scaffold, ADR log | — |
| **P1** | Macro Backdrop | v0.1 | T1 | — |
| **P2** | US Company Data | v0.2 | T2 | — |
| **P3** | Nigerian Manual Analyzer | v0.3 | T3 + OPERATIONS Part 1 correctness tables | — |
| **P4** | Nigerian Automated Ingestion | v0.4 | T4 | — |
| **P5** | News, Sentiment & Daily Brief | v0.5 | T5, T6, T7 | Level 1 |
| **P6** | Scenarios & Indicators | v0.6–v0.7 | T8, T9 | (indicators feed Level 2) |
| **P7** | Backtesting — THE GATE | v0.8 | T10, T11 | (new; not in Doc B) |
| **P8** | ML Signals | v0.9 | T12, T13 | Level 2 |
| **P9** | Memos & Hosted Web App | v1.0 | T14, T16 | Level 3 |
| **P10** | Portfolio & Alerts | v1.2 | T17, T18 | — |
| **P11** | Paper Trading | v1.5 | T19 | — |
| **P12** | Public Beta | v2.0 | T20 | — |
| **P13** | Personal Execution | v2.5 | T21 | Level 4 |

**T15 is not a phase.** Compliance middleware is marked "front-loaded, all versions" in
[SPEC.md §4.2](../SPEC.md). Its core lands in P0 and it is hardened in every phase through P12.

**Doc B does not exist as a file you can open.** `SPEC.md` describes itself as merging
"Document A (the data foundation) and Document B (the intelligence/signal/agent layers)".
Document A is `DATA_FOUNDATION.md` and is in the repo. Document B was consumed into `SPEC.md`
and is not. So a reference like "Doc B **Level 2**" resolves to a *section of SPEC.md*, not to
a separate document. Do not go looking for `DOC_B.md`.

See also: [00_START_HERE.md](00_START_HERE.md),
[03_ROADMAP_PART1_PHASES_0-6.md](03_ROADMAP_PART1_PHASES_0-6.md),
[04_ROADMAP_PART2_PHASES_7-13.md](04_ROADMAP_PART2_PHASES_7-13.md).

---

## Section 1 — Project-specific terms

These are the words this project uses in a specific way. If you look them up on the internet
you will get a different or vaguer answer than the one that applies here. Read this section
end to end.

---

### Access model

**Plain words.** The rule for who is allowed to log in and what they are allowed to see, kept
completely separate from the question of what the software is *capable* of.

**Precisely.** [PROJECT_CONTEXT.md §4](../PROJECT_CONTEXT.md) states it as two axes that must
never be conflated: **build scope** (what the system can do) versus **access** (who can reach
it). Build scope is "everything, public-grade, general-purpose, multi-user" from day one.
Access is "owner + family only" today, and "+ the public" after the SEC licence.

**Why it matters here.** This is the decision that saves the most rework. The naive reading of
"we are not licensed yet" is *don't build the advice features*. That reading is wrong and
[CLAUDE.md](../CLAUDE.md) explicitly forbids it: *"Do not add public-facing disclaimers or
strip advice features on the assumption this is a regulated product; it is not."* The system
may say BUY today, because it is the owner's own capital and his family's capital, and there
is no third-party client and therefore no registrable activity.

**Example.** The signal engine (P8 / T13) is built to serve any number of users with per-user
position sizing. Today exactly two principals have the `signals:read` entitlement. On the day
the SEC licence lands, opening it to the public is an entitlement change plus a disclosure
banner — no new code paths, no fork.

**Common misunderstanding.** People read "restricted access" as "reduced product." It is the
opposite: the product is complete, the door is narrow.

**See also:** [Build scope vs access control](#build-scope-vs-access-control),
[Entitlements](#entitlements), [Mode gate](#mode-gate), [Personal mode](#personal-mode),
[Public mode](#public-mode), [`licence_status`](#licence_status),
[01_ARCHITECTURE.md](01_ARCHITECTURE.md).

---

### Acquirability (and "the moat")

**Plain words.** "The moat" is the part of this project a competitor cannot copy quickly.
"Acquirability" is the set of properties that would make a bigger company want to buy this
one rather than build their own.

**Precisely.** [PROJECT_CONTEXT.md §9.3](../PROJECT_CONTEXT.md) names four things that make a
data company acquirable: (1) a proprietary dataset expensive to replicate — *"Five years of
normalized NGX financials is not something a buyer can spin up in a quarter. **This is the
moat**"*; (2) point-in-time integrity — *"the single most enterprise-grade feature. Do not
compromise it for speed"*; (3) API-first architecture with stable identifiers; (4) clean
licensing rights — *"This is the one that kills deals."*

**Why it matters here.** These four are not marketing. Each one maps to a concrete build
decision you make in P0–P4: versioned statements with `known_as_of` (point-in-time),
`security_identifiers` with `valid_from`/`valid_to` (stable IDs), a versioned public API, and
a per-source record of redistribution rights. Retrofitting any of them costs months.

**The project's stated position, which is contested elsewhere.**
[PROJECT_CONTEXT.md §9.5](../PROJECT_CONTEXT.md) is blunt: *"**Acquisition is a poor primary
goal.** Most companies aren't acquired, and building to be bought usually produces something
nobody wants."* It also notes the Nigerian institutional market is small — *"perhaps a few
dozen serious accounts"* — and price-sensitive. So: build the four properties because they
also make the product *good*, not because you are optimising for an exit. The exit is an
option, not a plan.

**See also:** [Coverage metrics](#coverage-metrics),
[Data licensing / redistribution rights](#data-licensing--redistribution-rights),
[Point-in-time](#point-in-time), [Stable entity ID](#stable-entity-id--securitiesid).

---

### As-of date

**Plain words.** The date a number was true — not the date you fetched it, and not today.

**Precisely.** Every stored figure carries the date of the period or observation it describes.
For a financial statement line item this is the `period_end`. For a macro series it is the
observation date. It is distinct from `retrieved_at` (when the scraper downloaded it),
`release_date` (when the publisher put it out), and `known_as_of` (the first date you could
have acted on it).

**Why it matters here.** [CLAUDE.md](../CLAUDE.md) hard rule: *"Provenance on every figure —
source document, page, **as-of date**. Non-negotiable."* And
[PROJECT_CONTEXT.md §7](../PROJECT_CONTEXT.md): *"Every screen must show an 'as of' date
prominently."* Without it you cannot tell a stale number from a fresh one, and the whole
"instrument, not judgment" promise collapses — a figure with no date is a rumour.

**Example.** The NBS CPI screen shows `Headline inflation 24.48% y/y — as of Jan 2025,
released 18 Feb 2025, retrieved 2026-08-27` (figures from
[DATA_FOUNDATION.md Key Finding 3](../DATA_FOUNDATION.md)). Three different dates, three
different meanings, all displayed.

**Common misunderstanding.** Conflating as-of with retrieval date. If you scrape MTN Nigeria's
FY2024 annual report in August 2026, the as-of date is 31 Dec 2024, not August 2026. Charts
keyed on retrieval date are meaningless.

**See also:** [`known_as_of`](#known_as_of), [Point-in-time](#point-in-time),
[Provenance](#provenance), [Staleness](#staleness), [Vintage](#vintage--alfred-vintages).

---

### Audit log

**Plain words.** A permanent, append-only record of who asked the system for what, in which
mode, and whether the compliance layer blocked it.

**Precisely.** The `audit_log` table ([SPEC.md §3.2](../SPEC.md)) with columns
`ts, principal, mode, endpoint, action, compliance_result, payload_hash`.
[SPEC.md §3.3](../SPEC.md): *"All personal-mode actions and all compliance blocks write to
`audit_log`."*

**Why it matters here.** It is the evidence that the mode gate worked. If a question is ever
asked — internally, by a family member, or by a regulator after the public launch — the audit
log is the answer. `payload_hash` rather than the payload itself keeps the log small and avoids
duplicating personal data (relevant under NDPA 2023).

**Example.** A row reads
`2026-09-14T08:02:11Z | principal=frank | mode=personal | endpoint=/personal/signals/MTNN |
action=signal_issued | compliance_result=ok | payload_hash=sha256:9f2c…`.

**Common misunderstanding.** Treating it as debug logging. It is not — it is a durable record
keyed by principal, and it must survive a database restore. It is also multi-user by
construction: `audit_log.principal` is exactly the column
[CLAUDE.md](../CLAUDE.md) means by *"every audit row carries its principal."*

**See also:** [Principal](#principal), [Compliance middleware](#compliance-middleware),
[Mode gate](#mode-gate), [02_INFRASTRUCTURE.md](02_INFRASTRUCTURE.md).

---

### Backtest gate, the

🟢 **SOLID** — the mechanism is simple, cheap, and its failure mode (nothing trades) is safe.

**Plain words.** A hard rule that says: no trading strategy is allowed to touch real money
until it has passed a specific, recorded test proving it probably isn't just luck.

**Precisely.** [SPEC.md §2C](../SPEC.md) defines it as a set of pre-registered pass criteria
that a recorded `backtest_run` row must meet before a signal can be issued:

- Deflated Sharpe Ratio **≥ 0.95** given the recorded trial count K
- Positive **net-of-cost** return after the full NGX cost stack
- Drawdown within tolerance
- Stable across **CPCV** paths — not one lucky path out of many
- Beats **both** the logistic-regression baseline **and** buy-and-hold, out of sample

*"Fail any → stays in research, never trades."* It is enforced in the schema, not just in
process: `signals.backtest_run_id` is a foreign key to `backtest_runs(id)`, described in
[SPEC.md §3.2](../SPEC.md) as *"gate provenance."* T13's acceptance criterion is
*"signal only issued with a passing `backtest_run_id`."*

**Why it matters here.** It is one of the seven build invariants
([SPEC.md §4.1](../SPEC.md), item 3) and appears in [CLAUDE.md](../CLAUDE.md) as a hard rule.
Without it, the honest expected outcome of a solo-built ML trading system is losing money
slowly while believing the backtest. [SPEC.md Part 6](../SPEC.md) says exactly that:
*"expect a thin, fragile edge at best, especially on NGX; keep it personal-only and be
ruthless with the backtest gate."*

**Example.** You run 40 parameter variations of a momentum strategy on 20 NGX names. The best
one reports Sharpe 1.8. You record K=40. DSR deflates that to 0.61. **Gate fails.** The
strategy does not trade. That is the system working, not a disappointment.

**Common misunderstanding.** Thinking the gate is a formality you tune until it passes. Tuning
until it passes *is* the failure — every extra attempt raises K, which lowers DSR, which makes
the gate harder. The gate is designed so that trying harder makes it stricter.

**Common misunderstanding, second.** Thinking the gate is a one-time event. It is per
strategy, per re-train. A retrained model needs a new passing `backtest_run`.

**See also:** [DSR](#dsr--deflated-sharpe-ratio-and-the-trial-count-k),
[CPCV](#cpcv--combinatorial-purged-cross-validation),
[Buy-and-hold baseline](#buy-and-hold-baseline),
[Logistic regression baseline](#logistic-regression-baseline),
[04_ROADMAP_PART2_PHASES_7-13.md](04_ROADMAP_PART2_PHASES_7-13.md).

---

### Banned-phrase linter

**Plain words.** A filter that reads every piece of text the system is about to show a public
user and blocks it if it contains advice-shaped words like "buy", "target price", or
"undervalued".

**Precisely.** Mechanism 4 of the five compliance mechanisms in
[SPEC.md §1.2](../SPEC.md): *"runs banned-phrase linting on all free-text LLM output
(Document A's list: 'buy', 'sell', 'strong buy', 'price target', 'you should', 'we recommend',
'undervalued/overvalued' as verdicts, etc.). A hit raises `ComplianceBlock` → audited error,
never a leaked response."* [DATA_FOUNDATION.md §4.6](../DATA_FOUNDATION.md) calls it the
*"banned-output filter"* and specifies *"a regex/classifier rejecting
'buy/sell/target/undervalued/recommend.'"*

**Why it matters here.** Large language models drift. You can instruct Claude twenty times to
avoid recommendations and it will still occasionally write "this looks undervalued". The
linter is the deterministic backstop that makes the guarantee mechanical rather than
aspirational. It runs in **public mode only** — in personal mode the same sentence is allowed
and expected.

**Example.** The scenario narrator produces: *"At your 12% discount rate the model implies a
value 30% above the current price, which suggests the stock is undervalued."* In public mode
the linter fires on `undervalued`, raises `ComplianceBlock`, writes an audit row, and the user
gets a blocked-response error rather than the sentence. In personal mode it passes through.

**Common misunderstanding.** Thinking a regex list is enough. It catches the obvious cases;
paraphrase defeats it ("worth more than it costs"). It is one of *five* mechanisms, and the
strongest ones are the type-level ones — a `PublicAnalysis` Pydantic model that has no field
named `target` cannot carry a price target no matter what the text says. The linter is the
last line, not the only line.

**Common misunderstanding, second.** Over-blocking. "Buy" appears legitimately in
"share buyback", "buy-side", and "buying power". The linter needs word-boundary and context
handling or it will block valid analytics. Its test battery
([SPEC.md §1.2](../SPEC.md) mechanism 5) must include false-positive cases, not only
true-positive ones.

**See also:** [Compliance middleware](#compliance-middleware), [Mode gate](#mode-gate),
[Public mode](#public-mode), [07_TEST_STRATEGY.md](07_TEST_STRATEGY.md).

---

### Build scope vs access control

**Plain words.** Two different questions that look like one: *what can the software do?* and
*who is allowed to use it?* This project answers the first with "everything" and the second
with "two people, for now."

**Precisely.** The table from [CLAUDE.md](../CLAUDE.md):

| | Build scope | Who can reach it |
|---|---|---|
| Now | Everything — public-grade, general-purpose, **multi-user** | Owner + family only |
| After the SEC licence | Unchanged | + the public |

*"Build it as if everyone will use it. Restrict who can log in, not what it can do. The licence
widens the audience; it does not add features. Nothing gets built twice."*
([PROJECT_CONTEXT.md §4](../PROJECT_CONTEXT.md))

**Why it matters here.** It is the reason multi-user is mandatory from day one.
[CLAUDE.md](../CLAUDE.md): *"**The expensive shortcut to avoid: never assume a single user.**"*
A single-user trading layer is a full rewrite to open up; a multi-user one that currently has
two users is a config change.

**Example of the shortcut to avoid.** Writing `ACCOUNT_EQUITY = 5_000_000` in a config file and
having the position sizer read it. That single line makes the sizing engine single-tenant. The
correct version takes equity as a parameter on the request, resolved from the calling
principal's portfolio.

**See also:** [Access model](#access-model), [Principal](#principal),
[Entitlements](#entitlements), [Position sizing](#position-sizing).

---

### Canonical chart of accounts

**Plain words.** One master list of standard names for financial-statement lines, so that
"Turnover" in one company's report and "Gross earnings" in another's and `Revenues` in a US
XBRL filing all end up stored under the same key.

**Precisely.** [DATA_FOUNDATION.md §3.4](../DATA_FOUNDATION.md) defines the mapping: map both
US-GAAP XBRL tags **and** Nigerian IFRS labels to common `canonical_key`s. Examples given
verbatim: `revenue` ← `Revenues` / `RevenueFromContractWithCustomerExcludingAssessedTax` /
"Revenue" / "Turnover" / "Gross earnings" (banks); `operating_profit` ← `OperatingIncomeLoss`
/ "Results from operating activities"; `profit_after_tax` ← `NetIncomeLoss` / "Profit/(loss)
for the year"; `total_assets` ← `Assets` / "Total assets"; `total_equity` ←
`StockholdersEquity`; `cash_from_ops` ← `NetCashProvidedByUsedInOperatingActivities`.

**Why it matters here.** Without it there is no comparability, and comparability is the whole
point of the product. It is also *the schema decision most expensive to change mid-build*
([TEAM_BRIEF.md §2.2-G](../TEAM_BRIEF.md)): *"Changing it after the extractor is running means
re-extracting everything."* Both [TEAM_BRIEF.md §5](../TEAM_BRIEF.md) and
[OPERATIONS.md §3.1](../OPERATIONS.md) list it among the "expensive to change later" items
that need an ADR.

**Banks need a second chart.** This is the specific trap.
[TEAM_BRIEF.md §3, bottleneck 2](../TEAM_BRIEF.md): *"GTCO's income statement has no 'revenue'
line — it has gross earnings, net interest income, and impairments. A schema built on MTN will
not survive a bank."* So build a `statement_template` per industry — financial versus
non-financial ([DATA_FOUNDATION.md §3.4](../DATA_FOUNDATION.md)) — and include at least one
bank in the first five companies so this surfaces in week two rather than month four.

**Example.**

```
canonical_key = "revenue"
  ← MTN Nigeria FY2024 AR, as_printed = "Revenue"
  ← Nestlé Nigeria FY2023 AR, as_printed = "Turnover"
  ← GTCO FY2024 AR, as_printed = "Gross earnings"   ← different template
  ← AAPL 10-K, XBRL tag = "RevenueFromContractWithCustomerExcludingAssessedTax"
```

**Common misunderstanding.** Thinking the canonical key replaces the original label. It does
not. `statement_line_items` stores **both** `canonical_key` (for querying) and `as_printed`
(the verbatim label from the page, for provenance display). You must always be able to show
the user the words that were actually printed in the audited filing.

**See also:** [`canonical_key`](#canonical_key), [IFRS](#ifrs),
[Gross earnings](#gross-earnings-banks), [Line item](#line-item),
[08_DATA_CONTRACTS.md](08_DATA_CONTRACTS.md).

---

### `canonical_key`

**Plain words.** The standard machine-readable name of a financial-statement line, e.g.
`revenue`, `total_assets`, `cash_from_ops`.

**Precisely.** A column on `statement_line_items`
([DATA_FOUNDATION.md §4.2](../DATA_FOUNDATION.md)). It is the join key that makes cross-company
and cross-country comparison possible, and it is what the ratio engine, the DCF engine, and the
ML feature builder all read.

**Why it matters here.** Every downstream consumer depends on it being stable. If you rename
`profit_after_tax` to `net_income` in month five, every ratio formula, every chart, and every
stored feature silently breaks or returns null.

**Common misunderstanding.** Thinking a missing `canonical_key` means the value is zero. It
means the value is **null** — the invariant "never infer missing financial data"
([SPEC.md §4.1](../SPEC.md), item 4) applies. A company that did not disclose a line and a
company that disclosed it as zero are different facts and must stay different.

**See also:** [Canonical chart of accounts](#canonical-chart-of-accounts),
[Never infer missing financial data](#never-infer-missing-financial-data).

---

### Compliance middleware

**Plain words.** A layer that sits between the application and the outside world, checks every
response before it leaves, and refuses to send anything that looks like investment advice to
someone who is not entitled to receive it.

**Precisely.** SPEC task **T15**, marked *"front-loaded, all versions"*
([SPEC.md §4.2](../SPEC.md)) — its core lands in P0 and it is hardened through P12. It is not
a phase of its own. [SPEC.md §3.3](../SPEC.md) gives the flow:

```
Request  → resolve mode from authenticated principal (never client input)
         → route to /public or /personal
Response → if mode=public: assert response type ∈ public schemas
         → run banned-phrase linter over all free text
         → block + audit on any hit
```

**Why it matters here.** [SPEC.md Key Findings](../SPEC.md), item 2:
*"Compliance is the spine, built first (T15), not last. The public product must be
architecturally incapable of emitting advice."* This is the one line in the whole project with
real legal risk ([CLAUDE.md](../CLAUDE.md)), and it is an access-control problem — *"solve it
in code, not in policy."*

**The P0 deviation you should know about.** [SPEC.md §4.2](../SPEC.md) places the API at T16
(v1.0 / P9), but T15's files are listed as `/compliance` and `/api`, and
[SPEC.md §4.1](../SPEC.md) invariant 6 requires *"Mode is server-derived — never trust a
client-supplied mode."* A Streamlit-only app has no server from which to derive mode.
Therefore **FastAPI stands up in P0, not P9.** This is a deliberate, documented deviation from
SPEC.md's literal task ordering, recorded here and in
[01_ARCHITECTURE.md](01_ARCHITECTURE.md).

**See also:** [Mode gate](#mode-gate), [Banned-phrase linter](#banned-phrase-linter),
[Audit log](#audit-log), [FastAPI](#fastapi), [01_ARCHITECTURE.md](01_ARCHITECTURE.md).

---

### Connector

🟢 **SOLID** — a well-understood pattern; [DATA_FOUNDATION.md §4.3](../DATA_FOUNDATION.md) calls
it *"the single most important extensibility decision."*

**Plain words.** A small, self-contained piece of code responsible for one data source. It
knows how to find new documents at that source, download them, and turn them into rows the
rest of the system understands. Every source gets one; nothing else in the system knows where
data came from.

**Precisely.** [DATA_FOUNDATION.md §4.3](../DATA_FOUNDATION.md) specifies the interface,
inspired by OpenBB's `Fetcher` design:

```python
class Connector(Protocol):
    name: str
    def discover(self) -> list[SourceRef]: ...          # find new docs/series
    def fetch(self, ref: SourceRef) -> RawPayload: ...  # download
    def parse(self, raw: RawPayload) -> list[Record]: ...# -> canonical records
```

Named concrete connectors: `EdgarConnector`, `FredConnector`, `WorldBankConnector`,
`AfxKwayisiConnector`, `AfricanFinancialsConnector`, `NgxDoclibConnector`, `NbsCpiConnector`,
`CbnRatesConnector`, `DmoAuctionConnector`, `RssNewsConnector`. They register in a dict; the
scheduler iterates.

**Why it matters here.** Free Nigerian sources have no uptime contract and can vanish
([TEAM_BRIEF.md §3, bottleneck 3](../TEAM_BRIEF.md)). The connector pattern means swapping
`afx.kwayisi` for `african-markets` or paid EODHD touches **one file**
([DATA_FOUNDATION.md §8.4](../DATA_FOUNDATION.md)). Without it, a source change is a rewrite.

**Connector health is a separate concern.** [OPERATIONS.md §2.3](../OPERATIONS.md) makes the
point that the realistic failure is not a crash: *"`afx.kwayisi` changing its HTML, the scraper
returning HTTP 200, the parser matching nothing, and **zero rows landing with no error
raised.** You notice weeks later when a chart has a flat line."* Hence the `connector_runs`
table and the rule that **every connector asserts a plausible row count before committing** —
the NGX daily price list has ~150 rows; a run writing 3 is a failure regardless of HTTP status.

**Example.** `AfxKwayisiConnector.discover()` returns today's price-list URL;
`.fetch()` pulls the HTML and stores the raw bytes keyed by URL + hash; `.parse()` returns ~150
`PriceRecord` objects; the writer asserts `rows_written >= 0.5 * trailing_median` before
committing.

**See also:** [Connector health](#connector-health), [Staleness](#staleness),
[Content-hash caching](#content-hash-caching), [02_INFRASTRUCTURE.md](02_INFRASTRUCTURE.md).

---

### Connector health

**Plain words.** Monitoring that tells you a data source has quietly stopped working, before
you notice weeks later that a chart is a flat line.

**Precisely.** The `connector_runs` table ([OPERATIONS.md §2.3](../OPERATIONS.md)) recording
`connector, started_at, finished_at, status ('ok'|'degraded'|'failed'), rows_expected,
rows_written, bytes_fetched, error`. Alert conditions given verbatim: *"zero rows where rows
were expected, a >50% drop versus the trailing median, three consecutive failures, or a source
whose response hash has not changed in longer than its cadence (a frozen page)."*

**Why it matters here.** This is the difference between a data product you can trust and one
you merely hope is right. [TEAM_BRIEF.md §3](../TEAM_BRIEF.md) calls silent data corruption
*"the worst failure mode: nothing crashes, numbers are just wrong."*

**Example.** `afx.kwayisi.org` changes its table markup. The scraper still gets HTTP 200. The
parser matches zero rows. `rows_written = 0`, `rows_expected ≈ 150`, status = `failed`, and a
Telegram message arrives in the same channel as the daily brief
([OPERATIONS.md §2.3](../OPERATIONS.md) — *"one place to look"*).

**See also:** [Connector](#connector), [Staleness](#staleness), [Idempotency](#idempotency).

---

### Coverage metrics

**Plain words.** The scoreboard for how much data you actually have and how good it is — the
numbers you would show a potential buyer, and the ones that tell you honestly whether the moat
is widening.

**Precisely.** [OPERATIONS.md §3.2](../OPERATIONS.md) defines seven, snapshotted monthly into
a `coverage_metrics` table:

| Metric | Definition |
|---|---|
| **Companies covered** | Distinct companies with ≥1 validated annual statement |
| **Depth** | Median years of history per covered company |
| **Completeness** | % of expected filing-periods present per company |
| **Extraction accuracy** | % of line items passing validation with no human correction, measured against the golden set |
| **Correction rate** | % of extracted items a human changed — *the honest quality number* |
| **Freshness** | % of series within their `stale_after_days` window |
| **Provenance completeness** | % of stored figures with a resolvable source document and page — **must be 100%** |

**Why it matters here.** [PROJECT_CONTEXT.md §9.4](../PROJECT_CONTEXT.md) requires *"coverage
metrics quotable to a buyer: N companies, M years, X% extraction accuracy."*
[OPERATIONS.md §3.2](../OPERATIONS.md) adds the operational reason: *"Compute them continuously
rather than assembling them the week a buyer asks."* And **correction rate is the leading
indicator of whether the extractor is learning** — [TEAM_BRIEF.md §3, bottleneck 5](../TEAM_BRIEF.md):
*"if it isn't falling, the extractor isn't learning and something is wrong with the feedback
loop."*

**Example.** A P4-exit snapshot might read:
`companies=22 · depth=5.0 yrs · completeness=87% · extraction_accuracy=91% ·
correction_rate=9% · freshness=94% · provenance_completeness=100%`.

**Common misunderstanding.** Treating provenance completeness as a target to improve toward.
It is not a target — it must be **100%** at all times. A figure without a resolvable source
document is a bug, not a low score.

**See also:** [Extraction accuracy](#extraction-accuracy), [Golden set](#golden-set),
[Provenance](#provenance), [Acquirability](#acquirability-and-the-moat).

---

### Curator, Collector, Data-entry analyst, Reviewer (the roles)

**Plain words.** The four kinds of human work this project needs, separated by what skill each
one requires. Right now one person may hold several of them.

**Precisely.** [TEAM_BRIEF.md §2.1](../TEAM_BRIEF.md):

| Role | Needs | Load |
|---|---|---|
| **Curator** (owner) | Market knowledge, accounting literacy | Front-loaded, then light |
| **Collector** | Care, organisation. No finance background needed. | Heavy at start, then light |
| **Data-entry analyst** | Can read a financial statement | Heavy during v0.3 backfill |
| **Reviewer** | Solid accounting — can spot a wrong number | Light at first, permanent thereafter |
| **Owner only** | Judgment, authority, money | Ongoing |

**Why it matters here.** Two of these are on the critical path before any code exists:
choosing the company universe (Curator, ~1 day, *do first*) and building the golden set
(Reviewer + Curator, ~2–3 days, *"highest leverage task in the project"*). And one is
permanent: ongoing extraction review never disappears — *"It shrinks but never disappears"*
([TEAM_BRIEF.md §2.2-I](../TEAM_BRIEF.md)).

**Example of the load.** At ~90% accuracy on ~200 line items per annual report, expect
**~20 corrections per filing**. Twenty-five companies filing quarterly is roughly
**2,000 corrections a year** ([TEAM_BRIEF.md §2.2-I, §3](../TEAM_BRIEF.md)).

**Common misunderstanding.** Thinking data-entry work can be fully contracted out.
[TEAM_BRIEF.md §2.3](../TEAM_BRIEF.md) is specific: a contractor *"can key numbers, but they
cannot build the golden set — that needs someone who will be held accountable for it."*

**See also:** [Golden set](#golden-set), [HITL](#hitl--human-in-the-loop),
[Universe](#universe-company-universe), [05_USER_STORIES.md](05_USER_STORIES.md).

---

### Data licensing / redistribution rights

🔴 **FRAGILE** — [PROJECT_CONTEXT.md §9.3](../PROJECT_CONTEXT.md) calls it *"the one that kills
deals"*, and gap **G5** notes no task in T1–T21 enforces it per-source.

**Plain words.** The legal right to take data from somewhere else and pass it on to your own
users. Having the *ability* to download something is not the same as having the *right* to
republish it.

**Precisely.** [DATA_FOUNDATION.md §6.3](../DATA_FOUNDATION.md): *"NGX Market Data is governed
by a **Data Agreement** restricting redistribution; paid API tiers come with dissemination
terms. Vendors (EODHD etc.) license data for your use, not for you to re-serve raw."* The
implication given: personal-use scraping for your own analysis is fine; a **public** product
must either (a) license redistribution from NGX or a vendor, (b) present only *derived and
transformed* analytics — ratios, explanations — not raw redistributable feeds, or (c) show data
with the delays and attribution the source permits.

**Why it matters here.** [CLAUDE.md](../CLAUDE.md) makes it a hard rule: *"**Data licensing
before ingestion** — confirm redistribution rights before a source enters the dataset."*
[PROJECT_CONTEXT.md §9.3](../PROJECT_CONTEXT.md): *"An acquirer's lawyers will ask exactly one
hard question: do you have the right to redistribute this data? A dataset built by scraping
sources whose terms prohibit redistribution is a **lawsuit, not an asset**."*

**Why it is FRAGILE.** Three reasons. (1) It is a *hard rule* with **no task that enforces it**
— see gap G5. (2) The consequence is discovered late, at P12, when the whole dataset already
exists and re-sourcing is impossible. (3) Free sources like `afx.kwayisi.org` have *"no
explicit API license"* ([DATA_FOUNDATION.md Part 2A](../DATA_FOUNDATION.md)), which means the
answer is not "yes" or "no" but "unknown", the worst of the three.

**Three approaches.**

1. **A per-source licensing register enforced in code, from P0.** Add a `data_sources` table
   with `redistribution_status ('own_use_only'|'derived_only'|'licensed'|'unknown')`,
   `terms_url`, `reviewed_by`, `reviewed_on`, and make the public API refuse to serve any
   figure whose source row is not `licensed` or `derived_only`. *Trade-off:* a few days of P0
   work, and it forces you to answer the question per source before ingesting. *Upside:* the
   rule becomes mechanical, and the register is literally the document a buyer's lawyer asks
   for.
2. **Derived-only public tier.** Serve nothing raw publicly — only ratios, growth rates,
   normalised comparisons, and narrative, never a redistributable price series or a verbatim
   statement figure. *Trade-off:* weakens the public product's usefulness and complicates the
   provenance promise (you must still show the source, just not the raw feed). *Upside:*
   sidesteps most redistribution restrictions without paying anyone.
3. **Buy the licence before public launch.** NGX Interday Prices is **$1,000/yr** and the
   NGX News & Corporate Actions product **$2,500/yr**
   ([DATA_FOUNDATION.md Key Finding 1](../DATA_FOUNDATION.md)); EODHD `.XNSA` is
   ~$60–$100/mo. *Trade-off:* real recurring cost before any revenue, and a vendor licence
   still typically forbids re-serving raw. *Upside:* unambiguous, and it is what an
   institutional buyer expects to see.

**Recommendation: 1 + 2 now, 3 at P12.** Build the register in P0 because it is cheap and it is
the only one of the three that is *enforceable*; default the public tier to derived-only;
revisit buying a licence when P12 (public beta) is actually near and the lawyer engagement
from [TEAM_BRIEF.md §2.2-J](../TEAM_BRIEF.md) has given an answer. **Book the lawyer early** —
both [TEAM_BRIEF.md §2.2-J](../TEAM_BRIEF.md) and [OPERATIONS.md §3.4](../OPERATIONS.md) say
the answer shapes the v2.0 architecture and *"finding out late is the expensive version."*

**Common misunderstanding.** Confusing this with the SEC licence. They are unrelated.
[CLAUDE.md](../CLAUDE.md) flags this explicitly: data licensing is *"(Distinct from the SEC
licence above.)"* One is about republishing other people's data; the other is about giving
investment advice.

**See also:** [ISA 2025](#isa-2025), [`licence_status`](#licence_status),
[Scraping legality](#scraping-legality), [NGX Market Data API](#ngx-market-data-api),
[06_RISK_REGISTER.md](06_RISK_REGISTER.md).

---

### Decision gate (buy-vs-build threshold)

**Plain words.** A rule you write down *before* you start something, saying exactly when you
will give up on it and pay for a shortcut instead.

**Precisely.** [PROJECT_CONTEXT.md §8](../PROJECT_CONTEXT.md) calls it **sunk-cost honesty**:
*"Set the rule now, while calm: if extraction accuracy stalls after N weeks, buy EODHD and move
on. Decide the threshold before being three weeks deep and reluctant to abandon work."*

**The concrete thresholds already set in the documents.**

| Gate | Threshold | Action if missed |
|---|---|---|
| P4 extraction ([DATA_FOUNDATION.md Rec. 4](../DATA_FOUNDATION.md)) | <~85% accuracy on 10 filings after human review after 2 weeks, **or** Claude spend trending above ~$100/mo | Buy EODHD `.XNSA` (~$60/mo) for the price/fundamental layer; reserve LLM extraction for statements EODHD lacks |
| NGX price/PDF sources ([SPEC.md Part 6](../SPEC.md)) | Free sources prove too unreliable | Buy EODHD `.XNSA` or an NGX paid tier *before building more on top* |
| P8 signals ([SPEC.md Part 6](../SPEC.md)) | No strategy clears the backtest gate after honest purged-CV + DSR testing | Abandon the signal layer for that market; keep the data/analytics/brief product |
| Public advice demand ([SPEC.md Part 6](../SPEC.md)) | Users ask for advice/signals | Stop; get SEC-licensed before enabling any personal-mode feature publicly |
| LLM memos ([SPEC.md Part 6](../SPEC.md)) | Spend or hallucination risk outweighs value | Downgrade to template-driven summaries over structured data only |

**Why it matters here.** The P4 gate is described as *"the single most important cost/effort
decision in the project"* ([DATA_FOUNDATION.md Rec. 4](../DATA_FOUNDATION.md)).

**See also:** [Extraction accuracy](#extraction-accuracy), [EODHD](#eodhd),
[Stage gate](#stage-gate), [Backtest gate](#backtest-gate-the).

---

### Doc A / Doc B

**Plain words.** Shorthand for the two source documents that were merged to create `SPEC.md`.
Doc A is a file you can open; Doc B is not.

**Precisely.**

- **Doc A = [`DATA_FOUNDATION.md`](../DATA_FOUNDATION.md).** The data foundation: verified
  source inventory (NGX, EDGAR, FRED, NBS, CBN, DMO), the PDF→LLM extraction pipeline, the base
  schema, and the ISA 2025 / NDPA / redistribution legal research. Its own editorial header
  says: *"This is 'Document A' — the data foundation… This document is the authority on data
  sources, the PDF pipeline, the base schema, and the regulatory research."*
- **Doc B = the intelligence/signal/agent layers document.** It was merged into
  [`SPEC.md`](../SPEC.md) and **does not exist as a separate file in the repo.** References
  like "Doc B **Level 1**" or "Document B's four Levels" point at sections of SPEC.md.

**Doc B's four Levels, since they are referenced by number:**

| Level | Content | Lands in |
|---|---|---|
| **Level 1** | Intel — sentiment, daily brief, alerts | P5 (v0.5) |
| **Level 2** | ML signals, calibrated probability | P8 (v0.9) |
| **Level 3** | Multi-agent research memos (Bull/Bear/Risk/Arbitrator) | P9 (v1.0) |
| **Level 4** | Execution — US API, NGX manual ticket | P13 (v2.5) |

**Why it matters here.** [SPEC.md TL;DR](../SPEC.md) makes the key structural point:
*"Document B's four 'Levels' are not a parallel product — they are layers that sit on top of
Document A's single data foundation, and the build order must interleave them with
BACKTESTING inserted before any signal is ever trusted with capital."* There is exactly one
data layer; Doc B's layers are consumers of it.

**Two scoping reconciliations you must carry when reading Doc A.** Doc A §1.4, §4.6, §6.5 and
§7.1 state *"no buy/sell language anywhere"* and *"NEVER generate recommendations"* as absolute
rules. Those were written before the personal/public split existed. **They are now scoped to the
public data tier only** ([DATA_FOUNDATION.md editorial header](../DATA_FOUNDATION.md),
[CLAUDE.md](../CLAUDE.md)). Also, Doc A §7.2's monorepo layout is superseded by
[SPEC.md §3.1](../SPEC.md)'s fuller layout.

**See also:**
[The four numbering systems](#the-four-numbering-systems--read-this-before-anything-else),
[Personal mode](#personal-mode), [Public mode](#public-mode).

---

### Entitlements

**Plain words.** A per-user list of what that specific user is allowed to do. Not a role like
"admin", but a set of specific permissions.

**Precisely.** [PROJECT_CONTEXT.md §4](../PROJECT_CONTEXT.md): *"The advice tier is gated by
`entitlements` + a `licence_status` flag — so opening it is a config change plus a disclosure
layer, never a re-architecture."* [CLAUDE.md](../CLAUDE.md): *"Gate on **entitlements +
`licence_status`** so that day is a config + disclosure change, never a rewrite."*

**Why it matters here.** It is what makes the licence a switch instead of a rewrite. If the
advice tier were gated on `if user == "frank"` you would have to touch every call site to open
it. Gated on `if "signals:read" in principal.entitlements and licence_status.allows(...)` you
change one row per user.

**Example.**

```json
{
  "principal": "frank",
  "entitlements": ["data:read", "scenarios:write", "signals:read",
                   "memos:personal", "execution:confirm"],
  "portfolio_ids": [1, 2]
}
{
  "principal": "family_member_2",
  "entitlements": ["data:read", "scenarios:write", "signals:read"],
  "portfolio_ids": [3]
}
```

**Common misunderstanding.** Thinking entitlements alone open the advice tier. They do not —
`licence_status` gates it as well, and that is deliberate: even if someone is granted
`signals:read` by mistake, the licence flag stops advice reaching a non-family principal
pre-licence. Two independent locks on the one line with real legal risk.

**Gap G3 applies here.** There is no task in T1–T21 that owns auth and identity — "auth" is one
word inside T16 (P9), yet multi-user is mandated from day one and mode is derived from the
principal in P0. **The principal and entitlement model must exist in P0.**

**See also:** [Principal](#principal), [`licence_status`](#licence_status),
[Mode gate](#mode-gate), [Access model](#access-model).

---

### Extraction accuracy

🔴 **FRAGILE** — every source document independently identifies this as the project's biggest
risk and cost sink.

**Plain words.** The percentage of numbers the automated PDF reader gets right without a human
fixing them.

**Precisely.** [OPERATIONS.md §3.2](../OPERATIONS.md) defines it as *"% of line items passing
validation with no human correction, measured against the golden set."* Its twin,
**correction rate**, is *"% of extracted items a human changed — the honest quality number."*

**Why it matters here.** It is the P4 stage gate: **≥85% extraction accuracy on 10 filings
after review, with Claude spend under ~$100/mo** ([TEAM_BRIEF.md Part 4](../TEAM_BRIEF.md)).
Miss it and the documented action is to buy EODHD. It is also the number you quote to a buyer
([PROJECT_CONTEXT.md §9.4](../PROJECT_CONTEXT.md)).

**Why it is FRAGILE, stated by the sources.**
[DATA_FOUNDATION.md §8.2](../DATA_FOUNDATION.md) risk 1: *"PDF extraction harder/slower than
expected → start manual (v0.3), automate incrementally, keep human review, **budget 2–3×**."*
[DATA_FOUNDATION.md §8.3](../DATA_FOUNDATION.md): *"Where estimates are most wrong: PDF
extraction (**bank statements especially** — different chart of accounts)."*
[TEAM_BRIEF.md §3](../TEAM_BRIEF.md) calls it *"the one that eats months"* and notes
rules-based extraction alone gets ~60%. [DATA_FOUNDATION.md §5](../DATA_FOUNDATION.md) budgets
v0.4 at *"3–6+ weeks"* with the same 2–3× multiplier.

**Three approaches.**

1. **The hybrid pipeline as specified** ([DATA_FOUNDATION.md §3.1](../DATA_FOUNDATION.md)):
   cheap deterministic tools first (PyMuPDF4LLM / pdfplumber for text and Markdown tables,
   tesseract + OpenCV OCR for scans), then Claude with a strict JSON schema as the
   reconciliation brain, then deterministic validation, then a human-review UI for anything
   below confidence 0.85. *Trade-off:* most build effort, and the LLM cost is real but bounded
   by content-hash caching. *Upside:* lifts accuracy from ~60% (rules only) to ~90%+, and it is
   the only approach that produces a dataset you *own* — the moat.
2. **Buy EODHD `.XNSA`** (~$59.99/mo Fundamentals, ~$99.99/mo All-In-One;
   [DATA_FOUNDATION.md Key Finding 6](../DATA_FOUNDATION.md)) and skip extraction for the names
   it covers. *Trade-off:* you rent the moat instead of owning it, the licence almost certainly
   forbids re-serving raw ([see Data licensing](#data-licensing--redistribution-rights)), and
   coverage depth for older Nigerian filings is unverified **[NEEDS VERIFICATION — confirm
   EODHD's actual NGX history depth and per-company completeness with a trial before
   committing]**. *Upside:* immediate structured fundamentals, zero extraction risk, and it
   frees months.
3. **Permanently manual, curated small.** Keep [DATA_FOUNDATION.md v0.3](../DATA_FOUNDATION.md)'s
   CSV-template approach forever for a deliberately tiny universe — 10 companies, annual only —
   and never build the automated extractor. *Trade-off:* ~2–4 hours per company-year
   ([TEAM_BRIEF.md §2.2-D](../TEAM_BRIEF.md)) means ~200–400 hours for 10 companies × 5 years,
   and quarterly maintenance forever; it does not scale and it is not a business. *Upside:*
   100% accuracy, zero LLM cost, and it ships in weeks.

**Recommendation: 1, with 2 pre-negotiated as the documented fallback and 3 as the P3 warm-up.**
This is exactly the sequence the sources prescribe — do the manual pass in P3 anyway because
*"it teaches the team what the data actually looks like"*
([TEAM_BRIEF.md §2.2-D](../TEAM_BRIEF.md)), then build the hybrid, then hold the 85%/two-week
gate honestly. The critical discipline is deciding the threshold **before** you are three weeks
deep ([PROJECT_CONTEXT.md §8](../PROJECT_CONTEXT.md)).

**Early-warning signals to watch.** Correction rate not falling filing over filing; review
queue depth growing; a bank taking materially longer than an industrial; Claude spend crossing
$60/mo before the tenth filing.

**See also:** [Golden set](#golden-set), [HITL](#hitl--human-in-the-loop),
[Decision gate](#decision-gate-buy-vs-build-threshold), [EODHD](#eodhd),
[Validation rules](#validation-rules-deterministic),
[06_RISK_REGISTER.md](06_RISK_REGISTER.md).

---

### Golden set

**Plain words.** A small number of financial filings where a human has checked every single
number by hand, so you have a known-correct answer to test the automated extractor against.

**Precisely.** [TEAM_BRIEF.md §2.2-C](../TEAM_BRIEF.md): hand-verify **every number** in 3
filings — ideally **MTN Nigeria FY2024** (messy in an instructive way: revenue up, huge
FX-driven loss), **a bank (GTCO)**, and **a clean industrial** — and produce the expected JSON
output by hand. Effort: Reviewer + Curator, ~2–3 days. It is called *"the highest leverage task
in the project."*

**Why it matters here, in the source's own words.** *"Without ground truth you cannot measure
extraction accuracy, which means you cannot tell whether the extractor is working, cannot hit
the ≥85% decision gate, and cannot honestly quote accuracy to a buyer. Every automated test in
the project measures against this set."* And: *"Alternative? **None whatsoever.**"*

**Gap G6 applies here.** No task in T1–T21 covers building the golden set, yet **T4's
acceptance criterion depends on it** — *"golden-file extraction ≥ threshold"*
([SPEC.md §4.2](../SPEC.md)) — and [SPEC.md §4.4](../SPEC.md) makes golden-file tests a
mandatory testing requirement. It must be scheduled explicitly in P3, before P4 starts.

**Example of what it produces.** A file at `tests/golden/MTNN_FY2024.json` containing the
hand-verified expected output, including `revenue = 3_360_000_000_000` and
`profit_after_tax = -400_440_000_000` (figures from
[DATA_FOUNDATION.md §3.2, §3.3](../DATA_FOUNDATION.md)). The extractor's output is diffed
against this file in CI.

**Common misunderstanding.** Thinking a contractor can build it.
[TEAM_BRIEF.md §2.3](../TEAM_BRIEF.md): *"they can key numbers, but they cannot build the
golden set — that needs someone who will be held accountable for it."*

**Common misunderstanding, second.** Thinking three filings is too few. Three is enough
*because they are chosen adversarially* — a messy telco, a bank with a different chart of
accounts, and a clean control. Breadth here buys nothing; the diversity of failure modes is
what matters.

**See also:** [Golden file test](#golden-file-test), [Extraction accuracy](#extraction-accuracy),
[Canonical chart of accounts](#canonical-chart-of-accounts),
[07_TEST_STRATEGY.md](07_TEST_STRATEGY.md).

---

### HITL — human in the loop

**Plain words.** A step where a person reviews and can correct what the machine produced,
before it becomes official data.

**Precisely.** [DATA_FOUNDATION.md §3.2](../DATA_FOUNDATION.md) specifies the mechanism: a
Streamlit page showing the PDF page image beside the extracted JSON, with editable fields and
approve/correct actions; anything with confidence below ~0.85 or any failed validation check is
routed there. Crucially: *"corrections stored as few-shot examples to improve future
extraction."*

**Why it matters here.** Three reasons. (1) It is what makes the data trustworthy — the
alternative is shipping unvalidated LLM output as fact. (2)
[PROJECT_CONTEXT.md §7](../PROJECT_CONTEXT.md) requires *"a dead-simple manual override…
a way to correct a number by hand and have the correction **stick**, with a note recording who
changed it and why."* (3) The corrections are the single most irreplaceable asset in the
system — [OPERATIONS.md §2.1](../OPERATIONS.md) ranks **HITL corrections** first in its
what-cannot-be-rebuilt table: *"Human judgment calls made once. Re-deriving means re-reviewing
every filing by hand."*

**HITL also appears in the agent layer.** [SPEC.md §2E](../SPEC.md) recommends LangGraph for
production partly for its *"native human-in-the-loop"* checkpointing, and
[SPEC.md §2I](../SPEC.md) requires *"a **required human confirmation step** in personal mode
before any order."* Same idea, different layer: a machine proposes, a human approves.

**Example.** Extraction returns `finance_costs = 925_360_000_000` with confidence 0.71 because
the table was borderless. The reviewer opens the review UI, sees page 84 of the MTN FY2024 AR
next to the JSON, confirms the figure, and clicks approve. The row's `needs_review` flips to
false, an attributed correction record is written, and the example is added to the few-shot
bank.

**Common misunderstanding.** Treating HITL as a temporary scaffold to be removed once accuracy
is high. [TEAM_BRIEF.md §2.2-I](../TEAM_BRIEF.md): *"Necessary? **Permanently.**… It shrinks
but never disappears."* Chasing full automation is how you ship wrong numbers.

**See also:** [needs_review](#needs_review), [No silent overwrite](#no-silent-overwrite),
[Extraction accuracy](#extraction-accuracy),
[Human-in-the-loop checkpoint](#human-in-the-loop-checkpoint),
[Curator, Collector, Data-entry analyst, Reviewer](#curator-collector-data-entry-analyst-reviewer-the-roles).

---

### Instrument, not judgment

**Plain words.** The design philosophy: the tool gives you the numbers and the machinery to
think with; you decide what to do. It does not decide for you.

**Precisely.** [TEAM_BRIEF.md Part 1](../TEAM_BRIEF.md): *"**We provide the instrument. The user
provides the judgment.**"* [DATA_FOUNDATION.md §1.4](../DATA_FOUNDATION.md) turns it into six
concrete UI rules for the public tier: no buy/sell language; every projection input
user-editable and visible; the system never generates a price target; scenario sliders and
sensitivity tables replace verdicts; always show provenance and as-of dates; a persistent
disclaimer.

**Why it matters here — and where the scoping is subtle.** In **public mode** this is a legal
boundary as well as a philosophy: it is what keeps the product outside SEC registration under
ISA 2025. In **personal mode** the philosophy still holds but the constraint does not.
[PROJECT_CONTEXT.md §4](../PROJECT_CONTEXT.md): *"The philosophy still holds in both modes: the
instrument shows its work. Even when it says BUY, it shows why — the assumptions, the data, the
as-of dates — so the judgment stays the user's. That is the difference between a tool that makes
someone a better investor and an oracle that makes them a dependent one."*

**Example, public mode.** The DCF screen shows a discount-rate slider defaulting to
*"risk-free ≈ latest FGN 10-yr yield 22.60%"* with the source cited
([DATA_FOUNDATION.md §1.4](../DATA_FOUNDATION.md)), and outputs *"given YOUR assumptions, DCF
outputs ₦X"* — never *"fair value is ₦X."*

**Example, personal mode.** The same screen may add: *"Signal: BUY. Calibrated probability 0.61.
Backtest run #47, DSR 0.97, K=12. Sizing 1.8% of equity at a 2.1×ATR stop. Assumptions: …"* The
verdict is present; the work is still shown.

**Common misunderstanding.** Reading "instrument, not judgment" as *"the system must never say
BUY."* That was true of Doc A before the access split and is now scoped to the public tier only
([DATA_FOUNDATION.md editorial header](../DATA_FOUNDATION.md), [CLAUDE.md](../CLAUDE.md)).

**See also:** [Show the work](#show-the-work), [Public mode](#public-mode),
[Personal mode](#personal-mode), [ISA 2025](#isa-2025).

---

### `known_as_of`

**Plain words.** The first date on which you *could have known* a piece of information. Not
when it happened, and not when you downloaded it — when it became public.

**Precisely.** A column that appears on `ml_features`, `price_adjustments`, and `fx_rates`
([SPEC.md §3.2](../SPEC.md), [OPERATIONS.md §1.1, §1.3](../OPERATIONS.md)). Its purpose is
stated in [SPEC.md §2C](../SPEC.md): *"every feature carries `known_as_of`; joins filter
`known_as_of <= decision_date`."*

**Why it matters here.** It is the mechanism that enforces the point-in-time invariant, which
is invariant 5 of the seven ([SPEC.md §4.1](../SPEC.md)): *"Point-in-time only —
features/labels respect `known_as_of`; restated financials use the version known at the
decision date."* Without it, backtests use information from the future and report a fictional
edge. This is the difference between a backtest that means something and one that is a lie.

**Example.** MTN Nigeria's FY2024 annual report has `period_end = 2024-12-31` but was published
some time in 2025. A model making a decision on 2025-02-01 must **not** see it. The join is
`WHERE known_as_of <= '2025-02-01'`, so the FY2023 figures are used instead — which is exactly
what a real trader on that date would have had.

**Common misunderstanding, and it is the expensive one.** Confusing `known_as_of` with
`as_of_date` / `period_end`. They are different columns with different meanings:

| Column | Answers |
|---|---|
| `period_end` / as-of date | *When was this true?* |
| `release_date` | *When did the publisher put it out?* |
| `known_as_of` | *From when could a decision-maker have used it?* |
| `retrieved_at` | *When did our scraper fetch it?* |

**Common misunderstanding, second.** Thinking it only matters for the trading half. It also
governs corporate-action adjustments — [OPERATIONS.md §1.1](../OPERATIONS.md) requires adjusted
price series be computed *"applying only adjustments with `known_as_of <= decision_date`"* —
and the vintage handling for macro series.

**See also:** [Point-in-time](#point-in-time), [As-of date](#as-of-date),
[Lookahead bias](#lookahead-bias), [Restatement bias](#restatement-bias),
[Vintage](#vintage--alfred-vintages), [01_ARCHITECTURE.md](01_ARCHITECTURE.md).

---

### `licence_status`

**Plain words.** A single system-wide flag recording whether the SEC registration has been
obtained yet. It is one half of the lock on the advice features.

**Precisely.** [PROJECT_CONTEXT.md §4](../PROJECT_CONTEXT.md) and [CLAUDE.md](../CLAUDE.md):
the advice tier is gated by `entitlements` **plus** `licence_status`, so that *"opening it is a
config change plus a disclosure layer, never a re-architecture."*

**Why it matters here.** It separates *"this user is entitled"* from *"we are legally permitted
to serve non-family users."* Pre-licence, the flag means advice-tier output can only reach
family principals no matter what entitlements say. Post-licence, the same flag flips and the
identical code serves the public with disclosures attached.

**Example, in pseudocode.**

```python
def may_receive_advice(principal) -> bool:
    if "signals:read" not in principal.entitlements:
        return False
    if licence_status.is_licensed():        # SEC registration obtained
        return True
    return principal.is_family()            # pre-licence: family only
```

**The SEC licence itself.** [PROJECT_CONTEXT.md §4](../PROJECT_CONTEXT.md): *"the intent is SEC
registration under Nigeria's **ISA 2025**, both the adviser and fund-manager categories."*
That is a real plan, not a hypothetical — but note the capital requirements in
[DATA_FOUNDATION.md §6.1](../DATA_FOUNDATION.md): full-scope fund managers **₦5 billion** under
SEC Circular 26-1, with a compliance deadline of **30 June 2027**.

**Common misunderstanding.** Thinking `licence_status` is about data redistribution. It is not
— that is a separate, unrelated licence. See
[Data licensing / redistribution rights](#data-licensing--redistribution-rights).

**See also:** [Entitlements](#entitlements), [ISA 2025](#isa-2025), [CMO](#cmo--capital-market-operator),
[Access model](#access-model).

---

### Mode gate

**Plain words.** The single switch that decides whether a given request gets the full
advice-capable version of the system or the data-only version. The server decides; the browser
never gets a vote.

**Precisely.** [SPEC.md §1.2](../SPEC.md) specifies **five mechanisms, all required**:

1. **Feature flag / mode context** — a request-scoped `mode: Literal["personal","public"]`
   *derived from the authenticated principal, never from a client-supplied parameter.* Default
   is `public` (fail-safe). Personal mode requires the owner principal plus a second factor.
2. **Separate output schemas** — Pydantic models `PublicAnalysis` (**no** fields named `signal`,
   `recommendation`, `entry`, `stop_loss`, `target`, `position_size`) versus `PersonalSignal`
   (has them). *"The public serializer only accepts `PublicAnalysis`, so serializing a
   `PersonalSignal` into a public response is impossible."*
3. **Separate API namespaces** — `/public/*` and `/personal/*` are different routers.
4. **Compliance middleware (output filter)** — blocks any body typed `PersonalSignal` in public
   mode and runs banned-phrase linting on all free text.
5. **Separate test suites** — `tests/compliance/` proves no public endpoint returns
   advice-shaped fields, the linter fires on a battery of known-bad outputs, and mode cannot be
   escalated by any client input. **CI fails the build otherwise.**

**Why it matters here.** [SPEC.md TL;DR](../SPEC.md): *"The one architectural decision that
governs everything is the PERSONAL/PUBLIC mode gate."* It is invariant 6 of seven
([SPEC.md §4.1](../SPEC.md)) and a [CLAUDE.md](../CLAUDE.md) hard rule. It is also the only
place in the project with real legal exposure: *"Never expose personal-mode output to a
non-family user pre-licence… This is the only line with real legal risk."*

**One codebase, never two.** [CLAUDE.md](../CLAUDE.md): *"Gate with `MODE=personal|public`,
**never two codebases**."* A fork would double every future change and guarantee drift.

**Example of the attack it defends against.** A user sends
`GET /public/analysis/MTNN?mode=personal`. The server ignores the query parameter entirely —
mode comes from the authenticated principal — resolves `public`, routes to the public router,
returns a `PublicAnalysis`, and the compliance test suite has a test asserting exactly this.

**Common misunderstanding.** Thinking the five mechanisms are alternatives to choose from. They
are layers, all required, because each catches a different class of failure: (1) is
authentication, (2) is type-level impossibility, (3) is routing, (4) is text-level, (5) is
regression protection.

**See also:** [Personal mode](#personal-mode), [Public mode](#public-mode),
[Compliance middleware](#compliance-middleware), [Principal](#principal),
[Banned-phrase linter](#banned-phrase-linter), [01_ARCHITECTURE.md](01_ARCHITECTURE.md).

---

### `needs_review`

**Plain words.** A true/false flag on an extracted number meaning "a human has not confirmed
this yet — do not fully trust it."

**Precisely.** A boolean column on `statement_line_items`
([DATA_FOUNDATION.md §4.2](../DATA_FOUNDATION.md)) and `corporate_actions`
([OPERATIONS.md §1.1](../OPERATIONS.md)). It is set when confidence falls below ~0.85 **or**
any deterministic validation check fails ([DATA_FOUNDATION.md §3.2](../DATA_FOUNDATION.md)).

**Why it matters here.** It is the queue that drives the reviewer's daily work, and it is what
lets the UI show a figure with an honest caveat rather than either hiding it or presenting it
as verified. [OPERATIONS.md §1.1](../OPERATIONS.md) extends the same treatment to corporate
actions: *"Corporate actions get the same provenance treatment as line items: source document,
confidence, `needs_review`."*

**Example.** The cash-flow tie-out fails on a filing by ₦2.1bn. Every line item in that
statement is written with `needs_review = TRUE` and appears in the review UI with the failing
check named, so the reviewer knows what to look for rather than re-checking 200 numbers.

**Common misunderstanding.** Thinking `needs_review = TRUE` means the number is wrong. It means
*unverified*. Most reviewed items turn out correct; the flag is about confidence, not error.

**See also:** [HITL](#hitl--human-in-the-loop), [Confidence](#confidence-two-different-meanings),
[Validation rules](#validation-rules-deterministic).

---

### Never infer missing financial data

**Plain words.** If a number is not in the filing, store nothing — never guess, never
interpolate, never carry forward last year's value.

**Precisely.** Invariant 4 of seven ([SPEC.md §4.1](../SPEC.md)): *"Never infer missing
financial data — absent line items are marked missing, never estimated."*
[CLAUDE.md](../CLAUDE.md) repeats it. The extraction prompt enforces it at the source
([DATA_FOUNDATION.md §3.2](../DATA_FOUNDATION.md)): *"Extract ONLY numbers present in the
source; never infer/estimate/fill gaps… If absent, use null."*

**Why it matters here.** An inferred number is indistinguishable from a real one once stored,
and it poisons everything downstream — ratios, DCF outputs, ML features, backtest results — with
no way to trace which figures were fabricated. It also destroys the acquirability argument: a
buyer's diligence will sample your data against the filings, and one invented number costs the
credibility of the whole set.

**Example of the tempting mistake.** A Nigerian filing does not break out "cost of sales"
separately. The gross-margin ratio therefore cannot be computed. The wrong fix is deriving
`cost_of_sales = revenue - gross_profit` and storing it as a line item. The right behaviour is
`cost_of_sales = NULL`, gross margin displays as "not disclosed", and if the ratio engine
computes a derived figure it is labelled **derived**, stored separately, and never written back
into `statement_line_items`.

**The same rule appears in the agent layer.** [SPEC.md §2E](../SPEC.md), grounding:
*"Invariant: **never infer missing financial data**."* A Bull agent may not fill a gap with a
plausible estimate to strengthen its case.

**See also:** [`canonical_key`](#canonical_key), [Provenance](#provenance),
[Hallucination](#hallucination), [Derived value](#derived-value).

---

### No silent overwrite

**Plain words.** You never change a stored number in place. If a figure changes, you write a
new version and keep the old one, with a record of who changed it and why.

**Precisely.** [CLAUDE.md](../CLAUDE.md) hard rule: *"**No silent overwrites** — corrections are
versioned, attributed, and noted."* [PROJECT_CONTEXT.md §10](../PROJECT_CONTEXT.md) rule 5 is
the same. The schema implements it:
`financial_statements(… version, superseded_by, restatement, …)` with
`UNIQUE(company_id, statement_type, period_end, period_type, version)`
([DATA_FOUNDATION.md §4.2](../DATA_FOUNDATION.md)), and
[DATA_FOUNDATION.md §3.6](../DATA_FOUNDATION.md): *"Restatements create a NEW versioned row;
old rows retained + marked superseded."* [OPERATIONS.md §1.1](../OPERATIONS.md) applies the same
principle to prices: *"`price_history` stores raw as-traded prices only. **Never back-adjust it
in place** — that destroys the ability to reconstruct what a trader actually saw."*

**Why it matters here.** Two reasons, one obvious and one not. The obvious one: you need an
audit trail. The subtle one: **point-in-time integrity is impossible without it.** If you
overwrite FY2023 revenue when the FY2024 report restates it, you can no longer answer "what did
we believe on 2024-06-01?", and every backtest that spans the restatement is silently wrong.
[PROJECT_CONTEXT.md §9.3](../PROJECT_CONTEXT.md) calls point-in-time integrity *"the single most
enterprise-grade feature. Do not compromise it for speed."*

**Example.** A company restates FY2023 profit after tax from ₦48.2bn to ₦44.9bn in its FY2024
report. You do **not** UPDATE the row. You insert `version = 2` with `restatement = TRUE` and
set `superseded_by` on `version = 1`. Both remain queryable, and a decision dated before the
restatement sees version 1.

**Common misunderstanding.** Thinking this only applies to restatements. It applies equally to
human corrections in the HITL queue and to corrected scraper output. Any change to a stored
figure is a new version with an attribution.

**See also:** [Restatement](#restatement), [Restatement bias](#restatement-bias),
[Point-in-time](#point-in-time), [Provenance](#provenance),
[Version (statement version)](#version-statement-version).

---

### P0–P13 (the phases)

**Plain words.** The fourteen stages of the build, in the order you do them. P0 is groundwork
with no user-visible output; P13 is the last thing you build.

**Precisely.** See
[The four numbering systems](#the-four-numbering-systems--read-this-before-anything-else) for
the full table mapping phases to versions, SPEC tasks, and Doc B levels. In brief:

| | | |
|---|---|---|
| **P0** Foundation & Rails | **P1** Macro Backdrop | **P2** US Company Data |
| **P3** Nigerian Manual Analyzer | **P4** Nigerian Automated Ingestion | **P5** News, Sentiment & Daily Brief |
| **P6** Scenarios & Indicators | **P7** Backtesting — THE GATE | **P8** ML Signals |
| **P9** Memos & Hosted Web App | **P10** Portfolio & Alerts | **P11** Paper Trading |
| **P12** Public Beta | **P13** Personal Execution | |

**Why the phase numbers exist at all.** SPEC.md numbers *versions* (v0.1–v2.5) and *tasks*
(T1–T21), but neither is a work sequence you can stand in — a version is an outcome, a task is
a unit of code. The phases are the sequencing layer this planning set adds. They are
canonical across all nine documents and are never renumbered.

**The one thing to notice about the ordering.** P7 (backtesting) comes **before** P8 (ML
signals). That is a deliberate reorder from Doc B, stated in
[SPEC.md §1.3](../SPEC.md): *"The critical reorder vs Document B: the backtest harness (v0.8)
ships **before** ML signals (v0.9). No signal is trusted until it clears the backtest gate."*
Build the lie-detector before you build the thing that might lie to you.

**See also:**
[The four numbering systems](#the-four-numbering-systems--read-this-before-anything-else),
[03_ROADMAP_PART1_PHASES_0-6.md](03_ROADMAP_PART1_PHASES_0-6.md),
[04_ROADMAP_PART2_PHASES_7-13.md](04_ROADMAP_PART2_PHASES_7-13.md).

---

### Personal mode

**Plain words.** The version of the system the owner and family see. It is allowed to tell you
what to buy, at what price, with how much money.

**Precisely.** [SPEC.md §1.2](../SPEC.md): *"PERSONAL MODE (Frank + family capital): may output
explicit BUY/SELL signals, entry/stop/target prices, position sizing, and (last) execution
tickets. This is legally 'investment advice' and 'portfolio management' — permissible only
because he is managing his own and his family's money, not third-party funds for a fee."*

**Why it matters here.** Understanding *why* it is permitted is what keeps you from
accidentally breaking it. It is permitted because there is no client and no fee. The moment
personal-mode output reaches someone outside that circle, the legal analysis changes entirely —
which is why [CLAUDE.md](../CLAUDE.md) calls it *"the only line with real legal risk"* and
demands access control *"in code, not in policy."*

**What it may do that public mode may not.** Emit `signal`, `recommendation`, `entry`,
`stop_loss`, `target`, `position_size`; produce an arbitrator verdict in a memo; generate an
execution ticket. All of those are fields on `PersonalSignal`, a type the public serializer
will not accept.

**What it must still do.** Show the work. [PROJECT_CONTEXT.md §10](../PROJECT_CONTEXT.md) rule
3: *"Even a BUY comes with its assumptions, its inputs, and their as-of dates. The instrument
argues; it does not pronounce."*

**Common misunderstanding.** Thinking personal mode is a debug or admin mode. It is a
*product tier*, built to public standard, that currently has two users. See
[Build scope vs access control](#build-scope-vs-access-control).

**See also:** [Public mode](#public-mode), [Mode gate](#mode-gate),
[Entitlements](#entitlements), [ISA 2025](#isa-2025), [Show the work](#show-the-work).

---

### Point-in-time

**Plain words.** Only using information that was actually available on the day you are
pretending to make a decision. No peeking at what came later.

**Precisely.** Invariant 5 of seven ([SPEC.md §4.1](../SPEC.md)): *"Point-in-time only —
features/labels respect `known_as_of`; restated financials use the version known at the
decision date."* It is implemented by three things working together: `known_as_of` columns,
statement versioning, and adjustment factors computed on read rather than baked into stored
prices.

**Why it matters here.** [PROJECT_CONTEXT.md §9.3](../PROJECT_CONTEXT.md) calls it *"the single
most enterprise-grade feature"* and *"exactly what institutional buyers pay premiums for — it is
the only way to backtest honestly. **Do not compromise it for speed.**"* Practically: every
backtest number is fiction without it, and every claim you would make to a buyer is
unverifiable.

**The three things that break it, and their fixes** (all from
[SPEC.md §2C](../SPEC.md)):

| Break | What happens | Fix |
|---|---|---|
| **Lookahead** | Using a filing before it was published | `known_as_of <= decision_date` on every join |
| **Restatement** | Using the corrected figure as though it were known at the time | Version every statement; select the version current at the decision date |
| **Adjusted-price sin** | Using back-adjusted prices that encode future corporate actions | Store raw prices + separate adjustment factors; reconstruct on read up to the decision date only |

**Example.** On 2025-03-15 you compute a P/E for GTCO. Point-in-time means: use the latest
statement whose `known_as_of <= 2025-03-15`, at whichever `version` was current on that date,
and the raw close price from `price_history` adjusted only by corporate actions whose
`known_as_of <= 2025-03-15`.

**Common misunderstanding.** Thinking point-in-time is only a backtesting concern. It is a
*data model* concern. If the schema cannot express it, no amount of care in the backtester can
recover it — and retrofitting it is a re-extraction, not a migration.

**See also:** [`known_as_of`](#known_as_of), [Lookahead bias](#lookahead-bias),
[Restatement bias](#restatement-bias), [Adjusted-price sin](#adjusted-price-sin),
[Vintage](#vintage--alfred-vintages), [01_ARCHITECTURE.md](01_ARCHITECTURE.md).

---

### Principal

**Plain words.** The identified user making a request — the "who" that everything is keyed to.
Not a session, not a browser, not a role: a specific authenticated identity.

**Precisely.** The term used throughout the source documents for the authenticated identity
that mode, entitlements, portfolios, limits, and audit rows all hang off.
[CLAUDE.md](../CLAUDE.md): *"Portfolios, watchlists, risk limits, alerts, spend caps, and audit
rows are keyed by principal; position sizing takes equity as a per-user parameter."*
[SPEC.md §1.2](../SPEC.md) mechanism 1: mode is *"derived from the authenticated principal,
never from a client-supplied parameter."* In the DDL it appears as `portfolios.owner` and
`audit_log.principal` ([SPEC.md §3.2](../SPEC.md)).

**Why it matters here.** It is the concrete form of "multi-user from day one", which
[CLAUDE.md](../CLAUDE.md) names *"the expensive shortcut to avoid"*.
[SPEC.md editorial note 2](../SPEC.md) is explicit that this must not regress: *"The DDL in
§3.2 already does this correctly (`portfolios.owner`, `positions.portfolio_id`,
`audit_log.principal`) — **do not regress it into single-tenant convenience during
v0.9–v1.5**."*

**Example of the shortcut to avoid.**

```python
# WRONG — single-tenant, a rewrite to open up
def size_position(prob, price):
    equity = settings.ACCOUNT_EQUITY          # a config constant
    ...

# RIGHT — multi-user from day one
def size_position(prob, price, *, principal: Principal, portfolio_id: int):
    equity = portfolio_equity(portfolio_id)   # per-user parameter
    ...
```

**Gap G3 applies here.** No task in T1–T21 owns auth and identity — "auth" is one word inside
T16 (P9). Yet mode is derived from the principal in P0 and multi-user is mandated from day one.
**The principal model must be built in P0.**

**Common misunderstanding.** Assuming a principal is a person. It may also be a service
identity — the scheduler running the nightly connector sweep writes audit rows too, and those
rows need a principal.

**See also:** [Entitlements](#entitlements), [Mode gate](#mode-gate), [Audit log](#audit-log),
[Multi-user from day one](#multi-user-from-day-one),
[01_ARCHITECTURE.md](01_ARCHITECTURE.md).

---

### Provenance

**Plain words.** For every single number in the system: which document it came from, which page
of that document, and what date it refers to. Click a figure, see its origin.

**Precisely.** [CLAUDE.md](../CLAUDE.md) hard rule: *"**Provenance on every figure** — source
document, page, as-of date. Non-negotiable."* Invariant 1 of seven
([SPEC.md §4.1](../SPEC.md)). [DATA_FOUNDATION.md §3.6](../DATA_FOUNDATION.md) gives the full
field list: *"Every number links to `source_document_id`, `page`, `retrieved_at`,
`extraction_job_id`, `confidence`, `as_of_date`, and a `version` (incremented on
restatement)."* It calls this *"the backbone of the 'instrument, not judgment' trust promise."*

**Why it matters here.** Three separate reasons, and it is worth holding all three:

1. **Trust.** [TEAM_BRIEF.md Part 1](../TEAM_BRIEF.md) states the three-to-five-year vision as
   a user who *"trusts it, because every figure traces back to the audited filing it came
   from."*
2. **Acquirability.** [PROJECT_CONTEXT.md §9.3](../PROJECT_CONTEXT.md): *"Most cheap vendors
   don't do this, and it is exactly what institutional buyers pay premiums for."*
3. **Operational.** When the reviewer sees a suspicious number, provenance is what lets them
   check it in thirty seconds instead of re-hunting the PDF.

**It is measured, and the target is 100%.** [OPERATIONS.md §3.2](../OPERATIONS.md):
*"**Provenance completeness** — % of stored figures with a resolvable source document and page —
**must be 100%**."* Not a KPI to improve; an invariant to hold.

**It extends to LLM model versions.** [OPERATIONS.md §2.6](../OPERATIONS.md): *"Pin the LLM
model **id and version** used for extraction… you must be able to answer 'which model produced
this number?' That question is a provenance question, and provenance is the product."*

**Example.** Hovering ₦3,360,000,000,000 on the MTN Nigeria revenue chart shows:
`Source: MTN Nigeria FY2024 Annual Report, p.72 · as printed "Revenue" · as of 2024-12-31 ·
retrieved 2026-08-27 · extraction job #1184 (claude-…) · confidence 0.96 · version 1`.
`GET /provenance/{line_item_id}` ([DATA_FOUNDATION.md §4.4](../DATA_FOUNDATION.md)) is the
endpoint that serves it.

**Common misunderstanding.** Thinking a URL is provenance. A URL to a 300-page PDF is not
provenance; the **page number** is what makes it verifiable in seconds rather than minutes.
Same for derived numbers — a ratio's provenance is the set of line-item IDs that fed it, not a
source document of its own.

**See also:** [As-of date](#as-of-date), [Derived value](#derived-value),
[Source document](#source-document), [No silent overwrite](#no-silent-overwrite),
[08_DATA_CONTRACTS.md](08_DATA_CONTRACTS.md).

---

### Public mode

**Plain words.** The version of the system anyone can see. It shows data and lets you model
your own assumptions. It never tells you what to buy.

**Precisely.** [SPEC.md §1.2](../SPEC.md): *"PUBLIC MODE (anyone else): data, analytics, ratios,
and user-supplied scenario calculators only. It must NEVER emit a system-generated
recommendation, price target, or advice-shaped language."* And the design intent: *"Public mode
is designed so that **no SEC-registrable activity occurs**."*

**Why it matters here.** [PROJECT_CONTEXT.md §4](../PROJECT_CONTEXT.md) notes something easy to
miss: the public data tier is *"A complete product on its own, and the one §9's B2B buyers
actually want."* Public mode is not a crippled version of the product — it is the product that
has commercial value to institutions, who want the data and would not buy the advice anyway.

**The default, and why.** [SPEC.md §1.2](../SPEC.md) mechanism 1: *"Default is `public`
(fail-safe)."* If mode resolution fails for any reason — a bug, an unauthenticated request, a
misconfigured principal — the system falls back to the mode that cannot cause legal harm.
Failing open would be the catastrophic direction.

**Example of the boundary.** Public mode may say: *"Revenue grew 36% to ₦3.36tn while profit
after tax fell to a loss of ₦400.44bn, driven by ₦925.36bn of net FX losses"* — that is
description, sourced and cited. It may not say *"the shares look cheap on that basis."*

**See also:** [Personal mode](#personal-mode), [Mode gate](#mode-gate),
[Instrument, not judgment](#instrument-not-judgment),
[Banned-phrase linter](#banned-phrase-linter), [ISA 2025](#isa-2025).

---

### Show the work

**Plain words.** Whatever the system concludes, it also shows you the numbers, the assumptions,
and the dates it used to get there.

**Precisely.** [CLAUDE.md](../CLAUDE.md) hard rule: *"**Show the work in every mode** — even a
BUY carries its assumptions, inputs, and as-of dates."*
[PROJECT_CONTEXT.md §10](../PROJECT_CONTEXT.md) rule 3: *"The instrument argues; it does not
pronounce."*

**Why it matters here.** It is what keeps the tool from becoming an oracle. It is also what
makes an error recoverable — if the conclusion is wrong you can see *which input* was wrong.
A bare verdict is unfalsifiable; a verdict with its inputs is a claim you can check.

**Example.** A personal-mode memo ends with a recommendation *and* a
*"Data-provenance appendix with as-of dates"* — the last section of the memo template in
[SPEC.md §2E](../SPEC.md).

**See also:** [Instrument, not judgment](#instrument-not-judgment),
[Provenance](#provenance), [Personal mode](#personal-mode).

---

### Stable entity ID (`securities.id`)

**Plain words.** A permanent internal number for each company or listed security that never
changes, even when the ticker changes. Everything else — ticker, ISIN, CIK — is treated as a
label that can move.

**Precisely.** [OPERATIONS.md §1.4](../OPERATIONS.md): *"`securities.id` is the permanent
internal key and **never changes or is reused** — it is the thing that makes the dataset an
asset. Tickers, ISINs, and CIKs are time-bounded attributes."* Implemented by the
`security_identifiers` table with `id_type`, `id_value`, `valid_from`, `valid_to`, and the rule
that *"All ticker resolution goes through a single `resolve_security(id_type, value,
as_of_date)` function; **no `WHERE ticker = ?` anywhere else in the codebase**."*

**Why it matters here.** Two reasons. **Correctness:**
*"**Guaranty Trust Bank became GTCO in 2021** under a holdco restructure, and Nigerian
corporate reorganisations are common. When a ticker is reused or reassigned, a scalar column
silently joins one company's new prices onto another company's old history."*
**Acquirability:** [PROJECT_CONTEXT.md §9.4](../PROJECT_CONTEXT.md) lists *"Stable entity IDs
(internal permanent ID ↔ ticker / ISIN / CIK)"* as a cheap-now, expensive-later requirement.

**Example of the bug it prevents.**

```sql
-- WRONG: silently joins GTCO's post-2021 prices to GTB's pre-2021 statements,
-- or worse, to a different company that later took the "GTB" ticker
SELECT * FROM price_history p JOIN securities s ON s.id = p.security_id
WHERE s.ticker = 'GTCO';

-- RIGHT
SELECT * FROM price_history WHERE security_id = resolve_security('ticker','GTCO','2020-06-01');
```

**Gap G2 applies here.** `security_identifiers` is one of the six OPERATIONS Part 1 correctness
tables with **no T-number**. [OPERATIONS.md priority order](../OPERATIONS.md) says identity is
one of the four things to do *"before writing schema code."* It belongs in P0/P3.

**See also:** [Ticker](#ticker), [ISIN](#isin), [CIK](#cik),
[Corporate action](#corporate-action), [Survivorship bias](#survivorship-bias).

---

### Stage gate

**Plain words.** A pass/fail checkpoint at the end of a phase. Pass and continue; miss it and
something changes — usually you buy a shortcut or you drop the feature.

**Precisely.** [TEAM_BRIEF.md Part 4](../TEAM_BRIEF.md) defines them per version:

| Stage | Success means | Threshold to continue |
|---|---|---|
| **v0.1** (P1) Macro dashboard | You open it instead of hunting PDFs | Used daily for one week |
| **v0.2** (P2) US analyzer | Schema and analysis engine work on clean data | 5 US names render 5-yr statements + ratios with provenance links |
| **v0.3** (P3) Manual NG analyzer | Schema survives real Nigerian filings | **Handles a bank (GTCO) and a devaluation-hit telco (MTN) without modification** |
| **v0.4** (P4) Automated ingestion | The moat exists | **≥85% extraction accuracy** on 10 filings after review; Claude spend under ~$100/mo. *Miss → buy EODHD.* |
| **v0.5** (P5) News + brief | The daily habit | You read the brief instead of five news sites |
| **v0.8** (P7) Backtest harness | The harness doesn't lie | Synthetic profitable series → correct numbers; random walk → ~zero edge net of costs |
| **v0.9** (P8) ML signals | A real edge, or an honest no | **Clears the backtest gate**: DSR ≥ 0.95, positive net-of-cost, beats logreg and buy-and-hold OOS. *Miss → keep the data product, drop the signal layer.* |
| **v1.0** (P9) Web app | Family relies on it | Family members log in unprompted |
| **v2.0** (P12) Public beta | Strangers find it useful | Legal sign-off obtained; users return weekly without prompting |

**Why it matters here.** Each gate has a *documented consequence for failing*, decided in
advance. That is the whole point — it converts a judgement made under sunk-cost pressure into a
rule agreed while calm ([PROJECT_CONTEXT.md §8](../PROJECT_CONTEXT.md)).

**The one metric above all others.** [TEAM_BRIEF.md Part 4](../TEAM_BRIEF.md):
*"**does someone who isn't you use it every week without being asked?** Everything else is a
proxy for that."*

**See also:** [Decision gate](#decision-gate-buy-vs-build-threshold),
[Backtest gate](#backtest-gate-the), [Coverage metrics](#coverage-metrics),
[07_TEST_STRATEGY.md](07_TEST_STRATEGY.md).

---

### Staleness

**Plain words.** Data being older than it should be, and the system saying so out loud instead
of quietly showing an old number as though it were current.

**Precisely.** [CLAUDE.md](../CLAUDE.md) hard rule: *"**Staleness is visible** — every series
shows its as-of date and flags when overdue."* [OPERATIONS.md §2.2](../OPERATIONS.md) makes it
executable by adding three columns to `macro_series`:

```sql
ALTER TABLE macro_series
  ADD COLUMN expected_cadence   TEXT,   -- 'daily','monthly','quarterly','per_mpc'
  ADD COLUMN expected_lag_days  INT,    -- typical publish delay after period end
  ADD COLUMN stale_after_days   INT;    -- overdue threshold
```

Reference values given: **NBS CPI** monthly, published ~mid-month for the prior month
(`expected_lag_days ≈ 18`, stale after ~35); **NBS GDP** quarterly with a long lag;
**CBN MPR** per MPC, roughly bi-monthly; **CBN FX** each trading day; **DMO auctions** monthly.
Company filings are quarterly UFS and annual AFS, *"frequently late."*

**Why it matters here.** [PROJECT_CONTEXT.md §7](../PROJECT_CONTEXT.md) lists it first among
practical gaps, in descending cost of ignoring: *"otherwise we reason from stale numbers
without noticing."*

**The insight worth keeping.** [OPERATIONS.md §2.2](../OPERATIONS.md): *"**Overdue is
information, not just a warning** — 'NBS CPI is 9 days late' is genuinely useful to a Nigerian
investor and is exactly the kind of thing the public data tier can say without touching
advice."* Lateness is a publishable fact, not an internal error state. Treat late company
filings the same way: *"treat lateness itself as a signal worth surfacing, not an error."*

**Example.** The macro dashboard banner reads
`NBS CPI — as of Jul 2026 · expected ~18 Aug 2026 · 9 days overdue`.

**See also:** [As-of date](#as-of-date), [Connector health](#connector-health),
[Freshness](#freshness), [02_INFRASTRUCTURE.md](02_INFRASTRUCTURE.md).

---

### T-numbers (T1–T21)

**Plain words.** The twenty-one build tasks in `SPEC.md`, each with dependencies, acceptance
criteria, and the folders it touches.

**Precisely.** [SPEC.md §4.2](../SPEC.md), format *"ID · title · deps · acceptance · files."*

| Task | Title | Version | Deps | Packages |
|---|---|---|---|---|
| T1 | Macro dashboard | v0.1 | — | `/ingestion`, `/apps/streamlit` |
| T2 | EDGAR connector + US analyzer | v0.2 | T1 | `/ingestion`, `/valuation` |
| T3 | Manual NG analyzer | v0.3 | T2 | `/ingestion`, `/normalize` |
| T4 | LLM PDF extractor + HITL | v0.4 | T3 | `/ingestion` |
| T5 | News RSS + ticker tagging | v0.5 | T3 | `/sentiment` |
| T6 | Sentiment tiering | v0.5 | T5 | `/sentiment` |
| T7 | Daily brief + Telegram | v0.5 | T6 | `/bot`, `/alerts` |
| T8 | Scenario engine | v0.6 | T2 | `/valuation` |
| T9 | Indicator engine | v0.7 | T1 | `/indicators` |
| T10 | Cost models | v0.8 | — | `/backtest` |
| T11 | Backtest harness + purged/CPCV + DSR | v0.8 | T9, T10 | `/backtest` |
| T12 | ML pipeline: triple-barrier + meta-labeling + calibration | v0.9 | T9, T11 | `/ml` |
| T13 | Signal service + backtest gate | v0.9 | T11, T12 | `/ml`, `/api` |
| T14 | Multi-agent memo | v1.0 | T4, T12 | `/agents` |
| T15 | Compliance middleware + audit | **all versions** | — | `/compliance`, `/api` |
| T16 | Hosted web app | v1.0 | T13, T14, T15 | `/apps/web`, `/services/api` |
| T17 | Portfolio tracker + NG tax/WHT | v1.2 | T2 | `/portfolio` |
| T18 | Alerts engine | v1.2 | T7 | `/alerts` |
| T19 | Paper trading | v1.5 | T10, T13, T17 | `/portfolio`, `/execution` |
| T20 | Public beta | v2.0 | T15, T16 | all |
| T21 | Execution: US API + NGX manual ticket + safety layer | v2.5 | T13, T19 | `/execution` |

**Why it matters here.** [SPEC.md §4.1](../SPEC.md) invariant 7: *"**One-task-one-PR**, tests
required, SPEC.md is source of truth."* The task's acceptance criteria become the PR checklist
([SPEC.md §4.5](../SPEC.md)).

**The gaps in T1–T21, stated plainly.** Six pieces of necessary work have no T-number at all.
They are real holes, not oversights you should paper over:

| Gap | What has no task |
|---|---|
| **G1** | **Price history ingestion.** T9 computes indicators on `price_history` and T11 needs OHLCV bars, but no task ingests daily prices for NGX or US. A hard blocker for P6 and P7. |
| **G2** | **OPERATIONS Part 1** — corporate actions (§1.1), trading calendar (§1.2), FX table (§1.3), identity history (§1.4), fiscal alignment (§1.5), single unit-conversion point (§1.6). |
| **G3** | **Auth and identity.** "auth" is one word inside T16 (P9), yet mode derives from the principal in P0. |
| **G4** | **Backup and DR** (OPERATIONS §2.1) — the dataset is the moat; losing it is the one unrecoverable failure. |
| **G5** | **The data-licensing gate** — a [CLAUDE.md](../CLAUDE.md) hard rule with nothing enforcing it per source. |
| **G6** | **The golden test set** — T4's acceptance criteria depend on golden files existing. |

See [Section 9](#section-9--gaps-this-document-surfaces) for gaps G7–G11 surfaced by this
document, and [06_RISK_REGISTER.md](06_RISK_REGISTER.md) for full treatment.

**See also:**
[The four numbering systems](#the-four-numbering-systems--read-this-before-anything-else),
[P0–P13](#p0p13-the-phases).

---

### Multi-user from day one

**Plain words.** Building as though many people will use the system, even though today only two
do — because retrofitting multi-user is a rewrite and building it now is nearly free.

**Precisely.** [CLAUDE.md](../CLAUDE.md): *"**The expensive shortcut to avoid: never assume a
single user.** Portfolios, watchlists, risk limits, alerts, spend caps, and audit rows are keyed
by principal; position sizing takes equity as a per-user parameter. A single-user trading layer
is a full rewrite to open up."* [PROJECT_CONTEXT.md §10](../PROJECT_CONTEXT.md) rule 2 repeats
it, adding *"LLM spend caps are per-user as well as global"* and *"never a global 'the
portfolio.'"*

**Why it matters here.** [SPEC.md editorial note 2](../SPEC.md) flags the specific window of
risk: *"do not regress it into single-tenant convenience during **v0.9–v1.5**"* — that is
P8 through P11, when the trading features arrive and the temptation to hardcode "my equity" is
strongest.

**The five things that must be per-principal.** Portfolios · watchlists · risk limits · alerts ·
LLM spend caps. Plus: position sizing takes equity as a parameter, and every audit row carries
its principal.

**See also:** [Principal](#principal), [Build scope vs access control](#build-scope-vs-access-control),
[Position sizing](#position-sizing), [Spend cap](#spend-cap).

---

### Universe (company universe)

**Plain words.** The specific list of companies the system covers. Deliberately short.

**Precisely.** [PROJECT_CONTEXT.md §8](../PROJECT_CONTEXT.md): *"NGX has ~150 listed companies;
most barely trade. Pick **15–25** that actually matter. Breadth is a trap — it multiplies
extraction work while adding little value."* [TEAM_BRIEF.md §2.2-A](../TEAM_BRIEF.md) makes
choosing it the **first** manual task, ~1 day, Curator: *"it must come first — everything
downstream is sized by this number."*

**The recommended composition.** Start with the two **dual-listed** names — **Airtel Africa**
and **Seplat Energy** — because they file cleaner UK-standard statements in USD; then the liquid
majors: **MTN Nigeria, Dangote Cement, GTCO, Zenith, UBA, Nestlé**. And the non-negotiable:
*"Include **at least one bank** — banks use a different chart of accounts and will break a
schema built only on industrials. Better to discover that in week two than month four."*

**Why it matters here.** It is also a backtesting term. [SPEC.md §2C](../SPEC.md) lists
**selection bias** among the biases to prevent, with the fix: *"pre-register a fixed universe
and window."* Changing the universe after seeing results is a form of data snooping.

**Common misunderstanding.** Assuming more coverage is strictly better. Risk 8 in
[DATA_FOUNDATION.md §8.2](../DATA_FOUNDATION.md) is *"Scope creep across NGX's ~150 companies →
curate 15–25 liquid names first."* Each additional company adds extraction work, review load,
and corporate-action backfill, while most add no liquidity and no user value.

**See also:** [Free float](#free-float), [Selection bias](#selection-bias),
[Survivorship bias](#survivorship-bias), [Participation cap](#participation-cap).

---

### `unit_multiplier`

**Plain words.** Financial statements often print numbers "in thousands" or "in millions". This
field records that scale, so a figure printed as `3,360,000` can be understood as
₦3.36 trillion.

**Precisely.** A column on `financial_statements`
([DATA_FOUNDATION.md §4.2](../DATA_FOUNDATION.md)) and part of the LLM extraction output schema
([DATA_FOUNDATION.md §3.2](../DATA_FOUNDATION.md)): *"Report values in the reporting
currency/units exactly as stated, plus a `unit_multiplier`."*

**Why it matters here — and the rule that matters more.**
[OPERATIONS.md §1.6](../OPERATIONS.md) makes the crucial point: the risk is not the field, it is
that **the multiplication has no single home**. *"If the extractor stores raw-as-printed, the
ratio engine multiplies, and a chart multiplies again, you get a silent 1,000× error that looks
plausible on a log axis."*

**The rule.** `statement_line_items.value` stores the **fully scaled value in base currency
units** — the multiplication happens **exactly once**, in the extractor, at write time.
`as_printed` preserves the original string for provenance display. Plus a validation rule that
flags any figure more than **3 orders of magnitude** from that company's own trailing median for
the same `canonical_key`. As OPERATIONS notes: *"This catches the class of error that no
balance-sheet tie-out will."*

**Example.** MTN Nigeria FY2024 revenue prints as `3,360,000` with the statement header
"₦ million" (`unit_multiplier = 1000` in the Doc A worked example, reflecting how that
particular statement was presented). Stored: `value = 3_360_000_000_000`,
`as_printed = "3,360,000"`. Every consumer reads `value` and never multiplies again.

**Gap G2 applies here.** OPERATIONS §1.6 has no T-number.

**See also:** [Validation rules](#validation-rules-deterministic), [Line item](#line-item),
[Derived value](#derived-value).

---

### Validation rules (deterministic)

**Plain words.** Arithmetic checks run on extracted figures that do not involve any AI — the
accounting equations that must hold if the numbers were read correctly.

**Precisely.** [DATA_FOUNDATION.md §3.2](../DATA_FOUNDATION.md) lists them:

- Balance sheet: `assets == liabilities + equity` (within tolerance)
- Cash flow: `opening + net change == closing`
- Cross-statement: profit after tax ties across statements
- Cross-year: this year's opening balances == last year's closing balances
- Sign and units sanity: revenue > 0; flag swings greater than 5×

Plus [OPERATIONS.md §1.6](../OPERATIONS.md)'s magnitude rule: flag any figure more than 3 orders
of magnitude from that company's trailing median for the same `canonical_key`.

**Why it matters here.** They are the cheap, non-AI half of the accuracy strategy. An LLM can
hallucinate a plausible number; it cannot make a hallucinated number satisfy a balance-sheet
identity by accident. *"Any fail → `needs_review`, drop confidence, queue for human review."*

**Common misunderstanding.** Expecting them to pass on translated figures. They will not, and
that is a real trap: [OPERATIONS.md §1.3](../OPERATIONS.md) warns that using one FX rate for
everything *"produces a balance sheet that does not balance after translation, which then trips
your own validation rules and sends clean extractions to human review for no reason."* Run
validation on as-reported figures, not on translated ones.

**See also:** [`needs_review`](#needs_review), [Confidence](#confidence-two-different-meanings),
[FX translation](#fx-translation-ias-21), [07_TEST_STRATEGY.md](07_TEST_STRATEGY.md).

---

### Version (statement version)

**Plain words.** A numbered edition of a company's financial statement for a given period. When
the company restates its numbers, you get version 2 — and version 1 stays.

**Precisely.** `financial_statements(… version, superseded_by, restatement …)` with
`UNIQUE(company_id, statement_type, period_end, period_type, version)`
([DATA_FOUNDATION.md §4.2](../DATA_FOUNDATION.md)). SPEC's bias taxonomy names the fields
needed for backtesting: `statement_version` and `first_available_date`
([SPEC.md §2C](../SPEC.md)).

**Why it matters here.** It is the mechanism behind [No silent overwrite](#no-silent-overwrite)
and half the mechanism behind [Point-in-time](#point-in-time). SPEC explicitly analogises it:
*"exactly what FRED's ALFRED vintages do for macro and Doc A's versioned statements do for
fundamentals."*

**See also:** [Restatement](#restatement), [Vintage](#vintage--alfred-vintages),
[No silent overwrite](#no-silent-overwrite).

---

### Version roadmap (v0.1–v2.5)

**Plain words.** The product-milestone numbering. Each version is a thing that works and is
worth using, not an internal checkpoint.

**Precisely.** [SPEC.md §1.3](../SPEC.md):

| Version | Deliverable | Phase |
|---|---|---|
| v0.1 | Macro dashboard (FRED, CBN, NBS, DMO) — local Streamlit | P1 |
| v0.2 | US company analyzer (EDGAR ingest, ratios, DCF) | P2 |
| v0.3 | Manual Nigerian analyzer (upload PDF → normalized) | P3 |
| v0.4 | Automated Nigerian ingestion (PDF pipeline + HITL review) | P4 |
| v0.5 | News + sentiment + daily brief | P5 |
| v0.6 | Scenario engine (user-set assumptions) | P6 |
| v0.7 | Technical indicators engine (features only, no signals yet) | P6 |
| **v0.8** | **Backtesting harness + purged/CPCV + NGX cost model** | **P7** |
| v0.9 | ML signals with calibration — gated by the v0.8 backtest gate | P8 |
| v1.0 | Multi-agent research memos + hosted web app | P9 |
| v1.2 | Portfolio tracking + alerts | P10 |
| v1.5 | Paper trading (simulated fills with NGX costs) | P11 |
| v2.0 | Public beta (data-only, public mode) | P12 |
| v2.5 | Optional execution — US via Alpaca/IBKR; NGX manual ticket | P13 |

**What each version unlocks**, from [SPEC.md Part 5](../SPEC.md): *"v0.1 macro context;
v0.2–0.4 the data moat (US then NG, manual then automated); v0.5 the daily habit (brief);
v0.7–0.9 the personal edge (indicators → backtest → calibrated signals); v1.0 memos + a real
web app; v1.2–1.5 portfolio truth + safe simulation; v2.0 a public data product; v2.5 personal
execution convenience."*

**See also:** [P0–P13](#p0p13-the-phases),
[The four numbering systems](#the-four-numbering-systems--read-this-before-anything-else).

---

<!-- APPEND-HERE -->

# 05 — Personas, Business Needs, Epics, User Stories & Outcomes

> Part of the `quant_model` planning set. Siblings: [00_START_HERE.md](00_START_HERE.md) ·
> [01_ARCHITECTURE.md](01_ARCHITECTURE.md) · [02_INFRASTRUCTURE.md](02_INFRASTRUCTURE.md) ·
> [03_ROADMAP_PART1_PHASES_0-6.md](03_ROADMAP_PART1_PHASES_0-6.md) ·
> [04_ROADMAP_PART2_PHASES_7-13.md](04_ROADMAP_PART2_PHASES_7-13.md) ·
> [06_RISK_REGISTER.md](06_RISK_REGISTER.md) · [07_TEST_STRATEGY.md](07_TEST_STRATEGY.md) ·
> [08_DATA_CONTRACTS.md](08_DATA_CONTRACTS.md) · [09_GLOSSARY.md](09_GLOSSARY.md)
>
> Last updated: 2026-08-28. **Nothing in this project has been built yet** — the repository
> today contains six markdown files, an empty `package.json`, and `node_modules/`. Every
> story below is unstarted.

---

## What this document is for

The other documents in this set say *what we are building* and *how*. This one says **who
wants it, what they actually do with it, and how we will know it worked.** It converts the
thesis in [PROJECT_CONTEXT.md](../PROJECT_CONTEXT.md) and the twenty-one engineering tasks in
[SPEC.md §4.2](../SPEC.md) into people with problems, and then into 130 numbered user stories
with testable acceptance criteria — so that when a coding agent (or you, six months from now)
asks "why does this feature exist and how do I know it is finished?", there is one place with
the answer. It also names the gaps in the source specification (TG1–TG20) where a story is
currently **undeliverable because no task owns the work**, and adds seven more found while
writing this.

Read it in one of three ways:

- **Planning a phase** → jump to the epic for that phase in §3, then its stories in §4.
- **Building one thing** → find the story ID, read its acceptance criteria, build to those.
- **Deciding whether to continue** → §7 (expected outcomes) and §6 (non-goals) are the
  honest checkpoints.

---

## Table of contents

- [§0 — How to read a story here](#0--how-to-read-a-story-here)
  - [0.1 Story block format](#01-story-block-format)
  - [0.2 Priority definitions](#02-priority-definitions)
  - [0.3 Risk markers](#03-risk-markers)
  - [0.4 Mode-sensitivity marker](#04-mode-sensitivity-marker)
  - [0.5 The vocabulary you need before §1](#05-the-vocabulary-you-need-before-1)
- [§1 — Personas](#1--personas)
  - [1.1 The persona map](#11-the-persona-map)
  - [1.2 Internal personas](#12-internal-personas--the-people-who-make-the-data-exist)
  - [1.3 Capital personas](#13-capital-personas--the-people-whose-money-is-at-risk)
  - [1.4 Public personas](#14-public-personas--post-p12)
  - [1.5 B2B personas](#15-b2b-personas--the-commercial-layer)
  - [1.6 Gatekeeper personas](#16-gatekeeper-personas)
  - [1.7 Anti-personas](#17-anti-personas--who-this-is-explicitly-not-for)
- [§2 — Business needs](#2--business-needs)
- [§3 — Epics, one per phase](#3--epics-one-per-phase)
- [§4 — The user stories](#4--the-user-stories)
- [§5 — Mode-sensitive stories, collected](#5--mode-sensitive-stories-collected)
- [§6 — Non-goals per version](#6--non-goals-per-version)
- [§7 — Expected results and outcomes](#7--expected-results-and-outcomes)
- [§8 — Traceability matrices](#8--traceability-matrices)
- [§9 — Gaps that leave stories undeliverable](#9--gaps-that-leave-stories-undeliverable)
- [§10 — What I left for other documents](#10--what-i-left-for-other-documents)

---

## §0 — How to read a story here

### 0.1 Story block format

Every story looks like this:

> #### US-000 · Short title
> `Persona` P-01 Owner · `Priority` Must · `Phase` P4 (v0.4) · `Task` T4 · `Risk` 🟡 WATCH
>
> **As** the Owner, **I want** X, **so that** Y.
>
> **Acceptance criteria**
> - **Given** a precondition, **When** an action happens, **Then** an observable result.
>
> **Decomposes into**
> - [ ] the concrete pieces of work

The fields mean:

| Field | What it is |
|---|---|
| **US-000** | A permanent identifier. Never reuse or renumber it. If a story is dropped, mark it `WITHDRAWN` and leave the number dead. |
| **Persona** | Who benefits. Codes defined in [§1.1](#11-the-persona-map). |
| **Priority** | Must / Should / Could — see [§0.2](#02-priority-definitions). |
| **Phase** | The canonical phase, plus the SPEC version it corresponds to. Never renumbered. |
| **Task** | The [SPEC.md §4.2](../SPEC.md) task (T1–T21) that delivers it, or an explicit note that **no task owns it** — a gap, see [§9](#9--gaps-that-leave-stories-undeliverable). |
| **Risk** | 🟢 / 🟡 / 🔴 — see [§0.3](#03-risk-markers). |

**Given/When/Then** is a way of writing an acceptance test in prose so it can be turned into a
real test without further interpretation. *Given* is the world before, *When* is the single
thing that happens, *Then* is what you can observe afterwards. If you cannot picture the
`assert` statement, the criterion is too vague and should be rewritten.

### 0.2 Priority definitions

| Priority | Meaning | Consequence of dropping it |
|---|---|---|
| **Must** | The phase is not done without it. | The phase gate fails; downstream phases build on sand. |
| **Should** | Real value; the phase is materially worse without it, but can ship and the story lands next phase. | Deferred debt, tracked. |
| **Could** | Genuinely optional. Recorded because someone will ask for it, and a rejected story beats an unrecorded idea. | Nothing breaks. |

There is no "Won't" priority. That is what [§6 Non-goals](#6--non-goals-per-version) is for,
and non-goals are stated per version so scope creep is visible the moment it happens.

### 0.3 Risk markers

Used identically across this document set. The full treatment lives in
[06_RISK_REGISTER.md](06_RISK_REGISTER.md); here the markers are attached to individual
stories.

| Marker | Meaning |
|---|---|
| 🟢 **SOLID** | Well-understood, low variance, proven approach. If it breaks, the break is obvious and cheap to fix. No reason to worry here. |
| 🟡 **WATCH** | It will work, but has a known failure mode, a cost curve, or a dependency that can move. Every WATCH story states the **early-warning signal** — the specific thing you would notice first. |
| 🔴 **FRAGILE** | Genuinely likely to go wrong, or the effort could be off by multiples. **Every FRAGILE story carries at least three distinct approaches** with trade-offs and a recommendation, because you should not discover you need a plan B in the middle of the problem. |

These ratings do not contradict the source documents' own honest assessments
([DATA_FOUNDATION.md §8.2, §8.3](../DATA_FOUNDATION.md), [SPEC.md PART 6](../SPEC.md),
[TEAM_BRIEF.md PART 3](../TEAM_BRIEF.md)) — they extend them down to story level.

### 0.4 Mode-sensitivity marker

Some stories have a **different acceptance criterion depending on which mode the system is
serving**. Those are marked:

> 🔀 **MODE-SENSITIVE** — separate acceptance criteria for personal and public mode.

The two modes, in plain words ([SPEC.md §1.2](../SPEC.md),
[PROJECT_CONTEXT.md §4](../PROJECT_CONTEXT.md), [CLAUDE.md](../CLAUDE.md)):

- **Personal mode** — the owner and family, using their own capital. The system **may** say
  BUY or SELL, print a price target, show model conviction, and size a position. There is no
  client, no fee, no fiduciary duty to a stranger, and no regulator interested in what
  someone does with their own money. **Do not write public-mode disclaimer language into a
  personal-mode criterion.** CLAUDE.md is explicit: "Do not add public-facing disclaimers or
  strip advice features on the assumption this is a regulated product; it is not."
- **Public mode** — everyone else, pre-licence. Data, ratios, macro, news, and calculators
  where the *user* supplies every assumption. It must never emit a system-generated
  recommendation, price target, or advice-shaped phrase, because doing that as a business
  requires SEC registration under Nigeria's Investments and Securities Act 2025
  ([SPEC.md §1.2](../SPEC.md)).

Mode is **derived server-side from the authenticated principal and defaults to `public`**
(fail-safe). It is never a request parameter ([SPEC.md §4.1](../SPEC.md), invariant 6).

One thing that is *not* mode-sensitive, in either direction: **showing the work.** Even a BUY
carries its assumptions, its inputs and their as-of dates
([PROJECT_CONTEXT.md §10](../PROJECT_CONTEXT.md) rule 3). The instrument argues; it does not
pronounce.

### 0.5 The vocabulary you need before §1

Defined once here, used throughout. The full dictionary is
[09_GLOSSARY.md](09_GLOSSARY.md).

| Term | Plain-language definition |
|---|---|
| **Principal** | The authenticated identity making a request — a specific user account, not "the app". Every portfolio row, alert, spend cap and audit record is keyed to one. Saying "the portfolio" instead of "this principal's portfolio" is the one shortcut that turns opening to the public into a rewrite ([CLAUDE.md](../CLAUDE.md)). |
| **Entitlement** | A flag on a principal saying which tier they may reach. Opening the advice tier to the public on licence day means flipping entitlements plus a `licence_status` flag — not writing new features. |
| **Provenance** | For any number: which source document, which page, and when it was retrieved. Non-negotiable on every figure ([PROJECT_CONTEXT.md §10](../PROJECT_CONTEXT.md), rule 4). |
| **As-of date** | The date the figure was true *as of*, distinct from when we fetched it. Nigerian CPI published mid-September is *as of* August. |
| **Point-in-time (PIT)** | Using only information actually knowable on the decision date. If a company restated its 2023 accounts in 2025, a backtest deciding in 2024 must use the 2023 numbers *as published in 2023*. Every feature carries a `known_as_of` timestamp; joins filter `known_as_of <= decision_date` ([SPEC.md §2C](../SPEC.md)). |
| **Restatement / vintage** | A corrected version of a previously published figure. We never overwrite; we add a new version and mark the old one superseded ([DATA_FOUNDATION.md §3.6](../DATA_FOUNDATION.md)). A *vintage* is the set of numbers as they stood at one moment. |
| **Canonical chart of accounts** | The internal dictionary mapping every label a Nigerian company might print — "Turnover", "Gross earnings", "Revenue" — onto one internal key such as `revenue`. Banks need a parallel chart ([TEAM_BRIEF.md §2.2-G](../TEAM_BRIEF.md)). |
| **Golden test set** | Three filings where a human hand-verified **every** number and wrote the expected output by hand. Every automated extraction test measures against it. TEAM_BRIEF §2.2-C calls building it "the highest leverage task in the project". |
| **HITL (human-in-the-loop)** | A review queue where a person confirms or corrects machine output before it is trusted. |
| **Backtest** | Replaying a trading strategy over historical data to see what it would have done. |
| **Backtest gate** | The hard rule that no signal touches real capital until a recorded backtest run passes pre-registered criteria ([SPEC.md §4.1](../SPEC.md), invariant 3). |
| **DSR (Deflated Sharpe Ratio)** | A Sharpe ratio (return per unit of volatility) adjusted downward for how many strategies you tried before finding this one, and for return skew and fat tails. It answers "did I find an edge, or did I get lucky after 500 attempts?" A nominal Sharpe of 2.0 can deflate to DSR 0.30 — almost certainly curve-fitted (Bailey & López de Prado, per [SPEC.md §2C](../SPEC.md)). |
| **K (trial count)** | How many strategy variants you tested. DSR needs it; not recording it honestly makes DSR meaningless. |
| **CPCV (Combinatorial Purged Cross-Validation)** | A way of splitting time-series data for testing that (a) removes training rows whose outcomes overlap the test window ("purging"), (b) leaves a gap after each test block ("embargo"), and (c) generates many train/test combinations, so you get a *distribution* of results instead of one number. Ordinary k-fold cross-validation is invalid for time series because it shuffles the future into the past. |
| **Triple-barrier labelling** | Defining "did this trade work?" by setting three exits — profit target, stop-loss, time limit — and labelling by whichever is hit first. |
| **Calibration** | Making a model's stated probability mean what it says: of all the times it says 70%, roughly 70% should happen. Measured by the Brier score (lower is better). |
| **±10% price band** | The NGX rule that **halts** a stock for the rest of the day once it moves 10% ([SPEC.md §2C](../SPEC.md)). Unlike US circuit breakers it does not pause and resume. A backtest assuming it filled at the band price is fiction. |
| **T+3** | NGX settlement: cash and shares actually change hands three trading days after the trade, so no same-day round trips, and capital is locked meanwhile. |
| **Participation cap** | A backtest assumption limiting a simulated fill to a small share of that day's real volume, so you do not "buy" more than the market actually traded. |
| **Corporate action** | A bonus issue, rights issue, split or dividend. A 1-for-4 bonus issue drops the quoted price ~20% overnight with no economic loss; unadjusted, every backtest crossing that date records a fake crash ([OPERATIONS.md §1.1](../OPERATIONS.md)). |
| **Mode gate / compliance middleware** | The server-side layer deciding which mode a request runs in and blocking advice-shaped output from leaving a public endpoint. Its core lands in **P0** and it is hardened in every phase through P12. |
| **Streamlit / FastAPI / Next.js** | Streamlit = a Python library that turns a script into a web page fast; used as a **thin client only**. FastAPI = the Python API server where all logic lives. Next.js = the polished JavaScript frontend arriving in P9, and the **only** non-Python component in the whole system. |
| **WHT (withholding tax)** | Tax deducted at source. Nigerian dividends are subject to 10% WHT, so the cash that lands is 90% of the declared amount ([SPEC.md §2H](../SPEC.md)). |
| **CGT (capital gains tax)** | Tax on the gain when you sell. Under the Nigeria Tax Act 2025 (effective 1 Jan 2026), share disposals are not chargeable where aggregate proceeds are under ₦150,000,000 **and** the chargeable gain does not exceed ₦10,000,000 in any 12 consecutive months ([SPEC.md §2H](../SPEC.md)). |

**One architectural note affecting many stories below.** FastAPI stands up in **P0**, not P9.
[SPEC.md §4.2](../SPEC.md) places the API at T16/v1.0, but T15 (compliance middleware) is
marked "front-loaded, all versions" with files `/compliance` and `/api`, and
[SPEC.md §4.1](../SPEC.md) invariant 6 requires mode to be server-derived. A Streamlit-only
app has no server to derive mode from. **This is a deliberate, documented deviation from
SPEC.md's literal task ordering, and it is flagged as such wherever it appears.** Streamlit is
a thin client from P1 onward; business logic in a Streamlit callback is a defect, and that
discipline is exactly what makes swapping in Next.js at P9 a presentation change rather than a
rewrite.

---

## §1 — Personas

A persona here is not a marketing sketch. It is a decision aid: when two designs are
plausible, the persona says which one is right. Each carries five fields, and the fourth —
**what would make them abandon** — is the one that most often changes a design, because it
names the failure that actually loses the user.

### 1.1 The persona map

| Code | Persona | Group | First served in |
|---|---|---|---|
| **P-01** | Owner / Operator (Frank) | Capital | **P1** |
| **P-02** | Family member with capital in the pot | Capital | **P9** (meaningfully); read-only glimpses from P1 |
| **P-03** | Nigerian retail investor | Public | **P12** |
| **P-04** | Nigerian professional analyst | Public | **P12** |
| **P-05** | Diaspora investor | Public | **P12** |
| **P-06** | Student / channel audience learner | Public | **P12** (content from P1 onward) |
| **P-07** | Broker or asset-manager research head | B2B | **P12** (pilot conversations from P4) |
| **P-08** | Fintech product manager | B2B | **P12** |
| **P-09** | Bank credit analyst | B2B | **P12** |
| **P-10** | Global data vendor partnerships lead | B2B | Post-P12 |
| **P-11** | Acquirer technical due-diligence lead | B2B | Post-P12, if ever |
| **P-12** | Curator | Internal | **P0** |
| **P-13** | Collector | Internal | **P0** |
| **P-14** | Reviewer | Internal | **P3** |
| **P-15** | Data-entry analyst | Internal | **P3** |
| **P-16** | Nigerian securities & data-protection lawyer | Gatekeeper | **P4** (book early), blocks **P12** |
| **P-17** | Future maintainer — human or coding agent | Internal | **P0** |

The internal roles P-12 to P-15 come from [TEAM_BRIEF.md §2.1](../TEAM_BRIEF.md). In a
one-person project all four hats sit on P-01's head — but they are still separate personas,
because the *tooling* each needs is different. A Collector needs a file-naming convention and
a download log. A Reviewer needs a diff view and a keyboard shortcut for "accept". Building
one screen for "the user" produces a screen that serves neither.

---

### 1.2 Internal personas — the people who make the data exist

#### P-12 · Curator

**Who they are.** The owner wearing the domain-expert hat. Needs market knowledge and
accounting literacy ([TEAM_BRIEF.md §2.1](../TEAM_BRIEF.md)). Load is front-loaded, then
light.

**What they are trying to accomplish.** Decide *which* 15–25 NGX companies exist in this
system and what every line item in every filing means. Concretely: the company universe
(TEAM_BRIEF §2.2-A, ~1 day, do first), the ticker alias table (§2.2-F, ~half a day, ongoing),
and the canonical chart of accounts (§2.2-G, ~2 days). Also co-owns the golden test set
(§2.2-C).

**Painful status quo.** These decisions currently live in the owner's head, get made
implicitly, and get made *differently* each time. Today "GTCO" and "Guaranty Trust Holding
Company" are the same company only because a human happens to know it.

**What would make them abandon.** Discovering in month four that the chart of accounts cannot
express a bank's income statement, and that fixing it means re-extracting everything.
[TEAM_BRIEF.md §2.2-G](../TEAM_BRIEF.md) is blunt: "Get it right before v0.4. Changing it
after the extractor is running means re-extracting everything."

**First served.** **P0** — the chart of accounts and the universe are inputs to the DDL, not
outputs of it.

#### P-13 · Collector

**Who they are.** Care and organisation; no finance background needed
([TEAM_BRIEF.md §2.1](../TEAM_BRIEF.md)). Heavy at the start, light later. Can be a
contractor.

**What they are trying to accomplish.** Get roughly 100 PDFs (15–25 companies × ~5 years) onto
disk, correctly named `TICKER_FY2024_AR.pdf`, with a spreadsheet logging source URL and
download date for every file — **that log becomes the `source_documents` table**
(TEAM_BRIEF §2.2-B). Also the corporate-actions backfill (§2.2-E) and the monthly macro
download (§2.2-H, ~30 min/month until automated).

**Painful status quo.** Downloading a PDF from `africanfinancials.com` into `~/Downloads` as
`AR_final_v2(3).pdf`, with the source URL lost the moment the browser tab closes. Provenance
destroyed at the first step — and provenance *is* the product.

**What would make them abandon.** Being asked to redo the collection because the naming
convention changed, or because nobody said the URL mattered until after 100 files were saved.

**First served.** **P0** — the naming convention, folder layout, and log template must exist
*before* the first download, not after.

#### P-14 · Reviewer

**Who they are.** Solid accounting; can spot a wrong number
([TEAM_BRIEF.md §2.1](../TEAM_BRIEF.md)). Light at first, then **permanent**.

**What they are trying to accomplish.** Hand-verify the golden set (§2.2-C), then work the
ongoing extraction review queue (§2.2-I) — every extraction below confidence 0.85 plus every
validation failure. The stated expectation: at ~90% accuracy on ~200 line items per annual
report, roughly **20 corrections per filing**.

**Painful status quo.** There is no queue. Today a wrong number in a spreadsheet is found when
a ratio looks impossible, if it is found at all.

**What would make them abandon.** A review queue that grows faster than they can clear it.
[TEAM_BRIEF.md PART 3](../TEAM_BRIEF.md) names this as bottleneck 5: "Review capacity becomes
the ceiling." The second abandonment trigger is corrections that do not stick — correcting the
same number twice because the next extraction run overwrote it is the fastest way to lose a
reviewer.

**First served.** **P3**, when there is data to review. But the *correction-persistence
guarantee* must be in the schema from **P0**, because retrofitting versioned corrections onto
a table that overwrites is a migration plus a data-loss investigation.

#### P-15 · Data-entry analyst

**Who they are.** Can read a financial statement. Heavy load during the P3 manual backfill,
~2–4 hours per company-year ([TEAM_BRIEF.md §2.2-D](../TEAM_BRIEF.md)). The one genuinely
parallelisable manual block; a contractor can do it.

**What they are trying to accomplish.** Hand-key statements into a CSV template. Scope: **5
companies × 2 years, not 5 × 5** (TEAM_BRIEF §2.2-D scopes this down deliberately). The point
is not volume — it is forcing IFRS edge cases into the open cheaply, before an expensive
extractor is built on wrong assumptions.

**Painful status quo.** No template exists, so every analyst invents their own column names.

**What would make them abandon.** A template that rejects their input without saying which
cell is wrong, or one that has no place to record "this line item does not exist in this
filing" — because [SPEC.md §4.1](../SPEC.md) invariant 4 forbids inferring a missing value,
so "absent" must be an expressible, first-class answer, not a blank cell that means either
"missing" or "not yet keyed".

**First served.** **P3**.

#### P-17 · Future maintainer (human or coding agent)

**Who they are.** Whoever touches this code in six months. Statistically, that is either the
owner with no memory of the decision, or an AI coding agent with no memory at all. This
project is explicitly built "largely with AI agents"
([TEAM_BRIEF.md](../TEAM_BRIEF.md), [SPEC.md §4.5](../SPEC.md)), so this persona is real, not
notional.

**What they are trying to accomplish.** Make one change without breaking an invariant they
have never read.

**Painful status quo.** In most projects: read the code, guess the intent, break something
subtle. [DATA_FOUNDATION.md §8.2](../DATA_FOUNDATION.md) item 10 names it: "Agent drift on a
big spec."

**What would make them abandon.** Nothing — they cannot abandon; they will simply do it
wrong. That is worse. The mitigations are structural: SPEC.md as law with invariants at the
top, one-task-one-PR, tests required, an ADR log recording *why* each decision was made, and
CI that fails the build when an agent adds an advice-shaped field to a public schema or
bypasses the backtest gate ([SPEC.md §4.5](../SPEC.md), [OPERATIONS.md §3.1](../OPERATIONS.md)).

**First served.** **P0**, and every phase after.

---

### 1.3 Capital personas — the people whose money is at risk

#### P-01 · Owner / Operator (Frank)

**Who they are.** Technically capable, building this largely with AI agents. Runs a
"Finance × Tech × Data" content channel, which [PROJECT_CONTEXT.md §8](../PROJECT_CONTEXT.md)
calls "a real asset the spec under-weights". Holds the Curator hat and, initially, all four
internal hats. The only person with authority over money, legal, and accounts
(TEAM_BRIEF §2.2-J).

**What they are trying to accomplish.** Three things that are genuinely separate:

1. **Replace a weekly manual research routine** — hunting NGX PDFs, hand-keying statements
   into spreadsheets, eyeballing valuations ([SPEC.md PART 5](../SPEC.md), "Personal value").
2. **Decide where to put real capital**, with a written rationale and an audit trail, and
   only after a backtest that has not lied to him.
3. **Build the missing structured database of Nigerian corporate finance** — which is the
   part that is valuable regardless of whether 1 and 2 work
   ([TEAM_BRIEF.md PART 1](../TEAM_BRIEF.md)).

**Painful status quo.** Stated precisely in [PROJECT_CONTEXT.md §2](../PROJECT_CONTEXT.md):
Nigerian company financials sit as PDFs on company websites; inflation is a PDF from NBS;
policy rates are on the CBN site; bond auctions are on DMO; news is spread across five or more
outlets. **To understand one company you visit six places and re-key numbers into a
spreadsheet.** Plus the failure mode that no amount of diligence fixes: "I forgot to look."

**What would make them abandon.** Three distinct things, in descending likelihood:

- **The middle.** [TEAM_BRIEF.md PART 1](../TEAM_BRIEF.md): "most projects like this die in
  the middle, when the novelty is gone and the PDFs are still badly formatted." The
  counterweight is that the boring part *is* the moat.
- **Three half-built products.** [PROJECT_CONTEXT.md §8](../PROJECT_CONTEXT.md): a data
  pipeline, an analytical product and a trading system share a foundation but "do **not** share
  a finish line". If six months in all three are half-built, the honest move is to finish the
  data layer completely and let the others wait.
- **Sunk cost on extraction.** The pre-agreed rule: if extraction accuracy stalls after N
  weeks, buy EODHD and move on. Decide the threshold while calm.

**First served.** **P1** — a Streamlit macro dashboard he opens instead of hunting PDFs.

#### P-02 · Family member with capital in the pot

**Who they are.** Not a finance professional. Has real money in decisions the owner makes.
Will not read a ratio table for fun and will not learn what EV/EBITDA means to check on their
own savings.

**What they are trying to accomplish.** Understand what is being done with their money and
why, without having to ask, and without having to trust blindly.
[SPEC.md PART 5](../SPEC.md), "Family value": shared visibility, every decision backed by a
written cited memo and a reproducible backtest, with hard risk limits and a human-confirm step
protecting against panic decisions in a dip.

**Painful status quo.** A verbal update from the owner, or nothing. No record of what was
decided or why. When the market falls, no way to check whether the plan anticipated it.

**What would make them abandon.** The interface not explaining itself.
[PROJECT_CONTEXT.md §7](../PROJECT_CONTEXT.md) states it directly: "The owner will understand
every number; family will not. If the goal is shared visibility, the interface must explain
itself — what a ratio means, why a figure moved — or **only one person will ever use it.**"
Second trigger: a login flow they cannot complete on a phone.

**First served.** Meaningfully at **P9**, whose stage gate is literally "family members log in
unprompted" ([TEAM_BRIEF.md PART 4](../TEAM_BRIEF.md)). This persona is the reason the
plain-language explanation layer is a Must and not a Could.

---

### 1.4 Public personas — post-P12

None of these people can reach the system before P12, and none can reach advice-tier output
before the SEC licence exists ([PROJECT_CONTEXT.md §10](../PROJECT_CONTEXT.md), rule 9 — "the
one line carrying real legal risk").

#### P-03 · Nigerian retail investor

**Who they are.** Putting real money into a market that determines whether their savings
outrun ~25% inflation ([TEAM_BRIEF.md PART 1](../TEAM_BRIEF.md)). Not an accountant. Mobile
first. Price sensitive.

**What they are trying to accomplish.** Read a company's numbers before buying its shares, and
understand whether the price is sane.

**Painful status quo.** They cannot. The data is published, publicly, by law — and is trapped
in a format nobody can query. An institution with a Bloomberg terminal pulls five years of
normalized financials in seconds; this person cannot. That asymmetry "is not subtle"
(TEAM_BRIEF PART 1).

**What would make them abandon.** A number they cannot trace to a filing; a page that takes
30 seconds to load on a Nigerian mobile connection; or a price point above the realistic
₦5,000–₦15,000/month band ([SPEC.md PART 5](../SPEC.md)), given strong free-tier expectations.

**First served.** **P12**.

#### P-04 · Nigerian professional analyst

**Who they are.** Works at a broker, asset manager, PFA or research house. Paid partly for
speed. Already knows what a ratio means — does not need the explainer, needs the export.

**What they are trying to accomplish.** Build a comparable set across ten NGX names without
spending two days assembling it.

**Painful status quo.** [PROJECT_CONTEXT.md §9.2](../PROJECT_CONTEXT.md): "Their analysts
download PDFs and re-key numbers today." The product sells back analyst hours.

**What would make them abandon.** One wrong number found by hand, if it is not traceable and
correctable. A professional will forgive a gap; they will not forgive a figure that is
confidently wrong with no provenance. Second trigger: no bulk export, forcing them to
copy-paste out of a web page — which is the same re-keying they came to escape.

**First served.** **P12**. But this persona is also the first realistic **paying** user, and
the first credible test of the B2B thesis, which is why the "first analyst who says *I use
this instead of building the spreadsheet*" is TEAM_BRIEF's year-two success marker.

#### P-05 · Diaspora investor

**Who they are.** Nigerian abroad, wanting Nigerian-market exposure, working from a distance
and a time zone.

**What they are trying to accomplish.** Real Nigerian-exposure data with as-of dates instead
of stale or absent numbers ([SPEC.md PART 5](../SPEC.md)).

**Painful status quo.** International data vendors have a Nigeria-shaped hole
([PROJECT_CONTEXT.md §9.2](../PROJECT_CONTEXT.md)). What they can find is stale, unsourced,
or a guess.

**What would make them abandon.** Discovering a figure was 14 months old and nothing said so.
This persona is the single strongest argument for the visible-staleness rule
([PROJECT_CONTEXT.md §10](../PROJECT_CONTEXT.md), rule 6): being far away means you cannot
sanity-check against local knowledge.

**First served.** **P12**.

#### P-06 · Student / channel audience learner

**Who they are.** Follows the content, wants the tool. Learning finance with actual local data
instead of American textbook examples ([TEAM_BRIEF.md PART 1](../TEAM_BRIEF.md)).

**What they are trying to accomplish.** See how a valuation is actually built, with real
inputs they can change.

**Painful status quo.** Textbook examples about companies they will never buy, in a currency
whose inflation rate does not resemble theirs.

**What would make them abandon.** A black box. This persona wants the *mechanism* visible —
which is the same thing the "instrument, not judgment" rule wants
([DATA_FOUNDATION.md §1.4](../DATA_FOUNDATION.md)), so serving them costs almost nothing extra.

**Why they matter more than their revenue.** They are **free validation before you write the
public version**: [PROJECT_CONTEXT.md §8](../PROJECT_CONTEXT.md) — "if viewers say *I'd use
that*, that's a signal earned before writing the public version." Building this in public is
content nobody else can make.

**First served.** **P12** for the product; the content flywheel starts at P1.

---

### 1.5 B2B personas — the commercial layer

From [PROJECT_CONTEXT.md §9.2](../PROJECT_CONTEXT.md). These personas justify the API-first,
stable-identifier, clean-licensing design decisions that would otherwise look like premature
engineering.

#### P-07 · Broker / asset-manager research head

**Who they are.** At a Meristem, CardinalStone, Chapel Hill Denham, ARM, or a PFA. Has a
research team whose hours cost money.

**Goal.** Company fundamentals for research notes and client reporting, in a form their
analysts can pull rather than assemble.

**Painful status quo.** Analysts download PDFs and re-key numbers. Every note starts with two
days of assembly.

**Would abandon if.** The coverage does not include the names they actually write about; the
API breaks without notice; or their compliance team asks "do you have the right to
redistribute this?" and the answer is unclear. That last one is
[PROJECT_CONTEXT.md §9.3](../PROJECT_CONTEXT.md) point 4 — "the one that kills deals."

**First served.** **P12** for a product. Pilot conversations are worth starting once coverage
metrics are real (P4).

#### P-08 · Fintech product manager

**Who they are.** At a Bamboo, Chaka, Trove, Cowrywise or Risevest. Lists Nigerian stocks in
an app and wants to show the financials behind them.

**Goal.** An embedded data API — a feature they would rather buy than build
([PROJECT_CONTEXT.md §9.2](../PROJECT_CONTEXT.md)).

**Painful status quo.** They either show no fundamentals or scrape something unreliable.

**Would abandon if.** No uptime record, no versioned API contract, or a breaking change
shipped without a deprecation window. This persona is the reason the public API is **versioned
from the first release** ([PROJECT_CONTEXT.md §9.4](../PROJECT_CONTEXT.md)).

**First served.** **P12**.

#### P-09 · Bank credit analyst

**Who they are.** Assessing a Nigerian corporate borrower.

**Goal.** Historical financials on that borrower, quickly, with something defensible in a
credit file.

**Painful status quo.** A manual research task per borrower
([PROJECT_CONTEXT.md §9.2](../PROJECT_CONTEXT.md)).

**Would abandon if.** The history is too shallow (a credit file needs years, not quarters) or
the figures cannot be tied back to the audited filing. Provenance is not a nice-to-have for
this persona; it is the deliverable.

**First served.** **P12**.

#### P-10 · Global data vendor partnerships lead

**Who they are.** At an LSEG/Refinitiv, FactSet, S&P, or a mid-tier vendor with an NGX
coverage gap.

**Goal.** Fill a coverage gap more cheaply than originating it themselves
([PROJECT_CONTEXT.md §9.2](../PROJECT_CONTEXT.md)).

**Painful status quo.** They do not cover NGX fundamentals meaningfully, and building the
capability is not worth it for one frontier market.

**Would abandon if.** The licensing chain is not clean, or coverage cannot be quoted precisely
— they need "N companies, M years, X% extraction accuracy"
([PROJECT_CONTEXT.md §9.4](../PROJECT_CONTEXT.md)) as a number, not an impression.

**First served.** Post-**P12**.

#### P-11 · Acquirer technical due-diligence lead

**Who they are.** Appears at most once, possibly never. Included because the properties they
check are cheap to design in early and expensive to retrofit
([PROJECT_CONTEXT.md §9.4](../PROJECT_CONTEXT.md)) — not because acquisition is the plan.

**Goal.** Answer four questions: is the dataset genuinely hard to replicate; is point-in-time
integrity real; are the identifiers stable and the API embedded in customer workflows; **do
you have the right to redistribute this data?**

**Would abandon if.** Any of the four fails. The fourth is the one that ends the conversation,
because "a dataset built by scraping sources whose terms prohibit redistribution is a lawsuit,
not an asset" ([PROJECT_CONTEXT.md §9.3](../PROJECT_CONTEXT.md)).

**First served.** Post-**P12**, if ever. See [§2.5](#25-the-honest-part) — this persona should
never drive a roadmap decision on their own.

---

### 1.6 Gatekeeper personas

#### P-16 · Nigerian securities & data-protection lawyer

**Who they are.** External counsel. Not a user of the software; a **gate** on it.

**Goal.** Confirm four things before a public launch: that the public tier's feature set stays
on the data/analytics side of ISA 2025; that redistribution rights exist for anything served
publicly (NGX and vendor terms); NDPC/DCPMI registration under the NDPA; and the licence path
for the advice tier ([DATA_FOUNDATION.md Recommendation 5](../DATA_FOUNDATION.md),
[OPERATIONS.md §3.4](../OPERATIONS.md)).

**Painful status quo.** The question has not been asked yet.

**What makes this persona urgent.** [TEAM_BRIEF.md §2.2-J](../TEAM_BRIEF.md) overrides the
"v2.0 gate" framing: "**Book this before you need it** — the answer on NGX redistribution
rights shapes the v2.0 architecture, and the SEC licence path has a long lead time. Finding
out late is the expensive version." This is why the legal-review story sits in **P4**, not
P12, even though it *blocks* P12.

**First served.** **P4** (engage), blocks **P12** (sign-off).

---

### 1.7 Anti-personas — who this is explicitly not for

Naming these prevents a whole class of scope creep, because each one has a plausible-sounding
request attached.

| Anti-persona | The request they will make | Why we say no |
|---|---|---|
| **The day trader** | Real-time NGX tick data and intraday charts | No real-time streaming at any version listed ([DATA_FOUNDATION.md §1.2](../DATA_FOUNDATION.md) non-goals). Intraday NGX data is not reliably available free, and the ±10% band plus the 100,000-share movement rule make intraday strategies especially unrealistic to backtest ([SPEC.md §2C](../SPEC.md)). |
| **The full-market screener** | "Cover all ~150 NGX companies" | [PROJECT_CONTEXT.md §8](../PROJECT_CONTEXT.md): most barely trade; breadth "multiplies extraction work while adding little value". Curate 15–25. |
| **The third-party client** | "Manage my money / tell me what to buy" | Managing third-party funds for a fee triggers SEC registration under ISA 2025, with a ₦5bn minimum capital requirement for full-scope fund managers ([SPEC.md §1.2, PART 5](../SPEC.md)). Off the table until licensed, and the ₦5bn threshold is a separate question from the licence itself. |
| **The crypto user** | "Add crypto" | Not in any version of the roadmap. Nothing in the data foundation, cost models, or compliance design contemplates it. |
| **The signal subscriber** | "Sell me the signals" | Exactly the licence-gated activity ([SPEC.md PART 5](../SPEC.md), monetization ladder: L2 signals, L3 memos and L4 execution-for-others are all off the table for a public product until licensed). |

---

## §2 — Business needs

### 2.1 Why this exists as a business and not only a tool

The honest sequence is: it is a personal tool **first**, and the business is what happens if
the tool turns out to be good. [PROJECT_CONTEXT.md §6](../PROJECT_CONTEXT.md) states the
trajectory as "A tool used daily → a tool the family relies on → **if it earns it**, the
missing structured database of Nigerian corporate finance, which is a business." The
conditional is load-bearing.

But there are three reasons to build it *as though* it were a business from day one, none of
which are "we might get rich":

1. **The properties that make it commercially valuable are the same properties that make it
   personally trustworthy.** Point-in-time integrity is what an institutional buyer pays a
   premium for ([PROJECT_CONTEXT.md §9.3](../PROJECT_CONTEXT.md)) *and* the only way to
   backtest your own money honestly ([SPEC.md §2C](../SPEC.md)). Provenance is a
   due-diligence answer *and* the reason you can trust a number at 2am. You are not adding
   enterprise features; you are refusing to cut corners that would hurt you first.
2. **Multi-user is cheap now and a rewrite later.** [CLAUDE.md](../CLAUDE.md) calls
   single-user "the expensive shortcut to avoid". A multi-user system with two users is a
   config change away from a hundred; a single-user system is a full rewrite.
3. **The restriction is on the audience, not the capability.**
   [PROJECT_CONTEXT.md §4](../PROJECT_CONTEXT.md): "Build it as if everyone will use it.
   Restrict who can log in, not what it can do." Nothing gets built twice.

### 2.2 The category and why the category matters

**This is not fintech.** It is **financial data infrastructure** — the market data and
financial information services category
([PROJECT_CONTEXT.md §9.1](../PROJECT_CONTEXT.md)). Global incumbents: Bloomberg,
LSEG/Refinitiv, FactSet, S&P Capital IQ, Moody's. Regional peers: African Financials, Stears,
Asoko Insight.

The distinction is not cosmetic — it changes what you optimise:

| | Fintech | Data infrastructure |
|---|---|---|
| Valued on | Users and transaction volume | Coverage, recurring revenue, workflow embeddedness |
| Growth motion | Acquire users fast | Deepen coverage, get embedded |
| Moat | Network effects, brand | A dataset that is expensive to replicate |
| What kills it | Churn | A licensing defect |

"A data business with 40 institutional clients can be worth more than a consumer app with
400,000 users, because the revenue is stickier and the asset is harder to replicate"
([PROJECT_CONTEXT.md §9.1](../PROJECT_CONTEXT.md)).

**The sub-niche stated precisely:** structured fundamental and macro data for a **frontier
market where it does not currently exist in machine-readable form.**

The practical consequence for this document: stories that deepen coverage and integrity
(P2–P4) outrank stories that add surface area, and when time is scarce, **the data layer has
priority** ([PROJECT_CONTEXT.md §10](../PROJECT_CONTEXT.md), rule 8) because it is the only
piece valuable independent of everything else.

### 2.3 The B2B thesis, buyer by buyer

Straight from [PROJECT_CONTEXT.md §9.2](../PROJECT_CONTEXT.md), with the story that serves
each attached:

| Buyer | What they need | Why buy rather than build | Served by |
|---|---|---|---|
| Nigerian brokers & asset managers | Company fundamentals for research and client reporting | Analysts re-key PDFs today; the API sells back analyst hours | US-116, US-118, US-120 |
| Fintechs (Bamboo, Chaka, Trove, Cowrywise, Risevest) | Show users the financials behind a listed stock | An embedded data API is a feature they would rather buy | US-118, US-119 |
| Banks & credit teams | Historical financials on corporate borrowers | Currently a manual research task per borrower | US-116, US-120 |
| Global data vendors | NGX fundamental coverage they lack | Cheaper to license than to originate | US-121, US-122 |
| Corporates | Peer benchmarking on standardized metrics | No standardized comparable set exists locally | US-120 |
| Media, researchers, universities | Reliable Nigerian financial data | No citable structured source today | US-116, US-120 |

The common thread: **all six want the data tier, not the advice tier.**
[PROJECT_CONTEXT.md §4](../PROJECT_CONTEXT.md) makes it explicit — the public data tier is
"a complete product on its own, and the one §9's B2B buyers actually want." That is
commercially convenient, because the data tier needs no SEC licence.

### 2.4 The four acquirability properties and which phase earns each

[PROJECT_CONTEXT.md §9.3](../PROJECT_CONTEXT.md) names four things that make a data company
acquirable. Below, each is mapped to the phase where it is actually *earned* — as opposed to
merely designed.

| # | Property | Designed in | **Earned in** | Why the gap |
|---|---|---|---|---|
| **1** | **A proprietary dataset expensive to replicate.** Five years of normalized NGX financials is not something a buyer spins up in a quarter. **This is the moat.** | P0 (schema) | **P4**, deepening through P12 | A schema is not a dataset. The moat exists when there are actual validated statements in it, and it widens every month the pipeline runs. |
| **2** | **Point-in-time integrity.** Versioned statements, provenance on every number (source document + page), as-of dates, restatement handling. "The single most enterprise-grade feature. Do not compromise it for speed." | **P0** (DDL) | **P3** | Earned the first time a restatement arrives and the old version survives, superseded rather than overwritten. Cannot be retrofitted: a table that overwrote for two years has lost the history permanently. |
| **3** | **API-first with stable identifiers.** Every company gets a permanent internal ID mapped to ticker, ISIN and CIK. If clients build against the API, switching costs get high. | **P0** | **P12** | The permanent ID is free in P0 and painful later ([OPERATIONS.md §1.4](../OPERATIONS.md) — GTBank became GTCO in 2021, so identity has history). Switching costs only exist once someone else has built against it. |
| **4** | **Clean licensing rights.** "The one that kills deals." | **P0** (the register) | **P12** (sign-off) | The per-source register costs minutes per source at ingestion time and is unreconstructable later — you cannot retroactively prove what a site's terms said in 2026. **This is gap G5: no task in T1–T21 enforces it.** |

Read that table as a warning about ordering: **properties 2, 3 and 4 are designed in P0 or
they are not real.** Property 1 is the only one that can be earned late, and it is earned by
grinding.

### 2.5 The honest part

**Acquisition is a poor primary goal.** [PROJECT_CONTEXT.md §9.5](../PROJECT_CONTEXT.md):
"Most companies aren't acquired, and building to be bought usually produces something nobody
wants. The reliable path is the opposite: build something people genuinely depend on and pay
for, and acquisition becomes one of several possible outcomes rather than the plan."

Three further facts that should be sitting in view whenever a story is justified by "a buyer
would want this":

- **The Nigerian institutional market is small** — "perhaps a few dozen serious accounts"
  (§9.5). Fine for a good business; probably not a large exit.
- **Buyers are price-sensitive.** Retail willingness-to-pay is around ₦5,000–₦15,000/month
  with strong free-tier expectations ([SPEC.md PART 5](../SPEC.md)).
- **The move that changes the picture is geographic, not featural.** Expanding coverage to
  Ghana, Kenya, Egypt and South Africa turns "Nigerian data company" into "African data
  company", and "the buyer list gets much more interesting" (§9.5). That is a coverage
  decision, not a product decision — which is another reason the extraction pipeline is the
  thing worth being good at.

And the conclusion PROJECT_CONTEXT reaches, which is also this document's default tiebreaker:
**"The thing that makes it acquirable is the same thing that makes it useful: a dataset nobody
else has, maintained reliably, with provenance you can defend. Build that, and the rest is
optional."**

The floor, from [TEAM_BRIEF.md PART 4](../TEAM_BRIEF.md), stated so it is impossible to
mistake this document for a pitch deck: *if the ML signals never clear the backtest gate, if
the public tier never monetises, if no acquirer ever calls — you still built the missing
structured database of Nigerian corporate finance, and you still replaced your own weekly
research routine with something better. That outcome is worth the work on its own. Everything
above it is upside.*

### 2.6 The monetization ladder and what is legally off the table

From [SPEC.md PART 5](../SPEC.md), unmodified in substance:

| Tier | What it is | Public, pre-licence? | Realistic price |
|---|---|---|---|
| **L1** | Dashboard + daily brief + data + basic ratios + macro | ✅ Yes | ~₦5,000–₦15,000/mo retail; expect strong free-tier expectations and price sensitivity |
| **L2** | Signals / API | API yes; **signals no** | Higher willingness-to-pay from professionals — but signals are exactly the licence-gated activity |
| **L3** | Recommendation memos | ❌ No | Licence-gated |
| **L4** | Execution for others | ❌ No | Licence-gated + capital requirements |

**Freemium shape:** free = data + basic ratios + macro brief (public mode); paid = deeper
history, exports, alerts, screening.

**What cannot be monetised without a licence:** anything constituting investment advice or
portfolio management for third parties triggers SEC Nigeria registration under ISA 2025 (and
the ₦5bn full-scope fund-manager capital rule). **Public mode monetizes data and tools;
personal mode keeps the advice for the owner and family.**

This is why the mode gate is architecture and not policy: the revenue-generating public
product and the advice-generating personal product are the same codebase with different
entitlements, and the only thing standing between them is code that has been tested to hold.

### 2.7 Business-need to story map

| Business need | Stories that serve it |
|---|---|
| Replace the owner's weekly research routine | US-017–US-025, US-026–US-034, US-060–US-069 |
| Build the moat (proprietary NG dataset) | US-035–US-047, US-048–US-059 |
| Point-in-time integrity (property 2) | US-005, US-006, US-041, US-042, US-078, US-079 |
| Stable identifiers, API-first (property 3) | US-003, US-004, US-044, US-118, US-119 |
| Clean licensing (property 4) | US-011, US-055, US-115, US-122 |
| Family shared visibility | US-093, US-096, US-098, US-100, US-103 |
| Quotable coverage metrics | US-056, US-057, US-120 |
| Public data product | US-115–US-124 |
| Personal trading edge (or an honest no) | US-078–US-092, US-111–US-114, US-125–US-130 |
| Not losing the asset | US-013, US-014, US-058 |

---

---

## §3 — Epics, one per phase

One epic per canonical phase. The **business outcome** is what changes in the world if the epic
lands — not what gets built, but what becomes possible.

| Epic | Phase | Business outcome |
|---|---|---|
| **E-00 Foundation & Rails** | P0 | The system can safely have more than one user, and cannot accidentally give advice to the wrong one. Nothing visible; everything after it is cheap. |
| **E-01 Macro Backdrop** | P1 | The owner stops assembling Nigerian macro context by hand from PDFs. |
| **E-02 US Company Data** | P2 | Any US-listed company can be analysed from primary filings in minutes, with every figure traceable. |
| **E-03 Nigerian Manual Analyzer** | P3 | Nigerian company financials become *structured data* for the first time — by hand, but correctly, with the correctness substrate underneath. |
| **E-04 Nigerian Automated Ingestion** | P4 | The moat. Nigerian PDFs become queryable data without a human typing them. |
| **E-05 News & Daily Brief** | P5 | The system reaches the owner rather than waiting to be visited. |
| **E-06 Scenarios & Indicators** | P6 | The owner's own assumptions drive valuations; price features exist for later modelling. |
| **E-07 Backtesting** | P7 | The owner can tell the difference between an edge and a story. |
| **E-08 ML Signals** | P8 | Calibrated probabilities, and a structural refusal to trade anything unproven. |
| **E-09 Memos & Web App** | P9 | Family use it unprompted; research arrives cited and two-sided. |
| **E-10 Portfolio & Alerts** | P10 | The owner knows what they hold, what it cost, what it is worth, and what tax it owes. |
| **E-11 Paper Trading** | P11 | Signals are tested against reality before capital. |
| **E-12 Public Beta** | P12 | Strangers can use it, and structurally cannot receive advice. |
| **E-13 Personal Execution** | P13 | Decisions become orders, behind a hard safety layer. |

---

## §4 — The user stories

Grouped by phase. Story IDs are permanent.

### P0 — Foundation & Rails

> #### US-001 · Server-derived mode
> `Persona` P-01 Owner · `Priority` Must · `Phase` P0 · `Task` T15 · `Risk` 🔴 FRAGILE
>
> **As** the Owner, **I want** the system to decide what a caller may see based on who they are
> authenticated as, **so that** no client can ever ask for advice it is not entitled to.
>
> **Acceptance criteria**
> - **Given** an anonymous request, **When** it reaches any endpoint, **Then** the resolved mode
>   is `public`.
> - **Given** a request supplying `mode=personal` in body, header, query **or** cookie, **When**
>   it is processed, **Then** the resolved mode is still `public`.
> - **Given** a principal without `entitlements.personal_tier`, **When** it calls `/personal/*`,
>   **Then** the response is HTTP 403.
>
> **Three approaches** (see [01_ARCHITECTURE.md](01_ARCHITECTURE.md) §3): global middleware
> (recommended, plus a test enumerating every route); a per-endpoint decorator (a forgotten one is
> undetectable); a per-router dependency (a router can still be mounted without it).
>
> **Decomposes into**
> - [ ] `resolve_principal` from credential
> - [ ] `resolve_mode` from entitlements + `licence_status`
> - [ ] Global middleware registration
> - [ ] Compliance test enumerating every registered route

> #### US-002 · Response-type assertion
> `Persona` P-01 · `Priority` Must · `Phase` P0 · `Task` T15 · `Risk` 🟢 SOLID
>
> **As** the Owner, **I want** a public response carrying a personal-mode payload to fail loudly,
> **so that** a refactor cannot leak advice silently.
>
> - **Given** public mode, **When** a handler returns a type outside the allow-list, **Then** the
>   request raises **HTTP 500** — our bug, not the caller's error.
> - **Given** a new advice-shaped type is added, **When** it is not added to the allow-list,
>   **Then** it is rejected by default.

> #### US-003 · Audit every request
> `Persona` P-01, P-16 Lawyer · `Priority` Must · `Phase` P0 · `Task` T15 · `Risk` 🟢 SOLID
>
> **As** the Owner, **I want** every request recorded with principal, mode, endpoint and response
> type, **so that** I can answer "who saw what, when" — the question a regulator asks and that
> cannot be answered retroactively.
>
> - **Given** any request including a failure, **When** it completes, **Then** an `audit_log` row
>   exists.

> #### US-004 · Multi-user from the first migration
> `Persona` P-01, P-02 Family · `Priority` Must · `Phase` P0 · `Task` — **no task owns this (TG3)**
> · `Risk` 🔴 FRAGILE
>
> **As** the Owner, **I want** every user-scoped table keyed by principal from day one, **so that**
> adding a second user is a row, not a rewrite.
>
> - **Given** the schema, **When** inspected, **Then** portfolios, watchlists, alerts, risk limits,
>   spend caps, scenarios and audit rows all carry a principal key.
> - **Given** a position-sizing function, **When** called, **Then** account equity is a
>   **parameter**, never a module constant.
>
> **Three approaches:** token table in Postgres now, hosted IdP at P9 (recommended); hosted IdP
> now (external dependency for two users who are both you); hardcoded single principal (the
> shortcut [CLAUDE.md](../CLAUDE.md) names as expensive).

> #### US-005 · Provenance columns exist before the first insert
> `Persona` P-01, P-14 Reviewer · `Priority` Must · `Phase` P0 · `Task` — **gap (TG2)** ·
> `Risk` 🟡 WATCH
>
> - **Given** any figure table, **When** inspected, **Then** `source_document_id` is `NOT NULL`
>   and `page`, `as_of_date`, `known_as_of`, `version` are present.
>
> *Early warning:* any provenance column you were tempted to make nullable to get a test passing.

> #### US-006 · A restore that has actually been performed
> `Persona` P-01 · `Priority` Must · `Phase` P0 · `Task` — **gap (TG4)** · `Risk` 🔴 FRAGILE
>
> **As** the Owner, **I want** to have restored from backup at least once, **so that** I know the
> backup is a backup and not merely a file.
>
> - **Given** a backup, **When** `restore.sh` runs, **Then** `quant_restore_test` has the same
>   table count as live, and the date is recorded.
>
> **Three approaches:** quarterly full drill + nightly automated dumps (recommended); automated
> restore-verification in CI against a scrubbed dump (stronger, more to build); rely on managed
> host backups from P9 (necessary but insufficient — covers nothing before P9, nor the object
> store).

> #### US-007 · A source cannot be ingested without stated redistribution rights
> `Persona` P-01, P-11 Acquirer DD, P-16 Lawyer · `Priority` Must · `Phase` P0 ·
> `Task` — **gap (TG5)** · `Risk` 🟡 WATCH
>
> - **Given** a connector whose `data_sources` row has `redistribution_allowed` unset, **When**
>   registration is attempted, **Then** it raises and the connector never runs.
>
> *Why:* [PROJECT_CONTEXT.md §9.3](../PROJECT_CONTEXT.md) — "the one that kills deals". One hour
> now; near-impossible to reconstruct after two years of ingestion.

> #### US-008 · Decisions are recorded as ADRs
> `Persona` P-17 Future maintainer · `Priority` Should · `Phase` P0 · `Risk` 🟢 SOLID
>
> - **Given** a non-obvious decision, **When** made, **Then** an ADR records context, decision,
>   consequences and rejected alternatives.

### P1 — Macro Backdrop

> #### US-010 · See Nigerian macro without opening a PDF
> `Persona` P-01 · `Priority` Must · `Phase` P1 · `Task` T1 · `Risk` 🟡 WATCH
>
> **As** the Owner, **I want** CPI, MPR, GDP, FX and debt on one screen, **so that** I stop
> assembling context by hand from government PDFs ([PROJECT_CONTEXT.md §2](../PROJECT_CONTEXT.md)).
>
> - **Given** the dashboard, **When** opened, **Then** each series shows value, **as-of date**, and
>   a source link.
> - **Given** a series past its `expected_lag_days`, **When** rendered, **Then** a **visible**
>   staleness flag appears — not subtle grey.
>
> *Early warning:* a connector returning 200 OK with zero rows.

> #### US-011 · Distinguish when a figure describes from when it was published
> `Persona` P-01 · `Priority` Must · `Phase` P1 · `Task` T1 · `Risk` 🔴 FRAGILE
>
> **As** the Owner, **I want** `as_of_date` and `known_as_of` stored separately, **so that** later
> backtests cannot use figures that were not yet public.
>
> - **Given** Nigerian CPI for August published mid-September, **When** stored, **Then**
>   `as_of_date` is August and `known_as_of` is the publication date.
>
> **Three approaches:** capture both at ingestion from source metadata where available — FRED's
> ALFRED gives it directly (recommended); infer publication dates from a release calendar
> (workable for scheduled series, wrong for irregular ones like MPC decisions); store only
> `as_of_date` and reconstruct later (**impossible** — the information is gone).

> #### US-012 · The dashboard works when a source is down
> `Persona` P-01 · `Priority` Should · `Phase` P1 · `Risk` 🟢 SOLID
>
> - **Given** no internet, **When** the dashboard loads, **Then** stored data renders with stale
>   flags rather than crashing.

> #### US-013 · Silent connector failure is detected
> `Persona` P-01 · `Priority` Must · `Phase` P1 · `Task` — **gap (TG8)** · `Risk` 🟡 WATCH
>
> - **Given** a connector returning 200 with no parsable rows, **When** the run completes, **Then**
>   `status='ok' AND rows_written=0` is **flagged**, not treated as success.

### P2 — US Company Data

> #### US-020 · Analyse a US company from primary filings
> `Persona` P-01 · `Priority` Must · `Phase` P2 · `Task` T2 · `Risk` 🟢 SOLID
>
> - **Given** a ticker, **When** requested, **Then** income statement, balance sheet and cash flow
>   render with every figure linked to its filing.

> #### US-021 · A missing line item stays missing
> `Persona` P-01, P-04 Analyst · `Priority` Must · `Phase` P2 · `Task` T2 · `Risk` 🔴 FRAGILE
>
> **As** an analyst, **I want** absent figures to be null, **so that** I am never shown a number
> the company did not report.
>
> - **Given** a filing lacking R&D expense, **When** ingested, **Then** `value IS NULL` — not `0`.
> - **Given** a ratio with a null input, **When** computed, **Then** it returns null — not `0`,
>   not infinity.
>
> **Three approaches:** null-safe arithmetic throughout plus a lint rule banning `fillna(0)` in
> the financial path (recommended); a sentinel value (invites arithmetic on it); permissive
> defaults for display (the failure this story exists to prevent).

> #### US-022 · Run a DCF on my own assumptions
> `Persona` P-01 · `Priority` Must · `Phase` P2 · `Task` T2 · `Risk` 🟢 SOLID
> 🔀 **MODE-SENSITIVE**
>
> - **Both modes — Given** growth, margin, WACC and terminal growth supplied by the user, **When**
>   the DCF runs, **Then** the output returns **alongside the assumptions that produced it**.
> - **Public mode — Then** no auto-generated price target and no verdict appear
>   ([DATA_FOUNDATION.md §1.4](../DATA_FOUNDATION.md)).
> - **Personal mode — Then** a fair-value range and recommendation **may** appear, still carrying
>   the assumption set ([CLAUDE.md](../CLAUDE.md): show the work in every mode).

> #### US-023 · Price history exists
> `Persona` P-01 · `Priority` Must · `Phase` P2 · `Task` — **no task owns this (TG1)** ·
> `Risk` 🟡 WATCH
>
> **As** the Owner, **I want** daily OHLCV stored with raw *and* adjusted closes, **so that** P6
> indicators and P7 backtests have inputs at all.
>
> - **Given** ingestion, **When** complete, **Then** `close_raw`, `close_adj` and `volume` are all
>   populated, and raw is never overwritten.
>
> *This story exists because no SPEC task creates `price_history`, while T9 and T11 both consume
> it.*

> #### US-024 · Point-in-time queries return what was known then
> `Persona` P-01 · `Priority` Must · `Phase` P2 · `Task` T2 · `Risk` 🔴 FRAGILE
>
> - **Given** a company that restated FY2024 revenue in September 2025, **When** queried as known
>   on 1 June 2025, **Then** the **original** figure is returned.
>
> **Three approaches:** mandatory-argument accessor + lint rule banning raw SQL in `ml`/`backtest`
> (recommended — forgetting the date is a `TypeError`); database views embedding the filter
> (strong, awkward to parameterise); convention and review (not a mechanism).

### P3 — Nigerian Manual Analyzer

> #### US-030 · Enter a Nigerian statement by hand, correctly
> `Persona` P-15 Data-entry analyst · `Priority` Must · `Phase` P3 · `Task` T3 · `Risk` 🟢 SOLID
>
> - **Given** an uploaded PDF, **When** entering figures, **Then** the page image shows beside the
>   fields and each saved figure records page and reviewer.

> #### US-031 · A split does not look like a crash
> `Persona` P-01 · `Priority` Must · `Phase` P3 · `Task` — **gap (TG2)** · `Risk` 🔴 FRAGILE
>
> **As** the Owner, **I want** corporate actions applied to price series, **so that** a 2-for-1
> split does not read as a 50% loss in every downstream calculation.
>
> - **Given** a security with a known split, **When** the adjusted series is plotted, **Then** it
>   is continuous across the ex-date while the raw series shows the mechanical cliff.
>
> **Three approaches:** build all six correctness tables in P3 before any price series is consumed
> (recommended); schema now and populate lazily (you must then track which securities are
> adjusted, and that check gets forgotten exactly once); defer to P6 (months of derived values to
> recompute, under pressure — this is how it gets skipped).

> #### US-032 · The golden test set exists
> `Persona` P-14 Reviewer, P-12 Curator · `Priority` Must · `Phase` P3 ·
> `Task` — **no task owns this (TG6)** · `Risk` 🔴 FRAGILE
>
> **As** the Reviewer, **I want** ≥10 hand-verified PDF→JSON pairs including ≥2 banks, **so that**
> P4's accuracy claim means something.
>
> - **Given** the golden set, **When** counted, **Then** ≥10 pairs exist, ≥2 are banks, and each
>   was checked by a second person.
> - **Given** a locked subset, **When** the extractor is tuned, **Then** the locked pairs are not
>   used for tuning.
>
> **Three approaches:** hold back a locked subset (recommended); grow the set continuously from
> reviewed filings (strong, but reviewer time is scarcest); rely on random production sampling
> instead (measures reality, cannot run in CI). *Recommendation: locked subset plus sampling.*
>
> *[TEAM_BRIEF.md §2.2-C](../TEAM_BRIEF.md) calls this "the highest leverage task in the
> project", and T4's acceptance criteria assume it already exists.*

> #### US-033 · Correct a figure without destroying history
> `Persona` P-14 Reviewer · `Priority` Must · `Phase` P3 · `Task` — **gap (TG10)** ·
> `Risk` 🟢 SOLID
>
> - **Given** a stored figure, **When** corrected, **Then** a new version is written with
>   `superseded_by`, author and reason, and the original remains queryable.

> #### US-034 · Nigerian units and currency are never guessed
> `Persona` P-01 · `Priority` Must · `Phase` P3 · `Task` — **gap (TG2)** · `Risk` 🔴 FRAGILE
>
> - **Given** a statement reported in thousands, **When** stored, **Then** `unit_multiplier` is
>   recorded and the base value is correct.
> - **Given** a 2023 Naira figure, **When** converted to USD, **Then** the 2023 rate is used.
>
> **Three approaches:** capture the multiplier at extraction and convert in exactly one function
> (recommended); post-hoc magnitude checks (catch gross errors, miss plausible ones); human review
> of every figure (does not scale). *USD/NGN moved ₦907.1 → ₦1,535 during 2024 — the wrong date is
> wrong by ~70%.*

> #### US-035 · A bank's statements do not break the schema
> `Persona` P-12 Curator · `Priority` Must · `Phase` P3 · `Task` — **gap (TG7)** ·
> `Risk` 🔴 FRAGILE
>
> - **Given** a bank's income statement, **When** normalized, **Then** "gross earnings" maps to
>   `gross_earnings` and **not** to `revenue`.
>
> **Three approaches:** parallel financial-institution chart of accounts before P4 (recommended);
> one chart with nullable bank fields (invites the silent category error above); exclude banks
> (indefensible — they are a large share of NGX capitalisation).

### P4 — Nigerian Automated Ingestion

> #### US-040 · Extraction without typing
> `Persona` P-01 · `Priority` Must · `Phase` P4 · `Task` T4 · `Risk` 🔴 FRAGILE
>
> - **Given** a Nigerian annual report, **When** the pipeline runs, **Then** line items are
>   extracted with page provenance and a confidence score.
> - **Given** the locked golden subset, **When** evaluated, **Then** accuracy meets the
>   pre-agreed threshold.
>
> **Three approaches:** hybrid pipeline + permanent human review + 15–25 companies (recommended,
> lifts ~60% → 90%+); buy EODHD and skip the pipeline (instant coverage, ongoing cost, no moat);
> narrow to 5–10 companies (accuracy rises, coverage becomes a P12 liability).
>
> *Budget 2–3× your estimate. [TEAM_BRIEF.md Part 3](../TEAM_BRIEF.md) calls this "the one that
> eats months".*

> #### US-041 · The extractor never invents a number
> `Persona` P-04 Analyst, P-01 · `Priority` Must · `Phase` P4 · `Task` T4 · `Risk` 🟡 WATCH
>
> - **Given** a line item absent from the source, **When** extracted, **Then** the value is null
>   and no plausible substitute appears.
> - **Given** an extraction, **When** validated, **Then** assets = liabilities + equity, cash flow
>   ties, and cross-year opening matches prior closing — or it is queued for review.
>
> *Early warning:* a figure that passes validation but fails a by-eye check against the PDF.

> #### US-042 · Low-confidence extractions reach a human
> `Persona` P-14 Reviewer · `Priority` Must · `Phase` P4 · `Task` T4 · `Risk` 🟡 WATCH
>
> - **Given** confidence below ~0.85 or any validation failure, **When** processing completes,
>   **Then** the extraction is queued for review, **prioritised by materiality**.
>
> *Early warning:* queue depth growing week over week.

> #### US-043 · Corrections make the extractor better
> `Persona` P-14 Reviewer · `Priority` Must · `Phase` P4 · `Task` T4 · `Risk` 🟡 WATCH
>
> - **Given** a reviewer correction, **When** stored, **Then** it is also retained as a few-shot
>   example, and the correction rate falls measurably over time.
>
> *Early warning — and this is the phase's exit signal:* **a flat correction rate means the
> feedback loop is broken and P4 has no end.**

> #### US-044 · FX losses are visible as their own line
> `Persona` P-04 Analyst · `Priority` Must · `Phase` P4 · `Task` T4 · `Risk` 🟢 SOLID
>
> - **Given** a post-float Nigerian statement, **When** normalized, **Then** net FX loss is stored
>   under its own canonical key and year-on-year comparisons carry a devaluation-distortion note.
>
> *MTN Nigeria FY2024: revenue up 36% to ₦3.36tn, and still a ₦400.44bn loss after ₦925.36bn of
> net FX losses ([DATA_FOUNDATION.md §3.3](../DATA_FOUNDATION.md)).*

> #### US-045 · Historical statements are never silently rewritten
> `Persona` P-04, P-11 Acquirer DD · `Priority` Must · `Phase` P4 · `Risk` 🟢 SOLID
>
> - **Given** a restated statement, **When** ingested, **Then** a new version is created and the
>   prior version is retained and marked superseded.

### P5 — News, Sentiment & Daily Brief

> #### US-050 · A brief arrives without my asking
> `Persona` P-01 · `Priority` Must · `Phase` P5 · `Task` T7 · `Risk` 🟢 SOLID
> 🔀 **MODE-SENSITIVE**
>
> - **Both — Given** a scheduled time, **When** it arrives, **Then** a brief with watchlist moves,
>   new filings, tagged news and macro releases is delivered, each figure carrying its as-of date.
> - **Public mode — Then** no fired signals and no recommendations appear.
> - **Personal mode — Then** fired signals may appear, each with its calibrated probability and
>   authorising backtest.

> #### US-051 · The same alert never arrives twice
> `Persona` P-01, P-02 · `Priority` Must · `Phase` P5 · `Task` T7 · `Risk` 🟡 WATCH
>
> - **Given** the brief job runs twice for the same window, **When** delivery is attempted,
>   **Then** exactly one message is sent, deduped by content hash.
>
> *Early warning:* any repeat at all. A bot that repeats gets muted, and a muted bot delivers
> nothing.

> #### US-052 · News is tagged to the right company
> `Persona` P-01 · `Priority` Must · `Phase` P5 · `Task` T5 · `Risk` 🟡 WATCH
>
> - **Given** an article mentioning "GTBank", "Guaranty Trust" or "GTCO", **When** tagged, **Then**
>   all three resolve to the same `security_id`.
> - **Given** an article about a similarly-named **unlisted** company, **When** tagged, **Then** it
>   is **not** attached to a listed security.
>
> *Early warning:* any tag you would not have made yourself. False positives destroy trust faster
> than missed tags.

> #### US-053 · Each principal gets their own brief
> `Persona` P-02 Family · `Priority` Must · `Phase` P5 · `Task` T7 · `Risk` 🟢 SOLID
>
> - **Given** two principals with different watchlists, **When** briefs are generated, **Then**
>   the content differs accordingly.

### P6 — Scenarios & Indicators

> #### US-060 · Save and compare named scenarios
> `Persona` P-01 · `Priority` Must · `Phase` P6 · `Task` T8 · `Risk` 🟢 SOLID
>
> - **Given** an assumption set saved as "bear", **When** reopened, **Then** it reproduces
>   identical output, and scenarios are scoped per principal.

> #### US-061 · Indicators computed on adjusted prices
> `Persona` P-01 · `Priority` Must · `Phase` P6 · `Task` T9 · `Risk` 🔴 FRAGILE
>
> - **Given** a security with a known split, **When** RSI is plotted across the ex-date, **Then**
>   it is continuous — no artificial spike.
> - **Given** RSI-14 and RSI-21, **When** both are stored, **Then** `param_hash` keeps them
>   distinct and neither overwrites the other.
>
> **Three approaches:** compute exclusively from `close_adj` with a lint rule against `close_raw`
> in `/packages/indicators` (recommended); compute from raw and adjust afterwards (double
> adjustment risk); compute from raw and ignore actions (**the silent corruption this story
> exists to prevent**).

> #### US-062 · No signals yet
> `Persona` P-01 · `Priority` Must · `Phase` P6 · `Task` T9 · `Risk` 🔴 FRAGILE
>
> **As** the Owner, **I want** indicators to remain features and never become signals, **so that**
> I do not start trading on the exact data-snooped rules the literature says do not work.
>
> - **Given** the indicator package, **When** inspected, **Then** nothing emits a buy or sell
>   recommendation.
>
> **Three approaches:** structural — no signal type exists until P8 (recommended); a config flag
> disabling signals (a flag can be flipped at 1am); discipline alone (not a mechanism).
>
> *Park & Irwin: 56 of 95 studies positive, nearly all contaminated by data snooping
> ([SPEC.md §2C](../SPEC.md)). Indicators are features for a validated model, never standalone
> signals.*

### P7 — Backtesting

> #### US-070 · A backtester that reports the truth on known data
> `Persona` P-01 · `Priority` Must · `Phase` P7 · `Task` T11 · `Risk` 🔴 FRAGILE
>
> - **Given** a synthetic series engineered to return 20% at Sharpe 1.33, **When** backtested,
>   **Then** those numbers are reported within tolerance.
> - **Given** a pure random walk, **When** backtested with the NGX cost model, **Then** it reports
>   **~zero edge**, and DSR < 0.5.
>
> **Three approaches:** roll your own + mandatory synthetic tests (recommended,
> [SPEC.md §2C](../SPEC.md)); cross-validate against `vectorbt` with costs disabled (catches blind
> spots — do this once before capital); use an off-the-shelf engine (inherits fill semantics wrong
> for the NGX — no engine models a ±10% halt).
>
> *If a random walk shows an edge, every other result is void.*

> #### US-071 · The real cost of an NGX trade
> `Persona` P-01 · `Priority` Must · `Phase` P7 · `Task` T10 · `Risk` 🔴 FRAGILE
>
> - **Given** a round trip, **When** costed, **Then** brokerage, SEC, NGX, CSCS, stamp duty, VAT
>   **on fees not principal**, and the flat ₦4–6 alert fee are itemised separately.
> - **Given** a real contract note, **When** reconciled, **Then** the model reproduces it **to the
>   naira**.
> - **Given** a typical trade, **When** costed, **Then** break-even lands near the ~4.5% figure.
>
> **Three approaches:** reconcile against your own broker's contract note (recommended, ~2 hours);
> use published rate cards (ranges vary by broker; yours is what matters); add a conservative
> buffer (hides the error rather than fixing it).

> #### US-072 · Fills that could not have happened do not happen
> `Persona` P-01 · `Priority` Must · `Phase` P7 · `Task` T11 · `Risk` 🔴 FRAGILE
>
> - **Given** a stock at the ±10% band, **When** a fill is attempted, **Then** it is refused — the
>   NGX **halts**, it does not pause and resume.
> - **Given** daily volume below the movement threshold, **When** simulated, **Then** no price move
>   is modelled.
> - **Given** an order above the participation cap, **Then** the fill is capped.
> - **Given** T+3 settlement, **Then** proceeds are unavailable to redeploy for three trading days.
>
> **Three approaches:** encode all four rules in the cost model with dated config (recommended —
> the movement rule already changed and was postponed once in 2026); model only the band (leaves
> three known distortions); assume close-price fills (**fictional** on a market where many stocks
> barely trade).

> #### US-073 · Know whether I found an edge or got lucky
> `Persona` P-01 · `Priority` Must · `Phase` P7 · `Task` T11 · `Risk` 🔴 FRAGILE
>
> - **Given** a completed run, **When** reported, **Then** DSR is present with the honest trial
>   count K, and CPCV gives a **distribution** across paths rather than one number.
>
> **Three approaches:** honest K + DSR + a one-touch holdout (recommended); CPCV for path
> distribution (adopt alongside, not instead); pre-registering hypotheses before testing
> (strongest, hardest solo).
>
> *A nominal Sharpe of 2.0 can deflate to DSR 0.30; a Sharpe of 1.0 with few trials can hold at
> 0.85 ([SPEC.md §2C](../SPEC.md)).*

### P8 — ML Signals

> #### US-080 · Probabilities that mean what they say
> `Persona` P-01 · `Priority` Must · `Phase` P8 · `Task` T12 · `Risk` 🔴 FRAGILE
>
> - **Given** a calibrated model, **When** Brier is compared, **Then** calibrated beats
>   uncalibrated.
> - **Given** the 0.6 bucket on a reliability diagram, **When** inspected, **Then** roughly 60% of
>   those cases resolved favourably.
>
> **Three approaches:** `CalibratedClassifierCV` comparing sigmoid vs isotonic by Brier
> (recommended, [SPEC.md §2B](../SPEC.md)); sigmoid only (less data-hungry, assumes a distortion
> shape); raw scores presented as confidence (**the fake "confidence: 72" this story replaces**).
>
> *Kelly sizing takes a probability as input — miscalibration over-bets systematically.*

> #### US-081 · No signal without a passing backtest
> `Persona` P-01 · `Priority` Must · `Phase` P8 · `Task` T13 · `Risk` 🟢 SOLID
>
> - **Given** a `backtest_run` that failed the gate, **When** a signal referencing it is inserted,
>   **Then** the **database** raises.
> - **Given** any signal, **When** returned, **Then** it carries `calibrated_prob`, model version,
>   `backtest_run_id`, and the feature values with their as-of dates.

> #### US-082 · Signals are personal-mode only
> `Persona` P-01, P-16 Lawyer · `Priority` Must · `Phase` P8 · `Task` T13 · `Risk` 🟢 SOLID
> 🔀 **MODE-SENSITIVE**
>
> - **Public mode — Given** any request, **When** signals are sought, **Then** no endpoint exists
>   and the compliance suite proves it.
> - **Personal mode — Then** signals are served with full provenance.

### P9 — Memos & Web App

> #### US-090 · Research that argues both sides, with citations
> `Persona` P-01, P-02, P-04 · `Priority` Must · `Phase` P9 · `Task` T14 · `Risk` 🔴 FRAGILE
> 🔀 **MODE-SENSITIVE**
>
> - **Both — Given** a memo, **When** generated, **Then** every numeric claim carries a
>   `document_id` and page, and uncited claims are stripped before output.
> - **Both — Then** bull and bear were produced **independently**, without shared context.
> - **Public mode — Then** `verdict` is null; the memo ends with "what to verify".
> - **Personal mode — Then** a recommendation and position sizing may appear, with the work shown.
>
> **Three approaches:** LangGraph for the production pipeline with checkpointing and HITL
> (recommended for auditability, [SPEC.md §2E](../SPEC.md)); CrewAI throughout (fastest to
> prototype, weaker observability); a single-model memo (loses the adversarial structure that
> makes it worth reading).

> #### US-091 · Family log in and it is worth their while
> `Persona` P-02 Family · `Priority` Must · `Phase` P9 · `Task` T16 · `Risk` 🟡 WATCH
>
> - **Given** a family member on a phone, **When** they log in, **Then** they see their own
>   portfolio, watchlist and briefs — not the owner's.
>
> *Early warning — this is the v1.0 stage gate ([TEAM_BRIEF.md Part 4](../TEAM_BRIEF.md)):* if
> nobody logs in **unprompted**, the phase has not landed regardless of what shipped.

> #### US-092 · LLM spend cannot run away
> `Persona` P-01 · `Priority` Must · `Phase` P9 · `Task` T14 · `Risk` 🟡 WATCH
>
> - **Given** an identical input bundle, **When** a memo is requested again, **Then** it is served
>   from the content-hash cache with no new charge.
> - **Given** the monthly cap is reached, **When** generation is attempted, **Then** it **halts**
>   rather than degrading silently.
>
> *Early warning:* cost per memo not falling as the cache warms.

### P10 — Portfolio & Alerts

> #### US-100 · Know what I actually hold
> `Persona` P-01, P-02 · `Priority` Must · `Phase` P10 · `Task` T17 · `Risk` 🟢 SOLID
>
> - **Given** transactions, **When** positions are computed, **Then** quantity, weighted-average
>   cost basis, realised and unrealised P&L are correct.
> - **Given** a 2-for-1 split, **When** applied, **Then** quantity doubles, basis halves, and total
>   value is unchanged.

> #### US-101 · Know what tax I owe
> `Persona` P-01, P-02 · `Priority` Must · `Phase` P10 · `Task` T17 · `Risk` 🔴 FRAGILE
>
> - **Given** dividends received, **When** recorded, **Then** 10% withholding tax is applied and
>   gross and net are both stored.
> - **Given** rolling 12-month proceeds crossing **₦150,000,000**, or gains crossing
>   **₦10,000,000**, **When** evaluated **per principal**, **Then** the CGT exemption flag is
>   raised.
>
> **Three approaches:** dated configuration for every threshold with a quarterly regulatory review
> (recommended — CGT changed in January 2026 and thresholds moved from ₦100m to ₦150m); hardcoded
> constants (silently wrong after the next change); defer tax entirely (real money, and the
> rolling window cannot be reconstructed later without lot-level history).

> #### US-102 · Alerts that fire once and matter
> `Persona` P-01 · `Priority` Must · `Phase` P10 · `Task` T18 · `Risk` 🟡 WATCH
>
> - **Given** any alert type, **When** its condition recurs within the dedupe window, **Then**
>   exactly one delivery occurs.
> - **Given** a risk-limit breach, **When** detected, **Then** it is evaluated against **that
>   principal's** limits.

### P11 — Paper Trading

> #### US-110 · Test signals without money
> `Persona` P-01 · `Priority` Must · `Phase` P11 · `Task` T19 · `Risk` 🔴 FRAGILE
>
> - **Given** the paper trader, **When** inspected, **Then** it **imports the same cost-model
>   class** as the backtester — verified by import identity, not by reading the code.
> - **Given** a month of paper trading, **When** compared with backtest expectation, **Then** any
>   material divergence blocks P13.
>
> **Three approaches:** shared cost-model instance plus an import-identity test (recommended,
> closes TG15); a shared config file with two implementations (drift is invisible until it
> matters); reimplement for the paper trader (**guarantees** the divergence you are testing for).

### P12 — Public Beta

> #### US-120 · Strangers can use it and cannot receive advice
> `Persona` P-03, P-04, P-05, P-16 · `Priority` Must · `Phase` P12 · `Task` T20 · `Risk` 🔴 FRAGILE
>
> - **Given** every registered route, **When** enumerated, **Then** each is covered by the mode
>   gate and asserted so by test.
> - **Given** an anonymous user attempting every known injection vector, **When** tried, **Then**
>   the resolved mode is always `public`.
> - **Given** `licence_status` unset, **When** any public request is served, **Then** no advice-
>   shaped payload can be returned by construction.
>
> **Three approaches:** all five enforcement mechanisms plus an exhaustive route-coverage test
> (recommended — this is the architecture); add a P12 kill switch disabling advice code paths
> entirely (strong belt-and-braces, adopt alongside); separate deployments per mode
> ([CLAUDE.md](../CLAUDE.md) explicitly forbids two codebases).

> #### US-121 · Only data we may redistribute is served
> `Persona` P-16 Lawyer, P-11 Acquirer DD · `Priority` Must · `Phase` P12 ·
> `Task` — **gap (TG5)** · `Risk` 🔴 FRAGILE
>
> - **Given** any publicly served figure, **When** traced, **Then** its source has
>   `redistribution_allowed = true`, **or** the output is derived analytics rather than a raw feed.
>
> **Three approaches:** derived-analytics-only public tier (recommended, safe default); license
> redistribution from NGX or a vendor (the answer if raw feeds are required); serve with permitted
> delay and attribution (viable where the source allows it).
>
> *NGX market data is governed by a Data Agreement restricting redistribution
> ([DATA_FOUNDATION.md §6.3](../DATA_FOUNDATION.md)).*

> #### US-122 · Personal data is handled lawfully
> `Persona` P-03, P-16 · `Priority` Must · `Phase` P12 · `Task` T20 · `Risk` 🟡 WATCH
>
> - **Given** a data subject, **When** they request access or erasure, **Then** both work end to
>   end.
> - **Given** processing exceeds **200 data subjects in six months**, **When** evaluated, **Then**
>   DCPMI registration and a DPO are in place.
>
> *Fines up to 2% of annual gross revenue or ₦10 million, whichever is greater
> ([DATA_FOUNDATION.md §6.2](../DATA_FOUNDATION.md)). Early warning: user count approaching 200.*

### P13 — Personal Execution

> #### US-130 · Nothing trades that has not passed every check
> `Persona` P-01 · `Priority` Must · `Phase` P13 · `Task` T21 · `Risk` 🔴 FRAGILE
>
> - **Given** each pre-trade assertion violated **individually**, **When** an order is attempted,
>   **Then** each one independently blocks it.
> - **Given** orders in flight, **When** the kill switch is used, **Then** everything halts within
>   seconds.
> - **Given** personal mode, **When** any order is ready, **Then** explicit human confirmation is
>   required.
>
> **Three approaches:** test every assertion by deliberate violation, fail-closed defaults, and
> mandatory human confirmation — **adopt all three**. This is the only place in the project where
> a bug moves money.

> #### US-131 · An NGX order I can actually place
> `Persona` P-01 · `Priority` Must · `Phase` P13 · `Task` T21 · `Risk` 🟡 WATCH
>
> - **Given** an approved decision, **When** a ticket is generated, **Then** it carries security,
>   side, quantity, limit price, rationale and the risk checks passed.
> - **Given** a fill confirmed by hand, **When** entered, **Then** positions and P&L update.
>
> *No mainstream Nigerian retail broker exposes a self-service order API
> ([SPEC.md §2I](../SPEC.md)) — the manual ticket is a necessity, not a preference.*

---

## §5 — Mode-sensitive stories, collected

The stories whose acceptance criteria **differ by mode**. These are where the legal line lives, and
each must be tested twice.

| Story | Public mode | Personal mode |
|---|---|---|
| **US-022** DCF | No auto price target, no verdict | Fair-value range and recommendation permitted |
| **US-050** Daily brief | No signals, no recommendations | Fired signals with calibrated probability |
| **US-082** Signals | Endpoint does not exist | Served with full provenance |
| **US-090** Memos | `verdict: null`; ends with "what to verify" | Recommendation and sizing added |
| **US-120** Public access | Advice structurally impossible | N/A |

**The rule that governs all five** ([CLAUDE.md](../CLAUDE.md)): today the system **may** say
BUY/SELL and output price targets in personal mode — it is the owner's own capital. **Do not add
public-facing disclaimers or strip advice features from personal mode** on the assumption this is
a regulated product. It is not. The gate is `entitlements` plus `licence_status`, and opening the
advice tier to the public one day should be a config and disclosure change, never a rewrite.

---

## §6 — Non-goals per version

What we are explicitly **not** building at each stage, so scope creep is visible the moment it
happens ([DATA_FOUNDATION.md §1.3](../DATA_FOUNDATION.md)).

| Phase | Explicitly NOT building |
|---|---|
| **P0** | Any user-facing feature. No dashboard, no data. Rails only. |
| **P1** | Nigerian company data; forecasts; any recommendation |
| **P2** | Nigerian companies; automated extraction; any signal |
| **P3** | Automated extraction; real-time prices; a public surface |
| **P4** | 100% automation — human review is permanent by design, not a stopgap; >25 companies |
| **P5** | Sentiment as a tradeable signal; paid news APIs for Nigerian coverage |
| **P6** | **Any trading signal.** Indicators are features only. |
| **P7** | Live trading; ML models; optimising toward a target Sharpe |
| **P8** | Trading real capital; uncalibrated confidence numbers; autonomous decisions |
| **P9** | Public access; advice to anyone outside the family; a mobile app |
| **P10** | Tax filing or tax advice — flagging thresholds is not advising on them |
| **P11** | Real capital; broker integration |
| **P12** | **Any advice to public users**; raw redistribution of licensed feeds; discretionary management of anyone's money |
| **P13** | Autonomous NGX execution (no API exists); autonomous US execution by default (human-confirm); managing others' funds |

---

## §7 — Expected results and outcomes

What is observably different if each phase worked. Grounded in
[TEAM_BRIEF.md PART 4](../TEAM_BRIEF.md)'s stage gates.

| Phase | Observable change in behaviour |
|---|---|
| **P0** | Nothing visible. You can add a second user without fear. |
| **P1** | You stop opening NBS and CBN PDFs to answer a macro question. |
| **P2** | You analyse a US company in minutes instead of an afternoon in a spreadsheet. |
| **P3** | Nigerian financials are queryable for the first time — and you trust them, because you typed them. |
| **P4** | **The moat exists.** New filings become data without you typing. |
| **P5** | You read the brief every morning. If you stop, the phase failed. |
| **P6** | You test a valuation intuition by changing an assumption instead of rebuilding a model. |
| **P7** | You can say "this strategy has no edge net of costs" **with evidence** — and that is a success. |
| **P8** | You have a probability you can size a position on, or an honest answer that you do not. |
| **P9** | **Family members log in unprompted** — the v1.0 gate. |
| **P10** | You know your position and tax exposure without a spreadsheet. |
| **P11** | You know whether the backtest resembles reality, before it costs anything. |
| **P12** | Strangers use it, and cannot get advice. |
| **P13** | Decisions become orders, behind checks you have deliberately tried to break. |

**The honest floor** ([TEAM_BRIEF.md §234](../TEAM_BRIEF.md)): even if signals never clear the
gate, even if the public product never launches — **a clean, provenance-tracked dataset of
Nigerian company financials is a real asset that did not exist before, and it is useful the day it
exists.** That floor is reachable by P4, and it is high enough to justify starting.

---

## §8 — Traceability matrices

### Story → phase → task

| Phase | Stories | SPEC tasks | Gap-covered stories |
|---|---|---|---|
| P0 | US-001…008 | T15 | US-004 (TG3), US-005 (TG2), US-006 (TG4), US-007 (TG5) |
| P1 | US-010…013 | T1 | US-013 (TG8) |
| P2 | US-020…024 | T2 | US-023 (TG1) |
| P3 | US-030…035 | T3 | US-031 (TG2), US-032 (TG6), US-033 (TG10), US-034 (TG2), US-035 (TG7) |
| P4 | US-040…045 | T4 | — |
| P5 | US-050…053 | T5, T6, T7 | — |
| P6 | US-060…062 | T8, T9 | — |
| P7 | US-070…073 | T10, T11 | — |
| P8 | US-080…082 | T12, T13 | — |
| P9 | US-090…092 | T14, T16 | — |
| P10 | US-100…102 | T17, T18 | — |
| P11 | US-110 | T19 | US-110 (TG15) |
| P12 | US-120…122 | T20 | US-121 (TG5) |
| P13 | US-130…131 | T21 | — |

### Business need → stories

| Business need | Stories |
|---|---|
| Nigerian data nobody else has (the moat) | US-030–035, US-040–045 |
| Trustworthy figures (provenance, corrections) | US-005, US-021, US-033, US-041, US-045 |
| Personal trading edge — or an honest no | US-070–073, US-080–082, US-110, US-130–131 |
| Family adoption | US-053, US-091, US-100 |
| Legal safety pre-licence | US-001–003, US-082, US-090, US-120–122 |
| Not losing the asset | US-006, US-007, US-121 |
| B2B / acquisition readiness | US-007, US-045, US-121 |

---

## §9 — Gaps that leave stories undeliverable

Eleven stories depend on work that **no SPEC task schedules**. Each is marked in its block above
and cross-referenced to [06_RISK_REGISTER.md](06_RISK_REGISTER.md) §5.

| Story | Gap | Without it |
|---|---|---|
| US-004 | **TG3** auth/identity | Multi-user is impossible; mode has no principal to derive from |
| US-005, US-031, US-034 | **TG2** correctness substrate | Silent corruption of every price-derived value |
| US-006 | **TG4** backup/DR | The one unrecoverable failure |
| US-007, US-121 | **TG5** licensing register | [PROJECT_CONTEXT.md §9.3](../PROJECT_CONTEXT.md)'s deal-killer |
| US-013 | **TG8** scheduler + health | Connectors fail silently |
| US-023 | **TG1** price history | P6 and P7 cannot start |
| US-032 | **TG6** golden set | P4's accuracy claim is unfalsifiable |
| US-033 | **TG10** manual override | Corrections destroy history |
| US-035 | **TG7** chart of accounts | Banks force a re-extraction |
| US-110 | **TG15** shared cost model | Paper and backtest drift, discovered with money |

**US-040's threshold is TG13** — T4 says "≥ threshold" and no document sets the number. Until it is
written down, US-040 cannot pass or fail. **Set it before P4 starts.**

---

## §10 — What I left for other documents

| Topic | Where it lives |
|---|---|
| How each story is built, step by step | [03](03_ROADMAP_PART1_PHASES_0-6.md) / [04](04_ROADMAP_PART2_PHASES_7-13.md) |
| The exact test for each acceptance criterion | [07_TEST_STRATEGY.md](07_TEST_STRATEGY.md) |
| Table and endpoint shapes behind each story | [08_DATA_CONTRACTS.md](08_DATA_CONTRACTS.md) |
| Full risk treatment and decision gates | [06_RISK_REGISTER.md](06_RISK_REGISTER.md) |
| Why the system is shaped this way | [01_ARCHITECTURE.md](01_ARCHITECTURE.md) |
| Any unfamiliar term | [09_GLOSSARY.md](09_GLOSSARY.md) |

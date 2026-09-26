# 03 — Roadmap Part 1: Phases 0 through 6

**What this document is for.** This is the build plan for the first seven phases of the
project — from an empty folder to a working local system that holds Nigerian and US financial
statements, macro series, news, daily briefs, user-driven valuation scenarios, and technical
indicators. It exists so you never have to start a work session by asking "what am I building
and how will I know it worked?" Every phase below tells you what must already be true before
you start, what human work must happen alongside the code, exactly what to build, the literal
data going in and coming out, **the specific tests you run to prove it works — including ones
you check by eye**, and the honest assessment of what is likely to go wrong. Phases 7 through
13 live in [04_ROADMAP_PART2_PHASES_7-13.md](04_ROADMAP_PART2_PHASES_7-13.md).

> **Nothing in this project has been built yet.** As of this writing the repository contains
> six markdown planning documents, an empty `package.json`, and a `node_modules/` folder.
> There is no git repository, no Python, no database, and no code. Everything below is
> forward-looking. If a command in this document does not run, that is because the phase that
> creates it has not happened yet — not because something broke.

---

## Table of contents

- [How to use this document](#how-to-use-this-document)
- [The repeating phase structure](#the-repeating-phase-structure)
- [Markers: SOLID / WATCH / FRAGILE](#markers-solid--watch--fragile)
- [Gap index — the holes in the source spec](#gap-index--the-holes-in-the-source-spec)
- [Threads that run through every phase](#threads-that-run-through-every-phase)
- [The manual-work calendar](#the-manual-work-calendar)
- [Phase map for this document](#phase-map-for-this-document)
- [**P0 — Foundation & Rails**](#p0--foundation--rails-pre-v01)
- [**P1 — Macro Backdrop (v0.1)**](#p1--macro-backdrop-v01)
- [**P2 — US Company Data (v0.2)**](#p2--us-company-data-v02)
- [**P3 — Nigerian Manual Analyzer (v0.3)**](#p3--nigerian-manual-analyzer-v03)
- [**P4 — Nigerian Automated Ingestion (v0.4)**](#p4--nigerian-automated-ingestion-v04)
- [**P5 — News, Sentiment & Daily Brief (v0.5)**](#p5--news-sentiment--daily-brief-v05)
- [**P6 — Scenarios & Indicators (v0.6–v0.7)**](#p6--scenarios--indicators-v06v07)
- [Handoff to Part 2](#handoff-to-part-2)

---

## How to use this document

Read the phase you are about to start, in full, before writing a line of code. Read its
**Entry criteria** first — if any box is unticked, you are starting the wrong phase.

When you hand a task to a coding agent, give it: `SPEC.md` (for the invariants in §4.1), this
document's section for that one task, and nothing else. Context hygiene is a real constraint
([SPEC.md 4.5](../SPEC.md)) — an agent that has read everything makes worse decisions than an
agent that has read the right thing.

Sibling documents, and what to go to them for:

| Go here | For |
|---|---|
| [01_ARCHITECTURE.md](01_ARCHITECTURE.md) | How the layers fit together, the mode gate, provenance and point-in-time design |
| [02_INFRASTRUCTURE.md](02_INFRASTRUCTURE.md) | Hosting, database specifics, secrets, CI/CD, backup mechanics, cost |
| [04_ROADMAP_PART2_PHASES_7-13.md](04_ROADMAP_PART2_PHASES_7-13.md) | Backtesting, ML signals, memos, the hosted app, portfolio, execution |
| [05_USER_STORIES.md](05_USER_STORIES.md) | Who each feature is for and what outcome it produces |
| [06_RISK_REGISTER.md](06_RISK_REGISTER.md) | The consolidated risk list with mitigations and early-warning signals |
| [07_TEST_STRATEGY.md](07_TEST_STRATEGY.md) | The testing *framework* — fixtures, layout, CI wiring, how the test types differ |
| [08_DATA_CONTRACTS.md](08_DATA_CONTRACTS.md) | The authoritative field-by-field schemas and API contracts |
| [09_GLOSSARY.md](09_GLOSSARY.md) | Any term you have forgotten |

The per-phase **TEST CHECKPOINT** sections here overlap in spirit with
[07_TEST_STRATEGY.md](07_TEST_STRATEGY.md). That document owns *how testing works*; this one
owns *what each phase must prove*. If they disagree on a mechanism, follow 07. If they
disagree on what a phase must prove, follow this document.

---

## The repeating phase structure

Every phase below uses the same headings, in the same order, so you can navigate by muscle
memory:

1. **Phase header** — number, name, spec version, the tasks it contains
2. **In one sentence** — what exists at the end that did not exist at the start
3. **Why this phase is here now** — what it unblocks, and why it is not earlier or later
4. **Entry criteria** — what must already be true
5. **Manual work required first** — the human tasks, who does them, effort, blocking or parallel
6. **The build, task by task** — plain-words description, files touched, concrete steps, decisions to make inside the task
7. **Expected inputs** — literal URLs, formats, and a real sample record
8. **Expected outputs** — literal table rows, API response shapes, what appears on screen
9. **TEST CHECKPOINT** — numbered verifications, exact commands, exact expected results, including checks you do by eye
10. **Exit criteria / definition of done** — an unambiguous checklist
11. **What could go wrong** and **what you will be tempted to skip** — risks, and the compounding cost of each shortcut

---

## Markers: SOLID / WATCH / FRAGILE

Every risk and every design decision in this document carries one of three markers. They mean
exactly this, and nothing softer:

| Marker | Meaning | What you do about it |
|---|---|---|
| 🟢 **SOLID** | Well understood, low variance, proven approach. If it fails, the failure is loud and cheap to fix. | Nothing. Stop worrying about this one. |
| 🟡 **WATCH** | It will work, but it has a known failure mode, a cost curve, or a dependency that can move under you. | Note the early-warning signal given with it, and check that signal periodically. |
| 🔴 **FRAGILE** | Genuinely likely to go wrong, or the effort estimate could be wrong by multiples. | Read the **three approaches** given with it before committing. Every FRAGILE item in this document carries three, with a recommendation. |

A document where everything is green would be useless. The ratings below are grounded in the
honest assessments the source documents already made — [DATA_FOUNDATION.md 8.2](../DATA_FOUNDATION.md)
("Top 10 things most likely to go wrong"), [DATA_FOUNDATION.md 8.3](../DATA_FOUNDATION.md)
("Where estimates are most wrong"), [SPEC.md PART 6](../SPEC.md) ("Top risks", "The honest
verdict"), and [TEAM_BRIEF.md PART 3](../TEAM_BRIEF.md) ("The big five"). Where this document
rates something, it extends those assessments rather than contradicting them.

---

## Gap index — the holes in the source spec

The source documents are good, but their task list ([SPEC.md 4.2](../SPEC.md), tasks T1–T21)
has holes. Work that nobody scheduled does not get done. Each gap below is given a **task ID**
so it can be assigned, tracked, and argued about like any other task. The `TG` prefix means
"task, gap-filling" — it keeps them distinct from SPEC's T-numbers and from DATA_FOUNDATION's
separate T-numbering, which also runs T1–T16 and which
[DATA_FOUNDATION.md 7.4](../DATA_FOUNDATION.md) itself flags as a collision risk.

| ID | Gap | Where it lands | Severity |
|---|---|---|---|
| **TG1** | **Price history ingestion has no T-number.** T9 computes indicators on `price_history` and T11 backtests on OHLCV bars, but no SPEC task fills that table. DATA_FOUNDATION's own T8 (`AfxKwayisiConnector`) covers it; SPEC's T1–T21 dropped it. | US half in **P2**; NGX half built in **P4**; hard-blocks **P6** and **P7** | 🔴 blocker |
| **TG2** | **OPERATIONS Part 1 correctness tables have no T-numbers.** Corporate actions (1.1, called "the highest-priority gap"), trading calendar (1.2), FX as a first-class table (1.3), stable identity (1.4), fiscal alignment (1.5), one unit-conversion point (1.6). | Schema in **P0**; semantics and data in **P3**; consumed from **P6** | 🔴 silent corruption |
| **TG3** | **Auth/identity has no task of its own.** "auth" is one word inside T16, which is P9 — yet mode is derived from the authenticated principal from P0 and multi-user is mandated from day one ([PROJECT_CONTEXT.md 4](../PROJECT_CONTEXT.md)). | **P0** | 🔴 legal exposure |
| **TG4** | **Backup and disaster recovery is unscheduled** ([OPERATIONS.md 2.1](../OPERATIONS.md)). The dataset is the moat; losing it is the one unrecoverable failure. | **P0** | 🔴 unrecoverable |
| **TG5** | **The data-licensing gate has no task.** [CLAUDE.md](../CLAUDE.md) makes it a hard rule and [PROJECT_CONTEXT.md 9.3](../PROJECT_CONTEXT.md) calls it "the one that kills deals", but nothing enforces it per-source. | **P0** (register), enforced every phase | 🟡 deal-killer later |
| **TG6** | **No task covers the golden test set**, which [TEAM_BRIEF.md 2.2-C](../TEAM_BRIEF.md) calls "the highest leverage task in the project". T4's acceptance criteria assume golden files already exist. | **P3** (build), consumed in **P4** | 🔴 blocks P4's gate |
| **TG7** | *(new)* **The canonical chart of accounts has no owning task in SPEC and no versioning story.** [TEAM_BRIEF.md 2.2-G](../TEAM_BRIEF.md) makes it 2 days of human work; [DATA_FOUNDATION.md 3.4](../DATA_FOUNDATION.md) sketches it. Changing it after the extractor runs means re-extracting everything. | **P2** (draft) → **P3** (freeze v1) | 🔴 expensive to change |
| **TG8** | *(new)* **Nothing owns the scheduler / job runner.** [DATA_FOUNDATION.md 3.5](../DATA_FOUNDATION.md) names APScheduler and [DATA_FOUNDATION.md 7.2](../DATA_FOUNDATION.md) has a `scheduler/` package, but [SPEC.md 3.1](../SPEC.md)'s monorepo dropped it, and [OPERATIONS.md 2.3](../OPERATIONS.md)'s `connector_runs` health table has no owner. A connector that never runs fails silently. | **P1** (minimal) → **P4** (full, with health) | 🟡 silent failure |
| **TG9** | *(new)* **The storage-engine decision is contradictory and unscheduled.** [DATA_FOUNDATION.md 4.1](../DATA_FOUNDATION.md) says DuckDB/SQLite for v0.x; [SPEC.md 3.2](../SPEC.md)'s DDL is Postgres-flavoured (`SERIAL`, `JSONB`, `TIMESTAMPTZ`, `BIGSERIAL`); [OPERATIONS.md 2.4](../OPERATIONS.md) requires the DuckDB→Postgres migration to be a scripted step. Nobody picked. | **P0** (ADR-0001) | 🟡 rework risk |
| **TG10** | *(new)* **The manual override has no task.** [PROJECT_CONTEXT.md 7](../PROJECT_CONTEXT.md) requires "a dead-simple manual override… with a note recording who changed it and why", and [CLAUDE.md](../CLAUDE.md) rule 5 forbids silent overwrites. T4's review queue only covers *new* extractions, not correcting a figure already stored and on screen. | **P3** | 🟡 trust erosion |
| **TG11** | *(new)* **There is no `watchlists` table anywhere.** [PROJECT_CONTEXT.md 4](../PROJECT_CONTEXT.md) names watchlists as one of the things that must be keyed by principal, and T7's daily brief is specified to pull "watchlist moves" — but [SPEC.md 3.2](../SPEC.md)'s DDL has `portfolios`, `positions`, and `alerts` and no watchlist. | Schema **P0**, used **P5** | 🟡 cheap now, annoying later |

Anything marked **[NEEDS VERIFICATION]** in this document is a value or a URL that the source
documents did not establish and that this document will not guess at. Check it before you
encode it. A wrong number here becomes a wrong number in production.

---

## Threads that run through every phase

Five things are not phases. They start in P0 and are tightened in every phase after it. If you
look for them in the task list and cannot find them, that is why.

### 1. T15 — compliance and the mode gate

[SPEC.md 4.2](../SPEC.md) marks T15 "front-loaded, all versions". Its **core** lands in P0:
mode resolution from the authenticated principal, the split `/public` and `/personal` routers,
the response-type assertion, the banned-phrase linter, and the audit log. Every phase after P0
adds its own surface to the compliance test suite:

| Phase | What T15 gains |
|---|---|
| P0 | Mode resolution, routers, response-type assertion, linter, `audit_log`, first compliance tests |
| P1 | Macro endpoints added to the public-surface sweep |
| P2 | Valuation outputs asserted to carry no `fair_value` / `target` field in public mode |
| P3 | Provenance assertion: every public figure resolves to a source document |
| P4 | LLM extraction output passes the linter *before storage* — an LLM can write advice-shaped prose into a notes field |
| P5 | LLM sentiment and brief text pass the linter; the Telegram surface joins the sweep |
| P6 | Scenario outputs never present a system-chosen assumption as a recommendation |

### 2. Provenance on every figure

[CLAUDE.md](../CLAUDE.md), non-negotiable: source document, page, as-of date. Practically, no
phase is done if it added a number to the database that cannot answer "where did you come
from?" Provenance completeness is a tracked metric and **must sit at 100%**
([OPERATIONS.md 3.2](../OPERATIONS.md)).

### 3. Point-in-time discipline

Every fact carries `known_as_of` — the date on which a human could first have seen it. A
feature computed for a decision on 2024-03-01 may only use facts with
`known_as_of <= 2024-03-01`. This matters nowhere in P1 and everywhere from P6 onward, which is
exactly why it must be in the schema from P0: retrofitting `known_as_of` onto three years of
already-loaded data is guesswork, and guessed point-in-time dates produce backtests that lie.

### 4. Multi-user from day one

Portfolios, watchlists, risk limits, alerts, spend caps, and audit rows are keyed by principal
([PROJECT_CONTEXT.md 4](../PROJECT_CONTEXT.md), [CLAUDE.md](../CLAUDE.md)). In P0–P6 you will
have between one and five users and this will feel like ceremony. It is not: a single-user
trading layer is a full rewrite to open up, and a multi-user one that currently has two users
is a config change.

### 5. Write an ADR whenever you decide something expensive to reverse

`docs/decisions/NNNN-short-title.md`, one page: context, decision, alternatives rejected,
consequences, date ([OPERATIONS.md 3.1](../OPERATIONS.md)). The failure this prevents is
specific: a coding-agent session three months from now proposes replacing Postgres with DuckDB,
or renaming a canonical key, because it cannot see why the current choice was made. The ADR is
the answer you write once instead of arguing five times.

---

## The manual-work calendar

Some phases are gated by human data work, not by code. You cannot agent your way past these.
Pulled from [TEAM_BRIEF.md PART 2](../TEAM_BRIEF.md), with the phase each one must be finished
by. "Solo" means you are all of these roles; the role names still matter because they tell you
what kind of attention the task needs.

| Task | Role | Effort | Start during | Must be done by | Blocks or parallel |
|---|---|---|---|---|---|
| **A.** Choose the 15–25 company universe | Curator | ~1 day | before P0 | P3 | **Blocks** — everything downstream is sized by this |
| **B.** Collect the seed document set (~100 PDFs) | Collector | 3–5 days | P0–P2 | P4 | Parallel with P0–P2, **blocks P4** |
| **C.** Build the golden test set (3 filings, every number by hand) — **TG6** | Reviewer + Curator | 2–3 days | P2–P3 | P4 | **Blocks P4's accuracy gate** |
| **D.** Manual data entry, 5 companies × 2 years | Data-entry analyst | 2–4 hrs per company-year | P3 | P3 | **Blocks P3 exit** |
| **E.** Backfill corporate actions, 5 years — **TG2** | Collector + Reviewer | 2–3 days | P3 | P6 | Parallel with P4, **blocks P6** |
| **F.** Seed the ticker alias table | Curator | ~0.5 day, then ongoing | P3 | P5 | **Blocks P5** news tagging |
| **G.** Build the canonical chart of accounts — **TG7** | Curator (needs accounting knowledge) | ~2 days | P2 | P3 | **Blocks P3 and P4** |
| **H.** Monthly macro download (NBS CPI, CBN MPR, FX, DMO) | Collector | ~30 min/month | P1 | ongoing until P4 | Parallel |
| **I.** Ongoing extraction review (~20 corrections per filing) | Reviewer | permanent, weekly | P4 | never done | Parallel, permanent |
| **J.** Accounts, applications, legal | Owner only | see below | P0 | mixed | Mixed |

**Task J unpacked, because "accounts and legal" hides three very different lead times:**

- **FRED API key** — free, minutes. Needed for **P1**.
- **Anthropic API key** — needed for **P4** (extraction) and **P5** (sentiment).
- **Telegram bot token** via BotFather — free, minutes. Needed for **P5**.
- **EODHD subscription** (~$60–100/mo per [DATA_FOUNDATION.md PART 2A](../DATA_FOUNDATION.md))
  — only if the P4 decision gate says buy.
- **The securities + data-protection lawyer** — [TEAM_BRIEF.md 2.2-J](../TEAM_BRIEF.md) says
  book this *earlier* than the v2.0 gate that [DATA_FOUNDATION.md Rec. 5](../DATA_FOUNDATION.md)
  makes it. The answer on NGX redistribution rights shapes architecture, and the SEC licence
  path has a long lead time. Nothing in P0–P6 is blocked by it — but the moment you can afford
  the conversation, have it, because the answer changes what P12 looks like.

🔴 **FRAGILE — the manual work is the schedule.** [TEAM_BRIEF.md PART 3](../TEAM_BRIEF.md)
names review capacity as one of the big five bottlenecks and attrition as the quietest killer.
Tasks A, B, C, D, E and G together are roughly **11–17 working days of human effort that
produce no visible software**. Solo, that is three weeks where the app does not change, sitting
right between P2 and P4.

Three approaches:

1. **Do it all yourself, front-loaded, before P3.** Cheapest in money; highest risk of
   stalling — three weeks of unrewarding work is exactly where solo projects die.
2. **Contract out the parallelisable parts (B and D) at local rates**, keep A, C, E, F, G
   yourself. [TEAM_BRIEF.md 2.3](../TEAM_BRIEF.md) explicitly warns that a contractor can key
   numbers but **cannot build the golden set** — that needs someone who will be held
   accountable for it.
3. **Interleave: do A and G before P3; do B and C in slices**, one company at a time, alongside
   the coding phases, and accept that P4 starts with a 3-filing golden set rather than a
   complete seed corpus.

**Recommendation: 3, with 2 as the escape hatch.** Interleaving keeps something shipping every
week, which is the real defence against attrition. Three filings is enough golden set to start
P4 — [TEAM_BRIEF.md 2.2-C](../TEAM_BRIEF.md) specifies exactly three (MTN Nigeria FY2024, a
bank, a clean industrial). Do not let "collect all 100 PDFs first" become the thing that stops
the project.

---

## Phase map for this document

| Phase | Name | Spec version | Tasks | Rough effort |
|---|---|---|---|---|
| **P0** | Foundation & Rails | pre-v0.1 | repo, monorepo, full DDL, FastAPI skeleton, T15 core, CI, ADRs + **TG3, TG4, TG5, TG9, TG11** | 5–9 working days |
| **P1** | Macro Backdrop | v0.1 | T1 + **TG8** (minimal) | 2–4 working days |
| **P2** | US Company Data | v0.2 | T2 + **TG1-US**, **TG7** (draft) | 4–7 working days |
| **P3** | Nigerian Manual Analyzer | v0.3 | T3 + **TG2**, **TG6**, **TG7** (freeze), **TG10** | 4–6 working days of code, plus the manual work |
| **P4** | Nigerian Automated Ingestion | v0.4 | T4 + **TG1-NG**, **TG8** (full) | 3–6+ weeks — **budget 2–3×** |
| **P5** | News, Sentiment & Daily Brief | v0.5 | T5, T6, T7 | 1–2 weeks |
| **P6** | Scenarios & Indicators | v0.6–v0.7 | T8, T9 | 2–3 weeks |

Effort ranges are working days of focused solo work with AI assistance, not calendar time.
They come from [DATA_FOUNDATION.md PART 5](../DATA_FOUNDATION.md) where that document gives
one, and are this document's estimate where it does not. The P4 figure is the source
document's own, including its instruction to budget 2–3×.

# P0 — Foundation & Rails (pre-v0.1)

**Spec version:** none (this phase exists in this document set, not in [SPEC.md 1.3](../SPEC.md))
**Tasks:** repo init · monorepo scaffold · full DDL · FastAPI skeleton · T15 core (mode gate) ·
CI · ADR log · **TG3** (principal/auth) · **TG4** (backup) · **TG5** (licensing register) ·
**TG9** (storage-engine ADR) · **TG11** (watchlists table)
**Rough effort:** 5–9 working days

## In one sentence

At the end of P0 you have an empty but *correct* system: a running API that already knows who
is asking and what mode they get, a database with every table the project will ever need, a
test suite that runs on every commit, and a backup you have actually restored from — and not
one line of financial logic yet.

## Why this phase is here now

P0 is not in the source spec. It exists because four things in that spec cannot be retrofitted
without a rewrite, and all four are invisible until it is too late:

1. **The mode gate.** [SPEC.md 4.1](../SPEC.md) requires that mode is *server-derived* — the
   client never says which mode it is in. If you build v0.1 as a local Streamlit script, there
   is no server, so there is no place for mode to be derived. Adding it later means rewriting
   every call site.
2. **Multi-user.** [CLAUDE.md](../CLAUDE.md) calls single-user "the expensive shortcut to
   avoid" and [PROJECT_CONTEXT.md 4](../PROJECT_CONTEXT.md) spells out why: portfolios,
   watchlists, risk limits, alerts, spend caps and audit rows are keyed by principal, and
   position sizing takes account equity as a per-user *parameter*. A single-user trading layer
   is a full rewrite to open up. Adding an `owner` column to eleven tables later is a data
   migration; adding a `principal` concept to logic that never had one is a redesign.
3. **Provenance.** Every figure carries source document, page, and as-of date. If the columns
   are not there from the first insert, the first thousand rows have no provenance and the rule
   is already broken.
4. **The correctness substrate (TG2).** Corporate actions, trading calendar, FX, identity
   history. These change the *meaning* of a stored price. Retrofitting them means recomputing
   every derived value you have.

Everything else in this project can be added incrementally. These four cannot. That is the
whole argument for P0.

> 🟡 **WATCH — the temptation to skip P0 entirely.** It produces nothing you can look at. There
> is no chart, no number, no page. [TEAM_BRIEF.md 267](../TEAM_BRIEF.md) says "this weekend:
> v0.1" and it is right that momentum matters. **The compromise, if you need to see something
> this week:** do P0 items 1, 2, 3, 5 and 8 below (repo, monorepo, DDL, API skeleton with mode
> resolution, CI) and defer items 6, 7 and 9 (backup drill, licensing register, full ADR
> backfill) until immediately after P1 ships. Do not defer the mode gate or the principal
> model. Those are the two that cost a rewrite.

## Entry criteria

- [ ] The six root documents have been read (or at least [CLAUDE.md](../CLAUDE.md) and
      [PROJECT_CONTEXT.md 4, 8, 10](../PROJECT_CONTEXT.md))
- [ ] The open decisions in [PROJECT_CONTEXT.md 8](../PROJECT_CONTEXT.md) ("Decisions to make
      before writing much code") have been answered, or consciously deferred with a note
- [ ] **Python 3.12** available via `uv python install 3.12` and pinned in `.python-version`
      — see [02_INFRASTRUCTURE.md](02_INFRASTRUCTURE.md) §2. **Not 3.13+**: `pyproject.toml`
      pins `>=3.11,<3.13`, and the build machine currently has only 3.14.3, so `uv sync`
      fails until 3.12 is installed ([10_PRE_BUILD_CORRECTIONS](10_PRE_BUILD_CORRECTIONS.md) §1)
- [ ] `uv` installed (`winget install astral-sh.uv`) — `uv sync --frozen` is a hard rule
- [ ] PostgreSQL client tools on `PATH`, **or** every `psql`/`createdb`/`pg_dump` command in
      this phase rewritten as `docker compose exec -T db …`. Checks 1, 14 and 16 need one or
      the other; the docs currently assume the client while recommending Docker
- [ ] A GitHub account and an empty remote repository exist
- [ ] You have decided the storage engine (this is **TG9** and is resolved *inside* this phase
      as ADR-0001 — see below)

## Manual work required first

None blocking. P0 is pure engineering. But two human tasks from
[TEAM_BRIEF.md PART 2](../TEAM_BRIEF.md) can start **in parallel** and should, because they are
long-lead and they gate P2–P4:

| Task | Role | Effort | Why start now |
|---|---|---|---|
| **A. Choose the company universe** ([TEAM_BRIEF 2.2-A](../TEAM_BRIEF.md)) | Curator | ~1 day | Everything downstream is scoped by it. Nothing can be collected until it exists. |
| **B. Collect the seed document set** ([TEAM_BRIEF 2.2-B](../TEAM_BRIEF.md)) | Collector | ~3–5 days | Nigerian annual reports are slow to gather. Starting now means P3 is not waiting on PDFs. |

Start A on day one of P0. Start B the moment A is done.

## The build, task by task

### P0.1 — Repository and version control

**What it is.** Turn the folder into a tracked git repository with sane defaults.

**Steps:**

```bash
cd /c/quant_model
git init
git branch -M main
printf '%s\n' \
  '__pycache__/' '*.py[cod]' '.venv/' 'venv/' '.env' '.env.*' '!.env.example' \
  'node_modules/' '*.duckdb' '*.sqlite' '*.db' '.pytest_cache/' '.ruff_cache/' \
  '.mypy_cache/' 'dist/' 'build/' '*.egg-info/' '.DS_Store' 'data/raw/' \
  'data/interim/' '.streamlit/secrets.toml' > .gitignore
git add -A
git commit -m "Initial commit: specification documents and planning set"
git remote add origin <your-remote-url>
git push -u origin main
```

**Decisions inside this task:**

- **Private repository.** Not optional. The repo will contain the extraction prompts, the
  cost model, and eventually strategy parameters. [PROJECT_CONTEXT.md 9.3](../PROJECT_CONTEXT.md)
  treats the dataset as the asset.
- **Branch protection on `main`.** [CLAUDE.md](../CLAUDE.md) requires "one task, one PR, tests
  required". Enforce it in GitHub settings so you cannot bypass it at 1am.
- **`data/` is git-ignored.** Source PDFs never go in git — they go to object storage. See
  [02_INFRASTRUCTURE.md](02_INFRASTRUCTURE.md) §4. Git is for code; a 400-page annual report is
  not code and will bloat the repository permanently.

> 🟢 **SOLID.** This is ten minutes of well-trodden work. The only real mistake available is
> committing a secret, and P0.7 installs the guard that prevents it.

### P0.2 — Monorepo scaffold

**What it is.** Create the directory structure from [SPEC.md 3.1](../SPEC.md), with every
package importable and empty, so that later phases have a place to put code and never have to
argue about where something lives.

**Target structure** (from [SPEC.md 3.1](../SPEC.md), plus the two additions this document
argues for):

```
/apps
  /streamlit      # local v0.x dashboards — thin client only (AD-3)
  /bot            # Telegram brief/alerts (P5+)
  /web            # Next.js (P9+) — empty until then
/services
  /api            # FastAPI: /public/* and /personal/* routers
/packages
  /ingestion      /normalize     /valuation    /indicators
  /ml             /backtest      /agents       /sentiment
  /alerts         /portfolio     /execution    /compliance
  /common         # schemas, provenance, db, config
  /scheduler      # ADDED — see TG8; SPEC 3.1 dropped it, DATA_FOUNDATION 7.2 has it
/db
  /migrations     # Alembic
/tests
  /unit  /golden  /compliance  /synthetic  /known_answer
/docs             # this planning set
/scripts          # operational scripts (backup, restore, seed)
```

**Steps:**

```bash
cd /c/quant_model
mkdir -p apps/{streamlit,bot,web} services/api db/migrations scripts \
         tests/{unit,golden,compliance,synthetic,known_answer}
for p in ingestion normalize valuation indicators ml backtest agents \
         sentiment alerts portfolio execution compliance common scheduler; do
  mkdir -p "packages/$p"
  printf '"""%s package."""\n' "$p" > "packages/$p/__init__.py"
done
```

Then the Python project files — `pyproject.toml` declaring the workspace, `ruff` and `mypy`
config, and `pytest` settings. Full contents are in
[02_INFRASTRUCTURE.md](02_INFRASTRUCTURE.md) §2.

**Decisions inside this task:**

- **`/packages/scheduler` is added** to SPEC's layout. This closes **TG8**. A connector that
  never runs fails silently, and [OPERATIONS.md 2.3](../OPERATIONS.md)'s `connector_runs`
  health table needs an owner. Record as ADR-0002.
- **Import direction is one-way.** `apps/*` and `services/api` may import from `packages/*`.
  `packages/*` must never import from `apps/*` or `services/*`. Enforce with an import-linter
  rule in CI. This is what keeps the Streamlit surface disposable (AD-3).

> 🟢 **SOLID.** Directory layout is cheap to get right and cheap to change early. The one-way
> import rule is the only part with teeth, and CI enforces it.

### P0.3 — Resolve the storage engine (TG9, ADR-0001)

**What it is.** The source documents contradict each other and nobody picked. This must be
decided before the DDL is written, because the DDL is written in one dialect or the other.

**The contradiction:**

| Document | Says |
|---|---|
| [DATA_FOUNDATION.md 4.1](../DATA_FOUNDATION.md) | DuckDB/SQLite for v0.x |
| [SPEC.md 3.2](../SPEC.md) | DDL uses `SERIAL`, `JSONB`, `TIMESTAMPTZ`, `BIGSERIAL` — all Postgres |
| [OPERATIONS.md 2.4](../OPERATIONS.md) | Requires the DuckDB→Postgres migration to be a scripted step |

🔴 **FRAGILE — this is a rework risk, and it is the first real decision of the project.**

**Approach 1 — PostgreSQL from day one (recommended).**
Install Postgres locally, write the DDL exactly as [SPEC.md 3.2](../SPEC.md) has it, never
migrate.
*For:* The DDL is already written in this dialect, so zero translation. TimescaleDB (the
time-series extension) is available when price history arrives in P2. Production and local are
the same engine, which kills an entire class of "works on my machine" bug. No migration step
ever needs writing or testing.
*Against:* You must install and run Postgres on Windows before you can run a single test. That
is perhaps two hours of setup, and it is friction on day one when momentum matters most.

**Approach 2 — DuckDB now, Postgres at P9.**
*For:* Zero install; it is a Python package and a file. Genuinely excellent for the analytical
queries this project makes. [DATA_FOUNDATION.md 4.1](../DATA_FOUNDATION.md) recommends it.
*Against:* You will write the DDL twice and the migration once, and you must *test* the
migration, which means owning a second code path for the life of the project. Every
Postgres-specific type in SPEC's DDL needs a DuckDB equivalent chosen now and re-chosen later.
The multi-user concurrency story is weak, and multi-user is mandated from day one.

**Approach 3 — SQLAlchemy with an engine-agnostic schema.**
*For:* Defers the decision; swap by changing a connection string.
*Against:* This is the trap. "Engine-agnostic" means you cannot use `JSONB`, cannot use
Timescale hypertables, and cannot use Postgres-specific constraints — so you give up the
features you chose Postgres for, and you still test against two engines. It costs more than
either commitment.

**Recommendation: Approach 1.** The two hours of Postgres setup buys back more than that on the
first migration you do not have to write. Use Docker Desktop on Windows 11 if a native install
is awkward — see [02_INFRASTRUCTURE.md](02_INFRASTRUCTURE.md) §2. Record the decision as
ADR-0001 with this reasoning, so that when it feels slow in week one you can re-read why.

### P0.4 — The full DDL

**What it is.** Create every table the project will need, including the ones that stay empty
for months. Empty tables cost nothing. Missing columns cost migrations and, worse, cost you the
data you did not record because there was nowhere to put it.

**What goes in:**

| Source | Tables |
|---|---|
| [DATA_FOUNDATION.md 4.2](../DATA_FOUNDATION.md) | The base schema: companies, securities, filings, statements, `statement_line_items`, macro series, news |
| [SPEC.md 3.2](../SPEC.md) | `indicators`, `ml_features`, `ml_models`, `backtest_runs`, `signals`, `portfolios`, `positions`, `alerts`, `alert_deliveries`, `audit_log` — read every line of that section |
| **TG2** ([OPERATIONS.md Part 1](../OPERATIONS.md)) | `corporate_actions`, `trading_calendar`, `fx_rates`, `security_identifiers` (ticker history), fiscal-period alignment fields |
| **TG3** | `principals`, `entitlements`, `sessions` |
| **TG5** | `data_sources` with redistribution-rights fields |
| **TG11** | `watchlists`, `watchlist_items` |

Exact column definitions are in [08_DATA_CONTRACTS.md](08_DATA_CONTRACTS.md) §2. Do not invent
them here; that document is the contract.

**The three rules every table follows:**

1. **Provenance columns travel with every extracted figure** — `source_document_id`, `page`,
   `as_of_date`, `extraction_method`, `confidence`, `reviewed_by`. ([CLAUDE.md](../CLAUDE.md)
   hard rule.)
2. **Point-in-time columns on anything a model will read** — `known_as_of` alongside the
   business date. ([SPEC.md 4.1](../SPEC.md).)
3. **Owner key on anything user-scoped** — `principal_id` on portfolios, positions, watchlists,
   alerts, risk limits, spend caps, audit rows. ([PROJECT_CONTEXT.md 4](../PROJECT_CONTEXT.md).)

**Steps:**

```bash
python -m pip install alembic sqlalchemy psycopg[binary]
cd /c/quant_model && alembic init db/migrations
# edit db/migrations/env.py to read the URL from packages/common/config.py
alembic revision -m "0001 base schema"       # DATA_FOUNDATION 4.2 tables
alembic revision -m "0002 spec 3.2 tables"   # SPEC 3.2 tables
alembic revision -m "0003 correctness substrate (TG2)"
alembic revision -m "0004 principals and entitlements (TG3)"
alembic revision -m "0005 data source licensing register (TG5)"
alembic revision -m "0006 watchlists (TG11)"
alembic upgrade head
```

Keep them as separate revisions rather than one. When something is wrong in six months, you
want to see which concern introduced it.

> 🟡 **WATCH — the DDL is long and writing it is tedious, so it is where attention lapses.**
> The specific failure: you write `statement_line_items` without `known_as_of` because it feels
> redundant next to `as_of_date`, and eight months later your backtest is training on restated
> financials that were not public at the decision date. Your **early-warning signal**: any table
> that a model or backtest will read and that has only one date column. Every such table is a
> bug. See [01_ARCHITECTURE.md](01_ARCHITECTURE.md) §5 for why the two dates differ.

### P0.5 — FastAPI skeleton with the mode gate (T15 core, TG3)

**What it is.** The single most important thing built in P0. A running HTTP service that
resolves *who is asking* (the principal), derives *what they are allowed to see* (the mode),
routes them to the correct router, and asserts on the way out that a public request cannot
possibly carry a personal-mode payload.

This is [SPEC.md 1.2](../SPEC.md)'s five enforcement mechanisms and
[SPEC.md 3.3](../SPEC.md)'s middleware design. It is built now, empty, so that every endpoint
added in every later phase inherits it by construction rather than by discipline.

**The request lifecycle:**

```mermaid
sequenceDiagram
    participant C as Client (Streamlit / bot / web)
    participant M as Mode middleware
    participant R as Router (/public or /personal)
    participant A as Response assertion
    participant L as Banned-phrase linter
    participant D as Audit log

    C->>M: request + credential
    M->>M: resolve principal from credential
    M->>M: derive mode from principal entitlements + licence_status
    Note over M: mode is NEVER read from the request body<br/>default is public
    M->>R: dispatch to the router for that mode
    R->>A: response object
    A->>A: assert response type is legal for this mode
    Note over A: a PersonalSignal on a /public route<br/>raises here, it does not warn
    A->>L: response text
    L->>L: scan for advice phrasing in public mode
    L->>D: write audit row (principal, mode, endpoint, response type)
    D->>C: response
```

**The five mechanisms, and what breaks without each:**

| # | Mechanism | Without it |
|---|---|---|
| 1 | **Mode derived server-side from the principal** | A client sends `mode=personal` and receives advice it is not entitled to. This is the legal-risk line in [CLAUDE.md](../CLAUDE.md). |
| 2 | **Separate `/public/*` and `/personal/*` routers** | Advice logic and data logic share a code path, and one `if` statement is all that stands between them. |
| 3 | **Response-type assertion** | A refactor returns the wrong object and nothing notices until a user sees it. |
| 4 | **Banned-phrase linter** | Advice leaks through as prose ("we think this is cheap") even when the response type is legal. |
| 5 | **Audit row per request** | You cannot prove after the fact who saw what, which is exactly what a regulator asks. |

**Skeleton:**

```python
# services/api/middleware/mode.py
from enum import Enum
from fastapi import Request, HTTPException

class Mode(str, Enum):
    PUBLIC = "public"
    PERSONAL = "personal"

async def resolve_mode(request: Request) -> Mode:
    """Derive mode from the authenticated principal. Never from the request.

    SPEC.md 4.1: 'Mode is server-derived — never trust a client-supplied mode.
    Default public.'
    """
    principal = await resolve_principal(request)   # None => anonymous
    if principal is None:
        return Mode.PUBLIC
    if not principal.entitlements.personal_tier:
        return Mode.PUBLIC
    # licence_status gates the PUBLIC advice tier, not the family tier.
    # Pre-licence, personal mode is reachable only by entitled principals.
    return Mode.PERSONAL
```

```python
# services/api/middleware/assert_response.py
PUBLIC_LEGAL_TYPES = {DataSeries, StatementView, RatioSet, ScenarioResult, NewsItem}

def assert_legal(mode: Mode, payload) -> None:
    if mode is Mode.PUBLIC and type(payload) not in PUBLIC_LEGAL_TYPES:
        raise HTTPException(500, "response type illegal for public mode")
```

Note that the assertion raises a **500, not a 403**. A public request receiving a personal
payload is not a permissions problem to be reported to the caller — it is a bug in our code,
and it should fail loudly and be impossible to ignore.

**Endpoints in P0:** exactly three, all trivial.

| Endpoint | Returns | Purpose |
|---|---|---|
| `GET /health` | `{"status":"ok","version":"...","db":"ok"}` | Liveness, and proves the DB connection works |
| `GET /public/ping` | `{"mode":"public"}` | Proves the public router and mode derivation work |
| `GET /personal/ping` | `{"mode":"personal"}` or 403 | Proves entitlement gating works |

> 🔴 **FRAGILE — authentication is TG3, it has no task in the source spec, and it is the piece
> most likely to be done badly under time pressure.** Three approaches:
>
> **1. API-key/token table in Postgres, checked by middleware (recommended for P0).** A
> `principals` table, a hashed token, a `Bearer` header. *For:* ~half a day; no third party;
> works identically for Streamlit, the Telegram bot, and later Next.js; the principal model —
> the part that is expensive to retrofit — is real from day one. *Against:* You own password
> reset, session expiry and rotation yourself when real users arrive at P9.
>
> **2. A hosted identity provider now (Auth0, Clerk, Supabase Auth).** *For:* Sessions, resets,
> MFA and social login solved properly; the right answer at P9. *Against:* An external
> dependency, a config surface, and a bill, for a system with two users who are both you. It
> also couples your local dev loop to a network service.
>
> **3. No auth in P0; a hardcoded single principal.** *For:* Fastest to something working.
> *Against:* This is precisely the shortcut [CLAUDE.md](../CLAUDE.md) names as the expensive
> one. The `principals` table would not exist, so nothing downstream would be keyed by it, and
> P9 becomes a redesign rather than a swap.
>
> **Recommendation: 1 now, 2 at P9.** The `principals` table and the middleware contract are
> what matter; the credential mechanism behind them is swappable precisely because the contract
> exists. Record as ADR-0003.

### P0.6 — Backup and restore, proven (TG4)

**What it is.** [OPERATIONS.md 2.1](../OPERATIONS.md) requires backup and DR and no task
schedules it. The dataset is the asset ([PROJECT_CONTEXT.md 9.3](../PROJECT_CONTEXT.md)) and
losing it is the only unrecoverable failure in this project — every other failure costs time,
this one costs the thing itself.

It goes in P0, when the database is empty, for one reason: **the restore is the part that
fails, and you want to discover that while there is nothing to lose.**

**Steps:**

- `scripts/backup.sh` — `pg_dump` to a timestamped file, plus the object-storage bucket sync
- `scripts/restore.sh` — restore into a *separate* database named `quant_restore_test`, never
  over the live one
- Schedule the backup (Windows Task Scheduler or a cron in your host — see
  [02_INFRASTRUCTURE.md](02_INFRASTRUCTURE.md) §8)
- **Run the restore once, now, and confirm the schema comes back.** Write the date you did it
  in the ADR log.

> 🟢 **SOLID once done, 🔴 FRAGILE until proven.** An untested backup is not a backup — it is a
> file you *believe* is a backup. The distinction is only visible on the day it matters. Ten
> minutes now.

### P0.7 — CI, linting, and the secret guard

**What it is.** A GitHub Actions workflow that runs on every push and blocks a merge that
breaks the rules. [CLAUDE.md](../CLAUDE.md): "one task, one PR, tests required."

**Pipeline stages:** `ruff` (lint) → `ruff format --check` → `mypy` (types) →
`import-linter` (the one-way rule from P0.2) → `pytest tests/unit` →
`pytest tests/compliance` → `alembic upgrade head` against a throwaway database (proves
migrations apply cleanly from empty) → secret scan.

Full YAML skeleton is in [02_INFRASTRUCTURE.md](02_INFRASTRUCTURE.md) §7.

Install a pre-commit hook with `gitleaks` or `detect-secrets` so a key never reaches the remote
in the first place. Once a secret is pushed to a remote it must be treated as compromised and
rotated, regardless of whether you force-push it away.

> 🟢 **SOLID.** Standard, well-documented, and the failure mode is a red badge, which is the
> friendliest kind of failure there is.

### P0.8 — The compliance test suite (T15, first tests)

**What it is.** Tests that prove the mode gate cannot be bypassed. These are the tests that may
never be skipped or marked `xfail` — see [07_TEST_STRATEGY.md](07_TEST_STRATEGY.md) §4.

Write these now, against the empty skeleton, so they are in place before there is anything to
leak:

```python
# tests/compliance/test_mode_gate.py

def test_client_cannot_set_mode_via_body():
    r = client.get("/public/ping", json={"mode": "personal"})
    assert r.json()["mode"] == "public"

def test_client_cannot_set_mode_via_header():
    r = client.get("/public/ping", headers={"X-Mode": "personal"})
    assert r.json()["mode"] == "public"

def test_client_cannot_set_mode_via_query():
    r = client.get("/public/ping?mode=personal")
    assert r.json()["mode"] == "public"

def test_anonymous_defaults_to_public():
    assert client.get("/public/ping").json()["mode"] == "public"

def test_unentitled_principal_cannot_reach_personal():
    assert client.get("/personal/ping", headers=unentitled_auth()).status_code == 403

def test_personal_payload_on_public_route_raises():
    with pytest.raises(Exception):
        assert_legal(Mode.PUBLIC, PersonalSignal(...))
```

### P0.9 — The ADR log

**What it is.** A decision record per non-obvious choice, in `docs/adr/NNNN-title.md`, with
context, decision, consequences, and alternatives rejected
([OPERATIONS.md 3.1](../OPERATIONS.md)).

Seed it with what is already decided:

| ADR | Decision |
|---|---|
| 0001 | Storage engine (P0.3) |
| 0002 | `/packages/scheduler` added to the monorepo (TG8) |
| 0003 | Authentication mechanism (P0.5) |
| 0004 | Python everywhere except the v1.0 frontend (AD-1) |
| 0005 | FastAPI stands up in P0, not P9 — a deliberate deviation from [SPEC.md 4.2](../SPEC.md)'s ordering (AD-2) |
| 0006 | Streamlit is a thin client; business logic in a callback is a defect (AD-3) |
| 0007 | Multi-user from day one (AD-4) |

Six months from now the value of this file is that it stops you re-litigating a decision you
already made carefully, and stops you keeping a decision whose reasoning has expired.

### P0.10 — The data-source licensing register (TG5)

**What it is.** A `data_sources` table plus a hard rule in the connector base class: a connector
whose row does not state its redistribution rights **cannot be enabled**.

[CLAUDE.md](../CLAUDE.md) makes licensing-before-ingestion a hard rule.
[PROJECT_CONTEXT.md 9.3](../PROJECT_CONTEXT.md) says an acquirer's lawyers will ask exactly one
hard question, and this is it. The register costs an hour now; reconstructing the provenance of
every source after two years of ingestion is close to impossible.

Columns: `source_name`, `url`, `licence_type`, `redistribution_allowed` (bool, **not null**),
`attribution_required`, `terms_url`, `terms_reviewed_on`, `reviewed_by`, `notes`.

`redistribution_allowed` being `NOT NULL` is the whole mechanism. It forces an answer.

## Expected inputs

P0 consumes almost nothing external. That is what makes it a good first phase — it cannot be
blocked by a website being down.

| Input | Source | Format |
|---|---|---|
| The six specification documents | This repository | Markdown |
| Postgres connection string | Your local install | `postgresql://user:pass@localhost:5432/quant` |
| GitHub remote URL | Your account | `git@github.com:you/quant_model.git` |
| Your own email/identity | You | Seeds the first `principals` row |

## Expected outputs

**A running service:**

```console
$ uvicorn services.api.main:app --reload
INFO:     Uvicorn running on http://127.0.0.1:8000

$ curl -s localhost:8000/health
{"status":"ok","version":"0.0.1","db":"ok","migrations":"0006"}

$ curl -s localhost:8000/public/ping
{"mode":"public"}

$ curl -s localhost:8000/personal/ping
{"detail":"forbidden"}          # anonymous — correct

$ curl -s -H "Authorization: Bearer $OWNER_TOKEN" localhost:8000/personal/ping
{"mode":"personal"}
```

**A populated schema:**

```console
$ psql quant -c "\dt" | wc -l
# ~30 tables, all empty except principals and data_sources
```

**An audit trail** — every one of those requests wrote a row:

```
| id | ts                  | principal | mode     | endpoint       | response_type | status |
|----|---------------------|-----------|----------|----------------|---------------|--------|
| 1  | 2026-08-28T14:02:11Z| anonymous | public   | /public/ping   | Ping          | 200    |
| 2  | 2026-08-28T14:02:19Z| anonymous | personal | /personal/ping | —             | 403    |
| 3  | 2026-08-28T14:02:31Z| frank     | personal | /personal/ping | Ping          | 200    |
```

**A green CI run** on a pull request, and a `docs/adr/` directory with seven records.

## TEST CHECKPOINT — P0

Run every one of these. A phase is not done because the code is written; it is done because
these pass.

| # | Check | Command | Expected result |
|---|---|---|---|
| 1 | Migrations apply from empty | `dropdb quant_t; createdb quant_t; DATABASE_URL=...quant_t alembic upgrade head` | Exits 0, no errors |
| 2 | Migrations are reversible | `alembic downgrade base && alembic upgrade head` | Exits 0 both ways |
| 3 | Service starts | `uvicorn services.api.main:app` | Binds port, `/health` returns `"db":"ok"` |
| 4 | Mode cannot be forced — body | `curl -X GET localhost:8000/public/ping -d '{"mode":"personal"}'` | `{"mode":"public"}` |
| 5 | Mode cannot be forced — header | `curl -H "X-Mode: personal" localhost:8000/public/ping` | `{"mode":"public"}` |
| 6 | Mode cannot be forced — query | `curl "localhost:8000/public/ping?mode=personal"` | `{"mode":"public"}` |
| 7 | Anonymous is public | `curl localhost:8000/public/ping` | `{"mode":"public"}` |
| 8 | Unentitled is refused | `curl -H "Authorization: Bearer $GUEST" localhost:8000/personal/ping` | HTTP 403 |
| 9 | Entitled is admitted | `curl -H "Authorization: Bearer $OWNER" localhost:8000/personal/ping` | `{"mode":"personal"}` |
| 10 | Compliance suite passes | `pytest tests/compliance -v` | All pass, none skipped |
| 11 | Import direction enforced | `lint-imports` | No `packages/*` importing `apps/*` |
| 12 | Secret scan clean | `gitleaks detect --no-git` | No findings |
| 13 | CI green on a PR | Open a trivial PR | All stages pass |
| 14 | **Backup restores** | `./scripts/backup.sh && ./scripts/restore.sh` | `quant_restore_test` has the same table count as `quant` |
| 15 | Licensing gate bites | Try to register a connector with `redistribution_allowed = NULL` | Raises; connector will not enable |

**Do these two by hand and by eye:**

16. **Read the audit log yourself.** `psql quant -c "SELECT * FROM audit_log ORDER BY id;"`
    Confirm your test requests are all there, with the right principal and the right mode. If a
    request is missing, the audit middleware is not on every route — find out which route
    escaped, because that route will one day carry something that matters.

17. **Try to break your own mode gate for ten minutes.** Send `mode` as a cookie. Send it as a
    nested JSON field. Send a `/personal/` path with odd casing or a trailing slash. Send an
    expired token. You are looking for any path where the answer is not `public`. This is the
    one rule in the project with real legal consequence
    ([CLAUDE.md](../CLAUDE.md)) and ten minutes of adversarial curl now is worth more than a
    test you wrote to pass.

## Exit criteria — definition of done

- [ ] All 17 checks above pass
- [ ] `git log` shows the work in reviewed PRs, not direct pushes to `main`
- [ ] Every table from [08_DATA_CONTRACTS.md](08_DATA_CONTRACTS.md) §2 exists, including the
      ones that stay empty until P8
- [ ] Every user-scoped table has a `principal_id`; every extracted-figure table has the
      provenance columns; every model-readable table has `known_as_of`
- [ ] `docs/adr/` contains ADR-0001 through ADR-0007
- [ ] A restore has actually been performed, and the date is recorded
- [ ] The tracker in [00_START_HERE.md](00_START_HERE.md) §6 is updated to P0 ✅

## What could go wrong

| Risk | Marker | Detail |
|---|---|---|
| Auth done badly or skipped | 🔴 FRAGILE | Three approaches in P0.5. The `principals` table existing matters more than which credential scheme sits on top of it. |
| Storage engine re-litigated later | 🔴 FRAGILE | Three approaches in P0.3. Decide once, record ADR-0001, move on. |
| DDL missing `known_as_of` on a model-readable table | 🟡 WATCH | Silent, and surfaces as an inexplicably good backtest in P7. |
| Backup never actually restored | 🟡 WATCH | Ten minutes to eliminate entirely. |
| P0 expands to fill available time | 🟡 WATCH | It is enjoyable, unblocked work with no external dependency, which is exactly why it can run long. If you are past nine days, cut items 6, 7 and 9 and come back after P1. |
| Monorepo layout wrong | 🟢 SOLID | Cheap to change now, and CI catches direction violations. |

## What you will be tempted to skip, and what it costs later

| Shortcut | Feels like | Actually costs |
|---|---|---|
| "I'll add auth when there are real users" | Saves a day | The entire multi-user retrofit. [CLAUDE.md](../CLAUDE.md) names this specifically as the expensive shortcut. |
| "Provenance columns can come later" | Saves an hour | Every row inserted before that day has no provenance and cannot get it — the source PDF page is not recoverable after the fact. |
| "`known_as_of` is the same as `as_of_date`" | Saves thinking | A P7 backtest that looks profitable and is not. The most expensive possible bug, because it looks like success. |
| "I'll test the restore when I need it" | Saves ten minutes | The one unrecoverable failure in the project. |
| "The licensing register is bureaucracy" | Saves an hour | [PROJECT_CONTEXT.md 9.3](../PROJECT_CONTEXT.md): the question that kills the deal. |

---

# P1 — Macro Backdrop (v0.1)

**Spec version:** v0.1 · **Tasks:** T1 + **TG8** (minimal scheduler) · **Effort:** 2–4 working days

## In one sentence

At the end of P1 you open a browser to a local dashboard and see Nigeria's inflation rate,
policy rate, GDP, and debt position next to US rates — each figure carrying the date it was
published and a visible flag if it has gone stale.

## Why this phase is here now

Three reasons, in order of importance:

1. **It proves the pattern everything else reuses.** [TEAM_BRIEF.md 267](../TEAM_BRIEF.md) says
   exactly this: v0.1 "proves the provenance-and-charting pattern that everything else reuses."
   Connector → normalized store → API → thin client → as-of date on screen. Get that loop right
   once on easy data, and every later connector is a variation on it.
2. **Macro is the easiest real data in the project.** FRED has a free, documented, stable REST
   API. Nothing about it is hard. That makes it the correct place to make your infrastructure
   mistakes.
3. **It is genuinely useful on its own.** [PROJECT_CONTEXT.md 2](../PROJECT_CONTEXT.md)
   describes the painful status quo of assembling Nigerian macro context by hand from PDFs.
   Even data-only, this replaces real manual work.

## Entry criteria

- [ ] P0 exit criteria all met — in particular the API runs and the mode gate is tested
- [ ] A free FRED API key obtained (`fred.stlouisfed.org` → My Account → API Keys)
- [ ] Each source registered in `data_sources` with `redistribution_allowed` set (TG5)

## Manual work required first

| Task | Role | Effort | Blocking? |
|---|---|---|---|
| **H. Monthly macro download** ([TEAM_BRIEF 2.2-H](../TEAM_BRIEF.md)) | Collector | ~30 min/month | Parallel — this is the manual fallback that keeps data flowing while scrapers are written |
| Decide the starting series list | Owner | ~1 hour | Blocking — you cannot build a dashboard without knowing what goes on it |

**A concrete starting series list.** Ten series is enough for v0.1 and small enough to finish:

| Series | Source | Why it is on the list |
|---|---|---|
| Nigeria headline CPI (y/y) | NBS (manual/scrape), FRED mirror `FPCPITOTLZGNGA` | The single most-quoted Nigerian number |
| Nigeria core CPI | NBS | Headline is distorted by food and energy |
| MPR (Monetary Policy Rate) | CBN | The discount-rate anchor for every valuation you will do |
| NFEM official FX rate (USD/NGN) | CBN | Needed as a first-class table anyway (TG2) |
| Nigeria real GDP growth (q/q, y/y) | NBS | Rebased to 2019, backcast to 1981 |
| Nigeria total public debt | DMO | Sovereign risk backdrop |
| FGN bond stop rates | DMO | The domestic risk-free curve |
| US Fed Funds rate | FRED `FEDFUNDS` | The global discount anchor |
| US CPI (y/y) | FRED `CPIAUCSL` | Global inflation backdrop |
| US 10-year Treasury | FRED `DGS10` | Global risk-free rate |

## The build, task by task

### P1.1 — The connector base class

Before the first connector, define the interface every connector will implement forever
([DATA_FOUNDATION.md 4.3](../DATA_FOUNDATION.md), OpenBB-inspired). Full contract in
[08_DATA_CONTRACTS.md](08_DATA_CONTRACTS.md) §5.

The parts that matter and are easy to omit:

- **`declare_licence()`** — returns the `data_sources` row. A connector that cannot state its
  redistribution rights raises at registration and never runs. This is **TG5** made executable.
- **`rate_limit`** — declared, not remembered. EDGAR's ≤10 req/s in P2 comes with a ~10-minute
  IP block if exceeded ([DATA_FOUNDATION.md C](../DATA_FOUNDATION.md)); you want that encoded,
  not in your head.
- **`fetch()` returns raw, `parse()` returns normalized.** Two steps, always. The raw response
  is written to object storage before parsing, so that when a parse is wrong in six months you
  can re-parse without re-fetching — and without hoping the source still has the page.
- **Every emitted record carries `as_of_date` and `known_as_of`.** For macro these differ
  meaningfully: Nigerian CPI for August is published in mid-September. `as_of_date` is August;
  `known_as_of` is the publication date. Getting this right here, on easy data, is rehearsal for
  P7 where getting it wrong invents profit that does not exist.

### P1.2 — FRED connector

🟢 **SOLID.** Free key, documented REST API, stable for years, ALFRED gives true vintages.

`GET https://api.stlouisfed.org/fred/series/observations?series_id=FEDFUNDS&api_key=...&file_type=json`

Store to `macro_series` / `macro_observations`. Use the ALFRED vintage endpoints where you can —
they give you `known_as_of` for free, which is the hard part elsewhere.

### P1.3 — CBN, NBS, DMO connectors

🔴 **FRAGILE — none of these has a REST API. All three require scraping HTML listings and
parsing PDF or Excel** ([DATA_FOUNDATION.md B](../DATA_FOUNDATION.md)). They will break, without
warning, when a government website is redesigned. [DATA_FOUNDATION.md 8.4](../DATA_FOUNDATION.md)
addresses exactly this scenario.

Three approaches:

**1. Scrape all three now, with the manual fallback wired in from day one (recommended).**
Write the scrapers, but also build the "upload a CSV" path that Collector task H feeds. The
scraper is the fast path; the human is the guaranteed path.
*For:* You get automation where it works and never block on it where it does not. The manual
path also serves P3's PDF upload, so it is not throwaway work.
*Against:* Two code paths per source from the start.

**2. Use the FRED/World Bank mirrors only, defer native scraping to P4.**
FRED carries ~94 World Bank Nigeria series ([DATA_FOUNDATION.md B](../DATA_FOUNDATION.md)).
*For:* One stable connector covers the headline Nigerian macro figures. P1 ships in two days
instead of four.
*Against:* Mirrors lag, and they do not carry MPR decisions, T-bill stop rates, or DMO auction
results at all. You would be building a Nigerian macro dashboard whose Nigerian sources are all
second-hand — which is precisely the weakness the product exists to fix.

**3. Manual-only for Nigeria in P1; scrapers in P4 alongside the PDF pipeline.**
*For:* Zero scraper fragility now; the PDF-parsing muscle you build in P4 is the same muscle
these need, so doing them together is more efficient.
*Against:* 30 min/month of human work continues for months, and the dashboard's freshness
depends on you remembering.

**Recommendation: 1, with a scope cut.** Scrape **CBN rates** (the MPR and FX pages are simple
HTML with Excel export) and take **NBS CPI and GDP from the FRED/World Bank mirror** for now,
with the manual CSV path as the guaranteed fallback for both. Defer **DMO PDF scraping to P4**,
where the PDF toolchain already exists — parsing an auction-results PDF is the same problem as
parsing an annual report, and doing it twice is waste.

**Early-warning signal for all three:** a connector that returns HTTP 200 with zero new rows for
two consecutive expected release dates. That is the classic silent scraper failure — the page
still loads, the parser still runs, the selector matches nothing. It is caught by the
`connector_runs` health table ([OPERATIONS.md 2.3](../OPERATIONS.md)), which is why P1.5 exists.

### P1.4 — API endpoints

| Endpoint | Mode | Returns |
|---|---|---|
| `GET /public/macro/series` | public | List of available series with as-of dates and staleness flags |
| `GET /public/macro/series/{id}/observations?from=&to=` | public | The observation array |

Macro data is public-tier in every mode — it is published government statistics, no advice
attaches to it. Note that "public tier" here means the *content class*, not who can log in
today; access is still owner + family ([CLAUDE.md](../CLAUDE.md) access model).

### P1.5 — Minimal scheduler and connector health (TG8)

**TG8** — nothing in [SPEC.md 3.1](../SPEC.md) owns job scheduling, though
[DATA_FOUNDATION.md 3.5](../DATA_FOUNDATION.md) names APScheduler.

Minimal version for P1: APScheduler in `/packages/scheduler`, one job per connector, and every
run writes a `connector_runs` row — `started_at`, `finished_at`, `status`, `rows_written`,
`error`. The `rows_written` column is the one that catches silent failure, so it is not
optional.

### P1.6 — The Streamlit dashboard

Per **AD-3**, this is a thin client. It calls `requests.get("http://localhost:8000/public/...")`
and renders. **No SQL in the Streamlit app. No calculations in the Streamlit app.** If you find
yourself computing a year-on-year change in a Streamlit callback, that belongs in
`/packages/valuation` behind the API.

Every chart and every figure shows its **as-of date**, and anything past its expected refresh
window renders with a visible staleness flag ([CLAUDE.md](../CLAUDE.md): "Staleness is
visible"). Do not use a subtle grey; the point is that you cannot miss it.

## Expected inputs

```
FRED:  https://api.stlouisfed.org/fred/series/observations
       ?series_id=FEDFUNDS&api_key=<KEY>&file_type=json
CBN:   https://www.cbn.gov.ng/rates/            (HTML, "Export to Excel")
NBS:   https://nigerianstat.gov.ng/             (HTML listing → PDF/XLSX)
       https://microdata.nigerianstat.gov.ng/   (catalog/154 = CPI)
DMO:   https://www.dmo.gov.ng/                  (docman PDFs)
```

**A real FRED response, trimmed:**

```json
{
  "realtime_start": "2026-08-28",
  "observations": [
    {"realtime_start":"2026-08-01","realtime_end":"9999-12-31",
     "date":"2026-07-01","value":"4.33"}
  ]
}
```

Note that `date` (2026-07-01) is the `as_of_date` and `realtime_start` (2026-08-01) is the
`known_as_of`. FRED hands you both. Most sources will not.

## Expected outputs

**Database:**

```
macro_series
| id | code       | name                  | source | unit    | freq    | expected_lag_days |
|----|------------|-----------------------|--------|---------|---------|-------------------|
| 1  | NG_CPI_YOY | Nigeria headline CPI  | NBS    | percent | monthly | 20                |
| 2  | NG_MPR     | Monetary Policy Rate  | CBN    | percent | irregular| 3                |

macro_observations
| series_id | as_of_date | known_as_of | value | source_document_id | revision |
|-----------|------------|-------------|-------|--------------------|----------|
| 1         | 2026-07-31 | 2026-08-15  | 22.22 | 41                 | 1        |
```

**API:**

```json
GET /public/macro/series
[{"id":1,"code":"NG_CPI_YOY","name":"Nigeria headline CPI",
  "latest_as_of":"2026-07-31","known_as_of":"2026-08-15",
  "latest_value":22.22,"unit":"percent","stale":false,
  "source":{"name":"NBS","document_id":41,"url":"https://..."}}]
```

**Screen:** a dashboard with ten series, each showing value, as-of date, source link, and a
staleness flag where overdue.

## TEST CHECKPOINT — P1

| # | Check | Command | Expected |
|---|---|---|---|
| 1 | Connector fetches | `pytest tests/unit/test_fred_connector.py` | Pass |
| 2 | Parse is deterministic | Re-parse a stored raw response | Byte-identical output |
| 3 | Provenance present | `SELECT count(*) FROM macro_observations WHERE source_document_id IS NULL` | `0` |
| 4 | Both dates present | `SELECT count(*) FROM macro_observations WHERE known_as_of IS NULL` | `0` |
| 5 | Staleness computes | Set a series' `as_of` back 90 days | Renders with a stale flag |
| 6 | Licence gate | Try registering a connector with no licence row | Raises at registration |
| 7 | Scheduler writes health | Run a job | A `connector_runs` row with `rows_written > 0` |
| 8 | Silent-failure detection | Point a scraper at a page with no data | `status='ok'` but `rows_written=0` **is flagged** |
| 9 | Thin client holds | `grep -rE "psycopg\|sqlalchemy\|SELECT " apps/streamlit/` | No matches |
| 10 | Mode gate still holds | `pytest tests/compliance` | All pass |

**By hand and by eye:**

11. **Open the dashboard next to the source website.** Put the CBN MPR page in one tab and your
    dashboard in another. Confirm the number matches *and the date matches*. A right number with
    the wrong date is a wrong number — it means your `as_of_date` mapping is broken, and that
    bug will propagate silently into every valuation that discounts at this rate.

12. **Check one figure against its PDF.** Take the NBS CPI figure, open the actual NBS release,
    find the number on the page. Confirm the value, the reference month, and the publication
    date. This is the first exercise of the reconciliation habit that
    [07_TEST_STRATEGY.md](07_TEST_STRATEGY.md) §8 makes routine.

13. **Unplug the internet and reload the dashboard.** It should render stored data with stale
    flags, not crash. Your dashboard must be readable when a government website is down, because
    government websites go down.

## Exit criteria

- [ ] Checks 1–13 pass
- [ ] Ten series populated with real values, provenance, and both date columns
- [ ] Dashboard renders every series with as-of date and staleness flag
- [ ] `connector_runs` populated; a zero-row run is flagged
- [ ] No SQL or arithmetic in `apps/streamlit/`
- [ ] Tracker in [00_START_HERE.md](00_START_HERE.md) §6 updated

## What could go wrong

| Risk | Marker | Detail / early warning |
|---|---|---|
| CBN/NBS/DMO scrapers break on redesign | 🔴 FRAGILE | Three approaches in P1.3. Warning: 200 OK with 0 rows. |
| `as_of` vs `known_as_of` conflated | 🔴 FRAGILE | Silent. Poisons P7. Test 4 and 11 catch it. Get it right here where it is easy. |
| Logic creeps into Streamlit | 🟡 WATCH | Warning: any `import pandas` in `apps/streamlit/` doing more than display. Test 9. |
| Nigerian revisions overwrite history | 🟡 WATCH | CPI was rebased to 2024 base and GDP to 2019 ([DATA_FOUNDATION B](../DATA_FOUNDATION.md)); rebasing changes past values. Store revisions, never overwrite ([CLAUDE.md](../CLAUDE.md)). |
| FRED connector | 🟢 SOLID | Free, documented, stable. Worst case is a key rotation. |
| Streamlit charting | 🟢 SOLID | Boring and well-trodden. |

## What you will be tempted to skip

| Shortcut | Costs |
|---|---|
| "One date column is enough for macro" | The exact bug that makes P7 lie to you. |
| "I'll query the DB directly from Streamlit, it's faster" | The P9 Next.js swap becomes a rewrite instead of a re-skin. |
| "Staleness flags are cosmetic" | You quote a six-month-old FX rate in a valuation and never notice. |

---

# P2 — US Company Data (v0.2)

**Spec version:** v0.2 · **Tasks:** T2 + **TG1-US** (price history) + **TG7** (chart of accounts,
draft) · **Effort:** 4–7 working days

## In one sentence

At the end of P2 you type `AAPL`, and see its income statement, balance sheet and cash flow
from real SEC filings, a set of computed ratios, and a DCF that runs on *your* assumptions —
with every figure traceable to the filing it came from.

## Why this phase is here now

Because US data is clean, free, structured, and legally unambiguous, and Nigerian data is none
of those things. EDGAR gives you XBRL — financial statements already tagged machine-readably. So
P2 lets you build and debug the entire downstream stack (normalization, ratios, DCF, valuation
UI, provenance display) against data that is *not* fighting you. When P3 and P4 bring Nigerian
PDFs, the only new problem is extraction, because everything after extraction is already proven.

Building the Nigerian pipeline first would mean debugging extraction and valuation
simultaneously, with no way to tell which layer is wrong.

## Entry criteria

- [ ] P1 complete; the connector pattern is proven
- [ ] A descriptive `User-Agent` string decided: EDGAR **requires** name + email, and enforces
      it ([DATA_FOUNDATION.md C](../DATA_FOUNDATION.md))
- [ ] The company universe (TEAM_BRIEF task A) at least drafted for the US side

## Manual work required first

| Task | Role | Effort | Blocking? |
|---|---|---|---|
| **G. Build the canonical chart of accounts** ([TEAM_BRIEF 2.2-G](../TEAM_BRIEF.md)) | Curator, needs accounting knowledge | ~2 days | **Partially blocking — start the draft here (TG7)** |

**TG7 matters more than it looks.** The canonical chart of accounts is the normalization target:
one internal key per financial concept, that every source maps onto. Draft it in P2 against
US GAAP/XBRL tags, where the tagging is already standardized and will teach you the shape. Then
**freeze v1 in P3** when Nigerian IFRS statements reveal what it is missing.

Why freezing matters: change the chart of accounts after the extractor has run over 200
company-years and you must re-extract all of them. Version it from the first day
(`chart_version` on every mapping) so a change is a migration, not a catastrophe.

## The build, task by task

### P2.1 — EDGAR connector

🟢 **SOLID**, with one hard operational rule.

```
https://data.sec.gov/api/xbrl/companyfacts/CIK0000320193.json
```

Non-negotiables from [DATA_FOUNDATION.md C](../DATA_FOUNDATION.md):
- **Zero-pad the CIK to 10 digits.** `320193` → `CIK0000320193`.
- **Descriptive `User-Agent` with name and email.** Required; requests without it are refused.
- **≤10 requests/second — use a ~0.12s delay.** Exceeding it returns 403/429 and gets your IP
  blocked for ~10 minutes. Encode this in the connector's declared `rate_limit`, not in your
  memory.
- For bulk work, prefer the nightly `companyfacts.zip` / `submissions.zip` over thousands of
  individual calls.

### P2.2 — Normalization to the canonical chart of accounts

XBRL tags (`us-gaap:Revenues`, `us-gaap:RevenueFromContractWithCustomerExcludingAssessedTax`,
…) map to your internal keys. Store the mapping as data in a table, not as a Python dict — it
will be edited by a human many times, and a table gives you versioning and an audit trail for
free.

**The rule that outranks convenience:** if a company does not report a line item, the value is
**null**. Never zero, never interpolated, never derived from a sibling.
[SPEC.md 4.1](../SPEC.md): "Never infer missing financial data." A null is honest and visibly
missing; a zero is a lie that silently flows into every ratio computed from it.

### P2.3 — Price history for US securities (TG1-US)

**This task does not exist in [SPEC.md 4.2](../SPEC.md).** T9 (indicators, P6) and T11
(backtest, P7) both consume `price_history`, and no SPEC task fills it. This is **TG1** and this
is where its US half lands.

🟡 **WATCH — the source choice is a known cost curve.**
[DATA_FOUNDATION.md C](../DATA_FOUNDATION.md) rates `yfinance` as "free, fragile, fine for
personal US" and recommends starting there, upgrading to FMP (~$22/mo) for clean fundamentals.
Start with yfinance behind the connector interface. Because the interface is the contract,
swapping the provider later is a connector change, not a system change.

**Store both raw and adjusted prices, in separate columns.** Never overwrite raw with adjusted.
This is what makes the corporate-actions work in P3 (TG2) possible — you cannot recompute an
adjustment you have destroyed.

### P2.4 — Ratios and DCF

🟢 **SOLID.** The arithmetic is textbook, deterministic, and exactly testable with hand-computed
vectors ([SPEC.md 4.4](../SPEC.md) known-answer tests). Full contracts in
[08_DATA_CONTRACTS.md](08_DATA_CONTRACTS.md) §6.

**The design rule that matters:** the DCF takes assumptions as *explicit inputs* — growth,
margin, WACC, terminal growth — and never chooses them for the user. It returns the output
*and* the inputs that produced it. [DATA_FOUNDATION.md 1.4](../DATA_FOUNDATION.md)'s
"instrument, not judgment" rules apply, and [CLAUDE.md](../CLAUDE.md)'s "show the work in every
mode" means the assumption set travels with the answer in personal mode too.

Every ratio returns `null` when an input is null. A P/E where earnings are missing is not
infinity and not zero — it is unknown, and it must say so.

## Expected inputs

```json
GET https://data.sec.gov/api/xbrl/companyfacts/CIK0000320193.json
User-Agent: Frank Nnatuanya nnatuanyafrank@gmail.com

{"cik":320193,"entityName":"Apple Inc.","facts":{"us-gaap":{
  "Revenues":{"units":{"USD":[
    {"start":"2024-09-29","end":"2025-09-27","val":416161000000,
     "accn":"0000320193-25-000073","fy":2025,"fp":"FY","form":"10-K",
     "filed":"2025-10-31","frame":"CY2025"}
  ]}}}}}
```

`filed` is the `known_as_of`. `end` is the `as_of_date`. They are different, and the difference
is the whole point.

## Expected outputs

```
statement_line_items
| security_id | period_end | canonical_key | value        | unit | known_as_of | filing_id | page |
|-------------|------------|---------------|--------------|------|-------------|-----------|------|
| 1           | 2025-09-27 | revenue       | 416161000000 | USD  | 2025-10-31  | 883       | NULL |
| 1           | 2025-09-27 | gross_profit  | 195000000000 | USD  | 2025-10-31  | 883       | NULL |
| 1           | 2025-09-27 | rd_expense    | NULL         | USD  | 2025-10-31  | 883       | NULL |
```

That `NULL` is correct behaviour, not a bug, if the tag was absent.

```json
GET /public/companies/AAPL/ratios?period=2025-FY
{"security":"AAPL","period_end":"2025-09-27","known_as_of":"2025-10-31",
 "ratios":{"gross_margin":0.4686,"net_margin":null,"current_ratio":0.8673},
 "provenance":{"filing_id":883,"form":"10-K","url":"https://www.sec.gov/..."}}
```

## TEST CHECKPOINT — P2

| # | Check | Command | Expected |
|---|---|---|---|
| 1 | CIK zero-padding | `pytest tests/unit/test_edgar.py -k cik` | `320193` → `CIK0000320193` |
| 2 | Rate limit respected | Fetch 50 companies, time it | ≥0.12s between calls; no 403/429 |
| 3 | User-Agent sent | Inspect the request | Contains name and email |
| 4 | Missing items are null | Ingest a company lacking R&D | `value IS NULL`, not `0` |
| 5 | Ratio known-answer | `pytest tests/known_answer/test_ratios.py` | Matches hand-computed vectors |
| 6 | DCF known-answer | `pytest tests/known_answer/test_dcf.py` | Matches a hand-built spreadsheet |
| 7 | Null propagates | Ratio with a null input | Returns `null`, not 0 or ∞ |
| 8 | `known_as_of` = filing date | `SELECT known_as_of, period_end FROM ...` | `known_as_of` is the `filed` date and is later |
| 9 | Raw prices preserved | `SELECT close_raw FROM price_history` at a split boundary | As-traded, never adjusted — there is **no `close_adj` column** ([08](08_DATA_CONTRACTS.md) §2.4, corrected 2026-08-30): adjusted prices are derived at read time up to the decision date, from `corporate_actions` |
| 10 | Chart of accounts versioned | Check the mapping table | Every row carries `chart_version` |
| 11 | Provenance on every figure | `SELECT count(*) ... WHERE filing_id IS NULL` | `0` |
| 12 | Compliance still green | `pytest tests/compliance` | All pass |

**By hand and by eye:**

13. **Open Apple's actual 10-K and check three numbers.** Revenue, total assets, and one you
    expect to be missing. Compare against your database. This is the single most valuable check
    in P2 — it validates the entire chain from fetch through normalization to storage, and no
    automated test substitutes for having seen it with your own eyes once.

14. **Run a DCF twice with one assumption changed** (WACC 9% → 10%). Confirm the value moves in
    the right direction and by a plausible magnitude. If a 100bp WACC change barely moves the
    answer, your terminal value is probably wrong.

15. **Pick a company that restated.** Confirm you hold both versions and that querying "as known
    on [date before the restatement]" returns the *original* figures. This is point-in-time
    correctness, and P7 depends on it absolutely.

## Exit criteria

- [ ] Checks 1–15 pass
- [ ] ≥20 US companies ingested end to end
- [ ] Ratios and DCF run from user assumptions, returning inputs alongside outputs
- [ ] `price_history` populated with as-traded prices, splits held apart (TG1-US closed; no stored adjusted column, [08](08_DATA_CONTRACTS.md) §2.4)
- [ ] Chart of accounts drafted and versioned (TG7 drafted, freeze deferred to P3)
- [ ] Tracker updated

## What could go wrong

| Risk | Marker | Detail |
|---|---|---|
| Missing values become zeros | 🔴 FRAGILE | Silent and corrupting. It happens through pandas defaults — `fillna(0)` anywhere in this path is a defect. Test 4 and 7. |
| Chart of accounts churns after extraction begins | 🔴 FRAGILE | TG7. Versioning it now is the mitigation; freezing v1 in P3 is the discipline. |
| EDGAR IP block | 🟡 WATCH | ~10-minute block on exceeding 10 req/s. Encode the delay in the connector. Warning: any 403/429. |
| yfinance breaks | 🟡 WATCH | Known-fragile. Mitigated by the connector interface. Warning: schema change or empty frames. |
| EDGAR data quality | 🟢 SOLID | XBRL is regulator-mandated and consistent. |
| Ratio/DCF math | 🟢 SOLID | Textbook, deterministic, exactly testable. |

## What you will be tempted to skip

| Shortcut | Costs |
|---|---|
| `fillna(0)` to make a chart render | Every downstream ratio silently wrong; no exception ever raised. |
| "I'll store only adjusted prices" | You can never recompute adjustments when TG2 lands in P3. |
| "Chart of accounts can be a Python dict" | No versioning, no audit trail, and a re-extraction when it changes. |
| Skipping check 13 | You would be trusting a pipeline no human has ever verified end to end. |

---

# P3 — Nigerian Manual Analyzer (v0.3)

**Spec version:** v0.3 · **Tasks:** T3 + **TG2** (correctness substrate) + **TG6** (golden set) +
**TG7** (freeze v1) + **TG10** (manual override) · **Effort:** 4–6 working days of code, plus
substantial manual work

## In one sentence

At the end of P3 you upload a Nigerian annual-report PDF, type its figures into a structured
form, and get the same normalized statements, ratios, and provenance you already get for US
companies — plus the correctness substrate that stops Nigerian price data from silently lying
to you.

## Why this phase is here now

P3 is the phase people want to skip, and skipping it is why the project would fail. It does
three things:

1. **It makes the target concrete before automating it.** You cannot write an extractor for a
   shape you have not seen. Typing in three annual reports by hand teaches you what Nigerian
   IFRS statements actually look like — which is the input P4's extractor needs, and which no
   amount of specification substitutes for.
2. **It produces the golden test set (TG6).** [TEAM_BRIEF.md 2.2-C](../TEAM_BRIEF.md) calls this
   "the highest leverage task in the project." Hand-verified PDF → expected-JSON pairs are the
   *only* way to know whether P4's automated extraction is working. **No SPEC task creates
   them, and T4's acceptance criteria assume they exist.** They are created here.
3. **It lands the correctness substrate (TG2).** Corporate actions, trading calendar, FX,
   ticker history. These must exist before any Nigerian price series is consumed by anything.

## Entry criteria

- [ ] P2 complete — the normalization and valuation stack is proven on clean data
- [ ] Seed document set collected (TEAM_BRIEF task B) — ideally 20+ company-years of PDFs
- [ ] Company universe finalized (TEAM_BRIEF task A)

## Manual work required first

This phase is **mostly manual work**, and the code is the smaller half. Plan for it honestly.

| Task | Role | Effort | Blocking? |
|---|---|---|---|
| **C. Build the golden test set** ([TEAM_BRIEF 2.2-C](../TEAM_BRIEF.md)) | Reviewer + Curator | ~2–3 days | **Critical — blocks P4's gate** |
| **D. Manual data entry** ([TEAM_BRIEF 2.2-D](../TEAM_BRIEF.md)) | Data-entry analyst | ~2–4 hrs per company-year | Blocking for content |
| **E. Backfill corporate actions** ([TEAM_BRIEF 2.2-E](../TEAM_BRIEF.md)) | Collector + Reviewer | ~2–3 days | Blocking for TG2 |
| **F. Seed the ticker alias table** ([TEAM_BRIEF 2.2-F](../TEAM_BRIEF.md)) | Curator | ~half a day, ongoing | Needed for P5 news tagging |
| **G. Freeze chart of accounts v1** | Curator | ~1 day on top of P2's draft | Blocking for P4 |

At 2–4 hours per company-year, ten company-years is 20–40 hours of typing. That is the real
shape of this phase and there is no way around it — see
[06_RISK_REGISTER.md](06_RISK_REGISTER.md) on review capacity as the ceiling.

## The build, task by task

### P3.1 — PDF upload and document store

Upload a PDF; store it immutably in object storage; create a `source_documents` row with hash,
page count, and metadata. **Immutable** means the stored file is never modified or replaced —
every extracted figure points at a page in *this exact file*, forever. If a company reissues its
report, that is a new document, not an edit.

### P3.2 — Manual entry form

A Streamlit form (thin client, per AD-3) showing the PDF page beside the input fields, writing
through the API to `statement_line_items` with full provenance: `source_document_id`, `page`,
`as_of_date`, `known_as_of`, `extraction_method='manual'`, `reviewed_by`.

The form enforces the same rules as everything else: **a field left blank stores null, never
zero** ([SPEC.md 4.1](../SPEC.md)).

### P3.3 — The correctness substrate (TG2) — the most important work in this phase

[OPERATIONS.md Part 1](../OPERATIONS.md) calls corporate actions "the highest-priority gap".
Nothing in T1–T21 schedules any of it. Here is what each one is and the concrete bug it prevents.

**Corporate actions** ([OPERATIONS.md 1.1](../OPERATIONS.md)) — splits, bonus issues, rights
issues, dividends.

*The worked example.* A stock trades at ₦100. It does a 2-for-1 split: every holder now has two
shares worth ₦50 each. Nobody gained or lost anything. But your raw `price_history` shows ₦100
yesterday and ₦50 today — a 50% crash. Now: your RSI screams oversold. Your volatility estimate
doubles. Your backtest sees a catastrophic loss that never happened, or, if the strategy was
short, a windfall that never happened. **No error is raised anywhere.** The number is wrong and
plausible, which is the worst combination in this project.

The fix is an adjustment factor computed from the corporate-actions table and applied to produce
`close_adj` from `close_raw`. This is why P2.3 insisted on storing both.

**Trading calendar** ([OPERATIONS.md 1.2](../OPERATIONS.md)) — which days the NGX was actually
open. Without it, a Nigerian public holiday looks like a day of zero return, which distorts
volatility, and a gap looks like missing data rather than a closed market.

**FX as a first-class table** ([OPERATIONS.md 1.3](../OPERATIONS.md)) — with the rate's own
as-of date. A Naira figure converted at *today's* rate rather than the rate on the statement
date is wrong, and given the Naira's history it can be wrong by a very large multiple.

**Stable identity and ticker history** ([OPERATIONS.md 1.4](../OPERATIONS.md)) — tickers get
reused and companies rename. If your primary key is the ticker, a rename silently merges two
different companies' histories into one series. Use a surrogate `security_id`; make the ticker a
time-bounded attribute.

**Fiscal period alignment** ([OPERATIONS.md 1.5](../OPERATIONS.md)) — not every company's year
ends in December. Comparing a June-year-end to a December-year-end as though they were the same
period is a category error that produces confident nonsense.

**One unit conversion point** ([OPERATIONS.md 1.6](../OPERATIONS.md)) — Nigerian statements
report in thousands or millions of Naira, inconsistently, sometimes changing between sections of
the same document. One function converts; nothing else is allowed to. A figure off by 1,000× is
usually obvious; off by 1,000× on *one line item among forty* is not.

> 🔴 **FRAGILE — this is the highest-value, most-skipped work in the first half of the project.**
> Every item above fails *silently*. Three approaches to sequencing it:
>
> **1. Build all six now, fully, before any Nigerian price data is consumed (recommended).**
> *For:* Nothing downstream is ever computed on corrupt inputs. P6 and P7 inherit correctness.
> *Against:* Two to three days plus the manual backfill, in a phase already heavy with typing,
> with nothing visible to show for it.
>
> **2. Build the schema now, populate lazily per company as needed.**
> *For:* Spreads the manual backfill over time; the structure is right immediately.
> *Against:* You must track which securities are adjusted and which are not, and every consumer
> must check. In practice that check gets forgotten exactly once, and that is enough.
>
> **3. Defer to P6, just before indicators need it.**
> *For:* Ships P3 faster.
> *Against:* By P6 you have months of stored prices and derived values to recompute, and you
> will be doing correctness work under pressure to start the interesting part. This is how it
> gets skipped.
>
> **Recommendation: 1, with a scope cut on volume rather than on structure.** Build all six
> tables and all six code paths now, and backfill corporate actions for your *initial universe
> only* (TEAM_BRIEF task E). Adding a company later then means backfilling one company, which
> is a known, bounded, repeatable task rather than a project.

### P3.4 — The golden test set (TG6)

For each of ~10 chosen company-years: the PDF, plus a hand-verified JSON of expected values,
**double-checked by a second person** ([TEAM_BRIEF 2.2-C](../TEAM_BRIEF.md)). Stored in
`tests/golden/`, version-controlled, and treated as the specification of correct extraction.

**Choose deliberately for coverage, not convenience.** Include at least two banks —
[TEAM_BRIEF.md Part 3](../TEAM_BRIEF.md) warns that "banks break everything built for
industrials", because their statement structure genuinely differs (interest income rather than
revenue, a fundamentally different balance sheet shape). A golden set of only industrials will
tell you your extractor works, right up until it meets a bank.

### P3.5 — The manual override (TG10)

[PROJECT_CONTEXT.md 7](../PROJECT_CONTEXT.md) requires "a dead-simple manual override… with a
note recording who changed it and why", and [CLAUDE.md](../CLAUDE.md) forbids silent overwrites.
T4's review queue covers *new* extractions only, not correcting a figure already stored and
already on screen.

Implementation: a correction writes a **new version** of the row with `superseded_by`,
`corrected_by`, `corrected_at`, and `reason`. The old value is never deleted. The UI shows the
current value with an indicator that it was corrected, and the history on request.

## Expected inputs

- Nigerian annual report PDFs, typically 100–400 pages, mixed text and scanned images
- Corporate-action records, hand-collected from NGX disclosures and company announcements
- NGX trading-calendar dates (public holidays)
- Human attention: 2–4 hours per company-year

## Expected outputs

```
statement_line_items (extraction_method='manual')
| security_id | period_end | canonical_key | value      | unit | scale     | page | reviewed_by |
|-------------|------------|---------------|------------|------|-----------|------|-------------|
| 44          | 2025-12-31 | revenue       | 1450000000 | NGN  | thousands | 87   | frank       |

corporate_actions
| security_id | ex_date    | type  | ratio_from | ratio_to | source_document_id |
|-------------|------------|-------|------------|----------|--------------------|
| 44          | 2025-06-14 | split | 1          | 2        | 219                |
```

And `tests/golden/GTCO_2025.pdf` + `tests/golden/GTCO_2025.expected.json`.

## TEST CHECKPOINT — P3

| # | Check | Command | Expected |
|---|---|---|---|
| 1 | Document immutability | Re-upload the same PDF | Same hash detected; no duplicate row |
| 2 | Provenance complete | `SELECT count(*) FROM statement_line_items WHERE page IS NULL AND extraction_method='manual'` | `0` |
| 3 | Blank → null | Leave a field empty | Stores `NULL`, not `0` |
| 4 | **Split adjustment** | `pytest tests/unit/test_corporate_actions.py` | A 2-for-1 split produces a *continuous* adjusted series — no artificial 50% drop |
| 5 | Trading calendar | Query a Nigerian public holiday | Marked closed, not a zero-return day |
| 6 | FX date correctness | Convert a 2023 figure | Uses the 2023 rate, not today's |
| 7 | Ticker history | Simulate a rename | Series stays attached to `security_id`, does not merge with the reused ticker |
| 8 | Fiscal alignment | Compare a June and a December year-end | Flagged as non-comparable |
| 9 | Unit conversion | Statement in thousands | Stored value is correct at 1,000× scale; `scale` recorded |
| 10 | Correction versioning | Correct a figure | Old row retained with `superseded_by`, reason, author |
| 11 | Golden set validates | `pytest tests/golden --collect-only` | ≥10 pairs, including ≥2 banks |
| 12 | Ratios work on NG data | Run P2's ratio engine on a Nigerian company | Same output shape as US |
| 13 | Compliance green | `pytest tests/compliance` | All pass |

**By hand and by eye:**

14. **Two people, one statement.** Have a second person independently type the same
    company-year, then diff. Every disagreement is either a typo or — more valuably — an
    ambiguity in your chart of accounts that would have silently corrupted the automated
    extractor in P4. This is the exercise that makes the golden set trustworthy.

15. **Plot a raw and an adjusted price series through a known split, side by side.** Look at
    them. The raw series has a cliff; the adjusted series does not. Seeing this once is what
    makes the corporate-actions work feel necessary rather than bureaucratic.

16. **Read your own chart of accounts against a bank's income statement.** Before freezing v1,
    confirm it can express "interest income", "net interest margin", and "loan loss provision".
    If it cannot, freezing now guarantees re-extraction later.

## Exit criteria

- [ ] Checks 1–16 pass
- [ ] ≥10 company-years entered manually with full provenance
- [ ] All six TG2 correctness tables built, populated for the initial universe, and tested
- [ ] Golden set ≥10 pairs, double-checked, ≥2 banks, in `tests/golden/`
- [ ] Chart of accounts **v1 frozen and versioned** (TG7 closed)
- [ ] Manual override with versioned corrections working (TG10 closed)
- [ ] Ticker alias table seeded (TEAM_BRIEF task F)
- [ ] Tracker updated

## What could go wrong

| Risk | Marker | Detail |
|---|---|---|
| Corporate actions skipped or partial | 🔴 FRAGILE | Three approaches in P3.3. Silent corruption of everything downstream. |
| Golden set too small or unrepresentative | 🔴 FRAGILE | P4's gate is meaningless without it. Banks are the specific coverage gap. |
| Chart of accounts frozen too early | 🔴 FRAGILE | Check 16 is the mitigation. Re-extraction is the cost. |
| Manual entry errors | 🟡 WATCH | Two-person check on golden rows; sampling on the rest. Warning: a balance sheet that does not balance. |
| Manual entry burnout | 🟡 WATCH | 20–40 hours of typing. Warning: the pace dropping, or checks being skipped to finish. |
| Upload/storage mechanics | 🟢 SOLID | Ordinary file handling. |
| Ratio engine on NG data | 🟢 SOLID | Already proven in P2; this is reuse. |

## What you will be tempted to skip

| Shortcut | Costs |
|---|---|
| "Corporate actions later, no splits recently" | The one bug class that is invisible until P7 reports a strategy that never existed. |
| "Five golden files is enough" | P4's acceptance threshold becomes noise; you cannot tell a good extractor from a lucky one. |
| "No banks in the golden set, they're awkward" | [TEAM_BRIEF.md Part 3](../TEAM_BRIEF.md)'s named bottleneck, discovered at the worst time. |
| "I'll skip the second-person check" | The golden set becomes one person's assumptions, and P4 is then validated against those assumptions rather than against the PDF. |

---

# P4 — Nigerian Automated Ingestion (v0.4)

**Spec version:** v0.4 · **Tasks:** T4 + **TG1-NG** (NGX price history) + **TG8** (full scheduler
with health) · **Effort:** 3–6+ weeks — **budget 2–3× whatever you estimate**

## In one sentence

At the end of P4 a Nigerian annual-report PDF arrives, the system extracts its financial
statements automatically, validates them arithmetically, and either stores them or routes them
to a human review queue — and the correction the human makes teaches the next extraction.

## Why this phase is here now

Because this is the moat. [CLAUDE.md](../CLAUDE.md)'s one-line summary of the whole project is
that "the hard, valuable part is turning Nigerian financial PDFs into clean, queryable,
provenance-tracked data." Everything before P4 was preparation for it, and everything after it
consumes what it produces.

It is also, by unanimous verdict of the source documents, **the phase most likely to consume
your project.** [TEAM_BRIEF.md Part 3](../TEAM_BRIEF.md) heads its bottleneck list with "PDF
extraction is harder than it looks — *the one that eats months*", and states plainly: rules-based
extraction alone gets ~60%, and **every planning document says budget 2–3× your estimate.**

Read that sentence again before you start. The single most common way this project fails is
that P4 quietly becomes the whole project.

## Entry criteria

- [ ] P3 complete — **especially** the golden set (TG6) and the frozen chart of accounts (TG7)
- [ ] ≥10 golden PDF/JSON pairs including ≥2 banks
- [ ] The correctness substrate (TG2) is in place and tested
- [ ] An LLM API key with a spend cap configured
      ([02_INFRASTRUCTURE.md](02_INFRASTRUCTURE.md) §10)
- [ ] **The decision gate below is written down and you have agreed to honour it**

> ### The P4 decision gate — agree to this before you begin
>
> [TEAM_BRIEF.md Part 3](../TEAM_BRIEF.md) gives an explicit exit condition: *"hold the decision
> gate: below 85% after two weeks, buy EODHD and move on."*
>
> Write this on paper. The reason it is stated up front is that at week five, deep in
> per-layout tuning, with accuracy at 78% and climbing slowly, you will not want to stop — and
> that is exactly the moment the gate exists for. Buying a data feed is not a failure; spending
> four months to avoid a subscription while the rest of the product does not exist is.
>
> See [06_RISK_REGISTER.md](06_RISK_REGISTER.md) §8 for the full decision-gate set.

## Manual work required first

| Task | Role | Effort | Blocking? |
|---|---|---|---|
| **I. Ongoing extraction review** ([TEAM_BRIEF 2.2-I](../TEAM_BRIEF.md)) | Reviewer | **Permanent** | Not blocking to start, but it never ends |

That "permanent" is the honest framing. [TEAM_BRIEF.md Part 3](../TEAM_BRIEF.md) item 5 does the
arithmetic: ~20 corrections per filing × 25 companies filing quarterly ≈ **2,000 corrections a
year**. One reviewer is the ceiling on how much coverage the product can have. Design for
human-in-the-loop permanently rather than chasing full automation — that is the stated strategy,
not a compromise.

## The build, task by task

### P4.1 — The hybrid extraction pipeline

[DATA_FOUNDATION.md 3.1](../DATA_FOUNDATION.md) evaluated the toolchain honestly. The
recommended hybrid, in order, with the reasoning for each stage:

```mermaid
flowchart TD
    A["PDF arrives"] --> B{"Native text layer<br/>or scanned?"}
    B -->|native| C["PyMuPDF4LLM / pdfplumber<br/>text + Markdown tables — cheap"]
    B -->|scanned| D["OCR: tesseract + OpenCV"]
    C --> E["Claude with a STRICT JSON schema<br/>reconciles and maps to canonical keys"]
    D --> E
    E --> F["Deterministic validation<br/>arithmetic identities"]
    F -->|passes, confidence >= 0.85| G["Store with provenance"]
    F -->|fails or low confidence| H["Human review queue"]
    H --> I["Reviewer corrects"]
    I --> G
    I --> J["Correction stored as a<br/>few-shot example"]
    J -.improves.-> E
```

**Why this shape and not "just give the PDF to an LLM":** cost and verifiability. The cheap
deterministic tools do the bulk reading; the LLM is the *reconciliation brain*, not the pixel
reader. [DATA_FOUNDATION.md 3.1](../DATA_FOUNDATION.md) puts the accuracy lift at ~60%
(rules only) → **90%+** with this hybrid, while bounding the LLM spend.

**Tool roles, from [DATA_FOUNDATION.md 3.1](../DATA_FOUNDATION.md):**

| Tool | Use it for | Do not use it for |
|---|---|---|
| **pdfplumber** | Coordinate-level control; borderless tables via char positions; debugging | Bulk speed — needs per-layout tuning, ~60% alone on messy pages |
| **PyMuPDF / PyMuPDF4LLM** | Fast text dump and clean Markdown for LLM prompts | Precise complex tables |
| **camelot** | *Bordered* tables (lattice) only | Borderless tables — common in annual reports; also needs Ghostscript and is sparsely maintained in 2026 |
| **tabula-py** | Quick batch on clean text-layer PDFs | Wide tables (column-merge errors); adds a JVM dependency |
| **Docling / unstructured** | Mixed-format pipelines, RAG | Anything latency-sensitive — heavier and slower |
| **Claude (PDF/vision)** | Messy, borderless, scanned pages; semantic mapping | Reading every page — cost |

### P4.2 — The LLM extraction contract

[DATA_FOUNDATION.md 3.2](../DATA_FOUNDATION.md) specifies the system prompt, and its constraints
are not stylistic — each one prevents a specific failure:

> "You are a financial-statement data extractor. You receive text and tables from ONE company's
> audited statements. Extract ONLY numbers present in the source; never infer/estimate/fill
> gaps. Return JSON per schema. For each line item include source page and the verbatim label
> as printed. If absent, use null. Report values in the reporting currency/units exactly as
> stated, plus a `unit_multiplier`."

| Constraint | Prevents |
|---|---|
| "ONE company's statements" | Cross-contamination between the parent and subsidiary statements that sit in the same PDF |
| "never infer/estimate/fill gaps" | The single most dangerous LLM behaviour here — a plausible fabricated number. Enforces [SPEC.md 4.1](../SPEC.md). |
| "verbatim label as printed" | Lets a human verify the mapping without reopening the PDF, and builds the alias vocabulary |
| "source page" | [CLAUDE.md](../CLAUDE.md)'s provenance rule, at the point of extraction |
| "If absent, use null" | Nulls, never zeros |
| "`unit_multiplier`" | The thousands/millions trap (TG2, [OPERATIONS.md 1.6](../OPERATIONS.md)) |

Output shape ([DATA_FOUNDATION.md 3.2](../DATA_FOUNDATION.md), abridged):

```json
{"company":"MTN Nigeria Communications Plc","period_end":"2024-12-31",
 "currency":"NGN","unit_multiplier":1000,"statement":"income_statement",
 "line_items":[
   {"canonical_key":"revenue","as_printed":"Revenue",
    "value":3360000000000,"page":94,"confidence":0.97},
   {"canonical_key":"profit_after_tax","as_printed":"Loss for the year",
    "value":-400440000000,"page":94,"confidence":0.95}],
 "extraction_notes":"FX losses disclosed separately in note 12"}
```

Those MTN figures are the real ones from
[DATA_FOUNDATION.md 3.3](../DATA_FOUNDATION.md) — FY2024 revenue ₦3.36 trillion and a loss after
tax of ₦400.44 billion — and they make a good first end-to-end test precisely because the loss
is large, negative, and easy to get sign-wrong.

### P4.3 — Deterministic validation

This is what makes the LLM's output trustworthy, and it is the part that separates a working
pipeline from a plausible one. From [DATA_FOUNDATION.md 3.2](../DATA_FOUNDATION.md), every
extraction is checked against arithmetic identities that must hold in any correct set of
financial statements:

- `total_assets == total_liabilities + total_equity` (within tolerance)
- Cash flow: `opening + net_change == closing`
- Cross-statement: profit after tax ties between the income statement and the cash flow
- Cross-year: this year's opening balances == last year's closing balances
- Sign and unit sanity: revenue > 0; flag year-on-year swings above ~5×

**Any failure sets `needs_review`, reduces confidence, and queues the extraction for a human.**

Confidence = LLM self-report × validation pass rate × table quality. **Below ~0.85 → review.**

The cross-year check is the quiet hero here: it catches a unit-multiplier error instantly,
because a figure that is 1,000× wrong will not tie to last year's closing balance.

### P4.4 — Human-in-the-loop review UI

A Streamlit page showing the **PDF page image beside the extracted JSON**, with editable fields
and approve/correct actions ([DATA_FOUNDATION.md 3.2](../DATA_FOUNDATION.md)).

**Corrections are stored as few-shot examples and fed back into future extractions.** This is
the mechanism by which accuracy compounds instead of plateauing, and
[TEAM_BRIEF.md Part 3](../TEAM_BRIEF.md) item 5 makes it the answer to the review-capacity
ceiling.

**Prioritise the queue by materiality.** A wrong revenue figure matters more than a wrong note
disclosure. A FIFO queue wastes your scarcest resource — reviewer attention — on trivia.

**Track correction rate as a headline metric.** [TEAM_BRIEF.md Part 3](../TEAM_BRIEF.md): *"if
it isn't falling, the extractor isn't learning and something is wrong with the feedback loop."*
That single number is your early-warning signal for the entire phase.

### P4.5 — Nigerian IFRS-specific handling

From [DATA_FOUNDATION.md 3.3](../DATA_FOUNDATION.md) — these are not edge cases, they are the
normal condition of Nigerian statements right now:

**FX translation losses.** The post-June-2023 Naira float produced enormous ones. MTN Nigeria's
net FX losses rose 24.98% to **₦925.36 billion** (from ₦740.43 billion in 2023) as the Naira
fell from **₦907.1/$ to ₦1,535/$** by end-2024. Revenue rose 36% and the company still posted a
₦400.44 billion loss. **Capture FX loss as a distinct line item, and annotate that year-on-year
comparisons are distorted by devaluation** — otherwise every growth metric you compute for
Nigerian companies over this period is misleading without being wrong.

**IAS 29 hyperinflation accounting is NOT triggered.** The FRC ruled in January 2025, reaffirmed
for FY2025, that it must not be applied; only the cumulative-inflation indicator is met. **Keep
statements at historical cost.** Offer an inflation-adjusted "real" view only as a
*user-selectable overlay*, clearly labelled as your computation and not the company's reported
figures. This is exactly [DATA_FOUNDATION.md 1.4](../DATA_FOUNDATION.md)'s "instrument, not
judgment" rule in practice.

**Restatements and changing fiscal-year ends.** Store `restatement_flag`, `fiscal_year_end`,
`restated_from`. **Never overwrite — version every statement**
([CLAUDE.md](../CLAUDE.md) hard rule; [DATA_FOUNDATION.md 3.6](../DATA_FOUNDATION.md)).

### P4.6 — Banks need a parallel chart of accounts

[TEAM_BRIEF.md Part 3](../TEAM_BRIEF.md) item 2 is blunt: *"GTCO's income statement has no
'revenue' line — it has gross earnings, net interest income, and impairments. A schema built on
MTN will not survive a bank."*

[DATA_FOUNDATION.md 3.4](../DATA_FOUNDATION.md) prescribes the fix: a `statement_template` per
industry (financial vs non-financial), with a parallel chart for banks covering gross earnings,
net interest income, impairments, and deposits.

*"Discovering this in week two costs a day; discovering it in month four costs a
re-extraction."* If P3 followed the advice to include a bank in the golden set, you have already
paid the day.

### P4.7 — NGX price history (TG1-NG)

The Nigerian half of **TG1**. [SPEC.md](../SPEC.md) has no task for it;
[DATA_FOUNDATION.md 7.4](../DATA_FOUNDATION.md)'s own T8 covers it as an
`AfxKwayisiConnector`.

🔴 **FRAGILE — this is [TEAM_BRIEF.md Part 3](../TEAM_BRIEF.md) item 3: "free sources have no
contract and can vanish."** `afx.kwayisi.org` and `africanfinancials.com` are named as single
points of failure with no uptime guarantee and no API agreement. Three approaches:

**1. Scrape the free source, cache every raw response permanently (recommended).**
*For:* Free, available now, and the permanent raw cache is what survives the source
disappearing — you keep everything you ever fetched even if the site vanishes tomorrow.
*Against:* It will break, and you cannot backfill history you never fetched. Start fetching
early for that reason alone.

**2. Buy the paid fallback now (EODHD `.XNSA`).**
*For:* Contractual, complete, backfillable. Removes the single point of failure entirely.
*Against:* A subscription for data you may be able to get free, before you know your coverage
needs.

**3. Both — free as primary, paid as documented fallback, not yet subscribed.**
*For:* [TEAM_BRIEF.md Part 3](../TEAM_BRIEF.md)'s stated strategy: "document the paid fallback in
advance so switching is a decision, not a scramble."
*Against:* Needs the discipline to actually write the fallback connector before you need it.

**Recommendation: 3, and start fetching on day one of P4.** Every day you delay is a day of NGX
price history you may never be able to buy back cheaply. The connector pattern means the swap
touches one file.

### P4.8 — Full scheduler and connector health (TG8)

Upgrade P1's minimal scheduler: retries with exponential backoff, per-domain token-bucket rate
limiting, ETag/Last-Modified caching so unchanged documents are never re-fetched, change
detection by hashing listing pages, and `connector_runs` health rows on every execution
([DATA_FOUNDATION.md 3.5](../DATA_FOUNDATION.md), [OPERATIONS.md 2.3](../OPERATIONS.md)).

Politeness rules, from [DATA_FOUNDATION.md 3.5](../DATA_FOUNDATION.md): respect `robots.txt`;
descriptive User-Agent with a contact email; **1 request per 2–5 seconds per domain**; run in
nightly windows.

## Expected inputs

- Nigerian annual-report PDFs: 100–400 pages, borderless tables, inconsistent layouts,
  occasional scans
- The golden set from P3, as the accuracy yardstick
- The frozen chart of accounts, plus the bank template
- LLM API budget — see the cost caps in
  [02_INFRASTRUCTURE.md](02_INFRASTRUCTURE.md) §10

## Expected outputs

```
extraction_jobs
| id | document_id | status        | confidence | validation_failures      | reviewed_by |
|----|-------------|---------------|------------|--------------------------|-------------|
| 91 | 219         | stored        | 0.94       | []                       | NULL        |
| 92 | 220         | needs_review  | 0.62       | ["balance_sheet_mismatch"]| NULL        |
| 93 | 221         | corrected     | 1.00       | ["cross_year_mismatch"]  | frank       |

statement_line_items (extraction_method='llm_hybrid')
| security_id | period_end | canonical_key    | value         | page | confidence |
|-------------|------------|------------------|---------------|------|------------|
| 12          | 2024-12-31 | revenue          | 3360000000000 | 94   | 0.97       |
| 12          | 2024-12-31 | profit_after_tax | -400440000000 | 94   | 0.95       |
| 12          | 2024-12-31 | fx_loss_net      | -925360000000 | 112  | 0.91       |
```

Plus: a review queue ordered by materiality, few-shot examples accumulating, and a correction
rate that falls week over week.

## TEST CHECKPOINT — P4

| # | Check | Command | Expected |
|---|---|---|---|
| 1 | **Golden-file accuracy** | `pytest tests/golden -v` | ≥ your agreed threshold across all pairs |
| 2 | **Bank golden files pass** | `pytest tests/golden -k bank` | Pass at the same threshold as industrials |
| 3 | Never infers | Feed a PDF with a genuinely missing line | Returns `null`; no fabricated value anywhere |
| 4 | Balance sheet identity | Run validation on all extractions | Failures are caught, not stored silently |
| 5 | Cross-year check | Extract two consecutive years | Opening ties to prior closing, or is flagged |
| 6 | Unit multiplier | A statement in thousands | `unit_multiplier=1000`; stored value correct |
| 7 | Sign handling | MTN FY2024 | Loss stored as **negative** ₦400.44bn |
| 8 | Confidence routing | An extraction scoring 0.7 | Lands in the review queue, not in the store |
| 9 | Provenance | `SELECT count(*) ... WHERE page IS NULL` | `0` |
| 10 | Corrections version | Correct an extracted figure | New row; old retained; author and reason recorded |
| 11 | Few-shot feedback | Correct, then re-extract a similar page | The same error does not recur |
| 12 | Rate limiting | Run the scraper | ≥2s between requests to one domain |
| 13 | Raw cache | Re-run on an unchanged document | Serves from cache; no re-fetch |
| 14 | Silent-failure detection | Point a connector at an empty page | `rows_written=0` is flagged |
| 15 | LLM spend cap | Simulate hitting the cap | Halts; does not silently continue billing |
| 16 | Compliance green | `pytest tests/compliance` | All pass |

**By hand and by eye — the most important checks in this phase:**

17. **Sample 20 extracted figures at random and check every one against its PDF page.** Not the
    golden files — those are the training target and the extractor may fit them. Twenty *fresh*
    figures, opened at the cited page, verified by eye. This is the only check that tells you
    the true error rate. Do it at the start of P4 and again at the end. See
    [07_TEST_STRATEGY.md](07_TEST_STRATEGY.md) §8 for the sampling protocol.

18. **Extract one bank and one industrial, and compare the shapes.** Confirm the bank did not
    silently map "gross earnings" to `revenue` and thereby produce a comparable-looking number
    that means something different. This is the failure that survives every automated check,
    because both numbers are real and both are plausible.

19. **Watch the correction rate weekly.** Plot it. If it is not falling, the feedback loop is
    broken — the few-shot examples are not reaching the prompt, or the corrections are not being
    stored in a usable form. Diagnose this immediately; a flat correction rate means the phase
    has no exit.

20. **At two weeks, honour the gate.** Measure accuracy on the golden set. Below 85%, buy EODHD
    and move on. Write down the measured number and the decision either way.

## Exit criteria

- [ ] Checks 1–20 pass
- [ ] Golden-set accuracy at or above the agreed threshold, **including banks**
- [ ] The human review queue works end to end, prioritised by materiality
- [ ] Corrections feed back as few-shot examples, and the correction rate is measurably falling
- [ ] NGX price history flowing, raw responses cached permanently (TG1 fully closed)
- [ ] Scheduler with retries, rate limiting, caching, and health rows (TG8 closed)
- [ ] FX loss captured as a distinct line; devaluation-distortion annotation present
- [ ] The two-week gate decision recorded either way
- [ ] Tracker updated

## What could go wrong

| Risk | Marker | Detail |
|---|---|---|
| **Extraction accuracy plateaus below target** | 🔴 FRAGILE | The named project-eater. Mitigations: curate 15–25 companies not 150; hybrid pipeline; permanent HITL; **honour the two-week gate.** |
| **P4 becomes the whole project** | 🔴 FRAGILE | [TEAM_BRIEF.md Part 3](../TEAM_BRIEF.md) item 4. Warning signal: three weeks in with no other phase touched. The gate is the defence. |
| **Banks break the schema** | 🔴 FRAGILE | Parallel chart (P4.6). Warning: bank golden files failing while industrials pass. |
| Free NGX price source vanishes | 🔴 FRAGILE | Three approaches in P4.7. Cache everything, permanently, from day one. |
| LLM cost overrun | 🟡 WATCH | Hard cap; cheap tools first. Warning: cost per document rising rather than falling. |
| LLM fabricates a plausible number | 🟡 WATCH | Prompt forbids it; validation catches identity breaks; check 17 catches the rest. |
| Review capacity ceiling | 🟡 WATCH | ~2,000 corrections/year at 25 companies. Warning: queue depth growing week over week. |
| Reviewer attrition | 🟡 WATCH | [TEAM_BRIEF.md Part 3](../TEAM_BRIEF.md) names attrition as the most common quiet killer. |
| The PDF toolchain itself | 🟢 SOLID | Mature libraries, honestly evaluated in [DATA_FOUNDATION.md 3.1](../DATA_FOUNDATION.md). The tools are not the risk; the documents are. |
| Storing and versioning extractions | 🟢 SOLID | Proven in P3. |

## What you will be tempted to skip

| Shortcut | Costs |
|---|---|
| "Skip the gate, accuracy is nearly there" | The single most likely way this project dies. |
| "Just send the whole PDF to the LLM" | Cost per document that never falls, and no page-level provenance. |
| "Validation rules can come later" | You store wrong numbers that look right, and the golden set stops meaning anything. |
| "I'll do banks after the industrials work" | A re-extraction, per [TEAM_BRIEF.md](../TEAM_BRIEF.md). |
| "Corrections don't need to feed back" | Accuracy plateaus and the reviewer becomes a permanent full-time cost. |
| "I'll start fetching prices later" | History you cannot buy back. Start on day one. |

---

# P5 — News, Sentiment & Daily Brief (v0.5)

**Spec version:** v0.5 · **Tasks:** T5, T6, T7 · **Effort:** 1–2 weeks

## In one sentence

At the end of P5 a brief arrives on your phone every morning — watchlist moves, new filings,
tagged news with sentiment, and upcoming macro releases — without you asking for it.

## Why this phase is here now

Because it converts a tool you *visit* into a habit that *reaches you*.
[SPEC.md 524](../SPEC.md) frames v0.5 as "the daily habit", and
[TEAM_BRIEF.md Part 4](../TEAM_BRIEF.md)'s stage gate for the web app is "family members log in
unprompted" — the brief is what creates that pull. It also sits deliberately *after* the data
moat: a brief with nothing behind it is a news reader.

## Entry criteria

- [ ] P4 complete or gated (if the gate was taken, a paid feed is supplying statements)
- [ ] Ticker alias table seeded (TEAM_BRIEF task F, from P3)
- [ ] `watchlists` table exists (TG11, from P0)
- [ ] A Telegram bot token

## The build, task by task

### P5.1 — RSS ingestion (T5)

🟢 **SOLID.** [DATA_FOUNDATION.md D](../DATA_FOUNDATION.md) recommends starting with free RSS:
Nairametrics `/feed`, Proshare, BusinessDay `/feed`, Punch business, Reuters Africa, and company
IR feeds.

**Do not rely on paid news APIs for Nigeria.** That document checked, and the finding is
explicit: *"None explicitly confirm Nigerian-source coverage; Finnhub free is US-only; Alpha
Vantage lists only NA/Europe/APAC."* Free RSS is not the budget option here — it is the option
that actually covers the market.

### P5.2 — Ticker tagging (T5)

Your own alias table plus fuzzy matching plus LLM entity extraction
([DATA_FOUNDATION.md D](../DATA_FOUNDATION.md)). "GTCO", "Guaranty Trust", and "GTBank" are the
same company; a naive string match gets this wrong in both directions, and a false tag on a
watchlist alert is the fastest way to make a brief untrustworthy.

### P5.3 — Sentiment tiering (T6)

Bulk scoring with FinBERT/VADER; the LLM only for ambiguous cases ([SPEC.md 2F](../SPEC.md)).
The tiering is a cost-control design: most headlines are unambiguous and do not need an LLM
call.

🟡 **WATCH — sentiment models are trained on US financial English.** Nigerian financial
journalism has different idiom and different framing conventions. Treat the scores as a weak
signal, verify a sample by hand, and do not let a sentiment score drive anything on its own.

### P5.4 — Daily brief and Telegram delivery (T7)

`python-telegram-bot` v22 async ([SPEC.md 4.3](../SPEC.md)). The brief pulls watchlist moves, new
filings, tagged news with sentiment, and macro releases.

**Idempotent delivery via `alert_deliveries` hash** ([SPEC.md 4.3](../SPEC.md)) — the same brief
must never send twice. A retry after a network blip that double-sends is how a useful bot
becomes a muted one.

**Multi-user from day one** ([CLAUDE.md](../CLAUDE.md)): the brief is per principal, built from
*their* watchlist. Not a global brief with one recipient.

## Expected inputs / outputs

**Input:** RSS XML, the `securities` and alias tables, `watchlists`, `macro_series` release
calendar.

**Output:**

```
news_items
| id | published_at        | source       | headline                          | url |
|----|---------------------|--------------|-----------------------------------|-----|
| 77 | 2026-08-27T09:14:00Z| Nairametrics | GTCO reports H1 profit of ...      | ... |

news_tags                          news_sentiment
| news_id | security_id | method | | news_id | score | label   | model    |
| 77      | 44          | alias  | | 77      | 0.62  | positive| finbert  |
```

A Telegram message at 07:00 WAT with watchlist moves, filings, tagged news, and today's macro
releases — with as-of dates on every figure.

## TEST CHECKPOINT — P5

| # | Check | Expected |
|---|---|---|
| 1 | RSS parses across all sources | Items stored with `published_at` and source |
| 2 | Alias tagging | "Guaranty Trust", "GTBank", "GTCO" all tag `security_id` 44 |
| 3 | **No false positives** | An article about a similarly-named unlisted company is **not** tagged |
| 4 | Sentiment scores stored | With the model name and version recorded |
| 5 | LLM tier only for ambiguous | Most items scored without an LLM call |
| 6 | **Idempotency** | Run the brief job twice; exactly one message sent |
| 7 | Per-principal briefs | Two principals with different watchlists get different briefs |
| 8 | Staleness visible | A stale macro figure is flagged in the message |
| 9 | Compliance green | Public-tier content only; no advice phrasing in the brief |

**By hand and by eye:**

10. **Read seven consecutive daily briefs.** Ask after each: did this tell me something I would
    have wanted to know? A brief you skim past is a failed brief, and the fix is editorial
    (fewer, better items), not technical.
11. **Check ten sentiment scores against the headlines.** Confirm the label matches what you
    would say. If it does not, adjust or drop the feature rather than shipping a number that is
    quietly wrong.

## Exit criteria

- [ ] Checks 1–11 pass
- [ ] Brief delivers daily, idempotently, per principal
- [ ] Alias tagging verified against false positives
- [ ] Tracker updated

## What could go wrong

| Risk | Marker | Detail |
|---|---|---|
| False-positive ticker tags | 🟡 WATCH | Erodes trust fast. Warning: any tag you would not have made yourself. |
| Sentiment on Nigerian text | 🟡 WATCH | Models trained on US English. Verify a sample; keep it a weak signal. |
| Duplicate sends | 🟡 WATCH | Idempotency hash. Warning: any repeat at all. |
| RSS feeds change or die | 🟡 WATCH | Same silent-failure pattern: 200 OK, zero new items. |
| Brief becomes noise | 🟡 WATCH | The real failure mode, and it is editorial. Warning: you stop reading it. |
| RSS ingestion mechanics | 🟢 SOLID | Well-trodden. |
| Telegram delivery | 🟢 SOLID | Mature library. |

---

# P6 — Scenarios & Indicators (v0.6–v0.7)

**Spec version:** v0.6 and v0.7 · **Tasks:** T8, T9 · **Effort:** 2–3 weeks

## In one sentence

At the end of P6 you can drive a valuation with your own assumptions and see how the answer
moves, and every security has a stored set of technical indicators — computed, tested, and
**explicitly not yet used as signals**.

## Why this phase is here now

P6 is the last phase before the gate. It builds the two input sets that P7 and P8 consume:
user-driven scenarios, and indicator features. Critically, **T9's acceptance criteria are
"computed + stored", not "traded"** ([SPEC.md 4.2](../SPEC.md)). No signal is generated here.

**Read the honest caveat before building the indicator engine.**
[SPEC.md 2C](../SPEC.md) cites Park & Irwin (*Journal of Economic Surveys* 21(4):786–826, 2007):
of 95 modern studies, 56 positive, 20 negative, 19 mixed — while noting nearly all suffer "data
snooping, ex post selection of trading rules… and difficulties in estimation of risk and
transaction costs", and that simple-rule profitability in US equities largely vanished after the
late 1980s–early 1990s. **The project's position: indicators are FEATURES for a properly
validated model, never standalone signals.** That is precisely why v0.7 precedes v0.9 and both
are gated by v0.8.

## Entry criteria

- [ ] **`price_history` populated for both markets** (TG1 closed in P2 and P4) — without this,
      P6 cannot start, and this dependency exists in no SPEC task
- [ ] **Corporate actions applied** (TG2 from P3) — indicators computed on unadjusted prices are
      wrong in a way nothing will report
- [ ] Trading calendar populated — gaps must be distinguishable from closures

## The build, task by task

### P6.1 — Scenario engine (T8)

User assumptions → DCF and ratio outputs. **No auto-generated targets**
([SPEC.md 4.2](../SPEC.md) T8 acceptance).

The output always carries the assumption set that produced it
([CLAUDE.md](../CLAUDE.md): "Show the work in every mode"). Save named scenarios per principal —
"base", "bear", "Naira at 2,000" — so they can be revisited and compared.

🟢 **SOLID.** This is P2's DCF with a parameter sweep and persistence.

### P6.2 — Indicator engine (T9)

RSI, MACD, Bollinger Bands, ATR, OBV, Stochastic — computed and stored per
`(security_id, date, name, param_hash)` per [SPEC.md 3.2](../SPEC.md)'s DDL.

**Library:** [SPEC.md 2A](../SPEC.md) is specific and current. The original `pandas-ta`
(twopirllc) is **effectively unmaintained**. The community successor is **`pandas-ta-classic`**
(`xgboosted/pandas-ta-classic`), first released Aug 2025, actively developed (v0.6.52, June
2026), 224+ indicators plus 62 candlestick patterns, **no TA-Lib dependency**, optional numba
acceleration (6–230× on hot indicators), pandas 3.0 compatible. **This is the recommended
default** — no C dependency, easiest for agents to install reproducibly.

**`param_hash` is not decoration.** RSI-14 and RSI-21 are different features. Without the hash
in the primary key you silently overwrite one with the other, and in P8 your feature matrix
contains whichever ran last.

**Known-answer tests are mandatory** ([SPEC.md 4.2](../SPEC.md) T9 acceptance): hand-computed
vectors, checked against the library's output. Libraries differ on smoothing conventions — Wilder
versus simple, for instance — and a subtly different RSI is a subtly different model.

### P6.3 — Point-in-time discipline

Every indicator row carries `known_as_of`. An indicator computed today from a price series that
was later revised is not what was knowable on the date. P7 depends on this absolutely.

## Expected inputs / outputs

**Inputs:** `price_history` with `close_adj` (corporate-action adjusted), the trading calendar,
user assumption sets.

**Outputs:**

```
indicators
| security_id | date       | name       | param_hash | value  |
|-------------|------------|------------|------------|--------|
| 44          | 2026-08-27 | rsi14      | a3f9c1     | 62.41  |
| 44          | 2026-08-27 | macd_hist  | 7d2e04     | 1.83   |

scenarios
| id | principal_id | security_id | name  | assumptions_json                    | result_json |
|----|--------------|-------------|-------|-------------------------------------|-------------|
| 5  | 1            | 44          | bear  | {"wacc":0.18,"g":0.02,"tg":0.03}    | {...}       |
```

## TEST CHECKPOINT — P6

| # | Check | Expected |
|---|---|---|
| 1 | **Known-answer RSI** | Matches a hand-computed 14-period vector exactly |
| 2 | Known-answer MACD, BB, ATR, OBV, Stochastic | Each matches hand-computed vectors |
| 3 | **Indicators use adjusted prices** | Verify against a security with a known split — no artificial spike |
| 4 | `param_hash` distinguishes | RSI-14 and RSI-21 coexist; neither overwrites the other |
| 5 | Trading calendar respected | No indicator row on a day the NGX was closed |
| 6 | `known_as_of` present | `SELECT count(*) FROM indicators WHERE known_as_of IS NULL` → `0` |
| 7 | Scenario reproducibility | Same assumptions → identical output |
| 8 | Scenarios are per principal | Two principals' scenarios do not collide |
| 9 | **No signal is emitted** | `grep -rEi "\b(buy\|sell\|signal)\b" packages/indicators/` → nothing that emits a recommendation |
| 10 | Compliance green | `pytest tests/compliance` passes |

**By hand and by eye:**

11. **Plot RSI over a known split date.** It should be continuous. A spike means you are
    computing on unadjusted prices, and every downstream model would inherit it.
12. **Compute one RSI-14 by hand in a spreadsheet** and compare. Tedious, once, and it is the
    only way to know your library's smoothing convention matches your assumption.
13. **Run a scenario you have intuition about.** Naira at ₦2,000/$ for an importer should hurt
    materially. If the model shrugs, an assumption is not wired through.

## Exit criteria

- [ ] Checks 1–13 pass
- [ ] All six indicators computed and stored for the full universe, with known-answer tests
- [ ] Indicators computed on **adjusted** prices, verified across a split
- [ ] Scenario engine saves and reproduces named scenarios per principal
- [ ] **No signals generated anywhere** — this is a hard exit criterion
- [ ] Tracker updated

## What could go wrong

| Risk | Marker | Detail |
|---|---|---|
| Indicators on unadjusted prices | 🔴 FRAGILE | Silent; corrupts P8's entire feature set. Checks 3 and 11. This is why TG2 was an entry criterion. |
| Treating indicators as signals | 🔴 FRAGILE | The Park & Irwin caveat. The structural defence is that P7 exists and P8 is gated by it. |
| `param_hash` omitted | 🟡 WATCH | Silent overwrite. Warning: an indicator whose values change when you re-run with different parameters. |
| Library smoothing conventions | 🟡 WATCH | Check 12 is the whole mitigation. |
| Scenario UI complexity | 🟡 WATCH | Easy to over-build. It is an instrument, not a product. |
| `pandas-ta-classic` | 🟢 SOLID | Actively maintained, no C dependency, pandas 3.0 compatible ([SPEC.md 2A](../SPEC.md)). |
| Scenario/DCF math | 🟢 SOLID | Proven in P2. |

## What you will be tempted to skip

| Shortcut | Costs |
|---|---|
| "Raw prices are close enough" | Every P8 feature is wrong, invisibly. |
| "Known-answer tests are tedious" | You never learn your library's convention differs from your assumption. |
| "Just one quick signal to see if it works" | Exactly the data-snooping the invariant exists to prevent. Wait for P7. |

---

# Handoff to Part 2

At the end of P6 you have: a multi-user API with an enforced mode gate; macro, US, and Nigerian
company data with full provenance and point-in-time correctness; automated Nigerian extraction
with a human review loop; a daily brief; a scenario engine; and stored technical indicators.

**What you do not have, and must not have yet: a single trading signal.**

[04_ROADMAP_PART2_PHASES_7-13.md](04_ROADMAP_PART2_PHASES_7-13.md) opens with P7 — the
backtesting harness — which is the gate everything after it depends on.
[SPEC.md 4.1](../SPEC.md) makes it an invariant: no signal trades without a passing recorded
`backtest_run`. P7 assumes every entry criterion above was genuinely met, and in particular that
TG1 and TG2 are closed. A backtester fed on unadjusted prices does not fail — it reports a
strategy that never existed.

The phase numbering here is canonical across the whole document set. P7–P13 continue in
[04_ROADMAP_PART2_PHASES_7-13.md](04_ROADMAP_PART2_PHASES_7-13.md).

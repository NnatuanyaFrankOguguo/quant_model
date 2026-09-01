# Project Context — Quant Model

> Standing context for what we are building, why, and who it serves.
> Last updated: 2026-08-28

---

## 1. What it is

A **centralized financial data hub for Nigerian and US publicly traded companies** — one
place to see a company's financial statements, its history, the macro backdrop (inflation,
interest rates, FX), relevant news, and tools to model its value yourself.

## 2. The problem it solves

That information is currently scattered:

- Nigerian company financials sit as PDFs on company websites
- Inflation data is a PDF from NBS
- Policy rates are on the CBN site
- Bond auctions are on DMO
- News is spread across five or more outlets

To understand one company you visit six places and re-key numbers into a spreadsheet.

For **US companies** this is largely solved — EDGAR and FRED are free and structured.
For **Nigerian companies**, nobody has done it. That gap is the whole opportunity:
**turning Nigerian financial PDFs into clean, queryable data _is_ the product.**

## 3. Who it serves

| Tier | Audience | Need |
|---|---|---|
| Now | The owner | Replaces a weekly manual research routine |
| Now | Family | Shared, documented visibility into decisions made with their own capital |
| Later | Nigerian retail investors | No accessible way today to read NGX company fundamentals |
| Later | Analysts | Lose hours to PDF-hunting |
| Later | Diaspora investors | Want real Nigerian data, not guesses |
| Later | Learners / channel audience | Follow the content, want the tool |
| Later | **Companies (B2B)** | See §9 — the commercial and acquisition layer |

## 4. Access model

**One codebase, one feature set, two audiences.** Everything is built to public standard;
what changes over time is who is entitled to reach which tier — never what the system is
capable of.

### The core rule: build scope ≠ access control

These are two separate axes, and conflating them is the mistake to avoid:

| | **Build scope** — what it can do | **Access** — who can reach it |
|---|---|---|
| **Now** | Everything. Public-grade, general-purpose, multi-user. | Owner + family only. |
| **After the licence** | Unchanged. | + the public. |

**Build it as if everyone will use it. Restrict who can log in, not what it can do.**
The licence widens the audience; it does not add features. Nothing gets built twice.

### Personal access — the mode we are in now

Users: **the owner and family.** Nobody else *yet*.

> **What "family" means here — settled 2026-08-30.** Members of the owner's household and
> first-degree relatives whose capital the owner already accounts for. **Capped at six
> principals**, enforced by the database so that adding a seventh fails rather than drifts.
>
> **No fee is charged to any of them, and no funds are pooled under the owner's control.**
> Those two conditions are not incidental — they are precisely what makes the personal tier
> lawful without SEC registration ([SPEC.md §1.2](SPEC.md): *"permissible only because he is
> managing his own and his family's money, **not third-party funds for a fee**"*). Both are
> recorded as columns on `principals` and enforced by a trigger, because the realistic failure
> is not an intruder — it is a slow drift from three relatives to eleven acquaintances, one of
> whom offers to cover the server bill. Every technical permission check would still pass on
> that day; these two flags are the only thing that would notice.
>
> If either condition ever becomes untrue, **the personal tier closes until the licence
> exists.** See [docs/10_PRE_BUILD_CORRECTIONS.md](docs/10_PRE_BUILD_CORRECTIONS.md) §8 D2.

The system may do anything useful, including the things an unlicensed public product could
not: say **BUY / SELL**, output **price targets**, surface **ML signal model** conviction, and
size a position. This is the owner's own capital and family capital the owner has agreed to
account for. There is no client, no fiduciary duty to a stranger, and no regulator interested
in what someone does with their own money.

**Everything is being proven here first.** Restricted access is how the extraction pipeline,
the valuation math, and the trading model earn trust before strangers depend on them — it is
a staging decision, not a permanent ceiling on the product.

### Public access — in two stages

**Stage 1 — data tier (no licence needed, ship whenever ready).**
Statements, ratios, macro, news, and user-driven valuation where the _user_ sets every
assumption. A complete product on its own, and the one §9's B2B buyers actually want.

**Stage 2 — advice tier (opens on the SEC licence).**
Signals, recommendation memos, sizing. **The licence is the plan, not a hypothetical** —
the intent is SEC registration under Nigeria's **ISA 2025**, both the adviser and
fund-manager categories. When it lands, this tier opens to the public with disclosures.
No new features are written that day; an entitlement opens.

### The design consequence — the expensive mistake to avoid

Access is **per-principal entitlement**, not a hardcoded audience:

- Mode is **derived server-side from the authenticated principal**, never client input, and
  defaults to the data tier (fail-safe).
- The advice tier is gated by `entitlements` + a `licence_status` flag — so opening it is a
  config change plus a disclosure layer, never a re-architecture.

**Build multi-user from day one.** This is the part that is cheap now and a rewrite later.
Because the trading half is meant for the public eventually, nothing in it may assume a
single user:

- Portfolios, watchlists, risk limits, and alerts are keyed by user — never a global
  "the portfolio."
- Position sizing takes account equity as a **parameter per user**, never a config constant.
- LLM spend caps are per-user as well as global.
- Every audit row carries its principal.

A single-user trading layer is a full rewrite to open up. A multi-user one that currently has
two users is a config change.

**The philosophy still holds in both modes:** the instrument shows its work. Even when it
says BUY, it shows _why_ — the assumptions, the data, the as-of dates — so the judgment stays
the user's. That is the difference between a tool that makes someone a better investor and an
oracle that makes them a dependent one.

## 5. The two halves

**Analysis** — public-ready today:
financial statements, ratios, macro series, news, scenario/valuation tools where the user
sets every assumption.

**Trading** — built public-grade, access-restricted until licensed:
indicators, an ML signal model, and critically a **backtesting harness** that proves a
strategy isn't just noise before real money touches it. **Build it for the general case —
every use case, multiple users** — because it is meant to serve the public once licensed.
Today it says BUY freely to the owner and family; the public simply cannot reach it yet.

## 6. Trajectory

A tool used daily → a tool the family relies on → if it earns it, **the missing structured
database of Nigerian corporate finance**, which is a business.

---

## 7. Practical gaps to close (descending cost of ignoring)

**Data update cadence and staleness.**
The spec covers where data comes from but not how fresh it must be. Nigerian companies file
quarterly and often late; NBS publishes CPI mid-month. Every screen must show an **"as of"**
date prominently and flag when a series is overdue — otherwise we reason from stale numbers
without noticing.

**Backup and disaster recovery.**
Once months have gone into extracting Nigerian financials from PDFs, that database is
genuinely irreplaceable — redoing it costs the same months. **Automated off-machine backups
from day one**, not v1.0.

**Onboarding for family.**
The owner will understand every number; family will not. If the goal is shared visibility,
the interface must explain itself — what a ratio means, why a figure moved — or only one
person will ever use it.

**A dead-simple manual override.**
Extraction will get things wrong. There must always be a way to correct a number by hand and
have the correction **stick**, with a note recording who changed it and why.

## 8. Decisions to make before writing much code

**Company coverage strategy.**
NGX has ~150 listed companies; most barely trade. Pick **15–25** that actually matter.
Breadth is a trap — it multiplies extraction work while adding little value.

**A single golden test case.**
Choose one company — **MTN Nigeria** is the recommendation, because its FY2024 numbers are
messy in an instructive way (revenue up, large loss driven by FX) — and make it the reference
every pipeline stage must handle correctly before moving on.

**Sunk-cost honesty.**
Set the rule now, while calm: *if extraction accuracy stalls after N weeks, buy EODHD and
move on.* Decide the threshold before being three weeks deep and reluctant to abandon work.

**The strategic risk worth sitting with.**
This is three things that could each be a full-time job: a **data pipeline**, an **analytical
product**, and a **trading system**. They share a foundation — which is why merging them made
sense — but they do **not** share a finish line:

- The data pipeline is done when it's reliable.
- The analytical product is done when someone uses it weekly.
- The trading system is never done, because markets move.

If six months in all three are half-built, the honest move is to **finish the data layer
completely** and let the others wait. The data layer is the only piece that is valuable
regardless of what happens to the other two.

**The content angle.**
The channel is a real asset the spec under-weights. Building this in public — the extraction
problems, the backtesting failures, the Nigerian data gaps nobody talks about — is content
nobody else can make. It is also free validation: if viewers say "I'd use that," that's a
signal earned before writing the public version.

---

## 9. Serving companies (B2B) — the commercial and acquisition layer

### 9.1 The industry / niche

**Not fintech.** This is **financial data infrastructure** — the market data and financial
information services category.

- **Global incumbents:** Bloomberg, LSEG/Refinitiv, FactSet, S&P Capital IQ, Moody's
- **Regional peers:** African Financials, Stears, Asoko Insight

That distinction matters enormously:

- Fintech companies are valued on **users and transaction volume**.
- Data companies are valued on **coverage, recurring revenue, and workflow embeddedness**.

A data business with 40 institutional clients can be worth more than a consumer app with
400,000 users, because the revenue is stickier and the asset is harder to replicate.

**The sub-niche, stated precisely:** structured fundamental and macro data for a **frontier
market where it does not currently exist in machine-readable form**.

### 9.2 How it serves companies

| Buyer | What they need | Why they'd buy rather than build |
|---|---|---|
| **Nigerian brokers & asset managers** (Meristem, CardinalStone, Chapel Hill Denham, ARM, PFAs) | Company fundamentals for research and client reporting | Their analysts download PDFs and re-key numbers today; the API sells back analyst hours |
| **Fintechs** (Bamboo, Chaka, Trove, Cowrywise, Risevest) | Show users the financials behind a stock they list | An embedded data API is a feature they'd rather buy than build |
| **Banks & credit teams** | Historical financials on Nigerian corporate borrowers | Currently a manual research task per borrower |
| **Global data vendors** | NGX fundamental coverage they lack | Coverage-gap fill — cheaper to license than to originate |
| **Corporates themselves** | Peer benchmarking on standardized metrics | No standardized comparable set exists locally |
| **Media, researchers, universities** | Reliable Nigerian financial data | No citable structured source today |

### 9.3 What makes a data company acquirable

Four things — and the hardest one is already designed in.

**1. A proprietary dataset that is expensive to replicate.**
Five years of normalized NGX financials is not something a buyer can spin up in a quarter.
**This is the moat.**

**2. Point-in-time integrity.**
Versioned statements, provenance on every number (source document + page), as-of dates, and
restatement handling. Most cheap vendors don't do this, and it is exactly what institutional
buyers pay premiums for — it is the only way to backtest honestly.
**This is the single most enterprise-grade feature. Do not compromise it for speed.**

**3. API-first architecture with stable identifiers.**
If clients build against the API, switching costs get high. Every company gets a **permanent
internal ID** mapped to ticker, ISIN, and CIK.

**4. Clean licensing rights.**
This is the one that kills deals. An acquirer's lawyers will ask exactly one hard question:
*do you have the right to redistribute this data?* A dataset built by scraping sources whose
terms prohibit redistribution is a lawsuit, not an asset.
**Not a v2.0 concern — it is the difference between an asset and a liability.**

### 9.4 What to add now, cheaply

Each of these costs little designed in early and a lot retrofitted:

- Stable entity IDs (internal permanent ID ↔ ticker / ISIN / CIK)
- A documented public API, **versioned** from the first release
- Bulk export (CSV / Parquet) alongside the API
- Coverage metrics quotable to a buyer: *N companies, M years, X% extraction accuracy*
- A data dictionary
- A clean record of where every dataset came from **and under what terms**
- Keep the IP **personally owned and unencumbered**
- Track uptime from the day anyone but the owner depends on it

### 9.5 The honest part

**Acquisition is a poor primary goal.** Most companies aren't acquired, and building to be
bought usually produces something nobody wants. The reliable path is the opposite: build
something people genuinely depend on and pay for, and acquisition becomes one of several
possible outcomes rather than the plan.

Also worth knowing: Nigerian market data buyers are **price-sensitive**, and the addressable
institutional market is small — perhaps a few dozen serious accounts. That is fine for a good
business; it is probably not a large exit unless coverage expands to other African exchanges
(Ghana, Kenya, Egypt, South Africa). That is the move that turns "Nigerian data company" into
"African data company," and the buyer list gets much more interesting.

**The thing that makes it acquirable is the same thing that makes it useful: a dataset nobody
else has, maintained reliably, with provenance you can defend. Build that, and the rest is
optional.**

---

## 10. Standing rules for this project

1. **Advice is access-gated, not absent.** Owner + family reach it now and it may say
   BUY/SELL, give targets, and surface model conviction freely — it is our own capital. The
   public reaches it when the SEC licence lands. Implement the gate as **entitlements +
   `licence_status`, never a code fork**, so licensing is a switch and not a rewrite.
2. **Build multi-user from day one.** Nothing in the trading half may assume a single user —
   portfolios, watchlists, risk limits, alerts, spend caps, and audit rows are all keyed by
   principal; position sizing takes equity as a per-user parameter. This is the one shortcut
   that turns opening to the public into a rewrite.
3. **Show the work in every mode.** Even a BUY comes with its assumptions, its inputs, and
   their as-of dates. The instrument argues; it does not pronounce.
4. **Provenance is not optional.** Every extracted figure carries source document, page, and
   as-of date.
5. **Never silently overwrite a figure.** Corrections are versioned, attributed, and noted.
6. **Show staleness.** Every series displays its as-of date and flags when overdue.
7. **Data licensing before ingestion.** Confirm redistribution rights for a source before it
   enters the dataset. (Distinct from the SEC licence in rule 1.)
8. **The data layer has priority** when time is scarce. It is the only piece valuable
   independent of everything else.
9. **Never let advice-tier output reach a non-family principal** before the licence exists.
   That is the one line carrying real legal risk, and it is an access-control problem —
   solve it in code, not in policy.

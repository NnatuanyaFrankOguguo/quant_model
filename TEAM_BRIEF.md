# Team Brief — What We're Building, What Must Be Done by Hand, and What Will Try to Stop Us

*The onboarding document. Read this first; the technical specs come after.*

> **Where this sits:** [PROJECT_CONTEXT.md](PROJECT_CONTEXT.md) (why) · [DATA_FOUNDATION.md](DATA_FOUNDATION.md) (sources & pipeline) · [SPEC.md](SPEC.md) (build order) · [OPERATIONS.md](OPERATIONS.md) (correctness & infrastructure) · **this file** (people, manual work, risk).

---

# PART 1 — WHAT THIS IS

## In one paragraph

We are building the **missing structured database of Nigerian corporate and macro finance** — and wrapping it in a tool that lets an ordinary person read a company's numbers, understand the economy around it, and model what they think it's worth. Nigerian company financials exist today only as PDFs scattered across company websites. Inflation is a PDF from NBS. Policy rates live on the CBN site. Bond auctions are on DMO. To understand a single company you visit six places and re-key numbers into a spreadsheet. For US companies this problem is solved — EDGAR and FRED are free and structured. For Nigerian companies, **nobody has done it.** That gap is the entire opportunity, and the act of closing it is the product.

## Why it matters

There is an information asymmetry in the Nigerian market, and it is not subtle.

An institution with a Bloomberg terminal can pull five years of normalized financials for any NGX company in seconds. A Nigerian retail investor — someone putting real money into a market that determines whether their savings outrun 25% inflation — cannot. Not because the data is secret. It is published, publicly, by law. It is simply **trapped in a format nobody can query**, and no one has done the unglamorous work of freeing it.

That work is unglamorous, and that is precisely why it is a moat. Anyone can build a charting site. Almost nobody will spend months turning badly-formatted annual report PDFs into clean, provenance-tracked time series — and once it's done, it cannot be spun up in a quarter by someone who decides they want it too.

## What we serve

**First, ourselves and our families.** Real capital, real decisions, documented and shared. If it isn't good enough for our own money, it isn't good enough for anyone's.

**Then, the people who have nothing.** Nigerian retail investors with no accessible way to read fundamentals. Analysts losing hours to PDF-hunting. Diaspora investors wanting real Nigerian numbers instead of stale guesses. Students learning finance with actual local data instead of American textbook examples.

**Eventually, institutions.** Brokers, asset managers, fintechs, banks, and global data vendors who currently have a Nigeria-shaped hole in their coverage. That's the business.

## The principle that governs everything

**We provide the instrument. The user provides the judgment.**

Every number shows its source — which document, which page, as of when. Every valuation assumption is set by the person using it, not by us. On the public tier we present data and let people think; we do not tell them what to buy. Partly because that requires an SEC licence under ISA 2025, which we intend to obtain. But mostly because a tool that makes people better investors is worth more than one that makes them dependent.

## The vision, stated plainly

Three to five years out, if this works: **a Nigerian investor, analyst, or student opens one page and sees what previously took a week of PDF-hunting to assemble** — and trusts it, because every figure traces back to the audited filing it came from.

Beyond Nigeria: the same problem exists in Ghana, Kenya, Egypt, and across frontier markets. What we build for NGX is a template. "Nigerian data company" becoming "African data company" is where this stops being a useful tool and becomes genuinely valuable infrastructure.

**And the honest version:** most projects like this die in the middle, when the novelty is gone and the PDFs are still badly formatted. What gets us through is that the boring part *is* the moat. Every week spent on extraction accuracy is a week nobody else is spending.

---

# PART 2 — MANUAL WORK: WHAT PEOPLE MUST ACTUALLY DO

Automation handles the repetitive parts. These are the tasks that genuinely need human hands or human judgment. Each entry states **whether it's truly necessary**, the **effort**, and the **alternative** — because some of these can be bought.

## 2.1 The roles

| Role | Needs | Load |
|---|---|---|
| **Curator** (owner) | Market knowledge, accounting literacy | Front-loaded, then light |
| **Collector** | Care, organisation. No finance background needed. | Heavy at start, then light |
| **Data-entry analyst** | Can read a financial statement | Heavy during v0.3 backfill |
| **Reviewer** | Solid accounting — can spot a wrong number | Light at first, permanent thereafter |
| **Owner only** | Judgment, authority, money | Ongoing |

## 2.2 The task list

### A. Choose the company universe — **Curator, ~1 day, do first**

Pick **15–25 NGX names**. NGX has ~150 listed companies; most barely trade, and breadth multiplies work while adding almost nothing.

*Necessary?* Yes, and it must come first — everything downstream is sized by this number.
*Alternative?* None. This is judgment.
*Guidance:* start with the two dual-listed names (**Airtel Africa, Seplat Energy** — they file cleaner UK-standard statements in USD), then the liquid majors (MTN Nigeria, Dangote Cement, GTCO, Zenith, UBA, Nestlé). Include **at least one bank** — banks use a different chart of accounts and will break a schema built only on industrials. Better to discover that in week two than month four.

### B. Collect the seed document set — **Collector, ~3–5 days**

Download annual reports for the chosen universe, ~5 years each (~100 PDFs). Sources: `africanfinancials.com`, company IR pages, NGX doclib.

*Necessary?* **The seed set is.** The scraper (v0.4) will handle the ongoing flow, but you cannot build or test an extractor without documents in hand today.
*Alternative?* Partially — the scraper automates collection later. It does not remove the need for a curated seed.
*Do it properly:* one folder per company, filename `TICKER_FY2024_AR.pdf`, and a spreadsheet logging source URL and download date for every file. **That log becomes the `source_documents` table.** Sloppy collection here costs provenance later, and provenance is the product.
*Also:* keep every PDF permanently. `africanfinancials` has no uptime guarantee. Once a 2013 report leaves the web, our copy may be the only one.

### C. Build the golden test set — **Reviewer + Curator, ~2–3 days. Highest leverage task in the project.**

Hand-verify **every number** in 3 filings — ideally MTN Nigeria FY2024 (messy: revenue up, huge FX-driven loss), a bank (GTCO), and a clean industrial. Produce the expected JSON output by hand.

*Necessary?* **Absolutely, and there is no substitute.** Without ground truth you cannot measure extraction accuracy, which means you cannot tell whether the extractor is working, cannot hit the ≥85% decision gate, and cannot honestly quote accuracy to a buyer. Every automated test in the project measures against this set.
*Alternative?* None whatsoever.
*This is tedious and it is the single most valuable manual work anyone will do here.*

### D. Manual data entry for v0.3 — **Data-entry analyst, ~2–4 hrs per company-year**

Hand-key statements into the CSV template for 5–10 companies.

*Necessary?* Yes — [Doc A Recommendation 3](DATA_FOUNDATION.md) is right that this forces IFRS edge cases into the open cheaply, *before* you've built an expensive extractor around wrong assumptions.
*But scope it down:* **5 companies × 2 years, not 5 × 5.** The purpose is to prove the schema survives a bank and a devaluation-hit telco — two years does that. Full history comes from the extractor.
*Alternative?* Buying **EODHD `.XNSA` (~$60/mo)** gives structured fundamentals immediately. But do the manual pass anyway — it's a few days, and it teaches the team what the data actually looks like. That understanding is what makes the reviewer good at their job later.

### E. Backfill corporate actions — **Collector + Reviewer, ~2–3 days**

For each company, 5 years of **bonus issues, rights issues, splits, and dividends** with ex-dates. Sources: NGX corporate disclosures, IR announcements, and the equity notes in the annual reports you already collected.

*Necessary?* **Yes, and it is the most commonly skipped task on this list.** [OPERATIONS.md §1.1](OPERATIONS.md) explains why: Nigerian companies issue bonus shares often, a 1-for-4 bonus drops the price ~20% overnight with no economic loss, and without the adjustment every backtest spanning it records a fake crash. This corrupts the trading model silently.
*Alternative?* **NGX's paid "News & Corporate Actions" product ($2,500/yr)** or EODHD. For a fixed historical backfill of 20 companies, manual is cheaper and better. For the ongoing flow, revisit if it becomes a burden.

### F. Seed the ticker alias table — **Curator, ~half a day, ongoing**

Map every name variant to the internal ID: "GTCO" / "Guaranty Trust" / "GTBank" / "Guaranty Trust Holding Company". Needed for news tagging.

*Necessary?* Yes. LLM entity extraction handles ambiguous cases, but a curated alias table is more reliable and far cheaper for the common ones.
*Note:* **GTBank became GTCO in 2021.** Aliases have valid-from dates — see [OPERATIONS.md §1.4](OPERATIONS.md).

### G. Build the canonical chart of accounts — **Curator, ~2 days, needs accounting knowledge**

Map Nigerian IFRS statement labels to canonical keys ("Turnover", "Gross earnings", "Revenue" → `revenue`). **Banks need a parallel chart** — gross earnings, net interest income, impairments, deposits.

*Necessary?* Yes, and it's the schema decision most expensive to change mid-build.
*Alternative?* None. This is domain expertise.
*Get it right before v0.4.* Changing it after the extractor is running means re-extracting everything.

### H. Monthly macro download — **Collector, ~30 min/month until automated**

NBS CPI (mid-month, prior month), CBN MPR after each MPC, FX, DMO auction results.

*Necessary?* Only until the scrapers exist (DATA_FOUNDATION T13).
*Alternative?* **FRED and World Bank cover Nigeria annually and automatically** — good enough for v0.1's context charts. Monthly tracking needs NBS/CBN, which means manual or scraped.

### I. Ongoing extraction review — **Reviewer, permanent**

Every extraction below confidence 0.85, plus every validation failure. At ~90% accuracy on ~200 line items per annual report, expect **~20 corrections per filing**.

*Necessary?* Permanently. This is the human-in-the-loop that makes the data trustworthy, and [PROJECT_CONTEXT.md](PROJECT_CONTEXT.md) rule 4 requires corrections to stick, versioned and attributed.
*It shrinks but never disappears.* Every correction is stored as a few-shot example, so the extractor improves. Budget it as a standing weekly commitment, not a project phase.

### J. Accounts, applications, and legal — **Owner only**

FRED API key (free) · Anthropic API · EODHD if bought · NGX Market Data application via `marketdata@ngxgroup.com` if licensing is needed · Alpaca/IBKR verification for US execution · **and the securities + data-protection lawyer.**

*On the lawyer:* [Doc A Recommendation 5](DATA_FOUNDATION.md) makes this a v2.0 gate. **Book it earlier than that.** The answer on NGX redistribution rights shapes the v2.0 architecture, and the SEC licence path has a long lead time. Finding out late is the expensive version.

## 2.3 What you can buy instead of doing

| Instead of | Buy | Cost | Worth it when |
|---|---|---|---|
| PDF extraction for fundamentals | **EODHD `.XNSA`** | ~$60–100/mo | Extraction accuracy stalls below 85% after 2 weeks, or Claude spend trends past ~$100/mo. **This is the project's single most important cost decision — [Doc A Rec. 4](DATA_FOUNDATION.md).** |
| Manual corporate-actions backfill | NGX News & Corporate Actions | $2,500/yr | Ongoing flow becomes a burden. Not for the historical backfill. |
| Scraping NGX prices | NGX Interday Prices | $1,000/yr | You need licensed redistribution rights for the public tier. |
| Nigerian macro scraping | Trading Economics | Paid | Never, probably. FRED + scraping covers it. |
| Data-entry labour | A contractor | Local rates | The v0.3 backfill is the one genuinely parallelisable manual block. **Note: they can key numbers, but they cannot build the golden set — that needs someone who will be held accountable for it.** |

**The standing rule from [PROJECT_CONTEXT.md §8](PROJECT_CONTEXT.md):** decide the buy-vs-build threshold now, while calm — not three weeks deep and reluctant to abandon work you've already done.

---

# PART 3 — BOTTLENECKS AND HOW WE BEAT THEM

## The big five

### 1. PDF extraction is harder than it looks — *the one that eats months*

Nigerian annual reports use borderless tables, inconsistent layouts, and occasional scans. Rules-based extraction alone gets ~60%. Every planning document says the same thing: **budget 2–3× your estimate.**

**How we beat it:** Start manual (v0.3) so the schema is proven before the extractor exists. Use the hybrid pipeline — cheap tools first, LLM only for reconciliation. Keep humans in the loop permanently rather than chasing full automation. **Curate 15–25 companies, not 150.** And hold the decision gate: below 85% after two weeks, buy EODHD and move on.

### 2. Banks break everything built for industrials

GTCO's income statement has no "revenue" line — it has gross earnings, net interest income, and impairments. A schema built on MTN will not survive a bank.

**How we beat it:** Include a bank in the first five companies. Build the parallel financial-institution chart of accounts in task G, before v0.4. Discovering this in week two costs a day; discovering it in month four costs a re-extraction.

### 3. Free sources have no contract and can vanish

`afx.kwayisi.org` and `africanfinancials.com` are single points of failure with no uptime guarantee and no API agreement.

**How we beat it:** The connector pattern means swapping a source touches one file. **Cache every raw document permanently** — that cache is what survives the source disappearing. Document the paid fallback in advance (EODHD `.XNSA`) so switching is a decision, not a scramble.

### 4. Three products, one team, no shared finish line

The data pipeline is done when it's reliable. The analytics product is done when someone uses it weekly. The trading system is never done, because markets move. Six months in, the realistic failure is **all three half-built.**

**How we beat it:** Sequence, don't parallelise. **When time is scarce, the data layer wins** — it's the only piece valuable regardless of what happens to the other two. If everything is half-done, finish the data layer completely and let the rest wait.

### 5. Review capacity becomes the ceiling

At ~20 corrections per filing, 25 companies filing quarterly is ~2,000 corrections a year. One reviewer becomes the bottleneck the moment coverage grows.

**How we beat it:** Every correction feeds back as a few-shot example, so accuracy compounds. Prioritise the review queue by materiality — a wrong revenue figure matters more than a wrong note disclosure. Track correction rate as a headline metric; if it isn't falling, the extractor isn't learning and something is wrong with the feedback loop.

## The quieter risks

**Silent data corruption.** The worst failure mode: nothing crashes, numbers are just wrong. Corporate actions, unit multipliers, ticker collisions, mixed fiscal periods — all covered in [OPERATIONS.md Part 1](OPERATIONS.md). *Beat it with* validation rules that run on every ingest and connector row-count assertions, so failure is loud.

**Regulatory drift.** The ground moved three times during planning alone — the NGX movement rule was approved then postponed a day before rollout; SEC capital requirements were restructured; share CGT changed in January 2026. *Beat it with* a quarterly one-hour review across NGX, SEC, NDPC, FRC, FIRS, recorded as ADRs.

**Agent drift.** On a long spec, coding agents re-litigate settled decisions and quietly add advice-shaped fields. *Beat it with* SPEC.md as law, one task per PR, and CI enforcing the invariants.

**Losing the data.** Months of extraction living on one laptop. *Beat it with* [OPERATIONS.md §2.1](OPERATIONS.md) — and a restore drill, because a backup nobody has restored is not a backup.

**Attrition.** Rarely stated, most common. Multi-year projects die in the middle, when novelty is gone and the PDFs are still badly formatted. *Beat it with* shipping v0.1 in a weekend so something real exists early, building in public so progress is visible, and remembering that the boring part is the moat — every week on extraction accuracy is a week nobody else is spending.

---

# PART 4 — WHAT SUCCESS LOOKS LIKE

Success is measurable at every stage. These are the thresholds — pass them and continue, miss them and something changes.

## Stage gates

| Stage | Success means | Threshold to continue |
|---|---|---|
| **v0.1** Macro dashboard | You open it instead of hunting PDFs | Used daily for one week |
| **v0.2** US analyzer | Schema and analysis engine work on clean data | 5 US names render 5-yr statements + ratios with provenance links |
| **v0.3** Manual NG analyzer | Schema survives real Nigerian filings | **Handles a bank (GTCO) and a devaluation-hit telco (MTN) without modification** |
| **v0.4** Automated ingestion | The moat exists | **≥85% extraction accuracy** on 10 filings after review; Claude spend under ~$100/mo. *Miss it → buy EODHD.* |
| **v0.5** News + brief | The daily habit | You read the brief instead of five news sites |
| **v0.8** Backtest harness | The harness doesn't lie | Synthetic profitable series → correct numbers; random walk → ~zero edge net of costs |
| **v0.9** ML signals | A real edge, or an honest no | **Clears the backtest gate**: DSR ≥ 0.95, positive net-of-cost after the full NGX stack, beats logistic regression and buy-and-hold out-of-sample. *Miss it → keep the data product, drop the signal layer.* |
| **v1.0** Web app | Family relies on it | Family members log in unprompted |
| **v2.0** Public beta | Strangers find it useful | Legal sign-off obtained; users return weekly without prompting |

## Health metrics to watch continuously

**Leading** (tell you early): correction rate falling filing over filing · connector run success rate · provenance completeness, which must sit at **100%** · review queue depth not growing.

**Lagging** (tell you it worked): companies covered × years of depth · % of expected filing periods present · weekly active users · revenue.

**The one that matters most:** *does someone who isn't you use it every week without being asked?* Everything else is a proxy for that.

## What "won" looks like

**Year one:** 20 NGX companies, 5 years deep, extraction reliable enough to trust without checking. Family uses it. You've stopped opening annual report PDFs.

**Year two:** A public data product people pay modestly for. Coverage metrics you'd show a buyer without flinching. The first analyst who says "I use this instead of building the spreadsheet."

**Year three-plus:** Either the licensed advice tier, or a second exchange, or an institutional client. All three are optional. **The dataset is the asset, and it's valuable regardless of which one happens.**

## And the honest floor

If the ML signals never clear the backtest gate, if the public tier never monetises, if no acquirer ever calls — **you still built the missing structured database of Nigerian corporate finance, and you still replaced your own weekly research routine with something better.** That outcome is worth the work on its own. Everything above it is upside.

---

# PART 5 — IS THE PLAN SET?

**Yes. The architecture and planning are laid, and they're built to be revised.**

## What is settled

**Direction** — data layer first, always ([PROJECT_CONTEXT.md](PROJECT_CONTEXT.md)).
**Access model** — build to public standard, restrict who logs in; multi-user from day one ([PROJECT_CONTEXT.md §4](PROJECT_CONTEXT.md)).
**Sources** — verified, priced, with fallbacks ([DATA_FOUNDATION.md Part 2](DATA_FOUNDATION.md)).
**Build order** — v0.1 → v2.5, backtest before signals, compliance front-loaded ([SPEC.md §1.3](SPEC.md)).
**Tasks** — T1–T21 with acceptance criteria ([SPEC.md §4.2](SPEC.md)).
**Schema** — base tables plus the six correctness completions ([OPERATIONS.md Part 1](OPERATIONS.md)).
**Invariants** — provenance on every number, never infer missing data, point-in-time only, backtest gate before capital ([SPEC.md §4.1](SPEC.md)).

## How to change it mid-build

The documents have **precedence**, so a conflict has one right answer rather than a debate:

> PROJECT_CONTEXT → SPEC → DATA_FOUNDATION → OPERATIONS

**To change something:** edit the highest-precedence document that owns it, note the change in the lower ones (the editorial headers in SPEC.md and DATA_FOUNDATION.md show the pattern), and **write an ADR** — context, decision, alternatives rejected, consequences, date ([OPERATIONS.md §3.1](OPERATIONS.md)). The ADR is what stops the same argument recurring in three months with a coding agent that can't see why the choice was made.

**Cheap to change later:** UI, delivery channels, model choice, hosting, company universe, indicator set.
**Expensive to change later:** canonical chart of accounts, entity identity model, provenance structure, the multi-user assumption, point-in-time discipline. Get these right before v0.4; revisit them only with a very good reason.

## Where to start

**This weekend: v0.1.** A Streamlit macro dashboard on FRED + World Bank, plus one manual NBS/CBN CSV. It's a weekend, and it proves the provenance-and-charting pattern that everything else reuses.

**In parallel, the team starts tasks A, B, and C** — universe, seed documents, golden set. None of them need code to exist, and all three are on the critical path.

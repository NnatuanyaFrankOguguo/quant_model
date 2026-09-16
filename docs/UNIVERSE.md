# The Company Universe

> **Decision A from the manual-work calendar** ([03_ROADMAP_PART1](03_ROADMAP_PART1_PHASES_0-6.md)),
> marked *"Blocks — everything downstream is sized by this."* Settled 2026-08-30.
>
> **This file is canonical.** It decides which PDFs get collected, how much extraction work
> exists, what the golden test set covers, and what any backtest runs on. It is also the
> universe referenced by `PREREGISTRATION.md` when P7 begins — so **changing it after a
> backtest has run invalidates that backtest**. Changes go through an ADR, dated.

---

## ⚠️ Verification status — checked 2026-09-16, three defects found

Every ticker below was checked against the exchange's own filing library
(`doclib.ngxgroup.com`), the companies' own investor-relations sites, regulatory filings, and
Nigerian financial press. **Twenty-two of the twenty-five ticker strings were correct.** The
three that were not are the reason this check was scheduled:

| # | What was wrong | What it is |
|---|---|---|
| 1 | **`WAPCO` is stale.** Holcim sold its 83.81% stake in Lafarge Africa to Huaxin Cement (~29 Aug 2025); shareholders approved the rename at the 30 Apr 2026 AGM, and NGX moved the symbol in July 2026. | Ticker **`HBMNG`**, legal name **HBM Nigeria Plc**. A pipeline keyed on `WAPCO` silently stops finding this company. |
| 2 | **`11PLC` was never a ticker.** The rename from Mobil Oil Nigeria to 11 Plc took effect on the exchange 11 Aug 2017, but the trading symbol did **not** change with it. | Ticker **`MOBIL`** for the whole of its listed life, to delisting on 7 May 2021. `11PLC` is the company's brand and domain, not its symbol. |
| 3 | **`FLOURMILL` is no longer listed.** Excelsior Shipping took it private under a CAMA §715 scheme; NGX suspended trading 16 Dec 2024 and removed it from the Daily Official List effective 30 Dec 2024. | It belongs in §2, not §1. Its price series ends in December 2024 and never resumes — a hard stop, not a gap that closes. |

The composition is unchanged: still the same twenty-five companies, so **no ADR is required**
— these are corrections of fact, not a decision about who is in. What did change is the split:
**21 live and 4 delisted**, which over-satisfies the survivorship requirement rather than
threatening it.

**Two fiscal year ends the earlier draft did not flag**, both of which matter more than a
ticker string because `OPERATIONS.md` §1.5's alignment rules key on them: **GUINNESS closes
30 June** and **AIRTELAFRI closes 31 March**. With FLOURMILL's 31 March, that is three of
twenty-five on a non-December year, not one.

**Confidence labels used below.** `CONFIRMED` — a primary source: the exchange's own filing
library, the company's own investor-relations site, or a regulator. `CONSISTENT` — two or more
independent secondary sources agree and no primary source was reachable. Where a date is
contested across sources, both are given rather than one chosen silently. Per
[00_START_HERE](00_START_HERE.md) §11, an unverified Nigerian market fact is a question, never
a fact — and §5 below lists what is still a question.

> **The exchange's own company-profile pages could not be read directly.** `ngxgroup.com`
> serves them as a JavaScript application, so the per-company pages return the same
> boilerplate whatever symbol is requested. Everything marked `CONFIRMED` therefore rests on
> the exchange's static filing library (`doclib.ngxgroup.com`, which serves real PDFs), a
> company's own site, or a regulator — not on the directory page itself.

---

## 1. The live universe — 21 companies

Chosen for three things at once: **liquidity** (they actually trade), **sector spread** (the
schema must survive all of them), and **audience interest** (these are the names Nigerian
retail investors, diaspora investors and analysts actually search for).

### Banks — 5

| # | Company | Ticker | FYE | Confidence | Why it is here |
|---|---|---|---|---|---|
| 1 | Guaranty Trust Holding Company Plc | `GTCO` | Dec | CONFIRMED | The **golden-set bank**. Holdco restructuring makes its statement history genuinely hard — exactly the instructive case. `TEAM_BRIEF` names it. |
| 2 | Zenith Bank Plc | `ZENITHBANK` | Dec | CONSISTENT | Consistently among the most traded; a clean tier-1 comparison against GTCO. |
| 3 | Access Holdings Plc | `ACCESSCORP` | Dec | CONSISTENT | Pan-African, acquisitive. Also the acquirer in the Diamond Bank merger (§2), which makes the identity-history test real. |
| 4 | United Bank for Africa Plc | `UBA` | Dec | CONSISTENT | Operations across ~20 African countries — the hardest FX translation of the five. |
| 5 | Stanbic IBTC Holdings Plc | `STANBIC` | Dec | CONFIRMED | Bank plus asset management. Different revenue shape again. |

**Why five banks and not two:** banks are the case the docs warn about most — *"a schema built
on MTN will not survive a bank"* — and the canonical chart of accounts has to be proven against
several, not one. Banks report *gross earnings*, not *revenue*. They are also what the B2B
buyers in `PROJECT_CONTEXT` §9.2 care about most.

**Zenith is mid-transition and it is not finished.** The central bank gave approval in
principle for a holdco in March 2023 and shareholders approved a scheme of arrangement at an
EGM on 26 April 2024 to move into *Zenith Bank Holding Company Plc*. As of 2026-09-16 the
listed entity still trades as `ZENITHBANK` under the bank's own name, and reporting from July
2026 still describes Zenith as standalone. **Do not pre-empt this**: if the conversion
completes it becomes a fourth ticker-history row like the three in §4, and the identity table
already handles that.

### Telecoms — 2

| # | Company | Ticker | FYE | Confidence | Why it is here |
|---|---|---|---|---|---|
| 6 | MTN Nigeria Communications Plc | `MTNN` | Dec | CONFIRMED | **The golden test case.** See the verified FY2024 figures below. |
| 7 | Airtel Africa Plc | `AIRTELAFRI` | **Mar** | CONSISTENT | ✅ **Dual-listed on the LSE as `AAF`.** Reports in USD — confirmed from its own annual report. |

**MTN Nigeria's FY2024, verified against the company's own earnings release** (27 Feb 2025) —
all three figures this document carried were right:

| Figure | As published | Verdict |
|---|---|---|
| Total revenue | ₦3,360,830m, **+36.1%** | right |
| Loss after tax | ₦400,435m | right, to the million |
| Net foreign exchange losses | ₦925,361m | right, to the million |

> **One trap worth a test.** The same release headlines **service revenue** of ₦3,334,910m
> (+35.9%) alongside total revenue of ₦3,360,830m, and the audited profit-and-loss line shows
> ₦3,358,461m. Three defensible answers to "MTN Nigeria's FY2024 revenue", about ₦26bn apart.
> The golden pair for this company should pin which line `revenue` maps to, because an
> extractor that grabs the wrong one is not obviously wrong.

### Cement and construction materials — 3

| # | Company | Ticker | FYE | Confidence | Why it is here |
|---|---|---|---|---|---|
| 8 | Dangote Cement Plc | `DANGCEM` | Dec | CONFIRMED | Historically the largest NGX company by market capitalisation. Cannot be omitted. |
| 9 | BUA Cement Plc | `BUACEMENT` | Dec | CONFIRMED | The direct comparison to Dangote — the clearest peer-benchmarking pair on the exchange. |
| 10 | HBM Nigeria Plc | `HBMNG` | Dec | CONFIRMED | **Was `WAPCO` / Lafarge Africa until July 2026.** Foreign-parent reporting conventions, and now a second change of control to handle. |

**HBM Nigeria carries four identities and that is why it stays in.** West African Portland
Cement (listed 17 Feb 1979) → Lafarge Cement WAPCO Nigeria → Lafarge Africa (July 2014) → HBM
Nigeria (2026), with the symbol moving `WAPCO` → `HBMNG` in July 2026. One continuous
security, four names: precisely what `security_identifiers` exists to hold.

### Consumer goods — 3

| # | Company | Ticker | FYE | Confidence | Why it is here |
|---|---|---|---|---|---|
| 11 | Nestlé Nigeria Plc | `NESTLE` | Dec | CONFIRMED | Severe FX-driven losses post-float. A second, independent test of the same distortion that hit MTN. |
| 12 | Nigerian Breweries Plc | `NB` | Dec | CONFIRMED | Large, liquid, and has run substantial losses — tests that your sign handling is right. |
| 13 | Guinness Nigeria Plc | `GUINNESS` | **Jun** | CONFIRMED | Diageo's 58.02% sold to Tolaram, **completed 30 Sep 2024**. Ticker and legal name unchanged — an ownership change with no identity change, which is the cheap version of the test. |

### Oil and gas — 2

| # | Company | Ticker | FYE | Confidence | Why it is here |
|---|---|---|---|---|---|
| 14 | Seplat Energy Plc | `SEPLAT` | Dec | CONFIRMED | ✅ **Dual-listed on the LSE as `SEPL`.** Reports in USD. Renamed from Seplat Petroleum Development Company at the 20 May 2021 AGM; same ticker throughout. |
| 15 | Oando Plc | `OANDO` | Dec | CONFIRMED | Suspended for roughly six months — see the dates below. A live company with a real hole in its price history. |

**Oando's suspension, as precisely as the sources allow.** Technical suspension began **on or
about 18–23 October 2017** (sources give 18, 20 and 23 October; the day could not be pinned to
a primary document), triggered by shareholder petitions and the resulting SEC-ordered forensic
audit. The regulator directed the lift on 9 April 2018, trading reopened on 11 April, was
halted again the same day on a conflicting communication, and resumed without impediment at the
start of trading on **12 April 2018**. That flip-flop is a better trading-calendar test than a
clean six-month gap would have been.

### Agriculture — 2

| # | Company | Ticker | FYE | Confidence | Why it is here |
|---|---|---|---|---|---|
| 16 | The Okomu Oil Palm Company Plc | `OKOMUOIL` | Dec | CONFIRMED | Unusually high margins; a useful outlier for ratio sanity checks. |
| 17 | Presco Plc | `PRESCO` | Dec | CONFIRMED | Okomu's direct peer. A second benchmarking pair. |

### Insurance — 2

| # | Company | Ticker | FYE | Confidence | Why it is here |
|---|---|---|---|---|---|
| 18 | AIICO Insurance Plc | `AIICO` | Dec | CONFIRMED | **The third statement shape.** Insurers report gross premium written, net claims incurred and technical reserves — neither a bank nor a normal company. This is the pair that forces the `statement_template` enum fixed in [10_PRE_BUILD_CORRECTIONS](10_PRE_BUILD_CORRECTIONS.md) §2.7. |
| 19 | Custodian Investment Plc | `CUSTODIAN` | Dec | CONFIRMED | Insurance plus investments — a hybrid that stresses the template choice further. Renamed from Custodian and Allied Plc (CAC approval 24 May 2018); some aggregators still index the old `CUSTODYINS`, and the ISIN still carries the legacy fragment. |

### Conglomerate and other — 2

| # | Company | Ticker | FYE | Confidence | Why it is here |
|---|---|---|---|---|---|
| 20 | Transnational Corporation Plc | `TRANSCORP` | Dec | CONFIRMED | Power, hospitality and energy in one entity — segment reporting that does not fit a single template. |
| 21 | Nigerian Exchange Group Plc | `NGXGROUP` | Dec | CONFIRMED | The exchange itself, listed on itself. Genuinely interesting to your channel audience, and a natural "about this data" story. |

**The Transcorp "restructuring" was not one.** Neither the ticker nor the legal name changed.
"Transcorp Group" is a brand; the registered name is still Transnational Corporation Plc, as
the FY2025 audited statements filed with the exchange confirm. Two separate 2024 events
produced the impression:

- **4 March 2024** — Transcorp Power listed by introduction on the Main Board, floating the
  power subsidiary as its own security beside Transcorp Hotels. The parent traded on unchanged.
- **28 October 2024** — a **1-for-4 share capital reconstruction**, 40.6bn shares down to
  10.2bn, which drove the reported ~300% price move that month.

That second one is a **corporate action this database must hold**, not a curiosity: a 1-for-4
consolidation with no adjustment factor makes the price look like it quadrupled overnight. It
belongs in the task E backfill with that exact date.

---

## 2. The delisted set — 4 companies, and why they are not optional

**These feel pointless and are not.** If every company in the universe is one that is healthy
*today*, then a backtest over 2019–2025 only ever tested companies that survived — and results
look far better than reality. The name for this is **survivorship bias**, and it is the most
common way a backtest lies to you.

Your own P7 check 11 requires it: *"a universe as of 2020 includes companies delisted in 2022."*
That check **cannot pass** unless these rows exist, and nothing in the plan was fetching them.

| # | Company | Ticker | What happened, and when | Confidence |
|---|---|---|---|---|
| 22 | Union Bank of Nigeria Plc | `UBN` | Titan Trust Bank's 89.4% purchase **completed ~1–2 June 2022**; last trading day **Fri 24 Nov 2023**; removed from the Daily Official List **Mon 27 Nov 2023**. The full legal merger into Titan Trust came later still, **1 Sep 2025** — three distinct dates, seventeen months between the first two. | CONSISTENT |
| 23 | Diamond Bank Plc | `DIAMONDBNK` | Merger into Access Bank took legal effect and the listing ended on the **same day, 1 April 2019**. Access traded as `ACCESS` then, and became `ACCESSCORP` on **28 March 2022** when Access Holdings listed in its place. | CONFIRMED |
| 24 | 11 Plc (formerly Mobil Oil Nigeria) | `MOBIL` | Renamed on the exchange **11 Aug 2017** (AGM approval 24 May 2017) **without the ticker changing**. Delisting approved at the AGM of 14 Oct 2020 and effective **Fri 7 May 2021**, after NIPCO's tender at ₦417.12. | CONFIRMED |
| 25 | Flour Mills of Nigeria Plc | `FLOURMILL` | **Newly found to be delisted.** Taken private by Excelsior Shipping under a CAMA §715 scheme (court-ordered meeting 14 Nov 2024, minorities bought out at ₦86). Trading suspended **16 Dec 2024**; removed from the Daily Official List effective **30 Dec 2024**. Fiscal year end **31 March**, which the earlier draft had flagged for verification and which is confirmed. | CONFIRMED |

**The rename that was not a ticker change.** This document previously expected 11 Plc to test a
ticker change at a rename. It does not: the symbol stayed `MOBIL` throughout. The company that
*does* test that case is **HBM Nigeria** (`WAPCO` → `HBMNG`, July 2026), and the banks test it
twice more (`GUARANTY` → `GTCO`, `ACCESS` → `ACCESSCORP`). The test is still covered, by better
examples, and all three are live enough to fetch.

**If any of these cannot be verified or its price history cannot be obtained, replace it — do
not simply drop it.** Three substitutes were checked and all three genuinely delisted inside
the window: **GlaxoSmithKline Consumer Nigeria** (`GLAXOSMITH`, last trade 2 Feb 2024, removed
5 Feb 2024), **Continental Reinsurance** (`CONTINSURE`, last trade 16 Jan 2020, removed 17 Jan
2020), and **Skye Bank** (`SKYEBANK`, resolved by the deposit insurer in September 2018 but
removed from the list on **20 Aug 2019**, which is inside the window even though the resolution
is not). **The requirement is three, not these three** — and with FLOURMILL there are now four.

**Critical for Decision 1:** the free scraper cannot fetch a delisted company's history by
definition — the pages are gone. **These exist only if the paid data pull includes them.**
Add them to the download list explicitly; a bulk "current constituents" export will silently
omit every one.

---

## 3. What this universe is designed to prove

| Test | Covered by |
|---|---|
| Bank chart of accounts survives | 5 banks |
| Insurance chart of accounts survives | AIICO, CUSTODIAN |
| FX devaluation distortion handled | MTNN, NESTLE, NB |
| Loss-making years signed correctly | MTNN, NB, NESTLE |
| Non-December fiscal year-end | **Three of them**: FLOURMILL (Mar), AIRTELAFRI (Mar), GUINNESS (Jun) |
| Foreign-currency reporting | AIRTELAFRI, SEPLAT (both USD) |
| **Independent accuracy cross-check** | AIRTELAFRI + SEPLAT — LSE filings for the same periods, so you can check your extracted numbers against a second published source **for free** |
| Peer benchmarking works | DANGCEM/BUACEMENT, OKOMUOIL/PRESCO, GTCO/ZENITHBANK |
| Trading halts and suspensions | OANDO, Oct 2017 to 12 Apr 2018, including a one-day reversal |
| Ticker changed at a rename | HBMNG (was WAPCO), GTCO (was GUARANTY), ACCESSCORP (was ACCESS) |
| One company absorbing another | DIAMONDBNK → ACCESS, same-day on 1 Apr 2019 |
| Share consolidation | TRANSCORP, 1-for-4 on 28 Oct 2024 |
| Survivorship bias avoided | The 4 delisted names |
| Audience interest | MTNN, DANGCEM, GTCO, ZENITHBANK, NESTLE, AIRTELAFRI are the most-searched NGX names |

**The two dual-listed names are worth more than they look.** Airtel Africa and Seplat publish
the same financial year twice — once to NGX, once to the LSE. That gives you a **free,
independent ground truth** for extraction accuracy on two full companies, without hand-keying
anything. Use them as the first accuracy check in P4 before spending days on the golden set.
Note that Airtel Africa's year ends in March, so its "FY2025" is April 2024 to March 2025 and
sits nine months off MTN Nigeria's — do not compare the two on the fiscal-year label.

---

## 4. Identity history, ready for the alias table

These are the dated rows task F (`TEAM_BRIEF` §2.2) needs, gathered while verifying the
tickers. `valid_to` is **inclusive** throughout, matching `docs/08` §2.1.

| Security | Was | Became | On | Confidence |
|---|---|---|---|---|
| Guaranty Trust | `GUARANTY` | `GTCO` | **24 Jun 2021** — see the note below | CONSISTENT |
| Access | `ACCESS` | `ACCESSCORP` | **28 Mar 2022** (suspended 24 Mar) | CONSISTENT |
| Lafarge Africa | `WAPCO` | `HBMNG` | **~10–13 Jul 2026** | CONFIRMED |
| Stanbic IBTC | `IBTC` | `STANBIC` | Holdco listed **23 Nov 2012** (incorporated 14 Mar 2012) | CONSISTENT, and the old string is the weakest part |
| Custodian | name only, no ticker change | `CUSTODIAN` | CAC approval **24 May 2018** | CONFIRMED |
| Seplat | name only, no ticker change | `SEPLAT` | AGM **20 May 2021** | CONFIRMED |
| 11 Plc | name only, **no ticker change** | `MOBIL` | Rename effective **11 Aug 2017** | CONFIRMED |

> **The GTCO date disagrees with this repository's own worked example, and the example is the
> one that is wrong.** `docs/08` §2.1 and the fixtures in `tests/unit/test_identity.py` run
> GUARANTY to 2021-07-31 and start GTCO on 2021-08-01. Four different 2021 dates are defensible
> and none of them is 1 August: the exchange suspended GUARANTY on **18 June**, delisted its
> 29,431,179,224 shares and listed the holdco's identical count on **24 June**, GTCO's own
> history page calls **1 July** the day it became the parent, and the closing-gong ceremony was
> **13 July**. For the exchange event — which is what a ticker interval means — **24 June 2021**
> is the best supported. The tests are unaffected: they use those dates as an illustrative
> fixture and prove the mechanism, not the history. The *document's* example should carry the
> real date before anyone mistakes it for one, and this row is the source when it does.

---

## 5. Still a question

Nothing below blocks PDF collection. Each is recorded so that it is a known unknown rather
than an assumption someone later mistakes for a fact.

- **The exchange's own directory was never read.** `ngxgroup.com`'s company pages are a
  JavaScript application and returned identical boilerplate for every symbol. If you can open
  the directory in a browser and confirm the twenty-one live symbols in one pass, that upgrades
  most `CONSISTENT` rows to `CONFIRMED`. **This is the half-day the task was scoped for, and
  most of it is now done** — what is left is confirmation, not discovery.
- **Oando's first day of suspension** — 18, 20 or 23 October 2017 depending on the source.
  Matters only if a backtest starts inside that week.
- **Stanbic's old ticker string** (`IBTC`) is widely repeated but was the one rename that could
  not be corroborated the way the others were.
- **Zenith's holdco conversion** — approved, apparently not completed. Worth re-checking before
  P4 rather than now.
- **Whether Flour Mills has re-registered from Plc to Limited** since going private. No source
  either way. Does not affect the price series, which stops regardless.
- **The Lafarge–Huaxin minority lawsuit** (Strategic Consultancy Ltd) had a status-quo order
  pending appeal as of mid-2025, and its disposition could not be found. The rebrand and symbol
  change proceeded anyway.
- **The 11 Plc buyout price and date** — sources give October 2016 at $248m and March 2017 at
  $301m for NIPCO's purchase of ExxonMobil's 60%. The delisting date is not in doubt.

---

## 6. Scope notes

- **21 live + 4 delisted = 25**, at the top of the 15–25 range. If P4 extraction proves slower
  than budgeted, cut from the bottom of each sector — **never cut the delisted four**, and
  never drop below one bank plus one insurer.
- **Not included, deliberately:** the ~125 remaining NGX listings. `PROJECT_CONTEXT` §8 is
  explicit that breadth *"multiplies extraction work while adding little value"*.
- **Expansion order if this succeeds:** the rest of the NGX 30, then Ghana (GSE), Kenya (NSE),
  Egypt (EGX) — which is the move `PROJECT_CONTEXT` §9.5 says turns "Nigerian data company"
  into "African data company".
- **US universe** is separate and unconstrained — EDGAR is free and structured, so US coverage
  costs almost nothing per company.

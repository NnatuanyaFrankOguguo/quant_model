# The Company Universe

> **Decision A from the manual-work calendar** ([03_ROADMAP_PART1](03_ROADMAP_PART1_PHASES_0-6.md)),
> marked *"Blocks — everything downstream is sized by this."* Settled 2026-08-30.
>
> **This file is canonical.** It decides which PDFs get collected, how much extraction work
> exists, what the golden test set covers, and what any backtest runs on. It is also the
> universe referenced by `PREREGISTRATION.md` when P7 begins — so **changing it after a
> backtest has run invalidates that backtest**. Changes go through an ADR, dated.

---

## ⚠️ Verify the tickers before collecting

Every ticker and every delisting date below is **[NEEDS VERIFICATION]** against NGX's own
listing directory. They are drawn from general knowledge of the exchange, not from a source
document in this repository, and NGX tickers change on restructuring — `FBNH` became a
holdco, `TRANSCORP` restructured, and several banks reorganised into holding companies during
the window this universe covers. Per [00_START_HERE](00_START_HERE.md) §11, an unverified
Nigerian market fact is a question, never a fact.

**Half a day of checking, once, before task B (collecting ~100 PDFs) starts.** A wrong ticker
here means a wrong folder of PDFs and a company you cannot join to its own price history.

---

## 1. The live universe — 22 companies

Chosen for three things at once: **liquidity** (they actually trade), **sector spread** (the
schema must survive all of them), and **audience interest** (these are the names Nigerian
retail investors, diaspora investors and analysts actually search for).

### Banks — 5

| # | Company | Ticker | Why it is here |
|---|---|---|---|
| 1 | Guaranty Trust Holding Co | `GTCO` | The **golden-set bank**. Holdco restructuring makes its statement history genuinely hard — exactly the instructive case. `TEAM_BRIEF` names it. |
| 2 | Zenith Bank | `ZENITHBANK` | Consistently among the most traded; a clean tier-1 comparison against GTCO. |
| 3 | Access Holdings | `ACCESSCORP` | Pan-African, acquisitive. Also the acquirer in the Diamond Bank merger (§2), which makes the identity-history test real. |
| 4 | United Bank for Africa | `UBA` | Operations across ~20 African countries — the hardest FX translation of the five. |
| 5 | Stanbic IBTC Holdings | `STANBIC` | Bank plus asset management. Different revenue shape again. |

**Why five banks and not two:** banks are the case the docs warn about most — *"a schema built
on MTN will not survive a bank"* — and the canonical chart of accounts has to be proven against
several, not one. Banks report *gross earnings*, not *revenue*. They are also what the B2B
buyers in `PROJECT_CONTEXT` §9.2 care about most.

### Telecoms — 2

| # | Company | Ticker | Why it is here |
|---|---|---|---|
| 6 | MTN Nigeria | `MTNN` | **The golden test case.** FY2024: revenue up 36% to ₦3.36tn *and* a ₦400.44bn loss, driven by ₦925.36bn of FX losses. Messy in exactly the instructive way. |
| 7 | Airtel Africa | `AIRTELAFRI` | ✅ **Dual-listed on the LSE.** Reports in USD. |

### Cement and construction materials — 3

| # | Company | Ticker | Why it is here |
|---|---|---|---|
| 8 | Dangote Cement | `DANGCEM` | Historically the largest NGX company by market capitalisation. Cannot be omitted. |
| 9 | BUA Cement | `BUACEMENT` | The direct comparison to Dangote — the clearest peer-benchmarking pair on the exchange. |
| 10 | Lafarge Africa | `WAPCO` | Foreign-parent (Holcim) reporting conventions differ from the local majors. |

### Consumer goods — 4

| # | Company | Ticker | Why it is here |
|---|---|---|---|
| 11 | Nestlé Nigeria | `NESTLE` | Severe FX-driven losses post-float. A second, independent test of the same distortion that hit MTN. |
| 12 | Nigerian Breweries | `NB` | Large, liquid, and has run substantial losses — tests that your sign handling is right. |
| 13 | Guinness Nigeria | `GUINNESS` | Ownership changed hands (Diageo → Tolaram). A live test of ownership-change handling without a full delisting. |
| 14 | Flour Mills of Nigeria | `FLOURMILL` | Agro-industrial, thin margins, non-December year-end **[VERIFY the fiscal year-end]** — which is precisely what `OPERATIONS.md` §1.5's fiscal-alignment rules exist for. |

### Oil and gas — 2

| # | Company | Ticker | Why it is here |
|---|---|---|---|
| 15 | Seplat Energy | `SEPLAT` | ✅ **Dual-listed on the LSE.** Reports in USD. |
| 16 | Oando | `OANDO` | **[VERIFY]** Was suspended from trading for an extended period (~2017–2018) before resuming. A live company with a real gap in its price history — the cheapest possible test that your trading-calendar and halt handling work. |

### Agriculture — 2

| # | Company | Ticker | Why it is here |
|---|---|---|---|
| 17 | Okomu Oil Palm | `OKOMUOIL` | Unusually high margins; a useful outlier for ratio sanity checks. |
| 18 | Presco | `PRESCO` | Okomu's direct peer. A second benchmarking pair. |

### Insurance — 2

| # | Company | Ticker | Why it is here |
|---|---|---|---|
| 19 | AIICO Insurance | `AIICO` | **The third statement shape.** Insurers report gross premium written, net claims incurred and technical reserves — neither a bank nor a normal company. This is the pair that forces the `statement_template` enum fixed in [10_PRE_BUILD_CORRECTIONS](10_PRE_BUILD_CORRECTIONS.md) §2.7. |
| 20 | Custodian Investment | `CUSTODIAN` | Insurance plus investments — a hybrid that stresses the template choice further. |

### Conglomerate and other — 2

| # | Company | Ticker | Why it is here |
|---|---|---|---|
| 21 | Transnational Corporation | `TRANSCORP` | **[VERIFY the restructuring history]** Power, hospitality and energy in one entity — segment reporting that does not fit a single template. |
| 22 | NGX Group | `NGXGROUP` | The exchange itself, listed on itself. Genuinely interesting to your channel audience, and a natural "about this data" story. |

---

## 2. The delisted set — 3 companies, and why they are not optional

**These feel pointless and are not.** If every company in the universe is one that is healthy
*today*, then a backtest over 2019–2025 only ever tested companies that survived — and results
look far better than reality. The name for this is **survivorship bias**, and it is the most
common way a backtest lies to you.

Your own P7 check 11 requires it: *"a universe as of 2020 includes companies delisted in 2022."*
That check **cannot pass** unless these rows exist, and nothing in the plan was fetching them.

| # | Company | Ticker | What happened | Confidence |
|---|---|---|---|---|
| 23 | Union Bank of Nigeria | `UBN` | Acquired by Titan Trust Bank; subsequently delisted from NGX | **[NEEDS VERIFICATION — the delisting date especially]** |
| 24 | Diamond Bank | `DIAMONDBNK` | Merged into Access Bank, 2019. The acquirer (`ACCESSCORP`) is already in the live set, so this pair tests **identity history end to end**: two tickers, one surviving entity, and a date on which one stops and the other absorbs it | **[NEEDS VERIFICATION — ticker string and merger completion date]** |
| 25 | 11 Plc (formerly Mobil Oil Nigeria) | `11PLC` / `MOBIL` | Delisted following a buyout | **[NEEDS VERIFICATION — the ticker changed at the rename, which is itself a useful test]** |

**If any of these three cannot be verified or its price history cannot be obtained, replace it
— do not simply drop it.** Candidates to substitute: GlaxoSmithKline Consumer Nigeria (wound
down its Nigerian operations), Continental Reinsurance, or any bank resolved by the NDIC during
the window. **The requirement is three, not these three.**

**Critical for Decision 1:** the free scraper cannot fetch a delisted company's history by
definition — the pages are gone. **These three exist only if the paid data pull includes
them.** Add them to the download list explicitly; a bulk "current constituents" export will
silently omit every one.

---

## 3. What this universe is designed to prove

| Test | Covered by |
|---|---|
| Bank chart of accounts survives | 5 banks |
| Insurance chart of accounts survives | AIICO, Custodian |
| FX devaluation distortion handled | MTNN, NESTLE, NB |
| Loss-making years signed correctly | MTNN, NB, NESTLE |
| Non-December fiscal year-end | FLOURMILL **[verify]** |
| Foreign-currency reporting | AIRTELAFRI, SEPLAT (USD) |
| **Independent accuracy cross-check** | AIRTELAFRI + SEPLAT — LSE filings for the same periods, so you can check your extracted numbers against a second published source **for free** |
| Peer benchmarking works | DANGCEM/BUACEMENT, OKOMUOIL/PRESCO, GTCO/ZENITHBANK |
| Trading halts and suspensions | OANDO **[verify]** |
| Identity history / ticker reuse | DIAMONDBNK → ACCESSCORP, 11PLC rename |
| Survivorship bias avoided | The 3 delisted names |
| Audience interest | MTNN, DANGCEM, GTCO, ZENITHBANK, NESTLE, AIRTELAFRI are the most-searched NGX names |

**The two dual-listed names are worth more than they look.** Airtel Africa and Seplat publish
the same financial year twice — once to NGX, once to the LSE. That gives you a **free,
independent ground truth** for extraction accuracy on two full companies, without hand-keying
anything. Use them as the first accuracy check in P4 before spending days on the golden set.

---

## 4. Scope notes

- **22 live + 3 delisted = 25**, at the top of the 15–25 range. If P4 extraction proves slower
  than budgeted, cut from the bottom of each sector — **never cut the delisted three**, and
  never drop below one bank plus one insurer.
- **Not included, deliberately:** the ~125 remaining NGX listings. `PROJECT_CONTEXT` §8 is
  explicit that breadth *"multiplies extraction work while adding little value"*.
- **Expansion order if this succeeds:** the rest of the NGX 30, then Ghana (GSE), Kenya (NSE),
  Egypt (EGX) — which is the move `PROJECT_CONTEXT` §9.5 says turns "Nigerian data company"
  into "African data company".
- **US universe** is separate and unconstrained — EDGAR is free and structured, so US coverage
  costs almost nothing per company.

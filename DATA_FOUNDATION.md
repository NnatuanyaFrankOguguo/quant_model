# Financial Data Hub — Implementation-Ready Build Specification & Phased Roadmap

*Prepared for Frank (Lagos, NG). Verified as of August 26, 2026. Hand this document to AI coding agents as the source-of-truth spec.*

> **Editorial header (added when this file was created — not part of the original document):**
>
> This is **"Document A"** — the data foundation. [SPEC.md](SPEC.md) is the merged Doc A + Doc B build spec and references this file throughout ("per Doc A", "Doc A's schema", "Doc A's `securities` table"). **This document is the authority on data sources, the PDF pipeline, the base schema, and the regulatory research. SPEC.md is the authority on layering, build order, and the trading half.**
>
> **One reconciliation you must apply when reading:** §1.4, §4.6, §6.5, and §7.1 below state "no buy/sell language anywhere" and "NEVER generate recommendations" as absolute rules. Those were written before the personal/public access split existed. **They are now scoped to the public data tier only.** The personal tier — owner and family — may emit BUY/SELL, targets, and sizing; see [PROJECT_CONTEXT.md §4](PROJECT_CONTEXT.md) and [SPEC.md §1.2](SPEC.md). Everything else in this document stands unchanged.
>
> **A second reconciliation, for §7.1 (the master agent brief that agents "always load") — added 2026-08-30 by the pre-build audit:** §7.1 also states **"Stack now: Python 3.12, DuckDB/SQLite, Streamlit… Stack later: FastAPI, Postgres+Timescale"** and closes with **"if a task conflicts with SPEC.md, stop and ask."** Both are superseded:
> - **The stack claim is wrong for this build.** PostgreSQL 16 + TimescaleDB and FastAPI both stand up in **P0**, not later — [ADR-0001](docs/01_ARCHITECTURE.md) and ADR-0005 in `docs/01_ARCHITECTURE.md` §9. A Streamlit-only v0.1 has no server from which to derive `mode`, which SPEC.md §4.1 requires. Streamlit is a thin client over the API (ADR-0003), never a place logic lives.
> - **"Stop and ask" means "check for an ADR first."** ADR-0001, ADR-0002 and ADR-0005 are all deliberate conflicts with SPEC.md's literal task ordering. An accepted ADR is the answer. Only a conflict with no ADR needs asking — otherwise this clause halts every P0 task.
>
> **Reading order:** [PROJECT_CONTEXT.md](PROJECT_CONTEXT.md) (why) → [docs/00_START_HERE.md](docs/00_START_HERE.md) + [docs/10_PRE_BUILD_CORRECTIONS.md](docs/10_PRE_BUILD_CORRECTIONS.md) (the executable plan and its corrections) → this file (data foundation) → [SPEC.md](SPEC.md) (full build) → [OPERATIONS.md](OPERATIONS.md) (running it for years).

## TL;DR
- **Build the Nigerian data layer as the moat.** US company/macro data is a commodity (SEC EDGAR + FRED are free, structured, reliable); Nigerian listed-company financials are trapped in PDFs with no free structured API, so the act of structuring them IS the product. Start dead-simple (Python + DuckDB + Streamlit, local) and grow into FastAPI + Postgres/Timescale + Next.js only when a free tier or the personal-vs-public boundary forces it.
- **Stay firmly on the "instrument, not judgment" side of the line.** Under Nigeria's Investments and Securities Act (ISA) 2025, giving investment advice or managing others' money triggers SEC registration and heavy minimum-capital rules (full-scope fund managers now need ₦5 billion). A pure data/analytics tool where the *user* sets every assumption is on the safe side of that line as long as you generate no recommendations, no price targets, and manage no one else's money. Personal/family use has near-zero regulatory surface; going public switches on SEC-adjacent obligations and NDPA 2023 duties.
- **The realistic critical path:** v0.1 macro dashboard (a weekend) → v0.2 US analyzer (a week) → v0.3 manual Nigerian analyzer (a weekend) → v0.4 automated Nigerian PDF ingestion (the hard multi-week block — budget 2–3× your estimate) → v0.5 news → v0.6 scenarios → v1.0 hosted family app. PDF extraction is the single biggest risk and cost sink; everything else is well-trodden.

## Key Findings
1. **There IS an official NGX Market Data API** at `marketdataapiv3.ngxgroup.com/portal`, but it is a paid annual-subscription product in ~12 "products," not a free developer API. Confirmed International (USD) annual prices: Interday Prices (10-yr OHLCV) **$1,000/yr**, Ticker Prices **$2,000/yr**, Daily CapNet Report **$2,500/yr**, NGX News & Corporate Actions **$2,500/yr**, Index Values **$7,500/yr** (Local ₦450,000), Quotes (L1 + fundamentals) **$12,500/yr**. Apply via `marketdata@ngxgroup.com`. No free tier; the separate web X-DataPortal gives 7 days of free historical price data. **UPGRADE LATER only.**
2. **Free/near-free Nigerian price data is good enough for personal use.** `afx.kwayisi.org/ngx/` publishes the full daily NGX price list, per-ticker pages, ASI, volumes — scrapeable HTML, updated each trading day. `africanfinancials.com` hosts a deep archive of NGX annual-report PDFs (back to ~2011 for many names) plus AI summaries (treat summaries as unreliable; use the PDFs). `stockanalysis.com/quote/ngx/` and `african-markets.com` also carry NGX data.
3. **Nigerian macro data is download-only (PDF/Excel), no clean public API.** Statistician-General Adeyemi Adeniran announced the rebased CPI (base year 2024, weights 2023, 934 product varieties, COICOP 2018) at an Abuja briefing on 18 Feb 2025; the All-Items Index for Jan 2025 stood at 110.7, giving headline inflation of **24.48% y/y vs 34.80% in Dec 2024** (food inflation fell to 26.08% from 39.84%). **GDP was rebased to base year 2019** (backcast to 1981). CBN publishes FX (NFEM = official volume-weighted rate), money-market indicators, T-bill data, and a Statistics Database — HTML with "Export to Excel," no REST API. DMO posts bond/savings-bond auction results and Eurobond prices as PDFs.
4. **International mirrors of Nigerian macro ARE APIs — your v0.1 backbone.** FRED carries ~94 World-Bank Nigeria series (e.g., `FPCPITOTLZGNGA` annual CPI inflation = 33.24% for 2024). World Bank WDI (`wbgapi`) and IMF give free Nigeria coverage. Annual/low-frequency — fine for context, not monthly tracking (that needs NBS/CBN scraping).
5. **US data is fully solved for free.** SEC EDGAR `data.sec.gov` (companyfacts/companyconcept/submissions XBRL + full-text search + nightly `companyfacts.zip`) is free, no key, requires descriptive `User-Agent` and a 10 req/sec cap. FRED API is free with a key. yfinance works for US tickers (unofficial, fragile). This is v0.2.
6. **yfinance does NOT reliably cover NGX** (no working suffix; NGX tickers effectively absent). EODHD covers NGX under `.XNSA` (NGXGROUP.XNSA, NB.XNSA, MTNN.XNSA) with EOD + fundamentals, but fundamentals require paid (~$59.99/mo Fundamentals, or $99.99/mo All-In-One; entry EOD ~$19.99–$29.99). **EODHD is the best paid shortcut for NGX structured data** if PDF extraction proves too costly.
7. **Nigeria is NOT classified as hyperinflationary.** The Financial Reporting Council of Nigeria (FRC) ruled (Jan 2025, reaffirmed for FY2025) that **IAS 29 must NOT be applied** — only the cumulative-inflation indicator is met, not the qualitative ones. Nigerian IFRS statements stay historical-cost, but you MUST handle large FX translation losses (post-2023 naira float) and occasional restatements.
8. **Regulatory line is clear enough to design around.** ISA 2025 (signed by Tinubu, repealing ISA 2007) requires SEC registration for anyone "dealing in securities or providing services in relation to securities," incl. investment advisers and fund/portfolio managers. A data/analytics tool that never advises and never manages money is not a CMO. NDPA 2023 duties switch on when you store third-party personal data at scale.

## PART 1 — PRODUCT DEFINITION

### 1.1 Product thesis

Two halves with opposite economics. **US data is a commodity:** EDGAR gives every 10-K/10-Q as structured XBRL free; FRED gives every macro series free; dozens of apps present it well — no moat, so you build here only because it's cheap practice and reuses your DCF/ratio toolkit. **Nigerian data is trapped:** NGX-listed companies file audited statements as PDFs (NGX X-Compliance + IR pages); there is no free structured API; the official NGX API costs $1,000–$12,500/yr per product; macro agencies publish PDFs/Excel. **The scarce, valuable act is turning those PDFs into clean, queryable, provenance-tracked time series and explaining them accessibly.** That structuring — done once, maintained continuously — is the durable product and the reason a "common man" tool doesn't exist yet. *You are not building another charting site; you are building the missing structured database of Nigerian corporate and macro finance, wrapped in an accessible explainer, with US data bolted on free.*

### 1.2 v1 core user stories (Frank as sole user)

**Screen A — "Nigerian company, 5-year financial story":** pick an NGX company (Dangote Cement, GTCO, MTN Nigeria) → 5-year normalized income statement, balance sheet, cash flow + ratios (margins, ROE, ROA, leverage, liquidity, per-share), each number linking to its source PDF+page with an as-of date; plain-language LLM explanations grounded strictly in extracted numbers; price history alongside fundamentals.

**Screen B — "Nigerian macro in one dashboard":** one page with current + historical inflation (rebased 2024), MPR/policy rate, FX (NFEM + parallel context), GDP growth (rebased 2019), T-bill/bond yields, each with source and release date, and a note when a series was rebased/restated.

**Non-goals for v1:** no multi-user auth, no trading/execution, no real-time streaming, no mobile app, no recommendation engine, no portfolio optimization, no full-NGX coverage (start with 15–25 liquid names).

### 1.3 Non-goals per version
- **v0.1–v0.3:** no DB server, no auth, no hosting, no scraping automation, no LLM. Local files only.
- **v0.4:** no full-exchange coverage; no real-time; no accounts. Robust ingestion for a curated set.
- **v0.5–v0.6:** no alerts infra, no email/SMS, no payments.
- **Before v2.0:** no public sign-ups, no storing others' personal data, nothing resembling advice/management.

### 1.4 "Instrument, not judgment" → concrete UI/UX rules

> *Scoping note: these rules govern the **public data tier**. The personal tier (owner + family) is exempt — see the editorial header.*

1. **No buy/sell/hold language anywhere** (no "undervalued," "target price," "should," "recommend"); lint code and LLM output against a banned-phrase list.
2. **Every projection input is user-editable and visible** (discount rate, growth, terminal multiple as sliders); system supplies sourced defaults ("risk-free ≈ latest FGN 10-yr yield 22.60%") never a "correct" answer.
3. **The system never generates a price target** — only "given YOUR assumptions, DCF outputs X."
4. **Scenario sliders + sensitivity tables replace verdicts.**
5. **Always show provenance + as-of dates** (source doc, page/URL, retrieval timestamp, restatement flag).
6. **Persistent disclaimer:** "This tool presents data and lets you model your own assumptions. It does not provide investment advice, recommendations, or price targets. You provide the judgment."

## PART 2 — DATA SOURCES: VERIFIED INVENTORY

### A. NIGERIAN COMPANY DATA

**NGX X-Compliance (`ngxgroup.com/.../x-compliance-report/`)** — disclosure-tracking hub for all listed companies; statements land in `doclib.ngxgroup.com/Financial_NewsDocs/` (e.g., `NGX_Group_-_2025_AFS.pdf`). PDF + HTML; cadence = as companies file (quarterly UFS, annual AFS); several years' history; free to view. Publicly posted regulatory disclosures; polite scraping low-risk. **START HERE for filings discovery + PDF pull.**

**NGX Market Data API (`marketdataapiv3.ngxgroup.com/portal`)** — official paid API, JSON/XML, ~12 products (prices above). Apply `marketdata@ngxgroup.com` / `ddinnovation@ngxgroup.com`. No free tier; redistribution governed by NGX Data Agreement. **UPGRADE LATER (public product needing licensed real-time); AVOID now.**

**afx.kwayisi.org (`/ngx/`)** — free HTML: full daily NGX price list, per-ticker pages (`/ngx/<ticker>.html`) with price, ISIN, sector, YTD, volumes; ASI + daily summary. Updated each trading day ~16:00 WAT. Python wrapper `afrimarket` on GitHub. No explicit API license — polite scraping only, cache, attribute; single-point-of-failure risk. **START HERE for NGX prices.**

**africanfinancials.com** — free archive of NGX annual-report PDFs (e.g., `/document/ng-mtn-2024-ar-00/`), back to ~2011 for many names; also AI summaries. **Caveat: AI summaries carry an explicit "may contain errors, not financial advice" disclaimer — extract from the PDF, not the summary.** **START HERE for historical PDFs.**

**Company IR pages** — Dangote Cement, MTN Nigeria (`mtn.ng`), GTCO (`gtcoplc.com`), Zenith, UBA, Nestlé (`nestle-cwa.com`), Seplat (`seplatenergy.com`), Airtel Africa (`airtel.africa`); annual/interim PDFs, 5–10 yrs. **START HERE as canonical primary source.**

**Dual-listed (LSE): Airtel Africa, Seplat Energy** — file UK-standard RNS + IFRS statements alongside NGX, cleaner to parse, USD-reported. **START HERE for these two.**

**Paid vendors — verified NGX coverage:** EODHD covers NGX as `.XNSA` (EOD + fundamentals; Fundamentals ~$59.99/mo, All-In-One ~$99.99/mo) — **best paid NGX shortcut, UPGRADE LATER**; FMP strong US/EDGAR fundamentals from ~$22/mo but **NGX unconfirmed**; Polygon/Massive (from ~$29/mo) US-only, **AVOID for NGX**; Alpha Vantage (25/day free, $49.99/mo) **no NGX/Africa**; Twelve Data/Finnhub/Marketstack/Tiingo **no confirmed NGX equity coverage, AVOID for NGX**; Trading Economics has Nigeria macro (paid) **UPGRADE LATER**; iTick/Quantextive/RapidAPI datasets **unverified, AVOID until tested**; **yfinance NO reliable NGX coverage — AVOID for NGX, US only.**

**News/analysis houses:** Proshare, Nairametrics (RSS `/feed`, incl. proprietary Nairalytics series), BusinessDay (`/feed`), TheCable, Stears. **START HERE for news (RSS).**

**CSCS & SEC Nigeria (`sec.gov.ng`)** — CSCS = clearing (no public data API); SEC publishes CMO registers + rules. **Reference only.**

### B. NIGERIAN MACRO DATA

**NBS (`nigerianstat.gov.ng`, `microdata.nigerianstat.gov.ng`)** — CPI, GDP, unemployment, capital importation, trade, NLSS/GHS surveys. PDF + Excel; microdata catalog (catalog/154 = CPI). **CPI rebased to 2024 base (2023 weights), 934 varieties, COICOP 2018, new Farm Produce/Energy/Services/Imported-Food sub-indices; GDP rebased to 2019, backcast to 1981.** CPI ~mid-month for prior month; GDP quarterly. No REST API — scrape listing + parse PDF/Excel. **START HERE (scrape) for monthly macro.**

**CBN (`cbn.gov.ng/rates/`, `statistics.cbn.gov.ng`)** — MPR/MPC decisions & calendar (306th MPC = July 21, 2026), FX (NFEM volume-weighted official rate), money-market indicators, T-bill auctions/stop rates, money supply, reserves. HTML with "Export to Excel"; Statistics Database "LiveShop." No REST API. FX daily; MPR per MPC (~bi-monthly). **START HERE (scrape/Excel).**

**DMO (`dmo.gov.ng`)** — FGN bond auction results, FGN Savings Bond offers/allotments, Eurobond closing prices/yields, total public debt. PDF (docman). Monthly bond auctions; savings bonds monthly. **START HERE (scrape PDFs) for fixed income.**

**FMDQ (`fmdqgroup.com`)** — fixed income & FX quotations, web/PDF. **UPGRADE LATER.**

**Sector regulators:** NCC (telecoms subs), NERC (power), NNPC (oil), FIRS (tax) — periodic PDFs, useful for industry projections. **OPTIONAL.**

**International mirrors (free APIs):** FRED (~94 WB Nigeria series, `FPCPITOTLZGNGA` = 33.24% for 2024, updated Dec 2025) **START HERE**; World Bank WDI via `wbgapi`/`world-bank-data` (~1,600 indicators) **START HERE**; IMF IFS/WEO (rebased Nigeria figures) **START HERE**; OECD/Trading Economics **OPTIONAL/paid.**

### C. US COMPANY + MACRO DATA

**SEC EDGAR (`data.sec.gov`):** companyfacts (`/api/xbrl/companyfacts/CIK##########.json`), companyconcept, submissions; full-text search; frames; nightly `companyfacts.zip`/`submissions.zip`; Form 4 (insider), 8-K (M&A/pending deals). Zero-pad CIK to 10 digits. **Free, no key; mandatory descriptive `User-Agent` (name+email); ≤10 req/sec (use ~0.12s delay); 403/429 + ~10-min IP block if exceeded.** **START HERE.**

**FRED API** — CPI, Fed Funds, yield curve, unemployment, GDP; bulk; ALFRED vintages. Free key. **START HERE.** **BEA/BLS/Treasury Fiscal Data APIs** free. **START HERE for deeper US macro.**

**Prices:** yfinance (free, fragile, fine for personal US); Alpha Vantage (25/day free, $49.99/mo); Polygon/Massive (~$29/mo); Finnhub (60 calls/min free, US news 1yr); EODHD; Twelve Data; FMP (from ~$22/mo, best US fundamentals+EDGAR). **START with yfinance+EDGAR; UPGRADE to FMP for clean US fundamentals.**

**Corporate actions / earnings / estimates:** free-ish via Finnhub/yfinance; robust versions paid (FMP, EODHD calendar add-on ~$19.99/mo).

### D. NEWS AND EVENTS

**Free RSS:** Nairametrics `/feed`, Proshare, BusinessDay `/feed`, Punch business, Reuters Africa, company IR RSS. **START HERE.**

**News APIs (2026 free → cheapest paid):** Marketaux 100 req/day free (3 articles/req) → entry ~$29/mo (unconfirmed)/confirmed $199/mo; NewsAPI.org 100 req/day free (dev-only, 24h delay) → $449/mo (no mid-tier); GNews 100 req/day free (10 articles, 12h delay, non-commercial) → €49.99/mo; Finnhub news 60 calls/min free (US company news) → ~$50/mo est; Alpha Vantage NEWS_SENTIMENT 25 req/day free → $49.99/mo. **None explicitly confirm Nigerian-source coverage; Finnhub free is US-only; Alpha Vantage lists only NA/Europe/APAC.** **START with RSS; news APIs UPGRADE LATER, don't rely on them for Nigeria.**

**Entity tagging:** maintain your own alias table ("GTCO"/"Guaranty Trust"/"GTBank") + fuzzy match + LLM entity extraction over RSS.

**Structured events:** SEC 8-K (US M&A) + NGX corporate disclosures (aggregated at abokiforex.app/ngx-stocks/disclosures or scrape NGX) are your best structured event feeds.

**Economic calendars:** Trading Economics (paid), Finnhub (free tier); for Nigeria build your own from CBN MPC dates + NBS release schedule.

## PART 3 — THE NIGERIAN DATA PIPELINE

### 3.1 PDF extraction toolchain (honest tradeoffs)
- **pdfplumber** — best coordinate-level control, handles borderless tables via char positions, great debugger; needs per-layout tuning (~60% alone on messy pages). *Default text+table extraction from native PDFs.*
- **PyMuPDF (fitz)/PyMuPDF4LLM** — fast, clean Markdown output ideal for LLM prompts; less precise on complex tables. *Fast text dump + Markdown for the LLM step.*
- **camelot** — cleanest on *bordered* tables (lattice); fails on borderless/text-drawn separators (common in annual reports), needs Ghostscript, sparsely maintained in 2026. *Bordered tables only.*
- **tabula-py** — zero-config stream mode; column-merge errors on wide tables, JVM dep. *Quick batch on clean text-layer PDFs.*
- **Docling/unstructured (hi_res, infer_table_structure=True)** — ML-based, multi-format, structured HTML output; heavier/slower. *Mixed-format pipelines/RAG.*
- **LLM (Claude PDF/vision)** — handles messy/borderless/scanned, understands semantics; cost per call, must validate every number. *The reconciliation/extraction brain.*

**Recommended hybrid:** (1) PyMuPDF4LLM/pdfplumber → text + Markdown tables cheaply, detect native vs scanned; (2) OCR (tesseract + OpenCV) for scanned; (3) feed extracted text/tables (and, for hard pages, the page image) to **Claude with a strict JSON schema**; (4) run deterministic **validation**; (5) route low-confidence to a **human-review UI**. Lifts accuracy ~60% (rules only) → ~90%+ and bounds LLM cost (LLM reconciles, doesn't read every pixel).

### 3.2 LLM extraction design

**System prompt:** "You are a financial-statement data extractor. You receive text and tables from ONE company's audited statements. Extract ONLY numbers present in the source; never infer/estimate/fill gaps. Return JSON per schema. For each line item include source page and the verbatim label as printed. If absent, use null. Report values in the reporting currency/units exactly as stated, plus a `unit_multiplier`."

**Output JSON (abridged):** `{company, period_end, currency, unit_multiplier, statement, line_items:[{canonical_key, as_printed, value, page, confidence}], extraction_notes}` — e.g. MTN Nigeria FY2024 revenue 3,360,000,000,000 (unit_multiplier 1000) and "Loss for the year" -400,440,000,000.

**Validation (deterministic, post-LLM):** balance sheet `assets == liabilities + equity` (tolerance); cash-flow opening+net change == closing; cross-statement PAT ties; cross-year opening balances == prior-year closing; sign/units sanity (revenue>0, flag >5× swings). Any fail → `needs_review`, drop confidence, queue for human review.

**Confidence:** LLM self-report × validation-pass rate × table-quality; below ~0.85 → review.

**Human-in-the-loop UI:** Streamlit page showing PDF page image beside extracted JSON, editable fields, approve/correct; corrections stored as few-shot examples to improve future extraction.

### 3.3 Nigerian IFRS-specific issues
- **Naira devaluation / FX translation losses:** the post-June-2023 float produced enormous FX losses. MTN Nigeria Communications Plc reported a **loss after tax of ₦400.44 billion for FY2024** (vs a ₦137.02 billion loss in 2023) despite revenue rising 36% to ₦3.36 trillion; its net FX losses rose 24.98% to **₦925.36 billion** (from ₦740.43 billion in 2023) as the naira fell from ₦907.1/$ to ₦1,535/$ by end-2024. Capture FX loss as a distinct line; annotate that YoY comparisons are distorted by devaluation.
- **IAS 29 hyperinflation: NOT triggered** — FRC ruled Jan 2025 (reaffirmed FY2025) it must not be applied; only the cumulative-inflation indicator is met. Keep statements historical-cost; offer a real (inflation-adjusted) view only as a *user-selectable overlay* clearly labeled as YOUR computation.
- **Related-party, restatements, changing FY-ends:** store `restatement_flag`, `fiscal_year_end`, `restated_from`; never overwrite — version every statement.

### 3.4 Normalization schema (canonical chart of accounts)

Map US-GAAP XBRL tags AND Nigerian IFRS labels to common `canonical_key`s, e.g. `revenue` ← `Revenues`/`RevenueFromContractWithCustomerExcludingAssessedTax` / "Revenue","Turnover","Gross earnings"(banks); `operating_profit` ← `OperatingIncomeLoss` / "Results from operating activities"; `profit_after_tax` ← `NetIncomeLoss` / "Profit/(loss) for the year"; `total_assets` ← `Assets` / "Total assets"; `total_equity` ← `StockholdersEquity`; `cash_from_ops` ← `NetCashProvidedByUsedInOperatingActivities`. Banks need a parallel chart (gross earnings, net interest income, impairments, deposits) — build a `statement_template` per industry (financial vs non-financial).

### 3.5 Scraping architecture

Politeness (robots.txt; descriptive User-Agent + contact email; 1 req/2–5s per domain; nightly windows); rate limiting/backoff (token bucket per domain; exponential backoff on 429/5xx; ≤10 req/sec for EDGAR); caching (store every raw response + PDF keyed by URL+hash; never re-fetch unchanged via ETag/Last-Modified); change detection (hash listing pages, diff for new filings, enqueue only new docs); scheduling (APScheduler for v0; Prefect/Dagster later).

### 3.6 Data quality & provenance

Every number links to `source_document_id`, `page`, `retrieved_at`, `extraction_job_id`, `confidence`, `as_of_date`, and a `version` (incremented on restatement). Restatements create a NEW versioned row; old rows retained + marked superseded. This is the backbone of the "instrument, not judgment" trust promise.

## PART 4 — SYSTEM ARCHITECTURE

### 4.1 Recommended stack (solo dev + AI agents)

**v0 (now):** Python 3.12, **DuckDB** (analytics) or SQLite (v0.1), **Streamlit** UI, **Plotly**, APScheduler, all local. Zero infra, fastest iteration, your toolkit plugs in, agents build/verify a Streamlit page in one session.

**Production (v1.0+):** **FastAPI** (async, auto OpenAPI, fits connector pattern), **PostgreSQL + TimescaleDB** (hypertables for `price_history`/`macro_observations`), Redis (cache + rate-limit + queue), **Next.js** with **Recharts/ECharts** + TradingView **Lightweight Charts** for price panels, **Prefect**/Dagster orchestration. Deploy on **Railway/Render/Fly.io** (managed Postgres, low-ops) or a single VPS; **Supabase** (managed Postgres + auth) is the shortcut when you add multi-user.

**Why FastAPI over Django:** you don't need Django's admin/ORM/templating; FastAPI async + Pydantic fits the OpenBB-style fetcher pattern. **Why Streamlit before Next.js:** a one-user data explorer needs charts + tables, not a web framework; Streamlit ships Screens A/B in days. Migrate to Next.js only when you need auth/multi-user/public polish.

### 4.2 Database schema (production, PostgreSQL + Timescale) — key tables

`companies(id, name, country['NG'|'US'], cik, ngx_ticker, isin, sector, is_financial, fiscal_year_end)`; `securities(id, company_id, exchange, ticker, currency, UNIQUE(exchange,ticker))`; `source_documents(id, company_id, doc_type, url, file_hash, retrieved_at, UNIQUE(url,file_hash))`; `financial_statements(id, company_id, statement_type, period_end, period_type, currency, unit_multiplier, version, superseded_by, restatement, source_document_id, UNIQUE(company_id,statement_type,period_end,period_type,version))`; `statement_line_items(id, statement_id, canonical_key, as_printed, value NUMERIC, page, confidence, needs_review)`; `price_history(security_id, ts DATE, open/high/low/close, volume, source, PK(security_id,ts))` → `create_hypertable('price_history','ts')`; `macro_series(id, code['NG_CPI_YOY'…], name, country, unit, frequency, source['NBS'|'CBN'|'FRED'|'DMO'], base_period['2024=100'], notes)`; `macro_observations(series_id, ts, value, release_date, vintage, source_document_id, PK(series_id,ts,vintage))` → hypertable; `news_items(id, title, url UNIQUE, source, published_at, summary, company_ids BIGINT[])`; `events_filings(id, company_id, event_type['8-K'|'AGM'|'board_meeting'|'auction'], event_date, headline, url)`; `extraction_jobs(id, source_document_id, status['pending'|'done'|'needs_review'|'failed'], model, cost_usd, started_at, finished_at)`. For v0.1 the same schema runs in SQLite/DuckDB minus the hypertable calls. (Full DDL to be generated as task T2.)

### 4.3 Ingestion: connector/adapter pattern (OpenBB-inspired)

Model each source as a pluggable module with a common interface, echoing OpenBB's `Fetcher` design (transform_query → extract_data → transform_data returning validated Pydantic models); each provider is an independent registered extension so sources add/remove without touching core:

```python
class Connector(Protocol):
    name: str
    def discover(self) -> list[SourceRef]: ...      # find new docs/series
    def fetch(self, ref: SourceRef) -> RawPayload: ...
    def parse(self, raw: RawPayload) -> list[Record]: ...  # -> canonical records
```

Concrete: `EdgarConnector`, `FredConnector`, `WorldBankConnector`, `AfxKwayisiConnector`, `AfricanFinancialsConnector`, `NgxDoclibConnector`, `NbsCpiConnector`, `CbnRatesConnector`, `DmoAuctionConnector`, `RssNewsConnector`. Register in a dict; the scheduler iterates. Single most important extensibility decision.

### 4.4 Internal REST API (FastAPI)

`GET /companies?country=NG`; `GET /companies/{id}/financials?years=5&statement=income`; `/companies/{id}/ratios`; `/companies/{id}/prices`; `GET /macro/series/{code}/observations`; `GET /macro/dashboard/ng`; `GET /news?company_id=`; `POST /analysis/dcf` (body = user assumptions → outputs); `POST /analysis/sensitivity`; `GET /provenance/{line_item_id}`.

### 4.5 Valuation/analysis engine

Wrap your existing toolkit (ratios, DCF, comps, risk) as a stateless service behind `POST /analysis/*`. **All assumptions arrive in the request body from the user;** the engine returns outputs + assumption echo + sensitivity grid. It NEVER stores a "fair value" as a fact or emits a recommendation.

### 4.6 Where AI/LLM fits (guardrails)

PDF extraction (grounded, validated, never inferring); plain-language explanation ("gross margin fell from X% to Y% because COGS rose faster than revenue" — guardrail: "Explain only what the numbers show. Do NOT say whether the stock is a good/bad investment, no price targets, no recommendations"); news summarization + entity tagging; scenario narration (describe what a user's scenario implies mathematically, never endorse). **Banned-output filter**: post-process every LLM output through a regex/classifier rejecting "buy/sell/target/undervalued/recommend."

### 4.7 Caching, rate limiting, cost control

Cache all external responses; dedupe LLM calls by document hash (never re-extract the same PDF); per-provider token buckets; global LLM spend cap + alerts; batch EDGAR via nightly `companyfacts.zip`; log every LLM call's tokens + USD to `extraction_jobs.cost_usd`.

## PART 5 — VERSIONED ROADMAP

**v0.1 — Personal macro dashboard (a weekend).** One Streamlit page: Nigerian inflation (rebased 2024), MPR, FX (NFEM), GDP growth + US CPI/Fed Funds. Sources: FRED + World Bank WDI (auto) + one manual CBN/NBS CSV. Tech: Python+SQLite+Streamlit+Plotly, local. Done = you open it daily instead of hunting PDFs. Unlocks the provenance+charting pattern.

**v0.2 — US company analyzer (~a week).** Type a US ticker → 5-yr normalized statements + ratios + price chart. Sources: EDGAR companyfacts + yfinance. Adds `EdgarConnector`, canonical schema, your ratio/DCF toolkit. Done = Screen A for US names. Unlocks the analysis engine + normalization layer.

**v0.3 — Nigerian analyzer, MANUAL (a weekend).** Same Screen A for 5–10 NGX names, data hand-entered from annual reports via a CSV template mapped to `canonical_key`. Done = you can tell any NGX company's 5-yr story from clean data. Proves the schema handles IFRS before automating.

**v0.4 — Automated Nigerian ingestion (the hard block, 3–6+ weeks).** Replace manual entry with scraping (afx.kwayisi + africanfinancials + NGX doclib/IR) + hybrid PDF→LLM extraction + validation + human-review UI. Connectors, Claude extraction, APScheduler. Done = new filing → extract → approve low-confidence → live. **Budget 2–3×.** Unlocks the moat.

**v0.5 — News & events (1–2 weeks).** Per-company news (RSS + entity tagging) + events feed (NGX disclosures + 8-K + macro calendar from CBN MPC/NBS dates). `RssNewsConnector`, LLM tagging.

**v0.6 — Scenario/projection tools (2–3 weeks).** User-driven DCF, comps, sensitivity sliders, scenario narration — assumptions user-set, sourced defaults, no targets. `POST /analysis/*`.

**v1.0 — Real web app (1–2 months).** FastAPI + Postgres/Timescale + Next.js, hosted Railway/Render, Supabase auth, family logins. Full migration; connectors reused unchanged. Unlocks the multi-tenant seam.

**v1.5 — Screening, alerts, portfolio, risk (1–2 months).** Filter NGX by ratios; price/filing alerts; watchlists; portfolio risk (vol, drawdown, correlation) — all descriptive.

**v2.0 — Public beta (gated on legal).** Multi-user, compliance layer, data-redistribution licensing, NDPA registration, monetization. Only after personal validation AND legal sign-off.

## PART 6 — REGULATORY AND LEGAL

### 6.1 ISA 2025 — where the line is

Tinubu assented to the **Investments and Securities Act 2025**, repealing ISA 2007: regulates digital/virtual assets + commodities, strengthens SEC enforcement + AML/CFT, and revised minimum capital via **SEC Circular 26-1 (16 Jan 2026)**. That circular sharply raised operator capital: **full-scope fund managers must now hold ₦5 billion (up from ₦150 million)** and limited-scope managers ₦2 billion; PE managers ₦500m; VC managers ₦200m; and any manager with NAV/AUM over ₦100 billion must hold at least 10% of NAV/AUM — with a compliance deadline of **30 June 2027**. (Per SEC Nigeria's official checklist, the old Fund/Portfolio Manager registration required ₦150,000,000 minimum paid-up capital plus a Fidelity Insurance Bond covering ≥20% of that capital and at least three sponsored individuals including a Compliance Officer — now superseded by the ₦5bn full-scope threshold.) Anyone "dealing in securities or providing services in relation to securities" — brokers, **investment advisers**, **fund/portfolio managers**, underwriters, trustees — must register as a Capital Market Operator (CMO).

**The line:** presenting data + letting the user model their own assumptions is a data/analytics product, NOT a CMO activity. You cross into **investment advice** (registrable) the moment you tell a specific person what to buy/sell/hold or issue tailored recommendations/price targets, and into **fund/portfolio management** (registrable, now ₦5bn-capital-heavy) the moment you manage someone else's money at discretion. Staying a pure instrument keeps you outside CMO registration — **enforce this in code, not just in a disclaimer.** **SEC sandbox:** SEC Nigeria runs a regulatory incubation track for novel capital-market fintech; if v2.0 ever drifts toward advice/tokenization, apply to the sandbox rather than launch unlicensed (confirm current terms with SEC directly).

### 6.2 NDPA 2023

The **Nigeria Data Protection Act 2023** (enforced by NDPC) applies once you process personal data. Personal/family use is de minimis. Public launch triggers: lawful basis (consent/contract), data-subject rights (access/erasure), **72-hour breach notification**, and — if you become a **Data Controller/Processor of Major Importance (DCPMI)** — mandatory NDPC registration. The NDPC Guidance Notice (14 Feb 2024) deems an entity a DCPMI if it **processes the personal data of more than 200 data subjects in six months**; registration is required within 6 months, plus a **DPO** and possible annual audits, and **failure to register can attract fines of up to 2% of annual gross revenue or ₦10 million, whichever is greater.** Cross-border transfer (hosting abroad) needs documented adequate safeguards. **Design now:** keep user data minimal, segregate it, keep the auth layer swappable.

### 6.3 Data licensing & redistribution

**NGX Market Data is governed by a Data Agreement** restricting redistribution; paid API tiers come with dissemination terms. Vendors (EODHD etc.) license data for your use, not for you to re-serve raw. **Implication:** personal-use scraping/APIs for your own analysis is fine; a PUBLIC product must either (a) license redistribution from NGX/a vendor, (b) present only *derived/transformed* analytics (ratios, explanations) not raw redistributable feeds, or (c) show data with delays/attribution the source permits. Review before v2.0.

### 6.4 Scraping legality

Public regulatory filings (NGX X-Compliance, EDGAR) and public agency data (NBS/CBN/DMO) are low-risk to scrape for personal use; respect robots.txt, rate limits, ToS. Copyright subsists in the presentation/PDF, not the facts — extracting facts for analysis is defensible; wholesale re-hosting of others' PDFs/summaries is riskier. EDGAR explicitly permits automated access ≤10 req/sec with a User-Agent. **Rule: scrape politely, cache, attribute; for public launch prefer licensed/API paths for anything you redistribute.**

### 6.5 Concrete "instrument-side" design rules

> *Scoping note: public data tier only — see the editorial header.*

No recommendations; no auto price targets; user-set assumptions only; persistent disclaimer; no discretionary management of others' money; no pooling of family funds under your control; banned-phrase linting on all copy and LLM output.

### 6.6 What switches on at public launch

SEC CMO registration — not required personally (no advice/management); required only IF you add advice/management, else stay data-only. NDPA/NDPC — de minimis personally → likely DCPMI (register + DPO + audits) public. Data redistribution — own-use OK → must license NGX/vendor data or serve only derived analytics. Disclaimers/ToS/privacy — light → full ToS + privacy policy + consent. Auth/multi-tenancy/security — optional → mandatory.

## PART 7 — THE AGENT BUILD PACK

### 7.1 Master project brief (agents always load this)

> **Project:** Financial Data Hub. **Principle:** "You provide the instrument, they provide the judgment." Present data + let the USER set assumptions. NEVER generate recommendations, buy/sell language, or price targets. Every number carries provenance (source doc, page, timestamp) + as-of date. **Stage:** personal/family first; architecture must allow adding auth/multi-tenancy/compliance later without rewrite. **Stack now:** Python 3.12, DuckDB/SQLite, Streamlit, Plotly, APScheduler. **Stack later:** FastAPI, Postgres+Timescale, Redis, Next.js. **Data:** US = EDGAR + FRED (free); Nigeria = scrape afx.kwayisi/africanfinancials/NGX/NBS/CBN/DMO + LLM PDF extraction. **DoD:** typed, tested, documented, provenance-tracked, no banned phrases. Keep `SPEC.md` as source of truth; if a task conflicts with SPEC.md, stop and ask.

> *Scoping note: "NEVER generate recommendations" applies to the **public data tier**. On personal-tier tasks the governing invariants are [SPEC.md §4.1](SPEC.md) plus the access rules in [PROJECT_CONTEXT.md §4](PROJECT_CONTEXT.md).*

### 7.2 Monorepo layout

`finhub/` → `SPEC.md`, `pyproject.toml`; `core/`(schema.sql, models.py, canonical_map.py); `connectors/`(base.py, edgar.py, fred.py, worldbank.py, afx_kwayisi.py, african_financials.py, ngx_doclib.py, nbs_cpi.py, cbn_rates.py, dmo_auction.py, rss_news.py); `extraction/`(pdf_tools.py, llm_extractor.py, validation.py, review_ui.py); `analysis/`(ratios.py, dcf.py, comps.py, risk.py); `api/`(FastAPI, v1.0+); `app/`(Streamlit v0 / Next.js v1.0+); `scheduler/`; `tests/`.

> *Note: [SPEC.md §3.1](SPEC.md) supersedes this with the fuller monorepo layout that adds `/indicators`, `/ml`, `/backtest`, `/agents`, `/sentiment`, `/alerts`, `/portfolio`, `/execution`, `/compliance`. This layout is the v0.x subset of that.*

### 7.3 Coding standards / testing / DoD

Python: type hints everywhere, `ruff`+`black`, Pydantic v2 at every boundary. Tests: pytest; every connector has a `parse()` test vs a saved raw fixture; every validation rule has a unit test; golden-file tests for extraction on 3 known filings. DoD: passes tests + lint + type check; provenance populated; no banned phrases (automated check); docstring + README note per module.

### 7.4 v0.1→v1.0 decomposition into agent tasks (parallelizable)

T1 (no deps) repo scaffold + SPEC.md + pyproject + CI. T2 (T1) `core/models.py` + `schema.sql` + `canonical_map.py`. T3 (T2) `FredConnector`+`WorldBankConnector`. T4 (T2) `EdgarConnector`. T5 (T3) v0.1 Streamlit macro dashboard (Screen B). T6 (T4) v0.2 US analyzer (Screen A) + wire `ratios.py`. T7 (T2) CSV template + importer for manual NGX entry (v0.3). T8 (T7) `AfxKwayisiConnector`. T9 (T2) `pdf_tools.py` (native/scanned detect, text+table). T10 (T9) `llm_extractor.py`+`validation.py`. T11 (T10) `review_ui.py`. T12 (T8,T10) `AfricanFinancialsConnector`+`NgxDoclibConnector` wired to extractor (v0.4). T13 (T2) `NbsCpiConnector`,`CbnRatesConnector`,`DmoAuctionConnector`. T14 (T2) `RssNewsConnector` + tagging (v0.5). T15 (T6) `dcf.py` + sensitivity endpoint + scenario UI (v0.6). T16 (all) FastAPI + Postgres migration + Next.js + Supabase auth (v1.0). T3/T4, T8/T9, T13/T14 parallelize across agents; each has acceptance criteria (tests pass, data lands in schema, provenance populated).

> *Note: these T-numbers are Doc A's own and are **distinct from SPEC.md §4.2's T1–T21**. When assigning agent work, cite the document explicitly ("DATA_FOUNDATION T9", "SPEC T11") to avoid collision.*

### 7.5 Sample detailed prompts

**"Build the EDGAR companyfacts connector":** "Implement `connectors/edgar.py` conforming to `Connector`. Use `data.sec.gov` companyfacts + submissions. Descriptive `User-Agent` ('FinHub frank@example.com'); ≤8 req/sec with 0.12s sleep; zero-pad CIK to 10 digits; resolve ticker→CIK via `company_tickers.json`; map US-GAAP tags to `canonical_key` via `canonical_map.py`, trying alternates (`Revenues`→`RevenueFromContractWithCustomerExcludingAssessedTax`); write to `financial_statements`/`statement_line_items` with provenance. Pytest against a saved AAPL fixture; no network in tests."

**"Build the LLM PDF financial-statement extractor with validation":** "Implement `extraction/llm_extractor.py`. Input: a `source_document` PDF. Detect native vs scanned (PyMuPDF); OCR if scanned; extract text+Markdown tables; call Claude with the strict JSON schema in SPEC §3.2; parse to Pydantic; run `validation.py` (assets==liabilities+equity, cash-flow tie-out, cross-year opening=closing, magnitude sanity); compute confidence; set `needs_review` when confidence<0.85 or any check fails; store cost to `extraction_jobs`. Never infer missing numbers. Golden-file test on MTN 2024 AR."

**"Build the macro dashboard page":** "Implement `app/macro.py` (Streamlit): Nigeria inflation (rebased 2024 base — label it), MPR, NFEM FX, GDP growth (rebased 2019), US CPI + Fed Funds, pulled from `macro_observations`. Each chart shows source + release/as-of date; banner when a series was rebased/restated. Plotly. No advice language."

### 7.6 Working effectively with coding agents at this scale

SPEC.md is law (agents diff their plan against it, stop on conflict); one task = one PR-sized unit with explicit acceptance criteria, verify each before moving on; incremental verification (run tests + open the page after every task); context hygiene (give each agent only its task + SPEC + files it touches); pin decisions (schema, canonical_map) early — changing them mid-build is the main source of drift.

## PART 8 — RISKS, COSTS, HONEST CAVEATS

### 8.1 Monthly cost by version (USD)

v0.1–v0.3: data free (FRED/WB/EDGAR/scrape), hosting $0 local, LLM $0 → **~$0**. v0.4: free scrape, $0 local, ~$20–$80 Claude extraction (bounded by caching) → **~$20–$80**. v0.5–v0.6: free RSS (news APIs optional), $0–$10, ~$20–$50 LLM → **~$20–$60**. v1.0: free + optional EODHD $60–$100, hosting ~$20–$40 (Railway/Render+Postgres), ~$30–$60 LLM → **~$70–$200**. v2.0: + NGX/vendor licensing ($1,000–$12,500/yr ≈ $85–$1,040/mo) + Trading Economics, hosting ~$50–$200, ~$50–$150 LLM → **~$300–$1,500+**.

### 8.2 Top 10 things most likely to go wrong
1. **PDF extraction harder/slower than expected** → start manual (v0.3), automate incrementally, keep human review, budget 2–3×.
2. **A free source changes layout/disappears** (afx.kwayisi, africanfinancials) → connector abstraction + cached raw docs + documented paid fallback (EODHD `.XNSA`).
3. **LLM hallucinates a number** → deterministic validation + provenance + human review; never ship unvalidated figures.
4. **Rebasing/restatements corrupt time series** → vintages + versioning + visible rebase flags (in schema).
5. **You drift toward advice** → banned-phrase lint + design rules; a hard invariant.
6. **Redistribution licensing blocks public launch** → serve derived analytics, not raw feeds, until licensed.
7. **NGX/vendor cost surprises at scale** → free/scrape for personal, license only at v2.0 with revenue.
8. **Scope creep across NGX's ~150 companies** → curate 15–25 liquid names first.
9. **NDPA obligations underestimated at public launch** → keep personal data minimal and swappable.
10. **Agent drift on a big spec** → SPEC.md as law, small tasks, incremental verification.

### 8.3 Where estimates are most wrong

PDF extraction (bank statements especially — different chart of accounts) and the FastAPI/Next.js migration (auth + data migration always overrun). Everything FRED/EDGAR-based is fast and predictable.

### 8.4 If a key source disappears

Because every source is a connector and every raw doc is cached, losing one degrades gracefully: swap the connector (afx.kwayisi → african-markets → EODHD paid), backfill from cache, flag affected series stale until restored.

### 8.5 Honest feasibility verdict

For a solo intermediate-Python builder with AI agents: **v0.1–v0.3 and v0.6 are very achievable in weeks; v0.4 (Nigerian automated ingestion) is genuinely hard and is where months go; v1.0 is a solid quarter; v2.0 depends far more on legal/licensing than on code.** The moat (structured Nigerian data) is real precisely because it's hard — but tractable if you keep humans in the loop and don't chase full-exchange coverage early. Start this weekend with v0.1.

## Recommendations (staged, with go/no-go thresholds)
1. **This weekend — ship v0.1.** Stand up the Streamlit macro dashboard on FRED + World Bank Nigeria series + one manual CBN/NBS CSV. Threshold to proceed: you actually open it instead of hunting PDFs for a week.
2. **Next — v0.2 US analyzer on EDGAR + yfinance.** This validates your canonical schema and analysis engine on clean, free data before you touch a single PDF. Threshold: 5-year statements + ratios render correctly for 5 US names with provenance links.
3. **Then — v0.3 MANUAL Nigerian analyzer.** Hand-enter 5–10 NGX names (start with the dual-listed Airtel Africa & Seplat, then GTCO, MTN, Dangote Cement, Nestlé). This forces the IFRS/bank-chart edge cases into the open cheaply. Threshold: the schema survives a bank (GTCO) and a devaluation-hit telco (MTN) without modification.
4. **Only now — v0.4 automated ingestion.** Build the hybrid PDF→LLM extractor with human review. **Decision gate:** if, after 2 weeks, extraction accuracy on 10 filings is below ~85% after human review OR your monthly Claude cost trends above ~$100, **buy EODHD `.XNSA` fundamentals (~$60/mo)** for the price/fundamental layer and reserve LLM extraction only for statements EODHD lacks. This is the single most important cost/effort decision in the project.
5. **Defer all public-facing work (v2.0) until two conditions hold:** (a) you and your family have used it for ≥3 months and trust the numbers, and (b) a Nigerian securities + data-protection lawyer confirms your feature set stays on the data/analytics side of ISA 2025 and advises on NGX redistribution licensing + NDPC registration. **Never** add a feature that recommends, targets prices, or manages money without that sign-off — that is the threshold that converts a ₦0-capital hobby into a ₦5-billion-capital regulated business.

## Caveats
- **NGX API prices and news-API tiers** were partly assembled from JavaScript-gated pages and secondary sources — treat exact figures as indicative and confirm with the vendor before purchase. Several NGX API product prices (Most Active Trades, Issuer Share Price, Trade Data) and the full Local-NGN price table could not be verified.
- **SEC Circular 26-1 capital figures** (₦5bn full-scope fund managers, etc.) come from legal-advisory summaries (Mondaq/Vanguard) of the January 2026 circular; confirm the exact schedule with SEC Nigeria before relying on it. These apply only if you ever become a fund/portfolio manager — a pure data tool is unaffected.
- **NDPA DCPMI threshold** (>200 data subjects in six months) and penalty (up to 2% of gross revenue or ₦10m) come from the NDPC Guidance Notice via KPMG Nigeria; the NDPC updates guidance periodically — verify before public launch.
- **Free Nigerian sources (afx.kwayisi, africanfinancials) have no formal API contract or uptime guarantee** and could change or disappear; the connector/caching architecture is your insurance, and EODHD `.XNSA` is the documented paid fallback.
- **Nigerian macro release schedules and rebasing details** verified against NBS, CBN, and FRC primary sources as of Aug 2026; the IAS 29 "not hyperinflationary" position is FRC's current stance and could be reassessed if inflation re-accelerates.

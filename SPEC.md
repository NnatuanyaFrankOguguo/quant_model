# Unified Build Specification: Nigerian/US Financial Data & Intelligence Platform (Personal → Public)

*Single reference document for a multi-month, AI-agent-assisted build. Merges Document A (the data foundation) and Document B (the intelligence/signal/agent layers) into one coherent product spec, fills the gaps in both, and is written to be handed directly to Claude Code / agent teams. Verified as of August 27, 2026. Anything unverified or likely to change is explicitly flagged.*

> **Editorial notes (added when this file was created — not part of the original document):**
> 1. **Companion doc:** [PROJECT_CONTEXT.md](PROJECT_CONTEXT.md) holds the *why* (purpose, audiences, B2B/acquisition thesis, standing rules). This file holds the *what and how*. Read both.
> 2. **Access-model clarification (owner's intent, confirmed) — read before implementing §1.2:** **build scope ≠ access control.** The trading half (indicators, ML signals, backtest harness, memos, sizing) is to be **built to public standard for the general case — every use case, multiple users** — because it is intended to serve the public once the owner is licensed. What is restricted today is *who can log in*, not what the system can do. The owner intends to obtain **both** SEC registrations (adviser and fund-manager).
>    The five enforcement mechanisms in §1.2 are still correct as the seam. Two adjustments to how they are read:
>    - **`mode` is an entitlement, not a permanent audience.** Gate the advice tier on `entitlements` + a `licence_status` flag, so Part 6's decision gate (*"if users ask for advice/signals → get SEC-licensed before enabling any personal-mode feature publicly"*) is a config change plus a disclosure layer — not unpicking `PublicAnalysis`.
>    - **⚠️ Build multi-user from day one.** This is the expensive shortcut. Nothing in `/portfolio`, `/ml`, `/agents`, `/alerts`, or `/execution` may assume a single user: portfolios, watchlists, risk limits, alerts, and LLM spend caps are keyed by principal, and position sizing takes account equity as a **per-user parameter**, never a config constant. The DDL in §3.2 already does this correctly (`portfolios.owner`, `positions.portfolio_id`, `audit_log.principal`) — do not regress it into single-tenant convenience during v0.9–v1.5.
> 3. **Status: COMPLETE.** Parts 1–6 present.

---

## TL;DR
- **Document B's four "Levels" are not a parallel product — they are layers that sit on top of Document A's single data foundation, and the build order must interleave them with BACKTESTING inserted before any signal is ever trusted with capital.** The indicators layer feeds the ML layer, which is gated by the backtest harness, which feeds recommendations/execution — all reading the same `price_history`, `statement_line_items`, and `news_items` tables Document A already defines.
- **The one architectural decision that governs everything is the PERSONAL/PUBLIC mode gate.** Personal mode (his and his family's capital) may emit BUY/SELL, entry/stop/target, position sizing, and (last) execution; public mode must be data + user-set scenarios only, with no advice. This is enforced by a server-derived mode flag, separate output schemas, separate `/public`/`/personal` API namespaces, a compliance middleware with banned-phrase linting, and a dedicated compliance test suite — because Level 2's output is legally "investment advice" under Nigeria's ISA 2025, which would trigger SEC registration if it leaked into a public product.
- **Two hard realities shape the trading layers.** (1) There is no open retail API for programmatic NGX order execution — execution must be a manual order-ticket layer. (2) NGX round-trip costs run ~2–4% (a trade "needs roughly a 4.5% margin just to break even") and a ±10% daily price band that *halts* stocks plus a 100,000-share movement rule destroy naive backtests. And the LLM's "confidence: 72" must be replaced by a properly calibrated probability (isotonic/Platt via `CalibratedClassifierCV`, measured by Brier score), which is what feeds sizing and any kill switch.

---

## Key Findings
1. **Merge model:** one stack, not two products. Everything in Document B consumes Document A's normalized store. Backtesting (new v0.8) must ship *before* ML signals (v0.9); Level 4 execution is last and personal-only.
2. **Compliance is the spine, built first (T15), not last.** The public product must be architecturally incapable of emitting advice.
3. **Backtesting was the single biggest gap in both documents** and is the immune system against fooling yourself. It must model the full NGX cost stack, the ±10% halt, T+3, and thin liquidity, and validate with purged/combinatorial CV plus the Deflated Sharpe Ratio.
4. **Document B's recommended data sources (Alpha Vantage, NewsAPI, yfinance) do not cover NGX** — RSS-first ingestion is mandatory for Nigerian coverage.
5. **Library landscape verified for 2026:** TA-Lib now installs cleanly via official wheels; use `pandas-ta-classic` (the maintained successor); `ib_async` replaces the abandoned `ib_insync`; `python-telegram-bot` v22.8 is current; AutoGen is in maintenance mode (use LangGraph for production, CrewAI for prototyping).
6. **Nigerian tax changed materially (Nigeria Tax Act 2025, effective 1 Jan 2026)** — the portfolio tracker must model dividend WHT and the new share-CGT thresholds.

---

# PART 1 — UNIFIED PRODUCT ARCHITECTURE

## 1.1 The single mental model

The system is one stack. From bottom to top:

```
                 ┌─────────────────────────────────────────────┐
   DELIVERY      │ Next.js web · Telegram bot · Email · Streamlit│
                 └─────────────────────────────────────────────┘
                 ┌───────────────┬─────────────────────────────┐
   MODE GATE     │  PUBLIC MODE  │        PERSONAL MODE          │  ← compliance middleware
                 │ data/analytics│ signals·memos·sizing·execute  │
                 └───────────────┴─────────────────────────────┘
                 ┌─────────────────────────────────────────────┐
   L3 AGENTS     │ Bull / Bear / Risk / Arbitrator → memo        │
   L2 SIGNALS    │ ML model (calibrated) + BACKTEST GATE         │
   L1 INTEL      │ sentiment · daily brief · alerts              │
   INDICATORS    │ RSI/MACD/BBands/ATR… (features, not signals)  │
                 └─────────────────────────────────────────────┘
                 ┌─────────────────────────────────────────────┐
   VALUATION     │ DCF · ratios · comps (user assumptions)       │  ← Doc A
   NORMALIZED    │ canonical chart of accounts, provenance       │  ← Doc A
   INGESTION     │ PDF→structured (pdfplumber+PyMuPDF+LLM+HITL)   │  ← Doc A
   RAW SOURCES   │ NGX·EDGAR·FRED·afx·africanfinancials·RSS·CBN   │  ← Doc A
                 └─────────────────────────────────────────────┘
```

The indicators layer reads `price_history`; the ML layer reads indicators + point-in-time fundamentals + macro + sentiment; the agents read `statement_line_items` via RAG with provenance. There is exactly one data layer, and Document B's layers are consumers of it.

## 1.2 The two-mode architecture

**PERSONAL MODE** (Frank + family capital): may output explicit BUY/SELL signals, entry/stop/target prices, position sizing, and (last) execution tickets. This is legally "investment advice" and "portfolio management" — permissible only because he is managing his own and his family's money, not third-party funds for a fee.

**PUBLIC MODE** (anyone else): data, analytics, ratios, and user-supplied scenario calculators only. It must NEVER emit a system-generated recommendation, price target, or advice-shaped language. Under Nigeria's Investments and Securities Act 2025, giving investment advice or managing portfolios as a business requires SEC registration; full-scope fund managers face a ₦5bn minimum capital requirement (deadline June 2027 per Document A). Public mode is designed so that no SEC-registrable activity occurs.

### Enforcement in code (five mechanisms, all required)
1. **Feature flag / mode context.** A request-scoped `mode: Literal["personal","public"]` derived from the authenticated principal, never from a client-supplied parameter. Default is `public` (fail-safe). Personal mode requires the owner principal + a second factor.
2. **Separate output schemas.** Pydantic models: `PublicAnalysis` (no fields named `signal`, `recommendation`, `entry`, `stop_loss`, `target`, `position_size`) vs `PersonalSignal` (has them). The public serializer only accepts `PublicAnalysis`, so serializing a `PersonalSignal` into a public response is impossible.
3. **Separate API namespaces.** `/public/*` and `/personal/*` are different routers; `/personal/*` sits behind owner-only auth and, in a future multi-tenant build, simply is not exposed to tenants.
4. **Compliance middleware (output filter).** Every public-mode response passes a filter that (a) blocks any body typed as `PersonalSignal` and (b) runs banned-phrase linting on all free-text LLM output (Document A's list: "buy", "sell", "strong buy", "price target", "you should", "we recommend", "undervalued/overvalued" as verdicts, etc.). A hit raises `ComplianceBlock` → audited error, never a leaked response.
5. **Separate test suites.** `tests/compliance/` exercises the full public surface and asserts (i) no endpoint returns advice-shaped fields, (ii) the linter fires on a battery of known-bad outputs, (iii) `mode` cannot be escalated via any client input. CI fails the build otherwise.

This means the compliance/multi-tenancy layer can be added later without a rewrite: the seam already exists.

## 1.3 Unified version roadmap

| Version | Deliverable | Doc |
|---|---|---|
| v0.1 | Macro dashboard (FRED, CBN, NBS, DMO) — local Streamlit | A |
| v0.2 | US company analyzer (EDGAR ingest, ratios, DCF) | A |
| v0.3 | Manual Nigerian analyzer (upload PDF → normalized) | A |
| v0.4 | Automated Nigerian ingestion (PDF pipeline + HITL review) | A |
| v0.5 | News + sentiment + daily brief (Doc B **Level 1**) | B |
| v0.6 | Scenario engine (user-set assumptions) | A |
| v0.7 | Technical indicators engine (features only, no signals yet) | B |
| **v0.8** | **Backtesting harness + purged/CPCV + NGX cost model** | **B (new)** |
| v0.9 | ML signals w/ calibration — gated by v0.8 backtest gate (Doc B **Level 2**, personal) | B |
| v1.0 | Multi-agent research memos (Doc B **Level 3**) + hosted web app | B |
| v1.2 | Portfolio tracking + alerts | B |
| v1.5 | Paper trading (simulated fills w/ NGX costs) | B |
| v2.0 | Public beta (data-only, public mode) | A+B |
| v2.5 | Optional execution — US via Alpaca/IBKR; NGX manual ticket (Doc B **Level 4**, personal only) | B |

The critical reorder vs Document B: the backtest harness (v0.8) ships **before** ML signals (v0.9). No signal is trusted until it clears the backtest gate. Level 4 execution is last and personal-only.

---

# PART 2 — THE MISSING LAYERS

## 2A. Technical indicators layer

### Library landscape, verified 2026
- **TA-Lib**: the painful-install era is over. The maintainer now ships official binary wheels on PyPI (`pip install TA-Lib`); `ta_lib-0.7.1` wheels uploaded July 2026 cover CPython 3.9–3.14 on Windows (incl. win_arm64), macOS, and manylinux. Christoph Gohlke's `talib-build` provides Windows wheels and conda-forge `ta-lib` is current. The old "download from Gohlke / compile with MSVC" dance is no longer needed.
- **pandas-ta (original, twopirllc)**: effectively unmaintained. The community successor is **pandas-ta-classic** (`xgboosted/pandas-ta-classic`), first released Aug 2025, actively developed (v0.6.52, June 2026), 224+ indicators + 62 candlestick patterns, no TA-Lib dependency required, optional numba acceleration (6–230× on hot indicators), pandas 3.0 compat, uv+pip support. **This is the recommended default** — no C dependency, easiest for agents to install reproducibly.
- **ta (Bukosabino)**: usable lightweight pure-Python option. **finta, tulipy**: older; not recommended as primary.

**Recommendation:** pandas-ta-classic as default; TA-Lib via wheel only where its exact reference implementations matter. Avoid the original pandas-ta.

### Indicators that matter, with formulas
- **SMA(n)** = mean of last n closes. **EMA(n)**: `EMA_t = α·P_t + (1−α)·EMA_{t−1}`, `α = 2/(n+1)`.
- **RSI(14)**: `RSI = 100 − 100/(1+RS)`, `RS = avg gain / avg loss` (Wilder smoothing). Momentum; >70 "overbought"/<30 "oversold" are heuristics, not signals.
- **MACD**: line = EMA(12) − EMA(26); signal = EMA(9) of line; histogram = line − signal.
- **Bollinger Bands(20,2)**: middle = SMA(20); upper/lower = SMA ± 2σ(20).
- **ATR(14)**: average True Range, `TR = max(high−low, |high−prev_close|, |low−prev_close|)`. Drives stops and sizing.
- **OBV**: cumulative signed volume (+vol on up-close, −vol on down-close).
- **Stochastic**: `%K = 100·(close − low_n)/(high_n − low_n)`; `%D = SMA(3) of %K`.

### Honest treatment of technical analysis
The evidence is mixed-to-negative and heavily contaminated by data-snooping. The canonical survey — Park & Irwin, *Journal of Economic Surveys* 21(4):786–826 (2007), "What Do We Know About the Profitability of Technical Analysis?" — states verbatim: **"Among a total of 95 modern studies, 56 studies find positive results regarding technical trading strategies, 20 studies obtain negative results, and 19 studies indicate mixed results,"** while noting nearly all suffer "data snooping, ex post selection of trading rules… and difficulties in estimation of risk and transaction costs." Simple-rule profitability in US equities largely vanished after the late 1980s–early 1990s. **Conclusion: treat indicators as FEATURES for a properly validated ML model, never as standalone signals** — which is exactly why v0.7 precedes v0.9 and both are gated by v0.8.

### Code pattern
Compute indicators per ordered per-security series and store in an `indicators` table keyed by `(security_id, date, name, param_hash, value)` so features are point-in-time and reproducible. Never compute across a survivorship-filtered universe.

## 2B. ML signal generation

### Feature engineering
- **Price-derived**: log returns at 1/5/10/21-day horizons; realized volatility; indicator values; distance from moving averages; volume z-score.
- **Fundamental** (from `statement_line_items`, point-in-time, lagged to filing's known date): margins, ROE, debt/equity, revenue growth, multiples.
- **Macro** (vintage-aware): CBN MPR, T-bill yields, FX, CPI as known at the feature date (ALFRED-style vintages for FRED).
- **Sentiment**: rolling per-ticker aggregate of article scores.
- **Scaling & stationarity**: use returns not prices; standardize on the training fold only; consider fractional differentiation (López de Prado).

### Model choices
Gradient-boosted trees (**XGBoost / LightGBM**) are the right default for tabular financial data; verify versions at build time. **Logistic regression is the mandatory baseline** — if boosting can't beat it out-of-sample, you have no edge. Deep learning usually overfits and underperforms boosted trees on small, noisy financial tabular data.

### Target definition — the most under-discussed decision
- Naive next-day up/down is flawed (ignores volatility heteroskedasticity and stop/target paths).
- **Triple-barrier labeling** (López de Prado, *Advances in Financial Machine Learning*, 2018): set an upper barrier (take-profit), lower barrier (stop-loss), and vertical barrier (time limit); label = whichever is touched first, with barriers scaled to point-in-time volatility. Use a CUSUM filter to select events. This reflects what a real stopped trade would have experienced.
- **Meta-labeling**: a primary model decides side (long/short); a secondary model predicts whether to *act* (bet/no-bet), using the triple-barrier outcome as its label. This "separates the decision of trade direction (side) from the decision of trade sizing," raises precision, and yields a natural probability for position sizing.

### Probability calibration — replaces Document B's fake "confidence: 72"
Raw XGBoost/LightGBM outputs are decision scores, not calibrated probabilities. Fix with `sklearn.calibration.CalibratedClassifierCV`:
- **Platt scaling** (`method='sigmoid'`): fits a logistic map; good when distortion is sigmoid-shaped and data is limited.
- **Isotonic regression** (`method='isotonic'`): non-parametric monotonic map; more flexible, best with enough data, can overfit on small sets.
- **Discipline**: calibrate on a validation set independent of training, evaluate on a separate test set, and respect time ordering / purging.
- **Measure**: **Brier score** (lower is better) and **reliability diagrams** (predicted vs observed frequency; diagonal = perfect); also report Expected Calibration Error. Published examples show isotonic/Platt cutting Brier from ~0.18 uncalibrated to ~0.05, slightly favoring isotonic when data allows.
- **This calibrated probability — not an LLM self-report — feeds position sizing and any Level 4 kill switch.**

### Class imbalance, weights, noisy labels
Use López de Prado's uniqueness weighting for overlapping labels, `scale_pos_weight` for imbalance, and accept that financial labels are inherently noisy — do not chase training accuracy.

### Realistic performance expectations (sourced)
Directional accuracy in the low-to-mid 50s% is the realistic ceiling for liquid markets; even 52–55% can be profitable when risk/reward is favorable, because expectancy `= p·win − (1−p)·loss`. Reported backtest accuracies are usually inflated by look-ahead, survivorship, and multiple-testing bias.

On sentiment specifically, Kirtac & Germano ("Sentiment trading with large language models," arXiv:2412.19245) processed 965,375 Refinitiv **US** news articles (Jan 2010–Jun 2023) and report sentiment-to-return accuracy of **OPT 0.744, BERT 0.725, FinBERT 0.722 vs the Loughran-McDonald dictionary 0.501**, with a long-short OPT strategy reaching a Sharpe of 3.05 net of 10bps costs (355% gain Aug 2021–Jul 2023). **Flag clearly:** these are US-market sentiment-classification/return-association results, not a net-of-cost tradable edge on NGX. Document B's "70–80% sentiment / 55–65% directional" claims are therefore only partly defensible (the sentiment-classification piece, on US data) and **must be flagged as not established for NGX or for net-of-cost trading.**

## 2C. BACKTESTING — the critical missing piece

### Why backtesting is the immune system
Two literatures matter:
- **Multiple-testing / factor zoo:** Harvey, Liu & Zhu, "…and the Cross-Section of Expected Returns," *Review of Financial Studies* 29(1):5–68, state: **"A new factor needs to clear a much higher hurdle, with a t-statistic greater than 3.0. We argue that most claimed research findings in financial economics are likely false."**
- **Backtest overfitting:** Bailey, Borwein, López de Prado & Zhu — "Pseudo-Mathematics and Financial Charlatanism" and "The Probability of Backtest Overfitting." The probability of selecting an overfit strategy grows rapidly with the number of trials.

### Bias taxonomy with code-level prevention
- **Look-ahead bias**: never use data timestamped after the decision. Prevention: point-in-time feature store; every feature carries `known_as_of`; joins filter `known_as_of <= decision_date`.
- **Survivorship bias**: include delisted securities; Doc A's `securities` table retains delisted rows with `delisted_date`.
- **Data-snooping / overfitting**: track trial count K; apply the Deflated Sharpe Ratio; lock a one-touch holdout.
- **Restatement bias** (critical because Doc A stores restatements): features must use the statement version known at the decision date. Prevention: version every statement (`statement_version`, `first_available_date`) — exactly what FRED's ALFRED vintages do for macro and Doc A's versioned statements do for fundamentals.
- **Selection bias**: pre-register a fixed universe and window.
- **Adjusted-price sin**: store raw prices + a separate adjustment-factor series; reconstruct point-in-time adjusted prices only up to the decision date; never mix adjusted and raw.

### Transaction costs & slippage — Nigerian specifics (verified 2026)
NGX round-trip costs are unusually heavy and will dominate any high-turnover backtest:
- **Brokerage commission**: ~0.75%–1.35% (traditional brokers up to 1.35%; CardinalStone lowest tracked at 1.20%; app brokers vary — Chaka ~0.5% or ₦100 min, Bamboo ~1%). Negotiable component.
- **SEC fee** 0.3%; **NGX fee** 0.3% (sell); **CSCS fee** 0.3% (sell; some cite 0.06%–0.3%); **stamp duty** 0.075% (buy); **VAT** 7.5% on brokerage + regulatory fees (not principal); **CSCS trade-alert** ~₦4–6 flat per ticket.
- **Net effect**: NairaCompare (2026): a typical NGX trade **"needs roughly a 4.5 percent margin just to break even once all fees are added… a stock must rise about 4.5% before you make a single naira of profit on a quick buy-and-sell."** A round trip commonly costs ~2%–4%; app platforms adding a 1% platform commission push all-in buy cost to ~3.46%–4.06%.
- **Settlement**: T+3 — no same-day round trips; model the capital lock-up.
- **Price band / movement rule**: NGX imposes a **±10% daily price band that HALTS the stock for the day when hit** (it does not pause-and-resume like NYSE's 7/13/20% breakers or the LSE's 8%). Per Nairametrics (May 30, 2026): "The first is the ±10% daily price band. The second is the rule that requires **100,000 shares to change hands before a stock price can move at all.**" **Flag — regulatory in flux:** a revised tiered movement threshold (Group A ≥₦1,000: 10,000 units; Group B ₦500–999.99: 50,000; Group C <₦500: 100,000), SEC-approved June 16, 2026 and scheduled for Aug 17, 2026, was **postponed a day before rollout** (Nairametrics, Aug 16, 2026); the flat 100,000-unit rule remains in force as of this writing. A fill at the band price is often impossible — a backtest that assumes it is fictional.
- **Liquidity / free float**: many NGX stocks barely trade; thin volume + the band means assuming you filled at the close is often unreal. Model a participation cap (e.g., fills ≤ X% of that day's volume) and drop illiquid names.
- **US costs** for contrast: commission-free at Alpaca/major brokers, but model bid-ask spread + market impact — the honest cost is the spread you cross, not zero.

### Validation methodology
- **Standard k-fold CV is INVALID for time series** — it shuffles future into past and leaks overlapping labels. Do not use it.
- **Walk-forward** (expanding/rolling train → forward test).
- **Purged k-fold with embargo** (López de Prado): purge training observations whose labels overlap the test set; embargo a gap after the test block to kill serial-correlation leakage.
- **Combinatorial Purged CV (CPCV)**: generate C(N,K) train/test combinations → many out-of-sample paths and a *distribution* of performance, not one number. Libraries: `eslazarev/purged-cross-validation` (MIT, sklearn-compatible, implements purged/embargoed/CPCV + PSR/DSR/MinTRL) and `skfolio`'s `CombinatorialPurgedCV`.
- Reserve a final locked holdout touched exactly once.

### Performance metrics beyond return
- **Sharpe** = mean excess return / σ (annualized). **Sortino** = downside deviation only. **Calmar** = annual return / max drawdown. Plus **max drawdown, hit rate, profit factor**.
- **Probabilistic Sharpe Ratio (PSR)** (Bailey & López de Prado): probability the true Sharpe exceeds a benchmark, correcting for skew, kurtosis, and track length.
- **Deflated Sharpe Ratio (DSR)** (Bailey & López de Prado, *Journal of Portfolio Management* 40(5):94–107, 2014): corrects Sharpe for (a) non-normal returns and (b) selection bias under multiple testing, adjusting the significance threshold by the number of trials, skewness, and kurtosis. Illustratively, a nominal Sharpe of 2.0 can deflate to **DSR 0.30** (likely curve-fit), while a Sharpe of 1.0 with few trials can hold at DSR 0.85. **Report DSR with every strategy and record trial count K.**

### Frameworks in Python 2026 (honest comparison)
- **vectorbt** (open source): fastest for parameter sweeps (a 5-yr, 500-stock momentum backtest in ~0.7s vs backtrader's 14.2s); Jupyter-native; weak/unrealistic execution semantics (vectorized, no microstructure). Best "does this even have alpha?" triage. **vectorbt PRO** is a paid fork (~$499) with better features; the split has fragmented the community.
- **backtrader**: mature, event-driven, huge docs, live-trading/broker integrations (IBKR, Oanda) — but development has slowed and multiple 2026 sources advise against starting new projects on it.
- **zipline-reloaded**: Quantopian's Pipeline API for cross-sectional factor research; painful bundle-ingestion install.
- **backtesting.py**: fast prototyping and clean reports; small scale.
- **PyBroker**: ML-first with built-in walk-forward + bootstrapped metrics — methodology aligned with what you need.
- **NautilusTrader**: production-first, realistic order/execution semantics; steep curve; best if you'll deploy live.
- **QuantConnect LEAN**: end-to-end managed research+backtest+deploy; ecosystem lock-in.

**Recommendation for this project:** (1) **Roll your own vectorized daily backtester first** to bake in the NGX cost/band/liquidity model exactly and for learning value (matches his curriculum). (2) Use **vectorbt** for fast idea triage. (3) When a strategy graduates toward capital, re-run in an **event-driven engine** (NautilusTrader, or backtrader if you accept its maintenance state) for realistic fills. Use `purged-cross-validation`/`skfolio` for purged/CPCV + DSR. Feed all engines NGX daily data through the cost/participation model.

### Backtest harness spec + the "backtest gate"
- **Interface**: `run_backtest(strategy, price_data, cost_model, universe, start, end, cv=PurgedKFold|CPCV) -> BacktestResult`.
- **Inputs**: point-in-time features; raw prices + adjustment factors; `NGXCostModel`/`USCostModel`; participation cap; price-band halt logic; delisted securities.
- **Outputs**: equity curve; per-trade blotter; Sharpe/Sortino/Calmar/maxDD/hit-rate/profit-factor; **PSR + DSR with K recorded**; turnover; net-of-cost return.
- **Backtest gate (hard rule):** no signal reaches personal capital unless it passes pre-registered criteria — e.g., DSR ≥ 0.95 given recorded K; positive net-of-cost return after the full NGX cost stack; drawdown within tolerance; stable across CPCV paths (not one lucky path); and it beats both the logistic-regression baseline and buy-and-hold out-of-sample. Fail any → stays in research, never trades.

## 2D. Position sizing and risk management
- **Kelly criterion**: `f* = p − (1−p)/b` (b = win/loss ratio). Full Kelly assumes you know your edge exactly (you don't); **fractional Kelly (0.25–0.5×)** is standard to cut drawdown and estimation-error risk.
- **Fixed-fractional**: risk a fixed % of equity (e.g., 1%) per trade.
- **Volatility targeting / risk parity**: size inversely to volatility so positions contribute similar risk.
- **ATR-based**: size = risk budget / ATR-based stop distance.
- **Stops**: fixed %, ATR-based, trailing, time-based (the triple-barrier vertical). Honest note: stops cap losses but whipsaw in noisy/illiquid markets (acute on NGX with the band) — backtest them explicitly, don't assume they help.
- **Portfolio limits**: max position size, max sector exposure, max daily/weekly loss, max-drawdown circuit breaker, correlation cap.
- **Connect to his toolkit**: report Sharpe, Sortino, max drawdown, and VaR/CVaR (historical + parametric) at portfolio level.

## 2E. Multi-agent research system

### Frameworks 2026 (verified)
- **AutoGen** is in maintenance mode; Microsoft directs new users to the **Microsoft Agent Framework** (unifying AutoGen + Semantic Kernel). The community fork **AG2** exists but is pre-1.0.
- **LangGraph** is the production choice: graph-state machines, checkpointing, time-travel debugging, native human-in-the-loop, LangSmith observability, v1.0 stability — best for auditable, regulated workflows (this is one).
- **CrewAI**: fastest role-based prototyping; Flows adds deterministic control; weaker observability/checkpointing.
- **Claude Agent SDK / subagents** and **OpenAI Agents SDK**: strong for tool-use and sandboxed sub-agents.

**Recommendation:** prototype Bull/Bear/Risk/Arbitrator in **CrewAI** for speed; migrate the production memo pipeline to **LangGraph** for auditability, checkpointing, and human-in-the-loop (compliance requirements here).

### Academic/OSS context (verified, honest)
- **TradingAgents** (Xiao, Sun, Luo & Wang, arXiv:2412.20138, Dec 2024, updated through 2025; `TauricResearch/TradingAgents`) — the canonical multi-agent LLM trading framework with fundamental/sentiment/technical analysts, Bull/Bear researchers, a risk team, and traders; reports improved cumulative returns/Sharpe/max-drawdown vs baselines. **Honest caveat:** independent readers on the HuggingFace paper page flagged the results as "too optimistic," with concerns about data leakage and the fact that LLMs were pretrained on the test-period data — treat the outperformance as unproven for live trading.
- **FinRobot** (Yang et al., arXiv:2405.14767) and **FinGPT** (Yang, Liu & Wang, 2023) — real open-source financial LLM/agent platforms; useful references, not proven alpha.
- 2024–2026 follow-ups (FinMem, FinCon, FinAgent, HedgeAgents, ContestTrade, FinPos, LiveTradeBench) — active field, benchmark-fragile, none a proven money-maker.

### Bull/Bear/Risk/Arbitrator architecture
- **Bull Agent** — strongest evidence-based long case, citing only `statement_line_items`/filings with provenance IDs.
- **Bear Agent** — mirror; strongest short/avoid case, same data, forced citations.
- **Risk Agent** — quantifies downside: leverage, liquidity (NGX free-float/volume!), FX exposure, concentration, macro stress.
- **Arbitrator Agent** — weighs all three. **Public mode:** outputs bull case / bear case / risks / "what you should verify," **no verdict.** **Personal mode:** may add a recommendation + position sizing.
- **Anti-sycophancy/groupthink:** run Bull and Bear independently (no shared context) before the arbitrator sees both; require each to attack the other's strongest point; penalize unsupported claims; the arbitrator must cite which data points moved its conclusion.
- **Grounding:** RAG over `statement_line_items` with provenance + as-of dates; every numeric claim carries a source doc ID or the compliance linter strips it. Invariant: **never infer missing financial data.**

### Investment memo template
Exec summary → Bull case (cited) → Bear case (cited) → Risk factors (incl. NGX liquidity/FX) → Recommendation + sizing (personal only) / "What to verify" (public) → Data-provenance appendix with as-of dates.

### Cost control
Token budget per memo; cache by content hash of the input data bundle; model tiering — cheap model (Haiku-class) for ticker tagging + sentiment, expensive model (Sonnet/Opus-class) only for the arbitrator/memo synthesis; hard monthly spend cap with alerting.

## 2F. Sentiment analysis and the daily brief
- **Approaches:** LLM-based (Claude) for nuanced/ambiguous text; **FinBERT** (ProsusAI, ~85–87% F1 on financial sentiment) and FinBERT-Tone as cheap GPU-hostable classifiers; **VADER** as a near-free lexical baseline (weak on finance — ~0.50 accuracy in the FOMC study, barely above chance).
- **Do finance-specific models beat general LLMs in 2026?** On simple text FinBERT is competitive and far cheaper; but general LLMs (GPT-4o/4.1-class) outperform FinBERT on complex/ambiguous text at ~300–500× the per-document cost and 20–40× the latency (per the "Hybrid News Sentiment Engine" arXiv survey). An ICAIF 2025 paper found "task-specific finetuning may not transfer well across domains." **Recommendation: tier it** — FinBERT/VADER for bulk cheap tagging, LLM for ambiguous headlines and the brief narrative.
- **Nigerian news problem (verified):** Alpha Vantage, NewsAPI, Finnhub, and yfinance do NOT cover NGX/Nigerian sources meaningfully — Document B's suggested starters are unusable for NGX. **Specify RSS-first:** Nairametrics, Proshare, BusinessDay, Punch, TheCable, Nairalytics — with ticker tagging via an alias table (name variants → security_id) plus LLM entity extraction for ambiguous mentions.
- **Earnings calls:** US transcripts exist (Seeking Alpha, Motley Fool, FMP transcript API). For NGX, public transcripts largely do **not** exist — specify what's actually available: NGX "facts behind the results" presentations, investor presentations on IR pages, occasional conference-call recordings. Be honest about the gap; do not fabricate transcript data.
- **Daily brief:** prompt pulls watchlist prices + moves, new filings, top tagged news with sentiment, macro releases, and (personal only) fired signals → structured sections → delivered **push-first** (Telegram/email), not a dashboard you must remember to open.

## 2G. Alerts and delivery
- **Telegram:** `python-telegram-bot` v22.x (v22.8, Aug 2026), async (asyncio) since v20, Python 3.10+, supports Telegram Bot API 10.0; use `ApplicationBuilder` + `CommandHandler`. Push-first briefs beat dashboards for adherence.
- **Email:** SendGrid/Resend/SMTP. **Push:** web push or Telegram.
- **Alert types:** price threshold, new filing detected, unusual volume, macro release, signal fired (personal), risk-limit breached.
- **Scheduling & idempotency:** cron/APScheduler/worker; dedupe with an `alert_deliveries` table keyed by a content/idempotency hash so the same alert never sends twice.

## 2H. Portfolio tracking and paper trading
- **Schema:** positions (security, qty, avg cost basis), transactions (buy/sell/dividend/corporate action), realized/unrealized P&L, dividends, corporate actions.
- **Nigerian specifics (verified):**
  - **CSCS:** shares held electronically under a CHN; **T+3 settlement**; broker issues a contract note.
  - **Dividends:** subject to **10% withholding tax**; track gross vs net.
  - **Capital gains tax (Nigeria Tax Act 2025, effective 1 Jan 2026):** a real change. Per the Act's Explanatory Memorandum, gains on disposal of shares in Nigerian companies "shall not be chargeable gains where the (i) disposal proceeds, in aggregate, is **less than ₦150,000,000** and the chargeable gain **does not exceed ₦10,000,000 in any 12 consecutive months**" (threshold raised from the prior ₦100m), or where proceeds are reinvested in the same year of assessment. Above those, gains are chargeable. For **individuals**, CGT is no longer a flat 10% — gains are folded into progressive personal income tax bands (0%–25%); for **companies**, the rate rose to effectively 30%. The tracker must compute a rolling 12-month proceeds/gains total per person to flag when the exemption is exceeded, and compute after-WHT dividend income.
- **Paper trading:** simulate fills using the SAME NGX cost model, price-band halt logic, and participation cap as the backtester — before any real capital. This is v1.5 and a required gate before v2.5 execution.

## 2I. Execution (personal only, last)
- **US brokers:** **Alpaca** — commission-free US equities/ETFs via API, free paper account seeded with $100k virtual, `alpaca-py` library; paper accounts available to anyone globally (email signup). **Live** accounts for non-US residents are offered in 195+ countries, but if a country isn't listed under Country of Tax Residence only paper trading is available — **Nigeria eligibility for a live Alpaca account must be verified case-by-case with Alpaca support.** **Interactive Brokers**: broadest access (150+ exchanges), TWS/Gateway + API; the Python wrapper `ib_insync` is **no longer maintained** (its author, Ewald de Wit, passed away in early 2024) and IBKR now directs users to the maintained successor **`ib_async`** (`ib-api-reloaded/ib_async`). Tradier and others also offer APIs.
- **NGX execution reality (verified via targeted research):** **No mainstream Nigerian retail broker/app exposes an open, self-service REST/FIX API for programmatic NGX equity order placement.** Bamboo, Chaka/Hisa, Trove, Risevest, Meritrade, Stanbic IBTC (E-Trade), CardinalStone, ARM, Afrinvest/PlutusNeo, InvestNaija, i-invest, and Cowrywise are mobile/web apps where a human places orders; digital sub-brokers forward orders to a sponsoring NGX dealing member (Chaka via Citi Investment Capital; Bamboo via Lambeth Capital). Direct NGX FIX/DMA is restricted to **Trading License Holders** using a certified ISV order-management system. A few B2B/embedded APIs *claim* NGX routing (Trove's partner API via Sigma Securities; Cowrywise's embedded API via Meristem; mystocks.africa's beta "Partner API") but all require commercial partner onboarding, gate production access, route through licensed dealing members, and — in mystocks.africa's case — are unverified vendor marketing. **Therefore specify a MANUAL EXECUTION LAYER for NGX:** the system generates an order ticket (security, side, qty, limit price, rationale, risk checks passed), the human places it in his broker app, and the human confirms the actual fill back into the system, which updates positions and P&L.
- **Hard safety layer (US and NGX personal execution):** pre-trade assertion checks (position within limits; asset on whitelist; calibrated probability ≥ threshold; daily-loss halt not tripped; price-band sanity); a kill switch; max-daily-loss halt; position limits; allowed-asset whitelist; and a **required human confirmation step** in personal mode before any order. Level 4 "autonomous" execution is US-only (Alpaca/IBKR), gated behind proven L1–L3, and defaults to human-confirm.

---

# PART 3 — INTEGRATED SYSTEM ARCHITECTURE

## 3.1 Monorepo structure
```
/apps
  /web            # Next.js (v1.0+)
  /streamlit      # local v0.x dashboards
  /bot            # Telegram brief/alerts
/services
  /api            # FastAPI: /public/* and /personal/* routers
/packages
  /ingestion      # Doc A: connectors, PDF pipeline, HITL
  /normalize      # Doc A: canonical chart of accounts
  /valuation      # Doc A: DCF, ratios, comps
  /indicators     # 2A
  /ml             # 2B: features, models, calibration
  /backtest       # 2C: harness, CV, cost models, DSR
  /agents         # 2E: bull/bear/risk/arbitrator, memos
  /sentiment      # 2F
  /alerts         # 2G
  /portfolio      # 2H
  /execution      # 2I: US adapters + NGX manual ticket
  /compliance     # mode gate, banned-phrase linter, audit
  /common         # schemas, provenance, db
/db               # migrations / DDL
/tests            # unit, golden, compliance, synthetic-backtest
SPEC.md
```

## 3.2 New DDL (added to Doc A's schema)
```sql
CREATE TABLE indicators (
  security_id INT NOT NULL REFERENCES securities(id),
  date DATE NOT NULL,
  name TEXT NOT NULL,            -- 'rsi14','macd_hist', etc.
  param_hash TEXT NOT NULL,
  value DOUBLE PRECISION,
  PRIMARY KEY (security_id, date, name, param_hash)
);

CREATE TABLE ml_features (
  security_id INT NOT NULL,
  date DATE NOT NULL,
  feature TEXT NOT NULL,
  value DOUBLE PRECISION,
  known_as_of DATE NOT NULL,     -- point-in-time guard
  PRIMARY KEY (security_id, date, feature)
);

CREATE TABLE ml_models (
  id SERIAL PRIMARY KEY,
  name TEXT, version TEXT,
  trained_at TIMESTAMPTZ,
  train_start DATE, train_end DATE,
  algo TEXT,                     -- 'xgboost','lightgbm','logreg'
  calibration TEXT,              -- 'isotonic','sigmoid','none'
  brier_score DOUBLE PRECISION,
  params JSONB, artifact_uri TEXT
);

CREATE TABLE ml_predictions (
  model_id INT REFERENCES ml_models(id),
  security_id INT, date DATE,
  raw_score DOUBLE PRECISION,
  calibrated_prob DOUBLE PRECISION,   -- feeds sizing / kill switch
  side SMALLINT,                       -- -1/0/1 (meta-label)
  PRIMARY KEY (model_id, security_id, date)
);

CREATE TABLE backtest_runs (
  id SERIAL PRIMARY KEY,
  strategy TEXT, created_at TIMESTAMPTZ,
  universe TEXT, start DATE, "end" DATE,
  cost_model TEXT, cv_method TEXT,
  n_trials INT,                        -- K, for DSR
  sharpe DOUBLE PRECISION, sortino DOUBLE PRECISION,
  calmar DOUBLE PRECISION, max_dd DOUBLE PRECISION,
  hit_rate DOUBLE PRECISION, profit_factor DOUBLE PRECISION,
  psr DOUBLE PRECISION, dsr DOUBLE PRECISION,
  net_return DOUBLE PRECISION, passed_gate BOOLEAN,
  config JSONB
);

CREATE TABLE backtest_trades (
  run_id INT REFERENCES backtest_runs(id),
  security_id INT, entry_date DATE, exit_date DATE,
  side SMALLINT, entry_px DOUBLE PRECISION, exit_px DOUBLE PRECISION,
  qty DOUBLE PRECISION, gross_pnl DOUBLE PRECISION,
  costs DOUBLE PRECISION, net_pnl DOUBLE PRECISION,
  exit_reason TEXT                     -- 'tp','sl','time','band_halt'
);

CREATE TABLE signals (
  id SERIAL PRIMARY KEY,
  security_id INT, date DATE, mode TEXT,   -- 'personal' only for actionable
  model_id INT, calibrated_prob DOUBLE PRECISION,
  side SMALLINT, suggested_entry NUMERIC, stop_loss NUMERIC,
  position_size NUMERIC, time_horizon TEXT,
  backtest_run_id INT REFERENCES backtest_runs(id),  -- gate provenance
  reasoning TEXT
);

CREATE TABLE agent_runs (
  id SERIAL PRIMARY KEY, security_id INT, created_at TIMESTAMPTZ,
  mode TEXT, model_tier TEXT, token_cost NUMERIC, status TEXT
);
CREATE TABLE agent_messages (
  run_id INT REFERENCES agent_runs(id),
  role TEXT,                         -- 'bull','bear','risk','arbitrator'
  content TEXT, citations JSONB, created_at TIMESTAMPTZ
);
CREATE TABLE memos (
  id SERIAL PRIMARY KEY, run_id INT REFERENCES agent_runs(id),
  security_id INT, mode TEXT, body_md TEXT,
  provenance JSONB, created_at TIMESTAMPTZ
);

CREATE TABLE portfolios (
  id SERIAL PRIMARY KEY, owner TEXT, name TEXT, base_ccy TEXT, is_paper BOOLEAN
);
CREATE TABLE positions (
  portfolio_id INT REFERENCES portfolios(id),
  security_id INT, qty NUMERIC, avg_cost NUMERIC,
  PRIMARY KEY (portfolio_id, security_id)
);
CREATE TABLE transactions (
  id SERIAL PRIMARY KEY, portfolio_id INT, security_id INT,
  type TEXT,                          -- buy/sell/dividend/split/bonus
  qty NUMERIC, price NUMERIC, fees NUMERIC, tax NUMERIC,
  trade_date DATE, settle_date DATE,  -- T+3
  contract_note TEXT
);

CREATE TABLE alerts (
  id SERIAL PRIMARY KEY, type TEXT, target JSONB,
  channel TEXT, condition JSONB, active BOOLEAN
);
CREATE TABLE alert_deliveries (
  id SERIAL PRIMARY KEY, alert_id INT REFERENCES alerts(id),
  idempotency_hash TEXT UNIQUE,       -- no double-send
  sent_at TIMESTAMPTZ, channel TEXT, status TEXT
);

CREATE TABLE audit_log (
  id BIGSERIAL PRIMARY KEY, ts TIMESTAMPTZ, principal TEXT,
  mode TEXT, endpoint TEXT, action TEXT,
  compliance_result TEXT, payload_hash TEXT
);
```

## 3.3 Compliance middleware design
- Request → resolve `mode` from authenticated principal (never client input) → route to `/public` or `/personal`.
- Response → if `mode=public`: assert response type ∈ public schemas; run banned-phrase linter over all free-text; block + audit on any hit.
- All personal-mode actions and all compliance blocks write to `audit_log`.

## 3.4 Data flow (text)
```
raw sources → ingestion → normalized store (provenance, versioned)
   → indicators + features (point-in-time, known_as_of)
   → ML model → calibrated_prob → BACKTEST GATE
        ├─ FAIL → research only (never trades)
        └─ PASS →
              PERSONAL: signal → memo → sizing → human-confirm → execution (US API / NGX ticket)
              PUBLIC:   analytics + user-set scenarios ONLY (no signal)
```

## 3.5 LLM cost-control architecture
Per-feature token budgets; cache by content hash of the input bundle (identical inputs → cached memo/sentiment); model tiering (cheap: tagging/sentiment; expensive: arbitrator/memo); monthly spend cap with alert at 80%.

---

# PART 4 — THE COMPLETE AGENT BUILD PACK

## 4.1 SPEC.md invariants (agents always load)
1. **Provenance on every number** — every figure carries a source doc ID + as-of date.
2. **No advice in public mode** — public endpoints never emit signal/recommendation/target/sizing; the compliance linter is authoritative.
3. **Backtest gate before capital** — no signal trades unless it passed a recorded `backtest_run` meeting gate criteria (DSR, net-of-cost, baselines).
4. **Never infer missing financial data** — absent line items are marked missing, never estimated.
5. **Point-in-time only** — features/labels respect `known_as_of`; restated financials use the version known at the decision date.
6. **Mode is server-derived** — never trust a client-supplied mode.
7. **One-task-one-PR**, tests required, SPEC.md is source of truth.

## 4.2 Task decomposition (v0.1 → v2.0)
Each task: ID · title · deps · acceptance · files.

- **T1** Macro dashboard (v0.1) · deps none · AC: FRED/CBN/NBS/DMO series render locally with as-of dates · `/ingestion`, `/apps/streamlit`.
- **T2** EDGAR connector + US analyzer (v0.2) · deps T1 · AC: pull 10-K/10-Q with User-Agent ≤10 req/s; ratios + DCF with user assumptions · `/ingestion`, `/valuation`.
- **T3** Manual NG analyzer (v0.3) · deps T2 · AC: upload PDF → normalized statement with provenance · `/ingestion`, `/normalize`.
- **T4** LLM PDF extractor + HITL (v0.4) · deps T3 · AC: golden-file extraction ≥ threshold; human review queue · `/ingestion`.
- **T5** News RSS + ticker tagging (v0.5) · deps T3 · AC: Nairametrics/Proshare/BusinessDay ingested, alias-tagged · `/sentiment`.
- **T6** Sentiment tiering (v0.5) · deps T5 · AC: FinBERT/VADER bulk + LLM ambiguous; scores stored · `/sentiment`.
- **T7** Daily brief + Telegram (v0.5) · deps T6 · AC: scheduled push brief; idempotent · `/bot`, `/alerts`.
- **T8** Scenario engine (v0.6) · deps T2 · AC: user assumptions → DCF/ratio outputs, no auto targets · `/valuation`.
- **T9** Indicator engine (v0.7) · deps T1 · AC: RSI/MACD/BB/ATR/OBV/Stoch computed + stored; known-answer tests · `/indicators`.
- **T10** Cost models (v0.8) · deps none · AC: `NGXCostModel` (commission tiers, SEC/NGX/CSCS/stamp/VAT/alert, ±10% band halt, T+3, participation cap) + `USCostModel` (spread/slippage), unit-tested vs worked examples · `/backtest`.
- **T11** Backtest harness + purged/CPCV + DSR (v0.8) · deps T9, T10 · AC: synthetic-data tests pass (profitable series → right numbers; random series → ~0 edge); DSR + K recorded · `/backtest`.
- **T12** ML pipeline: triple-barrier labels + meta-labeling + calibration (v0.9) · deps T9, T11 · AC: calibrated_prob stored; Brier reported; purged CV; beats logreg + B&H OOS · `/ml`.
- **T13** Signal service + backtest gate (v0.9, personal) · deps T11, T12 · AC: signal only issued with a passing `backtest_run_id`; personal-only · `/ml`, `/api`.
- **T14** Multi-agent memo (v1.0) · deps T4, T12 · AC: bull/bear/risk/arbitrator; citations enforced; public = no verdict, personal = recommendation · `/agents`.
- **T15** Compliance middleware + audit (front-loaded, all versions) · deps none · AC: public endpoints cannot emit PersonalSignal; linter fires on bad battery; audit rows written · `/compliance`, `/api`.
- **T16** Hosted web app (v1.0) · deps T13, T14, T15 · AC: Next.js + FastAPI on Railway/Render; auth · `/apps/web`, `/services/api`.
- **T17** Portfolio tracker + NG tax/WHT (v1.2) · deps T2 · AC: cost basis, P&L, 10% dividend WHT, rolling 12-mo CGT threshold flag (₦150m/₦10m) · `/portfolio`.
- **T18** Alerts engine (v1.2) · deps T7 · AC: all alert types, idempotent deliveries · `/alerts`.
- **T19** Paper trading (v1.5) · deps T10, T13, T17 · AC: simulated fills w/ NGX cost + band + participation · `/portfolio`, `/execution`.
- **T20** Public beta (v2.0) · deps T15, T16 · AC: data-only public surface; compliance suite green · all.
- **T21** Execution: US API + NGX manual ticket + safety layer (v2.5, personal) · deps T13, T19 · AC: pre-trade asserts, kill switch, daily-loss halt, whitelist, human-confirm; `ib_async`/`alpaca-py`; NGX ticket + fill-confirm · `/execution`.

## 4.3 Sample prompts (highest-leverage tasks)
Each agent receives SPEC.md + the task's AC. Abbreviated intents:
- **PDF extractor (T4):** "Extract IFRS statement line items from this Nigerian annual-report PDF using pdfplumber + PyMuPDF for layout and Claude for mapping to the canonical chart of accounts. Emit every value with page/coordinate provenance and as-of date. NEVER infer a missing value — mark it null. Output must pass the golden-file test in tests/golden/."
- **Backtest harness (T11):** "Implement a vectorized daily backtester plus purged-k-fold and CPCV splitters (embargo configurable). Consume NGXCostModel and USCostModel. Model the ±10% price-band halt (no fills at the limit), T+3 settlement lock, and a participation cap = X% of daily volume. Report Sharpe/Sortino/Calmar/maxDD/hit-rate/profit-factor plus PSR and DSR with the trial count K. Provide synthetic-data tests."
- **ML pipeline (T12):** "Build features (returns, vol, indicators, lagged point-in-time fundamentals, macro vintages, sentiment). Label with triple-barrier (vol-scaled) + meta-labeling. Train XGBoost + logreg baseline with sample-uniqueness weights. Calibrate with CalibratedClassifierCV (compare sigmoid vs isotonic by Brier). Validate with purged CV. Store calibrated_prob."
- **Multi-agent memo (T14):** "Run Bull and Bear independently over RAG'd statement_line_items (citations mandatory), then Risk (liquidity/FX/leverage), then Arbitrator. In public mode output bull/bear/risk/'what to verify' with NO verdict; in personal mode add recommendation + sizing. Enforce token budget and content-hash caching."
- **Compliance middleware (T15):** "Implement mode resolution from principal, public/personal routers, response-type assertion, and banned-phrase linter. Provide the compliance test suite that proves no public endpoint can emit advice."
- **NGX cost model (T10):** "Encode commission tiers, SEC 0.3%, NGX 0.3%, CSCS 0.3%, stamp 0.075%, VAT 7.5% on fees, ₦4–6 alert, ±10% band, T+3. Unit-test round-trip cost against the ~4.5% break-even example."
- **Telegram brief (T7):** "python-telegram-bot v22 async app; scheduled brief pulling watchlist moves, new filings, tagged news + sentiment, macro releases; idempotent deliveries via alert_deliveries hash."
- **Indicator engine (T9):** "Compute RSI/MACD/BB/ATR/OBV/Stoch on price_history with pandas-ta-classic; store per (security,date,name,param_hash); known-answer tests vs hand-computed values."

## 4.4 Testing requirements
- **Golden-file tests** for extraction (fixed PDF → expected normalized JSON).
- **Known-answer tests** for valuation and indicator math (hand-computed vectors).
- **Synthetic-data tests for the backtester (mandatory):** feed a known-profitable synthetic series and assert it reports the correct Sharpe/return; feed pure random-walk data and assert it reports ~zero edge net of costs. This proves the backtester isn't lying to you.
- **Compliance suite:** full public surface asserts no advice leakage; linter battery.

## 4.5 Working with coding agents at scale
SPEC.md as single source of truth (invariants at top); one-task-one-PR with the task's AC as the PR checklist; incremental verification (tests green before merge); context hygiene (load SPEC.md + only the touched packages); avoid drift (agents may not add advice-shaped fields or bypass the backtest gate — CI enforces both).

---

# PART 5 — HOW THIS SERVES HIM AND OTHERS

## Personal value
Replaces his manual weekly workflow of hunting NGX PDFs, hand-keying statements into spreadsheets, and eyeballing valuations. It gives him a daily push brief (no more remembering to check five news sites), normalized fundamentals for any NGX/US name in seconds, DCF/ratio scenarios he controls, and — only after the backtest gate — calibrated, risk-sized signals for his own capital with a documented rationale and an audit trail. It saves hours per company and removes the "I forgot to look" failure mode.

## Family value

Shared visibility into the family portfolio; every decision has a written, cited memo and a reproducible backtest behind it; the mode gate + human-confirm step + hard risk limits protect against emotional, panic-driven decisions (the "sell in a dip" error the NGX guides warn about). *[Source: NairaCompare]*

## Public value by segment
- **Nigerian retail investors:** NGX fundamentals are trapped in PDFs and available nowhere accessible — this is the moat. A clean, provenance-backed data + ratio product is genuinely novel and useful.
- **Nigerian professionals/analysts:** saves the hours currently spent PDF-hunting and re-keying; normalized, comparable statements.
- **Diaspora investors:** real Nigerian-exposure data with as-of dates instead of stale or absent numbers.
- **Students/learners:** tied to his "Finance × Tech × Data" content — the transparent scenario engine and methodology are a content flywheel.
- **Small firms:** comparable-company and macro context without a Bloomberg terminal.

## What each version unlocks

v0.1 macro context; v0.2–0.4 the data moat (US then NG, manual then automated); v0.5 the daily habit (brief); v0.7–0.9 the personal edge (indicators → backtest → calibrated signals); v1.0 memos + a real web app; v1.2–1.5 portfolio truth + safe simulation; v2.0 a public data product; v2.5 personal execution convenience.

## Monetization ladder — honest assessment
- **Would actually pay:** an L1 dashboard/brief SaaS for retail at realistic Nigerian price points of roughly **₦5,000–₦15,000/mo**, though expect strong free-tier expectations and price sensitivity; L2 signals/API and L3 memos carry higher willingness-to-pay from professionals but are exactly the license-gated activities.
- **Freemium:** free = data + basic ratios + macro brief (public mode); paid = deeper history, exports, alerts, screening.
- **CANNOT be monetized without a license:** anything that constitutes investment advice or portfolio management for third parties triggers SEC Nigeria registration under ISA 2025 (and the ₦5bn full-scope fund-manager capital rule). So L2 signals, L3 recommendation memos, and L4 execution-for-others are OFF the table for a public product until licensed. Public mode monetizes data and tools; personal mode keeps the advice for himself and family.

---

# PART 6 — UPDATED COSTS, RISKS, AND HONEST CAVEATS

## Monthly cost table by version (personal → public)
- **v0.1–0.4 (personal, local):** ~$0/mo. Free tiers: EDGAR, FRED, afx.kwayisi.org NGX prices, africanfinancials PDFs, RSS. LLM extraction is small, batched pay-per-use.
- **v0.5–0.9 (personal):** LLM tokens for sentiment/brief + occasional memo drafting — tens of dollars/mo with tiering + caching; ML compute is local CPU (XGBoost) — negligible.
- **v1.0 (hosted):** Railway/Render + Postgres/Timescale + Redis (~$20–$60/mo starter) plus model-tiered, capped LLM memos. Doc A's public range ($300–$1,500+/mo) applies as usage grows.
- **v2.0 public + v2.5 execution:** add the NGX Market Data API paid tier if redistribution requires it ($1,000–$12,500/yr per Doc A) or EODHD .XNSA (~$60–$100/mo); Alpaca commission-free (US); NGX manual (no API cost). LLM spend scales with users — enforce spend caps.

## Top risks (with the new layers)
1. **Overfitting / data-snooping** — the #1 killer; mitigated by DSR, purged/CPCV, the backtest gate, and trial-count discipline.
2. **NGX illiquidity + ±10% band** — many stocks barely trade; backtests and live fills can be fictional. Mitigate with participation caps, band-halt modeling, and dropping illiquid names.
3. **LLM hallucination in memos** — mitigate with RAG-only grounding, mandatory citations, "never infer missing data," and the compliance linter.
4. **Execution bugs** — mitigate with paper trading first, hard safety asserts, kill switch, human-confirm.
5. **Regulatory drift** — ISA 2025 / SEC circulars / NDPA and the new Nigeria Tax Act CGT rules can change; keep the mode gate strict and revisit thresholds. NGX's own ±10% band and 100,000-share movement rule are actively under review (a tiered replacement was SEC-approved June 2026 but postponed just before an Aug 17, 2026 rollout) — monitor.
6. **Data-source fragility** — free NGX price sources and RSS feeds can break; adapters must degrade gracefully.

## The honest verdict

A solo builder with AI coding agents can realistically ship the data moat (v0.1–0.4), the daily brief (v0.5), the scenario/analytics tools, portfolio tracking, and a public data-only product (v2.0) — high-value and legally clean. The ML signal + backtesting layer (v0.8–0.9) is buildable and pedagogically worthwhile, but expect a thin, fragile edge at best, especially on NGX; keep it personal-only and be ruthless with the backtest gate. Multi-agent memos (v1.0) are useful structured research aids, not oracles. Autonomous execution (L4) should stay US-only, human-confirmed, and last.

## Decision gates — where to stop, buy, or abandon
- If **NGX free price/PDF sources prove too unreliable** → buy EODHD .XNSA (~$60–100/mo) or an NGX paid data tier before building more on top.
- If, after honest purged-CV + DSR testing, **no strategy clears the backtest gate** → abandon the signal layer for that market and keep the system as a data/analytics/brief product (still valuable).
- If **public traction appears and users ask for advice/signals** → stop and get SEC-licensed before enabling any personal-mode feature publicly.
- If **LLM memo spend or hallucination risk outweighs value** → downgrade to template-driven summaries over the structured data only.

---

*End of document.*

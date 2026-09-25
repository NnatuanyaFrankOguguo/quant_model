/**
 * The only place this app talks to the API. AD-3: the client renders what the server
 * returns and computes nothing of its own.
 *
 * Every call happens on the server (these are used from React Server Components), which
 * is not a performance choice. `docs/01` ADR-0006 puts mode derivation on the server, and
 * a browser that called the API directly would need the bearer token in the browser -
 * where it is one devtools tab away from anybody looking at the page.
 */

const API_BASE = process.env.QUANT_API_BASE ?? "http://127.0.0.1:8000";
const TOKEN = process.env.QUANT_API_TOKEN ?? "";

/**
 * Long enough for a cold Neon compute to wake up, which it does on the first request -
 * and longer still during a build, which is not the same problem.
 *
 * 45s is a budget for a reader waiting on a page. A build has nobody waiting, and since
 * `failTheBuildInstead` turns a failed fetch into a failed build, a slow API and an
 * unreachable one would otherwise look identical. Measured 2026-09-24: a 2.6-3.5s median
 * across three public routes with a single 29.7s outlier - two thirds of the reader's
 * budget, and near enough to it that a build would fail on a coin flip rather than on
 * anything being wrong. The guard still fires for an API that is genuinely not there; it
 * just no longer fires for one that is merely having a bad minute.
 */
const TIMEOUT_MS =
  process.env.NEXT_PHASE === "phase-production-build" ? 180_000 : 60_000;

export class ApiError extends Error {
  constructor(
    readonly status: number,
    readonly path: string,
    message: string,
    /** The API's own `detail` - "invalid_request", "not_found" - when it sent one. */
    readonly detail: string | null = null,
    /**
     * The query fields the API rejected, named as it names them ("query.growth").
     *
     * Carried because a refusal is sometimes the answer rather than the failure. The DCF
     * endpoint will not run without the caller's own discount rate, growth and terminal
     * growth - `DATA_FOUNDATION` 6.5's "user-set assumptions only" - and it says which
     * are missing here. A page that threw this away could only show "something broke",
     * when what happened is that the reader has not told it what to assume yet.
     */
    readonly fields: string[] = [],
  ) {
    super(message);
  }
}

/**
 * Call this first in the `catch` of any page that can be prerendered.
 *
 * A page that catches its own fetch failure and renders an error state is doing the
 * right thing at runtime and the wrong thing during `next build`. A static route is
 * prerendered at build time, so a caught failure is baked into the HTML as a static
 * artifact: the build exits 0, nothing warns, and the deployed page tells every visitor
 * the data could not be loaded. `revalidate` heals it only *after* somebody has already
 * been shown the error.
 *
 * At build time this rethrows and the build fails, which is the correct outcome - a
 * build that could not reach the API has not produced a publishable page. At runtime it
 * does nothing and the page renders its error state as before.
 */
export function failTheBuildInstead(error: unknown): void {
  if (process.env.NEXT_PHASE === "phase-production-build") throw error;
}

/**
 * Our budget expired. **Not** the same thing as the service failing, and a page must not
 * write it as one.
 *
 * `/ratios` was measured at a median of 8.4s with a single 52s tail, so this is a real
 * reader-facing case rather than a theoretical one. A page that says "it did not answer"
 * when the truth is "we stopped waiting" tells the reader something that is not so about
 * data that is perfectly fine - the same mistake as printing a zero for a missing figure,
 * which is the one thing this app treats as unforgivable.
 */
export class ApiTimeout extends Error {
  constructor(
    readonly path: string,
    readonly afterMs: number,
  ) {
    super(`no answer from ${path} within ${afterMs}ms`);
  }
}

/**
 * Whether a rejected fetch was our own deadline expiring rather than the service failing.
 *
 * **The whole cause chain, not just the thrown error.** `AbortSignal.timeout` rejects
 * with a bare `TimeoutError` in plain Node - which is what an earlier version checked for
 * and what the end-to-end test against a stalling socket exercises - but `fetch` is
 * patched here for caching, and a wrapper that rethrows as `TypeError: fetch failed` with
 * the real reason on `.cause` would slip straight past a check on the outer name. The
 * failure mode is silent and one-directional: the reader is told the data "could not be
 * loaded" when the truth is that we stopped waiting, which is precisely the distinction
 * `ApiTimeout` exists to preserve.
 *
 * Matches on the error *name* only, never on message text. A connection dropped
 * mid-response is a real failure and must keep reading as one - classifying that as slow
 * would be the same lie in the opposite direction.
 */
function isTimeout(error: unknown): boolean {
  let current: unknown = error;
  for (let depth = 0; depth < 5 && current instanceof Error; depth += 1) {
    if (current.name === "TimeoutError") return true;
    current = (current as { cause?: unknown }).cause;
  }
  return false;
}

async function get<T>(path: string, personal = false): Promise<T> {
  const headers: Record<string, string> = { Accept: "application/json" };
  if (personal && TOKEN) headers.Authorization = `Bearer ${TOKEN}`;

  let response: Response;
  try {
    response = await fetch(`${API_BASE}${path}`, {
      headers,
      signal: AbortSignal.timeout(TIMEOUT_MS),
      // Figures change when a connector runs, not when someone reloads. Sixty seconds is
      // short enough that a fresh filing shows up promptly and long enough that reading
      // three pages does not mean three round trips for the same answer.
      next: { revalidate: 60 },
    });
  } catch (cause) {
    if (isTimeout(cause)) {
      throw new ApiTimeout(path, TIMEOUT_MS);
    }
    // Everything else - DNS, connection refused, TLS, a connection dropped
    // mid-response - is the service genuinely failing, and stays a failure.
    throw cause;
  }
  if (!response.ok) {
    // The body is read before throwing because the API puts the *reason* there, and a
    // 422 from the DCF route is a sentence a page needs to render, not noise to swallow.
    const body: unknown = await response.json().catch(() => null);
    const shape = (body ?? {}) as { detail?: unknown; fields?: unknown };
    throw new ApiError(
      response.status,
      path,
      `${response.status} from ${path}`,
      typeof shape.detail === "string" ? shape.detail : null,
      Array.isArray(shape.fields)
        ? shape.fields.filter((f): f is string => typeof f === "string")
        : [],
    );
  }
  return (await response.json()) as T;
}

// ---------------------------------------------------------------------------
// Shapes. Only the fields this app renders, so a server-side addition does not
// have to be mirrored here before anything works.
// ---------------------------------------------------------------------------

export interface CompanySummary {
  ticker: string;
  legal_name: string;
  cik: string;
  exchange: string;
  statement_periods: number;
  latest_period_end: string | null;
  latest_filing_date: string | null;
  next_filing_form: string | null;
  next_filing_due_by: string | null;
  filing_overdue: boolean;
}

export interface PriceRef {
  date: string;
  close_raw: string;
  known_as_of: string;
  age_days: number;
  attribution: string;
  /**
   * The bar before this one, and the move between them.
   *
   * `change` is a fraction computed by the API on **adjusted** closes, which is why it
   * is sent rather than worked out here from the two `close_raw` figures. Those are as
   * traded: a split between the bars takes the raw close to a quarter, and a move read
   * off them would be -75% on a day the security rose. Measured on Apple's 2020 split -
   * raw closes say -74.15%, the adjusted move is +3.39%.
   *
   * Null when there is no earlier bar. A first day of trading has no move, and a zero
   * there would assert one.
   */
  previous_close_raw: string | null;
  previous_date: string | null;
  change: string | null;
  /** Corporate actions between the two bars. Above zero the raw closes are not comparable. */
  actions_between: number;
}

export interface Ratios {
  ticker: string;
  legal_name: string;
  as_known_on: string;
  period_label: string;
  period_end: string;
  known_as_of: string;
  filing_type: string;
  currency: string;
  attribution: string;
  price: PriceRef | null;
  ratios: Record<string, string | null>;
  inputs: Record<string, string | null>;
}

/**
 * Every input the model ran on, echoed back. The three rates are the reader's own; the
 * base cash flow, net debt and share count were read from the filings and each carries
 * the period it was read from, so the page can say so rather than implying the system
 * picked them.
 */
export interface DcfAssumptionsUsed {
  base_free_cash_flow: string;
  base_free_cash_flow_source: string;
  growth_rates: string[];
  discount_rate: string;
  terminal_growth: string;
  net_debt: string;
  net_debt_source: string;
  shares: string | null;
  shares_source: string | null;
  mid_year: boolean;
}

/** The full result, including every intermediate line, so the workings can be shown. */
export interface Dcf {
  ticker: string;
  legal_name: string;
  as_known_on: string;
  currency: string;
  assumptions: DcfAssumptionsUsed;
  projected_free_cash_flow: string[];
  discount_factors: string[];
  present_values: string[];
  sum_of_present_values: string;
  terminal_value: string;
  present_value_of_terminal: string;
  enterprise_value: string;
  equity_value: string;
  value_per_share: string | null;
  terminal_share_of_value: string | null;
}

/**
 * How much of each kind of thing is held. Three scalars the server counted, so the front
 * page prints them rather than working them out - see `failTheBuildInstead` above for the
 * other half of why a displayed figure belongs on the server.
 */
export interface HoldingsSummary {
  counted_at: string;
  companies: number;
  statement_periods: number;
  macro_series: number;
}

export interface MacroSeries {
  code: string;
  name: string;
  unit: string;
  frequency: string;
  /** What an index value is counted against, e.g. "CPI 2024=100". Null for a rate. */
  base_period: string | null;
  source_name: string;
  attribution: string;
  observation_count: number;
  latest_as_of: string | null;
  /**
   * When the latest observation became knowable - which is not the period it is
   * about. DESIGN.md §5 requires both dates beside every displayed figure. The API
   * has always returned this field; it was simply not mirrored here yet.
   */
  latest_known_as_of: string | null;
  latest_value: string | null;
  is_stale: boolean | null;
  /**
   * How long silence is normal for this series, and how long it has actually been.
   *
   * Both are the API's own, and `days_since_as_of` is here specifically so a page can
   * say *how* late a series is without subtracting two dates in a component - which
   * AD-3 forbids, and which would also be wrong, since the API measures it against its
   * own clock rather than the reader's.
   */
  expected_lag_days: number | null;
  days_since_as_of: number | null;
}

/**
 * One period of a series, at one vintage.
 *
 * Two dates, never one. `as_of_date` is the period the figure describes; `known_as_of`
 * is the day that figure became public. Nigerian CPI for August is published at the end
 * of September, so those two are routinely a month apart and on an annual series they
 * are more than a year apart. DESIGN.md §6 is built on the difference.
 *
 * `value` is null when the publisher's own record for that period carries no figure -
 * the API's schema says so in as many words ("null means genuinely no observation. It
 * is never zero-filled"). The row exists and was loaded; the number does not, which
 * makes it the publisher's absence rather than ours.
 */
export interface MacroObservation {
  as_of_date: string;
  known_as_of: string;
  value: string | null;
}

/**
 * One series and its points, newest vintage per period, in chronological order.
 *
 * `total_available` counts the *periods* the query matched, which is not the same number
 * as `MacroSeries.observation_count` - that one counts every stored vintage, so a series
 * revised many times holds more rows than it has periods. US CPI holds 3,362 rows across
 * 956 periods. Both are true and they answer different questions.
 *
 * `truncated` is the one field here that must never be ignored: the API returns the most
 * recent `limit` periods, so a partial series drawn as a whole one is a different series.
 */
export interface MacroObservations {
  code: string;
  name: string;
  unit: string;
  source_name: string;
  attribution: string | null;
  /**
   * The point-in-time cut. Null means each period is shown at its newest vintage - so a
   * figure that was revised shows the revision, not what was first published.
   */
  as_known_on: string | null;
  /** Periods matching the query, before any limit was applied. */
  total_available: number;
  /** True when fewer points came back than exist. The ones returned are the most recent. */
  truncated: boolean;
  observations: MacroObservation[];
}

export interface JobHealth {
  name: string;
  scheduled_at_utc: string | null;
  last_run_at: string | null;
  runs_in_window: number;
  rows_in_window: number;
  level: "ok" | "warning" | "error" | "never_ran";
  finding: string | null;
}

export interface HealthReport {
  checked_at: string;
  window_days: number;
  needs_a_human: boolean;
  ok: number;
  warning: number;
  error: number;
  never_ran: number;
  jobs: JobHealth[];
}

/**
 * One trading day, **adjusted as of the decision date** - the series a chart draws.
 *
 * Every field is the API's own decimal string, printed rather than re-derived. Two of
 * them are the same price twice and mixing them up is the single worst thing this page
 * could do:
 *
 *   `close`     - adjusted for every corporate action knowable on the decision date
 *   `close_raw` - what the market actually printed that day
 *
 * Across Apple's 2020 four-for-one split the adjusted closes run 124.8075 -> 129.04, a
 * rise of 3.39%. The raw closes run 499.23 -> 129.04, which reads as a 74% collapse on a
 * day the stock went up. `DESIGN.md` 4b: a chart draws `close`, never `close_raw`.
 * `close_raw` exists so a readout can say what the screen showed that day, and for
 * nothing else.
 *
 * `factor` is the adjustment applied (0.25 before that split, 1 after it), carried so a
 * table can say *why* the two columns differ rather than leaving a reader to guess.
 */
export interface AdjustedBar {
  date: string;
  open: string;
  high: string;
  low: string;
  close: string;
  /** Shares traded. Sometimes sent in exponent form ("2.114956E+8"); still a decimal. */
  volume: string;
  close_raw: string;
  factor: string;
  known_as_of: string;
}

export interface CompanyPrices {
  ticker: string;
  legal_name: string;
  currency: string;
  as_known_on: string;
  attribution: string;
  /**
   * True when the API dropped the oldest bars to stay under its own cap of 6,000.
   *
   * It trims from the far end, never the near one, so what is missing is always the
   * distant past. A page must say so: a chart that silently begins in 2003 for a company
   * listed in 1980 is telling a reader something untrue about the security.
   */
  truncated: boolean;
  bars: AdjustedBar[];
}

/**
 * One stored indicator reading. `value` arrives as a JSON number rather than a decimal
 * string - unlike every other figure in this file - because an indicator is a derived
 * feature rather than a reported datum.
 */
export interface IndicatorPoint {
  date: string;
  value: number;
  known_as_of: string;
}

export interface IndicatorSeries {
  name: string;
  param_hash: string;
  /** The settings it was computed with, e.g. `{ length: 14 }`. The API's, never ours. */
  params: Record<string, number | string>;
  points: IndicatorPoint[];
}

export interface CompanyIndicators {
  ticker: string;
  legal_name: string;
  as_known_on: string;
  /**
   * Which price series the indicators were computed on. "adjusted" is the only correct
   * answer and the API says it out loud, so a page can repeat it rather than assert it -
   * RSI computed on raw closes read Apple's 2020 split as the most violent sell-off in
   * its history, and that is exactly the claim this field exists to rule out.
   */
  price_series: string;
  series: IndicatorSeries[];
}

// ---------------------------------------------------------------------------
// The statements themselves - the normalised line items every ratio is worked
// out from, and the filing history behind them.
// ---------------------------------------------------------------------------

/**
 * One line of one statement, for one period, at one vintage.
 *
 * Two different "previous" figures live on this object and they are not the same thing.
 * `prior_value` / `change_yoy` look **sideways**, to the period before this one -
 * FY2024's revenue beside FY2025's. `previous_value` / `previous_known_as_of` look
 * **backwards in time at the same period** - what FY2018's current liabilities said
 * before the filer restated them. Measured on Apple: FY2018 current liabilities read
 * 116,866,000,000 to anybody looking on 1 Dec 2018 and read 115,929,000,000 to anybody
 * looking today. Collapsing the two would be the worst thing a page here could do, since
 * keeping them apart is what the whole schema is for.
 *
 * `change_yoy` is the API's own division, and is why a page never needs to do one. AD-3.
 */
export interface StatementItem {
  /** The figure, as a decimal string. Null when this period has no figure for this line. */
  value: string | null;
  /** When this reading became knowable - which is not when the period ended. */
  known_as_of: string;
  /** Which vintage of this period's figure this is. 1 is the first publication. */
  version: number;
  /**
   * Which kind of absence, when `value` is null.
   *
   * `not_in_filing` is the filer's - the document does not carry this line, which for a
   * bank's gross profit is accounting rather than a fault. `no_mapping` is ours - the
   * filing has a tag nothing has been mapped to yet. `DESIGN.md` §6 gives each its own
   * phrase, and the two must never be printed as one.
   */
  absent_because: "not_in_filing" | "no_mapping" | null;
  /** True when a later filing changed this period's figure after it was first published. */
  restated: boolean;
  /** What this line said at the vintage before this one. Null when there was none. */
  previous_value: string | null;
  previous_known_as_of: string | null;
  /** The same line, one period earlier. Sideways, not backwards. */
  prior_value: string | null;
  /** The move from `prior_value` to `value`, as a fraction. The API's division, not ours. */
  change_yoy: string | null;
  correction_type: string;
  corrected_by: string | null;
  corrected_at: string | null;
  correction_reason: string | null;
}

/**
 * One fiscal period, and every line the source document carried for it.
 *
 * `items` is keyed by line name and is **not** the same set for every period, or for
 * every company. Apple's FY2025 holds 21 lines; JPMorgan's FY2020 holds 32 and its
 * FY2025 holds 18, because the newer period was read from a DEF 14A proxy rather than a
 * 10-K. A page therefore takes the union of whatever keys it is given and never assumes
 * a fixed roster - `items[key]` can be `undefined`, which this type says out loud rather
 * than leaving to a reader of the JSON.
 */
export interface StatementPeriod {
  period_type: string;
  period_end: string;
  fiscal_year: number;
  period_label: string;
  currency: string;
  /** When this whole period became knowable: the filing's publication. */
  known_as_of: string;
  filing_type: string;
  filing_date: string;
  accession_no: string;
  filing_url: string | null;
  source_document_id: number | null;
  items: Record<string, StatementItem | undefined>;
}

export interface Statements {
  ticker: string;
  legal_name: string;
  cik: string;
  exchange: string;
  fiscal_year_end_month: number | null;
  chart_version: string;
  /**
   * The vintage the whole response is cut at, echoed back - including when the caller
   * asked for one. A page says "as known on 1 Dec 2018" from this field rather than from
   * the string it sent, so what is printed is what the API actually applied.
   */
  as_known_on: string;
  attribution: string;
  /** Newest first, as the API orders them. */
  periods: StatementPeriod[];
}

export interface Filing {
  ticker: string;
  legal_name: string;
  filing_type: string;
  filing_date: string;
  period_end: string | null;
  accession_no: string;
  filing_url: string | null;
  /** When the filing became public. For a filing this is usually its filing date. */
  known_as_of: string;
  /** How many statement-line versions this filing produced. */
  statement_versions: number;
}

export interface FilingHistory {
  ticker: string;
  legal_name: string;
  as_known_on: string;
  attribution: string;
  /** Newest first. */
  filings: Filing[];
}

/**
 * One cash dividend.
 *
 * `cash_amount` is what was declared per share on the day; `amount_in_todays_shares` is
 * the same payment restated onto the current share count. Apple's May 1987 dividend was
 * 0.120064 a share then and is 0.000536 in today's shares, after four splits - the same
 * adjustment that keeps a price chart from showing a cliff where a split was. Both are
 * the API's own and a page prints both rather than choosing one.
 */
export interface DividendPayment {
  ex_date: string;
  cash_amount: string;
  amount_in_todays_shares: string;
  currency: string;
  known_as_of: string;
  source_document_id: number | null;
}

export interface DividendYear {
  year: number;
  total: string;
  count: number;
  /** The move on the year, as a fraction. The API's division. Null for the first year. */
  change_yoy: string | null;
  /** True while the year is still running, so its total is not yet the whole year. */
  partial: boolean;
}

export interface DividendHistory {
  ticker: string;
  legal_name: string;
  as_known_on: string;
  currency: string;
  attribution: string;
  /** False for a company that has never paid one. Not an absence - an answer. */
  pays: boolean;
  latest: DividendPayment | null;
  /** Oldest first, as the API orders them. */
  dividends: DividendPayment[];
  years: DividendYear[];
  /** The years the API itself flags as a fall on the year. Its selection, not ours. */
  cuts: DividendYear[];
}

/** Every ratio at one past publication date, with the price and share count behind it. */
export interface RatiosHistoryPoint {
  period_label: string;
  period_end: string;
  /** When this period's figures were first published: the vintage, not the period. */
  first_published: string;
  price: PriceRef | null;
  shares: {
    as_of_date: string;
    shares: string;
    share_classes: string[];
    basic_or_diluted: string;
    known_as_of: string;
  } | null;
  ratios: Record<string, string | null>;
  /** What the price did around the publication. Shapes vary; read it, never derive it. */
  reaction: Record<string, unknown> | null;
}

export interface RatiosHistory {
  ticker: string;
  legal_name: string;
  as_known_on: string;
  period_type: string;
  currency: string;
  attribution: string;
  /** The prices behind every multiple carry their own attribution, and it differs. */
  price_attribution: string;
  /** Oldest first. */
  points: RatiosHistoryPoint[];
}

export const api = {
  /**
   * The adjusted price history, oldest first.
   *
   * `start` narrows the window and is a *request* parameter, not a figure - the endpoint
   * takes dates and has no relative-range option, so a caller that wants "one year" has
   * to name the day it starts on. Omit it for everything held.
   */
  prices: (ticker: string, start?: string) =>
    get<CompanyPrices>(
      `/v1/public/companies/${encodeURIComponent(ticker)}/prices` +
        (start ? `?start=${encodeURIComponent(start)}` : ""),
    ),
  /**
   * Stored indicators, point-in-time. Features, never signals - `SPEC.md` 2C.
   *
   * `names` is sent as the API spells them (`rsi14`, `macd_hist`). An empty list asks for
   * nothing, so the caller is expected not to call at all in that case rather than to
   * receive all twelve by accident.
   */
  indicators: (ticker: string, names: string[], start?: string) =>
    get<CompanyIndicators>(
      `/v1/public/companies/${encodeURIComponent(ticker)}/indicators` +
        `?names=${encodeURIComponent(names.join(","))}` +
        (start ? `&start=${encodeURIComponent(start)}` : ""),
    ),

  summary: () => get<HoldingsSummary>("/v1/public/summary"),
  companies: () => get<{ companies: CompanySummary[] }>("/v1/public/companies"),
  ratios: (ticker: string) =>
    get<Ratios>(`/v1/public/companies/${encodeURIComponent(ticker)}/ratios`),
  /**
   * The three rates are passed through exactly as the reader typed them, encoded but
   * never cleaned up, defaulted or guessed at here. If one is blank the API answers 422
   * and names it, and that answer is the page's content - see `ApiError.fields`.
   */
  dcf: (ticker: string, discount: string, growth: string, terminal: string) =>
    get<Dcf>(
      `/v1/public/companies/${encodeURIComponent(ticker)}/dcf` +
        `?discount_rate=${encodeURIComponent(discount)}` +
        `&growth=${encodeURIComponent(growth)}` +
        `&terminal_growth=${encodeURIComponent(terminal)}`,
    ),
  macro: () => get<{ series: MacroSeries[]; as_of: string }>("/v1/public/macro/series"),
  /**
   * Every period of one series, oldest first, each at its newest vintage.
   *
   * `limit` is the API's own parameter and it takes the *most recent* periods, which is
   * why the response carries `truncated` - a caller that quietly received 2,000 of
   * 16,886 and drew a line from them would be drawing a different series. Omitted here,
   * the API applies its own default of 2,000.
   */
  macroObservations: (code: string, limit?: number) =>
    get<MacroObservations>(
      `/v1/public/macro/series/${encodeURIComponent(code)}/observations` +
        (limit === undefined ? "" : `?limit=${limit}`),
    ),
  /**
   * The normalised statements: every line item, every period, newest period first.
   *
   * `asKnownOn` is the whole reason this endpoint takes a parameter rather than just
   * answering. Omitted, the API cuts every period at its newest vintage - the figures as
   * they stand today. Given a date, it cuts them as they stood *then*, which is a
   * different set of numbers for the same periods and drops the periods that had not
   * been filed yet. It is passed through exactly as typed: a malformed date is the API's
   * to reject and say so, not this module's to quietly repair.
   */
  statements: (
    ticker: string,
    options: { periodType?: string; asKnownOn?: string } = {},
  ) =>
    get<Statements>(
      `/v1/public/companies/${encodeURIComponent(ticker)}/statements` +
        `?period_type=${encodeURIComponent(options.periodType ?? "FY")}` +
        (options.asKnownOn
          ? `&as_known_on=${encodeURIComponent(options.asKnownOn)}`
          : ""),
    ),
  /** Every filing held for one company, newest first. */
  filings: (ticker: string) =>
    get<FilingHistory>(`/v1/public/companies/${encodeURIComponent(ticker)}/filings`),
  /**
   * Every cash dividend, plus the API's own per-year totals and the years it flags as a
   * fall. `pays: false` is an answer and not an absence - a company that has never paid
   * one is not a company whose dividends failed to load.
   */
  dividends: (ticker: string) =>
    get<DividendHistory>(`/v1/public/companies/${encodeURIComponent(ticker)}/dividends`),
  /**
   * Every ratio at each past publication date, oldest first.
   *
   * Typed here but not yet drawn by any page. The obvious use - a change column on the
   * statements - is already answered better by `StatementItem.change_yoy`, which is
   * per line rather than per point; `RatiosHistoryPoint` carries no top-level
   * `change_yoy` at all (measured 2026-09-25: null on every point of AAPL and JPM).
   * What it is genuinely for is a ratio read back at its own vintage, which is a table
   * nothing needs yet.
   */
  ratiosHistory: (ticker: string, periodType = "FY") =>
    get<RatiosHistory>(
      `/v1/public/companies/${encodeURIComponent(ticker)}/ratios/history` +
        `?period_type=${encodeURIComponent(periodType)}`,
    ),
  health: (windowDays = 7) =>
    get<HealthReport>(`/v1/public/operations/connectors?window_days=${windowDays}`),
};

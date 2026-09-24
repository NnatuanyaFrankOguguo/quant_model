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

/** Long enough for a cold Neon compute to wake up, which it does on the first request. */
const TIMEOUT_MS = 45_000;

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

async function get<T>(path: string, personal = false): Promise<T> {
  const headers: Record<string, string> = { Accept: "application/json" };
  if (personal && TOKEN) headers.Authorization = `Bearer ${TOKEN}`;

  const response = await fetch(`${API_BASE}${path}`, {
    headers,
    signal: AbortSignal.timeout(TIMEOUT_MS),
    // Figures change when a connector runs, not when someone reloads. Sixty seconds is
    // short enough that a fresh filing shows up promptly and long enough that reading
    // three pages does not mean three round trips for the same answer.
    next: { revalidate: 60 },
  });
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

export const api = {
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
  macro: () => get<{ series: MacroSeries[] }>("/v1/public/macro/series"),
  health: (windowDays = 7) =>
    get<HealthReport>(`/v1/public/operations/connectors?window_days=${windowDays}`),
};

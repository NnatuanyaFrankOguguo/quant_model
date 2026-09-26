import type { Tone } from "@/components/chart-price";

/**
 * What the chart page can be asked for, and how that is written into a URL.
 *
 * Every control on this page is a link, and every choice a reader makes is a search
 * parameter. That is not a stylistic preference: `DESIGN.md` §8 puts all fetching on the
 * server, so a range button that narrowed the window in the browser would either have to
 * hold the whole history in the page or call the API from it, and both are ruled out.
 * Making the choice part of the URL also makes each view linkable, bookmarkable and
 * reachable with the back button, which is what the tabs already do one level up.
 *
 * Nothing in this file computes a displayed figure. It picks a window and a list of
 * series names to ask the API for.
 */

export interface RangeSpec {
  id: string;
  /** On the button. */
  short: string;
  /** In a sentence - the chart's accessible name, the table's caption. */
  label: string;
  /** Calendar months back from the decision date. Null asks for everything held. */
  months: number | null;
}

export const RANGES: RangeSpec[] = [
  { id: "1M", short: "1M", label: "the last month", months: 1 },
  { id: "6M", short: "6M", label: "the last six months", months: 6 },
  { id: "1Y", short: "1Y", label: "the last year", months: 12 },
  { id: "5Y", short: "5Y", label: "the last five years", months: 60 },
  { id: "MAX", short: "Max", label: "every bar held", months: null },
];

/**
 * A year. Long enough that the shape of a year is visible, short enough that the table
 * under the chart lists every plotted bar rather than a capped tail of them.
 */
export const DEFAULT_RANGE = "1Y";

export type SeriesKind = "line" | "bars";

export interface SeriesSpec {
  /** Exactly as the API spells it. This is what gets sent in `?names=`. */
  name: string;
  label: string;
  tone: Tone;
  /**
   * Dashed where two series share a pane.
   *
   * The second signal. `DESIGN.md` §9: colour is never the only one, and a canvas cannot
   * carry the arrow `.delta` uses - so a pane with two lines in it distinguishes them by
   * dash pattern as well as by hue, and the readout names both in text regardless.
   */
  dashed: boolean;
  kind: SeriesKind;
}

export interface OverlaySpec {
  id: string;
  label: string;
  /**
   * `price` shares the price pane and its scale - only a band drawn in the same units as
   * the price belongs there. Everything else is an oscillator in units of its own and
   * gets a pane, because plotting an RSI between 0 and 100 against a price in dollars
   * flattens one of them into a straight line.
   */
  where: "price" | "pane";
  series: SeriesSpec[];
}

/**
 * The seven groups, covering all twelve stored series.
 *
 * The numbers inside the labels - "RSI 14", "ATR 14" - are transcribed from the API's own
 * series names (`rsi14`, `atr14`), which is how it distinguishes two settings of the same
 * indicator. They are identifiers, not figures: the authoritative settings arrive as
 * `params` on each series and are printed from there, so nothing here asserts a length
 * the API did not send.
 */
export const OVERLAYS: OverlaySpec[] = [
  {
    id: "bollinger",
    label: "Bollinger bands",
    where: "price",
    series: [
      { name: "bb_upper", label: "Upper band", tone: "ink-faint", dashed: true, kind: "line" },
      { name: "bb_mid", label: "Middle band", tone: "ink-soft", dashed: false, kind: "line" },
      { name: "bb_lower", label: "Lower band", tone: "ink-faint", dashed: true, kind: "line" },
    ],
  },
  {
    id: "rsi14",
    label: "RSI 14",
    where: "pane",
    series: [{ name: "rsi14", label: "RSI 14", tone: "act", dashed: false, kind: "line" }],
  },
  {
    id: "rsi21",
    label: "RSI 21",
    where: "pane",
    series: [{ name: "rsi21", label: "RSI 21", tone: "act", dashed: false, kind: "line" }],
  },
  {
    id: "macd",
    label: "MACD",
    where: "pane",
    series: [
      { name: "macd_hist", label: "MACD histogram", tone: "ink-faint", dashed: false, kind: "bars" },
      { name: "macd", label: "MACD", tone: "act", dashed: false, kind: "line" },
      { name: "macd_signal", label: "Signal", tone: "ink-soft", dashed: true, kind: "line" },
    ],
  },
  {
    id: "stoch",
    label: "Stochastic",
    where: "pane",
    series: [
      { name: "stoch_k", label: "%K", tone: "act", dashed: false, kind: "line" },
      { name: "stoch_d", label: "%D", tone: "ink-soft", dashed: true, kind: "line" },
    ],
  },
  {
    id: "atr14",
    label: "ATR 14",
    where: "pane",
    series: [{ name: "atr14", label: "ATR 14", tone: "act", dashed: false, kind: "line" }],
  },
  {
    id: "obv",
    label: "On-balance volume",
    where: "pane",
    series: [{ name: "obv", label: "On-balance volume", tone: "act", dashed: false, kind: "line" }],
  },
];

export type Style = "line" | "candles";

/** What a search parameter can arrive as in Next 15. */
type Param = string | string[] | undefined;

function first(value: Param): string | undefined {
  return Array.isArray(value) ? value[0] : value;
}

/** An unknown or absent range falls back rather than erroring. A URL is user input. */
export function pickRange(value: Param): RangeSpec {
  const wanted = first(value);
  return RANGES.find((range) => range.id === wanted) ?? RANGES.find((r) => r.id === DEFAULT_RANGE)!;
}

export function pickStyle(value: Param): Style {
  return first(value) === "candles" ? "candles" : "line";
}

/** The groups named in `?show=`, in the order this file declares them, never duplicated. */
export function pickOverlays(value: Param): OverlaySpec[] {
  const wanted = new Set(
    (first(value) ?? "")
      .split(",")
      .map((part) => part.trim())
      .filter(Boolean),
  );
  return OVERLAYS.filter((overlay) => wanted.has(overlay.id));
}

/**
 * The first day of the window, or undefined for everything held.
 *
 * This is the one piece of date arithmetic on the page, and it is deliberate: the
 * endpoint takes `start` and `end` and has no relative-range parameter, so something has
 * to turn "one year" into a day. It happens on the server, it produces a *request*
 * boundary rather than a displayed figure, and the date every reader is shown -
 * `as_known_on` - still comes back from the API. AD-3 is about deriving figures, and no
 * figure is derived here.
 *
 * The day of the month is clamped, so a window measured back from the 31st lands on the
 * last day of a short month rather than skidding into the next one.
 */
export function windowStart(range: RangeSpec, today: Date = new Date()): string | undefined {
  if (range.months === null) return undefined;

  const year = today.getUTCFullYear();
  const month = today.getUTCMonth();
  const dayOfMonth = today.getUTCDate();

  const shifted = month - range.months;
  const lastOfTarget = new Date(Date.UTC(year, shifted + 1, 0)).getUTCDate();
  const start = new Date(Date.UTC(year, shifted, Math.min(dayOfMonth, lastOfTarget)));
  return start.toISOString().slice(0, 10);
}

/** Every API series name the chosen groups need, de-duplicated. */
export function seriesNames(chosen: OverlaySpec[]): string[] {
  return [...new Set(chosen.flatMap((overlay) => overlay.series.map((s) => s.name)))];
}

/**
 * The URL for one state of this page. Built from the whole state rather than patched,
 * so a link never carries a parameter the page no longer honours.
 */
export function chartHref(
  ticker: string,
  state: { range: string; style: Style; show: string[] },
): string {
  const query = new URLSearchParams();
  if (state.range !== DEFAULT_RANGE) query.set("range", state.range);
  if (state.style !== "line") query.set("style", state.style);
  if (state.show.length > 0) query.set("show", state.show.join(","));
  const tail = query.toString();
  return `/companies/${encodeURIComponent(ticker)}/chart${tail ? `?${tail}` : ""}`;
}

/** The same list with one group added or taken out - what an overlay link points at. */
export function toggled(show: string[], id: string): string[] {
  const has = show.includes(id);
  const next = has ? show.filter((item) => item !== id) : [...show, id];
  // Kept in declaration order so two routes to the same selection give the same URL.
  return OVERLAYS.filter((overlay) => next.includes(overlay.id)).map((overlay) => overlay.id);
}

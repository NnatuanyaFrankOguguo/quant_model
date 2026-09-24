/**
 * Display formatting, and nothing else. Every page in the app formats through this file.
 *
 * AD-3 (DESIGN.md §7): the client computes nothing. Every function here takes something
 * the API already returned and changes how it is *written* - never what it says. Nothing
 * here adds, subtracts, averages or compares two figures. Where a value changes units to
 * be readable - a fraction shown as a percentage, a large amount shown as "$1.43T" - the
 * change is made by `Intl.NumberFormat`, whose whole job is to express one value in a
 * readable form. No new figure is derived from two others anywhere, which is the thing
 * AD-3 actually forbids. The API's decimal string stays the source of truth; what reaches
 * the screen is a rounded view of it, and the `.source` block beside it says where it
 * came from.
 *
 * There is one of these modules on purpose. It replaced two - a `lib/format.ts` and a
 * `companies/_format.ts` - which between them defined the date formatter twice and the
 * vocabulary for a missing value twice. Neither copy was wrong, and that is exactly the
 * problem: nothing would have told us when they drifted apart.
 */

/**
 * What a reader is told when a request outran the page's patience. One sentence, used
 * wherever it can happen, so the same event never reads as two different problems.
 */
export const SERVICE_IS_SLOW =
  "The data service is answering, but more slowly than this page waits for. Nothing " +
  "is broken and no figures are missing — reloading usually works.";

// ---------------------------------------------------------------------------
// The words used when there is no value.
//
// Deliberately not "0", not "-" on its own, and not an empty cell: a zero is a
// measurement and an absence is not, and this app treats mistaking one for the other as
// the worst thing it could do.
//
// There are two phrases because there are two different facts, and the schema draws the
// same line - `not_in_filing` (an absence the world caused) against `no_mapping` (an
// absence we caused). Collapsing them into one phrase would throw that away.
// ---------------------------------------------------------------------------

/** We have not fetched it yet. The absence is ours. */
export const NOT_LOADED = "not loaded yet";

/** The filing does not contain this line. The absence is the filer's, and is not a fault. */
export const NOT_REPORTED = "not reported";

/**
 * The event has not happened. Nobody's absence at all - there is simply nothing to report
 * yet.
 *
 * A third phrase because a scheduled job that has never run is neither of the two above:
 * we have not failed to fetch it, and no publisher has declined to say it. Rendering it as
 * "not loaded yet" would blame the pipeline for a job the scheduler has not reached, which
 * is the same class of mistake as printing a zero for a missing figure - it is just a
 * quieter one. Pairs with `.pill.never_ran`, which is grey for the same reason.
 */
export const NEVER_RAN = "no run recorded";

/** True when the API sent no value - so a caller can choose which phrase fits. */
export function isMissing(value: string | null | undefined): boolean {
  return value === null || value === undefined || value.trim() === "";
}

// ---------------------------------------------------------------------------
// Dates
// ---------------------------------------------------------------------------

const MONTH_DAY_YEAR = new Intl.DateTimeFormat("en-US", {
  day: "numeric",
  month: "short",
  year: "numeric",
  timeZone: "UTC",
});

const DAY_AND_TIME = new Intl.DateTimeFormat("en-GB", {
  day: "numeric",
  month: "short",
  year: "numeric",
  hour: "2-digit",
  minute: "2-digit",
  hour12: false,
  timeZone: "UTC",
});

/**
 * Pinned to UTC. The API sends a calendar date with no time on it, and a machine west of
 * Greenwich would otherwise render the day before - on this site the exact day is the
 * point. `new Date("2026-08-31")` is already UTC by spec, but `new Date("2026-08-31T00:00:00")`
 * is local, so the `Z` is added rather than assumed.
 */
function parseDay(iso: string): Date | null {
  const text = /^\d{4}-\d{2}-\d{2}$/.test(iso) ? `${iso}T00:00:00Z` : iso;
  const parsed = new Date(text);
  return Number.isNaN(parsed.getTime()) ? null : parsed;
}

/**
 * Assembled from parts rather than taken whole from the locale, so that the order is
 * fixed no matter which locale the formatter is built with. `en-US` formatted whole gives
 * "Aug 31, 2026"; this gives "31 Aug 2026", and will keep giving it if somebody edits the
 * locale string above. Every month is three letters, so a column of dates keeps one
 * width. "01/09" is never written, in either order: half the world would read it as the
 * wrong month.
 */
function writeDay(parsed: Date): string {
  const parts = MONTH_DAY_YEAR.formatToParts(parsed);
  const part = (type: Intl.DateTimeFormatPartTypes) =>
    parts.find((candidate) => candidate.type === type)?.value ?? "";
  return `${part("day")} ${part("month")} ${part("year")}`;
}

/**
 * "2026-08-31" -> "31 Aug 2026", or null when there is no date.
 *
 * Returns null rather than a phrase so the caller decides what an absence should say -
 * on the macro pages a missing date means `NOT_LOADED`, which is not what it means on a
 * company page. Use `day()` where `NOT_REPORTED` is the right default.
 */
export function formatDay(iso: string | null | undefined): string | null {
  if (isMissing(iso)) return null;
  const parsed = parseDay(iso as string);
  return parsed ? writeDay(parsed) : String(iso);
}

/** "2026-08-31" -> "31 Aug 2026", or `NOT_REPORTED` when the filing had no date. */
export function day(iso: string | null | undefined): string {
  return formatDay(iso) ?? NOT_REPORTED;
}

/** "2026-09-24T11:56:56.443837Z" -> "24 Sep 2026, 11:56 UTC". */
export function formatMoment(iso: string | null | undefined): string | null {
  if (isMissing(iso)) return null;
  const parsed = new Date(iso as string);
  return Number.isNaN(parsed.getTime()) ? String(iso) : `${DAY_AND_TIME.format(parsed)} UTC`;
}

/**
 * The API writes a schedule two ways, and one of them is not obvious.
 *
 *   "05:30"  - a fixed time of day
 *   "**:15"  - every hour, at fifteen minutes past
 *   null     - no schedule at all; somebody runs it by hand
 *
 * A reader should never have to be told what `**:15` means, so it is never printed.
 */
export function describeSchedule(scheduledAtUtc: string | null): string {
  if (!scheduledAtUtc) return "no fixed time";

  const parts = /^(\*\*|\d{1,2}):(\d{2})$/.exec(scheduledAtUtc.trim());
  if (!parts) return scheduledAtUtc;

  const [, hour, minute] = parts;
  if (hour !== "**") return `daily, ${hour}:${minute}`;
  if (minute === "00") return "hourly, on the hour";
  return `hourly, at ${minute.replace(/^0/, "")} past`;
}

// ---------------------------------------------------------------------------
// Numbers
// ---------------------------------------------------------------------------

/** Parse for display only. Not a calculation; the API's string remains authoritative. */
function reading(value: string | null | undefined): number | null {
  if (isMissing(value)) return null;
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : null;
}

/** A fraction the API returned (0.469…) written the way it is usually read: 46.9%. */
export function percent(value: string | null | undefined, digits = 1): string {
  const parsed = reading(value);
  if (parsed === null) return NOT_REPORTED;
  return new Intl.NumberFormat("en-US", {
    style: "percent",
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  }).format(parsed);
}

/** A bare ratio - 0.89, 1.06 - for the figures whose names end in "to". */
export function ratio(value: string | null | undefined, digits = 2): string {
  const parsed = reading(value);
  if (parsed === null) return NOT_REPORTED;
  return new Intl.NumberFormat("en-US", {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  }).format(parsed);
}

/** A plain grouped number, for things that are neither money nor a percentage. */
export function plain(value: string | null | undefined, digits = 4): string {
  const parsed = reading(value);
  if (parsed === null) return NOT_REPORTED;
  return new Intl.NumberFormat("en-US", {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  }).format(parsed);
}

/** A whole number, for counts the API sent as numbers rather than decimal strings. */
export function count(value: number | null | undefined): string {
  if (value === null || value === undefined) return NOT_REPORTED;
  return new Intl.NumberFormat("en-US").format(value);
}

function currencyFormat(
  currency: string,
  extra: Intl.NumberFormatOptions,
): Intl.NumberFormat {
  try {
    return new Intl.NumberFormat("en-US", { style: "currency", currency, ...extra });
  } catch {
    // An unknown ISO code should cost the reader the currency symbol, not the figure.
    return new Intl.NumberFormat("en-US", extra);
  }
}

/** An amount in full: "$332.41". For per-share figures and prices. */
export function money(value: string | null | undefined, currency: string): string {
  const parsed = reading(value);
  if (parsed === null) return NOT_REPORTED;
  return currencyFormat(currency, {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  }).format(parsed);
}

/**
 * An amount shortened: "$98.77B". For company-sized totals, where twelve digits of
 * precision is not information a reader can use and thirteen characters of it crowds
 * everything else off a 320px screen.
 */
export function moneyCompact(
  value: string | null | undefined,
  currency: string,
): string {
  const parsed = reading(value);
  if (parsed === null) return NOT_REPORTED;
  return currencyFormat(currency, {
    notation: "compact",
    // Both, not just the maximum: otherwise "$90.8B" sits beside "$95.17B" in the same
    // column and the decimal points stop lining up.
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  }).format(parsed);
}

// ---------------------------------------------------------------------------
// Units and words
// ---------------------------------------------------------------------------

/** The API's unit codes, written the way a person writes them. */
const UNITS: Record<string, { suffix?: string; prefix?: string; spoken: string }> = {
  percent: { suffix: "%", spoken: "per cent" },
  index: { spoken: "index points" },
  ngn_per_usd: { spoken: "naira per US dollar" },
  ngn_billions: { spoken: "naira, billions" },
  usd: { prefix: "$", spoken: "US dollars" },
};

/** "ngn_per_usd" -> "naira per US dollar". Unknown codes lose their underscores. */
export function unitInWords(unit: string): string {
  return UNITS[unit]?.spoken ?? unit.replace(/_/g, " ");
}

/**
 * Puts the unit beside a value the API already formatted. The value string is passed
 * through untouched - not rounded, not re-rendered - because it is the figure of record
 * and this app does not quietly tidy figures.
 */
export function withUnit(value: string, unit: string): string {
  const shape = UNITS[unit];
  if (!shape) return value;
  return `${shape.prefix ?? ""}${value}${shape.suffix ?? ""}`;
}

/** "monthly" -> "Monthly". Frequencies arrive lower-cased. */
export function sentenceCase(text: string): string {
  return text.charAt(0).toUpperCase() + text.slice(1);
}

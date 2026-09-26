"use client";

import Link from "next/link";
import { Fragment, useId, useMemo, useState, type ReactNode } from "react";

import type { CompanySummary } from "@/lib/api";
import { NOT_LOADED, count, day, formatDay, isMissing } from "@/lib/format";

import { NumCell, ScrollHint, WordCell } from "./_ui";

/**
 * The screener: the whole company list, filterable by ticker or name and sortable by
 * any column.
 *
 * A client component, but not a client *fetch*. `page.tsx` reads the list on the server
 * and hands it down as a prop, so the first paint - and every paint with JavaScript
 * turned off - already carries all the rows, sorted. Hydration only adds the two
 * controls. `DESIGN.md` §8 keeps every request on the server; there is no `fetch` in
 * this file and never will be.
 *
 * Sorting here is *selection*: it reorders rows by a field the API sent. It derives no
 * new figure to sort by - AD-3 - and there is no arithmetic on a figure anywhere in the
 * file, not even a subtraction inside a comparator. `_search.tsx` draws the same line.
 */

type Direction = "ascending" | "descending";

/** What the API sent for one column of one row, or null when it sent nothing at all. */
type Key = string | number | null;

interface Column {
  id: string;
  /** The word in the header, and the accessible name of the button that sorts by it. */
  label: string;
  /** Right-aligned. `.num` already implies `.nowrap`, so §7's rule is covered. */
  numeric?: boolean;
  /**
   * The field this column orders by, exactly as the API sent it, or null when the API
   * sent nothing. Null is the only signal the comparator needs - see `order`.
   *
   * An ISO date is returned as the string it arrived as. `YYYY-MM-DD` sorts
   * chronologically under the collator below, so no date is parsed in order to be
   * compared and no clock is consulted.
   */
  key: (company: CompanySummary) => Key;
  /** The finished `<th>` or `<td>`. Every absence goes through `_ui`, never a blank. */
  render: (company: CompanySummary) => ReactNode;
}

const COLUMNS: Column[] = [
  {
    id: "ticker",
    label: "Ticker",
    key: (company) => company.ticker,
    render: (company) => (
      // The ticker labels the row, so it is a row header - `DESIGN.md` §9.
      <th scope="row" className="nowrap">
        <Link href={`/companies/${encodeURIComponent(company.ticker)}`}>
          {company.ticker}
        </Link>
      </th>
    ),
  },
  {
    id: "name",
    label: "Company",
    key: (company) => (isMissing(company.legal_name) ? null : company.legal_name),
    // `.nowrap` on the name too. The table is wider than a phone and scrolls sideways
    // either way, so letting the longest legal name wrap buys no width back - it only
    // turns a 35px row into a 70px one, and takes the even rhythm a screener is read by
    // with it.
    render: (company) => <WordCell text={nameOf(company)} nowrap />,
  },
  {
    id: "exchange",
    label: "Exchange",
    key: (company) => (isMissing(company.exchange) ? null : company.exchange),
    render: (company) => <WordCell text={exchangeOf(company)} nowrap />,
  },
  {
    id: "cik",
    label: "CIK",
    // The SEC's own identifier for the filer, printed exactly as it was given - zeros
    // and all, `DESIGN.md` §6. The collator reads past the padding, so ordering by it
    // gives the numeric order without this file ever turning it into a number.
    key: (company) => (isMissing(company.cik) ? null : company.cik),
    render: (company) => <WordCell text={cikOf(company)} nowrap />,
  },
  {
    id: "periods",
    label: "Periods",
    numeric: true,
    key: (company) =>
      Number.isFinite(company.statement_periods) ? company.statement_periods : null,
    render: (company) => <NumCell text={count(company.statement_periods)} />,
  },
  {
    id: "period_end",
    label: "Period end",
    key: (company) =>
      isMissing(company.latest_period_end) ? null : company.latest_period_end,
    render: (company) => <WordCell text={day(company.latest_period_end)} nowrap />,
  },
  {
    id: "filed",
    label: "Filed on",
    key: (company) =>
      isMissing(company.latest_filing_date) ? null : company.latest_filing_date,
    render: (company) => <WordCell text={day(company.latest_filing_date)} nowrap />,
  },
  {
    id: "next_form",
    label: "Next report",
    key: (company) =>
      isMissing(company.next_filing_form) ? null : company.next_filing_form,
    render: (company) => <WordCell text={formOf(company)} nowrap />,
  },
  {
    id: "due",
    label: "Due by",
    key: (company) =>
      isMissing(company.next_filing_due_by) ? null : company.next_filing_due_by,
    render: (company) => <WordCell text={dueOf(company)} nowrap />,
  },
  {
    id: "status",
    label: "Status",
    // The boolean the API sent, written down rather than counted up. "false" sorts
    // before "true", so ascending puts the rows that are not due first.
    key: (company) => String(company.filing_overdue),
    render: (company) => (
      <td className="nowrap">
        {company.filing_overdue ? (
          <span className="pill attention">Past due</span>
        ) : (
          <span className="pill ok">Not due</span>
        )}
      </td>
    ),
  },
];

/**
 * Words, codes and dates in one order.
 *
 * `numeric` is what makes "0000320193" sort against "0001018724" by the number the
 * zeros are padding, and what makes 2026-06-27 sort before 2026-06-30 as a date rather
 * than as a string that happens to look like one. `sensitivity: "base"` keeps "AMAZON
 * COM INC" and "Apple Inc." in alphabetical order instead of splitting the table into a
 * shouted half and a spoken half.
 */
const COLLATOR = new Intl.Collator("en", { numeric: true, sensitivity: "base" });

const BEFORE = -1;
const SAME = 0;
const AFTER = 1;

export function Screener({ companies }: { companies: CompanySummary[] }) {
  const fieldId = useId();
  const hintId = useId();

  const [query, setQuery] = useState("");
  // Ticker ascending is the order the API already answers in, so the server's HTML and
  // the browser's first render are the same table - and the header can say so.
  const [sort, setSort] = useState<{ id: string; direction: Direction }>({
    id: "ticker",
    direction: "ascending",
  });

  const column = COLUMNS.find((candidate) => candidate.id === sort.id) ?? COLUMNS[0];
  const needle = query.trim().toLowerCase();

  const rows = useMemo(() => {
    const matched = needle
      ? companies.filter(
          (company) =>
            company.ticker.toLowerCase().includes(needle) ||
            String(company.legal_name ?? "")
              .toLowerCase()
              .includes(needle),
        )
      : companies;
    // A copy: `sort` mutates, and the array belongs to the server component above.
    return [...matched].sort((a, b) => order(a, b, column, sort.direction));
  }, [companies, needle, column, sort.direction]);

  const sortBy = (id: string) =>
    setSort((current) =>
      current.id === id
        ? {
            id,
            direction: current.direction === "ascending" ? "descending" : "ascending",
          }
        : { id, direction: "ascending" },
    );

  return (
    <section className="panel">
      <div className="panel-head">
        <h2>Screen the list</h2>
      </div>

      <div className="panel-body">
        <label htmlFor={fieldId}>Filter by ticker or company name</label>
        <input
          id={fieldId}
          type="text"
          value={query}
          onChange={(event) => setQuery(event.target.value)}
          placeholder="AAPL, or Apple&hellip;"
          autoComplete="off"
          aria-describedby={hintId}
        />
        <p className="hint" id={hintId}>
          Narrows the table as you type, on ticker and on legal name. Every column
          heading is a button: it sorts by that column, and pressing it again reverses
          the order. A row the API sent no value for sorts to the bottom either way.
        </p>
      </div>

      <div className="scroller">
        <table>
          {/* Short on purpose. A `<caption>` is as wide as its table, and this table is
              wider than a phone - so a long caption runs off the right of the screen and
              has to be scrolled to, which a caption exists to avoid. The longer
              description is the `.page-note` above.

              It says which of the two tables this is, because a filtered table is not
              every company and a caption that claimed it was would be untrue for as
              long as the box had anything in it. Neither wording counts anything. */}
          <caption>
            {needle
              ? "The companies your filter matches, and how much of each."
              : "Every company loaded, and how much of each."}
          </caption>
          <thead>
            <tr>
              {COLUMNS.map((candidate) => {
                // One value drives both the announced state and the drawn one, so the
                // arrow cannot disagree with what a screen reader is told.
                const ariaSort =
                  candidate.id === sort.id ? sort.direction : ("none" as const);
                return (
                  <th
                    key={candidate.id}
                    scope="col"
                    aria-sort={ariaSort}
                    className={candidate.numeric ? "num" : undefined}
                  >
                    {/* A real `<button>`, not a `<th>` with a handler - `DESIGN.md` §9. The
                        arrow is drawn by `globals.css` from `aria-sort` on the `<th>`,
                        so the state a screen reader announces is the state that draws
                        and the two cannot disagree. */}
                    <button
                      type="button"
                      className="sort"
                      onClick={() => sortBy(candidate.id)}
                    >
                      {candidate.label}
                    </button>
                  </th>
                );
              })}
            </tr>
          </thead>
          <tbody>
            {rows.length === 0 ? (
              <tr>
                {/* In the table rather than above it: a reader moving through the page
                    with a screen reader would otherwise meet a heading, a row of column
                    headings, and then silence. */}
                <td colSpan={COLUMNS.length}>
                  No company loaded here matches that text. Only the loaded universe is
                  searchable.
                </td>
              </tr>
            ) : (
              rows.map((company) => (
                <tr key={company.ticker}>
                  {COLUMNS.map((candidate) => (
                    <Fragment key={candidate.id}>{candidate.render(company)}</Fragment>
                  ))}
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>
      <ScrollHint />
    </section>
  );
}

/**
 * Order two rows by one column.
 *
 * The absence test runs **before** the direction is applied, and that ordering is the
 * whole point. A company with no period end is not the oldest company; if reversing the
 * sort could lift it to the top, it would read as exactly that. So a null sorts to the
 * bottom ascending and to the bottom descending, and the direction never gets a say.
 *
 * The direction is then applied by swapping the pair rather than by negating a result,
 * which leaves the rule above untouched. Ties fall to the ticker, ascending, in both
 * directions - the ticker is unique and never absent, so the order is total and
 * reversing a column of equal values never reshuffles them.
 */
function order(
  a: CompanySummary,
  b: CompanySummary,
  column: Column,
  direction: Direction,
): number {
  const left = column.key(a);
  const right = column.key(b);

  if (left === null || right === null) {
    if (left === right) return byTicker(a, b);
    return left === null ? AFTER : BEFORE;
  }

  const [first, second] = direction === "ascending" ? [left, right] : [right, left];
  const ranked =
    typeof first === "number" && typeof second === "number"
      ? rank(first, second)
      : COLLATOR.compare(String(first), String(second));

  return ranked === SAME ? byTicker(a, b) : ranked;
}

/** Two counts in order, without subtracting one from the other. */
function rank(first: number, second: number): number {
  if (first < second) return BEFORE;
  if (first > second) return AFTER;
  return SAME;
}

/** The tie-break, always ascending, so reversing a column does not reshuffle equals. */
function byTicker(a: CompanySummary, b: CompanySummary): number {
  return COLLATOR.compare(a.ticker, b.ticker);
}

// ---------------------------------------------------------------------------
// Which kind of absence each column has.
//
// Two different facts, and `DESIGN.md` §6 keeps them apart. A date that should have come
// out of a filing is `NOT_REPORTED` when it did not - that is the filer's choice and not
// a fault, and `day()` already says so. Everything this system fetches or works out for
// itself - the exchange, the CIK, the form the SEC expects next and the day it is due -
// is `NOT_LOADED` when it is missing, because that absence is ours.
// ---------------------------------------------------------------------------

function nameOf(company: CompanySummary): string {
  return isMissing(company.legal_name) ? NOT_LOADED : company.legal_name;
}

function exchangeOf(company: CompanySummary): string {
  return isMissing(company.exchange) ? NOT_LOADED : company.exchange;
}

function cikOf(company: CompanySummary): string {
  return isMissing(company.cik) ? NOT_LOADED : company.cik;
}

function formOf(company: CompanySummary): string {
  const form = company.next_filing_form;
  // `isMissing` covers null as well; the explicit test is what narrows the type.
  return form === null || isMissing(form) ? NOT_LOADED : form;
}

/** `formatDay` rather than `day`, so the absence is ours rather than the filer's. */
function dueOf(company: CompanySummary): string {
  return formatDay(company.next_filing_due_by) ?? NOT_LOADED;
}

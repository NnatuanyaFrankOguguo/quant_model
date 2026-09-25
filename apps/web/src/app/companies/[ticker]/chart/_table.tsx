import Link from "next/link";

import type { AdjustedBar } from "@/lib/api";
import { NOT_LOADED, count, day, money, plain } from "@/lib/format";

import { ScrollHint, isAbsent } from "../../_ui";
import { RANGES, type RangeSpec, type Style, chartHref } from "./_view";

/**
 * Every point the chart plotted, as a table.
 *
 * `DESIGN.md` 4b: a canvas has no DOM, so a chart is invisible to a screen reader and is
 * never the only rendering of its data. This is the other one, and it is not a courtesy
 * copy - it is server-rendered HTML, it is in the page before any JavaScript runs, it
 * survives the chart failing, and it holds three columns the picture cannot show at all:
 * what the market printed that day, the factor that separates that from the plotted
 * close, and the date each bar became knowable.
 *
 * Nothing here is computed. Every cell is an API string re-written by `lib/format`.
 *
 * The cells are plain `<td>` rather than the shared `NumCell`, which is the one place
 * this file departs from the house style and does it deliberately: a server component is
 * serialised into the page a second time so the browser can navigate without a reload,
 * and at several hundred rows every extra component inside a cell is measured in hundreds
 * of kilobytes. `isAbsent` is still the shared one, so the rule it enforces is not copied.
 */

/** One indicator's readings, keyed by date so a row can look its own value up. */
export interface IndicatorColumn {
  /** The API's series name, used as the React key. */
  name: string;
  label: string;
  /** The settings the API says it was computed with. Printed, never assumed. */
  params: Record<string, number | string>;
  values: Map<string, number>;
}

/**
 * How many rows are listed.
 *
 * A month, six months and a year each plot fewer bars than this, so those ranges list
 * every point they draw. Five years is about 1,258 trading days and Max can be 6,000,
 * and a table that long is a megabyte of markup sitting inside a disclosure - which makes
 * the page slower for everybody, including the reader this table exists for.
 *
 * Where it does bite, the tail is kept rather than the head - the same choice the API
 * makes when it trims - and the page links to the ranges that list in full. `DESIGN.md`
 * 4b allows exactly that: a table of the plotted points *or a link to the table that
 * already shows them*.
 */
export const TABLE_ROWS = 500;

function describeParams(params: Record<string, number | string>): string {
  const pairs = Object.entries(params);
  if (pairs.length === 0) return "";
  return ` (${pairs.map(([key, value]) => `${key} ${value}`).join(", ")})`;
}

/** A figure, right-aligned, quiet when it is an absence rather than a measurement. */
function Num({ text }: { text: string }) {
  return <td className={isAbsent(text) ? "num absent" : "num"}>{text}</td>;
}

export function PlottedPoints({
  bars,
  columns,
  currency,
  range,
  style,
  ticker,
  show,
}: {
  bars: AdjustedBar[];
  columns: IndicatorColumn[];
  currency: string;
  range: RangeSpec;
  style: Style;
  ticker: string;
  show: string[];
}) {
  // Newest first, which is how a price table is read and what makes the row cap mean the
  // obvious thing. The chart runs the other way because time runs left to right.
  const shown = [...bars].reverse().slice(0, TABLE_ROWS);
  const held = bars.length;
  const capped = held > TABLE_ROWS;
  /** The ranges that plot few enough bars to list every one of them. */
  const inFull = RANGES.filter(
    (option) => option.months !== null && option.months <= 12 && option.id !== range.id,
  );

  return (
    <>
      {capped ? (
        <p>
          The {count(TABLE_ROWS)} most recent of {count(held)} plotted bars are listed
          below. To read a window in full, narrow the range:{" "}
          {inFull.map((option, at) => (
            <span key={option.id}>
              {at > 0 ? (at === inFull.length - 1 ? " and " : ", ") : null}
              <Link href={chartHref(ticker, { range: option.id, style, show })}>
                {option.label}
              </Link>
            </span>
          ))}{" "}
          each list every point they draw.
        </p>
      ) : null}

      <div className="scroller">
        <table>
          <caption>
            Every point drawn above — {range.label}, {count(held)} trading days, most
            recent first.{" "}
            {capped
              ? `Listing the ${count(TABLE_ROWS)} most recent.`
              : "Every one of them is listed."}{" "}
            <b>Close</b> is the adjusted price and is the line on the chart;{" "}
            <b>As traded</b> is what the market printed that day and is never plotted.
          </caption>
          <thead>
            <tr>
              <th scope="col">Date</th>
              <th scope="col" className="num">
                Open
              </th>
              <th scope="col" className="num">
                High
              </th>
              <th scope="col" className="num">
                Low
              </th>
              <th scope="col" className="num">
                Close
              </th>
              <th scope="col" className="num">
                As traded
              </th>
              <th scope="col" className="num">
                Factor
              </th>
              <th scope="col" className="num">
                Volume
              </th>
              {/* The project's core promise: when a figure became knowable is not the
                  same fact as the day it is about, and both are shown. `DESIGN.md` §6. */}
              <th scope="col">Knowable</th>
              {columns.map((column) => (
                <th key={column.name} scope="col" className="num">
                  {column.label}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {shown.map((bar) => (
              <tr key={bar.date}>
                <th scope="row" className="nowrap">
                  {day(bar.date)}
                </th>
                <Num text={money(bar.open, currency)} />
                <Num text={money(bar.high, currency)} />
                <Num text={money(bar.low, currency)} />
                <Num text={money(bar.close, currency)} />
                <Num text={money(bar.close_raw, currency)} />
                {/* Printed as the API sent it. A factor is a datum, not a rounding. */}
                <td className="num">{bar.factor}</td>
                <Num text={count(Number(bar.volume))} />
                <td className="nowrap">{day(bar.known_as_of)}</td>
                {columns.map((column) => {
                  const value = column.values.get(bar.date);
                  return value === undefined ? (
                    <td key={column.name} className="num absent">
                      {NOT_LOADED}
                    </td>
                  ) : (
                    <Num key={column.name} text={plain(String(value), 4)} />
                  );
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <ScrollHint />
      {columns.length > 0 ? (
        <p className="source">
          Indicator settings, as the API reports them:{" "}
          {columns
            .map((column) => `${column.label}${describeParams(column.params)}`)
            .join("; ")}
          . Each reading is the vintage knowable on the decision date, and a date the
          series does not reach is written out rather than left blank.
        </p>
      ) : null}
    </>
  );
}

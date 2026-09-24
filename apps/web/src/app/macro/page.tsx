import { Fragment } from "react";
import type { Metadata } from "next";
import Link from "next/link";

import { ApiError, ApiTimeout, api, failTheBuildInstead, type MacroSeries } from "@/lib/api";
import {
  NOT_LOADED,
  SERVICE_IS_SLOW,
  count,
  sentenceCase,
  unitInWords,
} from "@/lib/format";
import { Disclose } from "@/components/disclose";
import { DayCell, Freshness, LatestValueCell } from "../_series";

export const metadata: Metadata = {
  title: "The economy",
  description:
    "Nigerian and US economic series - prices, interest rates, output and debt - each " +
    "one showing the period it covers, the date it became knowable, and who published it.",
};

/**
 * The economy.
 *
 * One table, and it is the whole page. Every series held, every column the API sends
 * about it, and both dates on every row - `DESIGN.md` §6 requires the period a figure is
 * about and the moment it became knowable to sit beside it, and on a macro series those
 * two are routinely a month apart and occasionally a year.
 *
 * Nothing here is counted by this page. The row count is not printed, because a count
 * this file worked out is a figure the API did not send (AD-3), and the front page once
 * disagreed with this one about how many series exist for exactly that reason.
 */
export default async function MacroPage() {
  let series: MacroSeries[];

  try {
    ({ series } = await api.macro());
  } catch (error) {
    // First statement, before anything is rendered: this route is static, so a caught
    // failure during `next build` would otherwise be prerendered into the HTML and
    // served to every visitor as though the data were gone.
    failTheBuildInstead(error);

    // A timeout is our budget expiring, not the API failing. Painted red and worded as a
    // failure it sends a reader looking for a fault that is not there.
    const slow = error instanceof ApiTimeout;
    return (
      <>
        <h1>The economy</h1>
        {/* The title is a bold lead rather than an `<h3>`: this notice follows the
            `<h1>` directly, and DESIGN.md §9 allows no skipped heading level. */}
        <div className={slow ? "notice" : "notice bad"}>
          <p>
            <b>
              {slow
                ? "This is taking longer than the page waits."
                : "The economic series could not be loaded."}
            </b>{" "}
            {slow
              ? SERVICE_IS_SLOW
              : "This page asked the API for its list of series and did not get one. " +
                "Nothing is being hidden below — there is simply nothing to show until " +
                "that call succeeds."}
          </p>
          <p>
            Reported as:{" "}
            <span className="num">
              {error instanceof ApiError
                ? `${error.status} from ${error.path}`
                : error instanceof Error
                  ? error.message
                  : "unknown error"}
            </span>
          </p>
          <p>
            Running this locally, the API is the uvicorn process on port 8000. Reload once
            it is answering.
          </p>
        </div>
      </>
    );
  }

  if (series.length === 0) {
    return (
      <>
        <h1>The economy</h1>
        <div className="notice">
          <p>
            <b>No series are defined yet.</b> The API answered, and the list of economic
            series it holds is empty. That is not a failure: no series have been
            registered in this database. Once one is, it appears here whether or not any
            observations have been loaded into it.
          </p>
        </div>
      </>
    );
  }

  // One attribution per publisher, word for word - DESIGN.md §6 forbids paraphrasing one.
  // A Map keyed on the publisher's own name de-duplicates without altering a single
  // character of the string it stores.
  const attributions = new Map<string, string>();
  for (const candidate of series) {
    attributions.set(candidate.source_name, candidate.attribution);
  }

  return (
    <>
      <h1>The economy</h1>
      <p className="page-note">
        Prices, interest rates, output and debt for Nigeria and the United States, as the
        statistical agencies and central banks themselves published them.
      </p>

      <div className="panel">
        <div className="panel-head">
          <h2>Every series</h2>
          <Link href="/how-to-read-this">How to read this</Link>
        </div>
        <div className="scroller">
          <table>
            <caption>
              Every economic series this system holds, with the latest observation in
              each. <b>Value as of</b> is the period that observation covers;{" "}
              <b>known as of</b> is the day it became public. A series with nothing in it
              is still listed, so that an absence is visible rather than silent.
            </caption>
            <thead>
              <tr>
                <th scope="col">Code</th>
                <th scope="col">Series</th>
                <th scope="col" className="num">
                  Latest
                </th>
                {/* "Measured in", not "Unit", for the same reason as below: a header is
                    nowrap and a body cell is not, so a four-letter header squeezed
                    "per cent" onto two lines in every row of the table. */}
                <th scope="col">Measured in</th>
                <th scope="col">Frequency</th>
                {/* Named in parallel with its neighbour rather than shortened to "As
                    of". The two dates are the point of this table, so the pair reads as
                    a pair - and a header is `white-space: nowrap`, so the longer label
                    also holds the column open wide enough to keep a date on one line. */}
                <th scope="col">Value as of</th>
                <th scope="col">Known as of</th>
                <th scope="col" className="num">
                  Observations
                </th>
                <th scope="col">Freshness</th>
                <th scope="col">Publisher</th>
              </tr>
            </thead>
            <tbody>
              {series.map((item) => (
                <tr key={item.code}>
                  <th scope="row">{item.code}</th>
                  {/* The base period belongs with the name rather than with the unit:
                      it says what an index value is counted against, and the name cell
                      is the one wide enough to hold it on a single line. In the unit
                      column "GDP 2010=100 constant basic prices" wrapped to four lines
                      and took the whole row with it. */}
                  <td className="wrap-cell">
                    {item.name}
                    {item.base_period ? (
                      <div className="faint">{item.base_period}</div>
                    ) : null}
                  </td>
                  <LatestValueCell series={item} />
                  <td>{unitInWords(item.unit)}</td>
                  <td>{sentenceCase(item.frequency)}</td>
                  <DayCell iso={item.latest_as_of} whenMissing={NOT_LOADED} />
                  <DayCell iso={item.latest_known_as_of} whenMissing={NOT_LOADED} />
                  <td className="num">{count(item.observation_count)}</td>
                  <td>
                    <Freshness series={item} />
                  </td>
                  <td>{item.source_name}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        {/* Conditional on purpose. A flat "this table scrolls" is only true while the
            columns happen to overflow, and column widths changed twice on this page
            alone. `.scroll-hint` hides above a 900px *viewport*, which is not the same
            question as whether the *container* overflows. This wording asserts nothing
            about the current width, so it cannot go stale. */}
        <p className="scroll-hint">
          If this table is wider than your screen, it scrolls sideways rather than the
          page.
        </p>
      </div>

      <Disclose brief="CPI is the price of one fixed basket of what households buy, measured over and over.">
        <p>
          Statisticians fix a basket of the things households actually buy — rice, rent,
          transport, fuel, school fees — and price that same basket again each period. The
          index is what the basket costs, written against a base year set to 100, which is
          the <b>base period</b> shown beside the unit.
        </p>
        <p>
          Year-on-year turns the index into the figure people usually quote: the percentage
          by which the basket costs more than it did in the same month a year earlier. A{" "}
          <b>core</b> CPI leaves food and energy out, because those two move with weather
          and shipping rather than with the general level of prices.
        </p>
      </Disclose>

      <Disclose brief="A policy rate is the interest rate a central bank sets in order to steer every other rate.">
        <p>
          Nigeria&rsquo;s Monetary Policy Rate and the United States&rsquo; federal funds
          rate are both of this kind. It is the price of short-term money between banks,
          and mortgage, loan and savings rates move with it. A central bank raises it to
          make borrowing dearer and lowers it to make borrowing cheaper.
        </p>
      </Disclose>

      <Disclose brief="An observation count of zero is a true count. A value of zero would be a false measurement.">
        <p>
          The observation count is a count. Counting the rows in an empty series and
          getting nought is a true answer, so nought is what that column says. The latest
          value is a different kind of thing: there is no latest value to report, and
          printing a zero there would claim that a price, or a rate, had been measured at
          zero. So it says <b>{NOT_LOADED}</b> instead.
        </p>
        <p>
          This is the distinction the whole system is built around. A zero is something
          somebody measured. A blank is something nobody has.
        </p>
      </Disclose>

      <Disclose brief="Nigerian inflation is listed more than once because it is published more than once.">
        <p>
          The National Bureau of Statistics compiles it; the Central Bank of Nigeria
          republishes its own copy; the World Bank keeps an annual series that reaches this
          database through FRED. They are stored separately, under separate codes, because
          they are separate publications with separate dates.
        </p>
        <p>
          They are not merged into a single number. Where two of them differ you can see
          both and see which publisher said which, which is the reason for keeping them
          apart.
        </p>
      </Disclose>

      <Disclose brief="A series marked “no expected date” has nothing to be late for.">
        <p>
          Most of these arrive on a rhythm: a monthly index turns up a few weeks after the
          month it covers has ended, so the system can tell when one is later than it
          usually is. That is what <b>later than usual</b> and <b>arrived on time</b>{" "}
          compare against.
        </p>
        <p>
          A policy rate has no such rhythm. It changes when a committee decides to change
          it, and a long gap between observations means the rate did not move — not that
          anything failed to arrive. There is nothing for it to be late for, so the
          freshness column says that rather than guessing.
        </p>
      </Disclose>

      <div className="source">
        <p>
          Reproduced exactly as each publisher gives it. Each row of the table carries its
          own two dates.
        </p>
        <dl>
          {Array.from(attributions).map(([name, attribution]) => (
            <Fragment key={name}>
              <dt>{name}</dt>
              <dd>{attribution}</dd>
            </Fragment>
          ))}
        </dl>
      </div>
    </>
  );
}

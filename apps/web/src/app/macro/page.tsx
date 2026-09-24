import { Fragment } from "react";
import type { Metadata } from "next";
import Link from "next/link";

import { ApiTimeout, api, type MacroSeries, failTheBuildInstead } from "@/lib/api";
import {
  NOT_LOADED,
  formatDay,
  sentenceCase,
  unitInWords,
  withUnit,
  SERVICE_IS_SLOW,
} from "@/lib/format";

export const metadata: Metadata = {
  title: "The economy",
  description:
    "Nigerian and US economic series - prices, interest rates, output and debt - each " +
    "one showing the period it covers, the date it became knowable, and who published it.",
};

/**
 * The four series the explainer above them defines: two measures of prices and two
 * policy rates, one of each for Nigeria and the United States. DESIGN.md §2 caps a page
 * at four headline figures, so this list is four long and the rest of the page is the
 * full table.
 *
 * Matched by code. A code missing from the response simply does not get a card - a
 * series is never invented - and the table below still lists everything that is there.
 */
const HEADLINE_CODES = ["NG_CPI_YOY", "NG_MPR", "US_CPI_INDEX", "US_FED_FUNDS"];

/**
 * Freshness, as the API reports it. `is_stale` has three states and all three mean
 * something different:
 *
 *   false - the newest observation arrived inside the lag this source normally takes
 *   true  - it did not
 *   null  - there is no expected arrival date for it to be measured against
 *
 * DESIGN.md §3: the word is always beside the colour, and the colour is never blue.
 */
function Freshness({ series }: { series: MacroSeries }) {
  if (series.observation_count === 0) {
    return <span className="pill neutral">nothing loaded</span>;
  }
  if (series.is_stale === null) {
    return <span className="pill neutral">no expected date</span>;
  }
  if (series.is_stale) {
    return <span className="pill attention">later than usual</span>;
  }
  return <span className="pill ok">arrived on time</span>;
}

/**
 * A value, or the honest absence of one. Never a zero standing in for a blank, and
 * never an empty cell that a reader could mistake for one.
 */
function Value({ series }: { series: MacroSeries }) {
  if (series.observation_count === 0 || series.latest_value === null) {
    return <span className="muted">{NOT_LOADED}</span>;
  }
  return <span className="num">{withUnit(series.latest_value, series.unit)}</span>;
}

export default async function MacroPage() {
  let series: MacroSeries[];

  try {
    ({ series } = await api.macro());
  } catch (error) {
    failTheBuildInstead(error);
    // A timeout is our budget expiring, not the API failing. Painted red and worded as
    // a failure it sends a reader looking for a fault that is not there.
    const slow = error instanceof ApiTimeout;
    const detail = error instanceof Error ? error.message : "unknown error";
    return (
      <>
        <h1>The economy</h1>
        <div className={slow ? "notice" : "notice bad"}>
          <h3>
            {slow
              ? "This is taking longer than the page waits"
              : "The economic series could not be loaded"}
          </h3>
          <p>
            {slow
              ? SERVICE_IS_SLOW
              : "This page asked the API for its list of series and did not get one. " +
                "Nothing is being hidden below — there is simply nothing to show " +
                "until that call succeeds."}
          </p>
          <p>
            Reported as: <span className="num">{detail}</span>
          </p>
          <p>
            Running this locally, the API is the uvicorn process on port 8000. Reload
            once it is answering.
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
          <h3>No series are defined yet</h3>
          <p>
            The API answered, and the list of economic series it holds is empty. That is
            not a failure: no series have been registered in this database. Once one is,
            it appears here whether or not any observations have been loaded into it.
          </p>
        </div>
      </>
    );
  }

  const headlines = HEADLINE_CODES.map((code) =>
    series.find((candidate) => candidate.code === code),
  ).filter((candidate): candidate is MacroSeries => candidate !== undefined);

  const notLoaded = series.filter((candidate) => candidate.observation_count === 0);

  // One attribution per publisher, word for word - DESIGN.md §5 forbids paraphrasing
  // one. A Map keyed on the publisher's own name de-duplicates without altering a
  // single character of the string it stores.
  const attributions = new Map<string, string>();
  for (const candidate of series) {
    attributions.set(candidate.source_name, candidate.attribution);
  }

  return (
    <>
      <h1>The economy</h1>
      <p className="lede">
        Prices, interest rates, output and debt for Nigeria and the United States, as
        published by the statistical agencies and central banks themselves. Every figure
        shows the period it is about and the date it became public — two different
        things, and the difference is explained on{" "}
        <Link href="/how-to-read-this">how to read this</Link>.
      </p>

      <div className="explain">
        <span className="tag">What these numbers are</span>
        <p>
          <b>CPI</b> is the consumer price index. Statisticians fix a basket of the
          things households actually buy — rice, rent, transport, fuel, school fees —
          and price that same basket over and over. The index is what the basket costs,
          written against a base year set to 100. Year-on-year turns it into the figure
          people usually quote: the percentage by which the basket costs more than it
          did in the same month a year earlier. A <b>core</b> CPI leaves food and energy
          out, because those two move with weather and shipping rather than with the
          general level of prices.
        </p>
        <p>
          A <b>policy rate</b> — Nigeria&rsquo;s Monetary Policy Rate, the United
          States&rsquo; federal funds rate — is the interest rate a central bank sets in
          order to steer every other rate. It is the price of short-term money between
          banks, and mortgage, loan and savings rates move with it. A central bank
          raises it to make borrowing dearer and lowers it to make borrowing cheaper.
        </p>
      </div>

      {headlines.length > 0 && (
        <>
          <h2>Prices and policy rates</h2>
          <div className="grid cols-4">
            {headlines.map((item) => (
              <div className="card" key={item.code}>
                <div className="stat-value">
                  <Value series={item} />
                </div>
                <div className="stat-name">{item.name}</div>
                <div className="stat-note">
                  {item.latest_as_of
                    ? `Covers ${formatDay(item.latest_as_of)}`
                    : "No period recorded"}
                </div>
                <div className="stat-note">
                  {item.latest_known_as_of
                    ? `Knowable from ${formatDay(item.latest_known_as_of)}`
                    : "No publication date recorded"}
                </div>
                <div className="stat-note">
                  <Freshness series={item} />
                </div>
              </div>
            ))}
          </div>
        </>
      )}

      {notLoaded.length > 0 && (
        <div className="notice">
          <h3>Some series are defined but hold no observations</h3>
          <p>
            These exist in the schema and have a publisher assigned, but nothing has
            been loaded into them yet. They appear in the table below with{" "}
            <b>{NOT_LOADED}</b> where a value would go, and never with a zero — a zero
            is a measurement somebody took, and this is the absence of one.
          </p>
          <ul>
            {notLoaded.map((item) => (
              <li key={item.code}>
                {item.name} <span className="faint">({item.code})</span>
              </li>
            ))}
          </ul>
        </div>
      )}

      <h2>Every series</h2>
      <div className="scroller">
        <table>
          <caption>
            Every economic series this system holds, with the latest observation in
            each. A series with nothing in it is still listed, so that an absence is
            visible rather than silent.
          </caption>
          <thead>
            <tr>
              <th scope="col">Series</th>
              <th scope="col" className="num">
                Latest value
              </th>
              <th scope="col">Covers</th>
              <th scope="col">Knowable from</th>
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
                <th scope="row" className="wrap-cell">
                  {item.name}
                  <div className="faint">
                    {item.code} · {unitInWords(item.unit)} ·{" "}
                    {sentenceCase(item.frequency)}
                    {item.base_period ? ` · ${item.base_period}` : ""}
                  </div>
                </th>
                <td className="num">
                  <Value series={item} />
                </td>
                <td>
                  {formatDay(item.latest_as_of) ?? (
                    <span className="muted">{NOT_LOADED}</span>
                  )}
                </td>
                <td>
                  {formatDay(item.latest_known_as_of) ?? (
                    <span className="muted">{NOT_LOADED}</span>
                  )}
                </td>
                <td className="num">{item.observation_count}</td>
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
          alone. `.scroll-hint` hides above an 860px *viewport*, which is not the
          same question as whether the *container* overflows - inside `details.more`
          the container stops growing at --prose (~551px) and the two diverge. This
          wording asserts nothing about the current width, so it cannot go stale. */}
      <p className="scroll-hint">
        If this table is wider than your screen, it scrolls sideways rather than the
        page.
      </p>

      <details className="more">
        <summary>Why the observation count can be zero when the value cannot</summary>
        <p>
          The observation count is a count. Counting the rows in an empty series and
          getting nought is a true answer, so nought is what that column says. The value
          column is a different kind of thing: there is no latest value to report, and
          printing a zero there would claim that a price, or a rate, had been measured
          at zero. So it says <b>{NOT_LOADED}</b> instead.
        </p>
        <p>
          This is the distinction the whole system is built around. A zero is something
          somebody measured. A blank is something nobody has.
        </p>
      </details>

      <details className="more">
        <summary>Why some of these look like duplicates</summary>
        <p>
          Nigerian inflation appears more than once because it is published more than
          once. The National Bureau of Statistics compiles it; the Central Bank of
          Nigeria republishes its own copy; the World Bank keeps an annual series that
          reaches this database through FRED. They are stored separately, under separate
          codes, because they are separate publications with separate dates.
        </p>
        <p>
          They are not merged into a single number. Where two of them differ you can see
          both and see which publisher said which, which is the reason for keeping them
          apart.
        </p>
      </details>

      <details className="more">
        <summary>What &ldquo;no expected date&rdquo; means</summary>
        <p>
          Most of these series arrive on a rhythm: a monthly index turns up a few weeks
          after the month it covers has ended, so the system can tell when one is later
          than it usually is.
        </p>
        <p>
          A policy rate has no such rhythm. It changes when a committee decides to change
          it, and a long gap between observations means the rate did not move — not that
          anything failed to arrive. There is nothing for it to be late for, so the
          freshness column says that rather than guessing.
        </p>
      </details>

      <div className="source">
        <p>
          Attribution below is reproduced exactly as each publisher gives it. Each row of
          the table carries its own two dates.
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

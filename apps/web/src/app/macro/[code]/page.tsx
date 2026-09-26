import type { ReactNode } from "react";
import type { Metadata } from "next";
import Link from "next/link";

import {
  ApiError,
  ApiTimeout,
  api,
  failTheBuildInstead,
  type MacroObservations,
  type MacroSeries,
} from "@/lib/api";
import {
  NOT_LOADED,
  NOT_REPORTED,
  SERVICE_IS_SLOW,
  count,
  formatDay,
  sentenceCase,
  unitInWords,
  withUnit,
} from "@/lib/format";
import { Disclose } from "@/components/disclose";
import { SeriesChart, extremes } from "@/components/sparkline";
import { Freshness } from "../../_series";

interface PageProps {
  params: Promise<{ code: string }>;
}

/**
 * One economic series: what it measures, every period held, and both dates on every one
 * of them.
 *
 * This is the clearest place in the whole app to show what `DESIGN.md` §6 is about. A
 * company filing has two dates too, but a macro series makes the gap impossible to miss:
 * Nigerian CPI for August is published at the end of September, and the World Bank's
 * annual figure for 2025 reached this database in July 2026. So the two dates are a
 * column each in the table, a metric each at the top, and a sentence under the heading
 * that names them both for this series in particular.
 *
 * Twenty-eight thousand observations sat in the database with no page that could show
 * one. This is that page.
 */

/**
 * The thirteen codes, so each series prerenders rather than being fetched on a reader's
 * first visit.
 *
 * Returning an empty list is not a failure: unknown params still render on demand, so a
 * dev server started before the API is answering serves the page rather than refusing to
 * boot. At build time `failTheBuildInstead` rethrows, and a build that could not read the
 * list of series has not produced a publishable site.
 */
export async function generateStaticParams(): Promise<{ code: string }[]> {
  try {
    const { series } = await api.macro();
    return series.map((item) => ({ code: item.code }));
  } catch (error) {
    failTheBuildInstead(error);
    return [];
  }
}

export async function generateMetadata({ params }: PageProps): Promise<Metadata> {
  const { code } = await params;
  const written = decodeURIComponent(code);
  return {
    title: written,
    description:
      `Every observation held for ${written}, each showing the period it describes and ` +
      "the date it became public, with the publisher's own attribution.",
  };
}

/**
 * One figure and its label. Absent is a state of the tile, not a missing tile: an empty
 * cell in a metric row reads as a rendering fault, and `.absent` reads as an absence.
 */
function Metric({
  name,
  value,
  absent,
}: {
  name: string;
  value: ReactNode;
  absent?: boolean;
}) {
  return (
    <div className="metric">
      <div className="metric-name wrap">{name}</div>
      <div className={absent ? "metric-value absent" : "metric-value"}>{value}</div>
    </div>
  );
}

/**
 * Every way this page can fail to get its series, and what each one means.
 *
 * Three different things, three different answers, and only one of them is a fault. A
 * code nobody holds sends the reader back to the list. A request that outran our patience
 * is not a failure at all - §8, `.notice` rather than `.notice bad`, and never the word
 * "failed". Each supplies the page's `<h1>`, because the header that normally carries it
 * never got the data to render.
 */
function SeriesProblem({ code, error }: { code: string; error: unknown }) {
  const status = error instanceof ApiError ? error.status : null;

  if (error instanceof ApiTimeout) {
    return (
      <>
        <h1>{code}</h1>
        <div className="notice">
          <h2>This is taking longer than the page waits</h2>
          <p>{SERVICE_IS_SLOW}</p>
          <p>
            Reload the page. <Link href="/macro">Back to every series</Link>.
          </p>
        </div>
      </>
    );
  }

  if (status === 404) {
    return (
      <>
        <h1>No series under &ldquo;{code}&rdquo;</h1>
        <div className="notice bad">
          <h2>Nothing is held under this code</h2>
          <p>
            The API holds no economic series called <b>{code}</b>. It may be spelled
            differently, or it may simply not be one of the series registered here.
          </p>
          <p>
            <Link href="/macro">The list of every series held</Link> is the place to
            check — each row there links to its own page.
          </p>
        </div>
      </>
    );
  }

  return (
    <>
      <h1>{code}</h1>
      <div className="notice bad">
        <h2>These observations could not be loaded</h2>
        <p>
          The request for this series did not come back
          {status === null ? " at all" : ` — the API answered ${status}`}. Nothing is
          shown below, because half a series charted as a whole one is a different series.
        </p>
        <p>
          Reload the page. If it keeps happening, the API is not answering; the{" "}
          <Link href="/data-health">data health</Link> page is where that shows up.{" "}
          <Link href="/macro">Back to every series</Link>.
        </p>
      </div>
    </>
  );
}

export default async function MacroSeriesPage({ params }: PageProps) {
  const { code: raw } = await params;
  const code = decodeURIComponent(raw);

  let page: MacroObservations;
  try {
    // No limit passed: the API applies its own, takes the most recent periods, and says
    // `truncated` when it did. That flag is rendered below - a partial series drawn as a
    // whole one is the mistake this endpoint's own documentation warns about.
    page = await api.macroObservations(code);
  } catch (error) {
    // First statement in the catch. This route prerenders, so a caught failure during
    // `next build` would otherwise be baked into the HTML and served to every visitor as
    // though the series were gone.
    failTheBuildInstead(error);
    return <SeriesProblem code={code} error={error} />;
  }

  // The list is asked only for what the observations endpoint does not send: how often
  // this is published, what an index value is counted against, how long a wait is normal
  // and whether this one has exceeded it. It cannot take the page down - the observations
  // are the page, and they have already arrived.
  let described: MacroSeries | undefined;
  try {
    described = (await api.macro()).series.find((item) => item.code === page.code);
  } catch (error) {
    failTheBuildInstead(error);
    described = undefined;
  }

  const points = page.observations;
  // The array arrives oldest first, so the last element is the newest period held. Taking
  // the end of a list is not arithmetic; nothing here is derived from two figures.
  const newest = points.length === 0 ? null : points[points.length - 1];
  const edges = extremes(points);

  return (
    <>
      <p className="faint">
        <Link href="/macro">&larr; Every series</Link>
      </p>

      <div className="security-head">
        {/* The page's only `<h1>`. The code, because that is what the list links by and
            what the API answers to; the name sits beside it. */}
        <h1 className="symbol">{page.code}</h1>
        <span className="legal-name">{page.name}</span>
        <span className="exchange">{page.source_name}</span>

        {newest === null || newest.value === null ? (
          <span className="price metric-value absent">{NOT_LOADED}</span>
        ) : (
          <span className="price">{withUnit(newest.value, page.unit)}</span>
        )}

        {/* The sentence this page exists for. Both dates, named, for this series in
            particular - not a general note about provenance but the actual pair on the
            actual newest figure. */}
        <span className="asof">
          {newest === null
            ? "No observation has been loaded for this series, so there is no period and no publication date to report."
            : `The newest figure describes ${formatDay(newest.as_of_date)} — that is the period it is about — and became public on ${formatDay(newest.known_as_of)}. Those are two different dates and the difference is the point.`}
        </span>
        <span className="asof">
          {page.attribution ??
            `${page.source_name} — this endpoint sent no attribution line of its own.`}
        </span>
      </div>

      <div className="metrics">
        <Metric
          name="Newest figure"
          value={
            newest === null || newest.value === null
              ? NOT_LOADED
              : withUnit(newest.value, page.unit)
          }
          absent={newest === null || newest.value === null}
        />
        <Metric
          name="Period covered"
          value={newest === null ? NOT_LOADED : formatDay(newest.as_of_date)}
          absent={newest === null}
        />
        <Metric
          name="Public since"
          value={newest === null ? NOT_LOADED : formatDay(newest.known_as_of)}
          absent={newest === null}
        />
        <Metric name="Measured in" value={unitInWords(page.unit)} />
        {described === undefined ? null : (
          <>
            <Metric name="Published" value={sentenceCase(described.frequency)} />
            {/* Both of these come from the API. `days_since_as_of` in particular is sent
                so that a page can say how late a series is without subtracting two dates
                in a component, which AD-3 forbids and which would also be measured
                against the reader's clock rather than the API's. */}
            {/* Labels are kept to one line on purpose. `.metric-name.wrap` has a 2em
                floor rather than a fixed height, so a label that wraps to two lines
                pushes its own figure below the row - and a row of figures that do not
                share a baseline reads as a rendering fault. */}
            <Metric
              name="Since period end"
              value={
                described.days_since_as_of === null
                  ? NOT_LOADED
                  : `${count(described.days_since_as_of)} days`
              }
              absent={described.days_since_as_of === null}
            />
            <Metric
              name="Usual wait"
              value={
                described.expected_lag_days === null
                  ? NOT_REPORTED
                  : `${count(described.expected_lag_days)} days`
              }
              absent={described.expected_lag_days === null}
            />
            <Metric name="Freshness" value={<Freshness series={described} />} />
          </>
        )}
        <Metric name="Periods held" value={count(page.total_available)} />
        {described === undefined ? null : (
          <Metric name="Versions held" value={count(described.observation_count)} />
        )}
        {/* Omitted rather than written absent when there is none. A rate is not counted
            against a base year, so there is no base period to be missing - and none of
            the three absence phrases would be true of it. */}
        {described?.base_period ? (
          <Metric name="Counted against" value={described.base_period} />
        ) : null}
      </div>

      {described === undefined ? (
        <div className="notice">
          <h2>How often this is published could not be loaded</h2>
          <p>
            The observations below arrived and are complete. The separate call that
            describes the series — how often it is published, how long a wait is normal,
            and whether this one has exceeded it — did not come back, so those figures are
            not above. Nothing else on this page depends on it.
          </p>
        </div>
      ) : null}

      {page.truncated ? (
        <div className="notice">
          <h2>This is the end of a longer series</h2>
          <p>
            <b>{count(page.total_available)}</b> periods are held and the most recent{" "}
            <b>{count(points.length)}</b> are on this page. The chart and the table below
            both begin where those begin — the earlier periods exist and are not shown
            here.
          </p>
        </div>
      ) : null}

      {points.length === 0 ? (
        <div className="notice">
          <h2>Nothing has been loaded into this series</h2>
          <p>
            The series itself is held — its name, its unit and its publisher are above —
            and not one observation has been fetched into it. That is{" "}
            <b>{NOT_LOADED}</b>, and it is our absence rather than{" "}
            {page.source_name}&rsquo;s.
          </p>
          <p>
            It is not zero. Nobody has measured this at nought, and there is no chart
            below because a series with no observations has no line: a flat line along
            zero is the one thing this system will not draw.
          </p>
          <p>
            <Link href="/data-health">Data health</Link> is where you can see whether the
            job that fetches it has run.
          </p>
        </div>
      ) : (
        <>
          <div className="panel">
            <div className="panel-head">
              <h2>Every period held</h2>
              <a href="#observations">The figures behind it</a>
            </div>
            <div className="panel-body">
              {edges === null || edges.plotted < 2 ? (
                <p className="muted">
                  A line needs two periods that carry a figure, and this series has{" "}
                  {edges === null ? "none" : "one"}. Nothing is drawn, because a line
                  through a single point asserts a direction nobody measured. The table
                  below holds what there is.
                </p>
              ) : (
                <>
                  <SeriesChart
                    points={points}
                    label={
                      `${page.name}, ${count(edges.plotted)} periods from ` +
                      `${formatDay(edges.first.as_of_date)} to ${formatDay(edges.last.as_of_date)}. ` +
                      `Lowest ${withUnit(edges.low.value as string, page.unit)} for ` +
                      `${formatDay(edges.low.as_of_date)}; highest ` +
                      `${withUnit(edges.high.value as string, page.unit)} for ` +
                      `${formatDay(edges.high.as_of_date)}. ` +
                      `Every plotted figure is listed in the table below this chart.`
                    }
                  />
                  {/* The axis, in words. Nothing a reader needs is legible only as a
                      pixel, and this is also the description a screen reader gets in the
                      chart's own label. */}
                  <p className="hint">
                    Across: the period each figure describes, from{" "}
                    {formatDay(edges.first.as_of_date)} to{" "}
                    {formatDay(edges.last.as_of_date)} — not the days they were published.
                    Up: from the lowest figure held,{" "}
                    {withUnit(edges.low.value as string, page.unit)} for{" "}
                    {formatDay(edges.low.as_of_date)}, to the highest,{" "}
                    {withUnit(edges.high.value as string, page.unit)} for{" "}
                    {formatDay(edges.high.as_of_date)}. The scale spans the figures held
                    and is not anchored at zero.
                    {edges.gaps > 0
                      ? ` ${count(edges.gaps)} of these periods carry no figure, and the line breaks rather than crossing them.`
                      : ""}
                  </p>
                </>
              )}
            </div>
          </div>

          {/* Folded, as the price chart's table is (`DESIGN.md` 4b): the other rendering of
              the chart above, one summary line until it is asked for. Laid out open, a
              monthly series from 1947 is 956 rows - a page roughly 35,000px tall on a
              phone, with the notes below it out of reach. The anchor sits on a wrapper
              rather than inside the `<details>`, so following it lands on the summary in
              every browser instead of on an element some of them will not reveal. */}
          <div id="observations">
            <Disclose
              brief={`Every observation, as a table — ${count(points.length)} periods, newest first.`}
            >
              <div className="scroller">
                <table>
                  <caption>
                    <b>Period covered</b> is what each figure is about; <b>known as of</b>{" "}
                    is the day it became public. Each period is shown at its newest version.
                  </caption>
                  <thead>
                    <tr>
                      <th scope="col">Period covered</th>
                      <th scope="col">Known as of</th>
                      <th scope="col" className="num">
                        Value
                      </th>
                    </tr>
                  </thead>
                  <tbody>
                    {/* Reversed on a copy, so the newest period is at the top. Ordering,
                        not arithmetic - the same operation the overview uses on filings. */}
                    {[...points].reverse().map((point) => (
                      <tr key={point.as_of_date}>
                        <th scope="row" className="nowrap">
                          {formatDay(point.as_of_date)}
                        </th>
                        <td className="nowrap">{formatDay(point.known_as_of)}</td>
                        {point.value === null ? (
                          // The row was loaded and the publisher's own record for that
                          // period carries no figure. That is the publisher's absence, not
                          // ours, so it is `NOT_REPORTED` rather than `NOT_LOADED` - and it
                          // is never a zero, which would claim a measurement of nought.
                          <td className="num absent">{NOT_REPORTED}</td>
                        ) : (
                          <td className="num">{withUnit(point.value, page.unit)}</td>
                        )}
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              <p className="scroll-hint">
                If this table is wider than your screen, it scrolls sideways rather than the
                page.
              </p>
            </Disclose>
          </div>
        </>
      )}

      <Disclose brief="A period and a publication date are two different things, and mixing them up is how a backtest lies.">
        <p>
          Take the newest row above. The figure is about a period that has ended; it
          became public weeks or months later, once the agency had collected and checked
          it. Anyone deciding anything on the day that period ended could not have known
          it, because it did not exist yet.
        </p>
        <p>
          A model fed on period dates alone therefore appears to have known every figure
          the moment the period closed. It looks prescient and it is simply reading the
          future. Keeping both dates on every observation is what makes the difference
          checkable rather than assumed —{" "}
          <Link href="/how-to-read-this">how to read this</Link> goes further into it.
        </p>
      </Disclose>

      <Disclose brief="Each period here is shown at its newest version, and the older versions are still stored.">
        <p>
          Statistical agencies revise. The same month is published, then restated as more
          returns come in, and each publication is kept here as its own row with its own{" "}
          <b>known as of</b>. This page asks for the newest version of every period, which
          is the right view for reading what is true now.
        </p>
        <p>
          It is the wrong view for asking what was knowable on a particular day — and that
          is why the API takes a date and answers as of it. That view is not built into
          this page yet; the difference between <b>periods held</b> and{" "}
          <b>versions held</b> in the figures above is how many revisions are sitting behind
          it.
        </p>
      </Disclose>

      <Disclose brief="A figure this system was given is printed exactly as it was given, however many digits that is.">
        <p>
          Some of these carry more decimal places than anybody needs — an annual series
          relayed through a third party arrives with thirteen of them. They are not
          tidied, because the figure of record is the one the publisher issued and this
          app does not quietly round somebody else&rsquo;s number into something more
          comfortable.
        </p>
        <p>
          The rule cuts the other way for anything the system works out for itself: that
          is rounded, because its digits come from a division rather than from a
          measurement. Nothing on this page is worked out here at all.
        </p>
      </Disclose>

      <div className="source">
        <p>
          Reproduced exactly as the publisher gives it. Every row above carries its own
          two dates.
        </p>
        <dl>
          <dt>{page.source_name}</dt>
          <dd>
            {page.attribution ??
              "this endpoint sent no attribution line for this series"}
          </dd>
          <dt>Version shown</dt>
          <dd>
            {page.as_known_on === null
              ? "each period at its newest version"
              : `each period as it stood on ${formatDay(page.as_known_on)}`}
          </dd>
        </dl>
      </div>
    </>
  );
}

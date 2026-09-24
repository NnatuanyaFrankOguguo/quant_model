import { Fragment } from "react";
import Link from "next/link";
import type { Metadata } from "next";

import {
  ApiError,
  ApiTimeout,
  api,
  failTheBuildInstead,
  type CompanySummary,
  type HoldingsSummary,
  type MacroSeries,
} from "@/lib/api";
import { NOT_LOADED, NOT_REPORTED, SERVICE_IS_SLOW, count, formatDay } from "@/lib/format";
import { Disclose } from "@/components/disclose";
import { DayCell, Freshness, LatestValueCell } from "./_series";

export const metadata: Metadata = {
  title: "Overview",
  description:
    "What this system holds: companies and their filings, and the Nigerian and US " +
    "economic series, each figure showing the period it covers and the date it became " +
    "knowable.",
};

/**
 * The front page.
 *
 * It is not a menu. `DESIGN.md` §2 - data first, on every page - so this opens with the
 * three counts the API took of itself and then with the two tables worth scanning: what
 * has been filed most recently, and where the economic series stand. Every figure it
 * prints was produced by the server; none is written into this file.
 *
 * The three fetches are settled independently rather than awaited together, because one
 * dead endpoint should cost this page one panel rather than all of it.
 */

const RECENT_FILINGS = 10;

type Loaded<T> = { ok: true; value: T } | { ok: false; error: unknown };

/**
 * One fetch, resolved rather than thrown.
 *
 * `failTheBuildInstead(error)` is the first statement in the catch, and this page is
 * static: without it, a build started while the API was blinking would bake "could not
 * be reached" into the prerendered HTML, exit 0, and tell every visitor the same thing
 * until something revalidated it.
 */
async function settle<T>(fetching: Promise<T>): Promise<Loaded<T>> {
  try {
    return { ok: true, value: await fetching };
  } catch (error) {
    failTheBuildInstead(error);
    return { ok: false, error };
  }
}

/**
 * What a reader is told when one of the three calls did not come back.
 *
 * A timeout is our budget expiring, not the service failing - `.notice`, never
 * `.notice.bad`, and never the word "failed". DESIGN.md §8.
 */
function Trouble({ error, subject }: { error: unknown; subject: string }) {
  const slow = error instanceof ApiTimeout;
  // The title is a bold lead rather than an `<h3>`. A notice can open a page, and an
  // `<h3>` there jumps straight from the `<h1>` - DESIGN.md §9 allows no skipped level.
  return (
    <div className={slow ? "notice" : "notice bad"}>
      <p>
        <b>
          {slow
            ? `${subject} is taking longer than this page waits.`
            : `${subject} did not load.`}
        </b>{" "}
        {slow
          ? SERVICE_IS_SLOW
          : error instanceof ApiError
            ? `The data service answered ${error.status}. Nothing here is being hidden — there is nothing to show until that call succeeds.`
            : "The data service could not be reached. Running this locally, it is the uvicorn process on port 8000."}
      </p>
    </div>
  );
}

export default async function Overview() {
  const [held, companies, macro] = await Promise.all([
    settle<HoldingsSummary>(api.summary()),
    settle<{ companies: CompanySummary[] }>(api.companies()),
    settle<{ series: MacroSeries[] }>(api.macro()),
  ]);

  // Ordering, not arithmetic (AD-3). ISO dates sort chronologically as plain strings, so
  // "most recently filed" costs one string comparison and no date maths; a company with
  // no filing date recorded sorts to the end rather than to the top.
  const filings = companies.ok
    ? [...companies.value.companies]
        .sort((a, b) =>
          (b.latest_filing_date ?? "").localeCompare(a.latest_filing_date ?? ""),
        )
        .slice(0, RECENT_FILINGS)
    : [];

  const series = macro.ok ? macro.value.series : [];

  // One attribution per publisher, word for word - DESIGN.md §6 forbids paraphrasing one.
  // A Map keyed on the publisher's own name de-duplicates without altering a character of
  // the string it stores.
  const attributions = new Map<string, string>();
  for (const candidate of series) {
    attributions.set(candidate.source_name, candidate.attribution);
  }

  return (
    <>
      <h1>Overview</h1>
      <p className="page-note">
        Published company accounts and economic series, each figure kept with the period
        it covers and the date it became knowable.
      </p>

      {held.ok ? (
        <div className="metrics">
          <div className="metric">
            <div className="metric-name">Companies</div>
            <div className="metric-value num">{count(held.value.companies)}</div>
          </div>
          <div className="metric">
            <div className="metric-name">Reporting periods</div>
            <div className="metric-value num">{count(held.value.statement_periods)}</div>
          </div>
          <div className="metric">
            <div className="metric-name">Economic series</div>
            <div className="metric-value num">{count(held.value.macro_series)}</div>
          </div>
        </div>
      ) : (
        <Trouble error={held.error} subject="The count of what is held" />
      )}

      <Disclose brief="A reporting period and the day it became public are two different dates.">
        <p>
          <b>period_end</b> is what a figure is about. A company&rsquo;s revenue for the
          year ending 31 December 2024 is about 2024. <b>known_as_of</b> is when anybody
          outside the company could have read it — the books are closed, the auditors work
          through them, and the annual report reaches the public some months into 2025.
        </p>
        <p>
          So a 2024 figure is not a 2024 fact. It is a 2025 fact about 2024. Every table
          on this site carries both dates, and{" "}
          <Link href="/how-to-read-this">how to read this</Link> explains what goes wrong
          when they are collapsed into one.
        </p>
      </Disclose>

      <div className="panel">
        <div className="panel-head">
          <h2>Latest filings</h2>
          <Link href="/companies">All companies</Link>
        </div>
        {companies.ok ? (
          filings.length === 0 ? (
            <div className="panel-body">
              <p className="muted">
                The API answered and its company list is empty. Nothing has failed — a
                company appears here once the loader has fetched one of its filings.
              </p>
            </div>
          ) : (
            <>
              <div className="scroller">
                <table>
                  <caption>
                    The most recently filed companies, newest filing first. Periods held
                    is how many quarterly and annual statements this system stores for
                    that company.
                  </caption>
                  <thead>
                    <tr>
                      <th scope="col">Symbol</th>
                      <th scope="col">Company</th>
                      <th scope="col">Exchange</th>
                      <th scope="col" className="num">
                        Periods held
                      </th>
                      <th scope="col">Period end</th>
                      <th scope="col">Filed</th>
                      <th scope="col">Next report</th>
                      <th scope="col">Due by</th>
                    </tr>
                  </thead>
                  <tbody>
                    {filings.map((company) => (
                      <tr key={company.ticker}>
                        <th scope="row">
                          <Link href={`/companies/${encodeURIComponent(company.ticker)}`}>
                            {company.ticker}
                          </Link>
                        </th>
                        <td className="wrap-cell">{company.legal_name}</td>
                        <td>{company.exchange}</td>
                        <td className="num">{count(company.statement_periods)}</td>
                        <DayCell
                          iso={company.latest_period_end}
                          whenMissing={NOT_LOADED}
                        />
                        <DayCell
                          iso={company.latest_filing_date}
                          whenMissing={NOT_LOADED}
                        />
                        <td>
                          {company.next_filing_form ?? (
                            <span className="faint">{NOT_REPORTED}</span>
                          )}
                        </td>
                        <td>
                          {formatDay(company.next_filing_due_by) ?? (
                            <span className="faint">{NOT_REPORTED}</span>
                          )}
                          {company.filing_overdue ? (
                            <>
                              {" "}
                              <span className="pill attention">overdue</span>
                            </>
                          ) : null}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              <p className="scroll-hint">
                If this table is wider than your screen, it scrolls sideways rather than
                the page.
              </p>
            </>
          )
        ) : (
          <div className="panel-body">
            <Trouble error={companies.error} subject="The company list" />
          </div>
        )}
      </div>

      <Disclose brief="Overdue means the due date for the next report has passed without one reaching this database.">
        <p>
          A filer owes a particular form by a particular day — a 10-Q some weeks after the
          quarter it covers, a 10-K further after the year end. The due-by column is that
          deadline, and the pill appears once it is behind us and no such report has been
          loaded here.
        </p>
        <p>
          It is a statement about this database as much as about the filer: a report that
          was filed but has not yet been fetched looks the same from here.{" "}
          <Link href="/data-health">Data health</Link> is where you can see whether the
          job that fetches them has been running.
        </p>
      </Disclose>

      <div className="panel">
        <div className="panel-head">
          <h2>The economy</h2>
          <Link href="/macro">Every series in full</Link>
        </div>
        {macro.ok ? (
          series.length === 0 ? (
            <div className="panel-body">
              <p className="muted">
                The API answered, and the list of economic series it holds is empty. No
                series have been registered in this database yet.
              </p>
            </div>
          ) : (
            <>
              <div className="scroller">
                <table>
                  <caption>
                    Every economic series held, with its latest observation. A series with
                    nothing in it is still listed, so that an absence is visible rather
                    than silent.
                  </caption>
                  <thead>
                    <tr>
                      <th scope="col">Code</th>
                      <th scope="col">Series</th>
                      <th scope="col" className="num">
                        Latest
                      </th>
                      <th scope="col">Value as of</th>
                      <th scope="col">Known as of</th>
                      <th scope="col">Freshness</th>
                    </tr>
                  </thead>
                  <tbody>
                    {series.map((item) => (
                      <tr key={item.code}>
                        <th scope="row">{item.code}</th>
                        <td className="wrap-cell">{item.name}</td>
                        <LatestValueCell series={item} />
                        <DayCell iso={item.latest_as_of} whenMissing={NOT_LOADED} />
                        <DayCell iso={item.latest_known_as_of} whenMissing={NOT_LOADED} />
                        <td>
                          <Freshness series={item} />
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              <p className="scroll-hint">
                If this table is wider than your screen, it scrolls sideways rather than
                the page.
              </p>
            </>
          )
        ) : (
          <div className="panel-body">
            <Trouble error={macro.error} subject="The economic series" />
          </div>
        )}
      </div>

      <Disclose brief="A series with nothing loaded into it says so, and never says zero.">
        <p>
          A zero is a measurement: somebody looked and found none. A blank is the absence
          of one — the load has not run, or the source has not published yet. Treat one as
          the other and the damage is silent, because a zero slipped into an average drags
          it down and nothing on the screen says so.
        </p>
        <p>
          So where this site has no figure it writes <b>{NOT_LOADED}</b> or{" "}
          <b>{NOT_REPORTED}</b>, depending on whose absence it is: ours, or the
          publisher&rsquo;s.
        </p>
      </Disclose>

      <Disclose brief="This site measures and explains. It does not say whether a figure is good.">
        <p>
          It will show a company&rsquo;s profit margin and explain what a margin is. It
          will not tell you whether that margin is good, and it will never suggest buying
          or selling anything. Where a page shows a valuation, that number came from
          assumptions you typed in yourself — change them and the answer changes.
        </p>
        <p>
          Two reasons. Giving investment advice is a regulated activity, and this system is
          deliberately not registered to do it. More importantly, a number presented as a
          verdict stops being questioned — and the entire value of keeping every
          figure&rsquo;s source attached is that you <em>can</em> question it.
        </p>
      </Disclose>

      <div className="source">
        <dl>
          {held.ok ? (
            <>
              <dt>Counted</dt>
              <dd>
                {formatDay(held.value.counted_at) ?? NOT_LOADED}, by the API rather than
                by this page
              </dd>
            </>
          ) : null}
          <dt>Filings</dt>
          <dd>
            the companies endpoint sends no attribution line of its own; the filings
            behind it are the filers&rsquo; own, via SEC EDGAR
          </dd>
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

import type { Metadata } from "next";
import Link from "next/link";

import {
  ApiError,
  ApiTimeout,
  api,
  type CompanySummary,
  failTheBuildInstead,
} from "@/lib/api";
import { SERVICE_IS_SLOW, count, day, isMissing, NOT_REPORTED } from "@/lib/format";

export const metadata: Metadata = {
  title: "Companies",
  description:
    "Every company loaded, with how many reporting periods are held, the period the " +
    "newest figures cover, the day they became public, and whether the next report is " +
    "past its due date.",
};

/**
 * The register. One idea leads the page - that a period end and a filing date are two
 * different dates - because both columns are in the table and a reader who misses the
 * difference will misread every figure on every other page here.
 *
 * `DESIGN.md` §2 caps the lead at four headline figures. This page leads with none: a
 * count of the rows would be a number the API did not send, and AD-3 puts arithmetic on
 * the server. The table is the content.
 */
export default async function CompaniesPage() {
  let companies: CompanySummary[];
  try {
    companies = (await api.companies()).companies;
  } catch (error) {
    failTheBuildInstead(error);
    return <CouldNotLoad error={error} />;
  }

  if (companies.length === 0) {
    return (
      <>
        <Heading />
        <div className="notice">
          <h3>No companies are loaded</h3>
          <p>
            The API answered, and its list is empty. Nothing has failed — there is simply
            nothing here yet. A company appears in this list once the loader has fetched
            at least one of its filings.
          </p>
        </div>
      </>
    );
  }

  return (
    <>
      <Heading />

      <div className="explain">
        <span className="tag">Two dates, and they are not the same</span>
        <p>
          Every row carries a <b>period end</b> and a <b>filed on</b> date. The period end
          is the last day of the stretch of time the figures describe. The filed on date
          is the day those figures first became public — usually weeks later.
        </p>
        <p>
          The gap between them is the reason both dates sit beside every number on this
          site. Anything that claims to know a company&rsquo;s December figures in
          December is using something nobody could have known at the time.
        </p>
      </div>

      <details className="more">
        <summary>What the other columns mean</summary>
        <div>
          <p>
            <b>Periods</b> — how many distinct reporting periods this system holds
            statements for. A company that files quarterly adds about four a year, so a
            larger number means a longer run of history is available, not a larger
            company.
          </p>
          <p>
            <b>Next report</b> — the form that should come next, and the last day the SEC
            allows for it. That date is worked out from the fiscal year end and the latest
            deadline any filer category gets, not from the company&rsquo;s own announced
            calendar.
          </p>
          <p>
            <b>Past due</b> — that day has gone and this system does not hold the report.
            It is a freshness flag on this dataset. It can mean the filing is late, and it
            can equally mean the filing exists and our copy has not caught up.{" "}
            <b>Not due</b> means the day has not arrived yet.
          </p>
        </div>
      </details>

      <div className="scroller">
        <table>
          <caption>
            Every company loaded, and how much of each one is held. Each ticker opens that
            company&rsquo;s figures.
          </caption>
          <thead>
            <tr>
              <th scope="col">Ticker</th>
              <th scope="col">Company</th>
              <th scope="col">Exchange</th>
              <th scope="col" className="num">
                Periods
              </th>
              <th scope="col">Period end</th>
              <th scope="col">Filed on</th>
              <th scope="col">Next report</th>
              <th scope="col">Status</th>
            </tr>
          </thead>
          <tbody>
            {companies.map((company) => (
              <tr key={company.ticker}>
                {/* The ticker labels the row, so it is a row header - `DESIGN.md` §8. */}
                <th scope="row">
                  <Link href={`/companies/${encodeURIComponent(company.ticker)}`}>
                    {company.ticker}
                  </Link>
                </th>
                <td>{company.legal_name}</td>
                <td>{company.exchange}</td>
                <td className="num">{count(company.statement_periods)}</td>
                <td>{day(company.latest_period_end)}</td>
                <td>{day(company.latest_filing_date)}</td>
                <td>
                  {isMissing(company.next_filing_form) ? NOT_REPORTED : company.next_filing_form}
                  {isMissing(company.next_filing_due_by)
                    ? ""
                    : `, due ${day(company.next_filing_due_by)}`}
                </td>
                <td>
                  {company.filing_overdue ? (
                    <span className="pill attention">Past due</span>
                  ) : (
                    <span className="pill ok">Not due</span>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {/* The same conditional wording as the valuation tables. This one sits at top
          level, where the container does track the viewport, so a flat assertion would
          in fact be true here - but one sentence that holds everywhere beats two that
          each have to be re-checked against their own container. */}
      <p className="scroll-hint">
        If this table is wider than your screen, it scrolls sideways rather than the page.
      </p>

      <div className="source">
        <dl>
          <dt>What each row is about</dt>
          <dd>the period ending on that row&rsquo;s own latest period end</dd>
          <dt>When it became knowable</dt>
          <dd>that row&rsquo;s own filed on date</dd>
          <dt>Attribution</dt>
          <dd>
            This endpoint returns no attribution string of its own, so none is shown here
            rather than one being invented. Every figure on a company&rsquo;s own page
            carries the attribution the API sent with it, word for word.
          </dd>
        </dl>
      </div>
    </>
  );
}

function Heading() {
  return (
    <>
      <h1>Companies</h1>
      <p className="lede">
        Every company whose filings are loaded here, with how much of each one is held and
        how current it is.
      </p>
    </>
  );
}

/**
 * The failed state. `DESIGN.md` §7: say what happened and what to do — a blank page or a
 * bare "error" tells a reader nothing about whether to wait, reload, or give up.
 */
function CouldNotLoad({ error }: { error: unknown }) {
  const status = error instanceof ApiError ? error.status : null;

  if (error instanceof ApiTimeout) {
    return (
      <>
        <Heading />
        {/* `.notice`, not `.notice bad`. Nothing is broken, and painting a slow answer
            red tells the reader to go looking for a fault that is not there. */}
        <div className="notice">
          <h3>This is taking longer than the page waits</h3>
          <p>{SERVICE_IS_SLOW}</p>
          <p>Reload the page and the list should appear.</p>
        </div>
      </>
    );
  }

  return (
    <>
      <Heading />
      <div className="notice bad">
        <h3>The list could not be loaded</h3>
        <p>
          The request for the company list did not come back
          {status === null ? " at all" : ` — the API answered ${status}`}. No figures are
          shown, because showing a partial list would be worse than showing none.
        </p>
        <p>
          Nothing is wrong with the data itself. Reload the page; if it keeps happening,
          the API is not answering and the <Link href="/data-health">data health</Link>{" "}
          page is where that shows up.
        </p>
      </div>
    </>
  );
}

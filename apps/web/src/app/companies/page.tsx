import type { Metadata } from "next";
import Link from "next/link";

import { Disclose } from "@/components/disclose";
import {
  ApiError,
  ApiTimeout,
  api,
  type CompanySummary,
  failTheBuildInstead,
} from "@/lib/api";
import { NOT_LOADED, SERVICE_IS_SLOW, count, day, isMissing } from "@/lib/format";

import { NumCell, ScrollHint, WordCell } from "./_ui";

export const metadata: Metadata = {
  title: "Stocks",
  description:
    "Every company loaded, with how many reporting periods are held, the period the " +
    "newest figures cover, the day they became public, and whether the next report is " +
    "past its due date.",
};

/**
 * The screener: every company held, one row each, ticker first.
 *
 * The table is the page. `DESIGN.md` §2 puts data first and there is no headline figure
 * to put above it - a count of these rows would be a number the API did not send, and
 * AD-3 puts arithmetic on the server. What each column means is explained below the
 * table, one disclosure per idea, so a reader who already knows can scan and leave.
 */
export default async function StocksPage() {
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
          <h2>No companies are loaded</h2>
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

      <div className="scroller">
        <table>
          {/* Short on purpose. A `<caption>` is as wide as its table, and this table is
              851px wide against a 288px phone - so a long caption runs off the right of
              the screen and has to be scrolled to, which a caption exists to avoid. The
              longer description is the `.page-note` above. */}
          <caption>Every company loaded, and how much of each.</caption>
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
                {/* The ticker labels the row, so it is a row header - `DESIGN.md` §9. */}
                <th scope="row">
                  <Link href={`/companies/${encodeURIComponent(company.ticker)}`}>
                    {company.ticker}
                  </Link>
                </th>
                {/* The name gets `.nowrap` too. This table is wider than a phone and
                    scrolls sideways either way, so letting the longest legal name wrap
                    buys no width back - it only turns a 36px row into a 73px one and
                    takes the even row rhythm a screener is read by with it. */}
                <td className="nowrap">{company.legal_name}</td>
                <WordCell text={exchangeOf(company)} nowrap />
                <NumCell text={count(company.statement_periods)} />
                <WordCell text={day(company.latest_period_end)} nowrap />
                <WordCell text={day(company.latest_filing_date)} nowrap />
                <WordCell text={nextReport(company)} nowrap />
                <td className="nowrap">
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
      <ScrollHint />

      <Disclose brief="A period end and a filed on date are two different days, and the gap between them is the point.">
        <p>
          Every row carries a <b>period end</b> and a <b>filed on</b> date. The period end
          is the last day of the stretch of time the figures describe. The filed on date
          is the day those figures first became public — usually weeks later.
        </p>
        <p>
          That gap is the reason both dates sit beside every number on this site. Anything
          that claims to know a company&rsquo;s December figures in December is using
          something nobody could have known at the time.
        </p>
      </Disclose>

      <Disclose brief="Periods counts reporting periods held, not the size of the company.">
        <p>
          How many distinct reporting periods this system holds statements for. A company
          that files quarterly adds about four a year, so a larger number means a longer
          run of history is available here — not a larger company.
        </p>
      </Disclose>

      <Disclose brief="Next report is the form the SEC expects next, and the last day it allows for it.">
        <p>
          The form that should come next, and the last day the SEC allows for it. That
          date is worked out from the fiscal year end and the latest deadline any filer
          category gets — not from the company&rsquo;s own announced calendar, which this
          system does not hold.
        </p>
      </Disclose>

      <Disclose brief="Past due is a freshness flag on this dataset, not an accusation about the filer.">
        <p>
          <b>Past due</b> means that day has gone and this system does not hold the
          report. It can mean the filing is late, and it can equally mean the filing
          exists and our copy has not caught up. <b>Not due</b> means the day has not
          arrived yet.
        </p>
      </Disclose>

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
      <h1>Stocks</h1>
      <p className="page-note">
        Every company whose filings are loaded here, with how much of each one is held and
        how current it is.
      </p>
    </>
  );
}

/** The exchange, or the phrase for the kind of absence it is. Never an empty cell. */
function exchangeOf(company: CompanySummary): string {
  return isMissing(company.exchange) ? NOT_LOADED : company.exchange;
}

/**
 * "10-K, due 29 Dec 2026". Both halves come from the API; neither is worked out here.
 * When there is no form there is nothing to be due, so the whole cell is the absence.
 */
function nextReport(company: CompanySummary): string {
  if (isMissing(company.next_filing_form)) return NOT_LOADED;
  const due = company.next_filing_due_by;
  return isMissing(due)
    ? (company.next_filing_form as string)
    : `${company.next_filing_form}, due ${day(due)}`;
}

/**
 * The failed state. `DESIGN.md` §8: say what happened and what to do — a blank page or a
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
          <h2>This is taking longer than the page waits</h2>
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
        <h2>The list could not be loaded</h2>
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

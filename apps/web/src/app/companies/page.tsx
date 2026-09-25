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
import { SERVICE_IS_SLOW } from "@/lib/format";

import { Screener } from "./_screener";

export const metadata: Metadata = {
  title: "Stocks",
  description:
    "Every company loaded, sortable by any column and filterable by ticker or name, " +
    "with how many reporting periods are held, the period the newest figures cover, " +
    "the day they became public, and whether the next report is past its due date.",
};

/**
 * The screener: every company held, one row each, ticker first.
 *
 * The table is the page. `DESIGN.md` §2 puts data first and there is no headline figure
 * to put above it - a count of these rows would be a number the API did not send, and
 * AD-3 puts arithmetic on the server. What each column means is explained below the
 * table, one disclosure per idea, so a reader who already knows can scan and leave.
 *
 * The fetch stays here, in the server component, and the rows are handed to `<Screener>`
 * as a prop. That is what keeps the page working with JavaScript off: a client component
 * still renders on the server, so the first byte of HTML carries the whole table already
 * sorted, and hydration only wakes up the filter box and the column buttons. A screener
 * that fetched in the browser would show an empty table until it did not.
 *
 * Every column comes from the one `/v1/public/companies` call. Nothing here fans out per
 * row: a market figure beside each company would cost a request per company, which is a
 * cost the reader pays and the table does not need.
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

      <Screener companies={companies} />

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
          <dt>Ordering</dt>
          <dd>
            a column is sorted by the field the API sent for it, and nothing on this page
            is worked out from two of them
          </dd>
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

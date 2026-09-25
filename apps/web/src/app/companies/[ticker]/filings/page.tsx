import type { Metadata } from "next";

import { Disclose } from "@/components/disclose";
import {
  api,
  failTheBuildInstead,
  type DividendHistory,
  type FilingHistory,
} from "@/lib/api";
import {
  count,
  day,
  direction,
  NOT_REPORTED,
  plain,
  signedPercent,
} from "@/lib/format";

import { Metric, Panel, ScrollHint } from "../../_ui";
import { CompanyProblem } from "../_states";

interface PageProps {
  params: Promise<{ ticker: string }>;
}

export async function generateMetadata({ params }: PageProps): Promise<Metadata> {
  const { ticker } = await params;
  return {
    title: `${decodeURIComponent(ticker).toUpperCase()} filings`,
    description:
      "Every filing held for one company — form, period, filed date, the day it became " +
      "knowable and its accession number — and every cash dividend it has paid.",
  };
}

/**
 * Filings — the paper trail, and the dividends.
 *
 * The two belong on one page because they are the same kind of fact: a dated event that
 * became knowable on a particular day, rather than a measurement of a period. Every
 * other tab shows figures *from* filings; this is the list of the filings themselves,
 * and it is where the accession number lives — the identifier that makes a figure on the
 * Financials tab checkable against the document at the SEC rather than taken on trust.
 *
 * Nothing here is computed. The per-year dividend totals, their counts and their moves
 * on the year are all the API's own, including the years it flags as a fall. A page that
 * added up ninety-two payments to get a year would be doing arithmetic (AD-3) and would
 * also get a different answer, because the API knows which of them the year contains and
 * a naive sum over ex-dates does not.
 */
export default async function FilingsPage({ params }: PageProps) {
  const { ticker: raw } = await params;
  const ticker = decodeURIComponent(raw);

  let filings: FilingHistory | null = null;
  let filingsError: unknown = null;
  try {
    filings = await api.filings(ticker);
  } catch (error) {
    failTheBuildInstead(error);
    filingsError = error;
  }

  let dividends: DividendHistory | null = null;
  let dividendsError: unknown = null;
  try {
    dividends = await api.dividends(ticker);
  } catch (error) {
    failTheBuildInstead(error);
    dividendsError = error;
  }

  return (
    <>
      <h2>Filings</h2>

      {filingsError !== null ? (
        <CompanyProblem ticker={ticker} error={filingsError} withHeading={false} />
      ) : filings === null || filings.filings.length === 0 ? (
        <div className="notice">
          <h3>No filing is held for this company</h3>
          <p>
            Nothing has been loaded from EDGAR for {ticker} yet. That is an absence on
            this side rather than a company that has filed nothing.
          </p>
        </div>
      ) : (
        <Panel title="Every filing held">
          <div className="scroller">
            <table>
              <caption>
                Newest first. The accession number opens the filing at the SEC, so any
                figure on the Financials tab can be checked against the document it was
                read from.
              </caption>
              <thead>
                <tr>
                  <th scope="col">Form</th>
                  <th scope="col">Period ended</th>
                  <th scope="col">Filed</th>
                  <th scope="col">Knowable from</th>
                  <th scope="col" className="num">
                    Statement versions
                  </th>
                  <th scope="col">Accession</th>
                </tr>
              </thead>
              <tbody>
                {filings.filings.map((filing) => (
                  <tr key={`${filing.accession_no}-${filing.filing_date}`}>
                    <th scope="row">{filing.filing_type}</th>
                    <td className="nowrap">{day(filing.period_end)}</td>
                    <td className="nowrap">{day(filing.filing_date)}</td>
                    <td className="nowrap">{day(filing.known_as_of)}</td>
                    <td className="num">{count(filing.statement_versions)}</td>
                    <td className="nowrap">
                      {filing.filing_url === null ? (
                        filing.accession_no
                      ) : (
                        <a
                          href={filing.filing_url}
                          rel="noreferrer nofollow"
                          target="_blank"
                        >
                          {filing.accession_no}
                        </a>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <ScrollHint />
        </Panel>
      )}

      <Disclose brief="A filing has three dates on it and they are not interchangeable.">
        <p>
          The <b>period ended</b> is what the filing is about — the quarter or year it
          reports. The <b>filed</b> date is when it went to the SEC. <b>Knowable from</b>
          {" "}is the day it became public, which is the only one of the three that says
          when somebody could have acted on what is inside it. A 10-K for a year that
          ended in September and became public at the end of October tells you nothing
          about October until the end of October.
        </p>
      </Disclose>

      <Disclose brief="A statement version is one reading of one line, and a filing can produce several.">
        <p>
          A 10-Q carrying four quarters of comparatives produces four versions: one per
          period it restates or confirms. That count is why the same fiscal year can read
          differently depending on which day you look — the Financials tab shows both
          readings side by side under &ldquo;What changed after it was published&rdquo;.
        </p>
      </Disclose>

      <h2>Dividends</h2>

      {dividendsError !== null ? (
        <CompanyProblem ticker={ticker} error={dividendsError} withHeading={false} />
      ) : dividends === null ? (
        <div className="notice">
          <h3>The dividend history did not arrive</h3>
          <p>
            Nothing is shown rather than a partial history, because a dividend record
            with payments missing from it reads as a company that paid less than it did.
          </p>
        </div>
      ) : !dividends.pays ? (
        <div className="notice">
          <h3>{dividends.legal_name} has paid no cash dividend</h3>
          <p>
            That is an answer rather than an absence: no payment is held because none has
            been made, not because none has been loaded. Nothing is shown below in place
            of it.
          </p>
        </div>
      ) : (
        <DividendSection data={dividends} />
      )}

      <div className="source">
        <dl>
          {filings === null ? null : (
            <>
              <dt>Filings as known on</dt>
              <dd>{day(filings.as_known_on)}</dd>
              <dt>Filing attribution</dt>
              <dd>{filings.attribution}</dd>
            </>
          )}
          {dividends === null ? null : (
            <>
              <dt>Dividends as known on</dt>
              <dd>{day(dividends.as_known_on)}</dd>
              <dt>Currency</dt>
              <dd>{dividends.currency}</dd>
              <dt>Dividend attribution</dt>
              <dd>{dividends.attribution}</dd>
            </>
          )}
        </dl>
      </div>
    </>
  );
}

/**
 * The dividend record: the latest payment, the API's per-year totals, and every payment.
 *
 * Amounts are written with `plain(value, 6)` rather than `money`, and that is not a
 * style choice. `money` is fixed at two decimal places, and Apple's May 1987 dividend
 * restated onto today's share count is 0.000536 — which `money` renders as `$0.00`, a
 * zero standing in front of a real payment. Six places is what the API sends, trailing
 * zeros and all, and `DESIGN.md` §6 says a figure the system was *given* is printed
 * verbatim. The currency moves into the column heading instead, where it is stated once.
 */
function DividendSection({ data }: { data: DividendHistory }) {
  // Newest first, to match the filings table above. Reversing a list the API ordered is
  // selection, not derivation - no figure changes.
  const years = [...data.years].reverse();
  const payments = [...data.dividends].reverse();
  const cutYears = data.cuts.map((cut) => cut.year);
  const partOfAYear = new Set(data.years.filter((year) => year.partial).map((y) => y.year));

  return (
    <>
      {data.latest === null ? (
        <div className="notice">
          <h3>No latest payment is held</h3>
          <p>
            The company is recorded as paying a dividend, but no most-recent payment came
            back with the history. The table below is what is held.
          </p>
        </div>
      ) : (
        <div className="metrics">
          <Metric name="Latest ex-date" value={day(data.latest.ex_date)} />
          <Metric
            name={`Cash amount (${data.latest.currency})`}
            value={plain(data.latest.cash_amount, 6)}
          />
          <Metric
            name="In today's shares"
            value={plain(data.latest.amount_in_todays_shares, 6)}
          />
          <Metric name="Knowable from" value={day(data.latest.known_as_of)} />
        </div>
      )}

      <Panel title="By year">
        <div className="scroller">
          <table>
            <caption>
              The API&rsquo;s own per-year totals and its own move on the year, newest
              first.
              {cutYears.length === 0
                ? " It flags no year in which the total fell."
                : ` It flags these years as a fall on the year: ${cutYears.join(", ")}.`}
            </caption>
            <thead>
              <tr>
                <th scope="col">Year</th>
                <th scope="col" className="num">
                  Total per share ({data.currency})
                </th>
                <th scope="col" className="num">
                  Payments
                </th>
                <th scope="col" className="num">
                  Change on the year
                </th>
                <th scope="col">Coverage</th>
              </tr>
            </thead>
            <tbody>
              {years.map((year) => {
                const moved = signedPercent(year.change_yoy);
                const way = direction(year.change_yoy);
                return (
                  <tr key={year.year}>
                    <th scope="row">{year.year}</th>
                    <td className="num">{plain(year.total, 6)}</td>
                    <td className="num">{count(year.count)}</td>
                    {moved === null || way === null ? (
                      // The first year held has no year before it, so there is no move.
                      // Not a flat one: `.delta.flat` would assert the total did not
                      // change, which is a different claim from there being nothing to
                      // change from.
                      <td className="num absent">{NOT_REPORTED}</td>
                    ) : (
                      <td className="num">
                        <span className={`delta ${way}`}>{moved}</span>
                      </td>
                    )}
                    <td className="nowrap">
                      {partOfAYear.has(year.year) ? "part year" : "full year"}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
        <ScrollHint />
      </Panel>

      <Panel title="Every payment">
        <div className="scroller">
          <table>
            <caption>
              Every cash dividend held, newest first, each with the day it became
              knowable.
            </caption>
            <thead>
              <tr>
                <th scope="col">Ex-date</th>
                <th scope="col" className="num">
                  Cash amount ({data.currency})
                </th>
                <th scope="col" className="num">
                  In today&rsquo;s shares
                </th>
                <th scope="col">Knowable from</th>
              </tr>
            </thead>
            <tbody>
              {payments.map((payment) => (
                <tr key={`${payment.ex_date}-${payment.cash_amount}`}>
                  <th scope="row" className="nowrap">
                    {day(payment.ex_date)}
                  </th>
                  <td className="num">{plain(payment.cash_amount, 6)}</td>
                  <td className="num">
                    {plain(payment.amount_in_todays_shares, 6)}
                  </td>
                  <td className="nowrap">{day(payment.known_as_of)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <ScrollHint />
      </Panel>

      <Disclose brief="The same payment is written twice because a share is not the same size as it was.">
        <p>
          <b>Cash amount</b> is what was declared per share on the day.{" "}
          <b>In today&rsquo;s shares</b> is that same payment restated onto the current
          share count. Where a company has split its shares since, the two columns
          diverge — one share then is several shares now, so the payment per share now is
          the smaller figure. It is the same adjustment that keeps a price chart from
          showing a cliff where a split was.
        </p>
        <p>
          Both are the API&rsquo;s. Neither is more correct than the other: the first
          answers what a holder received, the second answers what that payment is worth
          per share you could buy now.
        </p>
      </Disclose>

      <Disclose brief="An ex-date is the day the payment stops travelling with the share.">
        <p>
          Buy on or after the ex-date and the seller keeps that dividend, not you. It is
          the date the record is keyed on here because it is the one a price reacts to —
          a share usually opens lower on its ex-date by roughly the payment, which is not
          a fall in the company&rsquo;s value but the payment leaving it.
        </p>
      </Disclose>
    </>
  );
}

import type { Metadata } from "next";

import { Disclose } from "@/components/disclose";
import {
  ApiError,
  api,
  failTheBuildInstead,
  type Ratios,
  type Statements,
} from "@/lib/api";
import { count, day } from "@/lib/format";

import { Panel, ScrollHint } from "../../_ui";
import { FigureTable, RATIO_GROUPS, reported } from "../_figures";
import { CompanyProblem } from "../_states";
import {
  AbsentLines,
  ProvenanceTable,
  RestatementTable,
  SECTIONS,
  StatementTable,
  hasRestatement,
  otherKeys,
  restatedRows,
  splitSection,
} from "./_lines";

interface PageProps {
  params: Promise<{ ticker: string }>;
  searchParams: Promise<Record<string, string | string[] | undefined>>;
}

export async function generateMetadata({ params }: PageProps): Promise<Metadata> {
  const { ticker } = await params;
  return {
    title: `${decodeURIComponent(ticker).toUpperCase()} financials`,
    description:
      "The income statement, balance sheet and cash flow as filed — line items down, " +
      "fiscal years across — with the filing behind every column and every figure a " +
      "later filing changed.",
  };
}

/** A query value the browser may have sent more than once. The first wins. */
function first(value: string | string[] | undefined): string | undefined {
  return Array.isArray(value) ? value[0] : value;
}

/**
 * How many fiscal periods the table shows.
 *
 * Ten by default rather than everything, for one concrete reason: `globals.css` styles a
 * row label `position: static`, so the line-item column scrolls away with the rest of
 * the table. At twenty columns a reader who has scrolled to FY2008 can no longer see
 * which line they are on.
 *
 * Measured at a 1280px viewport, a panel gives a table 1007px: ten periods and the
 * change column want about 1250, so it still scrolls a little, and five fit outright.
 * Everything held is one click away and named. This default is standing in for a sticky
 * first column, which the stylesheet has no class for - see the report note.
 */
const SPANS = [
  { value: "5", label: "5 periods", take: 5 },
  { value: "10", label: "10 periods", take: 10 },
  { value: "all", label: "everything held", take: Number.POSITIVE_INFINITY },
];
const DEFAULT_SPAN = SPANS[1];

/**
 * Financials — the statements as filed.
 *
 * Line items down, fiscal periods across, newest first. This is the table a stock
 * research site exists for, and until now the app has been showing ratios worked out
 * *from* these lines while never once showing the lines.
 *
 * Two things make it more than a grid of numbers, and both come from the schema rather
 * than from the layout:
 *
 * **A column is a vintage as well as a period.** Every figure carries its own
 * `known_as_of`, so `?as_known_on=` re-cuts every period as it stood on a past day.
 * Apple's FY2018 current liabilities read 116,866,000,000 on 1 Dec 2018 and read
 * 115,929,000,000 today. Both are true. They answer different questions, and the form
 * under the provenance table is how a reader asks the second one.
 *
 * **An absence says which kind it is.** `not_in_filing` is the filer's and is not a
 * fault; `no_mapping` is ours. A line no shown filing mentions at all is not drawn -
 * twenty-eight rows of "not reported" on a bank is exactly what `DESIGN.md` §6 forbids -
 * while a line a filing carried and left empty keeps its row and says so.
 *
 * The route reads `searchParams` and is therefore rendered per request rather than
 * prerendered. That is the trade `/valuation` already makes for the same reason: the
 * view is in the URL, so it can be linked, reloaded and sent to somebody else.
 */
export default async function FinancialsPage({ params, searchParams }: PageProps) {
  const { ticker: raw } = await params;
  const ticker = decodeURIComponent(raw);
  const query = await searchParams;

  const vintage = (first(query.as_known_on) ?? "").trim();
  const span = SPANS.find((option) => option.value === first(query.years)) ?? DEFAULT_SPAN;
  const base = `/companies/${encodeURIComponent(ticker)}/financials`;

  /** A link to this page with one control changed and the other kept. */
  const viewHref = (years: string, asKnownOn: string) => {
    const parts: string[] = [];
    if (years !== DEFAULT_SPAN.value) parts.push(`years=${encodeURIComponent(years)}`);
    if (asKnownOn) parts.push(`as_known_on=${encodeURIComponent(asKnownOn)}`);
    return parts.length === 0 ? base : `${base}?${parts.join("&")}`;
  };

  let statements: Statements | null = null;
  let statementsError: unknown = null;
  try {
    statements = await api.statements(ticker, vintage ? { asKnownOn: vintage } : {});
  } catch (error) {
    failTheBuildInstead(error);
    statementsError = error;
  }

  // Fetched by the shared layout for the header already, so this is served from the
  // request's own fetch cache rather than going out again.
  let ratios: Ratios | null = null;
  let ratiosError: unknown = null;
  try {
    ratios = await api.ratios(ticker);
  } catch (error) {
    failTheBuildInstead(error);
    ratiosError = error;
  }

  const periods = statements ? statements.periods.slice(0, span.take) : [];
  const sections = SECTIONS.map((section) => ({
    section,
    rows: splitSection(section.keys, periods),
  }));
  const spare = splitSection(otherKeys(periods), periods);
  const restated = restatedRows(periods, [
    ...sections.flatMap((entry) => entry.rows.live),
    ...spare.live,
  ]);

  // A date the API would not take is the reader's typo, not a broken service, and it
  // must not read as one. 404 is excluded because that is a ticker nobody holds, which
  // the shared error states already say better than this notice could.
  const rejectedVintage =
    vintage !== "" &&
    statementsError instanceof ApiError &&
    statementsError.status >= 400 &&
    statementsError.status < 500 &&
    statementsError.status !== 404;

  return (
    <>
      {vintage && statements ? (
        <div className="notice">
          <h2>These are the figures as they stood on {day(statements.as_known_on)}</h2>
          <p>
            Every column below is cut at that day: the reading each period carried then,
            not the reading it carries now, and no period filed after it. A restatement
            made later has not happened yet on this page.
          </p>
          <p>
            <a href={base}>Back to the figures as known today</a>.
          </p>
        </div>
      ) : null}

      <h2>Statements as filed</h2>

      {statementsError !== null ? (
        rejectedVintage ? (
          <div className="notice">
            <h3>That date was not accepted</h3>
            <p>
              The API would not read <b>{vintage}</b> as a day to cut the figures at. It
              takes a calendar date written as YYYY-MM-DD, such as 2018-12-01.
            </p>
            <p>
              <a href={base}>Show the figures as known today</a>, then try again from the
              form under the statements.
            </p>
          </div>
        ) : (
          <CompanyProblem ticker={ticker} error={statementsError} withHeading={false} />
        )
      ) : statements === null || periods.length === 0 ? (
        <div className="notice">
          <h3>No period is held at this vintage</h3>
          <p>
            {vintage
              ? `Nothing had been filed for ${ticker} on or before ${day(vintage)}, so there is no column to draw.`
              : `No fiscal-year statement is held for ${ticker}. The ratios below are worked out from statement lines, so if they are present this is a gap in the statement loader rather than in the filings.`}
          </p>
          {vintage ? (
            <p>
              <a href={base}>The figures as known today</a>.
            </p>
          ) : null}
        </div>
      ) : (
        <>
          <p className="hint">
            Showing{" "}
            {SPANS.map((option, index) => (
              <span key={option.value}>
                {index === 0 ? null : " · "}
                {option.value === span.value ? (
                  <b>{option.label}</b>
                ) : (
                  <a href={viewHref(option.value, vintage)}>{option.label}</a>
                )}
              </span>
            ))}{" "}
            of the {count(statements.periods.length)} held for {statements.legal_name},
            newest first.
          </p>

          {sections.map(({ section, rows }) => (
            <Panel key={section.title} title={section.title}>
              {rows.live.length === 0 &&
              rows.ours.length === 0 &&
              rows.filers.length === 0 ? (
                <div className="panel-body">
                  <div className="notice">
                    <p>{section.absent}</p>
                  </div>
                </div>
              ) : (
                <>
                  {rows.live.length === 0 ? null : (
                    <>
                      <div className="scroller">
                        <StatementTable
                          caption={section.caption}
                          keys={rows.live}
                          periods={periods}
                          restatementLegend={hasRestatement(rows.live, periods)}
                        />
                      </div>
                      <ScrollHint />
                    </>
                  )}
                  <AbsentLines rows={rows} />
                </>
              )}
            </Panel>
          ))}

          {spare.live.length === 0 && spare.ours.length === 0 && spare.filers.length === 0 ? null : (
            <Panel title="Other reported lines">
              {spare.live.length === 0 ? null : (
                <>
                  <div className="scroller">
                    <StatementTable
                      caption={
                        "Lines these filings carry that this page does not yet place on " +
                        "a statement. They are shown rather than dropped."
                      }
                      keys={spare.live}
                      periods={periods}
                      restatementLegend={hasRestatement(spare.live, periods)}
                    />
                  </div>
                  <ScrollHint />
                </>
              )}
              <AbsentLines rows={spare} />
            </Panel>
          )}

          <Disclose brief="A blank line and a zero are different facts, and this table never writes one as the other.">
            <p>
              Where a filing carried a line and left it empty, the cell says{" "}
              <b>not reported</b> — the filer did not state it, which is their choice and
              not a fault. Where a filing has a tag that has not been mapped to one of
              these lines yet, it says <b>not loaded yet</b>, because that absence is
              ours rather than theirs.
            </p>
            <p>
              A line no filing shown here mentions at all is not drawn, and a line every
              shown period left empty is named in a sentence under the table rather than
              given a row of its own. A bank has no cost of revenue and no gross profit,
              and eighty empty cells would say that something had gone wrong when what
              happened is that banks account differently. So the set of rows changes with
              the company, and changes again with how many periods are shown.
            </p>
          </Disclose>

          <Disclose brief="FVTPL and FVOCI are two ways a bank can hold a security and have its value move.">
            <p>
              <b>FVTPL</b> is fair value through profit or loss: the security is marked to
              its market price and the movement goes through the income statement.{" "}
              <b>FVOCI</b> is fair value through other comprehensive income: it is marked
              the same way, but the movement sits in equity until the security is sold.{" "}
              <b>Amortised cost</b> is neither — the security is carried at what was paid
              for it, adjusted over its life, and market movement does not appear at all.
            </p>
            <p>
              They are separate lines because they are separate measurements of the same
              kind of thing, and a filer reports them apart.
            </p>
          </Disclose>

          <Disclose brief="The change column is a change on the year, and it arrives already worked out.">
            <p>
              It compares the newest period shown with the one before it, and the API
              sends it: nothing on this page divides one cell by another. That matters
              more than it sounds, because two columns can come from filings published
              years apart — a figure restated in 2026 beside one untouched since 2019 —
              and a move read off the screen would be comparing two vintages without
              saying so.
            </p>
          </Disclose>

          <h2>Where each column came from</h2>

          <Panel title="The filing behind each period">
            <div className="scroller">
              <ProvenanceTable periods={periods} />
            </div>
            <ScrollHint />
          </Panel>

          <Panel title="Read the figures as they stood on a past day">
            <div className="panel-body">
              <form method="get" action={base}>
                <div className="grid">
                  <div>
                    <label htmlFor="as_known_on">Figures as known on</label>
                    <input
                      id="as_known_on"
                      name="as_known_on"
                      type="text"
                      inputMode="numeric"
                      autoComplete="off"
                      placeholder="YYYY-MM-DD"
                      pattern="\d{4}-\d{2}-\d{2}"
                      defaultValue={vintage}
                    />
                    <div className="faint">
                      <small>
                        a calendar date, so 2018-12-01 — leave it empty for the figures
                        as they stand today
                      </small>
                    </div>
                  </div>
                </div>
                {span.value === DEFAULT_SPAN.value ? null : (
                  <input type="hidden" name="years" value={span.value} />
                )}
                <p>
                  <button type="submit">Show that day</button>
                </p>
              </form>
            </div>
          </Panel>

          <Disclose brief="A period and a vintage are two different dates, and this is the page where the difference bites.">
            <p>
              A period is what a figure is <i>about</i> — the twelve months
              Apple&rsquo;s FY2018 covers. A vintage is when anybody could <i>know</i> it,
              which is the day the filing carrying it became public. The same period has
              more than one vintage whenever a later filing restates it: Apple&rsquo;s
              FY2018 current liabilities read 116,866,000,000 to anybody looking on 1 Dec
              2018, and read 115,929,000,000 to anybody looking now.
            </p>
            <p>
              So &ldquo;FY2018&rdquo; on its own does not identify a number. The column
              head gives the period, this table gives the vintage, and the form above
              moves the whole page to a different one.
            </p>
          </Disclose>

          <h2>What changed after it was published</h2>

          {restated.length === 0 ? (
            <div className="notice">
              <h3>No figure shown here has been restated</h3>
              <p>
                Every line in the periods above still reads as it did in the filing that
                first carried it. Widening the table to more periods may turn some up — an
                older period has had longer to be revisited.
              </p>
            </div>
          ) : (
            <Panel title="Restatements">
              <div className="scroller">
                <RestatementTable rows={restated} />
              </div>
              <ScrollHint />
            </Panel>
          )}

          <Disclose brief="A restatement changes what a past period says, without changing the past period.">
            <p>
              A filer who finds an error, or who reclassifies a line, republishes the
              affected period inside a later filing. The period is unchanged — FY2018 is
              still the same twelve months — but the figure attached to it is not, and the
              old figure does not stop having been the one everybody acted on at the time.
            </p>
            <p>
              The vintage column says which reading this is: version 1 is the first
              publication, version 2 the first revision, and so on.
            </p>
          </Disclose>
        </>
      )}

      {ratiosError !== null || ratios === null ? (
        <>
          <h2>Ratios</h2>
          <CompanyProblem
            ticker={ticker}
            error={ratiosError}
            withHeading={false}
          />
        </>
      ) : (
        <>
          <h2>
            Ratios from the {ratios.filing_type} for {ratios.period_label}
          </h2>

          <div className="grid">
            {RATIO_GROUPS.map((group) => {
              const values = ratios.ratios;
              const anyReported = group.figures.some((spec) => reported(spec, values));
              return (
                <Panel key={group.title} title={group.title}>
                  {anyReported ? (
                    <>
                      <div className="scroller">
                        <FigureTable
                          caption={group.caption}
                          figures={group.figures}
                          values={values}
                          currency={ratios.currency}
                        />
                      </div>
                      <ScrollHint />
                    </>
                  ) : (
                    <div className="panel-body">
                      <div className="notice">
                        {group.absent ?? (
                          <p>
                            This filing does not carry the lines these figures are worked
                            out from, so none of them is shown. Nothing has been estimated
                            in their place and no zero is standing in for a blank.
                          </p>
                        )}
                      </div>
                    </div>
                  )}
                </Panel>
              );
            })}
          </div>

          <h3>What each group measures</h3>

          {RATIO_GROUPS.map((group) => (
            <Disclose key={group.title} brief={`${group.title} — ${group.brief}`}>
              {group.detail}
            </Disclose>
          ))}
        </>
      )}

      <div className="source">
        <dl>
          {statements === null ? null : (
            <>
              <dt>Statements as known on</dt>
              <dd>{day(statements.as_known_on)}</dd>
              <dt>Periods held</dt>
              <dd>
                {count(statements.periods.length)}, {span.label} shown
              </dd>
              <dt>Statement attribution</dt>
              <dd>{statements.attribution}</dd>
              <dt>CIK</dt>
              <dd>{statements.cik}</dd>
            </>
          )}
          {ratios === null ? null : (
            <>
              <dt>Ratio period</dt>
              <dd>
                {ratios.period_label}, ended {day(ratios.period_end)}
              </dd>
              <dt>Ratio filing</dt>
              <dd>{ratios.filing_type}</dd>
              <dt>Became public</dt>
              <dd>{day(ratios.known_as_of)}</dd>
              <dt>Currency</dt>
              <dd>{ratios.currency}</dd>
              <dt>Ratio attribution</dt>
              <dd>{ratios.attribution}</dd>
              {ratios.price === null ? null : (
                <>
                  <dt>Price behind every multiple</dt>
                  <dd>
                    close of {day(ratios.price.date)}, knowable{" "}
                    {day(ratios.price.known_as_of)}
                  </dd>
                  <dt>Price attribution</dt>
                  <dd>{ratios.price.attribution}</dd>
                </>
              )}
            </>
          )}
        </dl>
      </div>
    </>
  );
}

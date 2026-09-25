import type { Metadata } from "next";

import { Disclose } from "@/components/disclose";
import { api, failTheBuildInstead, type Ratios } from "@/lib/api";
import { day } from "@/lib/format";

import { Panel, ScrollHint } from "../../_ui";
import { FigureTable, RATIO_GROUPS, reported } from "../_figures";
import { CompanyProblem } from "../_states";

interface PageProps {
  params: Promise<{ ticker: string }>;
}

export async function generateMetadata({ params }: PageProps): Promise<Metadata> {
  const { ticker } = await params;
  return {
    title: `${decodeURIComponent(ticker).toUpperCase()} financials`,
    description:
      "Every ratio the API holds for one company's latest filing, grouped, with what " +
      "each group measures and where the figures came from.",
  };
}

/**
 * Financials — the whole ratio set, grouped.
 *
 * Every one of the API's twenty-six ratio keys appears here exactly once, in a group
 * with its siblings. Unlike the metric rows on Overview, a table keeps its absent rows:
 * "not reported" beside a line a reader came looking for is an answer, and `td.absent`
 * draws it quieter than a figure so a column of them does not read as data.
 *
 * The one exception is a group with nothing in it at all. `DESIGN.md` §6: then the
 * figures are not drawn and one sentence says which lines are missing and why - which is
 * what a bank's margins get, rather than four rows of the same phrase.
 */
export default async function FinancialsPage({ params }: PageProps) {
  const { ticker: raw } = await params;
  const ticker = decodeURIComponent(raw);

  let data: Ratios;
  try {
    data = await api.ratios(ticker);
  } catch (error) {
    failTheBuildInstead(error);
    return <CompanyProblem ticker={ticker} error={error} withHeading={false} />;
  }

  const r = data.ratios;

  return (
    <>
      <h2>
        Ratios from the {data.filing_type} for {data.period_label}
      </h2>

      <div className="grid">
        {RATIO_GROUPS.map((group) => {
          const anyReported = group.figures.some((spec) => reported(spec, r));
          return (
            <Panel key={group.title} title={group.title}>
              {anyReported ? (
                <>
                  <div className="scroller">
                    <FigureTable
                      caption={group.caption}
                      figures={group.figures}
                      values={r}
                      currency={data.currency}
                    />
                  </div>
                  <ScrollHint />
                </>
              ) : (
                <div className="panel-body">
                  <div className="notice">
                    {group.absent ?? (
                      <p>
                        This filing does not carry the lines these figures are worked out
                        from, so none of them is shown. Nothing has been estimated in
                        their place and no zero is standing in for a blank.
                      </p>
                    )}
                  </div>
                </div>
              )}
            </Panel>
          );
        })}
      </div>

      <h2>What each group measures</h2>

      {RATIO_GROUPS.map((group) => (
        <Disclose key={group.title} brief={`${group.title} — ${group.brief}`}>
          {group.detail}
        </Disclose>
      ))}

      <div className="source">
        <dl>
          <dt>Period</dt>
          <dd>
            {data.period_label}, ended {day(data.period_end)}
          </dd>
          <dt>Filing</dt>
          <dd>{data.filing_type}</dd>
          <dt>Became public</dt>
          <dd>{day(data.known_as_of)}</dd>
          <dt>Shown as known on</dt>
          <dd>{day(data.as_known_on)}</dd>
          <dt>Currency</dt>
          <dd>{data.currency}</dd>
          <dt>Attribution</dt>
          <dd>{data.attribution}</dd>
          {data.price === null ? null : (
            <>
              <dt>Price behind every multiple</dt>
              <dd>
                close of {day(data.price.date)}, knowable {day(data.price.known_as_of)}
              </dd>
              <dt>Price attribution</dt>
              <dd>{data.price.attribution}</dd>
            </>
          )}
        </dl>
      </div>
    </>
  );
}

import type { Metadata } from "next";

import { Disclose } from "@/components/disclose";
import { api, failTheBuildInstead, type Ratios } from "@/lib/api";
import { day } from "@/lib/format";

import { Metric, Panel, ScrollHint } from "../_ui";
import {
  FALLBACK_LEAD,
  FigureTable,
  INPUT_GROUPS,
  MARGINS,
  MARKET_RESERVE,
  OVERVIEW_MARKET,
  RATIO_GROUPS,
  offered,
  reported,
  write,
} from "./_figures";
import { CompanyProblem } from "./_states";

interface PageProps {
  params: Promise<{ ticker: string }>;
}

export async function generateMetadata({ params }: PageProps): Promise<Metadata> {
  const { ticker } = await params;
  return {
    title: decodeURIComponent(ticker).toUpperCase(),
    description:
      "One company at a glance: the headline figures from its latest filing, what the " +
      "market is paying for it, and the filed lines the ratios were built from.",
  };
}

/** The margins group and the multiples group, whose explanations are reused here. */
const MARGIN_NOTE = RATIO_GROUPS[0];
const MULTIPLE_NOTE = RATIO_GROUPS[RATIO_GROUPS.length - 1];

/**
 * Overview — the company at a glance.
 *
 * Two metric rows and the filed lines behind them. The header, the tabs and the page's
 * only `<h1>` live in the layout, so this starts at `<h2>`.
 */
export default async function OverviewPage({ params }: PageProps) {
  const { ticker: raw } = await params;
  const ticker = decodeURIComponent(raw);

  let data: Ratios;
  try {
    // The same URL the layout asked for, so Next serves it from this request's own fetch
    // cache. The header is fetched once however many tabs get opened.
    data = await api.ratios(ticker);
  } catch (error) {
    failTheBuildInstead(error);
    return <CompanyProblem ticker={ticker} error={error} withHeading={false} />;
  }

  const r = data.ratios;
  const currency = data.currency;

  /**
   * Three of the twenty-four companies held - JPM, BAC, UNH - report none of the four
   * margins. That is bank and insurer accounting, not a gap in the data: there is no
   * cost of making a product to set against sales, so there is nothing for a margin to
   * measure. Where that happens the heading changes and the page leads with figures they
   * do report, taken in a fixed order so two banks lead with the same four in the same
   * places, and drawn only from figures the Financials tab explains.
   */
  const noMargins = !MARGINS.some((spec) => reported(spec, r));
  const lead = noMargins ? FALLBACK_LEAD.filter((spec) => reported(spec, r)) : MARGINS;
  /**
   * The market row, with anything the lead already showed taken out and the count made
   * back up from the reserve. Nothing appears twice on the page, and the row stays at
   * twelve - which is what lets it fill its last track at every width instead of leaving
   * the grid's own background showing as a grey block.
   */
  const taken = new Set(lead.map((spec) => spec.key));
  const market = [
    ...OVERVIEW_MARKET.filter((spec) => !taken.has(spec.key)),
    ...MARKET_RESERVE.filter((spec) => !taken.has(spec.key)),
  ].slice(0, OVERVIEW_MARKET.length);
  const noMultiples = !market.some((spec) => reported(spec, r));

  return (
    <>
      <h2>
        {noMargins
          ? "What it earned on what it holds"
          : "How much of what it sold it kept"}
      </h2>

      {lead.length === 0 ? (
        <div className="notice">
          <h3>No headline figure is reported for this period</h3>
          <p>
            This filing reports neither the four margins nor the returns that stand in for
            them. Nothing has been estimated in their place and no zero is standing in for
            a blank. The tables below show every line it does report.
          </p>
        </div>
      ) : (
        <div className="metrics">
          {lead.map((spec) => (
            <Metric
              key={spec.key}
              name={spec.short ?? spec.name}
              value={write(spec, r, currency)}
            />
          ))}
        </div>
      )}

      {noMargins ? (
        <div className="notice">
          <h3>Why these, and not margins</h3>
          <p>
            A margin measures profit against sales, so it needs both — and this filing
            does not report them in that shape. Not every company files that way: banks
            and insurers commonly do not, because they have no cost of making a product to
            set against what they sold. Nothing has been estimated in their place.
          </p>
          <p>
            So the figures above measure the year&rsquo;s profit against what the company
            owns and what its owners put into it, which this filing does report. Each one
            is explained again on the <b>Financials</b> tab.
          </p>
        </div>
      ) : null}

      <Disclose brief={MARGIN_NOTE.brief}>{MARGIN_NOTE.detail}</Disclose>

      <h2>What the market is paying</h2>

      {noMultiples ? (
        <div className="notice">
          <h3>No multiple can be put together for this period</h3>
          <p>
            A multiple needs a price and a figure from the filing to set it against, and
            for this period the API holds neither half of any pair. Nothing has been
            estimated in their place.
          </p>
        </div>
      ) : (
        <div className="metrics">
          {market.map((spec) => (
            <Metric
              key={spec.key}
              name={spec.short ?? spec.name}
              value={write(spec, r, currency)}
            />
          ))}
        </div>
      )}

      <Disclose brief={MULTIPLE_NOTE.brief}>
        {MULTIPLE_NOTE.detail}
        <p>
          That row ends with the per-share amounts the first ratios divide by, which are
          not multiples themselves. They sit beside them so the arithmetic is visible in
          one place; the <b>Financials</b> tab groups them with the other per-share
          figures.
        </p>
      </Disclose>

      <h2>What the filing reported</h2>

      <div className="grid">
        {INPUT_GROUPS.map((group) => {
          // Filtered against the keys this company's filing actually carries. A bank
          // sends deposits and loans where a manufacturer sends revenue and cost of
          // revenue; a key the API never offered is not a missing figure, and printing
          // "not reported" against a line that does not exist in this kind of filing
          // would say something untrue.
          const figures = group.figures.filter((spec) => offered(spec, data.inputs));
          if (figures.length === 0) return null;
          const anyReported = figures.some((spec) => reported(spec, data.inputs));

          return (
            <Panel key={group.title} title={group.title}>
              {anyReported ? (
                <>
                  <div className="scroller">
                    <FigureTable
                      caption={group.caption}
                      figures={figures}
                      values={data.inputs}
                      currency={currency}
                    />
                  </div>
                  <ScrollHint />
                </>
              ) : (
                <div className="panel-body">
                  <div className="notice">
                    <p>
                      This filing carries none of these lines in a form the loader could
                      read, so none is shown. Nothing has been estimated in their place.
                    </p>
                  </div>
                </div>
              )}
            </Panel>
          );
        })}
      </div>

      <Disclose brief="These are the filed lines the ratios were built from, not figures this page worked out.">
        <p>
          Everything in this block came out of the filing named below, as filed. The
          ratios higher up the page were worked out from these lines by the server, never
          by your browser — which is why a ratio can be absent while the lines behind it
          are present, and never the other way round.
        </p>
        <p>
          Large amounts are shortened — 98.77B rather than twelve digits — because twelve
          digits of precision is not information a reader can use and thirteen characters
          of it crowds everything else off a narrow screen. The full figure is what the
          server holds and what every ratio was worked out from.
        </p>
      </Disclose>

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
          <dd>{currency}</dd>
          <dt>Attribution</dt>
          <dd>{data.attribution}</dd>
          {data.price === null ? null : (
            <>
              <dt>Price</dt>
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

import type { Metadata } from "next";

import { ChartBoundary } from "@/components/chart-boundary";
import ChartPrice, {
  type ChartBar,
  type ChartLine,
  type ChartPane,
} from "@/components/chart-price";
import { Disclose } from "@/components/disclose";
import {
  ApiTimeout,
  api,
  failTheBuildInstead,
  type CompanyIndicators,
  type CompanyPrices,
  type IndicatorSeries,
} from "@/lib/api";
import { SERVICE_IS_SLOW, count, day } from "@/lib/format";

import { CompanyProblem } from "../_states";
import { IndicatorPicker, RangePicker } from "./_controls";
import { PlottedPoints, TABLE_ROWS, type IndicatorColumn } from "./_table";
import {
  pickOverlays,
  pickRange,
  pickStyle,
  seriesNames,
  windowStart,
} from "./_view";

interface PageProps {
  params: Promise<{ ticker: string }>;
  searchParams: Promise<Record<string, string | string[] | undefined>>;
}

export async function generateMetadata({ params }: PageProps): Promise<Metadata> {
  const { ticker } = await params;
  return {
    title: `${decodeURIComponent(ticker).toUpperCase()} chart`,
    description:
      "The adjusted price history of one company, with volume beneath it and any of " +
      "the stored indicators drawn over it. Every plotted point is also listed as a table.",
  };
}

/**
 * Chart — the price, the volume under it, and the stored indicators over it.
 *
 * THE ONE RULE THIS PAGE EXISTS TO KEEP
 * The line is `close`, which is adjusted as of the decision date. It is never
 * `close_raw`. Both come back from the same endpoint and they are the same price twice:
 * across Apple's 2020 four-for-one split the adjusted closes run 124.8075 -> 129.04 (a
 * rise of 3.39%) and the raw ones run 499.23 -> 129.04, which draws a 74% cliff on a day
 * the stock went up. The raw close is on the page - in its own table column, and in the
 * readout under the chart - because a reader is entitled to know what the screen said
 * that day. It is not on the chart.
 *
 * WHAT IT WILL NOT DO
 * `SPEC.md` 2C: indicators are features, not signals. There is no shaded band, no marked
 * crossover, no 30/70 line, no target and no word anywhere on this page about whether a
 * reading is good. `DESIGN.md` §1 applies to pixels exactly as it applies to prose.
 *
 * THE SHAPE OF THE FETCH
 * Two calls, and only one of them can take the page down. Without prices there is no
 * chart and no table, so a failure there is the page's failure. Indicators are an
 * overlay a reader asked for: if that call fails the price chart still draws and the
 * page says which overlays are missing, because losing an optional line is not a reason
 * to lose the price.
 */
export default async function ChartPage({ params, searchParams }: PageProps) {
  const { ticker: raw } = await params;
  const ticker = decodeURIComponent(raw);
  const query = await searchParams;

  const range = pickRange(query.range);
  const style = pickStyle(query.style);
  const chosen = pickOverlays(query.show);
  const show = chosen.map((overlay) => overlay.id);
  const start = windowStart(range);

  let prices: CompanyPrices;
  try {
    prices = await api.prices(ticker, start);
  } catch (error) {
    failTheBuildInstead(error);
    return <CompanyProblem ticker={ticker} error={error} withHeading={false} />;
  }

  // The overlays, asked for separately and allowed to fail on their own.
  const wanted = seriesNames(chosen);
  let indicators: CompanyIndicators | null = null;
  let overlayError: unknown = null;
  if (wanted.length > 0) {
    try {
      indicators = await api.indicators(ticker, wanted, start);
    } catch (error) {
      failTheBuildInstead(error);
      overlayError = error;
    }
  }

  const controls = (
    <>
      <RangePicker ticker={ticker} range={range} style={style} show={show} />
      <IndicatorPicker
        ticker={ticker}
        range={range}
        style={style}
        show={show}
        chosen={chosen}
      />
    </>
  );

  // ---- empty: a window with no bars in it renders the empty state, not an axis -----
  if (prices.bars.length === 0) {
    return (
      <>
        <h2>Price and volume</h2>
        {controls}
        <div className="notice">
          <h3>No price is held for this window</h3>
          <p>
            The API returned no trading days for {prices.legal_name} over {range.label}.
            Nothing has been drawn, because an empty axis looks like a flat price rather
            than like an absence.
          </p>
          <p>
            A wider range may hold bars this one does not — <b>Max</b> asks for every day
            held for this company.
          </p>
        </div>
        <p className="source">
          {prices.attribution} · figures as known on {day(prices.as_known_on)}
        </p>
      </>
    );
  }

  // ---- projection -------------------------------------------------------------------
  // Mapping an API series into the library's `{ time, value }` shape, and parsing a
  // decimal string the API already produced. No figure is derived: nothing here adds,
  // averages or compares two numbers. AD-3.
  const bars: ChartBar[] = [];
  for (const bar of prices.bars) {
    const close = Number(bar.close);
    if (!Number.isFinite(close)) continue;
    bars.push({
      time: bar.date,
      open: Number(bar.open),
      high: Number(bar.high),
      low: Number(bar.low),
      close,
      volume: Number(bar.volume),
      raw: bar.close_raw,
    });
  }

  const held: Map<string, IndicatorSeries> = new Map(
    (indicators?.series ?? []).map((series) => [series.name, series]),
  );

  const plot = (series: IndicatorSeries) =>
    series.points
      .filter((point) => Number.isFinite(point.value))
      .map((point) => ({ time: point.date, value: point.value }));

  const overlays: ChartLine[] = [];
  const panes: ChartPane[] = [];
  const columns: IndicatorColumn[] = [];
  const missing: string[] = [];

  for (const overlay of chosen) {
    let anyHeld = false;
    const lines: ChartLine[] = [];
    let histogram: ChartPane["bars"];

    for (const spec of overlay.series) {
      const series = held.get(spec.name);
      if (!series) continue;
      anyHeld = true;
      const points = plot(series);
      columns.push({
        name: spec.name,
        label: spec.label,
        params: series.params,
        values: new Map(series.points.map((point) => [point.date, point.value])),
      });
      if (spec.kind === "bars") {
        histogram = { key: spec.name, label: spec.label, points };
      } else {
        const line: ChartLine = {
          key: spec.name,
          label: spec.label,
          tone: spec.tone,
          dashed: spec.dashed,
          points,
        };
        if (overlay.where === "price") overlays.push(line);
        else lines.push(line);
      }
    }

    if (!anyHeld) {
      /**
       * Only an *answered* request can tell us a series is not held. When the call
       * itself failed, `held` is empty for every group and saying "the API holds a
       * fixed set per company and this one is not in it" would be inventing a reason -
       * the page would be asserting an absence it has no evidence for, next to a notice
       * correctly saying the request did not come back. One event, one explanation.
       */
      if (overlayError === null) missing.push(overlay.label);
      continue;
    }
    if (overlay.where === "pane") {
      panes.push({ key: overlay.id, label: overlay.label, lines, bars: histogram });
    }
  }

  const slow = overlayError instanceof ApiTimeout;

  return (
    <>
      <h2>Price and volume</h2>

      {controls}

      <section className="panel">
        <div className="panel-head">
          <h3>
            {prices.legal_name} — {range.label}
          </h3>
        </div>
        <div className="panel-body">
          {/* The fence. `DESIGN.md` 4b: a chart must not be the reason a page fails, and
              this is the only thing on the page that draws to a canvas. If it throws,
              the boundary replaces it and the table below is untouched. */}
          <ChartBoundary>
            <ChartPrice
              bars={bars}
              currency={prices.currency}
              overlays={overlays}
              panes={panes}
              style={style}
              ticker={prices.ticker}
              rangeLabel={range.label}
            />
          </ChartBoundary>
        </div>
      </section>

      {overlayError !== null ? (
        <div className={slow ? "notice" : "notice bad"}>
          <h3>
            {slow
              ? "The indicators are taking longer than the page waits"
              : "The indicators could not be loaded"}
          </h3>
          <p>
            {slow
              ? SERVICE_IS_SLOW
              : "The request for the stored indicators did not come back. Nothing has been " +
                "drawn in their place and no value has been estimated."}
          </p>
          <p>
            The price and volume above are unaffected — they came from a different request,
            which answered.
          </p>
        </div>
      ) : null}

      {missing.length > 0 ? (
        <div className="notice">
          <h3>Not every indicator asked for is held</h3>
          <p>
            No stored series was returned for {missing.join(", ")}, so nothing was drawn
            for {missing.length === 1 ? "it" : "them"}. The API holds a fixed set per
            company and this one is not in it — that is an absence, not a failure.
          </p>
        </div>
      ) : null}

      {bars.length !== prices.bars.length ? (
        <div className="notice">
          <h3>Some bars could not be drawn</h3>
          <p>
            {count(prices.bars.length - bars.length)} of {count(prices.bars.length)} bars
            held no close that could be plotted and were left off the chart. All{" "}
            {count(prices.bars.length)} are in the table below, exactly as the API sent
            them.
          </p>
        </div>
      ) : null}

      {prices.truncated ? (
        <div className="notice">
          <h3>This is not the whole history</h3>
          <p>
            The API caps a single answer and dropped the oldest bars to stay under it, so
            this chart begins later than the company&rsquo;s first trading day. It trims
            from the far end and never the near one, so nothing recent is missing. A
            narrower range returns every bar inside it.
          </p>
        </div>
      ) : null}

      {/* The other rendering of the same data - `DESIGN.md` 4b. Server-rendered, present
          before any JavaScript runs, and the thing a screen reader actually gets. */}
      <Disclose
        brief={`Every point on the chart, as a table — ${count(
          Math.min(prices.bars.length, TABLE_ROWS),
        )} rows, including what the market printed each day.`}
      >
        <PlottedPoints
          bars={prices.bars}
          columns={columns}
          currency={prices.currency}
          range={range}
          style={style}
          ticker={ticker}
          show={show}
        />
      </Disclose>

      <p className="source">
        {prices.attribution} · {count(prices.bars.length)} trading days from{" "}
        {day(prices.bars[0].date)} to {day(prices.bars[prices.bars.length - 1].date)} ·
        prices as known on {day(prices.as_known_on)} · each bar became knowable on its own
        date, shown in the table
        {indicators !== null
          ? ` · indicators computed on the ${indicators.price_series} price series, as known on ${day(
              indicators.as_known_on,
            )}; each reading is the vintage that date could see`
          : ""}
      </p>

      <Disclose brief="An adjusted close and the price the market printed are the same price written two ways.">
        <p>
          A company can split its shares, and when it does, the price per share changes
          without anything about the company changing. Apple did it in August 2020: every
          share became four, and the price the market printed fell from about 499 to about
          129 overnight.
        </p>
        <p>
          An <b>adjusted close</b> rewrites every earlier price as though that split had
          always happened, so a line drawn through them is continuous and a move measured
          across them is the move that actually occurred. Over that week Apple&rsquo;s
          adjusted closes run 124.81 to 129.04 — up 3.39% — while the prices as traded
          run 499.23 to 129.04, which is the same week drawn as a 74% collapse.
        </p>
        <p>
          Both are in the table. The chart draws the adjusted one, and the{" "}
          <b>As traded</b> column and the <b>Factor</b> beside it are how to see where the
          two part company.
        </p>
      </Disclose>

      <Disclose brief="These indicators are descriptions of past prices, and this page does not read anything into them.">
        <p>
          Each one is a fixed arithmetic recipe applied to the closes already shown. An
          RSI restates how the recent up days compare with the recent down days as a
          number between 0 and 100. Bollinger bands restate how far the recent closes have
          spread around their own average. MACD restates the distance between two moving
          averages of the close. A stochastic restates where the close sits inside its
          recent high-low range.
        </p>
        <p>
          They are stored here as features — inputs a model could be given — and nothing
          on this page marks a level, shades a region or annotates a crossing. That is
          deliberate and it is a rule of the project rather than a gap:{" "}
          <b>this site measures and explains, and it never tells anybody what to do.</b>
        </p>
        <p>
          Every reading is the one that was knowable on the decision date. Where a series
          was recomputed after the underlying prices were restated, the value shown is the
          vintage that date could see — not the newest that exists.
        </p>
      </Disclose>
    </>
  );
}

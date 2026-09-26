"use client";

import { useEffect, useRef, useState } from "react";
import type { IChartApi, MouseEventParams, Time } from "lightweight-charts";

import { count, day, money } from "@/lib/format";

/**
 * The price chart. The first chart in this application, and the only client component
 * that draws one.
 *
 * WHAT IT IS NOT
 * It is not the page's rendering of this data. `DESIGN.md` 4b: a canvas has no DOM, so a
 * chart is invisible to a screen reader and is therefore always an *additional*
 * rendering. The table of the same points sits below it, server-rendered, and is what a
 * reader who cannot see this gets. If this component fails to load, nothing on the page
 * is lost except the picture - which is why it is mounted inside `ChartBoundary`.
 *
 * WHAT IT DRAWS
 * `bar.close`, which is adjusted as of the decision date. Never `bar.raw`. Across
 * Apple's 2020 four-for-one split the adjusted closes run 124.8075 -> 129.04 and the raw
 * ones 499.23 -> 129.04; a raw line shows a 74% cliff on a day the stock rose 3.39%.
 * `raw` is carried on every bar for one purpose only - so the readout under the chart can
 * say what the screen actually showed that day.
 *
 * WHAT IT MUST NOT DRAW
 * `SPEC.md` 2C: indicators are features, not signals. There is no shaded zone, no
 * annotated crossover, no target line and no threshold anywhere in this file, and adding
 * one would turn a measurement into advice.
 *
 * COLOUR
 * Every colour is read off `document.documentElement` at mount. There is not a hex value
 * in this file. Where two lines share a pane they also differ in dash pattern, because
 * the library cannot draw an arrow and colour is never the only signal (`DESIGN.md` §9).
 */

/** One plotted trading day. Projected from `AdjustedBar` on the server. */
export interface ChartBar {
  /** "2020-08-31". The library takes a calendar date directly for a daily series. */
  time: string;
  open: number;
  high: number;
  low: number;
  /** Adjusted. The line. */
  close: number;
  volume: number;
  /** What the market printed that day, as the API spelled it. Readout only. */
  raw: string;
}

/** Which token a series is drawn in. Named, so the component resolves it from `:root`. */
export type Tone = "act" | "ink-soft" | "ink-faint" | "up" | "down";

export interface ChartLine {
  /** The API's own series name - `rsi14`, `macd_signal`. Stable and unique. */
  key: string;
  label: string;
  tone: Tone;
  dashed: boolean;
  points: { time: string; value: number }[];
}

/** An oscillator pane: its own vertical scale, under the price and the volume. */
export interface ChartPane {
  key: string;
  label: string;
  lines: ChartLine[];
  /** A histogram in the same pane - MACD's own bar series. Drawn in one neutral tone. */
  bars?: { key: string; label: string; points: { time: string; value: number }[] };
}

export interface ChartPriceProps {
  bars: ChartBar[];
  currency: string;
  /** Bollinger and anything else that shares the price scale. */
  overlays: ChartLine[];
  panes: ChartPane[];
  style: "line" | "candles";
  /** For the chart's accessible name, which is all a screen reader gets from a canvas. */
  ticker: string;
  rangeLabel: string;
}

/** The price pane, then one band per pane below it. Pixels the canvas needs, not CSS. */
const PRICE_HEIGHT = 300;
const BAND_HEIGHT = 100;

/**
 * The library's own name for a day, turned back into the key the bars are indexed by.
 *
 * A daily series is set with `"2020-08-31"` strings, but a crosshair event can hand back
 * either that string or the library's `{ year, month, day }` form depending on how the
 * point was produced. Reading only one of the two makes the readout silently stop
 * following the pointer, which looks like a broken chart rather than a missed branch.
 * This is a key being rewritten, not a figure being derived.
 */
function stampOf(time: Time | undefined): string | undefined {
  if (time === undefined) return undefined;
  if (typeof time === "string") return time;
  if (typeof time === "object" && "year" in time) {
    const pad = (part: number) => String(part).padStart(2, "0");
    return `${time.year}-${pad(time.month)}-${pad(time.day)}`;
  }
  return undefined;
}

type Palette = Record<Tone | "paper" | "line" | "ink", string>;

/**
 * The palette, read off the document rather than written here.
 *
 * `DESIGN.md` §5 forbids a hex value in a component, and a canvas cannot inherit a CSS
 * variable - so the tokens are resolved once at mount and handed to the library as
 * strings. Changing `globals.css` changes the chart; nothing here needs editing.
 */
function readTokens(): Palette {
  const css = getComputedStyle(document.documentElement);
  const read = (name: string) => css.getPropertyValue(name).trim();
  return {
    act: read("--act"),
    "ink-soft": read("--ink-soft"),
    "ink-faint": read("--ink-faint"),
    up: read("--up"),
    down: read("--down"),
    paper: read("--paper"),
    line: read("--line"),
    ink: read("--ink"),
  };
}

export default function ChartPrice({
  bars,
  currency,
  overlays,
  panes,
  style,
  ticker,
  rangeLabel,
}: ChartPriceProps) {
  const host = useRef<HTMLDivElement | null>(null);
  const [readout, setReadout] = useState<string | null>(null);
  /**
   * Set when the library itself throws. The boundary above catches a failure during
   * render; a failure inside the effect is caught here, so the page, the readout and the
   * table survive it either way.
   */
  const [broke, setBroke] = useState(false);

  /** What is on the chart, for the one sentence a screen reader gets from a canvas. */
  const drawn = [...overlays.map((line) => line.label), ...panes.map((pane) => pane.label)];

  useEffect(() => {
    const element = host.current;
    if (!element || bars.length === 0) return;

    let chart: IChartApi | null = null;
    let observer: ResizeObserver | null = null;
    let dropped = false;

    /**
     * Loaded here rather than imported at the top of the module. The library is ESM and
     * reaches for `document`; a top-level import would run while this component is
     * server-rendered, where there is none. This runs only in a browser, and it keeps
     * ~45KB out of the first load of every page that has no chart on it.
     */
    void import("lightweight-charts")
      .then((lib) => {
        if (dropped || !host.current) return;
        const colour = readTokens();
        const last = bars[bars.length - 1];

        const describe = (bar: ChartBar, extra: string[]): string =>
          [
            day(bar.time),
            `open ${money(String(bar.open), currency)}`,
            `high ${money(String(bar.high), currency)}`,
            `low ${money(String(bar.low), currency)}`,
            `close ${money(String(bar.close), currency)}`,
            `volume ${count(bar.volume)}`,
            `as traded that day ${money(bar.raw, currency)}`,
            ...extra,
          ].join(" · ");

        const made = lib.createChart(element, {
          width: element.clientWidth,
          height: PRICE_HEIGHT + BAND_HEIGHT * (1 + panes.length),
          layout: {
            background: { type: lib.ColorType.Solid, color: colour.paper },
            textColor: colour["ink-soft"],
            fontSize: 11,
            fontFamily: getComputedStyle(document.body).fontFamily,
            panes: { separatorColor: colour.line, enableResize: false },
          },
          grid: {
            vertLines: { color: colour.line },
            horzLines: { color: colour.line },
          },
          crosshair: {
            mode: lib.CrosshairMode.Magnet,
            vertLine: { color: colour["ink-faint"], labelBackgroundColor: colour.ink },
            horzLine: { color: colour["ink-faint"], labelBackgroundColor: colour.ink },
          },
          rightPriceScale: { borderColor: colour.line },
          timeScale: {
            borderColor: colour.line,
            rightOffset: 2,
            /**
             * The library will not squeeze bars closer than `minBarSpacing`, which
             * defaults to half a pixel - so `fitContent()` on Apple's 6,000-bar Max
             * range silently showed only the most recent ~1,200 of them and put the
             * first visible day in 2019 rather than 2002. A range labelled "every bar
             * held" that opens on a fifth of it is the page telling the reader something
             * that is not so, which is the one thing this project will not do. Low
             * enough that six thousand bars fit in the narrowest pane this page has.
             */
            minBarSpacing: 0.02,
          },
        });
        chart = made;

        /**
         * Every drawn series, with its own date-keyed readings.
         *
         * Keeping the lookup here rather than asking the crosshair event for it means
         * the readout can be filled for the settled bar too, not only for a bar under
         * the pointer - so a reader who never hovers still sees every value the chart
         * is showing, named.
         */
        const named: { label: string; values: Map<string, number> }[] = [];
        const remember = (label: string, points: { time: string; value: number }[]) =>
          named.push({ label, values: new Map(points.map((p) => [p.time, p.value])) });

        // ---- pane 0: price --------------------------------------------------
        if (style === "candles") {
          // Up candles are hollow and down candles filled, so direction survives for a
          // reader who cannot separate the two colours. `DESIGN.md` §9.
          const candles = made.addSeries(
            lib.CandlestickSeries,
            {
              upColor: colour.paper,
              downColor: colour.down,
              borderUpColor: colour.up,
              borderDownColor: colour.down,
              wickUpColor: colour.up,
              wickDownColor: colour.down,
              priceFormat: { type: "price", precision: 2, minMove: 0.01 },
            },
            0,
          );
          candles.setData(
            bars.map((bar) => ({
              time: bar.time as Time,
              open: bar.open,
              high: bar.high,
              low: bar.low,
              close: bar.close,
            })),
          );
        } else {
          const line = made.addSeries(
            lib.LineSeries,
            {
              color: colour.act,
              lineWidth: 2,
              priceLineVisible: false,
              priceFormat: { type: "price", precision: 2, minMove: 0.01 },
            },
            0,
          );
          // `bar.close` - adjusted. The whole point of this file.
          line.setData(bars.map((bar) => ({ time: bar.time as Time, value: bar.close })));
        }

        for (const overlay of overlays) {
          const series = made.addSeries(
            lib.LineSeries,
            {
              color: colour[overlay.tone],
              lineWidth: 1,
              lineStyle: overlay.dashed ? lib.LineStyle.Dashed : lib.LineStyle.Solid,
              priceLineVisible: false,
              lastValueVisible: false,
              crosshairMarkerVisible: false,
              priceFormat: { type: "price", precision: 2, minMove: 0.01 },
            },
            0,
          );
          series.setData(
            overlay.points.map((point) => ({ time: point.time as Time, value: point.value })),
          );
          remember(overlay.label, overlay.points);
        }

        // ---- pane 1: volume -------------------------------------------------
        // One neutral tone, not green and red by the day's direction: the library cannot
        // draw the arrow `.delta` supplies, so direction by colour alone would be the
        // one signal a red-green-blind reader does not get. Direction is in the price
        // pane, where the candle's own shape carries it.
        const volume = made.addSeries(
          lib.HistogramSeries,
          { color: colour["ink-faint"], priceFormat: { type: "volume" } },
          1,
        );
        volume.setData(bars.map((bar) => ({ time: bar.time as Time, value: bar.volume })));

        // ---- panes 2+: one per oscillator group ------------------------------
        panes.forEach((pane, index) => {
          const paneIndex = index + 2;
          if (pane.bars) {
            const histogram = made.addSeries(
              lib.HistogramSeries,
              {
                color: colour["ink-faint"],
                priceFormat: { type: "price", precision: 4, minMove: 0.0001 },
              },
              paneIndex,
            );
            histogram.setData(
              pane.bars.points.map((point) => ({
                time: point.time as Time,
                value: point.value,
              })),
            );
            remember(pane.bars.label, pane.bars.points);
          }
          for (const line of pane.lines) {
            const series = made.addSeries(
              lib.LineSeries,
              {
                color: colour[line.tone],
                lineWidth: 1,
                lineStyle: line.dashed ? lib.LineStyle.Dashed : lib.LineStyle.Solid,
                priceLineVisible: false,
                lastValueVisible: false,
                priceFormat: { type: "price", precision: 4, minMove: 0.0001 },
              },
              paneIndex,
            );
            series.setData(
              line.points.map((point) => ({ time: point.time as Time, value: point.value })),
            );
            remember(line.label, line.points);
          }
        });

        // The price pane keeps three bands' worth of the height and everything below it
        // gets one each, which is what makes the height arithmetic above come out exact.
        made.panes().forEach((pane, index) => pane.setStretchFactor(index === 0 ? 3 : 1));

        /**
         * A name on every pane under the price. Four unlabelled oscillator bands is a
         * chart that shows four things and says which of them is which nowhere - and
         * the reader who can see the shapes is the only one this text is for, since the
         * table below names every column regardless.
         *
         * A plain label, not a legend with a colour key: `DESIGN.md` §9 wants the name
         * beside the thing rather than a swatch to match up.
         */
        const paneNames = ["Volume", ...panes.map((pane) => pane.label)];
        paneNames.forEach((text, at) => {
          const pane = made.panes()[at + 1];
          if (!pane) return;
          lib.createTextWatermark(pane, {
            horzAlign: "left",
            vertAlign: "top",
            lines: [
              {
                text,
                color: colour["ink-faint"],
                fontSize: 11,
                fontFamily: getComputedStyle(document.body).fontFamily,
              },
            ],
          });
        });

        made.timeScale().fitContent();

        // ---- the readout ------------------------------------------------------
        // The figures under the pointer, in text. Deliberately not a floating tooltip: a
        // paragraph below the chart needs no positioning and therefore no inline style,
        // and it stays legible at 320px where a tooltip would cover the thing it labels.
        const indexByTime = new Map(bars.map((bar, at) => [bar.time, at]));
        const readingsOn = (stamp: string): string[] =>
          named.flatMap((entry) => {
            const value = entry.values.get(stamp);
            // A series that does not reach this day is left out rather than written as
            // a zero. An indicator needs a warm-up window, and 0 is a reading.
            return value === undefined ? [] : [`${entry.label} ${value.toFixed(4)}`];
          });
        const show = (bar: ChartBar) => setReadout(describe(bar, readingsOn(bar.time)));
        const settle = () => show(last);
        settle();

        made.subscribeCrosshairMove((event: MouseEventParams<Time>) => {
          const at = indexByTime.get(stampOf(event.time) ?? "");
          if (at === undefined) {
            settle();
            return;
          }
          show(bars[at]);
        });

        observer = new ResizeObserver(() => {
          if (chart && host.current) {
            chart.applyOptions({ width: host.current.clientWidth });
          }
        });
        observer.observe(element);
      })
      .catch(() => {
        if (!dropped) setBroke(true);
      });

    return () => {
      dropped = true;
      observer?.disconnect();
      chart?.remove();
      chart = null;
    };
  }, [bars, currency, overlays, panes, style]);

  if (broke) {
    return (
      <div className="notice">
        <h3>The chart could not be drawn</h3>
        <p>
          The drawing library did not load, so the picture is missing. Every figure it
          would have plotted is in the table below, unchanged — nothing about the data is
          in doubt.
        </p>
      </div>
    );
  }

  return (
    <>
      {/* A canvas carries no text, so the element is given a name and the table below is
          the rendering that actually carries the data. `DESIGN.md` 4b. */}
      <div
        ref={host}
        role="img"
        aria-label={
          `Price and volume for ${ticker}, ${rangeLabel}` +
          (drawn.length > 0 ? `, with ${drawn.join(", ")} drawn over it` : "") +
          ". The same figures are listed in the table below this chart."
        }
      />
      <p className="muted">
        {readout ?? "Point at the chart to read a day's figures here."}
      </p>
    </>
  );
}

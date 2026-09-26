import { Fragment, type ReactNode } from "react";
import Link from "next/link";

import {
  OVERLAYS,
  RANGES,
  type OverlaySpec,
  type RangeSpec,
  type Style,
  chartHref,
  toggled,
} from "./_view";

/**
 * The controls. Every one of them is a link.
 *
 * Not buttons with handlers, and not a client component: `DESIGN.md` §8 keeps all
 * fetching on the server, so changing the window means asking the server for a different
 * window. A link does that, works before hydration and with JavaScript off, is reachable
 * by keyboard without anything being written here to make it so, and leaves every view
 * of this page with an address somebody can send to somebody else.
 *
 * The selected item is `.button` (filled) and the rest are `.button.quiet` (outlined) -
 * an inversion rather than a change of hue, so the state survives without colour.
 * `aria-current` carries the same fact to a screen reader, and the sentence under the
 * indicator row states it a third time in words.
 *
 * LAYOUT, AND A CLASS THAT DOES NOT EXIST
 * `globals.css` has no class for a row of controls, and §10 forbids inventing an inline
 * style in place of one. So each row is a `<nav>` around a plain `<p>`: the buttons are
 * already `inline-flex`, a real space between them separates them, the paragraph wraps
 * them at any width including 320px, and its default margin supplies the rhythm between
 * the two rows. No class is invented and none is borrowed for a job it was not written
 * for. The gap is reported rather than worked around.
 */
function Row({ label, children }: { label: string; children: ReactNode }) {
  return (
    <nav aria-label={label}>
      <p>{children}</p>
    </nav>
  );
}

export function RangePicker({
  ticker,
  range,
  style,
  show,
}: {
  ticker: string;
  range: RangeSpec;
  style: Style;
  show: string[];
}) {
  return (
    <Row label="How much history the chart shows">
      {RANGES.map((option, at) => (
        <Fragment key={option.id}>
          {at > 0 ? " " : null}
          <Link
            href={chartHref(ticker, { range: option.id, style, show })}
            className={option.id === range.id ? "button" : "button quiet"}
            aria-current={option.id === range.id ? "true" : undefined}
          >
            {option.short}
          </Link>
        </Fragment>
      ))}{" "}
      <Link
        href={chartHref(ticker, {
          range: range.id,
          style: style === "line" ? "candles" : "line",
          show,
        })}
        className="button quiet"
      >
        {style === "line" ? "Show candlesticks" : "Show a line"}
      </Link>
    </Row>
  );
}

export function IndicatorPicker({
  ticker,
  range,
  style,
  show,
  chosen,
}: {
  ticker: string;
  range: RangeSpec;
  style: Style;
  show: string[];
  chosen: OverlaySpec[];
}) {
  return (
    <>
      <Row label="Indicators drawn on the chart">
        {OVERLAYS.map((overlay, at) => {
          const on = show.includes(overlay.id);
          return (
            <Fragment key={overlay.id}>
              {at > 0 ? " " : null}
              <Link
                href={chartHref(ticker, {
                  range: range.id,
                  style,
                  show: toggled(show, overlay.id),
                })}
                className={on ? "button" : "button quiet"}
                aria-current={on ? "true" : undefined}
              >
                {overlay.label}
              </Link>
            </Fragment>
          );
        })}
      </Row>
      {/* The state, in words. The filled-versus-outlined button says the same thing and
          `aria-current` says it again, but a sentence is the only one of the three that
          needs neither sight of the row nor a screen reader to be understood. */}
      <p className="muted">
        {chosen.length === 0
          ? "No indicator is drawn. Choosing one adds it to the chart, to the readout under the chart and to the table of plotted points."
          : `Drawn on the chart: ${chosen.map((overlay) => overlay.label).join(", ")}.`}
      </p>
    </>
  );
}

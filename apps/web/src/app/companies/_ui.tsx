import type { ReactNode } from "react";

import { NOT_LOADED, NOT_REPORTED } from "@/lib/format";

/**
 * The small render primitives the stock pages share.
 *
 * They exist so that the one rule this app treats as unbreakable - an absence is never a
 * zero and never an empty cell - is applied in one place rather than remembered in
 * fourteen. Everything here is presentation; nothing computes a figure. AD-3.
 */

/**
 * True when a formatter returned one of the two absence phrases rather than a figure.
 *
 * Compared against the constants rather than the strings, because `DESIGN.md` §6 forbids
 * a page from writing either phrase - and that has to include writing it in order to
 * test for it.
 */
export function isAbsent(text: string): boolean {
  return text === NOT_REPORTED || text === NOT_LOADED;
}

/** One cell of a `.metrics` row. Quiet when the figure is absent, never blank. */
export function Metric({ name, value }: { name: string; value: string }) {
  return (
    <div className="metric">
      <div className="metric-name">{name}</div>
      <div className={isAbsent(value) ? "metric-value absent" : "metric-value"}>
        {value}
      </div>
    </div>
  );
}

/** A right-aligned figure in a table. */
export function NumCell({ text }: { text: string }) {
  return <td className={isAbsent(text) ? "num absent" : "num"}>{text}</td>;
}

/**
 * A left-aligned word or date in a table.
 *
 * `nowrap` is opt-in and belongs on a date, a ticker or a cell holding a pill. Without
 * it, the moment a table exceeds its `.scroller` every column collapses to min-content
 * and "31 Aug 2026" becomes three lines - a 29px row turns into 73px and the density
 * this design exists for is gone.
 */
export function WordCell({ text, nowrap = false }: { text: string; nowrap?: boolean }) {
  const classes = [nowrap ? "nowrap" : "", isAbsent(text) ? "absent" : ""]
    .filter(Boolean)
    .join(" ");
  return <td className={classes || undefined}>{text}</td>;
}

/**
 * The hint under a table that can scroll inside its own box.
 *
 * Phrased as a condition and not as an assertion. `.scroll-hint` hides at a *viewport* of
 * 900px, but whether a given table actually overflows depends on its container, which is
 * narrower inside a `.panel` than at top level. "This table scrolls sideways" is false at
 * some widths; "if this table is wider than your screen" is true at all of them.
 */
export function ScrollHint() {
  return (
    <p className="scroll-hint">
      If this table is wider than your screen, it scrolls sideways rather than the page.
    </p>
  );
}

/** A group of related figures: a head with the group name, then whatever it holds. */
export function Panel({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section className="panel">
      <div className="panel-head">
        <h3>{title}</h3>
      </div>
      {children}
    </section>
  );
}

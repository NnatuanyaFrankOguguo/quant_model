import type { MacroSeries } from "@/lib/api";
import { NOT_LOADED, formatDay, withUnit } from "@/lib/format";

/**
 * The cells an economic series is written into.
 *
 * They live here rather than twice over because the overview and the economy page show
 * the same thirteen series and must say the same thing about them. `lib/format.ts`
 * already records what happens when one vocabulary is defined in two files: neither copy
 * is wrong, and nothing tells you when they drift apart.
 *
 * Each of these returns a `<td>` rather than its contents. `globals.css` styles an
 * absence as `td.absent` - the class has to land on the cell itself, so the cell is what
 * these hand back.
 */

/**
 * Freshness, as the API reports it. `is_stale` has three states and all three mean
 * something different:
 *
 *   false - the newest observation arrived inside the lag this source normally takes
 *   true  - it did not
 *   null  - there is no expected arrival date for it to be measured against
 *
 * DESIGN.md §5: the word is always beside the colour, and the colour is never blue.
 * "Nothing loaded" is the neutral pill, not the red one - an absence of observations is
 * not a broken series.
 */
export function Freshness({ series }: { series: MacroSeries }) {
  if (series.observation_count === 0) {
    return <span className="pill neutral">nothing loaded</span>;
  }
  if (series.is_stale === null) {
    return <span className="pill neutral">no expected date</span>;
  }
  if (series.is_stale) {
    return <span className="pill attention">later than usual</span>;
  }
  return <span className="pill ok">arrived on time</span>;
}

/**
 * The latest value, or the honest absence of one.
 *
 * Never a zero standing in for a blank, and never an empty cell a reader could mistake
 * for one. The string the API sent is printed exactly as it sent it - `16.7900%` is the
 * datum as the DMO published it, trailing zeros and all, and this app does not quietly
 * tidy a figure it was given.
 */
export function LatestValueCell({ series }: { series: MacroSeries }) {
  if (series.observation_count === 0 || series.latest_value === null) {
    return <td className="num absent">{NOT_LOADED}</td>;
  }
  return <td className="num">{withUnit(series.latest_value, series.unit)}</td>;
}

/** A calendar date, or `whenMissing` written quietly in its place. */
export function DayCell({
  iso,
  whenMissing,
}: {
  iso: string | null | undefined;
  whenMissing: string;
}) {
  const written = formatDay(iso);
  return written ? <td>{written}</td> : <td className="absent">{whenMissing}</td>;
}

import type { MacroObservation, MacroSeries } from "@/lib/api";
import { NOT_LOADED, NOT_REPORTED, count, formatDay, withUnit } from "@/lib/format";
import { Sparkline, extremes } from "@/components/sparkline";

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

/**
 * The recent shape of a series, in a table cell.
 *
 * An additive export: the overview at `/` renders the same three cells above and does
 * not fetch observations, so nothing there changes by this existing.
 *
 * `points` is what the observations endpoint returned for this series, and three
 * different absences reach here as three different things. `null` is our fetch not
 * coming back, which is `NOT_LOADED` - ours. An empty array is a series nothing has been
 * loaded into, which is the same phrase for the same reason, and the freshness pill
 * beside it already says "nothing loaded". Points that exist but carry no figures are
 * the publisher's absence and say so in their own words rather than borrowing ours.
 *
 * Every row is scaled to its own highest and lowest figure, which is what makes a
 * sparkline legible at 20 pixels and also what makes comparing two of them meaningless.
 * The page says so beneath the table.
 */
export function SparklineCell({
  series,
  points,
}: {
  series: MacroSeries;
  points: MacroObservation[] | null;
}) {
  if (points === null || points.length === 0) {
    return <td className="absent">{NOT_LOADED}</td>;
  }

  const edges = extremes(points);
  if (edges === null) {
    // Periods were loaded and not one of them carries a figure. That absence is the
    // publisher's, not ours, so it borrows the publisher's phrase - and `.absent` is
    // `white-space: nowrap`, so a longer sentence here would hold the column open at the
    // width of its own excuse.
    return <td className="absent">{NOT_REPORTED}</td>;
  }
  if (edges.plotted < 2) {
    // One point is not a line. Drawing one anyway would put a direction on the screen
    // that nobody measured.
    return <td className="absent">one period only</td>;
  }

  return (
    <td>
      <Sparkline
        points={points}
        label={
          `${series.name}: ${count(edges.plotted)} periods, ` +
          `${formatDay(edges.first.as_of_date)} to ${formatDay(edges.last.as_of_date)}, ` +
          `lowest ${withUnit(edges.low.value as string, series.unit)}, ` +
          `highest ${withUnit(edges.high.value as string, series.unit)}. ` +
          `Every figure is on this series' own page.`
        }
      />
    </td>
  );
}

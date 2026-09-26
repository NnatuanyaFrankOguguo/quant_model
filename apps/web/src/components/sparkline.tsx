import type { MacroObservation } from "@/lib/api";

/**
 * A line drawn from a macro series, in inline SVG, on the server.
 *
 * Deliberately not `lightweight-charts`, which this app uses for the interactive price
 * chart. That library is canvas: it is client-only, it has no DOM, and a screen reader
 * gets nothing from it - `DESIGN.md` §4b says as much. A macro series is a single line
 * with no crosshair and no zoom, so it costs one `<polyline>`, renders inside the server
 * component that fetched it, and takes its colours from the same custom properties as
 * everything else on the page. Nothing ships to the browser.
 *
 * What is drawn here is a *projection*: periods and figures scaled into a viewBox. AD-3
 * forbids the client deriving figures, and none is derived - no change, no average, no
 * percentage. The numbers a reader reads are printed from the API's own strings, beside
 * the picture, never read off it.
 *
 * §4b also forbids a chart implying a recommendation, so there is no shaded band, no
 * target line and no annotated level anywhere in this file. The only furniture is a rule
 * at the top and bottom of the plotted range, which says where the line can reach and
 * nothing about whether it should.
 */

/** The drawing area, in viewBox units. */
interface Box {
  width: number;
  height: number;
  pad: number;
}

const SPARK: Box = { width: 104, height: 20, pad: 3 };
const CHART: Box = { width: 960, height: 220, pad: 12 };

/**
 * Parsed for geometry only. The API's decimal string stays the figure of record and is
 * what every page prints; this number exists to decide where a pixel goes and is never
 * rendered, rounded into a caption, or combined with another figure to make a third.
 */
function figure(value: string | null): number | null {
  if (value === null) return null;
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : null;
}

/**
 * Pinned to UTC for the same reason `lib/format.ts` pins its formatter: the API sends a
 * calendar date with no time on it, and a machine west of Greenwich would otherwise place
 * every point one day early.
 */
function moment(iso: string): number {
  return Date.parse(/^\d{4}-\d{2}-\d{2}$/.test(iso) ? `${iso}T00:00:00Z` : iso);
}

/**
 * The observations at the edges of a series, so a caller can say in words what the
 * picture shows.
 *
 * Selecting the earliest, the latest, the smallest and the largest member of a list is
 * the same kind of operation as the sort on the overview page - ordering, not arithmetic.
 * Each one is an observation the API sent, and a caller prints its own `value` string
 * verbatim. No figure here is made out of two others.
 */
export interface Extremes {
  /** The period carrying the smallest figure, and the one carrying the largest. */
  low: MacroObservation;
  high: MacroObservation;
  /** The earliest and latest periods that carry a figure at all. */
  first: MacroObservation;
  last: MacroObservation;
  /** How many of the periods handed in carry a figure, and how many do not. */
  plotted: number;
  gaps: number;
}

/** Null when not one period in the set carries a figure - there is nothing to describe. */
export function extremes(points: readonly MacroObservation[]): Extremes | null {
  const carried = points.filter((point) => figure(point.value) !== null);
  if (carried.length === 0) return null;

  let low = carried[0];
  let high = carried[0];
  let first = carried[0];
  let last = carried[0];

  for (const point of carried) {
    const value = figure(point.value) as number;
    if (value < (figure(low.value) as number)) low = point;
    if (value > (figure(high.value) as number)) high = point;
    if (moment(point.as_of_date) < moment(first.as_of_date)) first = point;
    if (moment(point.as_of_date) > moment(last.as_of_date)) last = point;
  }

  return {
    low,
    high,
    first,
    last,
    plotted: carried.length,
    // Counted by filtering the list, not by subtracting one count from another. A page
    // uses it to say the line has a gap rather than letting the gap pass unremarked.
    gaps: points.filter((point) => figure(point.value) === null).length,
  };
}

interface Drawn {
  /** One `points` string per unbroken run. A period with no figure ends a run. */
  segments: string[];
  /** Where the newest plotted period landed, so it can be marked. */
  endX: number;
  endY: number;
}

/**
 * Scale the series into the box.
 *
 * Two rules matter more than the maths. **A period with no figure breaks the line** - it
 * is never joined across and it is certainly never drawn at zero, because a gap bridged
 * by a straight line is a measurement nobody took. And **the vertical axis spans the
 * figures present**, not zero to the maximum: a policy rate that moved between 26.0 and
 * 27.5 has a shape, and anchoring the axis to zero would flatten it out of existence. The
 * caller prints both ends in words beside the picture, so the scale is never a guess.
 *
 * Null when fewer than two periods carry a figure: one point is not a line, and a line
 * drawn through one point would assert a direction nobody measured.
 */
function draw(points: readonly MacroObservation[], box: Box): Drawn | null {
  const edges = extremes(points);
  if (edges === null || edges.plotted < 2) return null;

  const left = box.pad;
  const right = box.width - box.pad;
  const top = box.pad;
  const foot = box.height - box.pad;

  const tFirst = moment(edges.first.as_of_date);
  const tLast = moment(edges.last.as_of_date);
  const lowest = figure(edges.low.value) as number;
  const highest = figure(edges.high.value) as number;
  const acrossTime = tLast - tFirst;
  const acrossValue = highest - lowest;

  const place = (n: number) => Math.round(n * 100) / 100;

  // Time on the horizontal axis rather than position in the array. Several of these
  // series are irregular - the MPR changes when a committee decides to - and spacing them
  // evenly would draw a rhythm the publisher never had.
  const x = (point: MacroObservation) =>
    acrossTime === 0
      ? place((left + right) / 2)
      : place(left + ((moment(point.as_of_date) - tFirst) / acrossTime) * (right - left));
  const y = (value: number) =>
    acrossValue === 0
      ? place((top + foot) / 2)
      : place(top + ((highest - value) / acrossValue) * (foot - top));

  const segments: string[] = [];
  let run: string[] = [];
  const close = () => {
    // A run of one is written twice, so the polyline holds a zero-length segment: with a
    // round cap that renders as a dot, which keeps a lone period between two gaps on the
    // picture instead of silently dropping it.
    if (run.length === 1) segments.push(`${run[0]} ${run[0]}`);
    else if (run.length > 1) segments.push(run.join(" "));
    run = [];
  };

  for (const point of points) {
    const value = figure(point.value);
    if (value === null) {
      close();
      continue;
    }
    run.push(`${x(point)},${y(value)}`);
  }
  close();

  return { segments, endX: x(edges.last), endY: y(figure(edges.last.value) as number) };
}

/**
 * The line itself, plus a dot on the newest period.
 *
 * `vectorEffect="non-scaling-stroke"` is what lets the wide chart stretch to any column
 * width without the stroke stretching with it - and it is also what keeps that dot round,
 * since a zero-length stroke with a round cap is a circle no aspect ratio can squash. A
 * real `<circle>` would come out an ellipse on a phone.
 */
function Line({ drawn, weight, dot }: { drawn: Drawn; weight: number; dot: number }) {
  return (
    <>
      {drawn.segments.map((segment, index) => (
        <polyline
          key={index}
          points={segment}
          fill="none"
          stroke="var(--act)"
          strokeWidth={weight}
          strokeLinecap="round"
          strokeLinejoin="round"
          vectorEffect="non-scaling-stroke"
        />
      ))}
      <polyline
        points={`${drawn.endX},${drawn.endY} ${drawn.endX},${drawn.endY}`}
        fill="none"
        stroke="var(--act)"
        strokeWidth={dot}
        strokeLinecap="round"
        vectorEffect="non-scaling-stroke"
      />
    </>
  );
}

/**
 * A trend small enough to sit in a table cell.
 *
 * Returns null rather than an empty box when there is nothing to draw, so the caller
 * decides what the absence says - on `/macro` that is the phrase for a series nothing has
 * been loaded into, which is not a sentence a chart should be inventing for itself.
 */
export function Sparkline({
  points,
  label,
}: {
  points: readonly MacroObservation[];
  /** What the line shows. Required: a picture with no name is invisible to a reader. */
  label: string;
}) {
  const drawn = draw(points, SPARK);
  if (drawn === null) return null;

  return (
    <svg
      width={SPARK.width}
      height={SPARK.height}
      viewBox={`0 0 ${SPARK.width} ${SPARK.height}`}
      role="img"
      aria-label={label}
    >
      <Line drawn={drawn} weight={1.25} dot={3} />
    </svg>
  );
}

/**
 * The same line, full width, for one series' own page.
 *
 * `width="100%"` with `preserveAspectRatio="none"` is how it fits 320px and 1440px
 * without a stylesheet and without an inline style: both are SVG geometry attributes, and
 * the viewBox stretches horizontally while the height stays where it was put. No text is
 * drawn inside, because text would stretch with it - the axis is described in HTML beside
 * the picture, where it can also be read aloud.
 */
export function SeriesChart({
  points,
  label,
}: {
  points: readonly MacroObservation[];
  label: string;
}) {
  const drawn = draw(points, CHART);
  if (drawn === null) return null;

  return (
    <svg
      width="100%"
      height={CHART.height}
      viewBox={`0 0 ${CHART.width} ${CHART.height}`}
      preserveAspectRatio="none"
      role="img"
      aria-label={label}
    >
      {/* Two rules: the highest figure plotted, and the lowest. They say where the line
          can reach. Nothing is drawn between them - §4b. */}
      <line
        x1={0}
        y1={CHART.pad}
        x2={CHART.width}
        y2={CHART.pad}
        stroke="var(--line)"
        strokeWidth={1}
        vectorEffect="non-scaling-stroke"
      />
      <line
        x1={0}
        y1={CHART.height - CHART.pad}
        x2={CHART.width}
        y2={CHART.height - CHART.pad}
        stroke="var(--line)"
        strokeWidth={1}
        vectorEffect="non-scaling-stroke"
      />
      <Line drawn={drawn} weight={1.5} dot={5} />
    </svg>
  );
}

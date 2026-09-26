/**
 * The loading state for the chart — one of the four `DESIGN.md` §8 requires, and the one
 * a reader meets on every range button.
 *
 * Changing the window is a navigation rather than a redraw, because §8 keeps fetching on
 * the server: asking for five years asks the API for five years. That is a real wait and
 * it is worth saying what is being waited for, so a range change does not look like a
 * page that has stopped responding.
 *
 * No heading. The segment's layout has already drawn the `.security-head` carrying the
 * page's only `<h1>`.
 */
export default function Loading() {
  return (
    <div className="notice">
      <h2>Fetching the price history</h2>
      <p>
        Every bar is read on the server, adjusted for the corporate actions that were
        knowable on the decision date before it is sent — which is what keeps a line
        continuous across a split instead of dropping 75% on a day the stock rose. A long
        range is a lot of days.
      </p>
    </div>
  );
}

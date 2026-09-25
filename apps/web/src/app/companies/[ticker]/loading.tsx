/**
 * The loading state for one company - one of the four states `DESIGN.md` §8 requires,
 * and the one a reader meets most often: the figures are fetched on the server when the
 * page is asked for, so there is a real gap before anything can be drawn.
 *
 * No heading. Next renders this inside the segment's layout, which has already drawn the
 * `.security-head` carrying the page's only `<h1>`; a second one here would be a second
 * on the page.
 */
export default function Loading() {
  return (
    <div className="notice">
      <h2>Fetching the figures</h2>
      <p>
        The filing figures are read on the server before the page is drawn, so that every
        number arrives with the period it covers and the day it became public already
        attached to it. This takes a moment.
      </p>
    </div>
  );
}

/**
 * The loading state for everything under /companies - one of the four states
 * `DESIGN.md` §8 requires a page to handle, and a real route file rather than a spinner:
 * Next wraps the segment in a Suspense boundary for it, so a cold API - and the first
 * request to a sleeping compute is slow - shows a sentence rather than a white rectangle.
 *
 * No heading, and the wording names no particular page. This boundary is the nearest one
 * to the shared company layout as well as to the list, so it is what a reader sees while
 * either is being fetched; a heading here would be the right one for one of them and the
 * wrong one for the other.
 */
export default function Loading() {
  return (
    <div className="notice">
      <h2>Fetching from the data service</h2>
      <p>
        The figures are read on the server when the page is requested, so that every
        number arrives with the period it covers and the day it became public already
        attached to it. The first request after a quiet spell also waits for the database
        to wake up, which can take a few seconds.
      </p>
    </div>
  );
}

/**
 * The loading state, one of the three `DESIGN.md` §7 requires a page to handle. It is a
 * real route file rather than a spinner: Next wraps the segment in a Suspense boundary
 * for it, so a cold API - and the first request to a sleeping compute is slow - shows a
 * sentence rather than a white rectangle.
 */
export default function Loading() {
  return (
    <>
      <h1>Companies</h1>
      <p className="lede">
        Every company whose filings are loaded here, with how much of each one is held and
        how current it is.
      </p>
      <div className="notice">
        <h3>Fetching the company list</h3>
        <p>
          The figures are read on the server when the page is requested. The first request
          after a quiet spell waits for the database to wake up, which can take a few
          seconds.
        </p>
      </div>
    </>
  );
}

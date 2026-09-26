/**
 * The loading state, which DESIGN.md §7 requires a page to handle explicitly.
 *
 * The App Router shows this while the server-side fetch in `page.tsx` is in flight.
 * The first request of the day wakes a cold database, so this can be a few seconds -
 * long enough that a blank screen would read as a broken page.
 */
export default function LoadingMacro() {
  return (
    <>
      <h1>The economy</h1>
      <div className="notice">
        <h2>Loading the economic series</h2>
        <p>
          Fetching every series and its latest observation. The first request after a
          quiet spell wakes the database, which takes a few seconds longer than the
          rest.
        </p>
      </div>
    </>
  );
}

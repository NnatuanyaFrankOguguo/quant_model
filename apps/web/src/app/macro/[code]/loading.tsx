/**
 * The loading state, which `DESIGN.md` §8 requires a page to handle explicitly.
 *
 * It exists separately from `/macro/loading.tsx` because that one announces "fetching
 * every series and its latest observation", which is not what is happening here: this
 * segment is fetching every period of one series. A loading state that describes the
 * wrong work is worse than none, because a reader cannot tell whether the page they
 * asked for is the page that is coming.
 *
 * The heading cannot name the series - a `loading.tsx` receives no params - so it says
 * what is being fetched rather than guessing at which.
 */
export default function LoadingSeries() {
  return (
    <>
      <h1>Loading a series</h1>
      {/* An `h2`, not an `h3`: this notice follows the page's `h1` directly and §9
          allows no skipped level. */}
      <div className="notice">
        <h2>Fetching every period held</h2>
        <p>
          Each one comes with the period it describes and the date it became public. The
          first request after a quiet spell wakes the database, which takes a few seconds
          longer than the rest.
        </p>
      </div>
    </>
  );
}

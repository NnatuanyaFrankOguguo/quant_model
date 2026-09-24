import Link from "next/link";

/**
 * The loading state for one company. `DESIGN.md` §7 wants all three states handled and
 * this is the one a reader meets most often: the figures are fetched on the server when
 * the page is asked for, so there is a real gap before anything can be drawn.
 */
export default function Loading() {
  return (
    <>
      <p className="faint">
        <Link href="/companies">← All companies</Link>
      </p>
      <h1>Loading this company</h1>
      <div className="notice">
        <h3>Fetching the figures</h3>
        <p>
          The filing figures are read on the server before the page is drawn, so that
          every number arrives with the period it covers and the day it became public
          already attached to it. This takes a moment.
        </p>
      </div>
    </>
  );
}

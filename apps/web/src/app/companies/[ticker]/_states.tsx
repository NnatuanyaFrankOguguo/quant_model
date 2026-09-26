import Link from "next/link";

import { ApiError, ApiTimeout } from "@/lib/api";
import { SERVICE_IS_SLOW } from "@/lib/format";

/**
 * Every way a company's figures can fail to arrive, and what each one means.
 *
 * Three different things are three different answers. A ticker nobody holds is not a
 * fault and sends the reader back to the list. A request that outran our patience is not
 * a fault either - `DESIGN.md` §8, and it gets `.notice` rather than `.notice bad`,
 * because painting a slow answer red sends a reader looking for a break that is not
 * there. Only an actual refusal from the API gets the red rule.
 *
 * The heading inside each notice is an `<h2>`: this sits directly below the page's
 * `<h1>`, whether that came from the `.security-head` or from `withHeading` here, and an
 * `<h3>` there would skip a level.
 *
 * `withHeading` exists because this is rendered from two places. The shared layout draws
 * the `.security-head` that carries the page's only `<h1>`; when the layout itself is
 * what failed, that heading never happened and this has to supply one. When a tab below
 * a working header fails, it must not supply a second.
 */
export function CompanyProblem({
  ticker,
  error,
  withHeading,
}: {
  ticker: string;
  error: unknown;
  withHeading: boolean;
}) {
  const status = error instanceof ApiError ? error.status : null;

  if (error instanceof ApiTimeout) {
    return (
      <>
        {withHeading ? <h1>{ticker}</h1> : null}
        <div className="notice">
          <h2>This is taking longer than the page waits</h2>
          <p>{SERVICE_IS_SLOW}</p>
          <p>
            Reload the page. <Link href="/companies">Back to the list</Link>.
          </p>
        </div>
      </>
    );
  }

  if (status === 404) {
    return (
      <>
        {withHeading ? <h1>No company under “{ticker}”</h1> : null}
        <div className="notice bad">
          <h2>Nothing is held for this ticker</h2>
          <p>
            The API holds no company under <b>{ticker}</b>. It may be spelled
            differently, or it may simply not be loaded here — only a fixed set of
            companies is.
          </p>
          <p>
            <Link href="/companies">The list of every company held</Link> is the place to
            check.
          </p>
        </div>
      </>
    );
  }

  return (
    <>
      {withHeading ? <h1>{ticker}</h1> : null}
      <div className="notice bad">
        <h2>These figures could not be loaded</h2>
        <p>
          The request for this company&rsquo;s figures did not come back
          {status === null ? " at all" : ` — the API answered ${status}`}. Nothing is
          shown, because a half-loaded set of figures would be worse than none.
        </p>
        <p>
          Reload the page. If it keeps happening, the API is not answering; the{" "}
          <Link href="/data-health">data health</Link> page is where that shows up.{" "}
          <Link href="/companies">Back to the list</Link>.
        </p>
      </div>
    </>
  );
}

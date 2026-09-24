import Link from "next/link";
import { api, ApiError } from "@/lib/api";

/**
 * The front door.
 *
 * Deliberately short. `DESIGN.md` §2: a beginner is lost by answering questions they have
 * not asked yet, so this page says what the thing is, shows four figures, and offers three
 * doors. Everything else is one click away.
 */

export const metadata = {
  title: "A financial data instrument",
};

function Figure({
  value,
  name,
  note,
}: {
  value: string;
  name: string;
  note: string;
}) {
  return (
    <div className="card">
      <div className="stat-value num">{value}</div>
      <div className="stat-name">{name}</div>
      <div className="stat-note">{note}</div>
    </div>
  );
}

export default async function Home() {
  let companies = 0;
  let periods = 0;
  let unreachable: string | null = null;

  try {
    const list = await api.companies();
    companies = list.companies.length;
    periods = list.companies.reduce((n, c) => n + c.statement_periods, 0);
  } catch (error) {
    unreachable =
      error instanceof ApiError
        ? `The data service answered ${error.status}.`
        : "The data service did not answer.";
  }

  return (
    <>
      <h1>Figures with their sources attached</h1>
      <p className="lede">
        Company accounts, market prices and economic data, gathered automatically and
        stored so that every number keeps the filing it came from and the date it became
        public. This site explains what the numbers mean. It does not tell you what to do
        with them.
      </p>

      {unreachable ? (
        <div className="notice bad">
          <h3>The figures are not loading</h3>
          <p>
            {unreachable} Nothing is wrong with your browser. If you are running this
            locally, the API needs to be started — the rest of the site will work as soon
            as it is.
          </p>
        </div>
      ) : (
        <div className="grid cols-4">
          <Figure
            value={String(companies)}
            name="Companies"
            note="US filers, from SEC EDGAR"
          />
          <Figure
            value={periods.toLocaleString("en-GB")}
            name="Reporting periods"
            note="Quarters and years held"
          />
          <Figure value="14" name="Economic series" note="Nigeria and the US" />
          <Figure value="0" name="Recommendations" note="By design — see below" />
        </div>
      )}

      <div className="explain" style={{ marginTop: "var(--gap-lg)" }}>
        <span className="tag">Start here</span>
        <p>
          One idea makes everything else on this site make sense: <b>when a figure is
          about</b> and <b>when it became knowable</b> are two different dates. A
          company&rsquo;s results for 2024 are not public until well into 2025. Treating
          them as if they were is the most common way people fool themselves about the
          past.
        </p>
        <p style={{ marginBottom: 0 }}>
          <Link href="/how-to-read-this">
            How to read this site &rarr;
          </Link>
        </p>
      </div>

      <h2>Where to go</h2>
      <div className="grid cols-3">
        <div className="card">
          <h3>
            <Link href="/companies">Companies</Link>
          </h3>
          <p className="muted" style={{ marginBottom: 0, fontSize: "0.93rem" }}>
            What a company earned, owns and owes, taken from its own filings — with each
            figure explained in plain words.
          </p>
        </div>
        <div className="card">
          <h3>
            <Link href="/macro">The economy</Link>
          </h3>
          <p className="muted" style={{ marginBottom: 0, fontSize: "0.93rem" }}>
            Inflation, interest rates and exchange rates for Nigeria and the US, each with
            the date it was published.
          </p>
        </div>
        <div className="card">
          <h3>
            <Link href="/data-health">Data health</Link>
          </h3>
          <p className="muted" style={{ marginBottom: 0, fontSize: "0.93rem" }}>
            Whether the figures are current. A system that quietly stops updating is worse
            than one that says it has stopped.
          </p>
        </div>
      </div>

      <h2>Why there are no recommendations</h2>
      <p>
        This is a measuring instrument, not an adviser. It will show you a
        company&rsquo;s profit margin and explain what a margin is. It will not tell you
        whether that margin is good, and it will never suggest buying or selling
        anything.
      </p>
      <p>
        Where the site shows a valuation, that number came from assumptions{" "}
        <b>you typed in yourself</b> — change them and the answer changes. It is a
        calculator you are driving, not a verdict the system reached.
      </p>

      <details className="more">
        <summary>Why build it that way?</summary>
        <p>
          Two reasons. Giving investment advice is a regulated activity, and this system
          is deliberately not registered to do it. More importantly, a number presented as
          a verdict stops being questioned — and the entire value of keeping every
          figure&rsquo;s source attached is that you <em>can</em> question it.
        </p>
      </details>
    </>
  );
}

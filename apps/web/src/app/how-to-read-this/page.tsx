import type { Metadata } from "next";
import Link from "next/link";

export const metadata: Metadata = {
  title: "How to read this",
  description:
    "What this system is and is not, why every figure carries two dates rather than " +
    "one, why a missing number is shown as missing, and where every figure comes from.",
};

/**
 * The page that makes the rest of the site usable. No API call: nothing here depends on
 * what happens to be loaded, so there is no loading, empty or failed state to handle -
 * the page is the same on a cold database as on a full one.
 *
 * DESIGN.md §2 caps this at short sections with secondary detail folded, and §1 caps it
 * at describing and defining. Neither is a limitation here. The hard part of this page
 * is saying one idea at a time.
 */
export default function HowToReadThisPage() {
  return (
    <>
      <h1>How to read this</h1>
      <p className="lede">
        Five short things. The second one is the important one — it is the idea that
        makes everything else on this site make sense, and almost nobody is told it.
      </p>

      <h2>1. This is an instrument, not an adviser</h2>
      <p>
        A thermometer tells you it is thirty-nine degrees. It does not tell you to stay
        home from work. This site is the thermometer.
      </p>
      <p>It does three things:</p>
      <ul>
        <li>it stores published figures along with the dates that make them meaningful,</li>
        <li>it shows you those figures with the name of whoever published them, and</li>
        <li>it explains, in plain words, what each one measures.</li>
      </ul>
      <p>
        It does not do the fourth thing. It will not tell you that a figure is good or
        bad, will not say buy or sell, and will never produce a price target of its own.
        That is a deliberate limit on what the software is allowed to say, not a feature
        waiting to be added.
      </p>

      <h2>2. Two dates, and they are not the same date</h2>
      <p>
        Every figure here carries two dates. Telling them apart is the whole idea.
      </p>

      <div className="explain">
        <span className="tag">The one idea to take away</span>
        <p>
          <b>period_end</b> is <i>what the figure is about</i>. A company’s revenue for
          the year ending 31 December 2024 is about 2024. That is the stretch of time it
          measures.
        </p>
        <p>
          <b>known_as_of</b> is <i>when anybody outside the company could have known it</i>.
          Those 2024 results are not public the moment the year ends. The books are
          closed, the auditors work through them, and the annual report reaches the
          public some months into 2025. Until that filing date the figure existed in
          nobody else’s hands.
        </p>
        <p>
          So: <b>a 2024 figure is not a 2024 fact. It is a 2025 fact about 2024.</b>
        </p>
      </div>

      <h3>What it looks like on a real figure</h3>
      <div className="scroller">
        <table>
          <caption>
            The same gap, on four kinds of figure. Sometimes it is one evening. Sometimes
            it is more than a year.
          </caption>
          <thead>
            <tr>
              <th scope="col">The figure</th>
              <th scope="col">What it is about</th>
              <th scope="col">When it became knowable</th>
            </tr>
          </thead>
          <tbody>
            <tr>
              <th scope="row" className="wrap-cell">
                A company’s revenue for its 2024 financial year
              </th>
              <td className="wrap-cell">31 December 2024</td>
              <td className="wrap-cell">
                early 2025, the day the annual report was filed
              </td>
            </tr>
            <tr>
              <th scope="row" className="wrap-cell">
                A country’s inflation rate for November
              </th>
              <td className="wrap-cell">30 November</td>
              <td className="wrap-cell">
                mid-December, when the statistics bureau published it
              </td>
            </tr>
            <tr>
              <th scope="row" className="wrap-cell">
                An international agency’s annual estimate for a country
              </th>
              <td className="wrap-cell">the year 2025</td>
              <td className="wrap-cell">
                well into 2026, when that agency published its round-up
              </td>
            </tr>
            <tr>
              <th scope="row" className="wrap-cell">
                A closing share price
              </th>
              <td className="wrap-cell">that trading day</td>
              <td className="wrap-cell">that same evening, once the market shut</td>
            </tr>
          </tbody>
        </table>
      </div>
      <p className="scroll-hint">This table scrolls sideways.</p>

      <h3>Why it matters enough to build a database around</h3>
      <p>
        Because it is very easy to fool yourself, and the mistake leaves no trace.
      </p>
      <p>
        Suppose you want to know whether some rule for picking shares would have worked.
        You stand in March 2025, look back at March 2024, and ask what the rule would
        have told you then. To answer, you reach for the company’s full-year 2024
        results.
      </p>
      <p>
        But in March 2024 nobody had those results. They did not exist yet. The rule
        looks brilliant, and it looks brilliant because it was handed next year’s
        newspaper.
      </p>
      <p>
        This has a name — <b>look-ahead bias</b> — and it is the most common way a
        backtest flatters itself. In a database that stores only one date per figure it
        is undetectable, because there is nothing to check against.
      </p>
      <p>
        So this system stores both dates on every row and overwrites neither. Ask it what
        was knowable on a given day and it answers using only the rows whose{" "}
        <b>known_as_of</b> falls on or before that day. That single rule is the reason
        the schema looks the way it does, and it is the reason both dates appear beside
        every figure on every page here.
      </p>

      <details className="more">
        <summary>What happens when a figure is later revised</summary>
        <p>
          Revisions are normal. A statistics bureau restates last quarter when better
          returns come in; a company files an amended report. The first number was not a
          lie, and the second one does not erase it — both were true statements of what
          was known at the time.
        </p>
        <p>
          So a revision is stored as a new row with its own <b>known_as_of</b>, and the
          original row stays exactly as it was. Ask what was knowable before the revision
          and you get the original figure. Ask about today and you get the revised one.
          Neither answer is wrong, and the system does not have to pick.
        </p>
      </details>

      <details className="more">
        <summary>The words you will see for these two dates</summary>
        <p>
          The same idea gets slightly different labels depending on the figure. For
          company statements it is <b>period_end</b> — the last day of the period the
          statement covers. For an economic series it is <b>as_of</b>, shown on the
          economy page as <b>Covers</b>. For a price it is simply the trading date.
        </p>
        <p>
          The second date is <b>known_as_of</b> throughout, shown as{" "}
          <b>Knowable from</b>. If a page shows you a figure without it, that is a bug on
          the page, not a figure without a publication date.
        </p>
      </details>

      <h2>3. A blank is not a zero</h2>
      <p>
        Where this site does not have a number, it says so. It never fills the hole with
        a zero, and never with a blank cell that could be mistaken for one.
      </p>
      <p>
        The two mean opposite things. <b>Zero is a measurement.</b> Somebody looked and
        found none. <b>Missing means nobody looked</b> — the load has not run, or the
        source has not published yet, or the figure was never collected.
      </p>
      <p>
        Treat one as the other and the damage is silent. A zero slipped into an average
        drags it down, and nothing on the screen tells you it happened. So wherever you
        read <b>not loaded yet</b> on these pages, read it as: this system does not know,
        and would rather tell you than guess.
      </p>

      <details className="more">
        <summary>Then why does a count sometimes show zero?</summary>
        <p>
          Because a count of nothing really is zero. If a series holds no observations,
          the honest answer to “how many observations are there” is none — and the honest
          answer to “what is the latest value” is that there is not one.
        </p>
        <p>
          You can see both on the same row of the{" "}
          <Link href="/macro">economy page</Link>: a series with zero observations and no
          value at all. Same row, two different kinds of answer.
        </p>
      </details>

      <h2>4. Every figure names who published it</h2>
      <p>
        Underneath each block of figures is the attribution given by the body that
        published them, printed exactly as that body words it. It is not paraphrased, not
        shortened, and not replaced with a logo.
      </p>
      <p>Two reasons, and neither is legal box-ticking.</p>
      <p>
        You can go and check. A figure you cannot trace is a rumour with a decimal point
        in it.
      </p>
      <p>
        And sources disagree. Nigerian inflation is compiled by the National Bureau of
        Statistics, republished by the Central Bank of Nigeria, and estimated annually by
        the World Bank. This site keeps all three as separate series rather than merging
        them into one authoritative number. They are three separate publications, and
        which one you are reading is always on the screen.
      </p>

      <h2>5. Any valuation here came from assumptions you typed</h2>
      <p>
        If a page shows a value per share, it is arithmetic performed on numbers you
        entered: your growth rate, your discount rate, your terminal growth. Change any
        of them and the answer changes, sometimes by a lot.
      </p>
      <p>
        That is not a flaw in the model. That <i>is</i> the model. The output is a
        consequence of your inputs, not a discovery about the company, and the page
        always shows the inputs beside the result so that the two are never separated.
      </p>
      <p>
        This site has no view on whether the result is high or low, and is not permitted
        to invent one.
      </p>

      <h2>Where to go next</h2>
      <p>
        <Link href="/companies">Companies</Link> — filed figures and ratios, each one
        dated twice.
        <br />
        <Link href="/macro">The economy</Link> — Nigerian and US series, with what CPI
        and a policy rate actually are.
        <br />
        <Link href="/data-health">Data health</Link> — whether the jobs that load all of
        this have actually run.
      </p>

      <div className="source">
        <p>
          Nothing on this page is fetched. It describes how the rest of the site behaves,
          and it reads the same whether the database is full or empty.
        </p>
        <p>
          The two-date rule and the no-recommendations rule are not house style. They are
          written into the project’s data foundation and its design contract, and every
          page here is built to them.
        </p>
      </div>
    </>
  );
}

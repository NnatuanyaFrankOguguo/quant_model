import { ApiError, api, type Dcf, type PriceRef } from "@/lib/api";
import { day, isMissing, money, moneyCompact, percent, plain } from "@/lib/format";

/** The provenance of the stored figures the reader's own rates get joined to. */
export interface FilingRef {
  period_label: string;
  period_end: string;
  known_as_of: string;
  attribution: string;
}

export interface ValuationProps {
  ticker: string;
  currency: string;
  price: PriceRef | null;
  filing: FilingRef;
  /** Exactly what the reader typed, untouched. Undefined means the box was never sent. */
  discountRate?: string;
  growth?: string;
  terminalGrowth?: string;
  /** True once the form has been submitted at all, however incompletely. */
  submitted: boolean;
}

/**
 * The API names the query fields it rejected. Turned into words a reader can act on,
 * because "query.terminal_growth" is the API's vocabulary and not theirs.
 */
const NEEDED: Record<string, string> = {
  "query.discount_rate": "the discount rate",
  "query.growth": "the growth rate for each projected year",
  "query.terminal_growth": "the growth after the projection ends",
};

/** The order they appear in the form, so the sentence reads down the page. */
const IN_FORM_ORDER = [
  "query.discount_rate",
  "query.growth",
  "query.terminal_growth",
] as const;

/**
 * The valuation section.
 *
 * The API refuses to compute without all three rates - `DATA_FOUNDATION` 6.5's "user-set
 * assumptions only" - and that refusal is the content of this section rather than an
 * error it swallows. Nothing is prefilled, there is no default and no suggested level,
 * because a number this page put in the box would be this page's opinion wearing the
 * reader's name.
 *
 * It is a plain GET form. No JavaScript runs: the browser puts the three values in the
 * query string, the server reads them back out, and the reader's own numbers are visible
 * in the address bar where they can be checked, bookmarked or sent to somebody else.
 */
export function Valuation(props: ValuationProps) {
  const { ticker, filing, price, submitted } = props;

  return (
    <section>
      <h2 id="valuation">Put a value on it, using your own assumptions</h2>

      <div className="explain">
        <span className="tag">Why the boxes are empty</span>
        <p>
          A discounted cash flow puts a number on a company in two steps. First you say
          how much cash you think it will produce in each of the next few years. Then you
          shrink each of those future amounts down to what it is worth to you today,
          because money later is not the same as money now.
        </p>
        <p>
          Both steps are judgements, and the answer moves a long way when the judgements
          change. So this page does not make them. Nothing is calculated until all three
          boxes are filled in by you, and what comes back is the result of your numbers —
          not a view about the company.
        </p>
        <p>
          Each box wants a decimal fraction rather than a percentage: 0.075 means 7.5%.
          That example shows the format only. The level is entirely yours.
        </p>
      </div>

      <form method="get" action={`/companies/${encodeURIComponent(ticker)}#valuation`}>
        <div className="assumptions">
          <div>
            <label htmlFor="discount_rate">
              Discount rate
              <span className="hint">
                how much you shrink each future year to value it today
              </span>
            </label>
            <input
              id="discount_rate"
              name="discount_rate"
              type="text"
              inputMode="decimal"
              autoComplete="off"
              defaultValue={props.discountRate ?? ""}
            />
          </div>

          <div>
            <label htmlFor="growth">
              Growth each year
              <span className="hint">
                one rate, or one per year separated by commas — three numbers means a
                three-year projection
              </span>
            </label>
            <input
              id="growth"
              name="growth"
              type="text"
              inputMode="decimal"
              autoComplete="off"
              defaultValue={props.growth ?? ""}
            />
          </div>

          <div>
            <label htmlFor="terminal_growth">
              Growth after that, forever
              <span className="hint">
                must be below the discount rate, or the formula has no answer
              </span>
            </label>
            <input
              id="terminal_growth"
              name="terminal_growth"
              type="text"
              inputMode="decimal"
              autoComplete="off"
              defaultValue={props.terminalGrowth ?? ""}
            />
          </div>

          <div>
            <button type="submit">Calculate</button>
          </div>
        </div>
      </form>

      {submitted ? (
        <Result {...props} />
      ) : (
        <>
          <div className="notice">
            <h3>Nothing has been calculated yet</h3>
            <p>
              All three boxes are empty, and they stay empty until you fill them in. Put a
              discount rate, a growth rate for each projected year and a growth rate for
              everything afterwards, then press Calculate.
            </p>
          </div>
          {/* No figure is on screen yet, so `DESIGN.md` §5 has nothing to attach a
              `.source` block to. This says where the stored half will come from. */}
          <p className="faint">
            The starting cash flow, the net debt and the share count will come from{" "}
            {filing.period_label} and will be listed with their sources once a calculation
            has run. {filing.attribution}
            {price === null ? "" : ` ${price.attribution}`}
          </p>
        </>
      )}
    </section>
  );
}

async function Result(props: ValuationProps) {
  const { ticker, currency, price, filing } = props;

  let result: Dcf;
  try {
    result = await api.dcf(
      ticker,
      props.discountRate ?? "",
      props.growth ?? "",
      props.terminalGrowth ?? "",
    );
  } catch (error) {
    return <Refused error={error} props={props} />;
  }

  const { assumptions } = result;

  return (
    <>
      <div className="grid cols-2">
        <div className="card">
          <div className="stat-value">
            {money(result.value_per_share, result.currency)}
          </div>
          <div className="stat-name">Value per share, from your assumptions</div>
          <div className="stat-note">
            {isMissing(result.value_per_share)
              ? "no share count is held, so there is no per-share figure"
              : "arithmetic on the three rates you typed"}
          </div>
        </div>
        <div className="card">
          <div className="stat-value">
            {price === null ? "not reported" : money(price.close_raw, currency)}
          </div>
          <div className="stat-name">
            {price === null ? "Last close" : `Last close, ${day(price.date)}`}
          </div>
          <div className="stat-note">
            {price === null
              ? "no price is held for this company"
              : `that close is ${price.age_days} days old`}
          </div>
        </div>
      </div>

      <p>
        These two are not the same kind of number. The first is arithmetic on the three
        rates you typed; change any of them and it changes with them. The second is what
        the shares last traded at. This page does not say which of the two is right, does
        not treat the gap between them as a finding, and the first number is not a price
        target.
      </p>

      <details className="more">
        <summary>Year by year, and what each column is</summary>
        <div>
          <p>
            Each year&rsquo;s cash flow is the starting figure grown by your rate for that
            year. The discount factor is what one unit of currency arriving in that year
            is worth today at your discount rate — it gets smaller the further out the
            year is. The present value is those two multiplied together.
          </p>
          <div className="scroller">
            <table>
              <caption>The projection, one row for each year you asked for.</caption>
              <thead>
                <tr>
                  <th scope="col">Year</th>
                  <th scope="col" className="num">
                    Cash flow
                  </th>
                  <th scope="col" className="num">
                    Discount factor
                  </th>
                  <th scope="col" className="num">
                    Present value
                  </th>
                </tr>
              </thead>
              <tbody>
                {result.projected_free_cash_flow.map((cash, index) => (
                  <tr key={index}>
                    {/* The ordinal alone: the column header already says "Year", and a
                        row header takes `white-space: normal` without `.wrap-cell`'s
                        min-width, so "Year 1" broke onto two lines at 320px. */}
                    <th scope="row">{yearLabel(index)}</th>
                    <td className="num">{moneyCompact(cash, result.currency)}</td>
                    <td className="num">
                      {plain(result.discount_factors[index] ?? null, 4)}
                    </td>
                    <td className="num">
                      {moneyCompact(result.present_values[index] ?? null, result.currency)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          {/* Conditional on purpose. `.scroll-hint` hides at a *viewport* of 860px, but
              a table inside `details.more` sits in a container capped at `--prose` and
              frozen at 551px, so this one stops scrolling around 500px of viewport and
              the hint stays visible for another 360px. Phrased as a condition it is true
              at every width, and still tells a 320px reader what to do. */}
          <p className="scroll-hint">
            If this table is wider than your screen, it scrolls sideways rather than the
            page.
          </p>
        </div>
      </details>

      <details className="more">
        <summary>
          The totals, and how much of the answer is the part after the projection
        </summary>
        <div>
          <p>
            The projection stops after the years you gave it. The terminal value stands in
            for every year after that: it assumes the final year&rsquo;s cash carries on
            for ever, growing at the rate in your third box. The last row says how much of
            the answer came from that one assumption rather than from the years you
            projected.
          </p>
          <div className="scroller">
            <table>
              <caption>
                Every line between the projection and the per-share figure.
              </caption>
              <thead>
                <tr>
                  <th scope="col">Line</th>
                  <th scope="col" className="num">
                    Amount
                  </th>
                </tr>
              </thead>
              <tbody>
                <tr>
                  <th scope="row">Projected years, discounted and added up</th>
                  <td className="num">
                    {moneyCompact(result.sum_of_present_values, result.currency)}
                  </td>
                </tr>
                <tr>
                  <th scope="row">Terminal value, in that final year</th>
                  <td className="num">
                    {moneyCompact(result.terminal_value, result.currency)}
                  </td>
                </tr>
                <tr>
                  <th scope="row">Terminal value, brought back to today</th>
                  <td className="num">
                    {moneyCompact(result.present_value_of_terminal, result.currency)}
                  </td>
                </tr>
                <tr>
                  <th scope="row">The two together: the whole business</th>
                  <td className="num">
                    {moneyCompact(result.enterprise_value, result.currency)}
                  </td>
                </tr>
                <tr>
                  <th scope="row">Net debt, which lenders are owed first</th>
                  <td className="num">
                    {moneyCompact(assumptions.net_debt, result.currency)}
                  </td>
                </tr>
                <tr>
                  <th scope="row">What is left for shareholders</th>
                  <td className="num">
                    {moneyCompact(result.equity_value, result.currency)}
                  </td>
                </tr>
                <tr>
                  <th scope="row">Shares it is divided between</th>
                  <td className="num">{plain(assumptions.shares, 0)}</td>
                </tr>
                <tr>
                  <th scope="row">Share of the answer that is terminal value</th>
                  <td className="num">{percent(result.terminal_share_of_value)}</td>
                </tr>
              </tbody>
            </table>
          </div>
          {/* No `.scroll-hint` here at all. Two columns whose row headers wrap: measured
              at 253/551/551 against containers of 253/551/551, so it fits at every width
              and never scrolls. Not given `.wrap-cell` either - the 18rem floor would
              push it past its container and make a table that fits start scrolling,
              which on two columns hides the amount from its own label. */}
        </div>
      </details>

      <div className="source">
        <dl>
          <dt>Your rates</dt>
          <dd>
            discount {assumptions.discount_rate}, growth{" "}
            {assumptions.growth_rates.join(", ")}, then {assumptions.terminal_growth} for
            ever{assumptions.mid_year ? ", discounted mid-year" : ""}
          </dd>
          <dt>Starting cash flow</dt>
          <dd>
            {moneyCompact(assumptions.base_free_cash_flow, result.currency)} —{" "}
            {assumptions.base_free_cash_flow_source}
          </dd>
          <dt>Net debt</dt>
          <dd>
            {moneyCompact(assumptions.net_debt, result.currency)} —{" "}
            {assumptions.net_debt_source}
          </dd>
          <dt>Share count</dt>
          <dd>
            {plain(assumptions.shares, 0)}
            {assumptions.shares_source === null ? "" : ` — ${assumptions.shares_source}`}
          </dd>
          <dt>Period those came from</dt>
          <dd>
            {filing.period_label}, ended {day(filing.period_end)}, public on{" "}
            {day(filing.known_as_of)}
          </dd>
          <dt>Figures as known on</dt>
          <dd>{day(result.as_known_on)}</dd>
          <dt>Attribution</dt>
          <dd>{filing.attribution}</dd>
          {price === null ? null : (
            <>
              <dt>Price</dt>
              <dd>
                close of {day(price.date)}, knowable {day(price.known_as_of)}
              </dd>
              <dt>Price attribution</dt>
              <dd>{price.attribution}</dd>
            </>
          )}
        </dl>
      </div>
    </>
  );
}

/**
 * Every way the request can come back without a valuation. Each says which of two quite
 * different things happened: the reader has not finished saying what to assume, or the
 * assumptions cannot be valued at all.
 */
function Refused({ error, props }: { error: unknown; props: ValuationProps }) {
  if (!(error instanceof ApiError)) {
    return (
      <div className="notice bad">
        <h3>The calculation did not come back</h3>
        <p>
          The request to the API did not complete. Your figures are still in the boxes
          above — press Calculate again.
        </p>
      </div>
    );
  }

  if (error.status === 404) {
    return (
      <div className="notice bad">
        <h3>No such company</h3>
        <p>
          The API holds no company under this ticker, so there is nothing to value.
        </p>
      </div>
    );
  }

  if (error.status === 422) {
    // The API names the fields it could not parse. It cannot name an empty growth box:
    // that parameter is a comma-separated list, so "" is a perfectly good string and is
    // only rejected further in, by the model. An empty box the reader can see is still
    // an empty box, so it is added here. Nothing is assumed in its place - this reports
    // which boxes are blank, it does not decide what should be in them.
    const blank = new Set<string>(error.fields);
    if (isMissing(props.discountRate)) blank.add("query.discount_rate");
    if (isMissing(props.growth)) blank.add("query.growth");
    if (isMissing(props.terminalGrowth)) blank.add("query.terminal_growth");

    const missing = [
      ...IN_FORM_ORDER.filter((field) => blank.has(field)).map((field) => NEEDED[field]),
      ...error.fields.filter((field) => !(field in NEEDED)),
    ];
    if (missing.length > 0) {
      return (
        <div className="notice">
          <h3>Not enough assumptions yet</h3>
          <p>
            The API will not run a valuation until every rate has been set by you, in a
            form it can read — a decimal fraction, so 0.075 rather than 7.5%. Still to
            set: {missing.join(", ")}.
          </p>
          <p>
            That is the API refusing to invent a number, not a fault. A discounted cash
            flow built on a rate somebody else chose is that person&rsquo;s valuation with
            your name on it.
          </p>
        </div>
      );
    }
    return (
      <div className="notice bad">
        <h3>These assumptions cannot be valued</h3>
        <p>
          The API took the request and could not produce an answer from it. Two things
          cause that. The growth after the projection has to be <b>below</b> the discount
          rate — if cash grows for ever at least as fast as it is discounted, there is no
          finite answer. And each box has to hold a decimal fraction: 7.5 is read as 750%,
          exactly as written.
        </p>
        <p>
          It can also mean the starting figures are not in this company&rsquo;s filings.
          The calculation begins from cash from operations less what was spent on
          equipment, and from long-term debt less cash. Not every filer reports those
          lines, and where they are absent nothing is guessed in their place.
        </p>
      </div>
    );
  }

  return (
    <div className="notice bad">
      <h3>The calculation could not be run</h3>
      <p>
        The API answered {error.status}. Your figures are still in the boxes above — press
        Calculate again, and if it keeps happening the API itself is where to look.
      </p>
    </div>
  );
}

/**
 * "1", "2", "3" - the row's position in the list the API returned. It labels a row
 * rather than deriving a figure, so AD-3 is not in play; the word "Year" lives in the
 * column header, which a screen reader reads out with it.
 */
function yearLabel(index: number): string {
  return new Intl.NumberFormat("en-US").format(index + 1);
}

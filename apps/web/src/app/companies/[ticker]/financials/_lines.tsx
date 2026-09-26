import type { StatementItem, StatementPeriod } from "@/lib/api";
import {
  day,
  direction,
  money,
  moneyCompact,
  NOT_LOADED,
  NOT_REPORTED,
  sentenceCase,
  signedPercent,
} from "@/lib/format";

/**
 * What every statement line is called, which statement it belongs on, and the order it
 * is read in.
 *
 * None of this is arithmetic. Nothing here adds a line to another line, and no total is
 * assembled from its parts - `gross_profit` is printed because the API sent it, not
 * because revenue minus cost of revenue was worked out in a component. AD-3, and the
 * reason a real financial table is harder to build honestly than it looks: the obvious
 * implementation of a statement is a sum, and the obvious implementation is forbidden.
 *
 * ## Why this list is not the API's
 *
 * The statements endpoint sends `items` as a flat map of key to figure. It says nothing
 * about which statement a line sits on, what a human calls it, or what order a reader
 * expects it in - so those three things have to live somewhere, and a page is the least
 * bad place until the API carries them. That is a real cost: when the loader learns a
 * forty-seventh line, this file will not know its name.
 *
 * So it is written to degrade rather than to hide. A key that is not listed below is
 * **still rendered** - `nameFor` un-underscores it and `otherKeys` collects it into a panel
 * of its own. A line the filing reported is never silently dropped because this map has
 * not caught up.
 *
 * Measured 2026-09-25 across all 24 companies held: 46 distinct keys, every one of them
 * named here.
 */

/**
 * The names. Abbreviations are kept short on purpose: `tbody th[scope="row"]` is
 * `white-space: nowrap`, so the longest name in a panel sets the width of the label
 * column, and "Investment securities at fair value through other comprehensive income"
 * would push nine period columns off a 1280px screen on its own. FVOCI and FVTPL are
 * spelled out in the disclosure under the table instead, which is what a disclosure is
 * for.
 */
const LINE_NAMES: Record<string, string> = {
  // Income statement
  revenue: "Revenue",
  gross_earnings: "Gross earnings",
  cost_of_revenue: "Cost of revenue",
  gross_profit: "Gross profit",
  interest_income: "Interest income",
  interest_income_fvtpl: "Interest income (FVTPL)",
  net_interest_income: "Net interest income",
  fee_and_commission_income: "Fee and commission income",
  net_fee_and_commission_income: "Net fee and commission income",
  noninterest_income: "Non-interest income",
  finance_income: "Finance income",
  credit_loss_provision: "Provision for credit losses",
  loan_impairment_charges: "Loan impairment charges",
  impairment_other_financial_assets: "Impairment of other financial assets",
  rd_expense: "Research and development",
  personnel_expenses: "Personnel expenses",
  other_operating_expenses: "Other operating expenses",
  noninterest_expense: "Non-interest expense",
  operating_profit: "Operating profit",
  finance_costs: "Finance costs",
  interest_expense: "Interest expense",
  fx_loss_net: "Net foreign-exchange loss",
  net_monetary_gain: "Net monetary gain",
  profit_before_tax: "Profit before tax",
  income_tax: "Income tax",
  profit_after_tax: "Profit after tax",

  // Balance sheet
  cash: "Cash and equivalents",
  loans_and_advances_to_banks: "Loans and advances to banks",
  loans_and_advances_to_customers: "Loans and advances to customers",
  investment_securities_fvtpl: "Investment securities (FVTPL)",
  investment_securities_fvoci: "Investment securities (FVOCI)",
  investment_securities_amortised_cost: "Investment securities (amortised cost)",
  current_assets: "Current assets",
  total_assets: "Total assets",
  deposits_from_banks: "Deposits from banks",
  deposits_from_customers: "Deposits from customers",
  other_borrowed_funds: "Other borrowed funds",
  current_liabilities: "Current liabilities",
  long_term_debt: "Long-term debt",
  total_liabilities: "Total liabilities",
  total_equity: "Total equity",

  // Cash flow
  cash_from_ops: "Cash from operations",
  depreciation_amortisation: "Depreciation and amortisation",
  capex: "Capital expenditure",
  dividends_paid: "Dividends paid",
  buybacks: "Share buybacks",
};

/**
 * The name for a key, or a readable fallback for one this file has not met.
 *
 * The fallback is deliberately plain rather than clever. "no_mapping" is a phrase this
 * app reserves for an absence, and a guessed-at pretty name would be a worse lie than an
 * un-underscored key.
 */
export function nameFor(key: string): string {
  return LINE_NAMES[key] ?? sentenceCase(key.replace(/_/g, " "));
}

/**
 * Reading order, top of the statement to the bottom.
 *
 * Both shapes are in one list rather than in a corporate list and a bank list, because a
 * company is not asked which it is: a row appears when the filing carried that line and
 * does not when it did not. JPMorgan has no `gross_profit` and Apple has no
 * `net_interest_income`, and neither of those is a gap in this page.
 */
const INCOME = [
  "revenue",
  "gross_earnings",
  "cost_of_revenue",
  "gross_profit",
  "interest_income",
  "interest_income_fvtpl",
  "net_interest_income",
  "fee_and_commission_income",
  "net_fee_and_commission_income",
  "noninterest_income",
  "finance_income",
  "credit_loss_provision",
  "loan_impairment_charges",
  "impairment_other_financial_assets",
  "rd_expense",
  "personnel_expenses",
  "other_operating_expenses",
  "noninterest_expense",
  "operating_profit",
  "finance_costs",
  "interest_expense",
  "fx_loss_net",
  "net_monetary_gain",
  "profit_before_tax",
  "income_tax",
  "profit_after_tax",
];

const BALANCE = [
  "cash",
  "loans_and_advances_to_banks",
  "loans_and_advances_to_customers",
  "investment_securities_fvtpl",
  "investment_securities_fvoci",
  "investment_securities_amortised_cost",
  "current_assets",
  "total_assets",
  "deposits_from_banks",
  "deposits_from_customers",
  "other_borrowed_funds",
  "current_liabilities",
  "long_term_debt",
  "total_liabilities",
  "total_equity",
];

const CASHFLOW = [
  "cash_from_ops",
  "depreciation_amortisation",
  "capex",
  "dividends_paid",
  "buybacks",
];

export interface StatementSection {
  /** The panel head, and the key this section is rendered under. */
  title: string;
  caption: string;
  keys: string[];
  /** What is said instead of a table when this company reported none of these lines. */
  absent: string;
}

export const SECTIONS: StatementSection[] = [
  {
    title: "Income statement",
    caption:
      "What the company took in over each period and what it had left, line by line, " +
      "newest period first.",
    keys: INCOME,
    absent:
      "None of the income-statement lines this app normalises appears in any of the " +
      "filings shown. Nothing has been estimated in their place, and no zero is " +
      "standing in for a blank.",
  },
  {
    title: "Balance sheet",
    caption:
      "What the company held and what it owed on the last day of each period, newest " +
      "period first.",
    keys: BALANCE,
    absent:
      "None of the balance-sheet lines this app normalises appears in any of the " +
      "filings shown. Nothing has been estimated in their place, and no zero is " +
      "standing in for a blank.",
  },
  {
    title: "Cash flow",
    caption:
      "What cash moved over each period, and where it went, newest period first.",
    keys: CASHFLOW,
    absent:
      "None of the cash-flow lines this app normalises appears in any of the filings " +
      "shown. Nothing has been estimated in their place, and no zero is standing in " +
      "for a blank.",
  },
];

/** Every key the three sections already claim, so `otherKeys` can find the rest. */
const CLAIMED = new Set([...INCOME, ...BALANCE, ...CASHFLOW]);

/**
 * Every key the API sent for these periods that no section above lists.
 *
 * Empty today. It exists so that a line added to the loader tomorrow appears on the page
 * the same day, in a panel of its own, rather than being dropped by a map that did not
 * know about it.
 */
export function otherKeys(periods: StatementPeriod[]): string[] {
  const seen = new Set<string>();
  for (const period of periods) {
    for (const key of Object.keys(period.items)) {
      if (!CLAIMED.has(key)) seen.add(key);
    }
  }
  return [...seen].sort();
}

/** What one cell is: a figure, an absence that is ours, or an absence that is the filer's. */
function stateOf(item: StatementItem | undefined): "figure" | "ours" | "filers" {
  // Not in this period's document at all - the same fact as an empty line, and the
  // filer's rather than ours.
  if (item === undefined) return "filers";
  if (item.value === null || item.value.trim() === "") {
    return item.absent_because === "no_mapping" ? "ours" : "filers";
  }
  return "figure";
}

export interface SectionRows {
  /** Lines at least one shown period has a figure for. These get rows. */
  live: string[];
  /** Lines every shown period left empty, where at least one absence is ours. */
  ours: string[];
  /** Lines every shown period left empty, all of them the filer's. */
  filers: string[];
}

/**
 * Which lines of a section get a row, and which get a sentence.
 *
 * Three outcomes, because there are three different facts:
 *
 * - **A line with a figure in at least one shown period gets a row**, absences and all.
 *   Those absences are the interesting ones — Apple reported interest expense until
 *   FY2023 and stopped, and the row is where that shows.
 * - **A line every shown period left empty gets named in a sentence instead.** This is
 *   `DESIGN.md` §6 exactly: "when every headline figure in a section is absent, do not
 *   render the figures — render one `.notice` saying which lines are missing and why."
 *   JPMorgan's income statement has eight such lines, and eighty cells of "not reported"
 *   would bury the ten rows that say something.
 * - **A line no shown filing mentions at all is dropped**, because printing it would
 *   assert that a bank failed to report a cost of revenue.
 *
 * The two sentence lists are kept apart because the absences are. `no_mapping` is ours
 * and somebody could fix it; `not_in_filing` is the filer's and nobody can.
 */
export function splitSection(keys: string[], periods: StatementPeriod[]): SectionRows {
  const live: string[] = [];
  const ours: string[] = [];
  const filers: string[] = [];

  for (const key of keys) {
    if (!periods.some((period) => period.items[key] !== undefined)) continue;
    const states = periods.map((period) => stateOf(period.items[key]));
    if (states.includes("figure")) live.push(key);
    else if (states.includes("ours")) ours.push(key);
    else filers.push(key);
  }

  return { live, ours, filers };
}

/**
 * The lines a section holds but every shown period left empty, said once.
 *
 * The phrases are the constants from `@/lib/format`, never typed out here - `DESIGN.md`
 * §6 forbids a page writing either of them, and that has to include writing one in a
 * sentence rather than in a cell.
 */
export function AbsentLines({ rows }: { rows: SectionRows }) {
  if (rows.ours.length === 0 && rows.filers.length === 0) return null;
  return (
    <div className="panel-body">
      <div className="notice">
        {rows.filers.length === 0 ? null : (
          <p>
            <b>{sentenceCase(NOT_REPORTED)}</b> in any filing shown, so no row is drawn
            for them: {rows.filers.map(nameFor).join(", ")}. The documents do not carry
            these lines, which is the filer&rsquo;s choice and not a fault. No zero is
            standing in for one.
          </p>
        )}
        {rows.ours.length === 0 ? null : (
          <p>
            <b>{sentenceCase(NOT_LOADED)}</b>, so no row is drawn for them:{" "}
            {rows.ours.map(nameFor).join(", ")}. The filings have a tag for these and
            nothing has been mapped to them here. That absence is ours.
          </p>
        )}
      </div>
    </div>
  );
}

/** How a single figure is written, and whether what came out is an absence. */
function figureOf(
  item: StatementItem | undefined,
  currency: string,
): { text: string; absent: boolean } {
  // The schema's own two kinds of absence, kept apart by `stateOf` so that a cell and
  // the sentence that replaces a whole row of them can never disagree. `no_mapping` is
  // ours; `not_in_filing`, and a key the document does not carry at all, are the
  // filer's and are not a fault.
  switch (stateOf(item)) {
    case "ours":
      return { text: NOT_LOADED, absent: true };
    case "filers":
      return { text: NOT_REPORTED, absent: true };
  }

  const written = moneyCompact(item?.value ?? null, currency);
  // `moneyCompact` answers with an absence phrase if the string will not parse, and a
  // page must not then style it as a figure.
  return { text: written, absent: written === NOT_REPORTED };
}

/**
 * What the hover text on a cell says.
 *
 * An enhancement, never the only place a fact lives: the exact amount is a rounded
 * compact one on screen, the period is in the column head, and the vintage of every
 * column is in the provenance table under the statements. This just puts all three
 * together for a reader with a pointer.
 */
function cellTitle(item: StatementItem, period: StatementPeriod): string {
  const exact = money(item.value, period.currency);
  const base = `${exact} · ${period.period_label}, ended ${day(period.period_end)} · knowable ${day(item.known_as_of)}`;
  if (!item.restated) return base;
  const before =
    item.previous_value === null
      ? NOT_REPORTED
      : money(item.previous_value, period.currency);
  return `${base} · restated; read ${before} until ${day(item.known_as_of)}`;
}

/** True when any shown cell of this section was changed after it was first published. */
export function hasRestatement(keys: string[], periods: StatementPeriod[]): boolean {
  return periods.some((period) => keys.some((key) => period.items[key]?.restated === true));
}

/**
 * The statements table: line items down, fiscal periods across, newest period first.
 *
 * This is the shape the whole page exists for, and the shape is not negotiable in either
 * direction - a reader of a research site expects to run a finger down `Revenue` and
 * across the years, and transposing it to fit a phone would be a different table. So it
 * scrolls inside `.scroller` instead, which `DESIGN.md` §7 requires and which is why
 * every cell here is `nowrap`: `.num` supplies it for the figures, and one wrapped cell
 * doubles the height of a row that has twenty of them.
 *
 * The last column is the API's own `change_yoy` for the newest period. It is read off
 * `StatementItem`, never worked out from two cells of this table - which would be AD-3
 * arithmetic, and would also be wrong wherever the two periods came from filings with
 * different vintages.
 */
export function StatementTable({
  caption,
  keys,
  periods,
  restatementLegend,
}: {
  caption: string;
  keys: string[];
  /** Newest first, already narrowed to what this page is showing. */
  periods: StatementPeriod[];
  /** Whether the caption should explain the R marker. Only when there is one to explain. */
  restatementLegend: boolean;
}) {
  const newest = periods[0];
  // The change column is only meaningful if it can be labelled with both periods.
  const comparison = periods.length > 1 ? periods[1] : undefined;

  return (
    <table>
      <caption>
        {caption}
        {restatementLegend ? (
          <>
            {" "}
            <b>R</b> marks a figure a later filing changed after it was first published;
            the restatements table below gives both readings.
          </>
        ) : null}
      </caption>
      <thead>
        <tr>
          <th scope="col">Line</th>
          {periods.map((period) => (
            <th scope="col" className="num" key={period.period_label}>
              {period.period_label}
              <br />
              <span className="hint">{day(period.period_end)}</span>
            </th>
          ))}
          {comparison === undefined ? null : (
            <th scope="col" className="num">
              Change
              <br />
              <span className="hint">
                {newest.period_label} on {comparison.period_label}
              </span>
            </th>
          )}
        </tr>
      </thead>
      <tbody>
        {keys.map((key) => (
          <tr key={key}>
            <th scope="row">{nameFor(key)}</th>
            {periods.map((period) => {
              const item = period.items[key];
              const { text, absent } = figureOf(item, period.currency);
              return (
                <td
                  key={period.period_label}
                  className={absent ? "num absent" : "num"}
                  title={item && item.value !== null ? cellTitle(item, period) : undefined}
                >
                  {text}
                  {item?.restated ? <span className="hint"> R</span> : null}
                </td>
              );
            })}
            {comparison === undefined ? null : (
              <ChangeCell item={newest.items[key]} />
            )}
          </tr>
        ))}
      </tbody>
    </table>
  );
}

/**
 * The move on the year, exactly as the API sent it.
 *
 * `.delta` draws the arrow, and the arrow rather than the colour is what carries the
 * direction for a reader who cannot separate red from green - `DESIGN.md` §5. An absent
 * move stays absent: a line with no prior period has no move, and rendering that as
 * `.delta.flat` would assert that the figure did not change, which is a different claim
 * from not knowing.
 */
function ChangeCell({ item }: { item: StatementItem | undefined }) {
  const raw = item?.change_yoy ?? null;
  const written = signedPercent(raw);
  const way = direction(raw);
  if (written === null || way === null) {
    return <td className="num absent">{NOT_REPORTED}</td>;
  }
  return (
    <td className="num">
      <span className={`delta ${way}`}>{written}</span>
    </td>
  );
}

/**
 * Every restated figure among the shown periods, newest period first.
 *
 * This table is the reason the schema has a `known_as_of` on every line rather than one
 * date on the filing. A restated FY2018 read today is not the FY2018 anybody saw in
 * 2018, and until something prints both readings side by side that claim is a sentence
 * in a design document rather than a fact on a screen. Measured on Apple: 48 of its 406
 * line-figures have been changed since first publication; on JPMorgan, 123 of 494.
 *
 * Nothing is compared here. Both readings and both dates come off the same
 * `StatementItem`, and the page never subtracts one from the other.
 */
export function RestatementTable({ rows }: { rows: RestatedRow[] }) {
  return (
    <table>
      <caption>
        Figures a later filing changed after they were first published — the reading now,
        the reading before it, and the day each became knowable.
      </caption>
      <thead>
        <tr>
          <th scope="col">Line</th>
          <th scope="col">Period</th>
          <th scope="col" className="num">
            Reading now
          </th>
          <th scope="col">Knowable from</th>
          <th scope="col" className="num">
            Reading before
          </th>
          <th scope="col">Was knowable from</th>
          <th scope="col" className="num">
            Vintage
          </th>
        </tr>
      </thead>
      <tbody>
        {rows.map(({ period, key, item }) => {
          const now = figureOf(item, period.currency);
          const before =
            item.previous_value === null
              ? { text: NOT_REPORTED, absent: true }
              : {
                  text: moneyCompact(item.previous_value, period.currency),
                  absent: false,
                };
          return (
            <tr key={`${period.period_label}-${key}`}>
              <th scope="row">{nameFor(key)}</th>
              <td className="nowrap">{period.period_label}</td>
              <td className={now.absent ? "num absent" : "num"}>{now.text}</td>
              <td className="nowrap">{day(item.known_as_of)}</td>
              <td className={before.absent ? "num absent" : "num"}>{before.text}</td>
              <td className={item.previous_known_as_of === null ? "nowrap absent" : "nowrap"}>
                {item.previous_known_as_of === null
                  ? NOT_REPORTED
                  : day(item.previous_known_as_of)}
              </td>
              <td className="num">{item.version}</td>
            </tr>
          );
        })}
      </tbody>
    </table>
  );
}

export interface RestatedRow {
  period: StatementPeriod;
  key: string;
  item: StatementItem;
}

/**
 * The shown cells a later filing changed, newest period first.
 *
 * Selection, not derivation: every row is a `StatementItem` the API flagged `restated`,
 * picked out and re-ordered. Nothing is counted for display and nothing is compared -
 * `DESIGN.md` §8's one client component "selects rows, it does not derive figures", and
 * this is the same move.
 */
export function restatedRows(periods: StatementPeriod[], keys: string[]): RestatedRow[] {
  const rows: RestatedRow[] = [];
  for (const period of periods) {
    for (const key of keys) {
      const item = period.items[key];
      if (item?.restated) rows.push({ period, key, item });
    }
  }
  return rows;
}

/**
 * Where each column of the statements above came from.
 *
 * A period and a vintage are two different facts and this is the table that keeps them
 * apart: the period ended on one date and became knowable on another, out of a named
 * document with an accession number that can be opened at the SEC. It also answers a
 * question the statements table raises and cannot itself explain - JPMorgan's five most
 * recent fiscal years are read from a DEF 14A proxy rather than a 10-K, which is why
 * they carry eighteen lines where FY2020 carries thirty-two.
 */
export function ProvenanceTable({ periods }: { periods: StatementPeriod[] }) {
  return (
    <table>
      <caption>
        The document each period above was read from, and the two dates that are not the
        same thing: when the period ended, and when anybody could know it.
      </caption>
      <thead>
        <tr>
          <th scope="col">Period</th>
          <th scope="col">Period ended</th>
          <th scope="col">Filing</th>
          <th scope="col">Filed</th>
          <th scope="col">Knowable from</th>
          <th scope="col">Accession</th>
        </tr>
      </thead>
      <tbody>
        {periods.map((period) => (
          <tr key={period.period_label}>
            <th scope="row">{period.period_label}</th>
            <td className="nowrap">{day(period.period_end)}</td>
            <td className="nowrap">{period.filing_type}</td>
            <td className="nowrap">{day(period.filing_date)}</td>
            <td className="nowrap">{day(period.known_as_of)}</td>
            <td className="nowrap">
              {period.filing_url === null ? (
                period.accession_no
              ) : (
                <a href={period.filing_url} rel="noreferrer nofollow" target="_blank">
                  {period.accession_no}
                </a>
              )}
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

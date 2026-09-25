import type { ReactNode } from "react";

import { money, moneyCompact, percent, ratio } from "@/lib/format";

import { NumCell } from "../_ui";

/**
 * What every figure on a company page is called and how it is written.
 *
 * One table of names, shared by the tabs, so "Liabilities to assets" cannot be one thing
 * on the overview and another on the financials. Nothing here derives a figure: `write`
 * picks a formatter from `@/lib/format` and hands it the string the API sent. AD-3.
 */

/** Which formatter a figure takes. The API sends every one of them as a decimal string. */
export type Shape = "percent" | "ratio" | "money" | "compact";

export interface FigureSpec {
  /** The API's own key, inside `ratios` or `inputs`. */
  key: string;
  name: string;
  shape: Shape;
  /**
   * A shorter label for a `.metrics` cell.
   *
   * `.metric-name` is `white-space: nowrap` with `text-overflow: ellipsis`, so the design
   * system expects a short label there and quietly cuts a long one. A cell is about 167px
   * wide at a 1280px viewport and narrower still on a large monitor, which fits roughly
   * eighteen characters. A name longer than that gets one of these; the full name is what
   * the Financials tables and the disclosures use, where there is room for it.
   */
  short?: string;
}

/**
 * The figure, written. Returns one of the two absence phrases when the API sent null,
 * because every formatter in `@/lib/format` already does - which is what keeps the
 * phrases out of the pages.
 */
export function write(
  spec: FigureSpec,
  values: Record<string, string | null>,
  currency: string,
): string {
  const raw = values[spec.key] ?? null;
  switch (spec.shape) {
    case "percent":
      return percent(raw);
    case "ratio":
      return ratio(raw);
    case "money":
      return money(raw, currency);
    case "compact":
      return moneyCompact(raw, currency);
  }
}

/** True when the API sent a value for this figure at all. */
export function reported(
  spec: FigureSpec,
  values: Record<string, string | null>,
): boolean {
  const raw = values[spec.key];
  return raw !== null && raw !== undefined && raw.trim() !== "";
}

/** True when the API returned this key at all, whatever it put in it. */
export function offered(
  spec: FigureSpec,
  values: Record<string, string | null>,
): boolean {
  return Object.prototype.hasOwnProperty.call(values, spec.key);
}

// ---------------------------------------------------------------------------
// The ratios, grouped. Every one of the API's twenty-six keys appears exactly once.
//
// Margins are their own group rather than being folded in with the returns, and that is
// not tidiness. Three of the twenty-four companies held report none of the four - bank
// accounting has no cost of making a product to set against sales - and a group of its
// own is what lets the page replace all four with one sentence instead of printing four
// absences in a row.
// ---------------------------------------------------------------------------

export interface FigureGroup {
  title: string;
  caption: string;
  figures: FigureSpec[];
  /** The one line the disclosure shows while closed. A statement, never a question. */
  brief: string;
  detail: ReactNode;
  /**
   * What is said instead of the table when the API reported none of the group.
   *
   * `DESIGN.md` §6: when every figure in a section is absent, the figures are not drawn
   * at all and one `.notice` says which lines are missing and why. Most groups take the
   * general sentence; margins have a specific reason and say it.
   */
  absent?: ReactNode;
}

export const MARGINS: FigureSpec[] = [
  { key: "gross_margin", name: "Gross margin", shape: "percent" },
  { key: "operating_margin", name: "Operating margin", shape: "percent" },
  { key: "net_margin", name: "Net margin", shape: "percent" },
  { key: "fcf_margin", name: "Free cash flow margin", shape: "percent" },
];

/**
 * What to lead with when all four margins are absent, in this fixed order.
 *
 * Deterministic, so two banks lead with the same figures in the same places, and drawn
 * only from figures this company's pages explain elsewhere - it can never put a word in
 * the lead that the reader meets nowhere else.
 */
export const FALLBACK_LEAD: FigureSpec[] = [
  { key: "roe", name: "Return on equity", shape: "percent" },
  { key: "roa", name: "Return on assets", shape: "percent" },
  { key: "eps", name: "Earnings per share", shape: "money" },
  { key: "liabilities_to_assets", name: "Liabilities to assets", shape: "ratio" },
];

/** The market's own figures: what the shares cost, set against what the filings report. */
export const MULTIPLES: FigureSpec[] = [
  { key: "market_cap", name: "Market cap", shape: "compact" },
  { key: "enterprise_value", name: "Enterprise value", shape: "compact" },
  { key: "pe", name: "Price to earnings", shape: "ratio" },
  { key: "pb", name: "Price to book", shape: "ratio" },
  { key: "ps", name: "Price to sales", shape: "ratio" },
  { key: "ev_sales", name: "EV to sales", shape: "ratio" },
  { key: "ev_ebitda", name: "EV to EBITDA", shape: "ratio" },
  { key: "earnings_yield", name: "Earnings yield", shape: "percent" },
  { key: "fcf_yield", name: "Free cash flow yield", shape: "percent", short: "FCF yield" },
  { key: "dividend_yield", name: "Dividend yield", shape: "percent" },
];

/**
 * The overview's market row: the ten multiples, plus the two per-share figures the first
 * two of them divide by, so the arithmetic is visible in one place.
 *
 * Twelve and not ten for a reason that is presentational but real. `.metrics` is
 * `repeat(auto-fit, minmax(min(100%, 148px), 1fr))`, and `auto-fit` only collapses a
 * track that is empty in *every* row - so a count that does not fill its last row leaves
 * the grid's own background showing as a grey block at the end of it. Twelve divides by
 * the six columns a 1280px viewport gives, the four a 768px one gives, and the one a
 * phone gives. Ten does not.
 */
export const OVERVIEW_MARKET: FigureSpec[] = [
  ...MULTIPLES,
  { key: "eps", name: "Earnings per share", shape: "money" },
  { key: "book_value_per_share", name: "Book value per share", shape: "money" },
];

/**
 * Held back to refill the market row when the lead has already taken one of its figures.
 *
 * No figure is shown twice on one page: when the four margins are absent the lead falls
 * back to the returns, which includes earnings per share, and the market row would
 * otherwise print the same amount a second time two inches lower.
 */
export const MARKET_RESERVE: FigureSpec[] = [
  {
    key: "fcf_per_share",
    name: "Free cash flow per share",
    shape: "money",
    short: "FCF per share",
  },
  { key: "free_cash_flow", name: "Free cash flow", shape: "compact" },
  { key: "net_debt", name: "Net debt", shape: "compact" },
];

export const RATIO_GROUPS: FigureGroup[] = [
  {
    title: "Margins",
    caption:
      "How much of every 100 taken from customers was still there after a set of costs.",
    figures: MARGINS,
    brief: "A margin is the share of sales left after a particular set of costs.",
    absent: (
      <p>
        This filing reports none of the four margins. A margin measures profit against
        sales, so it needs both — and banks and insurers commonly report neither in that
        shape, because they have no cost of making a product to set against what they
        sold. Nothing has been estimated in their place and no zero is standing in for a
        blank.
      </p>
    ),
    detail: (
      <>
        <p>
          A margin answers one question: out of every 100 the company took from its
          customers, how much was still there after a particular set of costs? The first
          three take out more each time — first what it cost to make the product, then the
          cost of running the company, then interest and tax.
        </p>
        <p>
          The fourth counts cash instead of profit, and the two are not the same number.
          Profit records a sale on the day it is made; cash records it on the day the
          money actually arrives.
        </p>
        <p>
          A margin is a share of sales, so it says nothing about how large a company is —
          only how much of what came in stayed in.
        </p>
      </>
    ),
  },
  {
    title: "Returns",
    caption: "The year's profit set against the money behind it.",
    figures: [
      { key: "roe", name: "Return on equity", shape: "percent" },
      { key: "roa", name: "Return on assets", shape: "percent" },
    ],
    brief: "A return sets the year's profit against the money that produced it.",
    detail: (
      <>
        <p>
          <b>Return on equity</b> measures the year&rsquo;s profit against the money the
          owners have in the company. At 15%, there was 15 of profit in the year for every
          100 of owners&rsquo; money.
        </p>
        <p>
          <b>Return on assets</b> measures the same profit against everything the company
          owns, whoever paid for it. It comes out below return on equity whenever any of
          those things were paid for with borrowed money.
        </p>
      </>
    ),
  },
  {
    title: "Per share",
    caption: "The same year, divided by the number of shares it is spread across.",
    figures: [
      { key: "eps", name: "Earnings per share", shape: "money" },
      { key: "book_value_per_share", name: "Book value per share", shape: "money" },
      { key: "fcf_per_share", name: "Free cash flow per share", shape: "money" },
    ],
    brief: "A per-share figure is the slice of something sitting behind one share.",
    detail: (
      <>
        <p>
          <b>Earnings per share</b> is the year&rsquo;s profit divided by the number of
          shares: the slice of that profit sitting behind one share. It is not money paid
          to you. It stays inside the company unless some of it is handed out as a
          dividend.
        </p>
        <p>
          <b>Book value per share</b> does the same with the money the owners have in the
          company, and <b>free cash flow per share</b> with the cash the business
          generated after paying for its equipment.
        </p>
        <p>
          The share count used is the one true as of the price date, not today&rsquo;s — a
          bonus issue changes the denominator with no cash moving.
        </p>
      </>
    ),
  },
  {
    title: "What it owns and what it owes",
    caption: "Things the company has, set against the money it owes.",
    figures: [
      { key: "current_ratio", name: "Current ratio", shape: "ratio" },
      { key: "debt_to_equity", name: "Debt to equity", shape: "ratio" },
      { key: "liabilities_to_assets", name: "Liabilities to assets", shape: "ratio" },
      { key: "interest_coverage", name: "Interest coverage", shape: "ratio" },
      { key: "net_debt", name: "Net debt", shape: "compact" },
    ],
    brief:
      "Four of these are ratios: a ratio of 2 means the first thing is twice the size of the second.",
    detail: (
      <>
        <p>
          <b>Current ratio</b> — things it could turn into cash within a year, divided by
          the bills due within a year. At 1.00 the two are the same size. Below 1.00 the
          bills due within the year are the larger of the two; above 1.00 the resources
          are.
        </p>
        <p>
          <b>Debt to equity</b> — long-term borrowing divided by the money the owners have
          in the company. At 1.00 there is one unit borrowed for every unit the owners put
          in.
        </p>
        <p>
          <b>Liabilities to assets</b> — everything owed divided by everything owned. At
          0.60, 60 of every 100 of what the company owns is owed to somebody else and the
          other 40 belongs to the owners.
        </p>
        <p>
          <b>Interest coverage</b> — profit from operating the business, divided by the
          interest bill for the year. At 5, the year&rsquo;s operating profit was five
          times the interest due on the borrowing.
        </p>
        <p>
          <b>Net debt</b> — long-term borrowing with the cash on hand taken off. A
          negative figure means there is more cash on hand than long-term borrowing.
        </p>
      </>
    ),
  },
  {
    title: "Cash, and profit before the deductions",
    caption: "Two amounts rather than ratios, for the same period as everything else.",
    figures: [
      { key: "free_cash_flow", name: "Free cash flow", shape: "compact" },
      { key: "ebitda", name: "EBITDA", shape: "compact" },
    ],
    brief:
      "Free cash flow is cash left after equipment; EBITDA is profit with four things added back.",
    detail: (
      <>
        <p>
          <b>Free cash flow</b> is the cash the business generated over the year, after
          paying for the equipment and property it bought. It is the figure the valuation
          tab starts from.
        </p>
        <p>
          <b>EBITDA</b> — the name is the list of what has been left out: Earnings Before
          Interest, Tax, Depreciation and Amortisation. It is not a line in the accounts;
          it is put together by adding those four back on, and it is here because it is
          quoted so widely.
        </p>
      </>
    ),
  },
  {
    title: "What the market is paying",
    caption: "The close at the top of this page, set against the filing.",
    figures: MULTIPLES,
    brief: "A multiple divides what the shares cost by a figure from the filings.",
    detail: (
      <>
        <p>
          <b>Market cap</b> is the share price multiplied by the share count: what all the
          company&rsquo;s shares cost at that close. <b>Enterprise value</b> adds the net
          debt on top, because a buyer takes on the borrowing as well.
        </p>
        <p>
          The five ratios divide one of those two by a figure from the filings — earnings,
          book value, sales, or EBITDA. A price to earnings of 20 means the shares cost
          twenty times the year&rsquo;s profit per share.
        </p>
        <p>
          The three yields turn the same comparison the other way up and write it as a
          percentage, so an earnings yield of 5% is the same fact as a price to earnings
          of 20. A dividend yield is the only one of the three that is money actually paid
          out.
        </p>
        <p>
          Every one of them uses the close shown at the top of this page, which is days
          old, and the period stated below. None of them says whether a price is right.
        </p>
      </>
    ),
  },
];

// ---------------------------------------------------------------------------
// The filing lines the ratios were built from.
//
// Which keys arrive depends on how the company files: a bank sends deposits and loans
// where a manufacturer sends revenue and cost of revenue. So these groups are filtered
// against the keys the API actually returned for this company. A key missing from the
// response is not a missing figure - it is a line that does not exist in this kind of
// filing, and printing "not reported" against it would say something untrue.
// ---------------------------------------------------------------------------

export const INPUT_GROUPS: { title: string; caption: string; figures: FigureSpec[] }[] = [
  {
    title: "From the income statement",
    caption: "What came in over the period, and what was taken out of it.",
    figures: [
      { key: "revenue", name: "Revenue", shape: "compact" },
      { key: "gross_earnings", name: "Gross earnings", shape: "compact" },
      { key: "net_interest_income", name: "Net interest income", shape: "compact" },
      { key: "cost_of_revenue", name: "Cost of revenue", shape: "compact" },
      { key: "gross_profit", name: "Gross profit", shape: "compact" },
      { key: "rd_expense", name: "Research and development", shape: "compact" },
      { key: "operating_profit", name: "Operating profit", shape: "compact" },
      { key: "interest_expense", name: "Interest expense", shape: "compact" },
      { key: "income_tax", name: "Income tax", shape: "compact" },
      { key: "profit_after_tax", name: "Profit after tax", shape: "compact" },
    ],
  },
  {
    title: "From the balance sheet",
    caption: "What the company held on the last day of the period.",
    figures: [
      { key: "total_assets", name: "Total assets", shape: "compact" },
      { key: "current_assets", name: "Current assets", shape: "compact" },
      { key: "cash", name: "Cash and equivalents", shape: "compact" },
      {
        key: "loans_and_advances_to_customers",
        name: "Loans and advances to customers",
        shape: "compact",
      },
      {
        key: "loans_and_advances_to_banks",
        name: "Loans and advances to banks",
        shape: "compact",
      },
      {
        key: "investment_securities_amortised_cost",
        name: "Investment securities, at amortised cost",
        shape: "compact",
      },
      {
        key: "investment_securities_fvoci",
        name: "Investment securities, at fair value through other comprehensive income",
        shape: "compact",
      },
      {
        key: "investment_securities_fvtpl",
        name: "Investment securities, at fair value through profit or loss",
        shape: "compact",
      },
      { key: "total_liabilities", name: "Total liabilities", shape: "compact" },
      { key: "current_liabilities", name: "Current liabilities", shape: "compact" },
      {
        key: "deposits_from_customers",
        name: "Deposits from customers",
        shape: "compact",
      },
      { key: "deposits_from_banks", name: "Deposits from banks", shape: "compact" },
      { key: "long_term_debt", name: "Long-term debt", shape: "compact" },
      { key: "other_borrowed_funds", name: "Other borrowed funds", shape: "compact" },
      { key: "total_equity", name: "Total equity", shape: "compact" },
    ],
  },
  {
    title: "From the cash flow statement",
    caption: "Cash that actually moved over the period.",
    figures: [
      { key: "cash_from_ops", name: "Cash from operations", shape: "compact" },
      { key: "capex", name: "Capital expenditure", shape: "compact" },
      {
        key: "depreciation_amortisation",
        name: "Depreciation and amortisation",
        shape: "compact",
      },
      { key: "dividends_paid", name: "Dividends paid", shape: "compact" },
      { key: "buybacks", name: "Share buybacks", shape: "compact" },
      { key: "fx_loss_net", name: "Net foreign-exchange loss", shape: "compact" },
    ],
  },
];

/**
 * A figure table: the name of each line, and what it was.
 *
 * An absent value keeps its row and says which kind of absence it is. A table is exactly
 * where `DESIGN.md` §6's two phrases belong - "not reported" beside a line a reader came
 * looking for is an answer, and `td.absent` makes it quieter than a real figure so a
 * column of them does not read as data.
 */
export function FigureTable({
  caption,
  figures,
  values,
  currency,
}: {
  caption: string;
  figures: FigureSpec[];
  values: Record<string, string | null>;
  currency: string;
}) {
  return (
    <table>
      <caption>{caption}</caption>
      <thead>
        <tr>
          <th scope="col">Figure</th>
          {/* Not the currency code: a group holds ratios and amounts together, and only
              the amounts are in it. Each money figure carries its own symbol, and the
              `.source` block below states the currency once. */}
          <th scope="col" className="num">
            Value
          </th>
        </tr>
      </thead>
      <tbody>
        {figures.map((spec) => (
          <tr key={spec.key}>
            <th scope="row">{spec.name}</th>
            <NumCell text={write(spec, values, currency)} />
          </tr>
        ))}
      </tbody>
    </table>
  );
}

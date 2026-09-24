import type { Metadata } from "next";
import type { ReactNode } from "react";
import { Suspense } from "react";
import Link from "next/link";

import { ApiError, api, type Ratios } from "@/lib/api";
import { day, isMissing, money, moneyCompact, percent, ratio } from "@/lib/format";
import { Valuation } from "./_valuation";

interface PageProps {
  params: Promise<{ ticker: string }>;
  searchParams: Promise<Record<string, string | string[] | undefined>>;
}

export async function generateMetadata({ params }: PageProps): Promise<Metadata> {
  const { ticker } = await params;
  return {
    title: decodeURIComponent(ticker).toUpperCase(),
    description:
      "One company's figures, each one explained in plain words and shown with the " +
      "filing it came from and the day it became public.",
  };
}

/**
 * One company.
 *
 * `DESIGN.md` §2 caps the lead at four headline figures, so the page opens with the four
 * margins and nothing else. They are one idea rather than four - a margin - which is why
 * one `.explain` covers all four and why the other ten figures are folded away in three
 * groups, each group being one further idea.
 */
export default async function CompanyPage({ params, searchParams }: PageProps) {
  const { ticker: rawTicker } = await params;
  const ticker = decodeURIComponent(rawTicker);
  const query = await searchParams;

  let data: Ratios;
  try {
    data = await api.ratios(ticker);
  } catch (error) {
    return <CouldNotLoad ticker={ticker} error={error} />;
  }

  const r = data.ratios;
  const noMargins =
    isMissing(r.gross_margin) &&
    isMissing(r.operating_margin) &&
    isMissing(r.net_margin) &&
    isMissing(r.fcf_margin);

  const submitted =
    query.discount_rate !== undefined ||
    query.growth !== undefined ||
    query.terminal_growth !== undefined;

  return (
    <>
      <p className="faint">
        <Link href="/companies">← All companies</Link>
      </p>

      <h1>
        {data.ticker} — {data.legal_name}
      </h1>
      <p className="lede">
        Figures from its {data.filing_type} for {data.period_label}, the period ending{" "}
        {day(data.period_end)}. Every one of them is described below in plain words, and
        every one says where it came from.
      </p>

      <h2>How much of what it sold it kept</h2>

      {noMargins ? (
        <div className="notice">
          <h3>This filing does not report what the four margins need</h3>
          <p>
            A margin measures profit against sales, so it needs both — and this
            statement does not report them in that shape. Not every company files that
            way: banks and insurers commonly do not, because they have no cost of making
            a product to set against what they sold.
          </p>
          <p>
            Nothing has been estimated in their place, and no zero is standing in for a
            blank. The figures further down are built from other lines, and many of them
            are present.
          </p>
          <details className="more">
            <summary>What a margin is, for when you meet one</summary>
            <MarginExplainer currency={data.currency} />
          </details>
        </div>
      ) : (
        <>
          <div className="grid cols-4">
            <Stat
              value={percent(r.gross_margin)}
              name="Gross margin"
              note="left after the cost of making and delivering the product"
            />
            <Stat
              value={percent(r.operating_margin)}
              name="Operating margin"
              note="left after that, and after the cost of running the company"
            />
            <Stat
              value={percent(r.net_margin)}
              name="Net margin"
              note="left after everything, including interest and tax"
            />
            <Stat
              value={percent(r.fcf_margin)}
              name="Free cash flow margin"
              note="cash left after running the company and buying equipment"
            />
          </div>

          <div className="explain">
            <span className="tag">What a margin is</span>
            <MarginExplainer currency={data.currency} />
          </div>
        </>
      )}

      <h2>The other ten figures</h2>
      <p className="muted">
        Folded away rather than laid out, because fourteen numbers on one screen is how a
        reader loses all fourteen. Open a group to see it.
      </p>

      <details className="more">
        <summary>What it owns and what it owes</summary>
        <div>
          <p>
            These compare the things a company has against the money it owes. Four of them
            are ratios rather than amounts: a ratio of 2 means the first thing is twice
            the size of the second.
          </p>
          <Meaning name="Current ratio" value={ratio(r.current_ratio)}>
            Things it could turn into cash within a year, divided by the bills due within
            a year. At 1.00 the two are the same size. Below 1.00 the bills due within the
            year are the larger of the two; above 1.00 the resources are.
          </Meaning>
          <Meaning name="Debt to equity" value={ratio(r.debt_to_equity)}>
            Long-term borrowing divided by the money the owners have in the company. At
            1.00 there is one unit borrowed for every unit the owners put in.
          </Meaning>
          <Meaning name="Liabilities to assets" value={ratio(r.liabilities_to_assets)}>
            Everything owed divided by everything owned. At 0.60, 60 of every 100 of what
            the company owns is owed to somebody else and the other 40 belongs to the
            owners.
          </Meaning>
          <Meaning name="Interest coverage" value={ratio(r.interest_coverage)}>
            Profit from operating the business, divided by the interest bill for the year.
            At 5, the year&rsquo;s operating profit was five times the interest due on the
            borrowing.
          </Meaning>
          <Meaning name="Net debt" value={moneyCompact(r.net_debt, data.currency)}>
            Long-term borrowing with the cash on hand taken off. A negative figure means
            there is more cash on hand than long-term borrowing.
          </Meaning>
        </div>
      </details>

      <details className="more">
        <summary>What the owners get back for their money</summary>
        <div>
          <p>
            These three set the year&rsquo;s profit against something else — the money the
            owners put in, everything the company owns, or a single share.
          </p>
          <Meaning name="Return on equity" value={percent(r.roe)}>
            The year&rsquo;s profit measured against the money the owners have in the
            company. At 15%, there was 15 of profit in the year for every 100 of
            owners&rsquo; money.
          </Meaning>
          <Meaning name="Return on assets" value={percent(r.roa)}>
            The same profit measured against everything the company owns, whoever paid for
            it. It comes out below return on equity whenever any of those things were paid
            for with borrowed money.
          </Meaning>
          <Meaning name="Earnings per share" value={money(r.eps, data.currency)}>
            The year&rsquo;s profit divided by the number of shares: the slice of that
            profit sitting behind one share. It is not money paid to you. It stays inside
            the company unless some of it is handed out as a dividend.
          </Meaning>
        </div>
      </details>

      <details className="more">
        <summary>Cash, and profit before the deductions</summary>
        <div>
          <p>
            Two amounts rather than ratios, both in {data.currency}, and both for the same
            period as everything above.
          </p>
          <Meaning
            name="Free cash flow"
            value={moneyCompact(r.free_cash_flow, data.currency)}
          >
            The cash the business generated over the year, after paying for the equipment
            and property it bought. It is the figure the valuation further down starts
            from.
          </Meaning>
          <Meaning name="EBITDA" value={moneyCompact(r.ebitda, data.currency)}>
            The name is the list of what has been left out: Earnings Before Interest, Tax,
            Depreciation and Amortisation. It is not a line in the accounts — it is put
            together by adding those four back on — and it is here because it is quoted so
            widely.
          </Meaning>
        </div>
      </details>

      <div className="source">
        <dl>
          <dt>Period</dt>
          <dd>
            {data.period_label}, ended {day(data.period_end)}
          </dd>
          <dt>Filing</dt>
          <dd>{data.filing_type}</dd>
          <dt>Became public</dt>
          <dd>{day(data.known_as_of)}</dd>
          <dt>Shown as known on</dt>
          <dd>{day(data.as_known_on)}</dd>
          <dt>Currency</dt>
          <dd>{data.currency}</dd>
          <dt>Attribution</dt>
          <dd>{data.attribution}</dd>
        </dl>
      </div>

      <Suspense fallback={<ValuationLoading />}>
        <Valuation
          ticker={data.ticker}
          currency={data.currency}
          price={data.price}
          filing={{
            period_label: data.period_label,
            period_end: data.period_end,
            known_as_of: data.known_as_of,
            attribution: data.attribution,
          }}
          discountRate={first(query.discount_rate)}
          growth={first(query.growth)}
          terminalGrowth={first(query.terminal_growth)}
          submitted={submitted}
        />
      </Suspense>
    </>
  );
}

/**
 * The same three paragraphs whether the four margins are shown or explained in their
 * absence. One copy, because a reader who meets the idea on a bank's page and again on a
 * manufacturer's should meet exactly the same words - and because two copies drift.
 */
function MarginExplainer({ currency }: { currency: string }) {
  return (
    <>
      <p>
        A margin answers one question: out of every 100 {currency} the company took from
        its customers, how much was still there after a particular set of costs? The
        first three take out more each time — first what it cost to make the product,
        then the cost of running the company, then interest and tax.
      </p>
      <p>
        The fourth counts cash instead of profit, and the two are not the same number.
        Profit records a sale on the day it is made; cash records it on the day the money
        actually arrives.
      </p>
      <p>
        A margin is a share of sales, so it says nothing about how large a company is —
        only how much of what came in stayed in.
      </p>
    </>
  );
}

/** One headline figure. Four of these is the whole lead, per `DESIGN.md` §2. */
function Stat({ value, name, note }: { value: string; name: string; note: string }) {
  return (
    <div className="card">
      <div className="stat-value">{value}</div>
      <div className="stat-name">{name}</div>
      <div className="stat-note">{note}</div>
    </div>
  );
}

/** A folded figure: its name, its value, and what it is — in that order. */
function Meaning({
  name,
  value,
  children,
}: {
  name: string;
  value: string;
  children: ReactNode;
}) {
  return (
    <p>
      <b>{name}</b> — <span className="num">{value}</span>
      <br />
      {children}
    </p>
  );
}

/** A query string can repeat a key. The first value is what the form sent. */
function first(value: string | string[] | undefined): string | undefined {
  return Array.isArray(value) ? value[0] : value;
}

function ValuationLoading() {
  return (
    <section>
      <h2>Put a value on it, using your own assumptions</h2>
      <div className="notice">
        <h3>Running the calculation</h3>
        <p>
          The valuation runs on the server, on the three rates in the address bar. This
          takes a moment.
        </p>
      </div>
    </section>
  );
}

/**
 * The failed state. A ticker that does not exist and an API that is down are different
 * problems with different answers, so the page says which one happened.
 */
function CouldNotLoad({ ticker, error }: { ticker: string; error: unknown }) {
  const status = error instanceof ApiError ? error.status : null;

  if (status === 404) {
    return (
      <>
        <h1>No company under “{ticker}”</h1>
        <div className="notice bad">
          <h3>Nothing is held for this ticker</h3>
          <p>
            The API holds no company under <b>{ticker}</b>. It may be spelled differently,
            or it may simply not be loaded here — only a fixed set of companies is.
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
      <h1>{ticker}</h1>
      <div className="notice bad">
        <h3>These figures could not be loaded</h3>
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

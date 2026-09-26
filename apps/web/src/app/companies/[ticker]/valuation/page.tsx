import type { Metadata } from "next";
import { Suspense } from "react";

import { api, failTheBuildInstead, type Ratios } from "@/lib/api";

import { Valuation } from "../_valuation";
import { CompanyProblem } from "../_states";

interface PageProps {
  params: Promise<{ ticker: string }>;
  searchParams: Promise<Record<string, string | string[] | undefined>>;
}

export async function generateMetadata({ params }: PageProps): Promise<Metadata> {
  const { ticker } = await params;
  return {
    title: `${decodeURIComponent(ticker).toUpperCase()} valuation`,
    description:
      "A discounted cash flow on one company, run on three rates you set yourself, with " +
      "every intermediate line shown.",
  };
}

/**
 * Valuation — a discounted cash flow on the reader's own three rates.
 *
 * Its own route, so a filled-in valuation has an address: the three rates are in the
 * query string, and that URL can be bookmarked, reloaded or sent to somebody else who
 * will see exactly the same workings. Nothing is prefilled and nothing is defaulted -
 * `DATA_FOUNDATION` §6.5's "user-set assumptions only".
 */
export default async function ValuationPage({ params, searchParams }: PageProps) {
  const { ticker: raw } = await params;
  const ticker = decodeURIComponent(raw);
  const query = await searchParams;

  let data: Ratios;
  try {
    data = await api.ratios(ticker);
  } catch (error) {
    failTheBuildInstead(error);
    return <CompanyProblem ticker={ticker} error={error} withHeading={false} />;
  }

  const submitted =
    query.discount_rate !== undefined ||
    query.growth !== undefined ||
    query.terminal_growth !== undefined;

  return (
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
  );
}

/** A query string can repeat a key. The first value is what the form sent. */
function first(value: string | string[] | undefined): string | undefined {
  return Array.isArray(value) ? value[0] : value;
}

function ValuationLoading() {
  return (
    <>
      <h2>Put a value on it, using your own assumptions</h2>
      <div className="notice">
        <h3>Running the calculation</h3>
        <p>
          The valuation runs on the server, on the three rates in the address bar. This
          takes a moment.
        </p>
      </div>
    </>
  );
}

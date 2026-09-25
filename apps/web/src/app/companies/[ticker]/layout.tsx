import type { Metadata } from "next";
import type { ReactNode } from "react";
import Link from "next/link";

import {
  api,
  failTheBuildInstead,
  type CompanySummary,
  type Ratios,
} from "@/lib/api";
import { count, day, direction, isMissing, money, NOT_LOADED, signedPercent } from "@/lib/format";

import { CompanyProblem } from "./_states";
import { CompanyTabs } from "./_tabs";

interface LayoutProps {
  children: ReactNode;
  params: Promise<{ ticker: string }>;
}

export async function generateMetadata({
  params,
}: {
  params: Promise<{ ticker: string }>;
}): Promise<Metadata> {
  const { ticker } = await params;
  return { title: decodeURIComponent(ticker).toUpperCase() };
}

/**
 * The header every tab of a company sits under: symbol, legal name, exchange, the last
 * close, and the tabs themselves.
 *
 * It is a layout rather than three copies of a header because a layout survives
 * navigation between its own children. Opening Financials from Overview re-renders only
 * the panel below the tabs; this block and its fetch are not repeated.
 *
 * Two calls, and only one of them can take the page down. `ratios` is the company - if it
 * does not answer there is nothing to draw a header from. `companies` is asked only for
 * the exchange, and the root layout has already fetched the same URL for the search box,
 * so Next serves it from the request's own fetch cache rather than going out again.
 */
export default async function CompanyLayout({ children, params }: LayoutProps) {
  const { ticker: raw } = await params;
  const ticker = decodeURIComponent(raw);

  let data: Ratios;
  try {
    data = await api.ratios(ticker);
  } catch (error) {
    failTheBuildInstead(error);
    return <CompanyProblem ticker={ticker} error={error} withHeading />;
  }

  let listing: CompanySummary | undefined;
  try {
    listing = (await api.companies()).companies.find(
      (company) => company.ticker === data.ticker,
    );
  } catch (error) {
    failTheBuildInstead(error);
    listing = undefined;
  }

  const price = data.price;

  return (
    <>
      <p className="faint">
        <Link href="/companies">← All stocks</Link>
      </p>

      <div className="security-head">
        {/* The page's only `<h1>`. It is in the layout, so every tab has exactly one and
            no tab has two - `DESIGN.md` §9. */}
        <h1 className="symbol">{data.ticker}</h1>
        <span className="legal-name">{data.legal_name}</span>
        <span className="exchange">
          {listing === undefined || isMissing(listing.exchange)
            ? NOT_LOADED
            : listing.exchange}
        </span>

        {price === null ? (
          <span className="price metric-value absent">{NOT_LOADED}</span>
        ) : (
          <span className="price">{money(price.close_raw, data.currency)}</span>
        )}

        {/* The move. The API computes it on adjusted closes and sends it, because
            working it out here from two `close_raw` figures would be AD-3 arithmetic
            *and* wrong: a split between the bars reads as -75% on a day the security
            rose. An absent move stays absent - `.delta.flat` would assert the price did
            not move, which is a different claim from not knowing. */}
        {(() => {
          const way = price === null ? null : direction(price.change);
          const moved = price === null ? null : signedPercent(price.change);
          if (way === null || moved === null) {
            return <span className="absent">Day&rsquo;s move {NOT_LOADED}</span>;
          }
          return (
            <span className={`delta ${way}`}>
              {moved}
              {price !== null && price.actions_between > 0 ? (
                <span className="hint"> · adjusted for a corporate action</span>
              ) : null}
            </span>
          );
        })()}

        <span className="asof">
          {data.filing_type} for {data.period_label} · period ended{" "}
          {day(data.period_end)} · public on {day(data.known_as_of)} · figures as known on{" "}
          {day(data.as_known_on)}
        </span>
        <span className="asof">
          {price === null
            ? "No closing price is held for this company, so the figures that need one are absent below."
            : `Close of ${day(price.date)}, knowable ${day(price.known_as_of)}, ${count(
                price.age_days,
              )} days old. ${price.attribution}`}
        </span>
      </div>

      <CompanyTabs ticker={data.ticker} />

      {children}
    </>
  );
}

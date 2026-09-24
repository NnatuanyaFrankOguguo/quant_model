import type { Metadata } from "next";
import Link from "next/link";
import "./globals.css";
import { api, type CompanySummary } from "@/lib/api";
import { Rail } from "./_rail";
import { TickerSearch } from "./_search";

export const metadata: Metadata = {
  title: {
    default: "quant_model",
    template: "%s — quant_model",
  },
  description:
    "Company fundamentals, macro series and market data, each figure showing where it " +
    "came from and when it was true.",
};

/**
 * The shell every page inherits: brand, search, the left rail, and the disclaimer.
 *
 * The disclaimer lives here rather than on each page for one reason - `DATA_FOUNDATION`
 * §6.5 requires it to be *persistent*, and a banner a page has to remember to include is
 * one a page will eventually forget.
 *
 * The company list is fetched here, once, and handed to the search box. Twenty-four rows
 * is small enough to filter in the browser, which is what makes the search feel instant;
 * the day the universe is large enough for that to be wrong, this becomes an endpoint and
 * only `_search.tsx` changes. A failure here is swallowed deliberately - the search going
 * quiet must not take the whole application down with it, and every page below states its
 * own failure in its own terms.
 */
export default async function RootLayout({ children }: { children: React.ReactNode }) {
  let companies: CompanySummary[] = [];
  try {
    companies = (await api.companies()).companies;
  } catch {
    companies = [];
  }

  return (
    <html lang="en">
      <body>
        <div className="shell">
          <div className="brand">
            <Link href="/">quant_model</Link>
          </div>

          <div className="topbar">
            <TickerSearch
              companies={companies.map((company) => ({
                ticker: company.ticker,
                name: company.legal_name,
              }))}
            />
          </div>

          <Rail />

          <main className="main" id="main">
            {children}
          </main>

          <footer className="disclaimer">
            <b>Not investment advice.</b> This shows published figures and what they mean.
            It recommends nothing, and any valuation shown is the result of assumptions you
            entered yourself. Company data from SEC EDGAR; prices from Yahoo Finance;
            Nigerian macro from the NBS, the CBN and the DMO; US macro from FRED.
          </footer>
        </div>
      </body>
    </html>
  );
}

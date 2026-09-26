import type { Metadata } from "next";
import Link from "next/link";
import { GeistSans } from "geist/font/sans";
import { GeistMono } from "geist/font/mono";
import "./globals.css";
import { api, type CompanySummary, type HoldingsSummary } from "@/lib/api";
import { day } from "@/lib/format";
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

  // The top bar's "as of" chip. Same rule as the search: a failure here goes quiet
  // rather than taking the shell down, and the overview fetches the same URL, so this
  // costs nothing extra on the page most likely to be open.
  let summary: HoldingsSummary | null = null;
  try {
    summary = await api.summary();
  } catch {
    summary = null;
  }

  return (
    <html lang="en" className={`${GeistSans.variable} ${GeistMono.variable}`}>
      <body>
        <a className="skip-link" href="#main">
          Skip to content
        </a>
        <div className="shell">
          <div className="brand">
            <Link href="/" aria-label="quant_model, overview">
              <svg
                className="brand-mark"
                width="28"
                height="28"
                viewBox="0 0 28 28"
                aria-hidden="true"
              >
                <rect width="28" height="28" rx="7" fill="currentColor" />
                <path
                  d="M7 18.5 11.5 13l3.5 3.5L21 9.5"
                  fill="none"
                  stroke="var(--brand-mark-ink)"
                  strokeWidth="2.2"
                  strokeLinecap="round"
                  strokeLinejoin="round"
                />
              </svg>
              <span className="brand-name">
                <span>
                  quant<span className="brand-sep">_</span>model
                </span>
                <span className="brand-sub">Research</span>
              </span>
            </Link>
          </div>

          <div className="topbar">
            <TickerSearch
              companies={companies.map((company) => ({
                ticker: company.ticker,
                name: company.legal_name,
              }))}
            />
            <div className="topbar-meta">
              {summary === null ? null : (
                <span className="status-chip" title="The date the API last counted its holdings">
                  <span className="status-dot" aria-hidden="true" />
                  Data as of {day(summary.counted_at)}
                </span>
              )}
            </div>
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

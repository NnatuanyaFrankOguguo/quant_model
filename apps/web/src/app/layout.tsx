import type { Metadata } from "next";
import Link from "next/link";
import "./globals.css";

export const metadata: Metadata = {
  title: {
    default: "quant_model — a financial data instrument",
    template: "%s — quant_model",
  },
  description:
    "Company figures, macro series and market data, each one showing where it came " +
    "from and when it was true. It explains what the numbers mean. It never says what " +
    "to do with them.",
};

/**
 * The shell every page inherits: masthead, the disclaimer, and the footer.
 *
 * The disclaimer lives here rather than on each page for one reason - `DATA_FOUNDATION`
 * 6.5 requires it to be *persistent*, and a banner a page has to remember to include is
 * one a page will eventually forget.
 */
export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body>
        <a className="skip" href="#main">
          Skip to content
        </a>

        <header className="masthead">
          <div className="wrap">
            <Link href="/" className="brand">
              quant_model
              <small>figures with their sources attached</small>
            </Link>
            <nav className="nav" aria-label="Main">
              <Link href="/companies">Companies</Link>
              <Link href="/macro">Economy</Link>
              <Link href="/data-health">Data health</Link>
              <Link href="/how-to-read-this">How to read this</Link>
            </nav>
          </div>
        </header>

        <div className="disclaimer">
          <div className="wrap">
            <b>This is not investment advice.</b> It shows published figures and explains
            what they mean. It does not recommend anything, and any valuation you see is
            the result of assumptions you typed in yourself.
          </div>
        </div>

        <main id="main">
          <div className="wrap">{children}</div>
        </main>

        <footer className="foot">
          <div className="wrap">
            <p>
              Every figure here carries the filing it came from and the date it became
              public. Where a number is missing, the page says it is missing rather than
              showing a zero — the two mean different things.
            </p>
            <p className="faint">
              Company data from SEC EDGAR. Prices from Yahoo Finance. Nigerian macro data
              from the National Bureau of Statistics and the Central Bank of Nigeria. US
              macro data from FRED. Each page repeats the attribution for what it shows.
            </p>
          </div>
        </footer>
      </body>
    </html>
  );
}

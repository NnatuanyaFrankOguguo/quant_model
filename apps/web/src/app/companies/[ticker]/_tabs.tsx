"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

/**
 * The tabs on a company.
 *
 * A client component for the same reason the rail is one: `aria-current` needs the
 * current path, and marking the open tab is not decoration. `aria-current="page"` is
 * what `globals.css` styles, so the visual state and the announced state cannot diverge.
 *
 * Each tab is a real route, so each is linkable, server-rendered and reachable with the
 * back button. They sit under a shared layout, which is what stops the header being
 * fetched again every time one is opened.
 */
export function CompanyTabs({ ticker }: { ticker: string }) {
  const pathname = usePathname();
  const base = `/companies/${encodeURIComponent(ticker)}`;

  // The full set, declared in one place so three people adding a tab each do not each
  // edit this list. Order is the reading order of a company: what it is, what it did,
  // what it filed, what it might be worth.
  const tabs = [
    { href: base, text: "Overview" },
    { href: `${base}/chart`, text: "Chart" },
    { href: `${base}/financials`, text: "Financials" },
    { href: `${base}/filings`, text: "Filings" },
    { href: `${base}/valuation`, text: "Valuation" },
  ];

  /** Trailing slashes are stripped so /companies/AAPL/ still lights Overview. */
  const here = pathname.length > 1 ? pathname.replace(/\/+$/, "") : pathname;

  return (
    <nav className="tabs" aria-label={`${ticker} sections`}>
      {tabs.map((tab) => (
        <Link
          key={tab.href}
          href={tab.href}
          aria-current={here === tab.href ? "page" : undefined}
        >
          {tab.text}
        </Link>
      ))}
    </nav>
  );
}

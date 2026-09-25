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

  const tabs = [
    { href: base, text: "Overview" },
    { href: `${base}/financials`, text: "Financials" },
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

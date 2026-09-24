"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

/**
 * The left rail.
 *
 * A client component for one reason: `aria-current` needs the current path, and marking
 * the active destination is not decoration. It is what tells a reader where they are
 * without reading every label - and `aria-current="page"` is the same fact spoken aloud
 * for a screen reader, which is why it is the attribute driving the styling rather than a
 * class.
 */

const SECTIONS: { label: string; links: { href: string; text: string }[] }[] = [
  {
    label: "Markets",
    links: [
      { href: "/", text: "Overview" },
      { href: "/companies", text: "Stocks" },
      { href: "/macro", text: "Economy" },
    ],
  },
  {
    label: "System",
    links: [
      { href: "/data-health", text: "Data health" },
      { href: "/how-to-read-this", text: "How to read this" },
    ],
  },
];

export function Rail() {
  const pathname = usePathname();

  /** Exact for the root, prefix for the rest, so /companies/AAPL still lights Stocks. */
  const isCurrent = (href: string) =>
    href === "/" ? pathname === "/" : pathname.startsWith(href);

  return (
    <nav className="rail" aria-label="Sections">
      {SECTIONS.map((section) => (
        <div className="rail-group" key={section.label}>
          <div className="rail-label">{section.label}</div>
          {section.links.map((link) => (
            <Link
              key={link.href}
              href={link.href}
              aria-current={isCurrent(link.href) ? "page" : undefined}
            >
              {link.text}
            </Link>
          ))}
        </div>
      ))}
    </nav>
  );
}

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

/**
 * One stroke icon per destination, drawn inline so the set shares a 1.6px stroke and a
 * 16px box. Decorative only (`aria-hidden`): the label beside each one is the name.
 */
const ICONS: Record<string, React.ReactNode> = {
  "/": <path d="M3 13h4v5H3zM8.5 8h4v10h-4zM14 3h4v15h-4z" />,
  "/companies": (
    <>
      <path d="M3 17 8 11l3.5 3.5L17 7" />
      <path d="M13 7h4v4" />
    </>
  ),
  "/macro": (
    <>
      <circle cx="10" cy="10" r="7" />
      <path d="M3 10h14M10 3c2 2.2 2.8 4.5 2.8 7s-.8 4.8-2.8 7c-2-2.2-2.8-4.5-2.8-7S8 5.2 10 3Z" />
    </>
  ),
  "/data-health": <path d="M2.5 10h3.5l2-5 4 10 2-5h3.5" />,
  "/how-to-read-this": (
    <>
      <path d="M3 4.5h5a2 2 0 0 1 2 2V17a1.5 1.5 0 0 0-1.5-1.5H3z" />
      <path d="M17 4.5h-5a2 2 0 0 0-2 2V17a1.5 1.5 0 0 1 1.5-1.5H17z" />
    </>
  ),
};

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
              <svg
                className="rail-icon"
                width="16"
                height="16"
                viewBox="0 0 20 20"
                fill="none"
                stroke="currentColor"
                strokeWidth="1.6"
                strokeLinecap="round"
                strokeLinejoin="round"
                aria-hidden="true"
              >
                {ICONS[link.href]}
              </svg>
              <span>{link.text}</span>
            </Link>
          ))}
        </div>
      ))}
    </nav>
  );
}

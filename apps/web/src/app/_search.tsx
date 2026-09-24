"use client";

import { useEffect, useId, useMemo, useRef, useState } from "react";
import { useRouter } from "next/navigation";

/**
 * Ticker search: the control a reader of any stock research site reaches for first.
 *
 * Filtering happens here rather than on the server because the universe is twenty-four
 * rows - a round trip per keystroke would make a box that is instant feel slow for no
 * gain. `layout.tsx` fetches the list once and this filters it. When the universe is large
 * enough for that to be wrong, this file changes and nothing else does.
 *
 * It is a real combobox: `role="combobox"` with `aria-expanded` and `aria-activedescendant`
 * so a screen reader announces the highlighted option, arrow keys move, Enter navigates
 * and Escape closes. A `<div>` with a keydown handler would look identical and be
 * unusable without a mouse.
 */

interface Entry {
  ticker: string;
  name: string;
}

const LIMIT = 8;

export function TickerSearch({ companies }: { companies: Entry[] }) {
  const router = useRouter();
  const listId = useId();
  const box = useRef<HTMLDivElement>(null);

  const [query, setQuery] = useState("");
  const [open, setOpen] = useState(false);
  const [active, setActive] = useState(0);

  const matches = useMemo(() => {
    const needle = query.trim().toLowerCase();
    if (!needle) return [];
    // Ticker prefix first, then name: somebody typing "AA" wants AAPL above any company
    // with "aa" in the middle of its legal name.
    const byTicker = companies.filter((c) => c.ticker.toLowerCase().startsWith(needle));
    const byName = companies.filter(
      (c) => !byTicker.includes(c) && c.name.toLowerCase().includes(needle),
    );
    return [...byTicker, ...byName].slice(0, LIMIT);
  }, [companies, query]);

  useEffect(() => setActive(0), [query]);

  // Close when the click lands anywhere else. Without this the list survives a
  // navigation and hangs over the next page.
  useEffect(() => {
    if (!open) return;
    const away = (event: MouseEvent) => {
      if (!box.current?.contains(event.target as Node)) setOpen(false);
    };
    document.addEventListener("mousedown", away);
    return () => document.removeEventListener("mousedown", away);
  }, [open]);

  const go = (entry: Entry | undefined) => {
    if (!entry) return;
    setOpen(false);
    setQuery("");
    router.push(`/companies/${encodeURIComponent(entry.ticker)}`);
  };

  const onKeyDown = (event: React.KeyboardEvent<HTMLInputElement>) => {
    if (event.key === "ArrowDown" || event.key === "ArrowUp") {
      event.preventDefault();
      if (!matches.length) return;
      setOpen(true);
      setActive((current) => {
        const step = event.key === "ArrowDown" ? 1 : -1;
        return (current + step + matches.length) % matches.length;
      });
    } else if (event.key === "Enter") {
      event.preventDefault();
      go(matches[active]);
    } else if (event.key === "Escape") {
      setOpen(false);
    }
  };

  const showing = open && query.trim().length > 0;

  return (
    <div className="search" ref={box}>
      <span className="search-icon" aria-hidden="true">
        <svg width="14" height="14" viewBox="0 0 16 16" fill="none" stroke="currentColor">
          <circle cx="7" cy="7" r="4.5" strokeWidth="1.6" />
          <path d="M10.5 10.5 14 14" strokeWidth="1.6" strokeLinecap="round" />
        </svg>
      </span>
      <input
        type="text"
        value={query}
        role="combobox"
        aria-expanded={showing}
        aria-controls={listId}
        aria-autocomplete="list"
        aria-activedescendant={
          showing && matches.length ? `${listId}-${active}` : undefined
        }
        aria-label="Search by ticker or company name"
        placeholder="Search ticker or company…"
        autoComplete="off"
        onChange={(event) => {
          setQuery(event.target.value);
          setOpen(true);
        }}
        onFocus={() => setOpen(true)}
        onKeyDown={onKeyDown}
      />

      {showing ? (
        <ul className="search-results" id={listId} role="listbox">
          {matches.length === 0 ? (
            <li className="search-empty" role="presentation">
              No company held under that name. Only the loaded universe is searchable.
            </li>
          ) : (
            matches.map((entry, index) => (
              <li key={entry.ticker} role="presentation">
                <a
                  id={`${listId}-${index}`}
                  role="option"
                  aria-selected={index === active}
                  href={`/companies/${encodeURIComponent(entry.ticker)}`}
                  onMouseEnter={() => setActive(index)}
                  onClick={(event) => {
                    event.preventDefault();
                    go(entry);
                  }}
                  style={
                    index === active ? { background: "var(--act-wash)" } : undefined
                  }
                >
                  <span className="ticker">{entry.ticker}</span>
                  <span className="name">{entry.name}</span>
                </a>
              </li>
            ))
          )}
        </ul>
      ) : null}
    </div>
  );
}

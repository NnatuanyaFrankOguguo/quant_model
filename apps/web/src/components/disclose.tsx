import type { ReactNode } from "react";

/**
 * A one-line summary that becomes the full explanation when opened.
 *
 * Closed, it shows `brief` and a small arrow. Open, **the brief is replaced** by the
 * children - not pushed down by them. That swap is the whole point: the line is a
 * placeholder for the explanation rather than a heading above it, so a page full of these
 * reads as data with notes rather than as an essay with numbers in it.
 *
 * Deliberately a `<details>` and not a client component. It is keyboard-operable, it is
 * announced correctly by a screen reader, it works before hydration and with JavaScript
 * off entirely, and the swap costs one CSS rule (`.disclose[open] .brief { display:none }`)
 * rather than a state hook and a re-render. The arrow is drawn by `::after` in
 * `globals.css` and rotates on open, so the control's state is legible without reading
 * the text beside it.
 *
 * On the compliance line (`DATA_FOUNDATION` §6.5): what goes in here explains what a
 * figure *is*. It never says whether the figure is good. "Current ratio is 1.4 - that
 * means…" belongs here; "healthy balance sheet" belongs nowhere.
 */
export function Disclose({
  brief,
  children,
  className,
}: {
  /** The single line shown while closed. Written as a statement, not a question. */
  brief: ReactNode;
  children: ReactNode;
  className?: string;
}) {
  return (
    <details className={className ? `disclose ${className}` : "disclose"}>
      <summary>
        <span className="brief">{brief}</span>
      </summary>
      <div className="full">{children}</div>
    </details>
  );
}

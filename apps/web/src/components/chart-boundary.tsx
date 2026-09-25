"use client";

import { Component, type ErrorInfo, type ReactNode } from "react";

/**
 * The fence around a chart. `DESIGN.md` 4b: *a chart must not be the reason a page
 * fails.*
 *
 * A chart is the least trustworthy thing on any of these pages. It is the only client
 * component that draws, the only one that depends on a third-party library, and the only
 * one that touches a canvas - so it is the only one that can throw in a browser after
 * every figure on the page has already been fetched and rendered correctly. Without a
 * boundary that throw unmounts the whole route and the reader loses the table too, which
 * is the rendering that actually carried the data.
 *
 * A class component because that is still the only way to catch a render error in React.
 * `componentDidCatch` deliberately does not report anywhere: there is no telemetry in
 * this app, and inventing a sink here would be a bigger decision than this file.
 *
 * The fallback is `.notice` and not `.notice.bad`. A missing picture beside a complete
 * table is not a data failure and must not be painted as one - the same line §8 draws
 * between slow and broken.
 */
export class ChartBoundary extends Component<
  { children: ReactNode },
  { broke: boolean }
> {
  constructor(props: { children: ReactNode }) {
    super(props);
    this.state = { broke: false };
  }

  static getDerivedStateFromError(): { broke: boolean } {
    return { broke: true };
  }

  componentDidCatch(error: Error, info: ErrorInfo): void {
    // The browser console is the only place this can usefully go today, and a chart
    // that failed silently would be worse than one that says so twice.
    console.error("The price chart failed to render.", error, info.componentStack);
  }

  render(): ReactNode {
    if (this.state.broke) {
      return (
        <div className="notice">
          <h3>The chart is not being drawn</h3>
          <p>
            Something went wrong inside the drawing library, so the picture is missing.
            Nothing else on this page is affected: every figure the chart would have
            plotted is listed in full below it, exactly as the API returned it.
          </p>
        </div>
      );
    }
    return this.props.children;
  }
}

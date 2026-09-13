"""Valuation: ratios and a discounted-cash-flow model that never chooses for the user. P2.4.

Reserved in `packages/README.md` for P2; first written 2026-09-13.

Two rules from the source documents shape everything here:

* **Compute functions take data and return data, and do no I/O** (`docs/08` §6). That is
  what makes them testable against hand-computed vectors in `tests/known_answer/`.
* **Instrument, not judgment** (`DATA_FOUNDATION.md` §1.4; `CLAUDE.md` "show the work").
  The DCF takes growth, discount rate, terminal growth, net debt and share count as
  explicit inputs and returns them with the answer; `compute_ratios` returns a *fact* — a
  P/E is a number in both modes — and never a verdict. "Undervalued" is a banned phrase.

And one from `SPEC.md` §4.1: **a ratio with a missing input is None** — never 0, never
infinity. A P/E where earnings are missing is unknown, and it must say so.
"""

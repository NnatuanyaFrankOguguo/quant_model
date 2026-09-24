# The design contract

Every page in this app obeys this file. It exists because several people (and several
agents) build pages here, and a UI assembled by more than one hand drifts unless the rules
are written down rather than inferred from whichever page was read last.

**If a rule here is wrong, change this file and say so. Do not work around it in a page.**

---

## 1. What this app is for

A person with no finance background should be able to read any page here and come away
understanding what a number *means*. That is the whole product goal, and it decides most of
the rules below.

`DATA_FOUNDATION.md` §1.4 calls the system an **instrument, not a judgement**. It measures
and it explains. It never tells anybody what to do.

### The compliance line, which is not negotiable

`DATA_FOUNDATION.md` §6.5: *"No recommendations; no auto price targets; user-set
assumptions only; persistent disclaimer."*

In copy, that means:

| Never write | Write instead |
|---|---|
| "undervalued", "overvalued", "cheap", "expensive" | "your assumptions give a value of X; the market price is Y" |
| "strong balance sheet", "healthy margins" | "current ratio is 1.4 — that means…" |
| "you should", "consider", "worth a look" | nothing. Explain the number and stop. |
| a price target the system produced | a value the **reader's own inputs** produced, labelled as theirs |

Explaining what a ratio *is* is encouraged and is the point. Saying whether it is *good* is
prohibited. The dividing line: **describe and define, never evaluate or advise.**

---

## 2. Not too much at once

The single most common way to lose a beginner is to answer questions they have not asked
yet. So:

- **One idea per screenful.** A page opens with the thing it is about, not with everything
  known about it.
- **Lead with at most 4 headline figures.** Anything else goes below, or into a
  `<details class="more">`.
- **Explain once, where it is needed.** One `.explain` block per idea. Two on a screen is
  noise; the second stops being read.
- **Secondary detail is folded by default.** Use `<details class="more">` — it is native,
  keyboard-accessible, and works without JavaScript.
- Prose lines cap at `--prose` (68 characters). Longer lines measurably slow reading.

If a page feels full, the answer is to move something into `details`, not to shrink the
type.

---

## 3. The palette

Defined in `src/app/globals.css`. **Never write a hex value in a page or a component** —
use the variables.

- **Light only.** No dark theme. Maximum contrast, no ambiguity about what is a surface.
- **No gold, amber or orange.** Including the conventional amber warning.
- **Blue means "you can act on this"** — links, buttons, focus. Blue is never a status
  colour, so a reader never has to work out which sense is meant.
- **Status is green / violet / red**, and every status colour is *always* accompanied by a
  word. Colour is never the only signal (WCAG 1.4.1), and green/violet/red separates under
  the common forms of colour blindness where green/amber/red does not.

| Token | Use |
|---|---|
| `--act`, `--act-deep`, `--act-wash` | anything interactive |
| `--ok`, `--attention`, `--broken` (+ `-wash`) | status only, always with a label |
| `--ink`, `--ink-soft`, `--ink-faint` | primary / secondary / tertiary text |
| `--paper`, `--paper-sunk`, `--paper-raised` | page / recessed / card |
| `--line`, `--line-strong` | borders |

---

## 4. Responsive

It must work on a phone. It is *better* on a large screen, and that is fine to say — a
year-by-year table of figures wants width — but nothing may be unusable or invisible on a
narrow one.

- Every grid uses `repeat(auto-fit, minmax(min(100%, Npx), 1fr))`, which collapses to one
  column with no media query. `min(100%, …)` is what stops overflow at 320px.
- **A wide table scrolls inside `.scroller`, never by widening the page.** A horizontally
  scrolling *page* on a phone is the fastest way to lose somebody. `.scroll-hint` tells a
  narrow-screen reader the table scrolls, and hides itself above 860px.
- Type scales with `clamp()`. No fixed pixel font sizes for headings.
- Touch targets are at least 40px. Buttons and nav links already are.
- Test at **320px**, 768px and 1280px before calling a page done.

---

## 5. Every figure carries its provenance

This is the project's core promise and the UI must not quietly drop it. Every displayed
number shows, at minimum:

- **what period it is about** (`period_end` / `as_of`)
- **when it became knowable** (`known_as_of`) — not the same thing, and the difference is
  the whole point of the schema
- **where it came from** (the API's own `attribution` string, rendered verbatim)

Use the `.source` block at the foot of the section. Never paraphrase an attribution.

---

## 6. Components available

From `globals.css`. Use these before writing anything new; if you need something new, add
it here and to this list.

`.wrap` `.card` `.grid.cols-2|3|4` `.stat-value` `.stat-name` `.stat-note` `.explain`
`details.more` `.scroller` `table` `.pill.ok|attention|broken|neutral` `.source` `.notice`
`.notice.bad` `.assumptions` `button` `.button.quiet` `.lede` `.muted` `.faint` `.num`

---

## 7. Data fetching

- All fetching happens **server-side**, through `src/lib/api.ts`. Nothing else calls the
  API.
- The browser never holds a token. `docs/01` ADR-0006 derives mode on the server; a token
  in the browser is one devtools tab from anyone.
- **The client computes nothing.** AD-3: Streamlit and Next.js are both thin clients.
  Arithmetic in a component is a defect — if a number is needed, the API should return it.
- Every page handles three states explicitly: **loading**, **empty**, and **failed**. A
  blank page tells a reader nothing. Use `.notice` and say what happened and what to do.

---

## 8. Accessibility, briefly

- One `<h1>` per page, headings in order, no levels skipped.
- Every table has a `<caption>`.
- Colour is never the only signal.
- Interactive elements are real `<button>` and `<a>`, never a `<div>` with a handler.
- `:focus-visible` is styled globally — do not remove it.

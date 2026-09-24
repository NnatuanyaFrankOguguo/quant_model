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

**"Never ran" is not a failure.** `.pill.never_ran` renders grey, not red. An absence of
information is not a broken thing, and a page that paints fifty-six never-ran jobs red
says "fifty-six things have failed" when the truth is that a scheduler is not running.
Red is for something that ran and went wrong.

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

Where an endpoint sends no `attribution` of its own — `/v1/public/companies` does not —
the `.source` block says that, rather than inventing one or being left off.

### An absence says which kind of absence it is

A missing figure is never a zero, never a bare dash and never an empty cell. It is one of
two phrases, and which one is a fact about the world:

| Phrase | Constant | Means |
|---|---|---|
| "not reported" | `NOT_REPORTED` | the filing does not contain this line. The filer's choice, not a fault |
| "not loaded yet" | `NOT_LOADED` | we have not fetched it yet. Ours |

This is the line the schema already draws between `not_in_filing` and `no_mapping`.
Neither string is ever written into a page — import the constant.

**When every headline figure on a section is absent, do not render the figures.** Four
cards reading "not reported" is four dead ends and a reader who concludes the site is
broken. Render one `.notice` saying which lines are missing and why, and fold the
explainer inside it. A bank does not report the four margins; that is a fact about bank
accounting, not a failure, and the page should say so in a sentence.

---

## 6. Components available

From `globals.css`. Use these before writing anything new; if you need something new, add
it here and to this list.

`.wrap` `.card` `.grid.cols-2|3|4` `.stat-value` `.stat-name` `.stat-note` `.explain`
`details.more` `.scroller` `table` `.pill.ok|attention|broken|neutral` `.source` `.notice`
`.notice.bad` `.assumptions` `button` `.button.quiet` `.lede` `.muted` `.faint` `.num`

### One formatting module

`src/lib/format.ts` is the only one. Dates, numbers, money, units and the absence
vocabulary all come from there, so the same fact is written the same way on every page.
Do not add a second module beside a page: there were two, and before anyone noticed they
had drifted to two date formatters and two words for a missing value.

`.wrap-cell` is not scoped to `td` — a `<th scope="row">` is the cell most likely to hold
the long text it exists for. It is not automatic, though: its 18rem floor buys even
columns in a table that was going to scroll anyway, and forces scrolling on a narrow one
that would otherwise fit. Use it when the row header holds prose **and** the table scrolls
regardless; leave it off when the label is short, or when dropping the floor is what lets
a two-column table fit at 320px with its value still beside its label.

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
- A row label is `<th scope="row">`, which is styled for the job (not uppercase, not
  sticky). Do not demote a row header to `<td>` to escape the column-header styling.
- Colour is never the only signal.
- Interactive elements are real `<button>` and `<a>`, never a `<div>` with a handler.
- `:focus-visible` is styled globally — do not remove it.

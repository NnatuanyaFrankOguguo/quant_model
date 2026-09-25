# The design contract

Every page in this app obeys this file. It exists because several people (and several
agents) build pages here, and a UI assembled by more than one hand drifts unless the rules
are written down rather than inferred from whichever page was read last.

**If a rule here is wrong, change this file and say so. Do not work around it in a page.**

---

## 0. What changed, and why — read this first if you knew the old version

The first version of this app optimised for teaching. It produced an essay: a narrow
centred column, three paragraphs before the first figure, and four headline numbers per
screen. It was rejected, correctly. It did not look like a financial product and it was
exhausting to scan.

**The idiom is now a stock research site** — think stockanalysis.com or TIKR. A fixed
header with a ticker search, a persistent left rail, tabs on a company, and pages that are
mostly dense tables. That familiarity is the product: somebody who has ever looked up a
share price should not have to learn where anything is.

**The explanations were not deleted. They were moved.** They live inside `<Disclose>`,
which shows one line and swaps it for the full text when opened. See §4.

---

## 1. What this app is for

It measures and it explains. It never tells anybody what to do.

`DATA_FOUNDATION.md` §6.5: *"No recommendations; no auto price targets; user-set
assumptions only; persistent disclaimer."*

| Never write | Write instead |
|---|---|
| "undervalued", "overvalued", "cheap", "expensive" | "your assumptions give a value of X; the market price is Y" |
| "strong balance sheet", "healthy margins" | "current ratio is 1.4 — that means…" |
| "you should", "consider", "worth a look" | nothing. Explain the number and stop. |
| a price target the system produced | a value the **reader's own inputs** produced, labelled as theirs |

Explaining what a ratio *is* is encouraged and is the point. Saying whether it is *good* is
prohibited. **Describe and define, never evaluate or advise.**

---

## 2. Density is the default

- **Data first, on every page.** The first thing below a heading is a figure, a table or a
  metric row. Not a paragraph.
- **Tables are the primary unit**, not cards. A card is for a small fixed set of headline
  figures (`.metrics`); everything with rows is a table.
- **Small type is correct here.** `--fs-small` (13px) for table bodies, `--fs-base` (14px)
  for the working size. Do not scale anything up to fill space.
- **No paragraph on a data page is longer than two sentences** outside a `<Disclose>`.
- A page may open with one `.page-note` line of orientation. One, not three.

The old rule "lead with at most 4 headline figures" is **withdrawn**. A metric row of
eight to twelve figures is correct and expected where there are that many; that is what
`.metrics` is for. **Never pad one.** `/v1/public/summary` counts three things and the
overview leads with three — inventing a fourth to fill the row would be the hard-coded
figure §6 forbids, wearing a layout rule as an excuse.

---

## 3. Layout

The shell is in `layout.tsx` and pages do not touch it.

```
┌─────────┬──────────────────────────────┐
│ brand   │ search                       │
├─────────┼──────────────────────────────┤
│ rail    │ main                         │
│         │                              │
└─────────┴──────────────────────────────┘
```

- A company page opens with `.security-head` — symbol, legal name, exchange, price,
  change — then `.tabs`, then content.
- Group related tables in a `.panel` with a `.panel-head`.
- `--measure` is 1440px. Wide is fine; this is a data product.

---

## 4. The disclosure — where explanation lives now

Use `<Disclose brief="…">` from `@/components/disclose`.

Closed, it shows one line and a small arrow. Open, **the brief is replaced** by the
children — not pushed down by them.

```tsx
<Disclose brief="A margin is the share of sales left after a set of costs.">
  <p>Out of every 100 USD the company took from customers, how much…</p>
</Disclose>
```

- It is a native `<details>`: keyboard-operable, correct for a screen reader, and working
  with JavaScript off. Do not reimplement it as a client component.
- **One per idea, placed after the data it explains** — never before.
- The `brief` is a statement, not a question, and not "Learn more".
- What goes inside explains what a figure *is*. §1 still applies inside a disclosure.

---

## 4b. Charts

The library is **`lightweight-charts`** (TradingView's, 5.x, ESM). It is what the products
this app is modelled on use, it is ~45KB, and its only dependency is `fancy-canvas`.

**A chart draws `close`, never `close_raw`.** `/companies/{ticker}/prices` returns both:
`close` is adjusted as of the decision date, `close_raw` is what the market printed. A
chart of raw closes shows a 75% cliff on a 4-for-1 split — the same corruption that made
RSI read Apple's 2020 split as the most violent sell-off in its history. `close_raw` is
there so a tooltip can say what the screen actually showed that day; it is never the line.

**A chart is a client component and therefore invisible to a screen reader.** Canvas has
no DOM. So every chart ships with the same data reachable another way — a `<Disclose>`
holding a table of the plotted points, or a link to the table that already shows them. A
chart is an *additional* rendering of data, never the only one.

**No chart may imply a recommendation.** No shaded "buy zone", no annotated crossover, no
target line. §1 applies to pixels exactly as it applies to prose, and `SPEC.md` 2C is why
indicators are features rather than signals.

- Price is a line or a candlestick; volume is a histogram on its own scale.
- Use `--up` / `--down` for direction and `--act` for a single-series line. Never invent a
  colour: read the CSS custom properties off `document.documentElement` and pass them in.
- The four states of §8 still apply. An empty series renders the empty state, not an empty
  axis.
- A chart must not be the reason a page fails. Render it in its own boundary.

---

## 5. The palette

Defined in `src/app/globals.css`. **Never write a hex value in a page or component.**

- **Light only.** No dark theme. **No gold, amber or orange**, including the conventional
  amber warning.
- **Blue means "you can act on this"** — links, buttons, focus, the active nav item. Blue
  is never a status colour.
- **System status is green / violet / red**, always beside a word (WCAG 1.4.1).
- **Market direction is `--up` / `--down`**, and is a *different pair of tokens* from
  `--ok` / `--broken` on purpose: a price falling is not a failure, and a connector
  failing is not a price. Always render a move with `.delta up|down|flat`, which supplies
  an arrow — that glyph is what carries direction for a red-green-blind reader.

**"Never ran" is not a failure.** `.pill.never_ran` renders grey. An absence of
information is not a broken thing, and painting fifty-six never-ran jobs red says
"fifty-six things have failed" when a scheduler is simply not running.

---

## 6. Every figure carries its provenance

The project's core promise. Every displayed number shows:

- **what period it is about** (`period_end` / `as_of`)
- **when it became knowable** (`known_as_of`) — not the same thing, and the difference is
  the whole point of the schema
- **where it came from** (the API's own `attribution`, rendered verbatim)

Use `.source` at the foot of the section. Never paraphrase an attribution. Where an
endpoint sends no attribution — `/v1/public/companies` does not — say so rather than
inventing one or dropping the block.

### An absence says which kind of absence it is

Never a zero, never a bare dash, never an empty cell.

| Phrase | Constant | Means |
|---|---|---|
| "not reported" | `NOT_REPORTED` | the filing does not contain this line. The filer's choice, not a fault |
| "not loaded yet" | `NOT_LOADED` | we have not fetched it yet. Ours |
| "no run recorded" | `NEVER_RAN` | the event has not happened. Nobody's absence — a job the scheduler has not reached |

The line the schema already draws between `not_in_filing` and `no_mapping`. Import the
constant; never write any of the three into a page. Render an absent figure with
`.absent`, which makes it quieter than a real number so a column of them does not read as
data. The class works on any element — a `<td>`, a `.metric-value`, or a bare `<span>`.

**When every headline figure in a section is absent, do not render the figures.** Render
one `.notice` saying which lines are missing and why. A bank does not report the four
margins; that is bank accounting, not a failure.

### Round what the system derived; print what it was given

- **A figure the system computed** is rounded. `gross_margin` arrives as
  `0.4690516410716044992202536999`; those digits come from Decimal division, not from a
  measurement.
- **A figure the system was given** is printed verbatim, trailing zeros and all.
  `16.7900%` is the datum exactly as the DMO published it.

**No figure is ever hard-coded.** If a count is needed, the API counts it
(`/v1/public/summary`).

---

## 7. Responsive

It must work on a phone. It is *better* on a large screen and that is fine to say.

- The rail becomes a horizontal strip under the header below 860px. Nothing is hidden;
  there are five destinations and none needs a menu button.
- **A wide table scrolls inside `.scroller`, never by widening the page.** `.scroll-hint`
  tells a narrow reader it scrolls and hides above 900px.
- Grids use `repeat(auto-fit, minmax(min(100%, Npx), 1fr))`. The `min(100%, …)` is what
  stops overflow at 320px.
- **`th[scope="row"].sticky`** pins a row label while the columns scroll under it. Opt-in:
  it is right for a statements table twenty periods wide, where the line's name is gone by
  the tenth column, and wrong for a table you can read across.
- `.wrap-cell` and `.nowrap` pull in opposite directions and neither is automatic.
  `.nowrap` keeps one line in a body cell — use it on dates, tickers and pills, because
  once a cell wraps the whole row's height doubles and the density is gone. `.num`
  already implies it. `.wrap-cell`'s 18rem floor buys even columns in a table that was
  going to scroll anyway, and forces scrolling on a narrow one that would otherwise fit.
- Test at **320px**, 768px and 1280px before calling a page done.

---

## 8. Data fetching

- All fetching happens **server-side**, through `src/lib/api.ts`. Nothing else calls the
  API. The browser never holds a token.
- **The client computes nothing.** AD-3: arithmetic in a component is a defect. If a
  number is needed, the API returns it. The one client component that filters —
  `_search.tsx` — selects rows, it does not derive figures.
- Every page handles four states: **loading**, **empty**, **slow** and **failed**.
- **Slow is not failed.** `ApiTimeout` means our budget expired, not that the service
  died. Use the shared `SERVICE_IS_SLOW` sentence and render it `.notice`, never
  `.notice.bad`.
- **A page that catches its own failure calls `failTheBuildInstead(error)` first.** A
  static route prerenders, so a caught failure is baked into the HTML: the build exits 0
  and every visitor is told the data could not be loaded.

---

## 9. Accessibility

- One `<h1>` per page, headings in order, no levels skipped.
- Every table has a `<caption>`.
- A row label is `<th scope="row">`, styled for the job. Do not demote one to `<td>`.
- **A `.notice` title may be an `h2` or an `h3`** and both are styled identically. Use
  whichever keeps the order intact — a notice is often the first thing after the page's
  `<h1>`, and an `h3` there is a skipped level.
- The active nav item carries `aria-current="page"` — that attribute drives the styling,
  so the visual state and the announced state cannot diverge.
- Colour is never the only signal.
- Interactive elements are real `<button>` and `<a>`, never a `<div>` with a handler.
- `:focus-visible` is styled globally — do not remove it.

---

## 10. Components available

From `globals.css`, plus `<Disclose>` from `@/components/disclose`.

`.shell` `.brand` `.topbar` `.rail` `.main` `.search` `.security-head` `.delta.up|down|flat`
`.tabs` `.metrics` `.metric` `.metric-name` `.metric-value` `.absent` `.panel` `.panel-head`
`.panel-body` `.grid` `.scroller` `table` `.wrap-cell` `.nowrap` `th.sticky` `.scroll-hint`
`.disclose` `.sparkline` `.chart` `.mark` `.hint` `button.sort`
`.pill.ok|attention|broken|neutral` `.notice` `.notice.bad` `.source` `.page-note` `.prose`
`.muted` `.faint` `.num` `button` `.button.quiet`

Use these before writing anything new. If you need something new, add it here and to
`globals.css` — not as an inline style in a page.

# Build notes — what was built, what broke, what is left

> A narrative companion to the tracker in [00_START_HERE](00_START_HERE.md) §6. The
> tracker says *what state each phase is in*; this says *what happened*, because most of
> what was learned does not fit in a table cell.
>
> Covers 25 commits, 69 files, +15,854 / −658 lines. Last updated 2026-09-25.

---

## 1. Where it stands, in one screen

| | |
|---|---|
| Database | 320 MB · 43 tables · migration head `0030_p5_sentiment_tier` |
| Tests | **1,306 passing**, 7 skipped, 1 environmental error |
| Phases closed this stretch | **P5.3**, **P5.4**, **P6** (🧪), **P9.5** (the web app) |
| Indicator rows computed | 842,088 across all 24 securities |
| Nigerian securities | **0** — and this is the thing blocking most of the rest |

**The single most important fact:** none of the 25 Nigerian companies in
[UNIVERSE.md](UNIVERSE.md) is loaded. That blocks P3's gate, P4's gate, the Nigerian half
of P5 and P6, and all of P7. Everything built for Nigeria so far — the extraction
pipeline, the devaluation handling, the NGX price connector, the news tagger — is correct
and idle.

---

## 2. What got built

### P6 — Scenarios & Indicators (🧪 built, 13/13 checks)

Six indicators (RSI, MACD, Bollinger, ATR, OBV, Stochastic) across 7 specs producing 12
columns, **842,088 rows for all 24 securities**, plus a scenario engine and
`POST /v1/public/companies/{ticker}/scenario`.

The phase's one 🔴 FRAGILE risk is indicators computed on unadjusted prices — *"silent;
corrupts P8's entire feature set."* It is not theoretical. The same RSI-14 on Apple across
its 2020 4-for-1 split:

| | 2020-08-28 | 2020-08-31 |
|---|---|---|
| on adjusted prices | 74.34 | **78.27** |
| on raw prices | 74.34 | **15.03** |

A 63-point error on a day the stock rose, inherited silently by every downstream feature.

### P5.3 — Sentiment tiering

VADER for the bulk tier, the LLM tier built and gated on the absent key. The intellectual
content turned out to be what "ambiguous" means, and the obvious answer is wrong — see §4.

### P5.4 — The daily brief

Per-principal composition, idempotent delivery, Telegram send gated on the missing token.

### P9.5 — The web app

Six routes, twice: built once as an explanatory essay, rejected by the owner, rebuilt in
the idiom of a stock research site (persistent rail, ticker search, dense tables, tabs).
The second version is the right one and the rejection was correct.

---

## 3. What is left

### Not blocked — buildable today

| | data ready |
|---|---|
| **Price chart** on the company page | 269,298 bars ✓ |
| **Financial statements** as FY columns | 58,205 line items, 8,212 statements ✓ |
| **Screener** — sort and filter `/companies` | ✓ |
| **Filings + dividends** tabs | endpoints exist ✓ |
| **Macro series detail** + sparklines | 28,092 observations ✓ |
| **Indicators on the chart** | 842,088 rows ✓ |
| News + sentiment page | 44 articles — thin until NGX lands |

*(All six of the first are in progress as of this writing.)*

### Blocked on the owner

1. **The NGX universe.** 25 companies, 21 live + 4 delisted. Highest leverage by a wide
   margin. `UNIVERSE.md` §2 is blunt about the delisted four: P7 check 11 *"cannot pass
   unless these rows exist, and nothing in the plan was fetching them."*
2. **`ANTHROPIC_API_KEY`** — P4's extraction and P9's memo agents.
3. **A Telegram bot token** — P5.4 delivery.
4. **`PREREGISTRATION.md`** — does not exist; P7 marks it **Blocking**, ~1 hour.
5. **A broker contract note** — to reconcile the NGX fee stack. P7 **Blocking**, ~2 hours.
6. **CI green on a PR** — the last thing holding P0 at 🧪 rather than ✅.

### P7 cannot start, and should not be forced

Four of its entry criteria fail. Its own documentation is unusually direct: *"If any of
these is not genuinely true, stop and close it. A backtester built on unadjusted prices or
a survivor-only universe produces confident nonsense, and you will not be able to tell."*

---

## 4. The headaches

The useful section. Every one of these was found, not theorised.

### Things that lied about being fine

**A test suite can be green over nothing.** Several checks are shaped `assert not <query
for violations>` and pass on an empty table. Two P6 checks were rewritten to assert
against the *schema* instead, and a third now reports how many rows it examined and
**skips rather than passing** when there are none.

**Four greps all said "clean" while the defect sat there.** Auditing the web app for
arithmetic-in-components (forbidden by AD-3), four separate sweeps reported no findings
while `index + 1` was plainly present. One required whitespace around the operator; one
excluded quoted lines, hiding arithmetic inside `Intl.NumberFormat(...)`; one had a
malformed POSIX bracket expression that could never match anything; one skipped `/` on any
line containing `</` or `/>`, hiding division inside JSX — the operator that builds a
ratio. **A broken pattern and a clean codebase produce identical output.** The fix was an
auditor that refuses to report unless it first re-finds a known positive *in the same
invocation*.

**The API was down and every page still served real figures.** `next: { revalidate: 60 }`
kept answering from cache. A page returning 200 with real numbers does not prove the
backend is alive. Verify with a direct `curl`, not through the app.

**I discarded the evidence I needed.** Piping a 66-minute test run through `tail -8` sent
eight lines to the output file and threw away every traceback, leaving three errors I
could only guess at. Re-ran it capturing everything; the cause was a Neon disconnect at
fixture teardown.

### Things that were silently wrong

**The front page printed a number that was simply false.** "14 economic series" was
hard-coded while `/macro` listed **13**, on a site whose entire promise is that every
figure carries its source. Two other figures on that page were computed in the browser,
which AD-3 forbids. Now counted in SQL behind `/v1/public/summary`, with a test pinning
all three to the endpoints that list the same things.

**`Decimal` is not associative, and my own property test caught me asserting otherwise.**
I had written that a bulk factor path and the per-bar function "have nothing to disagree
about" because both use `Decimal`. They disagreed on Hypothesis's seventh case: folding a
suffix from the right instead of the left moved the 28th significant digit. Far too small
to notice, which is exactly how that drift survives for years.

**`thead th { position: sticky }` never stuck.** Every table sits in `.scroller`, where
`overflow-x: auto` computes `overflow-y: auto` — so the header was sticking to a box that
never scrolls vertically. The rule was present and did nothing.

**`scripts/run_scheduler.py` had been unrunnable since P5.1.** It formatted
`f"{job.hour:02d}"`, and the three hourly RSS jobs have `hour="*"`. The script an operator
would use to *run the scheduler* raised `ValueError` on import of its own job list.

**A scroll hint asserted something false.** `.scroll-hint` hides at an 860px *viewport*,
but a table inside `details.more` sits in a container frozen at 551px. Between roughly
500–859px the two diverge, and the table claimed to scroll when it fit. The fix that had
earlier corrected that table's row heights is what pushed it under the threshold — **the
fix created the defect.**

### Things that would have shipped broken

**A build that could not reach the API exited 0 and baked the error state into static
HTML.** Three of eight routes are static and catch their own failures; a deploy during an
API blip would have shipped all three saying "could not be loaded", with `revalidate`
healing it only *after* a visitor had seen it. `failTheBuildInstead()` now rethrows during
prerender. Proven in both directions — dead API exits 1, live API exits 0 — because a
guard that never fires and one that always fires are equally useless.

**A slow answer was written as a failed one.** `/ratios` has a measured 52-second tail
against what was a 45-second budget, so a company whose data is perfectly fine could
render *"the request did not come back at all."* `ApiTimeout` is now its own state: the
service answered, we stopped waiting. Verified against a socket server that accepts the
connection and answers nothing — **a dead port does not reproduce this**, because it fails
instantly instead of timing out.

**I committed a HEAD that could not import its own scheduler.** `jobs.py` imported
`packages.brief`, which was untracked at the time. Unwound it; every commit since is
verified standalone by stashing all untracked files and importing.

**`uv add` re-resolved the entire lockfile.** Adding one package upgraded sqlalchemy,
starlette, uvicorn and others, and wrote the new dependency into the core list — when the
project deliberately keeps the analytical stack in an optional extra. Use `uv pip install`
and declare by hand.

### Things where the documents disagreed

**`alert_deliveries`.** P5.4 is required to be idempotent "via `alert_deliveries` hash",
but `docs/08` assigns that table to **P10** with a NOT NULL foreign key to an `alerts`
table that does not exist, while `SPEC.md`'s own DDL has the column nullable. A brief has
no rule behind it. Resolved by bringing the table forward with `alert_id` nullable, and
migration 0029 argues it at length rather than quietly taking the convenient DDL.

**`docs/10` §5.3's own SQL matched zero rows** — `data_sources.source_name` holds
publishers, `connector_runs.connector_name` holds job identities.

### The environment

**Neon drops a connection mid-statement on long runs.** Seen repeatedly. `pool_pre_ping`
cannot help: it checks at *checkout*, not mid-statement. Re-run the single test before
blaming a change.

**A background browser tab returns zero geometry**, so a layout measurement there is
silently wrong rather than obviously missing.

**`next dev` and `next build` both write to `.next`**, so building while the preview runs
clobbers the runtime and every chunk 500s — which reads as a broken page rather than a
clobbered directory. `NEXT_DIST_DIR` now exists for that.

---

## 5. What went right

**The split-safety chain holds end to end.** Adjusted series → indicators → the price move
on the company header. Every layer computes on adjusted closes and each is pinned by a
test that asserts the naive reading *and* the correct one. Across a 2-for-1 the naive move
is −50% and the reported move is exactly zero.

**The scenario engine does not shrug.** P6 check 13 asks for a scenario you have intuition
about. An NGN importer, half its cost base dollar-priced, naira 1,535 → 2,000: value per
share **−59.6%**, or −65.4% with dollar debt, and **+166.9%** for an exporter on the same
move. It cannot shrug structurally — a shock naming no exposure is refused, and so is an
exposure whose line was never reported.

**Measuring a convention instead of assuming it reversed a wrong verdict.** Checked
against StockCharts' published RSI table, `pandas-ta-classic` looks 0.10 wrong and I called
it a mismatch. An independent implementation of Wilder's recurrence agrees with the library
to **ten decimal places** — the published table is the imprecise one. A test written
against it would have failed and the natural fix, "write our own", would have replaced
correct code.

**The sentiment tier is derived, not guessed.** A band around zero is a band around
*silence*: VADER normalises as `x/√(x²+15)`, so `|compound| < 0.05` needs a summed valence
under 0.194 — **a tenth of one ordinary word**. It catches every neutral and misses almost
every conflict. Reading a zero for its *cause* escalates 11 of 44 articles where the naive
band escalates 20, overlapping on only 5.

**The agents kept finding bugs in my code, which is the right direction for that traffic.**
`pandas-ta-classic` returns `None` rather than a frame of NaN for a short series, so my
`_column()` would have raised `TypeError` — a newly listed security would have taken down
the whole batch. Two catch blocks had no build guard. A `.wrap-cell` scoped to `td` never
reached a row header. And there was no way for a table cell to opt out of wrapping, which
turned 29px rows into 73px and destroyed the density the redesign existed for.

**The schema caught what review would not.** `test_every_table_is_classified` failed on all
four new tables — its own header explains why that test exists: *"a P8 or P10 table quietly
created without `principal_id` or without `known_as_of`, which is a redesign to fix once it
holds data."* One of them had been anticipated *wrongly* in a comment, and correcting it
tripped a second test that refuses to accept "inherited from a parent" without a NOT NULL
key to reach one through.

---

## 6. Known, unfixed

- **A critical advisory against `next@15.5.4`**, plus two high (postcss, sharp — both via
  Next). Pre-existing, not introduced by any dependency added here. Needs a Next upgrade.
- **`/macro` prints `23.0101235833333%`.** That is the rule working as written — print a
  figure the system was *given* verbatim, round only what it *derived* — but thirteen
  decimal places is upstream float noise, not published precision. The clean fix is a
  rounded display with the exact value in the `.source` block.
- **`/companies/NOSUCH` renders its 404 page with HTTP 200.**
- **The indicator backfill runs from 2015, not 1970.** Full history adds ~1 GB to a 320 MB
  database, and only 11 of the 24 securities exist before 2010 — so the deep history has a
  changing-composition problem `SPEC.md` 2A warns against. Extending: 2010 `+387 MB`,
  2000 `+596 MB`, 1970 `+1.04 GB`.
- **`uv.lock` is untracked.** Created accidentally; commit it or delete it, but an
  untracked lockfile silently changes what `uv sync` does next.

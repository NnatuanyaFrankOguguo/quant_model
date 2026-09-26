# The standing-review register

**Task P0.13. Closes TG16 (the banned-phrase list has no owner or review cadence) and TG18 (no
restore-drill cadence is defined), and carries TG20 (dated regulatory config has no owner).**

Four mechanisms in this project degrade silently if nobody revisits them. They do not fail — they
keep returning a confident answer that has quietly stopped being true. That is the worst failure
shape in the system, because it looks exactly like success.

> **The honesty rule for this file.** `last done` is **`never`** until someone actually does the
> thing. A register that opens with comfortable dates is worse than no register, because it
> converts "we have not checked" into "we checked" without anyone deciding to lie. When you do a
> review, edit the row in the same commit as the work — not from memory a week later.

## The register

| # | What | Cadence | Owner | Last done | Next due | Why it rots |
|---|---|---|---|---|---|---|
| 1 | **Banned-phrase list** — the advice-phrasing scanner | Quarterly | Owner | **never** — the call site exists, the list is deliberately near-empty until P4 | At P4, then quarterly | TG16. Language drifts and the list ages badly, giving *false confidence* at P12, the one phase with real legal exposure. An empty list that nobody revisits still returns "clean". |
| 2 | **Restore drill** — restore a real backup into a scratch database and compare row counts | Quarterly | Owner | **2026-09-02 — PASSED** (see below) | 2026-12-02 | TG18. Drills happen once and then never. An untested backup is a file you *believe* is a backup, and the belief is only tested on the day it matters. |
| 3 | **Regulatory sweep** — NGX fee stack, ±10% band, movement rule, settlement days, Nigerian CGT, `licence_status` | Quarterly | Owner | 2026-09-01 (seeded from the docs, **not** re-verified against primary sources) | 2026-12-01 | TG20. **The NGX movement rule and the Nigerian CGT thresholds both moved during planning.** Every value in `system_config` is dated for exactly this reason; a stale value silently mis-prices every backtest and every position size. |
| 4 | **Data-source terms** — redistribution rights for every row in `data_sources` | Semi-annual, **and before any new source is ingested** | Owner | 2026-09-01 (seeded; see the caveat below) | 2027-03-01 | TG5. [PROJECT_CONTEXT.md](../PROJECT_CONTEXT.md) §9.3 calls this "the question that kills deals". Terms change without notice and nobody emails you about it. |
| 5 | **`system_config` dated-config audit** — does every in-force row still have a live `effective_to`, a `reason`, and a source? | Quarterly, with #3 | Owner | **never** | At the first P1 config change | TG20. Dated config with no audit becomes undated config with extra columns. |
| 6 | **Schema-convention allow-lists** — `tests/unit/test_schema_conventions.py` | At every phase gate | Owner | 2026-09-01 (P0 spine) | P1 gate | A new table must be *classified* deliberately. The day someone adds a name to an allow-list to make a red test green, the invariant is gone and the test still passes. |

## Caveats on the rows that say a date

**Row 3 and row 4 record that the values were *seeded*, not that they were *verified*.** The
figures came from the planning documents, several of which carry `[NEEDS VERIFICATION]` against
exactly these numbers ([docs/00_START_HERE.md](00_START_HERE.md) §11). Those markers are carried
into the `reason` column of each `system_config` row and the `notes` column of each `data_sources`
row, so the uncertainty is visible in the database and not only here. **The first genuine sweep of
both has not happened.** It needs primary sources — NGX's published fee schedule, the FIRS
position on CGT, and each provider's current terms page — and it is a P1 task, not a P0 one.

**Row 2 — what the 2026-09-02 drill actually proved.** `scripts/backup.ps1` dumped `neondb`
(54,027 bytes, 133 restorable objects, verified with `pg_restore --list` and copied to a second
location), and `scripts/restore.ps1` restored it into `quant_restore_test` and compared all 18
tables row by row. Every count matched, `pg_restore` exited 0, and the drill exited 0.

**It proved the mechanism, not the hard case.** The database held 40 rows — principals,
entitlements, tokens, seeded config and audit rows — and no business data at all. Data is what
makes a restore slow, awkward and occasionally impossible. Two clauses of
[docs/10](10_PRE_BUILD_CORRECTIONS.md) §5.5's success criterion are also still unsatisfiable:
the known-answer suite cannot run against the restored copy until P2 creates it, and no PDF can
be re-hashed from `storage_key` until P1 builds the document store. **The first drill that means
anything is the one after P1 loads macro series.**

Two defects were found and fixed by *running* it, which is the argument for the drill in one
line. Both would have reported success while doing nothing: the `connector_runs` bookkeeping
statement reached `psql` word-split (Windows PowerShell 5.1 strips inner quotes from native
command arguments, so `-c "$SQL"` arrived as the bare word `INSERT`), and the comparison query's
`-F"|"` separator reached `sh` as an unquoted pipe. Neither touched the dump itself, which is
exactly why neither would have been noticed until a restore was needed.

**Off-site is still zero.** The current status is 2 copies, 1 medium, 0 off-site — both copies
are on the same physical disk, so theft, fire, disk failure or ransomware still costs the
dataset. The gpg/rclone/R2 chain is P3-entry work ([docs/10](10_PRE_BUILD_CORRECTIONS.md) §6.1),
and `backup.ps1` refuses to claim otherwise: setting `BACKUP_OFFSITE_ENABLED=1` throws rather
than reporting a success the backup did not earn.

## The part with no good answer

**There is no second reviewer.** This is TG14: the document set asked who double-checks the golden
set and left it open behind a gate, having mis-cited the requirement as inherited. The project is
explicitly solo, so the realistic answer is that **no second person exists**, and every review in
this register is the same person checking their own work.

That is recorded here rather than left blank, because [docs/10](10_PRE_BUILD_CORRECTIONS.md) §6.2
is right that an open gate nobody can close just stops the work. The compensating measure the
document set names is **raising production sampling to weekly for P4's first two months**. Do that
instead of pretending a reviewer exists.

## How to use this file

1. Open it at every phase gate ([OPERATIONS.md](../OPERATIONS.md) §3.4 defines the gates).
2. Do the reviews that are due. A review that is due and skipped gets a row in
   [docs/06_RISK_REGISTER.md](06_RISK_REGISTER.md), not a silent pass.
3. Update `last done` **in the commit that did the work.**
4. When a review finds something, the finding goes in the document it belongs to — an ADR, the
   risk register, or a `system_config` row with a new `effective_from`. This file records only
   *that* the review happened.

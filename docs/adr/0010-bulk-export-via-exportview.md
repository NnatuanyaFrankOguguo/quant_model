# ADR-0010 — Bulk export goes through a versioned `ExportView`, never a raw `SELECT`

- **Status:** ACCEPTED (design) · **NOT YET IMPLEMENTED** — built at **P12**
- **Date:** 2026-09-03
- **Closes:** TG22 (design half) · **Sources:**
  [docs/10_PRE_BUILD_CORRECTIONS.md](../10_PRE_BUILD_CORRECTIONS.md) §4.4 and §6.5;
  [PROJECT_CONTEXT.md](../../PROJECT_CONTEXT.md) §9.4;
  [DATA_FOUNDATION.md](../../DATA_FOUNDATION.md) §6.3

## Context

Bulk CSV/Parquet export is **required** by [PROJECT_CONTEXT.md](../../PROJECT_CONTEXT.md) §9.4,
and [docs/05](../05_USER_STORIES.md) names "no bulk export" as an analyst churn trigger. It
appears in no endpoint table, no phase task and no gap row — it was promised and scheduled
nowhere.

It is being designed in P0, years before it is built, for one reason:
**its natural implementation defeats three of the five compliance mechanisms at once**
([docs/10](../10_PRE_BUILD_CORRECTIONS.md) §4.4). An export is a stream over a `SELECT`:

| Mechanism | Why it does not fire |
|---|---|
| Response-type assertion | There is no Pydantic payload for `assert_legal` to check |
| Field-name discipline | Columns come from SQL, not from a declared public model |
| Banned-phrase linting | The body is a stream; linting it means buffering the whole file |

The concrete failure, from §4.4: `/v1/public/export/companies.parquet` runs
`SELECT * FROM v_company_facts`. Six months later somebody widens that view with
`latest_signal_direction` for an internal dashboard. **Advice is now in a Parquet file on a
stranger's laptop, unrevocable, with no record of what it contained.** Nothing raised, nothing
logged. It is simultaneously the sharpest **redistribution** exposure in the system: a bulk dump
of NGX-derived prices is exactly "re-serving raw", which
[DATA_FOUNDATION.md](../../DATA_FOUNDATION.md) §6.3 says the NGX agreement forbids.

Designing it now costs nothing and is binding on P12. Discovering it in P12 — the only phase
with real legal exposure — costs a redesign during the launch window.

## Decision

**Every export is generated from a named, versioned `ExportView`: an explicit column allow-list
declared in code.** Never `SELECT *`. Never a database view another feature can widen.

Each `ExportView` declares:

| Field | Purpose |
|---|---|
| `name`, `version` | Identity; the version changes whenever the column list changes |
| `columns` | The **explicit allow-list**. This is the mechanism — an export cannot contain a column nobody wrote down |
| `mode_allowed` | `public` / `personal`. Mode is still server-derived, exactly as for a route |
| `source_ids` | The `data_sources` rows the data came from |

And the rules around it:

1. **Generation asserts `redistribution_allowed = true`** for every `source_id`, or the column
   is a derived value rather than the source's own data. This is the
   [CLAUDE.md](../../CLAUDE.md) licensing rule reaching the one surface where breaching it is
   both easiest and least recoverable — a file on someone else's disk cannot be withdrawn.
2. **Every export writes an `exports` row** — `principal_id`, `view_name`, `view_version`,
   `row_count`, `sha256`, `generated_at`, `expires_at`, `source_ids`. That row **is** the audit
   record, replacing the per-request `audit_log` row that a streamed body cannot carry
   meaningfully. It answers "what exactly did that person receive", which is the question asked
   after the fact, and the one a `SELECT`-stream cannot answer at all.
3. **URLs are signed and expire.** An export is a snapshot with a lifetime, not a permanent
   public artefact.
4. **CI fails if any `ExportView` column is not in the public column allow-list** — the same
   list the field-name discipline uses. This is what restores mechanism 2 for a surface that
   has no Pydantic model, and it is why widening a view can no longer leak: the export's columns
   are declared in code that CI reads, not in SQL that a dashboard change can alter.

**The rule in one line, for whoever builds this in P12:** the export's column list lives in the
repository, is reviewed like code, and is checked by CI — because the whole defect is that SQL
column lists are none of those things.

## Consequences

- P12 builds to a settled design instead of inventing one under launch pressure.
- Adding a column to an export is a **deliberate, reviewable act** with a version bump, not a
  side effect of someone editing a database view for an unrelated feature.
- Slightly more friction per new export. That is the point: friction on the surface that hands
  out bulk data is where friction belongs.
- The `exports` table is **not** in the P0 spine — it lands with the feature at P12, and
  `tests/unit/test_schema_conventions.py` will require it to carry `principal_id` when it does,
  automatically, without anyone remembering this ADR.
- A P12 test must assert that an `ExportView` declaring a non-allow-listed column fails CI.
  Without it this ADR is a convention, and conventions are what the five mechanisms exist to
  replace.

## Alternatives rejected

**Buffer the export and run the existing response linter over it.** *For:* reuses mechanisms 3
and 4 unchanged. *Against:* it does not address the actual hole — the column list — and a
banned-phrase scan over a Parquet file is close to meaningless, because the leak is a
*numeric column* named `latest_signal_direction`, not prose. It also puts a memory ceiling on
export size for no compliance gain.

**Export only through the existing typed API, paginated.** *For:* every mechanism applies with
no new machinery. *Against:* it is not bulk export. [docs/05](../05_USER_STORIES.md) names the
absence of real bulk export as a churn trigger; ten thousand paginated requests is the same
absence with extra steps.

**Defer the design to P12 entirely.** *For:* it is years away and the design may not survive
contact. *Against:* [docs/10](../10_PRE_BUILD_CORRECTIONS.md)'s central finding is that work
recorded in an appendix and never written into a roadmap does not get done. This ADR is the
cheapest possible insurance against that, and it changes nothing about what P0 through P11 build.

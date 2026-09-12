# Manual macro uploads (P1.7)

Collector task H, ~30 minutes a month. This is the path that still works on the morning a
government website is redesigned, and it needs no API key.

1. Copy `TEMPLATE.csv` to something dated, e.g. `nbs_2026_07.csv`.
2. Fill in the figures **from the agency's own publication**. One file per agency: the
   connector declares that agency's licence terms, so CBN figures go in a CBN file.
3. Delete the rows you have no figure for. An empty `value` means "published, no observation";
   a row you cannot fill should simply not be there.
4. Ingest:

```powershell
.venv\Scripts\python.exe scripts\ingest_csv.py --source NBS --path data\manual\nbs_2026_07.csv
```

## The one column people get wrong

**`known_as_of` is the date the agency published the figure, not the date you typed it in.**
Nigerian CPI for August is published in mid-September, so August's row is
`as_of_date=2026-08-31, known_as_of=2026-09-15`. Recording it as August would let a
point-in-time query return a number the market did not have — the lookahead that makes a
backtest look profitable and be wrong.

A row whose `known_as_of` precedes its `as_of_date` is rejected outright.

## Nothing is written unless every row parses

A partially-ingested file is worse than a rejected one: the gaps are invisible and you have
already moved on. Fix the file and re-run. Re-running a file that is already ingested is a
safe no-op — observations are never overwritten, and a revision is a new row with a later
`known_as_of`.

This directory is git-ignored except for the template and this README: uploaded figures are
data, and `data/` never goes in git.

## The upload that is waiting to be done

NBS's **December 2025 CPI report** (published mid-January 2026) moved the year-on-year
reference to the 2024 twelve-month average and revised every 2025 headline and core print —
February 2025 became 26.27% (was 23.18%), November 17.33% (was 14.45%). `NG_CPI_YOY` holds
the original prints from the Nigeria Data Portal, which froze on them; the revised series is
so far only in the `_CBN` mirror. An NBS-attributed series takes NBS bytes only, so the
revised vintage enters `NG_CPI_YOY` through this path, from NBS's own report:

- one row per month, January–November 2025, `known_as_of` = the report's publication date
  (not the month after the period — that bound is for first prints, and these are revisions);
- December 2025 onward as first prints, with their own release dates;
- `--source NBS`, and the report's URL and page noted in the commit that adds the file.

A revision is a new row with a later `known_as_of`; the originals stay, which is what makes
"what did the market know in April 2025" answerable after the upload as well as before.

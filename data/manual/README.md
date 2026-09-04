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

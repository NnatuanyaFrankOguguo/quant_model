"""Ingest a hand-prepared macro CSV. The human half of P1.7.

Collector task H (`TEAM_BRIEF.md` §2.2-H, ~30 min/month): download the month's figures from
CBN, NBS or DMO, put them in a CSV, run this. It needs no API key and no working website,
which is the whole point — it is the path that still works on the morning a government site
is redesigned.

    .venv\\Scripts\\python.exe scripts\\ingest_csv.py --source NBS --path nbs_2026_07.csv

The CSV, one row per observation:

    series_code,as_of_date,known_as_of,value
    NG_CPI_YOY,2026-07-31,2026-08-15,34.2

`known_as_of` is the date the **agency published** the figure, not the date you typed it in.
August CPI is published in mid-September; recording it as August would let a point-in-time
query return a number the market did not have.

Nothing is written unless every row parses: a partially-ingested file is worse than a
rejected one, because the gaps are invisible and you have already moved on.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from packages.common.db import get_session
from packages.ingestion.base import register
from packages.ingestion.manual_csv import MANUAL_SOURCES, ManualCsvConnector


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--source",
        required=True,
        choices=sorted(MANUAL_SOURCES),
        help="The agency the figures came from. Its licence terms apply to them.",
    )
    parser.add_argument("--path", required=True, type=Path, help="The CSV to ingest")
    args = parser.parse_args(argv)

    connector = ManualCsvConnector(args.source)
    with get_session() as session:
        register(session, connector)
        result = connector.run(session, path=args.path)

    if result.status != "ok":
        print(f"FAILED: {result.error}", file=sys.stderr)
        print(
            "Nothing was written. Fix the file and re-run — the connector_runs row records "
            "this attempt either way.",
            file=sys.stderr,
        )
        return 1

    print(f"Parsed {result.records_parsed} record(s); inserted {result.rows_written}.")
    if result.rows_written == 0 and result.records_parsed > 0:
        print(
            "Every row was already present, so nothing was inserted. That is a successful "
            "no-op, not a failure — observations are never overwritten, and a revision is a "
            "new row with a later known_as_of."
        )
    print(f"Stored as source_document id={result.source_document_id}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

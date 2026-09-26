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
from pathlib import Path

from packages.common.console import configure_logging, error, step, success, warning
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
    configure_logging()

    connector = ManualCsvConnector(args.source)
    with get_session() as session:
        with step("Register the source licence", source=args.source) as registering:
            data_source_id = register(session, connector)
            registering.result(data_source_id=data_source_id)
        # The connector's own fetch / store raw / parse / write / record stages appear as
        # numbered sub-steps of this one.
        with step("Ingest the CSV", path=str(args.path)) as ingesting:
            result = connector.run(session, path=args.path)
            if result.status != "ok":
                ingesting.fail("nothing was written", error=result.error)
            else:
                ingesting.result(
                    records_parsed=result.records_parsed,
                    rows_inserted=result.rows_written,
                    source_document_id=result.source_document_id,
                )

    if result.status != "ok":
        error(
            "ingest failed: fix the file and re-run; the connector_runs row records this "
            "attempt either way",
            error=result.error,
        )
        return 1

    if result.rows_written == 0 and result.records_parsed > 0:
        warning(
            "every row was already present, so nothing was inserted: a successful no-op, "
            "not a failure: observations are never overwritten, and a revision is a new row "
            "with a later known_as_of",
            records_parsed=result.records_parsed,
        )
    success(
        "ingested",
        records_parsed=result.records_parsed,
        rows_inserted=result.rows_written,
        source_document_id=result.source_document_id,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

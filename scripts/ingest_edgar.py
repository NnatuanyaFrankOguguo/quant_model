r"""Ingest one US company from SEC EDGAR: identity, then every filed statement. P2.1.

    .venv\Scripts\python.exe scripts\ingest_edgar.py --ticker AAPL
    .venv\Scripts\python.exe scripts\ingest_edgar.py --cik 320193

Two connectors run in order, each as its own numbered step with the pipeline's fetch /
store raw / parse / write / record stages beneath it:

1. **submissions** - who the company is: legal name, tickers, exchanges, fiscal year-end
   month, SIC code. Registers `companies`, `securities`, `security_identifiers`,
   `industries`. Reference data is inserted when absent and never overwritten.
2. **companyfacts** - every XBRL fact the company ever filed, written through chart
   `v0.1` as versioned statements and line items. A period's first report is version 1;
   a later filing that re-reports it unchanged writes nothing; one that changes a figure
   is a restatement, version n+1, with the old version's `superseded_by` set.

Re-running is safe and cheap: the raw documents are stored by hash, statements that did
not change are not rewritten, and every run leaves a `connector_runs` row either way.

`SEC_USER_AGENT` must be set (a real name and email); without it EDGAR refuses and so do we.
"""

from __future__ import annotations

import argparse

from packages.common.console import configure_logging, error, step, success
from packages.common.db import get_session
from packages.ingestion.base import register
from packages.ingestion.edgar import (
    EdgarCompanyFactsConnector,
    EdgarSubmissionsConnector,
    resolve_cik,
    zero_pad_cik,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    who = parser.add_mutually_exclusive_group(required=True)
    who.add_argument("--ticker", help="Exchange ticker, resolved through EDGAR's own list")
    who.add_argument("--cik", help="SEC Central Index Key, with or without zero-padding")
    args = parser.parse_args(argv)
    configure_logging()

    submissions = EdgarSubmissionsConnector()
    facts = EdgarCompanyFactsConnector()

    with get_session() as session:
        with step("Register the SEC EDGAR licence") as registering:
            data_source_id = register(session, submissions)
            registering.result(data_source_id=data_source_id)

        with step("Resolve the company") as resolving:
            if args.cik:
                cik = zero_pad_cik(args.cik)
            else:
                cik = resolve_cik(session, submissions, args.ticker)
            resolving.result(cik=cik, ticker=args.ticker or "-")

        with step("Ingest submissions (identity)") as identity:
            first = submissions.run(session, run_name=f"edgar_submissions:{cik}", cik=cik)
            if first.status != "ok":
                identity.fail("submissions failed", error=first.error)
            else:
                identity.result(rows_inserted=first.rows_written)

        if first.status != "ok":
            error("stopped: without identity there is no company to attach statements to")
            return 1

        with step("Ingest company facts (statements)") as statements:
            second = facts.run(session, run_name=f"edgar_companyfacts:{cik}", cik=cik)
            if second.status != "ok":
                statements.fail("companyfacts failed", error=second.error)
            else:
                statements.result(
                    facts_parsed=second.records_parsed, rows_inserted=second.rows_written
                )

    if second.status != "ok":
        error("companyfacts ingest failed; the connector_runs row records the attempt")
        return 1
    success(
        "ingested",
        cik=cik,
        identity_rows=first.rows_written,
        facts_parsed=second.records_parsed,
        statement_rows=second.rows_written,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

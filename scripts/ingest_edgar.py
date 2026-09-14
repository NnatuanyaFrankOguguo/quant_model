r"""Ingest US companies from SEC EDGAR: identity, then every filed statement. P2.1.

    .venv\Scripts\python.exe scripts\ingest_edgar.py --ticker AAPL
    .venv\Scripts\python.exe scripts\ingest_edgar.py --cik 320193
    .venv\Scripts\python.exe scripts\ingest_edgar.py --universe      # every name in US_UNIVERSE

Two connectors run in order for each company, each as its own numbered step with the
pipeline's fetch / store raw / parse / write / record stages beneath it:

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
    PREDECESSORS,
    EdgarCompanyFactsConnector,
    EdgarSubmissionsConnector,
    load_ticker_map,
    resolve_cik,
    zero_pad_cik,
)
from packages.scheduler.jobs import US_UNIVERSE


def ingest_one(cik: str, *, label: str) -> bool:
    """Identity, then statements, for one company. True on success."""
    submissions = EdgarSubmissionsConnector()
    facts = EdgarCompanyFactsConnector()
    with get_session() as session:
        with step(f"Ingest {label}: submissions (identity)", cik=cik) as identity:
            first = submissions.run(session, run_name=f"edgar_submissions:{cik}", cik=cik)
            if first.status != "ok":
                identity.fail("submissions failed", error=first.error)
                return False
            identity.result(rows_inserted=first.rows_written)

        with step(f"Ingest {label}: company facts (statements)", cik=cik) as statements:
            second = facts.run(session, run_name=f"edgar_companyfacts:{cik}", cik=cik)
            if second.status != "ok":
                statements.fail("companyfacts failed", error=second.error)
                return False
            statements.result(facts_parsed=second.records_parsed, rows_inserted=second.rows_written)

        predecessor = PREDECESSORS.get(cik)
        if predecessor is not None:
            with step(
                f"Ingest {label}: predecessor registrant's filings",
                cik=predecessor.cik,
                succeeded_on=predecessor.succeeded_on.isoformat(),
                evidence=predecessor.evidence,
            ) as history:
                for stage, connector in (("submissions", submissions), ("companyfacts", facts)):
                    run = connector.run(
                        session, run_name=f"edgar_{stage}:{predecessor.cik}", cik=predecessor.cik
                    )
                    if run.status != "ok":
                        history.fail(f"predecessor {stage} failed", error=run.error)
                        return False
                history.result(rows_inserted=run.rows_written)
    return True


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    who = parser.add_mutually_exclusive_group(required=True)
    who.add_argument("--ticker", help="Exchange ticker, resolved through EDGAR's own list")
    who.add_argument("--cik", help="SEC Central Index Key, with or without zero-padding")
    who.add_argument("--universe", action="store_true", help="Every ticker in US_UNIVERSE")
    args = parser.parse_args(argv)
    configure_logging()

    resolver = EdgarSubmissionsConnector()
    with get_session() as session:
        with step("Register the SEC EDGAR licence") as registering:
            data_source_id = register(session, resolver)
            registering.result(data_source_id=data_source_id)

        with step("Resolve the companies") as resolving:
            targets: list[tuple[str, str]] = []  # (cik, label)
            if args.cik:
                targets.append((zero_pad_cik(args.cik), f"CIK {zero_pad_cik(args.cik)}"))
            else:
                tickers = list(US_UNIVERSE) if args.universe else [args.ticker]
                ticker_map = load_ticker_map(session, resolver)
                for ticker in tickers:
                    cik = resolve_cik(session, resolver, ticker, ticker_map=ticker_map)
                    targets.append((cik, ticker.upper()))
            resolving.result(companies=len(targets))

    failed = [label for cik, label in targets if not ingest_one(cik, label=label)]
    if failed:
        error("ingest failed for some companies", failed=len(failed), of=len(targets), which=failed)
        return 1
    success("ingested", companies=len(targets))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

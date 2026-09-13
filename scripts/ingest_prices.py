r"""Load daily prices for a US ticker from Yahoo Finance, as traded. P2.3.

    .venv\Scripts\python.exe scripts\ingest_prices.py --ticker AAPL            # full history
    .venv\Scripts\python.exe scripts\ingest_prices.py --ticker AAPL --days 30  # recent window
    .venv\Scripts\python.exe scripts\ingest_prices.py --universe --days 30     # every US name

The company must already be registered (`scripts/ingest_edgar.py`): a price attaches to a
security, never to a ticker string, and the ticker is looked up in `security_identifiers`.

Prices are stored as they traded. Yahoo serves split-adjusted history, and the connector
multiplies the provider's own split ratios back out before storing - see
`packages/ingestion/yahoo.py`. A bar seen again unchanged is not rewritten; a bar seen again
with different figures is a new vintage dated the day the change was seen.
"""

from __future__ import annotations

import argparse

from packages.common.console import configure_logging, error, step, success
from packages.scheduler.jobs import US_UNIVERSE, price_job
from packages.scheduler.runner import run_job


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    who = parser.add_mutually_exclusive_group(required=True)
    who.add_argument("--ticker", help="One exchange ticker, e.g. AAPL")
    who.add_argument("--universe", action="store_true", help="Every ticker in US_UNIVERSE")
    parser.add_argument(
        "--days",
        type=int,
        default=None,
        help="Only the last N days. Default: the whole history the source has.",
    )
    args = parser.parse_args(argv)
    configure_logging()

    tickers = list(US_UNIVERSE) if args.universe else [args.ticker.strip().upper()]
    with step("Plan the price loads", tickers=len(tickers), days=args.days or "all") as planning:
        jobs = [price_job(ticker, lookback_days=args.days) for ticker in tickers]
        planning.result(jobs=len(jobs))

    failed = [job.identity() for job in jobs if run_job(job).status != "ok"]
    if failed:
        error("price loads failed", failed=len(failed), of=len(jobs), which=failed)
        return 1
    success("prices loaded", tickers=len(jobs))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

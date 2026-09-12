r"""Run the connector schedule. P1.5 / TG8.

    .venv\Scripts\python.exe scripts
un_scheduler.py          # run forever
    .venv\Scripts\python.exe scripts
un_scheduler.py --once   # run every job now, then exit

Until this existed, `build_scheduler()` was a function nothing called — the schedule was
designed and unstartable, which is the same as not having one. `OPERATIONS.md` §2.3's whole
point is that a connector which never runs fails exactly like one that runs and returns
nothing, only quieter.

**The job list is here, in code, not in a crontab.** One place says what runs and how often,
and `scripts/check_connectors.py` compares what ran against the same expectation. A schedule
living only in the operating system is a schedule nobody can review in a pull request.

Times are UTC (TG21), and deliberately coarse. These sources publish monthly or daily at
best; polling more often is load on someone else's server for no new data.
"""

from __future__ import annotations

import argparse
import sys
import time

import structlog

from packages.ingestion.cbn import (
    CbnExchangeRateConnector,
    CbnInflationConnector,
    CbnMoneyMarketConnector,
)
from packages.ingestion.fred import FRED_SERIES, FredConnector
from packages.ingestion.nigeria_data_portal import (
    ITEM_KEYS,
    NigeriaDataPortalCpiConnector,
    NigeriaDataPortalGdpConnector,
)
from packages.scheduler.runner import ScheduledJob, build_scheduler, run_job

_log = structlog.get_logger("scheduler")


def build_jobs() -> list[ScheduledJob]:
    """Every scheduled data pull.

    CBN first and early: the FX rate is the only daily Nigerian series, and the rest of the
    day's work reads it. FRED runs after, one job per series, staggered by a few minutes so a
    free API we do not pay for never sees four simultaneous requests.

    FRED jobs ask for the default real-time window, which is every vintage. That is correct
    for three of the four series. `DGS10` exceeds FRED's 2,000-vintage response cap and needs
    windowed backfilling — see `packages.ingestion.fred.windows_from_vintage_dates`. Its
    scheduled job still works for keeping up to date, because the *recent* window is small;
    the historical load is a one-off, not a scheduled concern.
    """
    jobs: list[ScheduledJob] = [
        ScheduledJob(connector=CbnExchangeRateConnector(), params={}, hour=5, minute=30),
        ScheduledJob(connector=CbnMoneyMarketConnector(), params={}, hour=5, minute=45),
        ScheduledJob(connector=CbnInflationConnector(), params={}, hour=6, minute=0),
    ]
    # NBS CPI via the Nigeria Data Portal. Monthly data, so a daily pull is generous; it runs
    # daily anyway because the cost is one request and the alternative is noticing a release
    # a month late.
    for offset, item in enumerate(ITEM_KEYS):
        jobs.append(
            ScheduledJob(
                connector=NigeriaDataPortalCpiConnector(),
                params={"item": item},
                hour=6,
                minute=5 + offset * 5,
                job_id=f"ndp:{item}",
            )
        )
    # NBS GDP growth via the same portal. Quarterly data polled daily, for the same reason:
    # one request, and the alternative is a release noticed a quarter late.
    jobs.append(
        ScheduledJob(
            connector=NigeriaDataPortalGdpConnector(),
            params={},
            hour=6,
            minute=5 + len(ITEM_KEYS) * 5,
            job_id="ndp:gdp",
        )
    )
    for offset, series_id in enumerate(FRED_SERIES):
        jobs.append(
            ScheduledJob(
                connector=FredConnector(timeout_sec=180),
                params={"series_id": series_id},
                hour=6,
                minute=15 + offset * 5,
                job_id=f"fred:{series_id}",
            )
        )
    return jobs


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--once",
        action="store_true",
        help="Run every job immediately and exit. Use this to verify the list, or to catch up.",
    )
    args = parser.parse_args(argv)

    jobs = build_jobs()

    if args.once:
        failures = 0
        for job in jobs:
            result = run_job(job)
            status = "ok " if result.status == "ok" else "ERR"
            print(
                f"{status} {job.identity():38} parsed={result.records_parsed:>7} "
                f"inserted={result.rows_written:>7}"
            )
            if result.status != "ok":
                failures += 1
                print(f"      {result.error}", file=sys.stderr)
        print(f"\n{len(jobs) - failures} of {len(jobs)} jobs succeeded.")
        # Non-zero on any failure, so a one-shot run is usable as a scheduled task whose
        # exit code is the alert.
        return 1 if failures else 0

    scheduler = build_scheduler(jobs)
    scheduler.start()
    for job in jobs:
        _log.info("scheduled", job=job.identity(), at_utc=f"{job.hour:02d}:{job.minute:02d}")
    print(f"{len(jobs)} jobs scheduled (UTC). Ctrl+C to stop.")
    try:
        while True:
            time.sleep(60)
    except KeyboardInterrupt:
        print("\nStopping.")
        scheduler.shutdown(wait=False)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

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
import time

from packages.common.console import configure_logging, error, info, step, success, warning
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

#: Per-series overrides of the FRED request window. Only a series that FRED refuses in full
#: needs one. Three years of a daily series is ~760 vintage dates, well under the 2,000 cap
#: and far longer than any outage the scheduler is expected to recover from; anything older
#: is already loaded, and `Connector.write()` refuses the unchanged re-sends a bounded window
#: carries, so the job inserts only what is genuinely new.
FRED_JOB_PARAMS: dict[str, dict[str, object]] = {
    "DGS10": {"lookback_days": 3 * 365},
}


def build_jobs() -> list[ScheduledJob]:
    """Every scheduled data pull.

    CBN first and early: the FX rate is the only daily Nigerian series, and the rest of the
    day's work reads it. FRED runs after, one job per series, staggered by a few minutes so a
    free API we do not pay for never sees four simultaneous requests.

    FRED jobs ask for the default real-time window, which is every vintage. That is correct
    for three of the four series. `DGS10` exceeds FRED's 2,000-vintage response cap: its
    history was loaded once in windows (`packages.ingestion.fred.windows_from_vintage_dates`)
    and its scheduled job asks only for the last three years of vintages. An earlier version
    of this docstring claimed the default window "still works for keeping up to date"; it
    did not — every scheduled DGS10 run was refused, and the first run under the numbered
    console made that impossible to miss.
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
                params={"series_id": series_id, **FRED_JOB_PARAMS.get(series_id, {})},
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
    configure_logging()

    with step("Build the job list") as building:
        jobs = build_jobs()
        for job in jobs:
            building.note("job", id=job.identity(), at_utc=f"{job.hour:02d}:{job.minute:02d}")
        building.result(jobs=len(jobs))

    if args.once:
        # Each `run_job` is its own top-level step, numbered after the one above, with the
        # connector's fetch / store raw / parse / write / record stages nested beneath it.
        failed = [job.identity() for job in jobs if run_job(job).status != "ok"]
        if failed:
            # Non-zero on any failure, so a one-shot run is usable as a scheduled task
            # whose exit code is the alert.
            error("jobs failed", failed=len(failed), of=len(jobs), which=failed)
            return 1
        success("every job succeeded", jobs=len(jobs))
        return 0

    with step("Start the scheduler", timezone="UTC") as starting:
        scheduler = build_scheduler(jobs)
        scheduler.start()
        starting.result(jobs=len(jobs))
    info("running; each firing is logged as its own numbered flow. Ctrl+C to stop.")
    try:
        while True:
            time.sleep(60)
    except KeyboardInterrupt:
        warning("stopping on Ctrl+C")
        scheduler.shutdown(wait=False)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

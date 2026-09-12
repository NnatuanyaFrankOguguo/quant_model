"""The job list: every scheduled data pull, in code, in one place. P1.5.

`scripts/run_scheduler.py` runs these; `scripts/check_connectors.py` expects a run from each
of them. Until this module existed the two scripts each kept their own list, and a connector
had to be added to both by hand — the GDP connector was, and the day one is forgotten the
health check goes quiet about exactly the job that never ran. `expected_run_names()` is
derived from the same list the scheduler runs, so that cannot drift.

**A job's identity is the name its runs are recorded under.** `connector_runs.connector_name`
used to be the connector class's `name`, so all four FRED jobs wrote rows as `fred` and the
health check saw three successes for one series that failed on every run. `run_job` now
records each run under the job's identity — `fred:DGS10`, `ndp:gdp` — and the CBN jobs are
given ids equal to their connector names so their history reads continuously.
"""

from __future__ import annotations

from packages.ingestion.cbn import (
    CbnExchangeRateConnector,
    CbnInflationConnector,
    CbnMoneyMarketConnector,
)
from packages.ingestion.fred import FRED_SERIES, FredConnector
from packages.ingestion.manual_csv import MANUAL_SOURCES
from packages.ingestion.nigeria_data_portal import (
    ITEM_KEYS,
    NigeriaDataPortalCpiConnector,
    NigeriaDataPortalGdpConnector,
)
from packages.scheduler.runner import ScheduledJob

__all__ = ["FRED_JOB_PARAMS", "build_jobs", "expected_run_names"]

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

    Times are UTC (TG21), and deliberately coarse. These sources publish monthly or daily at
    best; polling more often is load on someone else's server for no new data.
    """
    jobs: list[ScheduledJob] = [
        ScheduledJob(
            connector=CbnExchangeRateConnector(),
            params={},
            hour=5,
            minute=30,
            job_id=CbnExchangeRateConnector.name,
        ),
        ScheduledJob(
            connector=CbnMoneyMarketConnector(),
            params={},
            hour=5,
            minute=45,
            job_id=CbnMoneyMarketConnector.name,
        ),
        ScheduledJob(
            connector=CbnInflationConnector(),
            params={},
            hour=6,
            minute=0,
            job_id=CbnInflationConnector.name,
        ),
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


def expected_run_names() -> set[str]:
    """Every name the health check should see a run under.

    The scheduled jobs, by identity, plus the manual CSV paths, which run when a human feeds
    them — monthly rather than daily — and are listed so that their silence is reported
    rather than unnoticed.
    """
    names = {job.identity() for job in build_jobs()}
    names.update(f"manual_csv_{source.lower()}" for source in MANUAL_SOURCES)
    return names

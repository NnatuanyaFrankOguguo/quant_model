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
from packages.ingestion.edgar import EdgarCompanyRefresh
from packages.ingestion.fred import FRED_SERIES, FredConnector
from packages.ingestion.manual_csv import MANUAL_SOURCES
from packages.ingestion.nigeria_data_portal import (
    ITEM_KEYS,
    NigeriaDataPortalCpiConnector,
    NigeriaDataPortalGdpConnector,
)
from packages.ingestion.yahoo import YahooChartConnector
from packages.scheduler.runner import Expectation, ScheduledJob

__all__ = [
    "FRED_JOB_PARAMS",
    "US_UNIVERSE",
    "build_jobs",
    "edgar_refresh_job",
    "expected_run_names",
    "expected_run_names_by_source",
    "expected_schedule",
    "price_job",
]

#: The US names P2 covers. `docs/UNIVERSE.md` keeps the US side "separate and unconstrained"
#: - EDGAR is free and structured, so breadth costs almost nothing here. Two banks (JPM,
#: BAC) are included on purpose: they exercise the `financial` template, whose income keys
#: have no XBRL mapping yet and resolve to NULL, which is the honest state of chart v0.1.
#: Statements come from EDGAR nightly (`edgar_refresh_job`, and by hand through
#: `scripts/ingest_edgar.py`); prices from Yahoo after the close, through the jobs below.
US_UNIVERSE: tuple[str, ...] = (
    "AAPL", "MSFT", "GOOGL", "AMZN", "META", "NVDA", "TSLA", "JPM", "BAC", "XOM", "CVX",
    "JNJ", "PFE", "PG", "KO", "WMT", "HD", "DIS", "CAT", "IBM", "INTC", "CSCO", "ORCL", "UNH",
)  # fmt: skip

#: A daily bar is final at the close; thirty days of look-back covers a long weekend, a
#: holiday week and Yahoo's late corrections, and the writer refuses unchanged bars anyway.
PRICE_LOOKBACK_DAYS = 30


def price_job(ticker: str, *, lookback_days: int | None = PRICE_LOOKBACK_DAYS) -> ScheduledJob:
    """One Yahoo price load. US markets close 21:00 UTC; the bars are settled by 22:30."""
    params: dict[str, object] = {"symbol": ticker}
    if lookback_days is not None:
        params["lookback_days"] = lookback_days
    minute = 30 + (US_UNIVERSE.index(ticker) if ticker in US_UNIVERSE else 0)
    return ScheduledJob(
        connector=YahooChartConnector(),
        params=params,
        hour=22 + minute // 60,
        minute=minute % 60,
        job_id=f"yahoo:{ticker}",
        publishes_every_days=7,
    )


#: How often each kind of source publishes, at the longest. A monthly series and its
#: slack; a quarter plus the 90-day 10-K deadline; the CBN's Monetary Policy Committee
#: meets every two months.
MONTHLY_DAYS = 45
QUARTERLY_DAYS = 185
MPC_DAYS = 75

#: EDGAR accepts filings until 22:00 US Eastern, 02:00 UTC in winter; the companyfacts
#: JSON is rebuilt overnight. Three in the morning UTC is after both, and the jobs are six
#: minutes apart because a company with a new 10-K takes the writer up to five minutes:
#: twenty-four names end by 05:24, before the CBN jobs begin at 05:30.
EDGAR_REFRESH_HOUR = 3
EDGAR_REFRESH_SPACING_MINUTES = 6


def edgar_refresh_job(ticker: str) -> ScheduledJob:
    """One company's nightly EDGAR refresh - identity, then statements - under `edgar:<ticker>`."""
    minute = US_UNIVERSE.index(ticker) if ticker in US_UNIVERSE else 0
    minute *= EDGAR_REFRESH_SPACING_MINUTES
    return ScheduledJob(
        connector=EdgarCompanyRefresh(),
        params={"ticker": ticker},
        hour=EDGAR_REFRESH_HOUR + minute // 60,
        minute=minute % 60,
        job_id=f"edgar:{ticker}",
        publishes_every_days=QUARTERLY_DAYS,
    )


#: Per-series overrides of the FRED request window. Only a series that FRED refuses in full
#: needs one. Three years of a daily series is ~760 vintage dates, well under the 2,000 cap
#: and far longer than any outage the scheduler is expected to recover from; anything older
#: is already loaded, and `Connector.write()` refuses the unchanged re-sends a bounded window
#: carries, so the job inserts only what is genuinely new.
FRED_JOB_PARAMS: dict[str, dict[str, object]] = {
    "DGS10": {"lookback_days": 3 * 365},
}

#: How often each FRED series publishes: the 10-year yield daily, the rest monthly, and
#: the World Bank's Nigerian CPI once a year.
FRED_CADENCE_DAYS: dict[str, int] = {"DGS10": 7, "FPCPITOTLZGNGA": 400}


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
            publishes_every_days=7,
        ),
        ScheduledJob(
            connector=CbnMoneyMarketConnector(),
            params={},
            hour=5,
            minute=45,
            job_id=CbnMoneyMarketConnector.name,
            publishes_every_days=MPC_DAYS,
        ),
        ScheduledJob(
            connector=CbnInflationConnector(),
            params={},
            hour=6,
            minute=0,
            job_id=CbnInflationConnector.name,
            publishes_every_days=MONTHLY_DAYS,
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
                publishes_every_days=MONTHLY_DAYS,
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
            publishes_every_days=QUARTERLY_DAYS,
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
                publishes_every_days=FRED_CADENCE_DAYS.get(series_id, MONTHLY_DAYS),
            )
        )
    # US prices after the close, one job per name, a minute apart.
    jobs.extend(price_job(ticker) for ticker in US_UNIVERSE)
    # US statements before dawn UTC, one job per name, six minutes apart.
    jobs.extend(edgar_refresh_job(ticker) for ticker in US_UNIVERSE)
    return jobs


def expected_schedule() -> dict[str, Expectation]:
    """Every expected run name with when it runs and how often its source publishes.
    Derived from the same list the scheduler runs, like `expected_run_names`; the manual
    paths are monthly uploads with no scheduled time."""
    schedule: dict[str, Expectation] = {
        job.identity(): Expectation(f"{job.hour:02d}:{job.minute:02d}", job.publishes_every_days)
        for job in build_jobs()
    }
    for source in MANUAL_SOURCES:
        schedule[f"manual_csv_{source.lower()}"] = Expectation(None, MONTHLY_DAYS)
    return schedule


def expected_run_names() -> set[str]:
    """Every name the health check should see a run under.

    The scheduled jobs, by identity, plus the manual CSV paths, which run when a human feeds
    them — monthly rather than daily — and are listed so that their silence is reported
    rather than unnoticed.
    """
    names = {job.identity() for job in build_jobs()}
    names.update(f"manual_csv_{source.lower()}" for source in MANUAL_SOURCES)
    return names


def expected_run_names_by_source() -> dict[str, set[str]]:
    """Every `data_sources.source_name` mapped to the run names that count as it being alive.

    `docs/10` §5.3's SQL joins `connector_runs.connector_name = data_sources.source_name`.
    Those two columns have never held the same vocabulary, and nothing in the schema says so:
    `source_name` is the publisher on the licensing register - 'FRED', 'SEC EDGAR', 'Yahoo
    Finance' - while `connector_name` is a *job identity* - 'fred:DGS10', 'edgar:AAPL',
    'yahoo:AAPL' - which `run_job` writes and this module's docstring explains. Run as
    written, the join matches on nothing, every source reports as never-run, and the check
    meant to end a silent failure becomes one. This function is that bridge.

    Derived from `build_jobs()` rather than written out, for the same reason
    `expected_run_names` is: a mapping maintained by hand goes quiet about exactly the job
    somebody forgot to add to it, and the whole subject here is what silence hides.
    `declare_licence()` is the authority for which register row a connector belongs to
    because it is the same call `register()` makes on every run, so the two cannot drift.

    Manual CSV paths map to their agency directly - `manual_csv_nbs` is how the NBS row is
    heard from, and for the NBS and the DMO it is the only way.
    """
    by_source: dict[str, set[str]] = {}
    for job in build_jobs():
        by_source.setdefault(job.connector.declare_licence().source_name, set()).add(job.identity())
    for source in MANUAL_SOURCES:
        by_source.setdefault(source, set()).add(f"manual_csv_{source.lower()}")
    return by_source

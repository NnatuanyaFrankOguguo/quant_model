"""The job runner and connector health. P1.5, closing TG8.

`SPEC.md` §3.1's monorepo has no scheduler package and nothing owns job scheduling
(`DATA_FOUNDATION.md` §3.5 names APScheduler but no task adopts it). ADR-0002 adds the
package; this module is its first content.

**Why a scheduler is a correctness concern rather than a convenience.** A connector that
never runs fails exactly like a connector that runs and returns nothing: the dashboard keeps
showing last month's figure, with an as-of date nobody re-reads. `OPERATIONS.md` §2.3 makes
`connector_runs.rows_written` the detector, and this module supplies the other half — the
query that actually looks at it, and a schedule that produces rows to look at.

The health rules, and why each is shaped the way it is:

* **`status='ok'` with `rows_written=0`** is the classic silent scraper failure — the page
  loads, the parser runs, the selector matches nothing. It is *not* an error on its own: a
  re-fetch of unchanged data legitimately writes nothing. It becomes a finding when it
  repeats across the window in which the source was expected to publish.
* **No run at all** is worse, and easier to miss, because there is no row to be suspicious
  of. Absence is checked explicitly rather than inferred from a list of rows.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from typing import Any

import structlog
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from packages.common.db import get_session
from packages.common.models import ConnectorRun
from packages.common.timez import utcnow
from packages.ingestion.base import Connector, ConnectorRunResult, register

__all__ = [
    "ConnectorHealth",
    "ScheduledJob",
    "build_scheduler",
    "check_health",
    "run_job",
]

_log = structlog.get_logger(__name__)


@dataclass(frozen=True)
class ScheduledJob:
    """One connector invocation, with the parameters it needs and when it runs."""

    connector: Connector
    # `Any`, not `object`: these are splatted into `Connector.run(**params)`, whose
    # keyword-only `storage` parameter is typed, and `object` values are not assignable to it.
    params: dict[str, Any]
    #: APScheduler cron-ish fields. Deliberately coarse: these sources publish on a monthly
    #: or quarterly rhythm, so polling more often than daily is load on someone else's
    #: server for no new data.
    hour: int = 6
    minute: int = 0
    job_id: str = ""

    def identity(self) -> str:
        return self.job_id or f"{self.connector.name}:{sorted(self.params.items())}"


@dataclass(frozen=True)
class ConnectorHealth:
    connector_name: str
    last_run_at: dt.datetime | None
    last_status: str | None
    runs_in_window: int
    rows_in_window: int
    #: True when something needs a human. The reason is in `finding`.
    unhealthy: bool
    finding: str | None


def run_job(job: ScheduledJob) -> ConnectorRunResult:
    """Run one connector in its own session, registering its source first.

    Registration is not skippable and not cached: `register()` re-checks that the declared
    licence still agrees with the reviewed `data_sources` row on every run, so a connector
    whose rights were quietly widened in code stops here rather than at the point where the
    data has already been served.
    """
    with get_session() as session:
        register(session, job.connector)
        result = job.connector.run(session, **job.params)
    _log.info(
        "connector_run",
        connector=result.connector_name,
        status=result.status,
        rows_written=result.rows_written,
        records_parsed=result.records_parsed,
    )
    return result


def build_scheduler(jobs: list[ScheduledJob]):
    """A `BackgroundScheduler` with one job per connector.

    Imported lazily so that the API and the test suite do not pay for APScheduler, and so
    that a missing optional dependency surfaces here rather than at import of the package.
    """
    from apscheduler.schedulers.background import BackgroundScheduler
    from apscheduler.triggers.cron import CronTrigger

    scheduler = BackgroundScheduler(timezone="UTC")  # TG21: schedules are UTC, like storage
    for job in jobs:
        scheduler.add_job(
            run_job,
            trigger=CronTrigger(hour=job.hour, minute=job.minute, timezone="UTC"),
            args=[job],
            id=job.identity(),
            # A missed run (laptop asleep) should run once on resume, not N times.
            coalesce=True,
            max_instances=1,
            misfire_grace_time=3600,
        )
    return scheduler


def check_health(
    session: Session, *, window_days: int = 30, now: dt.datetime | None = None
) -> list[ConnectorHealth]:
    """Health for every connector that has ever run, plus findings worth acting on.

    Deliberately reports on connectors *seen in the table*: a connector that has never run
    once has no row here, and that absence is what `scripts/check_connectors.py` reports
    separately against the list of jobs it expects. A health check that can only see things
    that already happened cannot tell you about the thing that never started.
    """
    now = now or utcnow()
    since = now - dt.timedelta(days=window_days)

    rows = session.execute(
        select(
            ConnectorRun.connector_name,
            func.max(ConnectorRun.started_at),
            func.count(),
            func.coalesce(func.sum(ConnectorRun.rows_written), 0),
        )
        .where(ConnectorRun.started_at >= since)
        .group_by(ConnectorRun.connector_name)
        .order_by(ConnectorRun.connector_name)
    ).all()

    health: list[ConnectorHealth] = []
    for name, last_run_at, runs, rows_written in rows:
        last_status = session.execute(
            select(ConnectorRun.status)
            .where(ConnectorRun.connector_name == name)
            .order_by(ConnectorRun.started_at.desc())
            .limit(1)
        ).scalar_one_or_none()

        finding: str | None = None
        if last_status == "error":
            finding = "last run failed"
        elif runs > 1 and rows_written == 0:
            # One quiet run is normal. Several in a row, across a window in which the source
            # was expected to publish, is the signature OPERATIONS 2.3 describes.
            finding = (
                f"{runs} runs in {window_days} days wrote zero rows — the classic silent "
                f"scraper failure: the page loads, the parser runs, the selector matches "
                f"nothing"
            )
        health.append(
            ConnectorHealth(
                connector_name=name,
                last_run_at=last_run_at,
                last_status=last_status,
                runs_in_window=runs,
                rows_in_window=int(rows_written),
                unhealthy=finding is not None,
                finding=finding,
            )
        )
    return health

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
import time
from dataclasses import dataclass
from typing import Any

import structlog
from sqlalchemy import func, select
from sqlalchemy.exc import DBAPIError, InterfaceError, OperationalError
from sqlalchemy.orm import Session

from packages.common.console import reset_steps, step
from packages.common.db import get_session
from packages.common.models import ConnectorRun
from packages.common.timez import utcnow
from packages.ingestion.base import Connector, ConnectorRunResult, record_run, register

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
    #: How often the source publishes something new, in days, at the longest. A run
    #: that writes nothing inside that span is a quiet day, not a finding; a window
    #: of quiet runs longer than it is the silent-failure signature. Daily sources
    #: get a week (holidays); monthly ones a month plus slack; quarterly ones a
    #: quarter plus the filing deadline.
    publishes_every_days: int = 7

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


#: Transient database failures worth one more attempt. Observed in practice, not theorised:
#: Neon scales to zero, and a run that starts while the endpoint is asleep gets
#: `AdminShutdown: terminating connection due to administrator command` mid-statement.
#: `pool_pre_ping` does not cover it — the connection was alive at checkout and killed during
#: the work. Left unhandled, every unattended run that happens to land on a cold endpoint
#: writes an `error` row, and the health check cannot tell that apart from a real failure
#: (ADR-0008 records the cold-start cost; this is where it is paid).
_RETRYABLE_DB_ERRORS = (OperationalError, InterfaceError, DBAPIError)


def run_job(
    job: ScheduledJob, *, attempts: int = 3, backoff_sec: float = 2.0
) -> ConnectorRunResult:
    """Run one connector in its own session, registering its source first.

    Registration is not skippable and not cached: `register()` re-checks that the declared
    licence still agrees with the reviewed `data_sources` row on every run, so a connector
    whose rights were quietly widened in code stops here rather than at the point where the
    data has already been served.

    Retries only apply to *connection* failures. A parse error, a licence violation or an
    HTTP failure is not retried: `Connector.run()` has already caught it, rolled back and
    returned an error result, and retrying a deterministic failure just writes the same row
    three times.
    """
    last_error: Exception | None = None
    for attempt in range(1, attempts + 1):
        with step(f"Run {job.identity()}", attempt=attempt, of=attempts) as running:
            try:
                result = _run_once(job)
            except _RETRYABLE_DB_ERRORS as exc:
                last_error = exc
                running.warn(
                    "connector_db_connection_failed",
                    connector=job.connector.name,
                    attempt=attempt,
                    of=attempts,
                    error_type=type(exc).__name__,
                )
            else:
                running.result(
                    status=result.status,
                    rows_written=result.rows_written,
                    records_parsed=result.records_parsed,
                )
                if result.status != "ok":
                    # The connector caught its own failure and reported it as a result; the
                    # error text is already redacted. Close the step red so the console
                    # agrees with the `connector_runs` row.
                    running.fail("connector_reported_error", error=result.error)
                return result
        if attempt < attempts:
            time.sleep(backoff_sec * attempt)
    # Out of attempts. Report it as a failed run rather than raising, so the scheduler keeps
    # its other jobs and the failure still lands in `connector_runs` where it can be seen.
    now = utcnow()
    result = ConnectorRunResult(
        connector_name=job.identity(),
        status="error",
        rows_written=0,
        records_parsed=0,
        started_at=now,
        finished_at=now,
        error=f"database unreachable after {attempts} attempts: {type(last_error).__name__}",
    )
    try:
        with get_session() as session:
            record_run(session, result)
    except Exception:  # noqa: BLE001 - the database is what failed; do not mask the result
        _log.error("connector_run_row_unwritable", connector=job.connector.name)
    return result


def _run_once(job: ScheduledJob) -> ConnectorRunResult:
    # `politeness_delay_sec` is declared on every connector and, until now, was enforced
    # nowhere — a number in a class attribute that no code read. The Nigeria Data Portal
    # returned 403 Forbidden on a second request issued immediately after the first, which is
    # what an unenforced declaration costs. Spacing consecutive runs is the honest minimum;
    # it does not throttle *within* a fetch that issues several requests, and a connector
    # that needs that must do it itself.
    delay = getattr(job.connector, "politeness_delay_sec", 0.0) or 0.0
    if delay > 0:
        time.sleep(delay)
    with get_session() as session:
        register(session, job.connector)
        result = job.connector.run(session, run_name=job.identity(), **job.params)
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
            _scheduled_run,
            trigger=CronTrigger(hour=job.hour, minute=job.minute, timezone="UTC"),
            args=[job],
            id=job.identity(),
            # A missed run (laptop asleep) should run once on resume, not N times.
            coalesce=True,
            max_instances=1,
            misfire_grace_time=3600,
        )
    return scheduler


def _scheduled_run(job: ScheduledJob) -> ConnectorRunResult:
    """A scheduled firing is its own flow on the console: numbering starts at 1 each time.

    Worker threads are reused, and a step counter that kept climbing across days of firings
    would number the four-hundredth run "487" for no one's benefit.
    """
    reset_steps()
    return run_job(job)


@dataclass(frozen=True)
class Expectation:
    """What the schedule expects of one name: when it runs, and how often it should write."""

    scheduled_at_utc: str | None  # 'HH:MM', or None for a path a human feeds
    publishes_every_days: int


@dataclass(frozen=True)
class JobHealth:
    """One job the schedule expects (or one name seen running), judged for a screen.

    `level` is the console's vocabulary: 'ok', 'warning', 'error', and 'never_ran' for a
    job the schedule expects that has not run in the window - which fails exactly like a
    job that runs and writes nothing, except quieter.
    """

    name: str
    scheduled_at_utc: str | None  # 'HH:MM' for a scheduled job; None for a manual path
    expected: bool  # in the schedule or the manual list, as opposed to merely seen
    last_run_at: dt.datetime | None
    last_status: str | None
    runs_in_window: int
    rows_in_window: int
    level: str
    finding: str | None


def health_report(
    session: Session,
    *,
    expected: dict[str, Expectation],
    window_days: int = 30,
    now: dt.datetime | None = None,
) -> list[JobHealth]:
    """`check_health` joined with what the schedule expects, so absence is reported too.

    `expected` maps every job the health check should see to its expectation: the time it
    runs (None for a path a human feeds) and how often its source publishes. A manual path
    that has not run is a warning - a reminder, not a failure; a scheduled job that has not
    run is an error. Quiet runs inside a source's publishing span are ok: a quarterly
    series checked over a week has nothing to write, and saying "silent failure" about it
    would teach the reader to ignore the words.
    """
    seen = {h.connector_name: h for h in check_health(session, window_days=window_days, now=now)}
    report: list[JobHealth] = []
    for name in sorted(set(expected) | set(seen)):
        health = seen.get(name)
        expectation = expected.get(name)
        at = expectation.scheduled_at_utc if expectation else None
        is_expected = expectation is not None
        finding: str | None
        if health is None:
            level = "warning" if name.startswith("manual_csv_") else "never_ran"
            finding = (
                "no manual upload in the window"
                if level == "warning"
                else f"never ran in the last {window_days} days"
            )
            report.append(JobHealth(name, at, is_expected, None, None, 0, 0, level, finding))
            continue
        finding = health.finding
        if health.last_status == "error":
            level = "error"
        elif health.unhealthy and expectation and window_days < expectation.publishes_every_days:
            level = "ok"
            finding = (
                f"quiet: nothing due yet - the source publishes about every "
                f"{expectation.publishes_every_days} days and the window is {window_days}"
            )
        elif health.unhealthy:
            level = "warning"
        else:
            level = "ok"
        report.append(
            JobHealth(
                name=name,
                scheduled_at_utc=at,
                expected=is_expected,
                last_run_at=health.last_run_at,
                last_status=health.last_status,
                runs_in_window=health.runs_in_window,
                rows_in_window=health.rows_in_window,
                level=level,
                finding=finding,
            )
        )
    return report


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

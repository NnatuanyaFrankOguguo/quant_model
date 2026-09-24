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
from sqlalchemy import case, func, select
from sqlalchemy.exc import DBAPIError, InterfaceError, OperationalError
from sqlalchemy.orm import Session

from packages.common.console import reset_steps, step
from packages.common.db import get_session
from packages.common.models import ConnectorRun, DataSource
from packages.common.timez import utcnow
from packages.ingestion.base import Connector, ConnectorRunResult, record_run, register

__all__ = [
    "ConnectorHealth",
    "ScheduledJob",
    "SourceHeartbeat",
    "build_scheduler",
    "check_health",
    "check_heartbeat",
    "run_job",
]

#: The only value `Connector.run()` ever writes for a run that worked. `connector_runs.status`
#: is plain `Text` with no check constraint, so this is a convention rather than a guarantee -
#: which is why the heartbeat also carries the last *attempt*, and never infers success from
#: the mere existence of a row.
OK_STATUS = "ok"

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
    from apscheduler.executors.pool import ThreadPoolExecutor
    from apscheduler.schedulers.background import BackgroundScheduler
    from apscheduler.triggers.cron import CronTrigger

    # One worker, so jobs run one after another. `coalesce` and `max_instances` below stop
    # *one* job running twice; they do nothing about twenty-four *different* jobs whose
    # misfires all come due at once, which is what happened when the laptop woke at 03:15
    # on 2026-09-16 and every EDGAR job fetched the shared ticker file simultaneously.
    # Serial execution is also what the EDGAR connector's process-wide 10 req/s throttle
    # assumes: parallel jobs would race past it and earn a ten-minute IP block.
    scheduler = BackgroundScheduler(  # TG21: schedules are UTC, like storage
        timezone="UTC", executors={"default": ThreadPoolExecutor(1)}
    )
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


@dataclass(frozen=True)
class SourceHeartbeat:
    """One `data_sources` row, judged against the interval it declares. `docs/10` §5.3.

    `ConnectorHealth` above answers *"how did the runs that happened go?"*. This answers the
    question that has no rows to look at: *"has this source been heard from at all?"*

    The two timestamps are kept apart on purpose, because they fail differently and the
    operator's next move differs:

    * `last_success_at` - the newest `finished_at` among runs with `status='ok'`. The
      deadline is measured against this one, following §5.3's `max(cr.finished_at)`.
    * `last_attempt_at` - the newest `started_at` of any run, successful or not. Recent
      attempt with an old success means the scheduler is alive and the connector is broken;
      both old means nothing launched it at all. §5.3 is about the second case, and a report
      that could not tell it from the first would send the reader to the wrong place.
    """

    source_name: str
    #: NULL in the database means nobody is watching this source; `unmonitored` carries it.
    expected_run_interval_hours: int | None
    #: The job identities whose runs count as this source being heard from, from
    #: `packages.scheduler.jobs.expected_run_names_by_source`. Empty means nothing feeds it.
    run_names: tuple[str, ...]
    last_success_at: dt.datetime | None
    last_attempt_at: dt.datetime | None
    hours_since_success: float | None
    #: True when the deadline has passed, or was never met at all. The reason is in `finding`.
    overdue: bool
    #: True when no interval is declared. Never also `overdue`: an expectation that was never
    #: set cannot be missed. Reported separately rather than dropped, because a source nobody
    #: watches and a source that is fine look identical - the whole complaint of §5.3.
    unmonitored: bool
    finding: str | None


def _latest(seen: dict[str, dt.datetime | None], names: tuple[str, ...]) -> dt.datetime | None:
    """The newest timestamp across the jobs feeding one source, ignoring those with none."""
    stamps = [stamp for name in names if (stamp := seen.get(name)) is not None]
    return max(stamps) if stamps else None


def check_heartbeat(
    session: Session,
    *,
    run_names_by_source: dict[str, set[str]],
    now: dt.datetime | None = None,
) -> list[SourceHeartbeat]:
    """Every registered source, with the evidence that it is still being run. `docs/10` §5.3.

    Starts from `data_sources` rather than from `connector_runs`, and that inversion is the
    entire point. `check_health` can only report connectors that appear in the runs table, so
    a job the scheduler stopped launching leaves the report without a trace. Here the row
    exists whether or not anything ran, so the absence has something to be absent from.

    `run_names_by_source` is a parameter rather than an import because
    `packages.scheduler.jobs` imports this module - the same reason `health_report` takes its
    `expected` map. The mapping is not decoration: `connector_runs.connector_name` holds job
    identities (`fred:DGS10`, `edgar:AAPL`) while `data_sources.source_name` holds publishers
    (`FRED`, `SEC EDGAR`), so §5.3's `ON cr.connector_name = ds.source_name` matches nothing
    if it is run literally, and reports every source as never-run for ever.

    Judged per *source*, not per job, because that is the table §5.3's `ALTER TABLE` puts the
    column on. The cost is worth stating plainly: 23 of the 24 Yahoo jobs could stop and
    `Yahoo Finance` would still look alive on the last one. `scripts/check_connectors.py`
    covers a single job going quiet; this covers a whole source going dark, which is the
    failure that one cannot see.
    """
    now = now or utcnow()
    names = sorted({name for feeders in run_names_by_source.values() for name in feeders})

    last_success: dict[str, dt.datetime | None] = {}
    last_attempt: dict[str, dt.datetime | None] = {}
    if names:
        recorded = session.execute(
            select(
                ConnectorRun.connector_name,
                # Successful runs only. The CASE yields NULL for everything else, so a run
                # that failed cannot be mistaken for a heartbeat by `max()`.
                func.max(case((ConnectorRun.status == OK_STATUS, ConnectorRun.finished_at))),
                func.max(ConnectorRun.started_at),
            )
            .where(ConnectorRun.connector_name.in_(names))
            .group_by(ConnectorRun.connector_name)
        ).all()
        for name, success_at, attempt_at in recorded:
            last_success[name] = success_at
            last_attempt[name] = attempt_at

    registered = session.execute(
        select(DataSource.source_name, DataSource.expected_run_interval_hours).order_by(
            DataSource.source_name
        )
    ).all()

    beats: list[SourceHeartbeat] = []
    for source_name, interval in registered:
        run_names = tuple(sorted(run_names_by_source.get(source_name, ())))
        success_at = _latest(last_success, run_names)
        attempt_at = _latest(last_attempt, run_names)
        hours_since = (now - success_at).total_seconds() / 3600 if success_at else None

        overdue = False
        finding: str | None = None
        if interval is None:
            finding = (
                "no expected_run_interval_hours recorded - nothing can say whether this "
                "source stopped, so it will read as healthy for as long as it is dead"
            )
        elif not run_names:
            overdue = True
            finding = (
                f"expects a run every {interval}h and no job in the schedule writes runs for "
                f"it: either the connector was removed or the interval names a source that "
                f"nothing feeds"
            )
        elif success_at is None and attempt_at is None:
            overdue = True
            finding = (
                f"never ran: no connector_runs row exists for any of {', '.join(run_names)}, "
                f"and a job that never ran fails exactly like one that runs and returns "
                f"nothing, except quieter"
            )
        elif success_at is None:
            overdue = True
            finding = (
                f"has run and never succeeded - last launched "
                f"{attempt_at:%Y-%m-%d %H:%MZ}; the scheduler is alive, the connector is not"
            )
        elif hours_since is not None and hours_since > interval:
            overdue = True
            finding = f"last succeeded {hours_since:.1f}h ago; a run is expected every {interval}h"
            if attempt_at is not None and attempt_at > success_at:
                finding += (
                    f" - last launched {attempt_at:%Y-%m-%d %H:%MZ}, so it is running and "
                    f"failing rather than not running"
                )

        beats.append(
            SourceHeartbeat(
                source_name=source_name,
                expected_run_interval_hours=interval,
                run_names=run_names,
                last_success_at=success_at,
                last_attempt_at=attempt_at,
                hours_since_success=hours_since,
                overdue=overdue,
                unmonitored=interval is None,
                finding=finding,
            )
        )
    return beats

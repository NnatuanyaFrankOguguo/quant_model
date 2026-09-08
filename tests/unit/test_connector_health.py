"""P1.5 check 8 — silent-failure detection.

`OPERATIONS.md` §2.3: the classic scraper failure is not a crash. The page loads, the parser
runs, the selector matches nothing, and `status` is `'ok'` with zero rows. These tests pin
the line between "quiet because there was nothing new" (normal, and must not alert) and
"quiet because it is broken" (a finding).
"""

from __future__ import annotations

import datetime as dt

from sqlalchemy.orm import Session

from packages.common.models import ConnectorRun
from packages.scheduler.runner import check_health

NOW = dt.datetime(2026, 9, 4, 6, 0, tzinfo=dt.UTC)


def _run(session: Session, name: str, *, days_ago: int, status: str, rows: int) -> None:
    started = NOW - dt.timedelta(days=days_ago)
    session.add(
        ConnectorRun(
            connector_name=name,
            started_at=started,
            finished_at=started + dt.timedelta(seconds=5),
            status=status,
            rows_written=rows,
        )
    )


def _health_for(session: Session, name: str):
    return next(h for h in check_health(session, now=NOW) if h.connector_name == name)


def test_repeated_zero_row_success_is_flagged(db_session: Session) -> None:
    """The signature of a selector that stopped matching."""
    for day in (1, 5, 9):
        _run(db_session, "silent_scraper", days_ago=day, status="ok", rows=0)
    db_session.flush()

    health = _health_for(db_session, "silent_scraper")
    assert health.runs_in_window == 3
    assert health.rows_in_window == 0
    assert health.unhealthy is True
    assert "zero rows" in (health.finding or "")


def test_a_single_quiet_run_is_not_flagged(db_session: Session) -> None:
    """Re-fetching unchanged data legitimately writes nothing.

    Alerting on one quiet run would make the check cry wolf, and a check that cries wolf is
    a check people switch off.
    """
    _run(db_session, "quiet_once", days_ago=1, status="ok", rows=0)
    db_session.flush()

    health = _health_for(db_session, "quiet_once")
    assert health.unhealthy is False
    assert health.finding is None


def test_a_healthy_connector_is_not_flagged(db_session: Session) -> None:
    _run(db_session, "healthy", days_ago=2, status="ok", rows=12)
    _run(db_session, "healthy", days_ago=1, status="ok", rows=0)  # nothing new today
    db_session.flush()

    health = _health_for(db_session, "healthy")
    assert health.rows_in_window == 12
    assert health.unhealthy is False


def test_a_failed_last_run_is_flagged(db_session: Session) -> None:
    _run(db_session, "broken", days_ago=3, status="ok", rows=5)
    _run(db_session, "broken", days_ago=1, status="error", rows=0)
    db_session.flush()

    health = _health_for(db_session, "broken")
    assert health.unhealthy is True
    assert health.finding == "last run failed"
    assert health.last_status == "error"


def test_runs_outside_the_window_are_ignored(db_session: Session) -> None:
    """A connector that worked two months ago and stopped must not look healthy."""
    _run(db_session, "stopped", days_ago=90, status="ok", rows=100)
    db_session.flush()

    assert all(h.connector_name != "stopped" for h in check_health(db_session, now=NOW))


def test_a_connector_that_never_ran_has_no_row(db_session: Session) -> None:
    """Absence is invisible here by construction, which is why it is checked elsewhere.

    `check_health` can only report on runs that happened. A connector that never started
    produces no row at all — so `scripts/check_connectors.py` compares this list against the
    connectors it *expects*, and that comparison is the only thing that can see a job which
    was never scheduled.
    """
    names = {h.connector_name for h in check_health(db_session, now=NOW)}
    assert "never_scheduled" not in names


class _StubConnector:
    """Just enough connector for `run_job`'s logging. The retry logic never calls it."""

    name = "stub"


# --------------------------------------------------------------------------------------
# Retry on a dropped connection — the Neon cold-start cost, paid here (ADR-0008)
# --------------------------------------------------------------------------------------


def test_run_job_retries_a_dropped_connection(monkeypatch) -> None:
    """Neon scales to zero and kills the connection mid-statement.

    `pool_pre_ping` does not cover it: the connection was alive at checkout. Without a retry
    every unattended run that lands on a cold endpoint writes an `error` row, and the health
    check cannot tell that apart from a source that genuinely broke.
    """
    from sqlalchemy.exc import OperationalError

    from packages.scheduler import runner

    calls: list[int] = []

    def flaky(job):
        calls.append(1)
        if len(calls) == 1:
            raise OperationalError("SELECT 1", {}, Exception("terminating connection"))
        return runner.ConnectorRunResult(
            connector_name="flaky",
            status="ok",
            rows_written=7,
            records_parsed=7,
            started_at=NOW,
            finished_at=NOW,
        )

    monkeypatch.setattr(runner, "_run_once", flaky)
    job = runner.ScheduledJob(connector=_StubConnector(), params={})  # type: ignore[arg-type]
    result = runner.run_job(job, attempts=3, backoff_sec=0)

    assert len(calls) == 2, "should have retried exactly once"
    assert result.status == "ok"
    assert result.rows_written == 7


def test_run_job_does_not_retry_a_deterministic_failure(monkeypatch) -> None:
    """A parse error or a licence violation is already an error *result*, not an exception.

    Retrying it would write the same failure row three times and delay the schedule for
    nothing. Only connection failures are worth a second attempt.
    """
    from packages.scheduler import runner

    calls: list[int] = []

    def failing(job):
        calls.append(1)
        return runner.ConnectorRunResult(
            connector_name="broken_parser",
            status="error",
            rows_written=0,
            records_parsed=0,
            started_at=NOW,
            finished_at=NOW,
            error="ValueError: bad payload",
        )

    monkeypatch.setattr(runner, "_run_once", failing)
    job = runner.ScheduledJob(connector=_StubConnector(), params={})  # type: ignore[arg-type]
    result = runner.run_job(job, attempts=3, backoff_sec=0)

    assert len(calls) == 1, "a deterministic failure must not be retried"
    assert result.status == "error"

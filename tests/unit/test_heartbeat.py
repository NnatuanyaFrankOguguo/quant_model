"""`docs/10` §5.3 - the job that stopped running, and nothing noticed.

`tests/unit/test_connector_health.py` pins the line between a quiet run and a broken one.
Every one of its cases needs a `connector_runs` row to exist. This file covers the case where
there is no row at all, which §5.3 argues is both the more dangerous failure and the one the
existing query is structurally unable to see: *"A connector the scheduler stopped launching
writes no row, and the query returns empty - indistinguishable from healthy."*

So the assertions here are mostly about absence - a source past its interval, a source that
has never run, a source that runs and never succeeds - plus the one case the brief for this
work insisted be decided rather than defaulted: what a NULL `expected_run_interval_hours`
means. It means *nobody is watching this source*, it is reported by name on every run, and it
is never quietly treated as healthy. The two script-level tests at the bottom are what stop
that decision being softened into silence by a later edit.
"""

from __future__ import annotations

import contextlib
import datetime as dt

import pytest
from sqlalchemy.orm import Session

from packages.common.models import ConnectorRun, DataSource
from packages.scheduler.jobs import expected_run_names_by_source
from packages.scheduler.runner import SourceHeartbeat, check_heartbeat
from scripts.check_heartbeat import PING_URL_VAR, main

NOW = dt.datetime(2026, 9, 24, 12, 0, tzinfo=dt.UTC)

#: A daily source's grace, matching migration `0024`'s `DAILY_HOURS`.
DAILY_HOURS = 26


def _source(session: Session, name: str, *, interval_hours: int | None) -> None:
    """A `data_sources` row with the licence fields filled in and the cadence under test.

    The licence columns are `NOT NULL` by design (TG5), so a heartbeat fixture cannot avoid
    answering them - which is the register working as intended even here.
    """
    session.add(
        DataSource(
            source_name=name,
            base_url=None,
            licence_type="test_fixture",
            redistribution_allowed=False,
            attribution_required=False,
            attribution_text=None,
            terms_url=None,
            terms_reviewed_on=dt.date(2026, 9, 1),
            reviewed_by="tests",
            rate_limit_per_sec=None,
            notes="fixture for tests/unit/test_heartbeat.py",
            expected_run_interval_hours=interval_hours,
        )
    )


def _run(session: Session, name: str, *, hours_ago: float, status: str = "ok", rows: int = 1):
    started = NOW - dt.timedelta(hours=hours_ago)
    session.add(
        ConnectorRun(
            connector_name=name,
            started_at=started,
            finished_at=started + dt.timedelta(seconds=5),
            status=status,
            rows_written=rows,
        )
    )


def _beat_for(session: Session, source_name: str, *, job: str) -> SourceHeartbeat:
    beats = check_heartbeat(session, run_names_by_source={source_name: {job}}, now=NOW)
    return next(beat for beat in beats if beat.source_name == source_name)


def test_a_source_past_its_interval_is_overdue(db_session: Session) -> None:
    """30 hours of silence from a daily source. This is the whole point of §5.3."""
    _source(db_session, "hb_stopped", interval_hours=DAILY_HOURS)
    _run(db_session, "hb:stopped", hours_ago=30)
    db_session.flush()

    beat = _beat_for(db_session, "hb_stopped", job="hb:stopped")
    assert beat.overdue is True
    assert beat.unmonitored is False
    assert beat.hours_since_success is not None
    assert round(beat.hours_since_success) == 30
    assert "expected every 26h" in (beat.finding or "")


def test_a_source_inside_its_interval_is_not_overdue(db_session: Session) -> None:
    """A run this morning. A check that cried wolf here would be switched off by Friday."""
    _source(db_session, "hb_fine", interval_hours=DAILY_HOURS)
    _run(db_session, "hb:fine", hours_ago=6)
    db_session.flush()

    beat = _beat_for(db_session, "hb_fine", job="hb:fine")
    assert beat.overdue is False
    assert beat.finding is None
    assert beat.last_success_at is not None


def test_a_zero_row_run_still_counts_as_a_heartbeat(db_session: Session) -> None:
    """Writing nothing is not the same as not running, and only one of them belongs here.

    `check_health` already owns the zero-row question. If this check also failed on it, the
    two would report the same incident twice under different words, and the reader would
    learn to skim both.
    """
    _source(db_session, "hb_quiet", interval_hours=DAILY_HOURS)
    _run(db_session, "hb:quiet", hours_ago=3, rows=0)
    db_session.flush()

    assert _beat_for(db_session, "hb_quiet", job="hb:quiet").overdue is False


def test_a_source_that_never_ran_is_overdue(db_session: Session) -> None:
    """§5.3's `HAVING max(cr.finished_at) IS NULL` branch - no row to be suspicious of."""
    _source(db_session, "hb_never", interval_hours=DAILY_HOURS)
    db_session.flush()

    beat = _beat_for(db_session, "hb_never", job="hb:never")
    assert beat.overdue is True
    assert beat.last_success_at is None
    assert beat.last_attempt_at is None
    assert "never ran" in (beat.finding or "")


def test_a_source_that_runs_and_never_succeeds_is_overdue(db_session: Session) -> None:
    """A live scheduler and a dead connector, told apart from a dead scheduler.

    Both are overdue, and the operator's next move is not the same: one is a broken parser,
    the other a scheduled task somebody disabled. The finding has to say which.
    """
    _source(db_session, "hb_failing", interval_hours=DAILY_HOURS)
    _run(db_session, "hb:failing", hours_ago=2, status="error", rows=0)
    db_session.flush()

    beat = _beat_for(db_session, "hb_failing", job="hb:failing")
    assert beat.overdue is True
    assert beat.last_success_at is None
    assert beat.last_attempt_at is not None  # it was launched
    assert "never succeeded" in (beat.finding or "")


def test_a_stale_success_with_a_recent_attempt_says_so(db_session: Session) -> None:
    """Succeeded three days ago, tried an hour ago: running and failing, not un-launched."""
    _source(db_session, "hb_degraded", interval_hours=DAILY_HOURS)
    _run(db_session, "hb:degraded", hours_ago=72)
    _run(db_session, "hb:degraded", hours_ago=1, status="error", rows=0)
    db_session.flush()

    beat = _beat_for(db_session, "hb_degraded", job="hb:degraded")
    assert beat.overdue is True
    assert "running and failing rather than not running" in (beat.finding or "")


def test_a_null_interval_is_unmonitored_rather_than_healthy(db_session: Session) -> None:
    """The decision, pinned: NULL means nobody is watching, and it never reads as fine.

    The source below last succeeded five hundred hours ago - unambiguously dead by any
    cadence anyone would have chosen. It is still not `overdue`, because an expectation that
    was never set cannot be missed and inventing one here would be the check making up the
    number it exists to read. What it must not do is disappear, so it comes back flagged
    `unmonitored` with a finding that names the missing column.
    """
    _source(db_session, "hb_no_cadence", interval_hours=None)
    _run(db_session, "hb:no_cadence", hours_ago=500)
    db_session.flush()

    beat = _beat_for(db_session, "hb_no_cadence", job="hb:no_cadence")
    assert beat.unmonitored is True
    assert beat.overdue is False
    assert beat.expected_run_interval_hours is None
    assert "expected_run_interval_hours" in (beat.finding or "")


def test_an_interval_on_a_source_nothing_feeds_is_overdue(db_session: Session) -> None:
    """An expectation that no job can ever satisfy is a configuration bug, not a quiet pass."""
    _source(db_session, "hb_orphan", interval_hours=DAILY_HOURS)
    db_session.flush()

    beats = check_heartbeat(db_session, run_names_by_source={}, now=NOW)
    beat = next(b for b in beats if b.source_name == "hb_orphan")
    assert beat.overdue is True
    assert beat.run_names == ()
    assert "nothing feeds" in (beat.finding or "")


def test_the_register_declares_a_cadence_for_every_scheduled_source(db_session: Session) -> None:
    """Migration `0024` populated every source the schedule actually feeds.

    Derived from `build_jobs()`, so a connector added later against a source with no cadence
    fails here rather than being discovered as a six-month gap in the data.
    """
    intervals = dict(
        db_session.query(DataSource.source_name, DataSource.expected_run_interval_hours).all()
    )
    for source_name in sorted(expected_run_names_by_source()):
        assert source_name in intervals, f"{source_name!r} has no data_sources row"
        assert intervals[source_name], f"{source_name!r} has no expected_run_interval_hours"


# --------------------------------------------------------------------------------------
# The script's exit code. The rules above are only as good as what the scheduled task does
# with them, and the NULL decision lives entirely here.
# --------------------------------------------------------------------------------------


def _beat(name: str, *, overdue: bool = False, unmonitored: bool = False) -> SourceHeartbeat:
    return SourceHeartbeat(
        source_name=name,
        expected_run_interval_hours=None if unmonitored else DAILY_HOURS,
        run_names=(f"{name}:job",),
        last_success_at=None if overdue else NOW,
        last_attempt_at=None,
        hours_since_success=None if overdue else 0.0,
        overdue=overdue,
        unmonitored=unmonitored,
        finding="never ran" if overdue else None,
    )


@pytest.fixture
def scripted(monkeypatch: pytest.MonkeyPatch):
    """Run `main()` against a canned report, with no database and no outbound ping."""
    monkeypatch.delenv(PING_URL_VAR, raising=False)
    monkeypatch.setattr("scripts.check_heartbeat.expected_run_names_by_source", dict)
    monkeypatch.setattr(
        "scripts.check_heartbeat.get_session",
        lambda: contextlib.nullcontext(None),
    )

    def run(beats: list[SourceHeartbeat], argv: list[str] | None = None) -> int:
        monkeypatch.setattr("scripts.check_heartbeat.check_heartbeat", lambda *a, **k: beats)
        return main(argv)

    return run


def test_the_script_fails_when_a_source_is_overdue(scripted, capsys) -> None:
    assert scripted([_beat("late", overdue=True)]) == 1
    assert "late" in capsys.readouterr().out


def test_the_script_passes_but_names_an_unmonitored_source(scripted, capsys) -> None:
    """Exit 0, because a permanently red check is a check nobody reads - but never silent.

    NGX and the operator-upload source are legitimately NULL, so failing on them by default
    would leave this task red for ever and train the reader to ignore it. The name still has
    to appear in the output on every single run; that is what "not silently" means.
    """
    assert scripted([_beat("unwatched", unmonitored=True)]) == 0
    assert "unwatched" in capsys.readouterr().out


def test_strict_turns_an_unmonitored_source_into_a_failure(scripted) -> None:
    """For CI and the quarterly review, where "is anything unwatched?" is the question."""
    assert scripted([_beat("unwatched", unmonitored=True)], ["--strict"]) == 1


def test_strict_is_quiet_when_every_source_declares_an_interval(scripted) -> None:
    assert scripted([_beat("watched")], ["--strict"]) == 0


def test_a_mistyped_flag_is_refused_rather_than_read_as_its_absence(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """`--stict` must not quietly mean "not strict".

    The flag changes what this script does about unmonitored sources and therefore what it
    exits with. Tested with a membership check, a typo runs the *weaker* check and reports
    that it passed, and the caller believes they asked for the stronger one - which on a
    script whose entire subject is a check that fails without saying so is the one mistake
    worth refusing outright.

    Exit 2, not 1: 1 means "the check ran and something needs a human", and a caller that
    cannot tell those apart will treat a usage error as an outage or an outage as a typo.
    """
    assert main(["--stict"]) == 2
    printed = capsys.readouterr().err
    assert "unrecognised argument(s) --stict" in printed
    assert "usage:" in printed

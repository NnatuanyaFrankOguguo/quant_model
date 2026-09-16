"""P1.4's engine: staleness and the point-in-time view.

Two behaviours here are the ones that would be wrong in a way nobody notices: a staleness
flag that reads "fresh" for a series it cannot judge, and a vintage query that quietly
returns today's knowledge for a decision made months ago.
"""

from __future__ import annotations

import datetime as dt
from decimal import Decimal

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from packages.common.models import MacroObservation, MacroSeries, SourceDocument
from packages.ingestion import macro


@pytest.fixture
def document_id(db_session: Session) -> int:
    """A source document to hang observations off — the column is NOT NULL by design."""
    document = SourceDocument(
        data_source_id=db_session.execute(
            select(MacroSeries.data_source_id).where(MacroSeries.code == "NG_CPI_YOY")
        ).scalar_one(),
        url="file:///fixture.csv",
        storage_key="documents/sha256/" + "f" * 64,
        sha256="f" * 64,
        media_type="text/csv",
        retrieved_at=dt.datetime(2026, 8, 15, tzinfo=dt.UTC),
    )
    db_session.add(document)
    db_session.flush()
    return document.id


def _add(session: Session, code: str, as_of: str, known: str, value: str | None, doc: int) -> None:
    session.add(
        MacroObservation(
            series_id=session.execute(
                select(MacroSeries.id).where(MacroSeries.code == code)
            ).scalar_one(),
            as_of_date=dt.date.fromisoformat(as_of),
            known_as_of=dt.date.fromisoformat(known),
            value=None if value is None else Decimal(value),
            source_document_id=doc,
        )
    )


def test_series_with_no_data_is_not_reported_fresh(db_session: Session) -> None:
    """`is_stale=None` means "cannot judge". A False here would read as reassurance."""
    summaries = {s.code: s for s in macro.list_series(db_session)}
    empty = summaries["NG_PUBLIC_DEBT_TOTAL"]
    assert empty.observation_count == 0
    assert empty.latest_as_of is None
    assert empty.is_stale is None


def test_overdue_series_is_flagged(db_session: Session, document_id: int) -> None:
    _add(db_session, "NG_CPI_YOY", "2026-01-31", "2026-02-15", "29.9", document_id)
    db_session.flush()
    # expected_lag_days is 25; evaluating six months later must flag it.
    summary = macro.series_summary(db_session, "NG_CPI_YOY", on=dt.date(2026, 8, 1))
    assert summary is not None
    assert summary.is_stale is True
    assert summary.days_since_as_of == 182


def test_recent_series_is_not_flagged(db_session: Session, document_id: int) -> None:
    _add(db_session, "NG_CPI_YOY", "2026-07-31", "2026-08-15", "34.2", document_id)
    db_session.flush()
    summary = macro.series_summary(db_session, "NG_CPI_YOY", on=dt.date(2026, 8, 16))
    assert summary is not None
    assert summary.is_stale is False
    assert summary.latest_value == Decimal("34.2")
    # The two dates differ, and both reach the caller.
    assert summary.latest_as_of == dt.date(2026, 7, 31)
    assert summary.latest_known_as_of == dt.date(2026, 8, 15)


def test_irregular_series_is_never_flagged_stale(db_session: Session, document_id: int) -> None:
    """The MPR changes when the MPC changes it. An unchanged rate is the normal state.

    Flagging it would train the reader to ignore the flag on the series that matter.
    """
    _add(db_session, "NG_MPR", "2026-01-22", "2026-01-22", "27.50", document_id)
    db_session.flush()
    summary = macro.series_summary(db_session, "NG_MPR", on=dt.date(2027, 1, 1))
    assert summary is not None
    assert summary.is_stale is None
    assert summary.days_since_as_of == 344


@pytest.mark.invariant
def test_as_known_on_hides_later_vintages(db_session: Session, document_id: int) -> None:
    """The point-in-time view. SPEC 4.1: features respect `known_as_of`.

    Q2 GDP was first published as 3.1 in August and revised to 3.4 in November. A decision
    made in September must see 3.1. Returning 3.4 is the lookahead that makes a backtest
    profitable and wrong — and it is invisible, because 3.4 is the *correct* number today.
    """
    _add(db_session, "NG_GDP_GROWTH_YOY", "2026-06-30", "2026-08-25", "3.1", document_id)
    _add(db_session, "NG_GDP_GROWTH_YOY", "2026-06-30", "2026-11-20", "3.4", document_id)
    db_session.flush()

    september = macro.observations(
        db_session, "NG_GDP_GROWTH_YOY", as_known_on=dt.date(2026, 9, 15)
    )
    assert [p.value for p in september] == [Decimal("3.1")]
    assert september[0].known_as_of == dt.date(2026, 8, 25)

    today = macro.observations(db_session, "NG_GDP_GROWTH_YOY")
    assert [p.value for p in today] == [Decimal("3.4")]


def test_as_known_on_before_first_publication_returns_nothing(
    db_session: Session, document_id: int
) -> None:
    """Before it was published, the figure did not exist. Not zero, not the later value."""
    _add(db_session, "NG_GDP_GROWTH_YOY", "2026-06-30", "2026-08-25", "3.1", document_id)
    db_session.flush()
    assert (
        macro.observations(db_session, "NG_GDP_GROWTH_YOY", as_known_on=dt.date(2026, 7, 1)) == []
    )


def test_observation_window_filters_by_period(db_session: Session, document_id: int) -> None:
    for month, value in ((1, "29.9"), (2, "31.7"), (3, "33.2")):
        _add(db_session, "NG_CPI_YOY", f"2026-0{month}-28", "2026-04-15", value, document_id)
    db_session.flush()
    points = macro.observations(
        db_session, "NG_CPI_YOY", start=dt.date(2026, 2, 1), end=dt.date(2026, 2, 28)
    )
    assert [p.value for p in points] == [Decimal("31.7")]


def test_unknown_series_returns_no_observations(db_session: Session) -> None:
    assert macro.observations(db_session, "NOT_A_SERIES") == []
    assert macro.series_summary(db_session, "NOT_A_SERIES") is None


def test_null_values_survive_as_null(db_session: Session, document_id: int) -> None:
    """An absent observation must not become zero on the way out of the database."""
    _add(db_session, "NG_CPI_CORE", "2026-07-31", "2026-08-15", None, document_id)
    db_session.flush()
    points = macro.observations(db_session, "NG_CPI_CORE")
    assert [p.value for p in points] == [None]


def test_every_series_carries_its_source_and_attribution(db_session: Session) -> None:
    """Attribution is required by the licensing register, so it travels with the data."""
    for summary in macro.list_series(db_session):
        assert summary.source_name
        assert summary.attribution, f"{summary.code} has no attribution text"


# --------------------------------------------------------------------------------------
# Limits — a partial answer must never look like a whole one
# --------------------------------------------------------------------------------------


def test_limit_returns_the_most_recent_periods(db_session: Session, document_id: int) -> None:
    """Asking for "some" of a price series and getting 1962 onwards is useless to everyone."""
    for day in range(1, 11):
        _add(db_session, "NG_CPI_YOY", f"2026-01-{day:02d}", "2026-03-01", str(day), document_id)
    db_session.flush()

    page = macro.observation_page(db_session, "NG_CPI_YOY", limit=3)
    assert page.total_available == 10
    assert page.truncated is True
    assert [p.as_of_date.day for p in page.points] == [8, 9, 10], "newest three, oldest first"


def test_points_are_always_chronological(db_session: Session, document_id: int) -> None:
    """The limit is applied newest-first internally; the caller must not see that order.

    A chart that plots points in arrival order draws time backwards, and nothing in the
    response would say so.
    """
    for day in range(1, 6):
        _add(db_session, "NG_CPI_YOY", f"2026-01-{day:02d}", "2026-03-01", str(day), document_id)
    db_session.flush()

    page = macro.observation_page(db_session, "NG_CPI_YOY", limit=3)
    dates = [p.as_of_date for p in page.points]
    assert dates == sorted(dates)


def test_not_truncated_when_the_limit_exceeds_the_data(
    db_session: Session, document_id: int
) -> None:
    _add(db_session, "NG_CPI_YOY", "2026-01-31", "2026-03-01", "29.9", document_id)
    db_session.flush()

    page = macro.observation_page(db_session, "NG_CPI_YOY", limit=500)
    assert page.total_available == 1
    assert page.truncated is False


def test_total_available_counts_the_window_not_the_series(
    db_session: Session, document_id: int
) -> None:
    """`total_available` must describe the query that was asked, or it misleads about scope."""
    for month in range(1, 5):
        _add(db_session, "NG_CPI_YOY", f"2026-0{month}-28", "2026-06-01", "30.0", document_id)
    db_session.flush()

    page = macro.observation_page(
        db_session, "NG_CPI_YOY", start=dt.date(2026, 2, 1), end=dt.date(2026, 3, 31), limit=1
    )
    assert page.total_available == 2, "two periods fall in the window, not four"
    assert page.truncated is True


def test_unknown_series_gives_an_empty_page(db_session: Session) -> None:
    page = macro.observation_page(db_session, "NOT_A_SERIES")
    assert page.points == []
    assert page.total_available == 0
    assert page.truncated is False


# --- the staleness threshold has to cover a whole period (migration 0016) -----------------

#: The longest a period of each frequency lasts, in days. A threshold below this flags every
#: healthy series for the second half of every cycle, because `_staleness` measures the age
#: of the newest *period held*, not the age of the last publication.
PERIOD_DAYS: dict[str, int] = {"daily": 1, "monthly": 31, "quarterly": 92, "annual": 365}


@pytest.mark.invariant
def test_every_threshold_leaves_room_for_a_period_and_its_publication_lag(
    db_session: Session,
) -> None:
    """Migration 0005 seeded these as [NEEDS VERIFICATION]; 0016 verified them.

    A monthly series set to 20 days cries wolf from day 21 of every month, and a dashboard
    that cries wolf is one a reader learns to ignore - which is the failure mode the flag
    exists to prevent.
    """
    rows = db_session.execute(
        select(MacroSeries.code, MacroSeries.frequency, MacroSeries.expected_lag_days)
    ).all()
    assert rows, "the seed migrations put series here"
    for code, frequency, lag in rows:
        if frequency == "irregular":
            continue  # never judged stale by the rule; there is no cadence to judge against
        period = PERIOD_DAYS[frequency]
        assert lag > period, (
            f"{code} is {frequency} with a {lag}-day threshold: a period alone is {period} "
            f"days, so this flags a healthy series before the next release is even due"
        )


def test_a_monthly_series_awaiting_its_next_release_is_not_stale(
    db_session: Session, document_id: int
) -> None:
    """The false alarm the operator found on 2026-09-15, as a test.

    US CPI for August is dated 2026-08-01 and published mid-September; September's figure is
    not due until mid-October. On 2026-09-16 the August figure is 46 days old and perfectly
    fresh - and on 2026-11-01 it is 92 days old, and genuinely overdue.
    """
    _add(db_session, "US_CPI_INDEX", "2026-08-01", "2026-09-11", "329.4", document_id)
    db_session.flush()

    healthy = macro.series_summary(db_session, "US_CPI_INDEX", on=dt.date(2026, 9, 16))
    assert healthy is not None
    assert healthy.days_since_as_of == 46
    assert healthy.is_stale is False, "the next release is not due yet"

    overdue = macro.series_summary(db_session, "US_CPI_INDEX", on=dt.date(2026, 11, 1))
    assert overdue is not None and overdue.is_stale is True, "two releases missed: say so"

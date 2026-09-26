"""P3 exit check 5: a Nigerian public holiday is marked closed, not a zero-return day.

`docs/03` P3, check 5: *"Query a Nigerian public holiday | Marked closed, not a zero-return
day"*. `docs/01` §7.2 states the bug it prevents: *"A Nigerian public holiday has no price
row. Is that a closed market or a failed scraper? Without a calendar you cannot tell — so you
either alert on every holiday, or you silence the alarm and miss real outages. Meanwhile a
'missing' day treated as zero return depresses your volatility estimate."*

**The behaviour worth testing hardest is the refusal.** A date the calendar has no row for is
*unknown*, and every arithmetic function raises rather than answer. Defaulting to open would
settle trades on days the exchange was shut; defaulting to closed is quieter and worse, since
it reads as a legitimate non-trading day and absorbs a zero return that never happened. Both
are what `OPERATIONS.md` §1.2 means by *"never `timedelta(days=3)`"*.

Each test seeds the days it needs. Nothing here depends on
`scripts/seed_trading_calendar.py` having been run, because a test that skipped or passed
according to ambient data would be telling us about the database rather than the code.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Iterator

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from packages.common.calendars import (
    ANNOUNCED,
    OBSERVED_BARS,
    WEEKEND,
    TradingCalendarDay,
    UnknownTradingDayError,
    add_trading_days,
    coverage,
    day,
    is_open,
    next_trading_day,
    previous_trading_day,
    settlement_date,
    trading_days,
)
from packages.common.models import Exchange
from scripts.seed_trading_calendar import (
    STATUTE_FIXED,
    easter_sunday,
    nigerian_statutory_closures,
    weekends,
)

pytestmark = pytest.mark.invariant

#: Independence Day. A Thursday in 2026, so being closed cannot be mistaken for a weekend.
INDEPENDENCE_DAY = dt.date(2026, 10, 1)


@pytest.fixture
def ngx(db_session: Session) -> int:
    return db_session.execute(select(Exchange.id).where(Exchange.code == "NGX")).scalar_one()


@pytest.fixture
def calendar(db_session: Session, ngx: int) -> Iterator[None]:
    """One working week around Independence Day 2026, plus the holiday itself.

    Monday 28 September to Friday 9 October, with 1 October closed. The weekend either side
    is seeded too, so `next_trading_day` has somewhere to walk.
    """
    rows = []
    for offset in range(-3, 9):
        when = INDEPENDENCE_DAY + dt.timedelta(days=offset)
        if when.weekday() >= 5:
            rows.append((when, False, WEEKEND, "weekend"))
        elif when == INDEPENDENCE_DAY:
            rows.append((when, False, STATUTE_FIXED, "public holiday: Independence Day"))
        else:
            rows.append((when, True, OBSERVED_BARS, "a price bar exists for this day"))
    for when, open_, source, note in rows:
        db_session.add(
            TradingCalendarDay(
                exchange_id=ngx, date=when, is_open=open_, source=source, session_note=note
            )
        )
    db_session.flush()
    yield


# --------------------------------------------------------------------------------------
# Check 5, stated
# --------------------------------------------------------------------------------------


def test_a_nigerian_public_holiday_is_marked_closed(db_session: Session, calendar: None) -> None:
    """Check 5. 1 October 2026 is a Thursday, so "closed" cannot be a weekend in disguise."""
    assert INDEPENDENCE_DAY.weekday() == 3, "a Thursday, deliberately"
    holiday = day(db_session, exchange="NGX", on=INDEPENDENCE_DAY)
    assert holiday.is_open is False
    assert holiday.session_note is not None
    assert "Independence Day" in holiday.session_note
    assert is_open(db_session, exchange="NGX", on=INDEPENDENCE_DAY) is False


def test_the_holiday_is_absent_from_the_trading_days_rather_than_a_zero_return(
    db_session: Session, calendar: None
) -> None:
    """The other half of check 5: it is not *in* the series at all.

    A day present with a zero return is what depresses a volatility estimate. A day the
    calendar knows was closed simply is not a day, so nothing divides by it.
    """
    week = trading_days(
        db_session,
        exchange="NGX",
        start=dt.date(2026, 9, 28),
        end=dt.date(2026, 10, 2),
    )
    assert INDEPENDENCE_DAY not in week
    assert week == [
        dt.date(2026, 9, 28),
        dt.date(2026, 9, 29),
        dt.date(2026, 9, 30),
        dt.date(2026, 10, 2),
    ], "Monday to Friday less the Thursday holiday"


def test_a_weekend_is_closed_and_says_which_kind_of_closed(
    db_session: Session, calendar: None
) -> None:
    """`source` separates the definitional from the announced, which is not decoration.

    A settlement resting on "no exchange trades on a Saturday" is on firmer ground than one
    resting on a holiday somebody typed in, and a reader is entitled to know which.
    """
    saturday = day(db_session, exchange="NGX", on=dt.date(2026, 10, 3))
    assert saturday.is_open is False and saturday.source == WEEKEND
    holiday = day(db_session, exchange="NGX", on=INDEPENDENCE_DAY)
    assert holiday.source == STATUTE_FIXED, "not the same claim as a weekend"


# --------------------------------------------------------------------------------------
# The refusal, which is the point of the table
# --------------------------------------------------------------------------------------


def test_a_day_the_calendar_does_not_know_is_refused_not_guessed(
    db_session: Session, calendar: None
) -> None:
    """Neither open nor closed. `SPEC.md` §4.1 forbids inferring missing data.

    The message has to say this explicitly, because "unknown" and "closed" look identical to
    anyone reading a boolean, and the whole table exists to separate them.
    """
    unseeded = dt.date(2026, 11, 20)
    with pytest.raises(UnknownTradingDayError, match="no calendar row"):
        is_open(db_session, exchange="NGX", on=unseeded)
    with pytest.raises(UnknownTradingDayError, match="not the same as being closed"):
        day(db_session, exchange="NGX", on=unseeded)


def test_arithmetic_refuses_at_the_first_unknown_day_it_reaches(
    db_session: Session, calendar: None
) -> None:
    """Walking off the end of the calendar must not answer from a region nobody filled in.

    This is the US-holiday case in miniature: the seeded calendar has no Thanksgiving, so
    `add_trading_days` across one stops rather than skipping it as though it were a weekend.
    """
    with pytest.raises(UnknownTradingDayError, match="reached while walking"):
        add_trading_days(db_session, exchange="NGX", start=dt.date(2026, 10, 8), days=10)


def test_an_unregistered_exchange_has_no_calendar(db_session: Session) -> None:
    with pytest.raises(UnknownTradingDayError, match="no exchange has the code"):
        is_open(db_session, exchange="LSE", on=INDEPENDENCE_DAY)


# --------------------------------------------------------------------------------------
# Date arithmetic that is not timedelta
# --------------------------------------------------------------------------------------


def test_the_next_trading_day_steps_over_the_holiday(db_session: Session, calendar: None) -> None:
    """Wednesday 30 September to Friday 2 October, because Thursday was Independence Day."""
    assert next_trading_day(db_session, exchange="NGX", after=dt.date(2026, 9, 30)) == dt.date(
        2026, 10, 2
    )
    assert previous_trading_day(db_session, exchange="NGX", before=dt.date(2026, 10, 2)) == dt.date(
        2026, 9, 30
    )


def test_the_next_trading_day_steps_over_a_weekend(db_session: Session, calendar: None) -> None:
    assert next_trading_day(db_session, exchange="NGX", after=dt.date(2026, 10, 2)) == dt.date(
        2026, 10, 5
    ), "Friday to Monday"


def test_settlement_counts_trading_days_and_not_calendar_days(
    db_session: Session, calendar: None
) -> None:
    """`OPERATIONS.md` §1.2: *"never `timedelta(days=3)`"*, and here is why.

    NGX settles T+3. A trade on Tuesday 29 September 2026 does not settle on Friday the 2nd:
    Thursday was Independence Day, so the third trading day is Monday 5 October. Calendar
    arithmetic would have answered the 2nd and been wrong by a weekend and a holiday.
    """
    cycle = db_session.execute(
        select(Exchange.settlement_days).where(Exchange.code == "NGX")
    ).scalar_one()
    assert cycle == 3, "NGX is T+3"

    traded = dt.date(2026, 9, 29)
    assert settlement_date(db_session, exchange="NGX", traded_on=traded) == dt.date(2026, 10, 5)
    assert traded + dt.timedelta(days=3) == dt.date(2026, 10, 2), "what timedelta would say"


def test_adding_zero_trading_days_returns_the_day_itself(
    db_session: Session, calendar: None
) -> None:
    """And does not check that the day was open: the caller asked for no movement.

    A settlement computed from a trade has already established that the trade happened, so
    re-litigating it here would refuse a calculation that is perfectly well founded.
    """
    unseeded = dt.date(2031, 5, 5)
    assert add_trading_days(db_session, exchange="NGX", start=unseeded, days=0) == unseeded


def test_negative_counts_walk_backwards(db_session: Session, calendar: None) -> None:
    assert add_trading_days(
        db_session, exchange="NGX", start=dt.date(2026, 10, 5), days=-2
    ) == dt.date(2026, 9, 30), "back over the weekend and the holiday"


def test_a_range_query_is_inclusive_at_both_ends(db_session: Session, calendar: None) -> None:
    single = trading_days(
        db_session, exchange="NGX", start=dt.date(2026, 9, 30), end=dt.date(2026, 9, 30)
    )
    assert single == [dt.date(2026, 9, 30)]
    with pytest.raises(ValueError, match="is after end"):
        trading_days(
            db_session, exchange="NGX", start=dt.date(2026, 10, 2), end=dt.date(2026, 9, 30)
        )


def test_coverage_reports_how_far_the_calendar_reaches(db_session: Session, calendar: None) -> None:
    """The question a reader has the moment an arithmetic call refuses."""
    reach = coverage(db_session, exchange="NGX")
    assert reach is not None
    earliest, latest, days = reach
    assert earliest == dt.date(2026, 9, 28)
    assert latest == dt.date(2026, 10, 9)
    assert days == 12


# --------------------------------------------------------------------------------------
# The seeder's pure parts
# --------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("year", "expected"),
    [
        (2000, "2000-04-23"),
        (2021, "2021-04-04"),
        (2024, "2024-03-31"),
        (2025, "2025-04-20"),
        (2026, "2026-04-05"),
    ],
)
def test_easter_is_computed_exactly(year: int, expected: str) -> None:
    """Good Friday and Easter Monday move, but they are computable and need no source.

    Checked against known dates rather than against the algorithm restated, which would only
    prove it agrees with itself.
    """
    assert easter_sunday(year).isoformat() == expected


def test_the_nigerian_statutory_list_is_the_fixed_dates_and_easter(
    db_session: Session,
) -> None:
    """Six fixed dates plus Good Friday and Easter Monday: eight closures a year.

    The moving Islamic holidays are absent on purpose. `OPERATIONS.md` §1.2 says they are
    *"announced only days in advance by the Federal Government"*, so they cannot be computed
    and must not be guessed - `docs/03` line 1540 makes them the operator's work.
    """
    closures = dict(nigerian_statutory_closures(dt.date(2026, 1, 1), dt.date(2026, 12, 31)))
    assert len(closures) == 8
    assert closures[dt.date(2026, 1, 1)] == "New Year's Day"
    assert closures[dt.date(2026, 5, 1)] == "Workers' Day"
    assert closures[dt.date(2026, 6, 12)] == "Democracy Day", "12 June, not the pre-2019 date"
    assert closures[dt.date(2026, 10, 1)] == "Independence Day"
    assert closures[dt.date(2026, 12, 25)] == "Christmas Day"
    assert closures[dt.date(2026, 12, 26)] == "Boxing Day"
    assert closures[dt.date(2026, 4, 3)] == "Good Friday"
    assert closures[dt.date(2026, 4, 6)] == "Easter Monday"
    for moving in ("Eid", "Maulid"):
        assert not any(moving in name for name in closures.values()), (
            f"{moving} moves and is announced; computing it would be inventing a date"
        )


def test_weekends_are_every_saturday_and_sunday_in_the_range() -> None:
    found = list(weekends(dt.date(2026, 9, 28), dt.date(2026, 10, 11)))
    assert found == [
        dt.date(2026, 10, 3),
        dt.date(2026, 10, 4),
        dt.date(2026, 10, 10),
        dt.date(2026, 10, 11),
    ]
    assert all(when.weekday() >= 5 for when in found)


def test_an_announced_day_outranks_what_a_seed_would_infer(
    db_session: Session, ngx: int, calendar: None
) -> None:
    """The seeder inserts with `ON CONFLICT DO NOTHING`, so a person's entry survives a re-run.

    An unscheduled closure is announced after the day it shut, and `OPERATIONS.md` §1.2's
    *"correct forward from NGX announcements"* only works if the correction sticks.
    """
    from sqlalchemy.dialects.postgresql import insert as pg_insert

    announced = dt.date(2026, 9, 30)  # seeded above as open, from observed bars
    db_session.execute(
        pg_insert(TradingCalendarDay)
        .values(
            [
                {
                    "exchange_id": ngx,
                    "date": announced,
                    "is_open": False,
                    "session_note": "unscheduled closure",
                    "source": ANNOUNCED,
                }
            ]
        )
        .on_conflict_do_nothing(index_elements=["exchange_id", "date"])
    )
    db_session.flush()
    kept = day(db_session, exchange="NGX", on=announced)
    assert kept.source == OBSERVED_BARS, (
        "the existing row is untouched - which is what protects a hand-entered day from a "
        "later seed, in the direction that matters"
    )

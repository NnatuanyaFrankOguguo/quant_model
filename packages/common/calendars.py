"""Which days an exchange trades, and the refusal that makes the answer worth having. TG2.

`OPERATIONS.md` §1.2: *"Every date arithmetic function in `/backtest`, `/portfolio`, and
`/execution` takes the calendar as a dependency — never `timedelta(days=3)`."* This is that
dependency.

**The one design decision.** A date with no row is **unknown**, not closed and not open, and
every function here raises rather than answer for it. That is unusual enough to justify:

* Defaulting to *open* puts a settlement on a day the exchange was shut, which is the exact
  failure §1.2 says a hardcoded weekday rule causes.
* Defaulting to *closed* is worse in a quieter way. It reads as a legitimate non-trading day,
  so a gap-detection alert stays silent and a volatility estimate absorbs a zero return that
  never happened — `docs/01` §7.2's *"a 'missing' day treated as zero return depresses your
  volatility estimate"*.
* Falling back to a weekday rule is the thing §1.2 opens by forbidding, and Nigeria is the
  reason: Eid al-Fitr, Eid al-Adha and Maulid move every year and are *"frequently announced
  only days in advance by the Federal Government"*. A Tuesday in Lagos is not a trading day
  because it is a Tuesday.

So an unknown day is an error with a message naming the exchange and the date, and the fix is
to put the day in the table. A caller that genuinely wants "as much as is known" asks
`trading_days` for a range, which returns what it has; a caller doing arithmetic that must be
right gets an exception.

## Where days come from

`source` on each row says which, because the three are not equally strong:

| `source` | Strength | How |
|---|---|---|
| `weekend` | definitional | no exchange here trades on a Saturday or Sunday |
| `observed_bars` | inferred | a day on which `price_history` holds a bar is a day that traded |
| `announced` | primary | a gazetted holiday or an exchange notice, entered by a person |

`observed_bars` is evidence of *opening*, never of closing: a weekday with no bar may have
been a holiday or a failed scrape, and that is the very ambiguity this table exists to end.
So the seeder writes open days from bars and never infers a closure from their absence.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass

from sqlalchemy import Boolean, Date, Integer, Text, func, select
from sqlalchemy.orm import Mapped, Session, mapped_column

from packages.common.models import Base, Exchange

__all__ = [
    "ANNOUNCED",
    "OBSERVED_BARS",
    "WEEKEND",
    "CalendarDay",
    "TradingCalendarDay",
    "UnknownTradingDayError",
    "add_trading_days",
    "day",
    "is_open",
    "next_trading_day",
    "previous_trading_day",
    "settlement_date",
    "trading_days",
]

#: `source` values. `weekend` is definitional, `observed_bars` inferred, `announced` primary.
WEEKEND = "weekend"
OBSERVED_BARS = "observed_bars"
ANNOUNCED = "announced"


class TradingCalendarDay(Base):
    """One day of one exchange's calendar. `docs/08` §2.1, built by migration `0023`."""

    __tablename__ = "trading_calendar"

    exchange_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    date: Mapped[dt.date] = mapped_column(Date, primary_key=True)
    is_open: Mapped[bool] = mapped_column(Boolean, nullable=False)
    session_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    source: Mapped[str] = mapped_column(Text, nullable=False)


@dataclass(frozen=True)
class CalendarDay:
    """What the calendar knows about one day, including where it learned it."""

    date: dt.date
    is_open: bool
    source: str
    session_note: str | None


class UnknownTradingDayError(LookupError):
    """The calendar has no row for that exchange and date, so there is no answer to give.

    Deliberately not a boolean. `SPEC.md` §4.1 forbids inferring missing data, and a calendar
    is the one table where the inference is most tempting and least safe.
    """


def _exchange_id(session: Session, exchange: str) -> int:
    found = session.execute(
        select(Exchange.id).where(Exchange.code == exchange)
    ).scalar_one_or_none()
    if found is None:
        raise UnknownTradingDayError(
            f"no exchange has the code {exchange!r}. The calendar is keyed on "
            f"`exchanges(id)`, so an unregistered exchange has no calendar at all."
        )
    return found


def day(session: Session, *, exchange: str, on: dt.date) -> CalendarDay:
    """What the calendar knows about one day, or `UnknownTradingDayError`."""
    exchange_id = _exchange_id(session, exchange)
    row = session.execute(
        select(
            TradingCalendarDay.is_open,
            TradingCalendarDay.source,
            TradingCalendarDay.session_note,
        )
        .where(TradingCalendarDay.exchange_id == exchange_id)
        .where(TradingCalendarDay.date == on)
    ).first()
    if row is None:
        raise UnknownTradingDayError(
            f"{exchange} has no calendar row for {on}. That is not the same as being closed: "
            f"nobody has recorded whether it traded. Add the day rather than assume it."
        )
    return CalendarDay(date=on, is_open=row[0], source=row[1], session_note=row[2])


def is_open(session: Session, *, exchange: str, on: dt.date) -> bool:
    """Whether the exchange traded on that day. Raises when the calendar does not know."""
    return day(session, exchange=exchange, on=on).is_open


def trading_days(session: Session, *, exchange: str, start: dt.date, end: dt.date) -> list[dt.date]:
    """Every day in `[start, end]` the calendar records as open, earliest first.

    Inclusive at both ends, and tolerant of unknown days by design: this is the "what is
    known" question, and a range with gaps is a legitimate answer to it. Arithmetic that must
    be right uses `add_trading_days`, which refuses instead.
    """
    if start > end:
        raise ValueError(f"start {start} is after end {end}")
    exchange_id = _exchange_id(session, exchange)
    return list(
        session.execute(
            select(TradingCalendarDay.date)
            .where(TradingCalendarDay.exchange_id == exchange_id)
            .where(TradingCalendarDay.is_open)
            .where(TradingCalendarDay.date >= start)
            .where(TradingCalendarDay.date <= end)
            .order_by(TradingCalendarDay.date)
        ).scalars()
    )


def _step(
    session: Session, *, exchange: str, from_date: dt.date, forward: bool, horizon: int = 30
) -> dt.date:
    """The next or previous open day, refusing at the first day the calendar does not know.

    `horizon` bounds the walk. An exchange shut for a month is an event somebody would know
    about; a walk that kept going would loop past the end of the calendar and answer from a
    region nobody has filled in.
    """
    exchange_id = _exchange_id(session, exchange)
    direction = 1 if forward else -1
    for offset in range(1, horizon + 1):
        candidate = from_date + dt.timedelta(days=direction * offset)
        row = session.execute(
            select(TradingCalendarDay.is_open)
            .where(TradingCalendarDay.exchange_id == exchange_id)
            .where(TradingCalendarDay.date == candidate)
        ).scalar_one_or_none()
        if row is None:
            raise UnknownTradingDayError(
                f"{exchange} has no calendar row for {candidate}, reached while walking "
                f"{'forward' if forward else 'back'} from {from_date}. The answer would rest "
                f"on a day nobody has recorded."
            )
        if row:
            return candidate
    raise UnknownTradingDayError(
        f"{exchange} records no open day within {horizon} days "
        f"{'after' if forward else 'before'} {from_date}"
    )


def next_trading_day(session: Session, *, exchange: str, after: dt.date) -> dt.date:
    """The first open day strictly after `after`."""
    return _step(session, exchange=exchange, from_date=after, forward=True)


def previous_trading_day(session: Session, *, exchange: str, before: dt.date) -> dt.date:
    """The last open day strictly before `before`."""
    return _step(session, exchange=exchange, from_date=before, forward=False)


def add_trading_days(session: Session, *, exchange: str, start: dt.date, days: int) -> dt.date:
    """`start` plus `days` trading days. Negative counts walk back; zero returns `start`.

    Zero does **not** check that `start` itself was a trading day: the caller asked for no
    movement, and a settlement calculated from a trade has already established that the trade
    happened. Every other count refuses at the first unknown day it meets.
    """
    if days == 0:
        return start
    current = start
    for _ in range(abs(days)):
        current = _step(session, exchange=exchange, from_date=current, forward=days > 0)
    return current


def settlement_date(session: Session, *, exchange: str, traded_on: dt.date) -> dt.date:
    """When a trade on `traded_on` settles, per that exchange's own settlement cycle.

    `exchanges.settlement_days` is the cycle - T+3 on NGX, T+1 on the US venues - and the
    days are *trading* days, which is the whole reason this cannot be `timedelta`.
    `OPERATIONS.md` §1.2: *"never `timedelta(days=3)`"*. A T+3 trade on the Thursday before a
    Monday holiday settles on the Wednesday, not the Sunday.
    """
    cycle = session.execute(
        select(Exchange.settlement_days).where(Exchange.code == exchange)
    ).scalar_one_or_none()
    if cycle is None:
        raise UnknownTradingDayError(f"no exchange has the code {exchange!r}")
    return add_trading_days(session, exchange=exchange, start=traded_on, days=int(cycle))


def coverage(session: Session, *, exchange: str) -> tuple[dt.date, dt.date, int] | None:
    """(earliest, latest, days recorded) for one exchange, or None when it has no calendar.

    What an operations page shows to answer "how far does the calendar reach", which is the
    question a reader has the moment a function above refuses.
    """
    exchange_id = _exchange_id(session, exchange)
    row = session.execute(
        select(
            func.min(TradingCalendarDay.date),
            func.max(TradingCalendarDay.date),
            func.count(),
        ).where(TradingCalendarDay.exchange_id == exchange_id)
    ).first()
    if row is None or row[0] is None:
        return None
    return (row[0], row[1], int(row[2]))

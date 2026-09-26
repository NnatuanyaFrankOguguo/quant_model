"""Timezone discipline — TG21 / task P0.14.

TG21 in `docs/00_START_HERE.md` §9: *"No document states the storage timezone, the NGX
session boundary in UTC, or which calendar date a WAT close belongs to."* The consequence
it names is the reason this module is P0 rather than P3: **off-by-one-day errors that look
like data errors, and one day of silent lookahead in every point-in-time join.**

The four rules, from `docs/08_DATA_CONTRACTS.md` §1.3 and `docs/10` §6.2:

1. **Storage is UTC.** Every `TIMESTAMPTZ` in the database is UTC. There are no exceptions
   and no local-time columns. `tests/unit/test_schema_conventions.py` fails the build on
   any naive `TIMESTAMP` column.
2. **Display is `Africa/Lagos`** (West Africa Time, UTC+1, no daylight saving).
3. **A plain `DATE` is a calendar date in the market's own local time.** An NGX trading
   date is a Lagos date. Deriving it from a UTC timestamp by taking `.date()` is wrong for
   every instant between 23:00 UTC and midnight UTC.
4. **NGX closes 14:30 WAT = 13:30 UTC.**

Naive datetimes are rejected rather than assumed to be UTC. Assuming is how a Lagos-local
timestamp becomes a UTC timestamp one hour in the past and nobody finds out.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo

#: The exchange's own timezone. `exchanges.timezone` holds this string per contract §2.1;
#: this constant is the NGX value, used where no exchange row is in hand yet.
NGX_TZ = ZoneInfo("Africa/Lagos")

#: The UTC timezone, re-exported so callers never reach for `pytz` or a bare `timezone`.
UTC_TZ = UTC

#: NGX close in exchange-local time.
NGX_CLOSE_LOCAL = time(14, 30)

#: NGX close expressed in UTC. WAT is UTC+1 with no daylight saving, so this is fixed.
#: `ngx_close_utc_on()` derives the same value from the tz database; a unit test asserts
#: the two agree, so a tz-database change is caught rather than silently ignored.
NGX_CLOSE_UTC = time(13, 30, tzinfo=UTC)


def utcnow() -> datetime:
    """Current instant as a timezone-aware UTC datetime.

    Use this everywhere instead of `datetime.utcnow()`, which returns a *naive* datetime
    holding UTC values — the single most common source of mixed naive/aware comparisons.
    """
    return datetime.now(UTC)


def utctoday() -> date:
    """Today's date in UTC. The default `on` date for dated-config lookups."""
    return utcnow().date()


def ensure_utc(ts: datetime) -> datetime:
    """Return `ts` converted to UTC, rejecting naive datetimes.

    Raises:
        ValueError: if `ts` has no tzinfo. A naive datetime carries no information about
            which instant it names, and guessing is how one-hour errors enter the data.
    """
    if ts.tzinfo is None or ts.tzinfo.utcoffset(ts) is None:
        raise ValueError(
            "Naive datetime rejected: attach a timezone before storing or comparing "
            "(packages.common.timez.utcnow() returns an aware UTC datetime)."
        )
    return ts.astimezone(UTC)


def to_ngx(ts: datetime) -> datetime:
    """Convert an instant to exchange-local (Africa/Lagos) time, for display only."""
    return ensure_utc(ts).astimezone(NGX_TZ)


def ngx_close_utc_on(day: date) -> datetime:
    """The exact UTC instant of the NGX close on a given Lagos calendar date.

    Derived from the tz database rather than from the `NGX_CLOSE_UTC` constant, so that a
    future offset change (or a tz-data correction) is reflected here rather than silently
    contradicting the constant.
    """
    local_close = datetime.combine(day, NGX_CLOSE_LOCAL, tzinfo=NGX_TZ)
    return local_close.astimezone(UTC)


def session_date_for(ts: datetime) -> date:
    """Map an instant to the NGX trading date it belongs to.

    The rule, and the reason for it:

    * An instant **at or before** the 14:30 WAT close belongs to that Lagos calendar
      date's session. The close itself is inclusive — the closing print is part of the
      session that produced it.
    * An instant **after** the close belongs to the **next** calendar date. A news item
      published at 18:00 WAT on Monday could not have moved Monday's close; attributing it
      to Monday is one day of lookahead, and it is invisible — a backtest that does it
      simply reports a better number.

    Note the deliberate limitation: this returns the next **calendar** date, not the next
    **open** date, because `trading_calendar` does not exist until P3. A post-close Friday
    timestamp maps to Saturday. Callers that need the next *trading* day must roll forward
    through `trading_calendar` once P3 lands; this function is the timezone half of the
    problem and does not pretend to be the holiday half.

    Raises:
        ValueError: if `ts` is naive (see `ensure_utc`).
    """
    local = to_ngx(ts)
    if local.timetz().replace(tzinfo=None) <= NGX_CLOSE_LOCAL:
        return local.date()
    return local.date() + timedelta(days=1)

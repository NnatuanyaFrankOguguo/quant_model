r"""Seed the trading calendar from what is known, and nothing else. TG2, P3 check 5.

    .venv\Scripts\python.exe scripts\seed_trading_calendar.py
    .venv\Scripts\python.exe scripts\seed_trading_calendar.py --from 2015-01-01 --to 2027-12-31

`OPERATIONS.md` §1.2 prescribes the method: *"Seed NGX from observed trading days in the
`afx.kwayisi` price history (a day with no price list is a day the exchange did not trade)
and correct forward from NGX announcements. For US exchanges use
`pandas-market-calendars`."*

Neither half is available as written - there are no NGX prices yet and
`pandas-market-calendars` is not installed - so this seeds the same *kinds* of day from the
evidence that does exist, and records on every row which kind it is.

## What it writes, and how strong each one is

**Weekends, `source='weekend'`.** Definitional. NGX, NYSE and NASDAQ do not trade on a
Saturday or a Sunday, and that needs no source beyond the calendar.

**Observed open days, `source='observed_bars'`.** Inferred, and only in the safe direction: a
day on which `price_history` holds a bar for a security on that exchange is a day the
exchange traded. 14,298 NYSE days and 13,626 NASDAQ days are available this way, back to
1970. The converse is **not** inferred - a weekday with no bar may have been a holiday or a
failed scrape, and that ambiguity is the whole reason `docs/01` §7.2 wants this table. So a
weekday gap is left absent, and `packages/common/calendars.py` reports it as unknown.

**Nigerian fixed-date statutory holidays, `source='statute_fixed'`.** The days Nigeria's
Public Holidays Act fixes to a date - 1 January, 1 May, 12 June, 1 October, 25 and 26
December - plus Good Friday and Easter Monday, which move but are computable exactly. Each
row's `session_note` says the basis is the statute and **not** an NGX notice, because those
are different claims and a reader deciding whether to trust a settlement date needs to know
which one they have.

## What it deliberately does not write

**Nigeria's moving holidays.** `OPERATIONS.md` §1.2: *"the Islamic ones (Eid al-Fitr, Eid
al-Adha, Maulid) move each year and are frequently announced only days in advance by the
Federal Government."* They cannot be computed. A secondary holiday aggregator was checked and
rejected as a source: it lists Children's Day as a public holiday, which is observed in
Nigeria but is not the same claim as the exchange being shut, and `docs/00` §11's rule is
that an unverified Nigerian market fact is a question rather than a fact. `docs/03` line 1540
already lists NGX trading-calendar dates among the operator's manual work.

**US weekday holidays.** Thanksgiving and the rest are absent, so `add_trading_days` on a
US exchange refuses when it reaches one. That is correct rather than convenient: the fix is
`pandas-market-calendars` (already declared in the `data` extra), and until it runs the
arithmetic refuses instead of answering from a guess.

Re-running is safe: every day already recorded is left exactly as it is, so a hand-entered
announcement is never overwritten by a later seed.
"""

from __future__ import annotations

import argparse
import datetime as dt
from collections.abc import Iterator

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from packages.common.calendars import OBSERVED_BARS, WEEKEND, TradingCalendarDay
from packages.common.console import configure_logging, info, step, success, warning
from packages.common.db import get_session
from packages.common.models import Exchange, PriceHistory, Security

#: `source` for a day that rests on the Public Holidays Act's fixed dates rather than on an
#: exchange notice. Distinct from `announced` on purpose: nobody has read an NGX circular.
STATUTE_FIXED = "statute_fixed"

#: (month, day, name) for the Nigerian holidays the statute fixes to a date.
NIGERIAN_FIXED_HOLIDAYS: tuple[tuple[int, int, str], ...] = (
    (1, 1, "New Year's Day"),
    (5, 1, "Workers' Day"),
    # Moved from 29 May to 12 June in 2019, and 12 June is the date in force.
    (6, 12, "Democracy Day"),
    (10, 1, "Independence Day"),
    (12, 25, "Christmas Day"),
    (12, 26, "Boxing Day"),
)

DEFAULT_FROM = dt.date(2015, 1, 1)
DEFAULT_TO = dt.date(2027, 12, 31)


def easter_sunday(year: int) -> dt.date:
    """Western Easter, by the anonymous Gregorian algorithm. Exact, so it needs no source."""
    a = year % 19
    b, c = divmod(year, 100)
    d, e = divmod(b, 4)
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i, k = divmod(c, 4)
    length = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * length) // 451
    month, day = divmod(h + length - 7 * m + 114, 31)
    return dt.date(year, month, day + 1)


def nigerian_statutory_closures(start: dt.date, end: dt.date) -> Iterator[tuple[dt.date, str]]:
    """Every fixed-date or computable Nigerian statutory holiday in the range."""
    for year in range(start.year, end.year + 1):
        for month, day_of_month, name in NIGERIAN_FIXED_HOLIDAYS:
            when = dt.date(year, month, day_of_month)
            if start <= when <= end:
                yield when, name
        easter = easter_sunday(year)
        for offset, name in ((-2, "Good Friday"), (1, "Easter Monday")):
            when = easter + dt.timedelta(days=offset)
            if start <= when <= end:
                yield when, name


def weekends(start: dt.date, end: dt.date) -> Iterator[dt.date]:
    current = start
    while current <= end:
        if current.weekday() >= 5:  # Saturday, Sunday
            yield current
        current += dt.timedelta(days=1)


def observed_open_days(session: Session, exchange_id: int) -> list[dt.date]:
    """Days on which some security of this exchange has a price bar."""
    return list(
        session.execute(
            select(PriceHistory.date)
            .join(Security, Security.id == PriceHistory.security_id)
            .where(Security.exchange_id == exchange_id)
            .distinct()
            .order_by(PriceHistory.date)
        ).scalars()
    )


#: Rows per INSERT. Postgres allows 65,535 bound parameters in one statement and each row
#: binds five, so NYSE's 14,298 observed days plus its weekends overflow a single statement -
#: which it did, with "number of parameters must be between 0 and 65535".
_BATCH = 5_000


def _write(session: Session, rows: list[dict[str, object]]) -> int:
    """Insert days in batches, leaving any that already exist untouched.

    `ON CONFLICT DO NOTHING` and not an upsert: a day a person entered from an announcement
    outranks anything this script infers, and a re-run must never quietly replace it.
    """
    written = 0
    for start in range(0, len(rows), _BATCH):
        batch = rows[start : start + _BATCH]
        if not batch:
            continue
        written += len(
            session.execute(
                pg_insert(TradingCalendarDay)
                .values(batch)
                .on_conflict_do_nothing(index_elements=["exchange_id", "date"])
                .returning(TradingCalendarDay.date)
            ).all()
        )
    return written


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--from", dest="start", type=dt.date.fromisoformat, default=DEFAULT_FROM)
    parser.add_argument("--to", dest="end", type=dt.date.fromisoformat, default=DEFAULT_TO)
    args = parser.parse_args(argv)
    configure_logging()

    if args.start > args.end:
        warning("nothing to do", start=str(args.start), end=str(args.end))
        return 1

    with get_session() as session:
        exchanges = list(session.execute(select(Exchange.id, Exchange.code)).all())

        for exchange_id, code in exchanges:
            with step(f"Seed {code}", start=str(args.start), end=str(args.end)) as seeding:
                rows: list[dict[str, object]] = [
                    {
                        "exchange_id": exchange_id,
                        "date": when,
                        "is_open": False,
                        "session_note": "weekend",
                        "source": WEEKEND,
                    }
                    for when in weekends(args.start, args.end)
                ]

                observed = observed_open_days(session, exchange_id)
                rows += [
                    {
                        "exchange_id": exchange_id,
                        "date": when,
                        "is_open": True,
                        "session_note": "a price bar exists for this day",
                        "source": OBSERVED_BARS,
                    }
                    for when in observed
                ]

                statutory = 0
                if code == "NGX":
                    for when, name in nigerian_statutory_closures(args.start, args.end):
                        rows.append(
                            {
                                "exchange_id": exchange_id,
                                "date": when,
                                "is_open": False,
                                "session_note": (
                                    f"public holiday: {name} (Public Holidays Act fixed date; "
                                    f"NOT verified against an NGX notice)"
                                ),
                                "source": STATUTE_FIXED,
                            }
                        )
                        statutory += 1

                # Christmas Day 2027 is a Saturday, so a statutory closure and a weekend can
                # name the same day. Deduplicated here rather than left to the conflict
                # clause: two rows with one key inside a single INSERT is not a case worth
                # depending on, and the first-wins order should be decided in the open. The
                # weekend row is the one kept - it is definitional, and no less closed.
                deduplicated: dict[dt.date, dict[str, object]] = {}
                for row in rows:
                    deduplicated.setdefault(row["date"], row)  # type: ignore[arg-type]
                inserted = _write(session, list(deduplicated.values()))
                seeding.result(
                    proposed=len(deduplicated),
                    inserted=inserted,
                    already_known=len(deduplicated) - inserted,
                    observed_open=len(observed),
                    statutory_closures=statutory,
                )

    info(
        "what is still absent",
        nigerian_moving_holidays="Eid al-Fitr, Eid al-Adha, Maulid - announced, operator's",
        us_weekday_holidays="needs pandas-market-calendars",
    )
    success("trading calendar seeded from evidence, and silent about the rest")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

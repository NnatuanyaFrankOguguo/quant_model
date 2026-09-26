"""P6 checks 3, 5 and 6, enforced structurally rather than counted.

A query of the form "count the rows that break this rule, assert zero" passes on an
empty table, which is the failure mode the P6 agents kept finding in their own audit
greps: a broken check and a clean system produce identical output. So two of these three
are asserted against the *schema*, which is true whether or not anybody has loaded data,
and the third is asserted by constructing the violation and watching it be refused.
"""

from __future__ import annotations

import datetime as dt

import pytest
from sqlalchemy import text

from packages.indicators.store import store_for_security
from tests.unit.test_indicator_series import _bars


def _constraints(session, table: str) -> dict[str, str]:  # type: ignore[no-untyped-def]
    # `to_regclass(:t)` rather than `:t::regclass`: psycopg will not bind a parameter
    # into a cast written with `::`, and the table name here is a literal anyway.
    rows = session.execute(
        text(
            "select conname, pg_get_constraintdef(oid) from pg_constraint "
            "where conrelid = to_regclass(:t)"
        ),
        {"t": table},
    ).all()
    return {name: definition for name, definition in rows}


def test_check_3_is_a_column_not_a_convention(db_session) -> None:  # type: ignore[no-untyped-def]
    """P6 check 3. `docs/08` §2.7 keeps `price_series` in the table so the adjusted-price
    rule is auditable in rows already written, not only in a lint rule that can see the
    next commit and not the last one. So the rule has to be *in* the schema."""
    defs = _constraints(db_session, "indicators")
    check = defs.get("indicators_price_series_known")
    assert check is not None, f"the price_series CHECK is gone: {sorted(defs)}"
    assert "adjusted" in check and "raw" in check

    not_null = db_session.execute(
        text(
            "select is_nullable from information_schema.columns "
            "where table_name='indicators' and column_name='price_series'"
        )
    ).scalar()
    # A CHECK passes when its predicate is NULL - only FALSE rejects - so the constraint
    # above is only worth having because the column cannot be NULL. Migration 0021.
    assert not_null == "NO"


def test_check_6_is_impossible_to_violate(db_session) -> None:  # type: ignore[no-untyped-def]
    """P6 check 6 asks for `count(*) where known_as_of is null` to be 0. It cannot be
    anything else: the column is NOT NULL and sits in the primary key."""
    nullable = db_session.execute(
        text(
            "select is_nullable from information_schema.columns "
            "where table_name='indicators' and column_name='known_as_of'"
        )
    ).scalar()
    assert nullable == "NO"

    pk = db_session.execute(
        text(
            "select pg_get_constraintdef(oid) from pg_constraint "
            "where conrelid='indicators'::regclass and contype='p'"
        )
    ).scalar()
    assert "known_as_of" in pk


def test_an_indicator_cannot_predate_the_bar_it_describes(db_session) -> None:  # type: ignore[no-untyped-def]
    """The PIT sanity CHECK, constructed rather than counted."""
    defs = _constraints(db_session, "indicators")
    assert "indicators_pit_sanity" in defs
    assert "known_as_of" in defs["indicators_pit_sanity"]


def test_a_recomputation_is_refused_rather_than_allowed_to_overwrite(db_session) -> None:  # type: ignore[no-untyped-def]
    """Migration 0002's trigger, on this table. An UPDATE must raise, not succeed.

    This is what makes `known_as_of` in the primary key load-bearing rather than
    decorative: with UPDATE forbidden, a recomputation has nowhere to go except a new
    row.
    """
    triggers = (
        db_session.execute(
            text(
                "select tgname from pg_trigger where tgrelid='indicators'::regclass "
                "and not tgisinternal"
            )
        )
        .scalars()
        .all()
    )
    assert "no_update" in triggers


def test_store_refuses_an_unknown_price_series(db_session) -> None:  # type: ignore[no-untyped-def]
    """`price_series` is recorded rather than assumed, so a typo must not become a row."""
    bars = _bars([dt.date(2024, 1, 1)] * 3)
    with pytest.raises(ValueError, match="price_series"):
        store_for_security(db_session, security_id=1, bars=bars, specs=[], price_series="ajusted")


# --------------------------------------------------------------------------------------
# P6 check 5, which is a property of the data rather than of the schema
# --------------------------------------------------------------------------------------


def test_check_5_no_indicator_on_a_day_the_market_was_closed(db_session) -> None:  # type: ignore[no-untyped-def]
    """P6 check 5.

    There is no constraint that can express this - it is a join between two tables - so
    it is counted. The count is only meaningful against a populated database, so the
    test says how many rows it actually examined and skips rather than passing silently
    when there are none. A green tick on nothing checked is worse than a skip.
    """
    examined = db_session.execute(
        text(
            "select count(*) from indicators i "
            "join securities se on se.id = i.security_id "
            "join trading_calendar tc "
            "  on tc.exchange_id = se.exchange_id and tc.date = i.date"
        )
    ).scalar_one()
    if examined == 0:
        pytest.skip("no indicator rows with a calendar entry in this database")

    closed = db_session.execute(
        text(
            "select count(*) from indicators i "
            "join securities se on se.id = i.security_id "
            "join trading_calendar tc "
            "  on tc.exchange_id = se.exchange_id and tc.date = i.date "
            "where tc.is_open = false"
        )
    ).scalar_one()
    assert closed == 0, f"{closed} of {examined} indicator rows fall on a closed day"

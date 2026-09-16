"""`packages.common.fx`: a conversion takes the date the money is measured at, and the date
the reader is standing on. TG2, `OPERATIONS.md` §1.3.

The naira is the reason this is not pedantry: the official rate went from 907.1 at the end of
2023 to 1,535.0 at the end of 2024, so a 2023 figure converted at the 2024 rate is wrong by
a multiple. The tests below use those two real rates.
"""

from __future__ import annotations

import datetime as dt
from decimal import Decimal

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from packages.common.fx import NFEM_OFFICIAL, convert, rate_on
from packages.common.models import DataSource, FxRate, SourceDocument
from packages.common.timez import utcnow

RATES = {
    dt.date(2023, 12, 29): Decimal("907.1"),
    dt.date(2024, 12, 31): Decimal("1535.0"),
}


@pytest.fixture
def seeded(db_session: Session) -> int:
    """The two real year-end rates, each dated the day it was true of. Returns the document."""
    source_id = db_session.execute(select(DataSource.id).order_by(DataSource.id)).scalars().first()
    document = SourceDocument(
        data_source_id=source_id,
        url="file:///cbn-rates.json",
        storage_key="documents/sha256/" + "c" * 64,
        sha256="c" * 64,
        media_type="application/json",
        retrieved_at=utcnow(),
    )
    db_session.add(document)
    db_session.flush()
    for as_of, rate in RATES.items():
        db_session.add(
            FxRate(
                base_currency="USD",
                quote_currency="NGN",
                rate_type=NFEM_OFFICIAL,
                as_of_date=as_of,
                known_as_of=as_of,
                rate=rate,
                data_source_id=source_id,
                source_document_id=document.id,
            )
        )
    db_session.flush()
    return document.id


@pytest.mark.invariant
def test_a_figure_is_converted_at_its_own_dates_rate_not_todays(
    db_session: Session, seeded: int
) -> None:
    """One billion naira is $1.10m at the end of 2023 and $0.65m a year later. Same money,
    different date, and the difference is the whole reason this function takes one."""
    then = convert(
        db_session,
        Decimal("1000000000"),
        from_currency="NGN",
        to_currency="USD",
        on=dt.date(2023, 12, 29),
        decision_date=dt.date(2026, 9, 16),
    )
    later = convert(
        db_session,
        Decimal("1000000000"),
        from_currency="NGN",
        to_currency="USD",
        on=dt.date(2024, 12, 31),
        decision_date=dt.date(2026, 9, 16),
    )
    assert then is not None and later is not None
    assert then.amount.quantize(Decimal("1")) == Decimal("1102414")  # 1bn / 907.1
    assert later.amount.quantize(Decimal("1")) == Decimal("651466")  # 1bn / 1535.0
    # The rate returned is the rate applied: a reader can reproduce the figure from it.
    assert then.rate.rate == Decimal("0.001102414287")
    assert (Decimal("1000000000") * then.rate.rate).quantize(Decimal("1")) == then.amount.quantize(
        Decimal("1")
    )
    assert then.rate.inverted is True, "the stored pair is USD/NGN; this direction inverts it"
    assert then.rate.as_of_date == dt.date(2023, 12, 29) and then.rate.age_days == 0
    assert then.rate.source_document_id == seeded, "provenance travels with the rate"


def test_the_stored_direction_is_used_as_it_is(db_session: Session, seeded: int) -> None:
    got = convert(
        db_session,
        Decimal("100"),
        from_currency="USD",
        to_currency="NGN",
        on=dt.date(2024, 12, 31),
        decision_date=dt.date(2026, 9, 16),
    )
    assert got is not None
    assert got.amount == Decimal("153500.0") and got.rate.inverted is False
    assert got.rate.rate == Decimal("1535.0")


@pytest.mark.invariant
def test_a_rate_published_after_the_decision_date_is_unseen(
    db_session: Session, seeded: int
) -> None:
    """A corrected rate is a second row, and a reader standing before it must not see it."""
    db_session.add(
        FxRate(
            base_currency="USD",
            quote_currency="NGN",
            rate_type=NFEM_OFFICIAL,
            as_of_date=dt.date(2024, 12, 31),
            known_as_of=dt.date(2025, 1, 15),  # corrected a fortnight later
            rate=Decimal("1540.0"),
            data_source_id=db_session.execute(select(DataSource.id).order_by(DataSource.id))
            .scalars()
            .first(),
            source_document_id=seeded,
        )
    )
    db_session.flush()
    on = dt.date(2024, 12, 31)
    before = rate_on(db_session, base="USD", quote="NGN", on=on, decision_date=dt.date(2025, 1, 2))
    after = rate_on(db_session, base="USD", quote="NGN", on=on, decision_date=dt.date(2025, 2, 1))
    assert before is not None and before.rate == Decimal("1535.0"), "the first vintage"
    assert after is not None and after.rate == Decimal("1540.0"), "the correction, once public"


def test_a_weekend_carries_fridays_rate_but_a_gap_does_not_carry_forever(
    db_session: Session, seeded: int
) -> None:
    """2024-12-31 was a Tuesday: the 2nd of January reads it, two days old. A date months
    past the newest rate gets nothing - a stale rate silently applied is the bug."""
    near = rate_on(
        db_session,
        base="USD",
        quote="NGN",
        on=dt.date(2025, 1, 2),
        decision_date=dt.date(2026, 9, 16),
    )
    assert near is not None and near.age_days == 2 and near.rate == Decimal("1535.0")

    far = rate_on(
        db_session,
        base="USD",
        quote="NGN",
        on=dt.date(2025, 6, 30),
        decision_date=dt.date(2026, 9, 16),
    )
    assert far is None, "no rate close enough: say so rather than convert at a half-year-old one"
    assert (
        convert(
            db_session,
            Decimal("1000"),
            from_currency="NGN",
            to_currency="USD",
            on=dt.date(2025, 6, 30),
            decision_date=dt.date(2026, 9, 16),
        )
        is None
    )


def test_a_rate_before_the_first_one_held_is_not_invented(db_session: Session, seeded: int) -> None:
    assert (
        rate_on(
            db_session,
            base="USD",
            quote="NGN",
            on=dt.date(2020, 1, 1),
            decision_date=dt.date(2026, 9, 16),
        )
        is None
    )


@pytest.mark.invariant
def test_a_conversion_without_dates_is_a_type_error(db_session: Session) -> None:
    """`OPERATIONS.md` §1.3: a conversion function without a date parameter is a defect."""
    with pytest.raises(TypeError):
        rate_on(db_session, base="USD", quote="NGN", on=dt.date(2024, 12, 31), decision_date=None)  # type: ignore[arg-type]
    with pytest.raises(TypeError):
        rate_on(db_session, base="USD", quote="NGN", on=None, decision_date=dt.date(2024, 12, 31))  # type: ignore[arg-type]
    with pytest.raises(TypeError):
        rate_on(db_session, base="USD", quote="NGN", on=dt.date(2024, 12, 31))  # type: ignore[call-arg]


def test_a_currency_pair_with_itself_is_refused(db_session: Session) -> None:
    with pytest.raises(ValueError, match="not a conversion"):
        convert(
            db_session,
            Decimal("1"),
            from_currency="NGN",
            to_currency="ngn",
            on=dt.date(2024, 12, 31),
            decision_date=dt.date(2026, 9, 16),
        )

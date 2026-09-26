"""`snapshot.backdrop_for`: the risk-free rate and inflation a yield is read against (Q16).

Every reading is point-in-time on the decision date - the same rule the macro routes apply -
and an index series becomes a year-on-year rate only from a reading exactly twelve months
earlier that was itself known on the date. Nothing is stretched, nothing is estimated.
"""

from __future__ import annotations

import datetime as dt
from decimal import Decimal

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from packages.common.models import MacroObservation, MacroSeries, SourceDocument
from packages.valuation.snapshot import backdrop_for


@pytest.fixture
def document_id(db_session: Session) -> int:
    document = SourceDocument(
        data_source_id=db_session.execute(
            select(MacroSeries.data_source_id).where(MacroSeries.code == "US_CPI_INDEX")
        ).scalar_one(),
        url="file:///backdrop-fixture.csv",
        storage_key="documents/sha256/" + "e" * 64,
        sha256="e" * 64,
        media_type="text/csv",
        retrieved_at=dt.datetime(2026, 9, 1, tzinfo=dt.UTC),
    )
    db_session.add(document)
    db_session.flush()
    return document.id


def _add(session: Session, code: str, as_of: str, known: str, value: str, doc: int) -> None:
    session.add(
        MacroObservation(
            series_id=session.execute(
                select(MacroSeries.id).where(MacroSeries.code == code)
            ).scalar_one(),
            as_of_date=dt.date.fromisoformat(as_of),
            known_as_of=dt.date.fromisoformat(known),
            value=Decimal(value),
            source_document_id=doc,
        )
    )


@pytest.mark.invariant
def test_an_index_becomes_a_year_on_year_rate_from_the_reading_twelve_months_earlier(
    db_session: Session, document_id: int
) -> None:
    _add(db_session, "US_10Y_TREASURY", "2026-08-28", "2026-08-29", "4.25", document_id)
    _add(db_session, "US_CPI_INDEX", "2025-07-01", "2025-08-12", "300.0", document_id)
    _add(db_session, "US_CPI_INDEX", "2026-07-01", "2026-08-12", "309.0", document_id)
    db_session.flush()

    backdrop = backdrop_for(db_session, currency="USD", decision_date=dt.date(2026, 8, 30))
    assert backdrop is not None
    assert backdrop.risk_free is not None and backdrop.risk_free.value == Decimal("4.25")
    assert backdrop.risk_free.as_of_date == dt.date(2026, 8, 28)
    assert backdrop.inflation is not None
    assert backdrop.inflation.value == Decimal("3.00"), "309 / 300 - 1"
    assert backdrop.inflation.unit == "percent"
    assert backdrop.inflation.as_of_date == dt.date(2026, 7, 1)
    assert backdrop.inflation_basis.startswith("index:")
    assert backdrop.real_risk_free == Decimal("1.25")


@pytest.mark.invariant
def test_a_revision_published_after_the_decision_date_is_unseen(
    db_session: Session, document_id: int
) -> None:
    _add(db_session, "US_10Y_TREASURY", "2026-08-28", "2026-08-29", "4.25", document_id)
    _add(db_session, "US_CPI_INDEX", "2025-07-01", "2025-08-12", "300.0", document_id)
    _add(db_session, "US_CPI_INDEX", "2026-07-01", "2026-08-12", "309.0", document_id)
    # A later vintage of the same month, published after the decision date.
    _add(db_session, "US_CPI_INDEX", "2026-07-01", "2026-09-10", "312.0", document_id)
    db_session.flush()

    on_aug_30 = backdrop_for(db_session, currency="USD", decision_date=dt.date(2026, 8, 30))
    on_sep_12 = backdrop_for(db_session, currency="USD", decision_date=dt.date(2026, 9, 12))
    assert on_aug_30 is not None and on_aug_30.inflation is not None
    assert on_sep_12 is not None and on_sep_12.inflation is not None
    assert on_aug_30.inflation.value == Decimal("3.00")
    assert on_sep_12.inflation.value == Decimal("4.00"), "312 / 300 - 1, the revised vintage"


@pytest.mark.invariant
def test_a_missing_month_a_year_earlier_gives_no_rate_rather_than_a_stretched_one(
    db_session: Session, document_id: int
) -> None:
    _add(db_session, "US_CPI_INDEX", "2025-06-01", "2025-07-12", "298.0", document_id)  # June
    _add(db_session, "US_CPI_INDEX", "2026-07-01", "2026-08-12", "309.0", document_id)  # July
    db_session.flush()

    backdrop = backdrop_for(db_session, currency="USD", decision_date=dt.date(2026, 8, 30))
    assert backdrop is not None
    assert backdrop.inflation is None, "July against June is not a year-on-year rate"
    assert backdrop.real_risk_free is None


def test_a_published_year_on_year_series_is_used_as_it_is(
    db_session: Session, document_id: int
) -> None:
    _add(db_session, "NG_MPR", "2026-07-31", "2026-07-31", "26.50", document_id)
    _add(db_session, "NG_CPI_YOY_CBN", "2026-07-31", "2026-08-31", "15.43", document_id)
    db_session.flush()

    backdrop = backdrop_for(db_session, currency="NGN", decision_date=dt.date(2026, 9, 1))
    assert backdrop is not None
    assert backdrop.inflation is not None and backdrop.inflation.value == Decimal("15.43")
    assert backdrop.inflation_basis.startswith("series:")
    assert backdrop.real_risk_free == Decimal("11.07")


def test_a_currency_with_no_series_behind_it_gets_nothing(db_session: Session) -> None:
    assert backdrop_for(db_session, currency="GBP", decision_date=dt.date(2026, 9, 1)) is None

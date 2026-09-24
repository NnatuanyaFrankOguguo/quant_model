"""`packages.normalize.devaluation`: the annotation P4.5 asks for, on real rates.

`docs/03` P4.5 requires that year-on-year comparisons be *annotated as distorted by
devaluation*, because *"every growth metric you compute for Nigerian companies over this
period is misleading without being wrong"*. Nothing here is a data error, so nothing here
can be caught by a validation rule - which is why it needs its own module and its own
tests.

The rates used are the real ones: 907.1 at the end of 2023 and 1,535.0 a year later, the
same two `test_fx.py` uses and the same two `docs/03` P4.5 quotes.
"""

from __future__ import annotations

import datetime as dt
from decimal import Decimal

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from packages.common.fx import NFEM_OFFICIAL
from packages.common.models import DataSource, FxRate, SourceDocument
from packages.common.timez import utcnow
from packages.normalize.devaluation import (
    DISTORTED,
    MATERIAL_NOMINAL_INFLATION,
    NOT_DISTORTED,
    UNKNOWN,
    devaluation_between,
)

pytestmark = pytest.mark.invariant

FY2023 = dt.date(2023, 12, 31)
FY2024 = dt.date(2024, 12, 31)
#: Far enough after both that every vintage below is knowable. Point-in-time still applies -
#: `devaluation_between` refuses to assume one, like `rate_on` before it.
TODAY = dt.date(2026, 1, 1)

#: The float. 907.1 to 1,535.0 is +69.2206% on the naira price of a dollar, and a 40.9055% fall in
#: what a naira buys. Both figures appear below, because confusing them is the specific
#: mistake this module is shaped to prevent.
RATES = {
    dt.date(2023, 12, 29): Decimal("907.1"),
    dt.date(2024, 12, 31): Decimal("1535.0"),
}
#: The peg years either side of it, for the case that must NOT be flagged.
FLAT = {
    dt.date(2018, 12, 31): Decimal("306.5"),
    dt.date(2019, 12, 31): Decimal("306.95"),
}


def _seed(session: Session, rates: dict[dt.date, Decimal], *, marker: str) -> None:
    """Rates dated the day each was true of, known the same day."""
    source_id = session.execute(select(DataSource.id).order_by(DataSource.id)).scalars().first()
    document = SourceDocument(
        data_source_id=source_id,
        url=f"file:///cbn-rates-{marker}.json",
        storage_key="documents/sha256/" + marker * 64,
        sha256=marker * 64,
        media_type="application/json",
        retrieved_at=utcnow(),
    )
    session.add(document)
    session.flush()
    for as_of, rate in rates.items():
        session.add(
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
    session.flush()


@pytest.fixture
def floated(db_session: Session) -> None:
    _seed(db_session, RATES, marker="d")


@pytest.fixture
def pegged(db_session: Session) -> None:
    _seed(db_session, FLAT, marker="e")


def test_the_float_year_is_flagged_and_both_figures_are_right(
    db_session: Session, floated: None
) -> None:
    """The MTN year, and the two numbers that describe it.

    907.1 to 1,535.0 means a figure unchanged in dollars appears 69.2% larger in naira, and
    one naira lost 40.9% of what it bought. Both are true of the same move and neither is
    the other's negative; a reader given the wrong one draws the wrong conclusion with full
    confidence, which is why the dataclass carries both under names that say which is which.
    """
    result = devaluation_between(
        db_session,
        presentation="NGN",
        earlier_period_end=FY2023,
        later_period_end=FY2024,
        decision_date=TODAY,
    )
    assert result.status == DISTORTED
    assert result.is_distorted
    assert result.nominal_inflation == pytest.approx(Decimal("0.692206"), abs=Decimal("0.000001"))
    assert result.presentation_loss == pytest.approx(Decimal("-0.409055"), abs=Decimal("0.000001"))
    # Not each other's negative, and the test says so rather than leaving it to be noticed.
    assert result.nominal_inflation != -result.presentation_loss


def test_the_note_says_the_thing_a_reader_needs_before_quoting_a_growth_rate(
    db_session: Session, floated: None
) -> None:
    """P4.5 asks for an annotation, not a boolean.

    The sentence has to survive being pasted next to "revenue up 36%" and still change what
    the reader does, so it leads with the consequence and names both figures.
    """
    note = devaluation_between(
        db_session,
        presentation="NGN",
        earlier_period_end=FY2023,
        later_period_end=FY2024,
        decision_date=TODAY,
    ).note
    assert "distorted by currency" in note
    assert "weakened" in note
    assert "40.9%" in note  # what the naira lost
    assert "+69.2%" in note  # what an unchanged dollar figure looks like in naira
    assert "should not be quoted alone" in note


def test_a_pegged_year_is_not_flagged(db_session: Session, pegged: None) -> None:
    """306.5 to 306.95 is a tenth of a per cent. Flagging it would train the reader to skip
    the annotation, which costs more than not having one."""
    result = devaluation_between(
        db_session,
        presentation="NGN",
        earlier_period_end=dt.date(2018, 12, 31),
        later_period_end=dt.date(2019, 12, 31),
        decision_date=TODAY,
    )
    assert result.status == NOT_DISTORTED
    assert not result.is_distorted
    assert result.nominal_inflation is not None
    assert abs(result.nominal_inflation) < MATERIAL_NOMINAL_INFLATION
    # The quiet case gets a sentence too. A reader who sees an annotation on one comparison
    # and nothing on the next cannot tell whether the second was checked and cleared or
    # never checked at all - which is the same confusion `UNKNOWN` exists to prevent, one
    # level up.
    assert "below the 10% threshold" in result.note
    assert "not dominated by currency" in result.note


def test_a_missing_rate_is_unknown_and_never_reads_as_comparable(db_session: Session) -> None:
    """The distinction the module exists around, in its sharpest form.

    With no rates seeded at all, the honest answer is "cannot tell". If that came back as
    `NOT_DISTORTED`, or with the ratios set to zero, a caller would publish "comparable"
    about a period nobody checked - the same absence-we-caused versus absence-the-world-
    caused confusion that `not_in_filing` and `no_mapping` exist to keep apart.
    """
    result = devaluation_between(
        db_session,
        presentation="NGN",
        earlier_period_end=FY2023,
        later_period_end=FY2024,
        decision_date=TODAY,
    )
    assert result.status == UNKNOWN
    assert not result.is_distorted
    # Not zero. Zero is a number, and a caller that forgot to check `status` would read it
    # as "the currency did not move".
    assert result.nominal_inflation is None
    assert result.presentation_loss is None
    assert "not a statement that the comparison is sound" in result.note


def test_only_the_later_rate_missing_is_still_unknown(db_session: Session) -> None:
    """Half an answer is not an answer, and the reason names which date was missing."""
    _seed(db_session, {dt.date(2023, 12, 29): Decimal("907.1")}, marker="f")
    result = devaluation_between(
        db_session,
        presentation="NGN",
        earlier_period_end=FY2023,
        later_period_end=FY2024,
        decision_date=TODAY,
    )
    assert result.status == UNKNOWN
    assert str(FY2024) in result.reason


def test_periods_out_of_order_raise_rather_than_return_an_inverted_move(
    db_session: Session, floated: None
) -> None:
    """A caller that swapped its arguments, not a data condition.

    Inverted, this comparison returns -40.9% and +69.2% with the labels exchanged, which
    reads as a strengthening naira and is perfectly plausible on its face. There is no
    downstream check that would catch it, so it is refused at the door.
    """
    with pytest.raises(ValueError, match="must fall before"):
        devaluation_between(
            db_session,
            presentation="NGN",
            earlier_period_end=FY2024,
            later_period_end=FY2023,
            decision_date=TODAY,
        )


def test_equal_periods_are_also_refused(db_session: Session, floated: None) -> None:
    """One date compared with itself is a zero move, and answering zero would be a way of
    saying "comparable" about a question that was not asked."""
    with pytest.raises(ValueError, match="must fall before"):
        devaluation_between(
            db_session,
            presentation="NGN",
            earlier_period_end=FY2024,
            later_period_end=FY2024,
            decision_date=TODAY,
        )


def test_a_statement_already_in_the_reference_currency_has_nothing_to_distort(
    db_session: Session,
) -> None:
    """A US filer reporting in dollars needs no annotation, and answering `UNKNOWN` because
    there is no USD/USD rate would be a false alarm on every American company in the set."""
    result = devaluation_between(
        db_session,
        presentation="USD",
        earlier_period_end=FY2023,
        later_period_end=FY2024,
        decision_date=TODAY,
    )
    assert result.status == NOT_DISTORTED
    assert result.nominal_inflation == Decimal(0)
    assert "reference currency" in result.reason


def test_a_rate_published_after_the_decision_date_is_not_used(
    db_session: Session, floated: None
) -> None:
    """Point-in-time, same as everywhere else.

    Standing in early 2024 the FY2024 rate is not knowable, so the answer is `UNKNOWN` -
    not the FY2024 figure borrowed from the future, which is how a backtest learns to
    predict a devaluation it was told about in advance.
    """
    result = devaluation_between(
        db_session,
        presentation="NGN",
        earlier_period_end=FY2023,
        later_period_end=FY2024,
        decision_date=dt.date(2024, 1, 15),
    )
    assert result.status == UNKNOWN

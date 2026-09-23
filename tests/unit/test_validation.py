"""P4.3's arithmetic identities, and the impossible states they refuse to let pass.

`docs/03` P4.3 calls this *"what makes the LLM's output trustworthy, and the part that
separates a working pipeline from a plausible one"*.

Two kinds of check live here and they answer different questions.

**Do the figures agree?** Assets against liabilities plus equity, profit against itself
across two statements, this year against last. A disagreement can have an innocent
explanation - a chart key that means something narrower than the identity assumes - so these
report the arithmetic and route to a human rather than pronouncing on blame.

**Is the figure possible at all?** A component larger than the total containing it, a going
concern with no assets, a negative cash balance. These have no innocent explanation. They
are the ones worth writing more of, because an impossible figure that nobody flags is
indistinguishable from a real one for as long as nobody happens to look.

The anchor case is real and is the first test below. Our FY2008 balance sheet for Bank of
America stored `total_assets = 0` beside $1.64tn of liabilities, and it had been sitting
there unremarked. It is not an extraction error: BAC's own FY2010 10-K tags `Assets` as `0`
for that instant, while its FY2009 filings report $1,817,943,000,000 - exactly liabilities
plus equity. The filer published a zero, the newest-vintage rule imported it over the correct
earlier figure, and nothing in the pipeline noticed. Two separate checks catch it.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Iterator
from decimal import Decimal

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from packages.common.models import (
    Company,
    DataSource,
    Exchange,
    Security,
    SourceDocument,
    Statement,
    StatementLineItem,
)
from packages.normalize.validation import (
    BALANCE_SHEET_BALANCES,
    CROSS_YEAR_SWING,
    FAILED,
    NOT_CHECKABLE,
    PASSED,
    PROFIT_TIES,
    validate_period,
)

pytestmark = pytest.mark.invariant

FY2008 = dt.date(2008, 12, 31)
FY2024 = dt.date(2024, 12, 31)
FY2025 = dt.date(2025, 12, 31)

#: Bank of America's 2008 balance sheet, as its FY2009 filings report it.
BAC_ASSETS = Decimal("1817943000000")
BAC_LIABILITIES = Decimal("1640891000000")
BAC_EQUITY = Decimal("177052000000")


@pytest.fixture
def company(db_session: Session) -> Iterator[int]:
    """One company and security to hang statements off."""
    exchange_id = db_session.execute(select(Exchange.id).order_by(Exchange.id)).scalars().first()
    row = Company(
        legal_name="zz-test-validation Plc",
        country="NG",
        statement_template="non_financial",
        fiscal_year_end=12,
    )
    db_session.add(row)
    db_session.flush()
    db_session.add(Security(company_id=row.id, exchange_id=exchange_id, currency="NGN"))
    db_session.flush()
    yield row.id


@pytest.fixture
def document(db_session: Session) -> int:
    source_id = db_session.execute(select(DataSource.id).order_by(DataSource.id)).scalars().first()
    row = SourceDocument(
        data_source_id=source_id,
        url="file:///validation.json",
        storage_key="documents/sha256/" + "f" * 64,
        sha256="f" * 64,
        media_type="application/json",
        retrieved_at=dt.datetime(2026, 9, 1, tzinfo=dt.UTC),
    )
    db_session.add(row)
    db_session.flush()
    return row.id


def write_statement(
    session: Session,
    *,
    company_id: int,
    document_id: int,
    statement_type: str,
    period_end: dt.date,
    figures: dict[str, Decimal | None],
    fiscal_year: int | None = None,
) -> int:
    """One statement and its figures, written straight in.

    Deliberately not through `enter_statement`: this module must be able to validate figures
    however they arrived, including ones no entry path would have accepted. A validator that
    can only see well-formed data is not a validator.
    """
    security_id = session.execute(
        select(Security.id).where(Security.company_id == company_id)
    ).scalar_one()
    statement = Statement(
        company_id=company_id,
        statement_type=statement_type,
        period_type="FY",
        period_end=period_end,
        fiscal_year=fiscal_year if fiscal_year is not None else period_end.year,
        calendar_year=period_end.year,
        period_label=f"FY{period_end.year}",
        presentation_currency="NGN",
        presentation_multiplier=1,
        is_audited=True,
        is_consolidated=True,
        statement_template="non_financial",
        chart_version="v1",
        version=1,
        known_as_of=period_end + dt.timedelta(days=120),
        source_document_id=document_id,
    )
    session.add(statement)
    session.flush()
    for key, value in figures.items():
        session.add(
            StatementLineItem(
                statement_id=statement.id,
                security_id=security_id,
                canonical_key=key,
                chart_version="v1",
                value=value,
                currency="NGN",
                unit_multiplier=1,
                period_end=period_end,
                known_as_of=period_end + dt.timedelta(days=120),
                version=1,
                correction_type="none",
                source_document_id=document_id,
                page=1,
                extraction_method="manual",
            )
        )
    session.flush()
    return statement.id


def outcome_of(report, name: str) -> str:
    return next(r.outcome for r in report.results if r.name == name)


def detail_of(report, name: str) -> str:
    return next(r.detail for r in report.results if r.name == name)


# --------------------------------------------------------------------------------------
# The Bank of America case: a figure that cannot be true
# --------------------------------------------------------------------------------------


def test_a_going_concern_reporting_no_assets_is_caught_twice(
    db_session: Session, company: int, document: int
) -> None:
    """The real defect this module found on its first run over stored data.

    BAC's FY2010 10-K tags `Assets` as 0 for 2008-12-31; the FY2009 filings say
    $1,817,943,000,000, which is exactly liabilities plus equity. Two checks catch it
    independently, which matters: the balance identity needs all three figures, and the
    positivity check needs only one. A statement missing its equity line would slip the
    first and still be caught by the second.
    """
    write_statement(
        db_session,
        company_id=company,
        document_id=document,
        statement_type="balance",
        period_end=FY2008,
        figures={
            "total_assets": Decimal(0),
            "total_liabilities": BAC_LIABILITIES,
            "total_equity": BAC_EQUITY,
        },
    )
    report = validate_period(db_session, company_id=company, period_type="FY", period_end=FY2008)
    assert outcome_of(report, BALANCE_SHEET_BALANCES) == FAILED
    assert outcome_of(report, "total_assets_is_positive") == FAILED
    assert report.needs_review
    assert "1,817,943,000,000" in detail_of(report, BALANCE_SHEET_BALANCES), (
        "the detail states the figure the identity expected, which is the one BAC filed in 2009"
    )


def test_the_correct_bank_of_america_figures_pass(
    db_session: Session, company: int, document: int
) -> None:
    """The same three lines, with the assets figure the FY2009 filings report. Exact."""
    write_statement(
        db_session,
        company_id=company,
        document_id=document,
        statement_type="balance",
        period_end=FY2008,
        figures={
            "total_assets": BAC_ASSETS,
            "total_liabilities": BAC_LIABILITIES,
            "total_equity": BAC_EQUITY,
        },
    )
    report = validate_period(db_session, company_id=company, period_type="FY", period_end=FY2008)
    assert outcome_of(report, BALANCE_SHEET_BALANCES) == PASSED
    assert BAC_LIABILITIES + BAC_EQUITY == BAC_ASSETS, "the identity holds to the naira"
    assert not report.needs_review


# --------------------------------------------------------------------------------------
# States that cannot be true
# --------------------------------------------------------------------------------------


def test_a_component_larger_than_its_total_is_refused(
    db_session: Session, company: int, document: int
) -> None:
    """Current assets cannot exceed total assets. There is no innocent reading of this.

    It is the shape a mis-scaled figure takes: read one line in thousands and its neighbour
    in millions, and the part overtakes the whole.
    """
    write_statement(
        db_session,
        company_id=company,
        document_id=document,
        statement_type="balance",
        period_end=FY2025,
        figures={
            "total_assets": Decimal("5000000000"),
            "current_assets": Decimal("9000000000"),  # 1,000x mis-scale on one line
            "total_liabilities": Decimal("3000000000"),
            "total_equity": Decimal("2000000000"),
        },
    )
    report = validate_period(db_session, company_id=company, period_type="FY", period_end=FY2025)
    assert outcome_of(report, "current_assets_within_total_assets") == FAILED
    assert "cannot exceed its whole" in detail_of(report, "current_assets_within_total_assets")
    assert outcome_of(report, BALANCE_SHEET_BALANCES) == PASSED, (
        "the totals still tie - which is why the subset rule has to exist separately"
    )


def test_a_component_equal_to_its_total_is_allowed(
    db_session: Session, company: int, document: int
) -> None:
    """A company may hold every asset as cash. The rule is one-directional, not equality."""
    write_statement(
        db_session,
        company_id=company,
        document_id=document,
        statement_type="balance",
        period_end=FY2025,
        figures={"total_assets": Decimal("100000000"), "cash": Decimal("100000000")},
    )
    report = validate_period(db_session, company_id=company, period_type="FY", period_end=FY2025)
    assert outcome_of(report, "cash_within_total_assets") == PASSED


def test_a_negative_cash_balance_is_refused(
    db_session: Session, company: int, document: int
) -> None:
    """An overdraft is a liability, not negative cash. A minus here is a sign error."""
    write_statement(
        db_session,
        company_id=company,
        document_id=document,
        statement_type="balance",
        period_end=FY2025,
        figures={"total_assets": Decimal("100000000"), "cash": Decimal("-5000000")},
    )
    report = validate_period(db_session, company_id=company, period_type="FY", period_end=FY2025)
    assert outcome_of(report, "cash_not_negative") == FAILED


def test_gross_profit_must_be_revenue_less_cost_of_sales(
    db_session: Session, company: int, document: int
) -> None:
    """Defined arithmetic, so the test is exact rather than a tolerance on a total."""
    write_statement(
        db_session,
        company_id=company,
        document_id=document,
        statement_type="income",
        period_end=FY2025,
        figures={
            "revenue": Decimal("1000000000"),
            "cost_of_revenue": Decimal("600000000"),
            "gross_profit": Decimal("500000000"),  # should be 400,000,000
        },
    )
    report = validate_period(db_session, company_id=company, period_type="FY", period_end=FY2025)
    assert outcome_of(report, "revenue_less_cost_of_revenue_is_gross_profit") == FAILED
    assert "400,000,000" in detail_of(report, "revenue_less_cost_of_revenue_is_gross_profit")


def test_profit_after_tax_must_be_profit_before_tax_less_tax(
    db_session: Session, company: int, document: int
) -> None:
    write_statement(
        db_session,
        company_id=company,
        document_id=document,
        statement_type="income",
        period_end=FY2025,
        figures={
            "profit_before_tax": Decimal("500000000"),
            "income_tax": Decimal("150000000"),
            "profit_after_tax": Decimal("350000000"),
        },
    )
    report = validate_period(db_session, company_id=company, period_type="FY", period_end=FY2025)
    assert outcome_of(report, "profit_before_tax_less_income_tax_is_profit_after_tax") == PASSED


# --------------------------------------------------------------------------------------
# The unit error, which is what the cross-year check is for
# --------------------------------------------------------------------------------------


def test_a_thousandfold_error_is_caught_against_last_year(
    db_session: Session, company: int, document: int
) -> None:
    """P4.3 calls this *"the quiet hero"*, and the reason is that the figure looks fine alone.

    3,360,000,000 is a perfectly plausible revenue. It is only implausible beside last
    year's 3,400,000 - which is the whole argument for checking across years rather than
    staring harder at one.
    """
    for period_end, revenue in (
        (FY2024, Decimal("3400000")),
        (FY2025, Decimal("3360000000")),  # read in units, stored as though thousands
    ):
        write_statement(
            db_session,
            company_id=company,
            document_id=document,
            statement_type="income",
            period_end=period_end,
            figures={"revenue": revenue},
        )
    report = validate_period(db_session, company_id=company, period_type="FY", period_end=FY2025)
    assert outcome_of(report, CROSS_YEAR_SWING) == FAILED
    assert "revenue" in detail_of(report, CROSS_YEAR_SWING)


def test_a_swing_into_loss_is_not_a_magnitude_error(
    db_session: Session, company: int, document: int
) -> None:
    """A sign change is a business event. Flagging it is how a check gets switched off.

    This is a real false positive the first version produced: a company whose profit ran
    +33.4bn to -2.7bn and back was reported as two magnitude errors. It had a bad year.
    """
    for period_end, assets in ((FY2024, Decimal("100000000")), (FY2025, Decimal("110000000"))):
        write_statement(
            db_session,
            company_id=company,
            document_id=document,
            statement_type="balance",
            period_end=period_end,
            figures={"total_assets": assets},
        )
    for period_end, profit in (
        (FY2024, Decimal("33364000000")),
        (FY2025, Decimal("-2722000000")),
    ):
        write_statement(
            db_session,
            company_id=company,
            document_id=document,
            statement_type="income",
            period_end=period_end,
            figures={"profit_after_tax": profit},
        )
    report = validate_period(db_session, company_id=company, period_type="FY", period_end=FY2025)
    assert outcome_of(report, CROSS_YEAR_SWING) == PASSED, (
        "profit is excluded from the swing keys, and a sign change would not count anyway"
    )


# --------------------------------------------------------------------------------------
# Three outcomes, and what a pass rate may be built on
# --------------------------------------------------------------------------------------


def test_an_identity_with_missing_inputs_is_not_a_pass(
    db_session: Session, company: int, document: int
) -> None:
    """The distinction the whole report rests on: untested is not the same as passed.

    Of 6,628 stored balance sheets only 940 carry all three figures. A validator that scored
    the rest as passing would report a 94% pass rate on checks it never ran.
    """
    write_statement(
        db_session,
        company_id=company,
        document_id=document,
        statement_type="balance",
        period_end=FY2025,
        figures={"total_assets": Decimal("100000000")},  # no liabilities, no equity
    )
    report = validate_period(db_session, company_id=company, period_type="FY", period_end=FY2025)
    assert outcome_of(report, BALANCE_SHEET_BALANCES) == NOT_CHECKABLE
    assert "missing total_liabilities, total_equity" in detail_of(report, BALANCE_SHEET_BALANCES)
    assert all(r.outcome != FAILED for r in report.results), "nothing failed; things were absent"
    assert not report.needs_review


def test_a_period_with_nothing_checkable_has_no_pass_rate(
    db_session: Session, company: int
) -> None:
    """None, not 1.0. A confidence score built on an empty check set is a fabricated one."""
    report = validate_period(
        db_session, company_id=company, period_type="FY", period_end=dt.date(2019, 12, 31)
    )
    assert report.checked == []
    assert report.pass_rate is None
    assert not report.needs_review


def test_the_pass_rate_counts_only_what_was_checked(
    db_session: Session, company: int, document: int
) -> None:
    write_statement(
        db_session,
        company_id=company,
        document_id=document,
        statement_type="balance",
        period_end=FY2025,
        figures={
            "total_assets": Decimal("1000"),
            "total_liabilities": Decimal("600"),
            "total_equity": Decimal("400"),
        },
    )
    report = validate_period(db_session, company_id=company, period_type="FY", period_end=FY2025)
    checked = report.checked
    assert checked, "at least the balance identity ran"
    assert report.pass_rate == Decimal(sum(1 for r in checked if r.outcome == PASSED)) / Decimal(
        len(checked)
    )
    assert all(r.outcome != NOT_CHECKABLE for r in checked)


# --------------------------------------------------------------------------------------
# Tolerance: rounding yes, a misread digit no
# --------------------------------------------------------------------------------------


def test_rounding_in_the_printed_statement_is_tolerated(
    db_session: Session, company: int, document: int
) -> None:
    """A balance sheet in millions rounds each line on its own, so a total can miss by units."""
    write_statement(
        db_session,
        company_id=company,
        document_id=document,
        statement_type="balance",
        period_end=FY2025,
        figures={
            "total_assets": Decimal("1000000000"),
            "total_liabilities": Decimal("600000000"),
            "total_equity": Decimal("400000001"),  # one naira out
        },
    )
    report = validate_period(db_session, company_id=company, period_type="FY", period_end=FY2025)
    assert outcome_of(report, BALANCE_SHEET_BALANCES) == PASSED


def test_a_misread_digit_is_not_tolerated(db_session: Session, company: int, document: int) -> None:
    """0.1% is wide enough for rounding and far too narrow for a wrong digit."""
    write_statement(
        db_session,
        company_id=company,
        document_id=document,
        statement_type="balance",
        period_end=FY2025,
        figures={
            "total_assets": Decimal("1000000000"),
            "total_liabilities": Decimal("600000000"),
            "total_equity": Decimal("500000000"),  # 4 read as 5
        },
    )
    report = validate_period(db_session, company_id=company, period_type="FY", period_end=FY2025)
    assert outcome_of(report, BALANCE_SHEET_BALANCES) == FAILED


# --------------------------------------------------------------------------------------
# One figure, two statements
# --------------------------------------------------------------------------------------


def test_profit_must_agree_between_the_income_statement_and_the_cash_flow(
    db_session: Session, company: int, document: int
) -> None:
    """`profit_after_tax` is a `both`-template key, so it can be reported twice for a period.

    Two different numbers for one period's profit is obvious once stated and invisible in a
    table, which is exactly the kind of thing a machine should be doing.
    """
    write_statement(
        db_session,
        company_id=company,
        document_id=document,
        statement_type="income",
        period_end=FY2025,
        figures={"profit_after_tax": Decimal("420000000")},
    )
    write_statement(
        db_session,
        company_id=company,
        document_id=document,
        statement_type="cashflow",
        period_end=FY2025,
        figures={"profit_after_tax": Decimal("420900000")},
    )
    report = validate_period(db_session, company_id=company, period_type="FY", period_end=FY2025)
    assert outcome_of(report, PROFIT_TIES) == FAILED
    assert "420,000,000" in detail_of(report, PROFIT_TIES)


def test_profit_reported_once_cannot_be_cross_checked(
    db_session: Session, company: int, document: int
) -> None:
    write_statement(
        db_session,
        company_id=company,
        document_id=document,
        statement_type="income",
        period_end=FY2025,
        figures={"profit_after_tax": Decimal("420000000")},
    )
    report = validate_period(db_session, company_id=company, period_type="FY", period_end=FY2025)
    assert outcome_of(report, PROFIT_TIES) == NOT_CHECKABLE
    assert "two statements are needed" in detail_of(report, PROFIT_TIES)


# --------------------------------------------------------------------------------------
# Finding last year, which is not "this date minus one year"
# --------------------------------------------------------------------------------------


def test_a_leap_day_period_end_does_not_crash_the_check(
    db_session: Session, company: int, document: int
) -> None:
    """29 February minus a year is not a date, and four such period ends are stored.

    `dt.date(2024 - 1, 2, 29)` raises. The whole report died on it, which the review queue
    found by sweeping every period in the database - the kind of input nobody writes a
    fixture for because nobody thinks of it.
    """
    for period_end, fiscal_year in ((dt.date(2023, 2, 28), 2023), (dt.date(2024, 2, 29), 2024)):
        write_statement(
            db_session,
            company_id=company,
            document_id=document,
            statement_type="income",
            period_end=period_end,
            figures={"revenue": Decimal("1000000000")},
            fiscal_year=fiscal_year,
        )
    db_session.flush()

    report = validate_period(
        db_session, company_id=company, period_type="FY", period_end=dt.date(2024, 2, 29)
    )
    assert outcome_of(report, CROSS_YEAR_SWING) == PASSED, (
        "the leap year compares against the ordinary one before it"
    )


def test_a_fifty_two_week_filer_is_compared_against_its_own_prior_year(
    db_session: Session, company: int, document: int
) -> None:
    """Apple's fiscal years end 2025-09-27 and 2024-09-28. Neither is the other minus a year.

    This is the quiet half of the same defect. Date arithmetic lands on a day with no
    statement, so the check reported "nothing to compare against" and passed on - not
    wrong, exactly, but silent about four years of comparable figures sitting beside it.
    """
    for period_end, fiscal_year, revenue in (
        (dt.date(2024, 9, 28), 2024, Decimal("391035000000")),
        (dt.date(2025, 9, 27), 2025, Decimal("416161000000")),
    ):
        write_statement(
            db_session,
            company_id=company,
            document_id=document,
            statement_type="income",
            period_end=period_end,
            figures={"revenue": revenue},
            fiscal_year=fiscal_year,
        )
    db_session.flush()

    report = validate_period(
        db_session, company_id=company, period_type="FY", period_end=dt.date(2025, 9, 27)
    )
    assert outcome_of(report, CROSS_YEAR_SWING) == PASSED
    assert "2024-09-28" in detail_of(report, CROSS_YEAR_SWING), (
        "it found the prior fiscal year, not a date that does not exist"
    )


def test_a_unit_error_is_still_caught_across_a_fifty_two_week_boundary(
    db_session: Session, company: int, document: int
) -> None:
    """The fix must not cost the check its teeth on the filers it just started seeing."""
    for period_end, fiscal_year, revenue in (
        (dt.date(2024, 9, 28), 2024, Decimal("391035000000")),
        (dt.date(2025, 9, 27), 2025, Decimal("416161000")),  # read in thousands by mistake
    ):
        write_statement(
            db_session,
            company_id=company,
            document_id=document,
            statement_type="income",
            period_end=period_end,
            figures={"revenue": revenue},
            fiscal_year=fiscal_year,
        )
    db_session.flush()

    report = validate_period(
        db_session, company_id=company, period_type="FY", period_end=dt.date(2025, 9, 27)
    )
    assert outcome_of(report, CROSS_YEAR_SWING) == FAILED
    assert "revenue" in detail_of(report, CROSS_YEAR_SWING)

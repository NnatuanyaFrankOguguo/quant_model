"""Checking figures before they are stored. `docs/03` P4.1, P4.3.

P4.1's flowchart puts validation ahead of the store:

    Claude maps to canonical keys --> Deterministic validation
      passes, confidence >= 0.85  --> Store with provenance
      fails or low confidence     --> Human review queue

`validate_period` could not do that - it begins by reading `statement_line_items`, so the
only figures it could check were ones already written. An extraction that has to be stored
before anybody can find out it is wrong is in the database by the time they do.

Most of what follows needs no rows at all. The session is required for exactly one
identity, the cross-year swing, which compares a candidate against last year's *stored*
closing balances - real history, not the candidate checking itself.
"""

from __future__ import annotations

import datetime as dt
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
    FAILED,
    NOT_CHECKABLE,
    PASSED,
    validate_candidate,
)

pytestmark = pytest.mark.invariant

PERIOD_END = dt.date(2024, 12, 31)
PRIOR_END = dt.date(2023, 12, 31)


def outcome(report, name: str) -> str:
    """The outcome of one identity by name, so a test names what it is asserting about."""
    for result in report.results:
        if result.name == name:
            return result.outcome
    raise AssertionError(f"no identity called {name!r}; got {[r.name for r in report.results]}")


def check(
    session: Session,
    figures: dict[tuple[str, str], Decimal | None],
    *,
    company_id: int = 0,
    fiscal_year: int | None = 2024,
):
    """The candidate's own year label is passed, because a candidate has no stored row to
    read it off - see `test_omitting_the_fiscal_year_silently_disables_the_cross_year_check`."""
    return validate_candidate(
        session,
        company_id=company_id,
        period_type="FY",
        period_end=PERIOD_END,
        figures=figures,
        fiscal_year=fiscal_year,
    )


# --------------------------------------------------------------------------------------
# The identities, on figures nobody has stored
# --------------------------------------------------------------------------------------


def test_a_balance_sheet_that_does_not_balance_is_caught_before_it_is_written(
    db_session: Session,
) -> None:
    """The whole point of the new entry point, in one assertion.

    These figures are in nobody's database. Under `validate_period` they could not have
    been checked until they were, and by then the wrong numbers are what the API serves.
    """
    report = check(
        db_session,
        {
            ("balance", "total_assets"): Decimal("1000"),
            ("balance", "total_liabilities"): Decimal("600"),
            ("balance", "total_equity"): Decimal("300"),  # 900, not 1000
        },
    )
    assert outcome(report, "balance_sheet_balances") == FAILED
    assert report.needs_review


def test_a_balanced_candidate_passes(db_session: Session) -> None:
    report = check(
        db_session,
        {
            ("balance", "total_assets"): Decimal("1000"),
            ("balance", "total_liabilities"): Decimal("600"),
            ("balance", "total_equity"): Decimal("400"),
        },
    )
    assert outcome(report, "balance_sheet_balances") == PASSED


def test_a_figure_the_statement_never_reported_is_not_checkable_rather_than_failed(
    db_session: Session,
) -> None:
    """Absent is not zero, at the stage where the distinction is cheapest to keep.

    An identity that cannot find a figure must take no view. Reading a missing key as zero
    would fail the balance sheet of every company that reports equity somewhere this
    mapping does not look, and the extractor would be blamed for the chart's gap.
    """
    report = check(db_session, {("balance", "total_assets"): Decimal("1000")})
    assert outcome(report, "balance_sheet_balances") == NOT_CHECKABLE
    assert report.pass_rate is None or outcome(report, "balance_sheet_balances") == NOT_CHECKABLE


def test_an_impossible_value_is_caught_on_a_candidate(db_session: Session) -> None:
    """Negative total assets is not a low-confidence reading; it is not a thing."""
    report = check(db_session, {("balance", "total_assets"): Decimal("-5000")})
    assert outcome(report, "total_assets_is_positive") == FAILED


def test_a_composition_identity_is_caught_on_a_candidate(db_session: Session) -> None:
    """Revenue less cost of revenue is gross profit, whoever has or has not stored it."""
    report = check(
        db_session,
        {
            ("income", "revenue"): Decimal("1000"),
            ("income", "cost_of_revenue"): Decimal("-600"),
            ("income", "gross_profit"): Decimal("300"),  # should be 400
        },
    )
    assert outcome(report, "revenue_less_cost_of_revenue_is_gross_profit") == FAILED


# --------------------------------------------------------------------------------------
# The one identity that still needs the database
# --------------------------------------------------------------------------------------


@pytest.fixture
def company_with_last_year(db_session: Session) -> int:
    """A company whose FY2023 balance sheet is stored, so FY2024 has something to tie to."""
    exchange_id = db_session.execute(select(Exchange.id).order_by(Exchange.id)).scalars().first()
    source_id = db_session.execute(select(DataSource.id).order_by(DataSource.id)).scalars().first()
    document = SourceDocument(
        data_source_id=source_id,
        url="file:///candidate-prior.json",
        storage_key="documents/sha256/" + "9" * 64,
        sha256="9" * 64,
        media_type="application/json",
        retrieved_at=dt.datetime(2024, 3, 1, tzinfo=dt.UTC),
    )
    db_session.add(document)
    company = Company(
        legal_name="zz-test-candidate Plc",
        country="NG",
        statement_template="non_financial",
        fiscal_year_end=12,
    )
    db_session.add(company)
    db_session.flush()
    security = Security(company_id=company.id, exchange_id=exchange_id, currency="NGN")
    db_session.add(security)
    db_session.flush()
    statement = Statement(
        company_id=company.id,
        statement_type="balance",
        period_type="FY",
        period_end=PRIOR_END,
        fiscal_year=2023,
        calendar_year=2023,
        period_label="FY2023",
        presentation_currency="NGN",
        presentation_multiplier=1,
        is_audited=True,
        is_consolidated=True,
        statement_template="non_financial",
        chart_version="v1",
        version=1,
        known_as_of=dt.date(2024, 4, 30),
        source_document_id=document.id,
    )
    db_session.add(statement)
    db_session.flush()
    db_session.add(
        StatementLineItem(
            statement_id=statement.id,
            security_id=security.id,
            canonical_key="total_assets",
            chart_version="v1",
            value=Decimal("1000000"),
            currency="NGN",
            unit_multiplier=1,
            period_end=PRIOR_END,
            known_as_of=dt.date(2024, 4, 30),
            version=1,
            correction_type="none",
            source_document_id=document.id,
            page=1,
            extraction_method="manual",
        )
    )
    db_session.flush()
    return company.id


def test_the_cross_year_check_still_reads_real_history(
    db_session: Session, company_with_last_year: int
) -> None:
    """A candidate is compared against last year's *stored* figures, not against itself.

    This is the identity that cannot be made session-free, and the reason the function
    still takes one. `docs/03` P4.3 calls it *"the quiet hero here, because a figure that
    is 1,000× wrong will not tie to last year's closing balance"* - so a candidate carrying
    an unapplied `unit_multiplier` is caught here and nowhere else.
    """
    report = check(
        db_session,
        {("balance", "total_assets"): Decimal("1000000000")},  # 1,000x last year
        company_id=company_with_last_year,
    )
    assert outcome(report, "cross_year_swing") == FAILED


def test_a_plausible_year_on_year_change_ties(
    db_session: Session, company_with_last_year: int
) -> None:
    """Growth is not an error. A check that flagged it would be muted within a week."""
    report = check(
        db_session,
        {("balance", "total_assets"): Decimal("1150000")},  # +15%
        company_id=company_with_last_year,
    )
    assert outcome(report, "cross_year_swing") == PASSED


def test_a_company_with_no_prior_year_is_not_checkable_rather_than_failed(
    db_session: Session,
) -> None:
    """A first extraction has nothing to tie to, and that is not a finding about it."""
    report = check(db_session, {("balance", "total_assets"): Decimal("1000")}, company_id=0)
    assert outcome(report, "cross_year_swing") == NOT_CHECKABLE


def test_omitting_the_fiscal_year_silently_disables_the_cross_year_check(
    db_session: Session, company_with_last_year: int
) -> None:
    """The hole this parameter exists to close, asserted so it cannot reopen.

    `_prior_period_end` finds last year by reading *this* year's
    `statements.fiscal_year` - and a candidate has no such row. Without the label the
    lookup returns nothing and the check reports `NOT_CHECKABLE`: not an error, not a
    warning, just the one identity that catches a 1,000x unit error quietly not running.

    Safe, and quiet in exactly the wrong way. The same figures with the label are caught by
    the test above; here, without it, they are not.
    """
    report = check(
        db_session,
        {("balance", "total_assets"): Decimal("1000000000")},  # 1,000x last year
        company_id=company_with_last_year,
        fiscal_year=None,
    )
    assert outcome(report, "cross_year_swing") == NOT_CHECKABLE

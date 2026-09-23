"""P4.4's review queue: what a reviewer sees first, and whose mistakes get counted.

`docs/03` P4.4: *"Prioritise the queue by materiality. A wrong revenue figure matters more
than a wrong note disclosure. A FIFO queue wastes your scarcest resource - reviewer
attention - on trivia."* And: *"Track correction rate as a headline metric … if it isn't
falling, the extractor isn't learning."*

`TEAM_BRIEF` Part 3 item 5 is why both matter: ~20 corrections per filing across 25
companies filing quarterly is about **2,000 corrections a year**, against one reviewer.
Ordering the queue is the only lever on that ceiling short of hiring.

Two things are worth testing hardest.

**The ordering has to be defensible**, because a reviewer who disagrees with it will stop
trusting it. So the priority decomposes into three legible terms and each is tested on its
own: severity, share of the statement, and whether the chart calls the key required.

**The correction rate has to count the right mistakes.** Every one of the 2,285 corrections
in the database is a `restatement` - the company restating its own figures. A metric that
counted those would report a 4.4% error rate for an extractor that has made no errors at
all, and would go on reporting it however well the extractor learned.
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
from packages.normalize.review import (
    REQUIRED_BONUS,
    SEVERITY_DISAGREEMENT,
    SEVERITY_FLAGGED,
    SEVERITY_IMPOSSIBLE,
    correction_rate,
    review_queue,
)

pytestmark = pytest.mark.invariant

FY2025 = dt.date(2025, 12, 31)
KNOWN = FY2025 + dt.timedelta(days=120)


@pytest.fixture
def company(db_session: Session) -> Iterator[int]:
    exchange_id = db_session.execute(select(Exchange.id).order_by(Exchange.id)).scalars().first()
    row = Company(
        legal_name="zz-test-review Plc",
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
        url="file:///review.json",
        storage_key="documents/sha256/" + "e" * 64,
        sha256="e" * 64,
        media_type="application/json",
        retrieved_at=dt.datetime(2026, 9, 1, tzinfo=dt.UTC),
    )
    db_session.add(row)
    db_session.flush()
    return row.id


def write(
    session: Session,
    *,
    company_id: int,
    document_id: int,
    statement_type: str,
    figures: dict[str, Decimal],
    period_end: dt.date = FY2025,
    flag_keys: tuple[str, ...] = (),
) -> None:
    security_id = session.execute(
        select(Security.id).where(Security.company_id == company_id)
    ).scalar_one()
    statement = Statement(
        company_id=company_id,
        statement_type=statement_type,
        period_type="FY",
        period_end=period_end,
        fiscal_year=period_end.year,
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
                needs_review=key in flag_keys,
            )
        )
    session.flush()


def queue_for(session: Session, company_id: int):
    return review_queue(session, limit=50, company_id=company_id)


# --------------------------------------------------------------------------------------
# The ordering, term by term
# --------------------------------------------------------------------------------------


def test_an_impossible_state_outranks_a_disagreement(
    db_session: Session, company: int, document: int
) -> None:
    """A part exceeding its whole has no innocent reading; a total that misses might.

    The balance identity can fail because `total_equity` maps to a parent-only figure and
    the company has minority interests - a mapping question, not a wrong number. Cash larger
    than total assets cannot be anything but wrong.
    """
    write(
        db_session,
        company_id=company,
        document_id=document,
        statement_type="balance",
        figures={
            "total_assets": Decimal("1000000000"),
            "cash": Decimal("1500000000"),  # impossible
            "total_liabilities": Decimal("600000000"),
            "total_equity": Decimal("500000000"),  # disagrees by 10%
        },
    )
    queue = queue_for(db_session, company)
    findings = [item.finding for item in queue]
    impossible = findings.index("cash_within_total_assets")
    disagreement = findings.index("balance_sheet_balances")
    assert impossible < disagreement, "the impossible state is seen first"
    assert queue[impossible].severity == SEVERITY_IMPOSSIBLE
    assert queue[disagreement].severity == SEVERITY_DISAGREEMENT


def test_materiality_is_a_share_of_the_statement_not_an_absolute(
    db_session: Session, company: int, document: int
) -> None:
    """NGN 50m is trivial to Dangote and fatal to a small insurer, so the score is relative.

    Two impossible states of the same kind, one on a line worth most of the balance sheet
    and one on a rounding error. Same severity; the share decides.
    """
    write(
        db_session,
        company_id=company,
        document_id=document,
        statement_type="balance",
        figures={
            "total_assets": Decimal("1000000000"),
            "cash": Decimal("-900000000"),  # negative, and nearly the whole statement
            "current_assets": Decimal("-1000"),  # negative, and immaterial
        },
    )
    queue = [
        item for item in queue_for(db_session, company) if item.finding.endswith("not_negative")
    ]
    assert len(queue) == 2
    big, small = queue[0], queue[1]
    assert big.canonical_key == "cash"
    assert small.canonical_key == "current_assets"
    assert big.share_of_anchor > small.share_of_anchor
    assert big.priority > small.priority


def test_a_required_key_is_lifted_above_an_optional_one(
    db_session: Session, company: int, document: int
) -> None:
    """The chart already knows which lines a statement cannot be complete without."""
    write(
        db_session,
        company_id=company,
        document_id=document,
        statement_type="balance",
        figures={"total_assets": Decimal(0), "total_liabilities": Decimal("500000000")},
    )
    queue = queue_for(db_session, company)
    assets = next(i for i in queue if i.finding == "total_assets_is_positive")
    assert assets.is_required, "total_assets is required in chart v1"
    assert assets.priority == SEVERITY_IMPOSSIBLE + assets.share_of_anchor + REQUIRED_BONUS


def test_the_priority_decomposes_into_terms_a_reviewer_can_read(
    db_session: Session, company: int, document: int
) -> None:
    """A ranking nobody can explain is a ranking nobody trusts."""
    write(
        db_session,
        company_id=company,
        document_id=document,
        statement_type="balance",
        figures={"total_assets": Decimal("1000000"), "cash": Decimal("2000000")},
    )
    item = next(
        i for i in queue_for(db_session, company) if i.finding == "cash_within_total_assets"
    )
    assert item.priority == item.severity + item.share_of_anchor + (
        REQUIRED_BONUS if item.is_required else Decimal(0)
    )
    assert "severity" in item.why
    assert "of the statement" in item.why


# --------------------------------------------------------------------------------------
# What reaches the queue at all
# --------------------------------------------------------------------------------------


def test_a_clean_period_puts_nothing_in_the_queue(
    db_session: Session, company: int, document: int
) -> None:
    """The queue is work outstanding, not a log of everything checked."""
    write(
        db_session,
        company_id=company,
        document_id=document,
        statement_type="balance",
        figures={
            "total_assets": Decimal("1000000000"),
            "total_liabilities": Decimal("600000000"),
            "total_equity": Decimal("400000000"),
        },
    )
    assert queue_for(db_session, company) == []


def test_an_extractor_flag_reaches_the_queue_below_the_arithmetic(
    db_session: Session, company: int, document: int
) -> None:
    """*"I am unsure"* is weaker evidence than *"this cannot be"*, and ranks that way.

    Nothing in the database carries `needs_review` today - XBRL arrives confident - so this
    path is written and tested before the extractor that will fill it, rather than after.
    """
    write(
        db_session,
        company_id=company,
        document_id=document,
        statement_type="balance",
        figures={"total_assets": Decimal("1000000000"), "cash": Decimal("1500000000")},
        flag_keys=("cash",),
    )
    queue = queue_for(db_session, company)
    flagged = next(i for i in queue if i.finding == "needs_review")
    impossible = next(i for i in queue if i.finding == "cash_within_total_assets")
    assert flagged.severity == SEVERITY_FLAGGED
    assert impossible.priority > flagged.priority
    assert "flagged cash for review" in flagged.detail


def test_the_queue_is_ordered_worst_first_across_companies(
    db_session: Session, company: int, document: int
) -> None:
    write(
        db_session,
        company_id=company,
        document_id=document,
        statement_type="balance",
        figures={
            "total_assets": Decimal("1000000000"),
            "cash": Decimal("1500000000"),
            "current_assets": Decimal("-5"),
        },
    )
    priorities = [item.priority for item in queue_for(db_session, company)]
    assert priorities == sorted(priorities, reverse=True)


def test_the_limit_caps_the_list_and_not_the_ordering(
    db_session: Session, company: int, document: int
) -> None:
    """A queue showing the worst of an arbitrary hundred periods would look identical.

    So every period is scored and the top slice returned, and asking for one item returns
    the single worst rather than the first one found.
    """
    write(
        db_session,
        company_id=company,
        document_id=document,
        statement_type="balance",
        figures={
            "total_assets": Decimal("1000000000"),
            "cash": Decimal("1500000000"),
            "current_assets": Decimal("-5"),
        },
    )
    everything = review_queue(db_session, limit=50, company_id=company)
    just_one = review_queue(db_session, limit=1, company_id=company)
    assert len(just_one) == 1
    assert just_one[0].finding == everything[0].finding
    assert just_one[0].priority == max(item.priority for item in everything)


# --------------------------------------------------------------------------------------
# The headline metric, and whose mistakes it counts
# --------------------------------------------------------------------------------------


def test_the_correction_rate_excludes_the_companys_own_restatements(
    db_session: Session, company: int, document: int
) -> None:
    """The distinction that decides whether the metric means anything.

    All 2,285 corrections stored today are restatements. Counting them would report a 4.4%
    error rate for an extractor that has made none, and the number would never fall however
    well it learned - which is precisely the signal `docs/03` says to watch.
    """
    security_id = db_session.execute(
        select(Security.id).where(Security.company_id == company)
    ).scalar_one()
    statement = Statement(
        company_id=company,
        statement_type="income",
        period_type="FY",
        period_end=FY2025,
        fiscal_year=2025,
        calendar_year=2025,
        period_label="FY2025",
        presentation_currency="NGN",
        presentation_multiplier=1,
        is_audited=True,
        is_consolidated=True,
        statement_template="non_financial",
        chart_version="v1",
        version=1,
        known_as_of=KNOWN,
        source_document_id=document,
    )
    db_session.add(statement)
    db_session.flush()
    for key, correction in (
        ("revenue", "none"),
        ("profit_after_tax", "restatement"),  # the company's doing
        ("income_tax", "transcription"),  # ours
        ("operating_profit", "extraction"),  # ours
    ):
        db_session.add(
            StatementLineItem(
                statement_id=statement.id,
                security_id=security_id,
                canonical_key=key,
                chart_version="v1",
                value=Decimal("1000000"),
                currency="NGN",
                unit_multiplier=1,
                period_end=FY2025,
                known_as_of=KNOWN,
                version=1,
                correction_type=correction,
                source_document_id=document,
                page=1,
                extraction_method="manual",
            )
        )
    db_session.flush()

    measured = correction_rate(db_session, start=KNOWN, end=KNOWN)
    assert measured.our_corrections == 2, "transcription and extraction, not the restatement"
    assert measured.restatements == 1
    assert measured.items_written == 4
    assert measured.rate == Decimal(2) / Decimal(4)


def test_a_window_with_nothing_written_has_no_rate(db_session: Session) -> None:
    """None, not zero. A quiet month must not put a reassuring point on an alarm chart."""
    empty = correction_rate(db_session, start=dt.date(1990, 1, 1), end=dt.date(1990, 12, 31))
    assert empty.items_written == 0
    assert empty.rate is None


def test_a_backwards_window_is_refused(db_session: Session) -> None:
    with pytest.raises(ValueError, match="is after end"):
        correction_rate(db_session, start=dt.date(2026, 2, 1), end=dt.date(2026, 1, 1))

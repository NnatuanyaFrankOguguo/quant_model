"""P3.2's rules: a hand-typed statement, and the four things a cell can be.

`docs/03` P3 checks 2 and 3 are both about this path:

    | 2 | Provenance complete | `SELECT count(*) FROM statement_line_items WHERE page IS
    NULL AND extraction_method='manual'` | `0` |
    | 3 | Blank -> null | Leave a field empty | Stores `NULL`, not `0` |

Check 2 currently passes **vacuously**: all 53,710 stored line items are
`extraction_method='xbrl'`, so "no manual item lacks a page" is true because there are no
manual items. These tests are the first manual items the project has had, and they make the
check mean what it says.

Check 3 is the one that decides whether a ratio can be trusted. A debt-to-equity of 0.0
published for a company whose debt line was simply not read is worse than no figure at all,
because it looks like an answer.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Iterator
from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from packages.common.identity import CIK, resolve_security
from packages.common.models import Statement, StatementLineItem
from packages.common.storage import LocalDiskBackend
from packages.common.timez import utctoday
from packages.common.units import UnreadableFigureError
from packages.ingestion import base as ingestion_base
from packages.ingestion.base import RawResponse, register
from packages.ingestion.documents import store_uploaded_report
from packages.ingestion.edgar import EdgarSubmissionsConnector
from packages.normalize.manual import (
    EntryRefusedError,
    ManualStatement,
    TypedFigure,
    enter_statement,
)
from tests.unit.test_documents import minimal_pdf

pytestmark = pytest.mark.invariant

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"
UA = "quant_model test suite (nnatuanyafrankoguguo@churchofjesuschrist.org)"
APPLE_CIK = "0000320193"

PERIOD_END = dt.date(2025, 12, 31)
#: When the issuer published. A Nigerian annual report lands three to four months out.
PUBLISHED = dt.date(2026, 4, 30)
REVIEWER = "nnatuanyafrankoguguo"


@pytest.fixture
def local_store(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> LocalDiskBackend:
    store = LocalDiskBackend(tmp_path / "documents")
    monkeypatch.setattr(ingestion_base, "get_storage", lambda: store)
    monkeypatch.setattr("packages.ingestion.documents.get_storage", lambda: store)
    return store


@pytest.fixture
def security(db_session: Session, local_store: LocalDiskBackend) -> Iterator[int]:
    connector = EdgarSubmissionsConnector(user_agent=UA)
    register(db_session, connector)
    connector.fetch = lambda **params: RawResponse(  # type: ignore[method-assign]
        data=(FIXTURES / "edgar" / "AAPL_submissions_trimmed.json").read_bytes(),
        media_type="application/json",
        url="s",
    )
    assert connector.run(db_session, cik=APPLE_CIK).status == "ok"
    resolved = resolve_security(db_session, value=APPLE_CIK, as_of=utctoday(), id_type=CIK)
    assert resolved is not None
    yield resolved.security_id


@pytest.fixture
def report(db_session: Session, local_store: LocalDiskBackend) -> int:
    """A 60-page annual report in the store, so page citations can be checked against it."""
    return store_uploaded_report(
        db_session, minimal_pdf(60), url="https://issuer.example/fy2025.pdf"
    ).document_id


def an_entry(security_id: int, document_id: int, **overrides: object) -> ManualStatement:
    """A well-formed income-statement entry, for a test to spoil one field of."""
    defaults: dict[str, object] = {
        "security_id": security_id,
        "statement_type": "income",
        "period_type": "FY",
        "period_end": PERIOD_END,
        "known_as_of": PUBLISHED,
        "currency": "NGN",
        "scale": "thousands",
        "source_document_id": document_id,
        "reviewed_by": REVIEWER,
        "figures": (
            TypedFigure("revenue", "3,360,000", 12),
            TypedFigure("profit_after_tax", "420,000", 12),
        ),
    }
    defaults.update(overrides)
    return ManualStatement(**defaults)  # type: ignore[arg-type]


def _items(session: Session, statement_id: int) -> dict[str, StatementLineItem]:
    rows = (
        session.execute(
            select(StatementLineItem).where(StatementLineItem.statement_id == statement_id)
        )
        .scalars()
        .all()
    )
    return {row.canonical_key: row for row in rows}


# --------------------------------------------------------------------------------------
# Check 3: blank, dash, zero and unreadable are four different answers
# --------------------------------------------------------------------------------------


def test_a_blank_field_stores_null_and_never_zero(
    db_session: Session, security: int, report: int
) -> None:
    """Check 3, stated. `SPEC.md` §4.1, and the reason a ratio can be trusted.

    A stored 0 would publish a debt-to-equity of 0.0 for a company whose debt line was
    simply not read — an answer, confidently wrong, and indistinguishable from a real one.
    """
    result = enter_statement(
        db_session,
        an_entry(
            security,
            report,
            figures=(
                TypedFigure("revenue", "3,360,000", 12),
                TypedFigure("interest_expense", "", 12),  # the operator found no such line
            ),
        ),
    )
    items = _items(db_session, result.statement_id)
    assert items["interest_expense"].value is None
    assert items["interest_expense"].value != Decimal(0), "NULL, not zero"
    assert items["interest_expense"].as_printed_value is None, "nothing was printed"
    assert result.figures_absent == 1


def test_a_printed_dash_is_kept_so_it_can_be_told_from_a_blank(
    db_session: Session, security: int, report: int
) -> None:
    """Both are absence. The difference is whose absence, and that is evidence.

    A dash is the company's own statement that there was nothing there; a blank is ours. A
    reviewer a year later can only tell them apart if the dash was kept.
    """
    result = enter_statement(
        db_session,
        an_entry(
            security,
            report,
            figures=(
                TypedFigure("revenue", "3,360,000", 12),
                TypedFigure("rd_expense", "—", 13),  # an em dash, as a typesetter sets it
            ),
        ),
    )
    items = _items(db_session, result.statement_id)
    assert items["rd_expense"].value is None
    assert items["rd_expense"].as_printed_value == "—", "the page said so, and it is kept"


def test_a_reported_zero_is_a_value(db_session: Session, security: int, report: int) -> None:
    """`docs/08` §1.4: zero is knowledge, and it is not the same as missing."""
    result = enter_statement(
        db_session,
        an_entry(
            security,
            report,
            # `fx_loss_net`, not `capex`: capex is a cashflow key, and the entry refuses a
            # key that does not belong to the statement being typed.
            figures=(
                TypedFigure("revenue", "3,360,000", 12),
                TypedFigure("fx_loss_net", "0", 14),
            ),
        ),
    )
    items = _items(db_session, result.statement_id)
    assert items["fx_loss_net"].value == Decimal(0)
    assert items["fx_loss_net"].value is not None, "a reported zero is not an absence"
    assert result.figures_absent == 0, "both figures were reported, one of them as zero"


def test_an_unreadable_figure_is_refused_rather_than_guessed(
    db_session: Session, security: int, report: int
) -> None:
    """The operator re-reads the page. Nothing is written, so there is nothing to un-write.

    The message names the key and the page, because "unreadable figure" alone sends someone
    back through forty fields looking for it.
    """
    with pytest.raises(UnreadableFigureError, match="revenue on page 12"):
        enter_statement(
            db_session,
            an_entry(security, report, figures=(TypedFigure("revenue", "circa 3,360", 12),)),
        )
    assert (
        not db_session.execute(select(Statement).where(Statement.period_end == PERIOD_END))
        .scalars()
        .all()
    ), "a refused entry leaves no statement behind"


# --------------------------------------------------------------------------------------
# Check 2: provenance complete — every manual item has a page
# --------------------------------------------------------------------------------------


def test_every_manual_line_item_carries_a_page_and_a_reviewer(
    db_session: Session, security: int, report: int
) -> None:
    """Check 2, and it is a constraint as well as a test.

    `page_required_unless_structured` permits a NULL page only for `extraction_method='xbrl'`,
    so a manual item without one cannot be written at all. This asserts the column the check
    queries, and that the figures carry the name of whoever typed them.
    """
    result = enter_statement(db_session, an_entry(security, report))
    items = _items(db_session, result.statement_id)
    assert set(items) == {"revenue", "profit_after_tax"}
    for item in items.values():
        assert item.extraction_method == "manual"
        assert item.page == 12
        assert item.reviewed_by == REVIEWER
        assert item.source_document_id == report
        assert item.confidence is None, "a person read it; confidence is the extractor's word"

    unprovenanced = db_session.execute(
        text(
            "SELECT count(*) FROM statement_line_items "
            "WHERE page IS NULL AND extraction_method = 'manual'"
        )
    ).scalar_one()
    assert unprovenanced == 0, "check 2, as docs/03 phrases it"


def test_the_scale_is_applied_once_and_recorded(
    db_session: Session, security: int, report: int
) -> None:
    """`docs/08` §1.4's worked figure: 3,360,000 in thousands is NGN 3.36 billion.

    Dividing the stored value by the recorded multiplier returns the numeral on the page,
    which is what makes the conversion checkable without reopening the PDF.
    """
    result = enter_statement(db_session, an_entry(security, report))
    revenue = _items(db_session, result.statement_id)["revenue"]
    assert revenue.value == Decimal("3360000000")
    assert revenue.unit_multiplier == 1_000
    assert revenue.as_printed_value == "3,360,000"
    assert revenue.as_printed_scale == "thousands"
    assert revenue.value is not None
    assert revenue.value / revenue.unit_multiplier == Decimal("3360000")


def test_the_statement_records_when_the_issuer_published_not_when_it_was_typed(
    db_session: Session, security: int, report: int
) -> None:
    """`known_as_of` is what decides whether a point-in-time read may see these figures.

    Defaulting it to today would let a backtest deciding in January 2026 read a report
    published in April — `SPEC.md` §4.1's lookahead, entered by hand.
    """
    result = enter_statement(db_session, an_entry(security, report))
    statement = db_session.get(Statement, result.statement_id)
    assert statement is not None
    assert statement.known_as_of == PUBLISHED
    assert statement.known_as_of > statement.period_end
    assert statement.filing_id is None, "a typed statement cites its document, not an accession"
    assert statement.version == 1 and statement.restatement_flag is False
    assert statement.presentation_multiplier == 1, "the figures are already in base units"


# --------------------------------------------------------------------------------------
# What the entry refuses, each fixable by re-reading the page
# --------------------------------------------------------------------------------------


def test_a_page_beyond_the_document_is_refused(
    db_session: Session, security: int, report: int
) -> None:
    """The reason P3.1 reads the page count off the file: so this check can exist.

    A figure citing page 143 of a 60-page report is a provenance error, and it is silent —
    the number may well be right and still be uncheckable.
    """
    with pytest.raises(EntryRefusedError, match="cites page 143 of a document with 60 pages"):
        enter_statement(
            db_session,
            an_entry(security, report, figures=(TypedFigure("revenue", "3,360,000", 143),)),
        )
    with pytest.raises(EntryRefusedError, match="not a page number"):
        enter_statement(
            db_session,
            an_entry(security, report, figures=(TypedFigure("revenue", "3,360,000", 0),)),
        )


def test_a_figure_with_no_document_is_refused(db_session: Session, security: int) -> None:
    """`CLAUDE.md` forbids the untraceable figure, and this is where one would enter."""
    with pytest.raises(EntryRefusedError, match="Upload the report first"):
        enter_statement(db_session, an_entry(security, 9_999_999))


def test_a_publication_date_before_the_period_end_is_refused(
    db_session: Session, security: int, report: int
) -> None:
    """A report cannot have been published before the period it covers had ended."""
    with pytest.raises(EntryRefusedError, match="precedes period_end"):
        enter_statement(db_session, an_entry(security, report, known_as_of=dt.date(2025, 6, 30)))


def test_an_invented_canonical_key_is_refused(
    db_session: Session, security: int, report: int
) -> None:
    """A figure under a key the chart does not have is a figure nothing will ever read."""
    with pytest.raises(EntryRefusedError, match="not a key of the income statement"):
        enter_statement(
            db_session,
            an_entry(security, report, figures=(TypedFigure("revenues_total", "1", 12),)),
        )


def test_a_balance_sheet_key_is_refused_on_the_income_statement(
    db_session: Session, security: int, report: int
) -> None:
    """`total_assets` is a real key, and not one the income statement has.

    Accepting it would put a balance in the income statement's row set, where every reader
    of that statement would then find a figure that does not belong to it.
    """
    with pytest.raises(EntryRefusedError, match="not a key of the income statement"):
        enter_statement(
            db_session,
            an_entry(security, report, figures=(TypedFigure("total_assets", "1,000", 40),)),
        )


def test_an_undeclared_scale_is_refused(db_session: Session, security: int, report: int) -> None:
    """Nigerian statements do print in billions; adding that scale is a `docs/08` change.

    Accepting it here would let a figure carry a scale that every reader of
    `as_printed_scale` — the review queue, the provenance panel — does not know.
    """
    with pytest.raises(EntryRefusedError, match="not a declared scale"):
        enter_statement(db_session, an_entry(security, report, scale="billions"))


def test_an_unsigned_entry_is_refused(db_session: Session, security: int, report: int) -> None:
    """A hand-typed figure is only as good as the name attached to it."""
    with pytest.raises(EntryRefusedError, match="reviewed_by is empty"):
        enter_statement(db_session, an_entry(security, report, reviewed_by="   "))


def test_an_entry_with_no_figures_is_refused(
    db_session: Session, security: int, report: int
) -> None:
    with pytest.raises(EntryRefusedError, match="no figures"):
        enter_statement(db_session, an_entry(security, report, figures=()))


def test_the_same_key_twice_is_refused(db_session: Session, security: int, report: int) -> None:
    """`one_current_version` would refuse the second row; the operator meant one of them."""
    with pytest.raises(EntryRefusedError, match="appears twice"):
        enter_statement(
            db_session,
            an_entry(
                security,
                report,
                figures=(
                    TypedFigure("revenue", "3,360,000", 12),
                    TypedFigure("revenue", "3,360,001", 12),
                ),
            ),
        )


def test_re_entering_a_period_points_at_the_correction_path(
    db_session: Session, security: int, report: int
) -> None:
    """A second entry for an entered period is a correction, and corrections version.

    Writing a quiet second version here would bypass the module that carries every sibling
    figure forward and records whose mistake it was (`docs/10` §2.10), so the refusal names
    the tool that does it properly.
    """
    enter_statement(db_session, an_entry(security, report))
    with pytest.raises(EntryRefusedError, match="correct_figure.py"):
        enter_statement(db_session, an_entry(security, report))

    statements = (
        db_session.execute(select(Statement).where(Statement.period_end == PERIOD_END))
        .scalars()
        .all()
    )
    assert len(statements) == 1, "the refusal wrote nothing"


def test_a_nonexistent_security_is_refused(db_session: Session, report: int) -> None:
    with pytest.raises(EntryRefusedError, match="does not exist"):
        enter_statement(db_session, an_entry(9_999_999, report))

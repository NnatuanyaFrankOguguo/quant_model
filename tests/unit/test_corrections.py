"""`packages.normalize.corrections`: a correction that sticks. TG10, `docs/03` P3.5.

`docs/10` §2.10 asked for "a golden test for each branch" of the `known_as_of` rule, and the
branch test is the one that matters here:

* **our own error** keeps the *original* date, so a point-in-time read with a decision date
  *before* the fix returns the corrected figure. Without that, the typo is baked into every
  backtest over that period, forever.
* **a restatement** takes the company's new publication date, so a read before it still
  returns the earlier figure, because that is genuinely what the market knew.

The rest of the file is the no-silent-overwrite promise: the superseded row survives, the
database refuses a bare `UPDATE`, and a correction without an author or a reason is refused
rather than stored anonymously.
"""

from __future__ import annotations

import datetime as dt
from decimal import Decimal

import pytest
from sqlalchemy import select, text, update
from sqlalchemy.exc import DatabaseError
from sqlalchemy.orm import Session

from packages.common.models import (
    Company,
    DataSource,
    Exchange,
    Filing,
    Security,
    SourceDocument,
    Statement,
    StatementLineItem,
)
from packages.common.pit import line_items_as_known_on
from packages.common.timez import utcnow
from packages.normalize.corrections import (
    Correction,
    CorrectionRefusedError,
    apply_correction,
    history_of,
)

pytestmark = pytest.mark.invariant

#: The figure under test: a revenue printed in thousands and stored 1,000x too small - the
#: `OPERATIONS.md` §1.6 error class, which is exactly what a hand correction is for.
PERIOD_END = dt.date(2024, 12, 31)
FILED_ON = dt.date(2025, 3, 31)
TYPO = Decimal("3360000000")
CORRECT = Decimal("3360000000000")
WHO = "frank"
WHY = "printed under a millions heading; stored as thousands. Checked against page 42."
#: A second figure on the same statement, to prove the siblings come across untouched.
SIBLING_VALUE = Decimal("1200000000")


@pytest.fixture
def figure(db_session: Session) -> StatementLineItem:
    """One stored figure with the typo in it, and everything a line item needs."""
    source_id = db_session.execute(select(DataSource.id).order_by(DataSource.id)).scalars().first()
    document = SourceDocument(
        data_source_id=source_id,
        url="file:///gtco-2024.pdf",
        storage_key="documents/sha256/" + "d" * 64,
        sha256="d" * 64,
        media_type="application/pdf",
        retrieved_at=utcnow(),
    )
    company = Company(
        legal_name="Correction Test Plc",
        country="NG",
        statement_template="bank",
        fiscal_year_end=12,
    )
    db_session.add_all([document, company])
    db_session.flush()
    exchange_id = db_session.execute(select(Exchange.id).where(Exchange.code == "NGX")).scalar_one()
    security = Security(company_id=company.id, exchange_id=exchange_id, currency="NGN")
    db_session.add(security)
    db_session.flush()
    filing = Filing(
        company_id=company.id,
        filing_type="annual",
        filing_date=FILED_ON,
        period_end=PERIOD_END,
        accession_no="ngx-2024-0001",
        source_document_id=document.id,
        known_as_of=FILED_ON,
    )
    db_session.add(filing)
    db_session.flush()
    statement = Statement(
        filing_id=filing.id,
        company_id=company.id,
        statement_type="income_statement",
        period_type="FY",
        period_end=PERIOD_END,
        fiscal_year=2024,
        calendar_year=2024,
        period_label="FY2024",
        presentation_currency="NGN",
        presentation_multiplier=1_000,
        known_as_of=FILED_ON,
        chart_version="v0.1",
        statement_template="bank",
        is_consolidated=True,
        source_document_id=document.id,
    )
    db_session.add(statement)
    db_session.flush()
    item = StatementLineItem(
        statement_id=statement.id,
        security_id=security.id,
        canonical_key="revenue",
        chart_version="v0.1",
        as_printed_label="Gross earnings",
        as_printed_value="3,360,000",
        as_printed_scale="thousands",
        needs_review=True,
        value=TYPO,
        currency="NGN",
        unit_multiplier=1_000,
        period_end=PERIOD_END,
        known_as_of=FILED_ON,
        version=1,
        source_document_id=document.id,
        page=42,
        extraction_method="manual",
    )
    db_session.add(item)
    db_session.flush()
    return item


@pytest.fixture
def sibling(db_session: Session, figure: StatementLineItem) -> StatementLineItem:
    """A second figure on the same statement, so the carry-forward is exercised."""
    item = StatementLineItem(
        statement_id=figure.statement_id,
        security_id=figure.security_id,
        canonical_key="cost_of_revenue",
        chart_version="v0.1",
        as_printed_label="Interest expense",
        as_printed_value="1,200,000",
        as_printed_scale="thousands",
        needs_review=False,
        value=SIBLING_VALUE,
        currency="NGN",
        unit_multiplier=1_000,
        period_end=PERIOD_END,
        known_as_of=FILED_ON,
        version=1,
        source_document_id=figure.source_document_id,
        page=42,
        extraction_method="manual",
    )
    db_session.add(item)
    db_session.flush()
    return item


def _correct(**overrides: object) -> Correction:
    fields: dict[str, object] = {
        "security_id": 0,
        "canonical_key": "revenue",
        "period_type": "FY",
        "period_end": PERIOD_END,
        "value": CORRECT,
        "corrected_by": WHO,
        "reason": WHY,
    }
    fields.update(overrides)
    return Correction(**fields)  # type: ignore[arg-type]


# --------------------------------------------------------------------------------------
# The date rule - `docs/10` §2.10's two branches
# --------------------------------------------------------------------------------------


def test_our_own_error_is_corrected_backwards_in_time(
    db_session: Session, figure: StatementLineItem
) -> None:
    """The branch test `docs/10` §2.10 asked for, and the reason the rule exists.

    We misread the figure, so the market always had the right number. A reader standing on
    any date after the company published - including dates long before anyone noticed the
    typo - must see the corrected figure. Otherwise the error is baked into every
    point-in-time read and every backtest over that period, forever.
    """
    result = apply_correction(db_session, _correct(security_id=figure.security_id))
    assert result.previous_value == TYPO and result.value == CORRECT
    assert result.known_as_of == FILED_ON == result.previous_known_as_of, (
        "a transcription correction keeps the original date"
    )

    # The decision date is a year before anybody spotted it, and the read is still correct.
    as_known = line_items_as_known_on(
        db_session,
        security_id=figure.security_id,
        decision_date=dt.date(2025, 4, 1),
        canonical_keys=("revenue",),
    )
    assert [i.value for i in as_known] == [CORRECT], "the typo must not survive in history"
    assert as_known[0].correction_type == "transcription"
    assert as_known[0].corrected_by == WHO and as_known[0].correction_reason == WHY
    assert as_known[0].version == 2


def test_a_restatement_is_only_visible_from_the_day_it_was_published(
    db_session: Session, figure: StatementLineItem
) -> None:
    """The other branch: the company republished, so both figures are historically true.

    A reader before the restatement date saw the original and must still see it. This is
    the same guarantee P2 check 15 proved on Apple's 2010 adoption, from the write side.
    """
    republished = dt.date(2025, 9, 30)
    result = apply_correction(
        db_session,
        _correct(
            security_id=figure.security_id,
            correction_type="restatement",
            known_as_of=republished,
        ),
    )
    assert result.known_as_of == republished

    before = line_items_as_known_on(
        db_session,
        security_id=figure.security_id,
        decision_date=republished - dt.timedelta(days=1),
        canonical_keys=("revenue",),
    )
    after = line_items_as_known_on(
        db_session,
        security_id=figure.security_id,
        decision_date=republished,
        canonical_keys=("revenue",),
    )
    assert [i.value for i in before] == [TYPO], "the earlier figure is what the market knew"
    assert [i.value for i in after] == [CORRECT]
    assert after[0].restatement_flag is True, "the company changed its mind, and it shows"
    assert before[0].restatement_flag is False


def test_our_own_error_does_not_masquerade_as_a_restatement(
    db_session: Session, figure: StatementLineItem
) -> None:
    """`restatement_flag` drives the page's marker; a typo is not the company republishing."""
    apply_correction(db_session, _correct(security_id=figure.security_id))
    current = db_session.execute(
        select(StatementLineItem)
        .where(StatementLineItem.security_id == figure.security_id)
        .where(StatementLineItem.superseded_by.is_(None))
    ).scalar_one()
    assert current.restatement_flag is False
    assert current.correction_type == "transcription"


# --------------------------------------------------------------------------------------
# No silent overwrite
# --------------------------------------------------------------------------------------


def test_the_superseded_figure_is_kept_and_pointed_at(
    db_session: Session, figure: StatementLineItem
) -> None:
    """`CLAUDE.md`: no silent overwrites. The old value is still there to be audited."""
    result = apply_correction(db_session, _correct(security_id=figure.security_id))
    old = db_session.get(StatementLineItem, result.superseded_id)
    assert old is not None, "the row a correction replaces is never deleted"
    assert old.value == TYPO, "and its value is untouched"
    assert old.superseded_by == result.line_item_id, "it points at what replaced it"

    versions = history_of(
        db_session,
        security_id=figure.security_id,
        canonical_key="revenue",
        period_type="FY",
        period_end=PERIOD_END,
    )
    assert [(v.version, v.value) for v in versions] == [(1, TYPO), (2, CORRECT)]
    assert [v.correction_reason for v in versions] == [None, WHY]


def test_exactly_one_version_is_current_afterwards(
    db_session: Session, figure: StatementLineItem
) -> None:
    """`one_current_version`: "the current value" is a guaranteed single row, not an ORDER BY."""
    apply_correction(db_session, _correct(security_id=figure.security_id))
    current = (
        db_session.execute(
            select(StatementLineItem)
            .where(StatementLineItem.security_id == figure.security_id)
            .where(StatementLineItem.superseded_by.is_(None))
        )
        .scalars()
        .all()
    )
    assert len(current) == 1 and current[0].value == CORRECT


def test_the_database_refuses_to_let_anyone_edit_a_figure_in_place(
    db_session: Session, figure: StatementLineItem
) -> None:
    """Why this module exists rather than a one-line `UPDATE`.

    `forbid_update_except_supersession` permits only setting `superseded_by` from NULL. An
    attempt to change the value itself is refused at the row, so the mechanism above is not
    a convention anyone can bypass in a hurry.
    """
    with pytest.raises(DatabaseError, match="UPDATE forbidden"), db_session.begin_nested():
        db_session.execute(
            update(StatementLineItem).where(StatementLineItem.id == figure.id).values(value=CORRECT)
        )
        db_session.flush()

    assert (
        db_session.execute(
            text("select value from statement_line_items where id = :i").bindparams(i=figure.id)
        ).scalar_one()
        == TYPO
    )


def test_a_figure_can_be_corrected_to_nothing(
    db_session: Session, figure: StatementLineItem
) -> None:
    """`docs/08` §1.4: a value we filled in that the company never reported must be emptiable,
    and the empty must be a real NULL rather than a zero."""
    result = apply_correction(
        db_session,
        _correct(security_id=figure.security_id, value=None, reason="not on the face of the page"),
    )
    assert result.value is None
    current = db_session.get(StatementLineItem, result.line_item_id)
    assert current is not None and current.value is None


# --------------------------------------------------------------------------------------
# What is refused, and why
# --------------------------------------------------------------------------------------


def test_a_correction_without_an_author_or_a_reason_is_refused(
    db_session: Session, figure: StatementLineItem
) -> None:
    """`PROJECT_CONTEXT.md` §7 requires "a note recording who changed it and why"."""
    with pytest.raises(CorrectionRefusedError, match="who made it"):
        apply_correction(db_session, _correct(security_id=figure.security_id, corrected_by="  "))
    with pytest.raises(CorrectionRefusedError, match="why it was made"):
        apply_correction(db_session, _correct(security_id=figure.security_id, reason=""))


def test_a_correction_that_changes_nothing_is_refused(
    db_session: Session, figure: StatementLineItem
) -> None:
    with pytest.raises(CorrectionRefusedError, match="changes nothing"):
        apply_correction(db_session, _correct(security_id=figure.security_id, value=TYPO))


def test_a_restatement_without_its_publication_date_is_refused(
    db_session: Session, figure: StatementLineItem
) -> None:
    with pytest.raises(CorrectionRefusedError, match="needs the date"):
        apply_correction(
            db_session, _correct(security_id=figure.security_id, correction_type="restatement")
        )


def test_our_own_error_will_not_accept_a_date(
    db_session: Session, figure: StatementLineItem
) -> None:
    """Offering one would mean choosing to hide the fix from earlier readers, which is the
    defect `docs/10` §2.10 exists to prevent."""
    with pytest.raises(CorrectionRefusedError, match="takes no date"):
        apply_correction(
            db_session, _correct(security_id=figure.security_id, known_as_of=dt.date(2025, 6, 1))
        )


def test_a_restatement_cannot_predate_the_figure_it_replaces(
    db_session: Session, figure: StatementLineItem
) -> None:
    with pytest.raises(CorrectionRefusedError, match="cannot predate"):
        apply_correction(
            db_session,
            _correct(
                security_id=figure.security_id,
                correction_type="restatement",
                known_as_of=FILED_ON - dt.timedelta(days=1),
            ),
        )


def test_an_unknown_correction_type_is_refused(
    db_session: Session, figure: StatementLineItem
) -> None:
    with pytest.raises(CorrectionRefusedError, match="not a correction type"):
        apply_correction(
            db_session,
            _correct(security_id=figure.security_id, correction_type="typo"),  # type: ignore[arg-type]
        )


def test_correcting_a_figure_that_does_not_exist_is_refused(
    db_session: Session, figure: StatementLineItem
) -> None:
    """A correction edits; it does not create. Creating is P3.2's manual entry form."""
    with pytest.raises(CorrectionRefusedError, match="no current figure"):
        apply_correction(
            db_session, _correct(security_id=figure.security_id, canonical_key="total_assets")
        )


def test_a_correction_versions_the_whole_statement_and_carries_its_siblings(
    db_session: Session, figure: StatementLineItem, sibling: StatementLineItem
) -> None:
    """The shape `one_current_version` forces, and `docs/03` P3 states outright.

    That index is unique per `(statement_id, canonical_key)` among un-superseded rows, so
    two current versions of one figure cannot share a statement. A correction therefore
    versions the statement, exactly as `StatementWriter` does for a restatement, and
    "as known after this change" is the whole statement rather than only the line that
    moved. Every sibling comes across unchanged and uncorrected.
    """
    result = apply_correction(db_session, _correct(security_id=figure.security_id))
    assert result.statement_id != result.superseded_statement_id
    assert result.carried_forward == 1, "one sibling, brought across"

    old_statement = db_session.get(Statement, result.superseded_statement_id)
    assert old_statement is not None
    assert old_statement.superseded_by == result.statement_id

    carried = db_session.execute(
        select(StatementLineItem)
        .where(StatementLineItem.statement_id == result.statement_id)
        .where(StatementLineItem.canonical_key == "cost_of_revenue")
    ).scalar_one()
    assert carried.value == SIBLING_VALUE, "carried forward, not touched"
    assert carried.correction_type == "none", "the note lands only on the figure that changed"
    assert carried.corrected_by is None and carried.restatement_flag is False
    assert carried.version == result.version, "one version across the statement"

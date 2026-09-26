"""Correcting a stored figure by hand, so that the correction sticks. TG10, `docs/03` P3.5.

`PROJECT_CONTEXT.md` §7: *"Extraction will get things wrong. There must always be a way to
correct a number by hand and have the correction **stick**, with a note recording who
changed it and why."* T4's review queue covers figures on their way in; this covers a figure
already stored and already on a screen.

**A correction is an insert, never an update.** `CLAUDE.md` forbids silent overwrites and
`docs/08` §10 spells out the mechanism: never `UPDATE`, insert a new version, set
`superseded_by`, record `corrected_by` and `correction_reason`. The database enforces it -
`forbid_update_except_supersession` permits exactly one write to an existing row, setting
`superseded_by` from NULL once, with every other column byte-identical. So the old value is
not merely kept by convention; it cannot be destroyed.

**The date rule is the whole point, and it is not obvious.** `docs/10` §2.10 found it
undefined and the two cases opposite:

* **A restatement** is the company republishing. `known_as_of` is the *new* publication
  date, because the market did not know the new figure until then. Both figures are
  historically true and a reader on the earlier date must still see the earlier one.
* **A correction** is *us* misreading or mistyping. The market always had the right number,
  so the corrected row carries the **original** `known_as_of`. Otherwise every point-in-time
  query with a decision date before the correction returns the typo **forever**, baked into
  every backtest that ever runs over that period.

`correction_type` records which, so the choice is stated rather than inferred from the
dates. `tests/unit/test_corrections.py` has the branch test `docs/10` §2.10 asked for, and
it is the one that matters: it reads back *before* the correction was made and asserts the
corrected figure, not the typo.

**What the new row keeps, and why.** `source_document_id`, `page` and `extraction_method`
come from the row being superseded. The figure still comes from that document and that page;
what changed is our reading of it, and `corrected_by`, `corrected_at`, `correction_reason`
and `correction_type` on the same row say so. Rewriting `extraction_method` to `'manual'`
would also break `page_required_unless_structured` for every XBRL-derived figure, which has
no page by definition - so the intervention is recorded in the columns built for it rather
than by overwriting the provenance of the original reading.

**`restatement_flag` stays false for our own corrections.** It drives the "restated" marker
the company page shows, and a transcription error is not a restatement. Conflating them
would tell a reader the company changed its mind when in fact we fixed our own typo.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from decimal import Decimal
from typing import Literal

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from packages.common.models import Statement, StatementLineItem
from packages.common.timez import utcnow

__all__ = [
    "CORRECTION_TYPES",
    "Correction",
    "CorrectionRefusedError",
    "CorrectionResult",
    "OUR_ERRORS",
    "apply_correction",
    "history_of",
]

#: `docs/10` §2.10's vocabulary. `'none'` is the default on an uncorrected row and is not a
#: correction anyone applies, so it is not offered here.
CORRECTION_TYPES = ("transcription", "extraction", "restatement")

#: The two that are *our* mistake rather than the company's republication. These keep the
#: original `known_as_of`; a restatement takes a new one.
OUR_ERRORS = ("transcription", "extraction")


class CorrectionRefusedError(ValueError):
    """The correction was not applied, and the reason says what to change."""


@dataclass(frozen=True)
class Correction:
    """One figure, corrected by hand, with the note `PROJECT_CONTEXT.md` §7 requires."""

    security_id: int
    canonical_key: str
    period_type: str
    period_end: dt.date
    #: The corrected figure. None is legitimate and means the company reported nothing
    #: there - `docs/08` §1.4's null rule - so a figure wrongly filled in can be emptied.
    value: Decimal | None
    corrected_by: str
    reason: str
    correction_type: Literal["transcription", "extraction", "restatement"] = "transcription"
    #: Required for a restatement and refused otherwise: the date the company republished.
    known_as_of: dt.date | None = None


@dataclass(frozen=True)
class CorrectionResult:
    """What was written, so the caller can show it and a test can assert it."""

    line_item_id: int  # the new, current row
    superseded_id: int  # the row it replaced, kept forever
    statement_id: int  # the new statement version the corrected figure belongs to
    superseded_statement_id: int
    #: How many figures came across unchanged. A statement version is the whole statement,
    #: so every sibling is carried forward rather than left pointing at the old version.
    carried_forward: int
    version: int
    previous_value: Decimal | None
    value: Decimal | None
    known_as_of: dt.date
    previous_known_as_of: dt.date
    correction_type: str


def apply_correction(session: Session, correction: Correction) -> CorrectionResult:
    """Correct one figure: insert a new version and supersede the old one.

    Raises `CorrectionRefusedError` when the correction is not one this module will write -
    an unknown figure, a missing author or reason, a value that is not a change, or a
    restatement without the date the company republished on.
    """
    _validate(correction)
    current = _current_row(session, correction)
    if current is None:
        raise CorrectionRefusedError(
            f"no current figure for {correction.canonical_key!r} "
            f"{correction.period_type} ending {correction.period_end} on security "
            f"{correction.security_id}. A correction edits a figure that exists; it does "
            "not create one."
        )
    if current.value == correction.value:
        raise CorrectionRefusedError(
            f"{correction.canonical_key!r} already reads {_shown(correction.value)}. A "
            "correction that changes nothing would add a version and say nothing."
        )

    known_as_of = _known_as_of_for(correction, current)
    statement = session.get(Statement, current.statement_id)
    if statement is None:  # pragma: no cover - the figure's FK guarantees it
        raise CorrectionRefusedError(f"line item {current.id} has no statement")
    siblings = _current_items_of(session, statement.id)

    new_statement = _next_statement_version(statement, known_as_of, correction)
    session.add(new_statement)
    session.flush()

    replacements: dict[int, StatementLineItem] = {}
    for old in siblings:
        corrected_here = old.id == current.id
        replacements[old.id] = _next_item_version(
            old,
            statement_id=new_statement.id,
            version=new_statement.version,
            known_as_of=known_as_of,
            correction=correction if corrected_here else None,
        )
    session.add_all(replacements.values())
    session.flush()

    # Supersession, the one write `forbid_update_except_supersession` permits:
    # `superseded_by` from NULL, once, with every other column untouched. Done after the
    # inserts and at both levels, exactly as `statements.StatementWriter` does it.
    session.execute(
        update(Statement)
        .where(Statement.id == statement.id)
        .where(Statement.superseded_by.is_(None))
        .values(superseded_by=new_statement.id)
    )
    session.execute(
        update(StatementLineItem),
        [{"id": old_id, "superseded_by": new.id} for old_id, new in replacements.items()],
    )
    session.flush()
    corrected = replacements[current.id]
    return CorrectionResult(
        line_item_id=corrected.id,
        superseded_id=current.id,
        statement_id=new_statement.id,
        superseded_statement_id=statement.id,
        carried_forward=len(replacements) - 1,
        version=corrected.version,
        previous_value=current.value,
        value=correction.value,
        known_as_of=known_as_of,
        previous_known_as_of=current.known_as_of,
        correction_type=correction.correction_type,
    )


def history_of(
    session: Session,
    *,
    security_id: int,
    canonical_key: str,
    period_type: str,
    period_end: dt.date,
) -> list[StatementLineItem]:
    """Every version of one figure, oldest first - what the page shows "on request".

    `PROJECT_CONTEXT.md` §7 wants the note recording who changed a number and why to be
    retrievable, not merely stored, so this is the read side of the same promise.
    """
    return list(
        session.execute(
            select(StatementLineItem)
            .join(Statement, Statement.id == StatementLineItem.statement_id)
            .where(StatementLineItem.security_id == security_id)
            .where(StatementLineItem.canonical_key == canonical_key)
            .where(StatementLineItem.period_end == period_end)
            .where(Statement.period_type == period_type)
            .order_by(StatementLineItem.version)
        )
        .scalars()
        .all()
    )


def _validate(correction: Correction) -> None:
    if correction.correction_type not in CORRECTION_TYPES:
        raise CorrectionRefusedError(
            f"{correction.correction_type!r} is not a correction type: "
            f"{list(CORRECTION_TYPES)} (`docs/10` §2.10)"
        )
    if not correction.corrected_by.strip():
        raise CorrectionRefusedError(
            "a correction records who made it. `PROJECT_CONTEXT.md` §7: 'a note recording "
            "who changed it and why'."
        )
    if not correction.reason.strip():
        raise CorrectionRefusedError(
            "a correction records why it was made. An unexplained figure that disagrees "
            "with the filing is worse than the wrong one, because nobody can check it."
        )
    if correction.correction_type == "restatement" and correction.known_as_of is None:
        raise CorrectionRefusedError(
            "a restatement needs the date the company republished: it is the new "
            "`known_as_of`, and a reader before it must still see the old figure."
        )
    if correction.correction_type in OUR_ERRORS and correction.known_as_of is not None:
        raise CorrectionRefusedError(
            f"a {correction.correction_type} correction takes no date. The market always "
            "had the right number, so the corrected row keeps the original `known_as_of` - "
            "otherwise every point-in-time read before today returns the error forever "
            "(`docs/10` §2.10)."
        )


def _known_as_of_for(correction: Correction, current: StatementLineItem) -> dt.date:
    """`docs/10` §2.10's rule, in one place.

    No lookahead check is needed here and one would be dead code: `line_items_pit_sanity`
    already holds `current.known_as_of >= current.period_end` on the row being replaced, and
    a restatement must not predate that date, so the new date is at or after the period end
    by construction.
    """
    if correction.correction_type in OUR_ERRORS:
        return current.known_as_of
    assert correction.known_as_of is not None  # _validate refused None for a restatement
    if correction.known_as_of < current.known_as_of:
        raise CorrectionRefusedError(
            f"a restatement published {correction.known_as_of} cannot predate the figure it "
            f"replaces, which was known on {current.known_as_of}."
        )
    return correction.known_as_of


def _next_statement_version(
    statement: Statement, known_as_of: dt.date, correction: Correction
) -> Statement:
    """The statement, one version on.

    A correction versions the *statement*, not the line item alone, because that is the
    shape the schema enforces: `one_current_version` is unique per
    `(statement_id, canonical_key)` where nothing supersedes the row, so two current
    versions of one figure cannot share a statement. `statements.StatementWriter` writes a
    restatement the same way, and `docs/03` P3 puts it plainly - "as known after this
    filing" is the whole statement, not only the lines that moved.
    """
    return Statement(
        filing_id=statement.filing_id,
        company_id=statement.company_id,
        statement_type=statement.statement_type,
        period_type=statement.period_type,
        period_start=statement.period_start,
        period_end=statement.period_end,
        fiscal_year=statement.fiscal_year,
        calendar_year=statement.calendar_year,
        period_label=statement.period_label,
        presentation_currency=statement.presentation_currency,
        presentation_multiplier=statement.presentation_multiplier,
        is_audited=statement.is_audited,
        is_consolidated=statement.is_consolidated,
        statement_template=statement.statement_template,
        chart_version=statement.chart_version,
        version=statement.version + 1,
        superseded_by=None,
        restatement_flag=correction.correction_type == "restatement",
        known_as_of=known_as_of,
        source_document_id=statement.source_document_id,
    )


def _next_item_version(
    old: StatementLineItem,
    *,
    statement_id: int,
    version: int,
    known_as_of: dt.date,
    correction: Correction | None,
) -> StatementLineItem:
    """One figure on the new statement version: corrected, or carried forward unchanged.

    `correction` is None for the siblings. They keep their value, their provenance and a
    `correction_type` of `'none'`, so the note lands only on the figure somebody actually
    changed and the page does not mark forty rows as corrected because one was.
    """
    corrected = correction is not None
    return StatementLineItem(
        statement_id=statement_id,
        security_id=old.security_id,
        canonical_key=old.canonical_key,
        chart_version=old.chart_version,
        as_printed_label=old.as_printed_label,
        as_printed_value=old.as_printed_value,
        as_printed_scale=old.as_printed_scale,
        # A human has looked at the corrected figure, which is what the queue waited for.
        needs_review=False if corrected else old.needs_review,
        value=correction.value if correction is not None else old.value,
        currency=old.currency,
        unit_multiplier=old.unit_multiplier,
        period_start=old.period_start,
        period_end=old.period_end,
        known_as_of=known_as_of,
        version=version,
        superseded_by=None,
        # True only where the company republished this figure: it drives the page's
        # "restated" marker, and our own typo is not the company changing its mind.
        restatement_flag=corrected
        and correction is not None
        and correction.correction_type == "restatement",
        correction_type=correction.correction_type if correction is not None else "none",
        # Provenance of the original reading, unchanged - see the module docstring.
        source_document_id=old.source_document_id,
        page=old.page,
        bbox=old.bbox,
        extraction_job_id=old.extraction_job_id,
        extraction_method=old.extraction_method,
        # Confidence is a model's self-report. A figure a person typed has none.
        confidence=None if corrected else old.confidence,
        reviewed_by=old.reviewed_by,
        corrected_by=correction.corrected_by.strip() if correction is not None else None,
        corrected_at=utcnow() if corrected else None,
        correction_reason=correction.reason.strip() if correction is not None else None,
    )


def _current_items_of(session: Session, statement_id: int) -> list[StatementLineItem]:
    """Every figure on this statement version that nothing has superseded."""
    return list(
        session.execute(
            select(StatementLineItem)
            .where(StatementLineItem.statement_id == statement_id)
            .where(StatementLineItem.superseded_by.is_(None))
            .order_by(StatementLineItem.canonical_key)
        )
        .scalars()
        .all()
    )


def _current_row(session: Session, correction: Correction) -> StatementLineItem | None:
    """The figure a reader sees today: the one version that nothing has superseded."""
    return session.execute(
        select(StatementLineItem)
        .join(Statement, Statement.id == StatementLineItem.statement_id)
        .where(StatementLineItem.security_id == correction.security_id)
        .where(StatementLineItem.canonical_key == correction.canonical_key)
        .where(StatementLineItem.period_end == correction.period_end)
        .where(Statement.period_type == correction.period_type)
        .where(StatementLineItem.superseded_by.is_(None))
    ).scalar_one_or_none()


def _shown(value: Decimal | None) -> str:
    return "nothing" if value is None else f"{value:,}"

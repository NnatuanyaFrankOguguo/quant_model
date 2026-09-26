"""Typing a statement in by hand, with the provenance that makes it trustworthy. P3.2.

`docs/03` P3.2:

    A Streamlit form (thin client, per AD-3) showing the PDF page beside the input fields,
    writing through the API to `statement_line_items` with full provenance:
    `source_document_id`, `page`, `as_of_date`, `known_as_of`, `extraction_method='manual'`,
    `reviewed_by`. The form enforces the same rules as everything else: **a field left blank
    stores null, never zero** (`SPEC.md` §4.1).

This module is the rule half. The form and the endpoint are thin over it on purpose: the
checks below must hold however a figure arrives, and a rule living in a Streamlit callback
protects only the people who use that callback.

**Why this is not `StatementWriter`.** That writer takes a filing's worth of XBRL facts and
writes every line item with `page=None`, which the `page_required_unless_structured`
constraint permits only for `extraction_method='xbrl'`. A hand-typed figure must cite the
page it was read from, and the page is per figure - two numbers from one report routinely sit
forty pages apart. Sharing the code would mean making `page` optional in the one path where
it is the point.

**Why re-entering a period is refused rather than versioned.** A second entry for a period
that already has one is a *correction*, and corrections are `packages/normalize/corrections.py`
- which versions the whole statement, carries every sibling figure forward, and decides whose
mistake it was so that `known_as_of` is right (`docs/10` §2.10). Quietly writing a second
version here would bypass all of that and lose the reason. So this writes version 1 and says
where to go for version 2.

## Blank, dash, zero, and unreadable

`docs/08` §1.4 distinguishes four things a cell can be, and the form has to keep them apart:

| The operator does this | Stored |
|---|---|
| leaves the field empty | `value` NULL, `as_printed_value` NULL - not reported |
| types the dash the page prints | `value` NULL, `as_printed_value` `'-'` - the page said so |
| types `0` | `value` 0 - a reported zero is knowledge |
| types something unreadable | refused, so the figure is entered again rather than guessed |

The first two are both absence, and the difference between them is evidence: a dash is the
company's own statement that there was nothing there, a blank is ours. Keeping the printed
dash is what lets a reviewer tell those apart a year later.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field
from decimal import Decimal

import structlog
from sqlalchemy import select
from sqlalchemy.orm import Session

from packages.common.models import (
    Company,
    Security,
    SourceDocument,
    Statement,
    StatementLineItem,
)
from packages.common.units import UnreadableFigureError, multiplier_for, to_base
from packages.normalize.chart import chart_template_for, load_chart
from packages.normalize.periods import fiscal_year_of, period_label

__all__ = [
    "EntryRefusedError",
    "ManualStatement",
    "ManualEntryResult",
    "TypedFigure",
    "enter_statement",
]

_log = structlog.get_logger(__name__)

EXTRACTION_METHOD = "manual"

#: The dashes a typeset statement uses for "nothing here". Anything else non-empty is read as
#: a figure, and refused if it will not read as one.
_DASHES = frozenset({"-", "--", "‒", "–", "—", "−"})


class EntryRefusedError(ValueError):
    """The entry was not written, and the message says which rule stopped it.

    Every refusal is whole-entry: nothing is written unless everything can be. A half-entered
    statement is worse than a rejected one, because the gaps are invisible and the operator
    has already moved on - the same reason `scripts/ingest_csv.py` refuses a CSV outright.
    """


@dataclass(frozen=True)
class TypedFigure:
    """One figure as the operator read it off the page."""

    canonical_key: str
    #: Exactly what the page shows, including brackets, a currency mark or a dash. Empty
    #: means the operator found no such line.
    printed: str
    #: The page it was read from, 1-based, as the PDF numbers it.
    page: int


@dataclass(frozen=True)
class ManualStatement:
    """One statement for one period, typed from one document."""

    security_id: int
    statement_type: str  # 'income'|'balance'|'cashflow'
    period_type: str  # 'FY'|'H1'|'Q1'|...
    period_end: dt.date
    #: When the issuer published the report. Not today, and not the period end: it is what
    #: decides whether a point-in-time read on some past date may see these figures.
    known_as_of: dt.date
    currency: str
    #: 'units'|'thousands'|'millions', as the statement's own column heading declares it.
    scale: str
    source_document_id: int
    reviewed_by: str
    figures: tuple[TypedFigure, ...]
    period_start: dt.date | None = None
    is_audited: bool = True
    is_consolidated: bool = True
    chart_version: str = "v1"


@dataclass
class ManualEntryResult:
    statement_id: int
    line_items_written: int = 0
    #: Figures stored as NULL because the company did not report them.
    figures_absent: int = 0
    keys: list[str] = field(default_factory=list)


def enter_statement(session: Session, entry: ManualStatement) -> ManualEntryResult:
    """Write one hand-typed statement and its figures, or refuse and write nothing.

    Raises `EntryRefusedError` for anything the operator can fix by re-reading the page, and
    `UnreadableFigureError` (from `packages.common.units`) for a figure that will not parse.
    """
    security, company = _resolve_security(session, entry.security_id)
    document = _resolve_document(session, entry)
    _check_dates(entry)
    _check_reviewer(entry)
    multiplier = _check_scale(entry)

    template = chart_template_for(company.statement_template)
    permitted = _permitted_keys(session, entry, template)
    _check_keys(entry, permitted)
    _refuse_if_already_entered(session, entry, company.id)

    # Every figure is read before anything is written. `_read` raises on a numeral it cannot
    # parse, and until this loop ran ahead of the insert below, that raise left a statement
    # row with no line items behind it - exactly the half-entered state this function's
    # docstring promises never to produce.
    parsed = [(figure, *_read(figure, entry.scale, multiplier)) for figure in entry.figures]

    statement = Statement(
        filing_id=None,  # a typed statement cites its document, not an EDGAR accession
        company_id=company.id,
        statement_type=entry.statement_type,
        period_type=entry.period_type,
        period_start=entry.period_start,
        period_end=entry.period_end,
        fiscal_year=fiscal_year_of(entry.period_end, company.fiscal_year_end),
        calendar_year=entry.period_end.year,
        period_label=period_label(
            entry.period_type, fiscal_year_of(entry.period_end, company.fiscal_year_end)
        ),
        presentation_currency=entry.currency,
        # 1, not the scale's multiplier. `docs/08` §1.5: the figures below are already in
        # base units, and this column is provenance - "what the page was printed in" - not a
        # number for anyone downstream to multiply by again.
        presentation_multiplier=1,
        is_audited=entry.is_audited,
        is_consolidated=entry.is_consolidated,
        statement_template=template,
        chart_version=entry.chart_version,
        version=1,
        restatement_flag=False,
        known_as_of=entry.known_as_of,
        source_document_id=document.id,
    )
    session.add(statement)
    session.flush()

    result = ManualEntryResult(statement_id=statement.id)
    for figure, value, printed_value, item_multiplier in parsed:
        session.add(
            StatementLineItem(
                statement_id=statement.id,
                security_id=security.id,
                canonical_key=figure.canonical_key,
                chart_version=entry.chart_version,
                as_printed_label=None,  # the form types keys, not labels; P4's extractor does
                as_printed_value=printed_value,
                as_printed_scale=entry.scale,
                value=value,
                currency=entry.currency,
                unit_multiplier=item_multiplier,
                period_start=entry.period_start,
                period_end=entry.period_end,
                known_as_of=entry.known_as_of,
                version=1,
                restatement_flag=False,
                correction_type="none",
                source_document_id=document.id,
                page=figure.page,
                extraction_method=EXTRACTION_METHOD,
                # No confidence figure. A person read it; `confidence` is the extractor's
                # self-report and a hand-typed 1.0 would put a machine's word on a human's.
                confidence=None,
                reviewed_by=entry.reviewed_by,
            )
        )
        result.line_items_written += 1
        result.keys.append(figure.canonical_key)
        if value is None:
            result.figures_absent += 1
    session.flush()

    _log.info(
        "manual_statement_entered",
        statement_id=statement.id,
        security_id=security.id,
        period=f"{entry.period_type} {entry.period_end}",
        figures=result.line_items_written,
        absent=result.figures_absent,
        reviewed_by=entry.reviewed_by,
    )
    return result


def _read(
    figure: TypedFigure, scale: str, multiplier: int
) -> tuple[Decimal | None, str | None, int]:
    """One typed cell, as (value, what the page printed, the multiplier that was applied).

    The blank case is handled here and not by `to_base`, which refuses an empty string - and
    rightly, since an empty string is not a figure. For a *form* a blank field is the
    operator saying the line is not on the page, which is an absence and not an error.
    """
    printed = figure.printed.strip()
    if not printed:
        return None, None, multiplier
    if printed in _DASHES:
        # The page's own statement that there was nothing there. Keeping the dash is what
        # distinguishes it from a blank a year later.
        return None, printed, multiplier
    try:
        scaled = to_base(printed, scale=scale)
    except UnreadableFigureError as exc:
        raise UnreadableFigureError(f"{figure.canonical_key} on page {figure.page}: {exc}") from exc
    return scaled.value, scaled.as_printed_value, scaled.unit_multiplier


def _resolve_security(session: Session, security_id: int) -> tuple[Security, Company]:
    security = session.get(Security, security_id)
    if security is None:
        raise EntryRefusedError(f"security {security_id} does not exist")
    company = session.get(Company, security.company_id)
    if company is None:  # pragma: no cover - the FK makes this unreachable
        raise EntryRefusedError(f"security {security_id} has no company")
    return security, company


def _resolve_document(session: Session, entry: ManualStatement) -> SourceDocument:
    document = session.get(SourceDocument, entry.source_document_id)
    if document is None:
        raise EntryRefusedError(
            f"source document {entry.source_document_id} does not exist. Upload the report "
            f"first (P3.1) - a typed figure with no document is the untraceable figure "
            f"CLAUDE.md forbids."
        )
    for figure in entry.figures:
        if figure.page < 1:
            raise EntryRefusedError(
                f"{figure.canonical_key}: page {figure.page} is not a page number"
            )
        if document.page_count is not None and figure.page > document.page_count:
            raise EntryRefusedError(
                f"{figure.canonical_key} cites page {figure.page} of a document with "
                f"{document.page_count} pages. Either the page is wrong or the document is."
            )
    return document


def _check_dates(entry: ManualStatement) -> None:
    if entry.known_as_of < entry.period_end:
        raise EntryRefusedError(
            f"known_as_of {entry.known_as_of} precedes period_end {entry.period_end}. A "
            f"report cannot have been published before the period it covers ended."
        )
    if entry.period_start is not None and entry.period_start > entry.period_end:
        raise EntryRefusedError(
            f"period_start {entry.period_start} is after period_end {entry.period_end}"
        )


def _check_reviewer(entry: ManualStatement) -> None:
    if not entry.reviewed_by.strip():
        raise EntryRefusedError(
            "reviewed_by is empty. A hand-typed figure is only as good as the name attached "
            "to it (OPERATIONS.md §1.1 rule 4)."
        )
    if not entry.figures:
        raise EntryRefusedError("the entry carries no figures")
    seen: set[str] = set()
    for figure in entry.figures:
        if figure.canonical_key in seen:
            raise EntryRefusedError(
                f"{figure.canonical_key} appears twice. One figure per key per statement - "
                f"the `one_current_version` index would refuse the second anyway, and the "
                f"operator meant one of them."
            )
        seen.add(figure.canonical_key)


def _check_scale(entry: ManualStatement) -> int:
    try:
        return multiplier_for(entry.scale)
    except UnreadableFigureError as exc:
        raise EntryRefusedError(
            f"{entry.scale!r} is not a declared scale: {exc}. Read it off the statement's "
            f"own column heading."
        ) from exc


def _permitted_keys(session: Session, entry: ManualStatement, template: str) -> tuple[str, ...]:
    chart = load_chart(
        session,
        version=entry.chart_version,
        # The source system only selects which label mappings load. A typed figure arrives
        # as a canonical key already, so which one is immaterial here - what matters is the
        # account list, which is per chart version and not per source system.
        source_system="ng_ifrs_label",
    )
    return chart.keys_for(entry.statement_type, template)


def _check_keys(entry: ManualStatement, permitted: tuple[str, ...]) -> None:
    allowed = set(permitted)
    for figure in entry.figures:
        if figure.canonical_key not in allowed:
            raise EntryRefusedError(
                f"{figure.canonical_key!r} is not a key of the {entry.statement_type} "
                f"statement under chart {entry.chart_version}. A figure under an invented "
                f"key is a figure nothing will ever read."
            )


def _refuse_if_already_entered(session: Session, entry: ManualStatement, company_id: int) -> None:
    existing = session.execute(
        select(Statement.id, Statement.version)
        .where(Statement.company_id == company_id)
        .where(Statement.statement_type == entry.statement_type)
        .where(Statement.period_type == entry.period_type)
        .where(Statement.period_end == entry.period_end)
        .where(Statement.is_consolidated == entry.is_consolidated)
        .order_by(Statement.version.desc())
        .limit(1)
    ).first()
    if existing is not None:
        statement_id, version = existing
        raise EntryRefusedError(
            f"{entry.period_type} {entry.period_end} is already entered as statement "
            f"{statement_id} (version {version}). Changing a figure is a correction, not a "
            f"second entry: use scripts/correct_figure.py, which versions the statement, "
            f"carries the other figures forward and records whose mistake it was."
        )

"""The review queue, ordered by what is worth a reviewer's attention. P4.4.

`docs/03` P4.4 gives two instructions and a warning:

* *"Prioritise the queue by materiality. A wrong revenue figure matters more than a wrong
  note disclosure. A FIFO queue wastes your scarcest resource - reviewer attention - on
  trivia."*
* *"Track correction rate as a headline metric … if it isn't falling, the extractor isn't
  learning and something is wrong with the feedback loop."*

The warning behind both is `TEAM_BRIEF` Part 3 item 5's arithmetic: ~20 corrections per
filing across 25 companies filing quarterly is **about 2,000 corrections a year**, and one
reviewer is the ceiling on how much of the market the product can cover. Ordering the queue
is not a nicety; it is the only lever on that ceiling that does not involve hiring.

## There is no queue table, and that is deliberate

Nothing in `docs/08` defines one, and a queue is a *view* of work outstanding rather than a
record of fact. Materialising it would create a second place for the truth to live and a way
for the two to disagree - a row still queued after its figure was corrected, or a figure
flagged with nothing queued. So the queue is derived on read, from two sources:

* rows carrying `needs_review`, which the extractor sets when it is unsure;
* periods failing an identity in `packages/normalize/validation.py`.

Today the second is the only one with anything in it, and that is worth stating plainly: of
44,500 stored line items, **none** carries `needs_review`, because XBRL arrives structured
and confident. The queue's whole content right now is what validation found, including Bank
of America's 2008 balance sheet reporting no assets at all.

## How materiality is scored

Materiality in accounting is a *share of something*, never an absolute, because NGN 50m is
trivial to Dangote and fatal to a small insurer. So a figure is scored against its own
statement's anchor - total assets for a balance sheet, revenue for an income statement or
cash flow - and a figure with no anchor scores zero rather than guessing.

    priority = severity + share_of_anchor + required_bonus

Each term is separately legible, which matters more than the exact numbers: a reviewer who
disagrees with an ordering should be able to see which term caused it.

`severity` separates the two kinds of finding `validation.py` produces. An **impossible**
state - a part exceeding its whole, a going concern with no assets - has no innocent
reading and outranks a **disagreement**, which may only mean a chart key is narrower than an
identity assumed. An unexplained `needs_review` flag sits below both, because the extractor
saying "I am unsure" is weaker evidence than arithmetic saying "this cannot be".

## The correction rate, and whose mistakes it counts

`correction_type` distinguishes `restatement` - the company restating its own figures - from
`transcription` and `extraction`, which are ours (`docs/10` §2.10, and `OUR_ERRORS` in
`packages/normalize/corrections.py`). The headline metric counts only ours.

That is not pedantry. All 2,285 corrections in the database today are restatements, so a
metric that counted every `correction_type != 'none'` would report a 4.4% error rate for an
extractor that has not made a single mistake - and would keep reporting it, unfalling,
however well the extractor learned.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from decimal import Decimal

from sqlalchemy import Select, func, select
from sqlalchemy.orm import Session

from packages.common.models import ChartAccount, Company, Statement, StatementLineItem
from packages.normalize.corrections import OUR_ERRORS
from packages.normalize.validation import (
    IdentityResult,
    ValidationReport,
    validate_period,
)

__all__ = [
    "IMPOSSIBLE_IDENTITIES",
    "CorrectionRate",
    "QueueItem",
    "correction_rate",
    "review_queue",
]

#: Identities whose failure means a figure cannot be true, as opposed to figures that merely
#: disagree. Named by suffix because the declarative rules in `validation.py` generate their
#: own names and the list there is meant to grow - matching on shape keeps the two in step
#: without a second list to forget to update.
IMPOSSIBLE_IDENTITIES = ("_within_", "_is_positive", "_not_negative", "_less_")

#: What each kind of finding contributes before materiality is added.
SEVERITY_IMPOSSIBLE = Decimal(2)
SEVERITY_DISAGREEMENT = Decimal(1)
SEVERITY_FLAGGED = Decimal("0.5")

#: Added when the chart marks the key required. A missing or wrong figure on a required line
#: leaves the statement incomplete, which is a different problem from a wrong optional one.
REQUIRED_BONUS = Decimal("0.25")

#: What a figure's materiality is measured against, per statement type. Accounting
#: materiality is always a share of something; these are the conventional bases.
ANCHOR_KEYS: dict[str, str] = {
    "balance": "total_assets",
    "income": "revenue",
    "cashflow": "revenue",
}


def _is_impossible(result: IdentityResult) -> bool:
    return any(marker in result.name for marker in IMPOSSIBLE_IDENTITIES)


@dataclass(frozen=True)
class QueueItem:
    """One thing worth a reviewer's time, and why it is above the thing below it."""

    company_id: int
    company_name: str
    period_type: str
    period_end: dt.date
    #: The finding's own name - an identity, or `needs_review` for an extractor flag.
    finding: str
    detail: str
    #: None for a period-level finding that names no single key.
    canonical_key: str | None
    priority: Decimal
    severity: Decimal
    #: The figure as a share of its statement's anchor, 0 when there is nothing to divide by.
    share_of_anchor: Decimal
    is_required: bool

    @property
    def why(self) -> str:
        """One line a reviewer can read without opening anything else."""
        parts = [f"severity {self.severity}"]
        if self.share_of_anchor > 0:
            parts.append(f"{self.share_of_anchor:.1%} of the statement")
        if self.is_required:
            parts.append("required key")
        return f"{self.detail} [{', '.join(parts)}]"


@dataclass(frozen=True)
class CorrectionRate:
    """`docs/03` P4.4's headline metric: are our own errors falling?"""

    period_start: dt.date
    period_end: dt.date
    items_written: int
    #: Corrections of *our* mistakes. Restatements are excluded - see the module docstring.
    our_corrections: int
    restatements: int

    @property
    def rate(self) -> Decimal | None:
        """Our corrections over items written, or None when nothing was written.

        None rather than zero: a month with no extractions has no error rate, and reporting
        0% would put a reassuring point on a chart that is meant to be an early warning.
        """
        if self.items_written == 0:
            return None
        return Decimal(self.our_corrections) / Decimal(self.items_written)


def _required_keys(session: Session, chart_version: str) -> set[str]:
    return set(
        session.execute(
            select(ChartAccount.canonical_key)
            .where(ChartAccount.chart_version == chart_version)
            .where(ChartAccount.is_required)
        ).scalars()
    )


def _key_in(finding: str, required: set[str]) -> str | None:
    """The canonical key a generated identity name is about, if it names one.

    The declarative rules build names like `cash_within_total_assets`, so the subject is the
    longest known key the name starts with. Longest wins because `cash` is a prefix of
    nothing here but `total_assets` and `total_assets_is_positive` would otherwise both
    match `total_assets`.
    """
    candidates = [key for key in required if finding.startswith(key)]
    return max(candidates, key=len) if candidates else None


def _score(
    result: IdentityResult,
    *,
    anchors: dict[str, Decimal],
    required: set[str],
    figures: dict[str, tuple[str, Decimal | None]],
) -> QueueItem | None:
    severity = SEVERITY_IMPOSSIBLE if _is_impossible(result) else SEVERITY_DISAGREEMENT
    key = _key_in(result.name, set(figures) | required)
    share = Decimal(0)
    if key is not None and key in figures:
        statement_type, value = figures[key]
        anchor = anchors.get(statement_type)
        if anchor and value is not None:
            share = min(abs(value) / anchor, Decimal(1))
    is_required = key in required if key else False
    return QueueItem(
        company_id=0,
        company_name="",
        period_type="",
        period_end=dt.date.min,
        finding=result.name,
        detail=result.detail,
        canonical_key=key,
        priority=severity + share + (REQUIRED_BONUS if is_required else Decimal(0)),
        severity=severity,
        share_of_anchor=share,
        is_required=is_required,
    )


def _periods_with_statements(
    session: Session, *, since: dt.date | None, company_id: int | None
) -> Select[tuple[int, str, dt.date]]:
    query = (
        select(Statement.company_id, Statement.period_type, Statement.period_end)
        .where(Statement.superseded_by.is_(None))
        .distinct()
    )
    if since is not None:
        query = query.where(Statement.period_end >= since)
    if company_id is not None:
        query = query.where(Statement.company_id == company_id)
    return query.order_by(Statement.company_id, Statement.period_end)


def review_queue(
    session: Session,
    *,
    limit: int = 50,
    since: dt.date | None = None,
    company_id: int | None = None,
    chart_version: str = "v1",
) -> list[QueueItem]:
    """Everything outstanding, worst first.

    `limit` caps the returned list, not the work scanned: the ordering has to be global or
    it is not an ordering, so every period is scored and the top slice returned. That is the
    expensive choice and the right one - a queue that showed the worst of an arbitrary
    hundred periods would look identical and be useless.
    """
    required = _required_keys(session, chart_version)
    names: dict[int, str] = {
        row[0]: row[1] for row in session.execute(select(Company.id, Company.legal_name))
    }
    items: list[QueueItem] = []

    for company, period_type, period_end in session.execute(
        _periods_with_statements(session, since=since, company_id=company_id)
    ).all():
        report: ValidationReport = validate_period(
            session, company_id=company, period_type=period_type, period_end=period_end
        )
        if not report.failures:
            continue
        figures = {
            key: (statement_type, value)
            for statement_type, key, value in session.execute(
                select(
                    Statement.statement_type,
                    StatementLineItem.canonical_key,
                    StatementLineItem.value,
                )
                .join(StatementLineItem, StatementLineItem.statement_id == Statement.id)
                .where(Statement.company_id == company)
                .where(Statement.period_type == period_type)
                .where(Statement.period_end == period_end)
                .where(Statement.superseded_by.is_(None))
                .where(StatementLineItem.superseded_by.is_(None))
            ).all()
        }
        # Anchors come from the figures already loaded rather than a second query. One
        # round trip per period matters here: the ordering has to be global, so every
        # period is scored, and against a remote database the duplicate query was a
        # measurable share of the whole sweep.
        anchors = {
            statement_type: abs(value)
            for anchor_statement, anchor_key in ANCHOR_KEYS.items()
            for key, (statement_type, value) in figures.items()
            if key == anchor_key and statement_type == anchor_statement and value
        }
        for failure in report.failures:
            scored = _score(failure, anchors=anchors, required=required, figures=figures)
            if scored is None:
                continue
            items.append(
                QueueItem(
                    company_id=company,
                    company_name=names.get(company, str(company)),
                    period_type=period_type,
                    period_end=period_end,
                    finding=scored.finding,
                    detail=scored.detail,
                    canonical_key=scored.canonical_key,
                    priority=scored.priority,
                    severity=scored.severity,
                    share_of_anchor=scored.share_of_anchor,
                    is_required=scored.is_required,
                )
            )

    items.extend(_flagged_items(session, required=required, since=since, company_id=company_id))
    items.sort(key=lambda item: (-item.priority, item.company_name, item.period_end))
    return items[:limit]


def _flagged_items(
    session: Session,
    *,
    required: set[str],
    since: dt.date | None,
    company_id: int | None,
) -> list[QueueItem]:
    """Rows the extractor itself marked `needs_review`.

    Empty today - XBRL arrives confident - and written anyway, because the extractor P4.1
    builds is the thing that will fill it, and a queue that only learned to read this column
    after the extractor shipped would hide its first uncertain month.
    """
    query = (
        select(
            Statement.company_id,
            Company.legal_name,
            Statement.statement_type,
            Statement.period_type,
            Statement.period_end,
            StatementLineItem.canonical_key,
            StatementLineItem.value,
            StatementLineItem.confidence,
        )
        .join(StatementLineItem, StatementLineItem.statement_id == Statement.id)
        .join(Company, Company.id == Statement.company_id)
        .where(StatementLineItem.needs_review)
        .where(StatementLineItem.superseded_by.is_(None))
        .where(Statement.superseded_by.is_(None))
    )
    if since is not None:
        query = query.where(Statement.period_end >= since)
    if company_id is not None:
        query = query.where(Statement.company_id == company_id)

    items = []
    for (
        company,
        name,
        _statement_type,
        period_type,
        period_end,
        key,
        value,
        confidence,
    ) in session.execute(query).all():
        is_required = key in required
        stated = f"{value:,}" if value is not None else "nothing"
        items.append(
            QueueItem(
                company_id=company,
                company_name=name,
                period_type=period_type,
                period_end=period_end,
                finding="needs_review",
                detail=(
                    f"the extractor flagged {key} for review, reading {stated}"
                    + (f" at confidence {confidence}" if confidence is not None else "")
                ),
                canonical_key=key,
                priority=SEVERITY_FLAGGED + (REQUIRED_BONUS if is_required else Decimal(0)),
                severity=SEVERITY_FLAGGED,
                share_of_anchor=Decimal(0),
                is_required=is_required,
            )
        )
    return items


def correction_rate(session: Session, *, start: dt.date, end: dt.date) -> CorrectionRate:
    """Our own corrections against items written, over a window. `docs/03` P4.4's metric.

    Counted on `known_as_of` rather than `created_at`, so a month's figure describes the
    statements that became knowable then rather than whenever a backfill happened to run.
    """
    if start > end:
        raise ValueError(f"start {start} is after end {end}")
    written = (
        session.execute(
            select(func.count())
            .select_from(StatementLineItem)
            .where(StatementLineItem.known_as_of >= start)
            .where(StatementLineItem.known_as_of <= end)
        ).scalar_one()
        or 0
    )
    ours = (
        session.execute(
            select(func.count())
            .select_from(StatementLineItem)
            .where(StatementLineItem.known_as_of >= start)
            .where(StatementLineItem.known_as_of <= end)
            .where(StatementLineItem.correction_type.in_(OUR_ERRORS))
        ).scalar_one()
        or 0
    )
    restated = (
        session.execute(
            select(func.count())
            .select_from(StatementLineItem)
            .where(StatementLineItem.known_as_of >= start)
            .where(StatementLineItem.known_as_of <= end)
            .where(StatementLineItem.correction_type == "restatement")
        ).scalar_one()
        or 0
    )
    return CorrectionRate(
        period_start=start,
        period_end=end,
        items_written=written,
        our_corrections=ours,
        restatements=restated,
    )

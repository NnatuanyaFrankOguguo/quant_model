"""The point-in-time accessor for statement figures. `docs/01` §5, `docs/10` §2.9.

**The decision date is a mandatory argument.** `docs/01` §5 chose this over convention and
over database views: feature construction must never read a plain "latest value", and the
way to make forgetting the date impossible is to make it a `TypeError` at the call rather
than a wrong number in a results table. There is no default of "now". Ask for today if you
mean today.

The query is `docs/10` §2.9's corrected form, which keeps every period rather than
collapsing a security to one row: for each `(canonical_key, period_type, period_end)`, the
latest vintage — highest `known_as_of`, then highest `version` — whose `known_as_of` is on
or before the decision date. A restated FY2024 is returned as the *original* figure on any
decision date before the restatement was filed, which is the entire mechanism that keeps a
backtest honest.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from packages.common.models import Statement, StatementLineItem

__all__ = ["LineItemAsKnown", "line_items_as_known_on"]


@dataclass(frozen=True)
class LineItemAsKnown:
    security_id: int
    canonical_key: str
    statement_type: str
    period_type: str
    period_start: dt.date | None
    period_end: dt.date
    fiscal_year: int
    period_label: str
    value: Decimal | None
    currency: str
    known_as_of: dt.date
    version: int
    statement_id: int
    source_document_id: int


def line_items_as_known_on(
    session: Session,
    *,
    security_id: int,
    decision_date: dt.date,
    consolidated: bool = True,
    canonical_keys: tuple[str, ...] | None = None,
) -> list[LineItemAsKnown]:
    """Every figure for one security as it was known on `decision_date`.

    One row per `(canonical_key, period_type, period_end)`: the vintage a reader on that
    date would have had. Nothing filed after the date is visible, including restatements.
    """
    if not isinstance(decision_date, dt.date):
        raise TypeError("decision_date must be a date - there is no default of today")

    query = (
        select(
            StatementLineItem.security_id,
            StatementLineItem.canonical_key,
            Statement.statement_type,
            Statement.period_type,
            StatementLineItem.period_start,
            StatementLineItem.period_end,
            Statement.fiscal_year,
            Statement.period_label,
            StatementLineItem.value,
            StatementLineItem.currency,
            StatementLineItem.known_as_of,
            StatementLineItem.version,
            StatementLineItem.statement_id,
            StatementLineItem.source_document_id,
        )
        .join(Statement, Statement.id == StatementLineItem.statement_id)
        .where(StatementLineItem.security_id == security_id)
        .where(StatementLineItem.known_as_of <= decision_date)
        .where(Statement.is_consolidated.is_(consolidated))
        .distinct(
            StatementLineItem.canonical_key,
            Statement.period_type,
            StatementLineItem.period_end,
        )
        .order_by(
            StatementLineItem.canonical_key,
            Statement.period_type,
            StatementLineItem.period_end,
            StatementLineItem.known_as_of.desc(),
            StatementLineItem.version.desc(),
        )
    )
    if canonical_keys:
        query = query.where(StatementLineItem.canonical_key.in_(canonical_keys))
    return [LineItemAsKnown(*row) for row in session.execute(query).all()]

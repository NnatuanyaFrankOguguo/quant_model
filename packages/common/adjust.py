"""Adjusted prices, computed on read, from what was known on the decision date. TG2, TG12.

`docs/08` §2.4 and `docs/10` §2.6: there is no stored adjusted price, because a stored one
is a single global vintage - a split announced after a backtest's decision date would rewrite
history the backtest had already consumed, and nothing would raise. So the adjustment is a
function of three things: the security, the bar's date, and the date the reader is standing
on. A call without a decision date is a TypeError, not a default.

The worked example (`docs/08` §2.4): Apple closed at 499.23 on 2020-08-28 and split 4-for-1
on 2020-08-31. Read on 2020-09-01 or later, the 08-28 close is 124.8075 - comparable with
the 129.04 of the 31st. Read on 2020-08-30, before the split was on the record, it is
499.23, exactly as the market saw it. Both are right; the decision date says which.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from packages.common.models import AdjustmentFactor, PriceHistory

__all__ = ["AdjustedClose", "adjusted_close", "cumulative_factor", "factors_known"]


@dataclass(frozen=True)
class AdjustedClose:
    date: dt.date
    close_raw: Decimal  # as traded
    factor: Decimal  # product of every applicable factor known on the decision date
    close_adjusted: Decimal  # close_raw * factor, for comparison across the actions
    actions_applied: int
    known_as_of: dt.date  # the bar's vintage


def factors_known(
    session: Session, *, security_id: int, decision_date: dt.date
) -> list[tuple[dt.date, Decimal]]:
    """Every (ex_date, factor) known on the decision date, at its newest vintage per action."""
    rows = session.execute(
        select(
            AdjustmentFactor.action_id,
            AdjustmentFactor.ex_date,
            AdjustmentFactor.factor,
            AdjustmentFactor.known_as_of,
        )
        .where(AdjustmentFactor.security_id == security_id)
        .where(AdjustmentFactor.known_as_of <= decision_date)
        .order_by(AdjustmentFactor.action_id, AdjustmentFactor.known_as_of)
    ).all()
    newest: dict[int, tuple[dt.date, Decimal]] = {}
    for action_id, ex_date, factor, _known in rows:
        newest[action_id] = (ex_date, factor)  # ordered by vintage: the last one wins
    return sorted(newest.values())


def cumulative_factor(on: dt.date, factors: list[tuple[dt.date, Decimal]]) -> tuple[Decimal, int]:
    """The multiplier for a bar on `on`: every factor whose ex-date is after it. Pure."""
    product = Decimal(1)
    applied = 0
    for ex_date, factor in factors:
        if ex_date > on:
            product *= factor
            applied += 1
    return product, applied


def adjusted_close(
    session: Session, *, security_id: int, date: dt.date, decision_date: dt.date
) -> AdjustedClose | None:
    """The bar on `date` as known on `decision_date`, adjusted by the actions known then.

    None when no bar for that date was known. The raw close is never touched: the adjusted
    figure is derived beside it, and both are returned so a reader can see the factor.
    """
    if not isinstance(decision_date, dt.date):
        raise TypeError("decision_date must be a date - there is no default of today")
    bar = session.execute(
        select(PriceHistory.close_raw, PriceHistory.known_as_of)
        .where(PriceHistory.security_id == security_id)
        .where(PriceHistory.date == date)
        .where(PriceHistory.known_as_of <= decision_date)
        .order_by(PriceHistory.known_as_of.desc())
        .limit(1)
    ).first()
    if bar is None:
        return None
    close_raw, known_as_of = bar
    factor, applied = cumulative_factor(
        date, factors_known(session, security_id=security_id, decision_date=decision_date)
    )
    return AdjustedClose(
        date=date,
        close_raw=close_raw,
        factor=factor,
        close_adjusted=close_raw * factor,
        actions_applied=applied,
        known_as_of=known_as_of,
    )

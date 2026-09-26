"""Currency conversion, at the rate that was true on a date and knowable on another. TG2.

`OPERATIONS.md` §1.3: **every conversion takes a date**, and a conversion function without a
date parameter is a defect. This module has two, and neither has a default:

* `on` - the date the money is being measured at. A 2023 Naira figure is converted at the
  2023 rate, not today's; the official USD/NGN went from 907.1 to 1,535.0 in twelve months,
  so using the wrong one is wrong by a multiple rather than by a rounding error.
* `decision_date` - the date the reader is standing on, so a rate published after that date
  is invisible. The same rule as `packages/common/pit.py` and `packages/common/adjust.py`.

**Nothing is invented.** A rate is looked up on or before `on` and must be no older than
`max_staleness_days` - enough to carry a Friday rate across a weekend or a public holiday,
not enough to quietly convert a June figure at February's rate. Outside that, the answer is
None, and the caller shows a blank rather than a number nobody can defend.

**The inverse is arithmetic, not a second rate.** NGN->USD is served by inverting the stored
USD/NGN rate. That is what the pair means; it is not a claim that anyone quoted the inverse,
and `FxRateRef.inverted` says which happened.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from decimal import Decimal, localcontext

from sqlalchemy import select
from sqlalchemy.orm import Session

from packages.common.models import FxRate

__all__ = ["Converted", "FxRateRef", "NFEM_OFFICIAL", "convert", "rate_on"]

#: The CBN's official mid rate, and the only `rate_type` with a source today.
NFEM_OFFICIAL = "nfem_official"

#: How far back a rate may be carried to cover days the market did not quote: a weekend, a
#: public holiday, a closed week. Beyond this the honest answer is "no rate", not a stale one.
DEFAULT_MAX_STALENESS_DAYS = 7

#: Places kept when a stored pair is inverted. Twelve, not eight, and the reason is
#: reproducibility: the rate returned is the rate *applied*, so a reader can multiply the
#: figure by the rate on screen and get the figure on screen. At eight places 1/907.1 is
#: 0.00110241, which costs five dollars on a billion naira; at twelve it costs none that
#: survives rounding to the cent.
_PLACES = Decimal("0.000000000001")


@dataclass(frozen=True)
class FxRateRef:
    """The rate a conversion used, with everything needed to defend it."""

    base_currency: str
    quote_currency: str
    rate_type: str
    rate: Decimal  # quote units per one base unit, as applied (inverted where noted)
    as_of_date: dt.date
    known_as_of: dt.date
    source_document_id: int
    inverted: bool  # True when the stored pair was the other way round
    age_days: int  # how far the rate was carried to reach `on`


@dataclass(frozen=True)
class Converted:
    amount: Decimal
    from_currency: str
    to_currency: str
    rate: FxRateRef


def rate_on(
    session: Session,
    *,
    base: str,
    quote: str,
    on: dt.date,
    decision_date: dt.date,
    rate_type: str = NFEM_OFFICIAL,
    max_staleness_days: int = DEFAULT_MAX_STALENESS_DAYS,
) -> FxRateRef | None:
    """The rate for `base`/`quote` on `on`, as known on `decision_date`. None if there is none.

    The newest rate dated on or before `on` at its newest vintage known by `decision_date`.
    The stored pair is used either way round; an inverted answer says so.
    """
    if not isinstance(on, dt.date) or not isinstance(decision_date, dt.date):
        raise TypeError("both `on` and `decision_date` are required dates - there is no default")
    base, quote = base.upper(), quote.upper()
    if base == quote:
        raise ValueError(f"{base} to {quote} is not a conversion")

    direct = _newest(session, base, quote, on, decision_date, rate_type)
    inverse = _newest(session, quote, base, on, decision_date, rate_type)
    # Prefer whichever was quoted closer to `on`; a tie goes to the direct quote.
    best = (
        direct if direct is not None and (inverse is None or direct[0] >= inverse[0]) else inverse
    )
    if best is None:
        return None
    as_of, known, rate, document_id = best
    age = (on - as_of).days
    if age > max_staleness_days:
        return None
    inverted = best is inverse
    if inverted:
        with localcontext() as context:
            context.prec = 34
            rate = (Decimal(1) / rate).quantize(_PLACES)
    return FxRateRef(
        base_currency=base,
        quote_currency=quote,
        rate_type=rate_type,
        rate=rate,
        as_of_date=as_of,
        known_as_of=known,
        source_document_id=document_id,
        inverted=inverted,
        age_days=age,
    )


def convert(
    session: Session,
    amount: Decimal,
    *,
    from_currency: str,
    to_currency: str,
    on: dt.date,
    decision_date: dt.date,
    rate_type: str = NFEM_OFFICIAL,
    max_staleness_days: int = DEFAULT_MAX_STALENESS_DAYS,
) -> Converted | None:
    """`amount` in `from_currency`, expressed in `to_currency` at the rate true on `on`.

    None when no rate close enough to `on` was known on `decision_date` - never an
    unconverted number wearing the wrong currency's name.
    """
    if from_currency.upper() == to_currency.upper():
        raise ValueError(f"{from_currency} to {to_currency} is not a conversion")
    rate = rate_on(
        session,
        base=from_currency,
        quote=to_currency,
        on=on,
        decision_date=decision_date,
        rate_type=rate_type,
        max_staleness_days=max_staleness_days,
    )
    if rate is None:
        return None
    return Converted(
        amount=amount * rate.rate,
        from_currency=from_currency.upper(),
        to_currency=to_currency.upper(),
        rate=rate,
    )


def _newest(
    session: Session,
    base: str,
    quote: str,
    on: dt.date,
    decision_date: dt.date,
    rate_type: str,
) -> tuple[dt.date, dt.date, Decimal, int] | None:
    row = session.execute(
        select(
            FxRate.as_of_date,
            FxRate.known_as_of,
            FxRate.rate,
            FxRate.source_document_id,
        )
        .where(FxRate.base_currency == base)
        .where(FxRate.quote_currency == quote)
        .where(FxRate.rate_type == rate_type)
        .where(FxRate.as_of_date <= on)
        .where(FxRate.known_as_of <= decision_date)
        .order_by(FxRate.as_of_date.desc(), FxRate.known_as_of.desc())
        .limit(1)
    ).first()
    return (row[0], row[1], row[2], row[3]) if row else None

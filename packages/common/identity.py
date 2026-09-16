"""Which security a ticker meant on a date. TG2, `OPERATIONS.md` §1.4.

**The bug this module exists to prevent.** Guaranty Trust Bank became GTCO on 2021-08-01,
and Nigerian corporate reorganisations are common. If the ticker is the join key, a rename
silently joins one company's new prices onto another company's old history: the series is
wrong, plausible, and already feeding a ratio. Nothing raises. So `securities.id` is the
permanent key and a ticker is a **time-bounded attribute** of it.

`OPERATIONS.md` §1.4 states the rule this module implements:

> All ticker resolution goes through a single `resolve_security(id_type, value, as_of_date)`
> function; no `WHERE ticker = ?` anywhere else in the codebase.

`tests/unit/test_identity.py::test_only_this_module_queries_the_identity_table` enforces
the second half by walking the AST of every module in the repository, so the rule fails the
build rather than relying on review.

**Every lookup takes a date, and there is no default.** The same discipline as
`packages/common/pit.py`, `adjust.py` and `fx.py`. `resolve_security(value="GUARANTY",
as_of=2020-01-01)` finds the bank; the same call with today's date finds nothing, because
that ticker no longer identifies anything. A resolver without a date can only answer for
the present, which is the wrong answer to every historical question a backtest asks.

**`valid_to` is inclusive** - the last day the identifier was valid. `docs/08` §2.1's
sample runs GUARANTY to 2021-07-31 and starts GTCO on 2021-08-01, which is gap-free only
under that reading. Migration 0018 converts it to an exclusive bound once, inside the
exclusion constraint, so this module and the database agree on the boundary day.

**Ambiguity raises rather than guesses.** Migration 0018's `no_overlapping_ids` makes
resolution provably single-valued *per exchange*. Across exchanges it cannot: NGX and
NASDAQ may both list a ticker of the same string, which is a real listing, not a defect.
Given no `exchange`, a value matching on two exchanges raises
`AmbiguousIdentifierError` instead of picking one, because picking one is the silent
merge this module was written to stop.
Today nothing collides across the three registered exchanges; P3's Nigerian load is when
that can change, and the fix then is to pass the exchange, not to loosen this.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass

from sqlalchemy import Subquery, or_, select
from sqlalchemy.orm import Session

from packages.common.models import Exchange, SecurityIdentifier

__all__ = [
    "AmbiguousIdentifierError",
    "CIK",
    "ID_TYPES",
    "ResolvedIdentifier",
    "TICKER",
    "has_primary_ticker",
    "identifier_exists",
    "primary_tickers",
    "resolve_security",
]

#: The identifier types migration 0018's `identifier_type_is_known` CHECK admits.
#: `docs/10` §2.11 restored `cik`, `lei` and `figi`, which `docs/08` §2.1 had dropped.
ID_TYPES = frozenset({"ticker", "isin", "cusip", "sedol", "cik", "lei", "figi"})

#: The two types in use today. A ticker is exchange-scoped; a CIK is global.
TICKER = "ticker"
CIK = "cik"


class AmbiguousIdentifierError(LookupError):
    """One value, one date, two exchanges. Naming them is the answer; choosing is not."""


@dataclass(frozen=True)
class ResolvedIdentifier:
    """The identifier row that matched, with everything needed to defend the match."""

    security_id: int
    id_type: str
    id_value: str
    exchange_id: int | None  # NULL for the global types: ISIN, CUSIP, SEDOL, CIK, LEI, FIGI
    valid_from: dt.date
    valid_to: dt.date | None  # NULL = still current; otherwise the last day it was valid
    is_primary: bool
    source: str | None


def resolve_security(
    session: Session,
    *,
    value: str,
    as_of: dt.date,
    id_type: str = TICKER,
    exchange: str | None = None,
) -> ResolvedIdentifier | None:
    """The security `value` identified on `as_of`, or None if it identified nothing then.

    `exchange` is an exchange code (`'NGX'`, `'NASDAQ'`, `'NYSE'`) and scopes a ticker to
    one market. Omitting it searches every exchange and raises
    `AmbiguousIdentifierError` when more than one answers, rather than returning
    whichever row sorted first.
    """
    if id_type not in ID_TYPES:
        raise ValueError(f"{id_type!r} is not an identifier type: {sorted(ID_TYPES)}")
    if not isinstance(as_of, dt.date):
        raise TypeError(
            "`as_of` is a required date - a resolver without one answers only for today"
        )
    rows = _matching(
        session, id_type=id_type, value=_normalise(value), as_of=as_of, exchange=exchange
    )
    if not rows:
        return None
    if len(rows) > 1:
        raise AmbiguousIdentifierError(
            f"{value!r} identified {len(rows)} securities on {as_of.isoformat()} "
            f"(exchange ids {sorted(str(r.exchange_id) for r in rows)}). "
            "Pass `exchange=` to say which market is meant."
        )
    return rows[0]


def identifier_exists(
    session: Session,
    *,
    value: str,
    id_type: str,
    exchange: str | None = None,
) -> bool:
    """Whether this identifier has **ever** been recorded, on any date.

    A different question from `resolve_security`, and the reason it takes no date: a writer
    asking "have I stored this predecessor CIK already" is asking about the table, not about
    what was true on a day. Resolution is the dated question and has a date.
    """
    if id_type not in ID_TYPES:
        raise ValueError(f"{id_type!r} is not an identifier type: {sorted(ID_TYPES)}")
    query = (
        select(SecurityIdentifier.security_id)
        .where(SecurityIdentifier.id_type == id_type)
        .where(SecurityIdentifier.id_value == _normalise(value))
        .limit(1)
    )
    if exchange is not None:
        query = query.join(Exchange, Exchange.id == SecurityIdentifier.exchange_id).where(
            Exchange.code == exchange
        )
    return session.execute(query).first() is not None


def has_primary_ticker(session: Session, *, security_id: int) -> bool:
    """Whether this security already has a current primary ticker.

    A writer's question: the first ticker EDGAR lists for a registrant is its common stock,
    so the first one inserted for a security is the primary. Asking first keeps
    `one_primary_ticker_per_security` a confirmation rather than the error path.
    """
    row = session.execute(
        select(SecurityIdentifier.id)
        .where(SecurityIdentifier.security_id == security_id)
        .where(SecurityIdentifier.id_type == TICKER)
        .where(SecurityIdentifier.valid_to.is_(None))
        .where(SecurityIdentifier.is_primary)
        .limit(1)
    ).first()
    return row is not None


def primary_tickers() -> Subquery:
    """`(security_id, ticker)` for each security's primary current ticker, one row each.

    EDGAR lists every ticker a registrant has - JPMorgan's exchange-traded notes, Bank of
    America's sixteen preferred series - and each is a current identifier of the same
    security. Exactly one of them is the common stock, and `is_primary` says which.

    Before migration 0018 the caller picked it with `min(id)`, which worked only because
    EDGAR happens to list common stock first and it happened to be inserted first.
    `one_primary_ticker_per_security` makes it a single guaranteed row instead of an
    ordering accident, and returning the subquery from here means a caller that needs the
    ticker string joins to this rather than reaching into the identifier table itself.
    """
    return (
        select(
            SecurityIdentifier.security_id.label("security_id"),
            SecurityIdentifier.id_value.label("ticker"),
        )
        .where(SecurityIdentifier.id_type == TICKER)
        .where(SecurityIdentifier.valid_to.is_(None))
        .where(SecurityIdentifier.is_primary)
        .subquery()
    )


def _normalise(value: str) -> str:
    """Tickers are stored upper-case and unpadded; a CIK is stored zero-padded to ten."""
    return value.strip().upper()


def _matching(
    session: Session,
    *,
    id_type: str,
    value: str,
    as_of: dt.date,
    exchange: str | None,
) -> list[ResolvedIdentifier]:
    """Every identifier row whose validity interval contains `as_of`. `valid_to` inclusive."""
    query = (
        select(
            SecurityIdentifier.security_id,
            SecurityIdentifier.id_type,
            SecurityIdentifier.id_value,
            SecurityIdentifier.exchange_id,
            SecurityIdentifier.valid_from,
            SecurityIdentifier.valid_to,
            SecurityIdentifier.is_primary,
            SecurityIdentifier.source,
        )
        .where(SecurityIdentifier.id_type == id_type)
        .where(SecurityIdentifier.id_value == value)
        .where(SecurityIdentifier.valid_from <= as_of)
        .where(or_(SecurityIdentifier.valid_to.is_(None), SecurityIdentifier.valid_to >= as_of))
    )
    if exchange is not None:
        query = query.join(Exchange, Exchange.id == SecurityIdentifier.exchange_id).where(
            Exchange.code == exchange
        )
    return [ResolvedIdentifier(*row) for row in session.execute(query).all()]

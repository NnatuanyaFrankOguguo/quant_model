"""Financial ratios and valuation multiples, from canonical line items and a price.

`docs/08` §6 gives the signature and `docs/10` §6.6 the reason it takes a price and a share
count: without them no multiple can come out, and multiples are what a reader opens a stock
page to see. Three tiers there; tier 1 (trailing multiples) and the profitability,
return, leverage and liquidity ratios live here. Tier 3 — forward multiples — needs a
forecast the user supplies (P6) and is deliberately absent.

**Every ratio is always present in the output**, as a value or as None, so a caller can tell
"not applicable" from "we forgot to pass a price". None means an input was missing or the
ratio is undefined for these figures: a divisor of zero, a P/E on a loss, an EV/EBITDA on
negative EBITDA. Never 0, never infinity, never a sign-flipped number that looks like a
valuation and is not.

**`shares` must be the count as of the price date** (`docs/08` §2.14 #49), never today's. A
bonus issue changes the denominator with no cash moving; today's count against last year's
price is a silently wrong multiple. `decision_date` is mandatory for the same reason the
point-in-time accessor's is: the caller has to have thought about *when*.

Sign conventions follow chart v0.1: `capex`, `dividends_paid` and `buybacks` are positive
outflows; `cost_of_revenue` and `interest_expense` are positive costs; profits are signed.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Mapping
from decimal import Decimal, DivisionByZero, InvalidOperation

__all__ = ["RATIO_KEYS", "compute_ratios"]

#: Every key the function returns, in display order. Always all of them.
RATIO_KEYS: tuple[str, ...] = (
    # profitability
    "gross_margin",
    "operating_margin",
    "net_margin",
    "fcf_margin",
    # returns
    "roe",
    "roa",
    # leverage and liquidity
    "current_ratio",
    "debt_to_equity",
    "liabilities_to_assets",
    "interest_coverage",
    # absolute derived figures
    "free_cash_flow",
    "ebitda",
    "net_debt",
    # per share
    "eps",
    "book_value_per_share",
    "fcf_per_share",
    # multiples - need price and shares
    "market_cap",
    "enterprise_value",
    "pe",
    "pb",
    "ps",
    "ev_sales",
    "ev_ebitda",
    "earnings_yield",
    "fcf_yield",
    "dividend_yield",
)


def compute_ratios(
    items: Mapping[str, Decimal | None],
    *,
    price: Decimal | None = None,
    shares: Decimal | None = None,
    decision_date: dt.date,
) -> dict[str, Decimal | None]:
    """Ratios from one period's line items. Any ratio with a null input is None.

    `items` is canonical key → value for one statement period (income, balance and cash
    flow keys together). `price` and `shares` are as of the price date; without them the
    multiples and per-share figures are None, not omitted.
    """
    if not isinstance(decision_date, dt.date):
        raise TypeError("decision_date must be a date - there is no default of today")

    get = items.get
    revenue = get("revenue")
    gross_profit = get("gross_profit")
    operating_profit = get("operating_profit")
    profit = get("profit_after_tax")
    total_assets = get("total_assets")
    total_liabilities = get("total_liabilities")
    total_equity = get("total_equity")
    current_assets = get("current_assets")
    current_liabilities = get("current_liabilities")
    cash = get("cash")
    long_term_debt = get("long_term_debt")
    cash_from_ops = get("cash_from_ops")
    capex = get("capex")
    depreciation = get("depreciation_amortisation")
    interest_expense = get("interest_expense")
    dividends_paid = get("dividends_paid")

    free_cash_flow = _sub(cash_from_ops, capex)
    ebitda = _add(operating_profit, depreciation)
    net_debt = _sub(long_term_debt, cash)
    market_cap = _mul(price, shares)
    enterprise_value = _add(market_cap, net_debt)

    return {
        "gross_margin": _div(gross_profit, revenue),
        "operating_margin": _div(operating_profit, revenue),
        "net_margin": _div(profit, revenue),
        "fcf_margin": _div(free_cash_flow, revenue),
        "roe": _div(profit, total_equity),
        "roa": _div(profit, total_assets),
        "current_ratio": _div(current_assets, current_liabilities),
        "debt_to_equity": _div(long_term_debt, total_equity),
        "liabilities_to_assets": _div(total_liabilities, total_assets),
        "interest_coverage": _div(operating_profit, interest_expense),
        "free_cash_flow": free_cash_flow,
        "ebitda": ebitda,
        "net_debt": net_debt,
        "eps": _div(profit, shares),
        "book_value_per_share": _div(total_equity, shares),
        "fcf_per_share": _div(free_cash_flow, shares),
        "market_cap": market_cap,
        "enterprise_value": enterprise_value,
        # A multiple on a loss or on negative book value is not a small or negative
        # multiple; it is not meaningful, and None is the only honest answer.
        "pe": _div(market_cap, profit) if _positive(profit) else None,
        "pb": _div(market_cap, total_equity) if _positive(total_equity) else None,
        "ps": _div(market_cap, revenue) if _positive(revenue) else None,
        "ev_sales": _div(enterprise_value, revenue) if _positive(revenue) else None,
        "ev_ebitda": _div(enterprise_value, ebitda) if _positive(ebitda) else None,
        "earnings_yield": _div(profit, market_cap),
        "fcf_yield": _div(free_cash_flow, market_cap),
        "dividend_yield": _div(dividends_paid, market_cap),
    }


def _positive(value: Decimal | None) -> bool:
    return value is not None and value > 0


def _add(a: Decimal | None, b: Decimal | None) -> Decimal | None:
    return None if a is None or b is None else a + b


def _sub(a: Decimal | None, b: Decimal | None) -> Decimal | None:
    return None if a is None or b is None else a - b


def _mul(a: Decimal | None, b: Decimal | None) -> Decimal | None:
    return None if a is None or b is None else a * b


def _div(numerator: Decimal | None, denominator: Decimal | None) -> Decimal | None:
    """None on a missing input or a zero divisor. Never raises, never returns infinity."""
    if numerator is None or denominator is None or denominator == 0:
        return None
    try:
        return numerator / denominator
    except (DivisionByZero, InvalidOperation):
        return None

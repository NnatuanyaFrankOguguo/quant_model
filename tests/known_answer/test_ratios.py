"""P2 checks 5 and 7 — ratios against `ratios_worksheet.md`, computed by hand."""

from __future__ import annotations

import datetime as dt
from decimal import Decimal

import pytest

from packages.valuation.ratios import RATIO_KEYS, compute_ratios

D = Decimal
DECISION = dt.date(2026, 9, 13)

APPLE_FY2025 = {
    "revenue": D(416_161),
    "cost_of_revenue": D(220_960),
    "gross_profit": D(195_201),
    "operating_profit": D(133_050),
    "profit_after_tax": D(112_010),
    "total_assets": D(359_241),
    "total_liabilities": D(285_508),
    "total_equity": D(73_733),
    "current_assets": D(147_957),
    "current_liabilities": D(165_631),
    "cash": D(35_934),
    "long_term_debt": D(78_328),
    "cash_from_ops": D(111_482),
    "capex": D(12_715),
    "depreciation_amortisation": D(11_698),
    "dividends_paid": D(15_421),
    "interest_expense": None,
}
PRICE = D("255.46")
SHARES = D(14_840)


def _close(actual: Decimal | None, expected: str, places: int = 6) -> bool:
    assert actual is not None, "expected a value, got None"
    return abs(actual - D(expected)) < D(10) ** -places


def test_every_ratio_key_is_always_present() -> None:
    with_price = compute_ratios(APPLE_FY2025, price=PRICE, shares=SHARES, decision_date=DECISION)
    without = compute_ratios(APPLE_FY2025, decision_date=DECISION)
    assert tuple(with_price) == RATIO_KEYS
    assert tuple(without) == RATIO_KEYS


def test_apple_fy2025_matches_the_worksheet() -> None:
    r = compute_ratios(APPLE_FY2025, price=PRICE, shares=SHARES, decision_date=DECISION)
    assert _close(r["gross_margin"], "0.469052")
    assert _close(r["operating_margin"], "0.319708")
    assert _close(r["net_margin"], "0.269151")
    assert _close(r["roe"], "1.519130")
    assert _close(r["roa"], "0.311796")
    assert _close(r["current_ratio"], "0.893293")
    assert _close(r["debt_to_equity"], "1.062319")
    assert _close(r["liabilities_to_assets"], "0.794753")
    assert r["interest_coverage"] is None, "Apple no longer reports interest expense"
    assert r["free_cash_flow"] == D(98_767)
    assert _close(r["fcf_margin"], "0.237329")
    assert r["ebitda"] == D(144_748)
    assert r["net_debt"] == D(42_394)
    assert r["market_cap"] == D("3791026.4")
    assert r["enterprise_value"] == D("3833420.4")
    assert _close(r["eps"], "7.547844")
    assert _close(r["book_value_per_share"], "4.968531")
    assert _close(r["fcf_per_share"], "6.655458")
    assert _close(r["pe"], "33.845428")
    assert _close(r["pb"], "51.415600")
    assert _close(r["ps"], "9.109519")
    assert _close(r["ev_sales"], "9.211388")
    assert _close(r["ev_ebitda"], "26.483408")
    assert _close(r["earnings_yield"], "0.029546")
    assert _close(r["fcf_yield"], "0.026053")
    assert _close(r["dividend_yield"], "0.004068")


def test_earnings_yield_is_the_reciprocal_of_pe() -> None:
    r = compute_ratios(APPLE_FY2025, price=PRICE, shares=SHARES, decision_date=DECISION)
    assert r["pe"] is not None and r["earnings_yield"] is not None
    assert _close(D(1) / r["pe"], str(r["earnings_yield"]), places=9)


@pytest.mark.invariant
def test_check_7_no_price_means_every_multiple_is_none_and_nothing_else_changes() -> None:
    priced = compute_ratios(APPLE_FY2025, price=PRICE, shares=SHARES, decision_date=DECISION)
    unpriced = compute_ratios(APPLE_FY2025, decision_date=DECISION)
    multiples = (
        "market_cap",
        "enterprise_value",
        "eps",
        "book_value_per_share",
        "fcf_per_share",
        "pe",
        "pb",
        "ps",
        "ev_sales",
        "ev_ebitda",
        "earnings_yield",
        "fcf_yield",
        "dividend_yield",
    )
    for key in multiples:
        assert unpriced[key] is None, key
    for key in RATIO_KEYS:
        if key not in multiples:
            assert unpriced[key] == priced[key], key


@pytest.mark.invariant
def test_check_7_a_missing_input_makes_the_ratio_none_never_zero() -> None:
    items = dict(APPLE_FY2025, profit_after_tax=None)
    r = compute_ratios(items, price=PRICE, shares=SHARES, decision_date=DECISION)
    for key in ("net_margin", "roe", "roa", "eps", "pe", "earnings_yield"):
        assert r[key] is None, key
        assert r[key] != 0
    assert r["gross_margin"] is not None, "unrelated ratios are unaffected"


@pytest.mark.invariant
def test_check_7_a_loss_gives_no_pe_and_a_zero_divisor_gives_no_infinity() -> None:
    loss = dict(APPLE_FY2025, profit_after_tax=D(-1000))
    r = compute_ratios(loss, price=PRICE, shares=SHARES, decision_date=DECISION)
    assert r["pe"] is None, "a P/E on a loss is not a negative multiple; it is not meaningful"
    assert r["earnings_yield"] is not None and r["earnings_yield"] < 0

    no_equity = dict(APPLE_FY2025, total_equity=D(0))
    r = compute_ratios(no_equity, price=PRICE, shares=SHARES, decision_date=DECISION)
    for key in ("roe", "debt_to_equity", "pb"):
        assert r[key] is None, key
    assert r["book_value_per_share"] == 0, "zero equity over shares is zero - a value"


def test_decision_date_is_mandatory() -> None:
    with pytest.raises(TypeError):
        compute_ratios(APPLE_FY2025, price=PRICE, shares=SHARES)  # type: ignore[call-arg]
    with pytest.raises(TypeError):
        compute_ratios(APPLE_FY2025, decision_date="2026-09-13")  # type: ignore[arg-type]


def test_no_float_anywhere() -> None:
    r = compute_ratios(APPLE_FY2025, price=PRICE, shares=SHARES, decision_date=DECISION)
    assert all(v is None or isinstance(v, Decimal) for v in r.values())

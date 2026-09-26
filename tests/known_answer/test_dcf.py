"""P2 checks 6 and 14 — the DCF against `dcf_worksheet.md`, computed by hand."""

from __future__ import annotations

from decimal import Decimal

import pytest

from packages.valuation.dcf import DcfAssumptions, dcf

D = Decimal


def _case_a(**overrides: object) -> DcfAssumptions:
    base = {
        "base_free_cash_flow": D(100),
        "growth_rates": (D("0.10"), D("0.10"), D("0.10")),
        "discount_rate": D("0.10"),
        "terminal_growth": D("0.02"),
        "net_debt": D(50),
        "shares": D(10),
    }
    base.update(overrides)
    return DcfAssumptions(**base)  # type: ignore[arg-type]


def _close(actual: Decimal | None, expected: str, places: int = 3) -> bool:
    assert actual is not None
    return abs(actual - D(expected)) < D(10) ** -places


def test_case_a_matches_the_worksheet_line_by_line() -> None:
    result = dcf(_case_a())
    assert [round(v, 3) for v in result.projected_free_cash_flow] == [
        D("110.000"),
        D("121.000"),
        D("133.100"),
    ]
    assert all(_close(pv, "100.000") for pv in result.present_values)
    assert _close(result.sum_of_present_values, "300.000")
    assert _close(result.terminal_value, "1697.025")
    assert _close(result.present_value_of_terminal, "1275.000")
    assert _close(result.enterprise_value, "1575.000")
    assert _close(result.equity_value, "1525.000")
    assert _close(result.value_per_share, "152.500")
    assert _close(result.terminal_share_of_value, "0.809524", places=6)


def test_the_result_carries_the_assumptions_that_produced_it() -> None:
    """`docs/03` P2.4: the DCF returns the output *and* the inputs. Show the work."""
    assumptions = _case_a()
    result = dcf(assumptions)
    assert result.assumptions == assumptions
    assert len(result.discount_factors) == len(result.present_values) == 3


def test_check_14_a_100bp_change_moves_the_value_the_right_way_by_a_plausible_amount() -> None:
    at_ten = dcf(_case_a(discount_rate=D("0.10")))
    at_nine = dcf(_case_a(discount_rate=D("0.09")))
    assert _close(at_nine.value_per_share, "175.316")
    assert at_nine.value_per_share > at_ten.value_per_share  # type: ignore[operator]
    change = (at_nine.value_per_share - at_ten.value_per_share) / at_ten.value_per_share  # type: ignore[operator]
    assert D("0.14") < change < D("0.16"), "a 100 bp cut should lift the value by about 15 %"


def test_case_c_mid_year_convention() -> None:
    result = dcf(_case_a(mid_year=True))
    assert _close(result.sum_of_present_values, "314.643")
    assert _close(result.present_value_of_terminal, "1275.000")
    assert _close(result.enterprise_value, "1589.643")


def test_no_shares_means_no_per_share_figure_not_a_guess() -> None:
    result = dcf(_case_a(shares=None))
    assert result.value_per_share is None
    assert _close(result.equity_value, "1525.000")


def test_case_d_terminal_growth_at_or_above_the_discount_rate_is_refused() -> None:
    with pytest.raises(ValueError, match="must exceed terminal growth"):
        dcf(_case_a(terminal_growth=D("0.10")))
    with pytest.raises(ValueError, match="must exceed terminal growth"):
        dcf(_case_a(terminal_growth=D("0.12")))


def test_case_d_an_empty_projection_and_bad_shares_are_refused() -> None:
    with pytest.raises(ValueError, match="at least one projected year"):
        dcf(_case_a(growth_rates=()))
    with pytest.raises(ValueError, match="shares must be positive"):
        dcf(_case_a(shares=D(0)))


def test_the_model_is_deterministic() -> None:
    assert dcf(_case_a()) == dcf(_case_a())

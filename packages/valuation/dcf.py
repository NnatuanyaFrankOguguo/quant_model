"""A discounted-cash-flow model that runs on the user's assumptions and returns them.

`docs/03` P2.4: *the DCF takes assumptions as explicit inputs — growth, margin, WACC,
terminal growth — and never chooses them for the user. It returns the output and the inputs
that produced it.* That is `DcfAssumptions` in, `DcfResult` out, with every intermediate
number on the result so the work is shown (`CLAUDE.md`): the projected cash flows, each
discount factor, each present value, the terminal value and its share of the total.

The arithmetic is the textbook one and nothing else:

    FCF_t  = FCF_{t-1} × (1 + g_t)                       for t = 1..N
    DF_t   = 1 / (1 + r)^t          (or (1 + r)^(t - 0.5) with mid-year discounting)
    TV     = FCF_N × (1 + g_T) / (r - g_T)                Gordon growth, requires r > g_T
    EV     = Σ FCF_t × DF_t  +  TV × DF_N
    Equity = EV - net debt;  per share = Equity / shares

`terminal_share_of_value` is on the result because it is the diagnostic P2 check 14 asks
for: if a 100 bp change in the discount rate barely moves the answer, the terminal value is
probably wrong, and this number says how much of the answer *is* terminal value.

`Decimal` throughout (`docs/08` §1.6); the exponentiation is done by repeated
multiplication so a half-year exponent never routes through a float.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, localcontext

__all__ = ["DcfAssumptions", "DcfResult", "dcf"]

#: Working precision for the model's own arithmetic; the process-wide context is untouched.
_PRECISION = 34


@dataclass(frozen=True)
class DcfAssumptions:
    """Everything the model needs, supplied by the caller. Nothing is defaulted from data."""

    #: The starting free cash flow, in base currency units. The user's number.
    base_free_cash_flow: Decimal
    #: Growth applied to each projected year in turn, as fractions: (0.10, 0.08, 0.05).
    growth_rates: tuple[Decimal, ...]
    #: The discount rate (WACC), as a fraction: 0.09 for 9%.
    discount_rate: Decimal
    #: Perpetual growth after the projection, as a fraction. Must be below the discount rate.
    terminal_growth: Decimal
    #: Debt less cash at the valuation date; negative for a net cash position.
    net_debt: Decimal
    #: Diluted shares as of the valuation date, for the per-share figure.
    shares: Decimal | None = None
    #: Discount cash flows as if received mid-year rather than at year end.
    mid_year: bool = False

    def validate(self) -> None:
        if not self.growth_rates:
            raise ValueError("at least one projected year is required")
        if self.discount_rate <= self.terminal_growth:
            raise ValueError(
                f"discount rate {self.discount_rate} must exceed terminal growth "
                f"{self.terminal_growth}: the Gordon formula is undefined otherwise"
            )
        if self.discount_rate <= -1:
            raise ValueError("discount rate must be greater than -100%")
        if self.shares is not None and self.shares <= 0:
            raise ValueError("shares must be positive when given")


@dataclass(frozen=True)
class DcfResult:
    """The answer, and everything that produced it."""

    assumptions: DcfAssumptions
    projected_free_cash_flow: tuple[Decimal, ...]
    discount_factors: tuple[Decimal, ...]
    present_values: tuple[Decimal, ...]
    sum_of_present_values: Decimal
    terminal_value: Decimal
    present_value_of_terminal: Decimal
    enterprise_value: Decimal
    equity_value: Decimal
    value_per_share: Decimal | None
    #: PV of the terminal value as a fraction of enterprise value. High is not wrong, but it
    #: is the thing to look at when a WACC change barely moves the answer.
    terminal_share_of_value: Decimal | None


def dcf(assumptions: DcfAssumptions) -> DcfResult:
    """Run the model. Pure and deterministic; raises on assumptions that cannot be valued."""
    assumptions.validate()
    with localcontext() as context:
        context.prec = _PRECISION
        return _run(assumptions)


def _run(assumptions: DcfAssumptions) -> DcfResult:
    one = Decimal(1)
    r = assumptions.discount_rate
    horizon = len(assumptions.growth_rates)

    projected: list[Decimal] = []
    fcf = assumptions.base_free_cash_flow
    for growth in assumptions.growth_rates:
        fcf = fcf * (one + growth)
        projected.append(fcf)

    factors: list[Decimal] = []
    for year in range(1, horizon + 1):
        exponent = year
        factor = one / _power(one + r, exponent)
        if assumptions.mid_year:
            factor = factor * (one + r).sqrt()  # (1+r)^-(t-0.5) = (1+r)^-t × (1+r)^0.5
        factors.append(factor)

    present_values = [cash * factor for cash, factor in zip(projected, factors, strict=True)]
    sum_pv = sum(present_values, Decimal(0))

    terminal_value = (
        projected[-1] * (one + assumptions.terminal_growth) / (r - assumptions.terminal_growth)
    )
    pv_terminal = terminal_value / _power(one + r, horizon)
    enterprise_value = sum_pv + pv_terminal
    equity_value = enterprise_value - assumptions.net_debt
    value_per_share = equity_value / assumptions.shares if assumptions.shares is not None else None
    terminal_share = pv_terminal / enterprise_value if enterprise_value != 0 else None

    return DcfResult(
        assumptions=assumptions,
        projected_free_cash_flow=tuple(projected),
        discount_factors=tuple(factors),
        present_values=tuple(present_values),
        sum_of_present_values=sum_pv,
        terminal_value=terminal_value,
        present_value_of_terminal=pv_terminal,
        enterprise_value=enterprise_value,
        equity_value=equity_value,
        value_per_share=value_per_share,
        terminal_share_of_value=terminal_share,
    )


def _power(base: Decimal, exponent: int) -> Decimal:
    result = Decimal(1)
    for _ in range(exponent):
        result *= base
    return result

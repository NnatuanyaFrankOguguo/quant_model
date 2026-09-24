"""The adjusted series, and P6 checks 3, 5, 6, 9 and 11.

The one that matters most is `test_bulk_factors_agree_with_the_per_bar_function`.
`series.py` exists because calling `adjusted_close()` once per bar would issue a query
per bar; it replaces a walk of the factor list with a suffix product and a binary search.
That is an optimisation, and an optimisation that rounds differently is how a feature set
goes wrong with nothing to report it.
"""

from __future__ import annotations

import datetime as dt
from decimal import Decimal
from pathlib import Path

import pytest
from hypothesis import given
from hypothesis import strategies as st
from sqlalchemy import text

from packages.common.adjust import cumulative_factor
from packages.indicators.series import AdjustedBars, adjusted_bars, cumulative_factors_for
from packages.indicators.store import running_vintages

DECISION = dt.date(2026, 9, 24)


# --------------------------------------------------------------------------------------
# The bulk/per-bar equivalence, which is the whole justification for series.py
# --------------------------------------------------------------------------------------

_dates = st.dates(min_value=dt.date(2000, 1, 1), max_value=dt.date(2030, 1, 1))
_factors = st.decimals(
    min_value=Decimal("0.01"), max_value=Decimal("100"), places=6, allow_nan=False
)


@given(
    factors=st.lists(st.tuples(_dates, _factors), max_size=12),
    queries=st.lists(_dates, min_size=1, max_size=12),
)
def test_bulk_factors_agree_with_the_per_bar_function(
    factors: list[tuple[dt.date, Decimal]], queries: list[dt.date]
) -> None:
    """Exactly, not approximately - and that is not free.

    Being Decimal on both sides is not enough. `Decimal` multiplication rounds to the
    context precision, so it is not associative: folding a suffix from the right instead
    of the left moved the 28th significant digit, and this test failed on the seventh
    factor Hypothesis tried. `cumulative_factors_for` now folds each suffix in the same
    order `cumulative_factor` walks it, which is what makes `==` the right assertion
    here. Weakening this to `approx` would delete the only thing it checks.
    """
    ordered = sorted(factors)
    bulk = cumulative_factors_for(queries, ordered)
    for on, (factor, applied) in zip(queries, bulk, strict=True):
        assert (factor, applied) == cumulative_factor(on, ordered)


def test_a_bar_is_unadjusted_by_an_action_on_its_own_day() -> None:
    """Strictly after, not on or after. A bar on the ex-date already trades adjusted."""
    ex = dt.date(2020, 8, 31)
    factors = [(ex, Decimal("0.25"))]
    assert cumulative_factors_for([ex], factors) == [(Decimal(1), 0)]
    assert cumulative_factors_for([ex - dt.timedelta(days=1)], factors) == [(Decimal("0.25"), 1)]


# --------------------------------------------------------------------------------------
# Vintages - P6 check 6
# --------------------------------------------------------------------------------------


def _bars(vintages: list[dt.date]) -> AdjustedBars:
    n = len(vintages)
    dates = [dt.date(2024, 1, 1) + dt.timedelta(days=i) for i in range(n)]
    ones = [Decimal(1)] * n
    return AdjustedBars(
        dates, list(ones), list(ones), list(ones), list(ones), list(ones), list(ones), vintages
    )


def test_a_vintage_never_goes_backwards() -> None:
    """A restated bar drags every later value's vintage forward, never back.

    The middle bar here was restated late. Every value computed from it, and every value
    after it, could only have been known once that restatement existed.
    """
    d = dt.date(2024, 1, 1)
    vintages = [d, d + dt.timedelta(days=1), d + dt.timedelta(days=90), d + dt.timedelta(days=3)]
    got = running_vintages(_bars(vintages))
    assert got == [
        d,
        d + dt.timedelta(days=1),
        d + dt.timedelta(days=90),
        d + dt.timedelta(days=90),
    ]
    assert all(got[i] <= got[i + 1] for i in range(len(got) - 1))


# --------------------------------------------------------------------------------------
# P6 check 9 - a hard exit criterion, checked as the roadmap words it
# --------------------------------------------------------------------------------------


def test_no_signal_is_emitted_anywhere_in_the_package() -> None:
    """P6 exit criterion: "No signals generated anywhere."

    `SPEC.md` 4.2's acceptance for T9 is "computed + stored", never "traded", and
    `SPEC.md` 2C's reason is Park & Irwin's survey - 95 studies, and simple-rule
    profitability in US equities largely gone after the early 1990s. An indicator is a
    feature for a model P7 will validate. The words are searched for rather than the
    behaviour because a threshold is easy to add and hard to notice.

    Prose is exempt: the package docstrings say "never a signal" a great many times, and
    a test that forbade the word would forbid explaining the rule.
    """
    banned = ("buy", "sell", "overbought", "oversold", "bullish", "bearish", "recommend")
    offences: list[str] = []
    for path in sorted(Path("packages/indicators").rglob("*.py")):
        source = path.read_text(encoding="utf-8")
        # Strip docstrings and comments: this is about code, not about the explanation.
        import ast
        import io
        import tokenize

        stripped: list[str] = []
        for token in tokenize.generate_tokens(io.StringIO(source).readline):
            if token.type in (tokenize.COMMENT, tokenize.NL):
                continue
            if token.type == tokenize.STRING:
                continue
            stripped.append(token.string)
        code = " ".join(stripped).lower()
        assert ast.parse(source) is not None
        for word in banned:
            if word in code:
                offences.append(f"{path}: {word}")
    assert offences == [], f"P6 forbids a signal in this package: {offences}"


# --------------------------------------------------------------------------------------
# Against the real database - P6 checks 3 and 11
# --------------------------------------------------------------------------------------


@pytest.mark.usefixtures("db_session")
def test_the_series_reproduces_the_documented_apple_split(db_session) -> None:  # type: ignore[no-untyped-def]
    """`docs/08` §2.4's worked example, read through the bulk path.

    Apple closed at 499.23 on 2020-08-28 and split 4-for-1 on 2020-08-31. Read today,
    the 08-28 close is 124.8075 - comparable with the 129.04 of the 31st.
    """
    security_id = db_session.execute(
        text("select security_id from security_identifiers where id_value='AAPL' limit 1")
    ).scalar()
    if security_id is None:
        pytest.skip("AAPL is not loaded in this database")

    bars = adjusted_bars(
        db_session,
        security_id=security_id,
        decision_date=DECISION,
        start=dt.date(2020, 8, 20),
        end=dt.date(2020, 9, 5),
    )
    at = {d: i for i, d in enumerate(bars.dates)}
    before = at[dt.date(2020, 8, 28)]
    after = at[dt.date(2020, 8, 31)]

    assert bars.close[before] == Decimal("124.807500")
    assert bars.factor[before] == Decimal("0.25")
    assert bars.factor[after] == Decimal(1)
    # The point of adjusting: the two are now comparable rather than 4x apart.
    assert abs(bars.close[after] - bars.close[before]) < Decimal(10)


def test_a_series_without_a_decision_date_is_a_type_error(db_session) -> None:  # type: ignore[no-untyped-def]
    """There is no default of today. `adjust.py` makes the same refusal for one bar."""
    with pytest.raises(TypeError, match="no default of today"):
        adjusted_bars(db_session, security_id=1, decision_date=None)  # type: ignore[arg-type]

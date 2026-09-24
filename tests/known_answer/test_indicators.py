"""P6 checks 1, 4 and 12 - the indicators against `indicators_worksheet.md`.

The independent implementations below are written from the recurrences in the worksheet,
not from the library's source, which is the only arrangement under which agreement means
anything. See the worksheet's note on why these do not compare against a published table.
"""

from __future__ import annotations

import pytest

from packages.indicators.compute import CATALOGUE, compute, param_hash
from packages.indicators.series import AdjustedBars

pytest.importorskip("pandas_ta_classic")

import datetime as dt  # noqa: E402
from decimal import Decimal  # noqa: E402

# Wilder's worked example. `indicators_worksheet.md` records its provenance.
WILDER_CLOSES = [
    44.3389,
    44.0902,
    44.1497,
    43.6124,
    44.3278,
    44.8264,
    45.0955,
    45.4245,
    45.8433,
    46.0826,
    45.8931,
    46.0328,
    45.6140,
    46.2820,
    46.2820,
    46.0028,
    46.0328,
    46.4116,
    46.2222,
    45.6439,
    46.2122,
    46.2521,
    45.7137,
    46.4515,
    45.7835,
    45.3548,
    44.0288,
    44.1783,
    44.2181,
    44.5672,
    43.4205,
    42.6628,
    43.1314,
]


def wilder_rsi(prices: list[float], n: int) -> list[float]:
    """Wilder 1978, straight from the worksheet: SMA seed, then (prev*(n-1) + x)/n."""
    changes = [prices[i] - prices[i - 1] for i in range(1, len(prices))]
    gains = [max(c, 0.0) for c in changes]
    losses = [max(-c, 0.0) for c in changes]

    avg_gain = sum(gains[:n]) / n
    avg_loss = sum(losses[:n]) / n
    out = [100.0 if avg_loss == 0 else 100 - 100 / (1 + avg_gain / avg_loss)]
    for i in range(n, len(changes)):
        avg_gain = (avg_gain * (n - 1) + gains[i]) / n
        avg_loss = (avg_loss * (n - 1) + losses[i]) / n
        out.append(100.0 if avg_loss == 0 else 100 - 100 / (1 + avg_gain / avg_loss))
    return out


def bars_from(closes: list[float]) -> AdjustedBars:
    """Bars carrying only closes. Enough for RSI, which reads nothing else."""
    dates = [dt.date(2020, 1, 1) + dt.timedelta(days=i) for i in range(len(closes))]
    decimals = [Decimal(str(c)) for c in closes]
    return AdjustedBars(
        dates,
        list(decimals),
        list(decimals),
        list(decimals),
        list(decimals),
        [Decimal(1_000)] * len(closes),
        [Decimal(1)] * len(closes),
        list(dates),
    )


@pytest.mark.parametrize("length", [14, 21])
def test_rsi_matches_wilders_recurrence(length: int) -> None:
    """P6 check 1. The library's smoothing is Wilder's, not a simple average."""
    spec = CATALOGUE[f"rsi{length}"]
    (series,) = compute(bars_from(WILDER_CLOSES), spec)

    got = [v for v in series.values if v is not None]
    expected = wilder_rsi(WILDER_CLOSES, length)

    assert len(got) == len(expected)
    for i, (g, e) in enumerate(zip(got, expected, strict=True)):
        assert g == pytest.approx(e, abs=1e-9), f"bar {i}: library {g}, Wilder {e}"


def test_rsi_warms_up_as_null_never_as_zero() -> None:
    """A bar before the first computable value has no RSI. Zero would be a measurement."""
    (series,) = compute(bars_from(WILDER_CLOSES), CATALOGUE["rsi14"])
    assert series.values[:14] == [None] * 14
    assert series.values[14] is not None
    assert len(series.values) == len(WILDER_CLOSES)


def test_rsi_is_100_when_nothing_ever_falls() -> None:
    """The zero-division case. A series that only rises is RSI 100, not a crash."""
    (series,) = compute(bars_from([float(100 + i) for i in range(40)]), CATALOGUE["rsi14"])
    assert series.values[-1] == pytest.approx(100.0)


def test_param_hash_separates_two_lengths_of_one_indicator() -> None:
    """P6 check 4. RSI-14 and RSI-21 are different features and must not share a key.

    `docs/03` P6.2: without the hash in the primary key "you silently overwrite one with
    the other, and in P8 your feature matrix contains whichever ran last."
    """
    assert CATALOGUE["rsi14"].hash != CATALOGUE["rsi21"].hash

    bars = bars_from(WILDER_CLOSES)
    (fourteen,) = compute(bars, CATALOGUE["rsi14"])
    (twentyone,) = compute(bars, CATALOGUE["rsi21"])
    assert fourteen.name != twentyone.name
    assert fourteen.values[-1] != twentyone.values[-1]


def test_param_hash_is_stable_across_processes_and_key_order() -> None:
    """A hash that moved between runs would make yesterday's rows unfindable today."""
    assert param_hash({"length": 14}) == "977c4fe2b936"
    assert param_hash({"a": 1, "b": 2}) == param_hash({"b": 2, "a": 1})

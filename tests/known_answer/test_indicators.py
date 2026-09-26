"""P6 checks 1, 4 and 12 - the indicators against `indicators_worksheet.md`.

The independent implementations below are written from the recurrences in the worksheet,
not from the library's source, which is the only arrangement under which agreement means
anything. See the worksheet's note on why these do not compare against a published table.
"""

from __future__ import annotations

import pytest

from packages.indicators.compute import CATALOGUE, IndicatorSpec, compute, param_hash
from packages.indicators.series import AdjustedBars

pytest.importorskip("pandas_ta_classic")

import datetime as dt  # noqa: E402
import math  # noqa: E402
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


# ======================================================================================
# The other five. P6 checks 2 and 12.
#
# Same arrangement as the RSI tests above: each recurrence below is written from
# `indicators_worksheet.md`, which was written from the definition, and neither was
# written from the library. The vector is generated rather than tabulated - a printed
# table is how the RSI trap got its teeth, and a formula cannot be rounded by a
# publisher. The worksheet carries the same four lines, so a second implementation can
# reproduce the input exactly.
# ======================================================================================


def synthetic_ohlcv(n: int = 60) -> tuple[list[float], list[float], list[float], list[float]]:
    """A deterministic OHLCV vector: a rising sine, with a high and a low around it.

    Sixty bars because MACD-12-26-9 needs thirty-four before its histogram exists, and a
    known-answer test that only reaches the first value has not tested the recurrence.
    Rounded to four places so the vector is the same on every libm; the test compares
    two implementations against *each other* on one array, so it would hold either way,
    but a reproducible input is the point of writing it down.

    High is always at least a point above the close and low at least a point below, so
    the bar is well formed and the stochastic's denominator is never accidentally zero.
    """
    close = [round(100 + 12 * math.sin(i / 4.0) + 0.45 * i, 4) for i in range(n)]
    high = [round(close[i] + 1.5 + 0.5 * math.cos(i / 3.0), 4) for i in range(n)]
    low = [round(close[i] - 1.5 - 0.5 * math.sin(i / 2.0), 4) for i in range(n)]
    volume = [float(1_000_000 + 25_000 * ((i * 37) % 11)) for i in range(n)]
    return close, high, low, volume


CLOSE, HIGH, LOW, VOLUME = synthetic_ohlcv()


def bars_from_ohlcv(
    close: list[float],
    high: list[float],
    low: list[float],
    volume: list[float],
) -> AdjustedBars:
    """Full bars, for the four indicators that read more than the close."""
    dates = [dt.date(2020, 1, 1) + dt.timedelta(days=i) for i in range(len(close))]
    return AdjustedBars(
        dates,
        [Decimal(str(c)) for c in close],
        [Decimal(str(h)) for h in high],
        [Decimal(str(value)) for value in low],
        [Decimal(str(c)) for c in close],
        [Decimal(str(v)) for v in volume],
        [Decimal(1)] * len(close),
        list(dates),
    )


# --------------------------------------------------------------------------------------
# The independent implementations, from the worksheet.
# --------------------------------------------------------------------------------------


def sma(xs: list[float | None], n: int) -> list[float | None]:
    """Simple moving average: None until there are n values, and None if any is None."""
    out: list[float | None] = []
    for i in range(len(xs)):
        window = xs[i - n + 1 : i + 1]
        if i < n - 1 or any(x is None for x in window):
            out.append(None)
        else:
            out.append(sum(window) / n)
    return out


def ema_sma_seeded(xs: list[float], n: int) -> list[float | None]:
    """EMA, alpha = 2/(n+1), seeded on the mean of the first n. First value at index n-1."""
    alpha = 2.0 / (n + 1)
    out: list[float | None] = [None] * (n - 1)
    value = sum(xs[:n]) / n
    out.append(value)
    for x in xs[n:]:
        value = alpha * x + (1 - alpha) * value
        out.append(value)
    return out


def ema_first_seeded(xs: list[float], n: int) -> list[float]:
    """The rival seeding: alpha = 2/(n+1) from the first observation. Not what MACD uses."""
    alpha = 2.0 / (n + 1)
    out = [xs[0]]
    for x in xs[1:]:
        out.append(alpha * x + (1 - alpha) * out[-1])
    return out


def macd_lines(
    closes: list[float], fast: int, slow: int, signal: int
) -> tuple[list[float | None], list[float | None], list[float | None]]:
    """MACD line, its smoothing, and the difference between them."""
    quick = ema_sma_seeded(closes, fast)
    slower = ema_sma_seeded(closes, slow)
    line: list[float | None] = [
        None if slower[i] is None else quick[i] - slower[i] for i in range(len(closes))
    ]
    start = slow - 1  # where the MACD line begins; the signal EMA is seeded from there
    sig: list[float | None] = [None] * start + ema_sma_seeded(line[start:], signal)
    hist: list[float | None] = [
        None if sig[i] is None else line[i] - sig[i] for i in range(len(closes))
    ]
    return line, sig, hist


def bollinger(
    closes: list[float], n: int, width: float, ddof: int = 0
) -> tuple[list[float | None], list[float | None], list[float | None]]:
    """Bollinger bands. ddof=0 is the population deviation, which is the convention."""
    mid = sma(closes, n)
    lower: list[float | None] = []
    upper: list[float | None] = []
    for i in range(len(closes)):
        centre = mid[i]
        if centre is None:
            lower.append(None)
            upper.append(None)
            continue
        window = closes[i - n + 1 : i + 1]
        deviation = math.sqrt(sum((x - centre) ** 2 for x in window) / (n - ddof))
        lower.append(centre - width * deviation)
        upper.append(centre + width * deviation)
    return lower, mid, upper


def true_range(highs: list[float], lows: list[float], closes: list[float]) -> list[float | None]:
    """max(h-l, |h - prev close|, |l - prev close|). Undefined on the first bar."""
    out: list[float | None] = [None]
    for i in range(1, len(closes)):
        out.append(
            max(
                highs[i] - lows[i],
                abs(highs[i] - closes[i - 1]),
                abs(lows[i] - closes[i - 1]),
            )
        )
    return out


def wilder_atr(
    highs: list[float], lows: list[float], closes: list[float], n: int
) -> list[float | None]:
    """The mean of the first n true ranges, then Wilder. First value at index n."""
    ranges = true_range(highs, lows, closes)
    out: list[float | None] = [None] * n
    value = sum(ranges[1 : n + 1]) / n
    out.append(value)
    for x in ranges[n + 1 :]:
        value = (value * (n - 1) + x) / n
        out.append(value)
    return out


def ewm_seeded_atr(
    highs: list[float], lows: list[float], closes: list[float], n: int
) -> list[float | None]:
    """The rival: alpha = 1/n from the first true range, no SMA seed. Not what ATR uses."""
    ranges = true_range(highs, lows, closes)
    value = ranges[1]
    out: list[float | None] = [None, value]
    for x in ranges[2:]:
        value = x / n + value * (1 - 1 / n)
        out.append(value)
    return out


def on_balance_volume(
    closes: list[float], volumes: list[float], seed: float | None = None
) -> list[float]:
    """Running signed volume. Seeded at +volume[0]; an unchanged close adds nothing."""
    out = [volumes[0] if seed is None else seed]
    for i in range(1, len(closes)):
        if closes[i] > closes[i - 1]:
            out.append(out[-1] + volumes[i])
        elif closes[i] < closes[i - 1]:
            out.append(out[-1] - volumes[i])
        else:
            out.append(out[-1])
    return out


def stochastic(
    highs: list[float], lows: list[float], closes: list[float], k: int, d: int, smooth_k: int
) -> tuple[list[float | None], list[float | None]]:
    """Raw %K over k bars, smoothed by smooth_k, then %D over d."""
    raw: list[float | None] = []
    for i in range(len(closes)):
        if i < k - 1:
            raw.append(None)
            continue
        highest = max(highs[i - k + 1 : i + 1])
        lowest = min(lows[i - k + 1 : i + 1])
        # No range means no answer. Not zero - zero would say "at the bottom of a range"
        # about a security that had none.
        raw.append(None if highest == lowest else 100.0 * (closes[i] - lowest) / (highest - lowest))
    fast = sma(raw, smooth_k)
    return fast, sma(fast, d)


def agree(got: list[float | None], expected: list[float | None], *, tol: float = 1e-9) -> None:
    """Same Nones in the same places, and the same numbers everywhere else."""
    assert len(got) == len(expected)
    for i, (g, e) in enumerate(zip(got, expected, strict=True)):
        assert (g is None) == (e is None), f"bar {i}: library {g!r}, independent {e!r}"
        if e is not None:
            assert g == pytest.approx(e, abs=tol), f"bar {i}: library {g}, independent {e}"


# --------------------------------------------------------------------------------------
# MACD
# --------------------------------------------------------------------------------------


def test_macd_matches_appels_recurrence() -> None:
    """P6 check 2. SMA-seeded EMAs, and a histogram that is macd - signal, not twice it."""
    line, signal, hist = compute(bars_from_ohlcv(CLOSE, HIGH, LOW, VOLUME), CATALOGUE["macd"])
    assert (line.name, signal.name, hist.name) == ("macd", "macd_signal", "macd_hist")

    want_line, want_signal, want_hist = macd_lines(CLOSE, 12, 26, 9)
    agree(line.values, want_line)
    agree(signal.values, want_signal)
    agree(hist.values, want_hist)


def test_macd_warms_up_as_null_never_as_zero() -> None:
    """Two warm-ups in one indicator: the line at slow-1, the signal eight bars later."""
    line, signal, hist = compute(bars_from_ohlcv(CLOSE, HIGH, LOW, VOLUME), CATALOGUE["macd"])
    assert line.values[:25] == [None] * 25
    assert line.values[25] is not None
    assert signal.values[:33] == [None] * 33
    assert signal.values[33] is not None
    assert hist.values[:33] == [None] * 33
    assert hist.values[33] is not None


# --------------------------------------------------------------------------------------
# Bollinger bands
# --------------------------------------------------------------------------------------


def test_bollinger_matches_a_population_deviation_about_an_sma() -> None:
    """P6 check 2. ddof=0, and bands symmetric about the centre by construction."""
    lower, mid, upper = compute(bars_from_ohlcv(CLOSE, HIGH, LOW, VOLUME), CATALOGUE["bbands"])
    assert (lower.name, mid.name, upper.name) == ("bb_lower", "bb_mid", "bb_upper")

    want_lower, want_mid, want_upper = bollinger(CLOSE, 20, 2.0)
    agree(lower.values, want_lower)
    agree(mid.values, want_mid)
    agree(upper.values, want_upper)

    for low, middle, high in zip(lower.values, mid.values, upper.values, strict=True):
        if middle is None:
            continue
        assert high - middle == pytest.approx(middle - low, abs=1e-9)


def test_bollinger_warms_up_as_null_never_as_zero() -> None:
    """Nineteen bars of nothing, then three lines at once."""
    produced = compute(bars_from_ohlcv(CLOSE, HIGH, LOW, VOLUME), CATALOGUE["bbands"])
    for series in produced:
        assert series.values[:19] == [None] * 19
        assert series.values[19] is not None


def test_bollinger_on_a_motionless_security_is_three_equal_lines() -> None:
    """Zero deviation is a measurement: the bands collapse onto the mean, correctly."""
    flat = [50.0] * 30
    lower, mid, upper = compute(bars_from_ohlcv(flat, flat, flat, VOLUME[:30]), CATALOGUE["bbands"])
    assert lower.values[-1] == pytest.approx(50.0)
    assert mid.values[-1] == pytest.approx(50.0)
    assert upper.values[-1] == pytest.approx(50.0)


# --------------------------------------------------------------------------------------
# ATR
# --------------------------------------------------------------------------------------


def test_atr_matches_wilders_true_range_recurrence() -> None:
    """P6 check 2. Wilder's smoothing with an SMA seed, over the three-way true range."""
    (series,) = compute(bars_from_ohlcv(CLOSE, HIGH, LOW, VOLUME), CATALOGUE["atr14"])
    assert series.name == "atr14"
    agree(series.values, wilder_atr(HIGH, LOW, CLOSE, 14))


def test_atr_warms_up_as_null_never_as_zero() -> None:
    """The first true range needs a previous close, so the first ATR lands at n, not n-1."""
    (series,) = compute(bars_from_ohlcv(CLOSE, HIGH, LOW, VOLUME), CATALOGUE["atr14"])
    assert series.values[:14] == [None] * 14
    assert series.values[14] is not None


def test_atr_of_a_motionless_security_is_zero_and_that_is_a_measurement() -> None:
    """The degenerate case. ATR divides only by the constant length, so nothing blows up.

    Zero here is not the absence `_column` guards against - it is the true range of a
    market that did not move, which really is zero and belongs in the database as zero.
    (2.2e-16 in practice; the library's true range adds a float epsilon to high - low.)
    """
    flat = [50.0] * 30
    (series,) = compute(bars_from_ohlcv(flat, flat, flat, VOLUME[:30]), CATALOGUE["atr14"])
    assert series.values[-1] is not None
    assert series.values[-1] == pytest.approx(0.0, abs=1e-12)


# --------------------------------------------------------------------------------------
# OBV
# --------------------------------------------------------------------------------------


def test_obv_matches_signed_cumulative_volume() -> None:
    """P6 check 2, and the seeding: the first bar is +volume[0], not zero."""
    (series,) = compute(bars_from_ohlcv(CLOSE, HIGH, LOW, VOLUME), CATALOGUE["obv"])
    assert series.name == "obv"
    agree(series.values, on_balance_volume(CLOSE, VOLUME), tol=1e-6)
    assert series.values[0] == pytest.approx(VOLUME[0])


def test_obv_has_no_warm_up_and_an_unchanged_close_adds_nothing() -> None:
    """Three states, not two: up adds, down subtracts, unchanged carries the total forward."""
    closes = [100.0, 100.0, 101.0, 101.0, 100.0]
    volumes = [10.0, 20.0, 30.0, 40.0, 50.0]
    (series,) = compute(bars_from_ohlcv(closes, closes, closes, volumes), CATALOGUE["obv"])
    assert series.values == [10.0, 10.0, 40.0, 40.0, -10.0]


# --------------------------------------------------------------------------------------
# Stochastic
# --------------------------------------------------------------------------------------


def test_stochastic_matches_lanes_recurrence() -> None:
    """P6 check 2. A k-bar lookback, %K smoothed by 3, %D a further 3-bar mean of %K."""
    fast, slow = compute(bars_from_ohlcv(CLOSE, HIGH, LOW, VOLUME), CATALOGUE["stoch"])
    assert (fast.name, slow.name) == ("stoch_k", "stoch_d")

    want_fast, want_slow = stochastic(HIGH, LOW, CLOSE, 14, 3, 3)
    agree(fast.values, want_fast)
    agree(slow.values, want_slow)


def test_stochastic_warms_up_as_null_never_as_zero() -> None:
    """%K at k+smooth_k-2, %D d-1 bars later. A zero in either place reads as a low."""
    fast, slow = compute(bars_from_ohlcv(CLOSE, HIGH, LOW, VOLUME), CATALOGUE["stoch"])
    assert fast.values[:15] == [None] * 15
    assert fast.values[15] is not None
    assert slow.values[:17] == [None] * 17
    assert slow.values[17] is not None


def test_stochastic_of_a_rangeless_window_is_null_not_zero() -> None:
    """The division by zero, and the reason it is not left to the library.

    `pandas-ta-classic` answers 0.0 here, by adding a float epsilon to the denominator
    rather than by choosing an answer. Zero says the close sat at the bottom of its
    range; there was no range. `_stoch` masks it, and masks every smoothed value that
    averaged one in.
    """
    flat = [50.0] * 30
    fast, slow = compute(bars_from_ohlcv(flat, flat, flat, VOLUME[:30]), CATALOGUE["stoch"])
    assert fast.values == [None] * 30
    assert slow.values == [None] * 30


def test_stochastic_keeps_a_genuine_zero_when_the_close_sits_at_the_low() -> None:
    """The mask must be structural, not by value: a %K of exactly 0 is an ordinary reading."""
    closes = [100.0 - i for i in range(30)]  # falling daily, so the close is always the low
    highs = [c + 2.0 for c in closes]
    fast, _slow = compute(bars_from_ohlcv(closes, highs, closes, VOLUME[:30]), CATALOGUE["stoch"])
    assert fast.values[-1] == pytest.approx(0.0)


def test_stochastic_recovers_after_a_dead_patch_ends() -> None:
    """The mask covers the contaminated bars and stops. It is not a latch."""
    closes = list(CLOSE)
    highs = list(HIGH)
    lows = list(LOW)
    for i in range(20, 40):  # twenty sessions with no trade at all
        closes[i] = highs[i] = lows[i] = 120.0
    fast, slow = compute(bars_from_ohlcv(closes, highs, lows, VOLUME), CATALOGUE["stoch"])
    assert fast.values[36] is None
    assert fast.values[-1] is not None
    assert slow.values[-1] is not None


# --------------------------------------------------------------------------------------
# The rival conventions are far enough apart to notice - so these tests discriminate
# --------------------------------------------------------------------------------------


def test_the_rival_conventions_differ_materially_from_what_the_library_does() -> None:
    """P6 check 12's real content: a known-answer test only earns its keep if it can fail.

    Each of these is the other plausible reading of the same indicator. If any agreed to
    within the tolerance the tests above use, the matching test would prove nothing. The
    gaps are in price points and index points, not in rounding.
    """
    bars = bars_from_ohlcv(CLOSE, HIGH, LOW, VOLUME)

    # MACD: EMAs seeded on the first close rather than on the mean of the first n.
    line, _signal, _hist = compute(bars, CATALOGUE["macd"])
    quick = ema_first_seeded(CLOSE, 12)
    slower = ema_first_seeded(CLOSE, 26)
    rival = [quick[i] - slower[i] for i in range(len(CLOSE))]
    gaps = [abs(v - rival[i]) for i, v in enumerate(line.values) if v is not None]
    assert max(gaps) > 1.0

    # Bollinger: the sample deviation instead of the population one.
    lower, _mid, _upper = compute(bars, CATALOGUE["bbands"])
    rival_lower, _rm, _ru = bollinger(CLOSE, 20, 2.0, ddof=1)
    gaps = [abs(v - rival_lower[i]) for i, v in enumerate(lower.values) if v is not None]
    assert max(gaps) > 0.5

    # ATR: Wilder's alpha applied from the first true range, with no SMA seed.
    (atr,) = compute(bars, CATALOGUE["atr14"])
    rival_atr = ewm_seeded_atr(HIGH, LOW, CLOSE, 14)
    gaps = [abs(v - rival_atr[i]) for i, v in enumerate(atr.values) if v is not None]
    assert max(gaps) > 0.1

    # OBV: seeded at zero rather than at the first bar's volume.
    (obv,) = compute(bars, CATALOGUE["obv"])
    rival_obv = on_balance_volume(CLOSE, VOLUME, seed=0.0)
    assert abs(obv.values[-1] - rival_obv[-1]) == pytest.approx(VOLUME[0])


# --------------------------------------------------------------------------------------
# Catalogue-wide properties
# --------------------------------------------------------------------------------------


@pytest.mark.parametrize("key", sorted(CATALOGUE))
def test_a_history_shorter_than_the_window_is_all_nulls_not_an_exception(key: str) -> None:
    """`pandas-ta-classic` returns None, not a frame of NaN, when it cannot compute.

    A security that listed three days ago is not an error. Iterating that None raises
    TypeError, which is why `_absent` exists: the whole column is the same "no value
    yet" the warm-up rows carry, and every spec has to answer it the same way. OBV is
    the exception that proves it - it needs one bar, so all three of these are real.
    """
    bars = bars_from_ohlcv([1.0, 2.0, 3.0], [2.0, 3.0, 4.0], [0.5, 1.5, 2.5], [10.0, 20.0, 30.0])
    produced = compute(bars, CATALOGUE[key])
    for series in produced:
        assert len(series.values) == 3
        if key == "obv":
            assert series.values == [10.0, 30.0, 60.0]  # a rising close, so all three add
        else:
            assert series.values == [None, None, None]


@pytest.mark.parametrize("key", sorted(CATALOGUE))
def test_every_spec_produces_its_declared_outputs_at_full_length(key: str) -> None:
    """`compute` enforces the names; this adds the lengths, the types and non-emptiness."""
    spec = CATALOGUE[key]
    produced = compute(bars_from_ohlcv(CLOSE, HIGH, LOW, VOLUME), spec)
    assert tuple(s.name for s in produced) == spec.outputs
    for series in produced:
        assert len(series.values) == len(CLOSE)
        assert all(v is None or isinstance(v, float) for v in series.values)
        assert not all(v is None for v in series.values), f"{series.name} is empty at 60 bars"


def test_param_hash_separates_two_parameter_sets_that_share_a_column_name() -> None:
    """P6 check 4, in the form that actually bites.

    RSI-14 and RSI-21 are separated by their names as well as their hashes, so they
    would survive a broken hash. Two Bollinger widths would not: both write `bb_upper`,
    for the same security on the same date, and only `param_hash` keeps the 2.5-sigma
    band from overwriting the 2.0-sigma one in a key that contains both.
    """
    wider = IndicatorSpec(
        "bbands25",
        {"length": 20, "std": 2.5},
        ("bb_lower", "bb_mid", "bb_upper"),
        CATALOGUE["bbands"].fn,
    )
    assert wider.hash != CATALOGUE["bbands"].hash

    bars = bars_from_ohlcv(CLOSE, HIGH, LOW, VOLUME)
    _lower, _mid, standard = compute(bars, CATALOGUE["bbands"])
    _wider_lower, _wider_mid, widened = compute(bars, wider)
    assert standard.name == widened.name == "bb_upper"
    assert standard.values[-1] != widened.values[-1]


def test_no_two_catalogue_entries_share_both_a_name_and_a_hash() -> None:
    """The primary key is (security_id, date, name, param_hash, known_as_of).

    `rsi14` and `atr14` hash identically - both are `{"length": 14}` - and that is fine
    and deliberate: the hash distinguishes parameter sets *within* one indicator name,
    as `param_hash`'s docstring says. What must never repeat is the pair.
    """
    pairs = [(name, spec.hash) for spec in CATALOGUE.values() for name in spec.outputs]
    assert len(pairs) == len(set(pairs))
    assert CATALOGUE["rsi14"].hash == CATALOGUE["atr14"].hash  # the same params, deliberately

"""The indicator catalogue: what is computed, from what, under which parameters. P6.2.

Compute functions take data and return data and do no I/O (`docs/08` §6), which is what
lets `tests/known_answer/` check them against hand-computed vectors. Persistence, and
the point-in-time vintage of a value, live in `store.py`.

## Nothing here is a signal

`SPEC.md` 4.2's acceptance for T9 is "computed + stored", never "traded", and P6's exit
criteria make *"no signals generated anywhere"* a hard gate. There is no threshold in this
file, no "overbought", no crossing test. RSI at 71 is a number; that it is above 70 is a
claim about the future, and `SPEC.md` 2C's survey of 95 studies is the reason this project
does not make it until P7 has had a say.

## The smoothing convention, measured rather than assumed

`docs/03` P6.2 warns that *"libraries differ on smoothing conventions - Wilder versus
simple, for instance - and a subtly different RSI is a subtly different model"*, and makes
known-answer tests mandatory for exactly that reason.

Measured 2026-09-24 against an independent implementation of Wilder's 1978 recurrence
(SMA seed, then `avg = (prev * (n-1) + x) / n`): `pandas-ta-classic` 0.8.32 agrees to
**ten decimal places**. It is Wilder, not simple. Worth recording how that was settled,
because the obvious check misleads: the RSI table StockCharts publishes for Wilder's own
example differs from both by up to 0.10, since it is derived from prices rounded to two
places and printed to four. A library checked against that table looks broken and is not.
So the known-answer tests here compare against an independent implementation of the
documented recurrence, never against a rounded published table.

The other five were measured the same way on the same day, each against an
implementation written from its definition. What 0.8.32 turned out to do:

- **MACD** - EMAs seeded on the *mean of the first `n`*, not on the first close. The
  signal line is that same seeding applied to the live MACD line, and the histogram is
  `macd - signal` rather than twice it. Agreement: exact, bit for bit.
- **Bollinger** - an SMA centre and a *population* deviation, `ddof=0`. 3e-14.
- **ATR** - Wilder's smoothing over true range, *SMA-seeded*; not `ewm(adjust=False)`
  from the first true range, which the library's name for it, `rma`, might suggest.
  9e-16.
- **OBV** - seeded at `+volume[0]`, not at zero. An unchanged close adds nothing. Exact.
- **Stochastic** - raw %K over `k` bars, %K = SMA(raw, `smooth_k`), %D = SMA(%K, `d`).
  4e-14.

Two of those were live coin-flips rather than formalities. An EMA seeded on the first
observation instead of on a mean differs from this one by 1.9 on the MACD line where the
line begins, and an `ewm`-seeded ATR by 0.59 - both converging, both wrong for exactly
the first few dozen bars a short window is made of. So every library call below pins its
convention explicitly (`mamode=`, `ddof=`, `talib=False`) even where the value passed is
already the default: a default is a fact about a version, and `talib=True` is what a
later `pip install TA-Lib` would switch several of these to without a word. The point of
measuring was to stop the arithmetic moving underneath us.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field

from packages.indicators.series import AdjustedBars

__all__ = [
    "CATALOGUE",
    "CODE_VERSION",
    "IndicatorSpec",
    "Series",
    "compute",
    "param_hash",
]

# Bumped when the arithmetic of any indicator changes - not on every commit. A git SHA
# would change when a docstring did, and `code_version` exists so a reader can tell
# whether two rows were produced by the same calculation, which a SHA answers wrongly.
CODE_VERSION = "p6-indicators-1"


def param_hash(params: Mapping[str, object]) -> str:
    """A short, stable digest of a parameter set.

    Stable across runs and processes, so `sort_keys` and a fixed separator rather than
    `hash()`, whose randomisation would make yesterday's rows unfindable today.

    Twelve hex characters. It is a key within one security, one date and one indicator
    name, not a content address for the world, and a full digest makes every row in the
    table harder to read for no collision benefit worth having.
    """
    canonical = json.dumps(params, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:12]


@dataclass(frozen=True)
class Series:
    """One named output column. An indicator may produce several - MACD produces three."""

    name: str
    values: list[float | None]


@dataclass(frozen=True)
class IndicatorSpec:
    """One indicator under one parameter set, and the column names it produces."""

    key: str
    params: dict[str, object]
    outputs: tuple[str, ...]
    # Takes the bars and the params, returns one list per name in `outputs`, each the
    # same length as the input with None where the indicator has no value yet.
    fn: Callable[..., list[Series]] = field(repr=False, compare=False)

    @property
    def hash(self) -> str:
        return param_hash(self.params)


def _frame(bars: AdjustedBars):  # type: ignore[no-untyped-def]
    return bars.to_frame()


def _column(result, length: int) -> list[float | None]:  # type: ignore[no-untyped-def]
    """A pandas column as a plain list, with NaN carried across as None.

    NaN and None are not the same fact and the database only has room for one of them.
    A leading NaN from an indicator's warm-up period is "no value yet", which is exactly
    what a NULL says; writing 0.0 there would be the zero-for-an-absence mistake that
    `packages/common`'s whole vocabulary exists to prevent.
    """
    import math

    values = [
        None if v is None or (isinstance(v, float) and math.isnan(v)) else float(v) for v in result
    ]
    if len(values) != length:
        raise ValueError(f"indicator returned {len(values)} values for {length} bars")
    return values


def _absent(length: int) -> list[float | None]:
    """A column that is "no value yet" throughout - too short a history, in other words.

    `pandas-ta-classic` returns `None` there, not a frame of NaN: measured, RSI needs
    `length` bars, MACD `slow`, Bollinger `length`, ATR `length`, Stochastic
    `k + smooth_k + d - 2`, and OBV one. Iterating that `None` raises `TypeError`, and
    raising is the wrong answer to it. A security that listed eleven days ago has no
    14-day RSI, which is not an error and not a zero - it is the same absence as the
    warm-up rows inside a longer series, and belongs in the database as the same NULL.
    """
    return [None] * length


def _pick(frame, prefix: str):  # type: ignore[no-untyped-def]
    """The one column of a multi-output result whose name starts with `prefix`.

    Positional indexing would be shorter and wrong. `bbands` returns five columns rather
    than the three we keep, and a release that inserts a sixth would silently re-point
    `bb_upper` at someone else's arithmetic without failing a single test. Matching the
    documented prefix and insisting the match is unique turns that into an exception.
    """
    matches = [c for c in frame.columns if c.startswith(prefix)]
    if len(matches) != 1:
        raise ValueError(f"expected exactly one column named {prefix}*, found {matches}")
    return frame[matches[0]]


# --------------------------------------------------------------------------------------
# The six. `docs/03` P6.2: RSI, MACD, Bollinger Bands, ATR, OBV, Stochastic.
#
# Every recurrence below is written out in `tests/known_answer/indicators_worksheet.md`
# and checked there against an independent implementation. None of them emits a signal:
# there is no threshold, no crossing, no comparison of one output to another. Where a
# name here reads like one - `macd_signal` is Appel's own term for the smoothing of the
# MACD line - it names a moving average and nothing else.
# --------------------------------------------------------------------------------------


def _rsi(bars: AdjustedBars, *, length: int) -> list[Series]:
    """Relative strength index, Wilder smoothing - see the module note on convention."""
    import pandas_ta_classic as ta

    frame = _frame(bars)
    out = ta.rsi(frame["close"], length=length, talib=False)
    name = f"rsi{length}"
    if out is None:
        return [Series(name, _absent(len(bars)))]
    return [Series(name, _column(out, len(bars)))]


def _macd(bars: AdjustedBars, *, fast: int, slow: int, signal: int) -> list[Series]:
    """Appel's MACD: two EMAs differenced, that difference smoothed, and the gap.

    `signal` is Appel's name for the third moving average, a `signal`-period EMA of the
    MACD line. It is a smoothing, not a recommendation - the crossing of `macd` and
    `macd_signal` is the classic rule and this phase deliberately does not compute it.

    Three outputs, one spec, one `param_hash`: they are one calculation with one
    parameter set, and splitting them into three specs would make a change to `fast`
    look like a change to three unrelated features.
    """
    import pandas_ta_classic as ta

    n = len(bars)
    out = ta.macd(_frame(bars)["close"], fast=fast, slow=slow, signal=signal, talib=False)
    if out is None:
        return [Series(name, _absent(n)) for name in ("macd", "macd_signal", "macd_hist")]
    return [
        Series("macd", _column(_pick(out, "MACD_"), n)),
        Series("macd_signal", _column(_pick(out, "MACDs_"), n)),
        Series("macd_hist", _column(_pick(out, "MACDh_"), n)),
    ]


def _bbands(bars: AdjustedBars, *, length: int, std: float) -> list[Series]:
    """Bollinger bands: an SMA, and a population standard deviation either side of it.

    `ddof=0` is passed rather than assumed. It is the library's default and it is also
    Bollinger's definition, but the sample deviation is the other plausible reading, and
    on a 20-bar window it is `sqrt(20/19)` larger - 2.6% further from the centre, 0.61 of
    a price point at its worst on the test vector. Not a rounding difference, and not one
    that would ever look like a bug either.
    """
    import pandas_ta_classic as ta

    n = len(bars)
    out = ta.bbands(_frame(bars)["close"], length=length, std=std, ddof=0, talib=False)
    if out is None:
        return [Series(name, _absent(n)) for name in ("bb_lower", "bb_mid", "bb_upper")]
    # `bbands` also returns bandwidth and %B. Both are positions relative to the bands
    # rather than the bands themselves, and neither is one of `docs/03` P6.2's six.
    return [
        Series("bb_lower", _column(_pick(out, "BBL_"), n)),
        Series("bb_mid", _column(_pick(out, "BBM_"), n)),
        Series("bb_upper", _column(_pick(out, "BBU_"), n)),
    ]


def _atr(bars: AdjustedBars, *, length: int) -> list[Series]:
    """Wilder's average true range. Reads high and low, already adjusted by `series.py`.

    There is no division by anything the data supplies - true range is a maximum of
    three differences and Wilder's smoothing divides by the constant `length` - so a
    security that did not move has an ATR of zero, which is a true measurement of a flat
    market and not an absence. (`pandas-ta-classic` returns 2.2e-16 rather than 0.0 for
    that case, because its true range adds a float epsilon to `high - low` to keep the
    percentage variant we do not compute from dividing by zero. Immaterial, but it is
    why a dead security's stored ATR is a denormal rather than a round zero.)
    """
    import pandas_ta_classic as ta

    frame = _frame(bars)
    name = f"atr{length}"
    out = ta.atr(
        frame["high"], frame["low"], frame["close"], length=length, mamode="rma", talib=False
    )
    if out is None:
        return [Series(name, _absent(len(bars)))]
    return [Series(name, _column(out, len(bars)))]


def _obv(bars: AdjustedBars) -> list[Series]:
    """On-balance volume: the running total of volume, signed by the close's direction.

    Reads volume, which `adjusted_bars` has already divided by the split factor - the
    inverse of what it did to the prices. Do not adjust it again; a 4-for-1 split that
    scaled price down by four scaled share count up by four, and applying the price
    factor to quantity would put a step in the running total that no one traded.

    No warm-up: the first bar has a value. `pandas-ta-classic` seeds that first bar at
    `+volume[0]` rather than at zero, so the whole series sits one bar's volume above a
    zero-seeded one. OBV is read in differences and slopes, so an additive constant
    changes nothing that anyone asks of it - but it does mean a value here is not
    comparable with a value from a differently-seeded library, and that is worth knowing
    before someone reconciles the two and concludes one of them is broken.
    """
    import pandas_ta_classic as ta

    frame = _frame(bars)
    out = ta.obv(frame["close"], frame["volume"], talib=False)
    if out is None:
        return [Series("obv", _absent(len(bars)))]
    return [Series("obv", _column(out, len(bars)))]


def _stoch(bars: AdjustedBars, *, k: int, d: int, smooth_k: int) -> list[Series]:
    """Lane's stochastic oscillator: where the close sits in its recent high-low range.

    **The degenerate window is handled here rather than left to the library.** When the
    highest high of the window equals its lowest low - a security that did not trade for
    `k` sessions, which for a thin NGX listing is not hypothetical - raw %K is `0/0` and
    there is no answer.
    `pandas-ta-classic` returns 0.0, not by choosing that answer but by adding a float
    epsilon to the denominator to avoid the exception, and 0.0 says "at the very bottom
    of its range", which is a claim about a market that did not move. That is the
    zero-for-an-absence mistake `_column` exists to prevent, arriving through the back
    door, so the affected bars are set to None instead.

    A smoothed value that averaged in an undefined one is undefined too, so the mask is
    widened through both smoothings: `smooth_k` bars for %K, then `d` more for %D. It
    cannot be done by value - a legitimate %K of exactly 0.0 (the close at the low of a
    real range) is common and must survive.
    """
    import pandas_ta_classic as ta

    frame = _frame(bars)
    n = len(bars)
    out = ta.stoch(
        frame["high"],
        frame["low"],
        frame["close"],
        k=k,
        d=d,
        smooth_k=smooth_k,
        mamode="sma",
        talib=False,
    )
    if out is None:
        return [Series(name, _absent(n)) for name in ("stoch_k", "stoch_d")]

    no_range = frame["high"].rolling(k).max() == frame["low"].rolling(k).min()
    # `min_periods=1` so the warm-up rows, where the rolling max is NaN and the
    # comparison is therefore False, stay untainted - they are already None.
    tainted_k = no_range.astype(float).rolling(smooth_k, min_periods=1).max() > 0
    tainted_d = tainted_k.astype(float).rolling(d, min_periods=1).max() > 0
    return [
        Series("stoch_k", _column(_pick(out, "STOCHk_").where(~tainted_k), n)),
        Series("stoch_d", _column(_pick(out, "STOCHd_").where(~tainted_d), n)),
    ]


CATALOGUE: dict[str, IndicatorSpec] = {
    "rsi14": IndicatorSpec("rsi14", {"length": 14}, ("rsi14",), _rsi),
    # RSI-21 is here from the start rather than as an afterthought: `docs/03` P6.2's
    # point about `param_hash` is that two lengths of the same indicator are two
    # different features, and a catalogue holding only one of them never tests that.
    "rsi21": IndicatorSpec("rsi21", {"length": 21}, ("rsi21",), _rsi),
    "macd": IndicatorSpec(
        "macd",
        {"fast": 12, "slow": 26, "signal": 9},
        ("macd", "macd_signal", "macd_hist"),
        _macd,
    ),
    "bbands": IndicatorSpec(
        "bbands", {"length": 20, "std": 2.0}, ("bb_lower", "bb_mid", "bb_upper"), _bbands
    ),
    # `atr14` carries its period in the name and `bb_upper` does not, following the
    # column names `docs/08` §2.7's DDL comment gives ('rsi14', 'macd_hist'). The name
    # is a label; `param_hash` is what actually separates two parameter sets, which is
    # why two Bollinger widths can share the name `bb_upper` without colliding.
    "atr14": IndicatorSpec("atr14", {"length": 14}, ("atr14",), _atr),
    "obv": IndicatorSpec("obv", {}, ("obv",), _obv),
    "stoch": IndicatorSpec(
        "stoch", {"k": 14, "d": 3, "smooth_k": 3}, ("stoch_k", "stoch_d"), _stoch
    ),
}


def compute(bars: AdjustedBars, spec: IndicatorSpec) -> list[Series]:
    """Run one spec over one security's bars. Pure: no session, no clock, no writes."""
    series = spec.fn(bars, **spec.params)
    names = tuple(s.name for s in series)
    if names != spec.outputs:
        raise ValueError(f"{spec.key} declared outputs {spec.outputs} but produced {names}")
    return series

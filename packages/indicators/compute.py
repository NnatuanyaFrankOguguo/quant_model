"""The indicator catalogue: what is computed, from what, under which parameters. P6.2.

Compute functions take data and return data and do no I/O (`docs/08` §6), which is what
lets `tests/known_answer/` check them against hand-computed vectors. Persistence lives in
`store.py`.

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
"""

from __future__ import annotations

import datetime as dt
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


# --------------------------------------------------------------------------------------
# The six. `docs/03` P6.2: RSI, MACD, Bollinger Bands, ATR, OBV, Stochastic.
# --------------------------------------------------------------------------------------


def _rsi(bars: AdjustedBars, *, length: int) -> list[Series]:
    """Relative strength index, Wilder smoothing - see the module note on convention."""
    import pandas_ta_classic as ta

    frame = _frame(bars)
    out = ta.rsi(frame["close"], length=length)
    return [Series(f"rsi{length}", _column(out, len(bars)))]


CATALOGUE: dict[str, IndicatorSpec] = {
    "rsi14": IndicatorSpec("rsi14", {"length": 14}, ("rsi14",), _rsi),
    # RSI-21 is here from the start rather than as an afterthought: `docs/03` P6.2's
    # point about `param_hash` is that two lengths of the same indicator are two
    # different features, and a catalogue holding only one of them never tests that.
    "rsi21": IndicatorSpec("rsi21", {"length": 21}, ("rsi21",), _rsi),
}


def compute(bars: AdjustedBars, spec: IndicatorSpec) -> list[Series]:
    """Run one spec over one security's bars. Pure: no session, no clock, no writes."""
    series = spec.fn(bars, **spec.params)
    names = tuple(s.name for s in series)
    if names != spec.outputs:
        raise ValueError(f"{spec.key} declared outputs {spec.outputs} but produced {names}")
    return series


def known_as_of_for(bars: AdjustedBars, index: int, *, window: int) -> dt.date:
    """When the value at `index` became knowable: the newest vintage among its inputs.

    An indicator is knowable once every bar it consumed was knowable, so this is a max
    over the window rather than the vintage of the last bar. A restated bar inside the
    window pushes the whole value's vintage forward, which is the honest answer - the
    number could not have been computed before the restatement existed.
    """
    start = max(0, index - window + 1)
    return max(bars.known_as_of[start : index + 1])

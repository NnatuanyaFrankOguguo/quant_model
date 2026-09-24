"""Writing indicator rows, and the two decisions that took the longest. P6.2, P6.3.

Separate from `compute.py` because compute functions take data and return data and do no
I/O (`docs/08` §6) - which is what lets them be checked against hand-computed vectors.

## `known_as_of` is a running maximum, not a window

An indicator value became knowable once every bar it consumed was knowable, so its
vintage is a maximum over its inputs rather than the vintage of its last bar. The
question is which inputs.

For a windowed indicator - a 20-day Bollinger mean - that is the last 20 bars. For a
*recursive* one it is the whole history: Wilder smoothing, and every EMA, carries a
decaying dependence on every bar since the seed, so RSI on bar 5,000 genuinely does
depend on bar 1. There is no window to take a maximum over.

So the vintage here is a **running maximum over every bar up to and including the one
being described**. For the recursive indicators that is exactly right. For the windowed
ones it is conservative: it can claim a value became knowable later than it strictly did,
if a bar outside the window was restated. That is the safe direction and the only safe
direction - the opposite error would let P7 read a value before it existed, which is the
one thing point-in-time discipline exists to prevent. `docs/03` P6.3: *"An indicator
computed today from a price series that was later revised is not what was knowable on the
date. P7 depends on this absolutely."*

## A row means a value

Rows are written only where the indicator produced one. During an indicator's warm-up
there is no value, and the absence of a row says so; the length of that warm-up is
derivable from the parameters, which are stored beside every row.

The alternative - writing NULL-valued rows across every warm-up - would add roughly a
fortnight of rows per indicator per security saying nothing that the parameters do not
already say, and would blur the distinction the nullable column exists for: a value that
is genuinely absent *mid-series*, which is a fact about the data rather than about the
calculation's start-up.

## Re-running is a no-op, never an overwrite

`ON CONFLICT DO NOTHING` against the primary key, which carries `known_as_of`. Recomputing
at the same vintage inserts nothing; recomputing after a restatement has a new vintage and
so inserts new rows beside the old ones rather than destroying them. The `no_update`
trigger from migration 0002 makes that the only available behaviour rather than the polite
one - an `ON CONFLICT DO UPDATE` here would raise, by design.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from packages.common.models import Indicator
from packages.indicators.compute import CODE_VERSION, IndicatorSpec, compute
from packages.indicators.series import AdjustedBars

__all__ = ["StoreResult", "running_vintages", "store_for_security"]


@dataclass(frozen=True)
class StoreResult:
    security_id: int
    rows_offered: int
    rows_written: int
    series_written: tuple[str, ...]

    @property
    def rows_already_present(self) -> int:
        return self.rows_offered - self.rows_written


def running_vintages(bars: AdjustedBars) -> list[dt.date]:
    """The newest bar vintage at or before each bar. See the module note.

    Monotonic by construction, which is the property that matters: a value's `known_as_of`
    can never go backwards as the series advances.
    """
    out: list[dt.date] = []
    highest = dt.date.min
    for vintage in bars.known_as_of:
        if vintage > highest:
            highest = vintage
        out.append(highest)
    return out


def store_for_security(
    session: Session,
    *,
    security_id: int,
    bars: AdjustedBars,
    specs: list[IndicatorSpec],
    price_series: str = "adjusted",
) -> StoreResult:
    """Compute every spec over one security's bars and insert what is missing.

    `price_series` is recorded on every row rather than assumed. `docs/08` §2.7 keeps it
    in the table so the rule that indicators are built on adjusted prices is auditable in
    rows already written, not only in a lint rule that can see the next commit and not the
    last one. The default is the only value any caller should be passing; `'raw'` exists
    so that a deliberate exception has to name itself.
    """
    if price_series not in ("adjusted", "raw"):
        raise ValueError(f"price_series must be 'adjusted' or 'raw', not {price_series!r}")
    if len(bars) == 0:
        return StoreResult(security_id, 0, 0, ())

    vintages = running_vintages(bars)
    payload: list[dict[str, object]] = []
    names: list[str] = []

    for spec in specs:
        for series in compute(bars, spec):
            names.append(series.name)
            for i, value in enumerate(series.values):
                if value is None:
                    continue  # no value yet - the absence of a row says so
                payload.append(
                    {
                        "security_id": security_id,
                        "date": bars.dates[i],
                        "name": series.name,
                        "param_hash": spec.hash,
                        "known_as_of": vintages[i],
                        "params": spec.params,
                        "value": value,
                        "price_series": price_series,
                        "code_version": CODE_VERSION,
                    }
                )

    if not payload:
        return StoreResult(security_id, 0, 0, tuple(names))

    before = session.execute(
        select(func.count()).select_from(Indicator).where(Indicator.security_id == security_id)
    ).scalar_one()

    # Chunked: a single statement with two million parameter sets is not a statement any
    # driver enjoys, and Neon drops a connection held open too long mid-write.
    for start in range(0, len(payload), 5_000):
        session.execute(
            insert(Indicator).on_conflict_do_nothing(constraint="indicators_pkey"),
            payload[start : start + 5_000],
        )
    session.commit()

    after = session.execute(
        select(func.count()).select_from(Indicator).where(Indicator.security_id == security_id)
    ).scalar_one()

    return StoreResult(security_id, len(payload), after - before, tuple(names))

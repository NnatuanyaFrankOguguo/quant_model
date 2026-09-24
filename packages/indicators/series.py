"""Point-in-time adjusted OHLCV series - the input every indicator is computed from.

`packages/common/adjust.py` answers the question for one bar. This answers it for a whole
history at once, because an indicator needs a series and calling the single-bar function
269,000 times would issue 269,000 queries and re-walk the factor list for every one.

**The two must never disagree.** `adjusted_close()` walks the factor list per bar;
this precomputes suffix products and looks each bar up. That is an optimisation, and an
optimisation that quietly rounds differently is how a feature set goes subtly wrong with
nothing to report it. `tests/.../test_series.py` asserts the two agree bar for bar on a
real security across a real split, and the arithmetic here stays in `Decimal` until the
frame is built so there is nothing for it to disagree about.

Why this matters more here than anywhere else: `docs/03` P6 marks "indicators on
unadjusted prices" as the phase's one 🔴 FRAGILE risk - *"Silent; corrupts P8's entire
feature set."* A split leaves a 4x cliff in a raw close series. RSI reads that cliff as
the most violent sell-off in the security's history, and nothing downstream can tell that
it was a clerical event rather than a market one.
"""

from __future__ import annotations

import bisect
import datetime as dt
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from packages.common.adjust import factors_known
from packages.common.models import PriceHistory

__all__ = ["AdjustedBars", "adjusted_bars", "cumulative_factors_for"]


class AdjustedBars:
    """One security's adjusted history, as parallel lists in date order.

    Deliberately not a DataFrame at this layer. pandas is an optional extra
    (`pyproject.toml` keeps the analytical stack out of the default install), and the
    reconciliation test that proves this agrees with `adjusted_close` should not need it.
    `to_frame()` is there for the indicator engine, which does.
    """

    __slots__ = ("dates", "open", "high", "low", "close", "volume", "factor", "known_as_of")

    def __init__(
        self,
        dates: list[dt.date],
        open_: list[Decimal | None],
        high: list[Decimal | None],
        low: list[Decimal | None],
        close: list[Decimal],
        volume: list[Decimal | None],
        factor: list[Decimal],
        known_as_of: list[dt.date],
    ) -> None:
        self.dates = dates
        self.open = open_
        self.high = high
        self.low = low
        self.close = close
        self.volume = volume
        self.factor = factor
        self.known_as_of = known_as_of

    def __len__(self) -> int:
        return len(self.dates)

    def to_frame(self):  # type: ignore[no-untyped-def]
        """A float DataFrame for the indicator library. Imported lazily - see the note above.

        Floats, not Decimals: every indicator is float arithmetic (exponential smoothing
        has no exact decimal form), and pretending otherwise by carrying Decimal into a
        moving average would claim an exactness the calculation does not have. The
        Decimal series above stays the record; this is the view handed to the maths.
        """
        import pandas as pd

        def floats(values: list[Decimal | None]) -> list[float | None]:
            return [None if v is None else float(v) for v in values]

        return pd.DataFrame(
            {
                "open": floats(self.open),
                "high": floats(self.high),
                "low": floats(self.low),
                "close": [float(v) for v in self.close],
                "volume": floats(self.volume),
            },
            index=pd.DatetimeIndex(self.dates, name="date"),
        )


def cumulative_factors_for(
    on_dates: list[dt.date], factors: list[tuple[dt.date, Decimal]]
) -> list[tuple[Decimal, int]]:
    """`cumulative_factor` for many dates at once, by suffix product. Pure.

    A bar's multiplier is the product of every factor whose ex-date is strictly after it,
    which is a suffix of the ex-date-sorted list. Computing the suffixes once makes each
    bar a binary search instead of a full walk: O(m + n log m) rather than O(n * m).

    `factors` must be sorted by ex-date, which is what `factors_known` returns.
    """
    ex_dates = [ex for ex, _ in factors]
    # suffix[i] = product of factors[i:], so suffix[len] == 1 for a bar after them all.
    suffix: list[Decimal] = [Decimal(1)] * (len(factors) + 1)
    for i in range(len(factors) - 1, -1, -1):
        suffix[i] = suffix[i + 1] * factors[i][1]

    out: list[tuple[Decimal, int]] = []
    for on in on_dates:
        # First index whose ex-date is strictly greater than the bar's date.
        i = bisect.bisect_right(ex_dates, on)
        out.append((suffix[i], len(factors) - i))
    return out


def adjusted_bars(
    session: Session,
    *,
    security_id: int,
    decision_date: dt.date,
    start: dt.date | None = None,
    end: dt.date | None = None,
) -> AdjustedBars:
    """Every bar knowable on `decision_date`, adjusted by the actions knowable then.

    No default for `decision_date`, for the reason `adjust.py` gives: a series adjusted
    "as of today" is not what any past date could have seen, and an indicator built from
    it has quietly consumed the future.

    Where a bar has been restated, the newest vintage at or before the decision date
    wins - `price_history` keys on `known_as_of`, so a restatement is another row rather
    than an overwrite, and taking the max is what "as known then" means.

    Volume is divided by the factor rather than multiplied. A 4-for-1 split takes the
    price to a quarter and the share count to four times, so the factor that scales a
    price down scales the quantity up. OBV accumulates volume, and mixing pre- and
    post-split quantities puts a step in it that has nothing to do with buying pressure.
    """
    if not isinstance(decision_date, dt.date):
        raise TypeError("decision_date must be a date - there is no default of today")

    query = (
        select(
            PriceHistory.date,
            PriceHistory.open_raw,
            PriceHistory.high_raw,
            PriceHistory.low_raw,
            PriceHistory.close_raw,
            PriceHistory.volume,
            PriceHistory.known_as_of,
        )
        .where(PriceHistory.security_id == security_id)
        .where(PriceHistory.known_as_of <= decision_date)
    )
    if start is not None:
        query = query.where(PriceHistory.date >= start)
    if end is not None:
        query = query.where(PriceHistory.date <= end)
    rows = session.execute(query.order_by(PriceHistory.date, PriceHistory.known_as_of)).all()

    # Ordered by vintage within each date, so the last write per date is the newest one
    # knowable. dict preserves insertion order, which keeps the dates ascending.
    newest: dict[dt.date, tuple] = {}
    for row in rows:
        newest[row[0]] = row

    dates = list(newest)
    factors = cumulative_factors_for(
        dates, factors_known(session, security_id=security_id, decision_date=decision_date)
    )

    def scaled(value: Decimal | None, factor: Decimal) -> Decimal | None:
        return None if value is None else value * factor

    bars = AdjustedBars([], [], [], [], [], [], [], [])
    for date, (factor, _applied) in zip(dates, factors, strict=True):
        _d, open_, high, low, close, volume, known_as_of = newest[date]
        bars.dates.append(date)
        bars.open.append(scaled(open_, factor))
        bars.high.append(scaled(high, factor))
        bars.low.append(scaled(low, factor))
        bars.close.append(close * factor)
        bars.volume.append(None if volume is None else Decimal(volume) / factor)
        bars.factor.append(factor)
        bars.known_as_of.append(known_as_of)
    return bars

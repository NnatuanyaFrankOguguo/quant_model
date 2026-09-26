"""Read-side macro queries: series summaries, staleness, and vintages. P1.4's engine.

Lives in a package, not in the API layer and certainly not in Streamlit (AD-3: *"business
logic in a Streamlit callback is a defect"*). The API serializes what this returns; the
dashboard renders what the API returns. That is what makes swapping Streamlit for Next.js at
P9 a presentation change.

Two ideas here are load-bearing:

**Staleness is computed, not stored.** `CLAUDE.md`: *"every series shows its as-of date and
flags when overdue."* A stored flag is wrong the moment the clock moves; a computed one
cannot be. `expected_lag_days` on `macro_series` is the threshold, which is why every value
of it being unverified (migration 0005) is worth saying out loud rather than hiding behind a
tidy boolean.

**The default view is the latest vintage; the point-in-time view is explicit.** For a human
looking at a dashboard, "the current value" is right. For anything a model reads, the
question is *what was known on date D*, and `as_known_on` answers it by filtering
`known_as_of <= D` and taking the newest surviving vintage per period. Both live here so the
distinction is one argument rather than two code paths that drift.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from packages.common.models import DataSource, MacroObservation, MacroSeries
from packages.common.timez import utctoday

__all__ = [
    "IRREGULAR",
    "ObservationPage",
    "ObservationPoint",
    "SeriesSummary",
    "list_series",
    "observation_page",
    "observations",
    "series_summary",
]

#: A series set by decision rather than by calendar — the MPR changes when the MPC changes
#: it and not otherwise. Staleness is meaningless for these: an unchanged rate is the
#: normal state, and flagging it would train the reader to ignore the flag that matters.
IRREGULAR = "irregular"


@dataclass(frozen=True)
class ObservationPoint:
    as_of_date: dt.date
    known_as_of: dt.date
    value: Decimal | None


@dataclass(frozen=True)
class SeriesSummary:
    code: str
    name: str
    unit: str
    frequency: str
    base_period: str | None
    expected_lag_days: int
    source_name: str
    attribution: str | None
    observation_count: int
    latest_as_of: dt.date | None
    latest_known_as_of: dt.date | None
    latest_value: Decimal | None
    days_since_as_of: int | None
    #: `None` means "not applicable" (irregular series, or no data yet) — deliberately not
    #: `False`, so a caller cannot render "fresh" for a series nobody can judge.
    is_stale: bool | None


def _latest_vintage_subquery(as_known_on: dt.date | None):
    """Newest `known_as_of` per (series, period), optionally as known on a date.

    This is the point-in-time join. With `as_known_on` set, vintages published after that
    date are invisible — which is the difference between a backtest that is honest and one
    that quietly knew the future.
    """
    query = select(
        MacroObservation.series_id.label("series_id"),
        MacroObservation.as_of_date.label("as_of_date"),
        func.max(MacroObservation.known_as_of).label("known_as_of"),
    )
    if as_known_on is not None:
        query = query.where(MacroObservation.known_as_of <= as_known_on)
    return query.group_by(MacroObservation.series_id, MacroObservation.as_of_date).subquery()


def _staleness(
    frequency: str, latest_as_of: dt.date | None, expected_lag_days: int, today: dt.date
) -> tuple[int | None, bool | None]:
    if latest_as_of is None:
        return None, None
    days = (today - latest_as_of).days
    if frequency == IRREGULAR:
        return days, None
    return days, days > expected_lag_days


def list_series(
    session: Session, *, on: dt.date | None = None, as_known_on: dt.date | None = None
) -> list[SeriesSummary]:
    """Every series with its latest observation and whether it is overdue."""
    today = on or utctoday()
    latest = _latest_vintage_subquery(as_known_on)

    # The newest period per series, and the value at its newest visible vintage.
    newest_period = (
        select(
            latest.c.series_id,
            func.max(latest.c.as_of_date).label("as_of_date"),
        )
        .group_by(latest.c.series_id)
        .subquery()
    )

    rows = session.execute(
        select(
            MacroSeries,
            DataSource.source_name,
            DataSource.attribution_text,
            newest_period.c.as_of_date,
            MacroObservation.known_as_of,
            MacroObservation.value,
        )
        .join(DataSource, DataSource.id == MacroSeries.data_source_id)
        .outerjoin(newest_period, newest_period.c.series_id == MacroSeries.id)
        .outerjoin(
            latest,
            (latest.c.series_id == MacroSeries.id)
            & (latest.c.as_of_date == newest_period.c.as_of_date),
        )
        .outerjoin(
            MacroObservation,
            (MacroObservation.series_id == latest.c.series_id)
            & (MacroObservation.as_of_date == latest.c.as_of_date)
            & (MacroObservation.known_as_of == latest.c.known_as_of),
        )
        .order_by(MacroSeries.code)
    ).all()

    count_rows = session.execute(
        select(MacroObservation.series_id, func.count()).group_by(MacroObservation.series_id)
    ).all()
    counts: dict[int, int] = {series_id: n for series_id, n in count_rows}

    summaries: list[SeriesSummary] = []
    for series, source_name, attribution, latest_as_of, known_as_of, value in rows:
        days_since, is_stale = _staleness(
            series.frequency, latest_as_of, series.expected_lag_days, today
        )
        summaries.append(
            SeriesSummary(
                code=series.code,
                name=series.name,
                unit=series.unit,
                frequency=series.frequency,
                base_period=series.base_period,
                expected_lag_days=series.expected_lag_days,
                source_name=source_name,
                attribution=attribution,
                observation_count=counts.get(series.id, 0),
                latest_as_of=latest_as_of,
                latest_known_as_of=known_as_of,
                latest_value=value,
                days_since_as_of=days_since,
                is_stale=is_stale,
            )
        )
    return summaries


def series_summary(
    session: Session, code: str, *, on: dt.date | None = None
) -> SeriesSummary | None:
    for summary in list_series(session, on=on):
        if summary.code == code:
            return summary
    return None


@dataclass(frozen=True)
class ObservationPage:
    """Points, plus whether they are all of them.

    `total_available` and `truncated` exist so a partial answer can never be mistaken for a
    whole one. A series like `US_10Y_TREASURY` holds 16,876 periods; returning the most recent
    slice is the right default for a chart, but a caller that silently received 2,000 of
    16,876 and drew a line from it would be drawing a different series.
    """

    points: list[ObservationPoint]
    total_available: int
    truncated: bool


def observations(
    session: Session,
    code: str,
    *,
    start: dt.date | None = None,
    end: dt.date | None = None,
    as_known_on: dt.date | None = None,
    limit: int | None = None,
) -> list[ObservationPoint]:
    """One point per period, at the newest vintage visible on `as_known_on`.

    Thin wrapper over :func:`observation_page` for callers that only want the points.
    """
    return observation_page(
        session, code, start=start, end=end, as_known_on=as_known_on, limit=limit
    ).points


def observation_page(
    session: Session,
    code: str,
    *,
    start: dt.date | None = None,
    end: dt.date | None = None,
    as_known_on: dt.date | None = None,
    limit: int | None = None,
) -> ObservationPage:
    """One point per period, newest vintage, optionally limited to the most recent `limit`.

    **The limit takes the most recent periods, not the first.** Asking for "some" of a price
    series and receiving 1962 onwards would be useless for every caller that exists, and the
    full series is still reachable with an explicit `start`/`end` window.

    Returns an empty page for an unknown code rather than raising — the caller distinguishes
    "no such series" from "no data" via `list_series`, and a 404 is the API's decision.
    """
    series_id = session.execute(
        select(MacroSeries.id).where(MacroSeries.code == code)
    ).scalar_one_or_none()
    if series_id is None:
        return ObservationPage(points=[], total_available=0, truncated=False)

    latest = _latest_vintage_subquery(as_known_on)
    base = (
        select(MacroObservation.as_of_date, MacroObservation.known_as_of, MacroObservation.value)
        .join(
            latest,
            (latest.c.series_id == MacroObservation.series_id)
            & (latest.c.as_of_date == MacroObservation.as_of_date)
            & (latest.c.known_as_of == MacroObservation.known_as_of),
        )
        .where(MacroObservation.series_id == series_id)
    )
    if start is not None:
        base = base.where(MacroObservation.as_of_date >= start)
    if end is not None:
        base = base.where(MacroObservation.as_of_date <= end)

    total = session.execute(select(func.count()).select_from(base.subquery())).scalar_one()

    if limit is None:
        rows = session.execute(base.order_by(MacroObservation.as_of_date)).all()
    else:
        # Newest first to apply the limit, then flipped back so the caller always receives
        # points in chronological order — a chart that plots them in arrival order draws
        # time backwards, and nothing in the response would say so.
        newest = session.execute(
            base.order_by(MacroObservation.as_of_date.desc()).limit(limit)
        ).all()
        rows = list(reversed(newest))

    return ObservationPage(
        points=[
            ObservationPoint(
                as_of_date=row.as_of_date, known_as_of=row.known_as_of, value=row.value
            )
            for row in rows
        ],
        total_available=total,
        truncated=len(rows) < total,
    )

"""The public router - data only, no verdicts.

Everything mounted here is reachable by an anonymous caller, and by the public
after the SEC licence changes ``licence_status``. ``PublicAPIRoute`` refuses at
import time to mount a route whose ``response_model`` is not registered as a public
legal type, so the failure lands on whoever adds the route rather than on whoever
reads the response six months later.
"""

import datetime as dt

from fastapi import APIRouter, Depends, HTTPException, Query

from packages.common.db import get_session
from packages.common.timez import utctoday
from packages.compliance.mode import Mode
from packages.ingestion import macro
from services.api.deps import get_mode
from services.api.middleware.assert_response import PublicAPIRoute
from services.api.routers import API_V1
from services.api.schemas import (
    MacroObservationPoint,
    MacroObservations,
    MacroSeriesInfo,
    MacroSeriesList,
    PublicPing,
)

router = APIRouter(prefix=f"{API_V1}/public", tags=["public"], route_class=PublicAPIRoute)


@router.get("/ping", response_model=PublicPing)
async def ping(mode: Mode = Depends(get_mode)) -> PublicPing:
    """Return the mode the *server* derived for this caller.

    Not a constant. The value comes from the middleware, which derived it from the
    principal behind the credential and from ``licence_status`` - never from
    anything in this request. That is what makes ``docs/03`` P0.8's injection tests
    worth running: they assert on a value that actually flows through the gate.
    """
    return PublicPing(mode=mode)


@router.get("/macro/series", response_model=MacroSeriesList)
async def macro_series() -> MacroSeriesList:
    """Every macro series, with its as-of date and whether it has gone overdue.

    No `mode` parameter and no principal check: published government statistics are
    public-tier content in every mode. Access is still restricted to owner and family by
    who can obtain a token, not by what this route serves (`CLAUDE.md`'s access model).
    """
    with get_session() as session:
        summaries = macro.list_series(session)
        return MacroSeriesList(
            as_of=utctoday(),
            series=[
                MacroSeriesInfo(
                    code=s.code,
                    name=s.name,
                    unit=s.unit,
                    frequency=s.frequency,
                    base_period=s.base_period,
                    source_name=s.source_name,
                    attribution=s.attribution,
                    expected_lag_days=s.expected_lag_days,
                    observation_count=s.observation_count,
                    latest_as_of=s.latest_as_of,
                    latest_known_as_of=s.latest_known_as_of,
                    latest_value=s.latest_value,
                    days_since_as_of=s.days_since_as_of,
                    is_stale=s.is_stale,
                )
                for s in summaries
            ],
        )


@router.get("/macro/series/{code}/observations", response_model=MacroObservations)
async def macro_observations(
    code: str,
    start: dt.date | None = Query(default=None, description="Earliest period to return"),
    end: dt.date | None = Query(default=None, description="Latest period to return"),
    as_known_on: dt.date | None = Query(
        default=None,
        description=(
            "Point-in-time view: exclude vintages published after this date. Omit to see "
            "each period at its newest vintage."
        ),
    ),
) -> MacroObservations:
    """The observation array for one series.

    `as_known_on` is the parameter that makes this honest. Without it a caller sees today's
    view of history, in which every restatement has always been known — which is exactly the
    lookahead that makes a P7 backtest profitable and wrong.
    """
    with get_session() as session:
        summary = macro.series_summary(session, code)
        if summary is None:
            raise HTTPException(status_code=404, detail="not_found")
        points = macro.observations(session, code, start=start, end=end, as_known_on=as_known_on)
        return MacroObservations(
            code=summary.code,
            name=summary.name,
            unit=summary.unit,
            source_name=summary.source_name,
            attribution=summary.attribution,
            as_known_on=as_known_on,
            observations=[
                MacroObservationPoint(
                    as_of_date=p.as_of_date, known_as_of=p.known_as_of, value=p.value
                )
                for p in points
            ],
        )

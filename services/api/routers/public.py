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

#: Enough for a readable chart of any series in the set, and small enough that one request
#: is bounded work. A caller wanting more narrows the window or raises the limit to the cap.
DEFAULT_OBSERVATION_LIMIT = 2000
#: Hard ceiling, enforced by the route rather than trusted to the caller.
MAX_OBSERVATION_LIMIT = 20000

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
    limit: int = Query(
        default=DEFAULT_OBSERVATION_LIMIT,
        ge=1,
        le=MAX_OBSERVATION_LIMIT,
        description=(
            "Maximum points to return, taking the most recent. Responses say "
            "`truncated` and `total_available` so a partial series is never mistaken "
            "for a whole one."
        ),
    ),
) -> MacroObservations:
    """The observation array for one series.

    `as_known_on` is the parameter that makes this honest. Without it a caller sees today's
    view of history, in which every restatement has always been known — which is exactly the
    lookahead that makes a P7 backtest profitable and wrong.

    **The limit is not decoration.** `US_10Y_TREASURY` holds 16,876 periods; an unbounded
    endpoint meant one request did unbounded work, which is a slow dashboard today and a
    trivial way to exhaust the server at P12. The cap is enforced by the route, so no caller
    can opt out of it.
    """
    with get_session() as session:
        summary = macro.series_summary(session, code)
        if summary is None:
            raise HTTPException(status_code=404, detail="not_found")
        page = macro.observation_page(
            session, code, start=start, end=end, as_known_on=as_known_on, limit=limit
        )
        return MacroObservations(
            code=summary.code,
            name=summary.name,
            unit=summary.unit,
            source_name=summary.source_name,
            attribution=summary.attribution,
            as_known_on=as_known_on,
            total_available=page.total_available,
            truncated=page.truncated,
            observations=[
                MacroObservationPoint(
                    as_of_date=p.as_of_date, known_as_of=p.known_as_of, value=p.value
                )
                for p in page.points
            ],
        )

"""The public router - data only, no verdicts.

Everything mounted here is reachable by an anonymous caller, and by the public
after the SEC licence changes ``licence_status``. ``PublicAPIRoute`` refuses at
import time to mount a route whose ``response_model`` is not registered as a public
legal type, so the failure lands on whoever adds the route rather than on whoever
reads the response six months later.
"""

from fastapi import APIRouter, Depends

from packages.compliance.mode import Mode
from services.api.deps import get_mode
from services.api.middleware.assert_response import PublicAPIRoute
from services.api.routers import API_V1
from services.api.schemas import PublicPing

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

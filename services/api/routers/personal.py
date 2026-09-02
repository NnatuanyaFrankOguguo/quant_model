"""The personal router - requires ``entitlements.personal_tier``.

Pre-licence this tier is lawful because no fee is charged and no funds are pooled
(``PROJECT_CONTEXT.md`` 4, ``SPEC.md`` 1.2), and it is reachable only by principals
whose ``kind`` is ``owner`` or ``family`` - the entitlement flag alone is not
sufficient (``docs/10_PRE_BUILD_CORRECTIONS.md`` 4.6, invariant I11).

``require_personal`` is a router-level dependency, not a per-endpoint one: a route
added to this file inherits the gate whether or not its author remembers it.
"""

from fastapi import APIRouter, Depends

from services.api.deps import RequestContext, require_personal
from services.api.middleware.assert_response import GuardedAPIRoute
from services.api.routers import API_V1
from services.api.schemas import PersonalPing

router = APIRouter(
    prefix=f"{API_V1}/personal",
    tags=["personal"],
    route_class=GuardedAPIRoute,
    dependencies=[Depends(require_personal)],
)


@router.get("/ping", response_model=PersonalPing)
async def ping(ctx: RequestContext = Depends(require_personal)) -> PersonalPing:
    """403 for anyone the server did not derive personal mode for.

    Anonymous, an expired or revoked token, a disabled principal, an unentitled
    principal, a service principal, and a ``kind='public'`` principal holding
    ``personal_tier`` pre-licence all land on the same 403 with the same body. The
    caller cannot tell which of those they are, which is the intent.
    """
    return PersonalPing(mode=ctx.mode)

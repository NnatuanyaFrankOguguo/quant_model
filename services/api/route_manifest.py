"""The declared route manifest - the version of the coverage test that bites.

``docs/10_PRE_BUILD_CORRECTIONS.md`` 4.5 retires
``test_every_registered_route_is_gate_covered``. That test asserts
``route_has_mode_middleware(route)``, and under the globally-applied middleware
that ``docs/01_ARCHITECTURE.md`` 3 recommends, the predicate is true for every
route by construction - including ``/openapi.json``, ``/docs``, and any router
mounted outside both trees next month. *"The test the docs call 'the important one'
passes trivially in exactly the configuration the docs recommend."*

The manifest is the replacement. Every route is declared here, by hand, with its
class, the mode it serves and the type it returns. The test in
``tests/compliance/test_route_manifest.py`` asserts the manifest and ``app.routes``
agree in **both** directions, so:

* a route added without a manifest entry fails CI, naming its own path;
* a manifest entry left behind by a deleted route fails CI too.

Adding a line here is a deliberate act. That is the entire mechanism: it makes
"which routes exist, and what may each one emit" a question with a written answer
that CI keeps honest, rather than something you reconstruct by reading routers.
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from enum import Enum

from packages.compliance.mode import Mode
from services.api.schemas import (
    CompanyDcf,
    CompanyDividends,
    CompanyFilings,
    CompanyList,
    CompanyRatioHistory,
    CompanyRatios,
    CompanyStatements,
    ConnectorHealthReport,
    CorrectionRateReport,
    DocumentStored,
    Health,
    HoldingsSummary,
    MacroObservations,
    MacroSeriesList,
    ManualEntryAccepted,
    PersonalPing,
    PublicPing,
    RecentFilings,
    ReviewQueue,
)

__all__ = ["MANIFEST", "RouteClass", "RouteSpec", "registered_routes"]


class RouteClass(str, Enum):
    """What kind of surface a route is, for the compliance test to check."""

    #: Liveness and operations. Anonymous-reachable, so it must still return a
    #: public-legal type.
    INFRA = "infra"
    #: Data only, no verdicts. Under ``/v1/public``.
    PUBLIC_DATA = "public_data"
    #: May carry advice. Under ``/v1/personal``, behind ``personal_tier``.
    PERSONAL_ADVICE = "personal_advice"


@dataclass(frozen=True)
class RouteSpec:
    route_class: RouteClass
    #: The mode a caller must be in to receive a 2xx. ``None`` for infrastructure,
    #: which serves either mode.
    mode: Mode | None
    #: The declared ``response_model``.
    response_model: type


#: Every route the application registers. Keys are ``"<METHOD> <path>"``.
MANIFEST: dict[str, RouteSpec] = {
    "GET /health": RouteSpec(RouteClass.INFRA, None, Health),
    "GET /v1/public/ping": RouteSpec(RouteClass.PUBLIC_DATA, Mode.PUBLIC, PublicPing),
    "GET /v1/public/macro/series": RouteSpec(RouteClass.PUBLIC_DATA, Mode.PUBLIC, MacroSeriesList),
    "GET /v1/public/macro/series/{code}/observations": RouteSpec(
        RouteClass.PUBLIC_DATA, Mode.PUBLIC, MacroObservations
    ),
    "GET /v1/public/operations/connectors": RouteSpec(
        RouteClass.PUBLIC_DATA, Mode.PUBLIC, ConnectorHealthReport
    ),
    "GET /v1/public/companies": RouteSpec(RouteClass.PUBLIC_DATA, Mode.PUBLIC, CompanyList),
    "GET /v1/public/summary": RouteSpec(RouteClass.PUBLIC_DATA, Mode.PUBLIC, HoldingsSummary),
    "GET /v1/public/companies/{ticker}/statements": RouteSpec(
        RouteClass.PUBLIC_DATA, Mode.PUBLIC, CompanyStatements
    ),
    "GET /v1/public/companies/{ticker}/ratios": RouteSpec(
        RouteClass.PUBLIC_DATA, Mode.PUBLIC, CompanyRatios
    ),
    "GET /v1/public/companies/{ticker}/ratios/history": RouteSpec(
        RouteClass.PUBLIC_DATA, Mode.PUBLIC, CompanyRatioHistory
    ),
    "GET /v1/public/companies/{ticker}/dividends": RouteSpec(
        RouteClass.PUBLIC_DATA, Mode.PUBLIC, CompanyDividends
    ),
    "GET /v1/public/companies/{ticker}/filings": RouteSpec(
        RouteClass.PUBLIC_DATA, Mode.PUBLIC, CompanyFilings
    ),
    "GET /v1/public/filings/recent": RouteSpec(RouteClass.PUBLIC_DATA, Mode.PUBLIC, RecentFilings),
    "GET /v1/public/companies/{ticker}/dcf": RouteSpec(
        RouteClass.PUBLIC_DATA, Mode.PUBLIC, CompanyDcf
    ),
    "GET /v1/personal/ping": RouteSpec(RouteClass.PERSONAL_ADVICE, Mode.PERSONAL, PersonalPing),
    # P3.1 and P3.2's write surfaces. Personal-tier because they change the record:
    # an anonymous caller must not be able to add a figure, and the name on a typed
    # figure is the authenticated principal's.
    "POST /v1/personal/documents": RouteSpec(
        RouteClass.PERSONAL_ADVICE, Mode.PERSONAL, DocumentStored
    ),
    # P4.4's review surface. Personal-tier not merely because it is write-adjacent: it
    # names companies beside figures this system believes are wrong, which is an internal
    # judgement rather than a fact about the company, and serving it anonymously would be
    # publishing an accusation.
    "GET /v1/personal/review/queue": RouteSpec(
        RouteClass.PERSONAL_ADVICE, Mode.PERSONAL, ReviewQueue
    ),
    "GET /v1/personal/review/correction-rate": RouteSpec(
        RouteClass.PERSONAL_ADVICE, Mode.PERSONAL, CorrectionRateReport
    ),
    "POST /v1/personal/statements": RouteSpec(
        RouteClass.PERSONAL_ADVICE, Mode.PERSONAL, ManualEntryAccepted
    ),
}


def iter_routes(app: object, prefix: str = "") -> Iterator[tuple[str, object]]:
    """Yield ``(full_path, route)`` for every leaf route, recursing into routers.

    **This has to recurse, and the reason is a live trap.** From FastAPI 0.141,
    ``include_router`` no longer flattens a router's routes into ``app.routes`` - it
    appends one lazy ``_IncludedRouter`` wrapper per include, holding the real routes
    on ``original_router``. A loop over ``app.routes`` that expects ``APIRoute``
    objects therefore finds **none**, and every assertion inside it passes over an
    empty set.

    That is the exact failure shape ``docs/10`` 4.5 retired the old coverage test
    for: a green test that asserts nothing. Here it would be worse than tautological,
    because the tests it silently disables are the ones proving each route carries the
    response guard. Discovery goes through this one function so there is a single
    place to get it right.
    """
    for route in getattr(app, "routes", []):
        # FastAPI >= 0.141 lazy include wrapper.
        included = getattr(route, "original_router", None)
        if included is not None:
            context = getattr(route, "include_context", None)
            yield from iter_routes(included, prefix + (getattr(context, "prefix", "") or ""))
            continue
        # A directly-nested router or Mount.
        if hasattr(route, "routes") and getattr(route, "endpoint", None) is None:
            yield from iter_routes(route, prefix + (getattr(route, "path", "") or ""))
            continue
        path = getattr(route, "path", None)
        if path is None:
            continue
        yield prefix + path, route


def registered_routes(app: object) -> set[str]:
    """``{"<METHOD> <path>"}`` for every route the app actually has.

    Includes anything FastAPI mounts on our behalf. ``/docs``, ``/redoc`` and
    ``/openapi.json`` are switched off in :mod:`services.api.main` rather than
    listed here - FastAPI's auto-schema publishes the entire ``/v1/personal/*``
    route list and ``PersonalSignal``'s field names to anonymous callers
    (``docs/10`` 4.5). If they are ever re-enabled, this function surfaces them and
    the manifest test fails until somebody decides that on purpose.
    """
    found: set[str] = set()
    for path, route in iter_routes(app):
        methods = getattr(route, "methods", None)
        if not methods:
            found.add(f"* {path}")
            continue
        for method in methods:
            found.add(f"{method} {path}")
    return found

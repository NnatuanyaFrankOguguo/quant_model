"""The route manifest test - the coverage test that actually bites.

``docs/10_PRE_BUILD_CORRECTIONS.md`` 4.5 retires
``test_every_registered_route_is_gate_covered``. Under the globally-applied
middleware that ``docs/01`` 3 recommends, ``route_has_mode_middleware(route)`` is
true for every route by construction, so *"the test the docs call 'the important
one' passes trivially in exactly the configuration the docs recommend"*.

This is the replacement, and the property that makes it bite is that it fails in
**both** directions:

* a route registered with no manifest entry fails, naming its own path;
* a manifest entry with no registered route fails too.

Neither can be satisfied by the middleware being global. Somebody has to write a
line declaring what the new route serves.
"""

from __future__ import annotations

import pytest

from packages.compliance.mode import Mode
from packages.compliance.response_types import public_legal_types
from services.api.main import app
from services.api.middleware.assert_response import GuardedAPIRoute, PublicAPIRoute
from services.api.middleware.audit import AuditMiddleware
from services.api.middleware.mode import ModeMiddleware
from services.api.route_manifest import MANIFEST, RouteClass, iter_routes, registered_routes

# Module level on purpose. `from __future__ import annotations` turns every annotation
# into a string, and `GuardedAPIRoute` resolves an endpoint's return hint with
# `typing.get_type_hints`, which looks in the defining module's globals. Imported
# inside a test function, `PublicPing` is not there, and the route guard fails with a
# NameError that looks like a bug in the guard rather than in the test.
from services.api.schemas import PublicPing  # noqa: E402


@pytest.mark.invariant
def test_route_manifest_is_exhaustive_and_exact() -> None:
    """`docs/10` 4.5, verbatim, plus the reason each half exists."""
    registered = registered_routes(app)
    declared = set(MANIFEST)
    assert registered == declared, (
        f"unclassified (registered but not in MANIFEST): {sorted(registered - declared)}; "
        f"stale (in MANIFEST but not registered): {sorted(declared - registered)}. "
        f"Add or remove the line in services/api/route_manifest.py deliberately."
    )


@pytest.mark.invariant
def test_adding_a_route_without_a_manifest_entry_fails() -> None:
    """Prove the test above is not vacuous, by making it fail on purpose."""
    from fastapi import APIRouter, FastAPI

    probe = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
    router = APIRouter(route_class=GuardedAPIRoute)

    @router.get("/v1/public/undeclared", response_model=PublicPing)
    async def undeclared() -> PublicPing:
        return PublicPing(mode=Mode.PUBLIC)

    probe.include_router(router)
    assert "GET /v1/public/undeclared" in registered_routes(probe)
    assert "GET /v1/public/undeclared" not in MANIFEST


@pytest.mark.invariant
def test_no_interactive_docs_are_published() -> None:
    """`docs/10` 4.5 - the auto-schema publishes the personal route list anonymously."""
    paths = {entry.split(" ", 1)[1] for entry in registered_routes(app)}
    for leaked in ("/docs", "/redoc", "/openapi.json", "/docs/oauth2-redirect"):
        assert leaked not in paths, f"{leaked} is registered; it exposes /v1/personal/* to anyone"


@pytest.mark.invariant
def test_every_public_route_declares_a_public_legal_response_model() -> None:
    legal = public_legal_types()
    for key, spec in MANIFEST.items():
        if spec.route_class in (RouteClass.PUBLIC_DATA, RouteClass.INFRA):
            assert spec.response_model in legal, (
                f"{key} is anonymously reachable but declares {spec.response_model.__name__}, "
                f"which is not registered as a public legal type"
            )


@pytest.mark.invariant
def test_route_classes_match_their_path_prefix() -> None:
    """A personal-advice route living outside /v1/personal is mechanism 2 broken."""
    for key, spec in MANIFEST.items():
        path = key.split(" ", 1)[1]
        if spec.route_class is RouteClass.PERSONAL_ADVICE:
            assert path.startswith("/v1/personal/"), key
            assert spec.mode is Mode.PERSONAL, key
        elif spec.route_class is RouteClass.PUBLIC_DATA:
            assert path.startswith("/v1/public/"), key
            assert spec.mode is Mode.PUBLIC, key
        else:
            assert not path.startswith("/v1/"), f"{key} is infra but sits on the versioned API"


@pytest.mark.invariant
def test_every_api_path_is_versioned() -> None:
    """`docs/10` 6.5 - versioning is free today and a breaking change later."""
    for key in MANIFEST:
        path = key.split(" ", 1)[1]
        assert path == "/health" or path.startswith("/v1/"), (
            f"{key} is neither /health nor versioned. Every API path is /v1/*."
        )


@pytest.mark.invariant
def test_every_route_object_uses_a_guarded_route_class() -> None:
    """Mechanisms 3 and 4 are inherited from the route class, not remembered."""
    from fastapi.routing import APIRoute

    seen = 0
    for path, route in iter_routes(app):
        if not isinstance(route, APIRoute):
            continue
        seen += 1
        assert isinstance(route, GuardedAPIRoute), f"{path} bypasses the response guard"
        if path.startswith("/v1/public/"):
            assert isinstance(route, PublicAPIRoute), (
                f"{path} is public but does not use PublicAPIRoute, so its "
                f"response_model is never checked against the allow-list at build time"
            )
    # Non-vacuity. Without this the test passes on an empty iteration, which is exactly
    # what FastAPI 0.141's lazy `_IncludedRouter` made it do: `app.routes` holds wrapper
    # objects, not `APIRoute`s, so the loop above ran zero times and asserted nothing.
    assert seen == len(MANIFEST), f"expected {len(MANIFEST)} API routes, walked {seen}"


@pytest.mark.invariant
def test_middleware_order_puts_audit_outside_mode() -> None:
    """Audit must wrap Mode, or 404s and unhandled exceptions write no row.

    Starlette runs the last-added middleware outermost, and `user_middleware` is
    ordered outermost-first.
    """
    classes = [m.cls for m in app.user_middleware]
    assert AuditMiddleware in classes and ModeMiddleware in classes
    assert classes.index(AuditMiddleware) < classes.index(ModeMiddleware), (
        f"middleware order is {[c.__name__ for c in classes]}; audit must be outermost"
    )

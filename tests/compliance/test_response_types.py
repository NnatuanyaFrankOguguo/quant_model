"""Mechanisms 3 and 4 - the response-type allow-list and the field-name rule.

The three failures these cover, in the order they are likely to happen:

1. A handler in the personal tree gets copy-pasted onto a public path. Runtime 500.
2. A public model grows a ``verdict`` / ``target`` / ``score`` field. Import error.
3. A public route is declared returning a type nobody allow-listed, or a raw
   ``Response``. Build failure - the app does not start.
"""

from __future__ import annotations

import pytest
from fastapi import APIRouter, FastAPI
from fastapi.responses import StreamingResponse
from fastapi.testclient import TestClient
from pydantic import BaseModel

from packages.compliance.mode import Mode
from packages.compliance.response_types import (
    BANNED_PUBLIC_FIELD_NAMES,
    PublicFieldNameViolation,
    ResponseTypeViolation,
    assert_legal,
    public_legal_types,
    register_public_type,
    walk_field_names,
)
from services.api.middleware.assert_response import (
    GuardedAPIRoute,
    PublicAPIRoute,
    RouteConfigurationError,
)
from services.api.middleware.mode import ModeMiddleware
from services.api.schemas import Health, PersonalPing, PersonalSignal, PublicPing

SIGNAL = PersonalSignal(
    security="GTCO",
    direction="long",
    calibrated_prob=0.61,
    position_size=0.04,
    backtest_run_id=44,
)


@pytest.mark.invariant
def test_personal_payload_on_a_public_route_raises() -> None:
    """`docs/03` P0.8's sixth test. 500, not 403 - it is our bug, not the caller's."""
    with pytest.raises(ResponseTypeViolation) as caught:
        assert_legal(Mode.PUBLIC, SIGNAL)
    assert caught.value.status_code == 500
    assert caught.value.type_name == "PersonalSignal"


@pytest.mark.invariant
def test_personal_ping_is_not_public_legal() -> None:
    """The two ping types are distinct so the type check has something to say."""
    assert PublicPing in public_legal_types()
    assert PersonalPing not in public_legal_types()
    assert PersonalSignal not in public_legal_types()
    assert Health in public_legal_types()


@pytest.mark.invariant
def test_personal_mode_permits_everything() -> None:
    assert_legal(Mode.PERSONAL, SIGNAL)  # must not raise


@pytest.mark.invariant
@pytest.mark.parametrize("payload", [{"mode": "public"}, [1, 2], "text", None, 42])
def test_raw_payloads_are_illegal_in_public_mode(payload: object) -> None:
    """`docs/10` 4.7 - a bare dict, a stream or a string has nothing to type-check."""
    with pytest.raises(ResponseTypeViolation):
        assert_legal(Mode.PUBLIC, payload)


@pytest.mark.invariant
def test_allow_list_is_exact_type_not_isinstance() -> None:
    """`docs/10` 4.3's `PersonalMemo(PublicMemo)` shape must not slip through."""

    class SubclassOfAPublicType(PublicPing):
        pass

    with pytest.raises(ResponseTypeViolation):
        assert_legal(Mode.PUBLIC, SubclassOfAPublicType(mode=Mode.PUBLIC))


@pytest.mark.invariant
@pytest.mark.parametrize("model", sorted(public_legal_types(), key=lambda m: m.__name__))
def test_public_types_carry_no_advice_shaped_field(model: type) -> None:
    """`docs/10` 4.3, verbatim."""
    offending = walk_field_names(model) & BANNED_PUBLIC_FIELD_NAMES
    assert not offending, f"{model.__name__}: {sorted(offending)}"


@pytest.mark.invariant
def test_registering_an_advice_shaped_model_fails_at_import_time() -> None:
    class Leaky(BaseModel):
        ticker: str
        target: float

    with pytest.raises(PublicFieldNameViolation):
        register_public_type(Leaky)


@pytest.mark.invariant
def test_the_field_name_rule_reaches_nested_models() -> None:
    """A `verdict` two levels down is still a `verdict`."""

    class Inner(BaseModel):
        verdict: str | None = None

    class Middle(BaseModel):
        items: list[Inner] = []

    class Outer(BaseModel):
        payload: Middle | None = None

    assert "verdict" in walk_field_names(Outer)
    with pytest.raises(PublicFieldNameViolation):
        register_public_type(Outer)


# --------------------------------------------------------------------------- #
# Build-time refusals on the public router.
# --------------------------------------------------------------------------- #


@pytest.mark.invariant
def test_public_route_with_an_unregistered_response_model_is_a_build_failure() -> None:
    router = APIRouter(route_class=PublicAPIRoute)
    with pytest.raises(RouteConfigurationError, match="not registered as a public legal type"):

        @router.get("/leak", response_model=PersonalPing)
        async def leak() -> PersonalPing:
            return PersonalPing(mode=Mode.PERSONAL)


@pytest.mark.invariant
def test_public_route_with_no_response_model_is_a_build_failure() -> None:
    router = APIRouter(route_class=PublicAPIRoute)
    with pytest.raises(RouteConfigurationError, match="declares no response_model"):

        @router.get("/unlabelled")
        async def unlabelled():
            return {"anything": True}


@pytest.mark.invariant
def test_public_route_returning_a_raw_response_is_a_build_failure() -> None:
    """`docs/10` 4.4 - this is the bulk-export bypass, refused before it exists."""
    router = APIRouter(route_class=PublicAPIRoute)
    with pytest.raises(RouteConfigurationError, match="raw Response"):

        @router.get("/export.csv", response_model=PublicPing)
        async def export() -> StreamingResponse:
            return StreamingResponse(iter([b""]))


# --------------------------------------------------------------------------- #
# Runtime: the guard fires on a real request through the real middleware.
# --------------------------------------------------------------------------- #


@pytest.mark.invariant
def test_a_leaking_handler_returns_500_through_the_real_stack() -> None:
    """The case the build-time check cannot catch: the wrong object at runtime.

    `GuardedAPIRoute` (not `PublicAPIRoute`) so the route is declarable, exactly as
    it would be if someone mounted a personal handler outside the public tree and
    an anonymous caller reached it.
    """
    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
    app.add_middleware(ModeMiddleware)
    router = APIRouter(route_class=GuardedAPIRoute)

    @router.get("/leak", response_model=PersonalSignal)
    async def leak() -> PersonalSignal:
        return SIGNAL

    app.include_router(router)

    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.get("/leak")

    assert response.status_code == 500
    # The advice itself must not be in the body of the error either.
    assert "GTCO" not in response.text
    assert "0.61" not in response.text


@pytest.mark.invariant
def test_the_guard_records_the_response_type_it_allowed() -> None:
    """The value that reaches ``audit_log.response_type`` is set by the guard.

    Driven through the guard itself rather than through HTTP, so the assertion is
    about the mechanism and not about one route happening to work.
    """
    import asyncio

    from services.api.deps import RequestContext, reset_current_context, set_current_context
    from services.api.middleware.assert_response import _guard_endpoint

    async def endpoint() -> PublicPing:
        return PublicPing(mode=Mode.PUBLIC)

    guarded = _guard_endpoint(endpoint)
    ctx = RequestContext(mode=Mode.PUBLIC)
    token = set_current_context(ctx)
    try:
        assert asyncio.run(guarded()) == PublicPing(mode=Mode.PUBLIC)
    finally:
        reset_current_context(token)

    assert ctx.response_type == "PublicPing"


@pytest.mark.invariant
def test_the_guard_assumes_public_when_no_context_exists() -> None:
    """A broken middleware stack must fail closed, not fall through to personal."""
    import asyncio

    from services.api.deps import current_context
    from services.api.middleware.assert_response import _guard_endpoint

    async def endpoint() -> PersonalSignal:
        return SIGNAL

    assert current_context() is None
    with pytest.raises(ResponseTypeViolation):
        asyncio.run(_guard_endpoint(endpoint)())

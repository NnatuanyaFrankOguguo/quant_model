"""Mechanisms 3 and 4 at the response boundary - route classes, not middleware.

By the time a response reaches an ASGI middleware it is bytes, and the Python type
that made it - the thing mechanism 3 exists to check - is gone. So the assertion
runs one layer in, at the route: :class:`GuardedAPIRoute` wraps the endpoint
function and inspects what it *returned*, before FastAPI serialises it.

Two levels of enforcement, because a runtime check that fires in production is a
check that fired too late:

**Build time** - :class:`PublicAPIRoute` refuses at import to mount a route whose
``response_model`` is not in the public allow-list, or which returns a raw
``Response`` (``docs/10_PRE_BUILD_CORRECTIONS.md`` 4.7: *"In public mode a handler
must return a Pydantic model from PUBLIC_LEGAL_TYPES; returning a bare Response is
a build failure."*). The app will not start.

**Request time** - :class:`GuardedAPIRoute` calls
:func:`~packages.compliance.response_types.assert_legal` and
:func:`~packages.compliance.banned_phrases.assert_clean` against the *live*
server-derived mode. That is the check that catches the case the static one cannot:
a personal-tree handler copy-pasted onto a public path, or a shared helper that
returns the wrong object under some branch.

Both route classes are applied at the ``APIRouter`` level, so an endpoint cannot
forget to opt in - the failure mode ``docs/01_ARCHITECTURE.md`` 3 rejects approach
2 for.
"""

from __future__ import annotations

import functools
import inspect
import typing
from collections.abc import Callable
from typing import Any

from fastapi.routing import APIRoute
from starlette.concurrency import run_in_threadpool
from starlette.responses import Response

from packages.compliance.banned_phrases import assert_clean
from packages.compliance.mode import Mode
from packages.compliance.response_types import assert_legal, public_legal_types
from services.api.deps import current_context

__all__ = ["GuardedAPIRoute", "PublicAPIRoute", "RouteConfigurationError"]

_GUARD_MARKER = "__quant_response_guard__"


class RouteConfigurationError(Exception):
    """A route was declared in a way the compliance gate cannot enforce.

    Raised at import time. The service does not start.
    """


def _resolve_annotations_in_place(endpoint: Callable[..., Any]) -> None:
    """Replace string annotations with the objects they name.

    Needed because the guard below wraps the endpoint, and FastAPI resolves string
    annotations against ``call.__globals__`` - which, for a wrapper defined in
    *this* module, is this module's namespace rather than the router's. Resolving
    them here, in the endpoint's own module, removes the trap entirely instead of
    leaving a rule ("never use postponed annotations in a router") for someone to
    break in eight months.
    """
    try:
        hints = typing.get_type_hints(endpoint, include_extras=True)
    except Exception as exc:  # noqa: BLE001
        raise RouteConfigurationError(
            "cannot resolve type hints for endpoint "
            f"{getattr(endpoint, '__qualname__', endpoint)!r}"
        ) from exc
    endpoint.__annotations__ = hints


def _guard_endpoint(endpoint: Callable[..., Any]) -> Callable[..., Any]:
    """Wrap an endpoint so its return value is checked before serialisation."""
    if getattr(endpoint, _GUARD_MARKER, False):
        return endpoint
    _resolve_annotations_in_place(endpoint)
    is_async = inspect.iscoroutinefunction(endpoint)

    @functools.wraps(endpoint)
    async def guarded(*args: Any, **kwargs: Any) -> Any:
        if is_async:
            payload = await endpoint(*args, **kwargs)
        else:
            payload = await run_in_threadpool(endpoint, *args, **kwargs)

        ctx = current_context()
        # No context means the mode middleware did not run, which should be
        # impossible. Assume public: the strict branch, so a broken stack fails
        # visibly on the next personal payload instead of quietly serving it.
        mode = ctx.mode if ctx is not None else Mode.PUBLIC

        assert_legal(mode, payload)  # mechanism 3
        assert_clean(mode, payload)  # mechanism 4

        if ctx is not None:
            ctx.response_type = type(payload).__name__
        return payload

    setattr(guarded, _GUARD_MARKER, True)
    return guarded


class GuardedAPIRoute(APIRoute):
    """Every route in the application uses this or a subclass."""

    def __init__(self, path: str, endpoint: Callable[..., Any], **kwargs: Any) -> None:
        super().__init__(path, _guard_endpoint(endpoint), **kwargs)


class PublicAPIRoute(GuardedAPIRoute):
    """Routes under ``/v1/public``. Adds the build-time half of mechanism 3."""

    def __init__(self, path: str, endpoint: Callable[..., Any], **kwargs: Any) -> None:
        response_model = kwargs.get("response_model")
        _assert_public_response_model(path, endpoint, response_model)
        super().__init__(path, endpoint, **kwargs)


def _assert_public_response_model(
    path: str, endpoint: Callable[..., Any], response_model: Any
) -> None:
    legal = public_legal_types()
    if isinstance(response_model, type) and issubclass(response_model, Response):
        raise RouteConfigurationError(
            f"public route {path!r} declares a raw Response as its response_model. In public "
            f"mode a handler must return a Pydantic model from PUBLIC_LEGAL_TYPES so that "
            f"mechanisms 3 and 4 have something to inspect (docs/10 4.7)."
        )
    return_annotation = typing.get_type_hints(endpoint).get("return")
    if isinstance(return_annotation, type) and issubclass(return_annotation, Response):
        raise RouteConfigurationError(
            f"public route {path!r} returns a raw Response ({return_annotation.__name__}). "
            f"Streaming a SELECT past the gate is exactly the bulk-export bypass in docs/10 4.4."
        )
    if response_model is None or not isinstance(response_model, type):
        raise RouteConfigurationError(
            f"public route {path!r} declares no response_model. Every public route must name "
            f"the type it returns so the allow-list can be checked before the service starts."
        )
    if response_model not in legal:
        raise RouteConfigurationError(
            f"public route {path!r} declares response_model {response_model.__name__}, which is "
            f"not registered as a public legal type. Decorate it with @register_public_type in "
            f"services/api/schemas.py if it genuinely carries no advice, or move the route to "
            f"the personal router."
        )

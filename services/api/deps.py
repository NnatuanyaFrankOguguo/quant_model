"""Per-request context, and the FastAPI dependencies that read it.

The context is created once, by :class:`services.api.middleware.mode.ModeMiddleware`,
and reached two ways:

* ``request.state.ctx`` - for handlers, via the ASGI ``scope["state"]`` dict, which
  every middleware layer shares by reference.
* :func:`current_context` - a :class:`~contextvars.ContextVar`, for the response
  guard in :mod:`services.api.middleware.assert_response`, which wraps the endpoint
  function and so has no ``Request`` to read.

Both point at the *same* mutable object, so a value written by the guard after the
handler returns (``response_type``) is visible to the audit middleware wrapped
around the outside of it. Context variables only propagate downwards; a shared
object propagates in both directions, which is what this needs.

Nothing here ever consults the request for the mode. The dependencies read it from
the context the middleware already derived, and that derivation
(:mod:`packages.compliance.mode`) has no request in scope at all.
"""

from __future__ import annotations

import uuid
from collections.abc import MutableMapping
from contextvars import ContextVar, Token
from dataclasses import dataclass, field
from typing import Any

from fastapi import HTTPException, Request

from packages.compliance.auth import ANONYMOUS, ResolvedPrincipal, principal_label
from packages.compliance.mode import Mode

__all__ = [
    "RequestContext",
    "current_context",
    "get_context",
    "get_mode",
    "get_principal",
    "require_personal",
    "reset_current_context",
    "set_current_context",
]

_STATE_KEY = "ctx"


@dataclass
class RequestContext:
    """Everything the gate decided about one request.

    ``mode`` defaults to :data:`Mode.PUBLIC` so that a context constructed on an
    error path - before anything is known - is the restrictive one.
    """

    request_id: uuid.UUID = field(default_factory=uuid.uuid4)
    mode: Mode = Mode.PUBLIC
    principal: ResolvedPrincipal | None = None
    response_type: str | None = None
    error: str | None = None

    @property
    def principal_label(self) -> str:
        """``audit_log.principal`` - ``'anonymous'`` when unauthenticated."""
        if self.principal is None:
            return ANONYMOUS
        return principal_label(self.principal)


_current: ContextVar[RequestContext | None] = ContextVar("quant_request_context", default=None)


def set_current_context(ctx: RequestContext) -> Token[RequestContext | None]:
    return _current.set(ctx)


def reset_current_context(token: Token[RequestContext | None]) -> None:
    _current.reset(token)


def current_context() -> RequestContext | None:
    """The context for the request being handled on this task, if any."""
    return _current.get()


def attach_context(scope: MutableMapping[str, Any], ctx: RequestContext) -> None:
    """Publish the context on the ASGI scope so ``request.state.ctx`` finds it.

    ``MutableMapping``, not ``dict``: an ASGI scope is only guaranteed to be a mutable
    mapping, and Starlette types it that way. Narrowing to ``dict`` here type-errors at
    every call site in the middleware.
    """
    state = scope.setdefault("state", {})
    state[_STATE_KEY] = ctx


def context_from_scope(scope: MutableMapping[str, Any]) -> RequestContext | None:
    state = scope.get("state")
    if not isinstance(state, dict):
        return None
    ctx = state.get(_STATE_KEY)
    return ctx if isinstance(ctx, RequestContext) else None


def get_context(request: Request) -> RequestContext:
    """FastAPI dependency. Falls back to a fresh public context, never to personal.

    The fallback should be unreachable - the middleware is global - but if it ever
    is reached, the handler runs in public mode rather than crashing or guessing.
    """
    ctx = context_from_scope(request.scope)
    if ctx is None:  # pragma: no cover - defensive
        ctx = RequestContext()
        attach_context(request.scope, ctx)
    return ctx


def get_mode(request: Request) -> Mode:
    """FastAPI dependency: the server-derived mode for this request."""
    return get_context(request).mode


def get_principal(request: Request) -> ResolvedPrincipal | None:
    """FastAPI dependency: the resolved principal, or ``None`` for anonymous."""
    return get_context(request).principal


def require_personal(request: Request) -> RequestContext:
    """Guard for every ``/v1/personal/*`` route.

    403, not 401: an anonymous caller and a caller holding a revoked token are
    indistinguishable from the outside, and should be. A 401 with a
    ``WWW-Authenticate`` challenge would tell a prober that a valid token exists
    for this endpoint.
    """
    ctx = get_context(request)
    if ctx.mode is not Mode.PERSONAL:
        raise HTTPException(status_code=403, detail="forbidden")
    return ctx

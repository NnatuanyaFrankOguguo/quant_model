"""Mechanism 1 at the HTTP boundary: resolve the principal, derive the mode.

Pure ASGI middleware, not ``BaseHTTPMiddleware``. Two reasons, both practical:
``BaseHTTPMiddleware`` runs the downstream app in a separate anyio task, which
breaks the context variable the response guard depends on; and it buffers the
response, which we would rather not do on a service that will stream exports.

The **only** thing this module reads from the request is the ``Authorization``
header. Not the body, not the query string, not a cookie, not the path or its
casing, not ``X-Mode``, not anything else a client controls. A test walks this
file's AST and fails if it ever grows a reference to ``query_params``, ``cookies``,
``path_params``, ``form`` or ``json`` (``tests/compliance/test_mode_gate.py``).

Every error path returns :data:`~packages.compliance.mode.Mode.PUBLIC`
(``docs/10_PRE_BUILD_CORRECTIONS.md`` 4.6): a database outage, a malformed
credential, an entitlements lookup that raises, an unparseable ``licence_status``.
Fail closed, loudly, but closed.
"""

from __future__ import annotations

from starlette.datastructures import Headers
from starlette.types import ASGIApp, Receive, Scope, Send

from packages.compliance.auth import ResolvedPrincipal, resolve_principal
from packages.compliance.mode import Mode, log_compliance_error, resolve_mode_for_principal
from services.api.deps import (
    RequestContext,
    attach_context,
    reset_current_context,
    set_current_context,
)

__all__ = ["ModeMiddleware", "resolve_mode"]

_AUTHORIZATION = "authorization"


def resolve_mode(authorization: str | None) -> tuple[ResolvedPrincipal | None, Mode, str | None]:
    """Credential -> (principal, mode, error). Never raises.

    Returns the error string so the audit row can carry it: a fail-closed request
    that looks like an ordinary 403 in the log is a fail-closed request nobody
    investigates.
    """
    try:
        principal = resolve_principal(authorization)
    except Exception as exc:  # noqa: BLE001 - DB down, driver error, anything
        error = f"principal_resolution_failed:{type(exc).__name__}"
        log_compliance_error("principal_resolution_failed", error_type=type(exc).__name__)
        # Not merely "no personal tier" - we do not know who this is at all, so
        # the audit row must say anonymous rather than name a principal we guessed.
        return None, Mode.PUBLIC, error

    try:
        mode = resolve_mode_for_principal(principal)
    except Exception as exc:  # noqa: BLE001 - resolve_mode_for_principal is itself
        # fail-closed, so reaching here means something failed even in its handler.
        error = f"mode_resolution_failed:{type(exc).__name__}"
        log_compliance_error("mode_resolution_failed", error_type=type(exc).__name__)
        # Keep the principal for forensics; the mode is public regardless.
        return principal, Mode.PUBLIC, error

    return principal, mode, None


class ModeMiddleware:
    """Global. Every request passes through here, including ones that 404."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        authorization = Headers(scope=scope).get(_AUTHORIZATION)
        principal, mode, error = resolve_mode(authorization)
        ctx = RequestContext(mode=mode, principal=principal, error=error)

        attach_context(scope, ctx)
        token = set_current_context(ctx)
        try:
            await self.app(scope, receive, send)
        finally:
            reset_current_context(token)

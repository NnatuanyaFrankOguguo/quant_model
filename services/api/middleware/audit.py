"""Mechanism 5 of five - one ``audit_log`` row per request. Every request.

``docs/01_ARCHITECTURE.md`` 3: *"Alone it prevents nothing - it is after the fact.
But it is the only mechanism that lets you answer 'who saw what, when', which is
precisely the question a regulator asks, and the question you cannot answer
retroactively if you did not record it."*

"Every request" is meant literally, and is the part that is easy to get wrong:

* 403s and 500s, not just successes - a refused attempt is the interesting row.
* Requests that never matched a route. A 404 on ``/v1/personal/signals`` before
  that route exists is somebody probing, and it should be in the log.
* Requests whose handler raised. The audit row is written from the ``except``
  block and the exception is re-raised untouched.

This middleware sits **outside** :class:`~services.api.middleware.mode.ModeMiddleware`
so all three of those are inside it.

**A failed audit write must not swallow the response, but must be loud.** Refusing
to serve because the ledger is down turns a bookkeeping outage into a total outage;
serving silently means the row is missing and nobody knows. So: the response goes
out, and the failure is counted in :data:`AUDIT_WRITE_FAILURES` and logged at error
level. ``docs/03`` P0's check 16 is to read the log by eye and confirm nothing is
missing - this counter is what makes that check answerable without doing it.
"""

from __future__ import annotations

import time
from collections import Counter
from datetime import UTC, datetime
from typing import Any

from starlette.datastructures import MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from packages.common import db
from packages.common.models import AuditLog
from packages.compliance.auth import ANONYMOUS
from packages.compliance.mode import Mode, log_compliance_error
from services.api.deps import RequestContext, context_from_scope

__all__ = ["AUDIT_WRITE_FAILURES", "AuditMiddleware", "write_audit_row"]

#: Loud counter for audit writes that failed. Never silently zero: a non-zero value
#: means the ledger has holes and the compliance story has a gap in it.
AUDIT_WRITE_FAILURES: Counter[str] = Counter()

_MAX_ENDPOINT_CHARS = 500
_REQUEST_ID_HEADER = "x-request-id"


def write_audit_row(
    *,
    ctx: RequestContext | None,
    method: str,
    endpoint: str,
    http_status: int,
    latency_ms: int,
    error: str | None = None,
) -> None:
    """Insert one ``audit_log`` row. Never raises."""
    principal = ctx.principal_label if ctx is not None else ANONYMOUS
    mode = ctx.mode if ctx is not None else Mode.PUBLIC
    response_type = ctx.response_type if ctx is not None else None
    request_id = ctx.request_id if ctx is not None else None
    combined_error = error or (ctx.error if ctx is not None else None)

    try:
        with db.get_session() as session:
            session.add(
                AuditLog(
                    ts=datetime.now(UTC),
                    principal=principal,
                    mode=mode.value,
                    method=method,
                    endpoint=endpoint[:_MAX_ENDPOINT_CHARS],
                    response_type=response_type,
                    http_status=http_status,
                    request_id=request_id,
                    latency_ms=latency_ms,
                    error=combined_error,
                )
            )
            session.commit()
    except Exception as exc:  # noqa: BLE001 - see the module docstring
        AUDIT_WRITE_FAILURES[type(exc).__name__] += 1
        log_compliance_error(
            "audit_write_failed",
            error_type=type(exc).__name__,
            endpoint=endpoint[:_MAX_ENDPOINT_CHARS],
            http_status=http_status,
        )


class AuditMiddleware:
    """Outermost application middleware. Writes exactly one row per request."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        started = time.perf_counter()
        method = str(scope.get("method", ""))
        # The path only. Not the query string: `docs/10` 4.7 keeps caller-supplied
        # *values* out of logs, and the attempt itself is recorded either way.
        endpoint = str(scope.get("path", ""))
        status: dict[str, Any] = {"code": 500}

        async def send_wrapper(message: Message) -> None:
            if message["type"] == "http.response.start":
                status["code"] = int(message.get("status", 500))
                ctx = context_from_scope(scope)
                if ctx is not None:
                    # Ties the response the caller holds to its audit row.
                    MutableHeaders(scope=message).append(_REQUEST_ID_HEADER, str(ctx.request_id))
            await send(message)

        try:
            await self.app(scope, receive, send_wrapper)
        except Exception as exc:
            latency_ms = int((time.perf_counter() - started) * 1000)
            write_audit_row(
                ctx=context_from_scope(scope),
                method=method,
                endpoint=endpoint,
                http_status=500,
                latency_ms=latency_ms,
                error=f"unhandled:{type(exc).__name__}",
            )
            raise
        else:
            latency_ms = int((time.perf_counter() - started) * 1000)
            write_audit_row(
                ctx=context_from_scope(scope),
                method=method,
                endpoint=endpoint,
                http_status=status["code"],
                latency_ms=latency_ms,
            )

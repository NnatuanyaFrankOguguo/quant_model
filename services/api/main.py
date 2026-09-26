"""The FastAPI application - P0.5, the compliance mode gate.

Three endpoints, and the five mechanisms that will still be enforcing the gate when
there are three hundred. ``docs/03_ROADMAP_PART1_PHASES_0-6.md`` P0.5: *"It is
built now, empty, so that every endpoint added in every later phase inherits it by
construction rather than by discipline."*

    ServerError -> Audit -> Mode -> ExceptionMiddleware -> router -> guarded endpoint
                     (5)     (1)                             (2)          (3)(4)

Paths are versioned - ``/v1/public/*``, ``/v1/personal/*`` - per
``docs/10_PRE_BUILD_CORRECTIONS.md`` 6.5, which calls versioning *"the cheapest
high-value fix in this audit"* and requires the change *before P0.5 is written*.
``/health`` stays unversioned.

The interactive docs are off. FastAPI's auto-schema publishes the whole
``/v1/personal/*`` route list and every field name of the personal response models
to anonymous callers, which is a disclosure the gate otherwise prevents
(``docs/10`` 4.5). P9 can serve a public-only schema deliberately.
"""

from __future__ import annotations

from fastapi import APIRouter, FastAPI, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy import text
from starlette.exceptions import HTTPException as StarletteHTTPException

from packages.common import db
from packages.common.config import get_settings
from packages.compliance.mode import log_compliance_error
from services.api.deps import get_context
from services.api.middleware.assert_response import GuardedAPIRoute
from services.api.middleware.audit import AuditMiddleware
from services.api.middleware.mode import ModeMiddleware
from services.api.routers import personal, public
from services.api.schemas import ErrorBody, Health

__all__ = ["app", "create_app"]

#: ``docs/10_PRE_BUILD_CORRECTIONS.md`` 4.7 - the closed error vocabulary. A
#: traceback, a field value, or the repr of a local variable must never reach a
#: response body: that is how a `PersonalMemo(verdict=...)` leaves the building
#: through a 500 rather than through a route.
_ERROR_VOCABULARY: dict[int, str] = {
    400: "invalid_request",
    401: "unauthorized",
    403: "forbidden",
    404: "not_found",
    405: "method_not_allowed",
    409: "conflict",
    413: "invalid_request",
    422: "invalid_request",
    429: "rate_limited",
}
_DEFAULT_ERROR = "internal"


def _error_response(
    request: Request, status_code: int, fields: list[str] | None = None
) -> Response:
    detail = _ERROR_VOCABULARY.get(status_code, _DEFAULT_ERROR)
    if status_code >= 500:
        detail = _DEFAULT_ERROR
    request_id: str | None = None
    try:
        request_id = str(get_context(request).request_id)
    except Exception:  # noqa: BLE001 - an error handler must not raise
        request_id = None
    body = ErrorBody(detail=detail, request_id=request_id, fields=fields or None)
    return JSONResponse(status_code=status_code, content=body.model_dump(exclude_none=True))


def _record_error(request: Request, label: str) -> None:
    """Put the reason on the context so the audit row carries it. The body will not."""
    try:
        ctx = get_context(request)
        if ctx.error is None:
            ctx.error = label
    except Exception:  # noqa: BLE001
        pass


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title="quant_model API",
        version=settings.app_version,
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )

    # Starlette runs the LAST-added middleware outermost. Mode must be inside
    # Audit so that a 404, a 405 and an unhandled exception all still produce an
    # audit row carrying whatever the gate managed to derive.
    app.add_middleware(ModeMiddleware)
    app.add_middleware(AuditMiddleware)

    infra = APIRouter(route_class=GuardedAPIRoute)

    @infra.get("/health", response_model=Health, tags=["infra"])
    async def health(response: Response) -> Health:
        """Liveness, and proof that the database connection works.

        503 when the database is unreachable. A health check that returns 200 while
        its only dependency is down is a health check that has to be ignored.
        """
        db_ok = _check_db()
        response.status_code = 200 if db_ok else 503
        return Health(
            status="ok" if db_ok else "degraded",
            version=settings.app_version,
            db="ok" if db_ok else "error",
            migrations=_alembic_head(),
        )

    app.include_router(infra)
    app.include_router(public.router)
    app.include_router(personal.router)

    @app.exception_handler(StarletteHTTPException)
    async def http_exception_handler(request: Request, exc: StarletteHTTPException) -> Response:
        _record_error(request, f"http_{exc.status_code}")
        if exc.status_code >= 500:
            log_compliance_error(
                "server_error_response",
                status_code=exc.status_code,
                exception_type=type(exc).__name__,
            )
        # `FieldedHTTPException` may name the fields at fault. Names only - the vocabulary
        # above still decides the `detail`, so nothing a route wrote reaches the body.
        fields = getattr(exc, "fields", None)
        return _error_response(request, exc.status_code, fields=fields)

    @app.exception_handler(RequestValidationError)
    async def validation_exception_handler(
        request: Request, exc: RequestValidationError
    ) -> Response:
        # Field NAMES only, never their values (docs/10 4.7).
        fields = sorted({".".join(str(p) for p in e.get("loc", ())) for e in exc.errors()})
        _record_error(request, "invalid_request")
        return _error_response(request, 422, fields=fields)

    @app.exception_handler(Exception)
    async def unhandled_exception_handler(request: Request, exc: Exception) -> Response:
        _record_error(request, f"unhandled:{type(exc).__name__}")
        log_compliance_error("unhandled_exception", exception_type=type(exc).__name__)
        return _error_response(request, 500)

    return app


def _check_db() -> bool:
    try:
        return bool(db.check_db())
    except Exception:  # noqa: BLE001 - /health must report, never raise
        return False


def _alembic_head() -> str:
    """Current migration revision, so ``/health`` answers 'which schema is this'."""
    try:
        with db.get_session() as session:
            row = session.execute(text("SELECT version_num FROM alembic_version")).first()
    except Exception:  # noqa: BLE001
        return "unknown"
    if not row:
        return "none"
    return str(row[0])


app = create_app()

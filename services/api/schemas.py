"""Response models for the P0 API, and the public/personal type split.

The split is the point. ``docs/10_PRE_BUILD_CORRECTIONS.md`` 4.3 rejects "one type
with a nullable advice field" because that downgrades a type-level guarantee to a
runtime convention defended by a single CHECK on the write path. So the public and
personal pings are *different types*, and only the public one is registered in
:func:`packages.compliance.response_types.public_legal_types`. Copy the personal
handler into the public router and the request fails with a 500 rather than
answering.

``@register_public_type`` also walks each model's fields at import time and refuses
any advice-shaped name, so the day someone adds ``target`` to a public model the
build breaks rather than the gate.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from packages.compliance.mode import Mode
from packages.compliance.response_types import register_public_type

__all__ = [
    "ErrorBody",
    "Health",
    "PersonalPing",
    "PersonalSignal",
    "PublicPing",
]


@register_public_type
class Health(BaseModel):
    """Liveness, plus the two facts that make it worth calling."""

    status: str = Field(description="'ok', or 'degraded' when the database is unreachable")
    version: str = Field(description="Application version")
    db: str = Field(description="'ok' or 'error'")
    migrations: str = Field(description="Current alembic revision, or 'unknown'")


@register_public_type
class PublicPing(BaseModel):
    """Proves the public router and mode derivation work.

    ``mode`` is the **server-derived** mode for the calling principal, not a
    constant. That distinction is the whole value of this endpoint: if it returned
    a hardcoded ``"public"``, ``docs/03`` P0.8's four injection tests would be
    asserting on a literal and would pass forever regardless of whether the gate
    worked. An entitled caller therefore sees ``"personal"`` here - which discloses
    nothing they do not already know, and keeps the tests honest.
    """

    mode: Mode


class PersonalPing(BaseModel):
    """Proves entitlement gating works. Deliberately **not** a public-legal type."""

    mode: Mode


class PersonalSignal(BaseModel):
    """The canonical advice-shaped payload. Never public-legal, in any phase.

    A placeholder in P0 - P8 fills in the real contract from
    ``docs/08_DATA_CONTRACTS.md`` 8, including ``authorised_by_backtest``. It exists
    now because the compliance suite needs a payload that *must* raise on a public
    route, and because it documents by example why ``PUBLIC_LEGAL_TYPES`` is an
    allow-list: every field below is a field a public response may never carry.
    """

    security: str
    direction: str
    calibrated_prob: float
    position_size: float
    backtest_run_id: int


class ErrorBody(BaseModel):
    """The fixed public error vocabulary (``docs/10`` 4.7).

    Error bodies, logs and Sentry sit outside all five mechanisms: an exception is
    raised before a response exists, and a traceback carrying a repr of a local
    ``PersonalMemo(verdict=...)`` would go into the 500 body. So public-mode errors
    are drawn from a closed vocabulary - ``not_found``, ``invalid_request`` (field
    *name* only, never the value), ``rate_limited``, ``forbidden``, ``internal`` -
    plus a ``request_id`` that ties the response to its ``audit_log`` row.
    """

    detail: str
    request_id: str | None = None
    fields: list[str] | None = Field(
        default=None,
        description="Names of the request fields that failed validation. Never their values.",
    )

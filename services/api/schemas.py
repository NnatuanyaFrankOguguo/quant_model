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

from datetime import date
from decimal import Decimal

from pydantic import BaseModel, Field

from packages.compliance.mode import Mode
from packages.compliance.response_types import register_public_type

__all__ = [
    "ErrorBody",
    "Health",
    "MacroObservationPoint",
    "MacroObservations",
    "MacroSeriesInfo",
    "MacroSeriesList",
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


class MacroSeriesInfo(BaseModel):
    """One macro series, with the two things `CLAUDE.md` requires on every figure.

    Every response carries an **as-of date** and a **staleness flag**, because a number on a
    screen with neither is a number a reader will trust for longer than it deserves.
    ``attribution`` travels with the data rather than living in a footer: the licensing
    register says attribution is required for these sources, and a client that never
    receives the text cannot display it.
    """

    code: str
    name: str
    unit: str
    frequency: str
    base_period: str | None = Field(
        default=None,
        description="'CPI 2024=100'. Rebasing changes past values, so it is part of identity.",
    )
    source_name: str
    attribution: str | None = None
    expected_lag_days: int
    observation_count: int
    latest_as_of: date | None = Field(
        default=None, description="The period the newest observation describes"
    )
    latest_known_as_of: date | None = Field(
        default=None, description="When that observation was published — not the same date"
    )
    latest_value: Decimal | None = None
    days_since_as_of: int | None = None
    is_stale: bool | None = Field(
        default=None,
        description=(
            "True when the newest period is older than expected_lag_days. **null means not "
            "applicable** — an irregular series such as the MPR, or one with no data yet — "
            "never 'fresh'."
        ),
    )


@register_public_type
class MacroSeriesList(BaseModel):
    """Published government statistics. Public-tier content in every mode.

    "Public tier" is the *content class*, not who may log in: access is still owner plus
    family until the licence changes (`CLAUDE.md`'s access model).
    """

    series: list[MacroSeriesInfo]
    as_of: date = Field(description="The date staleness was evaluated against, in UTC")


class MacroObservationPoint(BaseModel):
    """One observation at one vintage."""

    as_of_date: date = Field(description="The period this value describes")
    known_as_of: date = Field(description="The date this value was published")
    value: Decimal | None = Field(
        default=None,
        description="null means genuinely no observation. It is never zero-filled.",
    )


@register_public_type
class MacroObservations(BaseModel):
    """A series and its points, at the newest vintage visible on ``as_known_on``."""

    code: str
    name: str
    unit: str
    source_name: str
    attribution: str | None = None
    as_known_on: date | None = Field(
        default=None,
        description=(
            "When set, vintages published after this date were excluded — the "
            "point-in-time view. When null, each period shows its newest vintage."
        ),
    )
    observations: list[MacroObservationPoint]


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

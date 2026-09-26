"""Mechanism 1 of five - the mode is derived on the server, from the principal.

``SPEC.md`` 4.1: *"Mode is server-derived - never trust a client-supplied mode.
Default ``public``."*  ``CLAUDE.md``: *"Never expose personal-mode output to a
non-family user pre-licence. Access control in code, not policy. This is the only
line with real legal risk."*

**Nothing in this module reads the request.** There is no parameter here that a
client can reach: not the body, not a header, not the query string, not a cookie,
not the path or its casing. The only inputs are the ``principals`` /
``entitlements`` rows resolved from a credential, and the dated ``licence_status``
row in ``system_config``.

Every failure path returns :data:`Mode.PUBLIC`
(``docs/10_PRE_BUILD_CORRECTIONS.md`` 4.6 - *fail-open paths in ``resolve_mode``*).
That includes a database outage, a malformed row, a missing entitlement, an
attribute that raises on access, and a ``licence_status`` value that will not
parse. There is no code path in this file that reaches ``Mode.PERSONAL`` by
accident: it is the single ``return`` at the bottom of :func:`derive_mode`, guarded
by five explicit checks above it.

:func:`resolve_mode_for_principal` is deliberately *not* request-shaped, because
``docs/10_PRE_BUILD_CORRECTIONS.md`` 4.1 requires the non-request surfaces (the
07:00 scheduled brief, alert delivery) to derive mode through the same function the
HTTP middleware calls. A job that branches on mode itself is a defect.
"""

from __future__ import annotations

import contextlib
from collections import Counter
from datetime import UTC, date, datetime
from enum import Enum
from typing import Any

import structlog

from packages.common.system_config import licence_status

_log = structlog.get_logger(__name__)

__all__ = [
    "COMPLIANCE_ERRORS",
    "LICENSED",
    "PRE_LICENCE_PERSONAL_KINDS",
    "SERVICE_KIND",
    "Mode",
    "coerce_mode",
    "derive_mode",
    "is_licensed",
    "log_compliance_error",
    "resolve_mode_for_principal",
    "utcnow",
]


class Mode(str, Enum):
    """The only two modes. ``PUBLIC`` is the default and every failure path."""

    PUBLIC = "public"
    PERSONAL = "personal"


#: ``system_config.licence_status`` value that opens the personal tier to
#: principals who are neither owner nor family. Anything else - missing, NULL,
#: misspelled, a JSON object, a number - means UNLICENSED.
LICENSED = "LICENSED"

#: Pre-licence, entitlement alone is not enough: the principal must also *be*
#: owner or family. ``docs/10_PRE_BUILD_CORRECTIONS.md`` 4.6, invariant I11.
PRE_LICENCE_PERSONAL_KINDS = frozenset({"owner", "family"})

#: A service principal may never hold the personal tier
#: (``docs/10_PRE_BUILD_CORRECTIONS.md`` 4.7): server components authenticate as
#: the end user, never as the application. Otherwise every SSR render at P9 would
#: run in personal mode.
SERVICE_KIND = "service"

#: Loud, in-process tally of every fail-closed event. Tests assert on it, and it is
#: the cheapest possible "did this happen in production" signal until P1 wires
#: metrics. Not a substitute for the ``audit_log`` row, which the middleware writes.
COMPLIANCE_ERRORS: Counter[str] = Counter()

_MISSING = object()


def log_compliance_error(event: str, **fields: object) -> None:
    """Record a compliance failure loudly. Never raises, never swallows.

    Deliberately takes no payload, no credential and no connection string: this
    log line is written on the error path, which is exactly where a repr of a
    local variable would otherwise leak (``docs/10`` 4.7).
    """
    COMPLIANCE_ERRORS[event] += 1
    # Logging must never break the request: the counter above is the part that has to
    # survive, and it already has.
    with contextlib.suppress(Exception):
        _log.error(event, **fields)


def is_licensed(on: date | None = None) -> bool:
    """True only when ``system_config.licence_status`` says ``LICENSED``.

    Absence means unlicensed (``docs/08_DATA_CONTRACTS.md`` 2.15: *"A missing,
    NULL or unparseable licence_status row resolves to UNLICENSED"*). So does a
    lookup that raises, a non-string value, and any string that is not exactly
    ``LICENSED`` after stripping and upper-casing.
    """
    try:
        raw = licence_status(on=on)
    except Exception as exc:  # noqa: BLE001 - a DB outage must not open the gate
        log_compliance_error("licence_status_unavailable", error_type=type(exc).__name__)
        return False
    if not isinstance(raw, str):
        if raw is not None:
            log_compliance_error("licence_status_unparseable", value_type=type(raw).__name__)
        return False
    return raw.strip().upper() == LICENSED


def coerce_mode(mode: Any) -> Mode:
    """Turn anything into a :class:`Mode`, defaulting to the *stricter* one.

    Guards a real fail-open: :class:`Mode` subclasses ``str``, so on the plain
    string ``"public"`` an identity test like ``mode is not Mode.PUBLIC`` takes the
    permissive branch and silently disables whichever check it guards. Every
    compliance check coerces first, and an unrecognisable value becomes
    :data:`Mode.PUBLIC`.
    """
    if isinstance(mode, Mode):
        return mode
    try:
        return Mode(mode)
    except (ValueError, TypeError):
        log_compliance_error("unparseable_mode_value", value_type=type(mode).__name__)
        return Mode.PUBLIC


def _kind_of(principal: Any) -> str:
    kind = getattr(principal, "kind", None)
    if not isinstance(kind, str):
        return ""
    return kind.strip().lower()


def _personal_tier(principal: Any) -> bool:
    """Read ``personal_tier`` from an ORM ``Principal`` or a detached snapshot.

    Accepts either shape on purpose: the middleware passes a frozen snapshot
    (:class:`packages.compliance.auth.ResolvedPrincipal`) so no ORM object escapes
    its session, while the scheduler passes a live ``Principal`` row per
    ``docs/10`` 4.1. An attribute that *raises* - a detached instance, a dropped
    connection - is not caught here; it propagates to the fail-closed wrapper.
    """
    entitlement = getattr(principal, "entitlement", _MISSING)
    if entitlement is _MISSING:
        value = getattr(principal, "personal_tier", None)
    elif entitlement is None:
        return False
    else:
        value = getattr(entitlement, "personal_tier", None)
    # `is True`, not truthiness: the string "false", the integer 1, or a Mock all
    # fail closed here rather than opening the personal tier.
    return value is True


def derive_mode(principal: Any, *, licensed: bool) -> Mode:
    """Pure mode derivation. No I/O, no request, no clock.

    Separated from :func:`resolve_mode_for_principal` so the decision itself is
    testable without a database, and so the licence half is an explicit argument
    rather than an ambient lookup.
    """
    if principal is None:
        return Mode.PUBLIC
    if getattr(principal, "disabled_at", None) is not None:
        return Mode.PUBLIC

    kind = _kind_of(principal)
    if kind == SERVICE_KIND:
        return Mode.PUBLIC
    if not _personal_tier(principal):
        return Mode.PUBLIC
    if not licensed and kind not in PRE_LICENCE_PERSONAL_KINDS:
        # Invariant I11: pre-licence, a principal with kind='public' cannot reach
        # personal mode however its entitlements are set. One wrong IdP group
        # mapping at P9 must not be sufficient on its own.
        log_compliance_error("personal_tier_denied_pre_licence", kind=kind or "unknown")
        return Mode.PUBLIC
    return Mode.PERSONAL


def resolve_mode_for_principal(principal: Any, *, on: date | None = None) -> Mode:
    """The one entry point every surface uses - HTTP middleware and scheduler alike.

    ``docs/10_PRE_BUILD_CORRECTIONS.md`` 4.6: *"entitlements down, DB error,
    anything -> fail CLOSED, loudly, but closed."*
    """
    try:
        mode = derive_mode(principal, licensed=is_licensed(on=on))
    except Exception as exc:  # noqa: BLE001 - deliberate: any error means public
        log_compliance_error("mode_derivation_failed", error_type=type(exc).__name__)
        return Mode.PUBLIC
    if mode is not Mode.PUBLIC and mode is not Mode.PERSONAL:  # pragma: no cover
        log_compliance_error("mode_derivation_returned_non_mode")
        return Mode.PUBLIC
    return mode


def utcnow() -> datetime:
    """UTC-aware now. TG21: never a naive datetime anywhere in this codebase."""
    return datetime.now(UTC)

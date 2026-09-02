"""Mechanism 1's credential half - hashed bearer tokens (ADR-0003).

``Authorization: Bearer <token>`` -> ``sha256(token).hexdigest()`` ->
``principal_tokens.token_sha256``. **Only the hash is ever stored**; the token
itself exists once, in the output of ``scripts/mint_token.py``, and nowhere else.

*Why sha256 and not bcrypt/argon2.* A password is low-entropy and human-chosen, so
it needs a deliberately slow KDF to make offline guessing expensive. These tokens
are 32 bytes from :func:`secrets.token_urlsafe` - 256 bits of entropy. There is no
guessing attack to slow down, and a slow KDF would put ~100ms on **every single
request** including ``/health``. Do not "fix" this into bcrypt. If tokens ever
become user-chosen, that is the day the KDF changes, and that day needs an ADR.

Every rejection here resolves to *anonymous*, never to an error: an expired token,
a revoked token, a token for a disabled principal, and a malformed header all
return ``None``, which :mod:`packages.compliance.mode` turns into
:data:`~packages.compliance.mode.Mode.PUBLIC`. A 401 would confirm to the caller
that a token exists; anonymous plus 403 tells them nothing.
"""

from __future__ import annotations

import contextlib
import hashlib
import hmac
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from packages.common import db
from packages.common.models import Principal, PrincipalToken
from packages.compliance.mode import log_compliance_error

__all__ = [
    "ANONYMOUS",
    "MAX_TOKEN_CHARS",
    "ResolvedPrincipal",
    "hash_token",
    "parse_bearer",
    "principal_label",
    "resolve_principal",
]

#: ``audit_log.principal`` value when no valid credential was presented.
ANONYMOUS = "anonymous"

#: A bearer token we minted is 43 characters. Anything an order of magnitude
#: larger is not ours; refuse it before hashing rather than after, so a caller
#: cannot make us hash megabytes per request.
MAX_TOKEN_CHARS = 512

_BEARER_SCHEME = "bearer"


@dataclass(frozen=True)
class ResolvedPrincipal:
    """A detached, immutable snapshot of who is asking.

    The ORM row is deliberately *not* returned. A ``Principal`` handed back after
    its session closes raises ``DetachedInstanceError`` on the first lazy load -
    which, inside :func:`packages.compliance.mode.resolve_mode_for_principal`,
    would be caught and fail closed to public. Correct, but it would look like a
    permissions bug rather than a lifecycle bug. A frozen snapshot cannot drift,
    cannot lazy-load, and cannot be mutated by a handler.
    """

    id: int
    external_id: str | None
    display_name: str
    kind: str
    disabled_at: datetime | None
    personal_tier: bool
    data_tier: bool
    token_id: int

    @property
    def label(self) -> str:
        """The value written to ``audit_log.principal``."""
        return principal_label(self)


def principal_label(principal: Any) -> str:
    """Stable human-readable identifier for the audit row. Never an email."""
    if principal is None:
        return ANONYMOUS
    for attribute in ("external_id", "display_name"):
        value = getattr(principal, attribute, None)
        if isinstance(value, str) and value.strip():
            return value.strip()[:200]
    identifier = getattr(principal, "id", None)
    return f"principal:{identifier}" if identifier is not None else ANONYMOUS


def hash_token(raw_token: str) -> str:
    """The one and only place a raw token becomes a stored value."""
    return hashlib.sha256(raw_token.encode("utf-8")).hexdigest()


def parse_bearer(header_value: str | None) -> str | None:
    """Extract the token from an ``Authorization`` header, or ``None``.

    Tolerant of case and extra whitespace in the scheme, intolerant of everything
    else. A malformed header is anonymous, not an error.
    """
    if not header_value or not isinstance(header_value, str):
        return None
    parts = header_value.strip().split(None, 1)
    if len(parts) != 2:
        return None
    scheme, token = parts
    if scheme.lower() != _BEARER_SCHEME:
        return None
    token = token.strip()
    if not token or len(token) > MAX_TOKEN_CHARS:
        return None
    return token


def _as_utc(value: datetime | None) -> datetime | None:
    """Coerce to an aware UTC datetime. A naive value is assumed UTC.

    ``expires_at`` is ``TIMESTAMPTZ`` so this should never fire, but comparing a
    naive datetime to an aware one raises ``TypeError`` - which would surface as a
    fail-closed 403 on a token that is actually valid. Cheaper to normalise.
    """
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _snapshot(principal: Principal, token: PrincipalToken) -> ResolvedPrincipal:
    entitlement = principal.entitlement
    return ResolvedPrincipal(
        id=principal.id,
        external_id=principal.external_id,
        display_name=principal.display_name,
        kind=principal.kind,
        disabled_at=principal.disabled_at,
        personal_tier=getattr(entitlement, "personal_tier", None) is True,
        data_tier=getattr(entitlement, "data_tier", None) is True,
        token_id=token.id,
    )


def _touch_last_used(
    session: Session, token: PrincipalToken, now: datetime, *, commit: bool
) -> None:
    """Best effort. A failed bookkeeping write must never reject a valid token."""
    try:
        token.last_used_at = now
        if commit:
            session.commit()
        else:
            session.flush()
    except Exception as exc:  # noqa: BLE001 - bookkeeping, not authorisation
        log_compliance_error("token_last_used_update_failed", error_type=type(exc).__name__)
        with contextlib.suppress(Exception):
            session.rollback()


def _lookup(
    session: Session, digest: str, now: datetime, *, commit: bool
) -> ResolvedPrincipal | None:
    row = session.execute(
        select(PrincipalToken).where(PrincipalToken.token_sha256 == digest)
    ).scalar_one_or_none()
    if row is None:
        return None

    # The index lookup above already matched, but compare again in constant time.
    # `token_sha256` is CHAR(64), which Postgres blank-pads, hence the strip.
    stored = str(row.token_sha256 or "").strip()
    if not hmac.compare_digest(stored, digest):
        return None

    if row.revoked_at is not None:
        return None
    expires_at = _as_utc(row.expires_at)
    if expires_at is not None and expires_at <= now:
        return None

    principal = session.get(Principal, row.principal_id)
    if principal is None or principal.disabled_at is not None:
        return None

    snapshot = _snapshot(principal, row)
    _touch_last_used(session, row, now, commit=commit)
    return snapshot


def resolve_principal(
    header_value: str | None,
    *,
    session: Session | None = None,
    now: datetime | None = None,
) -> ResolvedPrincipal | None:
    """Resolve a credential to a principal snapshot, or ``None`` for anonymous.

    Raises only if the database itself fails. Callers must treat that as
    fail-closed-to-public; :func:`services.api.middleware.mode.resolve_mode` does.
    """
    token = parse_bearer(header_value)
    if token is None:
        # No credential at all: the common case, and it costs zero DB round-trips.
        return None
    digest = hash_token(token)
    # Drop the raw token from this frame's locals before any DB call that could
    # raise: a traceback repr of this frame is one of the few places it could
    # otherwise reach a log. (The caller's header string is still theirs to hold.)
    del token
    now = now or datetime.now(UTC)

    if session is not None:
        # Caller owns the transaction; do not commit inside it.
        return _lookup(session, digest, now, commit=False)
    with db.get_session() as owned:
        return _lookup(owned, digest, now, commit=True)

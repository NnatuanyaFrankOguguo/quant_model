"""The dated-config reader — P0.12 / TG20.

`system_config` is dated because the NGX movement rule and the Nigerian CGT thresholds
**both moved during planning**. A backtest over 2024 must read the 2024 value, not
today's, and the only way to guarantee that is to make every read carry a date.

Two functions, and everything reads config through them:

* :func:`get_config` — the value whose ``[effective_from, effective_to)`` window contains
  ``on``.
* :func:`licence_status` — the compliance half of the mode gate. **Fails closed.**

**Why `licence_status` fails closed** (`docs/08` §2.15): *"A missing, NULL or unparseable
licence_status row resolves to UNLICENSED."* The failure this prevents is the expensive
one — a truncated table, a botched migration or a typo'd value silently opening the advice
tier to the public before the SEC registration exists. Every unrecognised state is
`UNLICENSED`; only the exact string `LICENSED` opens the door.

A database error is *not* caught here. It propagates, the caller returns 5xx, and nothing
is served — which is also a closed door, but a loud one rather than a silent one.
"""

from __future__ import annotations

from datetime import date
from typing import Any, Final

from sqlalchemy import select
from sqlalchemy.orm import Session

from packages.common.db import get_session
from packages.common.models import SystemConfig
from packages.common.timez import utctoday

#: The two licence states. Anything else is a bug and resolves to UNLICENSED.
LICENSED: Final = "LICENSED"
UNLICENSED: Final = "UNLICENSED"

LICENCE_STATUS_KEY: Final = "licence_status"


def get_config(key: str, on: date | None = None, session: Session | None = None) -> Any | None:
    """Return the configured value for `key` in force on `on`.

    Args:
        key: the `system_config.key`.
        on: the date to resolve against. Defaults to today in **UTC** — never local time,
            because a local-midnight default makes a config change land on a different day
            for the scheduler than for the API.
        session: an open session to reuse. When omitted a short-lived one is opened; pass
            your own inside a request or a migration so the read joins that transaction.

    Returns:
        The decoded JSONB value, or `None` when no row's window contains `on` (and also
        when the stored value is a JSON `null`). Callers distinguishing "unset" from
        "explicitly null" must query the table directly — no P0 caller does.

    Overlapping windows resolve to the row with the **latest** `effective_from`, i.e. the
    most recently effective setting. The windows are half-open — a row with
    `effective_to = 2026-01-01` does not apply on 2026-01-01 — so a correctly maintained
    table never overlaps; the ordering exists so that a *mis*-maintained one still returns
    one deterministic answer instead of an arbitrary one.
    """
    when = on or utctoday()
    stmt = (
        select(SystemConfig.value)
        .where(
            SystemConfig.key == key,
            SystemConfig.effective_from <= when,
            (SystemConfig.effective_to.is_(None)) | (SystemConfig.effective_to > when),
        )
        .order_by(SystemConfig.effective_from.desc())
        .limit(1)
    )

    if session is not None:
        return session.execute(stmt).scalar_one_or_none()

    with get_session() as owned:
        return owned.execute(stmt).scalar_one_or_none()


def licence_status(on: date | None = None, session: Session | None = None) -> str:
    """Return `"LICENSED"` or `"UNLICENSED"` as at `on`. **Fails closed.**

    A missing row, a JSON `null`, a wrong type, or any string that is not exactly
    `LICENSED` (case- and whitespace-insensitive) all resolve to `UNLICENSED`.

    A dict is accepted for forward compatibility with a richer value — `{"status": ...}`
    or `{"value": ...}` — because the day this row grows a registration number is the day
    someone would otherwise store a dict here and silently break the gate.
    """
    raw = get_config(LICENCE_STATUS_KEY, on=on, session=session)

    if isinstance(raw, dict):
        raw = raw.get("status", raw.get("value"))

    if not isinstance(raw, str):
        return UNLICENSED

    return LICENSED if raw.strip().upper() == LICENSED else UNLICENSED


def is_licensed(on: date | None = None, session: Session | None = None) -> bool:
    """Convenience predicate over :func:`licence_status`."""
    return licence_status(on=on, session=session) == LICENSED

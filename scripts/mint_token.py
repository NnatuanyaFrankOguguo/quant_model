"""Mint a bearer token for a principal (ADR-0003).

    python scripts/mint_token.py --principal nnatuanyafrankoguguo --label "laptop" \
        --expires-days 90

The token is printed **once**, to stdout, and is not recoverable. Only its sha256
reaches the database (``principal_tokens.token_sha256``), so a full database dump
in the wrong hands still yields no usable credential.

``docs/10_PRE_BUILD_CORRECTIONS.md`` 6.5 notes that ``seed_dev.py`` is currently
the only way a principal comes into existence in any phase. This script is the only
way a *credential* comes into existence, which makes it the audit trail for "who
was given access, when, and until when" until P9's identity provider takes over.
"""

from __future__ import annotations

import argparse
import secrets
import sys
from datetime import UTC, datetime, timedelta

from sqlalchemy import or_, select

from packages.common.db import SessionLocal
from packages.common.models import Principal, PrincipalToken
from packages.compliance.auth import hash_token

#: 32 bytes -> 43 URL-safe characters -> 256 bits of entropy. See the note in
#: `packages/compliance/auth.py` on why this needs no slow KDF.
_TOKEN_BYTES = 32


def _find_principal(session, identifier: str) -> Principal | None:
    conditions = [Principal.external_id == identifier, Principal.email == identifier]
    if identifier.isdigit():
        conditions.append(Principal.id == int(identifier))
    return session.execute(select(Principal).where(or_(*conditions))).scalars().first()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--principal",
        required=True,
        help="external_id, email, or numeric id of the principal to mint for",
    )
    parser.add_argument("--label", required=True, help="Where this token will live, e.g. 'laptop'")
    parser.add_argument(
        "--expires-days",
        type=int,
        default=90,
        help="Days until expiry. 0 means no expiry - avoid it (default: 90)",
    )
    args = parser.parse_args(argv)

    if args.expires_days < 0:
        print("ERROR: --expires-days cannot be negative", file=sys.stderr)
        return 2

    with SessionLocal() as session:
        principal = _find_principal(session, args.principal)
        if principal is None:
            print(f"ERROR: no principal matches {args.principal!r}", file=sys.stderr)
            return 1
        if principal.disabled_at is not None:
            print(
                f"ERROR: principal {principal.display_name!r} is disabled "
                f"(disabled_at={principal.disabled_at.isoformat()}). Re-enable it first.",
                file=sys.stderr,
            )
            return 1

        raw_token = secrets.token_urlsafe(_TOKEN_BYTES)
        expires_at = (
            datetime.now(UTC) + timedelta(days=args.expires_days) if args.expires_days > 0 else None
        )
        session.add(
            PrincipalToken(
                principal_id=principal.id,
                token_sha256=hash_token(raw_token),
                label=args.label,
                expires_at=expires_at,
            )
        )
        session.commit()
        display_name = principal.display_name
        kind = principal.kind

    # stderr carries the warning, stdout carries only the token, so
    # `mint_token.py ... > token.txt` produces a file with just the credential and
    # still shows the operator the warning.
    print(
        f"Minted a token for {display_name!r} (kind={kind}, label={args.label!r}, "
        f"expires={'never' if expires_at is None else expires_at.date().isoformat()}).\n"
        "This is the ONLY time it will be shown. It is stored as a sha256 hash and\n"
        "cannot be recovered - if you lose it, mint another and revoke this one.\n"
        "Do not paste it into a chat, a commit, a log, or an issue.",
        file=sys.stderr,
    )
    print(raw_token)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

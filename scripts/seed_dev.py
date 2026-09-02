"""Seed a development database with three principals and their entitlements.

``docs/02_INFRASTRUCTURE.md`` 2.4: *"Three principals from day one - it is the
cheapest possible guard against single-user assumptions creeping in (ADR-0007),
because every manual test you run naturally exercises more than one."* A gate you
only ever exercise as the owner is a gate you have never actually tested.

**Why the personal tier is lawful pre-licence**, and why these columns exist:
``PROJECT_CONTEXT.md`` 4 and ``SPEC.md`` 1.2 - **no fee is charged and no funds are
pooled**. ``docs/08_DATA_CONTRACTS.md`` 2.15 makes that a stored, attested fact
rather than a remembered one, *"because the realistic failure is not an intruder -
it is drift from three relatives to eleven acquaintances, one of whom offers to
cover the server bill."* So ``fee_charged`` and ``funds_pooled`` are written
``false`` here as a factual claim about today, not as a default.

**Idempotent, and non-destructive.** Re-running creates nothing that already
exists and overwrites nothing that does - "no silent overwrites" (``CLAUDE.md``) is
a hard rule, and a seed script that quietly reset an entitlement somebody had
deliberately changed would be the least expected place to break it.

This script does **not** mint tokens. Run ``scripts/mint_token.py`` for that, so a
credential is always a deliberate act with an operator behind it.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from packages.common.config import get_settings
from packages.common.db import SessionLocal
from packages.common.models import Entitlement, Principal

OWNER_EXTERNAL_ID = "nnatuanyafrankoguguo"
OWNER_EMAIL = "nnatuanyafrank@gmail.com"


@dataclass(frozen=True)
class Seed:
    external_id: str
    display_name: str
    email: str | None
    kind: str
    relationship_kind: str | None
    attested: bool
    personal_tier: bool
    llm_spend_cap_usd: Decimal
    max_position_size: Decimal | None
    max_daily_loss: Decimal | None
    note: str


SEEDS: tuple[Seed, ...] = (
    Seed(
        external_id=OWNER_EXTERNAL_ID,
        display_name="Frank Oguguo",
        email=OWNER_EMAIL,
        kind="owner",
        relationship_kind="self",
        attested=True,
        personal_tier=True,
        llm_spend_cap_usd=Decimal("50"),
        max_position_size=Decimal("0.10"),
        max_daily_loss=Decimal("0.03"),
        note="own capital; no fee, no pooled funds",
    ),
    Seed(
        external_id="family-placeholder",
        display_name="Family member (placeholder - not yet attested)",
        email=None,
        kind="family",
        # Honestly NULL. There is no real relative behind this row yet, and
        # writing 'sibling' here to make the seed look complete would put a false
        # attestation in the one table whose purpose is to hold a true one.
        relationship_kind=None,
        attested=False,
        personal_tier=True,
        llm_spend_cap_usd=Decimal("10"),
        max_position_size=Decimal("0.05"),
        max_daily_loss=Decimal("0.02"),
        note="ATTEST BEFORE ISSUING A TOKEN - see the warning printed by this script",
    ),
    Seed(
        external_id="guest-public",
        display_name="Guest (public tier)",
        email=None,
        kind="public",
        relationship_kind=None,
        attested=False,
        personal_tier=False,
        llm_spend_cap_usd=Decimal("0"),
        max_position_size=None,
        max_daily_loss=None,
        note="data tier only; exists so every manual test has an unentitled caller",
    ),
)


def refuse_in_production(action: str) -> None:
    """``docs/02_INFRASTRUCTURE.md`` 2.2, guard 3.

    The realistic accident is not malice, it is a terminal window you thought was
    pointed somewhere else.
    """
    environment = str(getattr(get_settings(), "environment", "")).strip().lower()
    if environment in {"production", "prod"}:
        raise SystemExit(
            f"REFUSED: {action!r} writes rows and ENVIRONMENT={environment}. "
            "If you truly mean it, run it against a restored copy first."
        )


def _seed_principal(session: Session, seed: Seed, *, now: datetime) -> tuple[str, Principal]:
    existing = (
        session.execute(select(Principal).where(Principal.external_id == seed.external_id))
        .scalars()
        .first()
    )
    if existing is not None:
        return "unchanged", existing

    principal = Principal(
        external_id=seed.external_id,
        display_name=seed.display_name,
        email=seed.email,
        kind=seed.kind,
        relationship_kind=seed.relationship_kind,
        # The two facts that make the personal tier lawful without SEC
        # registration. Written explicitly, not left to a column default.
        fee_charged=False,
        funds_pooled=False,
        attested_by=OWNER_EMAIL if seed.attested else None,
        attested_on=now.date() if seed.attested else None,
    )
    session.add(principal)
    session.flush()
    return "created", principal


def _seed_entitlement(session: Session, seed: Seed, principal: Principal) -> str:
    existing = session.get(Entitlement, principal.id)
    if existing is not None:
        return "unchanged"
    session.add(
        Entitlement(
            principal_id=principal.id,
            personal_tier=seed.personal_tier,
            data_tier=True,
            llm_spend_cap_usd=seed.llm_spend_cap_usd,
            max_position_size=seed.max_position_size,
            max_daily_loss=seed.max_daily_loss,
            granted_by=OWNER_EMAIL,
        )
    )
    return "created"


def main(argv: list[str] | None = None) -> int:
    refuse_in_production("seed_dev.py")
    now = datetime.now(UTC)
    warnings: list[str] = []

    with SessionLocal() as session:
        for seed in SEEDS:
            principal_action, principal = _seed_principal(session, seed, now=now)
            entitlement_action = _seed_entitlement(session, seed, principal)
            print(
                f"  {seed.external_id:<24} principal={principal_action:<9} "
                f"entitlement={entitlement_action:<9} kind={seed.kind:<7} "
                f"personal_tier={str(seed.personal_tier).lower():<5}  # {seed.note}"
            )
            if seed.personal_tier and not seed.attested:
                warnings.append(seed.external_id)
        session.commit()

    print(
        "\nSeeded. No tokens were minted - run scripts/mint_token.py for that.\n"
        "fee_charged=false and funds_pooled=false on every row: that is what makes\n"
        "the personal tier lawful pre-licence (PROJECT_CONTEXT 4, SPEC 1.2)."
    )
    for external_id in warnings:
        print(
            f"WARNING: {external_id!r} holds personal_tier but has no attestation "
            "(relationship_kind, attested_by, attested_on are NULL). Fill them in "
            "with a real relative's details before minting it a token.",
            file=sys.stderr,
        )
    print(_licence_note(), file=sys.stderr)
    return 0


def _licence_note() -> str:
    """Report the licence state accurately, distinguishing absent from UNLICENSED.

    These are two different facts and the note used to conflate them: it announced
    "system_config has no licence_status row" whenever the status was not LICENSED,
    which is the normal state, so it printed a false statement about the compliance
    configuration on every seed of a correctly-seeded database. A message about the
    mode gate that is wrong in the ordinary case is worse than no message.
    """
    try:
        from packages.common.system_config import get_config, licence_status

        row = get_config("licence_status")
        status = str(licence_status()).strip().upper()
    except Exception as exc:  # noqa: BLE001 - the note is advisory, never fatal
        return (
            f"NOTE: could not read licence_status ({type(exc).__name__}). It therefore "
            f"resolves to UNLICENSED, which is the fail-closed default."
        )
    if row is None:
        return (
            "NOTE: system_config has no licence_status row - migration 0003 should have "
            "seeded one. It resolves to UNLICENSED (fail-closed), but the missing row is "
            "a defect worth chasing."
        )
    return (
        f"NOTE: licence_status = {status}. Pre-licence, personal mode is reachable only by "
        f"principals of kind 'owner' or 'family'; entitlement alone is not enough."
    )


if __name__ == "__main__":
    raise SystemExit(main())

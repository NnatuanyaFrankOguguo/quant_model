"""Fixtures for the compliance suite.

**The one thing this file must get right.** ``packages.common.db.engine`` is bound
to ``DATABASE_URL`` - the dev database. The API resolves principals and writes
audit rows through that engine, so a ``TestClient`` request would read and write
*dev* while the fixtures wrote to ``quant_test``. The tests would then be both
wrong and destructive.

:func:`_redirect_app_database` repoints ``packages.common.db``'s module-level
``engine`` and ``SessionLocal`` at the migrated test engine for the duration of the
session. Everything downstream - ``get_session``, ``check_db``, ``system_config``,
the audit middleware - reads those names at call time, so one patch covers the lot.

Fixture data is **committed**, not rolled back. The root ``db_session`` fixture
wraps a single connection in a transaction, and the application opens its own
connection from the pool; uncommitted rows would be invisible to it. So these
fixtures commit and clean up after themselves.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from packages.common import db as common_db
from packages.common.models import AuditLog, Entitlement, Principal, PrincipalToken
from packages.compliance.auth import hash_token

#: Every principal this suite creates carries this prefix in its `external_id`, so
#: teardown can remove exactly what the suite made and nothing else.
TEST_PREFIX = "cmpl-test-"


@pytest.fixture(scope="session", autouse=True)
def _redirect_app_database(migrated_db: Engine) -> Iterator[Engine]:
    """Point the application's engine at the test database for this session."""
    patch = pytest.MonkeyPatch()
    patch.setattr(common_db, "engine", migrated_db, raising=True)
    patch.setattr(
        common_db,
        "SessionLocal",
        sessionmaker(
            bind=migrated_db,
            autoflush=False,
            autocommit=False,
            expire_on_commit=False,
            class_=Session,
        ),
        raising=True,
    )
    try:
        yield migrated_db
    finally:
        patch.undo()


@pytest.fixture(scope="session")
def suite_started_at() -> datetime:
    return datetime.now(UTC)


@pytest.fixture(scope="session", autouse=True)
def _cleanup(_redirect_app_database: Engine, suite_started_at: datetime) -> Iterator[None]:
    """Remove the suite's principals, tokens and audit rows when it finishes."""
    yield
    with common_db.SessionLocal() as session:
        ids = [
            row[0]
            for row in session.execute(
                Principal.__table__.select()
                .with_only_columns(Principal.id)
                .where(Principal.external_id.like(f"{TEST_PREFIX}%"))
            ).all()
        ]
        if ids:
            session.execute(delete(PrincipalToken).where(PrincipalToken.principal_id.in_(ids)))
            session.execute(delete(Entitlement).where(Entitlement.principal_id.in_(ids)))
            session.execute(delete(Principal).where(Principal.id.in_(ids)))
        session.execute(delete(AuditLog).where(AuditLog.ts >= suite_started_at))
        session.commit()


@dataclass(frozen=True)
class Actor:
    """A principal plus the raw token that reaches it, for use in a request."""

    principal_id: int
    external_id: str
    token: str

    @property
    def auth(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.token}"}


MakeActor = Callable[..., Actor]


@pytest.fixture
def make_actor(_redirect_app_database: Engine) -> Iterator[MakeActor]:
    """Create a principal, its entitlement and a token. Committed, then removed."""
    created: list[int] = []

    def _make(
        *,
        kind: str = "owner",
        personal_tier: bool = True,
        disabled: bool = False,
        expires_in: timedelta | None = None,
        revoked: bool = False,
    ) -> Actor:
        suffix = uuid.uuid4().hex[:12]
        external_id = f"{TEST_PREFIX}{kind}-{suffix}"
        raw_token = f"tok-{uuid.uuid4().hex}{uuid.uuid4().hex}"
        now = datetime.now(UTC)
        with common_db.SessionLocal() as session:
            principal = Principal(
                external_id=external_id,
                display_name=f"Test {kind} {suffix}",
                email=f"{external_id}@example.invalid",
                kind=kind,
                relationship_kind="self" if kind == "owner" else None,
                fee_charged=False,
                funds_pooled=False,
                disabled_at=now if disabled else None,
            )
            session.add(principal)
            session.flush()
            session.add(
                Entitlement(
                    principal_id=principal.id,
                    personal_tier=personal_tier,
                    data_tier=True,
                    llm_spend_cap_usd=0,
                    granted_by="tests/compliance",
                )
            )
            session.add(
                PrincipalToken(
                    principal_id=principal.id,
                    token_sha256=hash_token(raw_token),
                    label="compliance-suite",
                    expires_at=now + expires_in if expires_in is not None else None,
                    revoked_at=now if revoked else None,
                )
            )
            session.commit()
            created.append(principal.id)
            return Actor(principal_id=principal.id, external_id=external_id, token=raw_token)

    try:
        yield _make
    finally:
        if created:
            with common_db.SessionLocal() as session:
                session.execute(
                    delete(PrincipalToken).where(PrincipalToken.principal_id.in_(created))
                )
                session.execute(delete(Entitlement).where(Entitlement.principal_id.in_(created)))
                session.execute(delete(Principal).where(Principal.id.in_(created)))
                session.commit()


@pytest.fixture
def owner(make_actor: MakeActor) -> Actor:
    return make_actor(kind="owner", personal_tier=True)


@pytest.fixture
def family(make_actor: MakeActor) -> Actor:
    return make_actor(kind="family", personal_tier=True)


@pytest.fixture
def guest(make_actor: MakeActor) -> Actor:
    """Entitled to data, not to advice. The `docs/03` P0 check-8 caller."""
    return make_actor(kind="public", personal_tier=False)


@pytest.fixture(scope="session")
def client(_redirect_app_database: Engine) -> Iterator[TestClient]:
    """The real application, with the real middleware stack.

    ``raise_server_exceptions=False`` so a 500 arrives as a *response* - which is
    what a real caller sees, and what the audit row must record.
    """
    from services.api.main import app

    with TestClient(app, raise_server_exceptions=False) as test_client:
        yield test_client


@pytest.fixture
def audit_rows() -> Callable[[uuid.UUID | str], list[AuditLog]]:
    """Fetch the ``audit_log`` rows for a request id taken from ``X-Request-Id``."""

    def _fetch(request_id: uuid.UUID | str) -> list[AuditLog]:
        value = request_id if isinstance(request_id, uuid.UUID) else uuid.UUID(str(request_id))
        with common_db.SessionLocal() as session:
            return list(
                session.execute(
                    AuditLog.__table__.select().where(AuditLog.request_id == value)
                ).all()
            )

    return _fetch

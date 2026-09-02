"""Shared test fixtures.

**The one rule this file exists to enforce: the test suite may never touch the dev
database.** A suite that can drop the dev schema is a P0 defect, not an inconvenience —
the whole point of the data layer is that the data in it is expensive to reproduce.
`pytest_configure` compares the resolved test URL against the dev URL by (host, port,
database) and stops the run outright if they match. It stops rather than skips, because a
misconfiguration that silently skips is how the guard gets discovered after the damage.

Everything here points at `TEST_DATABASE_URL` (`quant_test`), which is disposable. When no
test database is configured or reachable, DB-backed tests skip with a message that says
which of the two it was.

Fixtures:

* `test_engine` (session) — an engine on the test database.
* `migrated_db` (session) — `alembic upgrade head`, run once.
* `db_connection` (session) — a connection on the migrated database, for introspection.
* `db_session` (function) — a session whose work is rolled back after each test.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from urllib.parse import urlsplit

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import text
from sqlalchemy.engine import Connection, Engine
from sqlalchemy.orm import Session

from packages.common.config import get_settings, redact_url
from packages.common.db import make_engine

REPO_ROOT = Path(__file__).resolve().parents[1]
ALEMBIC_INI = REPO_ROOT / "alembic.ini"
MIGRATIONS_DIR = REPO_ROOT / "db" / "migrations"


def _target(url: str) -> tuple[str | None, int | None, str]:
    """The identity of a database: (host, port, database name). Never the credentials."""
    parts = urlsplit(url)
    return (parts.hostname, parts.port, parts.path.lstrip("/"))


def _resolve() -> tuple[str | None, str | None]:
    """Return (test_url, skip_reason). Exactly one is not None."""
    settings = get_settings()
    url = settings.sqlalchemy_test_database_url
    if not url:
        return None, (
            "TEST_DATABASE_URL is not set in .env. Database-backed tests need a disposable "
            "test database; they will not fall back to DATABASE_URL."
        )
    return url, None


TEST_URL, SKIP_REASON = _resolve()


def pytest_configure(config: pytest.Config) -> None:
    """Refuse to run at all if the test URL resolves to the dev database."""
    if TEST_URL is None:
        return
    settings = get_settings()
    if _target(TEST_URL) == _target(settings.sqlalchemy_database_url):
        pytest.exit(
            "REFUSING TO RUN: TEST_DATABASE_URL resolves to the same database as "
            f"DATABASE_URL ({redact_url(TEST_URL)}). The suite drops and rebuilds the "
            "schema it is pointed at. Point TEST_DATABASE_URL at a disposable database.",
            returncode=3,
        )


@pytest.fixture(scope="session")
def test_engine() -> Iterator[Engine]:
    """An engine on the test database, or a skip with the reason."""
    if TEST_URL is None:
        pytest.skip(SKIP_REASON or "No test database configured.")

    engine = make_engine(TEST_URL)
    try:
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
    except Exception as exc:  # noqa: BLE001 - the reason is the message, not the type
        engine.dispose()
        pytest.skip(
            f"Test database unreachable at {redact_url(TEST_URL)}: "
            f"{type(exc).__name__}. Database-backed tests skipped."
        )

    try:
        yield engine
    finally:
        engine.dispose()


def alembic_config(url: str) -> Config:
    """An Alembic config bound to `url`, with absolute paths so cwd does not matter."""
    config = Config(str(ALEMBIC_INI))
    config.set_main_option("script_location", str(MIGRATIONS_DIR))
    # Passed through `attributes`, never through `set_main_option`: the ini is
    # interpolated and a URL is a credential that must not land in a config file.
    config.attributes["sqlalchemy_url"] = url
    return config


@pytest.fixture(scope="session")
def migrated_db(test_engine: Engine) -> Engine:
    """Bring the test database to `head` once per session."""
    assert TEST_URL is not None  # test_engine would have skipped otherwise
    command.upgrade(alembic_config(TEST_URL), "head")
    return test_engine


@pytest.fixture(scope="session")
def db_connection(migrated_db: Engine) -> Iterator[Connection]:
    """A read-mostly connection on the migrated schema, for introspection tests."""
    with migrated_db.connect() as connection:
        yield connection


@pytest.fixture
def db_session(migrated_db: Engine) -> Iterator[Session]:
    """A session whose writes are rolled back when the test ends.

    Tests can commit freely: the session joins an outer transaction via savepoints, and
    the outer transaction is rolled back, so nothing survives the test.
    """
    connection = migrated_db.connect()
    transaction = connection.begin()
    session = Session(bind=connection, join_transaction_mode="create_savepoint")
    try:
        yield session
    finally:
        session.close()
        transaction.rollback()
        connection.close()

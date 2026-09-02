"""Alembic environment.

Two things this file exists to guarantee:

1. **The URL never comes from `alembic.ini`.** It is resolved from
   `packages.common.config`, which reads the gitignored `.env`. A URL in a committed ini
   file is a credential in git history.
2. **The URL is never printed.** `redact_url()` is used for the one line of output that
   names the target, so a CI log shows `postgresql://<redacted>@host/db` and nothing more.

Choosing a target:

* `QUANT_DB_TARGET=test` -> `Settings.test_database_url` (the `quant_test` database).
* anything else, or unset -> `Settings.database_url` (dev).
* `config.attributes["sqlalchemy_url"]` overrides both, for programmatic runs from
  `tests/conftest.py`.
"""

from __future__ import annotations

import os
import sys
from logging.config import fileConfig
from pathlib import Path

from alembic import context
from sqlalchemy import create_engine, pool
from sqlalchemy.engine import Connection

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from packages.common.config import get_settings, redact_url, sqlalchemy_url  # noqa: E402
from packages.common.models import Base  # noqa: E402

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def resolve_url() -> str:
    """Return the driver-normalised URL for the selected target. Never log the result."""
    override = config.attributes.get("sqlalchemy_url")
    if override:
        return sqlalchemy_url(str(override))

    settings = get_settings()
    target = os.environ.get("QUANT_DB_TARGET", "dev").strip().lower()

    if target == "test":
        url = settings.sqlalchemy_test_database_url
        if not url:
            raise RuntimeError(
                "QUANT_DB_TARGET=test but TEST_DATABASE_URL is not set in .env. "
                "Refusing to fall back to the dev database."
            )
        return url

    if target not in {"dev", ""}:
        raise RuntimeError(f"Unknown QUANT_DB_TARGET {target!r}; expected 'dev' or 'test'.")

    return settings.sqlalchemy_database_url


def run_migrations_offline() -> None:
    """Emit SQL to stdout without connecting."""
    url = resolve_url()
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Connect and run migrations.

    An externally supplied connection (`config.attributes["connection"]`) is reused so a
    test fixture can run migrations inside its own transaction.
    """
    external = config.attributes.get("connection")
    if external is not None:
        do_run_migrations(external)
        return

    url = resolve_url()
    print(f"alembic target: {redact_url(url)}")
    # NullPool: a migration opens one connection and exits. `pool_pre_ping` still
    # matters because Neon drops idle connections between the CLI's start and the first
    # statement.
    engine = create_engine(url, poolclass=pool.NullPool, pool_pre_ping=True, future=True)
    try:
        with engine.connect() as connection:
            do_run_migrations(connection)
    finally:
        engine.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()

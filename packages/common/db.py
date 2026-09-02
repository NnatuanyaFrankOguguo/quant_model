"""The engine, the session factory, and the health check.

`pool_pre_ping=True` is not optional on Neon. Neon suspends idle compute and drops
pooled connections; without a pre-ping the first request after an idle period fails with
an opaque `OperationalError` that looks like a bug in whatever code happened to run
first. The ping costs one round-trip and removes an entire class of phantom failure.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from packages.common.config import get_settings

POOL_SIZE = 5
MAX_OVERFLOW = 10


def make_engine(url: str, **kwargs: object) -> Engine:
    """Build an engine with the project's pool settings.

    Used by `db.engine` for the application database and by the test fixtures for the
    test database, so both get the same pooling behaviour.
    """
    options: dict[str, object] = {
        "pool_size": POOL_SIZE,
        "max_overflow": MAX_OVERFLOW,
        "pool_pre_ping": True,
        "pool_recycle": 300,
        "future": True,
    }
    options.update(kwargs)
    return create_engine(url, **options)


engine: Engine = make_engine(get_settings().sqlalchemy_database_url)

SessionLocal = sessionmaker(
    bind=engine,
    autoflush=False,
    autocommit=False,
    expire_on_commit=False,
    class_=Session,
)


@contextmanager
def get_session() -> Iterator[Session]:
    """Yield a session that commits on a clean exit and rolls back on any exception.

    The session is always closed. Callers never call `commit()` themselves; if the block
    raised, nothing is written — which is the only behaviour that makes a partially
    applied ingestion run impossible.
    """
    session = SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def check_db() -> bool:
    """Return True if the database answers `SELECT 1`. Backs `/health`.

    Swallows the exception deliberately: a health endpoint reports a boolean, it does not
    leak a driver error message (which on a bad DSN can contain the host and user).
    """
    try:
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
        return True
    except Exception:
        return False

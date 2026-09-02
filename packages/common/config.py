"""Application settings.

One place reads the environment. Everything else asks this module.

The single rule that matters here: **a connection string is a credential.** It is never
logged, never repr'd, never rendered into a stack trace and never written into
``alembic.ini``. ``Settings.__repr__`` is overridden precisely because pydantic's default
repr prints every field, and a `Settings` object ends up inside tracebacks and log lines
without anyone deciding it should.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

from pydantic_settings import BaseSettings, SettingsConfigDict

# The repo root — packages/common/config.py -> packages/common -> packages -> <root>.
REPO_ROOT = Path(__file__).resolve().parents[2]
ENV_FILE = REPO_ROOT / ".env"

# SQLAlchemy 2 + psycopg 3 needs an explicit driver in the scheme. Neon (and most
# hosted providers) hand out bare `postgresql://`, which SQLAlchemy resolves to
# psycopg2 — a driver this project does not install.
_DRIVER = "postgresql+psycopg"
_BARE_SCHEMES = {"postgres", "postgresql"}


def sqlalchemy_url(url: str) -> str:
    """Normalise a provider-issued Postgres URL into a SQLAlchemy 2 + psycopg 3 URL.

    ``postgresql://…`` and ``postgres://…`` both become ``postgresql+psycopg://…``.
    A URL that already names a driver (``postgresql+asyncpg://``) is returned unchanged,
    because overriding an explicit choice would be surprising.

    The query string is preserved verbatim, which is how ``sslmode=require`` survives —
    Neon refuses connections without it, and silently dropping it turns a security
    setting into an intermittent connection error.

    Raises:
        ValueError: if `url` is empty or is not a Postgres URL.
    """
    if not url or not url.strip():
        raise ValueError("Database URL is empty. Set DATABASE_URL in .env.")

    parts = urlsplit(url.strip())
    scheme = parts.scheme.lower()
    if not scheme:
        raise ValueError("Database URL has no scheme; expected a postgresql:// URL.")

    if "+" in scheme:
        base, _, _driver = scheme.partition("+")
        if base not in _BARE_SCHEMES:
            raise ValueError(f"Not a PostgreSQL URL (scheme {scheme!r}).")
        return urlunsplit(parts)

    if scheme not in _BARE_SCHEMES:
        raise ValueError(f"Not a PostgreSQL URL (scheme {scheme!r}).")

    return urlunsplit((_DRIVER, parts.netloc, parts.path, parts.query, parts.fragment))


def redact_url(url: str) -> str:
    """Render a URL safe to log: scheme, host, port and database name only.

    Used anywhere a connection target must appear in output — a health check, a test
    failure message, an alembic banner. Never print the raw URL instead of this.
    """
    try:
        parts = urlsplit(url)
    except ValueError:  # pragma: no cover - urlsplit is very forgiving
        return "<unparseable url>"
    host = parts.hostname or "?"
    port = f":{parts.port}" if parts.port else ""
    database = parts.path.lstrip("/") or "?"
    return f"{parts.scheme}://<redacted>@{host}{port}/{database}"


class Settings(BaseSettings):
    """Environment-backed configuration, read once per process."""

    model_config = SettingsConfigDict(
        env_file=ENV_FILE,
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    database_url: str
    test_database_url: str | None = None
    environment: str = "local"
    app_version: str = "0.0.1"

    def __repr__(self) -> str:
        """Credential-free repr. See the module docstring for why this is not optional."""
        return (
            f"Settings(environment={self.environment!r}, "
            f"app_version={self.app_version!r}, "
            f"database_url={redact_url(self.database_url)!r}, "
            f"test_database_url="
            f"{redact_url(self.test_database_url) if self.test_database_url else None!r})"
        )

    def __str__(self) -> str:
        return self.__repr__()

    @property
    def sqlalchemy_database_url(self) -> str:
        """The dev/production URL, driver-normalised."""
        return sqlalchemy_url(self.database_url)

    @property
    def sqlalchemy_test_database_url(self) -> str | None:
        """The test URL, driver-normalised, or None when no test database is configured."""
        if not self.test_database_url:
            return None
        return sqlalchemy_url(self.test_database_url)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return the process-wide Settings, constructed once."""
    return Settings()  # type: ignore[call-arg]  # values come from env/.env

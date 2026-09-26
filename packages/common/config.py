"""Application settings.

One place reads the environment. Everything else asks this module.

The single rule that matters here: **a connection string is a credential.** It is never
logged, never repr'd, never rendered into a stack trace and never written into
``alembic.ini``. ``Settings.__repr__`` is overridden precisely because pydantic's default
repr prints every field, and a `Settings` object ends up inside tracebacks and log lines
without anyone deciding it should.
"""

from __future__ import annotations

import re
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


#: Query parameters and headers whose value is a credential. Matched case-insensitively,
#: up to the next `&`, whitespace or quote.
_SECRET_PARAM = re.compile(
    r"((?:api[_-]?key|apikey|access[_-]?token|auth[_-]?token|token|password|passwd|secret)"
    r"\s*[=:]\s*)([^&\s\"'<>]+)",
    re.IGNORECASE,
)


def redact_secrets(text: str) -> str:
    """Strip credentials out of a string before it is logged, stored or displayed.

    **Why this exists, in one incident.** The FRED connector deliberately stores a
    key-free URL on its `RawResponse`, and that worked. But when a request failed, `httpx`
    raised an exception whose *message* contained the real request URL — key and all — and
    that message went straight into `connector_runs.error`, into the terminal, and would
    have gone into any log aggregator. A credential redacted in the happy path and printed
    on the error path is not redacted.

    Two passes, because either alone leaves a hole:

    1. **By parameter name** — catches `api_key=…` in any URL, including for services this
       code has never heard of and for keys that are not in our settings.
    2. **By known value** — catches a bare credential with no parameter name attached: a
       password inside a connection string, or a key echoed back in a response body.

    Never raises. It runs on error paths, where a redaction failure would replace a real
    diagnostic with a new traceback.
    """
    if not text:
        return text
    try:
        result = _SECRET_PARAM.sub(r"\1<redacted>", text)
        for value in _known_secret_values():
            # A short "secret" would match far too much ordinary text.
            if value and len(value) >= 8:
                result = result.replace(value, "<redacted>")
        return result
    except Exception:  # noqa: BLE001 - redaction must never break the caller
        return "<redaction failed; message withheld to avoid leaking a credential>"


def _known_secret_values() -> list[str]:
    """Literal secrets this process holds, for the value-based pass.

    Includes the password inside each connection string, which is the one credential most
    likely to turn up in a driver's error text.
    """
    try:
        settings = get_settings()
    except Exception:  # noqa: BLE001 - settings may be unavailable mid-failure
        return []
    values: list[str] = []
    # Every literal key this process can hold. An Anthropic error carries the request
    # context back in its message, so a key left out of this list is one that reaches the
    # log the first time the API refuses a call.
    for candidate in (
        settings.fred_api_key,
        settings.anthropic_api_key,
        settings.telegram_bot_token,
    ):
        if candidate:
            values.append(candidate)
    for url in (settings.database_url, settings.test_database_url):
        if not url:
            continue
        try:
            password = urlsplit(url).password
        except ValueError:  # pragma: no cover
            password = None
        if password:
            values.append(password)
    return values


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

    # P1.0 / ADR-0009. Local disk is the P1 backend; a remote bucket arrives at P3 entry
    # behind the same StorageBackend interface. Git-ignored, and covered by scripts/backup.ps1.
    documents_dir: str = "data/documents"

    # P1.2. Free key from fred.stlouisfed.org. Absent is a legitimate state: the FRED
    # connector refuses to run rather than half-running, and the manual CSV path (P1.7)
    # needs no key at all — which is the point of having it.
    fred_api_key: str | None = None

    # P2.1. EDGAR refuses requests without a descriptive User-Agent carrying a real name
    # and email (`DATA_FOUNDATION.md` §C). Absent is a legitimate state: the EDGAR
    # connectors refuse to run rather than send an anonymous request and be blocked.
    sec_user_agent: str | None = None

    # P4.2. The reconciliation step, and nothing else in the system, needs this. Absent is
    # a legitimate state and a common one: the deterministic half of the extraction
    # pipeline runs without it, the manual entry path (P3.2) needs no key at all, and
    # `ClaudeReconciler` refuses at the moment of use rather than at import.
    anthropic_api_key: str | None = None

    # P5.4. The daily brief's only credential. Absent is a legitimate state and is the
    # current one: `packages.brief.delivery.TelegramChannel` refuses at the moment of
    # send, the delivery is recorded `suppressed` with no `delivered_at`, and the same
    # content is retried once a token exists. Composing a brief needs no token at all.
    telegram_bot_token: str | None = None

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

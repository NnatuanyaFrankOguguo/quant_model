"""SQLAlchemy 2.0 typed declarative models — the P0 spine.

**Scope.** This is the P0 *spine only*, per `docs/10_PRE_BUILD_CORRECTIONS.md` §6.1: the
~14 tables P0 actually writes to, plus `industries`/`companies`/`securities` because
`watchlist_items.security_id` is a foreign key and a dangling FK stops
`alembic upgrade head` — finding #1 of the pre-build audit. The other ~35 tables in
`docs/08_DATA_CONTRACTS.md` §2.0 belong to the phase that first writes to them.

**The contract.** Every column here comes from `docs/08_DATA_CONTRACTS.md` §2 (§2.1
identity, §2.2 source, §2.5 macro, §2.11–2.13 compliance/ops, §2.15 the tables that had no
DDL), as corrected by `docs/10` §2. Nothing is invented. Where the documents disagree, the
divergence is called out in a comment on the class.

**Conventions enforced by `tests/unit/test_schema_conventions.py`:**

* every timestamp column is `TIMESTAMPTZ`, never a naive `TIMESTAMP` (TG21);
* user-scoped tables carry `principal_id`;
* tables a model reads carry `known_as_of` alongside a business date;
* tables holding an observed figure carry `source_document_id NOT NULL`.

Money is `NUMERIC` -> `decimal.Decimal`, never `float` (`docs/08` §1.6).
"""

from __future__ import annotations

import datetime as dt
import uuid
from decimal import Decimal

from sqlalchemy import (
    CHAR,
    BigInteger,
    Boolean,
    Computed,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    SmallInteger,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

# TIMESTAMPTZ. Declared once so no model can accidentally create a naive TIMESTAMP.
TZDateTime = DateTime(timezone=True)


class Base(DeclarativeBase):
    """Declarative base. `Base.metadata` is alembic's `target_metadata`."""


# ---------------------------------------------------------------------------
# §2.1 Identity and reference
#
# `exchanges` and `industries` are declared first because `companies` and `securities`
# reference them. Both were referenced by six foreign keys and defined in no document
# until the pre-build audit of 2026-08-30 (`docs/08` §2.1, `docs/10` §2.1).
# ---------------------------------------------------------------------------


class Exchange(Base):
    """A listing venue. `timezone` is what TG21 reads to place a session boundary."""

    __tablename__ = "exchanges"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    code: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    country: Mapped[str] = mapped_column(CHAR(2), nullable=False)
    timezone: Mapped[str] = mapped_column(Text, nullable=False)
    # NGX = 3. Never hardcode T+3 in code — `docs/08` §2.1.
    settlement_days: Mapped[int] = mapped_column(SmallInteger, nullable=False)


class Industry(Base):
    """Sector classification. Drives the default statement template."""

    __tablename__ = "industries"
    __table_args__ = (UniqueConstraint("scheme", "code"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    scheme: Mapped[str] = mapped_column(Text, nullable=False)  # 'ngx_sector'|'gics'|'sic'
    code: Mapped[str] = mapped_column(Text, nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    statement_template: Mapped[str] = mapped_column(Text, nullable=False)


class Company(Base):
    """The legal entity.

    `statement_template` here is a DEFAULT ONLY — the authoritative value lives on
    `statements.statement_template` (`docs/08` §2.3, deferred to P2).
    """

    __tablename__ = "companies"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    legal_name: Mapped[str] = mapped_column(Text, nullable=False)
    country: Mapped[str] = mapped_column(CHAR(2), nullable=False)  # ISO 3166-1
    industry_id: Mapped[int | None] = mapped_column(ForeignKey("industries.id"), nullable=True)
    # 'non_financial'|'bank'|'insurance'|'both' — insurers are a THIRD shape (§2.7).
    statement_template: Mapped[str] = mapped_column(Text, nullable=False)
    # Month, 1-12. NOT every company is December.
    fiscal_year_end: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    cik: Mapped[str | None] = mapped_column(Text, nullable=True)  # US only, zero-padded to 10
    rc_number: Mapped[str | None] = mapped_column(Text, nullable=True)  # Nigerian CAC
    created_at: Mapped[dt.datetime] = mapped_column(
        TZDateTime, nullable=False, server_default=func.now()
    )

    securities: Mapped[list[Security]] = relationship(back_populates="company")


class Security(Base):
    """A tradeable instrument.

    `delisted_date` is the survivorship-bias defence: a delisted row is retained forever,
    never deleted (`docs/08` §2.1, `SPEC.md` §2C).
    """

    __tablename__ = "securities"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id"), nullable=False)
    exchange_id: Mapped[int] = mapped_column(ForeignKey("exchanges.id"), nullable=False)
    currency: Mapped[str] = mapped_column(CHAR(3), nullable=False)  # 'NGN', 'USD'
    listed_date: Mapped[dt.date | None] = mapped_column(Date, nullable=True)
    # NOT NULL means delisted. NEVER delete the row.
    delisted_date: Mapped[dt.date | None] = mapped_column(Date, nullable=True)
    is_active: Mapped[bool] = mapped_column(
        Boolean, Computed("delisted_date IS NULL", persisted=True)
    )

    company: Mapped[Company] = relationship(back_populates="securities")
    exchange: Mapped[Exchange] = relationship()


# ---------------------------------------------------------------------------
# §2.2 Source and provenance
# ---------------------------------------------------------------------------


class DataSource(Base):
    """The licensing register — TG5, and a `CLAUDE.md` hard rule.

    `redistribution_allowed` is `NOT NULL` because that is the whole mechanism: it forces
    an answer at registration time. A connector whose source row is absent or incomplete
    cannot be enabled.
    """

    __tablename__ = "data_sources"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    source_name: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    base_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    licence_type: Mapped[str] = mapped_column(Text, nullable=False)
    redistribution_allowed: Mapped[bool] = mapped_column(Boolean, nullable=False)
    attribution_required: Mapped[bool] = mapped_column(Boolean, nullable=False)
    attribution_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    terms_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    terms_reviewed_on: Mapped[dt.date] = mapped_column(Date, nullable=False)
    reviewed_by: Mapped[str] = mapped_column(Text, nullable=False)
    rate_limit_per_sec: Mapped[Decimal | None] = mapped_column(Numeric, nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)


class SourceDocument(Base):
    """Every raw file ever fetched, immutable.

    A reissued report is a new row, never an edit — the `sha256` unique constraint
    enforces it. Every extracted figure points at a page in *this exact file*, forever.
    """

    __tablename__ = "source_documents"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    data_source_id: Mapped[int] = mapped_column(ForeignKey("data_sources.id"), nullable=False)
    url: Mapped[str | None] = mapped_column(Text, nullable=True)
    storage_key: Mapped[str] = mapped_column(Text, nullable=False)  # object-storage path
    sha256: Mapped[str] = mapped_column(CHAR(64), nullable=False, unique=True)
    media_type: Mapped[str] = mapped_column(Text, nullable=False)
    page_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    retrieved_at: Mapped[dt.datetime] = mapped_column(TZDateTime, nullable=False)
    http_status: Mapped[int | None] = mapped_column(Integer, nullable=True)
    etag: Mapped[str | None] = mapped_column(Text, nullable=True)
    last_modified: Mapped[dt.datetime | None] = mapped_column(TZDateTime, nullable=True)

    data_source: Mapped[DataSource] = relationship()


# ---------------------------------------------------------------------------
# §2.5 Macro
# ---------------------------------------------------------------------------


class MacroSeries(Base):
    """Series definitions. `expected_lag_days` drives the staleness flag."""

    __tablename__ = "macro_series"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    code: Mapped[str] = mapped_column(Text, nullable=False, unique=True)  # 'NG_CPI_YOY'
    name: Mapped[str] = mapped_column(Text, nullable=False)
    data_source_id: Mapped[int] = mapped_column(ForeignKey("data_sources.id"), nullable=False)
    unit: Mapped[str] = mapped_column(Text, nullable=False)  # 'percent'|'index'|'ngn_billions'
    frequency: Mapped[str] = mapped_column(Text, nullable=False)
    expected_lag_days: Mapped[int] = mapped_column(Integer, nullable=False)
    # 'CPI 2024=100' — rebasing changes history, so the base is part of the definition.
    base_period: Mapped[str | None] = mapped_column(Text, nullable=True)
    seasonal_adjustment: Mapped[str | None] = mapped_column(Text, nullable=True)

    data_source: Mapped[DataSource] = relationship()


class MacroObservation(Base):
    """Values, with vintages.

    `known_as_of` sits **inside** the primary key, and that is what makes vintages work: a
    revision inserts a second row rather than updating the first. Migration 0002 adds a
    `no_update` trigger so the rule survives someone with a SQL client at 1am, and makes
    `source_document_id` `NOT NULL` (`docs/10` §2.13 — provenance on every figure).
    """

    __tablename__ = "macro_observations"

    series_id: Mapped[int] = mapped_column(
        ForeignKey("macro_series.id"), primary_key=True, nullable=False
    )
    as_of_date: Mapped[dt.date] = mapped_column(Date, primary_key=True, nullable=False)
    known_as_of: Mapped[dt.date] = mapped_column(Date, primary_key=True, nullable=False)
    value: Mapped[Decimal | None] = mapped_column(Numeric, nullable=True)
    revision: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("1"))
    source_document_id: Mapped[int] = mapped_column(
        ForeignKey("source_documents.id"), nullable=False
    )

    series: Mapped[MacroSeries] = relationship()


# ---------------------------------------------------------------------------
# §2.12 Compliance and identity
# ---------------------------------------------------------------------------


class Principal(Base):
    """Who can authenticate — TG3.

    Carries the legal basis of the personal tier (`docs/10` §8 decision D2): personal mode
    is lawful without SEC registration **because no fee is charged and no funds are
    pooled**. `fee_charged` and `funds_pooled` record that, so it stays true by
    construction rather than by memory.

    `relationship_kind` maps to the SQL column `relationship` — the SQL name is the
    contract (`docs/08` §2.15), the Python name avoids colliding with
    `sqlalchemy.orm.relationship`.
    """

    __tablename__ = "principals"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    external_id: Mapped[str | None] = mapped_column(Text, nullable=True, unique=True)
    display_name: Mapped[str] = mapped_column(Text, nullable=False)
    email: Mapped[str | None] = mapped_column(Text, nullable=True, unique=True)
    kind: Mapped[str] = mapped_column(Text, nullable=False)  # 'owner'|'family'|'public'|'service'
    created_at: Mapped[dt.datetime] = mapped_column(
        TZDateTime, nullable=False, server_default=func.now()
    )
    disabled_at: Mapped[dt.datetime | None] = mapped_column(TZDateTime, nullable=True)

    # `docs/10` §8 D2 / `docs/08` §2.15.
    # 'self'|'spouse'|'parent'|'sibling'|'child'
    relationship_kind: Mapped[str | None] = mapped_column("relationship", Text, nullable=True)
    fee_charged: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    funds_pooled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )
    attested_by: Mapped[str | None] = mapped_column(Text, nullable=True)
    attested_on: Mapped[dt.date | None] = mapped_column(Date, nullable=True)

    entitlement: Mapped[Entitlement | None] = relationship(
        back_populates="principal", uselist=False
    )
    tokens: Mapped[list[PrincipalToken]] = relationship(back_populates="principal")


class Entitlement(Base):
    """What tier each principal reaches — TG3. `personal_tier` gates advice."""

    __tablename__ = "entitlements"

    principal_id: Mapped[int] = mapped_column(ForeignKey("principals.id"), primary_key=True)
    personal_tier: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )
    data_tier: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))
    llm_spend_cap_usd: Mapped[Decimal] = mapped_column(
        Numeric, nullable=False, server_default=text("0")
    )
    max_position_size: Mapped[Decimal | None] = mapped_column(Numeric, nullable=True)
    max_daily_loss: Mapped[Decimal | None] = mapped_column(Numeric, nullable=True)
    granted_by: Mapped[str] = mapped_column(Text, nullable=False)
    granted_at: Mapped[dt.datetime] = mapped_column(
        TZDateTime, nullable=False, server_default=func.now()
    )

    principal: Mapped[Principal] = relationship(back_populates="entitlement")


class PrincipalToken(Base):
    """Hashed bearer tokens — TG3, `docs/08` §2.15.

    Replaces the misleadingly-named `sessions` of §2.0: the P0 design is a hashed bearer
    token, not a session, and calling it a session invites cookie semantics this design
    does not want. `token_sha256` stores the hash — never the token itself. Swapped for a
    hosted identity provider at P9 (ADR-0003).
    """

    __tablename__ = "principal_tokens"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    principal_id: Mapped[int] = mapped_column(ForeignKey("principals.id"), nullable=False)
    token_sha256: Mapped[str] = mapped_column(CHAR(64), nullable=False, unique=True)
    label: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[dt.datetime] = mapped_column(
        TZDateTime, nullable=False, server_default=func.now()
    )
    expires_at: Mapped[dt.datetime | None] = mapped_column(TZDateTime, nullable=True)
    last_used_at: Mapped[dt.datetime | None] = mapped_column(TZDateTime, nullable=True)
    revoked_at: Mapped[dt.datetime | None] = mapped_column(TZDateTime, nullable=True)

    principal: Mapped[Principal] = relationship(back_populates="tokens")


class AuditLog(Base):
    """Every request.

    **Known open question, deliberately not resolved here.** `docs/08` §2.11–2.13 defines
    `principal TEXT` (a denormalised label) and that is what this model implements.
    `docs/10` §2.4 proposes replacing it with `principal_id INT REFERENCES principals(id)`
    plus a denormalised `principal_label TEXT`, but §2's own header states that all of §2
    is already applied to `docs/08` and that `docs/08` is what you build from — and
    `docs/08` still carries `principal TEXT`. The correction was not applied for this
    table. Changing it later is an additive migration over append-only rows, which is
    cheap; inventing a column the API is not writing to is not. Raised in the P0 report.
    """

    __tablename__ = "audit_log"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    ts: Mapped[dt.datetime] = mapped_column(TZDateTime, nullable=False, server_default=func.now())
    principal: Mapped[str | None] = mapped_column(Text, nullable=True)  # 'anonymous' if unauth
    mode: Mapped[str] = mapped_column(Text, nullable=False)
    method: Mapped[str] = mapped_column(Text, nullable=False)
    endpoint: Mapped[str] = mapped_column(Text, nullable=False)
    response_type: Mapped[str | None] = mapped_column(Text, nullable=True)
    http_status: Mapped[int] = mapped_column(Integer, nullable=False)
    request_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    latency_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)


class SystemConfig(Base):
    """Dated regulatory / operational config — TG20, P0.12.

    Dated because the NGX movement rule and the Nigerian CGT thresholds **both moved
    during planning**: a backtest over 2024 must read the 2024 value, not today's. The
    primary key is `(key, effective_from)`; `effective_to IS NULL` means currently in
    force. Read it through `packages.common.system_config`, never with an ad-hoc query.
    """

    __tablename__ = "system_config"

    key: Mapped[str] = mapped_column(Text, primary_key=True)
    value: Mapped[dict | list | str | int | float | bool | None] = mapped_column(
        JSONB, nullable=False
    )
    effective_from: Mapped[dt.date] = mapped_column(Date, primary_key=True)
    effective_to: Mapped[dt.date | None] = mapped_column(Date, nullable=True)
    set_by: Mapped[str] = mapped_column(Text, nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    source_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    adr_ref: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[dt.datetime] = mapped_column(
        TZDateTime, nullable=False, server_default=func.now()
    )


# ---------------------------------------------------------------------------
# §2.13 Operations
# ---------------------------------------------------------------------------


class ConnectorRun(Base):
    """Connector health — the silent-failure detector.

    `rows_written` is the single most important operational column in the schema. The
    classic scraper failure is not a crash: the page loads, the parser runs, the selector
    matches nothing, and `status` is `'ok'` with zero rows. Alert on
    `status='ok' AND rows_written=0` on a date the source was expected to publish.
    """

    __tablename__ = "connector_runs"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    connector_name: Mapped[str] = mapped_column(Text, nullable=False)
    started_at: Mapped[dt.datetime] = mapped_column(TZDateTime, nullable=False)
    finished_at: Mapped[dt.datetime | None] = mapped_column(TZDateTime, nullable=True)
    status: Mapped[str] = mapped_column(Text, nullable=False)
    rows_written: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    http_status: Mapped[int | None] = mapped_column(Integer, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)


class LlmSpend(Base):
    """Per-principal LLM cost tracking — `docs/08` §2.15.

    `principal_id IS NULL` means the scheduler — which is exactly the spend the global cap
    must cover, and which a per-principal cap alone would never stop.
    """

    __tablename__ = "llm_spend"
    __table_args__ = (
        Index("ix_llm_spend_principal_ts", "principal_id", "ts"),
        Index("ix_llm_spend_ts", "ts"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    principal_id: Mapped[int | None] = mapped_column(ForeignKey("principals.id"), nullable=True)
    ts: Mapped[dt.datetime] = mapped_column(TZDateTime, nullable=False, server_default=func.now())
    # 'extraction'|'sentiment'|'memo'|'tagging'
    job_kind: Mapped[str] = mapped_column(Text, nullable=False)
    model: Mapped[str] = mapped_column(Text, nullable=False)
    prompt_version: Mapped[str | None] = mapped_column(Text, nullable=True)
    input_tokens: Mapped[int] = mapped_column(Integer, nullable=False)
    output_tokens: Mapped[int] = mapped_column(Integer, nullable=False)
    cost_usd: Mapped[Decimal] = mapped_column(Numeric, nullable=False)
    cache_hit: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    source_document_id: Mapped[int | None] = mapped_column(
        ForeignKey("source_documents.id"), nullable=True
    )
    request_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)


# ---------------------------------------------------------------------------
# TG11 — watchlists
# ---------------------------------------------------------------------------


class Watchlist(Base):
    """A named watchlist owned by one principal — TG11."""

    __tablename__ = "watchlists"
    __table_args__ = (UniqueConstraint("principal_id", "name"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    principal_id: Mapped[int] = mapped_column(ForeignKey("principals.id"), nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[dt.datetime] = mapped_column(
        TZDateTime, nullable=False, server_default=func.now()
    )

    items: Mapped[list[WatchlistItem]] = relationship(
        back_populates="watchlist", cascade="all, delete-orphan"
    )


class WatchlistItem(Base):
    """One security on one watchlist.

    Ownership is inherited from `watchlists.principal_id`, not repeated here — the
    convention test classifies this as user-scoped *via parent*.
    """

    __tablename__ = "watchlist_items"

    watchlist_id: Mapped[int] = mapped_column(
        ForeignKey("watchlists.id", ondelete="CASCADE"), primary_key=True
    )
    security_id: Mapped[int] = mapped_column(ForeignKey("securities.id"), primary_key=True)
    added_at: Mapped[dt.datetime] = mapped_column(
        TZDateTime, nullable=False, server_default=func.now()
    )

    watchlist: Mapped[Watchlist] = relationship(back_populates="items")
    security: Mapped[Security] = relationship()


__all__ = [
    "AuditLog",
    "Base",
    "Company",
    "ConnectorRun",
    "DataSource",
    "Entitlement",
    "Exchange",
    "Industry",
    "LlmSpend",
    "MacroObservation",
    "MacroSeries",
    "Principal",
    "PrincipalToken",
    "Security",
    "SourceDocument",
    "SystemConfig",
    "Watchlist",
    "WatchlistItem",
]

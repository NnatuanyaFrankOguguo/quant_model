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
    CheckConstraint,
    Computed,
    Date,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
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
    # `cik` moved into `security_identifiers` in migration 0019 (`docs/10` §2.11): it is a
    # dated identifier like every other, and the column carried no unique constraint.
    # Read it through `identity.current_identifiers(CIK)`.
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


class SecurityIdentifier(Base):
    """A ticker, ISIN, CUSIP, SEDOL, CIK, LEI or FIGI, dated. `docs/08` §2.1, TG2.

    Tickers get reused and companies rename; GUARANTY became GTCO on 2021-06-24 and both
    rows point at the same security, so the price history never splits.

    **Read nothing here directly.** `packages/common/identity.py` is the only module that
    queries this table (`OPERATIONS.md` §1.4: "no `WHERE ticker = ?` anywhere else in the
    codebase"), and a test walks the AST of the repository to keep it that way.

    `valid_to` is **inclusive**: the last day the identifier was valid. The next row starts
    the following day, which is what makes `docs/08` §2.1's GUARANTY/GTCO sample gap-free.

    Two things migration 0018 creates in raw SQL, because neither is expressible here:

    * `no_overlapping_ids` - `EXCLUDE USING gist` over
      `(id_type, id_value, COALESCE(exchange_id, 0), daterange(valid_from, valid_to + 1))`.
      `docs/10` §2.11 calls it "the only mechanism that makes `resolve_security` provably
      single-valued", and it replaced a unique key that let two securities hold one ticker
      over overlapping dates as long as `valid_from` differed by a day.
    * `CREATE EXTENSION btree_gist`, which that constraint needs for integer equality.
    """

    __tablename__ = "security_identifiers"
    __table_args__ = (
        # Mirrors migration 0018. The dropped `UNIQUE (id_type, id_value, valid_from)` is
        # deliberately absent: it was not exchange-scoped, so it rejected one ticker string
        # legitimately listed on two exchanges from the same day.
        CheckConstraint(
            "id_type IN ('ticker', 'isin', 'cusip', 'sedol', 'cik', 'lei', 'figi')",
            name="identifier_type_is_known",
        ),
        CheckConstraint(
            "id_type <> 'ticker' OR exchange_id IS NOT NULL", name="identifier_has_exchange"
        ),
        CheckConstraint(
            "valid_to IS NULL OR valid_to >= valid_from", name="identifier_interval_is_ordered"
        ),
        Index("ix_security_identifiers_lookup", "id_type", "id_value", "valid_from", "valid_to"),
        Index(
            "one_primary_ticker_per_security",
            "security_id",
            unique=True,
            postgresql_where=text("is_primary AND id_type = 'ticker' AND valid_to IS NULL"),
        ),
        # Migration 0019. `no_overlapping_ids` keys on the value, so it would allow one
        # security to carry two different current CIKs - and then "this company's CIK",
        # which four API responses print, would have two answers.
        Index(
            "one_current_cik_per_security",
            "security_id",
            unique=True,
            postgresql_where=text("id_type = 'cik' AND valid_to IS NULL"),
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    security_id: Mapped[int] = mapped_column(ForeignKey("securities.id"), nullable=False)
    id_type: Mapped[str] = mapped_column(Text, nullable=False)  # see identity.ID_TYPES
    id_value: Mapped[str] = mapped_column(Text, nullable=False)
    valid_from: Mapped[dt.date] = mapped_column(Date, nullable=False)
    valid_to: Mapped[dt.date | None] = mapped_column(Date, nullable=True)  # NULL = current
    # NULL for the global types (ISIN, CUSIP, SEDOL, CIK, LEI, FIGI): they name an
    # instrument or a registrant, not a listing. A ticker without one is refused.
    exchange_id: Mapped[int | None] = mapped_column(ForeignKey("exchanges.id"), nullable=True)
    # Which of a security's current tickers is the common stock. EDGAR lists notes and
    # preferred series beside it; `one_primary_ticker_per_security` allows exactly one.
    is_primary: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    #: Who says this identifier was theirs. Provenance, `CLAUDE.md`'s hard rule.
    source: Mapped[str | None] = mapped_column(Text, nullable=True)

    security: Mapped[Security] = relationship()


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
# §2.2–2.3 Extraction, filings and financial statements (P2, migration 0011)
# ---------------------------------------------------------------------------


class ExtractionJob(Base):
    """How a document was turned into figures: `'xbrl'`, `'manual'` or `'llm_hybrid'`."""

    __tablename__ = "extraction_jobs"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    source_document_id: Mapped[int] = mapped_column(
        ForeignKey("source_documents.id"), nullable=False
    )
    method: Mapped[str] = mapped_column(Text, nullable=False)
    model_name: Mapped[str | None] = mapped_column(Text, nullable=True)
    prompt_version: Mapped[str | None] = mapped_column(Text, nullable=True)
    # 'pending'|'stored'|'needs_review'|'corrected'|'failed'
    status: Mapped[str] = mapped_column(Text, nullable=False)
    confidence: Mapped[Decimal | None] = mapped_column(Numeric, nullable=True)
    validation_failures: Mapped[list[object]] = mapped_column(
        JSONB, nullable=False, server_default=text("'[]'::jsonb")
    )
    token_cost_usd: Mapped[Decimal | None] = mapped_column(Numeric, nullable=True)
    started_at: Mapped[dt.datetime] = mapped_column(TZDateTime, nullable=False)
    finished_at: Mapped[dt.datetime | None] = mapped_column(TZDateTime, nullable=True)
    reviewed_by: Mapped[str | None] = mapped_column(Text, nullable=True)
    reviewed_at: Mapped[dt.datetime | None] = mapped_column(TZDateTime, nullable=True)


class Filing(Base):
    """One regulator submission. `filing_date` is the `known_as_of` of everything in it."""

    __tablename__ = "filings"
    __table_args__ = (UniqueConstraint("company_id", "filing_type", "period_end", "filing_date"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id"), nullable=False)
    filing_type: Mapped[str] = mapped_column(Text, nullable=False)  # '10-K'|'10-Q'|...
    filing_date: Mapped[dt.date] = mapped_column(Date, nullable=False)
    period_end: Mapped[dt.date] = mapped_column(Date, nullable=False)
    accession_no: Mapped[str | None] = mapped_column(Text, nullable=True)  # EDGAR only
    source_document_id: Mapped[int] = mapped_column(
        ForeignKey("source_documents.id"), nullable=False
    )
    known_as_of: Mapped[dt.date] = mapped_column(Date, nullable=False)
    created_at: Mapped[dt.datetime] = mapped_column(
        TZDateTime, nullable=False, server_default=func.now()
    )


class ChartAccount(Base):
    """One canonical key in one chart version. The vocabulary, versioned (TG7)."""

    __tablename__ = "chart_of_accounts"

    canonical_key: Mapped[str] = mapped_column(Text, primary_key=True)
    chart_version: Mapped[str] = mapped_column(Text, primary_key=True)
    statement: Mapped[str] = mapped_column(Text, nullable=False)  # 'income'|'balance'|'cashflow'
    # 'financial'|'non_financial'|'both'
    template: Mapped[str] = mapped_column(Text, nullable=False)
    display_name: Mapped[str] = mapped_column(Text, nullable=False)
    sign_convention: Mapped[str] = mapped_column(Text, nullable=False)
    is_required: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))


class AccountMapping(Base):
    """Source label → canonical key, as data. `priority` orders alternates for one key."""

    __tablename__ = "account_mappings"
    __table_args__ = (
        ForeignKeyConstraint(
            ["canonical_key", "chart_version"],
            ["chart_of_accounts.canonical_key", "chart_of_accounts.chart_version"],
        ),
        UniqueConstraint("chart_version", "source_system", "source_label", "template"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    chart_version: Mapped[str] = mapped_column(Text, nullable=False)
    source_system: Mapped[str] = mapped_column(Text, nullable=False)  # 'us_gaap_xbrl'|...
    source_label: Mapped[str] = mapped_column(Text, nullable=False)
    canonical_key: Mapped[str] = mapped_column(Text, nullable=False)
    template: Mapped[str] = mapped_column(Text, nullable=False)
    priority: Mapped[int] = mapped_column(SmallInteger, nullable=False, server_default=text("100"))
    confidence: Mapped[Decimal] = mapped_column(Numeric, nullable=False, server_default=text("1.0"))
    added_by: Mapped[str] = mapped_column(Text, nullable=False)


class Statement(Base):
    """One statement for one period, versioned. `docs/10` §2.3.

    `period_type` is what keeps Q4 and FY apart when both end on the same date. A
    restatement is a new row with `version + 1`; the old row's `superseded_by` points at it,
    and that pointer is the only column the update trigger lets anyone write.
    """

    __tablename__ = "statements"
    __table_args__ = (
        UniqueConstraint(
            "company_id",
            "statement_type",
            "period_type",
            "period_end",
            "is_consolidated",
            "version",
        ),
        CheckConstraint("known_as_of >= period_end", name="statements_pit_sanity"),
        Index(
            "ix_statements_company_period",
            "company_id",
            "statement_type",
            "period_type",
            "period_end",
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    filing_id: Mapped[int | None] = mapped_column(ForeignKey("filings.id"), nullable=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id"), nullable=False)
    statement_type: Mapped[str] = mapped_column(Text, nullable=False)
    period_type: Mapped[str] = mapped_column(Text, nullable=False)
    period_start: Mapped[dt.date | None] = mapped_column(Date, nullable=True)
    period_end: Mapped[dt.date] = mapped_column(Date, nullable=False)
    fiscal_year: Mapped[int] = mapped_column(Integer, nullable=False)
    calendar_year: Mapped[int] = mapped_column(Integer, nullable=False)
    period_label: Mapped[str] = mapped_column(Text, nullable=False)
    presentation_currency: Mapped[str] = mapped_column(CHAR(3), nullable=False)
    presentation_multiplier: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("1")
    )
    is_audited: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    is_consolidated: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("true")
    )
    statement_template: Mapped[str] = mapped_column(Text, nullable=False)
    chart_version: Mapped[str] = mapped_column(Text, nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("1"))
    superseded_by: Mapped[int | None] = mapped_column(ForeignKey("statements.id"), nullable=True)
    restatement_flag: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )
    known_as_of: Mapped[dt.date] = mapped_column(Date, nullable=False)
    source_document_id: Mapped[int] = mapped_column(
        ForeignKey("source_documents.id"), nullable=False
    )
    created_at: Mapped[dt.datetime] = mapped_column(
        TZDateTime, nullable=False, server_default=func.now()
    )

    line_items: Mapped[list[StatementLineItem]] = relationship(back_populates="statement")


class StatementLineItem(Base):
    """One figure. `value` NULL means the company did not report it — never 0 (`SPEC` §4.1).

    Four rules in one table (`docs/08` §2.3): `value` nullable; `source_document_id` NOT NULL
    and `page` required unless the source is structured; `known_as_of` separate from
    `period_end`; `version` + `superseded_by` instead of any update.
    """

    __tablename__ = "statement_line_items"
    __table_args__ = (
        ForeignKeyConstraint(
            ["canonical_key", "chart_version"],
            ["chart_of_accounts.canonical_key", "chart_of_accounts.chart_version"],
        ),
        CheckConstraint(
            "extraction_method = 'xbrl' OR page IS NOT NULL",
            name="page_required_unless_structured",
        ),
        CheckConstraint("known_as_of >= period_end", name="line_items_pit_sanity"),
        Index(
            "ix_line_items_pit",
            "security_id",
            "canonical_key",
            text("known_as_of DESC"),
            text("version DESC"),
        ),
        Index(
            "one_current_version",
            "statement_id",
            "canonical_key",
            unique=True,
            postgresql_where=text("superseded_by IS NULL"),
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    statement_id: Mapped[int] = mapped_column(ForeignKey("statements.id"), nullable=False)
    security_id: Mapped[int] = mapped_column(ForeignKey("securities.id"), nullable=False)
    canonical_key: Mapped[str] = mapped_column(Text, nullable=False)
    chart_version: Mapped[str] = mapped_column(Text, nullable=False)
    as_printed_label: Mapped[str | None] = mapped_column(Text, nullable=True)
    as_printed_value: Mapped[str | None] = mapped_column(Text, nullable=True)
    as_printed_scale: Mapped[str | None] = mapped_column(Text, nullable=True)
    needs_review: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )
    value: Mapped[Decimal | None] = mapped_column(Numeric, nullable=True)
    currency: Mapped[str] = mapped_column(CHAR(3), nullable=False)
    unit_multiplier: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("1"))
    period_start: Mapped[dt.date | None] = mapped_column(Date, nullable=True)
    period_end: Mapped[dt.date] = mapped_column(Date, nullable=False)
    known_as_of: Mapped[dt.date] = mapped_column(Date, nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("1"))
    superseded_by: Mapped[int | None] = mapped_column(
        ForeignKey("statement_line_items.id"), nullable=True
    )
    restatement_flag: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )
    # docs/10 §2.10: 'none'|'restatement'|'transcription'|'extraction'
    correction_type: Mapped[str] = mapped_column(
        Text, nullable=False, server_default=text("'none'")
    )
    source_document_id: Mapped[int] = mapped_column(
        ForeignKey("source_documents.id"), nullable=False
    )
    page: Mapped[int | None] = mapped_column(Integer, nullable=True)
    bbox: Mapped[dict[str, object] | None] = mapped_column(JSONB, nullable=True)
    extraction_job_id: Mapped[int | None] = mapped_column(
        ForeignKey("extraction_jobs.id"), nullable=True
    )
    extraction_method: Mapped[str] = mapped_column(Text, nullable=False)
    confidence: Mapped[Decimal | None] = mapped_column(Numeric, nullable=True)
    reviewed_by: Mapped[str | None] = mapped_column(Text, nullable=True)
    corrected_by: Mapped[str | None] = mapped_column(Text, nullable=True)
    corrected_at: Mapped[dt.datetime | None] = mapped_column(TZDateTime, nullable=True)
    correction_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[dt.datetime] = mapped_column(
        TZDateTime, nullable=False, server_default=func.now()
    )

    statement: Mapped[Statement] = relationship(back_populates="line_items")


# ---------------------------------------------------------------------------
# §2.4 Market data (P2.3, migration 0012)
# ---------------------------------------------------------------------------


class PriceHistory(Base):
    """One daily bar, as traded. `docs/08` §2.4 as corrected 2026-08-30.

    No adjusted column: adjusted prices are computed on read from `adjustment_factors`
    whose `known_as_of` is on or before the decision date (TG2). `known_as_of` is in the
    key so a restated bar is a second row, never an overwrite; migration 0002's `no_update`
    trigger guards the table.
    """

    __tablename__ = "price_history"
    __table_args__ = (CheckConstraint("known_as_of >= date", name="price_history_pit_sanity"),)

    security_id: Mapped[int] = mapped_column(ForeignKey("securities.id"), primary_key=True)
    date: Mapped[dt.date] = mapped_column(Date, primary_key=True)
    known_as_of: Mapped[dt.date] = mapped_column(Date, primary_key=True)
    open_raw: Mapped[Decimal | None] = mapped_column(Numeric, nullable=True)
    high_raw: Mapped[Decimal | None] = mapped_column(Numeric, nullable=True)
    low_raw: Mapped[Decimal | None] = mapped_column(Numeric, nullable=True)
    close_raw: Mapped[Decimal] = mapped_column(Numeric, nullable=False)  # AS TRADED
    volume: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    vwap: Mapped[Decimal | None] = mapped_column(Numeric, nullable=True)
    halted: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    data_source_id: Mapped[int] = mapped_column(ForeignKey("data_sources.id"), nullable=False)
    source_document_id: Mapped[int] = mapped_column(
        ForeignKey("source_documents.id"), nullable=False
    )


class SharesOutstanding(Base):
    """The share count as of a date. `docs/08` §2.14 #49: no P/E is correct without it."""

    __tablename__ = "shares_outstanding"
    __table_args__ = (
        CheckConstraint("known_as_of >= as_of_date", name="shares_pit_sanity"),
        CheckConstraint("shares > 0", name="shares_positive"),
    )

    security_id: Mapped[int] = mapped_column(ForeignKey("securities.id"), primary_key=True)
    as_of_date: Mapped[dt.date] = mapped_column(Date, primary_key=True)
    share_class: Mapped[str] = mapped_column(
        Text, primary_key=True, server_default=text("'ordinary'")
    )
    basic_or_diluted: Mapped[str] = mapped_column(Text, primary_key=True)  # 'basic'|'diluted'
    known_as_of: Mapped[dt.date] = mapped_column(Date, primary_key=True)
    shares: Mapped[Decimal] = mapped_column(Numeric, nullable=False)
    source_document_id: Mapped[int] = mapped_column(
        ForeignKey("source_documents.id"), nullable=False
    )
    page: Mapped[int | None] = mapped_column(Integer, nullable=True)


# ---------------------------------------------------------------------------
# §2.4 TG2 / TG12 - corporate actions and the point-in-time adjustment (migration 0015)
# ---------------------------------------------------------------------------


class CorporateAction(Base):
    """One split, bonus, rights issue, dividend or consolidation, as a dated fact off a
    document. `known_as_of` is in the unique key: a corrected ratio is a second row."""

    __tablename__ = "corporate_actions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    security_id: Mapped[int] = mapped_column(ForeignKey("securities.id"), nullable=False)
    action_type: Mapped[str] = mapped_column(Text, nullable=False)
    announcement_date: Mapped[dt.date | None] = mapped_column(Date, nullable=True)
    ex_date: Mapped[dt.date] = mapped_column(Date, nullable=False)
    record_date: Mapped[dt.date | None] = mapped_column(Date, nullable=True)
    pay_date: Mapped[dt.date | None] = mapped_column(Date, nullable=True)
    ratio_from: Mapped[Decimal | None] = mapped_column(Numeric, nullable=True)
    ratio_to: Mapped[Decimal | None] = mapped_column(Numeric, nullable=True)
    cash_amount: Mapped[Decimal | None] = mapped_column(Numeric, nullable=True)
    subscription_price: Mapped[Decimal | None] = mapped_column(Numeric, nullable=True)
    currency: Mapped[str | None] = mapped_column(CHAR(3), nullable=True)
    source_document_id: Mapped[int] = mapped_column(
        ForeignKey("source_documents.id"), nullable=False
    )
    confidence: Mapped[Decimal | None] = mapped_column(Numeric, nullable=True)
    needs_review: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )
    known_as_of: Mapped[dt.date] = mapped_column(Date, nullable=False)


class AdjustmentFactor(Base):
    """One action's own multiplier for prices before its ex-date, with the day it became
    knowable. Never cumulative: the read function multiplies what was known on the day."""

    __tablename__ = "adjustment_factors"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    security_id: Mapped[int] = mapped_column(ForeignKey("securities.id"), nullable=False)
    ex_date: Mapped[dt.date] = mapped_column(Date, nullable=False)
    action_id: Mapped[int] = mapped_column(ForeignKey("corporate_actions.id"), nullable=False)
    factor: Mapped[Decimal] = mapped_column(Numeric, nullable=False)
    known_as_of: Mapped[dt.date] = mapped_column(Date, nullable=False)
    source_document_id: Mapped[int] = mapped_column(
        ForeignKey("source_documents.id"), nullable=False
    )


class FxRate(Base):
    """One rate for one pair on one day, at the vintage it became knowable (TG2).

    `known_as_of` is in the primary key, so a corrected rate is a second row - and
    `packages.common.fx` refuses to convert without a decision date.
    """

    __tablename__ = "fx_rates"

    base_currency: Mapped[str] = mapped_column(CHAR(3), primary_key=True)
    quote_currency: Mapped[str] = mapped_column(CHAR(3), primary_key=True)
    rate_type: Mapped[str] = mapped_column(Text, primary_key=True)
    as_of_date: Mapped[dt.date] = mapped_column(Date, primary_key=True)
    known_as_of: Mapped[dt.date] = mapped_column(Date, primary_key=True)
    rate: Mapped[Decimal] = mapped_column(Numeric, nullable=False)
    data_source_id: Mapped[int] = mapped_column(ForeignKey("data_sources.id"), nullable=False)
    source_document_id: Mapped[int] = mapped_column(
        ForeignKey("source_documents.id"), nullable=False
    )


# ---------------------------------------------------------------------------
# §2.14 #50–54 The entity graph (P2, migration 0014; populated from P3/P4)
# ---------------------------------------------------------------------------


class Person(Base):
    """A director or officer. `normalised_name` is what matching joins on."""

    __tablename__ = "persons"
    __table_args__ = (Index("ix_persons_normalised_name", "normalised_name"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    full_name: Mapped[str] = mapped_column(Text, nullable=False)
    normalised_name: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[dt.datetime] = mapped_column(
        TZDateTime, nullable=False, server_default=func.now()
    )


class EntityRole(Base):
    """A board seat or executive role, dated: who sat where when the decision was made."""

    __tablename__ = "entity_roles"
    __table_args__ = (Index("ix_entity_roles_company", "company_id", "valid_from"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    person_id: Mapped[int] = mapped_column(ForeignKey("persons.id"), nullable=False)
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id"), nullable=False)
    role: Mapped[str] = mapped_column(Text, nullable=False)
    valid_from: Mapped[dt.date] = mapped_column(Date, nullable=False)
    valid_to: Mapped[dt.date | None] = mapped_column(Date, nullable=True)
    known_as_of: Mapped[dt.date] = mapped_column(Date, nullable=False)
    source_document_id: Mapped[int] = mapped_column(
        ForeignKey("source_documents.id"), nullable=False
    )
    page: Mapped[int | None] = mapped_column(Integer, nullable=True)
    confidence: Mapped[Decimal | None] = mapped_column(Numeric, nullable=True)
    needs_review: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )


class Shareholding(Base):
    """A substantial holder. `holder_company_id` makes cross-holdings queryable."""

    __tablename__ = "shareholdings"
    __table_args__ = (Index("ix_shareholdings_company", "company_id", "as_of_date"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id"), nullable=False)
    holder_name: Mapped[str] = mapped_column(Text, nullable=False)
    holder_type: Mapped[str] = mapped_column(Text, nullable=False)
    holder_person_id: Mapped[int | None] = mapped_column(ForeignKey("persons.id"), nullable=True)
    holder_company_id: Mapped[int | None] = mapped_column(ForeignKey("companies.id"), nullable=True)
    units: Mapped[Decimal | None] = mapped_column(Numeric, nullable=True)
    pct_held: Mapped[Decimal | None] = mapped_column(Numeric, nullable=True)
    as_of_date: Mapped[dt.date] = mapped_column(Date, nullable=False)
    known_as_of: Mapped[dt.date] = mapped_column(Date, nullable=False)
    source_document_id: Mapped[int] = mapped_column(
        ForeignKey("source_documents.id"), nullable=False
    )
    page: Mapped[int | None] = mapped_column(Integer, nullable=True)
    needs_review: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )


class CompanyRelationship(Base):
    """One generic edge: parent, subsidiary, auditor, related party, customer, supplier."""

    __tablename__ = "company_relationships"
    __table_args__ = (
        CheckConstraint(
            "to_company_id IS NOT NULL OR to_name IS NOT NULL", name="relationship_has_a_target"
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    from_company_id: Mapped[int] = mapped_column(ForeignKey("companies.id"), nullable=False)
    to_company_id: Mapped[int | None] = mapped_column(ForeignKey("companies.id"), nullable=True)
    to_name: Mapped[str | None] = mapped_column(Text, nullable=True)
    relation: Mapped[str] = mapped_column(Text, nullable=False)
    ownership_pct: Mapped[Decimal | None] = mapped_column(Numeric, nullable=True)
    valid_from: Mapped[dt.date | None] = mapped_column(Date, nullable=True)
    valid_to: Mapped[dt.date | None] = mapped_column(Date, nullable=True)
    known_as_of: Mapped[dt.date] = mapped_column(Date, nullable=False)
    source_document_id: Mapped[int] = mapped_column(
        ForeignKey("source_documents.id"), nullable=False
    )
    page: Mapped[int | None] = mapped_column(Integer, nullable=True)
    needs_review: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )


class IndexMembership(Base):
    """Point-in-time index constituents: 'the NGX 30 as of 2020' must be answerable (P7)."""

    __tablename__ = "index_membership"

    index_code: Mapped[str] = mapped_column(Text, primary_key=True)
    security_id: Mapped[int] = mapped_column(ForeignKey("securities.id"), primary_key=True)
    valid_from: Mapped[dt.date] = mapped_column(Date, primary_key=True)
    known_as_of: Mapped[dt.date] = mapped_column(Date, primary_key=True)
    valid_to: Mapped[dt.date | None] = mapped_column(Date, nullable=True)
    weight: Mapped[Decimal | None] = mapped_column(Numeric, nullable=True)
    source_document_id: Mapped[int] = mapped_column(
        ForeignKey("source_documents.id"), nullable=False
    )


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

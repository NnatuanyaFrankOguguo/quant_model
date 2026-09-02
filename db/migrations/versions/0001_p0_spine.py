"""0001 - the P0 spine.

Revision ID: 0001_p0_spine
Revises:
Create Date: 2026-09-01

**Scope: the spine only, not all 52 tables.** `docs/10_PRE_BUILD_CORRECTIONS.md` §6.1
replaces P0.4's "create every table" with **P0.4-SPINE** — one migration of the ~14 tables
P0 actually writes to — on the grounds that *"building 49 empty tables in P0 buys nothing
an empty table can buy"*, and that the conventions those tables were meant to guarantee are
better enforced by `tests/unit/test_schema_conventions.py`, which also governs P7's and
P10's tables, which P0 cannot.

The 14: `principals`, `entitlements`, `principal_tokens`, `system_config`, `data_sources`,
`source_documents`, `macro_series`, `macro_observations`, `connector_runs`, `audit_log`,
`watchlists`, `watchlist_items`, `llm_spend`, `exchanges`.

**Plus three, and here is why.** `industries`, `companies` and `securities` are created
here even though nothing in P0 writes to them, because `watchlist_items.security_id` is a
foreign key to `securities`, `securities` references `companies` and `exchanges`, and
`companies` references `industries`. A foreign key to a table that does not exist stops
`alembic upgrade head` outright — the exact failure the pre-build audit's finding #1
describes (`docs/10` §2.1: *"These reference tables that exist in no document. The first
migration fails on them."*). Dropping the column instead would silently permit a watchlist
item pointing at nothing, which is the failure mode the audit was written to prevent.

Every column is from `docs/08_DATA_CONTRACTS.md` §2 (§2.1 identity, §2.2 source, §2.5
macro, §2.11–2.13 compliance/ops, §2.15 the tables that had no DDL), as corrected by
`docs/10` §2. Nothing is invented.

**Deferred, with the reason:** every other table in `docs/08` §2.0 goes to the phase that
first writes to it (`docs/10` §2.15). Notably `statements`, `filings` and
`statement_line_items` (P2), `price_history` and `corporate_actions` (P2/P3),
`trading_calendar`, `security_identifiers` and `fx_rates` (P3), `extraction_jobs` (P4),
`alerts`/`alert_deliveries` and the portfolio tables (P10). None of the spine tables holds
a foreign key into any of them.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0001_p0_spine"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# TIMESTAMPTZ, spelled once. TG21: storage is UTC and every timestamp column carries a
# zone. `tests/unit/test_schema_conventions.py` fails the build on a naive TIMESTAMP.
TZ = sa.DateTime(timezone=True)


def upgrade() -> None:
    # -- §2.12 identity ----------------------------------------------------
    op.create_table(
        "principals",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("external_id", sa.Text(), nullable=True, unique=True),
        sa.Column("display_name", sa.Text(), nullable=False),
        sa.Column("email", sa.Text(), nullable=True, unique=True),
        # 'owner' | 'family' | 'public' | 'service'
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("created_at", TZ, nullable=False, server_default=sa.func.now()),
        sa.Column("disabled_at", TZ, nullable=True),
        # The legal basis of the personal tier, recorded rather than remembered
        # (`docs/10` §8 decision D2, `docs/08` §2.15). Personal mode is lawful without
        # SEC registration BECAUSE no fee is charged and no funds are pooled.
        # 'self' | 'spouse' | 'parent' | 'sibling' | 'child'
        sa.Column("relationship", sa.Text(), nullable=True),
        sa.Column("fee_charged", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("funds_pooled", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("attested_by", sa.Text(), nullable=True),
        sa.Column("attested_on", sa.Date(), nullable=True),
    )

    op.create_table(
        "entitlements",
        sa.Column(
            "principal_id",
            sa.Integer(),
            sa.ForeignKey("principals.id"),
            primary_key=True,
        ),
        # personal_tier gates advice. Default false: a new principal reaches nothing.
        sa.Column("personal_tier", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("data_tier", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("llm_spend_cap_usd", sa.Numeric(), nullable=False, server_default=sa.text("0")),
        sa.Column("max_position_size", sa.Numeric(), nullable=True),
        sa.Column("max_daily_loss", sa.Numeric(), nullable=True),
        sa.Column("granted_by", sa.Text(), nullable=False),
        sa.Column("granted_at", TZ, nullable=False, server_default=sa.func.now()),
    )

    op.create_table(
        "principal_tokens",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("principal_id", sa.Integer(), sa.ForeignKey("principals.id"), nullable=False),
        # The HASH, never the token itself.
        sa.Column("token_sha256", sa.CHAR(64), nullable=False, unique=True),
        sa.Column("label", sa.Text(), nullable=False),
        sa.Column("created_at", TZ, nullable=False, server_default=sa.func.now()),
        sa.Column("expires_at", TZ, nullable=True),
        sa.Column("last_used_at", TZ, nullable=True),
        sa.Column("revoked_at", TZ, nullable=True),
    )

    # -- TG20 dated config -------------------------------------------------
    op.create_table(
        "system_config",
        sa.Column("key", sa.Text(), primary_key=True),
        sa.Column("value", postgresql.JSONB(), nullable=False),
        sa.Column("effective_from", sa.Date(), primary_key=True),
        # NULL = currently in force. Windows are half-open: [effective_from, effective_to)
        sa.Column("effective_to", sa.Date(), nullable=True),
        sa.Column("set_by", sa.Text(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("source_url", sa.Text(), nullable=True),
        sa.Column("adr_ref", sa.Text(), nullable=True),
        sa.Column("created_at", TZ, nullable=False, server_default=sa.func.now()),
    )

    # -- §2.12 audit -------------------------------------------------------
    op.create_table(
        "audit_log",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("ts", TZ, nullable=False, server_default=sa.func.now()),
        # 'anonymous' when unauthenticated. `docs/10` §2.4 proposes replacing this with
        # principal_id + principal_label; `docs/08` §2.11 (which §2 of `docs/10` defers
        # to) still specifies `principal TEXT`, and the API is written against that name.
        # Raised as an open question in the P0 report rather than decided here.
        sa.Column("principal", sa.Text(), nullable=True),
        sa.Column("mode", sa.Text(), nullable=False),
        sa.Column("method", sa.Text(), nullable=False),
        sa.Column("endpoint", sa.Text(), nullable=False),
        sa.Column("response_type", sa.Text(), nullable=True),
        sa.Column("http_status", sa.Integer(), nullable=False),
        sa.Column("request_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("latency_ms", sa.Integer(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
    )

    # -- §2.13 operations --------------------------------------------------
    op.create_table(
        "connector_runs",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("connector_name", sa.Text(), nullable=False),
        sa.Column("started_at", TZ, nullable=False),
        sa.Column("finished_at", TZ, nullable=True),
        sa.Column("status", sa.Text(), nullable=False),
        # THE silent-failure detector: alert on status='ok' AND rows_written=0.
        sa.Column("rows_written", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("http_status", sa.Integer(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
    )

    # -- §2.1 identity and reference --------------------------------------
    op.create_table(
        "exchanges",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("code", sa.Text(), nullable=False, unique=True),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("country", sa.CHAR(2), nullable=False),
        # 'Africa/Lagos' — TG21 reads this to place a session boundary.
        sa.Column("timezone", sa.Text(), nullable=False),
        # NGX = 3. Never hardcode T+3 in code.
        sa.Column("settlement_days", sa.SmallInteger(), nullable=False),
    )

    op.create_table(
        "industries",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("scheme", sa.Text(), nullable=False),  # 'ngx_sector'|'gics'|'sic'
        sa.Column("code", sa.Text(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("statement_template", sa.Text(), nullable=False),
        sa.UniqueConstraint("scheme", "code"),
    )

    op.create_table(
        "companies",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("legal_name", sa.Text(), nullable=False),
        sa.Column("country", sa.CHAR(2), nullable=False),  # ISO 3166-1
        sa.Column("industry_id", sa.Integer(), sa.ForeignKey("industries.id"), nullable=True),
        # DEFAULT ONLY — the authoritative value lives on statements.statement_template
        # (`docs/08` §2.3, P2). 'non_financial'|'bank'|'insurance'|'both'.
        sa.Column("statement_template", sa.Text(), nullable=False),
        # Month, 1-12. NOT every company is December.
        sa.Column("fiscal_year_end", sa.SmallInteger(), nullable=False),
        sa.Column("cik", sa.Text(), nullable=True),  # US only, zero-padded to 10
        sa.Column("rc_number", sa.Text(), nullable=True),  # Nigerian CAC registration
        sa.Column("created_at", TZ, nullable=False, server_default=sa.func.now()),
    )

    op.create_table(
        "securities",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("company_id", sa.Integer(), sa.ForeignKey("companies.id"), nullable=False),
        sa.Column("exchange_id", sa.Integer(), sa.ForeignKey("exchanges.id"), nullable=False),
        sa.Column("currency", sa.CHAR(3), nullable=False),
        sa.Column("listed_date", sa.Date(), nullable=True),
        # NOT NULL means delisted. NEVER delete the row — this is the survivorship-bias
        # defence (`docs/08` §2.1, `SPEC.md` §2C).
        sa.Column("delisted_date", sa.Date(), nullable=True),
        sa.Column(
            "is_active",
            sa.Boolean(),
            sa.Computed("delisted_date IS NULL", persisted=True),
        ),
    )

    # -- §2.2 source and provenance ---------------------------------------
    op.create_table(
        "data_sources",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("source_name", sa.Text(), nullable=False, unique=True),
        sa.Column("base_url", sa.Text(), nullable=True),
        sa.Column("licence_type", sa.Text(), nullable=False),
        # NOT NULL is the whole mechanism: it forces an answer at registration time.
        sa.Column("redistribution_allowed", sa.Boolean(), nullable=False),
        sa.Column("attribution_required", sa.Boolean(), nullable=False),
        sa.Column("attribution_text", sa.Text(), nullable=True),
        sa.Column("terms_url", sa.Text(), nullable=True),
        sa.Column("terms_reviewed_on", sa.Date(), nullable=False),
        sa.Column("reviewed_by", sa.Text(), nullable=False),
        sa.Column("rate_limit_per_sec", sa.Numeric(), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
    )

    op.create_table(
        "source_documents",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("data_source_id", sa.Integer(), sa.ForeignKey("data_sources.id"), nullable=False),
        sa.Column("url", sa.Text(), nullable=True),
        sa.Column("storage_key", sa.Text(), nullable=False),
        # Dedupe, and proof the file never changed. A reissued report is a NEW row.
        sa.Column("sha256", sa.CHAR(64), nullable=False, unique=True),
        sa.Column("media_type", sa.Text(), nullable=False),
        sa.Column("page_count", sa.Integer(), nullable=True),
        sa.Column("retrieved_at", TZ, nullable=False),
        sa.Column("http_status", sa.Integer(), nullable=True),
        sa.Column("etag", sa.Text(), nullable=True),
        sa.Column("last_modified", TZ, nullable=True),
    )

    # -- §2.5 macro --------------------------------------------------------
    op.create_table(
        "macro_series",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("code", sa.Text(), nullable=False, unique=True),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("data_source_id", sa.Integer(), sa.ForeignKey("data_sources.id"), nullable=False),
        sa.Column("unit", sa.Text(), nullable=False),
        sa.Column("frequency", sa.Text(), nullable=False),
        # Drives the staleness flag.
        sa.Column("expected_lag_days", sa.Integer(), nullable=False),
        # 'CPI 2024=100'. Rebasing changes past values, so the base is part of the
        # definition — Nigerian CPI was rebased to 2024 and GDP to 2019.
        sa.Column("base_period", sa.Text(), nullable=True),
        sa.Column("seasonal_adjustment", sa.Text(), nullable=True),
    )

    op.create_table(
        "macro_observations",
        sa.Column("series_id", sa.Integer(), sa.ForeignKey("macro_series.id"), primary_key=True),
        # The period described.
        sa.Column("as_of_date", sa.Date(), primary_key=True),
        # When published (FRED: realtime_start). IN the primary key — that is what makes
        # vintages work: a revision inserts a second row instead of overwriting the first.
        sa.Column("known_as_of", sa.Date(), primary_key=True),
        sa.Column("value", sa.Numeric(), nullable=True),
        sa.Column("revision", sa.Integer(), nullable=False, server_default=sa.text("1")),
        # Nullable here; migration 0002 makes it NOT NULL (`docs/10` §2.13). Split across
        # two revisions to keep one concern per revision (`docs/02` §3.4).
        sa.Column(
            "source_document_id",
            sa.BigInteger(),
            sa.ForeignKey("source_documents.id"),
            nullable=True,
        ),
    )

    # -- §2.15 llm spend ---------------------------------------------------
    op.create_table(
        "llm_spend",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        # NULL = the scheduler. Exactly the spend a per-principal cap would never stop.
        sa.Column("principal_id", sa.Integer(), sa.ForeignKey("principals.id"), nullable=True),
        sa.Column("ts", TZ, nullable=False, server_default=sa.func.now()),
        # 'extraction'|'sentiment'|'memo'|'tagging'
        sa.Column("job_kind", sa.Text(), nullable=False),
        sa.Column("model", sa.Text(), nullable=False),
        sa.Column("prompt_version", sa.Text(), nullable=True),
        sa.Column("input_tokens", sa.Integer(), nullable=False),
        sa.Column("output_tokens", sa.Integer(), nullable=False),
        sa.Column("cost_usd", sa.Numeric(), nullable=False),
        sa.Column("cache_hit", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column(
            "source_document_id",
            sa.BigInteger(),
            sa.ForeignKey("source_documents.id"),
            nullable=True,
        ),
        sa.Column("request_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.create_index("ix_llm_spend_principal_ts", "llm_spend", ["principal_id", "ts"])
    op.create_index("ix_llm_spend_ts", "llm_spend", ["ts"])

    # -- TG11 watchlists ---------------------------------------------------
    op.create_table(
        "watchlists",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("principal_id", sa.Integer(), sa.ForeignKey("principals.id"), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("created_at", TZ, nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("principal_id", "name"),
    )

    op.create_table(
        "watchlist_items",
        sa.Column(
            "watchlist_id",
            sa.Integer(),
            sa.ForeignKey("watchlists.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        # The foreign key that forced `securities` (and transitively `companies`,
        # `exchanges`, `industries`) into this migration. See the module docstring.
        sa.Column("security_id", sa.Integer(), sa.ForeignKey("securities.id"), primary_key=True),
        sa.Column("added_at", TZ, nullable=False, server_default=sa.func.now()),
    )


def downgrade() -> None:
    # Reverse creation order so no drop trips over a dependent foreign key.
    op.drop_table("watchlist_items")
    op.drop_table("watchlists")
    op.drop_index("ix_llm_spend_ts", table_name="llm_spend")
    op.drop_index("ix_llm_spend_principal_ts", table_name="llm_spend")
    op.drop_table("llm_spend")
    op.drop_table("macro_observations")
    op.drop_table("macro_series")
    op.drop_table("source_documents")
    op.drop_table("data_sources")
    op.drop_table("securities")
    op.drop_table("companies")
    op.drop_table("industries")
    op.drop_table("exchanges")
    op.drop_table("connector_runs")
    op.drop_table("audit_log")
    op.drop_table("system_config")
    op.drop_table("principal_tokens")
    op.drop_table("entitlements")
    op.drop_table("principals")

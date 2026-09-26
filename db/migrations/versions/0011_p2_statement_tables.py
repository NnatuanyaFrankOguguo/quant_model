"""0011 - the financial statement tables, the chart of accounts, and the exchanges. P2.

Revision ID: 0011_p2_statement_tables
Revises: 0010_p1_fred_clipped_rows
Create Date: 2026-09-12

`docs/08` §2.2–2.3 as corrected by `docs/10` §2.1–2.3, §2.8–2.10 and §2.13–2.14. Seven tables:

* `security_identifiers` — tickers as dated identifiers (`docs/08` §2.1, TG2), created here
  because the EDGAR submissions connector is the first thing to write one.
* `extraction_jobs` — how a document was turned into figures (`'xbrl'` here; `'manual'`
  and `'llm_hybrid'` from P3), with the cost and the reviewer when there was one.
* `filings` — one row per regulator submission: the accession number, what it is, when it
  was filed. `filing_date` is the `known_as_of` of everything it contains.
* `chart_of_accounts` — the canonical vocabulary, **versioned** (TG7). Draft `v0.1` here,
  against US GAAP, where tagging is standardised; frozen as v1 in P3 once Nigerian IFRS
  statements have shown what it is missing.
* `account_mappings` — source label → canonical key, as data. A human edits this many
  times; a table gives versioning and an audit trail for free.
* `statements` — the row `docs/10` §2.3 calls the audit's most expensive omission: without
  `period_type`, Q4 and FY revenue both arrive as the same `period_end` on the same key.
* `statement_line_items` — the figures. `value` NULL means the company did not report the
  item. **Never 0 for missing** (`SPEC.md` §4.1).

## The structural rules, in the database rather than in review

* `page_required_unless_structured` — a figure read off a page carries the page; XBRL has
  none, and says so with `extraction_method = 'xbrl'` (`docs/10` §2.13).
* `pit_sanity` — `known_as_of >= period_end`. A figure knowable before its period ended is
  lookahead, and it is refused at the row.
* `one_current_version` — at most one un-superseded row per `(statement_id, canonical_key)`,
  so "the current value" is a guaranteed single row rather than whatever `ORDER BY` picks.
* `no_update_except_supersession` — `UPDATE` is forbidden on `statements` and
  `statement_line_items` **except** to set `superseded_by` from NULL, once. Migration 0002's
  blanket `forbid_update()` would also forbid the one write `docs/08` §10 requires: *"never
  UPDATE; insert a new version, set `superseded_by`"*. Values still never change; only the
  pointer that says a later version exists can be written, and only when it is empty.

## What is seeded

**Exchanges.** `exchanges` was empty; a security cannot exist without one. NGX settles T+3;
NASDAQ and NYSE settle T+1 since 2024-05-28. `settlement_days` is a column so that nobody
hardcodes either (`docs/08` §2.1).

**Chart of accounts v0.1** — seventeen monetary keys across the three statements for the
`non_financial` template, plus the three bank-only keys `docs/08` §4 names (`gross_earnings`,
`net_interest_income`, `fx_loss_net`) under `financial`, with no XBRL mapping: their labels
are Nigerian IFRS and arrive in P3. `gross_earnings` is deliberately **not** `revenue` — a
bank's gross earnings include interest and fee income and are not comparable to a
manufacturer's turnover; mapping them together produces a number that looks comparable and
is not.

**US GAAP mappings** for v0.1, with a `priority`: XBRL offers several tags for one concept
(`Revenues`, `RevenueFromContractWithCustomerExcludingAssessedTax`, `SalesRevenueNet`) and a
filer uses one of them, so resolution is "the first mapped tag that has a fact for the
period, in priority order". `priority` is an addition to the `docs/08` §2.3 DDL, recorded
here and there; without it the alternates would have to be ordered by `confidence`, which
means something else.

`downgrade()` drops the seven tables and the trigger function, and deletes exactly the
exchange rows seeded here.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "0011_p2_statement_tables"
down_revision: str | None = "0010_p1_fred_clipped_rows"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TZ = sa.DateTime(timezone=True)

CHART_VERSION = "v0.1"

EXCHANGES: list[dict[str, Any]] = [
    {
        "code": "NGX",
        "name": "Nigerian Exchange",
        "country": "NG",
        "timezone": "Africa/Lagos",
        "settlement_days": 3,
    },
    {
        "code": "NASDAQ",
        "name": "Nasdaq Stock Market",
        "country": "US",
        "timezone": "America/New_York",
        "settlement_days": 1,
    },
    {
        "code": "NYSE",
        "name": "New York Stock Exchange",
        "country": "US",
        "timezone": "America/New_York",
        "settlement_days": 1,
    },
]

# (canonical_key, statement, template, display_name, sign_convention, is_required)
CHART: list[tuple[str, str, str, str, str, bool]] = [
    # income statement
    ("revenue", "income", "non_financial", "Revenue", "positive", True),
    ("cost_of_revenue", "income", "non_financial", "Cost of revenue", "positive", False),
    ("gross_profit", "income", "non_financial", "Gross profit", "either", False),
    (
        "rd_expense",
        "income",
        "non_financial",
        "Research and development expense",
        "positive",
        False,
    ),
    ("operating_profit", "income", "non_financial", "Operating profit", "either", True),
    ("interest_expense", "income", "non_financial", "Interest expense", "positive", False),
    ("income_tax", "income", "non_financial", "Income tax expense", "either", False),
    ("profit_after_tax", "income", "both", "Profit after tax", "either", True),
    # balance sheet
    ("total_assets", "balance", "both", "Total assets", "positive", True),
    ("current_assets", "balance", "non_financial", "Current assets", "positive", False),
    ("cash", "balance", "both", "Cash and cash equivalents", "positive", False),
    ("total_liabilities", "balance", "both", "Total liabilities", "positive", False),
    ("current_liabilities", "balance", "non_financial", "Current liabilities", "positive", False),
    ("long_term_debt", "balance", "non_financial", "Long-term debt", "positive", False),
    ("total_equity", "balance", "both", "Total equity", "either", True),
    # cash flow statement
    ("cash_from_ops", "cashflow", "both", "Net cash from operating activities", "either", True),
    (
        "capex",
        "cashflow",
        "non_financial",
        "Purchase of property, plant and equipment",
        "positive",
        False,
    ),
    (
        "depreciation_amortisation",
        "cashflow",
        "non_financial",
        "Depreciation and amortisation",
        "positive",
        False,
    ),
    ("dividends_paid", "cashflow", "both", "Dividends paid", "positive", False),
    ("buybacks", "cashflow", "non_financial", "Repurchase of own shares", "positive", False),
    # bank-only, docs/08 §4 - labels are Nigerian IFRS and arrive with P3's manual analyzer
    ("gross_earnings", "income", "financial", "Gross earnings", "positive", True),
    ("net_interest_income", "income", "financial", "Net interest income", "either", True),
    ("fx_loss_net", "income", "both", "Net foreign exchange loss", "either", False),
]

# (canonical_key, us-gaap tag, priority) - lower priority number wins.
#
# An alternate is admitted only when it names the SAME measure under another tag - a
# taxonomy rename, or two spellings filers use for one total. It is NOT admitted when its
# value can legitimately differ from the primary's, because a later filing that carries only
# the alternate would then resolve the same period to a different number and the writer
# would record a restatement that never happened. The first draft of this list did exactly
# that with `CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalents` as an alternate
# for `cash`: Apple's 10-Q comparatives carry only the restricted-inclusive figure for the
# prior period, and six false "restatements" of cash appeared before a single real one.
# Left out for that reason: ProfitLoss (includes non-controlling interests), LongTermDebt
# (includes the current portion), StockholdersEquityIncludingPortionAttributableTo
# NoncontrollingInterest, InterestExpenseNonoperating, PaymentsOfDividendsCommonStock. A
# company that reports only one of those has a NULL, which is honest.
US_GAAP_MAPPINGS: list[tuple[str, str, int]] = [
    ("revenue", "Revenues", 10),
    ("revenue", "RevenueFromContractWithCustomerExcludingAssessedTax", 20),
    ("revenue", "SalesRevenueNet", 30),
    ("cost_of_revenue", "CostOfRevenue", 10),
    ("cost_of_revenue", "CostOfGoodsAndServicesSold", 20),
    ("gross_profit", "GrossProfit", 10),
    ("rd_expense", "ResearchAndDevelopmentExpense", 10),
    ("operating_profit", "OperatingIncomeLoss", 10),
    ("interest_expense", "InterestExpense", 10),
    ("income_tax", "IncomeTaxExpenseBenefit", 10),
    ("profit_after_tax", "NetIncomeLoss", 10),
    ("total_assets", "Assets", 10),
    ("current_assets", "AssetsCurrent", 10),
    ("cash", "CashAndCashEquivalentsAtCarryingValue", 10),
    ("total_liabilities", "Liabilities", 10),
    ("current_liabilities", "LiabilitiesCurrent", 10),
    ("long_term_debt", "LongTermDebtNoncurrent", 10),
    ("total_equity", "StockholdersEquity", 10),
    ("cash_from_ops", "NetCashProvidedByUsedInOperatingActivities", 10),
    ("capex", "PaymentsToAcquirePropertyPlantAndEquipment", 10),
    ("depreciation_amortisation", "DepreciationDepletionAndAmortization", 10),
    ("depreciation_amortisation", "DepreciationAndAmortization", 20),
    ("dividends_paid", "PaymentsOfDividends", 10),
    ("buybacks", "PaymentsForRepurchaseOfCommonStock", 10),
]

SUPERSESSION_TRIGGER_FN = """
CREATE OR REPLACE FUNCTION forbid_update_except_supersession() RETURNS TRIGGER AS $$
BEGIN
    IF OLD.superseded_by IS NULL
       AND NEW.superseded_by IS NOT NULL
       AND to_jsonb(NEW) - 'superseded_by' = to_jsonb(OLD) - 'superseded_by' THEN
        RETURN NEW;
    END IF;
    RAISE EXCEPTION
        'UPDATE forbidden on %; insert a new version and set superseded_by on the old row',
        TG_TABLE_NAME;
END;
$$ LANGUAGE plpgsql;
"""


def upgrade() -> None:
    op.create_table(
        "extraction_jobs",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column(
            "source_document_id",
            sa.BigInteger(),
            sa.ForeignKey("source_documents.id"),
            nullable=False,
        ),
        sa.Column("method", sa.Text(), nullable=False),  # 'manual'|'llm_hybrid'|'xbrl'
        sa.Column("model_name", sa.Text(), nullable=True),
        sa.Column("prompt_version", sa.Text(), nullable=True),
        sa.Column(
            "status", sa.Text(), nullable=False
        ),  # pending|stored|needs_review|corrected|failed
        sa.Column("confidence", sa.Numeric(), nullable=True),
        sa.Column(
            "validation_failures", JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb")
        ),
        sa.Column("token_cost_usd", sa.Numeric(), nullable=True),
        sa.Column("started_at", TZ, nullable=False),
        sa.Column("finished_at", TZ, nullable=True),
        sa.Column("reviewed_by", sa.Text(), nullable=True),
        sa.Column("reviewed_at", TZ, nullable=True),
    )

    op.create_table(
        "filings",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("company_id", sa.Integer(), sa.ForeignKey("companies.id"), nullable=False),
        sa.Column(
            "filing_type", sa.Text(), nullable=False
        ),  # '10-K'|'10-Q'|'annual_report'|'interim'
        sa.Column("filing_date", sa.Date(), nullable=False),
        sa.Column("period_end", sa.Date(), nullable=False),
        sa.Column("accession_no", sa.Text(), nullable=True),  # EDGAR only
        sa.Column(
            "source_document_id",
            sa.BigInteger(),
            sa.ForeignKey("source_documents.id"),
            nullable=False,
        ),
        sa.Column("known_as_of", sa.Date(), nullable=False),
        sa.Column("created_at", TZ, nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("company_id", "filing_type", "period_end", "filing_date"),
    )
    op.create_index("ix_filings_accession", "filings", ["accession_no"])

    # docs/08 §2.1 (TG2, OPERATIONS §1.4): tickers are dated identifiers, never a column on
    # securities, because tickers get reused and companies rename. Created here because the
    # EDGAR submissions connector is the first writer of one.
    op.create_table(
        "security_identifiers",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("security_id", sa.Integer(), sa.ForeignKey("securities.id"), nullable=False),
        sa.Column("id_type", sa.Text(), nullable=False),  # 'ticker'|'isin'|'cusip'|'sedol'
        sa.Column("id_value", sa.Text(), nullable=False),
        sa.Column("valid_from", sa.Date(), nullable=False),
        sa.Column("valid_to", sa.Date(), nullable=True),  # NULL = still current
        sa.UniqueConstraint("id_type", "id_value", "valid_from"),
    )
    op.create_index(
        "ix_security_identifiers_lookup",
        "security_identifiers",
        ["id_type", "id_value", "valid_from", "valid_to"],
    )

    op.create_table(
        "chart_of_accounts",
        sa.Column("canonical_key", sa.Text(), nullable=False),
        sa.Column("chart_version", sa.Text(), nullable=False),
        sa.Column("statement", sa.Text(), nullable=False),  # 'income'|'balance'|'cashflow'
        sa.Column("template", sa.Text(), nullable=False),  # 'financial'|'non_financial'|'both'
        sa.Column("display_name", sa.Text(), nullable=False),
        sa.Column("sign_convention", sa.Text(), nullable=False),  # 'positive'|'negative'|'either'
        sa.Column("is_required", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.PrimaryKeyConstraint("canonical_key", "chart_version"),
    )

    op.create_table(
        "account_mappings",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("chart_version", sa.Text(), nullable=False),
        sa.Column("source_system", sa.Text(), nullable=False),  # 'us_gaap_xbrl'|'ng_ifrs_label'
        sa.Column("source_label", sa.Text(), nullable=False),
        sa.Column("canonical_key", sa.Text(), nullable=False),
        sa.Column("template", sa.Text(), nullable=False),
        # Addition to docs/08 §2.3: resolution order among alternate labels for one key.
        sa.Column("priority", sa.SmallInteger(), nullable=False, server_default=sa.text("100")),
        sa.Column("confidence", sa.Numeric(), nullable=False, server_default=sa.text("1.0")),
        sa.Column("added_by", sa.Text(), nullable=False),
        sa.ForeignKeyConstraint(
            ["canonical_key", "chart_version"],
            ["chart_of_accounts.canonical_key", "chart_of_accounts.chart_version"],
        ),
        sa.UniqueConstraint("chart_version", "source_system", "source_label", "template"),
    )

    op.create_table(
        "statements",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("filing_id", sa.BigInteger(), sa.ForeignKey("filings.id"), nullable=True),
        sa.Column("company_id", sa.Integer(), sa.ForeignKey("companies.id"), nullable=False),
        sa.Column(
            "statement_type", sa.Text(), nullable=False
        ),  # 'income'|'balance'|'cashflow'|'equity'
        sa.Column("period_type", sa.Text(), nullable=False),  # 'FY'|'H1'|'Q1'|'Q2'|'Q3'|'Q4'|'YTD'
        sa.Column("period_start", sa.Date(), nullable=True),
        sa.Column("period_end", sa.Date(), nullable=False),
        sa.Column("fiscal_year", sa.Integer(), nullable=False),
        sa.Column("calendar_year", sa.Integer(), nullable=False),
        sa.Column("period_label", sa.Text(), nullable=False),
        sa.Column("presentation_currency", sa.CHAR(3), nullable=False),
        sa.Column(
            "presentation_multiplier", sa.Integer(), nullable=False, server_default=sa.text("1")
        ),
        sa.Column("is_audited", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("is_consolidated", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("statement_template", sa.Text(), nullable=False),
        sa.Column("chart_version", sa.Text(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False, server_default=sa.text("1")),
        sa.Column("superseded_by", sa.BigInteger(), sa.ForeignKey("statements.id"), nullable=True),
        sa.Column("restatement_flag", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("known_as_of", sa.Date(), nullable=False),
        sa.Column(
            "source_document_id",
            sa.BigInteger(),
            sa.ForeignKey("source_documents.id"),
            nullable=False,
        ),
        sa.Column("created_at", TZ, nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint(
            "company_id",
            "statement_type",
            "period_type",
            "period_end",
            "is_consolidated",
            "version",
        ),
        sa.CheckConstraint("known_as_of >= period_end", name="statements_pit_sanity"),
    )
    op.create_index(
        "ix_statements_company_period",
        "statements",
        ["company_id", "statement_type", "period_type", "period_end"],
    )

    op.create_table(
        "statement_line_items",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("statement_id", sa.BigInteger(), sa.ForeignKey("statements.id"), nullable=False),
        sa.Column("security_id", sa.Integer(), sa.ForeignKey("securities.id"), nullable=False),
        sa.Column("canonical_key", sa.Text(), nullable=False),
        sa.Column("chart_version", sa.Text(), nullable=False),
        sa.Column("as_printed_label", sa.Text(), nullable=True),
        sa.Column("as_printed_value", sa.Text(), nullable=True),
        sa.Column("as_printed_scale", sa.Text(), nullable=True),
        sa.Column("needs_review", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("value", sa.Numeric(), nullable=True),  # NULL = absent. NEVER 0 for missing.
        sa.Column("currency", sa.CHAR(3), nullable=False),
        sa.Column("unit_multiplier", sa.Integer(), nullable=False, server_default=sa.text("1")),
        sa.Column("period_start", sa.Date(), nullable=True),
        sa.Column("period_end", sa.Date(), nullable=False),  # the as-of date
        sa.Column("known_as_of", sa.Date(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False, server_default=sa.text("1")),
        sa.Column(
            "superseded_by",
            sa.BigInteger(),
            sa.ForeignKey("statement_line_items.id"),
            nullable=True,
        ),
        sa.Column("restatement_flag", sa.Boolean(), nullable=False, server_default=sa.false()),
        # docs/10 §2.10: 'none'|'restatement'|'transcription'|'extraction'
        sa.Column("correction_type", sa.Text(), nullable=False, server_default=sa.text("'none'")),
        sa.Column(
            "source_document_id",
            sa.BigInteger(),
            sa.ForeignKey("source_documents.id"),
            nullable=False,
        ),
        sa.Column("page", sa.Integer(), nullable=True),
        sa.Column("bbox", JSONB(), nullable=True),
        sa.Column(
            "extraction_job_id", sa.BigInteger(), sa.ForeignKey("extraction_jobs.id"), nullable=True
        ),
        sa.Column("extraction_method", sa.Text(), nullable=False),
        sa.Column("confidence", sa.Numeric(), nullable=True),
        sa.Column("reviewed_by", sa.Text(), nullable=True),
        sa.Column("corrected_by", sa.Text(), nullable=True),
        sa.Column("corrected_at", TZ, nullable=True),
        sa.Column("correction_reason", sa.Text(), nullable=True),
        sa.Column("created_at", TZ, nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(
            ["canonical_key", "chart_version"],
            ["chart_of_accounts.canonical_key", "chart_of_accounts.chart_version"],
        ),
        sa.CheckConstraint(
            "extraction_method = 'xbrl' OR page IS NOT NULL", name="page_required_unless_structured"
        ),
        sa.CheckConstraint("known_as_of >= period_end", name="line_items_pit_sanity"),
    )
    op.create_index(
        "ix_line_items_pit",
        "statement_line_items",
        ["security_id", "canonical_key", sa.text("known_as_of DESC"), sa.text("version DESC")],
    )
    op.create_index(
        "one_current_version",
        "statement_line_items",
        ["statement_id", "canonical_key"],
        unique=True,
        postgresql_where=sa.text("superseded_by IS NULL"),
    )

    op.execute(SUPERSESSION_TRIGGER_FN)
    for table in ("statements", "statement_line_items"):
        op.execute(
            f"CREATE TRIGGER no_update_except_supersession BEFORE UPDATE ON {table} "
            f"FOR EACH ROW EXECUTE FUNCTION forbid_update_except_supersession();"
        )

    # -- seeds -------------------------------------------------------------------------
    exchanges = sa.table(
        "exchanges",
        sa.column("code", sa.Text),
        sa.column("name", sa.Text),
        sa.column("country", sa.CHAR(2)),
        sa.column("timezone", sa.Text),
        sa.column("settlement_days", sa.SmallInteger),
    )
    op.bulk_insert(exchanges, EXCHANGES)

    chart = sa.table(
        "chart_of_accounts",
        sa.column("canonical_key", sa.Text),
        sa.column("chart_version", sa.Text),
        sa.column("statement", sa.Text),
        sa.column("template", sa.Text),
        sa.column("display_name", sa.Text),
        sa.column("sign_convention", sa.Text),
        sa.column("is_required", sa.Boolean),
    )
    op.bulk_insert(
        chart,
        [
            {
                "canonical_key": key,
                "chart_version": CHART_VERSION,
                "statement": statement,
                "template": template,
                "display_name": display_name,
                "sign_convention": sign,
                "is_required": required,
            }
            for key, statement, template, display_name, sign, required in CHART
        ],
    )

    mappings = sa.table(
        "account_mappings",
        sa.column("chart_version", sa.Text),
        sa.column("source_system", sa.Text),
        sa.column("source_label", sa.Text),
        sa.column("canonical_key", sa.Text),
        sa.column("template", sa.Text),
        sa.column("priority", sa.SmallInteger),
        sa.column("confidence", sa.Numeric),
        sa.column("added_by", sa.Text),
    )
    op.bulk_insert(
        mappings,
        [
            {
                "chart_version": CHART_VERSION,
                "source_system": "us_gaap_xbrl",
                "source_label": tag,
                "canonical_key": key,
                "template": "non_financial",
                "priority": priority,
                "confidence": 1.0,
                "added_by": "migration 0011 (draft v0.1, 2026-09-12)",
            }
            for key, tag, priority in US_GAAP_MAPPINGS
        ],
    )


def downgrade() -> None:
    for table in ("statement_line_items", "statements"):
        op.execute(f"DROP TRIGGER IF EXISTS no_update_except_supersession ON {table};")
    op.drop_table("statement_line_items")
    op.drop_table("statements")
    op.drop_table("account_mappings")
    op.drop_table("chart_of_accounts")
    op.drop_table("security_identifiers")
    op.drop_table("filings")
    op.drop_table("extraction_jobs")
    op.execute("DROP FUNCTION IF EXISTS forbid_update_except_supersession();")
    codes = [row["code"] for row in EXCHANGES]
    op.execute(sa.text("DELETE FROM exchanges WHERE code = ANY(:codes)").bindparams(codes=codes))

"""0012 - price_history, as traded, with the vintage in the key. P2.3, TG1-US.

Revision ID: 0012_p2_price_history
Revises: 0011_p2_statement_tables
Create Date: 2026-09-13

`docs/08` §2.4 as corrected on 2026-08-30 and in `docs/10` §2.13–2.14. Three things the DDL
insists on, each of which has cost a real backtest somewhere:

* **`close_raw` is the price that traded, and there is no `close_adj` column.** A stored
  adjusted price is one global vintage: it embeds every corporate action known when it was
  computed, including actions announced after a decision date. Adjusted prices are computed
  on read, from `adjustment_factors` whose `known_as_of` is on or before the decision date
  (TG2, P3). `docs/03` P2.3 and its check 9 predate this correction and still say "both
  columns"; the contract wins.
* **`known_as_of` is in the primary key.** Exchanges restate settlement prices and fetches
  get re-run; without it a re-run would UPDATE and the original bar would be gone - a silent
  overwrite on the most-read table in the system. A restated bar is a second row.
* **Provenance on every bar** - `data_source_id` and `source_document_id` NOT NULL - and the
  `no_update` trigger from migration 0002, as `docs/10` §2.14 lists for this table.

Also seeds the `data_sources` row for Yahoo Finance, the P2 price source `DATA_FOUNDATION.md`
§C recommends starting with ("free, fragile, fine for personal US"). Its historical prices
are split-adjusted retroactively, so the connector multiplies the provider's own split ratios
back out to store what actually traded; the raw response, splits included, is kept as the
source document. `redistribution_allowed = false`: Yahoo's terms permit personal use and say
nothing that could be read as a licence to re-serve.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date

import sqlalchemy as sa
from alembic import op

revision: str = "0012_p2_price_history"
down_revision: str | None = "0011_p2_statement_tables"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SOURCE_NAME = "Yahoo Finance"

data_sources_table = sa.table(
    "data_sources",
    sa.column("source_name", sa.Text),
    sa.column("base_url", sa.Text),
    sa.column("licence_type", sa.Text),
    sa.column("redistribution_allowed", sa.Boolean),
    sa.column("attribution_required", sa.Boolean),
    sa.column("attribution_text", sa.Text),
    sa.column("terms_url", sa.Text),
    sa.column("terms_reviewed_on", sa.Date),
    sa.column("reviewed_by", sa.Text),
    sa.column("rate_limit_per_sec", sa.Numeric),
    sa.column("notes", sa.Text),
)


def upgrade() -> None:
    op.create_table(
        "price_history",
        sa.Column("security_id", sa.Integer(), sa.ForeignKey("securities.id"), nullable=False),
        sa.Column("date", sa.Date(), nullable=False),
        sa.Column("open_raw", sa.Numeric(), nullable=True),
        sa.Column("high_raw", sa.Numeric(), nullable=True),
        sa.Column("low_raw", sa.Numeric(), nullable=True),
        sa.Column("close_raw", sa.Numeric(), nullable=False),  # AS TRADED. Never overwrite.
        sa.Column("volume", sa.BigInteger(), nullable=True),
        sa.Column("vwap", sa.Numeric(), nullable=True),
        sa.Column("halted", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("data_source_id", sa.Integer(), sa.ForeignKey("data_sources.id"), nullable=False),
        sa.Column(
            "source_document_id",
            sa.BigInteger(),
            sa.ForeignKey("source_documents.id"),
            nullable=False,
        ),
        sa.Column("known_as_of", sa.Date(), nullable=False),
        sa.PrimaryKeyConstraint("security_id", "date", "known_as_of"),
        sa.CheckConstraint("known_as_of >= date", name="price_history_pit_sanity"),
    )
    op.execute(
        "CREATE TRIGGER no_update BEFORE UPDATE ON price_history "
        "FOR EACH ROW EXECUTE FUNCTION forbid_update();"
    )

    connection = op.get_bind()
    already = connection.execute(
        sa.text("SELECT count(*) FROM data_sources WHERE source_name = :n"), {"n": SOURCE_NAME}
    ).scalar_one()
    if not already:
        op.bulk_insert(
            data_sources_table,
            [
                {
                    "source_name": SOURCE_NAME,
                    "base_url": "https://query2.finance.yahoo.com",
                    "licence_type": "personal_use_terms",
                    "redistribution_allowed": False,
                    "attribution_required": True,
                    "attribution_text": "Source: Yahoo Finance",
                    "terms_url": "https://legal.yahoo.com/us/en/yahoo/terms/otos/index.html",
                    "terms_reviewed_on": date(2026, 9, 13),
                    "reviewed_by": "nnatuanyafrankoguguo",
                    "rate_limit_per_sec": 1,
                    "notes": (
                        "Undocumented v8 chart endpoint (what yfinance uses); no contract, no "
                        "stability guarantee - DATA_FOUNDATION §C rates it fragile and fine for "
                        "personal US use. Historical OHLCV are split-adjusted retroactively; the "
                        "connector stores as-traded prices by reversing the provider's own split "
                        "ratios. Personal-use terms; redistribution not asserted. US only - no "
                        "reliable NGX coverage (DATA_FOUNDATION §C: AVOID for NGX)."
                    ),
                }
            ],
        )


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS no_update ON price_history;")
    op.drop_table("price_history")
    op.execute(data_sources_table.delete().where(data_sources_table.c.source_name == SOURCE_NAME))

"""0017 - fx_rates: a rate is a figure with two dates, and every conversion takes one. TG2.

Revision ID: 0017_tg2_fx_rates
Revises: 0016_p1_verified_staleness_lags
Create Date: 2026-09-16

`OPERATIONS.md` §1.3 and `docs/08` §2.4. The third of TG2's six correctness paths, after
corporate actions (0015) and fiscal alignment (P2's `normalize.periods`).

**Why this is not a nicety.** The official USD/NGN rate went from 907.1 at the end of 2023
to 1,535.0 at the end of 2024 - 69% in twelve months (`DATA_FOUNDATION.md` §3.3). A 2023
Naira figure converted at the 2024 rate is not off by a rounding error; it is off by a
multiple, and nothing raises. So the rate carries the date it was true of, the date it
became knowable, and `packages/common/fx.py` refuses to convert without a decision date -
a conversion function without a date parameter is a defect, in this project's own words.

**Shape.** `docs/08` §2.4's DDL, with two deviations this schema takes everywhere:

* `known_as_of` joins the primary key. `docs/08` keys on
  `(base, quote, rate_type, as_of_date)`, which makes a corrected rate an UPDATE - and an
  update to a figure is the thing the `no_update` trigger exists to prevent. A corrected
  rate is a second row, as it is for every other figure here.
* `source_document_id` is NOT NULL beside `data_source_id` (`docs/10` §2.13: provenance on
  every figure). The CBN's rates arrive in a stored response like everything else, and
  "which document said 1,535.0" must have an answer.

**Filled from the fetch that already happens.** `CbnExchangeRateConnector` reads the NFEM
central rate for the macro series `NG_FX_NFEM_USDNGN`; the same parsed records now also
land here, from the same response, with that response's document id. One fetch, one source,
two shapes: the macro series is the published indicator a dashboard plots, and `fx_rates` is
the substrate a conversion reads. Other rate types (`parallel`, `closing`,
`period_average`) have no source yet and no rows.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0017_tg2_fx_rates"
down_revision: str | None = "0016_p1_verified_staleness_lags"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "fx_rates",
        sa.Column("base_currency", sa.CHAR(3), nullable=False),
        sa.Column("quote_currency", sa.CHAR(3), nullable=False),
        # 'nfem_official'|'parallel'|'closing'|'period_average'
        sa.Column("rate_type", sa.Text(), nullable=False),
        sa.Column("as_of_date", sa.Date(), nullable=False),
        sa.Column("known_as_of", sa.Date(), nullable=False),
        # Quote units per one base unit: USD/NGN at 1535 means one dollar buys 1,535 naira.
        sa.Column("rate", sa.Numeric(), nullable=False),
        sa.Column("data_source_id", sa.Integer(), sa.ForeignKey("data_sources.id"), nullable=False),
        sa.Column(
            "source_document_id",
            sa.BigInteger(),
            sa.ForeignKey("source_documents.id"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint(
            "base_currency", "quote_currency", "rate_type", "as_of_date", "known_as_of"
        ),
        sa.CheckConstraint("rate > 0", name="fx_rate_positive"),
        sa.CheckConstraint("known_as_of >= as_of_date", name="fx_rates_pit_sanity"),
        sa.CheckConstraint("base_currency <> quote_currency", name="fx_rate_is_a_pair"),
    )
    op.create_index(
        "ix_fx_rates_lookup",
        "fx_rates",
        ["base_currency", "quote_currency", "rate_type", "as_of_date", "known_as_of"],
    )
    op.execute(
        "CREATE TRIGGER no_update BEFORE UPDATE ON fx_rates "
        "FOR EACH ROW EXECUTE FUNCTION forbid_update();"
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS no_update ON fx_rates;")
    op.drop_table("fx_rates")

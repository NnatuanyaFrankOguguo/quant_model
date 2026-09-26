"""0028 - indicators and scenarios: the two tables P6 fills. P6.1, P6.2, P6.3.

Revision ID: 0028_p6_indicators_scenarios
Revises: 0027_p5_ticker_tagging
Create Date: 2026-09-24

Both DDLs are taken from `docs/08` §2.7 and §2.9 rather than composed here, and the two
choices in them that look like decoration are the two that matter most.

## `price_series` is the phase's whole safety net

`docs/03` P6 marks exactly one risk 🔴 FRAGILE: indicators computed on unadjusted prices,
*"Silent; corrupts P8's entire feature set."* A 4-for-1 split leaves a 75% cliff in a raw
close series; RSI reads that as the most violent sell-off in the security's history, and
no downstream model can tell a clerical event from a market one.

`docs/08` §2.7 makes the defence structural: the column *"makes US-061's rule auditable in
the DATA, not only by a lint rule that cannot see rows already written."* A lint rule
constrains the code you run next. A column constrains the rows you already have - you can
ask the database which of them were built on raw prices, years later, and get an answer.
The CHECK is safe because the column is NOT NULL: a CHECK passes on a NULL predicate and
only rejects FALSE, which migration 0021 learned the hard way.

## `known_as_of` is in the primary key, and there is no result column

Two halves of the same rule.

For `indicators`, `known_as_of` in the key means recomputing after a price restatement
writes a *second* row rather than destroying the first - the silent overwrite
`docs/01` §6 forbids, in the tables most responsible for preventing it. The `no_update`
trigger from migration 0002 enforces what the key merely permits.

For `scenarios`, there is deliberately **no** stored result. `docs/03` P6's illustrative
sketch shows a `result_json`; `docs/08` §2.9's actual DDL does not, and carries
`inputs_as_of` with the note *"US-060: must reproduce identical output"* instead. A stored
answer is a single frozen vintage that goes quietly stale the moment a filing is restated,
and it would make P6 check 7 - "same assumptions produce identical output" - unfalsifiable,
because it would be comparing a cached answer with itself. Keeping the assumptions and the
as-of date, and recomputing, is what makes that check mean anything.

`code_version` on both: an answer produced by a version of the model that no longer exists
should say so rather than looking like one produced today.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "0028_p6_indicators_scenarios"
down_revision: str | None = "0027_p5_ticker_tagging"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "indicators",
        sa.Column("security_id", sa.Integer, sa.ForeignKey("securities.id"), nullable=False),
        sa.Column("date", sa.Date, nullable=False),
        # 'rsi14', 'macd_hist' - the indicator as a reader names it.
        sa.Column("name", sa.Text, nullable=False),
        # RSI-14 and RSI-21 are different features. Without this in the key one silently
        # overwrites the other and P8's feature matrix holds whichever ran last.
        sa.Column("param_hash", sa.Text, nullable=False),
        sa.Column("params", JSONB, nullable=False),
        # DOUBLE PRECISION per `docs/08` §1.5: statistical values only, where precision
        # loss is irrelevant and speed is not. A price is Numeric; an RSI is not a price.
        sa.Column("value", sa.Double, nullable=True),
        sa.Column("price_series", sa.Text, nullable=False),
        sa.Column("known_as_of", sa.Date, nullable=False),
        sa.Column(
            "computed_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("code_version", sa.Text, nullable=False),
        sa.PrimaryKeyConstraint(
            "security_id", "date", "name", "param_hash", "known_as_of", name="indicators_pkey"
        ),
        sa.CheckConstraint(
            "price_series IN ('adjusted', 'raw')", name="indicators_price_series_known"
        ),
        # An indicator cannot have been knowable before the bar it describes.
        sa.CheckConstraint("known_as_of >= date", name="indicators_pit_sanity"),
    )
    # The read pattern is "one indicator's series for one security", which the primary
    # key's (security_id, date, ...) prefix serves badly - it has to scan every name.
    op.create_index(
        "indicators_series_idx", "indicators", ["security_id", "name", "param_hash", "date"]
    )
    op.execute(
        """
        CREATE TRIGGER no_update BEFORE UPDATE ON indicators
          FOR EACH ROW EXECUTE FUNCTION forbid_update();
        """
    )

    op.create_table(
        "scenarios",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("principal_id", sa.Integer, sa.ForeignKey("principals.id"), nullable=False),
        sa.Column("security_id", sa.Integer, sa.ForeignKey("securities.id"), nullable=False),
        # 'bear', 'base', 'Naira at 2000' - the owner's word for it.
        sa.Column("name", sa.Text, nullable=False),
        # The complete user-supplied input set. Nothing the system chose belongs here:
        # `docs/03` P6.1 and SPEC T8 both forbid an auto-generated target.
        sa.Column("assumptions", JSONB, nullable=False),
        sa.Column("inputs_as_of", sa.Date, nullable=False),
        sa.Column("code_version", sa.Text, nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        # Per principal: P6 check 8 is that two principals' scenarios do not collide, and
        # "bear" means different things to different people.
        sa.UniqueConstraint("principal_id", "security_id", "name", name="scenarios_named_once"),
    )


def downgrade() -> None:
    op.drop_table("scenarios")
    op.execute("DROP TRIGGER IF EXISTS no_update ON indicators;")
    op.drop_index("indicators_series_idx", table_name="indicators")
    op.drop_table("indicators")

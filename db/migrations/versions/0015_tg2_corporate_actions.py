"""0015 - corporate_actions and adjustment_factors: the point-in-time adjustment. TG2, TG12.

Revision ID: 0015_tg2_corporate_actions
Revises: 0014_p2_entity_graph
Create Date: 2026-09-14

`docs/10` §2.6 raised TG12 to a blocker and moved these two tables to the P0 schema; they
land here, late, with the first source that can fill them - the split and dividend events
every stored Yahoo chart response already carries. `docs/08` §2.4 and `OPERATIONS.md` §1.1
are the contract; `docs/10` §2.13 adds the provenance columns.

**Why two tables.** A corporate action is a fact off a document: a 4-for-1 split with an
ex-date, a cash dividend per share. An adjustment factor is what that fact does to every
price *before* its ex-date. They are kept apart because the factor for a rights issue or a
dividend depends on a price as well as the action, and because the factor's own
`known_as_of` is the leak TG12 closes: an action *can* be announced after its ex-date, and
an adjusted series that embeds it before that day is lookahead.

**Per-action factors, never cumulative.** `docs/08` describes the column as a cumulative
multiplier. A stored cumulative product is a single global vintage - every new action would
rewrite every earlier row - which is the adjusted-column sin one level down. Each row here
is one action's own factor; the read function multiplies the factors whose ex-date is after
the bar and whose `known_as_of` is on or before the decision date. Same figures, no leak.

**Vintages.** `known_as_of` is in both unique keys, as on every figure table here: a
corrected ratio is a second row, never an edit, and the `no_update` trigger holds that
outside this code. `docs/08` wrote the actions' key without it; that is the one deviation,
and it is the rule every other table already follows.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0015_tg2_corporate_actions"
down_revision: str | None = "0014_p2_entity_graph"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "corporate_actions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("security_id", sa.Integer(), sa.ForeignKey("securities.id"), nullable=False),
        # 'split'|'bonus'|'rights'|'dividend'|'consolidation'
        sa.Column("action_type", sa.Text(), nullable=False),
        sa.Column("announcement_date", sa.Date(), nullable=True),
        sa.Column("ex_date", sa.Date(), nullable=False),  # the date that matters for adjustment
        sa.Column("record_date", sa.Date(), nullable=True),
        sa.Column("pay_date", sa.Date(), nullable=True),
        sa.Column("ratio_from", sa.Numeric(), nullable=True),  # split 1:2 -> from 1, to 2
        sa.Column("ratio_to", sa.Numeric(), nullable=True),
        sa.Column("cash_amount", sa.Numeric(), nullable=True),  # dividends: per share, gross
        sa.Column("subscription_price", sa.Numeric(), nullable=True),  # rights: for the TERP
        sa.Column("currency", sa.CHAR(3), nullable=True),
        sa.Column(
            "source_document_id",
            sa.BigInteger(),
            sa.ForeignKey("source_documents.id"),
            nullable=False,
        ),
        sa.Column("confidence", sa.Numeric(), nullable=True),
        sa.Column("needs_review", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("known_as_of", sa.Date(), nullable=False),
        sa.UniqueConstraint(
            "security_id", "ex_date", "action_type", "known_as_of", name="corporate_actions_vintage"
        ),
        sa.CheckConstraint(
            "action_type IN ('split','bonus','rights','dividend','consolidation')",
            name="corporate_actions_type",
        ),
        sa.CheckConstraint(
            "(action_type <> 'dividend') OR (cash_amount IS NOT NULL AND cash_amount >= 0)",
            name="dividend_has_an_amount",
        ),
        sa.CheckConstraint(
            "(action_type NOT IN ('split','bonus','consolidation')) "
            "OR (ratio_from > 0 AND ratio_to > 0)",
            name="ratio_action_has_a_ratio",
        ),
    )
    op.create_index(
        "ix_corporate_actions_security", "corporate_actions", ["security_id", "ex_date"]
    )
    op.execute(
        "CREATE TRIGGER no_update BEFORE UPDATE ON corporate_actions "
        "FOR EACH ROW EXECUTE FUNCTION forbid_update();"
    )

    op.create_table(
        "adjustment_factors",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("security_id", sa.Integer(), sa.ForeignKey("securities.id"), nullable=False),
        sa.Column("ex_date", sa.Date(), nullable=False),
        sa.Column("action_id", sa.Integer(), sa.ForeignKey("corporate_actions.id"), nullable=False),
        # This action's own multiplier for prices BEFORE ex_date. Never cumulative.
        sa.Column("factor", sa.Numeric(), nullable=False),
        # When this factor became knowable: an action announced after its ex-date is
        # exactly the leak this column closes (TG12).
        sa.Column("known_as_of", sa.Date(), nullable=False),
        # Provenance on every figure (`docs/10` §2.13): the document the action came from.
        sa.Column(
            "source_document_id",
            sa.BigInteger(),
            sa.ForeignKey("source_documents.id"),
            nullable=False,
        ),
        sa.UniqueConstraint(
            "security_id", "ex_date", "action_id", "known_as_of", name="adjustment_factors_vintage"
        ),
        sa.CheckConstraint("factor > 0", name="adjustment_factor_positive"),
    )
    op.create_index(
        "ix_adjustment_factors_security", "adjustment_factors", ["security_id", "ex_date"]
    )
    op.execute(
        "CREATE TRIGGER no_update BEFORE UPDATE ON adjustment_factors "
        "FOR EACH ROW EXECUTE FUNCTION forbid_update();"
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS no_update ON adjustment_factors;")
    op.drop_table("adjustment_factors")
    op.execute("DROP TRIGGER IF EXISTS no_update ON corporate_actions;")
    op.drop_table("corporate_actions")

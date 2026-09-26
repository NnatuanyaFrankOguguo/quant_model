"""0013 - shares_outstanding: the share count as of a date, with the vintage in the key. P2.4.

Revision ID: 0013_p2_shares_outstanding
Revises: 0012_p2_price_history
Create Date: 2026-09-13

`docs/08` §2.14 #49, raised by the owner on 2026-08-30: *without this, every P/E is silently
wrong.* A multiple needs the share count **as of the price date**. Bonus issues change the
denominator with no cash moving, so today's count against last year's price is a wrong
multiple that raises no error. `known_as_of` is in the primary key so a restated count is a
second row; `basic_or_diluted` is in it because both are published and a P/E must say which
it used. `source_document_id` NOT NULL and the `no_update` trigger, as on every other table
that holds a figure (`docs/10` §2.13–2.14).

Populated from EDGAR's cover-page count, `dei:EntityCommonStockSharesOutstanding`, which every
10-K and 10-Q carries with its own as-of date; Nigerian counts arrive with P3's manual
analyzer and P4's extraction.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0013_p2_shares_outstanding"
down_revision: str | None = "0012_p2_price_history"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "shares_outstanding",
        sa.Column("security_id", sa.Integer(), sa.ForeignKey("securities.id"), nullable=False),
        sa.Column("as_of_date", sa.Date(), nullable=False),
        sa.Column("shares", sa.Numeric(), nullable=False),  # never INT: bonus issues get large
        sa.Column("share_class", sa.Text(), nullable=False, server_default=sa.text("'ordinary'")),
        sa.Column("basic_or_diluted", sa.Text(), nullable=False),  # 'basic'|'diluted'
        sa.Column("known_as_of", sa.Date(), nullable=False),
        sa.Column(
            "source_document_id",
            sa.BigInteger(),
            sa.ForeignKey("source_documents.id"),
            nullable=False,
        ),
        sa.Column("page", sa.Integer(), nullable=True),
        sa.PrimaryKeyConstraint(
            "security_id", "as_of_date", "share_class", "basic_or_diluted", "known_as_of"
        ),
        sa.CheckConstraint("known_as_of >= as_of_date", name="shares_pit_sanity"),
        sa.CheckConstraint("shares > 0", name="shares_positive"),
    )
    op.execute(
        "CREATE TRIGGER no_update BEFORE UPDATE ON shares_outstanding "
        "FOR EACH ROW EXECUTE FUNCTION forbid_update();"
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS no_update ON shares_outstanding;")
    op.drop_table("shares_outstanding")

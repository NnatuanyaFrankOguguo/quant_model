"""0029 - news_sentiment and alert_deliveries: scoring a headline, and sending once. P5.3, P5.4.

Revision ID: 0029_p5_sentiment_deliveries
Revises: 0028_p6_indicators_scenarios
Create Date: 2026-09-24

`news_sentiment` is `docs/08` §2.6 unchanged. `alert_deliveries` is not, and the reason
is a conflict between three documents that cannot all be followed.

## The `alert_deliveries` conflict, and how it is resolved

`docs/03` P5.4 and `SPEC.md` T7 both require the daily brief to have **"idempotent
deliveries via `alert_deliveries` hash"** - in P5. `docs/08`'s table map row 40 assigns
that table to **P10**, and its DDL declares `alert_id INT NOT NULL REFERENCES alerts(id)`.
`alerts` is also P10, and does not exist. So P5.4 cannot be built as specified: there is
no alert row for a brief to point at, and there would not be one for five more phases.

`SPEC.md` §3.2's own DDL for the same table writes the column **nullable**
(`alert_id INT REFERENCES alerts(id)`), which is the shape that works.

**Decided: bring the table forward to P5 with `alert_id` nullable.** The argument is
about what a row asserts. A row here says *"this exact content went to this principal on
this channel, and must not go again"*. That claim is complete without an alert: the
idempotency hash is over the content, not over a rule. An alert rule is one reason to
send something; a scheduled brief is another; both need the same protection against a
retry after a network blip double-sending, which `docs/03` P5.4 names as "how a useful
bot becomes a muted one".

Making the column NOT NULL now would force one of two worse things: inventing a synthetic
`alerts` row per brief, which is a lie about why the message was sent, or building a
second near-identical `brief_deliveries` table, which puts the same invariant in two
places and lets them drift. P10 adds `alerts` and fills the column for rules that have
one; briefs leave it null, which is the honest reading of "this was not sent because of
a rule".

`docs/08` outranks `SPEC.md` in this project's precedence order, so this is a deliberate
departure rather than a reading of the stronger document, and it is recorded here for
that reason. The column is nullable and the FK is deferred to P10 along with `alerts`.

## `model_version` in the primary key

`docs/08` §2.6's note: *"re-scoring with a new model adds rows rather than destroying the
old scores, so you can compare."* That is the whole design, and it is what makes the
choice of scorer reversible - starting on VADER does not lock anything out, because
FinBERT later writes beside it rather than over it. The `no_update` trigger from
migration 0002 makes adding a row the only option rather than the polite one.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0029_p5_sentiment_deliveries"
down_revision: str | None = "0028_p6_indicators_scenarios"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "news_sentiment",
        sa.Column("news_id", sa.BigInteger, sa.ForeignKey("news_items.id"), nullable=False),
        # 'vader' | 'finbert' | 'claude-...'. The tier that produced the score.
        sa.Column("model", sa.Text, nullable=False),
        sa.Column("model_version", sa.Text, nullable=False),
        # -1..1. NUMERIC, not double: a score is compared for equality in tests and
        # displayed verbatim, and `docs/08` §1.5 reserves float for statistics.
        sa.Column("score", sa.Numeric, nullable=False),
        sa.Column("label", sa.Text, nullable=False),
        sa.Column("scored_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("news_id", "model", "model_version", name="news_sentiment_pkey"),
        sa.CheckConstraint("score >= -1 AND score <= 1", name="news_sentiment_score_in_range"),
        sa.CheckConstraint(
            "label IN ('positive', 'negative', 'neutral')", name="news_sentiment_label_known"
        ),
    )
    op.execute(
        """
        CREATE TRIGGER no_update BEFORE UPDATE ON news_sentiment
          FOR EACH ROW EXECUTE FUNCTION forbid_update();
        """
    )

    op.create_table(
        "alert_deliveries",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        # Nullable, and no foreign key yet - see the module docstring. P10 adds `alerts`
        # and the constraint; a brief has no rule behind it and says so by leaving this
        # null rather than by pointing at an invented one.
        sa.Column("alert_id", sa.Integer, nullable=True),
        sa.Column("principal_id", sa.Integer, sa.ForeignKey("principals.id"), nullable=False),
        # Over the *content*, which is what makes this work for a brief as well as an
        # alert: the same figures on the same morning hash the same however they were
        # triggered.
        sa.Column("idempotency_hash", sa.CHAR(64), nullable=False),
        sa.Column("channel", sa.Text, nullable=False),
        sa.Column("delivered_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("status", sa.Text, nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        # Per principal, not global: `CLAUDE.md` makes the brief per principal, built
        # from their watchlist, so two people can be sent the same content and neither
        # send suppresses the other.
        sa.UniqueConstraint("principal_id", "idempotency_hash", name="alert_deliveries_sent_once"),
        sa.CheckConstraint(
            "status IN ('pending', 'sent', 'failed', 'suppressed')",
            name="alert_deliveries_status_known",
        ),
        # A delivery that claims to have been sent must say when.
        sa.CheckConstraint(
            "(status <> 'sent') OR (delivered_at IS NOT NULL)",
            name="alert_deliveries_sent_has_a_time",
        ),
    )


def downgrade() -> None:
    op.drop_table("alert_deliveries")
    op.execute("DROP TRIGGER IF EXISTS no_update ON news_sentiment;")
    op.drop_table("news_sentiment")

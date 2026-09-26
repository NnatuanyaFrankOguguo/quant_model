"""0030 - why a sentiment score should or should not be believed. P5.3.

Revision ID: 0030_p5_sentiment_tier
Revises: 0029_p5_sentiment_deliveries
Create Date: 2026-09-24

`news_sentiment` as `docs/08` §2.6 specifies it stores a score and a label and nothing
about whether either is worth reading. On this corpus that is the wrong half.

Measured over the 44 Nigerian articles held, VADER scores **20 of them exactly 0.0000**,
and hand-checking says most of those are not neutral - they are unreadable. "NGX market
capitalization hits record N163.06tn as ASI rises 0.23%" scores 0.0000 because `record`,
`hits` and `rises` are all absent from the lexicon. "NTB stop rates crash after CBN's
350bps rate cut" scores -0.7184 off `stop`, `crash` and `cut`, when a falling auction
yield after a rate cut is not a crash. Stored bare, those two rows are indistinguishable
from a correct neutral and a correct negative.

So the tier is stored beside the score. `tier` is whether the lexicon was trusted;
`reason` is what decided it - `no_sentiment_words`, `clear`, `conflicting_words`,
`lexicon_gap`, `false_friend`, `name_in_lexicon`. A consumer can then ask for scores
VADER was competent to give rather than for all of them, which is the difference between
this table being useful and being actively misleading.

It is derived data and reproducible from the text, which is normally an argument against
storing it. The same argument was had and settled the other way for `indicators.params`
in migration 0028: *"a hash nobody can invert is not provenance"*. A score nobody can
judge is not evidence. Recomputing it also requires the exact lexicon build that produced
the row, which is precisely what will not be to hand in a year.

## `model_version` now carries the label band

Second, smaller, and a silent-failure path rather than a missing column.

`score` does not depend on the label band; `label` does. With `model_version` set to the
library version alone, changing `LABEL_BAND` changes what a label means while leaving the
primary key identical - so the re-score inserts nothing (`ON CONFLICT DO NOTHING`), the
`no_update` trigger forbids the alternative, and **the old label silently survives the
new rule**. Folding the band into the version makes `(model, model_version)` identify the
whole function from text to (score, label), which is what a version is for.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0030_p5_sentiment_tier"
down_revision: str | None = "0029_p5_sentiment_deliveries"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_REASONS = (
    "no_sentiment_words",
    "clear",
    "conflicting_words",
    "lexicon_gap",
    "false_friend",
    "name_in_lexicon",
)


def upgrade() -> None:
    # No server_default and no backfill: the table is empty. A default would let a future
    # writer omit the column and have the row claim a tier nobody decided.
    op.add_column("news_sentiment", sa.Column("tier", sa.Text, nullable=False))
    op.add_column("news_sentiment", sa.Column("reason", sa.Text, nullable=False))
    op.create_check_constraint(
        "news_sentiment_tier_known", "news_sentiment", "tier IN ('bulk', 'ambiguous')"
    )
    reasons = ", ".join(f"'{reason}'" for reason in _REASONS)
    op.create_check_constraint(
        "news_sentiment_reason_known", "news_sentiment", f"reason IN ({reasons})"
    )
    # The two are not independent: `clear` and `no_sentiment_words` are the lexicon being
    # trusted, and the other four are it not being. A row saying "ambiguous because the
    # reading was clear" is a bug in the router, and the database should not hold it.
    op.create_check_constraint(
        "news_sentiment_tier_matches_reason",
        "news_sentiment",
        "(tier = 'bulk') = (reason IN ('clear', 'no_sentiment_words'))",
    )


def downgrade() -> None:
    op.drop_constraint("news_sentiment_tier_matches_reason", "news_sentiment")
    op.drop_constraint("news_sentiment_reason_known", "news_sentiment")
    op.drop_constraint("news_sentiment_tier_known", "news_sentiment")
    op.drop_column("news_sentiment", "reason")
    op.drop_column("news_sentiment", "tier")

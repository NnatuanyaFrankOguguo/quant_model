"""0021 - a ratio action must actually carry a ratio. TG2.

Revision ID: 0021_p3_ratio_action_not_null
Revises: 0020_p3_chart_v1
Create Date: 2026-09-17

Migration `0015` gave `corporate_actions` a constraint meant to guarantee that a split, a
bonus issue or a consolidation carries the ratio the adjustment is computed from:

    CHECK (action_type <> ALL (ARRAY['split','bonus','consolidation'])
           OR (ratio_from > 0 AND ratio_to > 0))

It does not do that. A CHECK constraint rejects a row only when its predicate evaluates to
**FALSE**; a predicate that evaluates to NULL passes. For a split with no ratio at all,
`ratio_from > 0` is NULL, so the second branch is NULL, `FALSE OR NULL` is NULL, and the row
is accepted. Verified against the live constraint before writing this:

| `action_type` | `ratio_from` | `ratio_to` | predicate | outcome |
|---|---|---|---|---|
| split | NULL | NULL | NULL | **accepted** |
| bonus | NULL | 5 | NULL | **accepted** |
| split | 0 | 2 | FALSE | rejected |
| split | 1 | 2 | TRUE | accepted |

So the constraint catches a *zero* ratio and misses a *missing* one, which is the wrong way
round: zero is a typo somebody will notice, and NULL is the one that stays quiet.

**Why quiet matters here.** `packages/ingestion/yahoo.py` writes an `adjustment_factors` row
only when both ratios are present. A split stored with NULL ratios therefore produces no
factor, `adjusted_close` finds nothing to apply, and the series keeps the full artificial
step across the ex-date. Nothing errors. `docs/03` names this exact bug class - *"corporate
actions later, no splits recently"* - as *"the one bug class that is invisible until P7
reports a strategy that never existed"*, and `OPERATIONS.md` §1.1 opens by calling corporate
actions the highest-priority gap in the project.

The evidence that this was an oversight rather than a decision is one line further down the
same migration: `dividend_has_an_amount` spells out `cash_amount IS NOT NULL AND
cash_amount >= 0`. The author knew the NULL case needed saying and said it for dividends.

No existing row is affected - every one of the 138 ratio actions in the table carries both
ratios, checked before this ran - so the constraint is replaced rather than the data being
repaired. Found by writing `tests/unit/test_corporate_actions.py`, the file `docs/03` P3
check 4 names and which did not exist.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0021_p3_ratio_action_not_null"
down_revision: str | None = "0020_p3_chart_v1"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

CONSTRAINT = "ratio_action_has_a_ratio"
RATIO_TYPES = "('split','bonus','consolidation')"


def upgrade() -> None:
    op.drop_constraint(CONSTRAINT, "corporate_actions", type_="check")
    op.create_check_constraint(
        CONSTRAINT,
        "corporate_actions",
        # `IS NOT NULL` first, so the predicate is FALSE rather than NULL for a missing
        # ratio. Without it the comparisons alone leave the row accepted.
        f"action_type NOT IN {RATIO_TYPES} OR ("
        "ratio_from IS NOT NULL AND ratio_to IS NOT NULL "
        "AND ratio_from > 0 AND ratio_to > 0)",
    )


def downgrade() -> None:
    op.drop_constraint(CONSTRAINT, "corporate_actions", type_="check")
    op.create_check_constraint(
        CONSTRAINT,
        "corporate_actions",
        f"action_type NOT IN {RATIO_TYPES} OR (ratio_from > 0 AND ratio_to > 0)",
    )

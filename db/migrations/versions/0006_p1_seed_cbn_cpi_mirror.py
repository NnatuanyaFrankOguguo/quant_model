"""0006 - two CBN-attributed CPI mirror series.

Revision ID: 0006_p1_seed_cbn_cpi_mirror
Revises: 0005_p1_seed_macro_series
Create Date: 2026-09-08

Nigeria's CPI is compiled and published by the **NBS**. CBN republishes it, and CBN is the
source we can currently reach programmatically. These two rows are where those republished
figures land.

**Why not simply fill `NG_CPI_YOY`.** Attribution shown to a reader comes from the series'
`data_source_id`, so putting CBN-fetched bytes into an NBS-attributed series would print
"Source: National Bureau of Statistics" over data we actually took from CBN. The licensing
register that governs *our copy* would also be the wrong row. `docs/10` §6.1 and migration
0005 already set this precedent with the World Bank mirror, and the same reasoning applies
with more force here, because these numbers will be read far more often.

**The gap this deliberately leaves visible.** `NG_CPI_YOY` and `NG_CPI_CORE` stay empty until
an NBS path exists — the manual CSV route (P1.7) today, a connector later. `docs/03` P1.3
warns against "a Nigerian macro dashboard whose Nigerian sources are all second-hand"; an
empty primary series next to a populated mirror is what keeps that warning legible instead of
quietly satisfied.

`expected_lag_days` is 40, not 25: these are the *mirror's* figures, and CBN republishes after
NBS releases, so the mirror is legitimately later than the primary. Still
[NEEDS VERIFICATION] — see `docs/REVIEW_CADENCE.md` row 3.

`downgrade()` deletes exactly the two codes inserted here.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

import sqlalchemy as sa
from alembic import op

revision: str = "0006_p1_seed_cbn_cpi_mirror"
down_revision: str | None = "0005_p1_seed_macro_series"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


macro_series_table = sa.table(
    "macro_series",
    sa.column("code", sa.Text),
    sa.column("name", sa.Text),
    sa.column("data_source_id", sa.Integer),
    sa.column("unit", sa.Text),
    sa.column("frequency", sa.Text),
    sa.column("expected_lag_days", sa.Integer),
    sa.column("base_period", sa.Text),
    sa.column("seasonal_adjustment", sa.Text),
)

SEED_ROWS: list[dict[str, Any]] = [
    {
        "code": "NG_CPI_YOY_CBN",
        "name": "Nigeria headline CPI, year-on-year (CBN mirror of NBS)",
        "unit": "percent",
        "frequency": "monthly",
        "expected_lag_days": 40,
        "base_period": "CPI 2024=100",
        "seasonal_adjustment": "none",
    },
    {
        "code": "NG_CPI_CORE_CBN",
        "name": "Nigeria core CPI y/y, all items less farm produce and energy (CBN mirror)",
        "unit": "percent",
        "frequency": "monthly",
        "expected_lag_days": 40,
        "base_period": "CPI 2024=100",
        "seasonal_adjustment": "none",
    },
]


def upgrade() -> None:
    connection = op.get_bind()
    cbn_id = connection.execute(
        sa.text("SELECT id FROM data_sources WHERE source_name = 'CBN'")
    ).scalar_one_or_none()
    if cbn_id is None:
        raise RuntimeError("data_sources has no CBN row; migration 0004 must run first")
    op.bulk_insert(
        macro_series_table,
        [{**row, "data_source_id": cbn_id} for row in SEED_ROWS],
    )


def downgrade() -> None:
    codes = [row["code"] for row in SEED_ROWS]
    op.execute(macro_series_table.delete().where(macro_series_table.c.code.in_(codes)))

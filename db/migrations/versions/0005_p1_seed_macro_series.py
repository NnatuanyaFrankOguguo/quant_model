"""0005 - seed `macro_series`, the P1 starting series list.

Revision ID: 0005_p1_seed_macro_series
Revises: 0004_p0_seed_data_sources
Create Date: 2026-09-03

`docs/03_ROADMAP_PART1_PHASES_0-6.md` P1 makes "decide the starting series list" a
**blocking** manual task — you cannot build a dashboard without knowing what goes on it —
and gives a concrete list of ten. This migration is that decision, recorded where the code
can read it rather than in a comment.

Eleven rows, not ten: `NG_CPI_YOY_WB` is FRED's World Bank *mirror* of Nigerian CPI, kept
deliberately separate from `NG_CPI_YOY`, which is NBS's own figure. They are not the same
series — the mirror is annual, lags badly, and is second-hand. Collapsing them into one code
would let a stale mirror value silently stand in for the real thing, and "a Nigerian macro
dashboard whose Nigerian sources are all second-hand" is precisely the weakness the product
exists to fix.

A series is created only where a source exists to fill it: series with no connector yet
(MPR, FX, GDP, debt, bond stop rates) are fed by the manual CSV path (P1.7) until CBN
scraping lands. That is the intended state, not a gap — the human is the guaranteed path.

⚠️ **`expected_lag_days` on every row is [NEEDS VERIFICATION].** It drives the staleness flag
(`docs/08` §2.5), so a wrong value here makes the dashboard either cry wolf or stay silent
when data has genuinely stopped arriving. The values below are reasoned from each agency's
observed publication rhythm as described in `DATA_FOUNDATION.md` Part 2, **not** from a
published release calendar. Row 3 of `docs/REVIEW_CADENCE.md` owns correcting them against
the agencies' own calendars, and that sweep has not happened.

`base_period` matters and is not decoration: Nigerian CPI was rebased to a 2024 base and GDP
to 2019, and **rebasing changes past values**. A series whose base changed is a different
series; the column is what makes that visible rather than a mysterious level shift.

`downgrade()` deletes exactly the eleven codes inserted here.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

import sqlalchemy as sa
from alembic import op

revision: str = "0005_p1_seed_macro_series"
down_revision: str | None = "0004_p0_seed_data_sources"
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

# (code, name, source_name, unit, frequency, expected_lag_days, base_period, seasonal_adj)
SEED_ROWS: list[dict[str, Any]] = [
    {
        "code": "NG_CPI_YOY",
        "name": "Nigeria headline CPI, year-on-year",
        "source_name": "NBS",
        "unit": "percent",
        "frequency": "monthly",
        "expected_lag_days": 25,  # published ~mid-month for the prior month
        "base_period": "CPI 2024=100",
        "seasonal_adjustment": "none",
    },
    {
        "code": "NG_CPI_CORE",
        "name": "Nigeria core CPI, year-on-year (excl. food and energy)",
        "source_name": "NBS",
        "unit": "percent",
        "frequency": "monthly",
        "expected_lag_days": 25,
        "base_period": "CPI 2024=100",
        "seasonal_adjustment": "none",
    },
    {
        "code": "NG_MPR",
        "name": "Nigeria Monetary Policy Rate (CBN)",
        "source_name": "CBN",
        "unit": "percent",
        # Set by the MPC, roughly six times a year, and unchanged between meetings. Not a
        # periodic series: 'irregular' stops a staleness check from flagging a rate that is
        # simply the same as last month because nobody changed it.
        "frequency": "irregular",
        "expected_lag_days": 90,
        "base_period": None,
        "seasonal_adjustment": None,
    },
    {
        "code": "NG_FX_NFEM_USDNGN",
        "name": "NFEM official FX rate, USD/NGN",
        "source_name": "CBN",
        "unit": "ngn_per_usd",
        "frequency": "daily",
        "expected_lag_days": 4,  # allows a long weekend plus a public holiday
        "base_period": None,
        "seasonal_adjustment": None,
    },
    {
        "code": "NG_GDP_GROWTH_YOY",
        "name": "Nigeria real GDP growth, year-on-year",
        "source_name": "NBS",
        "unit": "percent",
        "frequency": "quarterly",
        "expected_lag_days": 100,
        "base_period": "GDP 2019 rebasing",
        "seasonal_adjustment": "none",
    },
    {
        "code": "NG_PUBLIC_DEBT_TOTAL",
        "name": "Nigeria total public debt stock",
        "source_name": "DMO",
        "unit": "ngn_billions",
        "frequency": "quarterly",
        "expected_lag_days": 100,
        "base_period": None,
        "seasonal_adjustment": None,
    },
    {
        "code": "NG_FGN_BOND_STOP_RATE",
        "name": "FGN bond auction stop rate (10-year benchmark)",
        "source_name": "DMO",
        "unit": "percent",
        "frequency": "monthly",
        "expected_lag_days": 45,
        "base_period": None,
        "seasonal_adjustment": None,
    },
    {
        "code": "US_FED_FUNDS",
        "name": "US federal funds effective rate",
        "source_name": "FRED",
        "unit": "percent",
        "frequency": "monthly",
        "expected_lag_days": 10,
        "base_period": None,
        "seasonal_adjustment": "none",
    },
    {
        "code": "US_CPI_INDEX",
        "name": "US CPI for all urban consumers (index)",
        "source_name": "FRED",
        "unit": "index",
        "frequency": "monthly",
        "expected_lag_days": 20,
        "base_period": "CPI 1982-84=100",
        "seasonal_adjustment": "seasonally_adjusted",
    },
    {
        "code": "US_10Y_TREASURY",
        "name": "US 10-year Treasury constant maturity rate",
        "source_name": "FRED",
        "unit": "percent",
        "frequency": "daily",
        "expected_lag_days": 4,
        "base_period": None,
        "seasonal_adjustment": None,
    },
    {
        "code": "NG_CPI_YOY_WB",
        "name": "Nigeria headline CPI, year-on-year (World Bank mirror via FRED)",
        "source_name": "FRED",
        "unit": "percent",
        # Annual and badly lagged. It exists so the FRED connector has somewhere to put
        # FPCPITOTLZGNGA, and as a cross-check on NBS — never as a substitute for it.
        "frequency": "annual",
        "expected_lag_days": 400,
        "base_period": None,
        "seasonal_adjustment": "none",
    },
]


def _source_ids(connection: sa.Connection) -> dict[str, int]:
    rows = connection.execute(sa.text("SELECT source_name, id FROM data_sources")).all()
    return {name: source_id for name, source_id in rows}


def upgrade() -> None:
    connection = op.get_bind()
    ids = _source_ids(connection)
    missing = sorted({r["source_name"] for r in SEED_ROWS} - set(ids))
    if missing:
        # Fail rather than skip. A macro_series row with no data_source_id is unreachable,
        # and silently seeding fewer series than intended is the kind of gap that surfaces
        # as "why is the dashboard missing MPR" three phases later.
        raise RuntimeError(f"data_sources is missing {missing}; migration 0004 must run first")
    op.bulk_insert(
        macro_series_table,
        [
            {
                "code": row["code"],
                "name": row["name"],
                "data_source_id": ids[row["source_name"]],
                "unit": row["unit"],
                "frequency": row["frequency"],
                "expected_lag_days": row["expected_lag_days"],
                "base_period": row["base_period"],
                "seasonal_adjustment": row["seasonal_adjustment"],
            }
            for row in SEED_ROWS
        ],
    )


def downgrade() -> None:
    codes = [row["code"] for row in SEED_ROWS]
    op.execute(macro_series_table.delete().where(macro_series_table.c.code.in_(codes)))

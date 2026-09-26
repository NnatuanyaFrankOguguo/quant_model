"""0016 - expected_lag_days, verified against our own vintages. Closes 0005's NEEDS VERIFICATION.

Revision ID: 0016_p1_verified_staleness_lags
Revises: 0015_tg2_corporate_actions
Create Date: 2026-09-16

Migration 0005 seeded `expected_lag_days` on every series and said so plainly: the values
were *reasoned from each agency's rhythm, not from a published calendar*, flagged
[NEEDS VERIFICATION], and owned by row 3 of `docs/REVIEW_CADENCE.md`. The sweep had not
happened. On 2026-09-15 the operator checked the macro dashboard by eye and found the
staleness flags crying wolf: three series were marked overdue although the source had
published nothing newer.

**The bug is in what the number has to cover.** `packages.ingestion.macro._staleness`
compares `expected_lag_days` against `today - latest_as_of` - the age of the newest *period
we hold*, not the age of the last publication. Just before a release, that age is always a
whole period plus the publisher's lag: on 2026-09-16 the newest US CPI period is 2026-08-01,
46 days old, and entirely on time, because September's figure is not due until mid-October.
A threshold set to the publication lag alone (20 days) therefore flags every healthy series
for the second half of every cycle. The threshold must be **one period + the publication
lag**, and that is what this migration sets.

The lags are measured, not assumed - from the first `known_as_of` of every period we hold,
over the last six years:

| series | frequency | observed lag (p90 / max) | period | set to |
|---|---|---|---|---|
| `US_CPI_INDEX` | monthly | 44 / 78 | 31 | 80 |
| `US_FED_FUNDS` | monthly | 33 / 34 | 31 | 70 |
| `NG_CPI_YOY` | monthly | 31 / 31 | 31 | 70 |
| `NG_CPI_YOY_CBN` | monthly | 31 (current cadence) | 31 | 70 |
| `NG_CPI_CORE_CBN` | monthly | 31 (current cadence) | 31 | 70 |
| `NG_GDP_GROWTH_YOY` | quarterly | 92 / 92 | 92 | 195 |
| `NG_CPI_YOY_WB` | annual | 552 / 552 | 365 | 930 |
| `US_10Y_TREASURY` | daily | 3 / 6 | 1 | 5 |
| `NG_FX_NFEM_USDNGN` | daily | 0 / 0 | 1 | 5 |

Two more carry no observations yet, so there is nothing to measure and these two values are
*reasoned from the agency's cadence*, exactly as 0005's were - but they at least clear a
whole period, which is the failure this migration is about. A test
(`test_every_threshold_leaves_room_for_a_period_and_its_publication_lag`) now holds the rule
for every series, which is how both of these were found:

| series | frequency | reasoning | period | set to |
|---|---|---|---|---|
| `NG_CPI_CORE` | monthly | NBS core CPI, released with the headline | 31 | 70 |
| `NG_PUBLIC_DEBT_TOTAL` | quarterly | DMO publishes a quarter or so in arrears | 92 | 195 |

`NG_FGN_BOND_STOP_RATE` is left at 45: monthly, and the DMO publishes auction results within
days, so 45 already clears a period with a fortnight to spare.

Two notes on judgement, because widening a staleness threshold is how a system learns to
stay quiet about real failures:

* **The daily series are tightened, not widened** (4 -> 5 only to cover a holiday weekend:
  Friday's figure read on a Tuesday after a Monday holiday is 4 days old and healthy). The
  US 10-year is 6 days stale as this lands - a real gap, from FRED jobs missed while the
  laptop slept - and it stays flagged, which is the point.
* **The CBN CPI mirrors' average lag is 124 days**, far above the 31 used here. That average
  is the 2025 revision episode (P1 check 12): NBS republished old months, and those rows
  carry a large as-of-to-known gap by construction. The *current* cadence is one month -
  July 2026 published 2026-08-31 - and that is what a freshness flag must judge.

After this, three series stay flagged and all three are genuine: NBS headline CPI (290 days,
the portal has published nothing since November 2025), Nigerian GDP (716 days, stopped at
Q3 2024), and the US 10-year (the missed run above). `NG_MPR` is `irregular` and is never
judged stale by the rule; the three manual-upload series hold no data and report "cannot
judge" rather than "fresh", which migration 0005 got right.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0016_p1_verified_staleness_lags"
down_revision: str | None = "0015_tg2_corporate_actions"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

#: code -> (verified, as seeded by 0005). The second value is what `downgrade()` restores.
LAGS: dict[str, tuple[int, int]] = {
    "US_CPI_INDEX": (80, 20),
    "US_FED_FUNDS": (70, 10),
    "NG_CPI_YOY": (70, 25),
    "NG_CPI_YOY_CBN": (70, 40),
    "NG_CPI_CORE_CBN": (70, 40),
    "NG_GDP_GROWTH_YOY": (195, 100),
    "NG_CPI_YOY_WB": (930, 400),
    "US_10Y_TREASURY": (5, 4),
    "NG_FX_NFEM_USDNGN": (5, 4),
    # No observations yet: reasoned from cadence, not measured.
    "NG_CPI_CORE": (70, 25),
    "NG_PUBLIC_DEBT_TOTAL": (195, 100),
}


def _apply(index: int) -> None:
    for code, values in LAGS.items():
        op.execute(
            sa.text(
                "UPDATE macro_series SET expected_lag_days = :days WHERE code = :code"
            ).bindparams(days=values[index], code=code)
        )


def upgrade() -> None:
    _apply(0)


def downgrade() -> None:
    _apply(1)

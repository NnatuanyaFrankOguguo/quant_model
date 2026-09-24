"""0024 - the cadence a heartbeat can be measured against. `docs/10` §5.3.

Revision ID: 0024_p3_heartbeat_interval
Revises: 0023_p3_trading_calendar
Create Date: 2026-09-24

`docs/10` §5.3 states the defect in one sentence: *"That query only sees runs that
**happened**. A connector the scheduler stopped launching writes no row, and the query
returns empty - indistinguishable from healthy."*

`packages/scheduler/runner.py:check_health` is the code it describes. It groups
`connector_runs` by `connector_name`, so a connector that stopped being launched contributes
no group, appears in no row of the report, and its silence is rendered as nothing at all.
Every detector downstream of that query inherits the blind spot, which is why §5.3 notes that
a search for "heartbeat", "dead man" or "last_success" across all sixteen planning documents
returned zero hits.

A heartbeat runs the query in the other direction: it starts from the register of sources we
*expect* to hear from and looks for evidence of each, so absence has something to be absent
*from*. That needs one number the schema did not carry - how long a gap is too long - and
this migration adds it.

## Why `macro_series.expected_lag_days` is not that number

`02 §8` claims the freshness monitor already covers this. It does not. `expected_lag_days`
measures how late a *publisher* is with a figure, it exists only for macro series, and
`docs/10` §5.6 spells out the consequence: *"NGX prices, EDGAR, RSS and the extraction
pipeline have no overdue concept at all."* A source can be perfectly fresh by that measure
while the job that fetches it has not been launched since a Windows Update disabled the
scheduled task.

## Where the numbers below come from

Read off `packages/scheduler/jobs.py:build_jobs`, not chosen. Every job it builds is a daily
cron - `CronTrigger(hour=..., minute=...)` with no day restriction - so the expected gap
between runs is 24 hours for every scheduled source: CBN from 05:30, the Nigeria Data Portal
from 06:05, FRED from 06:15, Yahoo after the US close from 22:30, EDGAR from 03:00. The
stored value is 26 rather than 24 because a deadline equal to the period fires on every
ordinary jitter; 26 is the same two-hour grace `scripts/backup.ps1` §8 already uses for its
healthchecks.io check, which `docs/10` §5.3 specifies as *"grace 26h"*.

NBS and the DMO are fed only by `packages/ingestion/manual_csv.py`, which a human runs.
`packages/scheduler/jobs.py:expected_schedule` gives those paths `MONTHLY_DAYS` (45), so
their interval is 45 × 24 = 1080 hours. Late is a reminder there, not an outage.

**Deliberately not `ScheduledJob.publishes_every_days`.** That field answers a different
question - how often the *source* publishes something new, which is what decides whether a
zero-row run is a quiet day or a silent failure. EDGAR carries 185 there because a company
files quarterly; its job still runs every night. Using 185 as EDGAR's heartbeat would let the
nightly refresh stop for half a year without a word, which is precisely the failure this
column exists to catch.

## NULL means unmonitored, and it is a statement rather than a default

Two seeded sources are left NULL on purpose. **NGX** has no connector at all - P2 prices come
from Yahoo - so there is no run whose absence could mean anything. **Issuer report (operator
upload)** is ad-hoc by construction (`0022`): a person uploads an annual report when one is
published, and inventing a cadence for that would manufacture an alert with no underlying
expectation.

NULL is therefore *"nothing is watching this"*, not *"assume it is fine"*.
`scripts/check_heartbeat.py` prints every NULL row by name in its own section on every run
and fails on them under `--strict`, so the gap is visible rather than silent - the whole
complaint of §5.3 being that an unmonitored thing reads exactly like a healthy one.

## The downgrade

`op.drop_column` is the honest inverse here, and it does not contradict `docs/10` §5.6's
*"dropping a column is three revisions across three phases"*. That rule protects columns
holding irreplaceable figures. This one holds seven integers that this migration itself wrote
and that `scripts/check_heartbeat.py` can re-derive from the schedule, so the only thing a
downgrade discards is a setting - and leaving a column behind that `upgrade()` would then try
to add again is a migration that cannot be replayed.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0024_p3_heartbeat_interval"
down_revision: str | None = "0023_p3_trading_calendar"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLE = "data_sources"
COLUMN = "expected_run_interval_hours"
CONSTRAINT = "heartbeat_interval_is_positive"

#: A daily cron plus the two-hour grace `backup.ps1` and `docs/10` §5.3 both already use.
DAILY_HOURS = 26

#: `packages/scheduler/jobs.py:MONTHLY_DAYS` (45), in hours - the cadence `expected_schedule`
#: gives the manual CSV paths. A month plus slack, because a human does the uploading.
MANUAL_MONTHLY_HOURS = 45 * 24

#: `data_sources.source_name` → hours. Names are the seeded register rows (`0004`, `0007`,
#: `0012`, `0022`); the sources fed by a scheduled job are read off `build_jobs()`. A name
#: absent from `data_sources` simply updates nothing, so this stays replayable.
INTERVAL_HOURS: dict[str, int] = {
    "CBN": DAILY_HOURS,  # cbn_fx 05:30, cbn_mpr 05:45, cbn_inflation 06:00, manual_csv_cbn
    "Nigeria Data Portal": DAILY_HOURS,  # ndp:<item> from 06:05, ndp:gdp after them
    "FRED": DAILY_HOURS,  # fred:<series> from 06:15, five minutes apart
    "Yahoo Finance": DAILY_HOURS,  # yahoo:<ticker> from 22:30, after the US close
    "SEC EDGAR": DAILY_HOURS,  # edgar:<ticker> from 03:00, six minutes apart
    "NBS": MANUAL_MONTHLY_HOURS,  # manual_csv_nbs only - no scheduled job reaches the NBS
    "DMO": MANUAL_MONTHLY_HOURS,  # manual_csv_dmo only; scripts/collect_dmo.py records no run
}


def upgrade() -> None:
    op.add_column(TABLE, sa.Column(COLUMN, sa.Integer(), nullable=True))
    # `IS NULL OR > 0`, never a bare `> 0`: migration 0021 is this repository's record of a
    # CHECK that let every NULL through because a NULL predicate is not FALSE. Here NULL is a
    # legitimate value, so it is admitted explicitly and zero or negative is not.
    op.create_check_constraint(CONSTRAINT, TABLE, f"{COLUMN} IS NULL OR {COLUMN} > 0")
    connection = op.get_bind()
    for source_name, hours in INTERVAL_HOURS.items():
        # A name that is not in the register updates nothing, so this stays replayable
        # against a database seeded by any subset of 0004 / 0007 / 0012 / 0022.
        connection.execute(
            sa.text(f"UPDATE {TABLE} SET {COLUMN} = :hours WHERE source_name = :source_name"),
            {"hours": hours, "source_name": source_name},
        )


def downgrade() -> None:
    # The constraint goes with the column in PostgreSQL, but dropping it by name first keeps
    # the inverse readable and does not depend on that behaviour.
    op.drop_constraint(CONSTRAINT, TABLE, type_="check")
    op.drop_column(TABLE, COLUMN)

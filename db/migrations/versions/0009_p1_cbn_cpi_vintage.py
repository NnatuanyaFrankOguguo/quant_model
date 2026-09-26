"""0009 - re-date the CBN CPI mirror's 2025 rows to the vintage they actually are.

Revision ID: 0009_p1_cbn_cpi_vintage
Revises: 0008_p1_gdp_base_period
Create Date: 2026-09-12

P1 checkpoint 12 — reconcile one figure against its release — found that `NG_CPI_YOY_CBN`
and `NG_CPI_YOY` disagree by about three points on every month they share. Both are NBS
figures. They are different **vintages**: in its December 2025 CPI report (published
mid-January 2026) NBS moved the year-on-year reference from a single month to the 2024
twelve-month average and revised every 2025 print upward — February 23.18% became 26.27%,
November 14.45% became 17.33%. CBN's endpoint carries only the revised series; the Nigeria
Data Portal froze on the originals.

`CbnInflationConnector` bounded every month's `known_as_of` at the end of the following
month, which is right for a first print and wrong for a revision. The twenty rows this
migration touches — headline and core, February to November 2025 — say that 26.27% was
knowable on 2025-03-31. It was not: the market had 23.18% until January 2026. Left as they
are, a P7 backtest deciding in spring 2025 would discount at a rate nobody had published.
`SPEC.md` §4.1: point-in-time only.

**Why delete-and-insert, in a schema that forbids updates.** `known_as_of` is part of the
primary key, and migration 0002's `no_update` trigger forbids UPDATE on this table so that a
revision is always a new row. That rule protects *source* figures from being edited; what
changes here is our own bound on knowability, and the value, the source document and the
period are carried across untouched. Inserting the re-dated rows *beside* the old ones would
leave the old rows still asserting the false date, and the point-in-time query would still
pick them up. The connector now emits these periods with the corrected bound and
`revision = 2`, so its next run is a no-op against the rows written here.

`downgrade()` reverses exactly this: the same twenty periods go back to the following-month
bound and `revision = 1`.

Nothing here touches `NG_CPI_YOY`. The original prints are the correct vintage for their
dates, and the revised NBS series can only enter an NBS-attributed series from an NBS
publication — P1.7's manual CSV path, fed from the December 2025 report itself.
"""

from __future__ import annotations

import calendar
import datetime as dt
from collections.abc import Callable, Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0009_p1_cbn_cpi_vintage"
down_revision: str | None = "0008_p1_gdp_base_period"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

MIRROR_SERIES = ("NG_CPI_YOY_CBN", "NG_CPI_CORE_CBN")
REVISED_FIRST = dt.date(2025, 1, 31)
REVISED_LAST = dt.date(2025, 11, 30)
REVISION_PUBLISHED_BY = dt.date(2026, 1, 31)

_SELECT = sa.text(
    """
    SELECT o.series_id, o.as_of_date, o.known_as_of, o.value, o.revision, o.source_document_id
    FROM macro_observations o
    JOIN macro_series s ON s.id = o.series_id
    WHERE s.code = ANY(:codes)
      AND o.as_of_date BETWEEN :first AND :last
      AND o.known_as_of = :known_as_of_matches
      AND o.revision = :revision_matches
    """
)
_DELETE = sa.text(
    "DELETE FROM macro_observations "
    "WHERE series_id = :series_id AND as_of_date = :as_of_date AND known_as_of = :known_as_of"
)
_INSERT = sa.text(
    "INSERT INTO macro_observations "
    "(series_id, as_of_date, known_as_of, value, revision, source_document_id) "
    "VALUES (:series_id, :as_of_date, :known_as_of, :value, :revision, :source_document_id) "
    "ON CONFLICT DO NOTHING"
)


def _end_of_following_month(period_end: dt.date) -> dt.date:
    year = period_end.year + (1 if period_end.month == 12 else 0)
    month = 1 if period_end.month == 12 else period_end.month + 1
    return dt.date(year, month, calendar.monthrange(year, month)[1])


def _redate(*, to_revision: int, new_known_as_of: Callable[[dt.date], dt.date]) -> None:
    """Move every matching row to a new `(known_as_of, revision)`, value and document intact."""
    connection = op.get_bind()
    from_revision = 1 if to_revision == 2 else 2
    # Selecting rows one period at a time keeps the WHERE exact: a row is only moved if it
    # sits at the bound this migration (or its downgrade) expects, never on value.
    period = REVISED_FIRST
    while period <= REVISED_LAST:
        expected = _end_of_following_month(period) if from_revision == 1 else REVISION_PUBLISHED_BY
        rows = connection.execute(
            _SELECT,
            {
                "codes": list(MIRROR_SERIES),
                "first": period,
                "last": period,
                "known_as_of_matches": expected,
                "revision_matches": from_revision,
            },
        ).all()
        for series_id, as_of_date, known_as_of, value, _revision, document_id in rows:
            connection.execute(
                _DELETE,
                {"series_id": series_id, "as_of_date": as_of_date, "known_as_of": known_as_of},
            )
            connection.execute(
                _INSERT,
                {
                    "series_id": series_id,
                    "as_of_date": as_of_date,
                    "known_as_of": new_known_as_of(as_of_date),
                    "value": value,
                    "revision": to_revision,
                    "source_document_id": document_id,
                },
            )
        period = _end_of_following_month(period)


def upgrade() -> None:
    _redate(to_revision=2, new_known_as_of=lambda _period: REVISION_PUBLISHED_BY)


def downgrade() -> None:
    _redate(to_revision=1, new_known_as_of=_end_of_following_month)

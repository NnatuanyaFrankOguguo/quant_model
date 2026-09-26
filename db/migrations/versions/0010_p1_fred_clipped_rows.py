"""0010 - remove the vintages the windowed DGS10 backfill invented.

Revision ID: 0010_p1_fred_clipped_rows
Revises: 0009_p1_cbn_cpi_vintage
Create Date: 2026-09-12

`US_10Y_TREASURY` (FRED `DGS10`) has more vintage dates than FRED returns in one response,
so P1.2 loaded it in four real-time windows. ALFRED clips `realtime_start` to the start of
the window asked for: every observation already known before a window came back dated *at*
that window's first day, and the loader stored each as a new vintage. The observation for
1990-01-02 therefore held four "vintages" of 7.94 - on 2005-06-28, 2012-01-19, 2018-03-14
and 2024-04-02 - of which only the first is real. 60,835 rows for 16,876 observation dates;
43,952 of them are this artefact, and exactly one row on each of the three later window
starts is a genuine vintage (the observation first published that day).

The 2005-06-28 rows stay. That is ALFRED's first vintage date for the series, and dating
everything known by then to that day is ALFRED's own statement, not our windowing.

**The rule, and why it is safe to apply.** A row is an artefact if an *earlier* vintage of
the same period exists and carries the same value: the value did not change, so nothing
became known. A row with no earlier vintage is a first appearance and stays; a row whose
value differs from the latest earlier vintage is a revision and stays. Point-in-time
queries return the same value before and after this migration - the deleted rows were
duplicates of what the query would have found anyway - so nothing a reader has seen
changes. What changes is that a count of vintages, or a study of *when* values were
revised, stops being wrong by a factor of three.

`Connector.write()` now refuses such rows at the door, so this cannot recur; see the
docstring there. `downgrade()` re-creates the deleted rows exactly - they were pure copies
of the then-latest value, dated at the window start and attributed to that window's
document - and is a no-op where the documents are absent, as on a fresh test database.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0010_p1_fred_clipped_rows"
down_revision: str | None = "0009_p1_cbn_cpi_vintage"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SERIES_CODE = "US_10Y_TREASURY"
FRED_SERIES_ID = "DGS10"
#: The first day of the second, third and fourth backfill windows. The first window's start
#: is ALFRED's genuine first vintage date and is deliberately not listed.
WINDOW_STARTS = (dt.date(2012, 1, 19), dt.date(2018, 3, 14), dt.date(2024, 4, 2))

_DELETE_ARTEFACTS = sa.text(
    """
    DELETE FROM macro_observations o
    USING (
        SELECT series_id, as_of_date, known_as_of
        FROM (
            SELECT o.series_id, o.as_of_date, o.known_as_of, o.value,
                   lag(o.value) OVER (
                       PARTITION BY o.series_id, o.as_of_date ORDER BY o.known_as_of
                   ) AS prev_value,
                   lag(o.known_as_of) OVER (
                       PARTITION BY o.series_id, o.as_of_date ORDER BY o.known_as_of
                   ) AS prev_known
            FROM macro_observations o
            JOIN macro_series m ON m.id = o.series_id
            WHERE m.code = :code
        ) v
        WHERE known_as_of = :window_start
          AND prev_known IS NOT NULL
          AND prev_value IS NOT DISTINCT FROM value
    ) a
    WHERE o.series_id = a.series_id
      AND o.as_of_date = a.as_of_date
      AND o.known_as_of = a.known_as_of
    """
)

_WINDOW_DOCUMENT = sa.text(
    "SELECT id FROM source_documents WHERE url LIKE :pattern ORDER BY id DESC LIMIT 1"
)

_RESTORE_ARTEFACTS = sa.text(
    """
    INSERT INTO macro_observations
        (series_id, as_of_date, known_as_of, value, revision, source_document_id)
    SELECT latest.series_id, latest.as_of_date, CAST(:window_start AS date),
           latest.value, 1, :document_id
    FROM (
        SELECT DISTINCT ON (o.series_id, o.as_of_date)
               o.series_id, o.as_of_date, o.value
        FROM macro_observations o
        JOIN macro_series m ON m.id = o.series_id
        WHERE m.code = :code AND o.known_as_of < :window_start
        ORDER BY o.series_id, o.as_of_date, o.known_as_of DESC
    ) latest
    ON CONFLICT DO NOTHING
    """
)


def upgrade() -> None:
    connection = op.get_bind()
    for window_start in WINDOW_STARTS:
        connection.execute(_DELETE_ARTEFACTS, {"code": SERIES_CODE, "window_start": window_start})


def downgrade() -> None:
    connection = op.get_bind()
    for window_start in WINDOW_STARTS:
        document_id = connection.execute(
            _WINDOW_DOCUMENT,
            {"pattern": f"%series_id={FRED_SERIES_ID}&%realtime_start={window_start}&%"},
        ).scalar()
        if document_id is None:
            continue
        connection.execute(
            _RESTORE_ARTEFACTS,
            {"code": SERIES_CODE, "window_start": window_start, "document_id": document_id},
        )

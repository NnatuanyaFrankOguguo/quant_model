"""0026 - the NGX price aggregator's own register row. `docs/03` P4.7.

`data_sources` already has an `NGX` row, and its own note asks for exactly this split:
*"P1/P2 should split this into two rows when the first NGX connector is built."* That row
is the exchange, under its Data Agreement. This one is `afx.kwayisi.org`, a third party
that republishes NGX prices and cannot grant rights to them - which is why
`redistribution_allowed` is `false` here as a documented answer rather than as caution.

The row is what unblocks the cache. `store_raw` goes through `_data_source_id`, which
raises `LicenceNotDeclaredError` when the source is unregistered, so without it the
connector cannot keep a single byte - and `docs/03` P4.7 rates this source FRAGILE with
the permanent raw cache as the entire mitigation: *"you cannot backfill history you never
fetched."*

`expected_run_interval_hours = 26` is a daily cron plus the two-hour grace migration `0024`
established. `packages/scheduler/jobs.py` runs two pages at 14:05 and 14:11 UTC, after the
14:30 WAT close - the listing is a live intraday snapshot and the connector refuses to
store a pre-close reading as a close.

Revision ID: 0026_p4_afx_kwayisi_source
Revises: 0025_p5_news_items
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date

import sqlalchemy as sa
from alembic import op

revision: str = "0026_p4_afx_kwayisi_source"
down_revision: str | None = "0025_p5_news_items"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SOURCE_NAME = "AFX Kwayisi"

#: A daily cron plus `0024`'s two-hour grace. The connector runs twice a day, so one
#: missed page does not trip this - `scripts/check_connectors.py` covers a single job
#: going quiet, and the heartbeat covers the whole source going dark.
INTERVAL_HOURS = 26

#: One request per 60.2 seconds. **Not `1/60`**: that is `0.016666666666666666`, Postgres
#: stores it in `NUMERIC` as `0.0166666666666667`, and `register()`'s `_same_rate` then
#: compares the two unequal and rewrites this row on every single run for ever.
#: `tests/unit/test_politeness_invariants.py` asserts the round trip for every connector.
RATE_LIMIT_PER_SEC = 0.0166

data_sources_table = sa.table(
    "data_sources",
    sa.column("source_name", sa.Text),
    sa.column("base_url", sa.Text),
    sa.column("licence_type", sa.Text),
    sa.column("redistribution_allowed", sa.Boolean),
    sa.column("attribution_required", sa.Boolean),
    sa.column("attribution_text", sa.Text),
    sa.column("terms_url", sa.Text),
    sa.column("terms_reviewed_on", sa.Date),
    sa.column("reviewed_by", sa.Text),
    sa.column("rate_limit_per_sec", sa.Numeric),
    sa.column("expected_run_interval_hours", sa.Integer),
    sa.column("notes", sa.Text),
)

NOTES = (
    "Third-party aggregator of NGX prices, separate from the exchange's own 'NGX' row, "
    "whose note asks for exactly this split when the first NGX connector is built. "
    "robots.txt allows the listing path and publishes Crawl-delay: 60 (verified "
    "2026-09-24); the listing page is the only path fetched, and it is paginated - "
    "'Showing 1 - 100 of 147'. The page is a live intraday snapshot carrying its own "
    "timestamp, so the connector refuses to store a pre-close reading as a close. No API, "
    "no contract, no uptime guarantee - docs/03 P4.7 rates it FRAGILE and the mitigation "
    "is the permanent raw cache, not the site. The paid fallback is EODHD .XNSA, "
    "documented and not subscribed. redistribution_allowed=false: the underlying data is "
    "NGX market data under a Data Agreement, and an aggregator cannot grant rights to it."
)


def upgrade() -> None:
    connection = op.get_bind()
    already = connection.execute(
        sa.text("SELECT count(*) FROM data_sources WHERE source_name = :n"),
        {"n": SOURCE_NAME},
    ).scalar_one()
    if already:
        # `register()` got here first - it did, on the dev database, which is how the
        # cache started before this migration existed. The reviewed content is identical
        # because both come from `declare_licence()`; only the heartbeat interval is not
        # on the licence, so that is set rather than re-inserted.
        op.execute(
            sa.text(
                "UPDATE data_sources SET expected_run_interval_hours = :h "
                "WHERE source_name = :n AND expected_run_interval_hours IS NULL"
            ).bindparams(h=INTERVAL_HOURS, n=SOURCE_NAME)
        )
        return
    op.bulk_insert(
        data_sources_table,
        [
            {
                "source_name": SOURCE_NAME,
                "base_url": "https://afx.kwayisi.org",
                "licence_type": "third_party_aggregator_no_terms",
                "redistribution_allowed": False,
                "attribution_required": True,
                # Credits both: the aggregator we fetched from and the exchange whose
                # prices they are. A reader needs to know which is which.
                "attribution_text": (
                    "Source: AFX (afx.kwayisi.org), data from Nigerian Exchange (NGX)"
                ),
                "terms_url": "https://afx.kwayisi.org/",
                "terms_reviewed_on": date(2026, 9, 24),
                "reviewed_by": "nnatuanyafrankoguguo",
                "rate_limit_per_sec": RATE_LIMIT_PER_SEC,
                "expected_run_interval_hours": INTERVAL_HOURS,
                "notes": NOTES,
            }
        ],
    )


def downgrade() -> None:
    # Only when nothing points at it. A stored document outliving its register row would
    # be a raw response nobody can say the provenance of, and on this source the raw
    # cache is the asset - `docs/03` P4.7's whole mitigation is that we keep everything we
    # ever fetched even if the site vanishes.
    op.execute(
        sa.text(
            "DELETE FROM data_sources WHERE source_name = :n AND NOT EXISTS ("
            "  SELECT 1 FROM source_documents d WHERE d.data_source_id = data_sources.id)"
        ).bindparams(n=SOURCE_NAME)
    )

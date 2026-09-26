"""0007 - register the Nigeria Data Portal as a data source.

Revision ID: 0007_p1_ndp_source
Revises: 0006_p1_seed_cbn_cpi_mirror
Create Date: 2026-09-10

`docs/03` P1.3 records that NBS has no REST API, and `nigerianstat.gov.ng` still does not.
NBS does publish through the **Nigeria Data Portal** (AfDB's Africa Information Highway),
which has a documented JSON API carrying CPI back to April 2001.

**This row exists because the portal is where the bytes come from, and the licensing register
records where bytes come from.** It is not a second compiler: `NG_CPI_YOY` and `NG_CPI_CORE`
stay attributed to NBS, who actually compile the index. The split is deliberate —
`source_documents.data_source_id` points here, so the register governs the file we fetched,
while `macro_series.data_source_id` points at NBS, so the reader is credited the compiler.

Contrast with migration 0006. CBN is a separate institution republishing NBS's figure under
its own data agreement, so those figures went to clearly-labelled `_CBN` mirror series. A
hosting platform carrying NBS's own terms link is a transport, and transports belong on the
document rather than in the series name.

`redistribution_allowed = false`, like every other row. The dataset's own metadata claims
"Public Domain" with a verified-source flag, and that may well be correct — but it is a third
party's characterisation of a Nigerian agency's data, and `PROJECT_CONTEXT.md` §9.3 makes
this the one register an acquirer's lawyers actually read. Raising it is a one-row change
once someone has read NBS's terms page and recorded that they did.

`downgrade()` deletes exactly the row inserted here.

Two notes for whoever writes migration 0008:

**The revision id is short on purpose.** `alembic_version.version_num` is `varchar(32)`, and
the first draft of this file was named `0007_p1_nigeria_data_portal_source` — 34 characters.
Alembic ran the migration, then failed stamping the version, so the database was left holding
the change while still reporting the previous revision. `tests/unit/test_schema_conventions.py`
now fails the build on an over-long id rather than letting it be discovered this way.

**`upgrade()` tolerates the row already existing.** `register()` creates a `data_sources` row
for any connector whose source is missing, so the row can legitimately arrive before this
migration runs. Inserting blindly would fail on the `source_name` unique constraint.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date

import sqlalchemy as sa
from alembic import op

revision: str = "0007_p1_ndp_source"
down_revision: str | None = "0006_p1_seed_cbn_cpi_mirror"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SOURCE_NAME = "Nigeria Data Portal"

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
    sa.column("notes", sa.Text),
)


def upgrade() -> None:
    connection = op.get_bind()
    already = connection.execute(
        sa.text("SELECT count(*) FROM data_sources WHERE source_name = :n"),
        {"n": SOURCE_NAME},
    ).scalar_one()
    if already:
        # register() got here first. The reviewed content is the same; re-inserting would
        # only violate the unique constraint.
        return
    op.bulk_insert(
        data_sources_table,
        [
            {
                "source_name": SOURCE_NAME,
                "base_url": "https://nigeria.opendataforafrica.org",
                "licence_type": "ng_public_agency_portal",
                "redistribution_allowed": False,
                "attribution_required": True,
                # Credits the compiler, not the transport — the reader wants to know whose
                # statistic this is.
                "attribution_text": "Source: National Bureau of Statistics, Nigeria",
                "terms_url": "https://nigerianstat.gov.ng/page/terms",
                "terms_reviewed_on": date(2026, 9, 10),
                "reviewed_by": "nnatuanyafrankoguguo",
                "rate_limit_per_sec": 0.5,
                "notes": (
                    "Transport for NBS data (AfDB Africa Information Highway, "
                    "Knoema-powered). Dataset NGNBSNCPIR2017 carries CPI monthly from "
                    "2001-04. Portal metadata asserts 'Public Domain' with a verified-source "
                    "flag; that is the portal's claim about NBS's data and is NOT treated as "
                    "clearance to redistribute. Series stay attributed to NBS."
                ),
            }
        ],
    )


def downgrade() -> None:
    op.execute(data_sources_table.delete().where(data_sources_table.c.source_name == SOURCE_NAME))

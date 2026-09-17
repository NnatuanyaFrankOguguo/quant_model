"""0022 - a data source for issuer reports the operator uploads. P3.1.

Revision ID: 0022_p3_issuer_upload_source
Revises: 0021_p3_ratio_action_not_null
Create Date: 2026-09-17

`source_documents.data_source_id` is `NOT NULL`, so a PDF cannot be stored until some row in
`data_sources` accounts for where it came from. Every source so far arrived with a connector
that had a licence to declare (`0004` seeded six, `0007` added the Nigeria Data Portal,
`0012` Yahoo). An annual report the operator downloads and uploads has no connector, and
`docs/03` P3.1 is the first task that needs one.

**One row, not one per issuer.** The document came from the issuer, via a person, and the
`url` on each `source_documents` row records which issuer and which page it was taken from.
A row per company would put 25 near-identical licence records in a table whose whole purpose
is to make the redistribution question answerable at a glance.

**`redistribution_allowed` is false, and this is the row where that matters most.** A
Nigerian annual report is published by its issuer for shareholders; publishing it is the
issuer's act, not a grant of the right to republish the file. `PROJECT_CONTEXT.md` §9.3 calls
redistribution *"the question that kills deals"*, and the *facts* extracted from a report are
a different question from the *file* itself - which is exactly why the licence sits on the
document's source and not on the figures. Serving a cached PDF to the public tier would be a
decision nobody has taken; this row makes the refusal the default.

`terms_url` is NULL on purpose. There is no single terms page: each issuer publishes its own
report under its own terms, and inventing a URL that covers all of them would be worse than
admitting there isn't one. `TEAM_BRIEF` §2.2-B is the task that collects these, and the legal
read of what may be served from them is `OPERATIONS.md` §3.4's standing legal review.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date

import sqlalchemy as sa
from alembic import op

revision: str = "0022_p3_issuer_upload_source"
down_revision: str | None = "0021_p3_ratio_action_not_null"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SOURCE_NAME = "Issuer report (operator upload)"

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
        return
    op.bulk_insert(
        data_sources_table,
        [
            {
                "source_name": SOURCE_NAME,
                # No base URL: the documents come from whichever issuer published them, and
                # each row's own `url` says which.
                "base_url": None,
                "licence_type": "issuer_published_no_redistribution",
                "redistribution_allowed": False,
                "attribution_required": True,
                # Per-document attribution is the `url`; this is what a page prints when it
                # has room for one line.
                "attribution_text": "Source: the issuer's own published report",
                "terms_url": None,
                "terms_reviewed_on": date(2026, 9, 17),
                "reviewed_by": "nnatuanyafrankoguguo",
                # Not fetched on a schedule - a person uploads these one at a time.
                "rate_limit_per_sec": None,
                "notes": (
                    "Annual and interim reports uploaded by the operator (TEAM_BRIEF "
                    "2.2-B), stored immutably and cited page by page by every figure typed "
                    "out of them (docs/03 P3.1, P3.2). No single terms page exists: each "
                    "issuer publishes under its own, so terms_url is NULL rather than "
                    "invented. Redistribution is NOT permitted - the issuer published the "
                    "report, which is not a grant to republish the file. Extracted figures "
                    "are a separate question from the file, and the distinction is the "
                    "reason this licence sits on the document. Serving a cached PDF "
                    "publicly needs the OPERATIONS 3.4 legal review first."
                ),
            }
        ],
    )


def downgrade() -> None:
    op.execute(sa.text("DELETE FROM data_sources WHERE source_name = :n").bindparams(n=SOURCE_NAME))

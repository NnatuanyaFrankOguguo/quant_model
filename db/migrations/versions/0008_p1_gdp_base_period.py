"""0008 - label NG_GDP_GROWTH_YOY with the base its loaded vintages are on.

Revision ID: 0008_p1_gdp_base_period
Revises: 0007_p1_ndp_source
Create Date: 2026-09-12

Migration 0005 seeded `NG_GDP_GROWTH_YOY` with `base_period = 'GDP 2019 rebasing'`, which
describes NBS's *current* methodology: the national accounts were rebased to 2019 in mid-2025
(`DATA_FOUNDATION.md` §B). The only machine-readable NBS GDP series we can reach — the
Nigeria Data Portal's `NGNBSNGDPPTO2016`, quarterly from 2015Q1 — is at **2010 constant basic
prices**, and its newest quarter predates the rebasing.

`docs/08` §2.5: "Rebasing changes past values, so the base is part of the definition." A
series labelled 2019 holding 2010-base figures is a definition that lies about its data, so
the label is corrected to what is actually loaded. When a source for the rebased series
exists, its figures insert as new `known_as_of` rows beside these — the primary key makes a
revision a second row, never an overwrite — and *that* migration moves the label to 2019.
Until then the staleness flag on this series is correct and should stay visible: NBS has
published newer quarters than this portal carries.

The second statement appends one sentence naming the GDP dataset to the portal's
`data_sources.notes`. The register records what we fetch from a source; a note naming only
the CPI dataset would be silently incomplete the day the GDP connector first runs.

`downgrade()` restores the label and strips exactly that sentence.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0008_p1_gdp_base_period"
down_revision: str | None = "0007_p1_ndp_source"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SERIES_CODE = "NG_GDP_GROWTH_YOY"
NEW_BASE = "GDP 2010=100 constant basic prices"
OLD_BASE = "GDP 2019 rebasing"

PORTAL_SOURCE_NAME = "Nigeria Data Portal"
#: Appended to the portal's register notes, never substituted for them. The row may hold
#: migration 0007's text or the connector's `declare_licence()` text — `register()` creates
#: the row when it gets there first, and 0007 tolerates that — and both are code-authored, so
#: neither is "the reviewed wording" to be preserved over the other. Appending keeps whichever
#: is there intact, and `downgrade()` can strip exactly this sentence back out.
GDP_NOTE = (
    " Dataset NGNBSNGDPPTO2016 carries real GDP growth quarterly from 2015Q1 at 2010 "
    "constant basic prices (pre-2019-rebasing vintages)."
)


def upgrade() -> None:
    connection = op.get_bind()
    connection.execute(
        sa.text("UPDATE macro_series SET base_period = :new WHERE code = :code"),
        {"new": NEW_BASE, "code": SERIES_CODE},
    )
    connection.execute(
        sa.text(
            "UPDATE data_sources SET notes = coalesce(notes, '') || :note "
            "WHERE source_name = :name AND coalesce(notes, '') NOT LIKE :marker"
        ),
        {"note": GDP_NOTE, "name": PORTAL_SOURCE_NAME, "marker": "%NGNBSNGDPPTO2016%"},
    )


def downgrade() -> None:
    connection = op.get_bind()
    connection.execute(
        sa.text("UPDATE macro_series SET base_period = :old WHERE code = :code"),
        {"old": OLD_BASE, "code": SERIES_CODE},
    )
    connection.execute(
        sa.text(
            "UPDATE data_sources SET notes = nullif(replace(notes, :note, ''), '') "
            "WHERE source_name = :name"
        ),
        {"note": GDP_NOTE, "name": PORTAL_SOURCE_NAME},
    )

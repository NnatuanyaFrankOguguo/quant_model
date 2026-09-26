"""0019 - the CIK joins identity history, and `companies.cik` goes. TG2.

Revision ID: 0019_tg2_cik_into_identity
Revises: 0018_tg2_identity_history
Create Date: 2026-09-16

The second half of `docs/10` §2.11, which 0018 deliberately left: *"DROP companies.cik;
migrate it into the identity table."* 0018 fixed the constraint; this finishes the sentence.

**What was actually wrong.** §2.11's objection is that "`companies.cik` remains a mutable
scalar outside identity history", and the live schema showed something worse: the column
carried **no unique constraint and no index at all**. Nothing but the connector's own
`WHERE cik = ?` stopped two companies holding one CIK. Meanwhile the identity table has
held `cik` rows since 0011 - the predecessor registrants - so CIKs already lived there, and
the current one was the exception rather than the rule.

Moving it gains the constraint it never had. `no_overlapping_ids` (0018) refuses a second
row with the same `id_type`, `id_value` and an overlapping interval, whichever security it
points at, so one CIK cannot identify two registrants at once. That is strictly stronger
than the unique constraint the column lacked.

**`valid_from` is derived, never invented.** `SPEC.md` §4.1 forbids inferring missing data,
and EDGAR does not say when a registrant received its CIK. Two dates in this database bound
it from below, and the migration takes the later of them:

* the **earliest filing we hold** for that company - a day the registrant was certainly
  filing under that number. The same rule `_record_predecessor` already uses.
* the **day after any predecessor CIK's last valid day**, where the identity table holds one.
  A successor's number cannot predate the succession.

The second is what makes this correct rather than merely plausible. Exxon's filings run back
to 2009 under the predecessor registrant, all written under the continuing company, so the
earliest filing date alone would claim the 2026 successor CIK identified the registrant in
2009. The predecessor row ends 2026-07-01, so `valid_from` becomes 2026-07-02. Disney is the
same shape at 2019-03-21. Neither date is hardcoded here: both are read from the rows 0011
and P2 already wrote, so a third succession needs no migration.

**One current CIK per security**, as a partial unique index, mirroring 0018's
`one_primary_ticker_per_security`. `no_overlapping_ids` keys on the *value*, so it would let
one security carry two different current CIKs; then "this company's CIK", which four API
responses print and every filing URL is built from, would have two answers.

**The company's primary security carries it**, defined here as the lowest security id, which
is exactly what `edgar._primary_security` picks and what the predecessor CIKs already hang
off. A CIK identifies a registrant rather than a listing, so this is a compromise the schema
made in 0011 and this migration follows rather than reopens; `exchange_id` stays NULL, as it
does for every global identifier. All 24 companies hold exactly one security today, so the
choice is not yet forced.

`downgrade()` puts the column back and refills it from the current CIK rows, so the 0018
shape is recoverable with its data.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0019_tg2_cik_into_identity"
down_revision: str | None = "0018_tg2_identity_history"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

#: Stamped on the rows this migration creates, so `downgrade` removes exactly these and
#: leaves the predecessor rows 0011 wrote untouched.
SOURCE = "companies.cik (0019)"


def upgrade() -> None:
    # GREATEST ignores NULLs in Postgres, and every company holds filings today, so the
    # first term is present; the second is absent for all but a successor registrant.
    op.execute(
        f"""
        WITH primary_security AS (
            SELECT company_id, min(id) AS security_id
              FROM securities
             GROUP BY company_id
        )
        INSERT INTO security_identifiers
               (security_id, id_type, id_value, valid_from, valid_to,
                exchange_id, is_primary, source)
        SELECT ps.security_id,
               'cik',
               c.cik,
               GREATEST(
                   (SELECT min(f.filing_date) FROM filings f WHERE f.company_id = c.id),
                   (SELECT max(si.valid_to) + 1
                      FROM security_identifiers si
                     WHERE si.security_id = ps.security_id
                       AND si.id_type = 'cik'
                       AND si.valid_to IS NOT NULL)
               ),
               NULL,
               NULL,
               false,
               '{SOURCE}'
          FROM companies c
          JOIN primary_security ps ON ps.company_id = c.id
         WHERE c.cik IS NOT NULL
           AND NOT EXISTS (
               SELECT 1 FROM security_identifiers si
                WHERE si.id_type = 'cik' AND si.id_value = c.cik
           )
        """
    )
    # A company whose CIK could not be dated has no filings and no derivable lower bound.
    # Refuse rather than store a guessed date or drop the column over a missing row.
    orphans = (
        op.get_bind()
        .execute(
            sa.text(
                """
            SELECT count(*) FROM companies c
             WHERE c.cik IS NOT NULL
               AND NOT EXISTS (
                   SELECT 1 FROM security_identifiers si
                    JOIN securities s ON s.id = si.security_id
                   WHERE s.company_id = c.id
                     AND si.id_type = 'cik'
                     AND si.id_value = c.cik
               )
            """
            )
        )
        .scalar_one()
    )
    if orphans:
        raise RuntimeError(
            f"{orphans} company CIK(s) could not be moved into identity history - most "
            "likely a company with no security or no filing. Fix those rows before "
            "dropping the column; a CIK that resolves to nothing makes the company "
            "unfindable and the next ingest would create a duplicate."
        )

    op.execute(
        """
        CREATE UNIQUE INDEX one_current_cik_per_security
            ON security_identifiers (security_id)
         WHERE id_type = 'cik' AND valid_to IS NULL
        """
    )
    op.drop_column("companies", "cik")


def downgrade() -> None:
    op.add_column("companies", sa.Column("cik", sa.Text(), nullable=True))
    op.execute(
        """
        UPDATE companies c
           SET cik = si.id_value
          FROM security_identifiers si
          JOIN securities s ON s.id = si.security_id
         WHERE s.company_id = c.id
           AND si.id_type = 'cik'
           AND si.valid_to IS NULL
        """
    )
    op.execute("DROP INDEX IF EXISTS one_current_cik_per_security;")
    op.execute(
        sa.text("DELETE FROM security_identifiers WHERE source = :source").bindparams(source=SOURCE)
    )

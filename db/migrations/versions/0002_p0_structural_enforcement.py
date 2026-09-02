"""0002 - structural enforcement on the spine.

Revision ID: 0002_p0_structural_enforcement
Revises: 0001_p0_spine
Create Date: 2026-09-01

`docs/08_DATA_CONTRACTS.md` §2.16, restricted to the tables the spine actually creates.

The argument in §2.16 is worth restating because it is the reason this is a migration and
not a code review checklist: the backtest gate got a CHECK **and** a trigger, with the
stated reason that *"application code can be bypassed at 1am by a person who is sure this
one is fine."* The no-silent-overwrite rule — ranked equally non-negotiable in `CLAUDE.md`
— got only *"enforce it in review."* **The same person at 1am has a SQL client.**

**What this revision applies:**

* `forbid_update()` — the plpgsql function §2.16 defines.
* a `no_update` trigger on `macro_observations`, the one spine table holding an observed
  figure. A revision must INSERT a new vintage row; an UPDATE destroys the earlier
  vintage, which is precisely the silent overwrite `01_ARCHITECTURE` §6 forbids.
* `macro_observations.source_document_id SET NOT NULL` — `docs/10` §2.13, provenance is
  mandatory on **every** figure, not only on line items (`CLAUDE.md` hard rule).

**What §2.16 specifies that this revision deliberately skips, and why:** every remaining
item targets a table this phase does not create, so applying it here is impossible, not
merely premature.

* `no_update` on `statement_line_items`, `price_history`, `corporate_actions`, `fx_rates`,
  `adjustment_factors` — those tables are P2/P3. The `forbid_update()` function created
  here is shared, so each of those phases adds one `CREATE TRIGGER` line and nothing else.
* `pit_sanity CHECK (known_as_of >= period_end)`, the `one_current_version` partial unique
  index, `page_required_unless_structured`, and `correction_type` — all on
  `statement_line_items` (P2).
* `CREATE EXTENSION btree_gist` and the `no_overlapping_ids` exclusion constraint on
  `security_identifiers` (P3). **btree_gist is not created here**: nothing in the spine
  needs a GiST exclusion constraint, and creating an unused extension is a
  privilege-requiring side effect with no caller. P3 creates it alongside the constraint
  that needs it.

An equivalent `pit_sanity` for `macro_observations` (`known_as_of >= as_of_date`) is
**not** added, because it is not in the contract and it is not obviously true: a
forward-looking or nowcast series can legitimately publish a value for a period that has
not ended. Proposing it belongs with P1, which will have real rows to test it against.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0002_p0_structural_enforcement"
down_revision: str | None = "0001_p0_spine"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE OR REPLACE FUNCTION forbid_update() RETURNS TRIGGER AS $$
        BEGIN
          RAISE EXCEPTION 'UPDATE forbidden on %; insert a new version', TG_TABLE_NAME;
        END;
        $$ LANGUAGE plpgsql;
        """
    )

    op.execute(
        """
        CREATE TRIGGER no_update BEFORE UPDATE ON macro_observations
          FOR EACH ROW EXECUTE FUNCTION forbid_update();
        """
    )

    # Provenance on every figure (`CLAUDE.md`; `docs/10` §2.13).
    op.alter_column("macro_observations", "source_document_id", nullable=False)


def downgrade() -> None:
    op.alter_column("macro_observations", "source_document_id", nullable=True)
    op.execute("DROP TRIGGER IF EXISTS no_update ON macro_observations;")
    op.execute("DROP FUNCTION IF EXISTS forbid_update();")

"""0018 - identity: the constraint that makes one ticker resolve to one security. TG2.

Revision ID: 0018_tg2_identity_history
Revises: 0017_tg2_fx_rates
Create Date: 2026-09-16

`docs/10` §2.11 and `OPERATIONS.md` §1.4. The fourth of TG2's six correctness paths, after
corporate actions (0015), fiscal alignment (P2's `normalize.periods`) and FX (0017).

**This is a correction, not a new table.** `security_identifiers` was created in 0011 with
`UNIQUE (id_type, id_value, valid_from)`, and `docs/10` §2.11 - the highest-precedence
document in the set - names three defects in exactly that shape:

* The unique key **does not prevent overlapping validity windows.** Two securities may both
  hold `GTCO` across overlapping dates provided `valid_from` differs by a single day. That
  is precisely the NGX ticker-reuse merge §1.4 was written to stop.
* It **is not exchange-scoped**, so an NGX ticker and a US ticker of the same string
  collide. P3 is the phase that loads Nigerian securities, so this stops being theoretical
  the moment the next connector runs.
* `cik`, `lei` and `figi` were dropped from the `id_type` list while `companies.cik`
  remains a mutable scalar outside identity history.

**Why now.** `OPERATIONS.md`'s own priority order puts §1.4 in the first band - "cheap now
and structurally painful later" - and the corruption it prevents is silent. A reused ticker
joins one company's new prices onto another company's old history and nothing raises: the
series is wrong, plausible, and already feeding a ratio.

**Shape.** `docs/10` §2.11's SQL, with two deviations this migration takes deliberately.
Both are cases where the literal SQL would not deliver the guarantee the same paragraph
states, which is that the constraint "is the only mechanism that makes
`resolve_security(id_type, value, as_of_date)` provably single-valued".

1. **`COALESCE(exchange_id, 0)`, not bare `exchange_id`.** `exchange_id` is NULL for the
   global identifier types (ISIN, CUSIP, SEDOL, CIK, LEI, FIGI), and in an exclusion
   constraint `NULL = NULL` is NULL, not true - so no pair of NULL-exchange rows ever
   conflicts. Every global identifier would escape the constraint, and an ISIN is globally
   unique *by definition*: it is the type where a duplicate matters most. Exchange ids are
   serial and start at 1, so 0 is a sentinel no row can hold.

2. **`COALESCE(valid_to + 1, 'infinity')`, not `COALESCE(valid_to, 'infinity')`.**
   `valid_to` is **inclusive** in this schema - the last day the identifier was valid. Two
   independent facts in the document set fix that reading:

   * `docs/08` §2.1's own worked sample runs `GUARANTY` to 2021-06-23 and starts `GTCO` on
     2021-06-24. Those two rows are gap-free only if 2021-06-23 belongs to `GUARANTY`.
   * `_record_predecessor` in `packages/ingestion/edgar.py` writes `valid_from == valid_to`
     when a payload shows no filing, calling it "the succession day alone". Under the
     half-open `'[)'` bound in the literal SQL that interval is the **empty range** - and an
     empty range overlaps nothing, so a duplicated one-day identity would pass the
     constraint silently. Both live `cik` rows were written by that function.

   So the inclusive end is converted to an exclusive bound once, here, rather than every
   caller having to remember which it was.

**Three additions beyond §2.11**, each closing a hole the correction leaves open:

* `source` (`OPERATIONS.md` §1.4's own DDL, dropped by `docs/08`). An identity claim is a
  figure like any other and "who says this ticker was theirs" must have an answer -
  `CLAUDE.md`'s provenance rule, and `docs/10` §2.15 names provenance a non-negotiable that
  is not deferred to a later phase.
* `one_primary_ticker_per_security`, a partial unique index. `is_primary` is useless without
  it: `packages/valuation/snapshot.py` currently picks a primary ticker with `min(id)`, a
  heuristic that happens to work because EDGAR lists common stock before notes and
  preferreds. Four securities carry more than one current ticker (`BAC` carries sixteen),
  so this is load-bearing today, and a heuristic is the wrong mechanism for it.
* `identifier_has_exchange`, a CHECK. A ticker without an exchange is the collision the
  exchange scoping exists to prevent, so the schema refuses one rather than letting it
  resolve against every market at once.

**The one part of §2.11 this migration does not do.** `docs/10` §2.11's SQL comment says
"DROP companies.cik; migrate it into the identity table". That touches the EDGAR connector,
four API responses and the company page, and `CLAUDE.md` requires one task per PR. It is
recorded as the next task in `docs/00` §6 rather than folded in here. Nothing in this
migration depends on it: the two predecessor CIKs already live in the identity table and are
now covered by the constraint.

`downgrade()` restores the original unique key, so the 0011 shape is recoverable.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0018_tg2_identity_history"
down_revision: str | None = "0017_tg2_fx_rates"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

#: `docs/10` §2.11's list, restoring the three types `docs/08` dropped.
ID_TYPES = ("ticker", "isin", "cusip", "sedol", "cik", "lei", "figi")


def upgrade() -> None:
    # Integer and text equality inside a GiST exclusion constraint. `docs/10` §2.11.
    op.execute("CREATE EXTENSION IF NOT EXISTS btree_gist;")

    op.add_column(
        "security_identifiers",
        sa.Column("exchange_id", sa.Integer(), sa.ForeignKey("exchanges.id"), nullable=True),
    )
    op.add_column(
        "security_identifiers",
        sa.Column("is_primary", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.add_column("security_identifiers", sa.Column("source", sa.Text(), nullable=True))

    # A ticker belongs to the exchange its security trades on. Global ids stay NULL.
    op.execute(
        """
        UPDATE security_identifiers si
           SET exchange_id = s.exchange_id
          FROM securities s
         WHERE s.id = si.security_id
           AND si.id_type = 'ticker'
        """
    )
    # Preserve today's behaviour exactly: the rule `snapshot._primary_ticker_ids` applies is
    # the lowest id among a security's current tickers, which is EDGAR's own ordering -
    # common stock before notes and preferreds. Promoting it from a heuristic in a query to
    # a column plus a constraint changes nothing about which ticker is chosen today.
    op.execute(
        """
        UPDATE security_identifiers
           SET is_primary = true
         WHERE id IN (
               SELECT min(id) FROM security_identifiers
                WHERE id_type = 'ticker' AND valid_to IS NULL
                GROUP BY security_id
         )
        """
    )
    # Every row present was written by the EDGAR submissions connector (0011 onwards).
    op.execute("UPDATE security_identifiers SET source = 'edgar_submissions' WHERE source IS NULL")

    # Dropped, not kept beside the new constraint: this key is not exchange-scoped, so it
    # would reject the very case the exchange scoping exists to allow - one ticker string
    # listed on two exchanges from the same day. The exclusion constraint below is strictly
    # stronger everywhere else.
    op.drop_constraint(
        "security_identifiers_id_type_id_value_valid_from_key",
        "security_identifiers",
        type_="unique",
    )

    op.create_check_constraint(
        "identifier_type_is_known",
        "security_identifiers",
        sa.text("id_type IN " + str(ID_TYPES)),
    )
    op.create_check_constraint(
        "identifier_has_exchange",
        "security_identifiers",
        sa.text("id_type <> 'ticker' OR exchange_id IS NOT NULL"),
    )
    op.create_check_constraint(
        "identifier_interval_is_ordered",
        "security_identifiers",
        sa.text("valid_to IS NULL OR valid_to >= valid_from"),
    )

    op.execute(
        """
        ALTER TABLE security_identifiers
          ADD CONSTRAINT no_overlapping_ids EXCLUDE USING gist (
            id_type WITH =,
            id_value WITH =,
            (COALESCE(exchange_id, 0)) WITH =,
            daterange(valid_from, COALESCE(valid_to + 1, 'infinity'::date), '[)') WITH &&
          )
        """
    )
    op.execute(
        """
        CREATE UNIQUE INDEX one_primary_ticker_per_security
            ON security_identifiers (security_id)
         WHERE is_primary AND id_type = 'ticker' AND valid_to IS NULL
        """
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS one_primary_ticker_per_security;")
    op.execute("ALTER TABLE security_identifiers DROP CONSTRAINT IF EXISTS no_overlapping_ids;")
    for name in (
        "identifier_interval_is_ordered",
        "identifier_has_exchange",
        "identifier_type_is_known",
    ):
        op.drop_constraint(name, "security_identifiers", type_="check")
    op.create_unique_constraint(
        "security_identifiers_id_type_id_value_valid_from_key",
        "security_identifiers",
        ["id_type", "id_value", "valid_from"],
    )
    op.drop_column("security_identifiers", "source")
    op.drop_column("security_identifiers", "is_primary")
    op.drop_column("security_identifiers", "exchange_id")

"""0023 - the trading calendar. TG2, TG21, `docs/08` §2.1's last `[proposed]` table.

Revision ID: 0023_p3_trading_calendar
Revises: 0022_p3_issuer_upload_source
Create Date: 2026-09-17

`docs/08` §2.1 carries the DDL marked `[proposed]`, and this builds it unchanged. The
documents disagreed about when, so the disagreement is worth recording: `OPERATIONS.md` §1.2
says *"before v0.7 indicators"*, which `docs/00` used to defer it to P6 — but `docs/10`
§1174 lists it under **P0.14**, *"timezone discipline … NGX session boundaries in
`trading_calendar`"*, and `docs/03` makes it P3 check 5. `docs/10` outranks every other
document in this repository (`docs/00` §5's precedence order), and two of the three put it
no later than P3. So it is late rather than early.

`docs/10` §1.4 also settles the shape: it lists `trading_calendar.exchange_id → exchanges(id)`
among the foreign keys the first migration would have failed on, so the column is an
`exchange_id` FK and not `OPERATIONS`'s `exchange TEXT`. `exchanges` exists with NGX, NASDAQ
and NYSE, carrying the settlement days each one needs.

## The bug it closes

`docs/01` §7.2 states it exactly: *"A Nigerian public holiday has no price row. Is that a
closed market or a failed scraper? Without a calendar you cannot tell — so you either alert
on every holiday, or you silence the alarm and miss real outages. Meanwhile a 'missing' day
treated as zero return depresses your volatility estimate."*

That is the same distinction as `not_in_filing` against `no_mapping`, one table over: an
absence the world caused, and an absence we caused. A calendar is what tells them apart.

## What is deliberately absent

The primary key is `(exchange_id, date)`, so **a date with no row is not a closed day — it is
an unknown one**, and `packages/common/calendars.py` refuses to answer for it rather than
defaulting to open. That refusal is the point of the table. A calendar that answered "open"
for every date it had never heard of would put settlements on days the exchange was shut,
which is precisely what `OPERATIONS.md` §1.2 warns a hardcoded weekday rule does.

Nigeria's moving holidays are why this matters here and not only in theory. §1.2: *"the
Islamic ones (Eid al-Fitr, Eid al-Adha, Maulid) move each year and are frequently announced
only days in advance by the Federal Government."* Those dates cannot be computed and must not
be guessed; `docs/03` line 1540 lists NGX trading-calendar dates among the operator's manual
work for exactly that reason. Until a year's dates are entered, that year's Eid days are
absent, and every caller is told so.

`session` from `OPERATIONS`'s draft (`'full'|'half'|'closed'`) is not here, because `docs/08`
omitted it and outranks that draft. A half day is `is_open` true with the fact in
`session_note`; nothing queries session length yet, and adding a column for an absent
consumer is the speculation this schema avoids elsewhere.

## Two departures from `docs/08`'s DDL, both deliberate

**`source` is added.** Days arrive three ways — definitional (an exchange does not trade on a
Saturday), inferred (a day on which bars exist is a day that traded), and announced (a
gazetted holiday). Those are not equally strong, and a reader deciding whether to trust a
settlement date needs to know which one they are standing on. Without the column an inference
and an announcement are indistinguishable, which is the failure this table exists to end one
level down.

**No `forbid_update` trigger**, unlike `price_history` and `corporate_actions`. A calendar day
is fact-shaped, but it is corrected *forward* by design: `OPERATIONS.md` §1.2 says to seed
from observed days and *"correct forward from NGX announcements"*, and an unscheduled closure
is announced after the day it shut. Forcing that through delete-and-insert would fight a
prescribed workflow, and `docs/08`'s key of `(exchange_id, date)` leaves no room for the
versioned alternative `statements` uses. `source` is what keeps a correction legible.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0023_p3_trading_calendar"
down_revision: str | None = "0022_p3_issuer_upload_source"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "trading_calendar",
        sa.Column("exchange_id", sa.Integer(), nullable=False),
        sa.Column("date", sa.Date(), nullable=False),
        sa.Column("is_open", sa.Boolean(), nullable=False),
        # 'public holiday: Eid al-Fitr', or how an open day was established.
        sa.Column("session_note", sa.Text(), nullable=True),
        # Where the day came from, so a seeded inference is never mistaken for an
        # announcement. `packages/common/calendars.py` names the values it writes.
        sa.Column("source", sa.Text(), nullable=False),
        sa.ForeignKeyConstraint(["exchange_id"], ["exchanges.id"]),
        sa.PrimaryKeyConstraint("exchange_id", "date"),
    )
    # The query is always "which days between these two dates", per exchange.
    op.create_index(
        "ix_trading_calendar_open",
        "trading_calendar",
        ["exchange_id", "date"],
        postgresql_where=sa.text("is_open"),
    )


def downgrade() -> None:
    op.drop_index("ix_trading_calendar_open", table_name="trading_calendar")
    op.drop_table("trading_calendar")

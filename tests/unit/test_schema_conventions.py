"""Schema convention invariants — `docs/10_PRE_BUILD_CORRECTIONS.md` §6.1, plus TG21.

`docs/10` §6.1 replaced P0.4's "create every table now" ceremony with this file, on the
grounds that the conventions matter more than the empty tables and that **one test governs
P7's and P10's tables, which P0 cannot**:

    # tests/unit/test_schema_conventions.py  — @pytest.mark.invariant
    # Introspect information_schema for EVERY table:
    #   - user-scoped tables (allow-list by name) MUST have principal_id
    #   - figure tables MUST have source_document_id NOT NULL, page, as_of_date
    #   - model-readable tables MUST have known_as_of AND a business date
    # Fails the build the day a phase creates a table that breaks the rule.

Added here: **every timestamp column is `TIMESTAMPTZ`, never a naive `TIMESTAMP`** (TG21),
together with the WAT/UTC boundary tests for `packages.common.timez`.

======================================================================================
HOW TO ADD A TABLE — read this before editing the lists below.
======================================================================================
`test_every_table_is_classified` fails on any table that appears in none of the sets
below. That is deliberate. **A new table must be classified here on purpose, not
default into being unconstrained** — the failure mode this whole file exists to prevent
is a P8 or P10 table quietly created without `principal_id` or without `known_as_of`,
which is a redesign to fix once it holds data.

So when a migration adds a table, add its name to the set that describes it — including
`STRUCTURAL_ONLY` if it genuinely carries no user data, no figures and nothing a model
reads. Adding it to `STRUCTURAL_ONLY` with a wrong reason is the one way to defeat this
test, so put the reason in the comment beside the name.
======================================================================================
"""

from __future__ import annotations

from datetime import UTC, datetime
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import text
from sqlalchemy.engine import Connection

from packages.common.timez import (
    NGX_CLOSE_LOCAL,
    NGX_CLOSE_UTC,
    NGX_TZ,
    ngx_close_utc_on,
    session_date_for,
    utcnow,
)

pytestmark = pytest.mark.invariant


# --------------------------------------------------------------------------------------
# The classification. Data, not logic — so that adding a table is an explicit decision.
# --------------------------------------------------------------------------------------

#: Tables whose rows belong to one principal. MUST carry `principal_id`.
#: `PROJECT_CONTEXT.md` §4: portfolios, watchlists, alerts, risk limits, spend caps and
#: audit rows are keyed by principal. A single-user trading layer is a full rewrite to
#: open up, which is why this is checked from P0 rather than from P10.
USER_SCOPED_TABLES: set[str] = {
    "entitlements",  # principal_id is the primary key
    "principal_tokens",
    "watchlists",
    "llm_spend",
    # --- added by later phases; listed here the day the migration lands ---
    # "portfolios", "positions", "transactions", "alerts", "alert_deliveries",
    # "risk_limits", "scenarios", "tax_lots"
}

#: Tables where `principal_id` may be NULL, each with the reason it must be.
PRINCIPAL_ID_NULLABLE_OK: set[str] = {
    # NULL = the scheduler. That is exactly the spend a per-principal cap would never
    # stop, and which the global cap must cover (`docs/08` §2.15).
    "llm_spend",
}

#: Tables whose ownership is inherited from a parent row rather than repeated.
#: Exempt from the `principal_id` rule, but only by name and only with a reason.
USER_SCOPED_VIA_PARENT: dict[str, str] = {
    "watchlist_items": "owned via watchlists.principal_id; PK is (watchlist_id, security_id)",
}

#: Tables holding an observed or extracted figure. MUST carry `source_document_id NOT
#: NULL` and a business date (`as_of_date` for an observation, `period_end` for a statement
#: figure - `docs/08` §2.3). `CLAUDE.md`: provenance on every figure.
FIGURE_TABLES: set[str] = {
    "macro_observations",
    "statement_line_items",  # P2, migration 0011
    "price_history",  # P2, migration 0012 - business date is `date`
    "shares_outstanding",  # P2, migration 0013
    "shareholdings",  # P2, migration 0014 - units and pct_held are figures off a page
    "corporate_actions",  # TG2, migration 0015 - a ratio or a cash amount off a document
    "adjustment_factors",  # TG12, migration 0015 - carries the action's document too
    "fx_rates",  # TG2, migration 0017 - a rate is a figure with a source document
    # --- later phases ---
    # "fx_rates"
}

#: The subset of FIGURE_TABLES that must also carry `page`.
#: `page` is meaningful only for figures read off a page of a document. `docs/10` §2.13
#: lists precisely which provenance columns each figure table gains, and for
#: `macro_observations` it specifies `source_document_id SET NOT NULL` and nothing more —
#: a FRED series value has no page. `statement_line_items` (P2) is where `page` becomes
#: mandatory, enforced there by `page_required_unless_structured`.
PAGE_REQUIRED_TABLES: set[str] = {
    "statement_line_items",  # P2; `page_required_unless_structured` makes it NOT NULL for PDFs
    "shareholdings",  # P2 schema, P4 extraction target: read off the shareholders schedule
}

#: Tables a model, feature or backtest will read. MUST carry `known_as_of` AND a business
#: date. `SPEC.md` §4.1 invariant 5: joins are on `known_as_of <= decision_date`, never on
#: the business date. A model-readable table with one date column is a look-ahead bug that
#: never raises — it just makes you rich on paper.
MODEL_READABLE_TABLES: set[str] = {
    "macro_observations",
    "statement_line_items",  # P2
    "statements",  # P2
    "filings",  # P2 - a filing date is an event a model may read; known_as_of + period_end
    "price_history",  # P2
    "shares_outstanding",  # P2
    # --- the entity graph, P2 migration 0014, populated from P3/P4 ---
    "entity_roles",
    "shareholdings",
    "company_relationships",
    "index_membership",
    # --- the point-in-time adjustment, TG2/TG12 migration 0015 ---
    "corporate_actions",  # a backtest reads splits and dividends; known_as_of + ex_date
    "adjustment_factors",  # P7 check 19: only factors known by the decision date apply
    "fx_rates",  # a naira figure is converted at the rate known on the decision date
    # --- P5 news, migration 0025 ---
    # An article is knowable from the moment it is published, and P5.3's sentiment score
    # joins straight back to it. `published_at` is the business timestamp; `known_as_of`
    # is the Lagos date of it, generated from it so the two cannot drift.
    "news_items",
    # --- later phases ---
    # "indicators", "ml_features", "news_sentiment"
}

#: The business-date column names a model-readable table may use. A table needs at least
#: one of these alongside `known_as_of`.
BUSINESS_DATE_COLUMNS: frozenset[str] = frozenset(
    {
        "as_of_date",
        "date",
        "period_end",
        "ts",
        "trade_date",
        "effective_from",
        "action_date",
        # `docs/08` uses valid_from for dated validity: identifiers, roles, index membership.
        "valid_from",
        # Corporate actions and their factors are dated by the ex-date, the day that matters.
        "ex_date",
        # An article is *about* the moment it went out, which is the same instant it became
        # knowable. The two columns are not redundant: one is a timestamp and the other the
        # Lagos calendar date a point-in-time filter compares against (P5, migration 0025).
        "published_at",
    }
)

#: Tables that are none of the above: reference data, config, identity, operational logs.
#: Each entry carries the reason it is unconstrained. This is the escape hatch, so it is
#: the one place to be suspicious when reviewing a migration.
STRUCTURAL_ONLY: dict[str, str] = {
    "alembic_version": "alembic's own bookkeeping",
    "principals": "the identity table itself; it IS the principal, it is not scoped to one",
    "system_config": (
        "dated global config, not per-principal; its own (key, effective_from) window is "
        "the point-in-time mechanism"
    ),
    "audit_log": (
        "one row per request, carrying a denormalised `principal` label per `docs/08` "
        "§2.11-2.13. `docs/10` §2.4 proposes principal_id + principal_label instead; that "
        "correction was not applied to `docs/08`, so it is an open question in the P0 "
        "report rather than a silent local decision. Revisit when it is settled."
    ),
    "connector_runs": "operational health, not user data and not a figure",
    "data_sources": "the licensing register; reference data",
    "source_documents": "provenance targets — they ARE the source document",
    "macro_series": "series definitions; the figures live in macro_observations",
    "exchanges": "reference data",
    "industries": "reference data",
    "companies": "reference data (entity identity)",
    "securities": "reference data (instrument identity)",
    # --- P2, migration 0011 ---
    "security_identifiers": (
        "dated identifier history (ticker, ISIN); reference data whose own valid_from/"
        "valid_to window is its time dimension (TG2)"
    ),
    "extraction_jobs": "operational record of how a document was processed; holds no figure",
    # --- TG2, migration 0023 ---
    "trading_calendar": (
        "market structure: which days an exchange traded. No user data and no figure - "
        "`is_open` is a fact about the venue, not a measurement of anything. It does not sit "
        "comfortably in any of the four sets, and the honest reason is worth stating. A "
        "backtest WILL read it, so 'nothing a model reads' is not quite true; but it is read "
        "for date arithmetic (`settlement_date`, `add_trading_days`) rather than joined on "
        "`known_as_of <= decision_date`, and `docs/08` §2.1 keys it `(exchange_id, date)`, "
        "which leaves no room for a vintage. **The open question:** a holiday announced days "
        "in advance was not knowable earlier, so a backtest deciding before the announcement "
        "should arguably not see it. That is a real look-ahead, though a small one - knowing "
        "a market holiday early is not much of an edge - and settling it means either a "
        "`known_as_of` column (a `docs/08` change) or a stated decision that calendars are "
        "exempt. Raise it before P7 check 19, not after."
    ),
    "persons": "identity of a director or officer; the dated facts about them are in entity_roles",
    "chart_of_accounts": "the canonical vocabulary, versioned; reference data (TG7)",
    "account_mappings": "source label -> canonical key, versioned; reference data (TG7)",
}


# --------------------------------------------------------------------------------------
# Introspection helpers
# --------------------------------------------------------------------------------------


def _tables(connection: Connection) -> set[str]:
    rows = connection.execute(
        text(
            """
            SELECT table_name
            FROM information_schema.tables
            WHERE table_schema = 'public' AND table_type = 'BASE TABLE'
            """
        )
    )
    return {row[0] for row in rows}


def _columns(connection: Connection) -> dict[str, dict[str, dict[str, str]]]:
    """{table: {column: {"data_type":…, "is_nullable":…}}} for the public schema."""
    rows = connection.execute(
        text(
            """
            SELECT c.table_name, c.column_name, c.data_type, c.is_nullable
            FROM information_schema.columns c
            JOIN information_schema.tables t
              ON t.table_schema = c.table_schema AND t.table_name = c.table_name
            WHERE c.table_schema = 'public' AND t.table_type = 'BASE TABLE'
            """
        )
    )
    out: dict[str, dict[str, dict[str, str]]] = {}
    for table, column, data_type, is_nullable in rows:
        out.setdefault(table, {})[column] = {
            "data_type": data_type,
            "is_nullable": is_nullable,
        }
    return out


@pytest.fixture(scope="module")
def schema(db_connection: Connection) -> dict[str, dict[str, dict[str, str]]]:
    return _columns(db_connection)


# --------------------------------------------------------------------------------------
# The invariants
# --------------------------------------------------------------------------------------


def test_schema_is_not_empty(db_connection: Connection) -> None:
    """Guard against every other test in this file passing vacuously."""
    tables = _tables(db_connection)
    assert "principals" in tables, (
        "The test database has no `principals` table — migrations did not run. "
        "Every convention check below would pass vacuously."
    )


def test_every_table_is_classified(db_connection: Connection) -> None:
    """A new table must be classified in this file deliberately, not default into nothing."""
    known = (
        USER_SCOPED_TABLES
        | set(USER_SCOPED_VIA_PARENT)
        | FIGURE_TABLES
        | MODEL_READABLE_TABLES
        | set(STRUCTURAL_ONLY)
    )
    unclassified = sorted(_tables(db_connection) - known)
    assert not unclassified, (
        "Unclassified tables: "
        + ", ".join(unclassified)
        + ". Add each to the right set at the top of tests/unit/test_schema_conventions.py "
        "— USER_SCOPED_TABLES, USER_SCOPED_VIA_PARENT, FIGURE_TABLES, "
        "MODEL_READABLE_TABLES, or STRUCTURAL_ONLY with a stated reason. Defaulting a "
        "table into 'unconstrained' is the failure this test exists to prevent."
    )


def test_user_scoped_tables_have_principal_id(
    schema: dict[str, dict[str, dict[str, str]]],
) -> None:
    """PROJECT_CONTEXT §4 — never assume a single user."""
    for table in sorted(USER_SCOPED_TABLES):
        if table not in schema:
            continue  # not yet created by any migration
        assert "principal_id" in schema[table], (
            f"{table} is classified user-scoped but has no principal_id. Adding an owner "
            "column later is a data migration; adding a principal concept to logic that "
            "never had one is a redesign."
        )
        if table not in PRINCIPAL_ID_NULLABLE_OK:
            assert schema[table]["principal_id"]["is_nullable"] == "NO", (
                f"{table}.principal_id is nullable. A NULL owner is a row nobody can be "
                "denied access to. Add the table to PRINCIPAL_ID_NULLABLE_OK with a "
                "reason if the NULL is deliberate."
            )


def test_figure_tables_carry_provenance(
    schema: dict[str, dict[str, dict[str, str]]],
) -> None:
    """CLAUDE.md hard rule — provenance on every figure, non-negotiable."""
    for table in sorted(FIGURE_TABLES):
        if table not in schema:
            continue
        columns = schema[table]
        assert "source_document_id" in columns, f"{table} holds figures but has no source doc"
        assert columns["source_document_id"]["is_nullable"] == "NO", (
            f"{table}.source_document_id is nullable. Optional provenance is no provenance: "
            "the rows without it are exactly the ones nobody can check."
        )
        business = sorted(set(columns) & BUSINESS_DATE_COLUMNS - {"known_as_of"})
        assert business, (
            f"{table} holds figures but has no business date column "
            f"(one of {sorted(BUSINESS_DATE_COLUMNS)}). `docs/08` §2.3 names period_end as "
            "the as-of date of a statement figure; §2.5 names as_of_date for an observation."
        )
        if table in PAGE_REQUIRED_TABLES:
            assert "page" in columns, f"{table} is page-provenanced but has no page column"


def test_model_readable_tables_are_point_in_time(
    schema: dict[str, dict[str, dict[str, str]]],
) -> None:
    """SPEC §4.1 invariant 5 — join on known_as_of, never on the business date."""
    for table in sorted(MODEL_READABLE_TABLES):
        if table not in schema:
            continue
        columns = schema[table]
        assert "known_as_of" in columns, (
            f"{table} is model-readable and has no known_as_of. Joining on the business "
            "date is look-ahead bias; it does not raise, it just inflates the backtest."
        )
        assert columns["known_as_of"]["is_nullable"] == "NO", (
            f"{table}.known_as_of is nullable — a NULL vintage is unusable in a "
            "point-in-time filter and silently drops or admits the row."
        )
        business = sorted(set(columns) & BUSINESS_DATE_COLUMNS - {"known_as_of"})
        assert business, (
            f"{table} has known_as_of but no business date column "
            f"(one of {sorted(BUSINESS_DATE_COLUMNS)}). One date is never enough."
        )


def test_every_timestamp_column_is_timestamptz(db_connection: Connection) -> None:
    """TG21 — storage is UTC and every timestamp carries its zone.

    A naive `TIMESTAMP` column is a value whose meaning depends on whoever wrote it. It
    compares cleanly against other naive values and wrongly against every real instant,
    and the error is exactly one WAT offset — an hour, or a day at the boundary.
    """
    rows = db_connection.execute(
        text(
            """
            SELECT c.table_name, c.column_name, c.data_type
            FROM information_schema.columns c
            JOIN information_schema.tables t
              ON t.table_schema = c.table_schema AND t.table_name = c.table_name
            WHERE c.table_schema = 'public'
              AND t.table_type = 'BASE TABLE'
              AND c.data_type LIKE 'timestamp%'
            ORDER BY 1, 2
            """
        )
    ).all()
    naive = [f"{t}.{c} ({d})" for t, c, d in rows if d != "timestamp with time zone"]
    assert not naive, (
        "Naive TIMESTAMP columns found: "
        + ", ".join(naive)
        + ". Every timestamp column is TIMESTAMPTZ (TG21, docs/08 §1.3)."
    )


def test_no_update_trigger_protects_macro_observations(db_connection: Connection) -> None:
    """docs/08 §2.16 — the no-silent-overwrite rule, enforced in the database.

    Application code can be bypassed at 1am by a person who is sure this one is fine. The
    same person has a SQL client, which is why this is a trigger and not a code review.
    """
    triggers = db_connection.execute(
        text(
            """
            SELECT tgname
            FROM pg_trigger
            WHERE tgrelid = 'macro_observations'::regclass AND NOT tgisinternal
            """
        )
    ).scalars()
    assert "no_update" in set(triggers), (
        "macro_observations has no `no_update` trigger. A revision must INSERT a new "
        "vintage; an UPDATE destroys the earlier one."
    )


# --------------------------------------------------------------------------------------
# TG21 / P0.14 — the WAT/UTC boundary. No database needed.
# --------------------------------------------------------------------------------------


class TestTimezoneDiscipline:
    """NGX closes 14:30 WAT = 13:30 UTC (`docs/00_START_HERE.md` §9, TG21)."""

    def test_utcnow_is_aware_and_utc(self) -> None:
        now = utcnow()
        assert now.tzinfo is not None
        assert now.utcoffset() == datetime.now(UTC).utcoffset()

    def test_wat_is_utc_plus_one_with_no_daylight_saving(self) -> None:
        """West Africa Time is UTC+1 all year. If this ever fails, tzdata changed."""
        january = datetime(2026, 1, 15, 12, 0, tzinfo=ZoneInfo("Africa/Lagos"))
        july = datetime(2026, 7, 15, 12, 0, tzinfo=ZoneInfo("Africa/Lagos"))
        assert january.utcoffset() == july.utcoffset()
        assert january.utcoffset().total_seconds() == 3600  # type: ignore[union-attr]

    def test_declared_close_matches_the_tz_database(self) -> None:
        """`NGX_CLOSE_UTC` is a constant; `ngx_close_utc_on` derives it. They must agree."""
        derived = ngx_close_utc_on(datetime(2026, 9, 1, tzinfo=NGX_TZ).date())
        assert derived.hour == NGX_CLOSE_UTC.hour == 13
        assert derived.minute == NGX_CLOSE_UTC.minute == 30
        assert derived.astimezone(NGX_TZ).time() == NGX_CLOSE_LOCAL

    @pytest.mark.parametrize(
        ("instant", "expected_session", "why"),
        [
            (
                datetime(2026, 9, 1, 13, 29, 59, tzinfo=UTC),
                (2026, 9, 1),
                "one second before the close, 14:29:59 WAT — same session",
            ),
            (
                datetime(2026, 9, 1, 13, 30, 0, tzinfo=UTC),
                (2026, 9, 1),
                "the close itself, 14:30:00 WAT — inclusive, the closing print belongs "
                "to the session that produced it",
            ),
            (
                datetime(2026, 9, 1, 13, 30, 1, tzinfo=UTC),
                (2026, 9, 2),
                "one second after the close — cannot have moved today's close, so it "
                "belongs to the next session. Attributing it to today is lookahead.",
            ),
            (
                datetime(2026, 9, 1, 22, 59, 59, tzinfo=UTC),
                (2026, 9, 2),
                "23:59:59 WAT, still 1 Sep in UTC — the naive .date() answer (1 Sep) is "
                "wrong twice over",
            ),
            (
                datetime(2026, 9, 1, 23, 0, 0, tzinfo=UTC),
                (2026, 9, 2),
                "midnight WAT on 2 Sep while UTC still says 1 Sep — THE off-by-one day",
            ),
            (
                datetime(2026, 9, 2, 0, 0, 0, tzinfo=UTC),
                (2026, 9, 2),
                "01:00 WAT on 2 Sep, before the close — same session date",
            ),
            (
                datetime(2026, 9, 1, 0, 0, 0, tzinfo=UTC),
                (2026, 9, 1),
                "01:00 WAT, pre-open, still that day's session",
            ),
        ],
    )
    def test_session_date_boundaries(
        self, instant: datetime, expected_session: tuple[int, int, int], why: str
    ) -> None:
        assert session_date_for(instant).timetuple()[:3] == expected_session, why

    def test_session_date_is_offset_aware_not_utc_naive(self) -> None:
        """The same instant, expressed in two zones, must give one session date."""
        as_utc = datetime(2026, 9, 1, 23, 30, tzinfo=UTC)
        as_wat = as_utc.astimezone(NGX_TZ)
        assert session_date_for(as_utc) == session_date_for(as_wat)

    def test_naive_datetime_is_rejected(self) -> None:
        """Guessing a naive datetime's zone is how a one-hour error enters the data."""
        with pytest.raises(ValueError, match="Naive datetime"):
            session_date_for(datetime(2026, 9, 1, 13, 30))


@pytest.mark.invariant
def test_every_alembic_revision_id_fits_the_version_column() -> None:
    """`alembic_version.version_num` is varchar(32). A longer id half-applies a migration.

    Found the hard way: a 34-character revision ran its changes, then failed stamping the
    version, leaving the database holding the change while reporting the previous revision.
    Nothing raised at write time and the next `upgrade` would have tried to run it again.
    """
    import re
    from pathlib import Path

    versions = Path(__file__).resolve().parents[2] / "db" / "migrations" / "versions"
    ids: list[str] = []
    for path in sorted(versions.glob("*.py")):
        match = re.search(r'^revision: str = "([^"]+)"', path.read_text(encoding="utf-8"), re.M)
        assert match, f"{path.name} declares no revision id"
        ids.append(match.group(1))

    assert ids, "no migrations found"
    too_long = [r for r in ids if len(r) > 32]
    assert not too_long, f"revision ids longer than varchar(32): {too_long}"
    assert len(set(ids)) == len(ids), "duplicate revision ids"

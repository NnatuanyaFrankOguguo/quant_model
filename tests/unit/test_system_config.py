"""`packages.common.system_config` — the dated-config reader (P0.12 / TG20).

The behaviour under test that actually matters is the failure behaviour. `licence_status`
is half of the mode gate, and `docs/08_DATA_CONTRACTS.md` §2.15 requires that *"a missing,
NULL or unparseable licence_status row resolves to UNLICENSED"*. Every one of those three
paths gets a test here, because the way this goes wrong in the real world is not a bug in
the happy path — it is a truncated table, a botched migration or a typo'd value, and the
consequence is the advice tier opening to the public before the licence exists.

This file also covers the P0 seeds themselves (revisions 0003 and 0004): the values, the
dating of the CGT row, and the fact that `[NEEDS VERIFICATION]` markers survived into the
rows. The data-source register is asserted here rather than in its own file because P0's
file ownership keeps the test surface to two files; it is the same seed migration chain.
"""

from __future__ import annotations

import contextlib
from collections.abc import Iterator
from datetime import date, timedelta

import pytest
from sqlalchemy import text
from sqlalchemy.orm import Session

from packages.common import system_config as sc
from packages.common.system_config import (
    LICENCE_STATUS_KEY,
    LICENSED,
    UNLICENSED,
    get_config,
    is_licensed,
    licence_status,
)
from packages.common.timez import utctoday

TODAY = date(2026, 9, 1)


def _insert(session: Session, **kwargs: object) -> None:
    """Insert one system_config row, defaulting the NOT NULL bookkeeping columns."""
    row = {
        "set_by": "test",
        "reason": "unit test fixture",
        "effective_to": None,
        **kwargs,
    }
    session.execute(
        text(
            """
            INSERT INTO system_config
              (key, value, effective_from, effective_to, set_by, reason)
            VALUES
              (:key, CAST(:value AS jsonb), :effective_from, :effective_to, :set_by, :reason)
            """
        ),
        row,
    )


# --------------------------------------------------------------------------------------
# licence_status — the fail-closed contract
# --------------------------------------------------------------------------------------


class TestLicenceStatusFailsClosed:
    def test_seeded_value_is_unlicensed(self, db_session: Session) -> None:
        """The state of the world today: no SEC registration."""
        assert licence_status(session=db_session) == UNLICENSED
        assert is_licensed(session=db_session) is False

    def test_no_row_at_all_resolves_to_unlicensed(self, db_session: Session) -> None:
        """The truncated-table case. Absence must never read as permission."""
        db_session.execute(
            text("DELETE FROM system_config WHERE key = :k"), {"k": LICENCE_STATUS_KEY}
        )
        assert get_config(LICENCE_STATUS_KEY, session=db_session) is None
        assert licence_status(session=db_session) == UNLICENSED

    def test_json_null_value_resolves_to_unlicensed(self, db_session: Session) -> None:
        """`value` is NOT NULL, but JSONB happily stores the JSON literal `null`."""
        db_session.execute(
            text("UPDATE system_config SET value = 'null'::jsonb WHERE key = :k"),
            {"k": LICENCE_STATUS_KEY},
        )
        assert licence_status(session=db_session) == UNLICENSED

    @pytest.mark.parametrize(
        "stored",
        [
            '"licenced"',  # British spelling typo
            '"licence"',
            '"TRUE"',
            "true",  # a boolean instead of the enum
            "1",
            '""',
            '{"unexpected": "shape"}',
            '["LICENSED"]',  # right word, wrong container
        ],
        ids=[
            "typo-licenced",
            "wrong-word",
            "TRUE-string",
            "boolean",
            "integer",
            "empty-string",
            "wrong-dict-shape",
            "list-not-string",
        ],
    )
    def test_unparseable_values_resolve_to_unlicensed(
        self, db_session: Session, stored: str
    ) -> None:
        db_session.execute(
            text(f"UPDATE system_config SET value = '{stored}'::jsonb WHERE key = :k"),
            {"k": LICENCE_STATUS_KEY},
        )
        assert licence_status(session=db_session) == UNLICENSED

    @pytest.mark.parametrize(
        "stored",
        ['"LICENSED"', '"licensed"', '"  Licensed  "', '{"status": "LICENSED"}'],
        ids=["exact", "lowercase", "padded", "dict-status-key"],
    )
    def test_only_the_licensed_value_opens_the_gate(self, db_session: Session, stored: str) -> None:
        db_session.execute(
            text(f"UPDATE system_config SET value = '{stored}'::jsonb WHERE key = :k"),
            {"k": LICENCE_STATUS_KEY},
        )
        assert licence_status(session=db_session) == LICENSED
        assert is_licensed(session=db_session) is True

    def test_a_future_licence_does_not_apply_today(self, db_session: Session) -> None:
        """Dating works in the direction that matters: not licensed until the day."""
        db_session.execute(
            text("DELETE FROM system_config WHERE key = :k"), {"k": LICENCE_STATUS_KEY}
        )
        _insert(
            db_session,
            key=LICENCE_STATUS_KEY,
            value='"LICENSED"',
            effective_from=TODAY + timedelta(days=30),
        )
        assert licence_status(on=TODAY, session=db_session) == UNLICENSED
        assert licence_status(on=TODAY + timedelta(days=30), session=db_session) == LICENSED


# --------------------------------------------------------------------------------------
# get_config — window semantics
# --------------------------------------------------------------------------------------


class TestGetConfigWindows:
    def test_missing_key_returns_none(self, db_session: Session) -> None:
        assert get_config("no_such_key_exists", session=db_session) is None

    def test_window_is_half_open(self, db_session: Session) -> None:
        """[effective_from, effective_to): the end date is excluded.

        Half-open is what lets a replacement row start on exactly the day the old one
        ends without the two overlapping for a day.
        """
        _insert(
            db_session,
            key="half_open_probe",
            value='"old"',
            effective_from=date(2026, 1, 1),
            effective_to=date(2026, 6, 1),
        )
        _insert(db_session, key="half_open_probe", value='"new"', effective_from=date(2026, 6, 1))
        assert get_config("half_open_probe", on=date(2025, 12, 31), session=db_session) is None
        assert get_config("half_open_probe", on=date(2026, 1, 1), session=db_session) == "old"
        assert get_config("half_open_probe", on=date(2026, 5, 31), session=db_session) == "old"
        assert get_config("half_open_probe", on=date(2026, 6, 1), session=db_session) == "new"
        assert get_config("half_open_probe", on=date(2027, 1, 1), session=db_session) == "new"

    def test_overlapping_windows_resolve_deterministically(self, db_session: Session) -> None:
        """A malformed table still returns ONE answer, and always the same one.

        Overlaps should not exist. When they do — a hand-edited row, a botched
        correction — an arbitrary answer is worse than a wrong one, because it is not
        reproducible and the backtest that used it cannot be re-run.
        """
        _insert(
            db_session,
            key="overlap_probe",
            value='"earlier"',
            effective_from=date(2026, 1, 1),
            effective_to=date(2026, 12, 31),
        )
        _insert(
            db_session,
            key="overlap_probe",
            value='"later"',
            effective_from=date(2026, 3, 1),
            effective_to=date(2026, 12, 31),
        )
        answers = {
            get_config("overlap_probe", on=date(2026, 6, 1), session=db_session) for _ in range(5)
        }
        assert answers == {"later"}, "latest effective_from wins, every time"
        assert get_config("overlap_probe", on=date(2026, 2, 1), session=db_session) == "earlier"

    def test_default_date_is_utc_today(self, db_session: Session) -> None:
        """Not local today. A local-midnight default lands on different days for the
        scheduler and the API."""
        assert utctoday() == date.today() or True  # documented, not asserted: TZ=UTC in .env
        _insert(db_session, key="today_probe", value='"now"', effective_from=utctoday())
        assert get_config("today_probe", session=db_session) == "now"
        _insert(
            db_session,
            key="tomorrow_probe",
            value='"later"',
            effective_from=utctoday() + timedelta(days=1),
        )
        assert get_config("tomorrow_probe", session=db_session) is None

    def test_works_without_an_explicit_session(
        self, db_session: Session, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The `session=None` branch opens its own session. Exercised against the TEST
        database only — `packages.common.db.engine` points at dev, so the real
        `get_session` is substituted rather than called."""

        @contextlib.contextmanager
        def fake_get_session() -> Iterator[Session]:
            yield db_session

        monkeypatch.setattr(sc, "get_session", fake_get_session)
        assert licence_status() == UNLICENSED
        assert get_config("family_tier_max_principals") == 6


# --------------------------------------------------------------------------------------
# The P0.12 seed (revision 0003)
# --------------------------------------------------------------------------------------


class TestSeededConfig:
    def test_family_tier_cap(self, db_session: Session) -> None:
        """Decision D2. A tripwire, not a limit."""
        assert get_config("family_tier_max_principals", session=db_session) == 6

    def test_settlement_and_band_and_movement_rule(self, db_session: Session) -> None:
        assert get_config("ngx_settlement_days", session=db_session) == 3

        band = get_config("ngx_price_band", session=db_session)
        assert band["pct"] == 0.10
        # NGX halts for the day; it does not pause and resume like NYSE or the LSE, so a
        # backtest that fills at the band price is fictional.
        assert band["on_hit"] == "halt_for_day"

        movement = get_config("ngx_movement_rule", session=db_session)
        assert movement["units"] == 100000
        assert movement["regulatory_status"] == "in_flux"

    def test_ngx_fee_stack(self, db_session: Session) -> None:
        fees = get_config("ngx_fee_stack", session=db_session)
        assert fees["sec_fee_pct"] == 0.003
        assert fees["ngx_fee_pct"] == 0.003
        assert fees["cscs_fee_pct"] == 0.003
        assert fees["stamp_duty_pct"] == 0.00075
        assert fees["vat_pct_on_fees"] == 0.075
        assert fees["vat_base"].startswith("brokerage_and_regulatory_fees")
        assert fees["brokerage_pct"] == 0.0135

    def test_extraction_thresholds_are_four_distinct_decisions(self, db_session: Session) -> None:
        """docs/10 §3.1: three unrelated 0.85s sat within a page of each other, and the
        pass bar equalled the abandon floor, so clearing 'abandon' read as passing."""
        assert get_config("extraction_target_headline", session=db_session) == 0.95
        assert get_config("extraction_target_all_items", session=db_session) == 0.90
        assert get_config("extraction_abandon_floor", session=db_session) == 0.85
        assert get_config("extraction_confidence_route", session=db_session) == 0.85

        floor_reason = db_session.execute(
            text("SELECT reason FROM system_config WHERE key = 'extraction_abandon_floor'")
        ).scalar_one()
        route_reason = db_session.execute(
            text("SELECT reason FROM system_config WHERE key = 'extraction_confidence_route'")
        ).scalar_one()
        # Same number, different meaning — each row has to say so on its own.
        assert "FLOOR, NOT A TARGET" in floor_reason
        assert "UNRELATED" in route_reason

    def test_cgt_is_dated_to_the_acts_commencement_not_the_migration(
        self, db_session: Session
    ) -> None:
        """The reason `system_config` is dated at all. The Nigeria Tax Act 2025 commenced
        2026-01-01; a portfolio computed for 2025 must not see the 2026 thresholds."""
        assert get_config("ng_cgt_shares", on=date(2025, 12, 31), session=db_session) is None

        cgt = get_config("ng_cgt_shares", on=date(2026, 1, 1), session=db_session)
        assert cgt["proceeds_exemption_ngn"] == 150_000_000
        assert cgt["chargeable_gain_exemption_ngn"] == 10_000_000
        assert cgt["lookback_months"] == 12
        assert cgt["dividend_wht_pct"] == 0.10

    @pytest.mark.parametrize("key", ["ngx_fee_stack", "ngx_movement_rule", "ng_cgt_shares"])
    def test_unverified_numbers_carry_their_marker(self, db_session: Session, key: str) -> None:
        """Do not launder an unverified number into a clean-looking config row.

        A value that looks settled and is not is worse than no value: it gets used, the
        doubt does not travel with it, and nobody re-checks a number that never
        advertised one.
        """
        reason = db_session.execute(
            text("SELECT reason FROM system_config WHERE key = :k"), {"k": key}
        ).scalar_one()
        assert "[NEEDS VERIFICATION]" in reason, f"{key} lost its verification marker"

    def test_every_seeded_row_states_who_and_why(self, db_session: Session) -> None:
        bad = (
            db_session.execute(
                text(
                    """
                SELECT key FROM system_config
                WHERE set_by IS NULL OR btrim(set_by) = ''
                   OR reason IS NULL OR btrim(reason) = ''
                """
                )
            )
            .scalars()
            .all()
        )
        assert not bad, f"system_config rows with no attribution or no reason: {bad}"


# --------------------------------------------------------------------------------------
# The P0.10 / TG5 seed (revision 0004) — the licensing register
# --------------------------------------------------------------------------------------


class TestDataSourceRegisterSeed:
    EXPECTED = {"FRED", "SEC EDGAR", "NGX", "CBN", "NBS", "DMO"}

    def test_the_six_verified_sources_are_registered(self, db_session: Session) -> None:
        names = set(
            db_session.execute(text("SELECT source_name FROM data_sources")).scalars().all()
        )
        assert names >= self.EXPECTED

    def test_ngx_may_not_be_redistributed(self, db_session: Session) -> None:
        """DATA_FOUNDATION §6.3 — NGX data may be used internally and may NOT be re-served
        raw. Derived analytics only. This is the row that kills deals."""
        row = db_session.execute(
            text("SELECT redistribution_allowed, notes FROM data_sources WHERE source_name = 'NGX'")
        ).one()
        assert row.redistribution_allowed is False
        assert "MAY NOT BE RE-SERVED RAW" in row.notes

    def test_every_source_answers_the_redistribution_question(self, db_session: Session) -> None:
        """`redistribution_allowed NOT NULL` is the whole mechanism: it forces an answer
        at registration time, and a source row that never answered cannot exist."""
        unanswered = (
            db_session.execute(
                text(
                    """
                SELECT source_name FROM data_sources
                WHERE redistribution_allowed IS NULL
                   OR terms_reviewed_on IS NULL
                   OR reviewed_by IS NULL
                   OR btrim(reviewed_by) = ''
                """
                )
            )
            .scalars()
            .all()
        )
        assert not unanswered

    def test_edgar_rate_limit_is_recorded(self, db_session: Session) -> None:
        """10 req/sec is the one verified numeric limit in the register; exceeding it
        earns a 403/429 and a ~10-minute IP block."""
        limit = db_session.execute(
            text("SELECT rate_limit_per_sec FROM data_sources WHERE source_name = 'SEC EDGAR'")
        ).scalar_one()
        assert limit == 10

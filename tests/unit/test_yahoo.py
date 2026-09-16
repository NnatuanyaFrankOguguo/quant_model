"""P2.3 — daily bars stored as traded, with vintages.

The fixture is Yahoo's real response for Apple around the 4-for-1 split of 2020-08-31, the
one case that decides whether `close_raw` means what `docs/08` §2.4 says it means.
"""

from __future__ import annotations

import datetime as dt
import json
from collections.abc import Iterator
from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from packages.common.identity import CIK, resolve_security
from packages.common.models import PriceHistory
from packages.common.storage import LocalDiskBackend
from packages.common.timez import utctoday
from packages.ingestion import base as ingestion_base
from packages.ingestion.base import RawResponse, register
from packages.ingestion.edgar import EdgarSubmissionsConnector
from packages.ingestion.yahoo import ActionRecord, PriceBar, Split, YahooChartConnector, unadjust

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"
UA = "Test Person test@example.com"
APPLE_CIK = "0000320193"


def _chart_raw() -> RawResponse:
    return RawResponse(
        data=(FIXTURES / "yahoo" / "AAPL_chart_2020_split.json").read_bytes(),
        media_type="application/json",
        url="https://query2.finance.yahoo.com/v8/finance/chart/AAPL?period1=0",
        http_status=200,
    )


# --------------------------------------------------------------------------------------
# As traded, not as served
# --------------------------------------------------------------------------------------


@pytest.mark.invariant
def test_prices_before_a_split_are_stored_as_they_traded() -> None:
    """Yahoo serves 124.81 for 2020-08-28. Apple closed at 499.23 that day."""
    bars = {r.date: r for r in YahooChartConnector().parse(_chart_raw()) if isinstance(r, PriceBar)}
    before = bars[dt.date(2020, 8, 28)]
    after = bars[dt.date(2020, 8, 31)]
    assert before.close_raw == Decimal("499.2300")
    assert before.open_raw == Decimal("504.0500")
    assert before.volume == 46_907_500
    # The ex-date bar is already in post-split terms and is left alone.
    assert after.close_raw == Decimal("129.0400")
    assert after.volume == 225_702_700


def test_unadjust_compounds_every_later_split_and_ignores_earlier_ones() -> None:
    splits = [
        Split(ex_date=dt.date(2014, 6, 9), ratio=Decimal(7)),
        Split(ex_date=dt.date(2020, 8, 31), ratio=Decimal(4)),
    ]
    assert unadjust(dt.date(2010, 1, 4), splits) == Decimal(28)
    assert unadjust(dt.date(2015, 1, 2), splits) == Decimal(4)
    assert unadjust(dt.date(2020, 8, 31), splits) == Decimal(1)
    assert unadjust(dt.date(2021, 1, 4), splits) == Decimal(1)


def test_parse_is_pure_and_dated_in_the_exchange_timezone() -> None:
    connector = YahooChartConnector()
    records = connector.parse(_chart_raw())
    assert records == connector.parse(_chart_raw())
    bars = [r for r in records if isinstance(r, PriceBar)]
    assert [b.date for b in bars][:2] == [dt.date(2020, 8, 20), dt.date(2020, 8, 21)]
    assert all(b.currency == "USD" and b.symbol == "AAPL" for b in bars)


def test_a_bar_with_no_close_is_not_a_bar() -> None:
    payload = json.loads(_chart_raw().data)
    payload["chart"]["result"][0]["indicators"]["quote"][0]["close"][0] = None
    raw = RawResponse(data=json.dumps(payload).encode(), media_type="application/json", url="x")
    bars = [r for r in YahooChartConnector().parse(raw) if isinstance(r, PriceBar)]
    assert dt.date(2020, 8, 20) not in {b.date for b in bars}
    assert len(bars) == 11


def test_a_chart_error_is_raised_not_swallowed() -> None:
    payload = {"chart": {"result": None, "error": {"code": "Not Found", "description": "x"}}}
    raw = RawResponse(data=json.dumps(payload).encode(), media_type="application/json", url="x")
    with pytest.raises(ValueError, match="Yahoo chart error"):
        YahooChartConnector().parse(raw)


# --------------------------------------------------------------------------------------
# Vintages, against the database
# --------------------------------------------------------------------------------------


@pytest.fixture
def local_store(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> LocalDiskBackend:
    store = LocalDiskBackend(tmp_path / "documents")
    monkeypatch.setattr(ingestion_base, "get_storage", lambda: store)
    return store


@pytest.fixture
def apple_security(db_session: Session, local_store: LocalDiskBackend) -> Iterator[int]:
    """Apple registered from the submissions fixture, so a ticker resolves to a security."""
    connector = EdgarSubmissionsConnector(user_agent=UA)
    register(db_session, connector)
    connector.fetch = lambda **params: RawResponse(  # type: ignore[method-assign]
        data=(FIXTURES / "edgar" / "AAPL_submissions_trimmed.json").read_bytes(),
        media_type="application/json",
        url="s",
    )
    assert connector.run(db_session, cik=APPLE_CIK).status == "ok"
    # The CIK is a dated identifier since 0019, so the security comes from the resolver.
    resolved = resolve_security(db_session, value=APPLE_CIK, as_of=utctoday(), id_type=CIK)
    assert resolved is not None, f"CIK {APPLE_CIK} identifies no security"
    security_id = resolved.security_id
    yield security_id


def _prices_connector(raw: RawResponse) -> YahooChartConnector:
    connector = YahooChartConnector()
    connector.fetch = lambda **params: raw  # type: ignore[method-assign]
    return connector


def test_first_sight_is_dated_the_day_it_traded(db_session: Session, apple_security: int) -> None:
    connector = _prices_connector(_chart_raw())
    register(db_session, connector)
    result = connector.run(db_session, symbol="AAPL")
    assert result.status == "ok", result.error
    assert result.rows_written == 12 + 2, "twelve bars, the split, and its factor row"
    rows = (
        db_session.execute(select(PriceHistory).where(PriceHistory.security_id == apple_security))
        .scalars()
        .all()
    )
    assert all(r.known_as_of == r.date for r in rows)
    assert all(r.source_document_id is not None and r.data_source_id is not None for r in rows)
    by_date = {r.date: r for r in rows}
    assert by_date[dt.date(2020, 8, 28)].close_raw == Decimal("499.23")


@pytest.mark.invariant
def test_an_unchanged_refetch_writes_nothing_and_a_changed_bar_is_a_new_vintage(
    db_session: Session, apple_security: int
) -> None:
    connector = _prices_connector(_chart_raw())
    register(db_session, connector)
    assert connector.run(db_session, symbol="AAPL").rows_written == 14
    assert connector.run(db_session, symbol="AAPL").rows_written == 0

    payload = json.loads(_chart_raw().data)
    quote = payload["chart"]["result"][0]["indicators"]["quote"][0]
    quote["volume"][-1] = quote["volume"][-1] + 1000  # a late print corrected upstream
    corrected = _prices_connector(
        RawResponse(data=json.dumps(payload).encode(), media_type="application/json", url="y")
    )
    assert corrected.run(db_session, symbol="AAPL").rows_written == 1

    versions = db_session.execute(
        select(PriceHistory.known_as_of, PriceHistory.volume)
        .where(PriceHistory.security_id == apple_security)
        .where(PriceHistory.date == dt.date(2020, 9, 4))
        .order_by(PriceHistory.known_as_of)
    ).all()
    assert len(versions) == 2, "the original bar must still be there"
    assert versions[0].known_as_of == dt.date(2020, 9, 4)
    assert versions[1].known_as_of > versions[0].known_as_of
    assert versions[1].volume == versions[0].volume + 1000


@pytest.mark.invariant
def test_bars_cannot_be_updated(db_session: Session, apple_security: int) -> None:
    connector = _prices_connector(_chart_raw())
    register(db_session, connector)
    assert connector.run(db_session, symbol="AAPL").rows_written == 14
    with pytest.raises(Exception, match="UPDATE forbidden"):
        db_session.execute(
            text("UPDATE price_history SET close_raw = close_raw + 1 WHERE security_id = :s"),
            {"s": apple_security},
        )
    db_session.rollback()


def test_an_unknown_ticker_is_refused_not_invented(db_session: Session, local_store) -> None:
    connector = _prices_connector(_chart_raw())
    register(db_session, connector)
    result = connector.run(db_session, symbol="AAPL")
    assert result.status == "error"
    assert "no current security carries ticker" in (result.error or "")


# --- the price around a publication day (docs/05 §11, Q6) ------------------------------


def _write_bars(session: Session, security_id: int, closes: dict[str, str]) -> None:
    """Bars straight into price_history, first sight on their own date, one document."""
    from packages.common.models import DataSource, SourceDocument

    source_id = session.execute(
        select(DataSource.id).where(DataSource.source_name == "Yahoo Finance")
    ).scalar_one()
    document = SourceDocument(
        data_source_id=source_id,
        url="file:///bars.json",
        storage_key="documents/sha256/" + "d" * 64,
        sha256="d" * 64,
        media_type="application/json",
        retrieved_at=dt.datetime(2026, 9, 1, tzinfo=dt.UTC),
    )
    session.add(document)
    session.flush()
    for day, close in closes.items():
        session.add(
            PriceHistory(
                security_id=security_id,
                date=dt.date.fromisoformat(day),
                known_as_of=dt.date.fromisoformat(day),
                close_raw=Decimal(close),
                data_source_id=source_id,
                source_document_id=document.id,
            )
        )
    session.flush()


@pytest.mark.invariant
def test_the_reaction_runs_from_the_close_before_publication_day(
    db_session: Session, apple_security: int
) -> None:
    from packages.valuation.snapshot import _reactions_around

    # Eight sessions: a Friday publication on the 6th, the split-free case.
    _write_bars(
        db_session,
        apple_security,
        {
            "2026-03-04": "100",
            "2026-03-05": "102",  # the close before
            "2026-03-06": "101",  # publication day (filed after the bell)
            "2026-03-09": "108",  # +1
            "2026-03-10": "107",
            "2026-03-11": "109",
            "2026-03-12": "110",
            "2026-03-13": "112.2",  # +5
            "2026-03-16": "120",
        },
    )
    on = dt.date(2026, 3, 6)
    reactions = _reactions_around(
        db_session, security_id=apple_security, dates=[on], known_by=dt.date(2026, 9, 1)
    )
    r = reactions[on]
    assert (r.before.date, r.on_day.date, r.after_1.date, r.after_5.date) == (
        dt.date(2026, 3, 5),
        dt.date(2026, 3, 6),
        dt.date(2026, 3, 9),
        dt.date(2026, 3, 13),
    )
    assert r.return_1d == Decimal("0.0588"), "108 / 102 - 1"
    assert r.return_5d == Decimal("0.1000"), "112.2 / 102 - 1"

    # Known only up to the third session after: no fifth bar, no reaction, not a partial one.
    early = _reactions_around(
        db_session, security_id=apple_security, dates=[on], known_by=dt.date(2026, 3, 11)
    )
    assert on not in early
    # A day with no bar of its own (a weekend filing) gets nothing.
    assert dt.date(2026, 3, 7) not in _reactions_around(
        db_session,
        security_id=apple_security,
        dates=[dt.date(2026, 3, 7)],
        known_by=dt.date(2026, 9, 1),
    )


@pytest.mark.invariant
def test_an_action_the_tables_do_not_hold_withholds_the_reaction(
    db_session: Session, apple_security: int
) -> None:
    """As-traded closes with a 4-for-1 jump and no corporate action on the record: served as
    a reaction it would be a 74% crash. It is withheld instead, until the action is held."""
    from packages.valuation.snapshot import _reactions_around

    _write_bars(
        db_session,
        apple_security,
        {
            "2026-04-01": "400",
            "2026-04-02": "404",  # the close before
            "2026-04-03": "402",  # publication day
            "2026-04-06": "101",  # a 4-for-1 nobody told the tables about
            "2026-04-07": "102",
            "2026-04-08": "103",
            "2026-04-09": "104",
            "2026-04-10": "105",
        },
    )
    on = dt.date(2026, 4, 3)
    reactions = _reactions_around(
        db_session, security_id=apple_security, dates=[on], known_by=dt.date(2026, 9, 1)
    )
    assert on not in reactions


# --- corporate actions and the point-in-time adjustment (TG2 / TG12, migration 0015) -----


def test_the_split_and_its_dividends_parse_as_actions_in_as_traded_terms() -> None:
    """The response's events become actions. A dividend served at 0.205 in post-split terms
    traded at 0.82 before the 4-for-1 - unadjusted exactly as a price is."""
    payload = json.loads(_chart_raw().data)
    events = payload["chart"]["result"][0]["events"]
    events["dividends"] = {
        "1596806400": {"amount": 0.205, "date": 1596806400},  # 2020-08-07, before the split
        "1604671200": {"amount": 0.205, "date": 1604671200},  # 2020-11-06, after it
    }
    raw = RawResponse(data=json.dumps(payload).encode(), media_type="application/json", url="e")
    actions = [r for r in YahooChartConnector().parse(raw) if isinstance(r, ActionRecord)]
    assert [(a.action_type, a.ex_date) for a in actions] == [
        ("dividend", dt.date(2020, 8, 7)),
        ("split", dt.date(2020, 8, 31)),
        ("dividend", dt.date(2020, 11, 6)),
    ]
    split = actions[1]
    assert (split.ratio_from, split.ratio_to) == (Decimal(1), Decimal(4)), "1 old -> 4 new"
    assert actions[0].cash_amount == Decimal("0.820000"), "as it traded, before the split"
    assert actions[2].cash_amount == Decimal("0.205000")
    assert all(a.symbol == "AAPL" and a.currency == "USD" for a in actions)


@pytest.mark.invariant
def test_an_action_is_dated_its_ex_date_and_a_changed_ratio_is_a_new_vintage(
    db_session: Session, apple_security: int
) -> None:
    from packages.common.models import AdjustmentFactor, CorporateAction

    connector = _prices_connector(_chart_raw())
    register(db_session, connector)
    assert connector.run(db_session, symbol="AAPL").status == "ok"
    actions = (
        db_session.execute(
            select(CorporateAction).where(CorporateAction.security_id == apple_security)
        )
        .scalars()
        .all()
    )
    assert len(actions) == 1
    (split,) = actions
    assert split.action_type == "split" and split.ex_date == dt.date(2020, 8, 31)
    assert split.known_as_of == dt.date(2020, 8, 31), "public by its ex-date at the latest"
    assert (split.ratio_from, split.ratio_to) == (Decimal(1), Decimal(4))
    assert split.source_document_id is not None
    factors = (
        db_session.execute(
            select(AdjustmentFactor).where(AdjustmentFactor.security_id == apple_security)
        )
        .scalars()
        .all()
    )
    assert len(factors) == 1 and factors[0].action_id == split.id
    assert factors[0].factor == Decimal("0.25") and factors[0].known_as_of == split.known_as_of

    # Served again with the same terms: nothing. Served with a corrected ratio: a second
    # vintage, dated the day the change was seen, and the first row untouched.
    assert connector.run(db_session, symbol="AAPL").rows_written == 0
    payload = json.loads(_chart_raw().data)
    payload["chart"]["result"][0]["events"]["splits"]["1598880600"]["numerator"] = 5.0
    corrected = _prices_connector(
        RawResponse(data=json.dumps(payload).encode(), media_type="application/json", url="c")
    )
    result = corrected.run(db_session, symbol="AAPL")
    assert result.status == "ok", result.error
    versions = (
        db_session.execute(
            select(CorporateAction)
            .where(CorporateAction.security_id == apple_security)
            .order_by(CorporateAction.known_as_of)
        )
        .scalars()
        .all()
    )
    assert [(v.ratio_to, v.known_as_of) for v in versions] == [
        (Decimal(4), dt.date(2020, 8, 31)),
        (Decimal(5), dt.date.today()),
    ]
    # The update trigger holds outside this code, as on every figure table.
    with pytest.raises(Exception, match="forbid|update|UPDATE"):
        db_session.execute(
            text("UPDATE corporate_actions SET ratio_to = 6 WHERE id = :id"), {"id": split.id}
        )
        db_session.flush()
    db_session.rollback()


@pytest.mark.invariant
def test_adjusted_close_depends_on_the_decision_date(
    db_session: Session, apple_security: int
) -> None:
    """docs/08 §2.4's worked example: 499.23 on 2020-08-28, 4-for-1 on the 31st.

    Read after the split is on the record, the 28th is 124.8075 beside the 31st's 129.04.
    Read on the 30th - before the split's ex-date, which is when it was public at the latest
    by this connector's rule - it is 499.23, as the market saw it. Both right; the date
    decides. And a call without a decision date is a TypeError, never a default of today.
    """
    from packages.common.adjust import adjusted_close

    connector = _prices_connector(_chart_raw())
    register(db_session, connector)
    assert connector.run(db_session, symbol="AAPL").status == "ok"
    on = dt.date(2020, 8, 28)

    later = adjusted_close(
        db_session, security_id=apple_security, date=on, decision_date=dt.date(2020, 9, 30)
    )
    assert later is not None
    assert later.close_raw == Decimal("499.2300"), "the raw close is never touched"
    assert later.factor == Decimal("0.25") and later.actions_applied == 1
    assert later.close_adjusted == Decimal("124.807500")

    before = adjusted_close(
        db_session, security_id=apple_security, date=on, decision_date=dt.date(2020, 8, 30)
    )
    assert before is not None
    assert before.factor == Decimal(1) and before.actions_applied == 0
    assert before.close_adjusted == Decimal("499.2300"), "the split was not yet on the record"

    ex_day = adjusted_close(
        db_session,
        security_id=apple_security,
        date=dt.date(2020, 8, 31),
        decision_date=dt.date(2020, 9, 30),
    )
    assert ex_day is not None and ex_day.factor == Decimal(1), "the ex-date bar is post-split"

    assert (
        adjusted_close(
            db_session,
            security_id=apple_security,
            date=dt.date(2020, 8, 19),
            decision_date=dt.date(2020, 9, 30),
        )
        is None
    ), "no bar, no answer - never an interpolation"
    with pytest.raises(TypeError):
        adjusted_close(db_session, security_id=apple_security, date=on, decision_date=None)  # type: ignore[arg-type]


@pytest.mark.invariant
def test_a_known_split_inside_the_window_is_a_non_event_for_the_reaction(
    db_session: Session, apple_security: int
) -> None:
    """The split guard's retirement. With the action on the record, the reaction across
    Apple's 4-for-1 is computed on adjusted closes; on a decision date before the split was
    known, the as-traded closes would lie and the window is withheld, as before."""
    from packages.valuation.snapshot import _reactions_around

    connector = _prices_connector(_chart_raw())
    register(db_session, connector)
    assert connector.run(db_session, symbol="AAPL").status == "ok"
    on = dt.date(2020, 8, 25)  # +5 sessions reach 2020-09-01, across the split
    served = _reactions_around(
        db_session, security_id=apple_security, dates=[on], known_by=dt.date(2020, 12, 31)
    )
    assert on in served
    r = served[on]
    # 2020-08-24 closed 503.43 as traded, 125.8575 adjusted; 2020-09-01 closed 134.18.
    assert r.before.close_raw == Decimal("503.4300")
    assert r.after_5.close_raw == Decimal("134.1800")
    assert r.return_5d == (Decimal("134.18") / Decimal("125.8575") - 1).quantize(Decimal("0.0001"))
    assert r.return_1d == (Decimal("126.5225") / Decimal("125.8575") - 1).quantize(
        Decimal("0.0001")
    )
    withheld = _reactions_around(
        db_session, security_id=apple_security, dates=[on], known_by=dt.date(2020, 8, 30)
    )
    assert on not in withheld, "the fifth session after is not yet known on the 30th"


# --- the dividend history in today's share terms (docs/05 §11, Q4) -----------------------


def _write_actions(session: Session, security_id: int, actions: list[tuple[str, str, str]]) -> None:
    """(type, ex_date, figure) rows straight into corporate_actions, first sight on the ex-date.
    A split's figure is 'from:to'; a dividend's is its per-share amount."""
    from packages.common.models import AdjustmentFactor, CorporateAction, DataSource, SourceDocument

    source_id = session.execute(
        select(DataSource.id).where(DataSource.source_name == "Yahoo Finance")
    ).scalar_one()
    document = SourceDocument(
        data_source_id=source_id,
        url="file:///actions.json",
        storage_key="documents/sha256/" + "a" * 64,
        sha256="a" * 64,
        media_type="application/json",
        retrieved_at=dt.datetime(2026, 9, 1, tzinfo=dt.UTC),
    )
    session.add(document)
    session.flush()
    for action_type, ex_date, figure in actions:
        row = CorporateAction(
            security_id=security_id,
            action_type=action_type,
            ex_date=dt.date.fromisoformat(ex_date),
            ratio_from=Decimal(figure.split(":")[0]) if action_type == "split" else None,
            ratio_to=Decimal(figure.split(":")[1]) if action_type == "split" else None,
            cash_amount=Decimal(figure) if action_type == "dividend" else None,
            currency="USD",
            source_document_id=document.id,
            known_as_of=dt.date.fromisoformat(ex_date),
        )
        session.add(row)
        session.flush()
        if action_type == "split":
            session.add(
                AdjustmentFactor(
                    security_id=security_id,
                    ex_date=row.ex_date,
                    action_id=row.id,
                    factor=row.ratio_from / row.ratio_to,
                    known_as_of=row.known_as_of,
                    source_document_id=document.id,
                )
            )
    session.flush()


@pytest.mark.invariant
def test_a_split_is_not_a_cut_and_a_real_cut_is_named(
    db_session: Session, apple_security: int
) -> None:
    """Four years of dividends: 3.05 a quarter, then a 7-for-1 after which 0.47 a quarter is
    the same money per old share; then a year that really was cut; then the current year,
    still running, which is never called a cut."""
    from packages.valuation.snapshot import dividends_for

    _write_actions(
        db_session,
        apple_security,
        [
            ("dividend", "2023-02-10", "3.05"),
            ("dividend", "2023-05-12", "3.05"),
            ("dividend", "2023-08-11", "3.05"),
            ("dividend", "2023-11-10", "3.05"),
            ("split", "2024-01-02", "1:7"),
            ("dividend", "2024-02-09", "0.47"),
            ("dividend", "2024-05-10", "0.47"),
            ("dividend", "2024-08-09", "0.47"),
            ("dividend", "2024-11-08", "0.47"),
            ("dividend", "2025-02-07", "0.20"),  # the cut
            ("dividend", "2025-05-09", "0.20"),
            ("dividend", "2025-08-08", "0.20"),
            ("dividend", "2025-11-07", "0.20"),
            ("dividend", "2026-02-06", "0.21"),
        ],
    )
    history = dividends_for(
        db_session, security_id=apple_security, decision_date=dt.date(2026, 3, 1)
    )
    assert len(history.dividends) == 13, "thirteen dividends; the split is not one"
    first = history.dividends[0]
    assert first.cash_amount == Decimal("3.05"), "as it traded"
    assert first.amount_in_todays_shares == Decimal("0.435714"), "3.05 / 7, in today's shares"
    totals = {
        y.year: (y.total.quantize(Decimal("0.0001")), y.count, y.partial) for y in history.years
    }
    assert totals == {
        2023: (Decimal("1.7429"), 4, False),  # 12.20 / 7
        2024: (Decimal("1.8800"), 4, False),
        2025: (Decimal("0.8000"), 4, False),
        2026: (Decimal("0.2100"), 1, True),
    }
    assert [c.year for c in history.cuts] == [2025], "the split year is not a cut; 2025 is"
    changes = {y.year: y.change_yoy for y in history.years}
    assert changes[2023] is None
    assert changes[2024] == Decimal("0.0787"), "1.88 against 1.742856"
    assert changes[2025] == Decimal("-0.5745")
    assert changes[2026] is None, "a running year is not compared with a complete one"

    # Before the split was known, the 2023 amounts stand as they traded.
    earlier = dividends_for(
        db_session, security_id=apple_security, decision_date=dt.date(2023, 12, 31)
    )
    assert earlier.dividends[0].amount_in_todays_shares == Decimal("3.05")
    assert [y.year for y in earlier.years] == [2023] and earlier.cuts == []


def test_a_year_with_no_dividend_inside_the_span_is_a_zero_and_a_cut(
    db_session: Session, apple_security: int
) -> None:
    from packages.valuation.snapshot import dividends_for

    _write_actions(
        db_session,
        apple_security,
        [("dividend", "2022-06-01", "1.00"), ("dividend", "2024-06-01", "1.00")],
    )
    history = dividends_for(
        db_session, security_id=apple_security, decision_date=dt.date(2024, 12, 31)
    )
    assert [(y.year, y.total, y.count) for y in history.years] == [
        (2022, Decimal("1.00"), 1),
        (2023, Decimal(0), 0),
        (2024, Decimal("1.00"), 1),
    ]
    assert [c.year for c in history.cuts] == [2023]
    assert history.years[2].change_yoy is None, "growth from nothing is not a fraction"

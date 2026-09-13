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

from packages.common.models import Company, PriceHistory, Security
from packages.common.storage import LocalDiskBackend
from packages.ingestion import base as ingestion_base
from packages.ingestion.base import RawResponse, register
from packages.ingestion.edgar import EdgarSubmissionsConnector
from packages.ingestion.yahoo import Split, YahooChartConnector, unadjust

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
    bars = {bar.date: bar for bar in YahooChartConnector().parse(_chart_raw())}
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
    bars = connector.parse(_chart_raw())
    assert bars == connector.parse(_chart_raw())
    assert [b.date for b in bars][:2] == [dt.date(2020, 8, 20), dt.date(2020, 8, 21)]
    assert all(b.currency == "USD" and b.symbol == "AAPL" for b in bars)


def test_a_bar_with_no_close_is_not_a_bar() -> None:
    payload = json.loads(_chart_raw().data)
    payload["chart"]["result"][0]["indicators"]["quote"][0]["close"][0] = None
    raw = RawResponse(data=json.dumps(payload).encode(), media_type="application/json", url="x")
    bars = YahooChartConnector().parse(raw)
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
    security_id = db_session.execute(
        select(Security.id).join(Company).where(Company.cik == APPLE_CIK)
    ).scalar_one()
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
    assert result.rows_written == 12
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
    assert connector.run(db_session, symbol="AAPL").rows_written == 12
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
    assert connector.run(db_session, symbol="AAPL").rows_written == 12
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

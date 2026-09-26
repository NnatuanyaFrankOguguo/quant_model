"""P4.7 - the NGX listing scraper, against the page as it actually is.

Both fixtures are the real `afx.kwayisi.org/ngx/` pages, saved unmodified on 2026-09-24:
page 1 (100 of 147 listings) and page 2 (the remaining 47). Nothing here is invented HTML,
because invented HTML tests the parser against the author's memory of the page rather than
against the page - and the whole risk `docs/03` P4.7 records is that this page changes
without telling anyone.

The three failures these tests exist to catch are the three this connector could have had:

1. **The silent scraper.** A renamed column, a redesigned page or a block page must not
   arrive as `status='ok'` with zero rows, which in `connector_runs` is indistinguishable
   from a market where nothing happened (`OPERATIONS.md` 2.3).
2. **The silent drop.** No NGX security exists yet, so *every* ticker on the page fails to
   resolve. That must be counted and named, not quietly discarded.
3. **The intraday close.** The page is live. Writing a 10:17 WAT price into `close_raw` -
   a column whose `no_update` trigger makes it uncorrectable - would be permanent.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Iterator
from decimal import Decimal
from pathlib import Path

import pytest
import structlog
from sqlalchemy import select
from sqlalchemy.orm import Session

from packages.common.identity import TICKER
from packages.common.models import Company, Exchange, PriceHistory, Security, SecurityIdentifier
from packages.common.storage import LocalDiskBackend
from packages.common.timez import utctoday
from packages.ingestion import base as ingestion_base
from packages.ingestion.base import RawResponse, register
from packages.ingestion.ngx import SOURCE_NAME, AfxKwayisiConnector, NgxQuote

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "ngx"

#: What the saved pages say about themselves. Asserted rather than assumed, so that a
#: re-saved fixture that silently lost half its rows fails here and not in a review.
PAGE1_ROWS = 100
PAGE2_ROWS = 47
TOTAL_LISTINGS = 147

#: The `<time datetime=...>` on page 1: 09:17 UTC, which is 10:17 in Lagos - seventeen
#: minutes into a session that closes at 14:30. Every "this is not a close" test hangs
#: off this being before the close, so it is named once.
SNAPSHOT_UTC = dt.datetime(2026, 9, 24, 9, 17, 4, tzinfo=dt.UTC)
TRADE_DATE = dt.date(2026, 9, 24)


def _raw(name: str = "afx_kwayisi_ngx_listing.html", *, url: str | None = None) -> RawResponse:
    return RawResponse(
        data=(FIXTURES / name).read_bytes(),
        media_type="text/html",
        url=url or "https://afx.kwayisi.org/ngx/",
        http_status=200,
    )


def _after_the_close(
    name: str = "afx_kwayisi_ngx_listing.html", *, on: dt.date = TRADE_DATE
) -> RawResponse:
    """The real page with only its timestamp moved to 15:05 Lagos on `on`.

    The bytes are otherwise untouched, so the write-path tests still run against real
    markup. Moving the clock rather than hand-writing a table is the difference between
    testing the parser and testing a mock of it.

    `on` exists because a vintage is a day: a correction seen on the same date the bar was
    first stored collides on `(security_id, date, known_as_of)`, and a test that wanted a
    second vintage had to pick a trading day in the past or it would pass today and fail
    tomorrow.
    """
    document = (FIXTURES / name).read_bytes()
    moved = document.replace(
        b"2026-09-24T09:17:04+00:00", f"{on.isoformat()}T14:05:00+00:00".encode()
    )
    assert moved != document, "the timestamp this fixture is edited by hand has moved"
    return RawResponse(
        data=moved, media_type="text/html", url="https://afx.kwayisi.org/ngx/", http_status=200
    )


# --------------------------------------------------------------------------------------
# The page, parsed
# --------------------------------------------------------------------------------------


def test_the_listing_yields_one_record_per_symbol_with_sane_prices() -> None:
    """A plausible count, and prices that are prices.

    The bounds are deliberately wide: this asserts that the parser found the market, not
    that NGX had exactly 147 listings on one Thursday. A count that collapses to three is
    the failure worth catching, and 1,000,000 naira is above Okomu Oil's 1,276.20 by
    enough that a decimal point lost to a stray comma would still trip it.
    """
    quotes = AfxKwayisiConnector().parse(_raw())
    assert len(quotes) == PAGE1_ROWS
    assert len({q.ticker for q in quotes}) == PAGE1_ROWS, "tickers must be unique on a page"
    assert all(q.ticker and q.ticker == q.ticker.upper() for q in quotes)

    priced = [q for q in quotes if q.price is not None]
    assert len(priced) == PAGE1_ROWS, "every row on this page carried a price"
    assert all(Decimal("0.01") <= q.price <= Decimal(1_000_000) for q in priced)

    by_ticker = {q.ticker: q for q in quotes}
    # Three rows read off the saved page by hand, one of each shape: an ordinary row, the
    # most expensive one (where a thousands comma has to survive), and a mover.
    assert by_ticker["ABBEYBANK"].price == Decimal("7.00")
    assert by_ticker["ABBEYBANK"].volume == 66_713
    assert by_ticker["OKOMUOIL"].price == Decimal("1276.20")
    assert by_ticker["OKOMUOIL"].volume == 8_754
    assert by_ticker["ACCESSCORP"].price == Decimal("30.05")
    assert by_ticker["ACCESSCORP"].name == "Access Holdings Plc"


def test_change_is_absolute_naira_and_is_not_confused_with_the_percent_tables() -> None:
    """The same page carries percentage movers. Reading one as the other is 100x wrong.

    NAHCO moved +9.00 naira on the day, and appears in the gainers table at +6.43%. If the
    parser had locked on to the wrong table, this would be 6.43.
    """
    by_ticker = {q.ticker: q for q in AfxKwayisiConnector().parse(_raw())}
    assert by_ticker["NAHCO"].change == Decimal("9.00")
    assert by_ticker["NAHCO"].price == Decimal("149.00")
    # A flat row is a real zero, not an absent value: the stock traded and did not move.
    assert by_ticker["OANDO"].change == Decimal("0.00")
    moved = [q for q in AfxKwayisiConnector().parse(_raw()) if q.change not in (None, Decimal(0))]
    assert len(moved) == 14, "14 of the 100 rows had moved by 10:17 Lagos time"


def test_a_suspended_row_is_recognised_and_keeps_its_stale_price() -> None:
    """`class="ss"` with an empty volume. Parsed faithfully; `write()` is where it stops."""
    quotes = AfxKwayisiConnector().parse(_raw())
    suspended = {q.ticker: q for q in quotes if q.suspended}
    assert set(suspended) == {
        "AFRINSURE",
        "AFROMEDIA",
        "ALEX",
        "EKOCORP",
        "GOLDBREW",
        "MULTITREX",
    }
    assert all(q.volume is None for q in suspended.values()), "no volume means no trade"
    assert all(q.price is not None for q in suspended.values()), "the stale price is kept"
    # NULL, never 0. A zero volume is a claim that the stock traded nothing today, which is
    # a different fact from the page declining to say (SPEC 4.1).
    assert suspended["AFRINSURE"].volume is None


def test_the_snapshot_instant_comes_off_the_page_and_is_the_same_for_every_row() -> None:
    """One page is one snapshot. A per-row timestamp would be an invention."""
    quotes = AfxKwayisiConnector().parse(_raw())
    assert {q.snapshot_at for q in quotes} == {SNAPSHOT_UTC}
    assert quotes[0].trade_date == TRADE_DATE
    assert quotes[0].session_complete is False, "10:17 Lagos is inside the session"
    assert _after_the_close_quotes()[0].session_complete is True


def _after_the_close_quotes() -> list[NgxQuote]:
    return AfxKwayisiConnector().parse(_after_the_close())


def test_parse_is_pure_and_deterministic() -> None:
    """Rule 3 of the connector contract, and what makes a stored document re-parseable."""
    connector = AfxKwayisiConnector()
    assert connector.parse(_raw()) == connector.parse(_raw())


def test_the_second_page_parses_and_the_two_together_are_the_whole_market() -> None:
    """The listing paginates at 100 and the exchange has 147 listings.

    A connector that stopped at page 1 would hold 68% of the market with nothing to say
    about the rest, which is the silent-scraper failure wearing a plausible number.
    """
    page1 = AfxKwayisiConnector().parse(_raw())
    page2 = AfxKwayisiConnector().parse(
        _raw("afx_kwayisi_ngx_listing_page2.html", url="https://afx.kwayisi.org/ngx/?page=2")
    )
    assert len(page2) == PAGE2_ROWS
    assert len(page1) + len(page2) == TOTAL_LISTINGS
    assert not ({q.ticker for q in page1} & {q.ticker for q in page2}), "pages must not overlap"


def test_a_partial_page_says_so_rather_than_reporting_a_complete_market() -> None:
    with structlog.testing.capture_logs() as logs:
        AfxKwayisiConnector().parse(_raw())
    paginated = [e for e in logs if e["event"] == "ngx_listing_is_paginated"]
    assert len(paginated) == 1
    assert paginated[0]["showing"] == "1-100" and paginated[0]["of"] == TOTAL_LISTINGS
    _assert_row_count_agrees(logs)


def test_the_last_page_is_not_reported_as_partial() -> None:
    """Warning on the complete case is how a warning earns a mute."""
    with structlog.testing.capture_logs() as logs:
        AfxKwayisiConnector().parse(_raw("afx_kwayisi_ngx_listing_page2.html"))
    assert not [e for e in logs if e["event"] == "ngx_listing_is_paginated"]
    _assert_row_count_agrees(logs)


def _assert_row_count_agrees(logs: list[dict[str, object]]) -> None:
    """Neither coverage alarm may fire on a page the parser read correctly.

    A parser that skipped rows would still return a plausible list; the footer is the only
    independent statement of how many there should have been, so its silence is a result.
    """
    assert not [e for e in logs if e["event"] == "ngx_row_count_disagrees_with_page"]
    assert not [e for e in logs if e["event"] == "ngx_coverage_footer_missing"]


def test_fetch_declares_the_published_crawl_delay_rather_than_a_rate_of_our_own() -> None:
    """`robots.txt` publishes `Crawl-delay: 60`. One request a minute, or slower."""
    connector = AfxKwayisiConnector()
    assert 1.0 / connector.rate_limit_per_sec >= 60.0
    # The declared float must survive a round-trip through `data_sources.rate_limit_per_sec`
    # (a NUMERIC), or `register()` rewrites the row on every run forever - see
    # `base._same_rate`. `1/60` would fail this.
    assert float(Decimal(str(connector.rate_limit_per_sec))) == connector.rate_limit_per_sec


# --------------------------------------------------------------------------------------
# A renamed, emptied or blocked page fails loudly
# --------------------------------------------------------------------------------------


def test_a_renamed_price_column_raises_instead_of_yielding_zero_rows() -> None:
    """The exact silent-scraper failure: the page loads, the parser matches nothing.

    `status='ok'` with zero rows is what a quiet market looks like in `connector_runs`, so
    a redesign must not be able to wear that costume.
    """
    broken = _raw().data.replace(b"<th>Price<th>Change", b"<th>Last<th>Change")
    raw = RawResponse(data=broken, media_type="text/html", url="u", http_status=200)
    with pytest.raises(ValueError, match="no table on"):
        AfxKwayisiConnector().parse(raw)


def test_a_table_with_a_header_and_no_rows_raises() -> None:
    document = _raw().data.decode("utf-8")
    header = "<table><thead><tr><th>Ticker<th>Name<th>Volume<th>Price<th>Change<tbody>"
    start = document.index(header)
    end = document.index("</table>", start)
    emptied = (document[:start] + header + document[end:]).encode("utf-8")
    raw = RawResponse(data=emptied, media_type="text/html", url="u", http_status=200)
    with pytest.raises(ValueError, match="header and no rows"):
        AfxKwayisiConnector().parse(raw)


def test_a_block_page_raises_rather_than_parsing_to_nothing() -> None:
    """403 bodies, maintenance pages and Cloudflare interstitials all look like this."""
    raw = RawResponse(
        data=b"<html><body><h1>403 Forbidden</h1></body></html>",
        media_type="text/html",
        url="u",
        http_status=200,
    )
    with pytest.raises(ValueError, match="no <time datetime"):
        AfxKwayisiConnector().parse(raw)


def test_a_page_with_no_timestamp_raises_rather_than_guessing_a_date() -> None:
    """A price dated by guesswork is worse than no price: nothing downstream can tell."""
    stripped = _raw().data.replace(b"datetime=2026-09-24T09:17:04+00:00", b"")
    raw = RawResponse(data=stripped, media_type="text/html", url="u", http_status=200)
    with pytest.raises(ValueError, match="no instant to date these prices"):
        AfxKwayisiConnector().parse(raw)


def test_one_unparseable_cell_costs_that_field_and_not_the_run() -> None:
    """The row-level rule is the opposite of the page-level one, on purpose.

    A page that changed shape is a broken parser; a single junk cell is a bad cell. This
    page has no contract, and one of those must not throw away the other 99 rows.
    """
    document = _raw().data.replace(b"<td>66,713<td>7.00<td>+0.00", b"<td>n/a<td>--<td>&mdash;", 1)
    quotes = AfxKwayisiConnector().parse(
        RawResponse(data=document, media_type="text/html", url="u", http_status=200)
    )
    assert len(quotes) == PAGE1_ROWS, "the other rows survive"
    abbey = next(q for q in quotes if q.ticker == "ABBEYBANK")
    assert abbey.price is None and abbey.volume is None and abbey.change is None


# --------------------------------------------------------------------------------------
# Writing: against the database
# --------------------------------------------------------------------------------------


@pytest.fixture
def local_store(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> LocalDiskBackend:
    store = LocalDiskBackend(tmp_path / "documents")
    monkeypatch.setattr(ingestion_base, "get_storage", lambda: store)
    return store


@pytest.fixture
def registered(db_session: Session, local_store: LocalDiskBackend) -> AfxKwayisiConnector:
    """A connector whose `data_sources` row exists, and which never touches the network."""
    connector = AfxKwayisiConnector()
    register(db_session, connector)
    return connector


def _fixed(connector: AfxKwayisiConnector, raw: RawResponse) -> AfxKwayisiConnector:
    connector.fetch = lambda **params: raw  # type: ignore[method-assign]
    return connector


@pytest.fixture
def access_holdings(db_session: Session) -> Iterator[int]:
    """One real NGX security, so the resolved path is exercised and not only the empty one.

    ACCESSCORP is on page 1 of the fixture at 30.05 with 2,657,719 shares traded. There are
    no NGX securities in the database at all today, which is precisely why this fixture has
    to build one.
    """
    exchange_id = db_session.execute(select(Exchange.id).where(Exchange.code == "NGX")).scalar_one()
    company = Company(
        legal_name="Access Holdings Plc",
        country="NG",
        statement_template="bank",
        fiscal_year_end=12,
    )
    db_session.add(company)
    db_session.flush()
    security = Security(company_id=company.id, exchange_id=exchange_id, currency="NGN")
    db_session.add(security)
    db_session.flush()
    db_session.add(
        SecurityIdentifier(
            security_id=security.id,
            id_type=TICKER,
            id_value="ACCESSCORP",
            valid_from=dt.date(2022, 3, 28),
            valid_to=None,
            exchange_id=exchange_id,
            is_primary=True,
            source="test",
        )
    )
    db_session.flush()
    yield security.id


@pytest.mark.invariant
def test_unresolvable_tickers_are_counted_and_named_not_dropped_quietly(
    db_session: Session, registered: AfxKwayisiConnector
) -> None:
    """Today every ticker on the page is unresolvable. That must be a number, not silence.

    `securities` holds no NGX row, so `write()` can insert nothing. The run still has to
    say how many rows it saw, how many it could place, and which ones it could not - the
    alternative is `rows_written=0` with no way to tell a dead parser from an empty
    identifier table.
    """
    connector = _fixed(registered, _after_the_close())
    with structlog.testing.capture_logs() as logs:
        result = connector.run(db_session)

    assert result.status == "ok", result.error
    assert result.records_parsed == PAGE1_ROWS
    assert result.rows_written == 0

    unresolved = [e for e in logs if e["event"] == "ngx_tickers_unresolved"]
    assert len(unresolved) == 1, "the whole page going unplaced must be said exactly once"
    # 100 rows, six of them suspended and dropped before resolution is even attempted.
    assert unresolved[0]["unresolved"] == PAGE1_ROWS - 6
    assert unresolved[0]["resolved"] == 0
    assert "ACCESSCORP" in unresolved[0]["sample"]
    assert "register the companies" in unresolved[0]["remedy"]

    summary = [e for e in logs if e["event"] == "ngx_listing_resolved"]
    assert len(summary) == 1
    counted = summary[0]
    # Every parsed row is accounted for in exactly one bucket. This is the assertion that
    # makes the counting trustworthy: a row cannot be dropped without moving a number.
    assert (
        counted["storable"]
        + counted["unresolved"]
        + counted["ambiguous"]
        + counted["suspended"]
        + counted["no_price"]
        == counted["quotes"]
        == PAGE1_ROWS
    )
    assert counted["suspended"] == 6

    # And the base class's own silent-scraper warning fires beside it, so the two agree.
    assert [e for e in logs if e["event"] == "connector_wrote_no_rows"]


@pytest.mark.invariant
def test_a_run_that_writes_nothing_still_caches_the_raw_response_forever(
    db_session: Session, registered: AfxKwayisiConnector, local_store: LocalDiskBackend
) -> None:
    """The reason `write()` never raises. `docs/03` P4.7's whole strategy is the raw cache.

    `run()` commits only after `write()` returns, so an exception there rolls the
    `source_documents` row back with it. A connector that refused to place 147 unknown
    tickers would therefore throw away the history it exists to collect - every night,
    invisibly, for as long as the securities were missing.
    """
    connector = _fixed(registered, _after_the_close())
    result = connector.run(db_session)

    assert result.status == "ok" and result.rows_written == 0
    assert result.source_document_id is not None
    document = ingestion_base.cached_document(db_session, "https://afx.kwayisi.org/ngx/")
    assert document is not None, "the page must be retrievable from storage after the run"
    assert local_store.get(document.sha256) == _after_the_close().data


def test_a_resolvable_ticker_is_written_as_the_day_it_traded(
    db_session: Session, registered: AfxKwayisiConnector, access_holdings: int
) -> None:
    connector = _fixed(registered, _after_the_close())
    with structlog.testing.capture_logs() as logs:
        result = connector.run(db_session)

    assert result.status == "ok", result.error
    assert result.rows_written == 1, "one NGX security exists, so one bar can be placed"
    summary = next(e for e in logs if e["event"] == "ngx_listing_resolved")
    assert summary["storable"] == 1 and summary["unresolved"] == PAGE1_ROWS - 7

    bar = db_session.execute(
        select(PriceHistory).where(PriceHistory.security_id == access_holdings)
    ).scalar_one()
    assert bar.date == TRADE_DATE
    assert bar.known_as_of == TRADE_DATE, "first sight is dated the day it traded"
    assert bar.close_raw == Decimal("30.05")
    assert bar.volume == 2_657_719
    # The listing gives one price and no intraday range. Filling these with the close would
    # invent a day that opened, peaked and troughed at exactly one number.
    assert bar.open_raw is None and bar.high_raw is None and bar.low_raw is None
    assert bar.halted is False, "the page's suspension flag is not the price-band halt"


def _corrected(raw: RawResponse) -> RawResponse:
    """The same page with ACCESSCORP's close moved from 30.05 to 30.15."""
    changed = raw.data.replace(
        b'title="Access Holdings Plc">Access Holdings Plc</a><td>2,657,719<td>30.05',
        b'title="Access Holdings Plc">Access Holdings Plc</a><td>2,657,719<td>30.15',
    )
    assert changed != raw.data, "ACCESSCORP's row is not where this test thinks it is"
    return RawResponse(data=changed, media_type="text/html", url="v", http_status=200)


def test_an_unchanged_refetch_writes_nothing_and_a_changed_price_is_a_new_vintage(
    db_session: Session, registered: AfxKwayisiConnector, access_holdings: int
) -> None:
    """Dated two days back, because a vintage is a day - see `_after_the_close`."""
    traded_on = TRADE_DATE - dt.timedelta(days=2)
    connector = _fixed(registered, _after_the_close(on=traded_on))
    assert connector.run(db_session).rows_written == 1
    assert connector.run(db_session).rows_written == 0, "the same close is the same vintage"

    second = _fixed(AfxKwayisiConnector(), _corrected(_after_the_close(on=traded_on)))
    assert second.run(db_session).rows_written == 1

    vintages = db_session.execute(
        select(PriceHistory.known_as_of, PriceHistory.close_raw)
        .where(PriceHistory.security_id == access_holdings)
        .where(PriceHistory.date == traded_on)
        .order_by(PriceHistory.known_as_of)
    ).all()
    assert len(vintages) == 2, "the original close must still be there"
    assert vintages[0].close_raw == Decimal("30.05")
    assert vintages[0].known_as_of == traded_on, "first sight is dated the day it traded"
    assert vintages[1].close_raw == Decimal("30.15")
    assert vintages[1].known_as_of > vintages[0].known_as_of


@pytest.mark.invariant
def test_a_correction_on_the_day_of_first_sight_is_refused_out_loud(
    db_session: Session, registered: AfxKwayisiConnector, access_holdings: int
) -> None:
    """A vintage is a day, so a same-day correction has nowhere to go. Say so.

    `known_as_of` is in the primary key at day granularity, so a changed close seen on the
    same date the bar was first stored collides and `ON CONFLICT DO NOTHING` discards it.
    Inventing a later knowledge date to dodge the key would put a fabricated date in the
    one column whose job is to say when a figure was knowable, so the row is dropped - but
    never quietly. Tomorrow's run stores it.
    """
    today = utctoday()
    first = _fixed(registered, _after_the_close(on=today))
    assert first.run(db_session).rows_written == 1

    second = _fixed(AfxKwayisiConnector(), _corrected(_after_the_close(on=today)))
    with structlog.testing.capture_logs() as logs:
        assert second.run(db_session).rows_written == 0

    refused = [e for e in logs if e["event"] == "ngx_same_day_correction_not_stored"]
    assert len(refused) == 1 and refused[0]["count"] == 1
    held = (
        db_session.execute(
            select(PriceHistory.close_raw)
            .where(PriceHistory.security_id == access_holdings)
            .where(PriceHistory.date == today)
        )
        .scalars()
        .all()
    )
    assert held == [Decimal("30.05")], "the first figure stands, and it is the only one"


@pytest.mark.invariant
def test_an_intraday_snapshot_is_refused_rather_than_stored_as_a_close(
    db_session: Session, registered: AfxKwayisiConnector, access_holdings: int
) -> None:
    """The fixture as saved: 10:17 Lagos, four hours before the close.

    `price_history.close_raw` means the closing price as traded, and migration 0002's
    `no_update` trigger means a wrong one can never be corrected in place - only buried
    under a later vintage. So a mid-session price is not written at all, and the run says
    why. The raw response is cached regardless, which is what makes this cheap: the bars
    can be produced from stored bytes later, and a wrong close cannot be taken back.
    """
    connector = _fixed(registered, _raw())
    with structlog.testing.capture_logs() as logs:
        result = connector.run(db_session)

    assert result.status == "ok", result.error
    assert result.records_parsed == PAGE1_ROWS
    assert result.rows_written == 0
    refused = [e for e in logs if e["event"] == "ngx_snapshot_before_session_close"]
    assert len(refused) == 1
    assert refused[0]["lagos_time"] == "2026-09-24 10:17"
    assert refused[0]["quotes"] == PAGE1_ROWS
    # Scoped to this security, not to the table: `price_history` holds 269,298 rows from
    # the US connectors, so a bare "is the table empty" would pass for the wrong reason.
    assert not db_session.execute(
        select(PriceHistory.date).where(PriceHistory.security_id == access_holdings)
    ).all()


def test_the_declared_licence_matches_the_row_register_writes(
    db_session: Session, registered: AfxKwayisiConnector
) -> None:
    """The licensing gate, and the rate round-trip that would otherwise churn the row.

    `register()` refuses a connector whose stored `redistribution_allowed` disagrees with
    its declared one, and rewrites `rate_limit_per_sec` whenever the two differ. Running it
    twice proves the second call is a no-op rather than a silent update every night.
    """
    licence = registered.declare_licence()
    assert licence.source_name == SOURCE_NAME != "NGX", "the aggregator, not the exchange"
    assert licence.redistribution_allowed is False

    with structlog.testing.capture_logs() as logs:
        register(db_session, registered)
    assert not [e for e in logs if e["event"] == "data_source_rate_limit_updated"], (
        "the declared rate must round-trip through NUMERIC, or the row churns every run"
    )

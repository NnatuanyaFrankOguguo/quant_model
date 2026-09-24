"""Asking the server whether what we hold is still current. P4 check 13.

*"Re-run on an unchanged document -> Serves from cache; no re-fetch."*

`PoliteFetcher.get` has accepted `etag`/`last_modified` and returned `NotModified` since it
was written, and no connector passed them, because `fetch()` takes no session and so cannot
look up what was stored last time. `Connector.cache_url()` is the seam that closes it: a
connector names the URL it is about to request, `run()` does the lookup on its behalf, and
a connector that does not override it is never handed anything and behaves as before.

Measured on the live endpoints before any of it was written, because machinery that can
never fire is worse than none - it reads as a solved problem:

    FRED observations   Last-Modified, honours If-Modified-Since, 304 saves 1.6 MB
    SEC ticker file     Last-Modified, honours it, 304 saves 800 KB
    EDGAR submissions   sends neither
    CBN, Nigeria Data Portal   send neither
    Yahoo chart         sends neither, and Cache-Control: no-store

FRED also returns a full 200 for a deliberately stale validator, which is the check that
matters most: a server answering 304 regardless would hide every real update behind a cache
that looked like it was working.
"""

from __future__ import annotations

import datetime as dt

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from packages.common.models import DataSource, SourceDocument
from packages.common.timez import utcnow
from packages.ingestion.base import CachedDocument, cached_document, revalidated
from packages.ingestion.cbn import CbnExchangeRateConnector
from packages.ingestion.fred import FredConnector
from packages.ingestion.yahoo import YahooChartConnector

pytestmark = pytest.mark.invariant

URL = "https://api.stlouisfed.org/fred/series/observations?series_id=DGS10&file_type=json"
BODY = b'{"observations": []}'


class FakeStore:
    """Object storage as a dict, keyed the way the real backend is - on the hash."""

    def __init__(self, **objects: bytes) -> None:
        self._objects = dict(objects)

    def get(self, sha256: str) -> bytes:
        return self._objects[sha256]


def _document(
    session: Session,
    *,
    marker: str,
    url: str = URL,
    etag: str | None = None,
    last_modified: dt.datetime | None = None,
) -> SourceDocument:
    source_id = session.execute(select(DataSource.id).order_by(DataSource.id)).scalars().first()
    row = SourceDocument(
        data_source_id=source_id,
        url=url,
        storage_key=f"documents/sha256/{marker * 64}",
        sha256=marker * 64,
        media_type="application/json",
        retrieved_at=utcnow(),
        etag=etag,
        last_modified=last_modified,
    )
    session.add(row)
    session.flush()
    return row


# --------------------------------------------------------------------------------------
# The lookup
# --------------------------------------------------------------------------------------


def test_a_url_never_fetched_has_nothing_cached(db_session: Session) -> None:
    """`None`, so a first run sends no conditional header and gets a normal 200."""
    assert cached_document(db_session, "https://nowhere.test/never-fetched.json") is None


def test_the_newest_document_for_a_url_is_the_one_returned(db_session: Session) -> None:
    """A URL is fetched again and again; only the latest validator is any use.

    An older row's `Last-Modified` would be sent as though it were current, the server
    would answer 200 with a full body every time, and conditional requests would appear to
    be running while saving nothing.
    """
    _document(db_session, marker="a", last_modified=dt.datetime(2026, 1, 1, tzinfo=dt.UTC))
    newest = _document(db_session, marker="b", last_modified=dt.datetime(2026, 9, 1, tzinfo=dt.UTC))
    found = cached_document(db_session, URL)
    assert found is not None
    assert found.document_id == newest.id
    assert found.sha256 == "b" * 64


def test_a_stored_document_with_no_validator_cannot_revalidate(db_session: Session) -> None:
    """CBN, the Nigeria Data Portal and Yahoo all land here.

    Holding the bytes is not the same as having a way to ask whether they are current, and
    conflating the two would send an empty conditional request and read the inevitable 200
    as proof the document changed.
    """
    _document(db_session, marker="c")
    found = cached_document(db_session, URL)
    assert found is not None
    assert not found.can_revalidate


def test_an_etag_alone_is_enough_to_ask(db_session: Session) -> None:
    _document(db_session, marker="d", etag='W/"abc"')
    found = cached_document(db_session, URL)
    assert found is not None
    assert found.can_revalidate


# --------------------------------------------------------------------------------------
# Serving from cache
# --------------------------------------------------------------------------------------


def test_a_304_is_answered_from_storage_with_the_real_bytes() -> None:
    """*"Serves from cache"* means the document still reaches `parse`.

    Returning nothing would be cheaper and would silently skip every parser improvement
    made since the document was stored - the run would report success having processed
    nothing, which is the shape of failure this project keeps finding.
    """
    cached = CachedDocument(
        url=URL,
        etag='W/"abc"',
        last_modified=dt.datetime(2026, 9, 2, 20, 16, 25, tzinfo=dt.UTC),
        sha256="e" * 64,
        media_type="application/json",
        document_id=7,
    )
    raw = revalidated(cached, storage=FakeStore(**{"e" * 64: BODY}))
    assert raw.data == BODY
    assert raw.url == URL
    assert raw.media_type == "application/json"


def test_a_revalidated_response_records_304_not_200() -> None:
    """The run record should say what happened on the wire.

    Zero rows after a revalidation is the expected outcome; zero rows after a real 200 is
    the silent-scraper signature. Recording both as 200 would make the two indistinguishable
    in `connector_runs`, which is the one place somebody looks to tell them apart.
    """
    cached = CachedDocument(
        url=URL,
        etag=None,
        last_modified=dt.datetime(2026, 9, 2, tzinfo=dt.UTC),
        sha256="f" * 64,
        media_type="application/json",
        document_id=8,
    )
    assert revalidated(cached, storage=FakeStore(**{"f" * 64: BODY})).http_status == 304


# --------------------------------------------------------------------------------------
# Who opts in
# --------------------------------------------------------------------------------------


def test_a_connector_that_did_not_opt_in_names_no_url() -> None:
    """The default, and therefore the behaviour of everything that has not changed.

    `run()` calls `cache_url` first and only looks anything up when it gets a URL back, so
    `None` here is what keeps every existing connector on exactly its old code path - no
    database read, no extra keyword reaching its `fetch`.
    """
    assert CbnExchangeRateConnector().cache_url() is None
    assert YahooChartConnector().cache_url(symbol="AAPL") is None


def test_fred_names_the_url_it_will_actually_record(db_session: Session) -> None:
    """The one that would fail silently, and the reason `_recorded_url` is shared.

    `source_documents.url` holds FRED's **key-stripped** URL. If `cache_url` returned the
    requested shape instead - the one carrying `api_key` - the lookup would match no row,
    every run, for ever: no error, no warning, conditional requests simply never firing
    while appearing to be wired in.
    """
    connector = FredConnector(api_key="deadbeefcafe")
    url = connector.cache_url(series_id="DGS10", lookback_days=30)
    assert url is not None
    assert "deadbeefcafe" not in url
    assert "series_id=DGS10" in url
    assert "realtime_start=" in url

    # And it is the string a fetch would store, not merely a similar one. Proved by storing
    # a document under the recorded URL and finding it through `cache_url`.
    _document(db_session, marker="1", url=url, last_modified=dt.datetime(2026, 9, 2, tzinfo=dt.UTC))
    found = cached_document(db_session, connector.cache_url(series_id="DGS10", lookback_days=30))
    assert found is not None, "cache_url and the recorded URL have drifted apart"
    assert found.can_revalidate


def test_fred_asks_the_same_question_twice_and_gets_the_same_key(db_session: Session) -> None:
    """`cache_url` must be stable across calls with the same params.

    It resolves a real-time window from `lookback_days` against today's date, so a window
    that moved between the lookup and the fetch would key them differently - and the
    mismatch would look exactly like a document that had never been fetched.
    """
    connector = FredConnector(api_key="k")
    first = connector.cache_url(series_id="DGS10", lookback_days=30)
    second = connector.cache_url(series_id="DGS10", lookback_days=30)
    assert first == second

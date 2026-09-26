"""P5.1 - RSS news ingestion, against saved copies of the real feeds.

Every fixture in `tests/fixtures/rss/` is bytes a live server actually sent on 2026-09-24,
trimmed to its first few items and otherwise untouched. That matters more here than for
most connectors: the defects this file tests for are things real feeds *do*, and a
hand-written feed would only ever contain the defects the author already knew about.

What each fixture is for:

* `nairametrics_feed_trimmed.xml` - WordPress RSS 2.0, the ordinary case, with a
  `<guid isPermaLink="false">` that is a post id rather than the article's URL.
* `businessday_feed_trimmed.xml` - the same shape from a different publisher, with an
  `<img>` inside the summary and five categories on one item.
* `punch_latest_news_trimmed.xml` - every link and guid decorated with
  `?utm_source=rss.punchng.com&utm_medium=web`, and `<category><![CDATA[]]></category>`:
  an element that exists and labels nothing.
* `punch_business_empty.xml` - **200 OK, well formed, zero items.** This is what
  `rss.punchng.com/v1/category/business` actually served, and it is the best example this
  repository has of the silent failure `OPERATIONS.md` §2.3 is about.
* `edgar_filings_atom_trimmed.xml` - a real Atom feed, for the company-filing shape
  `DATA_FOUNDATION.md` §D expects the IR feeds to arrive in. It carries the three things
  that make Atom different from RSS: a link in an attribute, a non-URL `<id>`, and a
  category in a `term=`. It also carries a trap - a structured `<content type="text/xml">`
  block whose text is filing metadata, not prose.
"""

from __future__ import annotations

import datetime as dt
from pathlib import Path

import httpx
import pytest
from sqlalchemy import func, select, text
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.orm import Session

from packages.common.models import DataSource, NewsItem, SourceDocument
from packages.common.storage import LocalDiskBackend
from packages.ingestion import base as base_module
from packages.ingestion.base import CachedDocument, RawResponse
from packages.ingestion.polite import PoliteFetcher
from packages.ingestion.rss import (
    FEEDS,
    MalformedFeedError,
    NewsFeed,
    RssNewsConnector,
    canonical_url,
    feed_connectors,
    strip_markup,
)

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "rss"

#: Comfortably after every fixture's newest item, so nothing is dropped as post-dated by
#: accident. The one test that *wants* that branch sets its own.
FETCHED_AT = dt.datetime(2026, 9, 25, 0, 0, tzinfo=dt.UTC)


def _raw(
    name: str,
    *,
    feed_key: str = "nairametrics",
    retrieved_at: dt.datetime = FETCHED_AT,
    data: bytes | None = None,
) -> RawResponse:
    """A fixture as the response it came back in."""
    return RawResponse(
        data=data if data is not None else (FIXTURES / name).read_bytes(),
        media_type="application/rss+xml",
        url=FEEDS[feed_key].feed_url,
        http_status=200,
        retrieved_at=retrieved_at,
    )


def _parse(name: str, *, feed_key: str = "nairametrics", **kwargs: object) -> list:
    return RssNewsConnector(FEEDS[feed_key]).parse(_raw(name, feed_key=feed_key, **kwargs))  # type: ignore[arg-type]


# --------------------------------------------------------------------------------------
# The fixtures are real, and the tests below are therefore not vacuous
# --------------------------------------------------------------------------------------


def test_the_fixtures_are_the_feeds_they_claim_to_be() -> None:
    """Every assertion in this file would pass over an empty list. So count first.

    This is the same guard `test_politeness_invariants.py` opens with, for the same
    reason: a fixture that silently stopped being a feed - a renamed directory, a botched
    trim - would turn this whole file green while testing nothing at all.
    """
    for name, expected in [
        ("nairametrics_feed_trimmed.xml", 3),
        ("businessday_feed_trimmed.xml", 3),
        ("punch_latest_news_trimmed.xml", 3),
        ("edgar_filings_atom_trimmed.xml", 2),
    ]:
        assert (FIXTURES / name).exists(), f"{name} is missing"
        assert (
            b"<item" in (FIXTURES / name).read_bytes()
            or b"<entry" in (FIXTURES / name).read_bytes()
        ), f"{name} contains no items"
        assert len(_parse(name)) == expected, f"{name} did not parse to {expected} items"


# --------------------------------------------------------------------------------------
# Reading an ordinary feed
# --------------------------------------------------------------------------------------


def test_a_wordpress_item_parses_whole() -> None:
    """Headline, prose summary, categories and a publication instant, from one item."""
    first = _parse("nairametrics_feed_trimmed.xml")[0]
    assert first.headline.startswith("Nigeria")
    assert "raw material trade balance" in first.headline
    # The apostrophe arrived as `&#8217;` and must come out as a character.
    assert "&#" not in first.headline and "&amp;" not in first.headline
    assert first.body is not None and first.body.startswith("Nigeria recorded")
    assert first.categories == ("Economy",)
    assert first.published_at == dt.datetime(2026, 9, 24, 9, 6, 18, tzinfo=dt.UTC)
    assert first.url_canonical.startswith("https://nairametrics.com/2026/09/24/")


def test_markup_inside_a_summary_does_not_become_part_of_the_sentence() -> None:
    """BusinessDay opens every summary with an `<img>` tag and a wall of attributes.

    Left in, a sentiment model reads `class="attachment-large size-large"` as English and
    a Telegram message shows the reader an image tag.
    """
    first = _parse("businessday_feed_trimmed.xml", feed_key="businessday")[0]
    assert first.body is not None
    assert "<img" not in first.body and "wp-post-image" not in first.body
    assert first.body.startswith("ASKY has announced the return to service")


def test_several_categories_on_one_item_are_all_kept_in_order() -> None:
    second = _parse("businessday_feed_trimmed.xml", feed_key="businessday")[1]
    assert second.categories[:2] == ("News", "bdothernews")
    assert "SEDC" in second.categories


def test_a_category_element_with_no_label_contributes_nothing() -> None:
    """Punch sends `<category><![CDATA[]]></category>` on every item.

    An empty string in the array would be a label that is not a label, and every query
    grouping by category would grow a phantom bucket.
    """
    for record in _parse("punch_latest_news_trimmed.xml", feed_key="punch"):
        assert record.categories == ()


def test_parse_is_deterministic() -> None:
    """`docs/08` §5 rule 3 - the property that makes a stored raw response worth keeping."""
    raw = _raw("businessday_feed_trimmed.xml", feed_key="businessday")
    connector = RssNewsConnector(FEEDS["businessday"])
    assert connector.parse(raw) == connector.parse(raw)


# --------------------------------------------------------------------------------------
# Identity: what makes two fetches the same article
# --------------------------------------------------------------------------------------


def test_campaign_parameters_never_reach_identity() -> None:
    """Every Punch link and guid carries `utm_source=rss.punchng.com`.

    Left in the key, the day Punch renames that campaign the entire feed re-inserts as new
    articles and a brief reports the same news twice. The raw `url` keeps them, because
    what the feed said is provenance.
    """
    first = _parse("punch_latest_news_trimmed.xml", feed_key="punch")[0]
    assert "utm_source" in first.url, "the URL as served must be preserved verbatim"
    assert "utm_" not in first.url_canonical
    assert "utm_" not in first.item_key
    assert first.item_key == first.url_canonical


def test_a_wordpress_guid_is_the_key_rather_than_the_slug() -> None:
    """`<guid isPermaLink="false">https://nairametrics.com/?p=550279</guid>`.

    The guid is the post id and survives a slug rewrite; the link does not. Keying on the
    link would store the article a second time the day an editor fixes a typo in the URL.
    """
    first = _parse("nairametrics_feed_trimmed.xml")[0]
    assert first.item_key == "https://nairametrics.com/?p=550279"
    assert first.item_key != first.url_canonical


def test_the_same_words_from_two_publishers_hash_the_same() -> None:
    """`content_hash` is over the text only, so a syndicated story is findable.

    The rows are still separate - attribution and the licence governing our copy are per
    publisher - but P5.4 has to be able to ask "have we already printed this?" without
    comparing prose. Parsing one publisher's bytes under another's feed is the honest way
    to assert that the hash ignores everything except the words.
    """
    as_nairametrics = _parse("nairametrics_feed_trimmed.xml", feed_key="nairametrics")
    as_punch = _parse("nairametrics_feed_trimmed.xml", feed_key="punch")
    assert [r.content_hash for r in as_nairametrics] == [r.content_hash for r in as_punch]
    assert as_nairametrics[0].feed_key != as_punch[0].feed_key


def test_an_edited_headline_is_a_different_version() -> None:
    """A newsroom rewriting a headline must not silently overwrite what the market read.

    The bytes are the real feed with one word changed, which is exactly what the second
    poll of an edited article looks like.
    """
    original = (FIXTURES / "nairametrics_feed_trimmed.xml").read_bytes()
    edited = original.replace(b"swings to a N466.79 billion surplus", b"swings to a surplus", 1)
    assert edited != original, "the fixture no longer contains the headline being edited"

    before = _parse("nairametrics_feed_trimmed.xml")[0]
    after = RssNewsConnector(FEEDS["nairametrics"]).parse(
        _raw("nairametrics_feed_trimmed.xml", data=edited)
    )[0]
    assert after.item_key == before.item_key, "it is still the same article"
    assert after.content_hash != before.content_hash, "and it is a new version of it"


# --------------------------------------------------------------------------------------
# The two dates, which are not interchangeable
# --------------------------------------------------------------------------------------


def test_published_and_retrieved_are_different_facts() -> None:
    """`docs/08` §1.3: `retrieved_at` is provenance and never a feature join.

    They come from different places on purpose - the feed states one and the response
    carries the other - so a parser that quietly used the fetch time for both would be
    caught here rather than in a backtest.
    """
    records = _parse("nairametrics_feed_trimmed.xml")
    assert all(r.retrieved_at == FETCHED_AT for r in records)
    assert all(r.published_at < r.retrieved_at for r in records)
    assert len({r.published_at for r in records}) == len(records), "each item has its own time"


def test_an_item_published_after_we_fetched_it_is_dropped(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """A post-dated item is a scheduled post or a clock error, and never news.

    Storing it would let a brief announce something that has not happened, and give it a
    `known_as_of` in the future - the one value that turns a point-in-time table into a
    lookahead generator. The whole real feed is re-read as though we had fetched it an
    hour before its newest items, which is precisely the clock-skew case.
    """
    early = dt.datetime(2026, 9, 24, 8, 45, tzinfo=dt.UTC)
    records = _parse("nairametrics_feed_trimmed.xml", retrieved_at=early)
    assert len(records) < 3, "the two items published after 08:45 should be gone"
    assert all(r.published_at <= early for r in records)
    output = capsys.readouterr().out
    assert "rss_item_published_after_it_was_fetched" in output
    assert "rss_items_skipped" in output, "a dropped item must be counted out loud"


def test_an_offset_is_converted_rather_than_ignored() -> None:
    """EDGAR's Atom stamps `2026-09-01T16:30:35-04:00`. Stored UTC is 20:30:35.

    Dropping the offset would put the article four hours early, which is four hours of
    knowledge nobody had.
    """
    records = RssNewsConnector(_atom_feed()).parse(_atom_raw())
    assert records[0].published_at == dt.datetime(2026, 9, 1, 20, 30, 35, tzinfo=dt.UTC)
    assert records[0].published_at.tzinfo is dt.UTC


# --------------------------------------------------------------------------------------
# The silent failure: 200 OK with nothing in it
# --------------------------------------------------------------------------------------


def test_the_empty_punch_business_feed_parses_to_nothing_and_says_so(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """These are the exact bytes `rss.punchng.com/v1/category/business` served.

    `OPERATIONS.md` §2.3's failure in one fixture: the page loads, the parser runs, the
    document is well formed, and there is nothing in it. `run()` will warn about the zero
    rows; this says which of the two zeroes it was, because a feed with no items and a
    parser that matched no items are different faults with one symptom.
    """
    records = _parse("punch_business_empty.xml", feed_key="punch")
    assert records == []
    assert "rss_feed_carried_no_items" in capsys.readouterr().out


# --------------------------------------------------------------------------------------
# Malformed XML, which is the normal condition of RSS in the wild
# --------------------------------------------------------------------------------------


def test_a_byte_order_mark_does_not_lose_the_feed() -> None:
    """A BOM or a blank line before `<?xml` fails every conforming parser.

    "XML or text declaration not at start of entity" is the message, and the feed is
    perfectly good. Losing a publisher to it would be absurd, so it is stripped.
    """
    original = (FIXTURES / "nairametrics_feed_trimmed.xml").read_bytes()
    assert len(_parse("nairametrics_feed_trimmed.xml", data=b"\xef\xbb\xbf\n  " + original)) == 3


def test_a_doctype_is_refused_rather_than_expanded() -> None:
    """`xml.etree` fetches no external entity but does expand an internal one.

    That is the billion-laughs shape, and no feed needs a doctype to be a feed, so one is
    a refusal. Refused loudly: a run that swallowed it would report `ok` with zero rows.
    """
    original = (FIXTURES / "nairametrics_feed_trimmed.xml").read_bytes()
    poisoned = original.replace(b"<?xml version", b'<!DOCTYPE rss [<!ENTITY a "x">]><?xml version')
    with pytest.raises(MalformedFeedError, match="DOCTYPE"):
        _parse("nairametrics_feed_trimmed.xml", data=poisoned)


def test_an_article_that_quotes_a_doctype_is_not_mistaken_for_one() -> None:
    """A doctype is only a doctype in the prolog. Anywhere else it is prose.

    A feed carrying a tech story about HTML would otherwise be refused wholesale, which
    is a worse outcome than the one the refusal exists to prevent - and it would look
    exactly like the publisher having broken their feed.
    """
    original = (FIXTURES / "nairametrics_feed_trimmed.xml").read_bytes()
    quoting = original.replace(b"<p>Nigeria recorded", b"<p>The tag &lt;!DOCTYPE html&gt; and", 1)
    assert quoting != original, "the fixture no longer contains the summary being edited"
    records = _parse("nairametrics_feed_trimmed.xml", data=quoting)
    assert len(records) == 3
    assert records[0].body is not None and "DOCTYPE" in records[0].body


def test_a_truncated_feed_raises_rather_than_returning_nothing() -> None:
    """Half a response is a failure, and a failure that returns `[]` is recorded as `ok`.

    `OPERATIONS.md` §2.3 again: `status='ok'` with zero rows is the signature this project
    keeps finding, so a document that is not a document must raise and be recorded as the
    error it is.
    """
    half = (FIXTURES / "businessday_feed_trimmed.xml").read_bytes()[:2000]
    with pytest.raises(MalformedFeedError, match="not parseable as XML"):
        _parse("businessday_feed_trimmed.xml", feed_key="businessday", data=half)


def test_an_encoding_the_feed_does_not_have_is_re_read_leniently(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """A declared encoding Python has never heard of raises `LookupError` on the bytes path.

    Feeds declare junk encodings, and one bad attribute must not cost a publisher. The
    retry drops the declaration and reads UTF-8, and says out loud that it had to.
    """
    original = (FIXTURES / "nairametrics_feed_trimmed.xml").read_bytes()
    lying = original.replace(b'encoding="UTF-8"', b'encoding="utf8mb4"', 1)
    assert lying != original, "the fixture no longer declares the encoding being broken"
    assert len(_parse("nairametrics_feed_trimmed.xml", data=lying)) == 3
    assert "rss_feed_needed_a_lenient_reparse" in capsys.readouterr().out


def test_an_empty_body_is_not_an_empty_feed() -> None:
    """Zero bytes is a failure with a different message, because it is a different fault."""
    with pytest.raises(MalformedFeedError, match="empty response body"):
        _parse("nairametrics_feed_trimmed.xml", data=b"")


# --------------------------------------------------------------------------------------
# Atom, for the company IR feeds that come next
# --------------------------------------------------------------------------------------


def _atom_feed() -> NewsFeed:
    """A feed record for the Atom fixture. Not in `FEEDS` - nothing ingests it yet."""
    return NewsFeed(
        key="edgar_atom",
        source_name="SEC EDGAR",
        feed_url="https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&output=atom",
        base_url="https://www.sec.gov",
        attribution_text="Source: SEC EDGAR",
        sends_validators=False,
        terms_url=None,
        notes="Fixture only: the Atom shape company IR feeds use.",
    )


def _atom_raw() -> RawResponse:
    return RawResponse(
        data=(FIXTURES / "edgar_filings_atom_trimmed.xml").read_bytes(),
        media_type="application/atom+xml",
        url=_atom_feed().feed_url,
        http_status=200,
        retrieved_at=FETCHED_AT,
    )


def test_atom_entries_parse_beside_rss_items() -> None:
    """Three things Atom does differently, all of them in this one real document.

    The link is an attribute rather than text, the id is a `urn:` and not a URL, and the
    category label lives in `term=`. A parser written against RSS alone returns nothing
    here, and returns it quietly.
    """
    records = RssNewsConnector(_atom_feed()).parse(_atom_raw())
    assert len(records) == 2
    first = records[0]
    assert first.url.startswith("https://www.sec.gov/Archives/edgar/data/320193/")
    assert first.item_key == "urn:tag:sec.gov,2008:accession-number=0001140361-26-035325"
    assert first.categories == ("8-K/A",)
    assert first.headline.startswith("8-K/A")


def test_a_structured_content_block_does_not_become_the_body() -> None:
    """EDGAR's `<content type="text/xml">` holds filing metadata, not prose.

    Read as a summary it yields an accession number and a file size glued together, which
    a sentiment model would happily score. `<summary>` is asked first for exactly this.
    """
    first = RssNewsConnector(_atom_feed()).parse(_atom_raw())[0]
    assert first.body is not None
    assert first.body.startswith("Filed: 2026-09-01")
    assert "ELECTRONIC COMPUTERS" not in first.body


# --------------------------------------------------------------------------------------
# The small pure functions
# --------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("given", "expected", "why"),
    [
        (
            "https://punchng.com/a/?utm_source=rss&utm_medium=web",
            "https://punchng.com/a/",
            "campaign parameters are not the article",
        ),
        (
            "https://EXAMPLE.com:443/a?b=2&a=1",
            "https://example.com/a?a=1&b=2",
            "host case, a default port and parameter order are not identity either",
        ),
        (
            "https://example.com/a#comments",
            "https://example.com/a",
            "a fragment is a place in the page, not another page",
        ),
        (
            "https://example.com/a/",
            "https://example.com/a/",
            "the trailing slash is left alone - it is one page on most servers and two on "
            "some, and guessing costs either a duplicate or a merge",
        ),
        (
            "urn:tag:sec.gov,2008:accession-number=1",
            "urn:tag:sec.gov,2008:accession-number=1",
            "an id that is not a URL comes back unmangled",
        ),
    ],
)
def test_canonical_url(given: str, expected: str, why: str) -> None:
    assert canonical_url(given) == expected, why


def test_strip_markup_handles_the_double_escaping_wordpress_emits() -> None:
    """`&amp;#8217;` is a real thing a feed sends, and one pass leaves `&#8217;` in the text."""
    assert strip_markup("<p>Nigeria&amp;#8217;s banks</p>") == "Nigeria’s banks"


def test_strip_markup_discards_script_content_rather_than_reading_it() -> None:
    assert strip_markup("<p>Real text</p><script>var x = 1;</script>") == "Real text"


# --------------------------------------------------------------------------------------
# The fetch path: politeness, conditional requests, and what gets recorded
# --------------------------------------------------------------------------------------


class Clock:
    """Time only moves when something sleeps, so a slow rate costs the test nothing."""

    def __init__(self) -> None:
        self.seconds = 0.0
        self.slept: list[float] = []

    def now(self) -> float:
        return self.seconds

    def sleep(self, seconds: float) -> None:
        self.slept.append(seconds)
        self.seconds += seconds


def _answer(status: int, body: bytes = b"", *, url: str) -> httpx.Response:
    """A canned response. `request=` matters: `raise_for_status` refuses one without it."""
    return httpx.Response(status, content=body, request=httpx.Request("GET", url))


def _responses(*canned: httpx.Response) -> object:
    """A transport that answers `robots.txt` permissively and then serves `canned` in order.

    Robots is answered rather than disabled, so the real `_robots_allows` path runs - it
    is the first thing `_send` does and the one most likely to stop a new connector.
    """
    queue = list(canned)

    def transport(url: str, **kwargs: object) -> httpx.Response:
        if url.endswith("/robots.txt"):
            return _answer(200, b"User-agent: *\nDisallow:\n", url=url)
        transport.sent.append((url, kwargs))  # type: ignore[attr-defined]
        if not queue:
            raise AssertionError(f"transport asked {url} with no answer left")
        return queue.pop(0)

    transport.sent = []  # type: ignore[attr-defined]
    return transport


def test_fetch_spends_the_declared_rate_and_delay() -> None:
    """The declared figures must reach the wire, not sit in `data_sources` as documentation.

    `DATA_FOUNDATION.md` §3.5 asks for 1 request per 2-5 seconds per domain and
    `tests/unit/test_politeness_invariants.py` asserts the declaration; this asserts that
    the declaration is what the fetcher actually waits.
    """
    clock = Clock()
    body = (FIXTURES / "nairametrics_feed_trimmed.xml").read_bytes()
    url = FEEDS["nairametrics"].feed_url
    transport = _responses(_answer(200, body, url=url), _answer(200, body, url=url))
    fetcher = PoliteFetcher(
        user_agent="test/0.1 (nobody@example.com)",
        transport=transport,  # type: ignore[arg-type]
        now=clock.now,
        sleep=clock.sleep,
    )
    connector = RssNewsConnector(FEEDS["nairametrics"], fetcher=fetcher)
    connector.fetch()
    connector.fetch()
    assert sum(clock.slept) >= 4.0, "two requests, at least two seconds apart each"
    assert clock.slept.count(2.0) == 2, "the politeness delay is applied per request"


def test_fetch_identifies_itself_with_a_contact_address() -> None:
    """A source that wants to complain before blocking us needs somewhere to complain to.

    `PoliteFetcher` refuses a User-Agent with no `@` in it, so this is really a test that
    the connector uses the shared fetcher rather than reaching for httpx itself.
    """
    connector = RssNewsConnector(FEEDS["nairametrics"])
    assert "@" in connector._fetcher.user_agent
    assert "quant_model" in connector._fetcher.user_agent


def test_only_the_feeds_that_answer_a_conditional_request_ask_one() -> None:
    """`Connector.cache_url` - opting in against a source that sends no validator costs a
    database read per run and saves nothing.

    Measured on the live hosts: Nairametrics and BusinessDay send ETag and Last-Modified;
    Punch sends neither and `Cache-Control: no-store` besides.
    """
    by_key = {connector.feed.key: connector for connector in feed_connectors()}
    assert by_key["nairametrics"].cache_url() == FEEDS["nairametrics"].feed_url
    assert by_key["businessday"].cache_url() == FEEDS["businessday"].feed_url
    assert by_key["punch"].cache_url() is None


def test_a_304_serves_the_bytes_we_already_hold(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The point of storing a validator: an unchanged feed transfers no body.

    The stored bytes still go through `parse`, so a parser improvement is never skipped
    because the source had nothing new to say, and `http_status` is 304 rather than 200 so
    the run record says what actually happened - zero rows after a revalidation is
    expected, and after a real 200 it is the silent-scraper signature.
    """
    storage = LocalDiskBackend(tmp_path)
    monkeypatch.setattr(base_module, "get_storage", lambda: storage)
    body = (FIXTURES / "nairametrics_feed_trimmed.xml").read_bytes()
    stored = storage.put(body, media_type="application/rss+xml")

    clock = Clock()
    fetcher = PoliteFetcher(
        user_agent="test/0.1 (nobody@example.com)",
        transport=_responses(_answer(304, url=FEEDS["nairametrics"].feed_url)),  # type: ignore[arg-type]
        now=clock.now,
        sleep=clock.sleep,
    )
    connector = RssNewsConnector(FEEDS["nairametrics"], fetcher=fetcher)
    cached = CachedDocument(
        url=FEEDS["nairametrics"].feed_url,
        etag='W/"cee1f8c8"',
        last_modified=None,
        sha256=stored.sha256,
        media_type="application/rss+xml",
        document_id=1,
    )
    raw = connector.fetch(cached=cached)
    assert raw.http_status == 304
    assert raw.data == body
    assert len(connector.parse(raw)) == 3, "a revalidated feed is still parsed"


def test_every_registered_feed_is_https_and_named() -> None:
    """A feed fetched over http is a feed anyone on the path can rewrite."""
    for key, feed in FEEDS.items():
        assert feed.key == key
        assert feed.feed_url.startswith("https://"), feed.feed_url
        assert feed.source_name and feed.attribution_text


# --------------------------------------------------------------------------------------
# Writing: deduplication, versioning, and the constraints that outlive this code
# --------------------------------------------------------------------------------------


def _source_document(session: Session, *, marker: str) -> SourceDocument:
    """A stored feed response for the news rows to point at. Provenance is NOT NULL."""
    source_id = session.execute(
        select(DataSource.id).where(DataSource.source_name == "Nairametrics")
    ).scalar_one()
    row = SourceDocument(
        data_source_id=source_id,
        url=FEEDS["nairametrics"].feed_url,
        storage_key=f"documents/sha256/{marker * 64}",
        sha256=marker * 64,
        media_type="application/rss+xml",
        retrieved_at=FETCHED_AT,
    )
    session.add(row)
    session.flush()
    return row


def _write(session: Session, records: list, *, marker: str) -> int:
    document = _source_document(session, marker=marker)
    return RssNewsConnector(FEEDS["nairametrics"]).write(
        session, records, source_document_id=document.id
    )


def test_the_register_row_for_every_implemented_feed_exists(db_session: Session) -> None:
    """Migration 0025 seeds them, and `register()` refuses a connector without one.

    Asserted before anything else here writes: a missing row makes every test below fail
    with a foreign-key error that says nothing about the licensing register being the
    precondition it is.
    """
    for feed in FEEDS.values():
        row = db_session.execute(
            select(DataSource).where(DataSource.source_name == feed.source_name)
        ).scalar_one()
        assert row.redistribution_allowed is False, "an RSS feed is not a copyright licence"
        assert row.attribution_required is True
        assert row.expected_run_interval_hours == 3, "hourly, plus 0024's two-hour grace"


def test_an_unchanged_feed_polled_again_writes_nothing(db_session: Session) -> None:
    """The ordinary case, and the one that would otherwise grow the table by 24x a day."""
    records = _parse("nairametrics_feed_trimmed.xml")
    first = _write(db_session, records, marker="a")
    assert first == 3, "the fixture must land before the next assertion means anything"
    assert _write(db_session, records, marker="b") == 0


def test_an_edited_article_is_a_second_row_and_the_first_survives(db_session: Session) -> None:
    """`CLAUDE.md`: no silent overwrites. Applied to text.

    The evening rewrite of a morning headline is not a correction of what the market read
    at 09:00, and a schema that made it an UPDATE would destroy the only record of it.
    """
    original = (FIXTURES / "nairametrics_feed_trimmed.xml").read_bytes()
    edited = original.replace(b"swings to a N466.79 billion surplus", b"swings to a surplus", 1)
    assert _write(db_session, _parse("nairametrics_feed_trimmed.xml"), marker="c") == 3
    assert (
        _write(
            db_session,
            RssNewsConnector(FEEDS["nairametrics"]).parse(
                _raw("nairametrics_feed_trimmed.xml", data=edited)
            ),
            marker="d",
        )
        == 1
    ), "only the edited item is new"

    versions = (
        db_session.execute(
            select(NewsItem.headline)
            .where(NewsItem.item_key == "https://nairametrics.com/?p=550279")
            .order_by(NewsItem.id)
        )
        .scalars()
        .all()
    )
    assert len(versions) == 2
    assert "N466.79 billion surplus" in versions[0], "the words the market actually read"
    assert "N466.79 billion surplus" not in versions[1]


def test_the_same_item_twice_in_one_response_is_written_once(db_session: Session) -> None:
    """A feed listing an item twice is common, and `ON CONFLICT` arbitrates against
    committed rows rather than against the statement's own."""
    records = _parse("nairametrics_feed_trimmed.xml")
    assert _write(db_session, records + records, marker="e") == 3


def test_updating_a_news_row_is_refused_by_the_database(db_session: Session) -> None:
    """`docs/08` §2.16 - application code can be bypassed at 1am by a person with `psql`."""
    assert _write(db_session, _parse("nairametrics_feed_trimmed.xml"), marker="f") == 3
    with pytest.raises(DBAPIError, match="UPDATE forbidden"):
        db_session.execute(text("UPDATE news_items SET headline = 'rewritten'"))
    db_session.rollback()


def test_known_as_of_is_the_lagos_date_of_publication(db_session: Session) -> None:
    """Generated, not written, so it cannot disagree with `published_at`.

    The interesting row is the one published at 23:30 UTC: it is already tomorrow in
    Lagos, and `docs/08` §1.3 says a plain `DATE` in this schema is a calendar date in the
    market's own local time. Taking the UTC date would put the article a day early for
    part of every night.
    """
    document = _source_document(db_session, marker="g")
    db_session.execute(
        text(
            "INSERT INTO news_items (data_source_id, source_document_id, item_key, url, "
            "url_canonical, headline, published_at, retrieved_at, content_hash) VALUES "
            "(:s, :d, :k, :u, :u, :h, :p, :r, :c)"
        ),
        {
            "s": document.data_source_id,
            "d": document.id,
            "k": "late-night",
            "u": "https://nairametrics.com/late-night/",
            "h": "Published at half past eleven, UTC",
            "p": dt.datetime(2026, 9, 24, 23, 30, tzinfo=dt.UTC),
            "r": FETCHED_AT,
            "c": "0" * 64,
        },
    )
    known = db_session.execute(
        select(NewsItem.known_as_of).where(NewsItem.item_key == "late-night")
    ).scalar_one()
    assert known == dt.date(2026, 9, 25), "23:30 UTC is 00:30 the next day in Lagos"


def test_a_blank_body_is_refused_and_an_absent_one_is_not(db_session: Session) -> None:
    """The `IS NULL OR` form, tested from both sides.

    Migration 0021 is this repository's record of a CHECK written the short way, which
    admitted every NULL because a NULL predicate is not FALSE. A bare `btrim(body) <> ''`
    here would reject nothing it was written to reject and accept the one value - `''` -
    that a feed actually sends for an absent summary.
    """
    document = _source_document(db_session, marker="h")
    insert = text(
        "INSERT INTO news_items (data_source_id, source_document_id, item_key, url, "
        "url_canonical, headline, body, published_at, retrieved_at, content_hash) VALUES "
        "(:s, :d, :k, :u, :u, :h, :b, :p, :r, :c)"
    )
    common = {
        "s": document.data_source_id,
        "d": document.id,
        "u": "https://nairametrics.com/x/",
        "h": "A headline",
        "p": dt.datetime(2026, 9, 24, 9, 0, tzinfo=dt.UTC),
        "r": FETCHED_AT,
    }
    db_session.execute(insert, {**common, "k": "null-body", "b": None, "c": "1" * 64})
    assert (
        db_session.execute(
            select(func.count()).select_from(NewsItem).where(NewsItem.item_key == "null-body")
        ).scalar_one()
        == 1
    ), "a feed that carries no summary carries no summary"

    with pytest.raises(IntegrityError, match="news_body_is_absent_or_present"):
        db_session.execute(insert, {**common, "k": "blank-body", "b": "   ", "c": "2" * 64})
    db_session.rollback()


def test_an_article_cannot_have_been_fetched_before_it_was_published(
    db_session: Session,
) -> None:
    """The parser drops these; this is the floor under the parser.

    A `published_at` in the future is a `known_as_of` in the future, and a point-in-time
    table that admits one has stopped being a point-in-time table.
    """
    document = _source_document(db_session, marker="i")
    with pytest.raises(IntegrityError, match="news_published_before_retrieved"):
        db_session.execute(
            text(
                "INSERT INTO news_items (data_source_id, source_document_id, item_key, url, "
                "url_canonical, headline, published_at, retrieved_at, content_hash) VALUES "
                "(:s, :d, :k, :u, :u, :h, :p, :r, :c)"
            ),
            {
                "s": document.data_source_id,
                "d": document.id,
                "k": "tomorrow",
                "u": "https://nairametrics.com/tomorrow/",
                "h": "News from tomorrow",
                "p": dt.datetime(2026, 9, 26, 9, 0, tzinfo=dt.UTC),
                "r": FETCHED_AT,
                "c": "3" * 64,
            },
        )
    db_session.rollback()

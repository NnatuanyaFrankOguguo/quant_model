"""RSS news ingestion - the only source that actually covers this market. P5.1.

`docs/03` P5.1 and `DATA_FOUNDATION.md` §D. The finding that puts this file here rather
than a news API client is quoted verbatim in the roadmap: *"None explicitly confirm
Nigerian-source coverage; Finnhub free is US-only; Alpha Vantage lists only NA/Europe/APAC."*
Free RSS is not the budget option for Nigeria - it is the option that covers the market.

One class, :class:`RssNewsConnector`, constructed with the :class:`NewsFeed` it serves, in
the shape `FredConnector` already uses for one class over many series. Each feed is one
`run()`: one fetch, one stored document, one parse, one write, one `connector_runs` row.

## What was checked on the live sites, on 2026-09-24

`robots.txt` was read for every candidate, as us, through the same transport
`PoliteFetcher` uses - `urllib`'s own reader is answered 403 by hosts that block unfamiliar
clients and stores that as `disallow_all`, which `polite.py`'s docstring explains at length.

| Host | robots.txt | Crawl-delay | Validators |
|---|---|---|---|
| `nairametrics.com` | `User-agent: *` / `Disallow:` - all allowed | none | ETag, Last-Modified |
| `businessday.ng` | allowed; `/search/`, `/?s=`, wp-login denied | none | ETag, Last-Modified |
| `punchng.com` | allowed; `/search/`, `/*?s=`, `/*noamp=` denied | none | - |
| `rss.punchng.com` | `User-agent: *` / `Disallow:` - all allowed | none | none, `no-store` |
| `www.reuters.com` | `Allow: /plus/` then `Disallow: /` - **refused** | none | - |
| `www.proshare.co` | `User-agent: *` / `Disallow:` - all allowed | none | no feed exists |

No host publishes a `Crawl-delay`, so nothing lowers the rate below what this connector
declares. `PoliteFetcher._rate_for` would apply one automatically if a host ever adds it,
and it only ever slows us down.

**Two feeds `docs/03` P5.1 names are not implemented, and neither is an oversight.**
Reuters disallows every path except `/plus/` to this client, so `PoliteFetcher` raises
`RobotsRefusedError` before the first request - that is the correct outcome and not one to
route around. Proshare publishes no feed at all: no `<link rel="alternate">` on the
homepage, and `/rss` and `/feed` both answer the site's own 404 page **with HTTP 200**,
which is the silent-failure shape this project keeps finding - an unwary fetcher would
store that page forever and report success. TheCable, the obvious substitute from
`DATA_FOUNDATION.md` §A, answers 403 to our User-Agent, and a 403 is terminal in
`polite.py` because repeating one is how a refusal becomes an IP block.

**Punch's business feed is empty.** The site declares it at
`punchng.com/topics/business/feed/`, which 302s to `rss.punchng.com/v1/category/latest_news`
- the RSS host drops the category on the way. The category-scoped URL does exist and served
a well-formed feed with **zero items**. So this connector takes Punch's general feed and
leaves scope to P5.2's tagging, because a connector pointed at a permanently empty feed
would warn `connector_wrote_no_rows` every hour forever, and an alert that is always on is
an alert nobody reads. `tests/unit/test_rss.py` keeps that empty feed as a fixture: it is
the best example this repository has of 200 OK with nothing in it.

## Identity, and why it is not the URL

The same article arrives again in every poll, and the same words arrive from more than one
place. Three rules, and they are the whole of deduplication:

1. **`item_key`** - the feed's own `<guid>` if it has one, else the canonical link. A
   WordPress guid (`https://nairametrics.com/?p=550279`) survives a slug rewrite, which is
   exactly the rename that would otherwise store one article twice. A guid that is itself a
   URL is canonicalised first, because Punch's guid carries the same campaign parameters
   its link does.
2. **`url_canonical`** - :func:`canonical_url`. Every Punch link arrives with
   `?utm_source=rss.punchng.com&utm_medium=web`; a campaign parameter that changed would
   re-insert the entire feed as new articles.
3. **`content_hash`** - SHA-256 over the normalised headline and body and nothing else. The
   same words from two publishers hash the same, so a cross-outlet duplicate is one indexed
   lookup for P5.4; the rows stay separate because attribution and the licence governing
   our copy are per publisher.

A row is written once per `(data_source_id, item_key, content_hash)`. A re-fetch of an
unchanged item writes nothing. An **edited** item writes a second row and leaves the first
alone, which is `CLAUDE.md`'s no-silent-overwrite rule applied to text: the evening
rewrite of a morning headline is not a correction of what the market read at 09:00.

## Parsing defensively, because RSS in the wild is malformed constantly

Every element is looked up with a wildcard namespace - `{*}item`, `{*}title` - so RSS 2.0,
RSS 1.0 and a feed that wrongly namespaces its own vocabulary all parse, and Atom is
handled beside them for the company IR feeds `DATA_FOUNDATION.md` §D expects next. A BOM or
stray whitespace before the XML declaration is stripped, because it is the single most
common reason a real feed fails to parse at all. A `<!DOCTYPE>` is refused outright:
`xml.etree` does not fetch external entities, but it does expand internal ones, and no
legitimate feed needs a doctype.

An item that cannot be read is **skipped and counted**, never guessed at. Skips are logged
with the reason, and a parse that dropped items says so out loud, because the alternative
is a feed that quietly halves and looks like a quiet news day.
"""

from __future__ import annotations

import datetime as dt
import re
import unicodedata
import urllib.parse
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from email.utils import parsedate_to_datetime
from html import unescape
from urllib.parse import urlsplit, urlunsplit

import structlog
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from packages.common.models import NewsItem
from packages.common.storage import sha256_hex
from packages.ingestion.base import (
    CachedDocument,
    Connector,
    DataSourceLicence,
    RawResponse,
    _data_source_id,
    revalidated,
)
from packages.ingestion.polite import (
    NotModified,
    PoliteFetcher,
    require_document,
    shared_fetcher,
)

__all__ = [
    "FEEDS",
    "NewsFeed",
    "NewsRecord",
    "RssNewsConnector",
    "canonical_url",
    "feed_connectors",
    "strip_markup",
]

_log = structlog.get_logger(__name__)

#: A descriptive agent with a contact address. None of these sites agreed to be scraped;
#: the least we owe them is somewhere to complain to before they block us.
_USER_AGENT = "quant_model/0.1 (nnatuanyafrankoguguo@churchofjesuschrist.org) research"

#: Query parameters that identify a *campaign*, not an article. Stripped before an article
#: is identified, because they change without the article changing - every Punch link
#: carries `utm_source=rss.punchng.com`, and a publisher that renamed its campaign would
#: otherwise re-insert its entire archive as new news.
_TRACKING_PARAMS = frozenset(
    {
        "utm_source",
        "utm_medium",
        "utm_campaign",
        "utm_term",
        "utm_content",
        "utm_id",
        "utm_reader",
        "fbclid",
        "gclid",
        "msclkid",
        "igshid",
        "mc_cid",
        "mc_eid",
        "ref",
        "source",
        "amp",
    }
)

#: Ports that say nothing. `https://x:443/a` and `https://x/a` are one article.
_DEFAULT_PORTS = {"http": "80", "https": "443"}

#: Tags whose *content* is not prose. A feed summary that embeds a script or a style block
#: would otherwise contribute its source code to the sentiment score.
_NON_PROSE = re.compile(r"(?is)<(script|style)\b[^>]*>.*?</\1\s*>")
_TAGS = re.compile(r"(?s)<[^>]*>")
_WHITESPACE = re.compile(r"\s+")

#: A feed that starts with a BOM, a stray newline or a blank line before `<?xml` is
#: rejected by every conforming parser with "XML or text declaration not at start of
#: entity". It is also extremely common. Stripped rather than mourned.
_LEADING_JUNK = re.compile(rb"^(?:\xef\xbb\xbf|\s)+")

#: `xml.etree` does not fetch external entities (Python 3.7.1 onward), but it does expand
#: internal ones, which is the billion-laughs shape. No legitimate feed needs a doctype, so
#: one is a refusal rather than a parse.
_DOCTYPE = re.compile(rb"<!DOCTYPE", re.IGNORECASE)

#: The start of the root element, and therefore the end of the prolog - the only place a
#: doctype may legally appear. `<?xml` and `<!--` and `<!DOCTYPE` all begin `<?` or `<!`,
#: so the first `<` followed by a letter is the root tag. Searching only the prolog means
#: an article whose summary quotes `<!DOCTYPE html>` does not cost us the whole feed.
_ROOT_ELEMENT = re.compile(rb"<[A-Za-z]")

#: An `encoding=` a feed declares and does not honour. Removing the declaration and
#: decoding as UTF-8 is the second attempt, not the first - see `_document`.
_XML_DECL_ENCODING = re.compile(rb'(<\?xml[^>]*?)\s+encoding\s*=\s*["\'][^"\']*["\']')


class MalformedFeedError(ValueError):
    """The bytes are not a feed we will parse. Raised rather than silently returning [].

    A connector that answers an unparseable document with zero records writes a `status`
    of `'ok'`, and `OPERATIONS.md` §2.3's whole subject is that this is indistinguishable
    from a quiet news day. A feed that stopped being XML is a failure and is recorded as
    one.
    """


@dataclass(frozen=True)
class NewsFeed:
    """One feed, and everything the register needs to account for it.

    Data rather than a subclass per publisher: the three feeds differ in a URL, a name and
    a licence, and nothing else. `source_name` is the **publisher**, not the feed - the
    redistribution question is answered by the masthead, and a second feed from the same
    one does not re-open it. Which feed an article came from is recorded by its
    `source_documents` row, whose `url` is the feed that was fetched.
    """

    #: Job and connector identity. `connector_runs.connector_name` is `rss:<key>`.
    key: str
    source_name: str
    feed_url: str
    base_url: str
    attribution_text: str
    #: Whether the host sends `ETag` or `Last-Modified`. Measured, not assumed: opting a
    #: connector into conditional requests against a source that sends neither costs a
    #: database read per run and saves nothing (`Connector.cache_url`).
    sends_validators: bool
    #: NULL where the publisher has none. `0022`'s rule - inventing a URL that looks like
    #: terms is worse than admitting there are none to point at.
    terms_url: str | None
    notes: str


#: The feeds this connector serves, keyed by `NewsFeed.key`. Seeded into `data_sources` by
#: migration 0025, whose docstring carries the robots.txt and licensing findings in full.
FEEDS: dict[str, NewsFeed] = {
    "nairametrics": NewsFeed(
        key="nairametrics",
        source_name="Nairametrics",
        feed_url="https://nairametrics.com/feed/",
        base_url="https://nairametrics.com",
        attribution_text="Source: Nairametrics",
        sends_validators=True,
        terms_url=None,
        notes=(
            "WordPress feed, 20 items, sy:updatePeriod hourly. robots.txt allows "
            "everything and publishes no Crawl-delay (checked 2026-09-24). Sends ETag "
            "and Last-Modified. No terms-of-use or copyright page is published; only a "
            "privacy policy, which governs personal data and not reuse."
        ),
    ),
    "businessday": NewsFeed(
        key="businessday",
        source_name="BusinessDay",
        feed_url="https://businessday.ng/feed/",
        base_url="https://businessday.ng",
        attribution_text="Source: BusinessDay NG",
        sends_validators=True,
        terms_url="https://businessday.ng/copyright/",
        notes=(
            "WordPress feed. robots.txt allows the feed and publishes no Crawl-delay "
            "(checked 2026-09-24). Sends ETag and Last-Modified. The feed carried five "
            "items when measured, which is why this connector asks to run hourly."
        ),
    ),
    "punch": NewsFeed(
        key="punch",
        source_name="Punch",
        feed_url="https://punchng.com/topics/business/feed/",
        base_url="https://punchng.com",
        attribution_text="Source: Punch Newspapers",
        sends_validators=False,
        terms_url=None,
        notes=(
            "The site's declared business feed, which 302s to "
            "rss.punchng.com/v1/category/latest_news - the RSS host drops the category, "
            "and the category-scoped URL serves zero items. Scope is left to P5.2. Both "
            "hosts allow everything in robots.txt and publish no Crawl-delay. No ETag, no "
            "Last-Modified, Cache-Control: no-store."
        ),
    ),
}


@dataclass(frozen=True)
class NewsRecord:
    """One article as one feed served it, ready to be written.

    `published_at` is when the world learned it and `retrieved_at` is when we fetched it,
    and `docs/08` §1.3 allows only the first anywhere near a feature join. Both are carried
    on the record because `write()` never sees the `RawResponse` - `retrieved_at` is a fact
    about the response, so it travels with the records parsed out of it.
    """

    feed_key: str
    item_key: str
    url: str
    url_canonical: str
    headline: str
    body: str | None
    categories: tuple[str, ...]
    published_at: dt.datetime
    retrieved_at: dt.datetime
    content_hash: str


def canonical_url(url: str) -> str:
    """The identity of a link: the same article's URL however it was decorated.

    Lowercases the scheme and host, drops a default port and the fragment, removes the
    campaign parameters in `_TRACKING_PARAMS`, and orders what remains. The **path is left
    exactly alone**, trailing slash included: `/a/` and `/a` are one page on most servers
    and two on some, and guessing which costs a duplicated article or a merged pair.

    A string that is not a URL comes back unchanged rather than mangled - some feeds put a
    bare id in `<guid>`, and :func:`_item_key` sends it through here without knowing.
    """
    parts = urlsplit(url.strip())
    if not parts.scheme or not parts.netloc:
        return url.strip()
    host = parts.hostname or ""
    port = parts.port
    if port is not None and str(port) != _DEFAULT_PORTS.get(parts.scheme.lower()):
        host = f"{host}:{port}"
    pairs = [
        (name, value)
        for name, value in urllib.parse.parse_qsl(parts.query, keep_blank_values=True)
        if name.lower() not in _TRACKING_PARAMS
    ]
    query = urllib.parse.urlencode(sorted(pairs))
    return urlunsplit((parts.scheme.lower(), host, parts.path, query, ""))


def strip_markup(value: str) -> str:
    """A feed summary as prose: entities resolved, tags gone, whitespace collapsed.

    The raw XML is stored before this runs, so nothing is lost - `parse()` is re-runnable
    against the stored bytes the day this function improves. What it buys is that a
    sentiment model and a Telegram message both receive text rather than markup, and that
    an `<img>` tag in the middle of a BusinessDay summary does not become part of the
    sentence.

    Entities are unescaped **after** tags are removed and then once more, because feeds
    routinely double-escape: `&amp;#8217;` is a real thing WordPress emits.
    """
    without_blocks = _NON_PROSE.sub(" ", value)
    text = unescape(_TAGS.sub(" ", without_blocks))
    if "&" in text:
        text = unescape(text)
    # NBSP and friends are whitespace to a reader and not to `str.split`.
    text = unicodedata.normalize("NFKC", text)
    return _WHITESPACE.sub(" ", text).strip()


def _content_hash(headline: str, body: str | None) -> str:
    """SHA-256 over the words, and nothing else.

    Deliberately excludes the URL and the source, so the same wire story republished by two
    outlets hashes the same and P5.4 can ask "have we already printed this?" with one
    indexed lookup. The newline separator keeps a headline that swallowed its summary from
    hashing equal to one that did not.
    """
    return sha256_hex(f"{headline}\n{body or ''}".encode())


class RssNewsConnector(Connector[NewsRecord]):
    """One feed's articles into `news_items`. `docs/08` §5, migration 0025.

    Constructed with the :class:`NewsFeed` it serves, in the shape `FredConnector` uses for
    one class over many series: the three publishers differ in a URL, a name and a licence,
    and a subclass each would be three copies of this file's body.
    """

    #: No host publishes a limit and none publishes a `Crawl-delay`, so this is a figure we
    #: chose rather than one we were given: `DATA_FOUNDATION.md` §3.5's 1 request per 2-5
    #: seconds per domain, at the slow end. One request per run, so it costs nothing.
    rate_limit_per_sec = 0.5
    #: On top of the bucket, for sites that never agreed to be scraped. Two seconds is the
    #: floor `tests/unit/test_politeness_invariants.py` enforces across every connector.
    politeness_delay_sec = 2.0

    def __init__(
        self,
        feed: NewsFeed,
        *,
        timeout_sec: float = 60.0,
        fetcher: PoliteFetcher | None = None,
    ) -> None:
        self.feed = feed
        #: `rss:nairametrics`. An instance attribute, not a class one, so each feed's runs
        #: are recorded under their own name without the scheduler having to pass
        #: `run_name` - `jobs.py`'s own docstring is about what it cost when four FRED jobs
        #: all wrote rows as `fred` and three healthy series hid a fourth that failed.
        self.name = f"rss:{feed.key}"
        self._timeout = timeout_sec
        # Shared, not per-instance: two feeds on one host would otherwise hold two
        # allowances for it, which is the unthrottled behaviour with extra steps.
        # Injectable so a test can drive `fetch` without a network or a real clock.
        self._fetcher = fetcher or shared_fetcher(user_agent=_USER_AGENT)

    def declare_licence(self) -> DataSourceLicence:
        """Matches the reviewed `data_sources` row seeded in migration 0025.

        `redistribution_allowed=False`, and that is the conservative answer rather than a
        researched permission. An RSS feed is an invitation to read and to link; it is not
        a copyright licence, and a headline and standfirst are the publisher's protected
        text. `DataSourceLicence` sets the rule for exactly this case: where the terms are
        unclear the answer is False plus a note saying why. `register()` refuses this
        connector if the stored row ever disagrees.
        """
        return DataSourceLicence(
            source_name=self.feed.source_name,
            base_url=self.feed.base_url,
            licence_type="news_publisher_copyright",
            redistribution_allowed=False,
            attribution_required=True,
            attribution_text=self.feed.attribution_text,
            terms_url=self.feed.terms_url,
            terms_reviewed_on=dt.date(2026, 9, 24),
            reviewed_by="nnatuanyafrankoguguo",
            rate_limit_per_sec=self.rate_limit_per_sec,
            notes=self.feed.notes,
        )

    def cache_url(self, **params: object) -> str | None:
        """The feed URL, for the two publishers that answer a conditional request.

        Opting in is per feed because `Connector.cache_url` says it is only worth it
        against a source that actually sends a validator, and Punch sends none and
        `Cache-Control: no-store` besides. Nairametrics and BusinessDay send both an ETag
        and a Last-Modified, so most hourly polls cost a 304 and no body.

        The recorded URL is the *requested* one here - unlike FRED, nothing is stripped -
        but Punch's redirect means the URL finally stored is the one the fetcher ended up
        at. That is deliberate provenance and it is also why Punch would look up nothing:
        another reason its `sends_validators` is False.
        """
        return self.feed.feed_url if self.feed.sends_validators else None

    def fetch(self, **params: object) -> RawResponse:
        """One feed, at the rate this connector declared.

        Redirects are followed: Punch's declared business feed 302s onto its RSS host, and
        the URL recorded is where we ended up, which is the honest provenance.
        """
        cached = params.pop("cached", None)
        answer = self._fetcher.get(
            self.feed.feed_url,
            rate_per_sec=self.rate_limit_per_sec,
            politeness_delay_sec=self.politeness_delay_sec,
            media_type="application/rss+xml",
            timeout=self._timeout,
            etag=cached.etag if isinstance(cached, CachedDocument) else None,
            last_modified=cached.last_modified if isinstance(cached, CachedDocument) else None,
        )
        if isinstance(answer, NotModified):
            # The feed has not changed. The stored bytes come back out of storage and go
            # through `parse` exactly as a fresh body would, so a parser improvement is
            # never skipped just because the source had nothing new to say. `run()` records
            # http_status 304, which is why zero rows written is expected here rather than
            # the silent-scraper signature it otherwise looks exactly like.
            assert isinstance(cached, CachedDocument)  # noqa: S101 - a 304 needs one
            return revalidated(cached)
        return require_document(answer)

    def parse(self, raw: RawResponse) -> list[NewsRecord]:
        """Pure: the same bytes give the same records, every time.

        `retrieved_at` comes off the `RawResponse`, which is part of the input, so this
        stays a function of its argument. Items that cannot be read are skipped and
        counted; the counts are logged, because a feed that quietly halves looks exactly
        like a quiet news day.
        """
        root = _document(raw)
        entries = root.findall(".//{*}item") or root.findall(".//{*}entry")
        records: list[NewsRecord] = []
        skipped: dict[str, int] = {}

        for entry in entries:
            headline = strip_markup(_text(entry, "title"))
            link = _link(entry)
            if not headline or not link:
                skipped["no_headline_or_link"] = skipped.get("no_headline_or_link", 0) + 1
                continue
            published_at = _published(entry)
            if published_at is None:
                # Never invented. A knowledge date we made up is the one value that turns a
                # point-in-time table into a lookahead generator, and `SPEC.md` §4.1's null
                # rule says an absent fact is absent. The item is dropped and counted.
                skipped["no_published_date"] = skipped.get("no_published_date", 0) + 1
                continue
            if published_at > raw.retrieved_at:
                # A post-dated item: a scheduled post or a clock error. Admitting it would
                # let a brief announce news that has not happened, and the database CHECK
                # `news_published_before_retrieved` would refuse the whole batch anyway.
                skipped["published_in_the_future"] = skipped.get("published_in_the_future", 0) + 1
                _log.warning(
                    "rss_item_published_after_it_was_fetched",
                    feed=self.feed.key,
                    url=link,
                    published_at=published_at.isoformat(),
                    retrieved_at=raw.retrieved_at.isoformat(),
                )
                continue
            body = _summary(entry) or None
            url_canonical = canonical_url(link)
            records.append(
                NewsRecord(
                    feed_key=self.feed.key,
                    item_key=_item_key(entry, url_canonical),
                    url=link,
                    url_canonical=url_canonical,
                    headline=headline,
                    body=body,
                    categories=_categories(entry),
                    published_at=published_at,
                    retrieved_at=raw.retrieved_at,
                    content_hash=_content_hash(headline, body),
                )
            )

        if skipped:
            _log.warning("rss_items_skipped", feed=self.feed.key, found=len(entries), **skipped)
        if not entries:
            # 200 OK and nothing in it: exactly what `rss.punchng.com/v1/category/business`
            # serves. `run()` will warn about the zero rows; this says which of the two
            # zeroes it was, because a feed with no items and a parser that matched no
            # items are different faults with the same symptom.
            _log.warning("rss_feed_carried_no_items", feed=self.feed.key, url=raw.url)
        return records

    def write(self, session: Session, records: list[NewsRecord], *, source_document_id: int) -> int:
        """Insert the article versions this source does not already hold. Rows inserted.

        `ON CONFLICT DO NOTHING` on `(data_source_id, item_key, content_hash)`, never an
        upsert: a re-poll of an unchanged item is a no-op, and an **edited** item is a new
        row beside the old one. There is no reachable path here that updates an article,
        and migration 0025 puts a `no_update` trigger on the table so the rule holds
        outside this code too.

        Duplicates *within one response* are collapsed first. A feed that lists the same
        item twice is common enough, and `ON CONFLICT` arbitrates against rows that are
        already committed rather than against the statement's own.

        One statement, unbatched, unlike `write_macro_records`. PostgreSQL caps a
        statement at 65,535 bound parameters and a row here binds eleven, so the ceiling
        is near 5,900 articles in one response - two orders of magnitude above the largest
        feed any of these publishers serves, which is thirty. `base.INSERT_BATCH_ROWS`
        exists because a FRED series carries decades of daily observations; a feed window
        does not, and cannot grow into one.
        """
        if not records:
            return 0
        data_source_id = _data_source_id(session, self)

        seen: set[tuple[str, str]] = set()
        rows: list[dict[str, object]] = []
        for record in records:
            identity = (record.item_key, record.content_hash)
            if identity in seen:
                continue
            seen.add(identity)
            rows.append(
                {
                    "data_source_id": data_source_id,
                    "source_document_id": source_document_id,
                    "item_key": record.item_key,
                    "url": record.url,
                    "url_canonical": record.url_canonical,
                    "headline": record.headline,
                    "body": record.body,
                    "categories": list(record.categories),
                    "published_at": record.published_at,
                    "retrieved_at": record.retrieved_at,
                    "content_hash": record.content_hash,
                }
            )
        if len(rows) < len(records):
            _log.info(
                "rss_duplicate_items_in_one_response",
                feed=self.feed.key,
                items=len(records),
                distinct=len(rows),
            )

        statement = (
            pg_insert(NewsItem)
            .values(rows)
            .on_conflict_do_nothing(index_elements=["data_source_id", "item_key", "content_hash"])
            .returning(NewsItem.id)
        )
        inserted = len(session.execute(statement).fetchall())
        _log.info("rss_items_written", feed=self.feed.key, rows=inserted, of=len(rows))
        return inserted


def feed_connectors(
    *, timeout_sec: float = 60.0, fetcher: PoliteFetcher | None = None
) -> list[RssNewsConnector]:
    """One connector per feed in :data:`FEEDS`, in a stable order.

    So `packages/scheduler/jobs.py` and anything else that wants every feed - a backfill
    script, a health check - build the same list from one place. `jobs.py`'s own docstring
    records what two hand-kept lists cost: a connector had to be added to both, and the
    day one is forgotten the health check goes quiet about exactly the job that never ran.

    `packages/scheduler/runner.py` calls `register()` on a job's connector before every
    run, so each feed's `data_sources` row is re-checked against its declared licence on
    every poll rather than once at setup.
    """
    return [
        RssNewsConnector(feed, timeout_sec=timeout_sec, fetcher=fetcher) for feed in FEEDS.values()
    ]


# ---------------------------------------------------------------------------
# Parsing. Everything below is pure and takes no session, no clock and no network.
# ---------------------------------------------------------------------------


def _document(raw: RawResponse) -> ET.Element:
    """The feed's root element, or `MalformedFeedError` saying why not.

    Three real-world defects are handled here and nowhere else, in the order they bite:

    1. **Leading junk.** A BOM or a blank line before `<?xml` makes every conforming
       parser fail with "not at start of entity". Stripped.
    2. **A doctype.** Refused. `xml.etree` will not fetch an external entity, but it will
       expand an internal one, and no feed needs a doctype to be a feed.
    3. **A lied-about encoding.** A feed declaring `iso-8859-1` and sending UTF-8 raises on
       the bytes path. The retry drops the declaration and decodes as UTF-8, replacing what
       will not decode - one mangled character in a headline beats losing the feed.
    """
    data = _LEADING_JUNK.sub(b"", raw.data)
    if not data:
        raise MalformedFeedError(f"{raw.url}: empty response body")
    root_at = _ROOT_ELEMENT.search(data)
    if _DOCTYPE.search(data[: root_at.start()] if root_at else data):
        raise MalformedFeedError(
            f"{raw.url}: the feed declares a DOCTYPE. Internal entity expansion is the "
            f"billion-laughs shape and no feed needs one, so this is refused rather than "
            f"parsed."
        )
    try:
        return ET.fromstring(data)  # noqa: S314 - no doctype above; etree resolves no external entities
    except (ET.ParseError, UnicodeDecodeError, LookupError) as first:
        try:
            lenient = _XML_DECL_ENCODING.sub(rb"\1", data).decode("utf-8", errors="replace")
            root = ET.fromstring(lenient)  # noqa: S314 - same document, declaration removed
        except ET.ParseError as second:
            raise MalformedFeedError(f"{raw.url}: not parseable as XML ({second})") from first
        _log.warning("rss_feed_needed_a_lenient_reparse", url=raw.url, reason=str(first))
        return root


def _children(entry: ET.Element, local_name: str) -> list[ET.Element]:
    """Every child with this local name, in any namespace - or none at all.

    The wildcard is the whole point. RSS 2.0 puts `<title>` in no namespace, RSS 1.0 puts
    it in `http://purl.org/rss/1.0/`, Atom in `http://www.w3.org/2005/Atom`, and a
    depressing number of feeds invent their own. Matching on the local name reads all of
    them, and the local names that matter do not collide across those vocabularies.
    """
    return entry.findall(f"{{*}}{local_name}")


def _text(entry: ET.Element, local_name: str) -> str:
    """The first non-empty text of a child with this local name. `""` when there is none.

    `itertext()` rather than `.text`: a feed that wrote `<title>GTCO <b>H1</b></title>`
    has parsed children, and `.text` would return "GTCO " and drop the rest.
    """
    for child in _children(entry, local_name):
        value = "".join(child.itertext()).strip()
        if value:
            return value
    return ""


def _link(entry: ET.Element) -> str:
    """The article's URL, from whichever shape the feed used.

    RSS puts it in `<link>`'s text. Atom puts it in a `href` attribute and may list
    several, of which only `rel="alternate"` (or no `rel` at all) is the article itself -
    `rel="replies"` and `rel="enclosure"` point elsewhere. An `<atom:link rel="self">`
    inside an RSS item is common and must not win, which is why `rel` is checked before
    `href` is taken.
    """
    for child in _children(entry, "link"):
        text = "".join(child.itertext()).strip()
        if text:
            return unescape(text)
    for child in _children(entry, "link"):
        href = (child.get("href") or "").strip()
        if href and child.get("rel", "alternate") == "alternate":
            return unescape(href)
    # Last resort: a permalink guid. Some minimal feeds carry no <link> at all.
    for child in _children(entry, "guid"):
        text = "".join(child.itertext()).strip()
        if text and child.get("isPermaLink", "true").lower() == "true":
            return unescape(text)
    return ""


def _summary(entry: ET.Element) -> str:
    """The article's standfirst, as prose. `""` when the feed carried none.

    Four element names in a deliberate order. `description` is RSS's summary and
    `summary` is Atom's, and both are asked before the full-text fields because a
    standfirst is what a brief prints and what a sentiment model should read - the full
    article is the raw document's job, and P5 has no full-text fetch.

    `content` is asked last and is the reason the order is written down: EDGAR's Atom
    feed puts a *structured* `<content type="text/xml">` block in every entry, and
    `itertext()` over it would return a filing's accession number and file size as though
    they were a sentence. It only wins when a feed offers nothing else.
    """
    for name in ("description", "summary", "encoded", "content"):
        text = strip_markup(_text(entry, name))
        if text:
            return text
    return ""


def _item_key(entry: ET.Element, url_canonical: str) -> str:
    """The feed's identifier for this article, canonicalised when it is a URL.

    A `<guid>` (or Atom `<id>`) is what the publisher says is the same article, and it
    survives a slug rewrite that the link does not. When it is itself a URL it goes through
    :func:`canonical_url`, because Punch's guid carries the same campaign parameters its
    link does and would otherwise re-key the article the day a campaign is renamed.
    """
    for name in ("guid", "id"):
        value = _text(entry, name)
        if value:
            return canonical_url(value)
    return url_canonical


def _categories(entry: ET.Element) -> tuple[str, ...]:
    """The feed's own labels, verbatim, de-duplicated, in the order the feed gave them.

    Punch sends `<category><![CDATA[]]></category>` - an element with no label in it -
    which becomes nothing rather than an empty string in the array.
    """
    labels: list[str] = []
    for child in _children(entry, "category"):
        # RSS carries the label as text; Atom carries it in a `term` attribute.
        label = strip_markup("".join(child.itertext())) or (child.get("term") or "").strip()
        if label and label not in labels:
            labels.append(label)
    return tuple(labels)


def _published(entry: ET.Element) -> dt.datetime | None:
    """When the world learned about this article, in UTC, or `None` if the feed did not say.

    `pubDate` is RSS's RFC 2822 (`Thu, 24 Sep 2026 09:06:18 +0000`); `published` and
    `updated` are Atom's ISO 8601; `date` is Dublin Core's, which RSS 1.0 uses. The first
    that parses wins, and `pubDate` is asked first because it is the *publication* time
    where `updated` is the last edit - and an edit is not when the market learned it.

    A timestamp with no offset is read as UTC and logged. It is the one inference in this
    file, and it is bounded: the feeds here are all UTC-stamped, WAT is one hour away, and
    the alternative - dropping the article - loses information to avoid an error smaller
    than the daily grain `known_as_of` is measured in.
    """
    for name in ("pubDate", "published", "date", "updated"):
        value = _text(entry, name)
        if not value:
            continue
        parsed = _parse_rfc2822(value) or _parse_iso8601(value)
        if parsed is None:
            continue
        if parsed.tzinfo is None:
            _log.warning("rss_timestamp_had_no_offset", field=name, value=value)
            return parsed.replace(tzinfo=dt.UTC)
        return parsed.astimezone(dt.UTC)
    return None


def _parse_rfc2822(value: str) -> dt.datetime | None:
    """RSS's own date format. Returns `None` rather than raising on anything else."""
    try:
        return parsedate_to_datetime(value)
    except (TypeError, ValueError):
        return None


def _parse_iso8601(value: str) -> dt.datetime | None:
    """Atom's format. `fromisoformat` handles the trailing `Z` from Python 3.11."""
    try:
        return dt.datetime.fromisoformat(value.strip())
    except ValueError:
        return None

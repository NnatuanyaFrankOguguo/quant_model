"""Fetching politely: one place that enforces what every connector already declares. P4.8.

`docs/03` P4.8 asks for *"retries with exponential backoff, per-domain token-bucket rate
limiting, ETag/Last-Modified caching so unchanged documents are never re-fetched"*, and
`DATA_FOUNDATION.md` §3.5's politeness rules: *"respect `robots.txt`; descriptive User-Agent
with a contact email; **1 request per 2-5 seconds per domain**"*.

## What was enforced before this, exactly

Worth stating precisely, because an earlier version of this docstring said none of it ran
and that was wrong about EDGAR.

**EDGAR enforced its own.** `packages/ingestion/edgar.py` has had a process-wide `_Throttle`
since P2 - a fixed 0.12s interval reached through `EdgarConnector._get`, so all four of its
concrete connectors and the ticker-file fetch share it, with an injectable clock and a lock.
It works, and this module does not replace it.

**Everyone else enforced nothing.** CBN, FRED and Yahoo each called `httpx.get` directly
with no spacing between calls, and the Nigeria Data Portal called `httpx.post` - which is
how it escaped a first survey that grepped for `httpx.get` and concluded it made no
requests. That last one is the connector where the gap had already cost something: its own
comment records the portal answering 403 to a second request issued immediately after the
first, and then declares the 0.5/s that would have prevented it and never ran.

**And `rate_limit_per_sec` was read by nobody, EDGAR included.** Every connector declares
it, `register()` writes it into `data_sources`, and the scheduler, the connectors and the
fetch path all ignored it - EDGAR spaces requests by its own `MIN_INTERVAL_SEC` constant,
which happens to agree with its declared 8.0/s but is not derived from it. So the number in
the database was documentation, and a connector whose declared limit changed would have gone
on fetching at the old rate.

`Connector`'s own comment says what that costs:

    Declared, not remembered. EDGAR's <=10 req/s in P2 comes with a ~10-minute IP block when
    exceeded (`DATA_FOUNDATION.md` §C) - that belongs in code, not in your head.

`politeness_delay_sec` is declared and unread everywhere, and no connector has ever sent a
conditional request or consulted `robots.txt`. The risk is not theoretical: an IP block
costs a night's ingestion and there is no way to appeal it quickly.

## The robots.txt trap, which is worth knowing about before trusting this

`urllib.robotparser.RobotFileParser.read()` fetches the file with **urllib's** User-Agent,
not ours. A host that blocks unfamiliar clients answers that agent `403`, and the parser
stores a 403 as `disallow_all`. The result is a blanket refusal derived from a rejection of
a client we are not, reported as though robots.txt had asked for it.

`www.cbn.gov.ng` does exactly this - 403 to urllib, 200 and `Allow: /` to us - so turning
this module on would have disabled CBN entirely, with an error message blaming a file that
says the opposite. Robots is therefore fetched through our own transport, as us.

One limit of the parser remains and is not fixed here: it does not implement `$`-anchored
wildcards, so given `Disallow: /*.asp$` it answers True for `/x.asp`. It under-enforces
rather than over-enforces, which is the wrong direction to be wrong in. No connector
currently fetches a path that only a `$` rule would cover.

## Why the bucket is keyed on the domain

`data.sec.gov` is fetched by four different connector classes - submissions, companyfacts,
instance shares and the company refresh that drives them. A limiter attached to a connector
would let four of them through at once, and SEC's limit is on the *client*, not on whatever
the client calls its code. So the bucket belongs to the host, and every connector hitting
that host shares one.

Per-host is the right key and it is not strictly the most conservative one. EDGAR also
fetches `company_tickers.json` from `www.sec.gov`, which is a different host and therefore a
different bucket here, while EDGAR's own process-wide throttle counts it against the same
allowance. SEC's limit is per client rather than per hostname, so for that one source the
older, blunter instrument is the safer of the two - which is a further reason this module
leaves it alone.

The bucket is process-wide and guarded by a lock, because the scheduler runs jobs in
sequence today and will not always.

## What a 304 means, and why it is not an error

With an `ETag` or `Last-Modified` from last time, the request carries `If-None-Match` or
`If-Modified-Since`, and the server may answer `304 Not Modified` with no body. That is a
success: the document we hold is current. It is returned as `NotModified` rather than an
empty `RawResponse`, because an empty body that looks like a document is how a connector
stores nothing and reports success - the silent failure this project keeps finding.

## What this module does not do

It does not retry a *parse* failure or a bad row. Backoff here covers transport only -
429, 5xx, timeouts - because those are the failures where waiting helps. A 404 is answered
immediately and a 403 is not retried at all: both mean the next identical request gets the
same answer, and hammering is what turns a 403 into a block.
"""

from __future__ import annotations

import datetime as dt
import threading
import time
import urllib.parse
import urllib.robotparser
from collections.abc import Callable
from dataclasses import dataclass, field
from email.utils import parsedate_to_datetime
from urllib.parse import urlsplit, urlunsplit

import httpx
import structlog

from packages.ingestion.base import RawResponse

__all__ = [
    "DEFAULT_MAX_ATTEMPTS",
    "NotModified",
    "NotModifiedError",
    "PoliteFetcher",
    "RobotsRefusedError",
    "TokenBucket",
    "redact_url",
    "require_document",
    "shared_fetcher",
]

_log = structlog.get_logger(__name__)

#: Transport failures worth waiting for. A 429 is the server asking; a 5xx is the server
#: struggling; a timeout is the network. Each one is different next time.
_RETRYABLE_STATUS = frozenset({429, 500, 502, 503, 504})

#: Never retried, however many attempts remain. A 403 repeated is what turns a refusal into
#: an IP block, and a 404 does not become a 200 by being asked twice.
_TERMINAL_STATUS = frozenset({400, 401, 403, 404, 405, 410})

DEFAULT_MAX_ATTEMPTS = 3

#: robots.txt is one small file, once per host per process. A host too slow to serve it in
#: ten seconds is a host we will find out about on the real request anyway.
_ROBOTS_TIMEOUT_SEC = 10.0

#: Doubling, from `DATA_FOUNDATION.md` §3.5's politeness. The P1 scheduler used
#: `backoff * attempt`, which is linear - 2s, 4s, 6s - and P4.8 asks for exponential.
_BACKOFF_BASE_SEC = 2.0

#: However long a `Retry-After` asks for, never sleep longer than this in one wait. A server
#: answering "come back in six hours" should fail the run and be seen, not block a scheduler
#: thread until morning.
_MAX_BACKOFF_SEC = 120.0


class RobotsRefusedError(PermissionError):
    """`robots.txt` disallows this path for our User-Agent, so it is not fetched."""


class NotModifiedError(RuntimeError):
    """A `304` came back where the caller had promised it could not.

    `get()` returns `NotModified` only when it was given an `etag` or a `last_modified`,
    so a caller that passes neither cannot receive one - which is why `Connector.fetch()`
    can go on returning `RawResponse`. :func:`require_document` is where that reasoning is
    written down, and this is what it raises if the reasoning is ever wrong. It should be
    unreachable; if it is reached, the conditional-request plumbing grew a caller that did
    not grow a 304 branch, and the honest outcome is a loud failure rather than a
    `NotModified` returned from something typed to return bytes.
    """


@dataclass
class _BucketRegistry:
    """The buckets, and the lock that guards creating one.

    Separate from the fetcher because the allowance belongs to the *host*, not to us. A
    fetcher built directly gets its own registry, which is what the tests want - a fake
    clock must not leak into another test's bucket. A fetcher from
    :func:`shared_fetcher` gets the process-wide one, which is what production wants:
    CBN's three connectors are three objects hitting one host, and three separate
    allowances for one host is just the unthrottled behaviour with extra steps.
    """

    buckets: dict[str, TokenBucket] = field(default_factory=dict)
    lock: threading.Lock = field(default_factory=threading.Lock)


@dataclass(frozen=True)
class NotModified:
    """The server says what we already hold is current. A success, and not a document."""

    url: str
    etag: str | None
    last_modified: dt.datetime | None


class TokenBucket:
    """One host's allowance, refilling at a fixed rate.

    Deliberately not a sliding window. A bucket permits a short burst up to its capacity and
    then settles to the declared rate, which is what a polite client actually wants: fetching
    three small files back to back is fine, fetching three hundred is not.

    `now` and `sleep` are injected so the tests can run a thousand simulated seconds without
    taking a thousand seconds.
    """

    def __init__(
        self,
        rate_per_sec: float,
        *,
        capacity: float | None = None,
        now: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        if rate_per_sec <= 0:
            raise ValueError(f"rate_per_sec must be positive, got {rate_per_sec}")
        self.rate_per_sec = rate_per_sec
        # One second's worth, and at least one token, so a rate below 1/s can still fetch.
        self.capacity = capacity if capacity is not None else max(rate_per_sec, 1.0)
        self._tokens = self.capacity
        self._now = now
        self._sleep = sleep
        self._last = now()
        self._lock = threading.Lock()

    def take(self, tokens: float = 1.0) -> float:
        """Wait until `tokens` are available, then spend them. Returns the seconds waited."""
        with self._lock:
            waited = 0.0
            while True:
                current = self._now()
                self._tokens = min(
                    self.capacity, self._tokens + (current - self._last) * self.rate_per_sec
                )
                self._last = current
                if self._tokens >= tokens:
                    self._tokens -= tokens
                    return waited
                shortfall = tokens - self._tokens
                delay = shortfall / self.rate_per_sec
                self._sleep(delay)
                waited += delay


#: Query parameters whose value must never reach a stored URL. `source_documents.url` is
#: content-addressed history: it is kept forever, it is read by people who are not the owner,
#: and it is the last place a live credential should end up. FRED strips its own key when it
#: builds the recorded URL; this is the floor under every connector that forgets to.
_SECRET_PARAMS = frozenset(
    {
        "api_key",
        "apikey",
        "key",
        "token",
        "access_token",
        "auth",
        "password",
        "secret",
        "signature",
        "sig",
    }
)
_REDACTED = "REDACTED"


def redact_url(url: str) -> str:
    """The same URL with any credential-shaped parameter's value replaced.

    Only the value goes. Which parameters were sent is part of knowing what was asked for,
    and is worth keeping; what they were set to is not.
    """
    parts = urlsplit(url)
    if not parts.query:
        return url
    pairs = urllib.parse.parse_qsl(parts.query, keep_blank_values=True)
    if not any(name.lower() in _SECRET_PARAMS for name, _ in pairs):
        return url
    cleaned = [
        (name, _REDACTED if name.lower() in _SECRET_PARAMS else value) for name, value in pairs
    ]
    return urlunsplit(parts._replace(query=urllib.parse.urlencode(cleaned)))


def _default_transport(url: str, *, method: str = "GET", **kwargs: object) -> httpx.Response:
    """One callable for every verb, so the fetcher has a single door to the network.

    `httpx.get` cannot send a POST and `httpx.post` cannot send a GET, so a transport fixed
    to either would need a second one beside it - and then two places to stub, two places
    to forget."""
    return httpx.request(method, url, **kwargs)  # type: ignore[arg-type]


def _host_of(url: str) -> str:
    parts = urlsplit(url)
    return f"{parts.scheme}://{parts.netloc}"


def _parse_http_date(value: str | None) -> dt.datetime | None:
    if not value:
        return None
    try:
        return parsedate_to_datetime(value)
    except (TypeError, ValueError):
        return None


class PoliteFetcher:
    """The one way a connector reaches the network.

    Holds a token bucket per host, a `robots.txt` verdict per host, and the backoff policy.
    Stateful on purpose: the whole point is that two connectors hitting one host share an
    allowance, which they cannot do if each makes its own fetcher.
    """

    def __init__(
        self,
        *,
        user_agent: str,
        transport: Callable[..., httpx.Response] = _default_transport,
        now: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
        respect_robots: bool = True,
        buckets: _BucketRegistry | None = None,
    ) -> None:
        if "@" not in user_agent:
            # `DATA_FOUNDATION.md` §3.5 asks for a contact email, and SEC requires one. A
            # User-Agent nobody can reply to is how a polite client gets blocked anyway.
            raise ValueError(
                f"user_agent must carry a contact email, got {user_agent!r}. A source that "
                f"wants to complain before blocking us needs somewhere to complain to."
            )
        self.user_agent = user_agent
        self._transport = transport
        self._now = now
        self._sleep = sleep
        self._respect_robots = respect_robots
        # Own registry by default, so a test's fake clock cannot leak into another test's
        # bucket. `shared_fetcher()` passes the process-wide one.
        self._registry = buckets if buckets is not None else _BucketRegistry()
        # The robots cache stays per-instance on purpose: robots rules are addressed to a
        # User-Agent, and two fetchers with different agents can be told different things.
        self._robots: dict[str, urllib.robotparser.RobotFileParser | None] = {}
        self._lock = threading.Lock()

    def bucket_for(self, url: str, *, rate_per_sec: float) -> TokenBucket:
        """The bucket for this URL's host, created once and shared by every caller."""
        host = _host_of(url)
        with self._registry.lock:
            bucket = self._registry.buckets.get(host)
            if bucket is None:
                bucket = TokenBucket(rate_per_sec, now=self._now, sleep=self._sleep)
                self._registry.buckets[host] = bucket
                _log.info("rate_limiter_created", host=host, rate_per_sec=rate_per_sec)
            return bucket

    def _read_robots(self, host: str) -> urllib.robotparser.RobotFileParser | None:
        """Fetch and parse one host's robots.txt. `None` means "no rules to apply".

        **Fetched through our own transport, with our own User-Agent, on purpose.**
        `RobotFileParser.read()` opens the URL with urllib's `Python-urllib/x.y`, and a host
        that blocks unknown agents answers 403 - which `RobotFileParser` stores as
        `disallow_all`. The result is a blanket refusal derived from a rejection of a client
        we are not, reported as though robots.txt had asked for it. `www.cbn.gov.ng` does
        exactly this: 403 to urllib, 200 and `Allow: /` to us.
        """
        url = f"{host}/robots.txt"
        try:
            response = self._transport(
                url,
                method="GET",
                params=None,
                headers={"User-Agent": self.user_agent},
                timeout=_ROBOTS_TIMEOUT_SEC,
                follow_redirects=True,
            )
        except Exception as exc:  # noqa: BLE001 - any failure means "unknown"
            # Not permission and not refusal. Refusing would stop every connector the first
            # time a host had a bad day; allowing is what a browser does.
            _log.warning("robots_unreadable", host=host, reason=type(exc).__name__)
            return None
        if response.status_code >= 400:
            # RFC 9309 §2.3.1.3: an unavailable robots.txt means no restrictions. This is
            # the branch CBN lands in if the WAF ever blocks us too, and it is the
            # standard's answer rather than a convenience.
            _log.info("robots_unavailable", host=host, status=response.status_code)
            return None
        parser = urllib.robotparser.RobotFileParser()
        parser.set_url(url)
        parser.parse(response.text.splitlines())
        return parser

    def _robots_allows(self, url: str) -> bool:
        """Whether this path is ours to fetch.

        Note that `urllib.robotparser` does not implement `$`-anchored wildcards: given
        `Disallow: /*.asp$` it answers True for `/x.asp`. It under-enforces rather than
        over-enforces, which is the wrong direction to be wrong in, and is worth knowing
        before reading `respect_robots=True` as a guarantee. It is not currently load-
        bearing - no connector fetches a path that only a `$` rule would cover - and
        replacing the parser is not this change.
        """
        if not self._respect_robots:
            return True
        host = _host_of(url)
        with self._lock:
            if host not in self._robots:
                self._robots[host] = self._read_robots(host)
            parser_or_none = self._robots[host]
        if parser_or_none is None:
            return True
        return parser_or_none.can_fetch(self.user_agent, url)

    def _crawl_delay(self, url: str) -> float | None:
        """Seconds between requests, if the host publishes a number for our agent.

        `api.stlouisfed.org` asks for 2. Our FRED connector declares 5 requests a second.
        Only one of those two numbers belongs to the host, and until now neither the code
        nor anyone reading it knew the other one existed.

        Only meaningful after `_robots_allows` has run, which is the only thing that
        populates the cache - and it runs first in every `get`."""
        if not self._respect_robots:
            return None
        parser = self._robots.get(_host_of(url))
        if parser is None:
            return None
        try:
            delay = parser.crawl_delay(self.user_agent)
        except Exception:  # noqa: BLE001 - a malformed directive is not a reason to stop
            return None
        return float(delay) if delay else None

    def _rate_for(self, url: str, *, declared: float) -> float:
        """The declared rate, lowered to the host's `Crawl-delay` when that is slower.

        Never raised. A host saying "every 2 seconds" is a ceiling we accept; a host
        saying nothing does not license us to go faster than we declared."""
        delay = self._crawl_delay(url)
        if not delay:
            return declared
        allowed = 1.0 / delay
        if allowed >= declared:
            return declared
        _log.info(
            "rate_lowered_by_crawl_delay",
            host=_host_of(url),
            declared_per_sec=declared,
            crawl_delay_sec=delay,
            using_per_sec=allowed,
        )
        return allowed

    def post(
        self,
        url: str,
        *,
        rate_per_sec: float,
        media_type: str,
        json: object = None,
        params: dict[str, object] | None = None,
        politeness_delay_sec: float = 0.0,
        timeout: float = 30.0,
        max_attempts: int = 1,
        record_url: str | None = None,
    ) -> RawResponse:
        """A POST, with everything a GET gets except the optimism about retrying.

        `max_attempts` defaults to **one**. A GET is safe to repeat; a POST the server
        already processed is not, and a retry after a 503 can mean the work happened twice.
        A caller whose POST is really a query - the Nigeria Data Portal's pivot endpoint is
        one - passes a higher number and says why.

        `record_url` matters more here than anywhere: a POST body is not in the URL, so
        without one the stored document says only "the pivot endpoint" and six months later
        nobody can tell which series it holds.

        Redirects are not followed. See the comment on the call below - a followed redirect
        turns this into a GET without the body, which is the quietest way to get a
        confident answer to a question nobody asked.
        """
        result = self._send(
            "POST",
            url,
            # Not followed, unlike a GET. httpx does what browsers do and rewrites a
            # redirected POST into a GET (301, 302 and 303 all do it - see
            # `httpx._client.BaseClient._redirect_method`), which drops the body. For a
            # query expressed as a POST that means the question is silently thrown away and
            # a 200 comes back carrying something else entirely, which `raise_for_status`
            # has no reason to complain about. Left unfollowed, the 3xx reaches
            # `raise_for_status` and is raised, which is the outcome worth having.
            follow_redirects=False,
            rate_per_sec=rate_per_sec,
            media_type=media_type,
            params=params,
            json=json,
            politeness_delay_sec=politeness_delay_sec,
            timeout=timeout,
            max_attempts=max_attempts,
            record_url=record_url,
        )
        # No conditional headers are sent, so a 304 is not reachable. `require_document`
        # says the same thing where a caller can see it.
        return require_document(result)

    def get(
        self,
        url: str,
        *,
        rate_per_sec: float,
        media_type: str,
        params: dict[str, object] | None = None,
        etag: str | None = None,
        last_modified: dt.datetime | None = None,
        politeness_delay_sec: float = 0.0,
        timeout: float = 30.0,
        max_attempts: int = DEFAULT_MAX_ATTEMPTS,
        record_url: str | None = None,
        follow_redirects: bool = True,
    ) -> RawResponse | NotModified:
        """One polite GET: robots, rate limit, conditional headers, backoff.

        `etag` and `last_modified` are what we stored last time. Passing them turns the
        request conditional, and a `304` comes back as `NotModified` - which is the whole
        point of storing them, and was not happening.

        `record_url` is the URL to *store*, when that differs from the one to *request*.
        FRED's request carries a live API key and its stored URL must not; a connector can
        hand over the exact shape it wants preserved. Credential-shaped parameters are
        stripped either way - see :func:`redact_url` - because the floor should not depend
        on every connector remembering.

        `follow_redirects` defaults to true because that is what every caller wants and
        what the one caller that said so out loud (CBN) already did. Note that a redirect
        chain is several requests and one token, so the bucket under-counts by the length
        of the chain, which httpx bounds at 20.
        """
        return self._send(
            "GET",
            url,
            rate_per_sec=rate_per_sec,
            media_type=media_type,
            params=params,
            etag=etag,
            last_modified=last_modified,
            politeness_delay_sec=politeness_delay_sec,
            timeout=timeout,
            max_attempts=max_attempts,
            record_url=record_url,
            follow_redirects=follow_redirects,
        )

    def _send(
        self,
        method: str,
        url: str,
        *,
        rate_per_sec: float,
        media_type: str,
        params: dict[str, object] | None = None,
        json: object = None,
        etag: str | None = None,
        last_modified: dt.datetime | None = None,
        politeness_delay_sec: float = 0.0,
        timeout: float = 30.0,
        max_attempts: int = DEFAULT_MAX_ATTEMPTS,
        record_url: str | None = None,
        follow_redirects: bool = True,
    ) -> RawResponse | NotModified:
        """The one path to the network: robots, bucket, conditional headers, backoff."""
        if not self._robots_allows(url):
            raise RobotsRefusedError(
                f"robots.txt at {_host_of(url)} disallows {url} for {self.user_agent!r}"
            )

        headers: dict[str, str] = {"User-Agent": self.user_agent}
        if etag:
            headers["If-None-Match"] = etag
        if last_modified:
            headers["If-Modified-Since"] = last_modified.strftime("%a, %d %b %Y %H:%M:%S GMT")

        bucket = self.bucket_for(url, rate_per_sec=self._rate_for(url, declared=rate_per_sec))
        last_error: Exception | None = None

        for attempt in range(1, max_attempts + 1):
            bucket.take()
            if politeness_delay_sec:
                # On top of the bucket, for a site that never agreed to be scraped.
                self._sleep(politeness_delay_sec)
            try:
                response = self._transport(
                    url,
                    method=method,
                    params=params,
                    headers=headers,
                    timeout=timeout,
                    follow_redirects=follow_redirects,
                    **({"json": json} if json is not None else {}),
                )
            except httpx.HTTPError as exc:
                last_error = exc
                if attempt == max_attempts:
                    break
                self._wait(attempt, reason=type(exc).__name__, url=url)
                continue

            if response.status_code == 304:
                _log.info("not_modified", url=url, attempt=attempt)
                return NotModified(
                    url=redact_url(record_url or url),
                    etag=response.headers.get("ETag", etag),
                    last_modified=_parse_http_date(response.headers.get("Last-Modified"))
                    or last_modified,
                )

            if response.status_code in _TERMINAL_STATUS:
                response.raise_for_status()

            if response.status_code in _RETRYABLE_STATUS and attempt < max_attempts:
                self._wait(
                    attempt,
                    reason=f"http_{response.status_code}",
                    url=url,
                    retry_after=response.headers.get("Retry-After"),
                )
                continue

            response.raise_for_status()
            return RawResponse(
                data=response.content,
                media_type=media_type,
                # `response.url` is where we *ended up*, which after a redirect is more
                # honest provenance than where we aimed.
                url=redact_url(record_url or str(response.url)),
                http_status=response.status_code,
                etag=response.headers.get("ETag"),
                last_modified=_parse_http_date(response.headers.get("Last-Modified")),
            )

        raise httpx.HTTPError(
            f"{method} {url} failed after {max_attempts} attempts"
            + (f": {type(last_error).__name__}" if last_error else "")
        )

    def _wait(self, attempt: int, *, reason: str, url: str, retry_after: str | None = None) -> None:
        """Exponential, unless the server named a figure, and never longer than the cap."""
        delay = _BACKOFF_BASE_SEC * (2 ** (attempt - 1))
        if retry_after:
            try:
                delay = max(delay, float(retry_after))
            except ValueError:
                asked = _parse_http_date(retry_after)
                if asked is not None:
                    delay = max(delay, (asked - dt.datetime.now(dt.UTC)).total_seconds())
        delay = max(0.0, min(delay, _MAX_BACKOFF_SEC))
        _log.warning("fetch_retry", url=url, attempt=attempt, reason=reason, sleeping=delay)
        self._sleep(delay)


#: Every fetcher handed out by `shared_fetcher` draws on these, so an allowance belongs to
#: the host rather than to whichever object happened to ask for it.
_SHARED_BUCKETS = _BucketRegistry()
_SHARED_FETCHERS: dict[tuple[str, bool], PoliteFetcher] = {}
_SHARED_FETCHERS_LOCK = threading.Lock()


def shared_fetcher(*, user_agent: str, respect_robots: bool = True) -> PoliteFetcher:
    """The process-wide fetcher for this User-Agent, sharing one allowance per host.

    Connectors call this rather than constructing their own, because CBN alone is three
    connector objects pointed at one host: three fetchers would be three allowances, which
    is the unthrottled behaviour with extra steps. Keyed by User-Agent because robots rules
    are addressed to an agent and a shared robots cache would answer for the wrong one.

    Constructing `PoliteFetcher` directly is still right in tests, where a fake clock must
    not leak into another test's bucket.
    """
    key = (user_agent, respect_robots)
    with _SHARED_FETCHERS_LOCK:
        fetcher = _SHARED_FETCHERS.get(key)
        if fetcher is None:
            fetcher = PoliteFetcher(
                user_agent=user_agent,
                respect_robots=respect_robots,
                buckets=_SHARED_BUCKETS,
            )
            _SHARED_FETCHERS[key] = fetcher
        return fetcher


def require_document(result: RawResponse | NotModified) -> RawResponse:
    """Narrow `get()`'s return to bytes, for a caller that asked unconditionally.

    `Connector.fetch()` is typed to return a `RawResponse`, and `get()` can return
    `NotModified`. The two are reconciled by a fact rather than by a cast: a request sent
    with neither `If-None-Match` nor `If-Modified-Since` cannot be answered `304`, so a
    connector that passes no `etag` and no `last_modified` cannot receive one.

    That is the kind of reasoning that stays true until somebody adds the etag plumbing and
    forgets this line exists. So it is checked rather than assumed, and the check raises
    with the reason instead of returning a `NotModified` out of something typed to return
    bytes - which would surface much later, as a parse error on an object with no `.data`.
    """
    if isinstance(result, RawResponse):
        return result
    raise NotModifiedError(
        f"{result.url} answered 304, but this caller sent no conditional headers and has "
        f"no branch for one. If conditional requests were just wired in here, the caller "
        f"needs to handle NotModified - skipping the run and recording the unchanged "
        f"document - rather than calling require_document()."
    )

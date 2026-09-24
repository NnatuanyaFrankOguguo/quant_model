"""Fetching politely: one place that enforces what every connector already declares. P4.8.

`docs/03` P4.8 asks for *"retries with exponential backoff, per-domain token-bucket rate
limiting, ETag/Last-Modified caching so unchanged documents are never re-fetched"*, and
`DATA_FOUNDATION.md` §3.5's politeness rules: *"respect `robots.txt`; descriptive User-Agent
with a contact email; **1 request per 2-5 seconds per domain**"*.

## What was enforced before this, exactly

Worth stating precisely, because an earlier version of this docstring said none of it ran
and that was wrong about EDGAR.

**EDGAR enforced its own.** `packages/ingestion/edgar.py` has had a process-wide `_Throttle`
since P2 - a fixed 0.12s interval, shared by all five of its connectors through
`_SHARED_THROTTLE`, with an injectable clock and a lock. It works, and this module does not
replace it.

**CBN, FRED and Yahoo enforced nothing.** Each called `httpx.get` directly with no spacing
between calls.

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

## Why the bucket is keyed on the domain

`data.sec.gov` is fetched by five different connector classes - submissions, companyfacts,
company concept, instance shares, and the shared ticker file. A limiter attached to a
connector would let five of them through at once, and SEC's limit is on the *client*, not on
whatever the client calls its code. So the bucket belongs to the host, and every connector
hitting that host shares one.

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
import urllib.robotparser
from collections.abc import Callable
from dataclasses import dataclass
from email.utils import parsedate_to_datetime
from urllib.parse import urlsplit

import httpx
import structlog

from packages.ingestion.base import RawResponse

__all__ = [
    "DEFAULT_MAX_ATTEMPTS",
    "NotModified",
    "PoliteFetcher",
    "RobotsRefusedError",
    "TokenBucket",
]

_log = structlog.get_logger(__name__)

#: Transport failures worth waiting for. A 429 is the server asking; a 5xx is the server
#: struggling; a timeout is the network. Each one is different next time.
_RETRYABLE_STATUS = frozenset({429, 500, 502, 503, 504})

#: Never retried, however many attempts remain. A 403 repeated is what turns a refusal into
#: an IP block, and a 404 does not become a 200 by being asked twice.
_TERMINAL_STATUS = frozenset({400, 401, 403, 404, 405, 410})

DEFAULT_MAX_ATTEMPTS = 3

#: Doubling, from `DATA_FOUNDATION.md` §3.5's politeness. The P1 scheduler used
#: `backoff * attempt`, which is linear - 2s, 4s, 6s - and P4.8 asks for exponential.
_BACKOFF_BASE_SEC = 2.0

#: However long a `Retry-After` asks for, never sleep longer than this in one wait. A server
#: answering "come back in six hours" should fail the run and be seen, not block a scheduler
#: thread until morning.
_MAX_BACKOFF_SEC = 120.0


class RobotsRefusedError(PermissionError):
    """`robots.txt` disallows this path for our User-Agent, so it is not fetched."""


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
        transport: Callable[..., httpx.Response] = httpx.get,
        now: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
        respect_robots: bool = True,
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
        self._buckets: dict[str, TokenBucket] = {}
        self._robots: dict[str, urllib.robotparser.RobotFileParser | None] = {}
        self._lock = threading.Lock()

    def bucket_for(self, url: str, *, rate_per_sec: float) -> TokenBucket:
        """The bucket for this URL's host, created once and shared by every caller."""
        host = _host_of(url)
        with self._lock:
            bucket = self._buckets.get(host)
            if bucket is None:
                bucket = TokenBucket(rate_per_sec, now=self._now, sleep=self._sleep)
                self._buckets[host] = bucket
                _log.info("rate_limiter_created", host=host, rate_per_sec=rate_per_sec)
            return bucket

    def _robots_allows(self, url: str) -> bool:
        if not self._respect_robots:
            return True
        host = _host_of(url)
        with self._lock:
            if host not in self._robots:
                parser = urllib.robotparser.RobotFileParser()
                parser.set_url(f"{host}/robots.txt")
                try:
                    parser.read()
                except Exception as exc:  # noqa: BLE001 - any failure means "unknown"
                    # An unreadable robots.txt is not permission and not refusal. Treating it
                    # as refusal would stop every connector the first time a host had a bad
                    # day; treating it as permission is what a browser does.
                    _log.warning("robots_unreadable", host=host, reason=type(exc).__name__)
                    self._robots[host] = None
                else:
                    self._robots[host] = parser
            parser_or_none = self._robots[host]
        if parser_or_none is None:
            return True
        return parser_or_none.can_fetch(self.user_agent, url)

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
    ) -> RawResponse | NotModified:
        """One polite GET: robots, rate limit, conditional headers, backoff.

        `etag` and `last_modified` are what we stored last time. Passing them turns the
        request conditional, and a `304` comes back as `NotModified` - which is the whole
        point of storing them, and was not happening.
        """
        if not self._robots_allows(url):
            raise RobotsRefusedError(
                f"robots.txt at {_host_of(url)} disallows {url} for {self.user_agent!r}"
            )

        headers: dict[str, str] = {"User-Agent": self.user_agent}
        if etag:
            headers["If-None-Match"] = etag
        if last_modified:
            headers["If-Modified-Since"] = last_modified.strftime("%a, %d %b %Y %H:%M:%S GMT")

        bucket = self.bucket_for(url, rate_per_sec=rate_per_sec)
        last_error: Exception | None = None

        for attempt in range(1, max_attempts + 1):
            bucket.take()
            if politeness_delay_sec:
                # On top of the bucket, for a site that never agreed to be scraped.
                self._sleep(politeness_delay_sec)
            try:
                response = self._transport(url, params=params, headers=headers, timeout=timeout)
            except httpx.HTTPError as exc:
                last_error = exc
                if attempt == max_attempts:
                    break
                self._wait(attempt, reason=type(exc).__name__, url=url)
                continue

            if response.status_code == 304:
                _log.info("not_modified", url=url, attempt=attempt)
                return NotModified(
                    url=url,
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
                url=str(response.url),
                http_status=response.status_code,
                etag=response.headers.get("ETag"),
                last_modified=_parse_http_date(response.headers.get("Last-Modified")),
            )

        raise httpx.HTTPError(
            f"{url} failed after {max_attempts} attempts"
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

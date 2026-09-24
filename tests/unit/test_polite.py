"""P4.8's politeness: the limits every connector declared and nothing enforced.

`docs/03` P4.8 asks for *"retries with exponential backoff, per-domain token-bucket rate
limiting, ETag/Last-Modified caching so unchanged documents are never re-fetched"*.
`DATA_FOUNDATION.md` §3.5 adds `robots.txt`, a contact email in the User-Agent, and
*"1 request per 2-5 seconds per domain"*.

All of it was declared. `Connector.rate_limit_per_sec` carries the figure, the licence
writes it into `data_sources`, and the base class explains the stakes in its own comment:
*"EDGAR's <=10 req/s in P2 comes with a ~10-minute IP block when exceeded - that belongs in
code, not in your head."* It was in neither. Every `fetch` called `httpx.get` directly.

No test here touches the network or the clock. The transport is a list of canned responses
and time is a counter, so a thousand simulated seconds cost nothing - which is what makes it
possible to assert on *how long a caller would have waited*, the property that matters and
the one a real-clock test has to weaken into "roughly".
"""

from __future__ import annotations

import datetime as dt

import httpx
import pytest

from packages.ingestion.base import RawResponse
from packages.ingestion.polite import (
    NotModified,
    NotModifiedError,
    PoliteFetcher,
    RobotsRefusedError,
    TokenBucket,
    redact_url,
    require_document,
    shared_fetcher,
)

pytestmark = pytest.mark.invariant

UA = "quant_model (nnatuanyafrankoguguo@churchofjesuschrist.org)"
SEC = "https://data.sec.gov/submissions/CIK0000320193.json"
SEC_OTHER = "https://data.sec.gov/api/xbrl/companyfacts/CIK0000320193.json"
NGX = "https://doclib.ngxgroup.com/Financial_NewsDocs/report.pdf"


class FakeClock:
    """A counter that only moves when something sleeps."""

    def __init__(self) -> None:
        self.seconds = 0.0
        self.slept: list[float] = []

    def now(self) -> float:
        return self.seconds

    def sleep(self, delay: float) -> None:
        self.slept.append(delay)
        self.seconds += delay

    @property
    def total_slept(self) -> float:
        return sum(self.slept)


def response(
    status: int = 200,
    *,
    body: bytes = b"{}",
    headers: dict[str, str] | None = None,
    url: str = SEC,
) -> httpx.Response:
    return httpx.Response(
        status_code=status,
        content=body,
        headers=headers or {},
        request=httpx.Request("GET", url),
    )


class FakeTransport:
    """Returns canned responses in order, and records the headers it was asked with."""

    def __init__(self, *responses: httpx.Response | Exception) -> None:
        self._queue = list(responses)
        self.calls: list[dict[str, str]] = []
        #: Every keyword the fetcher passed, per call. `follow_redirects` lives here.
        self.kwargs: list[dict[str, object]] = []

    def __call__(self, url, **kw):  # noqa: ANN001
        self.calls.append(dict(kw.get("headers") or {}))
        self.kwargs.append({"url": url, **kw})
        if not self._queue:
            raise AssertionError(f"transport called more times than it has answers: {url}")
        nxt = self._queue.pop(0)
        if isinstance(nxt, Exception):
            raise nxt
        return nxt


def robots(body: str, *, status: int = 200) -> httpx.Response:
    """A robots.txt answer, served by the transport like any other request.

    It *is* any other request: `PoliteFetcher` fetches robots.txt through its own transport
    with its own User-Agent, because `RobotFileParser.read()` uses urllib's and a host that
    blocks unknown agents answers 403 - which the parser stores as "everything disallowed".
    """
    return httpx.Response(
        status_code=status,
        content=body.encode("utf-8"),
        request=httpx.Request("GET", "https://data.sec.gov/robots.txt"),
    )


def fetcher(clock: FakeClock, transport: FakeTransport, **kwargs) -> PoliteFetcher:
    return PoliteFetcher(
        user_agent=UA,
        transport=transport,
        now=clock.now,
        sleep=clock.sleep,
        respect_robots=False,  # exercised on its own below
        **kwargs,
    )


# --------------------------------------------------------------------------------------
# The token bucket
# --------------------------------------------------------------------------------------


def test_a_burst_is_allowed_and_then_the_rate_settles() -> None:
    """A bucket, not a sliding window: three small files back to back is polite; three
    hundred is not."""
    clock = FakeClock()
    bucket = TokenBucket(2.0, now=clock.now, sleep=clock.sleep)
    assert bucket.take() == 0.0, "the first is free"
    assert bucket.take() == 0.0, "so is the second, up to capacity"
    waited = bucket.take()
    assert waited == pytest.approx(0.5), "then it settles to 2 per second"


def test_ten_requests_at_two_per_second_take_about_five_seconds() -> None:
    """The property the whole module exists for, asserted as elapsed time."""
    clock = FakeClock()
    bucket = TokenBucket(2.0, now=clock.now, sleep=clock.sleep)
    for _ in range(10):
        bucket.take()
    assert clock.total_slept == pytest.approx(4.0), "2 free from the bucket, 8 at 0.5s each"


def test_a_rate_below_one_per_second_still_permits_one_request() -> None:
    """NGX and the Nigeria Data Portal declare 0.5/s. Capacity must not round to zero."""
    clock = FakeClock()
    bucket = TokenBucket(0.5, now=clock.now, sleep=clock.sleep)
    assert bucket.take() == 0.0
    assert bucket.take() == pytest.approx(2.0), "1 request per 2 seconds, as declared"


def test_a_nonsense_rate_is_refused() -> None:
    for rate in (0, -1):
        with pytest.raises(ValueError, match="must be positive"):
            TokenBucket(rate)


# --------------------------------------------------------------------------------------
# Per domain, not per connector — the point of the whole design
# --------------------------------------------------------------------------------------


def test_two_connectors_on_one_host_share_one_allowance() -> None:
    """`data.sec.gov` is fetched by five connector classes, and SEC limits the *client*.

    A limiter attached to a connector would let five through at once and earn the ~10-minute
    block the base class warns about. So the bucket belongs to the host.
    """
    clock = FakeClock()
    transport = FakeTransport(*[response() for _ in range(4)])
    polite = fetcher(clock, transport)

    for url in (SEC, SEC_OTHER, SEC, SEC_OTHER):
        polite.get(url, rate_per_sec=1.0, media_type="application/json")

    assert polite.bucket_for(SEC, rate_per_sec=1.0) is polite.bucket_for(
        SEC_OTHER, rate_per_sec=1.0
    ), "one bucket for the host, whichever connector asks"
    assert clock.total_slept == pytest.approx(3.0), "4 requests at 1/s, one free"


def test_a_different_host_has_its_own_allowance() -> None:
    """Being slow to NGX must not make us slow to the SEC, or every night gets longer."""
    clock = FakeClock()
    transport = FakeTransport(response(), response(url=NGX))
    polite = fetcher(clock, transport)

    polite.get(SEC, rate_per_sec=1.0, media_type="application/json")
    polite.get(NGX, rate_per_sec=0.5, media_type="application/pdf")

    assert clock.total_slept == 0.0, "both hosts start full"
    assert polite.bucket_for(SEC, rate_per_sec=1.0) is not polite.bucket_for(NGX, rate_per_sec=0.5)


# --------------------------------------------------------------------------------------
# Conditional requests: the columns that were stored and never sent
# --------------------------------------------------------------------------------------


def test_a_stored_etag_is_sent_and_a_304_means_unchanged() -> None:
    """`source_documents.etag` has been written since P1 and never put on a request.

    A 304 is a success, and it is returned as `NotModified` rather than an empty
    `RawResponse` - an empty body that looks like a document is how a connector stores
    nothing and reports success.
    """
    clock = FakeClock()
    transport = FakeTransport(response(304, body=b"", headers={"ETag": '"abc"'}))
    polite = fetcher(clock, transport)

    result = polite.get(SEC, rate_per_sec=10.0, media_type="application/json", etag='"abc"')
    assert isinstance(result, NotModified)
    assert not isinstance(result, RawResponse)
    assert transport.calls[0]["If-None-Match"] == '"abc"'


def test_a_stored_last_modified_is_sent_as_if_modified_since() -> None:
    clock = FakeClock()
    transport = FakeTransport(response(304, body=b""))
    polite = fetcher(clock, transport)

    polite.get(
        SEC,
        rate_per_sec=10.0,
        media_type="application/json",
        last_modified=dt.datetime(2026, 9, 1, 12, 30, tzinfo=dt.UTC),
    )
    assert transport.calls[0]["If-Modified-Since"] == "Tue, 01 Sep 2026 12:30:00 GMT"


def test_a_200_returns_the_validators_for_next_time(clock_free: None = None) -> None:
    """The round trip: what comes back is what the next request will send."""
    clock = FakeClock()
    transport = FakeTransport(
        response(
            200,
            body=b'{"ok":true}',
            headers={"ETag": '"v2"', "Last-Modified": "Wed, 02 Sep 2026 08:00:00 GMT"},
        )
    )
    polite = fetcher(clock, transport)

    result = polite.get(SEC, rate_per_sec=10.0, media_type="application/json")
    assert isinstance(result, RawResponse)
    assert result.data == b'{"ok":true}'
    assert result.etag == '"v2"'
    assert result.last_modified == dt.datetime(2026, 9, 2, 8, 0, tzinfo=dt.UTC)


def test_no_validators_means_an_unconditional_request() -> None:
    """A first fetch must not carry headers that would make a fresh document look cached."""
    clock = FakeClock()
    transport = FakeTransport(response())
    polite = fetcher(clock, transport)
    polite.get(SEC, rate_per_sec=10.0, media_type="application/json")
    assert "If-None-Match" not in transport.calls[0]
    assert "If-Modified-Since" not in transport.calls[0]


# --------------------------------------------------------------------------------------
# Backoff: exponential, and only where waiting helps
# --------------------------------------------------------------------------------------


def test_backoff_doubles_rather_than_adding() -> None:
    """P1's scheduler used `backoff * attempt` - 2, 4, 6. P4.8 asks for exponential."""
    clock = FakeClock()
    transport = FakeTransport(response(503), response(503), response(200))
    polite = fetcher(clock, transport)

    result = polite.get(SEC, rate_per_sec=100.0, media_type="application/json")
    assert isinstance(result, RawResponse)
    assert clock.slept == [2.0, 4.0], "doubling, not 2 then 4 by addition"


def test_a_retry_after_header_is_honoured_when_it_asks_for_longer() -> None:
    """A 429 is the server telling us its limit. Arguing with it earns a block."""
    clock = FakeClock()
    transport = FakeTransport(response(429, headers={"Retry-After": "30"}), response(200))
    polite = fetcher(clock, transport)

    polite.get(SEC, rate_per_sec=100.0, media_type="application/json")
    assert clock.slept == [30.0], "the server's figure, not our 2 seconds"


def test_an_absurd_retry_after_is_capped_rather_than_obeyed() -> None:
    """ "Come back in six hours" should fail the run and be seen, not block until morning."""
    clock = FakeClock()
    transport = FakeTransport(response(503, headers={"Retry-After": "21600"}), response(200))
    polite = fetcher(clock, transport)

    polite.get(SEC, rate_per_sec=100.0, media_type="application/json")
    assert clock.slept == [120.0], "capped"


def test_a_403_is_not_retried_at_all() -> None:
    """Repeating a refusal is what turns a 403 into an IP block.

    The transport holds exactly one answer, so a second attempt would raise
    `called more times than it has answers` - which is the assertion.
    """
    clock = FakeClock()
    transport = FakeTransport(response(403))
    polite = fetcher(clock, transport)

    with pytest.raises(httpx.HTTPStatusError):
        polite.get(SEC, rate_per_sec=100.0, media_type="application/json")
    assert len(transport.calls) == 1
    assert clock.slept == [], "nothing waited for a refusal that will not change"


def test_a_404_is_answered_immediately() -> None:
    clock = FakeClock()
    transport = FakeTransport(response(404))
    polite = fetcher(clock, transport)
    with pytest.raises(httpx.HTTPStatusError):
        polite.get(SEC, rate_per_sec=100.0, media_type="application/json")
    assert len(transport.calls) == 1


def test_a_timeout_is_retried_and_then_reported() -> None:
    """The network, not the server. Worth waiting for, and worth giving up on."""
    clock = FakeClock()
    transport = FakeTransport(
        httpx.ConnectTimeout("slow"), httpx.ConnectTimeout("slow"), httpx.ConnectTimeout("slow")
    )
    polite = fetcher(clock, transport)

    with pytest.raises(httpx.HTTPError, match="failed after 3 attempts"):
        polite.get(SEC, rate_per_sec=100.0, media_type="application/json")
    assert len(transport.calls) == 3
    assert clock.slept == [2.0, 4.0]


def test_the_rate_limit_still_applies_between_retries() -> None:
    """A server returning 503 is struggling. Retrying without the bucket is piling on.

    The two waits are not added blindly, and should not be: time spent in backoff refills
    the bucket like any other time, so a 2-second backoff already satisfies a 1/s limit. The
    property is that the *slower* of the two governs.

    At 0.2/s a token takes 5 seconds and the backoff is 2, so the bucket adds the missing 3.
    My first version of this test asserted 2 + 1 = 3 seconds at 1/s and was simply wrong
    about how a refill works.
    """
    clock = FakeClock()
    transport = FakeTransport(response(503), response(200))
    polite = fetcher(clock, transport)

    polite.get(SEC, rate_per_sec=0.2, media_type="application/json")
    assert clock.slept == pytest.approx([2.0, 3.0]), "2s of backoff, then 3s for the token"
    assert clock.total_slept == pytest.approx(5.0), "one request per 5 seconds, as declared"


def test_a_backoff_longer_than_the_token_interval_needs_no_extra_wait() -> None:
    """The other side of the same rule: waiting is waiting, whatever asked for it."""
    clock = FakeClock()
    transport = FakeTransport(response(503), response(200))
    polite = fetcher(clock, transport)

    polite.get(SEC, rate_per_sec=1.0, media_type="application/json")
    assert clock.slept == [2.0], "the 2s backoff already covers a 1/s limit"


# --------------------------------------------------------------------------------------
# robots.txt and the User-Agent
# --------------------------------------------------------------------------------------


def test_a_user_agent_without_a_contact_is_refused() -> None:
    """`DATA_FOUNDATION` §3.5 asks for a contact email; SEC requires one.

    A source that would rather complain than block us needs somewhere to complain to.
    """
    with pytest.raises(ValueError, match="contact email"):
        PoliteFetcher(user_agent="quant_model/1.0")


def test_the_user_agent_is_sent_on_every_request() -> None:
    clock = FakeClock()
    transport = FakeTransport(response(), response())
    polite = fetcher(clock, transport)
    polite.get(SEC, rate_per_sec=100.0, media_type="application/json")
    polite.get(SEC, rate_per_sec=100.0, media_type="application/json")
    assert all(call["User-Agent"] == UA for call in transport.calls)


def test_a_disallowed_path_is_not_fetched() -> None:
    """The request is never made, rather than made and discarded.

    This is Yahoo's robots.txt verbatim - `query2.finance.yahoo.com` really does disallow
    every path to every agent, which is why that connector carries a named, documented
    exception rather than a flag somebody flipped.
    """
    clock = FakeClock()
    transport = FakeTransport(robots("User-agent: *\nDisallow: /"))
    polite = PoliteFetcher(user_agent=UA, transport=transport, now=clock.now, sleep=clock.sleep)

    with pytest.raises(RobotsRefusedError, match="disallows"):
        polite.get(NGX, rate_per_sec=1.0, media_type="application/pdf")
    # One call, for robots.txt itself. The document was never asked for.
    assert len(transport.kwargs) == 1
    assert transport.kwargs[0]["url"].endswith("/robots.txt")


def test_an_unreadable_robots_file_does_not_stop_everything() -> None:
    """Unknown is not refusal.

    Treating it as refusal stops every connector the first time a host has a bad day; a
    browser would carry on, and so does this.
    """
    clock = FakeClock()
    transport = FakeTransport(httpx.ConnectError("no route to host"), response(url=NGX))
    polite = PoliteFetcher(user_agent=UA, transport=transport, now=clock.now, sleep=clock.sleep)

    result = polite.get(NGX, rate_per_sec=1.0, media_type="application/pdf")
    assert isinstance(result, RawResponse)


def test_a_403_on_robots_txt_is_not_a_blanket_refusal() -> None:
    """The bug that would have disabled CBN the day this module was wired in.

    `RobotFileParser.read()` fetches with urllib's own agent. `www.cbn.gov.ng` answers that
    agent 403, and the parser stores a 403 as `disallow_all` - so every path on a site
    whose robots.txt says `Allow: /` came back refused, with an error message blaming
    robots.txt for it. Fetching as ourselves is the real fix; this is the backstop for the
    day a WAF blocks us too.

    RFC 9309 §2.3.1.3 is explicit that an unavailable robots.txt means no restrictions, so
    this is the standard's answer and not a convenience.
    """
    clock = FakeClock()
    transport = FakeTransport(robots("", status=403), response(url=NGX))
    polite = PoliteFetcher(user_agent=UA, transport=transport, now=clock.now, sleep=clock.sleep)

    assert isinstance(polite.get(NGX, rate_per_sec=1.0, media_type="application/pdf"), RawResponse)


def test_robots_txt_is_fetched_as_us() -> None:
    """Our User-Agent, not urllib's - which is the whole reason the 403 above happened."""
    clock = FakeClock()
    transport = FakeTransport(robots("User-agent: *\nAllow: /"), response())
    polite = PoliteFetcher(user_agent=UA, transport=transport, now=clock.now, sleep=clock.sleep)
    polite.get(SEC, rate_per_sec=100.0, media_type="application/json")

    assert transport.kwargs[0]["url"].endswith("/robots.txt")
    assert transport.calls[0]["User-Agent"] == UA


def test_robots_is_read_once_per_host() -> None:
    """Fetching robots.txt before every request would double the traffic it exists to limit."""
    clock = FakeClock()
    transport = FakeTransport(robots("User-agent: *\nAllow: /"), response(), response(), response())
    polite = PoliteFetcher(user_agent=UA, transport=transport, now=clock.now, sleep=clock.sleep)
    for _ in range(3):
        polite.get(SEC, rate_per_sec=100.0, media_type="application/json")

    fetched = [k["url"] for k in transport.kwargs if str(k["url"]).endswith("/robots.txt")]
    assert len(fetched) == 1


# --------------------------------------------------------------------------------------
# What wiring the connectors exposed
#
# Each of these is a regression that the wiring would have introduced, written down before
# the wiring rather than after it. None of them is hypothetical: the FRED key is in the URL
# today, CBN passes `follow_redirects=True` today, and `api.stlouisfed.org` publishes a
# `Crawl-delay` today that disagrees with FRED's declared rate by a factor of ten.
# --------------------------------------------------------------------------------------

FRED = "https://api.stlouisfed.org/fred/series/observations"


def test_redact_url_strips_a_credential_but_keeps_the_question() -> None:
    """A stored URL must survive being read by someone who should not have the key.

    `source_documents.url` is kept forever. Which parameters were sent is provenance and
    stays; what the key was set to is a live credential and goes.
    """
    cleaned = redact_url(f"{FRED}?series_id=DGS10&api_key=deadbeefcafe&file_type=json")
    assert "deadbeefcafe" not in cleaned
    assert "api_key=REDACTED" in cleaned
    assert "series_id=DGS10" in cleaned
    assert "file_type=json" in cleaned


def test_redact_url_leaves_an_innocent_url_byte_identical() -> None:
    """Re-encoding every URL would churn the ones that never had a secret in them."""
    url = "https://www.cbn.gov.ng/api/GetAllExchangeRates"
    assert redact_url(url) is url or redact_url(url) == url


def test_a_credential_in_the_query_never_reaches_the_recorded_url() -> None:
    """The floor under a connector that forgets to strip its own key.

    FRED does strip it. This asserts that a connector which did not would still not write
    a live key into the permanent register.
    """
    clock = FakeClock()
    requested = f"{FRED}?series_id=DGS10&api_key=deadbeefcafe"
    transport = FakeTransport(response(url=requested))
    raw = fetcher(clock, transport).get(
        requested, rate_per_sec=100.0, media_type="application/json"
    )
    assert isinstance(raw, RawResponse)
    assert raw.url is not None
    assert "deadbeefcafe" not in raw.url


def test_record_url_is_stored_and_the_requested_url_is_fetched() -> None:
    """They differ on purpose: FRED asks with a key and records without one."""
    clock = FakeClock()
    asked = f"{FRED}?series_id=DGS10&api_key=secret"
    transport = FakeTransport(response(url=asked))
    raw = fetcher(clock, transport).get(
        asked,
        rate_per_sec=100.0,
        media_type="application/json",
        record_url=f"{FRED}?series_id=DGS10&file_type=json",
    )
    assert isinstance(raw, RawResponse)
    assert raw.url == f"{FRED}?series_id=DGS10&file_type=json"
    assert transport.kwargs[0]["url"] == asked


def test_redirects_are_followed_because_cbn_needs_them() -> None:
    """`httpx.get` defaults to not following, and an unfollowed 3xx raises.

    CBN passed `follow_redirects=True` explicitly before this module existed. Routing it
    through a fetcher that dropped the flag would have turned every redirect into an error.
    """
    clock = FakeClock()
    transport = FakeTransport(response())
    fetcher(clock, transport).get(SEC, rate_per_sec=100.0, media_type="application/json")
    assert transport.kwargs[0]["follow_redirects"] is True


def test_one_host_one_allowance_across_connectors() -> None:
    """CBN is three connector objects pointed at one host.

    Three fetchers would be three allowances, which is the unthrottled behaviour with extra
    steps - so the shared accessor has to hand back one bucket per host, not one per caller.
    """
    first = shared_fetcher(user_agent=UA, respect_robots=False)
    second = shared_fetcher(user_agent=UA, respect_robots=False)
    assert first is second
    assert first.bucket_for(SEC, rate_per_sec=1.0) is second.bucket_for(SEC_OTHER, rate_per_sec=1.0)


def test_a_directly_built_fetcher_keeps_its_own_buckets() -> None:
    """Otherwise one test's fake clock ends up inside another test's bucket.

    Which, under `pytest-randomly`, would fail in whichever order happened to come up.
    """
    own = PoliteFetcher(user_agent=UA, transport=FakeTransport(), respect_robots=False)
    assert own.bucket_for(SEC, rate_per_sec=1.0) is not shared_fetcher(
        user_agent=UA, respect_robots=False
    ).bucket_for(SEC, rate_per_sec=1.0)


def test_crawl_delay_lowers_a_rate_we_declared_too_high() -> None:
    """`api.stlouisfed.org` asks for 2 seconds. Our FRED connector declares 5 a second.

    Only one of those numbers belongs to the host. Before this, nothing read it: the host
    published a limit and we fetched ten times faster than it asked for.
    """

    clock = FakeClock()
    # `api.stlouisfed.org/robots.txt`, verbatim.
    transport = FakeTransport(
        robots("# Allows all robots to visit all files.\nUser-agent: *\nCrawl-delay: 2\nDisallow:"),
        response(),
        response(),
    )
    polite = PoliteFetcher(user_agent=UA, transport=transport, now=clock.now, sleep=clock.sleep)
    for _ in range(2):
        polite.get(FRED, rate_per_sec=5.0, media_type="application/json")
    # 0.5/s, so the second call waits 2s - not the 0.2s that 5/s would have allowed.
    assert clock.total_slept == pytest.approx(2.0)


def test_crawl_delay_never_speeds_us_up() -> None:
    """A permissive host is not permission to exceed what we declared.

    The declared figure is a promise we made in `data_sources`; `Crawl-delay` is a ceiling
    the host set. The effective rate is the lower of the two, in both directions.
    """

    clock = FakeClock()
    transport = FakeTransport(
        robots("User-agent: *\nCrawl-delay: 0.001\nDisallow:"),  # 1000/s
        response(),
        response(),
    )
    polite = PoliteFetcher(user_agent=UA, transport=transport, now=clock.now, sleep=clock.sleep)
    for _ in range(2):
        polite.get(NGX, rate_per_sec=0.5, media_type="application/pdf")
    assert clock.total_slept == pytest.approx(2.0)  # our 0.5/s, not the host's 1000/s


def test_require_document_refuses_to_hand_back_a_304() -> None:
    """The narrowing that lets `Connector.fetch()` keep returning `RawResponse`.

    A request with no conditional headers cannot be answered 304, so this should be
    unreachable. If it is ever reached, someone wired conditional requests into a caller
    that has no branch for the answer, and a loud failure here beats a `NotModified`
    returned from something typed to return bytes - which surfaces much later as an
    AttributeError on `.data`.
    """
    with pytest.raises(NotModifiedError, match="no branch for one"):
        require_document(NotModified(url=SEC, etag='W/"1"', last_modified=None))


def test_require_document_passes_a_real_document_through() -> None:
    raw = RawResponse(data=b"{}", media_type="application/json", url=SEC)
    assert require_document(raw) is raw


# --------------------------------------------------------------------------------------
# POST
#
# The connector my first survey missed. I grepped for `httpx.get` and reported that the
# Nigeria Data Portal made no requests; it makes them with `httpx.post`, on a schedule,
# and its own comment records the portal answering 403 to a second request issued
# immediately after the first. The gap there is not theoretical - it has already been hit.
# --------------------------------------------------------------------------------------


def test_a_post_carries_its_body_and_records_the_url_we_chose() -> None:
    """A POST body is not in the URL, so `record_url` is the only provenance there is.

    Without it a stored document says "the pivot endpoint" and nothing about which series
    it holds, which is unrecoverable six months later.
    """
    clock = FakeClock()
    transport = FakeTransport(response(body=b'{"data": []}'))
    asked = "https://nigeria.opendataforafrica.test/api/1.0/data/pivot"
    raw = fetcher(clock, transport).post(
        asked,
        rate_per_sec=0.5,
        media_type="application/json",
        json={"dataset": "NGNBSNCPIR2017"},
        record_url=f"{asked}?dataset=NGNBSNCPIR2017&item=All+Items",
    )
    assert raw.url == f"{asked}?dataset=NGNBSNCPIR2017&item=All+Items"
    assert transport.kwargs[0]["method"] == "POST"
    assert transport.kwargs[0]["json"] == {"dataset": "NGNBSNCPIR2017"}


def test_a_post_is_tried_once_unless_the_caller_says_otherwise() -> None:
    """A retried POST the server already processed is the work happening twice.

    A GET is safe to repeat and a POST is not, so the default differs from `get`'s. A
    caller whose POST is really a query opts in, which is what the portal connector does.
    """
    clock = FakeClock()
    transport = FakeTransport(response(status=503), response(status=503), response())
    with pytest.raises(httpx.HTTPStatusError):
        fetcher(clock, transport).post(
            SEC, rate_per_sec=10.0, media_type="application/json", json={}
        )
    assert len(transport.kwargs) == 1  # no second attempt
    assert clock.total_slept == 0.0  # and no backoff wait either


def test_a_post_that_is_really_a_query_may_retry() -> None:
    """The portal's pivot endpoint is a read. Repeating it costs nothing but politeness."""
    clock = FakeClock()
    transport = FakeTransport(response(status=503), response(body=b'{"data": []}'))
    raw = fetcher(clock, transport).post(
        SEC, rate_per_sec=10.0, media_type="application/json", json={}, max_attempts=2
    )
    assert raw.data == b'{"data": []}'
    assert len(transport.kwargs) == 2


def test_a_redirected_post_is_raised_rather_than_quietly_turned_into_a_get() -> None:
    """httpx does what browsers do, and for a query expressed as a POST that is wrong.

    `httpx._client.BaseClient._redirect_method` rewrites a redirected POST into a GET on
    301, 302 and 303 alike. The body goes with it, so the portal answers a question nobody
    asked, with a 200 that `raise_for_status` has no reason to object to. Left unfollowed,
    the 3xx is raised - which is the outcome worth having, because a wrong answer stored
    under the right URL is unrecoverable later.
    """
    clock = FakeClock()
    transport = FakeTransport(response(status=302, headers={"Location": "/elsewhere"}))
    with pytest.raises(httpx.HTTPStatusError):
        fetcher(clock, transport).post(
            SEC, rate_per_sec=10.0, media_type="application/json", json={"q": 1}
        )
    assert transport.kwargs[0]["follow_redirects"] is False

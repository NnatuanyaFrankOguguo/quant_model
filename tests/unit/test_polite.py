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
    PoliteFetcher,
    RobotsRefusedError,
    TokenBucket,
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

    def __call__(self, url, *, params=None, headers=None, timeout=None):  # noqa: ANN001
        self.calls.append(dict(headers or {}))
        if not self._queue:
            raise AssertionError(f"transport called more times than it has answers: {url}")
        nxt = self._queue.pop(0)
        if isinstance(nxt, Exception):
            raise nxt
        return nxt


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


def test_a_disallowed_path_is_not_fetched(monkeypatch: pytest.MonkeyPatch) -> None:
    """The request is never made, rather than made and discarded."""

    class Disallowing:
        def set_url(self, url: str) -> None: ...
        def read(self) -> None: ...
        def can_fetch(self, agent: str, url: str) -> bool:
            return False

    monkeypatch.setattr("urllib.robotparser.RobotFileParser", Disallowing)
    clock = FakeClock()
    transport = FakeTransport()  # no answers: being called at all is the failure
    polite = PoliteFetcher(user_agent=UA, transport=transport, now=clock.now, sleep=clock.sleep)

    with pytest.raises(RobotsRefusedError, match="disallows"):
        polite.get(NGX, rate_per_sec=1.0, media_type="application/pdf")
    assert transport.calls == []


def test_an_unreadable_robots_file_does_not_stop_everything(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Unknown is not refusal. Treating it as refusal stops every connector the first time
    a host has a bad day; a browser would carry on, and so does this."""

    class Unreadable:
        def set_url(self, url: str) -> None: ...
        def read(self) -> None:
            raise OSError("no robots.txt here")

        def can_fetch(self, agent: str, url: str) -> bool:  # pragma: no cover
            raise AssertionError("should not be consulted after a failed read")

    monkeypatch.setattr("urllib.robotparser.RobotFileParser", Unreadable)
    clock = FakeClock()
    transport = FakeTransport(response(url=NGX))
    polite = PoliteFetcher(user_agent=UA, transport=transport, now=clock.now, sleep=clock.sleep)

    result = polite.get(NGX, rate_per_sec=1.0, media_type="application/pdf")
    assert isinstance(result, RawResponse)


def test_robots_is_read_once_per_host(monkeypatch: pytest.MonkeyPatch) -> None:
    """Fetching robots.txt before every request would double the traffic it exists to limit."""
    reads = {"count": 0}

    class CountingRobots:
        def set_url(self, url: str) -> None: ...
        def read(self) -> None:
            reads["count"] += 1

        def can_fetch(self, agent: str, url: str) -> bool:
            return True

    monkeypatch.setattr("urllib.robotparser.RobotFileParser", CountingRobots)
    clock = FakeClock()
    transport = FakeTransport(response(), response(), response())
    polite = PoliteFetcher(user_agent=UA, transport=transport, now=clock.now, sleep=clock.sleep)
    for _ in range(3):
        polite.get(SEC, rate_per_sec=100.0, media_type="application/json")
    assert reads["count"] == 1

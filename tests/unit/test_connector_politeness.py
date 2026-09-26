"""What each connector's `fetch` does now that it goes through `PoliteFetcher`.

Until this file, `fetch` was the one method of CBN, FRED and Yahoo with no test at all.
`test_cbn_connector.py` and `test_yahoo.py` hand canned bytes to `parse` and `write`, which
is the right shape for those - but it means the network path was covered by nothing, and
the network path is where the declared rate, the stored URL and FRED's 400 branch live.

Three of the five assertions here are regressions the wiring could have introduced, and one
- the API key in the stored URL - would have been silent, permanent and unnoticed until
somebody read `source_documents` who should not have had the key.

Nothing here touches the network or the clock: each connector is handed a fetcher built on
a list of canned responses and a counter.
"""

from __future__ import annotations

import httpx
import pytest

from packages.ingestion import cbn, yahoo
from packages.ingestion.base import RawResponse
from packages.ingestion.cbn import CbnExchangeRateConnector
from packages.ingestion.fred import FredConnector, VintageLimitExceededError
from packages.ingestion.polite import PoliteFetcher
from packages.ingestion.yahoo import YahooChartConnector

_CBN_RATES = "https://www.cbn.gov.ng/api/GetAllExchangeRates"

pytestmark = pytest.mark.invariant


class Clock:
    """Time only moves when something sleeps, so a slow rate costs the test nothing."""

    def __init__(self) -> None:
        self.seconds = 0.0
        self.slept: list[float] = []

    def now(self) -> float:
        return self.seconds

    def sleep(self, delay: float) -> None:
        self.slept.append(delay)
        self.seconds += delay


class Transport:
    """Canned answers, and a record of exactly what it was asked."""

    def __init__(self, *responses: httpx.Response) -> None:
        self._queue = list(responses)
        self.urls: list[str] = []
        self.params: list[dict[str, object] | None] = []
        self.headers: list[dict[str, str]] = []
        self.kwargs: list[dict[str, object]] = []

    def __call__(self, url, **kw):  # noqa: ANN001
        self.urls.append(url)
        self.params.append(kw.get("params"))
        self.headers.append(dict(kw.get("headers") or {}))
        self.kwargs.append({"url": url, **kw})
        if not self._queue:
            raise AssertionError(f"transport asked {url} with no answer left")
        return self._queue.pop(0)


def ok(body: bytes = b"{}", *, url: str = "https://example.test/x") -> httpx.Response:
    return httpx.Response(200, content=body, request=httpx.Request("GET", url))


def polite(clock: Clock, transport: Transport) -> PoliteFetcher:
    return PoliteFetcher(
        user_agent="quant_model/0.1 (test@example.test) research",
        transport=transport,
        now=clock.now,
        sleep=clock.sleep,
        respect_robots=False,  # robots itself is covered in `test_polite.py`
    )


# --------------------------------------------------------------------------------------
# FRED
# --------------------------------------------------------------------------------------


def test_fred_asks_with_the_key_and_records_without_it() -> None:
    """The one that would have been silent.

    `source_documents.url` is kept forever and read by people who are not the owner. The
    request has to carry the key and the stored row must not, and both halves of that are
    worth asserting because only one of them is visible afterwards.
    """
    clock = Clock()
    transport = Transport(ok(b'{"observations": []}'))
    connector = FredConnector(api_key="deadbeefcafe", fetcher=polite(clock, transport))

    raw = connector.fetch(series_id="DGS10")

    assert transport.params[0]["api_key"] == "deadbeefcafe"  # asked with it
    assert isinstance(raw, RawResponse)
    assert raw.url is not None
    assert "deadbeefcafe" not in raw.url  # recorded without it
    assert "series_id=DGS10" in raw.url
    assert "realtime_start=" in raw.url  # the window survives; without it the file is unplaceable


def test_fred_still_explains_the_vintage_cap() -> None:
    """A 400 is terminal to the fetcher, which raises before the caller sees the body.

    FRED puts the actionable reason in that body - *"exceeds the maximum number of vintage
    dates"* - and the advice that follows it is the difference between a user who knows to
    load `DGS10` in windows and one who files a bug. The response rides along on the
    exception, so routing through the fetcher costs nothing here, but only if somebody
    remembers to unwrap it.
    """
    refusal = httpx.Response(
        400,
        json={"error_message": "This exceeds the maximum number of vintage dates allowed"},
        request=httpx.Request("GET", "https://api.stlouisfed.org/fred/series/observations"),
    )
    clock = Clock()
    connector = FredConnector(api_key="k", fetcher=polite(clock, Transport(refusal)))

    with pytest.raises(VintageLimitExceededError, match="windows_from_vintage_dates"):
        connector.fetch(series_id="DGS10")


def test_fred_lets_an_ordinary_400_stay_a_400() -> None:
    """Only the vintage-cap refusal is translated. A bad key is not a windowing problem."""
    refusal = httpx.Response(
        400,
        json={"error_message": "Bad Request. The value for variable api_key is not registered"},
        request=httpx.Request("GET", "https://api.stlouisfed.org/fred/series/observations"),
    )
    clock = Clock()
    connector = FredConnector(api_key="wrong", fetcher=polite(clock, Transport(refusal)))

    with pytest.raises(httpx.HTTPStatusError):
        connector.fetch(series_id="DGS10")


def test_fred_declares_the_rate_its_host_publishes() -> None:
    """`api.stlouisfed.org/robots.txt` carries `Crawl-delay: 2`, which is 0.5/s.

    This used to be 5.0 and call itself conservative. `declare_licence()` writes it into
    `data_sources`, so a figure that disagrees with the host's is not a small thing: it is
    the stored number being wrong, which is the problem this whole change exists to fix.
    """
    assert FredConnector.rate_limit_per_sec == 0.5


# --------------------------------------------------------------------------------------
# CBN
# --------------------------------------------------------------------------------------


def test_cbn_spends_its_declared_rate_and_delay() -> None:
    """0.5/s plus a 2s politeness delay, both of which reached nothing before.

    Asserting the total wait is the point: the figures in `data_sources` are now the
    figures that run, rather than documentation nobody read.
    """
    clock = Clock()
    transport = Transport(ok(b"[]"), ok(b"[]"))
    fetcher = polite(clock, transport)
    connector = CbnExchangeRateConnector(fetcher=fetcher)

    connector.fetch()
    connector.fetch()

    assert connector.rate_limit_per_sec == 0.5
    assert connector.politeness_delay_sec == 2.0
    # The declared rate reached the bucket, which is the thing that was not happening.
    assert fetcher.bucket_for(_CBN_RATES, rate_per_sec=999).rate_per_sec == 0.5
    # Two politeness delays and nothing else. The delay does all the work here: 2s of
    # waiting refills exactly the half-token-per-second the next call needs, so the bucket
    # never bites for CBN. Worth writing down, because the obvious guess is 6s - it was
    # mine - and it double-counts a wait that has already happened.
    assert sum(clock.slept) == pytest.approx(4.0)


def test_cbn_follows_redirects() -> None:
    """It passed `follow_redirects=True` before this module existed, and needed to.

    `httpx.get` defaults to not following, and an unfollowed 3xx reaches
    `raise_for_status()`, which raises. The site was rebuilt once already and the old
    paths moved rather than vanished, so dropping the flag would break it on the next move.
    """

    class Recording(Transport):
        seen: list[object] = []  # noqa: RUF012

        def __call__(self, url, *, follow_redirects=None, **kw):  # noqa: ANN001
            Recording.seen.append(follow_redirects)
            return super().__call__(url, follow_redirects=follow_redirects, **kw)

    Recording.seen = []
    clock = Clock()
    CbnExchangeRateConnector(fetcher=polite(clock, Recording(ok(b"[]")))).fetch()
    assert Recording.seen == [True]


def test_cbn_sends_a_user_agent_that_can_be_replied_to() -> None:
    """A source that wants to complain before blocking us needs somewhere to complain to.

    Asserted on the constant rather than on a sent header, because the agent belongs to the
    fetcher now - a test that injects its own fetcher is asserting on its own string.
    """
    assert "@" in cbn._USER_AGENT


# --------------------------------------------------------------------------------------
# Yahoo
# --------------------------------------------------------------------------------------


def test_yahoo_records_both_ends_of_the_window() -> None:
    """The recorded URL is built by hand rather than taken from the response.

    `params` comes back in whatever order httpx encoded it, and which slice of history a
    stored file covers is the one thing you cannot recover from the bytes.
    """
    clock = Clock()
    transport = Transport(ok(b'{"chart": {"result": []}}'))
    connector = YahooChartConnector(fetcher=polite(clock, transport))

    raw = connector.fetch(symbol="aapl", lookback_days=30)

    assert isinstance(raw, RawResponse)
    assert raw.url is not None
    assert "/v8/finance/chart/AAPL" in raw.url  # symbol upper-cased, as before
    assert "period1=" in raw.url
    assert "period2=" in raw.url


def test_yahoo_user_agent_stays_browser_shaped_and_gains_a_contact() -> None:
    """Both halves matter, and they pull in opposite directions.

    The chart endpoint refuses clients that are not browser-shaped, so the `Mozilla/5.0`
    prefix has to stay. `PoliteFetcher` refuses a User-Agent with no contact in it, and it
    is right to: the old string gave Yahoo nowhere to send a complaint before blocking us.
    """
    assert yahoo._USER_AGENT.startswith("Mozilla/5.0")
    assert "@" in yahoo._USER_AGENT
    # And the constant is reachable by the fetcher that would reject it, which is what
    # makes the second assertion more than a string check.
    PoliteFetcher(user_agent=yahoo._USER_AGENT, respect_robots=False)

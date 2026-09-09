"""FRED / ALFRED connector. P1.2.

🟢 The easiest real data in the project: a free key, a documented REST API, and years of
stability. That is exactly why it is first — `docs/03` P1 puts it here so the infrastructure
mistakes get made on data that is not also fighting you.

**Why ALFRED rather than FRED.** The plain observations endpoint returns the series *as it
is today*. ALFRED — the same endpoint with a realtime range — returns every **vintage**: the
value as it was known on each date, with `realtime_start` being the date that value first
became public. That is `known_as_of`, supplied by the source rather than guessed, and it is
the one thing that makes a point-in-time backtest honest. Most sources will never give it to
us; taking it for free here means the schema is exercised correctly from the first row.

**Missing values are `None`, never zero.** FRED encodes "no observation" as `"."`. SPEC §4.1:
*never infer missing financial data*. A `0.0` here would be a fabricated data point that
looks exactly like a real one, and it would be indistinguishable six months later.
"""

from __future__ import annotations

import datetime as dt
import json
from decimal import Decimal, InvalidOperation

import httpx

from packages.common.config import get_settings
from packages.ingestion.base import (
    Connector,
    DataSourceLicence,
    MacroRecord,
    RawResponse,
)

__all__ = [
    "FRED_SERIES",
    "FredConnector",
    "MissingApiKeyError",
    "VintageLimitExceededError",
    "windows_from_vintage_dates",
]

_BASE_URL = "https://api.stlouisfed.org/fred/series/observations"

#: The FRED half of the P1 series list (`docs/03` P1). The Nigerian series here come from
#: FRED's World Bank mirror, which lags and does not carry MPR decisions, T-bill stop rates
#: or DMO auction results at all — those need CBN/NBS/DMO directly, which is why the manual
#: CSV path exists rather than pretending the mirror is enough.
FRED_SERIES: dict[str, str] = {
    "FEDFUNDS": "US_FED_FUNDS",
    "CPIAUCSL": "US_CPI_INDEX",
    "DGS10": "US_10Y_TREASURY",
    "FPCPITOTLZGNGA": "NG_CPI_YOY_WB",
}


class MissingApiKeyError(Exception):
    """No `FRED_API_KEY`. The connector refuses to run rather than half-running."""


class VintageLimitExceededError(Exception):
    """The real-time window holds more vintage dates than FRED will return at once."""


class FredConnector(Connector):
    """One series per run. `run()` is called once per series by the scheduler."""

    name = "fred"
    #: FRED does not publish a hard limit; this is deliberately conservative for a free API
    #: we depend on and do not pay for.
    rate_limit_per_sec = 5.0
    politeness_delay_sec = 0.2

    def __init__(self, *, api_key: str | None = None, timeout_sec: float = 30.0) -> None:
        self._api_key = api_key
        self._timeout = timeout_sec

    @property
    def api_key(self) -> str:
        key = self._api_key or get_settings().fred_api_key
        if not key:
            raise MissingApiKeyError(
                "FRED_API_KEY is not set. Get a free key at "
                "https://fredaccount.stlouisfed.org/apikeys and put it in .env. "
                "Until then use the manual CSV path (packages.ingestion.manual_csv), "
                "which needs no key."
            )
        return key

    def declare_licence(self) -> DataSourceLicence:
        """Matches the reviewed `data_sources` row seeded in migration 0004.

        `redistribution_allowed=False` is the conservative answer, and it is the honest one:
        FRED aggregates series from many providers under differing terms, so blanket
        redistribution rights cannot be asserted from the fact that the API is free. The
        series we actually redistribute must be cleared individually before any public tier
        or bulk export exists (ADR-0010).
        """
        return DataSourceLicence(
            source_name="FRED",
            base_url="https://api.stlouisfed.org/fred",
            licence_type="public_api_attribution",
            redistribution_allowed=False,
            attribution_required=True,
            attribution_text="Source: Federal Reserve Bank of St. Louis (FRED)",
            terms_url="https://fred.stlouisfed.org/legal/",
            terms_reviewed_on=dt.date(2026, 9, 1),
            reviewed_by="nnatuanyafrankoguguo",
            rate_limit_per_sec=self.rate_limit_per_sec,
            notes=(
                "Free API key required. ALFRED realtime range gives true vintages, so "
                "known_as_of comes from the source rather than being assumed. FRED "
                "re-publishes third-party series under varying terms; redistribution is "
                "therefore not asserted at the source level."
            ),
        )

    def vintage_dates(self, series_id: str) -> list[dt.date]:
        """Every date on which FRED published a new vintage of this series.

        A *planning* call, deliberately outside the `fetch`/`parse` contract: it decides how
        many runs a backfill needs, and does not itself produce records. Keeping it separate
        is what lets `parse()` stay pure.
        """
        response = httpx.get(
            _VINTAGE_URL,
            params={"series_id": series_id, "api_key": self.api_key, "file_type": "json"},
            timeout=self._timeout,
        )
        response.raise_for_status()
        payload = response.json()
        dates: list[dt.date] = []
        for item in payload.get("vintage_dates", []):
            parsed = _parse_date(item)
            if parsed is not None:
                dates.append(parsed)
        return dates

    def fetch(self, **params: object) -> RawResponse:
        """One FRED series over one real-time window.

        `realtime_start=1776-07-04` is FRED's own sentinel for "the beginning of time"; with
        `realtime_end=9999-12-31` it asks for every vintage rather than only today's view.
        That is the default, and it is what most series need.

        **It does not work for every series, and the failure is a hard 400.** FRED caps a
        JSON response at 2,000 vintage dates. `DGS10` has 5,104 and is simply refused:
        *"This exceeds the maximum number of vintage dates allowed for this file type."*
        So the window is a parameter, and a long-history daily series is loaded as several
        runs — see :meth:`vintage_dates` and
        :func:`windows_from_vintage_dates`. One run is still one fetch and one parse, so the
        contract in `docs/08` §5 holds; there are just more runs.
        """
        series_id = str(params["series_id"])
        realtime_start = str(params.get("realtime_start") or "1776-07-04")
        realtime_end = str(params.get("realtime_end") or "9999-12-31")
        query = {
            "series_id": series_id,
            "api_key": self.api_key,
            "file_type": "json",
            "realtime_start": realtime_start,
            "realtime_end": realtime_end,
        }
        response = httpx.get(_BASE_URL, params=query, timeout=self._timeout)
        if response.status_code == 400 and "vintage dates" in response.text:
            # Say what to do about it. The raw message names the count and the cap, which is
            # the number you need in order to pick a window size.
            raise VintageLimitExceededError(
                f"FRED refused {series_id} for {realtime_start}..{realtime_end}: too many "
                f"vintage dates in one request. Load it in windows — see "
                f"packages.ingestion.fred.windows_from_vintage_dates(). FRED said: "
                f"{response.json().get('error_message', '')}"
            )
        response.raise_for_status()
        return RawResponse(
            data=response.content,
            media_type="application/json",
            # The stored URL has the key stripped. Raw responses are kept forever and the
            # register is read by people who are not the owner; a live credential must not
            # be one of the things preserved forever alongside them. The real-time window is
            # kept, because without it you cannot tell which slice of history this file is.
            url=(
                f"{_BASE_URL}?series_id={series_id}&file_type=json"
                f"&realtime_start={realtime_start}&realtime_end={realtime_end}"
            ),
            http_status=response.status_code,
            etag=response.headers.get("etag"),
        )

    def parse(self, raw: RawResponse) -> list[MacroRecord]:
        """Pure: same bytes in, same records out. No network, no clock, no settings."""
        payload = json.loads(raw.data.decode("utf-8"))
        series_id = _series_id_from(payload, raw)
        code = FRED_SERIES.get(series_id, series_id)
        records: list[MacroRecord] = []
        for observation in payload.get("observations", []):
            as_of = _parse_date(observation.get("date"))
            known_as_of = _parse_date(observation.get("realtime_start"))
            if as_of is None or known_as_of is None:
                continue
            records.append(
                MacroRecord(
                    series_code=code,
                    as_of_date=as_of,
                    known_as_of=known_as_of,
                    value=_parse_value(observation.get("value")),
                )
            )
        return records


def _series_id_from(payload: dict[str, object], raw: RawResponse) -> str:
    """Recover the series id, which the observations payload does not echo back.

    Taken from the request URL we stored. Keeping `parse()` pure means it cannot ask the
    network which series this was, so the answer has to travel with the raw response.
    """
    url = raw.url or ""
    for part in url.split("?", 1)[-1].split("&"):
        if part.startswith("series_id="):
            return part.removeprefix("series_id=")
    raise ValueError("cannot determine series_id from the stored raw response URL")


def _parse_date(value: object) -> dt.date | None:
    if not isinstance(value, str):
        return None
    try:
        return dt.date.fromisoformat(value)
    except ValueError:
        return None


def _parse_value(value: object) -> Decimal | None:
    """`"."` means no observation. It becomes NULL, never 0 (SPEC §4.1)."""
    if not isinstance(value, str) or value.strip() in {"", "."}:
        return None
    try:
        return Decimal(value.strip())
    except InvalidOperation:
        return None


#: FRED's cap on vintage dates in one JSON response. Not configurable by us; discovered by
#: being refused. Windows are sized under it so a series that gains vintages between runs
#: does not start failing on a boundary.
FRED_MAX_VINTAGE_DATES = 2000

_VINTAGE_URL = "https://api.stlouisfed.org/fred/series/vintagedates"

#: FRED's sentinel for "and everything after today". It is the ONLY future value the API
#: accepts: any other `realtime_end` beyond today is a 400.
REALTIME_MAX = "9999-12-31"


def windows_from_vintage_dates(
    dates: list[dt.date], *, max_per_window: int = 1500
) -> list[tuple[str, str]]:
    """Turn a series' real vintage dates into request windows.

    Windowing by *calendar* guesswork fails twice over, and both failures are 400s that say
    nothing useful until you read the body:

    * a window before the series' first vintage is refused with *"the series does not exist
      in ALFRED"* — it exists, it just has no vintages that far back;
    * a window whose `realtime_end` is in the future is refused outright, because FRED
      accepts no future date except its own sentinel.

    Driving off the actual vintage list avoids both. Each window spans real vintages, and
    the final window ends at the sentinel so today's vintage — and tomorrow's — are included.
    """
    if not dates:
        return []
    ordered = sorted(set(dates))
    windows: list[tuple[str, str]] = []
    for start in range(0, len(ordered), max_per_window):
        chunk = ordered[start : start + max_per_window]
        is_last = start + max_per_window >= len(ordered)
        windows.append((chunk[0].isoformat(), REALTIME_MAX if is_last else chunk[-1].isoformat()))
    return windows

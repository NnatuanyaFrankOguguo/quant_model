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

__all__ = ["FRED_SERIES", "FredConnector", "MissingApiKeyError"]

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

    def fetch(self, **params: object) -> RawResponse:
        """One FRED series, all vintages.

        `realtime_start=1776-07-04` is FRED's own sentinel for "the beginning of time"; with
        `realtime_end=9999-12-31` it asks for every vintage rather than only today's view.
        """
        series_id = str(params["series_id"])
        query = {
            "series_id": series_id,
            "api_key": self.api_key,
            "file_type": "json",
            "realtime_start": "1776-07-04",
            "realtime_end": "9999-12-31",
        }
        response = httpx.get(_BASE_URL, params=query, timeout=self._timeout)
        response.raise_for_status()
        return RawResponse(
            data=response.content,
            media_type="application/json",
            # The stored URL has the key stripped. Raw responses are kept forever and the
            # register is read by people who are not the owner; a live credential must not
            # be one of the things preserved forever alongside them.
            url=f"{_BASE_URL}?series_id={series_id}&file_type=json",
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

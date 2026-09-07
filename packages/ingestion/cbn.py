"""CBN connectors — the NFEM USD/NGN rate and the Monetary Policy Rate. P1.3.

`docs/03` P1.3 rates this 🔴 FRAGILE: *"none of these has a REST API... they will break,
without warning, when a government website is redesigned."* Half of that was already true
when we looked. The `.asp` URLs the source documents describe are **404** — the site has been
rebuilt, the pages are `.html`, and the tables are rendered client-side by Kendo UI. The data
itself turned out to be reachable as JSON, which is better than scraping HTML but is still an
**undocumented internal endpoint with no contract**: it can change or vanish without notice,
which is exactly why P1.7's manual CSV path exists and stays wired.

Two datasets, one per connector, because `run()` is one fetch and one parse:

* `/api/GetAllExchangeRates` — daily rates by currency, back to 2001. Feeds
  `NG_FX_NFEM_USDNGN` from `centralrate`, the official mid.
* `/api/GetAllMoneyMarketIndicatorsGRAPH` — monthly indicators. Feeds `NG_MPR`.

**Three data-quality traps found in the live payload, each handled explicitly.** They are
worth reading before changing anything here, because all three fail silently:

1. **The currency label is not clean.** Both `"US DOLLAR"` and `"US DOLLAR "` (trailing
   space) appear. An exact-string match drops the row with the space — one row today, and a
   row that would be silently missing from any future date. Matching is normalised.
2. **The same rate date appears twice, with different values.** Six USD dates carry two rows;
   four of them disagree, one by 3.4% (2024-02-22: 1488.8960 against 1440.1210). CBN
   republishes corrections. The higher `id` is taken as the later record, and a disagreement
   is logged rather than resolved quietly.
3. **`mpr` and `mrr` arrive as empty strings**, not nulls. An empty string must become
   `None`, never `0` — SPEC §4.1, and a 0% policy rate is a number a valuation would happily
   discount at.

**The limitation this connector cannot fix, and must not paper over.** When CBN republishes a
rate it does not say *when* it did so. The corrected value is therefore stored at the
original `ratedate`, and the superseded value is not kept as an earlier vintage. A backtest
deciding on 2024-02-22 would have acted on 1488.8960 and this table will tell it 1440.1210.
Recording an invented correction date would be worse — it would put a fabricated date in the
column whose entire purpose is to say when something was knowable — so the gap is recorded
here and in the connector's log output instead. Closing it needs either a CBN publication
calendar or a daily snapshot of our own, and that is P3/P7 work.
"""

from __future__ import annotations

import calendar
import datetime as dt
import json
from collections import defaultdict
from decimal import Decimal, InvalidOperation

import httpx
import structlog

from packages.ingestion.base import (
    Connector,
    DataSourceLicence,
    MacroRecord,
    RawResponse,
)

__all__ = [
    "CbnConnector",
    "CbnExchangeRateConnector",
    "CbnMoneyMarketConnector",
]

_log = structlog.get_logger(__name__)

_BASE = "https://www.cbn.gov.ng"
#: A descriptive agent with a contact address. The site never agreed to be scraped; the least
#: we owe it is identifying ourselves so an administrator can complain to a human.
_USER_AGENT = "quant_model/0.1 (nnatuanyafrank@gmail.com) research"


class CbnConnector(Connector):
    """Shared licence and HTTP manners for every CBN dataset."""

    #: No published limit and no contract. One request per run, and a polite gap.
    rate_limit_per_sec = 0.5
    politeness_delay_sec = 2.0

    path: str = ""

    def __init__(self, *, timeout_sec: float = 90.0) -> None:
        self._timeout = timeout_sec

    def declare_licence(self) -> DataSourceLicence:
        """Matches the reviewed `data_sources` row seeded in migration 0004.

        `redistribution_allowed=False`. `DATA_FOUNDATION.md` §6.3–6.4 establishes that
        accessing public agency data for personal use is low-risk; it establishes nothing
        about re-serving it. The conservative answer is the only honest one, and
        `register()` will refuse this connector if the stored row ever disagrees.
        """
        return DataSourceLicence(
            source_name="CBN",
            base_url=_BASE,
            licence_type="ng_public_agency",
            redistribution_allowed=False,
            attribution_required=True,
            attribution_text="Source: Central Bank of Nigeria",
            terms_url=f"{_BASE}/",
            terms_reviewed_on=dt.date(2026, 9, 7),
            reviewed_by="nnatuanyafrankoguguo",
            rate_limit_per_sec=self.rate_limit_per_sec,
            notes=(
                "Undocumented JSON endpoints behind the public rates pages; no API contract, "
                "no stability guarantee. The .asp URLs named in the source documents are now "
                "404 — the site was rebuilt. P1.7's manual CSV path is the fallback and stays "
                "wired for exactly this reason."
            ),
        )

    def fetch(self, **params: object) -> RawResponse:
        url = f"{_BASE}{self.path}"
        response = httpx.get(
            url, timeout=self._timeout, headers={"User-Agent": _USER_AGENT}, follow_redirects=True
        )
        response.raise_for_status()
        return RawResponse(
            data=response.content,
            media_type="application/json",
            url=url,
            http_status=response.status_code,
            etag=response.headers.get("etag"),
        )


class CbnExchangeRateConnector(CbnConnector):
    """Daily NFEM USD/NGN, from `centralrate` — the official mid rate."""

    name = "cbn_fx"
    path = "/api/GetAllExchangeRates"
    series_code = "NG_FX_NFEM_USDNGN"
    #: Normalised comparison target. See trap 1 in the module docstring.
    currency = "US DOLLAR"

    def parse(self, raw: RawResponse) -> list[MacroRecord]:
        payload = json.loads(raw.data.decode("utf-8"))
        wanted = self.currency.strip().upper()

        by_date: dict[dt.date, list[dict[str, object]]] = defaultdict(list)
        for row in payload:
            if not isinstance(row, dict):
                continue
            currency = str(row.get("currency", "")).strip().upper()
            if currency != wanted:
                continue
            rate_date = _parse_date(row.get("ratedate"))
            if rate_date is None:
                continue
            by_date[rate_date].append(row)

        records: list[MacroRecord] = []
        for rate_date, rows in sorted(by_date.items()):
            chosen = max(rows, key=lambda r: _as_int(r.get("id")))
            if len(rows) > 1:
                values = {str(r.get("centralrate", "")).strip() for r in rows}
                if len(values) > 1:
                    # Loud, because it is a real disagreement about a real rate and the
                    # superseded vintage is being dropped. See the module docstring.
                    _log.warning(
                        "cbn_duplicate_rate_date_disagrees",
                        rate_date=rate_date.isoformat(),
                        values=sorted(values),
                        chosen_id=_as_int(chosen.get("id")),
                    )
            value = _parse_decimal(chosen.get("centralrate"))
            records.append(
                MacroRecord(
                    series_code=self.series_code,
                    as_of_date=rate_date,
                    # The rate for a day is published that day. [NEEDS VERIFICATION] against
                    # CBN's own publication timing: if it is actually next-morning, every
                    # point-in-time query here is one day optimistic, which is small for a
                    # valuation and not small for P7.
                    known_as_of=rate_date,
                    value=value,
                )
            )
        return records


class CbnMoneyMarketConnector(CbnConnector):
    """Monthly money-market indicators. Feeds the Monetary Policy Rate."""

    name = "cbn_mpr"
    path = "/api/GetAllMoneyMarketIndicatorsGRAPH"
    series_code = "NG_MPR"

    def parse(self, raw: RawResponse) -> list[MacroRecord]:
        payload = json.loads(raw.data.decode("utf-8"))
        records: list[MacroRecord] = []
        for row in payload:
            if not isinstance(row, dict):
                continue
            period_end = _month_end(row.get("tyear"), row.get("tmonth"))
            if period_end is None:
                continue
            records.append(
                MacroRecord(
                    series_code=self.series_code,
                    as_of_date=period_end,
                    # The MPR in force during a month was public during that month — the MPC
                    # announces decisions immediately — so month-end is a safe knowledge
                    # date. It is deliberately not the date this table was published, which
                    # would understate what the market knew.
                    known_as_of=period_end,
                    value=_parse_decimal(row.get("mpr")),
                )
            )
        return records


def _parse_date(value: object) -> dt.date | None:
    if not isinstance(value, str):
        return None
    try:
        return dt.date.fromisoformat(value[:10])
    except ValueError:
        return None


def _month_end(year: object, month: object) -> dt.date | None:
    """Last day of the month a row describes, or None if the row does not say.

    Goes through `str()` because the payload types are not guaranteed: `tyear` arrives as an
    int today and would arrive as a string the day CBN changes its serializer, and a parser
    that crashes on that is a connector that stops rather than degrades.
    """
    try:
        y, m = int(str(year).strip()), int(str(month).strip())
        return dt.date(y, m, calendar.monthrange(y, m)[1])
    except (TypeError, ValueError):
        return None


def _as_int(value: object) -> int:
    """Row id for choosing between duplicates. -1 sorts an unparseable id last."""
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return -1


def _parse_decimal(value: object) -> Decimal | None:
    """Empty string means absent. It becomes NULL, never 0 (SPEC §4.1).

    CBN sends `""` for an indicator it has no figure for. A zero policy rate is a number a
    valuation would cheerfully discount at, and nothing downstream could tell it apart from
    a real one.
    """
    if value is None:
        return None
    text = str(value).strip().replace(",", "")
    if text in {"", "-", "n/a", "N/A", "NA", "."}:
        return None
    try:
        return Decimal(text)
    except InvalidOperation:
        return None

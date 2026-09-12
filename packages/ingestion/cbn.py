"""CBN connectors — the NFEM USD/NGN rate and the Monetary Policy Rate. P1.3.

`docs/03` P1.3 rates this 🔴 FRAGILE: *"none of these has a REST API... they will break,
without warning, when a government website is redesigned."* Half of that was already true
when we looked. The `.asp` URLs the source documents describe are **404** — the site has been
rebuilt, the pages are `.html`, and the tables are rendered client-side by Kendo UI. The data
itself turned out to be reachable as JSON, which is better than scraping HTML but is still an
**undocumented internal endpoint with no contract**: it can change or vanish without notice,
which is exactly why P1.7's manual CSV path exists and stays wired.

Three datasets, one connector each, because `run()` is one fetch and one parse:

* `/api/GetAllExchangeRates` — daily rates by currency, back to 2001. Feeds
  `NG_FX_NFEM_USDNGN` from `centralrate`, the official mid.
* `/api/GetAllMoneyMarketIndicatorsGRAPH` — monthly indicators. Feeds `NG_MPR`.
* `/api/GetAllInflationRatesGRAPH` — monthly CPI. Feeds the `_CBN` **mirror** series, not
  the NBS-attributed ones; see :class:`CbnInflationConnector` for why that distinction is
  not pedantry.

The two monthly datasets need opposite treatment of `known_as_of`, and getting that backwards
is the single most expensive mistake available in this file. The MPR in force during a month
was public *within* that month, because the MPC announces immediately. A month's CPI is
computed *after* the month ends and released mid-way through the next one. Same shape of row,
opposite knowledge date.

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
    "CbnInflationConnector",
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


class CbnInflationConnector(CbnConnector):
    """Nigerian CPI, year-on-year: headline and core. Feeds the `_CBN` mirror series.

    **This is second-hand data and it is labelled as such.** Nigeria's CPI is compiled and
    published by the NBS; CBN republishes it. The figures therefore land in
    `NG_CPI_YOY_CBN` / `NG_CPI_CORE_CBN`, not in the NBS-attributed `NG_CPI_YOY` /
    `NG_CPI_CORE`, for the same reason the World Bank mirror is kept separate in migration
    0005: the attribution a reader sees must match where the bytes actually came from, and
    the licensing register that governs our copy is CBN's row, not NBS's.

    `docs/03` P1.3 warns against "a Nigerian macro dashboard whose Nigerian sources are all
    second-hand". This connector does not close that gap — it narrows it while an NBS path
    is still missing, and keeps the primary series visibly empty so the gap stays visible.

    **The publication-date rule, which is the whole reason this class needs care.** Unlike
    the MPR — which the MPC announces immediately, so the rate in force during a month was
    public within that month — a month's CPI is *computed after the month ends* and released
    in the middle of the following one. Setting `known_as_of` to the period end would claim
    July's inflation was knowable on 31 July, which is precisely the lookahead that makes a
    P7 backtest profitable and wrong.

    CBN's payload does not carry the release date, so it is bounded rather than invented:
    `known_as_of` is the **last day of the following month**, which is never earlier than the
    real release. The asymmetry is deliberate — erring late costs a little responsiveness,
    erring early manufactures knowledge nobody had. [NEEDS VERIFICATION] against NBS's
    published release calendar, which would replace the bound with the actual date.

    **The 2025 figures are a later vintage, and the bound above is wrong for them.** In its
    December 2025 CPI report (published mid-January 2026) NBS moved the year-on-year
    reference from a single month to the 2024 twelve-month average and revised every 2025
    print upward: February 23.18% became 26.27%, November 14.45% became 17.33%. CBN's
    endpoint carries *only* the revised vintage — the figures the market actually had during
    2025 are gone from it. A revised February figure bounded at 2025-03-31 would claim the
    market knew 26.27% when it knew 23.18%, so for those periods `known_as_of` is bounded at
    the revision's publication instead, and the record is marked `revision=2`. The original
    prints live in `NG_CPI_YOY`, from NBS via the Nigeria Data Portal, which froze on them.

    This was found by P1 checkpoint 12 — reconciling one figure against its release — and it
    is precisely why `docs/03` P1.3 warns about second-hand Nigerian sources. The same
    reconciliation showed CBN's June 2025 row to be a copy of May's (26.06 against NBS's
    revised 25.29). That row is stored as CBN published it, because this series is a mirror
    of what CBN says; the parser flags a month identical to its predecessor rather than
    deciding which of the two is real.
    """

    name = "cbn_inflation"
    path = "/api/GetAllInflationRatesGRAPH"

    #: Periods whose values on CBN's endpoint are the January-2026 revision, and the earliest
    #: date that revision could have been known. December 2025 onward are first prints under
    #: the new method and the ordinary bound already lands on or after this date.
    REVISED_PERIODS = (dt.date(2025, 1, 31), dt.date(2025, 11, 30))
    REVISION_PUBLISHED_BY = dt.date(2026, 1, 31)

    #: CBN's field name -> our series code. `allItemsLessFrmProdAndEnergyYearOn` is
    #: "all items less farm produce and energy", which is the core measure.
    FIELDS = {
        "allItemsYearOn": "NG_CPI_YOY_CBN",
        "allItemsLessFrmProdAndEnergyYearOn": "NG_CPI_CORE_CBN",
    }

    def parse(self, raw: RawResponse) -> list[MacroRecord]:
        payload = json.loads(raw.data.decode("utf-8"))
        records: list[MacroRecord] = []
        dated: list[tuple[dt.date, dict[str, object]]] = []
        for row in payload:
            if not isinstance(row, dict):
                continue
            period_end = _month_end(row.get("tyear"), row.get("tmonth"))
            if period_end is None:
                continue
            dated.append((period_end, row))
        dated.sort(key=lambda item: item[0])

        previous: dict[str, Decimal | None] | None = None
        for period_end, row in dated:
            values = {field: _parse_decimal(row.get(field)) for field in self.FIELDS}
            if (
                previous is not None
                and values == previous
                and any(v is not None for v in values.values())
            ):
                # Every headline and core figure equal to last month's, to two decimals, is
                # a copy-paste on the publisher's side far more often than it is an economy
                # standing perfectly still. Said out loud, not dropped: the mirror records
                # what CBN published, and the NBS primary is where the truth is checked.
                _log.warning("cbn_cpi_row_identical_to_previous_period", period=str(period_end))
            previous = values

            known_as_of, revision = self._vintage(period_end)
            for field, series_code in self.FIELDS.items():
                records.append(
                    MacroRecord(
                        series_code=series_code,
                        as_of_date=period_end,
                        known_as_of=known_as_of,
                        value=values[field],
                        revision=revision,
                    )
                )
        return records

    @classmethod
    def _vintage(cls, period_end: dt.date) -> tuple[dt.date, int]:
        """When the figure CBN now serves for this period became knowable, and which print."""
        published_by = _end_of_following_month(period_end)
        first, last = cls.REVISED_PERIODS
        if first <= period_end <= last:
            return max(published_by, cls.REVISION_PUBLISHED_BY), 2
        return published_by, 1


def _end_of_following_month(period_end: dt.date) -> dt.date:
    """A conservative upper bound on the release date. Never earlier than the real one."""
    year = period_end.year + (1 if period_end.month == 12 else 0)
    month = 1 if period_end.month == 12 else period_end.month + 1
    return dt.date(year, month, calendar.monthrange(year, month)[1])

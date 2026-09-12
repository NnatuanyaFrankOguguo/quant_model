"""Nigeria Data Portal connectors — NBS CPI and NBS GDP growth. P1.3.

`docs/03` P1.3 says the statistics bureau has no REST API, and `nigerianstat.gov.ng` still
does not. But NBS also publishes through the **Nigeria Data Portal**
(`nigeria.opendataforafrica.org`), part of the African Development Bank's Africa Information
Highway, and that *does* have a documented JSON API. It carries the CPI series back to
**April 2001** — 296 monthly observations against the 18 months CBN's page offers — and the
quarterly GDP growth series from **2015Q1**.

## Who compiled it, and who we fetched it from

These are two different facts and these connectors keep them apart, because collapsing them
is how attribution goes quietly wrong:

* **The series are NBS's.** `macro_series.data_source_id` for `NG_CPI_YOY` and
  `NG_GDP_GROWTH_YOY` points at NBS, because NBS compiles Nigeria's CPI and national
  accounts. That is what a reader sees credited.
* **The bytes came from the Nigeria Data Portal.** `source_documents.data_source_id` points
  at the portal's own `data_sources` row, and the stored URL is the portal's. That is what
  the licensing register governs, and it is the honest answer to "where did you get this
  file".

This is deliberately *not* how `CbnInflationConnector` is modelled, and the difference is
real. CBN is a separate institution republishing NBS's figure under CBN's own data
agreement, so those figures land in clearly-labelled `_CBN` mirror series. The Data Portal
is a hosting platform for NBS's own data, carrying NBS's own terms link — a transport, not a
second publisher asserting rights. So its figures fill the NBS series, and the transport is
recorded on the document rather than in the series name.

## The guards that matter

The pivot response is self-describing — every row names its indicator, its measure, its
frequency and its location — and all of them are checked rather than assumed. **A
"Month-on change (%)" value written into a year-on-year series would be silently, plausibly
wrong**: about the right magnitude, entirely the wrong statistic, and nothing downstream
could tell. The same applies to a state-level CPI row landing in the national series, to
GDP growth *at market prices* (3.12% for 2024Q3) landing in the headline series NBS reports
*at basic prices* (3.46%), to nominal growth landing in a real series, and to an annual GDP
row landing in a quarterly one — an annual figure's period-end is also Q4's period-end, so
the collision would not even be a duplicate key, just a wrong number.

## The publication date

The portal gives no per-observation release date. `known_as_of` is therefore **bounded** at
the end of the period *following* the one described — the last day of the next month for a
monthly CPI figure, the last day of the next quarter for a quarterly GDP figure. Never
earlier than the real release, because a period's statistic is computed after that period
ends. Erring late costs a little responsiveness; erring early manufactures knowledge nobody
had. [NEEDS VERIFICATION] against NBS's release calendar, which would replace the bounds
with the actual dates.

One consequence is recorded rather than smoothed over: the portal carries NBS's *latest*
revision of each figure, not its first print, and NBS does revise recent quarters in later
GDP releases. A revised value therefore sits under a `known_as_of` bounded at the *first*
release, which is earlier than the revised number was actually knowable. The error is the
size of NBS's revisions — typically tenths of a point — and it is the same limitation the
tracker already records for CBN's silently-corrected FX rates. Closing it needs a source
that publishes vintages, which this portal is not.
"""

from __future__ import annotations

import calendar
import datetime as dt
import json
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
    "CPI_DATASET",
    "GDP_DATASET",
    "ITEM_TO_SERIES",
    "NigeriaDataPortalConnector",
    "NigeriaDataPortalCpiConnector",
    "NigeriaDataPortalGdpConnector",
    "PORTAL_SOURCE_NAME",
]

_log = structlog.get_logger(__name__)

_BASE = "https://nigeria.opendataforafrica.org"
_PIVOT_URL = f"{_BASE}/api/1.0/data/pivot"
_USER_AGENT = "quant_model/0.1 (nnatuanyafrank@gmail.com) research"

PORTAL_SOURCE_NAME = "Nigeria Data Portal"


class NigeriaDataPortalConnector(Connector):
    """Shared licence and HTTP manners for every dataset on the portal."""

    #: A free public portal with no published limit. One request per run, politely spaced.
    #: The portal returned 403 on a second request issued immediately after the first.
    rate_limit_per_sec = 0.5
    politeness_delay_sec = 2.0

    def __init__(self, *, timeout_sec: float = 120.0) -> None:
        self._timeout = timeout_sec

    def declare_licence(self) -> DataSourceLicence:
        """The portal's row, not NBS's.

        `redistribution_allowed=False`, consistent with every other source in the register.
        The dataset metadata claims "Public Domain", and that may well be right — but it is a
        third party's characterisation of a Nigerian agency's data, and
        `PROJECT_CONTEXT.md` §9.3 makes this the one register an acquirer's lawyers read.
        Raising it to `true` is a one-row change once someone has read NBS's own terms page
        and recorded that they did.
        """
        return DataSourceLicence(
            source_name=PORTAL_SOURCE_NAME,
            base_url=_BASE,
            licence_type="ng_public_agency_portal",
            redistribution_allowed=False,
            attribution_required=True,
            attribution_text="Source: National Bureau of Statistics, Nigeria",
            terms_url="https://nigerianstat.gov.ng/page/terms",
            terms_reviewed_on=dt.date(2026, 9, 10),
            reviewed_by="nnatuanyafrankoguguo",
            rate_limit_per_sec=self.rate_limit_per_sec,
            notes=(
                "Transport for NBS data, not a second compiler: the portal (AfDB Africa "
                "Information Highway, Knoema-powered) hosts NBS's own series under NBS's "
                "terms link. Attribution therefore credits NBS. Dataset metadata asserts "
                "'Public Domain' with a verified source flag; that is the portal's claim "
                "about NBS's data and is NOT treated as our clearance to redistribute."
            ),
        )

    def _pivot(self, request: dict[str, object], *, query: str) -> RawResponse:
        """POST one pivot query and return exactly what came back.

        `query` is recorded in the URL we store, because a POST body is not in a URL.
        Without it the stored document says only "the pivot endpoint", and six months from
        now nobody could tell which series the file holds.
        """
        response = httpx.post(
            _PIVOT_URL,
            json=request,
            timeout=self._timeout,
            headers={"User-Agent": _USER_AGENT, "Content-Type": "application/json"},
        )
        response.raise_for_status()
        return RawResponse(
            data=response.content,
            media_type="application/json",
            url=f"{_PIVOT_URL}?{query}",
            http_status=response.status_code,
        )


# ---------------------------------------------------------------------------------------
# CPI
# ---------------------------------------------------------------------------------------

#: The dataset holding CPI. Its metadata reports `licenseTypeName: "Public Domain"` and a
#: terms link to `nigerianstat.gov.ng`, but that is the portal's assertion about NBS's data,
#: not NBS's own statement to us — so the register still says redistribution is not asserted.
CPI_DATASET = "NGNBSNCPIR2017"

#: Dimension member keys, read from the portal's own metadata endpoints.
_LOCATION_NIGERIA = 1000000
_INDICATOR_COMPOSITE_CPI = 1000000
_MEASURE_YEAR_ON_CHANGE = 1000050

#: The measure this connector is allowed to store. Checked against every row.
EXPECTED_MEASURE = "Year-on change (%)"
EXPECTED_LOCATION = "Nigeria"

#: Portal item name -> our series code. Keyed by the name the response carries, so the
#: mapping is checked against what actually arrived rather than against what was requested.
ITEM_TO_SERIES: dict[str, str] = {
    "All Items": "NG_CPI_YOY",
    "All Items less Farm Produce and Energy": "NG_CPI_CORE",
}

#: Request-side keys — **fetchable items only**, which is fewer than the mapping above.
#:
#: The portal's item dimension lists "All Items less Farm Produce and Energy" with
#: `hasData: true`, but that flag describes the item across *all* measures. Asked for it with
#: "Year-on change (%)" the pivot returns zero rows: the portal carries core CPI as an index,
#: not as a published year-on-year rate.
#:
#: Core is therefore not fetchable here, and it is not derived here either. Computing a
#: year-on-year change from the index and storing it in an NBS-attributed series would be
#: publishing our own statistic under someone else's name — `CLAUDE.md`'s provenance rule, and
#: SPEC §4.1's "never infer". `NG_CPI_CORE` stays empty from this source; the CBN mirror
#: (`NG_CPI_CORE_CBN`) carries a published core rate, for 18 months rather than 24 years.
#:
#: Listing core here anyway would let the scheduler create a job that returns zero rows
#: forever, which is exactly the signature the silent-failure detector exists to flag.
ITEM_KEYS: dict[str, int] = {
    "All Items": 1000000,
}


class NigeriaDataPortalCpiConnector(NigeriaDataPortalConnector):
    """One CPI item per run — headline or core."""

    name = "nigeria_data_portal_cpi"

    def fetch(self, **params: object) -> RawResponse:
        """One item's full monthly history, as a pivot query."""
        item_name = str(params["item"])
        if item_name not in ITEM_KEYS:
            raise ValueError(f"unknown item {item_name!r}; expected one of {sorted(ITEM_KEYS)}")
        request = {
            "Header": [{"DimensionId": "Time", "Members": [], "Frequencies": ["M"]}],
            "Stub": [
                {"DimensionId": "location", "Members": [_LOCATION_NIGERIA]},
                {"DimensionId": "item", "Members": [ITEM_KEYS[item_name]]},
                {"DimensionId": "indicator", "Members": [_INDICATOR_COMPOSITE_CPI]},
                {"DimensionId": "measure", "Members": [_MEASURE_YEAR_ON_CHANGE]},
            ],
            "Filter": [],
            "Frequencies": ["M"],
            "Dataset": CPI_DATASET,
        }
        return self._pivot(
            request, query=f"dataset={CPI_DATASET}&item={item_name.replace(' ', '+')}"
        )

    def parse(self, raw: RawResponse) -> list[MacroRecord]:
        """Pure. Every row's item, measure and location are checked, never assumed."""
        payload = json.loads(raw.data.decode("utf-8"))
        records: list[MacroRecord] = []
        skipped_measure = 0
        for row in payload.get("data", []):
            if not isinstance(row, dict):
                continue
            measure = str(row.get("measure", "")).strip()
            if measure != EXPECTED_MEASURE:
                # A month-on-month figure in a year-on-year series is the wrong statistic at
                # roughly the right magnitude — plausible, and undetectable downstream.
                skipped_measure += 1
                continue
            if str(row.get("location", "")).strip() != EXPECTED_LOCATION:
                continue
            series_code = ITEM_TO_SERIES.get(str(row.get("item", "")).strip())
            if series_code is None:
                continue
            period_end = _month_end_from_timestamp(row.get("Time"))
            if period_end is None:
                continue
            records.append(
                MacroRecord(
                    series_code=series_code,
                    as_of_date=period_end,
                    known_as_of=_end_of_following_month(period_end),
                    value=_parse_decimal(row.get("Value")),
                )
            )
        if skipped_measure:
            _log.warning(
                "portal_rows_skipped_wrong_measure",
                count=skipped_measure,
                expected=EXPECTED_MEASURE,
            )
        return records


# ---------------------------------------------------------------------------------------
# GDP
# ---------------------------------------------------------------------------------------

#: "Nigerian Gross Domestic Product Report" — NBS's quarterly national accounts at **2010
#: constant basic prices**, quarterly from 2015Q1. Migration 0008 labels the series with that
#: base, because rebasing changes past values and the base is part of the definition
#: (`docs/08` §2.5). NBS rebased GDP to 2019 in mid-2025; those figures are a later vintage
#: and this dataset does not carry them, so the newest quarter here is what the portal holds,
#: and the staleness flag says so. When a source for the rebased series exists, its figures
#: insert as new `known_as_of` rows beside these — never over them.
GDP_DATASET = "NGNBSNGDPPTO2016"

#: Dimension member keys, read from the portal's metadata endpoints. Three real-growth
#: indicators exist; 1000170 is the one whose values match NBS's own headline ("grew by
#: 3.46% (year-on-year) in real terms in the third quarter of 2024"). Market-price growth
#: (1000180) is 3.12% for the same quarter — the near-miss the indicator guard exists for.
_GDP_INDICATOR_REAL_GROWTH_BASIC = 1000170
_GDP_SECTOR_TOTAL = 1000000

EXPECTED_GDP_INDICATOR = "Real Growth Rate at Basic Price"
EXPECTED_GDP_SECTOR = "Total"
EXPECTED_GDP_FREQUENCY = "Q"
GDP_SERIES_CODE = "NG_GDP_GROWTH_YOY"


class NigeriaDataPortalGdpConnector(NigeriaDataPortalConnector):
    """Headline real GDP growth, year-on-year, quarterly. One request per run."""

    name = "nigeria_data_portal_gdp"

    def fetch(self, **params: object) -> RawResponse:
        """The full quarterly history of the aggregate real growth rate."""
        request = {
            "Header": [
                {"DimensionId": "Time", "Members": [], "Frequencies": [EXPECTED_GDP_FREQUENCY]}
            ],
            "Stub": [
                {"DimensionId": "indicator", "Members": [_GDP_INDICATOR_REAL_GROWTH_BASIC]},
                {"DimensionId": "activity-sector", "Members": [_GDP_SECTOR_TOTAL]},
            ],
            "Filter": [],
            "Frequencies": [EXPECTED_GDP_FREQUENCY],
            "Dataset": GDP_DATASET,
        }
        return self._pivot(
            request,
            query=(
                f"dataset={GDP_DATASET}"
                f"&indicator={EXPECTED_GDP_INDICATOR.replace(' ', '+')}"
                f"&sector={EXPECTED_GDP_SECTOR}&frequency={EXPECTED_GDP_FREQUENCY}"
            ),
        )

    def parse(self, raw: RawResponse) -> list[MacroRecord]:
        """Pure. Indicator, sector and frequency are all checked against every row."""
        payload = json.loads(raw.data.decode("utf-8"))
        records: list[MacroRecord] = []
        skipped_indicator = 0
        skipped_frequency = 0
        for row in payload.get("data", []):
            if not isinstance(row, dict):
                continue
            if str(row.get("indicator", "")).strip() != EXPECTED_GDP_INDICATOR:
                # Market-price, nominal, oil, non-oil: each is a growth rate of about the
                # right size, and none is the headline.
                skipped_indicator += 1
                continue
            if str(row.get("Frequency", "")).strip() != EXPECTED_GDP_FREQUENCY:
                # An annual figure ends on the same date as Q4. It would not collide — it
                # would be stored as Q4, and be wrong.
                skipped_frequency += 1
                continue
            if str(row.get("activity-sector", "")).strip() != EXPECTED_GDP_SECTOR:
                continue
            period_end = _quarter_end_from_timestamp(row.get("Time"))
            if period_end is None:
                continue
            records.append(
                MacroRecord(
                    series_code=GDP_SERIES_CODE,
                    as_of_date=period_end,
                    known_as_of=_end_of_following_quarter(period_end),
                    value=_parse_decimal(row.get("Value")),
                )
            )
        if skipped_indicator:
            _log.warning(
                "portal_rows_skipped_wrong_indicator",
                count=skipped_indicator,
                expected=EXPECTED_GDP_INDICATOR,
            )
        if skipped_frequency:
            _log.warning(
                "portal_rows_skipped_wrong_frequency",
                count=skipped_frequency,
                expected=EXPECTED_GDP_FREQUENCY,
            )
        return records


# ---------------------------------------------------------------------------------------
# Dates and numbers
# ---------------------------------------------------------------------------------------


def _first_of_period(value: object) -> dt.date | None:
    """`2001-04-01T00:00:00Z` names a period by its first day."""
    if not isinstance(value, str) or len(value) < 10:
        return None
    try:
        return dt.date.fromisoformat(value[:10])
    except ValueError:
        return None


def _month_end(year: int, month: int) -> dt.date:
    return dt.date(year, month, calendar.monthrange(year, month)[1])


def _month_end_from_timestamp(value: object) -> dt.date | None:
    """The period we store is the month's last day."""
    first = _first_of_period(value)
    if first is None:
        return None
    return _month_end(first.year, first.month)


def _quarter_end_from_timestamp(value: object) -> dt.date | None:
    """`2024-07-01` names 2024Q3; the period we store ends 2024-09-30.

    A timestamp that is not the first month of a quarter is refused rather than rounded:
    it would mean the portal's frequency label and its timestamp disagree, and the honest
    response to a self-contradicting row is to skip it and let `rows_written` tell.
    """
    first = _first_of_period(value)
    if first is None or first.month not in (1, 4, 7, 10):
        return None
    return _month_end(first.year, first.month + 2)


def _end_of_following_month(period_end: dt.date) -> dt.date:
    """A conservative upper bound on the release date. Never earlier than the real one."""
    year = period_end.year + (1 if period_end.month == 12 else 0)
    month = 1 if period_end.month == 12 else period_end.month + 1
    return _month_end(year, month)


def _end_of_following_quarter(period_end: dt.date) -> dt.date:
    """The quarterly counterpart: the last day of the next quarter.

    NBS publishes a quarter's GDP roughly seven to nine weeks after it ends, so the true
    release is inside this bound. Tighter would risk being earlier than a late release,
    which is the one direction that manufactures lookahead.
    """
    month = period_end.month + 3
    year = period_end.year
    if month > 12:
        month -= 12
        year += 1
    return _month_end(year, month)


def _parse_decimal(value: object) -> Decimal | None:
    """Absent stays absent. A missing reading must never become 0% growth or inflation."""
    if value is None:
        return None
    text = str(value).strip().replace(",", "")
    if text in {"", "-", "n/a", "N/A", "NA", "."}:
        return None
    try:
        return Decimal(text)
    except InvalidOperation:
        return None

"""P1.3 — the Nigeria Data Portal connector.

The two guards are the point of this file. The portal's pivot response is self-describing, and
both descriptions are checked: a month-on-month value written into a year-on-year series, or a
state-level row written into the national series, would be plausible and wrong.
"""

from __future__ import annotations

import datetime as dt
import json
from decimal import Decimal

import pytest

from packages.ingestion.base import RawResponse
from packages.ingestion.nigeria_data_portal import (
    PORTAL_SOURCE_NAME,
    NigeriaDataPortalConnector,
)


def _raw(rows: list[dict[str, object]]) -> RawResponse:
    return RawResponse(
        data=json.dumps({"data": rows}).encode(),
        media_type="application/json",
        url="https://nigeria.opendataforafrica.org/api/1.0/data/pivot?dataset=NGNBSNCPIR2017",
        http_status=200,
    )


def _row(**overrides: object) -> dict[str, object]:
    """A real pivot row, copied from the live response shape."""
    row: dict[str, object] = {
        "Time": "2025-11-01T00:00:00Z",
        "measure": "Year-on change (%)",
        "indicator": "Composite Consumer Price Index",
        "item": "All Items",
        "location": "Nigeria",
        "RegionId": "NG",
        "Frequency": "M",
        "Value": 16.05,
        "Unit": "%",
        "Scale": 1,
    }
    row.update(overrides)
    return row


def test_headline_and_core_map_to_the_nbs_series() -> None:
    records = NigeriaDataPortalConnector().parse(
        _raw([_row(), _row(item="All Items less Farm Produce and Energy", Value=20.1)])
    )
    assert {r.series_code for r in records} == {"NG_CPI_YOY", "NG_CPI_CORE"}
    by_code = {r.series_code: r.value for r in records}
    assert by_code["NG_CPI_YOY"] == Decimal("16.05")
    assert by_code["NG_CPI_CORE"] == Decimal("20.1")


def test_period_is_the_last_day_of_the_month() -> None:
    records = NigeriaDataPortalConnector().parse(_raw([_row(Time="2025-11-01T00:00:00Z")]))
    assert records[0].as_of_date == dt.date(2025, 11, 30)


@pytest.mark.invariant
def test_cpi_is_not_knowable_within_its_own_month() -> None:
    """A month's CPI is computed after the month ends. Month-end would be lookahead."""
    records = NigeriaDataPortalConnector().parse(_raw([_row(Time="2025-11-01T00:00:00Z")]))
    assert records[0].known_as_of == dt.date(2025, 12, 31)
    assert records[0].known_as_of > records[0].as_of_date


def test_december_rolls_into_the_next_year() -> None:
    records = NigeriaDataPortalConnector().parse(_raw([_row(Time="2025-12-01T00:00:00Z")]))
    assert records[0].as_of_date == dt.date(2025, 12, 31)
    assert records[0].known_as_of == dt.date(2026, 1, 31)


@pytest.mark.invariant
def test_a_month_on_month_row_is_refused(capsys: pytest.CaptureFixture[str]) -> None:
    """The expensive near-miss: right magnitude, wrong statistic, undetectable downstream."""
    records = NigeriaDataPortalConnector().parse(
        _raw([_row(measure="Month-on change (%)", Value=1.2)])
    )
    assert records == []
    assert "portal_rows_skipped_wrong_measure" in capsys.readouterr().out


@pytest.mark.invariant
def test_a_state_level_row_never_becomes_the_national_series() -> None:
    records = NigeriaDataPortalConnector().parse(_raw([_row(location="Kano", Value=18.4)]))
    assert records == []


def test_an_unmapped_item_is_skipped_not_guessed() -> None:
    records = NigeriaDataPortalConnector().parse(_raw([_row(item="Imported Food")]))
    assert records == []


def test_absent_value_is_none_never_zero() -> None:
    """A missing CPI reading must not become 0% inflation."""
    records = NigeriaDataPortalConnector().parse(_raw([_row(Value=None)]))
    assert len(records) == 1
    assert records[0].value is None


def test_parse_is_deterministic() -> None:
    connector = NigeriaDataPortalConnector()
    raw = _raw([_row(), _row(item="All Items less Farm Produce and Energy")])
    assert connector.parse(raw) == connector.parse(raw)


def test_malformed_rows_are_skipped() -> None:
    records = NigeriaDataPortalConnector().parse(
        _raw([_row(Time="nonsense"), _row(Time=None), "not a dict"])  # type: ignore[list-item]
    )
    assert records == []


def test_licence_credits_nbs_but_registers_the_portal() -> None:
    """The compiler and the transport are different facts, and both are recorded."""
    licence = NigeriaDataPortalConnector().declare_licence()
    assert licence.source_name == PORTAL_SOURCE_NAME
    assert "National Bureau of Statistics" in (licence.attribution_text or "")
    assert licence.redistribution_allowed is False


def test_fetch_refuses_an_unknown_item() -> None:
    with pytest.raises(ValueError, match="unknown item"):
        NigeriaDataPortalConnector().fetch(item="Not An Item")


def test_core_is_not_fetchable_and_is_not_derived() -> None:
    """The portal has no published year-on-year core rate, so this source offers none.

    Deriving one from the index and storing it under NBS's name would be publishing our own
    statistic as theirs. A scheduled job for it would also return zero rows forever — the
    exact signature the silent-failure detector exists to flag.
    """
    from packages.ingestion.nigeria_data_portal import ITEM_KEYS, ITEM_TO_SERIES

    assert "All Items less Farm Produce and Energy" not in ITEM_KEYS
    # The parser still maps it, so it works unchanged if the portal ever publishes one.
    assert ITEM_TO_SERIES["All Items less Farm Produce and Energy"] == "NG_CPI_CORE"

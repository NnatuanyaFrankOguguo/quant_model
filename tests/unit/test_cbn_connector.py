"""P1.3 — the CBN connectors, against the traps found in the live payload.

Every fixture below is a trimmed copy of real CBN response shapes, including the three
defects that fail silently: a currency label with a trailing space, a rate date carrying two
disagreeing rows, and an indicator sent as an empty string.
"""

from __future__ import annotations

import datetime as dt
import json
from decimal import Decimal

import pytest

from packages.ingestion.base import RawResponse
from packages.ingestion.cbn import (
    CbnExchangeRateConnector,
    CbnInflationConnector,
    CbnMoneyMarketConnector,
)


def _raw(payload: object) -> RawResponse:
    return RawResponse(
        data=json.dumps(payload).encode(),
        media_type="application/json",
        url="https://www.cbn.gov.ng/api/GetAllExchangeRates",
        http_status=200,
    )


FX_PAYLOAD = [
    {"id": 1, "currency": "EURO", "ratedate": "2026-09-04", "centralrate": "1534.2758"},
    {"id": 2, "currency": "US DOLLAR", "ratedate": "2026-09-04", "centralrate": "1320.7160"},
    # Trailing space — the real payload contains one of these. An exact match drops it.
    {"id": 3, "currency": "US DOLLAR ", "ratedate": "2026-09-03", "centralrate": "1319.5000"},
    # The same date twice, disagreeing. The higher id is CBN's later record.
    {"id": 10, "currency": "US DOLLAR", "ratedate": "2024-02-22", "centralrate": "1488.8960"},
    {"id": 20, "currency": "US DOLLAR", "ratedate": "2024-02-22", "centralrate": "1440.1210"},
]


def test_currency_match_is_normalised() -> None:
    """A trailing space in the label must not silently drop a day's rate."""
    records = CbnExchangeRateConnector().parse(_raw(FX_PAYLOAD))
    dates = {r.as_of_date for r in records}
    assert dt.date(2026, 9, 3) in dates, "the 'US DOLLAR ' row was dropped"
    assert dt.date(2026, 9, 4) in dates


def test_other_currencies_are_ignored() -> None:
    records = CbnExchangeRateConnector().parse(_raw(FX_PAYLOAD))
    assert {r.series_code for r in records} == {"NG_FX_NFEM_USDNGN"}
    assert all(r.value != Decimal("1534.2758") for r in records)


def test_duplicate_rate_date_takes_the_later_record() -> None:
    """CBN republishes corrections. The choice must be deterministic, not incidental."""
    records = CbnExchangeRateConnector().parse(_raw(FX_PAYLOAD))
    feb = [r for r in records if r.as_of_date == dt.date(2024, 2, 22)]
    assert len(feb) == 1, "a duplicated date must not produce two rows for one vintage"
    assert feb[0].value == Decimal("1440.1210")


def test_disagreeing_duplicate_is_logged(capsys: pytest.CaptureFixture[str]) -> None:
    """Dropping a superseded rate silently would hide a 3.4% disagreement.

    Read from stdout rather than `caplog`: structlog writes there directly and does not go
    through the stdlib logging handlers pytest captures.
    """
    CbnExchangeRateConnector().parse(_raw(FX_PAYLOAD))
    output = capsys.readouterr().out
    assert "cbn_duplicate_rate_date_disagrees" in output
    assert "1488.8960" in output and "1440.1210" in output, "both values must be named"


def test_identical_duplicate_is_not_logged(capsys: pytest.CaptureFixture[str]) -> None:
    """The same value twice is noise, not a finding. Warning on it trains you to ignore it."""
    payload = [
        {"id": 1, "currency": "US DOLLAR", "ratedate": "2020-11-18", "centralrate": "379.5000"},
        {"id": 2, "currency": "US DOLLAR", "ratedate": "2020-11-18", "centralrate": "379.5000"},
    ]
    CbnExchangeRateConnector().parse(_raw(payload))
    assert "cbn_duplicate_rate_date_disagrees" not in capsys.readouterr().out


def test_fx_parse_is_deterministic() -> None:
    connector = CbnExchangeRateConnector()
    assert connector.parse(_raw(FX_PAYLOAD)) == connector.parse(_raw(FX_PAYLOAD))


def test_fx_known_as_of_equals_the_rate_date() -> None:
    """A daily official rate is public on its own date — not the date we fetched it."""
    records = CbnExchangeRateConnector().parse(_raw(FX_PAYLOAD))
    assert all(r.known_as_of == r.as_of_date for r in records)


MPR_PAYLOAD = [
    {"id": 233, "tyear": 2025, "tmonth": 2, "period": "February 2025", "mpr": "27.50", "mrr": ""},
    {"id": 234, "tyear": 2026, "tmonth": 7, "period": "July 2026", "mpr": "26.50", "mrr": ""},
    # An indicator CBN has no figure for.
    {"id": 235, "tyear": 2026, "tmonth": 8, "period": "August 2026", "mpr": "", "mrr": ""},
]


def test_mpr_uses_month_end_as_the_period() -> None:
    records = CbnMoneyMarketConnector().parse(_raw(MPR_PAYLOAD))
    assert records[0].as_of_date == dt.date(2025, 2, 28)
    assert records[1].as_of_date == dt.date(2026, 7, 31)
    assert {r.series_code for r in records} == {"NG_MPR"}


@pytest.mark.invariant
def test_empty_mpr_is_none_never_zero() -> None:
    """SPEC 4.1. A 0% policy rate is a number a valuation would happily discount at."""
    records = CbnMoneyMarketConnector().parse(_raw(MPR_PAYLOAD))
    august = next(r for r in records if r.as_of_date == dt.date(2026, 8, 31))
    assert august.value is None


def test_mpr_known_as_of_is_month_end_not_publication_of_the_table() -> None:
    """The MPC announces immediately, so the rate in force was public within its month."""
    records = CbnMoneyMarketConnector().parse(_raw(MPR_PAYLOAD))
    assert all(r.known_as_of == r.as_of_date for r in records)


def test_malformed_rows_are_skipped_not_guessed() -> None:
    payload = [
        {"id": 1, "currency": "US DOLLAR", "ratedate": "not-a-date", "centralrate": "1"},
        {"id": 2, "currency": "US DOLLAR", "centralrate": "1"},
        "not even a dict",
    ]
    assert CbnExchangeRateConnector().parse(_raw(payload)) == []


def test_cbn_declares_the_reviewed_licence() -> None:
    licence = CbnExchangeRateConnector().declare_licence()
    assert licence.source_name == "CBN"
    assert licence.redistribution_allowed is False
    assert licence.attribution_text == "Source: Central Bank of Nigeria"


# --------------------------------------------------------------------------------------
# CPI mirror — where known_as_of must NOT equal the period end
# --------------------------------------------------------------------------------------

CPI_PAYLOAD = [
    {
        "id": 296,
        "tyear": 2026,
        "tmonth": 7,
        "period": "July 2026",
        "allItemsYearOn": "15.43",
        "allItemsLessFrmProdAndEnergyYearOn": "14.97",
    },
    {
        "id": 297,
        "tyear": 2026,
        "tmonth": 12,
        "period": "December 2026",
        "allItemsYearOn": "",
        "allItemsLessFrmProdAndEnergyYearOn": "13.10",
    },
]


@pytest.mark.invariant
def test_cpi_is_not_knowable_within_its_own_month() -> None:
    """The opposite of the MPR rule, and the expensive one to get backwards.

    July's CPI is computed after July ends and released in August. A `known_as_of` of
    2026-07-31 would claim it was knowable on the last day of the month it describes —
    lookahead, invisible, and it would make a P7 backtest profitable and wrong.
    """
    records = CbnInflationConnector().parse(_raw(CPI_PAYLOAD))
    july = [r for r in records if r.as_of_date == dt.date(2026, 7, 31)]
    assert july, "July should parse"
    for record in july:
        assert record.known_as_of > record.as_of_date
        assert record.known_as_of == dt.date(2026, 8, 31)


def test_cpi_year_boundary_rolls_into_january() -> None:
    """December's figure is released in the next calendar year."""
    records = CbnInflationConnector().parse(_raw(CPI_PAYLOAD))
    december = [r for r in records if r.as_of_date == dt.date(2026, 12, 31)]
    assert {r.known_as_of for r in december} == {dt.date(2027, 1, 31)}


def test_cpi_feeds_the_mirror_series_not_the_nbs_ones() -> None:
    """Attribution must match where the bytes came from."""
    records = CbnInflationConnector().parse(_raw(CPI_PAYLOAD))
    codes = {r.series_code for r in records}
    assert codes == {"NG_CPI_YOY_CBN", "NG_CPI_CORE_CBN"}
    assert "NG_CPI_YOY" not in codes and "NG_CPI_CORE" not in codes


def test_cpi_headline_and_core_map_to_the_right_fields() -> None:
    records = CbnInflationConnector().parse(_raw(CPI_PAYLOAD))
    july = {r.series_code: r.value for r in records if r.as_of_date == dt.date(2026, 7, 31)}
    assert july["NG_CPI_YOY_CBN"] == Decimal("15.43")
    assert july["NG_CPI_CORE_CBN"] == Decimal("14.97")


@pytest.mark.invariant
def test_empty_cpi_field_is_none_never_zero() -> None:
    records = CbnInflationConnector().parse(_raw(CPI_PAYLOAD))
    december = {r.series_code: r.value for r in records if r.as_of_date == dt.date(2026, 12, 31)}
    assert december["NG_CPI_YOY_CBN"] is None
    assert december["NG_CPI_CORE_CBN"] == Decimal("13.10")


# --------------------------------------------------------------------------------------
# The 2025 revision — where the ordinary bound would have stored lookahead
# --------------------------------------------------------------------------------------

REVISED_2025_PAYLOAD = [
    {"id": 278, "tyear": 2024, "tmonth": 12, "allItemsYearOn": "34.80",
     "allItemsLessFrmProdAndEnergyYearOn": "29.28"},
    {"id": 279, "tyear": 2025, "tmonth": 2, "allItemsYearOn": "26.27",
     "allItemsLessFrmProdAndEnergyYearOn": "25.66"},
    {"id": 282, "tyear": 2025, "tmonth": 5, "allItemsYearOn": "26.06",
     "allItemsLessFrmProdAndEnergyYearOn": "24.92"},
    {"id": 283, "tyear": 2025, "tmonth": 6, "allItemsYearOn": "26.06",
     "allItemsLessFrmProdAndEnergyYearOn": "24.92"},
    {"id": 288, "tyear": 2025, "tmonth": 11, "allItemsYearOn": "17.33",
     "allItemsLessFrmProdAndEnergyYearOn": "20.59"},
    {"id": 289, "tyear": 2025, "tmonth": 12, "allItemsYearOn": "15.15",
     "allItemsLessFrmProdAndEnergyYearOn": "18.63"},
]  # fmt: skip


def _by_period(records, series_code: str = "NG_CPI_YOY_CBN"):
    return {r.as_of_date: r for r in records if r.series_code == series_code}


@pytest.mark.invariant
def test_2025_figures_are_the_january_2026_revision() -> None:
    """February 2025's 26.27% is NBS's *revised* print. The market had 23.18% in March 2025.

    Bounding it at 2025-03-31 would let a backtest deciding in April 2025 discount at a rate
    nobody published until January 2026. The revision's publication is the bound.
    """
    by_period = _by_period(CbnInflationConnector().parse(_raw(REVISED_2025_PAYLOAD)))
    february = by_period[dt.date(2025, 2, 28)]
    assert february.value == Decimal("26.27")
    assert february.known_as_of == dt.date(2026, 1, 31)
    assert february.revision == 2
    november = by_period[dt.date(2025, 11, 30)]
    assert november.known_as_of == dt.date(2026, 1, 31)
    assert november.revision == 2


def test_the_revision_applies_to_core_as_well() -> None:
    by_period = _by_period(
        CbnInflationConnector().parse(_raw(REVISED_2025_PAYLOAD)), "NG_CPI_CORE_CBN"
    )
    assert by_period[dt.date(2025, 2, 28)].known_as_of == dt.date(2026, 1, 31)
    assert by_period[dt.date(2025, 2, 28)].revision == 2


def test_periods_before_the_revision_window_are_first_prints() -> None:
    by_period = _by_period(CbnInflationConnector().parse(_raw(REVISED_2025_PAYLOAD)))
    december_2024 = by_period[dt.date(2024, 12, 31)]
    assert december_2024.known_as_of == dt.date(2025, 1, 31)
    assert december_2024.revision == 1


def test_december_2025_is_a_first_print_under_the_new_method() -> None:
    """The first figure computed on the new base, published in the same report as the
    revision. The ordinary bound lands on the same date, and it is a first print."""
    by_period = _by_period(CbnInflationConnector().parse(_raw(REVISED_2025_PAYLOAD)))
    december = by_period[dt.date(2025, 12, 31)]
    assert december.known_as_of == dt.date(2026, 1, 31)
    assert december.revision == 1


def test_later_periods_keep_the_ordinary_bound_and_revision() -> None:
    by_period = _by_period(CbnInflationConnector().parse(_raw(CPI_PAYLOAD)))
    assert by_period[dt.date(2026, 7, 31)].known_as_of == dt.date(2026, 8, 31)
    assert by_period[dt.date(2026, 7, 31)].revision == 1


def test_a_month_identical_to_its_predecessor_is_flagged_not_dropped(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """CBN's June 2025 row is a copy of May's; NBS's revised June is 25.29%.

    The mirror stores what CBN published — that is what a mirror is — but it says so.
    """
    by_period = _by_period(CbnInflationConnector().parse(_raw(REVISED_2025_PAYLOAD)))
    assert by_period[dt.date(2025, 5, 31)].value == Decimal("26.06")
    assert by_period[dt.date(2025, 6, 30)].value == Decimal("26.06")
    out = capsys.readouterr().out
    assert "cbn_cpi_row_identical_to_previous_period" in out
    assert "2025-06-30" in out


def test_revised_cpi_parse_is_deterministic_regardless_of_row_order() -> None:
    connector = CbnInflationConnector()
    forward = connector.parse(_raw(REVISED_2025_PAYLOAD))
    backward = connector.parse(_raw(list(reversed(REVISED_2025_PAYLOAD))))
    assert forward == backward

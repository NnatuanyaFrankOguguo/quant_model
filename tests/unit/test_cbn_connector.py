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
from packages.ingestion.cbn import CbnExchangeRateConnector, CbnMoneyMarketConnector


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

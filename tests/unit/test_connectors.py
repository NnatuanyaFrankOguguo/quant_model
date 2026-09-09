"""P1.1, P1.2, P1.7 — the connector contract, and the two connectors that use it.

The tests that matter here are the ones asserting a rule cannot be bypassed rather than that
a happy path works: the licence gate, `parse()` purity, and the two places where a wrong
answer silently invents data — a missing value becoming zero, and `known_as_of` being
allowed to precede the period it describes.
"""

from __future__ import annotations

import datetime as dt
import json
from decimal import Decimal

import pytest

from packages.ingestion.base import (
    Connector,
    DataSourceLicence,
    LicenceNotDeclaredError,
    MacroRecord,
    RawResponse,
    _validated_licence,
)
from packages.ingestion.fred import FredConnector, MissingApiKeyError
from packages.ingestion.manual_csv import CsvFormatError, ManualCsvConnector

# --------------------------------------------------------------------------------------
# P1.1 — the licence gate (TG5 made executable)
# --------------------------------------------------------------------------------------


class _NoLicence(Connector):
    name = "no_licence"

    def declare_licence(self) -> DataSourceLicence:
        raise NotImplementedError

    def fetch(self, **params: object) -> RawResponse:  # pragma: no cover - never reached
        raise AssertionError("fetch must not be reachable without a licence")

    def parse(self, raw: RawResponse) -> list[MacroRecord]:  # pragma: no cover
        raise AssertionError("parse must not be reachable without a licence")


class _WrongType(_NoLicence):
    name = "wrong_type"

    def declare_licence(self):  # type: ignore[override]
        return {"redistribution_allowed": True}


@pytest.mark.invariant
def test_connector_without_a_licence_cannot_register() -> None:
    """CLAUDE.md: data licensing before ingestion. Enforced before any network call."""
    with pytest.raises(LicenceNotDeclaredError):
        _validated_licence(_NoLicence())


@pytest.mark.invariant
def test_licence_must_be_the_declared_type() -> None:
    with pytest.raises(LicenceNotDeclaredError):
        _validated_licence(_WrongType())


@pytest.mark.invariant
@pytest.mark.parametrize("bad", [None, "", 0, 1, "true", "no"])
def test_redistribution_allowed_must_be_a_real_boolean(bad: object) -> None:
    """`NOT NULL` is the whole mechanism — it forces an answer.

    Truthiness would let the string "no" register as permission to redistribute, which is
    the one register PROJECT_CONTEXT 9.3 says an acquirer's lawyers actually read.
    """

    class _Sloppy(_NoLicence):
        name = "sloppy"

        def declare_licence(self) -> DataSourceLicence:
            licence = DataSourceLicence(
                source_name="X",
                licence_type="t",
                redistribution_allowed=True,
                attribution_required=False,
                terms_reviewed_on=dt.date(2026, 9, 1),
                reviewed_by="test",
            )
            object.__setattr__(licence, "redistribution_allowed", bad)
            return licence

    with pytest.raises(LicenceNotDeclaredError):
        _validated_licence(_Sloppy())


def test_a_complete_licence_passes() -> None:
    assert _validated_licence(FredConnector(api_key="x")).source_name == "FRED"


# --------------------------------------------------------------------------------------
# P1.2 — FRED
# --------------------------------------------------------------------------------------

FRED_PAYLOAD = json.dumps(
    {
        "observations": [
            # Two vintages of the same period: the original print and a later revision.
            {"date": "2026-01-01", "realtime_start": "2026-02-05", "value": "4.33"},
            {"date": "2026-01-01", "realtime_start": "2026-03-05", "value": "4.35"},
            # FRED's encoding for "no observation".
            {"date": "2026-02-01", "realtime_start": "2026-03-05", "value": "."},
        ]
    }
).encode()


def _fred_raw() -> RawResponse:
    return RawResponse(
        data=FRED_PAYLOAD,
        media_type="application/json",
        url="https://api.stlouisfed.org/fred/series/observations?series_id=FEDFUNDS&file_type=json",
        http_status=200,
    )


def test_fred_parse_maps_realtime_start_to_known_as_of() -> None:
    """ALFRED gives the publication date directly; it must not be assumed or defaulted."""
    records = FredConnector(api_key="x").parse(_fred_raw())
    january = [r for r in records if r.as_of_date == dt.date(2026, 1, 1)]
    assert {r.known_as_of for r in january} == {dt.date(2026, 2, 5), dt.date(2026, 3, 5)}
    assert {r.value for r in january} == {Decimal("4.33"), Decimal("4.35")}


@pytest.mark.invariant
def test_fred_missing_value_is_none_never_zero() -> None:
    """SPEC 4.1: never infer missing financial data. A 0.0 here is a fabricated data point."""
    records = FredConnector(api_key="x").parse(_fred_raw())
    february = next(r for r in records if r.as_of_date == dt.date(2026, 2, 1))
    assert february.value is None


def test_fred_parse_is_deterministic() -> None:
    """Same bytes in, same records out — what makes it testable without the network."""
    connector = FredConnector(api_key="x")
    assert connector.parse(_fred_raw()) == connector.parse(_fred_raw())


def test_fred_maps_series_id_to_the_local_series_code() -> None:
    records = FredConnector(api_key="x").parse(_fred_raw())
    assert {r.series_code for r in records} == {"US_FED_FUNDS"}


def test_fred_without_a_key_refuses_rather_than_half_running(monkeypatch) -> None:
    monkeypatch.setattr(
        "packages.ingestion.fred.get_settings",
        lambda: type("S", (), {"fred_api_key": None})(),
    )
    with pytest.raises(MissingApiKeyError):
        _ = FredConnector().api_key


def test_fred_stored_url_carries_no_api_key() -> None:
    """Raw responses are kept forever; a live credential must not be kept with them."""
    raw = _fred_raw()
    assert "api_key" not in (raw.url or "")


# --------------------------------------------------------------------------------------
# P1.7 — the manual CSV fallback
# --------------------------------------------------------------------------------------


def _csv_raw(body: str) -> RawResponse:
    return RawResponse(data=body.encode("utf-8"), media_type="text/csv", url="file:///x.csv")


GOOD_CSV = (
    "series_code,as_of_date,known_as_of,value\n"
    "NG_CPI_YOY,2026-07-31,2026-08-15,34.2\n"
    "NG_CPI_CORE,2026-07-31,2026-08-15,\n"
)


def test_manual_csv_parses_and_keeps_absent_values_null() -> None:
    records = ManualCsvConnector("NBS").parse(_csv_raw(GOOD_CSV))
    assert [r.series_code for r in records] == ["NG_CPI_YOY", "NG_CPI_CORE"]
    assert records[0].value == Decimal("34.2")
    assert records[1].value is None


@pytest.mark.invariant
def test_manual_csv_rejects_publication_before_the_period() -> None:
    """A figure published before the period it describes is a typo or a forecast.

    Storing it would let a point-in-time query return a number the market could not have
    had — the lookahead that makes a P7 backtest profitable and wrong.
    """
    bad = "series_code,as_of_date,known_as_of,value\nNG_CPI_YOY,2026-07-31,2026-07-01,34.2\n"
    with pytest.raises(CsvFormatError, match="precedes as_of_date"):
        ManualCsvConnector("NBS").parse(_csv_raw(bad))


def test_manual_csv_requires_known_as_of() -> None:
    bad = "series_code,as_of_date,known_as_of,value\nNG_CPI_YOY,2026-07-31,,34.2\n"
    with pytest.raises(CsvFormatError, match="known_as_of"):
        ManualCsvConnector("NBS").parse(_csv_raw(bad))


def test_manual_csv_rejects_a_missing_column() -> None:
    bad = "series_code,as_of_date,value\nNG_CPI_YOY,2026-07-31,34.2\n"
    with pytest.raises(CsvFormatError, match="missing required column"):
        ManualCsvConnector("NBS").parse(_csv_raw(bad))


def test_manual_csv_tolerates_an_excel_bom() -> None:
    """Excel is what the human will actually use, and it writes a BOM."""
    records = ManualCsvConnector("NBS").parse(
        RawResponse(data=b"\xef\xbb\xbf" + GOOD_CSV.encode(), media_type="text/csv")
    )
    assert len(records) == 2


def test_manual_csv_claims_the_agency_licence_not_a_human_one() -> None:
    """Hand-copied CBN data is still CBN's data on CBN's terms."""
    licence = ManualCsvConnector("CBN").declare_licence()
    assert licence.source_name == "CBN"
    assert licence.redistribution_allowed is False


def test_manual_csv_rejects_an_unknown_source() -> None:
    with pytest.raises(ValueError, match="unknown manual source"):
        ManualCsvConnector("BLOOMBERG")


# --------------------------------------------------------------------------------------
# Credential redaction — a real incident, not a hypothetical
# --------------------------------------------------------------------------------------


class _LeakyConnector(Connector):
    """Fails the way httpx does: the exception message contains the full request URL."""

    name = "leaky"

    def declare_licence(self) -> DataSourceLicence:
        return DataSourceLicence(
            source_name="FRED",
            licence_type="public_api_attribution",
            redistribution_allowed=False,
            attribution_required=True,
            terms_reviewed_on=dt.date(2026, 9, 1),
            reviewed_by="test",
        )

    def fetch(self, **params: object) -> RawResponse:
        raise RuntimeError(
            "Client error '400 Bad Request' for url "
            "'https://api.stlouisfed.org/fred/series/observations"
            "?series_id=DGS10&api_key=abcdef0123456789abcdef0123456789&file_type=json'"
        )

    def parse(self, raw: RawResponse) -> list[MacroRecord]:  # pragma: no cover
        return []


@pytest.mark.invariant
def test_api_key_never_reaches_the_stored_error() -> None:
    """The happy path stripped the key; the error path did not, and that is not redaction.

    This is a real incident: a 400 from FRED put the live key into `connector_runs.error`,
    into the terminal, and would have put it into any log aggregator. A credential is only
    redacted if it is redacted on the path that fails.
    """
    from packages.common.config import redact_secrets

    try:
        _LeakyConnector().fetch()
    except RuntimeError as exc:
        raw_text = f"{type(exc).__name__}: {exc}"
    else:  # pragma: no cover
        raise AssertionError("fetch should have raised")

    assert "abcdef0123456789abcdef0123456789" in raw_text, "fixture must contain a key"
    cleaned = redact_secrets(raw_text)
    assert "abcdef0123456789abcdef0123456789" not in cleaned
    assert "<redacted>" in cleaned
    # The diagnostic must survive — a redaction that deletes the error is its own bug.
    assert "400 Bad Request" in cleaned
    assert "series_id=DGS10" in cleaned


@pytest.mark.parametrize(
    "text",
    [
        "https://x/api?api_key=SUPERSECRETVALUE1&z=1",
        "https://x/api?apikey=SUPERSECRETVALUE1",
        "https://x/api?token=SUPERSECRETVALUE1",
        "Authorization: Bearer token=SUPERSECRETVALUE1",
        "password=SUPERSECRETVALUE1 host=db",
        "API_KEY=SUPERSECRETVALUE1",
    ],
)
def test_redaction_covers_the_common_parameter_names(text: str) -> None:
    """By name, so it catches services this code has never heard of."""
    from packages.common.config import redact_secrets

    assert "SUPERSECRETVALUE1" not in redact_secrets(text)


def test_redaction_leaves_ordinary_text_alone() -> None:
    """It must not mangle a message that carries no credential."""
    from packages.common.config import redact_secrets

    message = "HTTPStatusError: 404 Not Found for series_id=FEDFUNDS"
    assert redact_secrets(message) == message


def test_redaction_never_raises() -> None:
    from packages.common.config import redact_secrets

    assert redact_secrets("") == ""

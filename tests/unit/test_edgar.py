"""P2.1 — the EDGAR connectors, the chart, the periods, the versioned writer, point-in-time.

Checkpoint items from `docs/03` P2 covered here: 1 (CIK zero-padding), 2 (rate limit),
3 (User-Agent sent), 4 (missing items are NULL), 8 (`known_as_of` is the filing date),
11 (provenance on every figure), 15 (a restatement keeps both versions and a decision date
before it returns the original). The fixtures are real EDGAR responses for Apple, trimmed
to the mapped tags and the last few years; no test touches the network.
"""

from __future__ import annotations

import datetime as dt
import json
from collections.abc import Iterator
from decimal import Decimal
from pathlib import Path

import httpx
import pytest
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from packages.common.models import (
    Company,
    Filing,
    Security,
    SecurityIdentifier,
    Statement,
    StatementLineItem,
)
from packages.common.pit import line_items_as_known_on
from packages.common.storage import LocalDiskBackend
from packages.ingestion import base as ingestion_base
from packages.ingestion.base import RawResponse, register
from packages.ingestion.edgar import (
    EdgarCompanyFactsConnector,
    EdgarRefusedError,
    EdgarSubmissionsConnector,
    MissingUserAgentError,
    _Throttle,
    zero_pad_cik,
)
from packages.normalize.chart import ChartVersion, LabelMapping, load_chart, resolve
from packages.normalize.periods import (
    fiscal_year_of,
    period_label,
    period_type_of,
    quarter_of,
)

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "edgar"
UA = "Test Person test@example.com"
APPLE_CIK = "0000320193"


def _raw(name: str, url: str) -> RawResponse:
    return RawResponse(
        data=(FIXTURES / name).read_bytes(), media_type="application/json", url=url, http_status=200
    )


def _facts_raw() -> RawResponse:
    return _raw(
        "AAPL_companyfacts_trimmed.json",
        f"https://data.sec.gov/api/xbrl/companyfacts/CIK{APPLE_CIK}.json",
    )


def _submissions_raw() -> RawResponse:
    return _raw(
        "AAPL_submissions_trimmed.json", f"https://data.sec.gov/submissions/CIK{APPLE_CIK}.json"
    )


# --------------------------------------------------------------------------------------
# Check 1 - CIK zero-padding
# --------------------------------------------------------------------------------------


@pytest.mark.parametrize("given", [320193, "320193", " 320193 ", "CIK320193", "0000320193"])
def test_cik_is_zero_padded_to_ten_digits(given: object) -> None:
    assert zero_pad_cik(given) == "0000320193"  # type: ignore[arg-type]


@pytest.mark.parametrize("bad", ["AAPL", "12345678901", "", "32-0193"])
def test_a_non_cik_is_refused(bad: str) -> None:
    with pytest.raises(ValueError, match="not a CIK"):
        zero_pad_cik(bad)


# --------------------------------------------------------------------------------------
# Checks 2 and 3 - rate limit and User-Agent, and the refusal that is never retried
# --------------------------------------------------------------------------------------


def test_requests_are_spaced_at_least_120ms_apart() -> None:
    clock = [1000.0]
    slept: list[float] = []

    def fake_sleep(seconds: float) -> None:
        slept.append(seconds)
        clock[0] += seconds

    throttle = _Throttle(0.12, clock=lambda: clock[0], sleep=fake_sleep)
    throttle.wait()  # first request: no wait
    throttle.wait()  # immediately after: must wait the full interval
    clock[0] += 0.05
    throttle.wait()  # 50 ms later: waits the remaining 70 ms
    assert slept == pytest.approx([0.12, 0.07])


def test_user_agent_with_name_and_email_is_sent(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: dict[str, str] = {}

    def fake_get(url: str, *, headers: dict[str, str], **_: object) -> httpx.Response:
        seen.update(headers)
        return httpx.Response(200, content=b"{}", request=httpx.Request("GET", url))

    monkeypatch.setattr(httpx, "get", fake_get)
    connector = EdgarSubmissionsConnector(
        user_agent=UA, throttle=_Throttle(0, sleep=lambda s: None)
    )
    connector.fetch(cik="320193")
    assert seen["User-Agent"] == UA
    assert "@" in seen["User-Agent"]


def test_missing_user_agent_refuses_to_run(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "packages.ingestion.edgar.get_settings",
        lambda: type("S", (), {"sec_user_agent": None})(),
    )
    with pytest.raises(MissingUserAgentError):
        _ = EdgarSubmissionsConnector().user_agent
    with pytest.raises(MissingUserAgentError):
        _ = EdgarSubmissionsConnector(user_agent="no email here").user_agent


@pytest.mark.parametrize("status", [403, 429])
def test_a_refusal_raises_and_is_not_retried(monkeypatch: pytest.MonkeyPatch, status: int) -> None:
    calls: list[str] = []

    def fake_get(url: str, **_: object) -> httpx.Response:
        calls.append(url)
        return httpx.Response(status, content=b"blocked", request=httpx.Request("GET", url))

    monkeypatch.setattr(httpx, "get", fake_get)
    connector = EdgarCompanyFactsConnector(
        user_agent=UA, throttle=_Throttle(0, sleep=lambda s: None)
    )
    with pytest.raises(EdgarRefusedError, match=str(status)):
        connector.fetch(cik="320193")
    assert len(calls) == 1, "a 403/429 comes with a ten-minute IP block; retrying extends it"
    assert calls[0].endswith(f"/CIK{APPLE_CIK}.json")


# --------------------------------------------------------------------------------------
# Periods - fiscal year and period type from the dates, never from the filing's fy/fp
# --------------------------------------------------------------------------------------


def test_apple_quarters_and_fiscal_years() -> None:
    """September year end: December is Q1 of the *next* fiscal year."""
    assert quarter_of(dt.date(2025, 12, 27), 9) == 1
    assert quarter_of(dt.date(2026, 3, 28), 9) == 2
    assert quarter_of(dt.date(2026, 6, 27), 9) == 3
    assert quarter_of(dt.date(2024, 9, 28), 9) == 4
    assert fiscal_year_of(dt.date(2024, 9, 28), 9) == 2024
    assert fiscal_year_of(dt.date(2025, 12, 27), 9) == 2026


def test_walmart_january_year_end() -> None:
    assert fiscal_year_of(dt.date(2025, 1, 31), 1) == 2025
    assert quarter_of(dt.date(2025, 4, 30), 1) == 1
    assert fiscal_year_of(dt.date(2025, 4, 30), 1) == 2026


def test_a_53_week_spillover_stays_in_its_fiscal_month() -> None:
    """A year end of 2022-10-01 is still September's year end, not October's."""
    assert quarter_of(dt.date(2022, 10, 1), 9) == 4
    assert fiscal_year_of(dt.date(2022, 10, 1), 9) == 2022


def test_period_types_by_duration() -> None:
    fy_end = dt.date(2025, 9, 27)
    assert period_type_of(dt.date(2024, 9, 29), fy_end, 9) == "FY"
    assert period_type_of(None, fy_end, 9) == "FY"
    q1_end = dt.date(2025, 12, 27)
    assert period_type_of(dt.date(2025, 9, 28), q1_end, 9) == "Q1"
    assert period_type_of(None, q1_end, 9) == "Q1"
    h1_end = dt.date(2026, 3, 28)
    assert period_type_of(dt.date(2025, 9, 28), h1_end, 9) == "H1"
    assert period_type_of(dt.date(2025, 12, 28), h1_end, 9) == "Q2"
    nine_months_end = dt.date(2026, 6, 27)
    assert period_type_of(dt.date(2025, 9, 28), nine_months_end, 9) == "YTD"
    assert period_type_of(dt.date(2026, 3, 29), nine_months_end, 9) == "Q3"


@pytest.mark.invariant
def test_a_thirteen_week_span_at_year_end_is_q4_not_fy() -> None:
    """Mistaking a fourth-quarter duration for the annual figure would understate FY by 75%."""
    assert period_type_of(dt.date(2025, 6, 29), dt.date(2025, 9, 27), 9) == "Q4"


def test_a_span_the_vocabulary_cannot_name_is_refused() -> None:
    assert period_type_of(dt.date(2025, 1, 1), dt.date(2025, 5, 31), 9) is None  # 5 months
    assert period_type_of(dt.date(2023, 9, 29), dt.date(2025, 9, 27), 9) is None  # 2 years


def test_period_labels() -> None:
    assert period_label("FY", 2025) == "FY2025"
    assert period_label("Q1", 2026) == "Q1-FY2026"
    assert period_label("H1", 2026) == "H1-FY2026"
    assert period_label("YTD", 2026) == "9M-FY2026"


# --------------------------------------------------------------------------------------
# The chart - alternates resolve by priority; absent stays absent
# --------------------------------------------------------------------------------------


def _chart() -> ChartVersion:
    from packages.normalize.chart import Account

    return ChartVersion(
        version="t",
        source_system="us_gaap_xbrl",
        accounts={
            "revenue": Account("revenue", "income", "non_financial", "Revenue", "positive", True),
            "rd_expense": Account(
                "rd_expense", "income", "non_financial", "R&D", "positive", False
            ),
        },
        mappings={
            "revenue": (
                LabelMapping("Revenues", "revenue", 10),
                LabelMapping("RevenueFromContractWithCustomerExcludingAssessedTax", "revenue", 20),
            ),
            "rd_expense": (LabelMapping("ResearchAndDevelopmentExpense", "rd_expense", 10),),
        },
    )


def test_the_highest_priority_reporting_label_wins() -> None:
    reported = {
        "Revenues": Decimal("100"),
        "RevenueFromContractWithCustomerExcludingAssessedTax": Decimal("99"),
    }
    assert resolve(reported, _chart(), ["revenue"]) == {"revenue": Decimal("100")}
    reported = {"RevenueFromContractWithCustomerExcludingAssessedTax": Decimal("99")}
    assert resolve(reported, _chart(), ["revenue"]) == {"revenue": Decimal("99")}


@pytest.mark.invariant
def test_an_unreported_key_is_none_never_zero() -> None:
    resolved = resolve({"Revenues": Decimal("100")}, _chart(), ["revenue", "rd_expense"])
    assert resolved["rd_expense"] is None
    assert resolved["rd_expense"] != 0


# --------------------------------------------------------------------------------------
# Parse - pure, and the two dates stay two dates
# --------------------------------------------------------------------------------------


def test_parse_is_pure_and_keeps_filed_apart_from_end() -> None:
    connector = EdgarCompanyFactsConnector(user_agent=UA)
    facts = connector.parse(_facts_raw())
    assert facts == connector.parse(_facts_raw())
    assert len(facts) == 670
    fy2024_revenue = [
        f
        for f in facts
        if f.tag == "RevenueFromContractWithCustomerExcludingAssessedTax"
        and f.end == dt.date(2024, 9, 28)
        and f.start == dt.date(2023, 10, 1)
    ]
    # Reported twice: the FY2024 10-K, and as a comparative in the FY2025 10-K.
    assert [f.filed for f in fy2024_revenue] == [dt.date(2024, 11, 1), dt.date(2025, 10, 31)]
    assert {f.value for f in fy2024_revenue} == {Decimal("391035000000")}
    # The comparative's fy is the *filing's* year. It must not become the period's.
    assert fy2024_revenue[1].fy == 2025


def test_parse_keeps_only_monetary_us_gaap_facts() -> None:
    facts = EdgarCompanyFactsConnector(user_agent=UA).parse(_facts_raw())
    assert {f.unit for f in facts} == {"USD"}
    assert {f.taxonomy for f in facts} == {"us-gaap"}


def test_submissions_parse() -> None:
    (record,) = EdgarSubmissionsConnector(user_agent=UA).parse(_submissions_raw())
    assert record.cik == APPLE_CIK
    assert record.name == "Apple Inc."
    assert record.tickers == ("AAPL",)
    assert record.exchanges == ("Nasdaq",)
    assert record.fiscal_year_end_month == 9
    assert record.sic == "3571"


# --------------------------------------------------------------------------------------
# End to end against the database - identity, then statements, then a restatement
# --------------------------------------------------------------------------------------


@pytest.fixture
def local_store(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> LocalDiskBackend:
    store = LocalDiskBackend(tmp_path / "documents")
    monkeypatch.setattr(ingestion_base, "get_storage", lambda: store)
    return store


@pytest.fixture
def apple(db_session: Session, local_store: LocalDiskBackend) -> Iterator[Company]:
    """Apple registered from the submissions fixture, in a transaction that is rolled back."""
    connector = EdgarSubmissionsConnector(user_agent=UA)
    register(db_session, connector)
    connector.fetch = lambda **params: _submissions_raw()  # type: ignore[method-assign]
    result = connector.run(db_session, cik=APPLE_CIK)
    assert result.status == "ok", result.error
    company = db_session.execute(select(Company).where(Company.cik == APPLE_CIK)).scalar_one()
    yield company


def _facts_connector(raw: RawResponse) -> EdgarCompanyFactsConnector:
    connector = EdgarCompanyFactsConnector(user_agent=UA)
    connector.fetch = lambda **params: raw  # type: ignore[method-assign]
    return connector


def test_submissions_register_company_security_ticker_and_industry(
    db_session: Session, apple: Company
) -> None:
    assert apple.legal_name == "Apple Inc."
    assert apple.fiscal_year_end == 9
    assert apple.statement_template == "non_financial"
    security = db_session.execute(
        select(Security).where(Security.company_id == apple.id)
    ).scalar_one()
    assert security.currency == "USD"
    ticker = db_session.execute(
        select(SecurityIdentifier).where(SecurityIdentifier.security_id == security.id)
    ).scalar_one()
    assert (ticker.id_type, ticker.id_value, ticker.valid_to) == ("ticker", "AAPL", None)
    assert apple.industry_id is not None


def test_registering_twice_inserts_nothing_and_overwrites_nothing(
    db_session: Session, apple: Company
) -> None:
    connector = EdgarSubmissionsConnector(user_agent=UA)
    connector.fetch = lambda **params: _submissions_raw()  # type: ignore[method-assign]
    again = connector.run(db_session, cik=APPLE_CIK)
    assert again.status == "ok" and again.rows_written == 0
    assert db_session.execute(select(func.count()).select_from(Company)).scalar_one() >= 1


def test_companyfacts_write_statements_with_the_filing_date_as_known_as_of(
    db_session: Session, apple: Company
) -> None:
    """Checks 8 and 11, and the unchanged-re-report rule, on real Apple data."""
    result = _facts_connector(_facts_raw()).run(db_session, cik=APPLE_CIK)
    assert result.status == "ok", result.error
    assert result.records_parsed == 670
    assert result.rows_written > 0

    statements = (
        db_session.execute(select(Statement).where(Statement.company_id == apple.id))
        .scalars()
        .all()
    )
    assert statements, "no statements written"
    # Every period is version 1: Apple re-reported nothing differently in these filings,
    # and a comparative that matches is the same vintage continuing.
    assert {s.version for s in statements} == {1}
    assert all(s.superseded_by is None for s in statements)

    fy2024_income = next(
        s
        for s in statements
        if s.statement_type == "income"
        and s.period_type == "FY"
        and s.period_end == dt.date(2024, 9, 28)
    )
    assert fy2024_income.known_as_of == dt.date(2024, 11, 1), "known_as_of is the filing date"
    assert fy2024_income.known_as_of > fy2024_income.period_end
    assert fy2024_income.fiscal_year == 2024 and fy2024_income.period_label == "FY2024"
    assert fy2024_income.is_audited is True

    items = {i.canonical_key: i for i in fy2024_income.line_items}
    assert items["revenue"].value == Decimal("391035000000")
    assert items["rd_expense"].value == Decimal("31370000000")
    assert all(i.known_as_of == dt.date(2024, 11, 1) for i in items.values())
    assert all(i.source_document_id is not None for i in items.values())
    assert all(i.extraction_method == "xbrl" and i.page is None for i in items.values())

    filings = (
        db_session.execute(select(Filing).where(Filing.company_id == apple.id)).scalars().all()
    )
    assert any(
        f.accession_no == "0000320193-24-000123" and f.filing_type == "10-K" for f in filings
    )

    # Check 11 in the form docs/03 writes it.
    orphans = db_session.execute(
        text("SELECT count(*) FROM statement_line_items WHERE source_document_id IS NULL")
    ).scalar_one()
    assert orphans == 0


@pytest.mark.invariant
def test_a_missing_line_item_is_null_not_zero(db_session: Session, apple: Company) -> None:
    """Check 4: a company that reports no R&D has rd_expense NULL, never 0."""
    payload = json.loads(_facts_raw().data)
    del payload["facts"]["us-gaap"]["ResearchAndDevelopmentExpense"]
    raw = RawResponse(
        data=json.dumps(payload).encode(), media_type="application/json", url="x", http_status=200
    )
    assert _facts_connector(raw).run(db_session, cik=APPLE_CIK).status == "ok"
    security_id = db_session.execute(
        select(Security.id).where(Security.company_id == apple.id)
    ).scalar_one()
    rd = (
        db_session.execute(
            select(StatementLineItem.value)
            .where(StatementLineItem.security_id == security_id)
            .where(StatementLineItem.canonical_key == "rd_expense")
        )
        .scalars()
        .all()
    )
    assert rd, "the row exists so that the absence is visible"
    assert all(v is None for v in rd)


@pytest.mark.invariant
def test_a_restatement_keeps_both_versions_and_point_in_time_returns_the_original(
    db_session: Session, apple: Company
) -> None:
    """Check 15. FY2024 revenue is restated by a later filing; a decision date before that
    filing must return the figure the market actually had."""
    assert _facts_connector(_facts_raw()).run(db_session, cik=APPLE_CIK).status == "ok"

    # A later 10-K restating FY2024 revenue by exactly one dollar.
    payload = json.loads(_facts_raw().data)
    tag = "RevenueFromContractWithCustomerExcludingAssessedTax"
    payload["facts"]["us-gaap"] = {tag: payload["facts"]["us-gaap"][tag]}
    payload["facts"]["us-gaap"][tag]["units"]["USD"] = [
        {
            "start": "2023-10-01",
            "end": "2024-09-28",
            "val": 391035000001,
            "accn": "0000320193-26-999999",
            "fy": 2026,
            "fp": "FY",
            "form": "10-K",
            "filed": "2026-10-30",
        }
    ]
    raw = RawResponse(
        data=json.dumps(payload).encode(), media_type="application/json", url="y", http_status=200
    )
    restating = _facts_connector(raw).run(db_session, cik=APPLE_CIK)
    assert restating.status == "ok", restating.error

    versions = (
        db_session.execute(
            select(Statement)
            .where(Statement.company_id == apple.id)
            .where(Statement.statement_type == "income")
            .where(Statement.period_type == "FY")
            .where(Statement.period_end == dt.date(2024, 9, 28))
            .order_by(Statement.version)
        )
        .scalars()
        .all()
    )
    assert [v.version for v in versions] == [1, 2]
    original, restated = versions
    assert original.superseded_by == restated.id and restated.superseded_by is None
    assert restated.known_as_of == dt.date(2026, 10, 30) and restated.restatement_flag is True

    by_key = {i.canonical_key: i for i in restated.line_items}
    assert by_key["revenue"].value == Decimal("391035000001")
    assert by_key["revenue"].restatement_flag is True
    assert by_key["revenue"].correction_type == "restatement"
    # Not re-reported by the restating filing: carried forward, and not flagged.
    assert by_key["rd_expense"].value == Decimal("31370000000")
    assert by_key["rd_expense"].restatement_flag is False
    old_revenue = next(i for i in original.line_items if i.canonical_key == "revenue")
    assert old_revenue.superseded_by == by_key["revenue"].id

    security_id = db_session.execute(
        select(Security.id).where(Security.company_id == apple.id)
    ).scalar_one()
    before = {
        (r.period_type, r.period_end): r.value
        for r in line_items_as_known_on(
            db_session,
            security_id=security_id,
            decision_date=dt.date(2026, 6, 1),
            canonical_keys=("revenue",),
        )
    }
    after = {
        (r.period_type, r.period_end): r.value
        for r in line_items_as_known_on(
            db_session,
            security_id=security_id,
            decision_date=dt.date(2026, 12, 31),
            canonical_keys=("revenue",),
        )
    }
    assert before[("FY", dt.date(2024, 9, 28))] == Decimal("391035000000")
    assert after[("FY", dt.date(2024, 9, 28))] == Decimal("391035000001")


def test_point_in_time_requires_a_decision_date(db_session: Session) -> None:
    with pytest.raises(TypeError):
        line_items_as_known_on(db_session, security_id=1)  # type: ignore[call-arg]


@pytest.mark.invariant
def test_values_cannot_be_updated_but_supersession_can(db_session: Session, apple: Company) -> None:
    """The trigger: `UPDATE` of a figure is refused; setting `superseded_by` once is allowed."""
    assert _facts_connector(_facts_raw()).run(db_session, cik=APPLE_CIK).status == "ok"
    item_id = db_session.execute(
        select(StatementLineItem.id).where(StatementLineItem.value.is_not(None)).limit(1)
    ).scalar_one()
    with pytest.raises(Exception, match="UPDATE forbidden"):
        db_session.execute(
            text("UPDATE statement_line_items SET value = value + 1 WHERE id = :id"),
            {"id": item_id},
        )
    db_session.rollback()


def test_the_seeded_chart_loads_with_priorities(db_session: Session) -> None:
    chart = load_chart(db_session, version="v0.1", source_system="us_gaap_xbrl")
    assert "revenue" in chart.accounts and "gross_earnings" in chart.accounts
    assert [m.source_label for m in chart.mappings["revenue"]] == [
        "Revenues",
        "RevenueFromContractWithCustomerExcludingAssessedTax",
        "SalesRevenueNet",
    ]
    assert "gross_earnings" not in chart.keys_for("income", "non_financial")
    assert "profit_after_tax" in chart.keys_for("income", "financial")


def test_two_tickers_on_one_exchange_share_one_security(
    db_session: Session, local_store: LocalDiskBackend
) -> None:
    """Alphabet: tickers ["GOOGL", "GOOG"], exchanges ["Nasdaq", "Nasdaq"] - parallel lists.

    The first live run treated the exchange list as a set and the tickers as its children,
    inserted the same identifier twice, and Alphabet failed to register.
    """
    payload = json.loads(_submissions_raw().data)
    payload.update(
        {
            "cik": 1652044,
            "name": "Alphabet Inc.",
            "tickers": ["GOOGL", "GOOG"],
            "exchanges": ["Nasdaq", "Nasdaq"],
            "sic": "7370",
            "fiscalYearEnd": "1231",
        }
    )
    raw = RawResponse(data=json.dumps(payload).encode(), media_type="application/json", url="g")
    connector = EdgarSubmissionsConnector(user_agent=UA)
    register(db_session, connector)
    connector.fetch = lambda **params: raw  # type: ignore[method-assign]
    result = connector.run(db_session, cik="0001652044")
    assert result.status == "ok", result.error

    company = db_session.execute(select(Company).where(Company.cik == "0001652044")).scalar_one()
    securities = (
        db_session.execute(select(Security).where(Security.company_id == company.id))
        .scalars()
        .all()
    )
    assert len(securities) == 1
    tickers = (
        db_session.execute(
            select(SecurityIdentifier.id_value)
            .where(SecurityIdentifier.security_id == securities[0].id)
            .order_by(SecurityIdentifier.id_value)
        )
        .scalars()
        .all()
    )
    assert tickers == ["GOOG", "GOOGL"]
    assert company.fiscal_year_end == 12

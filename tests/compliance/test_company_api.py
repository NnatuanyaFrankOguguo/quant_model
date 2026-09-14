"""The P2 company routes: statements, ratios and DCF, through the real middleware stack.

Apple's real EDGAR and Yahoo fixtures are committed into the test database for the module
and removed afterwards, so the app's own connection sees them. The compliance properties
under test: every figure carries provenance and its filing date, the point-in-time date is
honoured, nulls stay null, the DCF runs only on the caller's assumptions and echoes every
input, and nothing served is a verdict.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Iterator
from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy import delete, func, select

from packages.common import db as common_db
from packages.common.models import (
    AdjustmentFactor,
    Company,
    CorporateAction,
    ExtractionJob,
    Filing,
    PriceHistory,
    Security,
    SecurityIdentifier,
    SharesOutstanding,
    SourceDocument,
    Statement,
    StatementLineItem,
)
from packages.common.storage import LocalDiskBackend
from packages.compliance.response_types import BANNED_PUBLIC_FIELD_NAMES
from packages.ingestion import base as ingestion_base
from packages.ingestion.base import RawResponse, register
from packages.ingestion.edgar import EdgarCompanyFactsConnector, EdgarSubmissionsConnector
from packages.ingestion.yahoo import YahooChartConnector

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"
UA = "Test Person test@example.com"
APPLE_CIK = "0000320193"


def _raw(relative: str) -> RawResponse:
    return RawResponse(
        data=(FIXTURES / relative).read_bytes(),
        media_type="application/json",
        url=f"fixture://{relative}",
        http_status=200,
    )


@pytest.fixture(scope="module")
def apple_loaded(tmp_path_factory: pytest.TempPathFactory) -> Iterator[None]:
    """Apple's identity, statements, share counts and 2020 prices, committed for the module."""
    store = LocalDiskBackend(tmp_path_factory.mktemp("documents"))
    original_storage = ingestion_base.get_storage
    ingestion_base.get_storage = lambda: store  # type: ignore[assignment]

    with common_db.SessionLocal() as session:
        first_document_id = session.execute(select(func.max(SourceDocument.id))).scalar() or 0
        submissions = EdgarSubmissionsConnector(user_agent=UA)
        register(session, submissions)
        submissions.fetch = lambda **p: _raw("edgar/AAPL_submissions_trimmed.json")  # type: ignore[method-assign]
        assert submissions.run(session, cik=APPLE_CIK).status == "ok"
        facts = EdgarCompanyFactsConnector(user_agent=UA)
        facts.fetch = lambda **p: _raw("edgar/AAPL_companyfacts_trimmed.json")  # type: ignore[method-assign]
        assert facts.run(session, cik=APPLE_CIK).status == "ok"
        prices = YahooChartConnector()
        register(session, prices)
        prices.fetch = lambda **p: _raw("yahoo/AAPL_chart_2020_split.json")  # type: ignore[method-assign]
        assert prices.run(session, symbol="AAPL").status == "ok"
        session.commit()
    try:
        yield
    finally:
        ingestion_base.get_storage = original_storage  # type: ignore[assignment]
        with common_db.SessionLocal() as session:
            company_id = session.execute(
                select(Company.id).where(Company.cik == APPLE_CIK)
            ).scalar_one()
            security_ids = select(Security.id).where(Security.company_id == company_id)
            session.execute(
                delete(StatementLineItem).where(StatementLineItem.security_id.in_(security_ids))
            )
            session.execute(delete(Statement).where(Statement.company_id == company_id))
            session.execute(delete(Filing).where(Filing.company_id == company_id))
            session.execute(
                delete(SharesOutstanding).where(SharesOutstanding.security_id.in_(security_ids))
            )
            session.execute(
                delete(AdjustmentFactor).where(AdjustmentFactor.security_id.in_(security_ids))
            )
            session.execute(
                delete(CorporateAction).where(CorporateAction.security_id.in_(security_ids))
            )
            session.execute(delete(PriceHistory).where(PriceHistory.security_id.in_(security_ids)))
            session.execute(
                delete(SecurityIdentifier).where(SecurityIdentifier.security_id.in_(security_ids))
            )
            session.execute(delete(Security).where(Security.company_id == company_id))
            session.execute(delete(Company).where(Company.id == company_id))
            session.execute(
                delete(ExtractionJob).where(ExtractionJob.source_document_id > first_document_id)
            )
            session.execute(delete(SourceDocument).where(SourceDocument.id > first_document_id))
            session.commit()


def test_companies_lists_apple_under_its_primary_ticker(client, apple_loaded) -> None:
    body = client.get("/v1/public/companies").json()
    apple = next(c for c in body["companies"] if c["ticker"] == "AAPL")
    assert apple["legal_name"] == "Apple Inc."
    assert apple["cik"] == APPLE_CIK
    assert apple["statement_periods"] > 0
    assert apple["latest_filing_date"] is not None
    # docs/05 §11 Q12/Q22: the fixture's newest period is Q3 FY2026 (to 2026-06-27), so
    # the next report is the 10-K, due by the SEC's longest deadline, 2026-12-29.
    assert apple["latest_period_end"] == "2026-06-27"
    assert apple["next_filing_form"] == "10-K"
    assert apple["next_filing_due_by"] == "2026-12-29"
    assert apple["filing_overdue"] is (dt.date.today() > dt.date(2026, 12, 29))


def test_statements_carry_provenance_and_the_filing_date(client, apple_loaded) -> None:
    response = client.get("/v1/public/companies/AAPL/statements", params={"period_type": "FY"})
    assert response.status_code == 200
    body = response.json()
    assert body["attribution"].startswith("Source: U.S. Securities and Exchange Commission")
    fy2025 = next(p for p in body["periods"] if p["period_label"] == "FY2025")
    assert fy2025["period_end"] == "2025-09-27"
    assert fy2025["known_as_of"] == "2025-10-31"
    assert fy2025["filing_type"] == "10-K"
    assert fy2025["accession_no"] == "0000320193-25-000079"
    # docs/05 §11 Q20: the accession is a door, not a label - the filing's folder on sec.gov.
    assert (
        fy2025["filing_url"] == "https://www.sec.gov/Archives/edgar/data/320193/000032019325000079/"
    )
    assert fy2025["source_document_id"] is not None
    revenue = fy2025["items"]["revenue"]
    assert Decimal(revenue["value"]) == Decimal("416161000000")
    assert revenue["known_as_of"] == "2025-10-31" and revenue["version"] == 1
    # docs/05 §11 Q2: the same figure a year earlier, as known on the same date, beside it.
    assert Decimal(revenue["prior_value"]) == Decimal("391035000000")
    assert Decimal(revenue["change_yoy"]) == Decimal("0.0643")
    assert fy2025["items"]["interest_expense"]["change_yoy"] is None
    oldest = min(body["periods"], key=lambda p: p["period_end"])
    assert oldest["items"]["revenue"]["prior_value"] is None, "no earlier year known: nothing"
    assert oldest["items"]["revenue"]["change_yoy"] is None
    # Apple no longer reports interest expense separately: null, present, never zero.
    assert "interest_expense" in fy2025["items"]
    assert fy2025["items"]["interest_expense"]["value"] is None


@pytest.mark.invariant
def test_a_blank_says_whose_silence_it_is(client, apple_loaded) -> None:
    """docs/05 §11 Q21. Two blanks, two different answers to "why is this empty?".

    `interest_expense`: chart v0.1 maps `InterestExpense`, and Apple's FY2025 10-K carries
    no such fact - the company's silence. `fx_loss_net`: chart v0.1 maps no XBRL tag at all,
    so no filing could have filled it - our gap, and the screen must not blame Apple for it.
    A figure that has a value carries no reason.
    """
    response = client.get("/v1/public/companies/AAPL/statements", params={"period_type": "FY"})
    assert response.status_code == 200
    fy2025 = next(p for p in response.json()["periods"] if p["period_label"] == "FY2025")
    items = fy2025["items"]
    assert items["revenue"]["value"] is not None and items["revenue"]["absent_because"] is None
    assert items["interest_expense"]["value"] is None
    assert items["interest_expense"]["absent_because"] == "not_in_filing"
    assert items["fx_loss_net"]["value"] is None
    assert items["fx_loss_net"]["absent_because"] == "no_mapping"
    # Every null names its kind; every value names none.
    for period in response.json()["periods"]:
        for key, figure in period["items"].items():
            assert (figure["value"] is None) == (figure["absent_because"] is not None), key


@pytest.mark.invariant
def test_statements_respect_the_point_in_time_date(client, apple_loaded) -> None:
    before = client.get(
        "/v1/public/companies/AAPL/statements",
        params={"as_known_on": "2025-10-30", "period_type": "FY"},
    ).json()
    labels = {p["period_label"] for p in before["periods"]}
    assert "FY2024" in labels
    assert "FY2025" not in labels, "filed 2025-10-31; unknowable the day before"
    assert before["as_known_on"] == "2025-10-30"


def test_unknown_ticker_is_a_404_from_the_public_vocabulary(client, apple_loaded) -> None:
    response = client.get("/v1/public/companies/NOPE/statements")
    assert response.status_code == 404
    assert response.json()["detail"] == "not_found"


def test_ratios_name_the_price_and_share_count_they_used(client, apple_loaded) -> None:
    response = client.get("/v1/public/companies/AAPL/ratios", params={"as_known_on": "2026-09-13"})
    assert response.status_code == 200
    body = response.json()
    assert body["period_label"] == "FY2025"
    assert body["known_as_of"] == "2025-10-31"
    # The fixture's newest bar is 2020-09-04; the response must say so, loudly.
    assert body["price"]["date"] == "2020-09-04"
    assert body["price"]["age_days"] == (dt.date(2026, 9, 13) - dt.date(2020, 9, 4)).days
    assert body["price"]["attribution"] == "Source: Yahoo Finance"
    assert body["shares"]["as_of_date"] == "2026-07-17"
    assert body["shares"]["basic_or_diluted"] == "basic"
    assert set(body["ratios"]) >= {"pe", "pb", "gross_margin", "interest_coverage"}
    assert body["ratios"]["interest_coverage"] is None
    assert Decimal(body["ratios"]["gross_margin"]).quantize(Decimal("0.0001")) == Decimal("0.4691")
    assert Decimal(body["inputs"]["revenue"]) == Decimal("416161000000")
    # docs/05 §11 Q16: the backdrop block is present for a USD company. The test database
    # holds no macro observations, so every reading is null and says so - never a default.
    backdrop = body["backdrop"]
    assert backdrop is not None
    assert backdrop["risk_free"] is None and backdrop["inflation"] is None
    assert backdrop["real_risk_free"] is None
    assert backdrop["inflation_basis"]


@pytest.mark.invariant
def test_ratios_without_a_known_price_return_multiples_as_null_not_omitted(
    client, apple_loaded
) -> None:
    body = client.get(
        "/v1/public/companies/AAPL/ratios", params={"as_known_on": "2024-01-15"}
    ).json()
    assert body["period_label"] == "FY2023"
    assert body["price"] is not None  # 2020 bars are known by 2024
    body = client.get(
        "/v1/public/companies/AAPL/ratios",
        params={"as_known_on": "2024-01-15", "period": "FY2023"},
    ).json()
    assert "pe" in body["ratios"]


def test_dcf_runs_on_the_callers_assumptions_and_echoes_every_input(client, apple_loaded) -> None:
    response = client.get(
        "/v1/public/companies/AAPL/dcf",
        params={
            "growth": "0.05,0.05,0.05",
            "discount_rate": "0.09",
            "terminal_growth": "0.02",
            "as_known_on": "2026-09-13",
        },
    )
    assert response.status_code == 200, response.text
    body = response.json()
    used = body["assumptions"]
    assert used["growth_rates"] == ["0.05", "0.05", "0.05"]
    assert used["discount_rate"] == "0.09" and used["terminal_growth"] == "0.02"
    # The facts were read from the statements, and the response says which period.
    assert used["base_free_cash_flow_source"] == "FY2025: cash_from_ops - capex"
    assert Decimal(used["base_free_cash_flow"]) == Decimal("111482000000") - Decimal("12715000000")
    assert used["net_debt_source"] == "FY2025: long_term_debt - cash"
    assert used["shares_source"].startswith("shares_outstanding as of 2026-07-17")
    assert len(body["present_values"]) == 3
    # To the cent: the model works at 34 significant digits, this arithmetic at 28.
    cent = Decimal("0.01")
    equity = Decimal(body["equity_value"]).quantize(cent)
    expected = (Decimal(body["enterprise_value"]) - Decimal(used["net_debt"])).quantize(cent)
    assert equity == expected
    assert body["value_per_share"] is not None
    assert 0 < Decimal(body["terminal_share_of_value"]) < 1


def test_dcf_never_chooses_the_assumptions(client, apple_loaded) -> None:
    """No growth, no discount rate, no terminal growth - no answer. A 422, not a default."""
    response = client.get("/v1/public/companies/AAPL/dcf", params={"discount_rate": "0.09"})
    assert response.status_code == 422
    assert response.json()["detail"] == "invalid_request"


def test_dcf_refuses_assumptions_it_cannot_value(client, apple_loaded) -> None:
    response = client.get(
        "/v1/public/companies/AAPL/dcf",
        params={"growth": "0.05", "discount_rate": "0.02", "terminal_growth": "0.03"},
    )
    assert response.status_code == 422


@pytest.mark.invariant
@pytest.mark.invariant
def test_ratio_history_is_the_multiple_as_the_market_first_saw_it(client, apple_loaded) -> None:
    """docs/05 §11 Q5. Each point is the period's first vintage on its own filing date.

    The fixture holds three annual reports (FY2023-FY2025) and prices only for 2020, so
    every point has its share count and no price: the multiples that need a price are
    null and say so by being present; the margins that do not are computed.
    """
    body = client.get("/v1/public/companies/AAPL/ratios/history").json()
    assert body["period_type"] == "FY" and body["price_attribution"].startswith("Source:")
    labels = [p["period_label"] for p in body["points"]]
    assert labels == ["FY2023", "FY2024", "FY2025"], "oldest first, own season only"
    published = {p["period_label"]: p["first_published"] for p in body["points"]}
    assert published == {"FY2023": "2023-11-03", "FY2024": "2024-11-01", "FY2025": "2025-10-31"}
    for point in body["points"]:
        gap = dt.date.fromisoformat(point["first_published"]) - dt.date.fromisoformat(
            point["period_end"]
        )
        assert 0 <= gap.days <= 120, "an original report, not a comparative years later"
        assert point["price"] is None and point["ratios"]["pe"] is None
        assert point["shares"] is not None
        assert set(point["ratios"]) == set(body["points"][0]["ratios"]), "every key, always"
    fy2025 = body["points"][-1]
    assert Decimal(fy2025["ratios"]["net_margin"]).quantize(Decimal("0.0001")) == Decimal("0.2692")
    assert fy2025["shares"]["as_of_date"] <= "2025-10-31", "the count known that day, not today's"

    # Point-in-time: a decision date before the FY2024 report sees one point.
    early = client.get(
        "/v1/public/companies/AAPL/ratios/history", params={"as_known_on": "2024-01-01"}
    ).json()
    assert [p["period_label"] for p in early["points"]] == ["FY2023"]


def test_no_company_response_field_is_advice_shaped(client, apple_loaded) -> None:
    for path, params in (
        ("/v1/public/companies", {}),
        ("/v1/public/companies/AAPL/statements", {"period_type": "FY"}),
        ("/v1/public/companies/AAPL/ratios", {}),
        ("/v1/public/companies/AAPL/ratios/history", {}),
        (
            "/v1/public/companies/AAPL/dcf",
            {"growth": "0.05", "discount_rate": "0.09", "terminal_growth": "0.02"},
        ),
    ):
        body = client.get(path, params=params).json()
        assert not (_all_keys(body) & BANNED_PUBLIC_FIELD_NAMES), path


def _all_keys(value: object) -> set[str]:
    keys: set[str] = set()
    if isinstance(value, dict):
        for k, v in value.items():
            keys.add(str(k))
            keys |= _all_keys(v)
    elif isinstance(value, list):
        for v in value:
            keys |= _all_keys(v)
    return keys


def test_the_company_page_is_a_thin_client_and_shows_a_banner_not_a_stack_trace(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The page holds no SQL and no arithmetic of its own; with the API down it says so."""
    from streamlit.testing.v1 import AppTest

    script = Path(__file__).resolve().parents[2] / "apps" / "streamlit" / "company_page.py"
    source = script.read_text(encoding="utf-8")
    for forbidden in ("sqlalchemy", "psycopg", "from packages", "import packages", "SELECT "):
        assert forbidden not in source, f"the page must not contain {forbidden!r}"

    monkeypatch.setenv("QUANT_API_BASE", "http://127.0.0.1:9")
    app = AppTest.from_file(str(script), default_timeout=30).run()
    assert not app.exception, "the page must not raise when the API is down"
    banners = [e.value for e in app.error]
    assert any("Cannot reach the API" in text for text in banners), banners
    assert any("uvicorn" in text for text in banners), "it must say how to start the API"


@pytest.mark.parametrize(
    ("params", "expected"),
    [
        ({}, ("AAPL", dt.date(2026, 9, 14), "FY")),
        (
            {"ticker": "msft", "as_known_on": "2024-03-01", "periods": "q1"},
            ("MSFT", dt.date(2024, 3, 1), "Q1"),
        ),
        (
            {"ticker": "NOPE", "as_known_on": "not-a-date", "periods": "weekly"},
            ("AAPL", dt.date(2026, 9, 14), "FY"),
        ),
        ({"as_known_on": "2031-01-01"}, ("AAPL", dt.date(2026, 9, 14), "FY")),  # never the future
        ({"as_known_on": "1970-01-01"}, ("AAPL", dt.date(1980, 1, 1), "FY")),  # never before data
    ],
)
def test_a_shared_address_reproduces_the_view_or_falls_back_to_the_defaults(
    params: dict[str, str], expected: tuple[str, dt.date, str]
) -> None:
    """docs/05 §11 Q31: the page's address carries ticker, date and period type."""
    import importlib.util

    script = Path(__file__).resolve().parents[2] / "apps" / "streamlit" / "company_page.py"
    spec = importlib.util.spec_from_file_location("company_page", script)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    tickers = ["AAPL", "MSFT", "NVDA"]
    assert module._state_from_query(params, tickers, dt.date(2026, 9, 14)) == expected

"""P3.1 and P3.2's write surfaces, end to end through the API. AD-3.

`docs/03` P3.2 says the form is a *thin client* writing **through the API**, so these two
routes are where the rules actually have to hold. The rules themselves are tested against the
domain module in `tests/unit/test_manual_entry.py`; what is tested here is the part only the
HTTP surface can get wrong:

* **who may write.** These are the first routes in the project that change the record, and
  they sit behind `personal_tier` for that reason. An anonymous caller adding a figure to a
  financial database would be the single worst hole the API could have.
* **whose name goes on the figure.** `reviewed_by` is taken from the authenticated principal
  and the request body has no such field. A caller who could name the reviewer could
  attribute their typing to somebody else, and the only value that column has is telling a
  later reader who to ask.
* **that a refusal writes nothing.** The 422 path runs inside `get_session`, so the
  transaction rolls back. A form that reported an error while leaving a statement behind
  would be the half-entered state the whole entry module is built to prevent.
"""

from __future__ import annotations

import datetime as dt
import uuid
from pathlib import Path

import pytest
from sqlalchemy import text

from packages.common import db as common_db

pytestmark = pytest.mark.invariant

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"
REAL_REPORT = FIXTURES / "pdf" / "dmo_auction_september_2026.pdf"

DOCUMENTS = "/v1/personal/documents"
STATEMENTS = "/v1/personal/statements"

#: Prefix on every company this suite creates, so a leftover row is identifiable.
TEST_COMPANY_PREFIX = "zz-test-manual-entry-"


def _pdf_bytes() -> bytes:
    return REAL_REPORT.read_bytes()


@pytest.fixture
def cleanup() -> object:
    """Remove what these tests write. They commit, because an endpoint commits."""
    written: dict[str, list[int]] = {
        "statements": [],
        "documents": [],
        "securities": [],
        "companies": [],
        "identifiers": [],
    }
    yield written
    # Children before parents, or the foreign keys refuse the delete and the next run finds
    # this suite's rows still sitting in the database.
    with common_db.SessionLocal() as session:
        if written["securities"]:
            session.execute(
                text("DELETE FROM statement_line_items WHERE security_id = ANY(:ids)"),
                {"ids": written["securities"]},
            )
        if written["companies"]:
            session.execute(
                text("DELETE FROM statements WHERE company_id = ANY(:ids)"),
                {"ids": written["companies"]},
            )
        if written["statements"]:
            session.execute(
                text("DELETE FROM statement_line_items WHERE statement_id = ANY(:ids)"),
                {"ids": written["statements"]},
            )
            session.execute(
                text("DELETE FROM statements WHERE id = ANY(:ids)"),
                {"ids": written["statements"]},
            )
        if written["identifiers"]:
            session.execute(
                text("DELETE FROM security_identifiers WHERE security_id = ANY(:ids)"),
                {"ids": written["identifiers"]},
            )
        if written["securities"]:
            session.execute(
                text("DELETE FROM securities WHERE id = ANY(:ids)"),
                {"ids": written["securities"]},
            )
        if written["companies"]:
            session.execute(
                text("DELETE FROM companies WHERE id = ANY(:ids)"),
                {"ids": written["companies"]},
            )
        if written["documents"]:
            session.execute(
                text("DELETE FROM source_documents WHERE id = ANY(:ids)"),
                {"ids": written["documents"]},
            )
        session.commit()


# --------------------------------------------------------------------------------------
# Who may write
# --------------------------------------------------------------------------------------


def test_an_anonymous_caller_cannot_upload_a_document(client) -> None:
    """The first routes that change the record, and the gate is the router's, not the route's."""
    response = client.post(DOCUMENTS, files={"file": ("r.pdf", _pdf_bytes(), "application/pdf")})
    assert response.status_code == 403


def test_an_anonymous_caller_cannot_enter_a_statement(client) -> None:
    response = client.post(STATEMENTS, json={"ticker": "ZZNOSUCH"})
    assert response.status_code == 403


def test_an_unentitled_caller_cannot_write(client, make_actor) -> None:
    """Same 403, same body, whatever the reason — the caller cannot tell which they are."""
    plain = make_actor(personal_tier=False)
    assert (
        client.post(
            DOCUMENTS,
            files={"file": ("r.pdf", _pdf_bytes(), "application/pdf")},
            headers=plain.auth,
        ).status_code
        == 403
    )
    assert client.post(STATEMENTS, json={}, headers=plain.auth).status_code == 403


# --------------------------------------------------------------------------------------
# P3.1 through HTTP
# --------------------------------------------------------------------------------------


def test_uploading_a_real_pdf_stores_it_and_counts_its_pages(client, make_actor, cleanup) -> None:
    operator = make_actor()
    response = client.post(
        DOCUMENTS,
        files={"file": ("dmo_september_2026.pdf", _pdf_bytes(), "application/pdf")},
        headers=operator.auth,
    )
    assert response.status_code == 201, response.text
    body = response.json()
    cleanup["documents"].append(body["document_id"])

    assert body["page_count"] == 1, "the real document has one page"
    assert body["created"] is True
    assert len(body["sha256"]) == 64


def test_re_uploading_the_same_pdf_is_a_no_op(client, make_actor, cleanup) -> None:
    """P3 check 1 over HTTP. 201 both times — the request succeeded — and `created` differs."""
    operator = make_actor()
    first = client.post(
        DOCUMENTS,
        files={"file": ("r.pdf", _pdf_bytes(), "application/pdf")},
        headers=operator.auth,
    ).json()
    cleanup["documents"].append(first["document_id"])
    second = client.post(
        DOCUMENTS,
        files={"file": ("a-different-name.pdf", _pdf_bytes(), "application/pdf")},
        headers=operator.auth,
    ).json()

    assert second["document_id"] == first["document_id"]
    assert first["created"] is True and second["created"] is False


def test_an_upload_that_is_not_a_pdf_is_refused(client, make_actor) -> None:
    """Named `.pdf`, and an HTML error page inside. The content is what is checked."""
    operator = make_actor()
    response = client.post(
        DOCUMENTS,
        files={
            "file": (
                "annual_report.pdf",
                b"<!DOCTYPE html><html><body>404 Not Found</body></html>",
                "application/pdf",
            )
        },
        headers=operator.auth,
    )
    assert response.status_code == 422
    body = response.json()
    # `docs/10` §4.7's closed vocabulary: the reason never reaches the body. What comes back
    # is the fixed word plus the *name* of the field at fault, so the form can mark it.
    assert body["detail"] == "invalid_request"
    assert body["fields"] == ["file"]
    assert "not a PDF" not in response.text, "the reason belongs in the log, not the body"


# --------------------------------------------------------------------------------------
# P3.2 through HTTP
# --------------------------------------------------------------------------------------


@pytest.fixture
def ticker(cleanup: dict[str, list[int]]) -> str:
    """A company, a security and a current primary ticker, committed and then removed.

    Created rather than looked up. The first version of this file skipped when the database
    held no securities, which meant the two tests that actually exercise P3.2 were the two
    that did not run - and a skip reads as success in the summary line.

    The ticker is registered because the endpoint resolves one: a client cannot obtain a
    `security_id` from the public API, so the write route is addressed the way every read
    route is.
    """
    symbol = f"ZZT{uuid.uuid4().hex[:5].upper()}"
    with common_db.SessionLocal() as session:
        exchange_id = session.execute(
            text("SELECT id FROM exchanges ORDER BY id LIMIT 1")
        ).scalar_one()
        company_id = session.execute(
            text(
                "INSERT INTO companies (legal_name, country, statement_template, "
                "fiscal_year_end) VALUES (:name, 'NG', 'non_financial', 12) RETURNING id"
            ),
            {"name": f"{TEST_COMPANY_PREFIX}{uuid.uuid4().hex[:8]} Plc"},
        ).scalar_one()
        security_id = session.execute(
            text(
                "INSERT INTO securities (company_id, exchange_id, currency) "
                "VALUES (:company, :exchange, 'NGN') RETURNING id"
            ),
            {"company": company_id, "exchange": exchange_id},
        ).scalar_one()
        session.execute(
            text(
                "INSERT INTO security_identifiers (security_id, id_type, id_value, "
                "exchange_id, is_primary, valid_from, source) VALUES "
                "(:security, 'ticker', :symbol, :exchange, true, :from_date, :source)"
            ),
            {
                "security": security_id,
                "symbol": symbol,
                "exchange": exchange_id,
                "from_date": dt.date(2000, 1, 1),
                "source": "test_manual_entry_api",
            },
        )
        session.commit()
    cleanup["identifiers"].append(security_id)
    cleanup["securities"].append(security_id)
    cleanup["companies"].append(company_id)
    return symbol


def test_a_typed_statement_is_written_with_the_callers_name_on_it(
    client, make_actor, cleanup, ticker
) -> None:
    """The heart of P3.2: provenance the server fills in, not the caller.

    `reviewed_by` is the authenticated principal's label. The request body cannot set it,
    which is checked below by sending one and finding it ignored.
    """
    operator = make_actor()

    document = client.post(
        DOCUMENTS,
        files={"file": ("r.pdf", _pdf_bytes(), "application/pdf")},
        headers=operator.auth,
    ).json()
    cleanup["documents"].append(document["document_id"])

    response = client.post(
        STATEMENTS,
        json={
            "ticker": ticker,
            "statement_type": "income",
            "period_type": "FY",
            "period_end": "2019-12-31",
            "known_as_of": "2020-04-30",
            "currency": "USD",
            "scale": "thousands",
            "source_document_id": document["document_id"],
            "figures": [
                {"canonical_key": "revenue", "printed": "3,360,000", "page": 1},
                {"canonical_key": "income_tax", "printed": "", "page": 1},
            ],
            # Sent deliberately, and must be ignored: the server names the reviewer.
            "reviewed_by": "somebody-else",
        },
        headers=operator.auth,
    )
    assert response.status_code == 201, response.text
    body = response.json()
    cleanup["statements"].append(body["statement_id"])

    assert body["line_items_written"] == 2
    assert body["figures_absent"] == 1, "the blank field stored NULL"
    assert body["reviewed_by"] != "somebody-else"
    assert operator.external_id in body["reviewed_by"], "the server attached its own name"

    with common_db.SessionLocal() as session:
        rows = session.execute(
            text(
                "SELECT canonical_key, value, page, extraction_method, reviewed_by "
                "FROM statement_line_items WHERE statement_id = :id ORDER BY canonical_key"
            ),
            {"id": body["statement_id"]},
        ).all()
    stored = {row[0]: row for row in rows}
    assert stored["income_tax"][1] is None, "blank stored NULL, not zero"
    assert stored["revenue"][1] == 3_360_000_000
    for row in rows:
        assert row[2] == 1, "every manual item cites a page"
        assert row[3] == "manual"
        assert operator.external_id in row[4]


def test_a_refused_entry_leaves_nothing_behind(client, make_actor, cleanup, ticker) -> None:
    """422 with the reason, and no statement — the endpoint's half of the whole-entry promise.

    The refusal is raised inside `get_session`, which rolls back on any exception. A form
    reporting an error while leaving a statement behind is the state the entry module exists
    to prevent, and it would be invisible until someone counted rows.
    """
    operator = make_actor()
    document = client.post(
        DOCUMENTS,
        files={"file": ("r.pdf", _pdf_bytes(), "application/pdf")},
        headers=operator.auth,
    ).json()
    cleanup["documents"].append(document["document_id"])

    period_end = "2018-12-31"
    response = client.post(
        STATEMENTS,
        json={
            "ticker": ticker,
            "statement_type": "income",
            "period_type": "FY",
            "period_end": period_end,
            "known_as_of": "2019-04-30",
            "currency": "USD",
            "scale": "thousands",
            "source_document_id": document["document_id"],
            # The second figure cites page 500 of a one-page document.
            "figures": [
                {"canonical_key": "revenue", "printed": "1,000", "page": 1},
                {"canonical_key": "profit_after_tax", "printed": "100", "page": 500},
            ],
        },
        headers=operator.auth,
    )
    assert response.status_code == 422
    refusal = response.json()
    assert refusal["detail"] == "invalid_request", "docs/10 §4.7's closed vocabulary"
    # The offending figure, by the name of its input. The form marks that row; the sentence
    # explaining why is in the log under this response's `request_id`.
    assert refusal["fields"] == ["figures.1.printed"]
    assert refusal["request_id"], "the body ties itself to its audit row"
    assert "500" not in refusal["detail"], "no value the caller typed comes back"

    with common_db.SessionLocal() as session:
        left_behind = session.execute(
            text(
                "SELECT count(*) FROM statements WHERE period_end = :end "
                "AND source_document_id = :doc"
            ),
            {"end": dt.date.fromisoformat(period_end), "doc": document["document_id"]},
        ).scalar_one()
    assert left_behind == 0, "the refusal rolled back"


def test_a_malformed_body_is_refused_before_anything_is_read(client, make_actor) -> None:
    """Pydantic's own 422: a page below 1 and an unknown statement type never reach the rules."""
    operator = make_actor()
    response = client.post(
        STATEMENTS,
        json={
            "ticker": "ZZNOSUCH",
            "statement_type": "equity",  # not one of income|balance|cashflow
            "period_type": "FY",
            "period_end": "2025-12-31",
            "known_as_of": "2026-04-30",
            "currency": "NGN",
            "scale": "thousands",
            "source_document_id": 1,
            "figures": [{"canonical_key": "revenue", "printed": "1", "page": 0}],
        },
        headers=operator.auth,
    )
    assert response.status_code == 422


def test_an_entry_with_no_figures_is_refused_by_the_schema(client, make_actor) -> None:
    """`figures` has `min_length=1`. A statement with no figures is not a statement."""
    operator = make_actor()
    response = client.post(
        STATEMENTS,
        json={
            "ticker": "ZZNOSUCH",
            "statement_type": "income",
            "period_type": "FY",
            "period_end": "2025-12-31",
            "known_as_of": "2026-04-30",
            "currency": "NGN",
            "scale": "thousands",
            "source_document_id": 1,
            "figures": [],
        },
        headers=operator.auth,
    )
    assert response.status_code == 422


def test_an_unknown_ticker_is_refused_and_blamed_on_the_ticker(client, make_actor, cleanup) -> None:
    """The route resolves the ticker, so an unknown one is a 422 naming that field.

    Worth its own test because the resolution happens before any rule in the entry module
    runs: a typo in the company box must not read as a problem with the figures.
    """
    operator = make_actor()
    document = client.post(
        DOCUMENTS,
        files={"file": ("r.pdf", _pdf_bytes(), "application/pdf")},
        headers=operator.auth,
    ).json()
    cleanup["documents"].append(document["document_id"])

    response = client.post(
        STATEMENTS,
        json={
            "ticker": "ZZ-NO-SUCH-TICKER",
            "statement_type": "income",
            "period_type": "FY",
            "period_end": "2025-12-31",
            "known_as_of": "2026-04-30",
            "currency": "NGN",
            "scale": "thousands",
            "source_document_id": document["document_id"],
            "figures": [{"canonical_key": "revenue", "printed": "1,000", "page": 1}],
        },
        headers=operator.auth,
    )
    assert response.status_code == 422
    assert response.json()["fields"] == ["ticker"]

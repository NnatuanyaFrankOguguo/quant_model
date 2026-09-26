"""P4.1's pipeline, end to end, with the model stubbed. `docs/03` P4.1.

Every box in P4.1's flowchart except the model call is deterministic, so the whole path can
be exercised today against a reconciler that returns a canned response. That is the point
of the `Reconciler` protocol: the day an API key arrives the work is one class, and the
wiring around it has already been proved.

What these assert is the **order**, because the order is the safety property. Budget before
the call, grounding before validation, validation before the store, and a row on every
path including the ones that fall over.
"""

from __future__ import annotations

import datetime as dt
import json
from collections.abc import Sequence
from decimal import Decimal

import pytest
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from packages.common.models import Company, DataSource, Entitlement, Principal, SourceDocument
from packages.common.timez import utcnow
from packages.extract.budget import BudgetExceededError
from packages.extract.pdf import PageRead
from packages.extract.pipeline import UNREADABLE, ModelCall, extract_document
from packages.extract.routing import NEEDS_REVIEW, STORED

pytestmark = pytest.mark.invariant

PERIOD_END = dt.date(2024, 12, 31)
FISCAL_YEAR = 2024
REQUIRED = frozenset({"revenue", "profit_after_tax"})

#: A one-page PDF whose text layer really does contain the figures below, built with
#: pdfplumber-readable content so `read_pages` classifies it `native` and grounding has
#: something true to find. Hand-built rather than a fixture file for the same reason
#: `test_documents.py` builds its own: a fixture would only prove pdfplumber agrees with
#: itself.
STATEMENT_TEXT = (
    "MTN Nigeria Communications Plc\n"
    "Statement of profit or loss\n"
    "In thousands of naira 2024 2023\n"
    "Revenue 3,360,000 2,470,000\n"
    "Cost of sales (1,120,000) (890,000)\n"
    "Gross profit 2,240,000 1,580,000\n"
    "Loss for the year (400,440) (137,000)\n"
)


def one_page_pdf(body: str) -> bytes:
    """A single-page PDF with a real text layer, assembled by hand.

    Long enough to clear `MIN_NATIVE_CHARS`, so the page classifies `native` and the
    routing decision is not quietly penalised by table quality.
    """
    lines = "".join(
        f"({line.replace('(', chr(92) + '(').replace(')', chr(92) + ')')}) Tj T*\n"
        for line in body.splitlines()
    )
    stream = f"BT /F1 10 Tf 12 TL 40 740 Td\n{lines}ET".encode("latin-1")
    objects = [
        b"1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj\n",
        b"2 0 obj<</Type/Pages/Count 1/Kids[3 0 R]>>endobj\n",
        b"3 0 obj<</Type/Page/Parent 2 0 R/MediaBox[0 0 612 792]"
        b"/Resources<</Font<</F1 5 0 R>>>>/Contents 4 0 R>>endobj\n",
        b"4 0 obj<</Length "
        + str(len(stream)).encode()
        + b">>stream\n"
        + stream
        + b"\nendstream endobj\n",
        b"5 0 obj<</Type/Font/Subtype/Type1/BaseFont/Helvetica>>endobj\n",
    ]
    out = bytearray(b"%PDF-1.4\n")
    offsets = []
    for obj in objects:
        offsets.append(len(out))
        out += obj
    xref_at = len(out)
    out += f"xref\n0 {len(objects) + 1}\n0000000000 65535 f \n".encode()
    for offset in offsets:
        out += f"{offset:010d} 00000 n \n".encode()
    out += (
        f"trailer<</Size {len(objects) + 1}/Root 1 0 R>>\nstartxref\n{xref_at}\n%%EOF\n"
    ).encode()
    return bytes(out)


PDF = one_page_pdf(STATEMENT_TEXT)


def response(**overrides: object) -> str:
    payload: dict[str, object] = {
        "company": "MTN Nigeria Communications Plc",
        "period_end": "2024-12-31",
        "currency": "NGN",
        "unit_multiplier": 1000,
        "statement": "income_statement",
        "line_items": [
            {
                "canonical_key": "revenue",
                "as_printed": "Revenue",
                "value": 3360000,
                "page": 1,
                "confidence": 0.97,
            },
            {
                "canonical_key": "cost_of_revenue",
                "as_printed": "Cost of sales",
                "value": -1120000,
                "page": 1,
                "confidence": 0.95,
            },
            {
                "canonical_key": "gross_profit",
                "as_printed": "Gross profit",
                "value": 2240000,
                "page": 1,
                "confidence": 0.96,
            },
            {
                "canonical_key": "profit_after_tax",
                "as_printed": "Loss for the year",
                "value": -400440,
                "page": 1,
                "confidence": 0.95,
            },
        ],
    }
    payload.update(overrides)
    return json.dumps(payload)


class StubReconciler:
    """A `Reconciler` that returns whatever it was handed, and records that it was called.

    `called` is the assertion that matters for the budget test: the gate is only a gate if
    the model is *not* reached when it closes.
    """

    model_name = "claude-test"
    prompt_version = "p4.2-v1"

    def __init__(self, text_response: str | None = None, *, cost: str = "0.05") -> None:
        self._response = text_response if text_response is not None else response()
        self._cost = Decimal(cost)
        self.called = 0

    def estimate_usd(self, pages: Sequence[PageRead]) -> Decimal:
        return self._cost

    def reconcile(
        self, pages: Sequence[PageRead], *, company: str, period_end: dt.date
    ) -> ModelCall:
        self.called += 1
        return ModelCall(
            response=self._response,
            input_tokens=12_000,
            output_tokens=900,
            cost_usd=self._cost,
        )


@pytest.fixture
def context(db_session: Session) -> dict[str, int]:
    """A principal with a budget, a company, and a stored document to attribute to."""
    who = Principal(display_name="zz-test-pipeline", kind="human")
    db_session.add(who)
    db_session.flush()
    db_session.add(
        Entitlement(
            principal_id=who.id,
            personal_tier=True,
            data_tier=True,
            llm_spend_cap_usd=Decimal("50"),
            granted_by="tests",
        )
    )
    company = Company(
        legal_name="zz-test-pipeline Plc",
        country="NG",
        statement_template="non_financial",
        fiscal_year_end=12,
    )
    db_session.add(company)
    source_id = db_session.execute(select(DataSource.id).order_by(DataSource.id)).scalars().first()
    document = SourceDocument(
        data_source_id=source_id,
        url="https://doclib.ngxgroup.test/mtn-fy2024.pdf",
        storage_key="documents/sha256/" + "7" * 64,
        sha256="7" * 64,
        media_type="application/pdf",
        retrieved_at=utcnow(),
    )
    db_session.add(document)
    db_session.flush()
    return {"principal_id": who.id, "company_id": company.id, "document_id": document.id}


def run(session: Session, context: dict[str, int], reconciler: StubReconciler, **kwargs: object):
    return extract_document(
        session,
        document_id=context["document_id"],
        pdf_bytes=PDF,
        company_id=context["company_id"],
        company_name="MTN Nigeria Communications Plc",
        period_type="FY",
        period_end=PERIOD_END,
        fiscal_year=FISCAL_YEAR,
        reconciler=reconciler,
        principal_id=context["principal_id"],
        required_keys=REQUIRED,
        **kwargs,
    )


# --------------------------------------------------------------------------------------
# The happy path
# --------------------------------------------------------------------------------------


def test_a_clean_extraction_comes_back_ready_to_store(
    db_session: Session, context: dict[str, int]
) -> None:
    """Every figure on the page, every identity that can run passing, confidence above the
    threshold. The pipeline's answer is `stored`, which is it saying *no human needed*."""
    outcome = run(db_session, context, StubReconciler())
    assert outcome.status == STORED
    assert outcome.stored
    assert outcome.extraction is not None
    assert outcome.grounding == ()
    assert outcome.pages_read == 1
    assert outcome.failures == []


def test_the_multiplier_is_applied_before_the_identities_see_the_figures(
    db_session: Session, context: dict[str, int]
) -> None:
    """₦3,360,000 thousand is ₦3.36 trillion, and the identities are checked in naira.

    Left unapplied, every identity would fail by a factor of a thousand - which reads as a
    catastrophic extraction rather than as the units mistake it is, and the cross-year
    check that exists to catch exactly this would be reporting the error it was built to
    prevent.
    """
    outcome = run(db_session, context, StubReconciler())
    assert outcome.extraction is not None
    revenue = outcome.extraction.line_items[0]
    assert outcome.extraction.in_reporting_units(revenue) == Decimal("3360000000")
    # And the composition identity passed on those figures, so it saw them consistently.
    assert outcome.status == STORED


# --------------------------------------------------------------------------------------
# Each gate, in order
# --------------------------------------------------------------------------------------


def test_the_budget_gate_closes_before_the_model_is_called(
    db_session: Session, context: dict[str, int]
) -> None:
    """*"Halt - do not continue billing."* A check after the call is an audit, not a limit.

    `reconciler.called` is the whole assertion: an exception raised after a successful API
    request would still have cost the money it was there to save.
    """
    db_session.execute(
        text("UPDATE entitlements SET llm_spend_cap_usd = 0 WHERE principal_id = :p"),
        {"p": context["principal_id"]},
    )
    db_session.flush()
    reconciler = StubReconciler()
    with pytest.raises(BudgetExceededError):
        run(db_session, context, reconciler)
    assert reconciler.called == 0, "the model was called after the budget had halted"


def test_an_invented_figure_routes_to_review_and_names_itself(
    db_session: Session, context: dict[str, int]
) -> None:
    """Grounding runs before validation, so a phantom figure is reported as a phantom.

    ₦2,800,000 thousand is a plausible revenue, on a real page, under a real label, with a
    confident score, and it breaks no arithmetic identity. It is simply not in the
    document, and the only check that can see that is the one comparing it to the page.
    """
    payload = json.loads(response())
    payload["line_items"][0]["value"] = 2800000
    outcome = run(db_session, context, StubReconciler(json.dumps(payload)))
    assert outcome.status == NEEDS_REVIEW
    assert any("value_not_on_page" in failure for failure in outcome.failures)


def test_a_broken_identity_routes_to_review(db_session: Session, context: dict[str, int]) -> None:
    """Gross profit that is not revenue less cost of revenue, with every figure real.

    All three are printed on the page, so grounding passes; the arithmetic between them
    does not, which is what the identities are for.
    """
    payload = json.loads(response())
    # 3,360,000 - 1,120,000 is 2,240,000, and the page prints it. Claim a different real
    # number from the same page instead, so grounding still passes and only the sum breaks.
    payload["line_items"][2]["value"] = 1580000
    payload["line_items"][2]["as_printed"] = "Gross profit"
    outcome = run(db_session, context, StubReconciler(json.dumps(payload)))
    assert outcome.status == NEEDS_REVIEW
    assert "revenue_less_cost_of_revenue_is_gross_profit" in outcome.failures


def test_a_low_confidence_reading_routes_to_review(
    db_session: Session, context: dict[str, int]
) -> None:
    """P4 check 8 through the whole pipeline rather than against `route` alone."""
    payload = json.loads(response())
    payload["line_items"][0]["confidence"] = 0.7
    outcome = run(db_session, context, StubReconciler(json.dumps(payload)))
    assert outcome.status == NEEDS_REVIEW
    assert outcome.decision is not None
    assert outcome.decision.self_report == Decimal("0.7")


# --------------------------------------------------------------------------------------
# Every run leaves a row
# --------------------------------------------------------------------------------------


def test_an_unparseable_response_still_writes_a_job_row(
    db_session: Session, context: dict[str, int]
) -> None:
    """A document the pipeline choked on and left no trace of looks exactly like one
    nobody ever tried - the same blindness `docs/10` §5.3 describes for connectors.

    It is also the case most likely to happen in production, because it is the one the
    model controls entirely.
    """
    outcome = run(db_session, context, StubReconciler("I could not read that PDF."))
    assert outcome.status == UNREADABLE
    assert outcome.extraction is None
    assert outcome.error is not None and "not JSON" in outcome.error

    row = db_session.execute(
        text("SELECT status, method, model_name FROM extraction_jobs WHERE id = :i"),
        {"i": outcome.job_id},
    ).one()
    assert row.status == UNREADABLE
    assert row.method == "llm_hybrid"
    assert row.model_name == "claude-test"


def test_the_job_row_records_what_failed_and_what_it_cost(
    db_session: Session, context: dict[str, int]
) -> None:
    """`validation_failures` is the column P4's own example table fills, and the reviewer
    reads it before opening anything."""
    payload = json.loads(response())
    payload["line_items"][0]["value"] = 2800000
    outcome = run(db_session, context, StubReconciler(json.dumps(payload), cost="0.12"))
    row = db_session.execute(
        text(
            "SELECT status, confidence, validation_failures, token_cost_usd, finished_at "
            "FROM extraction_jobs WHERE id = :i"
        ),
        {"i": outcome.job_id},
    ).one()
    assert row.status == NEEDS_REVIEW
    assert row.validation_failures
    assert row.token_cost_usd == Decimal("0.12")
    assert row.finished_at is not None


def test_the_call_is_billed_against_the_principal(
    db_session: Session, context: dict[str, int]
) -> None:
    """A run that spends and records nothing is a cap that cannot see its own spend."""
    run(db_session, context, StubReconciler(cost="0.30"))
    spent = db_session.execute(
        text("SELECT sum(cost_usd) FROM llm_spend WHERE principal_id = :p"),
        {"p": context["principal_id"]},
    ).scalar_one()
    assert spent == Decimal("0.30")


# --------------------------------------------------------------------------------------
# Printed sign versus stored sign
#
# Found by the first end-to-end run of this file, on a payload that was correct. The page
# prints cost of sales as `(1,120,000)`; the contract says `value` is what is printed, so
# the model reports it negative and grounding confirms it. The store's convention is the
# opposite - 2,068 `cost_of_revenue` rows are positive and none is negative - and
# `chart_of_accounts.sign_convention` declares it.
#
# Without the translation every gross-profit identity fails on correctly-read figures. Had
# the identity not existed, a negative cost would have been stored instead and every margin
# in the system would be wrong.
# --------------------------------------------------------------------------------------


def test_a_cost_printed_in_brackets_is_stored_as_a_positive_magnitude(
    db_session: Session, context: dict[str, int]
) -> None:
    """The page says `(1,120,000)`, the column holds `1,120,000`, and both are right."""
    outcome = run(db_session, context, StubReconciler())
    assert outcome.status == STORED
    # Reported as printed - negative - and grounded against the page in that form.
    cost = next(i for i in outcome.extraction.line_items if i.canonical_key == "cost_of_revenue")
    assert cost.value == Decimal("-1120000")
    assert outcome.grounding == ()
    # And the identities, which see the stored convention, agree that it composes.
    assert "revenue_less_cost_of_revenue_is_gross_profit" not in outcome.failures
    assert "cost_of_revenue_not_negative" not in outcome.failures


def test_a_loss_keeps_its_sign_because_the_chart_says_either(
    db_session: Session, context: dict[str, int]
) -> None:
    """The translation must not touch `profit_after_tax`.

    `sign_convention` is `either` for it, and that is the whole reason the column exists: a
    loss is negative and a profit is positive and both are real. Forcing a sign on it is
    how MTN's ₦400bn loss becomes a ₦400bn profit - the single most consequential wrong
    number this pipeline could produce, and one that breaks no identity on its own.
    """
    outcome = run(db_session, context, StubReconciler())
    loss = next(i for i in outcome.extraction.line_items if i.canonical_key == "profit_after_tax")
    assert loss.value == Decimal("-400440")
    assert outcome.extraction.in_reporting_units(loss) == Decimal("-400440000")
    assert outcome.status == STORED, "the loss was not flipped into a profit"

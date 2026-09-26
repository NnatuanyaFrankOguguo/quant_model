"""The review surface: what needs a human, and who is allowed to ask. P4.4.

`docs/03` P4.4 asks for a queue *"prioritised by materiality"*, because *"a FIFO queue
wastes your scarcest resource - reviewer attention - on trivia"*, and for the correction
rate as a headline metric: *"if it isn't falling, the extractor isn't learning and
something is wrong with the feedback loop."*

Both are **personal-tier**, and not merely because they are write-adjacent. The queue names
companies beside figures this system believes are wrong. That is an internal judgement
rather than a fact about the company, and serving it anonymously would be publishing an
accusation - so the gate is tested first and hardest.
"""

from __future__ import annotations

import datetime as dt
import uuid
from collections.abc import Iterator
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete, select

from packages.common import db as common_db
from packages.common.models import (
    Company,
    DataSource,
    Exchange,
    Security,
    SourceDocument,
    Statement,
    StatementLineItem,
)

pytestmark = pytest.mark.invariant

QUEUE = "/v1/personal/review/queue"
RATE = "/v1/personal/review/correction-rate"
WINDOW = {"start": "2026-01-01", "end": "2026-09-24"}

#: A balance sheet that does not balance, by a wide margin, on a required key. Enough to
#: produce a finding the queue will rank - and deliberately a large one, so it is not
#: ranked below whatever else the database happens to hold.
BROKEN = {
    "total_assets": Decimal("1000000000"),
    "total_liabilities": Decimal("400000000"),
    "total_equity": Decimal("100000000"),  # 500m, not 1bn
}
PERIOD_END = dt.date(2024, 12, 31)


@pytest.fixture
def a_finding_exists() -> Iterator[int]:
    """One company with one broken balance sheet, committed.

    Committed rather than held in a transaction because the endpoint opens its own session
    through `get_session()` - a row that only exists inside the test's transaction is a row
    the API cannot see, and the assertions would skip on an empty queue while appearing to
    have run.
    """
    marker = uuid.uuid4().hex[:10]
    with common_db.SessionLocal() as session:
        exchange_id = session.execute(select(Exchange.id).order_by(Exchange.id)).scalars().first()
        source_id = session.execute(select(DataSource.id).order_by(DataSource.id)).scalars().first()
        document = SourceDocument(
            data_source_id=source_id,
            url=f"file:///review-api-{marker}.json",
            storage_key=f"documents/sha256/{marker * 7}",
            sha256=(marker * 7)[:64],
            media_type="application/json",
            retrieved_at=dt.datetime(2025, 3, 1, tzinfo=dt.UTC),
        )
        session.add(document)
        company = Company(
            legal_name=f"cmpl-test-review {marker} Plc",
            country="NG",
            statement_template="non_financial",
            fiscal_year_end=12,
        )
        session.add(company)
        session.flush()
        security = Security(company_id=company.id, exchange_id=exchange_id, currency="NGN")
        session.add(security)
        session.flush()
        statement = Statement(
            company_id=company.id,
            statement_type="balance",
            period_type="FY",
            period_end=PERIOD_END,
            fiscal_year=2024,
            calendar_year=2024,
            period_label="FY2024",
            presentation_currency="NGN",
            presentation_multiplier=1,
            is_audited=True,
            is_consolidated=True,
            statement_template="non_financial",
            chart_version="v1",
            version=1,
            known_as_of=dt.date(2025, 4, 30),
            source_document_id=document.id,
        )
        session.add(statement)
        session.flush()
        for key, value in BROKEN.items():
            session.add(
                StatementLineItem(
                    statement_id=statement.id,
                    security_id=security.id,
                    canonical_key=key,
                    chart_version="v1",
                    value=value,
                    currency="NGN",
                    unit_multiplier=1,
                    period_end=PERIOD_END,
                    known_as_of=dt.date(2025, 4, 30),
                    version=1,
                    correction_type="none",
                    source_document_id=document.id,
                    page=1,
                    extraction_method="manual",
                )
            )
        session.commit()
        company_id = company.id
        statement_id = statement.id
        document_id = document.id
    try:
        yield company_id
    finally:
        with common_db.SessionLocal() as session:
            session.execute(
                delete(StatementLineItem).where(StatementLineItem.statement_id == statement_id)
            )
            session.execute(delete(Statement).where(Statement.id == statement_id))
            session.execute(delete(Security).where(Security.company_id == company_id))
            session.execute(delete(Company).where(Company.id == company_id))
            session.execute(delete(SourceDocument).where(SourceDocument.id == document_id))
            session.commit()


# --------------------------------------------------------------------------------------
# Who may ask
# --------------------------------------------------------------------------------------


def test_the_queue_is_not_served_anonymously(client: TestClient) -> None:
    """An accusation about a named company is not public data.

    The connector health report next door *is* anonymous, and the difference is the point:
    that one says a job did not run, this one says a figure is wrong.
    """
    assert client.get(QUEUE).status_code in (401, 403)


def test_the_correction_rate_is_not_served_anonymously(client: TestClient) -> None:
    """It is a measure of how often this system is wrong. Internal by construction."""
    assert client.get(RATE, params=WINDOW).status_code in (401, 403)


def test_a_caller_without_the_personal_tier_is_refused(client: TestClient, make_actor) -> None:
    """Authenticated is not the same as entitled."""
    actor = make_actor(personal_tier=False)
    assert client.get(QUEUE, headers=actor.auth).status_code == 403


# --------------------------------------------------------------------------------------
# What comes back
# --------------------------------------------------------------------------------------


def test_the_queue_answers_an_entitled_caller(client: TestClient, make_actor) -> None:
    """The happy path, and the shape the page depends on."""
    actor = make_actor()
    response = client.get(QUEUE, params={"limit": 5}, headers=actor.auth)
    assert response.status_code == 200
    body = response.json()
    assert body["limit"] == 5
    assert body["shown"] == len(body["items"])
    assert body["shown"] <= 5
    assert body["generated_at"]


def test_shown_is_reported_separately_from_the_limit(client: TestClient, make_actor) -> None:
    """A queue that returned fifty items and said nothing else looks identical whether
    fifty or five thousand are waiting - and queue depth is what `docs/03` P4 watches for
    reviewer-capacity trouble."""
    actor = make_actor()
    body = client.get(QUEUE, params={"limit": 3}, headers=actor.auth).json()
    assert "shown" in body and "limit" in body
    assert body["limit"] == 3


def test_every_item_carries_what_put_it_where_it_is(
    client: TestClient, make_actor, a_finding_exists: int
) -> None:
    """The ordering is a judgement, so the components of it come too.

    A reviewer who disagrees with the order can see what produced it rather than having to
    trust it - which matters because `priority` is the whole reason the queue is not FIFO.
    """
    actor = make_actor()
    items = client.get(
        QUEUE, params={"limit": 5, "company_id": a_finding_exists}, headers=actor.auth
    ).json()["items"]
    assert items, "the seeded broken balance sheet produced no finding"
    first = items[0]
    for field in (
        "company_name",
        "finding",
        "detail",
        "priority",
        "severity",
        "share_of_anchor",
        "is_required",
        "occurrences",
    ):
        assert field in first, f"the queue item does not carry {field!r}"


def test_the_queue_comes_back_worst_first(
    client: TestClient, make_actor, a_finding_exists: int
) -> None:
    """`docs/03` P4.4's actual requirement. A queue in the wrong order is a FIFO queue
    with extra steps.

    Seeded rather than skipped when the database is quiet: a skip reads as a pass in the
    summary line, and the ordering is the single thing P4.4 asks this endpoint for.
    """
    actor = make_actor()
    items = client.get(QUEUE, params={"limit": 20}, headers=actor.auth).json()["items"]
    assert len(items) >= 1, "the seeded finding is missing, so there is no order to check"
    priorities = [float(item["priority"]) for item in items]
    assert priorities == sorted(priorities, reverse=True)


# --------------------------------------------------------------------------------------
# The correction rate
# --------------------------------------------------------------------------------------


def test_the_correction_rate_separates_our_errors_from_restatements(
    client: TestClient, make_actor
) -> None:
    """Both are returned; only ours is in the rate.

    A company revising its own figures is the world changing its mind, not this system
    being wrong. Counting restatements would move the metric every time a filer amended
    something - in whichever direction, meaninglessly - and `TEAM_BRIEF.md` Part 3 makes
    this number the early-warning signal for the entire phase.
    """
    actor = make_actor()
    body = client.get(RATE, params=WINDOW, headers=actor.auth).json()
    assert "our_corrections" in body
    assert "restatements" in body
    assert "correction_rate" in body
    if body["items_written"]:
        expected = body["our_corrections"] / body["items_written"]
        assert abs(float(body["correction_rate"]) - expected) < 1e-9


def test_an_empty_window_reports_an_unknown_rate_rather_than_zero(
    client: TestClient, make_actor
) -> None:
    """Zero over zero items is not zero.

    A dashboard showing 0.0% for a week nothing ran would read as the best week on record,
    which is the opposite of what happened.
    """
    actor = make_actor()
    body = client.get(
        RATE,
        params={"start": "1990-01-01", "end": "1990-01-31"},
        headers=actor.auth,
    ).json()
    assert body["items_written"] == 0
    assert body["correction_rate"] is None


def test_a_window_that_ends_before_it_starts_is_refused(client: TestClient, make_actor) -> None:
    """It would otherwise return a confident zero over an impossible period."""
    actor = make_actor()
    response = client.get(
        RATE, params={"start": "2026-09-01", "end": "2026-01-01"}, headers=actor.auth
    )
    assert response.status_code == 422
    assert set(response.json()["fields"]) == {"start", "end"}


def test_the_window_comes_back_as_it_was_asked_for(client: TestClient, make_actor) -> None:
    """So a figure pasted into a report carries the period it describes."""
    actor = make_actor()
    body = client.get(RATE, params=WINDOW, headers=actor.auth).json()
    assert body["period_start"] == WINDOW["start"]
    assert body["period_end"] == WINDOW["end"]
    assert dt.date.fromisoformat(body["period_end"]) >= dt.date.fromisoformat(body["period_start"])

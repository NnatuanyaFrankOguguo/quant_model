"""The macro endpoints through the API layer. P1.4.

`tests/unit/test_macro_queries.py` proves the query engine. This proves the *surface*: that
an anonymous caller can reach published statistics, that provenance and both dates survive
serialization, and that the point-in-time parameter still hides later vintages once it has
been through a query string and a Pydantic model.

It lives in the compliance suite because that is where the `TestClient` is wired to the test
database, and because what it asserts is compliance-shaped: public-tier content reachable
without a credential, carrying its attribution, and carrying no advice-shaped field.
"""

from __future__ import annotations

import datetime as dt

import pytest
from sqlalchemy import delete, select

from packages.common import db as common_db
from packages.common.models import MacroObservation, MacroSeries, SourceDocument
from packages.compliance.response_types import BANNED_PUBLIC_FIELD_NAMES

SHA = "e" * 64


@pytest.fixture
def gdp_vintages():
    """Two vintages of one period, committed so the app's own connection can see them.

    Q2 2026 GDP first printed at 3.1 in August and was revised to 3.4 in November — the
    shape every point-in-time question is really about.
    """
    with common_db.SessionLocal() as session:
        series_id, data_source_id = session.execute(
            select(MacroSeries.id, MacroSeries.data_source_id).where(
                MacroSeries.code == "NG_GDP_GROWTH_YOY"
            )
        ).one()
        document = SourceDocument(
            data_source_id=data_source_id,
            url="file:///macro-api-fixture.csv",
            storage_key=f"documents/sha256/{SHA}",
            sha256=SHA,
            media_type="text/csv",
            retrieved_at=dt.datetime(2026, 8, 25, tzinfo=dt.UTC),
        )
        session.add(document)
        session.flush()
        for known, value in ((dt.date(2026, 8, 25), "3.1"), (dt.date(2026, 11, 20), "3.4")):
            session.add(
                MacroObservation(
                    series_id=series_id,
                    as_of_date=dt.date(2026, 6, 30),
                    known_as_of=known,
                    value=value,
                    source_document_id=document.id,
                )
            )
        session.commit()
    yield
    with common_db.SessionLocal() as session:
        session.execute(
            delete(MacroObservation).where(
                MacroObservation.source_document_id.in_(
                    select(SourceDocument.id).where(SourceDocument.sha256 == SHA)
                )
            )
        )
        session.execute(delete(SourceDocument).where(SourceDocument.sha256 == SHA))
        session.commit()


def test_series_list_is_reachable_anonymously(client) -> None:
    """Published government statistics are public-tier content in every mode."""
    response = client.get("/v1/public/macro/series")
    assert response.status_code == 200
    body = response.json()
    assert body["series"], "the seeded series list should not be empty"
    assert "as_of" in body


def test_every_series_carries_attribution(client) -> None:
    """The licensing register requires attribution, so it must reach the client.

    A surface that never receives the text cannot display it, and the register's requirement
    would be satisfied only in the database.
    """
    body = client.get("/v1/public/macro/series").json()
    for series in body["series"]:
        assert series["attribution"], f"{series['code']} reached the client with no attribution"
        assert series["source_name"]


@pytest.mark.invariant
def test_no_public_macro_field_is_advice_shaped(client) -> None:
    """Mechanism 2, at the surface rather than at the model.

    `register_public_type` walks field names at import time; this checks the JSON that
    actually goes out, which is what a reader — or a bulk export (ADR-0010) — would see.
    """
    body = client.get("/v1/public/macro/series").json()
    offending = set(body["series"][0]) & BANNED_PUBLIC_FIELD_NAMES
    assert not offending, f"advice-shaped field names in a public payload: {sorted(offending)}"


def test_unknown_series_is_a_404_from_the_public_vocabulary(client) -> None:
    """`docs/10` 4.7: public errors come from a closed vocabulary, with a request id."""
    response = client.get("/v1/public/macro/series/NOT_A_SERIES/observations")
    assert response.status_code == 404
    body = response.json()
    assert body["detail"] == "not_found"
    assert body["request_id"]


def test_observations_carry_both_dates(client, gdp_vintages) -> None:
    """as_of_date and known_as_of are different facts and both must survive to the client."""
    body = client.get("/v1/public/macro/series/NG_GDP_GROWTH_YOY/observations").json()
    assert body["observations"], "the fixture inserted two vintages"
    point = body["observations"][0]
    assert point["as_of_date"] == "2026-06-30"
    assert point["known_as_of"] == "2026-11-20"  # newest vintage by default
    assert point["value"] == "3.4"


@pytest.mark.invariant
def test_as_known_on_hides_later_vintages_through_the_api(client, gdp_vintages) -> None:
    """The point-in-time guarantee, end to end through a query string.

    SPEC 4.1: features respect `known_as_of`. A caller asking what was known in September
    must get 3.1 — the number the market actually had — not today's corrected 3.4.
    """
    body = client.get(
        "/v1/public/macro/series/NG_GDP_GROWTH_YOY/observations",
        params={"as_known_on": "2026-09-15"},
    ).json()
    assert body["as_known_on"] == "2026-09-15"
    assert [p["value"] for p in body["observations"]] == ["3.1"]
    assert [p["known_as_of"] for p in body["observations"]] == ["2026-08-25"]


def test_as_known_on_before_publication_returns_nothing(client, gdp_vintages) -> None:
    """Before publication the figure did not exist. Not zero, and not the later value."""
    body = client.get(
        "/v1/public/macro/series/NG_GDP_GROWTH_YOY/observations",
        params={"as_known_on": "2026-07-01"},
    ).json()
    assert body["observations"] == []


def test_period_window_filters(client, gdp_vintages) -> None:
    body = client.get(
        "/v1/public/macro/series/NG_GDP_GROWTH_YOY/observations",
        params={"start": "2027-01-01"},
    ).json()
    assert body["observations"] == []


def test_a_series_with_no_data_reports_null_not_false(client) -> None:
    """`is_stale` is three-state at the surface too — null means "cannot judge"."""
    body = client.get("/v1/public/macro/series").json()
    empty = [s for s in body["series"] if s["observation_count"] == 0]
    assert empty, "at least one seeded series has no observations yet"
    for series in empty:
        assert series["is_stale"] is None
        assert series["latest_as_of"] is None


def test_observations_are_limited_and_say_so(client, gdp_vintages) -> None:
    """An unbounded endpoint is unbounded work. The cap is enforced by the route."""
    body = client.get(
        "/v1/public/macro/series/NG_GDP_GROWTH_YOY/observations", params={"limit": 1}
    ).json()
    assert body["total_available"] >= 1
    assert "truncated" in body
    assert len(body["observations"]) <= 1


def test_limit_above_the_cap_is_refused(client) -> None:
    """The ceiling is the route's to enforce, not the caller's to respect."""
    response = client.get(
        "/v1/public/macro/series/NG_GDP_GROWTH_YOY/observations", params={"limit": 10_000_000}
    )
    assert response.status_code == 422


def test_limit_of_zero_is_refused(client) -> None:
    response = client.get(
        "/v1/public/macro/series/NG_GDP_GROWTH_YOY/observations", params={"limit": 0}
    )
    assert response.status_code == 422

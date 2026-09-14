"""P1 checkpoint 13, in code: degrade, never crash, when the database is gone.

`docs/03` P1 check 13 says *"unplug the internet and reload the dashboard. It should render
stored data with stale flags, not crash."* ADR-0008 changed what that can mean: the database
is Neon, so losing the internet loses the data, not just the sources. The half of the check
that survives that decision is the half that matters for a reader at 2am — nothing crashes,
nothing leaks, and the screen says what is wrong — and it is proven here rather than by
pulling a cable:

* `/health` answers 503 and says the database is the problem;
* the public series endpoint answers a JSON error body, not a traceback, and the body does
  not carry the connection string (a driver's error text routinely does);
* the dashboard renders an error banner naming the API and how to start it, and raises no
  exception of its own.

The engine is pointed at a port nothing listens on, so the failure is immediate and the
tests do not wait on a timeout.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from packages.common import db as common_db

UNREACHABLE_URL = "postgresql+psycopg://nobody:nothing@127.0.0.1:9/quant_unreachable"


@pytest.fixture
def unreachable_database(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Swap the application's engine for one that cannot connect, for one test."""
    engine = create_engine(UNREACHABLE_URL, pool_pre_ping=True, connect_args={"connect_timeout": 2})
    monkeypatch.setattr(common_db, "engine", engine, raising=True)
    monkeypatch.setattr(
        common_db,
        "SessionLocal",
        sessionmaker(bind=engine, autoflush=False, autocommit=False, class_=Session),
        raising=True,
    )
    try:
        yield
    finally:
        engine.dispose()


def test_health_reports_the_database_as_the_problem(client, unreachable_database) -> None:
    response = client.get("/health")
    assert response.status_code == 503
    body = response.json()
    assert body["status"] == "degraded"
    assert body["db"] == "error"


@pytest.mark.invariant
def test_the_series_endpoint_fails_clean_and_leaks_nothing(client, unreachable_database) -> None:
    response = client.get("/v1/public/macro/series")
    assert response.status_code == 500
    body = response.json()
    assert isinstance(body, dict), "a JSON error body, the shape every client already handles"
    assert "Traceback" not in response.text
    assert "nothing@127.0.0.1" not in response.text, "the connection string must not leak"
    assert "quant_unreachable" not in response.text


def test_the_dashboard_shows_a_banner_not_a_stack_trace(monkeypatch: pytest.MonkeyPatch) -> None:
    """The thin client's own branch for an unreachable API, exercised for real."""
    from streamlit.testing.v1 import AppTest

    monkeypatch.setenv("QUANT_API_BASE", "http://127.0.0.1:9")
    repo_root = Path(__file__).resolve().parents[2]
    script = repo_root / "apps" / "streamlit" / "macro_dashboard.py"
    app = AppTest.from_file(str(script), default_timeout=30).run()

    assert not app.exception, "the dashboard must not raise when the API is down"
    banners = [e.value for e in app.error]
    assert any("Cannot reach the API" in text for text in banners), banners
    assert any("uvicorn" in text for text in banners), "it must say how to start the API"


def test_the_operations_report_is_served_anonymously_and_judges_every_job(client) -> None:
    """The operations page's one call. Public data - it carries no figure, only which jobs
    ran - and it lists every job the schedule expects, so absence is visible."""
    from packages.scheduler.jobs import expected_schedule

    response = client.get("/v1/public/operations/connectors", params={"window_days": 7})
    assert response.status_code == 200
    body = response.json()
    assert body["window_days"] == 7
    names = {j["name"] for j in body["jobs"]}
    assert set(expected_schedule()) <= names, "every expected job is on the report"
    levels = {j["level"] for j in body["jobs"]}
    assert levels <= {"ok", "warning", "error", "never_ran"}
    assert body["ok"] + body["warning"] + body["error"] + body["never_ran"] == len(body["jobs"])
    assert body["needs_a_human"] == any(j["level"] != "ok" for j in body["jobs"])
    for job in body["jobs"]:
        if job["scheduled_at_utc"] is not None:
            assert len(job["scheduled_at_utc"]) == 5, "HH:MM"


def test_the_operations_page_shows_a_banner_not_a_stack_trace(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from streamlit.testing.v1 import AppTest

    monkeypatch.setenv("QUANT_API_BASE", "http://127.0.0.1:9")
    script = Path(__file__).resolve().parents[2] / "apps" / "streamlit" / "operations_page.py"
    source = script.read_text(encoding="utf-8")
    for forbidden in ("sqlalchemy", "psycopg", "from packages", "import packages", "SELECT "):
        assert forbidden not in source, f"the page must not contain {forbidden!r}"
    app = AppTest.from_file(str(script), default_timeout=30).run()
    assert not app.exception
    banners = [e.value for e in app.error]
    assert any("Cannot reach the API" in text for text in banners), banners

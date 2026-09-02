"""Mechanism 5 - one ``audit_log`` row per request, including the ones that failed.

``docs/03`` P0's check 16 is *"read the audit log yourself... If a request is
missing, the audit middleware is not on every route - find out which route escaped,
because that route will one day carry something that matters."* These tests are
that check, run automatically, on the routes that exist today.

Every assertion here is keyed on the ``X-Request-Id`` header the audit middleware
attaches, so a test never accidentally reads another test's row.
"""

from __future__ import annotations

import pytest

from packages.compliance.auth import ANONYMOUS
from services.api.middleware import audit as audit_module

PUBLIC_PING = "/v1/public/ping"
PERSONAL_PING = "/v1/personal/ping"


def _row(response, audit_rows):
    request_id = response.headers.get("x-request-id")
    assert request_id, "no X-Request-Id header; the audit middleware did not see this response"
    rows = audit_rows(request_id)
    assert len(rows) == 1, f"expected exactly one audit row, found {len(rows)}"
    return rows[0]._mapping


@pytest.mark.invariant
def test_anonymous_public_request_is_audited(client, audit_rows) -> None:
    response = client.get(PUBLIC_PING)
    row = _row(response, audit_rows)
    assert row["principal"] == ANONYMOUS
    assert row["mode"] == "public"
    assert row["method"] == "GET"
    assert row["endpoint"] == PUBLIC_PING
    assert row["http_status"] == 200
    assert row["response_type"] == "PublicPing"
    assert row["latency_ms"] is not None and row["latency_ms"] >= 0
    assert row["error"] is None


@pytest.mark.invariant
def test_entitled_request_is_audited_with_the_principal_and_personal_mode(
    client, audit_rows, owner
) -> None:
    response = client.get(PERSONAL_PING, headers=owner.auth)
    assert response.status_code == 200
    row = _row(response, audit_rows)
    assert row["principal"] == owner.external_id
    assert row["mode"] == "personal"
    assert row["response_type"] == "PersonalPing"
    assert row["http_status"] == 200


@pytest.mark.invariant
def test_a_refused_request_is_audited(client, audit_rows, guest) -> None:
    """A 403 is the most interesting row in the table, not the least."""
    response = client.get(PERSONAL_PING, headers=guest.auth)
    assert response.status_code == 403
    row = _row(response, audit_rows)
    assert row["principal"] == guest.external_id
    assert row["mode"] == "public"
    assert row["http_status"] == 403
    assert row["response_type"] is None
    assert row["error"] == "http_403"


@pytest.mark.invariant
def test_an_anonymous_refusal_is_audited(client, audit_rows) -> None:
    response = client.get(PERSONAL_PING)
    assert response.status_code == 403
    row = _row(response, audit_rows)
    assert row["principal"] == ANONYMOUS
    assert row["mode"] == "public"
    assert row["http_status"] == 403


@pytest.mark.invariant
def test_an_unmatched_route_is_audited(client, audit_rows) -> None:
    """A 404 on a path that does not exist yet is somebody probing."""
    response = client.get("/v1/personal/signals")
    assert response.status_code == 404
    row = _row(response, audit_rows)
    assert row["endpoint"] == "/v1/personal/signals"
    assert row["http_status"] == 404
    assert row["mode"] == "public"


@pytest.mark.invariant
def test_an_expired_token_is_audited_as_anonymous(client, audit_rows, make_actor) -> None:
    from datetime import timedelta

    actor = make_actor(kind="owner", personal_tier=True, expires_in=timedelta(seconds=-1))
    response = client.get(PERSONAL_PING, headers=actor.auth)
    assert response.status_code == 403
    row = _row(response, audit_rows)
    assert row["principal"] == ANONYMOUS
    assert row["mode"] == "public"


@pytest.mark.invariant
def test_a_fail_closed_request_records_why(client, audit_rows, owner, monkeypatch) -> None:
    """A fail-closed 403 that looks like an ordinary one is one nobody investigates."""
    from services.api.middleware import mode as mode_middleware

    def explode(*_args, **_kwargs):
        raise RuntimeError("connection refused")

    monkeypatch.setattr(mode_middleware, "resolve_principal", explode)
    response = client.get(PERSONAL_PING, headers=owner.auth)
    assert response.status_code == 403
    row = _row(response, audit_rows)
    assert row["principal"] == ANONYMOUS
    assert row["mode"] == "public"
    assert row["error"] is not None
    assert "principal_resolution_failed" in row["error"]


@pytest.mark.invariant
def test_health_is_audited_too(client, audit_rows) -> None:
    response = client.get("/health")
    row = _row(response, audit_rows)
    assert row["endpoint"] == "/health"
    assert row["response_type"] == "Health"


@pytest.mark.invariant
def test_the_query_string_is_not_stored(client, audit_rows) -> None:
    """`docs/10` 4.7 keeps caller-supplied values out of logs. The attempt is still recorded."""
    response = client.get(PUBLIC_PING, params={"mode": "personal", "secret": "hunter2"})
    row = _row(response, audit_rows)
    assert row["endpoint"] == PUBLIC_PING
    assert "hunter2" not in str(dict(row))


@pytest.mark.invariant
def test_an_audit_write_failure_is_loud_but_does_not_swallow_the_response(
    client, monkeypatch
) -> None:
    """Refusing to serve because the ledger is down turns bookkeeping into an outage.

    Serving silently means the row is missing and nobody knows. So: serve, and
    count it.
    """
    before = sum(audit_module.AUDIT_WRITE_FAILURES.values())

    class _Boom:
        def __enter__(self):
            raise RuntimeError("audit database unreachable")

        def __exit__(self, *_exc):
            return False

    monkeypatch.setattr(audit_module.db, "get_session", lambda: _Boom())
    response = client.get(PUBLIC_PING)

    assert response.status_code == 200
    assert response.json()["mode"] == "public"
    after = sum(audit_module.AUDIT_WRITE_FAILURES.values())
    assert after == before + 1, "an audit write failure must be counted, not swallowed silently"


@pytest.mark.invariant
def test_request_ids_are_unique_per_request(client) -> None:
    ids = {client.get(PUBLIC_PING).headers["x-request-id"] for _ in range(5)}
    assert len(ids) == 5


@pytest.mark.invariant
def test_the_request_id_is_server_generated_not_client_supplied(client, audit_rows) -> None:
    """A caller-chosen request id would let them collide with, or forge, a row."""
    forged = "00000000-0000-4000-8000-000000000000"
    response = client.get(PUBLIC_PING, headers={"X-Request-Id": forged})
    assert response.headers["x-request-id"] != forged
    row = _row(response, audit_rows)
    assert str(row["request_id"]) != forged

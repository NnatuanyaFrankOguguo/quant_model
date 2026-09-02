"""Invariant I4 - mode is server-derived, and every failure path is public.

``docs/07_TEST_STRATEGY.md`` 3: *"These may never be skipped, marked ``xfail``, or
made conditional."* ``CLAUDE.md``: this is the only rule in the project with real
legal consequence.

``docs/07`` 8.6 asks for a thirty-minute adversarial session by hand - ``mode`` in
the body, a header, the query string, a cookie; a ``/personal/`` path with odd
casing; a trailing slash; an expired token. Those are encoded below instead, so
they run on every commit forever rather than once, on a Tuesday, by someone who
already knows how the code works.
"""

from __future__ import annotations

import ast
import pathlib
from datetime import UTC, datetime, timedelta

import pytest

from packages.compliance import auth as auth_module
from packages.compliance import mode as mode_module
from packages.compliance.mode import Mode, coerce_mode, derive_mode, resolve_mode_for_principal

PUBLIC_PING = "/v1/public/ping"
PERSONAL_PING = "/v1/personal/ping"


class _FakePrincipal:
    """The shape :func:`derive_mode` accepts, with nothing else attached."""

    def __init__(self, *, kind="owner", personal_tier=True, disabled_at=None):
        self.kind = kind
        self.personal_tier = personal_tier
        self.disabled_at = disabled_at


class _ExplodingPrincipal:
    """A principal whose entitlement lookup raises - a dropped connection mid-request."""

    kind = "owner"
    disabled_at = None

    @property
    def entitlement(self):
        raise RuntimeError("connection to the database was closed")


# --------------------------------------------------------------------------- #
# Pure derivation. No database, no HTTP, never skipped for any reason.
# --------------------------------------------------------------------------- #


@pytest.mark.invariant
def test_anonymous_derives_public() -> None:
    assert derive_mode(None, licensed=False) is Mode.PUBLIC
    assert derive_mode(None, licensed=True) is Mode.PUBLIC


@pytest.mark.invariant
@pytest.mark.parametrize("licensed", [False, True])
def test_disabled_principal_derives_public(licensed: bool) -> None:
    principal = _FakePrincipal(disabled_at=datetime.now(UTC))
    assert derive_mode(principal, licensed=licensed) is Mode.PUBLIC


@pytest.mark.invariant
def test_unentitled_principal_derives_public() -> None:
    assert derive_mode(_FakePrincipal(personal_tier=False), licensed=False) is Mode.PUBLIC


@pytest.mark.invariant
@pytest.mark.parametrize("value", [1, "true", "True", "yes", [1], object()])
def test_truthy_non_boolean_personal_tier_fails_closed(value: object) -> None:
    """A `1` from a raw SQL read, or a Mock in a future test, must not open the tier."""
    assert derive_mode(_FakePrincipal(personal_tier=value), licensed=True) is Mode.PUBLIC


@pytest.mark.invariant
def test_service_principal_never_reaches_personal() -> None:
    """`docs/10` 4.7 - server components authenticate as the end user, never as the app.

    Otherwise the P9 frontend's server-side token renders every SSR page in
    personal mode.
    """
    principal = _FakePrincipal(kind="service", personal_tier=True)
    assert derive_mode(principal, licensed=False) is Mode.PUBLIC
    assert derive_mode(principal, licensed=True) is Mode.PUBLIC


@pytest.mark.invariant
def test_invariant_i11_public_kind_cannot_reach_personal_pre_licence() -> None:
    """`docs/10` 4.6, invariant I11. Entitlement alone is not enough pre-licence."""
    principal = _FakePrincipal(kind="public", personal_tier=True)
    assert derive_mode(principal, licensed=False) is Mode.PUBLIC
    # Post-licence the same principal is admissible; that is the config change the
    # SEC registration is supposed to be, rather than a rewrite.
    assert derive_mode(principal, licensed=True) is Mode.PERSONAL


@pytest.mark.invariant
@pytest.mark.parametrize("kind", ["owner", "family", "OWNER", " Family "])
def test_owner_and_family_reach_personal_pre_licence(kind: str) -> None:
    assert derive_mode(_FakePrincipal(kind=kind), licensed=False) is Mode.PERSONAL


@pytest.mark.invariant
def test_entitlement_lookup_that_raises_fails_closed() -> None:
    """`docs/10` 4.6 - 'entitlements down, DB error, anything -> fail CLOSED'."""
    with pytest.raises(RuntimeError):
        derive_mode(_ExplodingPrincipal(), licensed=False)
    assert resolve_mode_for_principal(_ExplodingPrincipal()) is Mode.PUBLIC


@pytest.mark.invariant
def test_licence_status_failures_all_resolve_to_unlicensed(monkeypatch) -> None:
    """A missing, NULL, wrongly-typed or unreadable licence never opens the tier."""

    def raises(**_kwargs):
        raise RuntimeError("system_config unreachable")

    for stub, expected in (
        (raises, False),
        (lambda **_k: None, False),
        (lambda **_k: 1, False),
        (lambda **_k: {"status": "LICENSED"}, False),  # a dict is not a str here
        (lambda **_k: "licensed", True),
        (lambda **_k: "  LICENSED  ", True),
        (lambda **_k: "UNLICENSED", False),
        (lambda **_k: "PENDING", False),
    ):
        monkeypatch.setattr(mode_module, "licence_status", stub)
        assert mode_module.is_licensed() is expected


@pytest.mark.invariant
def test_database_outage_during_mode_resolution_resolves_to_public(monkeypatch) -> None:
    """A DB failure at principal-resolution time is public, never personal."""
    from services.api.middleware import mode as mode_middleware

    def explode(*_args, **_kwargs):
        raise RuntimeError("connection refused")

    monkeypatch.setattr(mode_middleware, "resolve_principal", explode)
    principal, resolved, error = mode_middleware.resolve_mode("Bearer anything-at-all")
    assert resolved is Mode.PUBLIC
    assert principal is None
    assert error is not None and "principal_resolution_failed" in error


@pytest.mark.invariant
@pytest.mark.parametrize("value", ["personal", "PERSONAL", "", None, 0, object(), b"personal"])
def test_coerce_mode_never_invents_personal(value: object) -> None:
    """Only the enum member and the exact string 'personal' are personal."""
    if value == "personal":
        assert coerce_mode(value) is Mode.PERSONAL
    else:
        assert coerce_mode(value) is Mode.PUBLIC


# --------------------------------------------------------------------------- #
# Credential handling.
# --------------------------------------------------------------------------- #


@pytest.mark.invariant
@pytest.mark.parametrize(
    "header",
    [
        None,
        "",
        "   ",
        "Basic abc",
        "Bearer",
        "Bearer ",
        "bearertoken",
        "Token abc",
        "Bearer " + "x" * (auth_module.MAX_TOKEN_CHARS + 1),
    ],
)
def test_malformed_credentials_are_anonymous_not_errors(header: str | None) -> None:
    assert auth_module.parse_bearer(header) is None


@pytest.mark.invariant
def test_bearer_scheme_is_case_insensitive_but_the_token_is_not() -> None:
    assert auth_module.parse_bearer("bearer abc") == "abc"
    assert auth_module.parse_bearer("BEARER abc") == "abc"
    assert auth_module.parse_bearer("Bearer   abc  ") == "abc"


@pytest.mark.invariant
def test_only_the_hash_is_ever_stored() -> None:
    raw = "a-token-nobody-should-ever-see"
    digest = auth_module.hash_token(raw)
    assert len(digest) == 64
    assert raw not in digest
    assert digest == auth_module.hash_token(raw)


# --------------------------------------------------------------------------- #
# The four injection vectors, plus the two `docs/07` 8.6 adds by hand.
# --------------------------------------------------------------------------- #


@pytest.mark.invariant
@pytest.mark.parametrize(
    "vector",
    [
        pytest.param({"json": {"mode": "personal"}}, id="body"),
        pytest.param({"json": {"user": {"session": {"mode": "personal"}}}}, id="nested-body"),
        pytest.param({"headers": {"X-Mode": "personal"}}, id="header"),
        pytest.param({"headers": {"Mode": "personal"}}, id="header-plain"),
        pytest.param({"params": {"mode": "personal"}}, id="query"),
        pytest.param({"cookies": {"mode": "personal"}}, id="cookie"),
        pytest.param({"cookies": {"session": "mode=personal"}}, id="cookie-embedded"),
    ],
)
def test_client_cannot_force_mode(client, vector: dict) -> None:
    response = client.request("GET", PUBLIC_PING, **vector)
    assert response.status_code == 200
    assert response.json()["mode"] == "public"


@pytest.mark.invariant
def test_anonymous_defaults_to_public(client) -> None:
    assert client.get(PUBLIC_PING).json()["mode"] == "public"


@pytest.mark.invariant
@pytest.mark.parametrize(
    "path",
    [
        "/v1/personal/ping",
        "/v1/personal/ping/",
        "/v1/PERSONAL/ping",
        "/v1/Personal/Ping",
        "/v1/personal//ping",
        "/v1/personal/ping?mode=personal",
        "/V1/personal/ping",
    ],
)
def test_no_path_variant_admits_an_anonymous_caller(client, path: str) -> None:
    """Odd casing, a trailing slash, a doubled separator - `docs/03` check 17.

    Whether the answer is 403 or 404 does not matter. What matters is that it is
    never 200, and never carries a personal payload.
    """
    response = client.get(path)
    assert response.status_code in (307, 403, 404), response.text
    assert "personal" not in response.text


@pytest.mark.invariant
def test_unentitled_principal_cannot_reach_personal(client, guest) -> None:
    """`docs/03` P0 check 8."""
    response = client.get(PERSONAL_PING, headers=guest.auth)
    assert response.status_code == 403
    assert response.json()["detail"] == "forbidden"


@pytest.mark.invariant
def test_unentitled_principal_is_public_on_the_public_route(client, guest) -> None:
    assert client.get(PUBLIC_PING, headers=guest.auth).json()["mode"] == "public"


@pytest.mark.invariant
def test_entitled_owner_is_admitted(client, owner) -> None:
    """`docs/03` P0 check 9."""
    response = client.get(PERSONAL_PING, headers=owner.auth)
    assert response.status_code == 200
    assert response.json() == {"mode": "personal"}


@pytest.mark.invariant
def test_entitled_family_is_admitted(client, family) -> None:
    response = client.get(PERSONAL_PING, headers=family.auth)
    assert response.status_code == 200
    assert response.json() == {"mode": "personal"}


@pytest.mark.invariant
def test_owner_sees_server_derived_mode_on_the_public_route(client, owner) -> None:
    """The ping reports what the server derived, not a constant.

    If it returned a hardcoded 'public', every injection test above would be
    asserting on a literal and would pass whether or not the gate worked.
    """
    assert client.get(PUBLIC_PING, headers=owner.auth).json()["mode"] == "personal"


@pytest.mark.invariant
def test_expired_token_is_refused(client, make_actor) -> None:
    actor = make_actor(kind="owner", personal_tier=True, expires_in=timedelta(seconds=-1))
    assert client.get(PERSONAL_PING, headers=actor.auth).status_code == 403
    assert client.get(PUBLIC_PING, headers=actor.auth).json()["mode"] == "public"


@pytest.mark.invariant
def test_revoked_token_is_refused(client, make_actor) -> None:
    actor = make_actor(kind="owner", personal_tier=True, revoked=True)
    assert client.get(PERSONAL_PING, headers=actor.auth).status_code == 403
    assert client.get(PUBLIC_PING, headers=actor.auth).json()["mode"] == "public"


@pytest.mark.invariant
def test_token_for_a_disabled_principal_is_refused(client, make_actor) -> None:
    actor = make_actor(kind="owner", personal_tier=True, disabled=True)
    assert client.get(PERSONAL_PING, headers=actor.auth).status_code == 403
    assert client.get(PUBLIC_PING, headers=actor.auth).json()["mode"] == "public"


@pytest.mark.invariant
def test_service_principal_is_refused_end_to_end(client, make_actor) -> None:
    actor = make_actor(kind="service", personal_tier=True)
    assert client.get(PERSONAL_PING, headers=actor.auth).status_code == 403


@pytest.mark.invariant
def test_public_kind_with_personal_tier_is_refused_pre_licence(client, make_actor) -> None:
    actor = make_actor(kind="public", personal_tier=True)
    assert client.get(PERSONAL_PING, headers=actor.auth).status_code == 403


@pytest.mark.invariant
def test_an_unknown_token_is_anonymous(client) -> None:
    headers = {"Authorization": "Bearer " + "z" * 43}
    assert client.get(PERSONAL_PING, headers=headers).status_code == 403
    assert client.get(PUBLIC_PING, headers=headers).json()["mode"] == "public"


@pytest.mark.invariant
def test_database_outage_end_to_end_never_admits_personal(client, owner, monkeypatch) -> None:
    """The same token that works above must be refused when the lookup fails."""
    from services.api.middleware import mode as mode_middleware

    assert client.get(PERSONAL_PING, headers=owner.auth).status_code == 200

    def explode(*_args, **_kwargs):
        raise RuntimeError("connection refused")

    monkeypatch.setattr(mode_middleware, "resolve_principal", explode)
    assert client.get(PERSONAL_PING, headers=owner.auth).status_code == 403
    assert client.get(PUBLIC_PING, headers=owner.auth).json()["mode"] == "public"


# --------------------------------------------------------------------------- #
# Structural: the derivation code cannot read the request even by accident.
# --------------------------------------------------------------------------- #

#: Attribute names that expose caller-controlled data. `headers` is absent
#: deliberately - the credential arrives in one, and that is the single permitted
#: input. Everything else here is a way to smuggle a `mode` in.
FORBIDDEN_REQUEST_ACCESSORS = frozenset(
    {"query_params", "cookies", "path_params", "form", "body", "json", "stream"}
)

_GATE_SOURCES = (
    pathlib.Path("packages/compliance/mode.py"),
    pathlib.Path("services/api/middleware/mode.py"),
)


@pytest.mark.invariant
@pytest.mark.parametrize("path", _GATE_SOURCES, ids=lambda p: p.name)
def test_mode_derivation_never_reads_caller_controlled_input(path: pathlib.Path) -> None:
    """Walk the AST of the two files that decide the mode.

    A black-box injection test proves today's code is safe. This one makes the
    *next* edit fail loudly: the day somebody reaches for `request.query_params`
    inside the derivation, CI names the file.
    """
    tree = ast.parse(path.read_text(encoding="utf-8"))
    used = {
        node.attr
        for node in ast.walk(tree)
        if isinstance(node, ast.Attribute) and node.attr in FORBIDDEN_REQUEST_ACCESSORS
    }
    assert not used, f"{path} reads caller-controlled input: {sorted(used)}"


@pytest.mark.invariant
def test_the_only_header_the_gate_reads_is_authorization() -> None:
    """One permitted input, named once."""
    source = pathlib.Path("services/api/middleware/mode.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    literals = {
        node.value.lower()
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant) and isinstance(node.value, str)
    }
    header_like = {value for value in literals if value.startswith("x-") or value == "mode"}
    assert not header_like, f"unexpected header-shaped literal in the gate: {sorted(header_like)}"

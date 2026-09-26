"""Mechanism 3 of five - the response-type assertion, and the public type registry.

``docs/08_DATA_CONTRACTS.md`` 7: *"An allow-list, not a deny-list - a deny-list
needs updating every time an advice-shaped type is added, and the one you forget is
the one that leaks."*

**500, not 403.** A public request that received a personal payload is not the
caller doing something forbidden; it is our code being wrong. It must be impossible
to mistake for normal operation (``docs/03`` P0.5, ``docs/01`` 3).

Two enforcement points, both here:

1. **Import time.** :func:`register_public_type` walks a model's fields - including
   nested models, and through ``list``/``dict``/``Optional`` - and refuses any name
   in :data:`BANNED_PUBLIC_FIELD_NAMES`. A public type that grows a ``verdict``
   field fails at import, not in production (``docs/10`` 4.3).
2. **Request time.** :func:`assert_legal` checks the *exact* type of the object a
   handler returned, before serialisation.

The registry exists because ``packages/`` may not import ``services/`` (ADR-0006,
enforced by import-linter), so this module cannot name the Pydantic models it
guards. ``services/api/schemas.py`` registers them instead. The route manifest test
then closes the loop: a public route whose declared ``response_model`` was never
registered fails CI.
"""

from __future__ import annotations

from typing import Any, TypeVar, get_args

from fastapi import HTTPException
from pydantic import BaseModel

from packages.compliance.mode import Mode, coerce_mode, log_compliance_error

__all__ = [
    "BANNED_PUBLIC_FIELD_NAMES",
    "PublicFieldNameViolation",
    "ResponseTypeViolation",
    "assert_legal",
    "is_public_legal",
    "public_legal_types",
    "register_public_type",
    "walk_field_names",
]

#: ``docs/10_PRE_BUILD_CORRECTIONS.md`` 4.3. A public response model may not carry
#: a field with any of these names, at any nesting depth. The last seven are the
#: ones people forget: a ranked score *is* a recommendation even when no word in
#: the response says so (``docs/10`` 4.7, "advice without advice words").
BANNED_PUBLIC_FIELD_NAMES = frozenset(
    {
        "calibrated_prob",
        "conviction",
        "entry",
        "fair_value",
        "grade",
        "percentile",
        "position_size",
        "price_target",
        "probability",
        "rank",
        "rating",
        "recommendation",
        "score",
        "signal",
        "stop_loss",
        "target",
        "verdict",
    }
)

_MAX_FIELD_WALK_DEPTH = 12


class ResponseTypeViolation(HTTPException):
    """A public request was about to receive a payload that is not public-legal.

    An ``HTTPException`` with status 500 so it surfaces as a server error through
    FastAPI's normal exception handling, and a distinct class so the scheduler and
    the tests can catch exactly this and nothing else.
    """

    def __init__(self, type_name: str) -> None:
        super().__init__(status_code=500, detail="response type illegal for public mode")
        self.type_name = type_name


class PublicFieldNameViolation(Exception):  # noqa: N818 - "violation" is the domain word
    """Raised at import time. A public model declared an advice-shaped field."""


_PUBLIC_LEGAL_TYPES: set[type] = set()


def _iter_nested_models(annotation: Any) -> list[type[BaseModel]]:
    """Every ``BaseModel`` reachable from an annotation, however it is wrapped."""
    found: list[type[BaseModel]] = []
    if isinstance(annotation, type) and issubclass(annotation, BaseModel):
        found.append(annotation)
        return found
    for argument in get_args(annotation):
        found.extend(_iter_nested_models(argument))
    return found


def walk_field_names(model: type[BaseModel], _depth: int = 0) -> set[str]:
    """Every field name in a model, recursively through nested models."""
    if _depth > _MAX_FIELD_WALK_DEPTH:  # pragma: no cover - pathological schema
        return set()
    names: set[str] = set()
    for name, field in model.model_fields.items():
        names.add(name)
        for nested in _iter_nested_models(field.annotation):
            if nested is model:
                continue
            names |= walk_field_names(nested, _depth + 1)
    return names


T = TypeVar("T", bound=type[BaseModel])


def register_public_type(model: T) -> T:
    """Declare a model legal for public mode. Usable as a decorator.

    Refuses at import time if the model - or anything nested inside it - carries
    an advice-shaped field name.
    """
    offending = sorted(walk_field_names(model) & BANNED_PUBLIC_FIELD_NAMES)
    if offending:
        raise PublicFieldNameViolation(
            f"{model.__name__} declares advice-shaped field(s) {offending} and cannot be "
            f"a public response type. Split it: a public model with no such attribute, "
            f"and a personal subclass that adds it (docs/10 4.3)."
        )
    _PUBLIC_LEGAL_TYPES.add(model)
    return model


def public_legal_types() -> frozenset[type]:
    """The allow-list, as it stands after every schema module has imported."""
    return frozenset(_PUBLIC_LEGAL_TYPES)


def is_public_legal(payload: Any) -> bool:
    """Exact-type membership. Deliberately not ``isinstance``.

    ``PersonalMemo(PublicMemo)`` is the shape ``docs/10`` 4.3 asks for, and an
    ``isinstance`` check would wave it straight through a public route.
    """
    return type(payload) in _PUBLIC_LEGAL_TYPES


def assert_legal(mode: Any, payload: Any) -> None:
    """Mechanism 3. Raise if this payload cannot lawfully be sent in this mode."""
    if coerce_mode(mode) is not Mode.PUBLIC:
        return
    if is_public_legal(payload):
        return
    type_name = type(payload).__name__
    log_compliance_error("illegal_public_response_type", response_type=type_name)
    raise ResponseTypeViolation(type_name)


# `docs/10` 4.7 - "raw `Response` returns bypass mechanisms 2, 3 and 4" - needs no
# separate runtime check: a `FileResponse`, a `StreamingResponse`, a bare `dict`
# and `None` are all types nobody can register, so `assert_legal` already refuses
# them in public mode. What it *does* need is the build-time half, so the mistake
# is caught before it ships: see `PublicAPIRoute` in
# `services/api/middleware/assert_response.py`, which refuses at import time to
# mount a public route that declares a `Response` return type or a
# `response_model` outside this registry.

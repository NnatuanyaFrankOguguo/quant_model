"""An HTTP error that may name the request fields at fault. `docs/10` §4.7.

The error vocabulary is closed on purpose: *"a traceback, a field value, or the repr of a
local variable must never reach a response body: that is how a `PersonalMemo(verdict=...)`
leaves the building through a 500 rather than through a route."* So `HTTPException(detail=...)`
never reaches the caller — `services/api/main.py` replaces the detail with one of nine fixed
words, and a 422 becomes `invalid_request` however carefully the route worded it.

That is right, and it left P3.2's entry form unusable. An operator typing forty figures off a
page and getting back `invalid_request` has no way to find which one was refused, and the
next thing they do is stop reading the error.

`ErrorBody` already carries the answer: a `fields` list, *"names of the request fields that
failed validation. Never their values."* FastAPI's own `RequestValidationError` handler
populates it. This exception lets a route do the same, so a refusal can say
`fields: ["figures.3.page"]` while still saying only `invalid_request` about what was wrong.

A canonical key is a field name, not a value — `revenue` is the name of the input, and the
number the operator typed into it never appears. That distinction is the whole reason this is
allowed to exist.
"""

from __future__ import annotations

from typing import Any

from fastapi import HTTPException

__all__ = ["FieldedHTTPException"]


class FieldedHTTPException(HTTPException):
    """`HTTPException` plus the field names at fault. `detail` is still discarded."""

    def __init__(
        self,
        status_code: int,
        *,
        fields: list[str] | None = None,
        detail: Any = None,
    ) -> None:
        super().__init__(status_code=status_code, detail=detail)
        #: Read by the handler in `main.py`. Names only; a value here would be a leak.
        self.fields = fields or None

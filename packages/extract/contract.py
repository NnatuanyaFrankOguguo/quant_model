"""Checking an extraction against the page it claims to come from. P4.2.

`docs/03` P4.2 specifies the system prompt and then tabulates what each of its constraints
prevents. Two of them are the reason this module exists:

    "never infer/estimate/fill gaps"  ->  The single most dangerous LLM behaviour here - a
                                          plausible fabricated number.
    "verbatim label as printed"       ->  Lets a human verify the mapping without reopening
                                          the PDF.

A prompt is not enforcement. It asks a model not to fabricate, and a model that fabricates
anyway returns something perfectly well-formed: a real-looking figure, a plausible label, a
page number in range, a confidence of 0.95. Every schema check passes. `P4.3`'s arithmetic
identities catch some of it - a fabricated figure that breaks `assets = liabilities +
equity` is caught - but a fabricated *revenue* breaks no identity at all, and the review
queue prioritises by materiality, so the biggest invented numbers are seen and the rest are
not.

## Grounding

The one check that does not depend on a fabricated number being inconvenient: **the label
and the digits have to be on the page the extraction cites.** We have that page's text.
The model does not know we are going to look.

It is not a proof of correctness. A model can cite a real label on the right page and
attach the wrong figure from two rows down, and grounding passes. What it does catch is
invention - a number that appears nowhere in the document - which is the failure `docs/03`
calls *"the single most dangerous"*, and it catches it deterministically, offline, before
anything is stored.

## `value` is what is printed, not what it means

This is the one place `docs/03` P4.2 is ambiguous and the ambiguity is expensive, so it is
resolved here explicitly rather than guessed at silently.

The prompt says *"Report values in the reporting currency/units exactly as stated, plus a
`unit_multiplier`."* The abridged example beside it shows `unit_multiplier: 1000` with
`value: 3360000000000`, which is ₦3.36 trillion in full naira - already multiplied, not
"as stated".

This module takes the instruction, not the example: **`value` is the number printed on the
page** and the figure in naira is `value * unit_multiplier`. Two reasons, and the second is
the deciding one:

1. It is what the prompt actually tells the model to do, so it is what a model following
   the prompt will produce.
2. A pre-multiplied value cannot be grounded. `3360000000000` appears nowhere on a page
   that prints `3,360,000`, so the strongest check available would have to be switched off
   for every statement not reported in units.

`grounding_findings` reports a `VALUE_NOT_ON_PAGE` when a figure cannot be found, and a
statement whose every figure is off by exactly the multiplier is the signature of a model
that followed the example instead. That is a visible, diagnosable failure rather than a
silent thousand-fold error, which is the outcome TG2 and `OPERATIONS.md` §1.6 are about.
"""

from __future__ import annotations

import datetime as dt
import json
import re
from collections.abc import Mapping
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation

__all__ = [
    "ALLOWED_MULTIPLIERS",
    "LABEL_NOT_ON_PAGE",
    "NO_SUCH_PAGE",
    "VALUE_NOT_ON_PAGE",
    "ContractViolationError",
    "Extraction",
    "Finding",
    "LineItem",
    "grounding_findings",
    "parse_extraction",
]

#: The cited page is not one we read. A fabricated citation, or a page-numbering mismatch
#: between the file and the printed folio - both worth a human, neither worth storing.
NO_SUCH_PAGE = "no_such_page"
#: The verbatim label is not on the page it is claimed from.
LABEL_NOT_ON_PAGE = "label_not_on_page"
#: The digits are not on the page. The fabrication check.
VALUE_NOT_ON_PAGE = "value_not_on_page"

#: What a statement may be reported in. Nigerian and US filings between them use units,
#: thousands, millions and billions; anything else is a misread scale rather than a real
#: one, and `OPERATIONS.md` §1.6 is about what a silent factor of a thousand costs.
ALLOWED_MULTIPLIERS = (1, 1_000, 1_000_000, 1_000_000_000)

#: Characters a printed figure may carry that its digits do not: thousands separators in
#: either convention, currency marks, and the spaces some typesetters use for grouping.
_NOISE = str.maketrans({",": None, " ": None, " ": None, " ": None, "'": None})


class ContractViolationError(ValueError):
    """The response does not have the shape P4.2 specifies, so it is not read further."""


@dataclass(frozen=True)
class LineItem:
    """One figure, with everything needed to check it without reopening the PDF."""

    canonical_key: str
    #: The label exactly as printed. Not a normalisation of it - the point is to be able to
    #: find this string on the page, and a tidied one cannot be found.
    as_printed: str
    #: The number printed on the page. `None` means the line was absent, which is a fact.
    #: Zero means the company reported zero, which is a different fact.
    value: Decimal | None
    page: int
    confidence: Decimal


@dataclass(frozen=True)
class Extraction:
    """One statement, from one company, as returned by the reconciler."""

    company: str
    period_end: dt.date
    currency: str
    unit_multiplier: int
    statement: str
    line_items: tuple[LineItem, ...]
    extraction_notes: str | None = None

    def in_reporting_units(self, item: LineItem) -> Decimal | None:
        """`value * unit_multiplier`, or `None` for an absent line.

        The multiplication lives here rather than at the call site because doing it twice,
        or not at all, is the thousands trap and it is easiest to fall into when the
        arithmetic is spread out.
        """
        return None if item.value is None else item.value * self.unit_multiplier


@dataclass(frozen=True)
class Finding:
    """One thing that could not be confirmed against the source."""

    kind: str
    canonical_key: str
    page: int
    detail: str


def parse_extraction(payload: str | Mapping[str, object]) -> Extraction:
    """Read a response into an `Extraction`, or refuse it.

    Shape only - whether the figures are real is `grounding_findings`' question. Every
    refusal names the field, because this runs against model output and "invalid response"
    is not something anybody can act on.
    """
    data = _as_mapping(payload)
    items = data.get("line_items")
    if not isinstance(items, list):
        raise ContractViolationError("`line_items` must be a list, even when it is empty")
    multiplier = _int_field(data, "unit_multiplier")
    if multiplier not in ALLOWED_MULTIPLIERS:
        raise ContractViolationError(
            f"unit_multiplier={multiplier} is not one of {ALLOWED_MULTIPLIERS}. A scale "
            f"nobody reports in is a misread one, and the error is silent and thousandfold."
        )
    return Extraction(
        company=_text_field(data, "company"),
        period_end=_date_field(data, "period_end"),
        currency=_text_field(data, "currency").upper(),
        unit_multiplier=multiplier,
        statement=_text_field(data, "statement"),
        line_items=tuple(_line_item(raw, index) for index, raw in enumerate(items)),
        extraction_notes=_optional_text(data, "extraction_notes"),
    )


def grounding_findings(extraction: Extraction, pages: Mapping[int, str]) -> list[Finding]:
    """Everything in this extraction that is not on the page it says it is.

    `pages` maps a one-based page number to that page's text, as
    `packages.extract.pdf.read_pages` produces it. Pages that were not read are simply
    absent from the mapping, and a citation into one of them is reported rather than
    assumed good - a page we could not read is not a page that confirms anything.

    An absent line (`value is None`) is checked for its label only. There is no figure to
    find, and requiring one would punish the model for the behaviour the prompt asks for.
    """
    findings: list[Finding] = []
    for item in extraction.line_items:
        text = pages.get(item.page)
        if text is None:
            findings.append(
                Finding(
                    kind=NO_SUCH_PAGE,
                    canonical_key=item.canonical_key,
                    page=item.page,
                    detail=(
                        f"page {item.page} was not among the pages read "
                        f"({_describe(sorted(pages))}), so nothing on it can be confirmed"
                    ),
                )
            )
            continue
        haystack = _normalise(text)
        if _normalise(item.as_printed) not in haystack:
            findings.append(
                Finding(
                    kind=LABEL_NOT_ON_PAGE,
                    canonical_key=item.canonical_key,
                    page=item.page,
                    detail=(
                        f"{item.as_printed!r} is not printed on page {item.page}. The "
                        f"label is what lets a reviewer check the mapping without "
                        f"reopening the PDF, so one that is not there is not usable."
                    ),
                )
            )
        if item.value is not None and not _value_on_page(item.value, text):
            findings.append(
                Finding(
                    kind=VALUE_NOT_ON_PAGE,
                    canonical_key=item.canonical_key,
                    page=item.page,
                    detail=(
                        f"{item.value} does not appear on page {item.page}. Either the "
                        f"figure was invented, or it was multiplied by unit_multiplier "
                        f"({extraction.unit_multiplier}) before being reported - `value` "
                        f"is the number as printed."
                    ),
                )
            )
    return findings


# --------------------------------------------------------------------------------------
# Finding a number on a page
# --------------------------------------------------------------------------------------


def _value_on_page(value: Decimal, text: str) -> bool:
    """Whether this exact figure is one of the numbers printed on this page.

    Compared as numbers rather than as text. The first version of this stripped separators
    and searched the result, which confirmed two classes of figure that were never printed:
    a short number found inside a longer one (`336` inside `3360000`), and any number
    formed by two columns running together once the spaces between them were removed
    (`Revenue 3,360,000 2,470,000` yields `0002470`, among hundreds of others).

    A false positive here is the worst failure available to this module, because it reports
    a fabricated figure as confirmed against the source.
    """
    return value in _numbers_on(text)


def _numbers_on(text: str) -> set[Decimal]:
    """Every figure printed on the page, signed.

    A negative may be printed either way a statement prints one: a leading minus, or the
    brackets accounting uses. `(400,440)` and `-400,440` are the same figure and both have
    to compare equal to `-400440`.
    """
    found: set[Decimal] = set()
    for match in _NUMBER.finditer(text):
        digits = match.group("digits").translate(_SEPARATORS)
        try:
            magnitude = Decimal(digits)
        except InvalidOperation:  # pragma: no cover - the pattern cannot produce one
            continue
        negative = bool(match.group("minus")) or bool(match.group("open") and match.group("close"))
        found.add(-magnitude if negative else magnitude)
    return found


#: One printed figure. Groups are separated by commas, apostrophes, or the no-break spaces
#: typesetters use - deliberately **not** the ordinary space, which in a statement is the
#: gap between two columns and not part of either number.
#:
#: The digits are required to group in threes once a separator appears, so `1,23,456` is
#: read as `1` followed by other text rather than as a number nobody printed.
_NUMBER = re.compile(
    r"(?P<open>\()?\s*"
    r"(?P<minus>[-\u2212])?\s*"
    r"(?P<digits>\d{1,3}(?:[,'\u00a0\u202f]\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?)"
    r"\s*(?P<close>\))?"
)

#: Removed from a matched token before it is read as a number. The ordinary space is absent
#: on purpose; see `_NUMBER`.
_SEPARATORS = str.maketrans({",": None, "'": None, "\u00a0": None, "\u202f": None})


def _normalise(text: str) -> str:
    """Case-folded with runs of whitespace collapsed.

    A label wraps across two lines in the PDF and arrives with a newline in the middle of
    it; the model reports it as one line. Neither is wrong and they must compare equal.
    """
    return re.sub(r"\s+", " ", text).strip().casefold()


def _describe(pages: list[int]) -> str:
    if not pages:
        return "none"
    if len(pages) <= 6:
        return ", ".join(str(p) for p in pages)
    return f"{pages[0]}-{pages[-1]}, {len(pages)} pages"


# --------------------------------------------------------------------------------------
# Field reading, with a named refusal for each
# --------------------------------------------------------------------------------------


def _as_mapping(payload: str | Mapping[str, object]) -> Mapping[str, object]:
    if isinstance(payload, Mapping):
        return payload
    try:
        loaded = json.loads(payload)
    except json.JSONDecodeError as exc:
        raise ContractViolationError(f"response is not JSON: {exc}") from exc
    if not isinstance(loaded, Mapping):
        raise ContractViolationError(f"response is a {type(loaded).__name__}, not a JSON object")
    return loaded


def _line_item(raw: object, index: int) -> LineItem:
    if not isinstance(raw, Mapping):
        raise ContractViolationError(
            f"line_items[{index}] is a {type(raw).__name__}, not an object"
        )
    where = f"line_items[{index}]"
    page = _int_field(raw, "page", where=where)
    if page < 1:
        raise ContractViolationError(
            f"{where}.page={page}; pages are one-based, as a reviewer counts them and as "
            f"the provenance column expects"
        )
    confidence = _decimal_field(raw, "confidence", where=where)
    if not 0 <= confidence <= 1:
        raise ContractViolationError(f"{where}.confidence={confidence} is outside 0..1")
    return LineItem(
        canonical_key=_text_field(raw, "canonical_key", where=where),
        as_printed=_text_field(raw, "as_printed", where=where),
        value=_optional_decimal(raw, "value", where=where),
        page=page,
        confidence=confidence,
    )


def _text_field(data: Mapping[str, object], name: str, *, where: str = "response") -> str:
    value = data.get(name)
    if not isinstance(value, str) or not value.strip():
        raise ContractViolationError(f"{where}.{name} must be a non-empty string, got {value!r}")
    return value.strip()


def _optional_text(data: Mapping[str, object], name: str) -> str | None:
    value = data.get(name)
    if value is None:
        return None
    if not isinstance(value, str):
        raise ContractViolationError(f"response.{name} must be a string or null, got {value!r}")
    return value.strip() or None


def _int_field(data: Mapping[str, object], name: str, *, where: str = "response") -> int:
    value = data.get(name)
    # `bool` is an `int` in Python, and `True` would read as 1 - a multiplier of one, or
    # page one, from a field that was never a number.
    if isinstance(value, bool) or not isinstance(value, int):
        raise ContractViolationError(f"{where}.{name} must be an integer, got {value!r}")
    return value


def _decimal_field(data: Mapping[str, object], name: str, *, where: str) -> Decimal:
    value = _optional_decimal(data, name, where=where)
    if value is None:
        raise ContractViolationError(f"{where}.{name} is required and must not be null")
    return value


def _optional_decimal(data: Mapping[str, object], name: str, *, where: str) -> Decimal | None:
    value = data.get(name, _MISSING)
    if value is _MISSING:
        raise ContractViolationError(
            f"{where}.{name} is absent. The prompt asks for null where a line is missing, "
            f"and an absent key is not the same as a reported absence."
        )
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float, str, Decimal)):
        raise ContractViolationError(f"{where}.{name} must be a number or null, got {value!r}")
    try:
        # Through `str` so a JSON float arrives as the figure it was written as rather than
        # as its binary approximation: Decimal(0.1) is 0.1000000000000000055511151231.
        return Decimal(str(value))
    except InvalidOperation as exc:
        raise ContractViolationError(f"{where}.{name}={value!r} is not a number") from exc


def _date_field(data: Mapping[str, object], name: str) -> dt.date:
    value = data.get(name)
    if not isinstance(value, str):
        raise ContractViolationError(f"response.{name} must be an ISO date string, got {value!r}")
    try:
        return dt.date.fromisoformat(value)
    except ValueError as exc:
        raise ContractViolationError(f"response.{name}={value!r} is not an ISO date") from exc


class _Missing:
    """Distinguishes "the key was absent" from "the key was null", which mean different
    things: one is a model that did not answer, the other is a model reporting an absence."""


_MISSING = _Missing()

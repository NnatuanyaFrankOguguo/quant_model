"""The one place a printed figure becomes a stored number. TG2, `OPERATIONS.md` §1.6.

**The bug this module exists to prevent.** Nigerian statements report in thousands or in
millions, *inconsistently, sometimes varying between sections of the same document*
(`docs/01` §7.6 and `docs/06` R-22). The risk is not the `unit_multiplier` column - it is
that the multiplication has no single home. If an extractor stores the numeral as printed,
a ratio engine multiplies, and a chart multiplies again, the result is a silent 1,000x
error. As `docs/03` P3.3 puts it: a figure off by 1,000x is usually obvious; off by 1,000x
on *one line item among forty* is not.

So the multiplication happens **exactly once, here**, and `docs/08` §1.5 states the
downstream half of the rule: `unit_multiplier` is kept "for provenance and audit, **not**
for anyone downstream to multiply by again".

**Why this module is in `common` and not `normalize`.** `docs/06` R-22 weighs three
approaches and recommends "`unit_multiplier` captured at extraction + one conversion
function in `common`". That also puts it beside the other shared accessors that exist to be
the single home for one dangerous operation: `fx.py` for rates, `adjust.py` for split
factors, `pit.py` for point-in-time reads, `identity.py` for tickers.

**A dash is not a zero, and neither is a blank.** `docs/08` §1.4's null-rule table is
explicit, and this module implements it exactly:

| The statement prints | `value` | why |
|---|---|---|
| `3,360,000` under a "millions" heading | `3360000000000` | present, scaled once |
| `-`, `--`, an en dash or an em dash | `None` | the company reported nothing there |
| `0` | `Decimal("0")` | zero is a value, and is not the same as missing |
| anything else | `UnreadableFigureError` | absence of *knowledge*: the caller sets `needs_review` |

The last row is the important one. A parser that guessed here would turn "absence of
knowledge" into a number, and `SPEC.md` §4.1 forbids inferring missing financial data. So
this raises instead, and the caller records a NULL with `needs_review = TRUE` - the row
`docs/08` §1.4 reserves for "the extractor could not read the number".

**The scale vocabulary is the contract's, and only the contract's.** `docs/08` §2.3 declares
`as_printed_scale` as `'thousands'|'millions'|'units'`. Nigerian statements do occasionally
print in billions, and adding a fourth key here would let a writer declare a scale the
column's readers do not know. Widening it is a contract change in `docs/08` first, then a
change here - deliberately in that order, deliberately not free.

**What calls this.** Nothing yet, and that is the documented plan rather than an oversight:
`docs/03` P3.3 recommends building all six TG2 code paths "before any Nigerian price data is
consumed", and the callers are P3.2's manual entry form and P4's extractor. The EDGAR path
needs no conversion at all - XBRL facts arrive in base units, which is why
`normalize/statements.py` writes `unit_multiplier = 1` and no printed string.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Final

__all__ = [
    "SCALES",
    "Scaled",
    "UnreadableFigureError",
    "multiplier_for",
    "to_base",
]

#: The declared scales, and only these. `docs/08` §2.3's `as_printed_scale` vocabulary.
SCALES: Final[dict[str, int]] = {
    "units": 1,
    "thousands": 1_000,
    "millions": 1_000_000,
}

#: Every dash a statement uses for nil, including the en and em dashes a PDF carries and
#: the double hyphen a keyboard produces. `docs/08` §1.4: the company reported nothing.
_NIL = frozenset({"-", "--", "\u2010", "\u2011", "\u2012", "–", "—", "\u2015"})

#: Currency marks a printed figure may carry. Stripped only when the remainder still parses,
#: so a stray letter cannot be mistaken for a currency and quietly dropped.
_CURRENCY = ("₦", "NGN", "USD", "GBP", "EUR", "$", "£", "€")

#: What is left after the marks and separators come off: digits, with an optional decimal.
_NUMERAL = re.compile(r"^\d+(?:\.\d+)?$")

#: Thousands separators a statement may use, and the space variants a PDF introduces.
_SEPARATORS = ("\u00a0", "\u2009", "\u202f", " ", ",", "'", "_")


class UnreadableFigureError(ValueError):
    """The numeral could not be read. The caller records NULL and `needs_review`, never a guess."""


@dataclass(frozen=True)
class Scaled:
    """One figure, converted once, with everything `statement_line_items` needs to store it."""

    #: The fully scaled value in the major unit of its currency - naira, not kobo. None when
    #: the statement printed a nil dash, which is an absence and never a zero.
    value: Decimal | None
    #: The multiplier applied. Provenance and audit only: never multiply by this again.
    unit_multiplier: int
    #: The numeral exactly as printed, for provenance display: `'3,360,000'`.
    as_printed_value: str
    #: The scale as declared by the document: `'thousands'|'millions'|'units'`.
    as_printed_scale: str


def multiplier_for(scale: str) -> int:
    """The multiplier for a declared scale. Raises on anything outside the contract."""
    try:
        return SCALES[scale]
    except KeyError:
        raise UnreadableFigureError(
            f"{scale!r} is not a declared scale: {sorted(SCALES)}. Widening the vocabulary "
            "is a change to docs/08 §2.3 first, because as_printed_scale's readers must know it."
        ) from None


def to_base(printed: str, *, scale: str) -> Scaled:
    """`printed`, read under `scale`, as a value in base currency units. Multiplied once.

    `printed` is the numeral as it appears on the page and is preserved verbatim on the
    result. `scale` is what the document declares, typically in a column heading such as
    "N'000" or "in millions of naira" - it is the reader's job to carry that down from the
    heading, because this function cannot see the page.

    Returns a nil `value` for a printed dash. Raises `UnreadableFigureError` for anything it
    cannot read, so the caller stores NULL with `needs_review` rather than a guessed figure.
    """
    multiplier = multiplier_for(scale)
    as_printed = printed.strip()
    if not as_printed:
        raise UnreadableFigureError(
            "an empty string is not a figure. A line item that does not appear carries no "
            "row, or a row with value and as_printed both NULL (docs/08 §1.4)."
        )
    if _collapse(as_printed) in _NIL:
        return Scaled(None, multiplier, as_printed, scale)
    return Scaled(_read(as_printed) * multiplier, multiplier, as_printed, scale)


def _collapse(text: str) -> str:
    """Whitespace out, so `'( 3,360 )'` and `'- '` are the shapes they are meant to be."""
    return re.sub(r"\s+", "", text)


def _read(printed: str) -> Decimal:
    """The signed numeral, unscaled. Raises rather than guess."""
    body = _collapse(printed)

    # Accounting negatives come in brackets; a sign may also be printed outright. Both are
    # read, neither is assumed, and a figure carrying both is refused as contradictory.
    bracketed = body.startswith("(") and body.endswith(")")
    if bracketed:
        body = body[1:-1]
    signed = body.startswith("-") or body.startswith("\u2212")
    if signed:
        body = body[1:]
    if bracketed and signed:
        raise UnreadableFigureError(
            f"{printed!r} is bracketed and signed: two claims about one sign, so neither is used."
        )

    for mark in _CURRENCY:
        if body.upper().startswith(mark):
            body = body[len(mark) :]
            break
    for separator in _SEPARATORS:
        body = body.replace(separator, "")

    if not _NUMERAL.match(body):
        raise UnreadableFigureError(
            f"{printed!r} is not a figure this module will read. Store NULL with "
            "needs_review rather than a guess (SPEC.md §4.1: never infer missing data)."
        )
    try:
        value = Decimal(body)
    except InvalidOperation:  # pragma: no cover - _NUMERAL already excludes this
        raise UnreadableFigureError(f"{printed!r} is not a decimal") from None
    return -value if (bracketed or signed) else value

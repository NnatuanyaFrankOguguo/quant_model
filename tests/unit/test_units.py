"""`packages.common.units`: one conversion point. TG2, `OPERATIONS.md` §1.6.

Pure functions, no database. The class of error under test is the silent one: a figure off
by 1,000x because the multiplication happened in two places, or in none. `docs/03` P3.3 -
"off by 1,000x on *one line item among forty*" is not visually obvious, and no
balance-sheet tie-out catches it.

The second half of the file is the `docs/08` §1.4 null rule, which is a separate promise and
just as easy to break: a printed dash is an absence, a printed zero is a value, and an
unreadable numeral is neither. Confusing the first two publishes a debt-to-equity of 0.0 for
a company whose debt line was simply not read.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from packages.common.units import (
    SCALES,
    Scaled,
    UnreadableFigureError,
    multiplier_for,
    to_base,
)

pytestmark = pytest.mark.invariant

#: `docs/08` §1.4's worked figure. Under "millions" it is NGN 3.36 trillion; under
#: "thousands", NGN 3.36 billion. That 1,000x gap is the whole subject of this module, and
#: `docs/10` §2.8 names it exactly: "nothing distinguishes a correct NGN3.36tn from a
#: misread NGN3.36bn without reopening the PDF".
PRINTED = "3,360,000"
AS_TRILLIONS = Decimal("3360000000000")
AS_BILLIONS = Decimal("3360000000")

#: U+2212, the true minus sign a typeset statement uses where a keyboard gives U+002D.
#: Named rather than inlined, because beside a digit the two are indistinguishable.
MINUS_SIGN = "−"


# --------------------------------------------------------------------------------------
# Scaling, exactly once
# --------------------------------------------------------------------------------------


def test_the_same_numeral_under_two_scales_differs_by_a_thousand() -> None:
    """The contract's worked example, both readings, side by side.

    This is the test the module exists for. Nigerian statements declare the scale in a
    column heading, and the same numeral means two different companies' worth of money
    depending on which heading it sat under.
    """
    millions = to_base(PRINTED, scale="millions")
    thousands = to_base(PRINTED, scale="thousands")
    assert millions.value == AS_TRILLIONS
    assert thousands.value == AS_BILLIONS
    assert millions.value is not None and thousands.value is not None
    assert millions.value / thousands.value == 1000


@pytest.mark.parametrize("scale", sorted(SCALES))
def test_the_multiplication_happens_exactly_once(scale: str) -> None:
    """Dividing the stored value by the recorded multiplier returns the bare numeral.

    `docs/08` §1.5: `unit_multiplier` is kept "for provenance and audit, **not** for anyone
    downstream to multiply by again". This is the arithmetic that makes that checkable.
    """
    result = to_base(PRINTED, scale=scale)
    assert result.value is not None
    assert result.unit_multiplier == SCALES[scale]
    assert result.value / result.unit_multiplier == Decimal("3360000")


def test_units_is_a_scale_and_changes_nothing() -> None:
    result = to_base("3360000", scale="units")
    assert result.value == Decimal("3360000") and result.unit_multiplier == 1


def test_the_numeral_is_preserved_exactly_as_printed() -> None:
    """Provenance: the page said `'3,360,000'`, and the row must still be able to say so."""
    result = to_base("  3,360,000  ", scale="millions")
    assert result.as_printed_value == "3,360,000", "stripped of surrounding space, not reformatted"
    assert result.as_printed_scale == "millions"
    assert isinstance(result, Scaled)


def test_a_scale_outside_the_contract_is_refused() -> None:
    """Nigerian statements do print in billions, and the fix is `docs/08` first, not here.

    A fourth key added quietly would let a writer declare a scale that every reader of
    `as_printed_scale` - the review queue, the provenance panel - does not know.
    """
    with pytest.raises(UnreadableFigureError, match="not a declared scale"):
        to_base(PRINTED, scale="billions")
    with pytest.raises(UnreadableFigureError):
        multiplier_for("Thousands")  # the vocabulary is lower-case, and is not guessed at


def test_every_declared_scale_has_a_power_of_ten_multiplier() -> None:
    assert SCALES == {"units": 1, "thousands": 1_000, "millions": 1_000_000}
    assert [multiplier_for(s) for s in ("units", "thousands", "millions")] == [1, 1_000, 1_000_000]


# --------------------------------------------------------------------------------------
# The null rule: a dash, a zero, and an unreadable numeral are three different answers
# --------------------------------------------------------------------------------------


@pytest.mark.parametrize("dash", ["-", "--", "–", "—", " - ", "\u2012"])
def test_a_printed_dash_is_an_absence_and_never_a_zero(dash: str) -> None:
    """`docs/08` §1.4: "The company reported nothing there. We record nothing."

    The assertion is `is None`, not `== 0`, on purpose: in Python `Decimal(0) == 0` and
    `None == 0` differ, and it is precisely that difference the ratio engine depends on.
    """
    result = to_base(dash, scale="thousands")
    assert result.value is None
    assert result.as_printed_value == dash.strip(), "the dash itself is the provenance"


def test_a_printed_zero_is_a_value() -> None:
    """`docs/08` §1.4, verbatim: zero is a value, and it is not the same as missing."""
    result = to_base("0", scale="millions")
    assert result.value == Decimal("0")
    assert result.value is not None, "a reported zero is knowledge, not absence"


def test_an_unreadable_numeral_raises_rather_than_guess() -> None:
    """Absence of *knowledge*, which the caller stores as NULL plus `needs_review`.

    A parser that returned None here would be indistinguishable from the company printing a
    dash, and one that returned a number would be inferring missing financial data -
    `SPEC.md` §4.1's fourth invariant.
    """
    for unreadable in ("n/a", "N/A", "circa 3,360", "3,360 (restated)", "abc", "3.360.000", "??"):
        with pytest.raises(UnreadableFigureError):
            to_base(unreadable, scale="thousands")


def test_an_empty_string_is_not_a_figure() -> None:
    with pytest.raises(UnreadableFigureError, match="empty string"):
        to_base("   ", scale="units")


# --------------------------------------------------------------------------------------
# The shapes a real statement prints
# --------------------------------------------------------------------------------------


def test_an_accounting_negative_is_read_from_its_brackets() -> None:
    """IFRS statements print losses and outflows in brackets, not with a minus sign."""
    assert to_base("(3,360)", scale="millions").value == Decimal("-3360000000")
    assert to_base("( 3,360 )", scale="millions").value == Decimal("-3360000000")


def test_a_signed_negative_is_read_from_its_sign() -> None:
    """Both the ASCII hyphen-minus a keyboard gives and the true minus sign a PDF sets."""
    assert to_base("-3,360", scale="thousands").value == Decimal("-3360000")
    assert to_base(f"{MINUS_SIGN}3,360", scale="thousands").value == Decimal("-3360000")


def test_a_figure_both_bracketed_and_signed_is_refused() -> None:
    """Two claims about one sign. Neither is used, because choosing would be a guess."""
    with pytest.raises(UnreadableFigureError, match="two claims about one sign"):
        to_base("(-3,360)", scale="thousands")


@pytest.mark.parametrize(
    "printed",
    ["₦3,360", "NGN3,360", "NGN 3,360", "$3,360", "£3,360"],
)
def test_a_currency_mark_is_stripped(printed: str) -> None:
    assert to_base(printed, scale="thousands").value == Decimal("3360000")


@pytest.mark.parametrize("separator", ["\u00a0", "\u2009", "\u202f", " ", ","])
def test_the_thousands_separators_a_pdf_produces(separator: str) -> None:
    """A PDF carries non-breaking and thin spaces where a screen shows a plain one."""
    assert to_base(f"3{separator}360", scale="thousands").value == Decimal("3360000")


def test_a_decimal_survives_scaling() -> None:
    """Half a thousand is five hundred, and the arithmetic must not round it away."""
    assert to_base("3,360.5", scale="thousands").value == Decimal("3360500")
    assert to_base("0.001", scale="millions").value == Decimal("1000")

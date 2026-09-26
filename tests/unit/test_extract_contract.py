"""`packages.extract.contract`: catching a number the document does not contain. P4.2.

`docs/03` P4.2 tabulates what each prompt constraint prevents, and names the worst one:
*"never infer/estimate/fill gaps"* prevents *"the single most dangerous LLM behaviour here
- a plausible fabricated number."*

A prompt is not enforcement. A model that fabricates anyway returns something perfectly
well-formed - real-looking figure, plausible label, page number in range, confidence 0.95 -
and every schema check passes. P4.3's arithmetic identities catch a fabricated figure only
when it happens to break one, and a fabricated *revenue* breaks none.

Grounding is the check that does not depend on the invented number being inconvenient: the
label and the digits have to be on the page the extraction cites, and we have that page.

The figures below are the real MTN ones `docs/03` P4.2 uses for the same reason it does -
FY2024 revenue ₦3.36 trillion and a loss after tax of ₦400.44 billion - *"because the loss
is large, negative, and easy to get sign-wrong."*
"""

from __future__ import annotations

import json
from decimal import Decimal

import pytest

from packages.extract.contract import (
    LABEL_NOT_ON_PAGE,
    NO_SUCH_PAGE,
    VALUE_NOT_ON_PAGE,
    ContractViolationError,
    grounding_findings,
    parse_extraction,
)

pytestmark = pytest.mark.invariant

#: A statement page as pdfplumber returns one: figures with thousands separators, the loss
#: in brackets the way accounting prints it, and an absent line shown as a dash.
PAGE_94 = """MTN Nigeria Communications Plc
Statement of profit or loss for the year ended 31 December 2024
In thousands of naira                        2024            2023
Revenue                                 3,360,000       2,470,000
Cost of sales                          (1,120,000)       (890,000)
Loss for the year                        (400,440)       (137,000)
Gross profit                                    -               -
"""

PAGES = {94: PAGE_94}


def response(**overrides: object) -> dict[str, object]:
    """The P4.2 output shape, with `value` as printed and the multiplier beside it."""
    payload: dict[str, object] = {
        "company": "MTN Nigeria Communications Plc",
        "period_end": "2024-12-31",
        "currency": "NGN",
        "unit_multiplier": 1000,
        "statement": "income_statement",
        "line_items": [
            {
                "canonical_key": "revenue",
                "as_printed": "Revenue",
                "value": 3360000,
                "page": 94,
                "confidence": 0.97,
            },
            {
                "canonical_key": "profit_after_tax",
                "as_printed": "Loss for the year",
                "value": -400440,
                "page": 94,
                "confidence": 0.95,
            },
        ],
        "extraction_notes": "FX losses disclosed separately in note 12",
    }
    payload.update(overrides)
    return payload


def item(**overrides: object) -> dict[str, object]:
    base: dict[str, object] = {
        "canonical_key": "revenue",
        "as_printed": "Revenue",
        "value": 3360000,
        "page": 94,
        "confidence": 0.9,
    }
    base.update(overrides)
    return base


# --------------------------------------------------------------------------------------
# Grounding - the check the module exists for
# --------------------------------------------------------------------------------------


def test_a_faithful_extraction_grounds_completely() -> None:
    """Every label and every figure is on page 94, so nothing is reported."""
    assert grounding_findings(parse_extraction(response()), PAGES) == []


def test_an_invented_figure_is_caught_even_though_it_is_plausible() -> None:
    """The failure `docs/03` calls the most dangerous, and the only check that sees it.

    ₦2,800,000 thousand is a perfectly reasonable revenue for this company, sits on a real
    page, under a real label, with a confident score. It breaks no arithmetic identity. It
    is simply not in the document.
    """
    payload = response(line_items=[item(value=2800000)])
    findings = grounding_findings(parse_extraction(payload), PAGES)
    assert [f.kind for f in findings] == [VALUE_NOT_ON_PAGE]
    assert "2800000" in findings[0].detail


def test_an_invented_label_is_caught() -> None:
    """The label is what lets a reviewer check a mapping without reopening the PDF, so one
    that is not on the page is not doing the job it exists for."""
    payload = response(line_items=[item(as_printed="Total turnover")])
    findings = grounding_findings(parse_extraction(payload), PAGES)
    assert [f.kind for f in findings] == [LABEL_NOT_ON_PAGE]
    assert "Total turnover" in findings[0].detail


def test_a_citation_to_a_page_we_did_not_read_is_reported_not_assumed_good() -> None:
    """A page we could not read is not a page that confirms anything.

    Passing it silently would make every unread page a place a fabricated figure can hide,
    which is worse than not checking at all because the check would appear to have run.
    """
    payload = response(line_items=[item(page=412)])
    findings = grounding_findings(parse_extraction(payload), PAGES)
    assert [f.kind for f in findings] == [NO_SUCH_PAGE]
    assert "412" in findings[0].detail


def test_the_accounting_bracket_is_read_as_a_negative() -> None:
    """`(400,440)` on the page and `-400440` in the response are the same figure.

    P4.2 picks this example precisely because the sign is easy to get wrong, so the
    matching has to see through the bracket convention rather than around it.
    """
    payload = response(
        line_items=[
            item(canonical_key="profit_after_tax", as_printed="Loss for the year", value=-400440)
        ]
    )
    assert grounding_findings(parse_extraction(payload), PAGES) == []


def test_a_loss_reported_as_a_profit_does_not_ground() -> None:
    """The sign error itself, caught rather than waved through.

    The digits are on the page, so a check that matched on digits alone would pass this -
    and a ₦400 billion loss stored as a ₦400 billion profit is the single most consequential
    wrong number this pipeline could produce.
    """
    payload = response(
        line_items=[
            item(canonical_key="profit_after_tax", as_printed="Loss for the year", value=400440)
        ]
    )
    assert [f.kind for f in grounding_findings(parse_extraction(payload), PAGES)] == [
        VALUE_NOT_ON_PAGE
    ]


def test_a_premultiplied_value_does_not_ground_and_says_why() -> None:
    """The `docs/03` P4.2 ambiguity, made visible instead of silent.

    The prompt says report values as stated; the abridged example beside it shows one
    already multiplied. A model that follows the example produces figures that are off by
    exactly the multiplier - and rather than a silent thousandfold error, every line comes
    back as a finding that names the multiplier as the likely cause.
    """
    payload = response(line_items=[item(value=3360000 * 1000)])
    findings = grounding_findings(parse_extraction(payload), PAGES)
    assert [f.kind for f in findings] == [VALUE_NOT_ON_PAGE]
    assert "unit_multiplier" in findings[0].detail


def test_an_absent_line_needs_a_label_but_no_figure() -> None:
    """`null` is what the prompt asks for when a line is missing.

    There is no figure to find, and demanding one would report a finding against a model
    that did exactly the right thing.
    """
    payload = response(
        line_items=[item(canonical_key="gross_profit", as_printed="Gross profit", value=None)]
    )
    assert grounding_findings(parse_extraction(payload), PAGES) == []


def test_a_wrapped_label_still_grounds() -> None:
    """A label broken across two lines in the PDF arrives with a newline inside it; the
    model reports it as one line. Neither is wrong, and they have to compare equal."""
    pages = {94: PAGE_94.replace("Cost of sales", "Cost of\nsales")}
    payload = response(line_items=[item(as_printed="Cost of sales", value=-1120000)])
    assert grounding_findings(parse_extraction(payload), pages) == []


def test_a_figure_that_is_only_a_substring_of_a_larger_one_does_not_ground() -> None:
    """`336` appears inside `3,360,000`, and a loose search would call it found.

    That is the quietest possible false pass: the check reports confidence in a figure that
    is not on the page, for a reason nobody would think to look for.
    """
    payload = response(line_items=[item(value=336)])
    assert [f.kind for f in grounding_findings(parse_extraction(payload), PAGES)] == [
        VALUE_NOT_ON_PAGE
    ]


# --------------------------------------------------------------------------------------
# Shape
# --------------------------------------------------------------------------------------


def test_the_multiplier_is_applied_in_one_place() -> None:
    """₦3,360,000 thousand is ₦3.36 trillion, and the arithmetic lives on the dataclass so
    it cannot be done twice or not at all."""
    extraction = parse_extraction(response())
    assert extraction.in_reporting_units(extraction.line_items[0]) == Decimal("3360000000")
    assert extraction.in_reporting_units(extraction.line_items[1]) == Decimal("-400440000")


def test_a_scale_nobody_reports_in_is_refused() -> None:
    """A multiplier of 100 is a misread scale, and the error it causes is silent."""
    with pytest.raises(ContractViolationError, match="unit_multiplier=100"):
        parse_extraction(response(unit_multiplier=100))


def test_an_absent_value_key_is_not_the_same_as_a_null_one() -> None:
    """One is a model reporting an absence, the other is a model that did not answer.

    Defaulting the missing key to `None` would turn a non-answer into a reported absence -
    a fact the document never asserted, recorded as though it had.
    """
    broken = item()
    del broken["value"]
    with pytest.raises(ContractViolationError, match="is absent"):
        parse_extraction(response(line_items=[broken]))


def test_a_zero_page_is_refused() -> None:
    """Pages are one-based. Zero means an off-by-one somewhere upstream, and a reviewer
    sent to check a figure would be sent to the page before it, every time."""
    with pytest.raises(ContractViolationError, match="one-based"):
        parse_extraction(response(line_items=[item(page=0)]))


def test_a_confidence_outside_the_range_is_refused() -> None:
    """Routing at 0.85 is meaningless if the scale is not the one it assumes."""
    with pytest.raises(ContractViolationError, match="outside 0..1"):
        parse_extraction(response(line_items=[item(confidence=1.4)]))


def test_a_boolean_is_not_an_integer_here() -> None:
    """`True` is an `int` in Python and would read as a multiplier of one, from a field
    that was never a number."""
    with pytest.raises(ContractViolationError, match="unit_multiplier"):
        parse_extraction(response(unit_multiplier=True))


def test_a_json_float_keeps_the_figure_that_was_written() -> None:
    """Through `str`, so 0.1 is 0.1 and not 0.1000000000000000055511151231257827."""
    extraction = parse_extraction(json.dumps(response(line_items=[item(confidence=0.1)])))
    assert extraction.line_items[0].confidence == Decimal("0.1")


def test_a_response_that_is_not_json_names_that_as_the_problem() -> None:
    """This runs against model output, and "invalid response" is not actionable."""
    with pytest.raises(ContractViolationError, match="not JSON"):
        parse_extraction("I'm sorry, I could not read that PDF.")


def test_an_empty_line_items_list_is_accepted() -> None:
    """A page with no figures on it is a real answer, and refusing it would push the model
    towards inventing one - the exact behaviour everything here exists to discourage."""
    assert parse_extraction(response(line_items=[])).line_items == ()


# --------------------------------------------------------------------------------------
# The two false positives the first version of the matcher had
#
# Both were found by writing the substring test above, and both are the worst failure this
# module can have: reporting that a fabricated figure was confirmed against the source.
# --------------------------------------------------------------------------------------


def test_two_columns_running_together_do_not_invent_numbers() -> None:
    """`Revenue 3,360,000 2,470,000` is two figures, not a fourteen-digit one.

    The first matcher stripped separators *and spaces* and searched the result, so the page
    contained `33600002470000` and therefore `0002470`, `60000247`, and several hundred
    other numbers nobody printed. A two-column statement generates these by the page.
    """
    payload = response(line_items=[item(value=2470)])
    assert [f.kind for f in grounding_findings(parse_extraction(payload), PAGES)] == [
        VALUE_NOT_ON_PAGE
    ]


def test_a_thin_space_between_groups_is_still_one_number() -> None:
    """A typeset statement may group with a no-break space rather than a comma.

    The ordinary space cannot be treated that way - it is the gap between columns - but
    U+00A0 and U+202F are only ever used inside a figure, so reading them as separators
    adds no ambiguity and refusing them would fail to ground a correctly-read page.
    """
    pages = {94: "Revenue 3 360 000 2 470 000\n"}
    payload = response(line_items=[item(value=3360000)])
    assert grounding_findings(parse_extraction(payload), pages) == []


def test_a_figure_printed_with_a_leading_minus_grounds() -> None:
    """Not every statement uses brackets. Both conventions mean the same thing."""
    pages = {94: "Loss for the year -400,440\n"}
    payload = response(
        line_items=[
            item(canonical_key="profit_after_tax", as_printed="Loss for the year", value=-400440)
        ]
    )
    assert grounding_findings(parse_extraction(payload), pages) == []


def test_a_decimal_figure_grounds_on_its_printed_precision() -> None:
    """Ratios and per-share figures are printed to two places and reported the same way."""
    pages = {94: "Basic earnings per share 12.45\n"}
    payload = response(
        line_items=[
            item(canonical_key="eps_basic", as_printed="Basic earnings per share", value=12.45)
        ]
    )
    assert grounding_findings(parse_extraction(payload), pages) == []

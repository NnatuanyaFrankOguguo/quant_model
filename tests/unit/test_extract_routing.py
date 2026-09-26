"""`packages.extract.routing`: stored, or seen by a human. P4.3, P4 check 8.

`docs/03` P4.3: *"Confidence = LLM self-report × validation pass rate × table quality.
**Below ~0.85 → review.**"* and *"Any failure sets `needs_review`, reduces confidence, and
queues the extraction for a human."*

P4 check 8 names the case: *"An extraction scoring 0.7 -> Lands in the review queue, not in
the store."*

Everything here is arithmetic over three numbers and two rules, so none of it needs a
database or a model.
"""

from __future__ import annotations

import datetime as dt
from decimal import Decimal

import pytest

from packages.extract.contract import (
    LABEL_NOT_ON_PAGE,
    VALUE_NOT_ON_PAGE,
    Extraction,
    Finding,
    LineItem,
)
from packages.extract.pdf import MIXED, NATIVE, SCANNED
from packages.extract.routing import (
    NEEDS_REVIEW,
    REVIEW_THRESHOLD,
    STORED,
    route,
    table_quality_of,
)
from packages.normalize.validation import FAILED, NOT_CHECKABLE, PASSED, IdentityResult
from packages.normalize.validation import ValidationReport as Report

pytestmark = pytest.mark.invariant

PERIOD_END = dt.date(2024, 12, 31)
REQUIRED = frozenset({"revenue", "profit_after_tax"})


def line(key: str, confidence: str) -> LineItem:
    return LineItem(
        canonical_key=key,
        as_printed=key.replace("_", " ").title(),
        value=Decimal("1000"),
        page=94,
        confidence=Decimal(confidence),
    )


def extraction(*items: LineItem) -> Extraction:
    return Extraction(
        company="MTN Nigeria Communications Plc",
        period_end=PERIOD_END,
        currency="NGN",
        unit_multiplier=1000,
        statement="income_statement",
        line_items=items,
    )


def report(*outcomes: str) -> Report:
    """A validation report with one identity per outcome given."""
    return Report(
        company_id=1,
        period_type="FY",
        period_end=PERIOD_END,
        results=[
            IdentityResult(
                name=f"identity_{index}", outcome=outcome, detail="", expected=None, actual=None
            )
            for index, outcome in enumerate(outcomes)
        ],
    )


# --------------------------------------------------------------------------------------
# The threshold
# --------------------------------------------------------------------------------------


def test_an_extraction_scoring_0_7_lands_in_the_queue() -> None:
    """P4 check 8, word for word: *"not in the store."*"""
    decision = route(
        extraction(line("revenue", "0.7")),
        validation=report(PASSED),
        page_kinds=[NATIVE],
        required_keys=REQUIRED,
    )
    assert decision.status == NEEDS_REVIEW
    assert decision.needs_review
    assert decision.confidence == Decimal("0.7")


def test_a_clean_extraction_is_stored_without_a_human() -> None:
    """The other half of check 8, which a rule that reviewed everything would also pass."""
    decision = route(
        extraction(line("revenue", "0.97"), line("profit_after_tax", "0.95")),
        validation=report(PASSED, PASSED),
        page_kinds=[NATIVE],
        required_keys=REQUIRED,
    )
    assert decision.status == STORED
    assert decision.confidence == Decimal("0.95")


def test_exactly_at_the_threshold_is_stored() -> None:
    """`docs/03` P4.3 says *below* 0.85, so 0.85 itself is not below it.

    Asserted rather than left to the reader, because a boundary nobody wrote down is one
    that moves the next time somebody reads the sentence.
    """
    decision = route(
        extraction(line("revenue", "0.85")),
        validation=report(PASSED),
        page_kinds=[NATIVE],
        required_keys=REQUIRED,
    )
    assert decision.confidence == REVIEW_THRESHOLD
    assert decision.status == STORED


# --------------------------------------------------------------------------------------
# The rules the product cannot express
# --------------------------------------------------------------------------------------


def test_a_failed_identity_forces_review_however_confident_the_model_was() -> None:
    """*"Any failure sets `needs_review`"* - not "reduces the score a bit".

    A model at 0.99 whose balance sheet does not balance is a confident model and a wrong
    statement, and the product of three high numbers would happily store it.
    """
    decision = route(
        extraction(line("revenue", "0.99"), line("profit_after_tax", "0.99")),
        validation=report(PASSED, PASSED, PASSED, FAILED),
        page_kinds=[NATIVE],
        required_keys=REQUIRED,
    )
    assert decision.status == NEEDS_REVIEW
    assert decision.failed_identities == ("identity_3",)
    assert "any failure sets needs_review" in decision.reason


def test_an_unvalidated_extraction_is_never_stored() -> None:
    """A pass rate of `None` is not a pass rate of one.

    `ValidationReport.pass_rate` is `None` when nothing could be checked, and the docstring
    there is explicit that such a period *"is not a period that passed"*. Multiplied in as
    1.0 it would mean unvalidated is perfect, and every statement too sparse to check would
    reach the store on the model's opinion of itself alone.
    """
    decision = route(
        extraction(line("revenue", "0.99")),
        validation=report(NOT_CHECKABLE, NOT_CHECKABLE),
        page_kinds=[NATIVE],
        required_keys=REQUIRED,
    )
    assert decision.status == NEEDS_REVIEW
    assert decision.pass_rate is None
    assert "Unvalidated is not the same as validated-and-passed" in decision.reason


def test_forgetting_to_validate_is_not_quieter_than_failing_to() -> None:
    """`validation=None` routes exactly as an unvalidatable one does.

    The two differ in cause and not at all in what should happen next, and a caller that
    skipped the step must not get a better answer than one whose figures were too sparse.
    """
    decision = route(
        extraction(line("revenue", "0.99")),
        validation=None,
        page_kinds=[NATIVE],
        required_keys=REQUIRED,
    )
    assert decision.status == NEEDS_REVIEW
    assert decision.pass_rate is None


def test_a_figure_that_is_not_on_its_page_forces_review_before_any_arithmetic() -> None:
    """Grounding failure is not a confidence question.

    A number the document does not contain is not a number read with low confidence, and
    scoring it would imply that enough confidence elsewhere could outvote it.
    """
    decision = route(
        extraction(line("revenue", "0.99")),
        validation=report(PASSED),
        page_kinds=[NATIVE],
        required_keys=REQUIRED,
        grounding=[Finding(kind=VALUE_NOT_ON_PAGE, canonical_key="revenue", page=94, detail="x")],
    )
    assert decision.status == NEEDS_REVIEW
    assert decision.unverified == (f"{VALUE_NOT_ON_PAGE}:revenue",)
    assert "not a low-confidence reading" in decision.reason


def test_grounding_outranks_an_arithmetic_failure_in_the_reason_given() -> None:
    """Both send it to review; the reason should name the more fundamental one.

    "This figure is not in the document" tells a reviewer what to do; "the balance sheet
    does not balance" sends them looking for the arithmetic error that a phantom figure
    caused.
    """
    decision = route(
        extraction(line("revenue", "0.99")),
        validation=report(FAILED),
        page_kinds=[NATIVE],
        required_keys=REQUIRED,
        grounding=[Finding(kind=LABEL_NOT_ON_PAGE, canonical_key="revenue", page=94, detail="x")],
    )
    assert decision.status == NEEDS_REVIEW
    assert "could not be found on the page cited" in decision.reason


# --------------------------------------------------------------------------------------
# How the three factors are combined
# --------------------------------------------------------------------------------------


def test_a_badly_read_required_figure_is_not_averaged_away() -> None:
    """The worst outcome available, and the reason the mean is not used.

    Revenue at 0.4 among four notes at 0.99 averages to 0.87 and stores - and revenue is
    what everything downstream divides by.
    """
    decision = route(
        extraction(
            line("revenue", "0.4"),
            line("note_a", "0.99"),
            line("note_b", "0.99"),
            line("note_c", "0.99"),
            line("note_d", "0.99"),
        ),
        validation=report(PASSED),
        page_kinds=[NATIVE],
        required_keys=REQUIRED,
    )
    assert decision.status == NEEDS_REVIEW
    assert decision.self_report == Decimal("0.4")


def test_a_badly_read_note_does_not_hold_the_whole_statement() -> None:
    """The reason the unconditional minimum is not used either.

    One obscure note at 0.6 sending a forty-line statement to review is how a queue fills
    with work that changes nothing, which is the FIFO failure `docs/03` P4.4 warns about
    arriving by a different route.
    """
    decision = route(
        extraction(
            line("revenue", "0.97"),
            line("profit_after_tax", "0.96"),
            line("note_on_directors_emoluments", "0.6"),
        ),
        validation=report(PASSED),
        page_kinds=[NATIVE],
        required_keys=REQUIRED,
    )
    assert decision.status == STORED
    assert decision.self_report == Decimal("0.96")


def test_a_statement_with_no_required_keys_falls_back_to_every_line() -> None:
    """Otherwise `min()` over an empty selection, and a statement of pure notes would be
    judged on nothing at all."""
    decision = route(
        extraction(line("note_a", "0.5"), line("note_b", "0.99")),
        validation=report(PASSED),
        page_kinds=[NATIVE],
        required_keys=REQUIRED,
    )
    assert decision.self_report == Decimal("0.5")
    assert decision.status == NEEDS_REVIEW


def test_an_extraction_with_no_figures_scores_zero_rather_than_perfectly() -> None:
    """`min()` of nothing is an error and "no doubts" is the wrong reading of no figures.

    An extraction that found nothing is exactly what a human should look at - it is the
    empty-page case from P4 check 14, arriving through the model instead of the scraper.
    """
    decision = route(
        extraction(), validation=report(PASSED), page_kinds=[NATIVE], required_keys=REQUIRED
    )
    assert decision.self_report == Decimal(0)
    assert decision.status == NEEDS_REVIEW


def test_a_scanned_page_costs_confidence() -> None:
    """A figure recovered from a photograph is not evidence of the same strength as one
    read off a text layer, and P4.3 puts table quality in the product for that reason."""
    clean = route(
        extraction(line("revenue", "0.94")),
        validation=report(PASSED),
        page_kinds=[NATIVE],
        required_keys=REQUIRED,
    )
    scanned = route(
        extraction(line("revenue", "0.94")),
        validation=report(PASSED),
        page_kinds=[SCANNED],
        required_keys=REQUIRED,
    )
    # 0.94 is chosen so the scan is what decides it: 0.94 stores, 0.94 x 0.90 = 0.846 does
    # not. At 0.95 both sides clear the threshold and the test would pass without the
    # factor doing anything.
    assert clean.status == STORED
    assert scanned.confidence == Decimal("0.8460")
    assert scanned.status == NEEDS_REVIEW


def test_the_weakest_page_sets_the_quality_not_the_average() -> None:
    """A statement assembled from one clean page and one photograph is only as good as the
    photograph for whatever came off it."""
    assert table_quality_of([NATIVE, NATIVE, MIXED]) == Decimal("0.80")
    assert table_quality_of([NATIVE]) == Decimal("1.00")


def test_no_pages_given_assumes_a_clean_one() -> None:
    """For a caller that has no page information - an XBRL path, or a test - table quality
    must not silently penalise an extraction that never came off a page at all."""
    assert table_quality_of([]) == Decimal("1.00")


def test_the_decision_carries_every_factor_that_produced_it() -> None:
    """`extraction_jobs.confidence` is one column, and a reviewer asking "why is this in my
    queue" needs to know whether the model was unsure, the arithmetic disagreed, or the
    page was a photograph."""
    decision = route(
        extraction(line("revenue", "0.9")),
        validation=report(PASSED, FAILED),
        page_kinds=[MIXED],
        required_keys=REQUIRED,
    )
    assert decision.self_report == Decimal("0.9")
    assert decision.pass_rate == Decimal("0.5")
    assert decision.table_quality == Decimal("0.80")
    assert decision.failed_identities

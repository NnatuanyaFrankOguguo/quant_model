"""Deciding whether an extraction is stored or seen by a human. P4.3, P4 check 8.

`docs/03` P4.3 gives the rule in two sentences, and they are the whole of this module:

    Any failure sets `needs_review`, reduces confidence, and queues the extraction for a
    human.

    Confidence = LLM self-report × validation pass rate × table quality. **Below ~0.85 →
    review.**

P4 check 8 is the test: *"An extraction scoring 0.7 -> Lands in the review queue, not in
the store."*

The three factors already exist separately and nothing multiplied them:

* **self-report** - `packages.extract.contract.LineItem.confidence`, per figure.
* **validation pass rate** - `packages.normalize.validation.ValidationReport.pass_rate`.
* **table quality** - derivable from `packages.extract.pdf.PageRead.kind`; a figure read
  off a clean text layer is not evidence of the same strength as one recovered from a scan.

## Two things the formula does not say, and this module has to

**A pass rate of `None` cannot be multiplied.** `ValidationReport.pass_rate` returns `None`
when no identity had the figures it needed, and it is deliberate: *"a period whose figures
are too sparse to test is not a period that passed, and it is not one that failed either."*
Treated as `1.0` it would mean unvalidated is perfect, and every statement too sparse to
check would sail into the store on the model's own opinion of itself. Treated as `0` it
would condemn every partial extraction. So it is neither: **an unvalidated extraction
routes to review whatever the other two factors say.** Not a number, a rule.

**"LLM self-report" is singular and the contract's confidences are per figure.** Combining
them by mean lets one badly-read revenue at 0.4 hide among thirty-nine notes at 0.98 -
which is the single worst outcome available, because revenue is what everything downstream
divides by. Combining by minimum over *every* line sends a whole statement to review
because one obscure note scored 0.6, which floods the queue and spends the reviewer
attention `docs/03` P4.4 says to protect.

So: the **minimum over the required keys**, falling back to the minimum over all lines when
a statement carries none. A figure the chart marks required is one a reader will actually
use; a note is not, and a note read badly is a per-line flag rather than grounds to hold
the statement.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from decimal import Decimal

from packages.extract.contract import Extraction, Finding, LineItem
from packages.extract.pdf import BLANK, MIXED, NATIVE, SCANNED
from packages.normalize.validation import ValidationReport

__all__ = [
    "NEEDS_REVIEW",
    "REVIEW_THRESHOLD",
    "STORED",
    "TABLE_QUALITY",
    "RoutingDecision",
    "route",
    "table_quality_of",
]

#: Stored with provenance, no human needed. `docs/03` P4.1's "passes, confidence >= 0.85".
STORED = "stored"
#: Queued for a human. The `extraction_jobs.status` value P4's own example table uses.
NEEDS_REVIEW = "needs_review"

#: `docs/03` P4.3's figure: *"Below ~0.85 → review."* At the threshold is stored - the text
#: says *below* - and the boundary is asserted in the tests so nobody has to guess later.
REVIEW_THRESHOLD = Decimal("0.85")

#: How much a page's own readability is worth as evidence. A figure lifted from a clean text
#: layer was read; one recovered from a scan was guessed at well. `MIXED` is the worst of the
#: three on purpose - it means the text we can see is a header and the figures are in the
#: part we cannot, so the reconciler was working from the least of the page.
TABLE_QUALITY: dict[str, Decimal] = {
    NATIVE: Decimal("1.00"),
    SCANNED: Decimal("0.90"),
    MIXED: Decimal("0.80"),
    BLANK: Decimal("0.80"),
}


@dataclass(frozen=True)
class RoutingDecision:
    """Where this extraction goes, and every number that sent it there.

    The factors are kept rather than folded away because `extraction_jobs.confidence` is one
    column, and a reviewer asking "why is this in my queue" needs to know whether the model
    was unsure, the arithmetic disagreed, or the page was a photograph.
    """

    status: str
    confidence: Decimal
    self_report: Decimal
    #: `None` when no identity could be checked - which forces review on its own.
    pass_rate: Decimal | None
    table_quality: Decimal
    #: Identities that failed. Any of these forces review, whatever the product comes to.
    failed_identities: tuple[str, ...]
    #: Grounding findings. A figure that is not on its page is not a confidence question.
    unverified: tuple[str, ...]
    reason: str

    @property
    def needs_review(self) -> bool:
        return self.status == NEEDS_REVIEW


def table_quality_of(kinds: Iterable[str]) -> Decimal:
    """The weakest page the extraction drew on.

    The weakest rather than the average, because a statement assembled from one clean page
    and one photograph is only as good as the photograph for whatever came off it, and the
    routing decision covers the statement as a whole.
    """
    seen = [TABLE_QUALITY.get(kind, TABLE_QUALITY[MIXED]) for kind in kinds]
    return min(seen) if seen else TABLE_QUALITY[NATIVE]


def _self_report(items: Sequence[LineItem], required: frozenset[str]) -> Decimal:
    """The lowest confidence among the figures that matter.

    Required keys when the statement has any, every line otherwise. See the module
    docstring for why neither the mean nor the unconditional minimum is right.
    """
    if not items:
        # No figures at all. Not a confident extraction of nothing - an extraction that
        # found nothing, which is precisely what a human should look at.
        return Decimal(0)
    matter = [item for item in items if item.canonical_key in required]
    return min(item.confidence for item in (matter or items))


def route(
    extraction: Extraction,
    *,
    validation: ValidationReport | None,
    page_kinds: Iterable[str] = (),
    required_keys: frozenset[str] = frozenset(),
    grounding: Sequence[Finding] = (),
) -> RoutingDecision:
    """`docs/03` P4.3's rule, applied. Never stores an extraction it could not check.

    `validation` is `None` when validation has not been run at all, which is treated the
    same as a validation that could check nothing: review. The two differ in cause and not
    in what should happen next, and a caller that forgot to validate must not get a
    quieter answer than one whose figures were too sparse to validate.
    """
    self_report = _self_report(extraction.line_items, required_keys)
    quality = table_quality_of(page_kinds)
    pass_rate = validation.pass_rate if validation is not None else None
    failed = tuple(
        result.name for result in (validation.failures if validation is not None else [])
    )
    unverified = tuple(f"{f.kind}:{f.canonical_key}" for f in grounding)

    # The product, with an unvalidated pass rate left out of it rather than guessed at. The
    # figure is still reported, because `extraction_jobs.confidence` wants a number even
    # when the routing was decided by a rule rather than by the threshold.
    confidence = self_report * quality * (pass_rate if pass_rate is not None else Decimal(1))

    if unverified:
        return _review(
            confidence,
            self_report,
            pass_rate,
            quality,
            failed,
            unverified,
            reason=(
                f"{len(unverified)} figure(s) could not be found on the page cited: "
                f"{', '.join(unverified[:4])}. A figure the document does not contain is "
                f"not a low-confidence reading of one."
            ),
        )
    if pass_rate is None:
        return _review(
            confidence,
            self_report,
            pass_rate,
            quality,
            failed,
            unverified,
            reason=(
                "no arithmetic identity had the figures it needed, so nothing about this "
                "extraction has been checked against anything. Unvalidated is not the same "
                "as validated-and-passed, and only the model's own opinion is left."
            ),
        )
    if failed:
        return _review(
            confidence,
            self_report,
            pass_rate,
            quality,
            failed,
            unverified,
            reason=(
                f"{len(failed)} identity failed: {', '.join(failed[:4])}. `docs/03` P4.3: "
                f"any failure sets needs_review."
            ),
        )
    if confidence < REVIEW_THRESHOLD:
        return _review(
            confidence,
            self_report,
            pass_rate,
            quality,
            failed,
            unverified,
            reason=(
                f"confidence {confidence:.3f} is below {REVIEW_THRESHOLD} (self-report "
                f"{self_report}, pass rate {pass_rate}, table quality {quality})"
            ),
        )
    return RoutingDecision(
        status=STORED,
        confidence=confidence,
        self_report=self_report,
        pass_rate=pass_rate,
        table_quality=quality,
        failed_identities=failed,
        unverified=unverified,
        reason=(
            f"confidence {confidence:.3f} at or above {REVIEW_THRESHOLD}, every checkable "
            f"identity passed, and every figure was found on the page it cites"
        ),
    )


def _review(
    confidence: Decimal,
    self_report: Decimal,
    pass_rate: Decimal | None,
    quality: Decimal,
    failed: tuple[str, ...],
    unverified: tuple[str, ...],
    *,
    reason: str,
) -> RoutingDecision:
    return RoutingDecision(
        status=NEEDS_REVIEW,
        confidence=confidence,
        self_report=self_report,
        pass_rate=pass_rate,
        table_quality=quality,
        failed_identities=failed,
        unverified=unverified,
        reason=reason,
    )

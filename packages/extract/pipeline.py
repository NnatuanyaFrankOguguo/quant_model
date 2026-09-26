"""The hybrid extraction pipeline, with the model behind an interface. P4.1.

`docs/03` P4.1 draws the whole thing, and every box except one now exists:

    PDF arrives --> native or scanned?        packages.extract.pdf
      native  --> pdfplumber, text + tables   packages.extract.pdf
      scanned --> OCR                         (not built; no scanned fixture yet)
    --> Claude reconciles to canonical keys   `Reconciler`, below - the missing box
    --> Deterministic validation              packages.normalize.validation
      passes, confidence >= 0.85 --> store    NOT YET BUILT - see below
      fails or low confidence    --> queue    packages.normalize.review
    --> correction stored as a few-shot example

This module is the wiring between them, and the reason it can exist before the API key
does: **the model is a `Reconciler`, which is a protocol.** Everything on either side of
that one call is deterministic, so the pipeline is testable end to end today with a
reconciler that returns a canned response, and the day a key arrives the work is one class
that satisfies four attributes.

## The order is the safety property

Budget, then model, then parse, then ground, then validate, then route, then store. Each
gate is ahead of the cost or the harm it prevents:

* the **budget** check is before the call, because `docs/02` §10 is about not billing after
  the cap, and a check afterwards is an audit rather than a limit;
* **grounding** is before validation, because a figure that is not in the document is not a
  figure whose arithmetic is worth discussing;
* **validation** is before the store, which is what `validate_candidate` exists for;
* the **store** happens only on `STORED`, because *"fails or low confidence -> human review
  queue"* means the queue instead of the store, not as well as it.

## The store does not exist yet, and `enter_statement` cannot be it

An earlier version of this docstring said the write was
`packages.normalize.manual.enter_statement`'s job. That was wrong, and wrong in a way worth
recording rather than quietly fixing.

`enter_statement` hardcodes `extraction_method='manual'` and refuses an empty
`reviewed_by` - *"a hand-typed figure is only as good as the name attached to it"*. Both
are right for P3.2 and both are exactly wrong here. An extraction that reaches `STORED`
reached it **because no human was needed**; putting it through that path would label a
model's reading as hand-typed and attribute it to somebody who never saw the page. That is
a provenance lie, and provenance is the one thing this system sells.

So `extract_document` returns the decision and writes no figures. `decision.status` is the
instruction and the caller carries it out - which today means nothing does, because the
`llm_hybrid` write path has still to be built. The two paths share a great deal (the
statement row, the permitted-key check, the refuse-if-already-entered guard, the
parse-everything-before-writing ordering) and differ on the two fields that matter most, so
the right shape is a shared writer rather than a flag on either - and that is a decision to
make deliberately, not in passing.

## Every run leaves a row

An `extraction_jobs` row is written whatever happens - including for a response that could
not be parsed at all. A document the pipeline choked on and left no trace of is
indistinguishable from one nobody ever tried, which is the same blindness `docs/10` §5.3
describes for connectors, one layer up.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Sequence
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Protocol, runtime_checkable

import structlog
from sqlalchemy.orm import Session

from packages.common.models import ExtractionJob
from packages.common.timez import utcnow
from packages.extract.budget import BudgetExceededError, raise_if_halted, record_spend
from packages.extract.contract import (
    ContractViolationError,
    Extraction,
    Finding,
    grounding_findings,
    parse_extraction,
)
from packages.extract.pdf import PageRead, read_pages
from packages.extract.routing import STORED, RoutingDecision, route
from packages.normalize.chart import ChartVersion, load_chart
from packages.normalize.validation import ValidationReport, validate_candidate

__all__ = [
    "EXTRACTION_METHOD",
    "SOURCE_SYSTEM",
    # Re-exported so a caller can catch the one exception this raises without
    # importing the budget module to do it.
    "BudgetExceededError",
    "UNREADABLE",
    "ExtractionOutcome",
    "ModelCall",
    "Reconciler",
    "extract_document",
]

_log = structlog.get_logger(__name__)

#: `statement_line_items.extraction_method` and `extraction_jobs.method` for this path.
#: `docs/08` §5's vocabulary is `manual` | `llm_hybrid` | `xbrl`, and hybrid is what P4.1
#: describes: deterministic tools read the page, the model only reconciles.
EXTRACTION_METHOD = "llm_hybrid"

#: Which `account_mappings.source_system` this path resolves against. `manual` and
#: `llm_hybrid` both read Nigerian IFRS labels off a page, so they share one vocabulary -
#: `packages.normalize.chart.SOURCE_SYSTEM_BY_METHOD` is where that is decided.
SOURCE_SYSTEM = "ng_ifrs_label"

#: The response did not parse. Not one of P4's three statuses because it is not an
#: extraction at all - but it still needs a human, and it still needs a row.
UNREADABLE = "unreadable"


@dataclass(frozen=True)
class ModelCall:
    """What the model returned and what it cost. Everything billing needs, in one place."""

    #: The raw response text, exactly as returned. Parsed by `parse_extraction`, not here.
    response: str
    input_tokens: int
    output_tokens: int
    cost_usd: Decimal
    #: True when this came from the content-hash cache rather than the API. `docs/02` §10
    #: item 2; a hit costs nothing and must not count against the cap.
    cache_hit: bool = False


@runtime_checkable
class Reconciler(Protocol):
    """The one box in P4.1's flowchart that needs an API key.

    Deliberately narrow. It is handed pages that have already been read and classified, and
    returns text; it does not fetch, parse, validate, store or decide. Everything it could
    get wrong is checked by something downstream that does not share its opinions.

    `estimate_usd` runs *before* the call, because the budget gate needs a number to add to
    the month's spend and a limit enforced after the fact is an audit.

    `runtime_checkable` so a test can assert an implementation satisfies it. That only
    checks the members are present, not their signatures - but a missing `estimate_usd` is
    the drift that would surface as an `AttributeError` on the first real document, at
    the moment an API key finally exists and nobody is looking for a typo.
    """

    model_name: str
    prompt_version: str

    def estimate_usd(self, pages: Sequence[PageRead]) -> Decimal:
        """Roughly what reconciling these pages will cost, before doing it."""
        ...

    def reconcile(
        self, pages: Sequence[PageRead], *, company: str, period_end: dt.date
    ) -> ModelCall:
        """Text and tables in, one JSON statement out. See `docs/03` P4.2 for the contract."""
        ...


@dataclass(frozen=True)
class ExtractionOutcome:
    """What happened to one document, and every artefact that decided it."""

    job_id: int
    status: str
    #: `None` when the response did not parse, which is the only case where there is none.
    extraction: Extraction | None
    decision: RoutingDecision | None
    validation: ValidationReport | None
    grounding: tuple[Finding, ...] = ()
    pages_read: int = 0
    cost_usd: Decimal = Decimal(0)
    #: Populated for `UNREADABLE`; the parser's own message, which names the field.
    error: str | None = None
    failures: list[str] = field(default_factory=list)

    @property
    def stored(self) -> bool:
        return self.status == STORED


def extract_document(
    session: Session,
    *,
    document_id: int,
    pdf_bytes: bytes,
    company_id: int,
    company_name: str,
    period_type: str,
    period_end: dt.date,
    fiscal_year: int,
    reconciler: Reconciler,
    principal_id: int,
    chart_version: str = "v1",
    required_keys: frozenset[str] | None = None,
    max_pages: int | None = None,
) -> ExtractionOutcome:
    """One PDF through P4.1's pipeline, up to but not including the write.

    Returns what should happen rather than doing it. A `STORED` outcome is this pipeline
    saying *no human is needed here*; `decision.status` is the instruction, and the caller
    carries it out.

    Today no caller does, because the `llm_hybrid` write path has still to be built -
    `enter_statement` cannot serve as it, for the reason in the module docstring. Nothing
    here is blocked on that: the decision is the useful artefact and the `extraction_jobs`
    row records it either way.

    Raises `BudgetExceededError` before calling the model, and nothing else: every other
    failure is recorded on the job row and returned, because a document that fell over is
    one somebody has to look at and an exception that escapes here would take the
    `extraction_jobs` row with it.
    """
    started_at = utcnow()
    pages = read_pages(pdf_bytes, pages=max_pages)
    page_text = {page.page_number: page.text for page in pages}
    page_kinds = [page.kind for page in pages]

    # Before the call, not after. `docs/02` §10: halt, do not continue billing.
    raise_if_halted(
        session, principal_id=principal_id, estimated_usd=reconciler.estimate_usd(pages)
    )

    call = reconciler.reconcile(pages, company=company_name, period_end=period_end)
    record_spend(
        session,
        principal_id=principal_id,
        job_kind="extraction",
        model=reconciler.model_name,
        prompt_version=reconciler.prompt_version,
        input_tokens=call.input_tokens,
        output_tokens=call.output_tokens,
        cost_usd=call.cost_usd,
        source_document_id=document_id,
        cache_hit=call.cache_hit,
    )

    try:
        extraction = parse_extraction(call.response)
    except ContractViolationError as exc:
        # A row even here. A document the pipeline choked on and left no trace of looks
        # exactly like one nobody ever tried.
        _log.warning("extraction_unreadable", document=document_id, reason=str(exc))
        failures = [f"unreadable_response: {exc}"]
        return ExtractionOutcome(
            job_id=_finish(
                session,
                document_id=document_id,
                reconciler=reconciler,
                started_at=started_at,
                status=UNREADABLE,
                confidence=None,
                failures=failures,
                cost_usd=call.cost_usd,
            ),
            status=UNREADABLE,
            extraction=None,
            decision=None,
            validation=None,
            pages_read=len(pages),
            cost_usd=call.cost_usd,
            error=str(exc),
            failures=failures,
        )

    # Grounding first, and against the value exactly as the model reported it - which is
    # the value as printed. Normalising before this would compare a translated figure
    # against the page and call a real sign error a match.
    grounding = tuple(grounding_findings(extraction, page_text))

    chart = load_chart(session, version=chart_version, source_system=SOURCE_SYSTEM)
    if required_keys is None:
        required_keys = frozenset(
            key for key, account in chart.accounts.items() if account.is_required
        )
    validation = validate_candidate(
        session,
        company_id=company_id,
        period_type=period_type,
        period_end=period_end,
        figures=_figures_of(extraction, chart),
        fiscal_year=fiscal_year,
    )
    decision = route(
        extraction,
        validation=validation,
        page_kinds=page_kinds,
        required_keys=required_keys,
        grounding=grounding,
    )
    failures = [result.name for result in validation.failures]
    failures += [f"{finding.kind}:{finding.canonical_key}" for finding in grounding]
    return ExtractionOutcome(
        job_id=_finish(
            session,
            document_id=document_id,
            reconciler=reconciler,
            started_at=started_at,
            status=decision.status,
            confidence=decision.confidence,
            failures=failures,
            cost_usd=call.cost_usd,
        ),
        status=decision.status,
        extraction=extraction,
        decision=decision,
        validation=validation,
        grounding=grounding,
        pages_read=len(pages),
        cost_usd=call.cost_usd,
        failures=failures,
    )


def _figures_of(
    extraction: Extraction, chart: ChartVersion
) -> dict[tuple[str, str], Decimal | None]:
    """`(statement_type, canonical_key) -> value`, in reporting units and the stored sign.

    `in_reporting_units` applies `unit_multiplier` here and only here. A candidate handed to
    the identities still carrying it unapplied fails every one of them by a factor of a
    thousand, which reads as a catastrophic extraction rather than as the units mistake it
    is - and the cross-year check, the one that exists to catch exactly this, would be
    reporting the error it was built to prevent.

    The statement type comes from the extraction's own `statement` field, normalised to the
    vocabulary the identities use.
    """
    kind = _statement_kind(extraction.statement)
    return {
        (kind, item.canonical_key): _stored_sign(
            extraction.in_reporting_units(item), chart, item.canonical_key
        )
        for item in extraction.line_items
    }


def _stored_sign(value: Decimal | None, chart: ChartVersion, canonical_key: str) -> Decimal | None:
    """The figure in the sign the column holds, rather than the sign the page printed.

    A statement prints cost of sales as `(1,120,000)`. The contract says `value` is what is
    printed, so the model reports -1,120,000 and grounding confirms it against the page -
    and then the store wants +1,120,000. Of 2,068 `cost_of_revenue` rows, every one is
    positive; `chart_of_accounts.sign_convention` declares that for the key.

    Translating rather than asking the model to do it, for two reasons. A schema convention
    is not something a model can verify and the page contradicts it, so the instruction
    would be fighting the evidence. And a translated figure cannot be grounded - the page
    shows brackets - so doing it in the prompt would mean giving up the strongest check
    available in exchange for the weakest possible guarantee.

    Only `positive` and `negative` translate. `either` is left exactly alone: a loss is
    negative, a gain is positive, and both are real - that is what `either` means, and
    forcing a sign on it is how a ₦400bn loss becomes a ₦400bn profit.
    """
    if value is None:
        return None
    account = chart.accounts.get(canonical_key)
    if account is None or account.sign_convention == "either":
        return value
    if account.sign_convention == "positive":
        return abs(value)
    if account.sign_convention == "negative":
        return -abs(value)
    return value


#: `Extraction.statement` is the model's word for the statement; the identities are keyed on
#: `statements.statement_type`. Mapped explicitly rather than by prefix matching, so an
#: unrecognised word falls through to something a reader can see rather than to `balance`.
_STATEMENT_KINDS = {
    "income_statement": "income",
    "income": "income",
    "profit_or_loss": "income",
    "balance_sheet": "balance",
    "balance": "balance",
    "financial_position": "balance",
    "cash_flow": "cashflow",
    "cashflow": "cashflow",
    "cash_flows": "cashflow",
}


def _statement_kind(reported: str) -> str:
    """The identities' vocabulary, or the model's own word left visible.

    An unrecognised statement name is returned unchanged rather than guessed at. Every
    identity then finds nothing under it and reports `NOT_CHECKABLE`, which routes the
    extraction to a human - the right outcome, and one that shows the unmapped word in the
    figures rather than silently filing a cash flow under `balance`.
    """
    return _STATEMENT_KINDS.get(reported.strip().lower(), reported.strip().lower())


def _finish(
    session: Session,
    *,
    document_id: int,
    reconciler: Reconciler,
    started_at: dt.datetime,
    status: str,
    confidence: Decimal | None,
    failures: list[str],
    cost_usd: Decimal,
) -> int:
    """Write the `extraction_jobs` row and return its id. Every path calls this."""
    job = ExtractionJob(
        source_document_id=document_id,
        method=EXTRACTION_METHOD,
        model_name=reconciler.model_name,
        prompt_version=reconciler.prompt_version,
        status=status,
        confidence=confidence,
        validation_failures=failures,
        token_cost_usd=cost_usd,
        started_at=started_at,
        finished_at=utcnow(),
    )
    session.add(job)
    session.flush()
    if status != STORED:
        _log.info(
            "extraction_needs_a_human",
            job=job.id,
            document=document_id,
            status=status,
            confidence=str(confidence) if confidence is not None else None,
            failures=failures[:6],
        )
    return job.id

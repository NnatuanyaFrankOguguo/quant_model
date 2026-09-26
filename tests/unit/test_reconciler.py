"""`packages.extract.reconciler`: everything about the model call except the call. P4.2.

The prompt, the page rendering, the cost estimate and the refusal when no key is set are
all deterministic, so all of them are covered here without an API key and without a
network. The one line that is not is `client.messages.create`, and it is kept to one line
for exactly that reason.

The prompt is the part where most of the quality lives, and `docs/03` P4.2 specifies it
word for word with a rationale attached to every clause - so the first test is simply that
it still says what the document says.
"""

from __future__ import annotations

import datetime as dt
from decimal import Decimal
from pathlib import Path

import pytest

from packages.extract.pdf import BLANK, MIXED, NATIVE, PageRead, read_pages
from packages.extract.reconciler import (
    MAX_PAGE_CHARS,
    PROMPT_VERSION,
    SYSTEM_PROMPT,
    ClaudeReconciler,
    MissingApiKeyError,
    ModelPricing,
    render_pages,
)

pytestmark = pytest.mark.invariant

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"
REAL_REPORT = FIXTURES / "pdf" / "dmo_auction_september_2026.pdf"

#: Round numbers, so an arithmetic slip in a test is visible rather than plausible.
PRICING = ModelPricing(input_per_million_usd=Decimal("10"), output_per_million_usd=Decimal("50"))


def reconciler(**kwargs: object) -> ClaudeReconciler:
    return ClaudeReconciler(api_key="test-key", pricing=PRICING, **kwargs)  # type: ignore[arg-type]


def page(
    number: int,
    *,
    kind: str = NATIVE,
    text: str = "Revenue 1,000",
    tables: tuple = (),
) -> PageRead:
    return PageRead(
        page_number=number,
        kind=kind,
        characters=len(text),
        images=0,
        largest_image_share=0.0,
        text=text,
        tables=tables,
    )


# --------------------------------------------------------------------------------------
# The prompt
# --------------------------------------------------------------------------------------


def test_the_system_prompt_is_the_one_the_document_specifies() -> None:
    """`docs/03` P4.2 gives the prompt verbatim and a reason for every clause.

    Asserted phrase by phrase rather than as one string, so a diff says *which* constraint
    went missing - and each of them is switching off a specific failure, not a style.
    """
    for clause in (
        "ONE company's",  # parent mixed with group
        "never infer/estimate/fill gaps",  # a plausible fabricated number
        "verbatim label as printed",  # a mapping a human can verify
        "source page",  # provenance at the point of extraction
        "If absent, use null",  # nulls, never zeros
        "unit_multiplier",  # the thousands/millions trap
    ):
        assert clause in SYSTEM_PROMPT, f"the prompt no longer says {clause!r}"


def test_the_user_turn_names_the_company_and_the_period() -> None:
    """P4.2's first constraint is *"ONE company's statements"*, and a Nigerian annual
    report carries the parent's and the group's side by side. Leaving it implicit asks the
    model to guess which one the caller meant."""
    prompt = reconciler().user_prompt([page(1)], "MTN Nigeria Plc", dt.date(2024, 12, 31))
    assert "MTN Nigeria Plc" in prompt
    assert "2024-12-31" in prompt


def test_the_prompt_version_is_recorded_on_the_instance() -> None:
    """It reaches `extraction_jobs.prompt_version` and `llm_spend.prompt_version`, and the
    content-hash cache is keyed partly on it: an unchanged version against a changed prompt
    serves a stale answer and reports a cache hit."""
    assert reconciler().prompt_version == PROMPT_VERSION


# --------------------------------------------------------------------------------------
# What the model is shown
# --------------------------------------------------------------------------------------


def test_every_page_is_labelled_with_its_number() -> None:
    """The model has to cite a page, and cannot cite one it was not told.

    Without this the `source page` field is a guess, and `page` is the column a reviewer
    opens to check a figure.
    """
    rendered = render_pages([page(1), page(7), page(94)])
    assert "--- PAGE 1 (native) ---" in rendered
    assert "--- PAGE 7 (native) ---" in rendered
    assert "--- PAGE 94 (native) ---" in rendered


def test_a_blank_page_is_not_sent() -> None:
    """It carries nothing, and forty of them cost real money to establish that."""
    rendered = render_pages([page(1), page(2, kind=BLANK, text=""), page(3)])
    assert "PAGE 2" not in rendered
    assert "PAGE 1" in rendered and "PAGE 3" in rendered


def test_a_partially_readable_page_is_still_sent_and_says_so() -> None:
    """`MIXED` means the figures are in the part we could not read.

    Dropping it would hide the page entirely; sending it with its classification lets the
    model see there is a page there, and lets a reader of the prompt see why the answer
    from it was thin. The caller already knows from `page.kind` that OCR is owed.
    """
    rendered = render_pages([page(5, kind=MIXED, text="Statement of financial position")])
    assert "--- PAGE 5 (mixed) ---" in rendered


def test_tables_are_rendered_as_markdown_beside_the_text() -> None:
    """`docs/03` P4.1 asks for *"text + Markdown tables"* because a model reads a pipe
    table far more reliably than columns held together by spacing."""
    rendered = render_pages([page(1, tables=((("Revenue", "1,000"), ("Cost", "(400)")),))])
    assert "| Revenue | 1,000 |" in rendered
    assert "| --- | --- |" in rendered


def test_a_very_long_page_is_truncated_rather_than_sent_whole() -> None:
    """A page of dense notes should not decide the month's budget.

    A cap on what is sent, not a judgement about what matters on the page: the statements
    themselves run to a few thousand characters and sit far under it.
    """
    rendered = render_pages([page(1, text="x" * (MAX_PAGE_CHARS * 3))])
    assert len(rendered) < MAX_PAGE_CHARS * 2


def test_a_real_filing_renders_with_its_figures_intact() -> None:
    """The DMO auction page, through the real reader, into the real prompt."""
    rendered = render_pages(read_pages(REAL_REPORT.read_bytes()))
    assert "--- PAGE 1 (native) ---" in rendered
    assert "DEBT MANAGEMENT OFFICE" in rendered
    assert "Tables on this page:" in rendered


# --------------------------------------------------------------------------------------
# Cost
# --------------------------------------------------------------------------------------


def test_the_price_is_supplied_rather_than_compiled_in() -> None:
    """A price constant goes stale without failing: it bills correctly and reports the
    wrong figure, and every cost-per-document trend built on it is wrong the same way.

    `docs/02` §10 makes cost per document the metric to watch, so the number it is computed
    from has to be one somebody set on purpose.
    """
    assert PRICING.cost(input_tokens=1_000_000, output_tokens=0) == Decimal("10")
    assert PRICING.cost(input_tokens=0, output_tokens=1_000_000) == Decimal("50")
    assert PRICING.cost(input_tokens=500_000, output_tokens=200_000) == Decimal("15")


def test_the_estimate_assumes_the_full_output_allowance() -> None:
    """Deliberately pessimistic, because the gate it feeds must not be crossed.

    An estimate that came in under the real cost would let the last call of the month go
    over the cap - the one thing `docs/02` §10 says must not happen. Cheap to be wrong in
    this direction; the cost of being wrong in the other is the thing the cap exists for.
    """
    small = reconciler(max_output_tokens=1_000).estimate_usd([page(1, text="Revenue 1,000")])
    # 1,000 output tokens at $50/M is $0.05 before the input is counted at all.
    assert small > Decimal("0.05")


def test_more_pages_cost_more() -> None:
    """The estimate has to move with the document, or the gate is a constant."""
    one = reconciler().estimate_usd([page(1, text="a" * 4_000)])
    many = reconciler().estimate_usd([page(n, text="a" * 4_000) for n in range(1, 11)])
    assert many > one


def test_a_blank_page_costs_nothing_to_estimate() -> None:
    """It is not sent, so it must not be priced - otherwise the estimate charges for
    tokens that will never be spent and the cap closes early."""
    with_blank = reconciler().estimate_usd([page(1), page(2, kind=BLANK, text="")])
    without = reconciler().estimate_usd([page(1)])
    assert with_blank == without


# --------------------------------------------------------------------------------------
# No key
# --------------------------------------------------------------------------------------


def test_no_key_is_refused_at_the_moment_of_use_not_at_import(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Absent is a legitimate state for the rest of the system.

    The deterministic half of the pipeline runs without a key and the manual entry path
    (P3.2) needs none at all - which is the point of having it. So importing this module,
    constructing the reconciler and estimating a cost must all work; only reaching for the
    key fails, and it says what to do.
    """
    bare = ClaudeReconciler(pricing=PRICING)
    assert bare.estimate_usd([page(1)]) > 0  # no key needed to get this far

    monkeypatch.setattr(
        "packages.common.config.get_settings",
        lambda: type("S", (), {"anthropic_api_key": None})(),
    )
    with pytest.raises(MissingApiKeyError, match="ANTHROPIC_API_KEY is not set"):
        _ = bare.api_key


def test_an_explicit_key_beats_the_environment() -> None:
    """So a caller can run two reconcilers against different keys - and so the tests do
    not depend on what happens to be in the environment."""
    assert reconciler().api_key == "test-key"


def test_the_implementation_satisfies_the_protocol_the_pipeline_expects() -> None:
    """Drift between the two would surface as an `AttributeError` on the first real
    document - at the moment a key finally exists and nobody is looking for a typo.

    `runtime_checkable` only proves the members are present, not that their signatures
    agree; the tests above cover `estimate_usd` and `model_name` behaviourally, and
    `reconcile` is the one line that needs a key to exercise.
    """
    from packages.extract.pipeline import Reconciler

    assert isinstance(reconciler(), Reconciler)
    assert callable(reconciler().reconcile)

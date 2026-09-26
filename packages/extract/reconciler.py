"""The one box in P4.1's flowchart that needs an API key. P4.2.

`docs/03` P4.2 specifies the system prompt and then tabulates what each of its constraints
prevents, which is the rare case of a prompt with a rationale attached to every clause. It
is reproduced here **verbatim**, as `SYSTEM_PROMPT`, and the table is in this docstring so
that the next person to edit a clause can see what they would be switching off.

* **"ONE company's statements"** - mixing the parent's figures with the group's, which
  sit in the same PDF.
* **"never infer/estimate/fill gaps"** - the most dangerous behaviour available here, a
  plausible fabricated number.
* **"verbatim label as printed"** - lets a human verify a mapping without reopening the PDF.
* **"source page"** - `CLAUDE.md`'s provenance rule, at the point of extraction.
* **"If absent, use null"** - nulls, never zeros.
* **"`unit_multiplier`"** - the thousands/millions trap (TG2, `OPERATIONS.md` §1.6).

## What is testable here without a key, and what is not

Everything except the request. The prompt assembly, the page rendering, the cost estimate
and the refusal when no key is configured are all deterministic and all covered. The one
untested line is the SDK call itself, and it is kept to one line for exactly that reason.

## Why the pages are rendered rather than the PDF uploaded

`docs/03` P4.1's table is explicit that Claude's PDF mode is for *"messy, borderless,
scanned pages"* and **not** for *"reading every page - cost"*. The deterministic tools
have already read the text and the tables; sending the file again would pay a second time
for work already done and give up the page-level provenance that `packages.extract.pdf`
produced. So the model receives text and Markdown tables, per page, with the page number
attached - which is also what makes `source page` answerable at all.

Pages classified `BLANK` are dropped. They carry nothing, and a model given forty empty
pages spends tokens establishing that.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal

import structlog

from packages.extract.pdf import BLANK, PageRead, to_markdown
from packages.extract.pipeline import ModelCall

__all__ = [
    "DEFAULT_MODEL",
    "PROMPT_VERSION",
    "SYSTEM_PROMPT",
    "ClaudeReconciler",
    "MissingApiKeyError",
    "ModelPricing",
    "render_pages",
]

_log = structlog.get_logger(__name__)

#: `docs/03` P4.2, word for word. Changing a clause switches off the failure it prevents -
#: the table in the module docstring says which.
SYSTEM_PROMPT = (
    "You are a financial-statement data extractor. You receive text and tables from ONE "
    "company's audited statements. Extract ONLY numbers present in the source; never "
    "infer/estimate/fill gaps. Return JSON per schema. For each line item include source "
    "page and the verbatim label as printed. If absent, use null. Report values in the "
    "reporting currency/units exactly as stated, plus a `unit_multiplier`."
)

#: Recorded on every `extraction_jobs` row and every `llm_spend` row. Bump it whenever
#: `SYSTEM_PROMPT` or `render_pages` changes, because `docs/02` §10's content-hash cache is
#: keyed partly on it - an unchanged version against a changed prompt serves a stale answer
#: and reports a cache hit, which looks like the cache working unusually well.
PROMPT_VERSION = "p4.2-v1"

#: The reconciliation is the expensive, judgement-heavy step P4.1 reserves a capable model
#: for; the cheap tools have already done the reading. `SPEC.md` §2E's tiering puts a
#: Haiku-class model on ticker tagging and bulk sentiment, not here.
DEFAULT_MODEL = "claude-opus-5"

#: How many characters of one page's text to send. A statement page is a few thousand; the
#: cap is a guard against a page of dense notes blowing the budget estimate, not a
#: judgement about what matters on it.
MAX_PAGE_CHARS = 12_000


class MissingApiKeyError(RuntimeError):
    """No `ANTHROPIC_API_KEY`. Refused rather than run, like the FRED connector before it."""


@dataclass(frozen=True)
class ModelPricing:
    """Dollars per million tokens, supplied rather than hardcoded.

    Prices change and a constant compiled into a module goes stale silently - it would not
    fail, it would bill correctly and report the wrong figure, and every cost-per-document
    trend built on it would be wrong in the same direction. `docs/02` §10 makes cost per
    document the metric to watch, so the number it is computed from has to be one somebody
    set deliberately.
    """

    input_per_million_usd: Decimal
    output_per_million_usd: Decimal

    def cost(self, *, input_tokens: int, output_tokens: int) -> Decimal:
        return (
            Decimal(input_tokens) * self.input_per_million_usd
            + Decimal(output_tokens) * self.output_per_million_usd
        ) / Decimal(1_000_000)


def render_pages(pages: Sequence[PageRead]) -> str:
    """Pages as text and Markdown tables, each one labelled with its number.

    The page number is in the text because the model has to cite it, and a model that
    cannot see which page it is reading cannot answer the `source page` field that
    `CLAUDE.md`'s provenance rule turns into a reviewer's starting point.

    Blank pages are dropped; they carry nothing and a model given forty of them spends
    tokens establishing that. `MIXED` and `SCANNED` pages are kept, with what little text
    they have: the caller already knows from `page.kind` that OCR is owed, and sending the
    header is better than sending nothing while that is pending.
    """
    blocks: list[str] = []
    for page in pages:
        if page.kind == BLANK:
            continue
        body = page.text.strip()[:MAX_PAGE_CHARS]
        tables = "\n\n".join(to_markdown(table) for table in page.tables if table)
        section = [f"--- PAGE {page.page_number} ({page.kind}) ---"]
        if body:
            section.append(body)
        if tables:
            section.append("Tables on this page:\n" + tables)
        blocks.append("\n".join(section))
    return "\n\n".join(blocks)


class ClaudeReconciler:
    """`packages.extract.pipeline.Reconciler`, against the Anthropic API.

    The SDK is imported inside the call rather than at module scope, for the same reason
    `packages.ingestion.documents` defers `pdfplumber`: `anthropic` lives in the `data`
    extra and is not installed in CI, and a module-level import would make importing the
    *pipeline* fail on a machine that is only running tests.
    """

    def __init__(
        self,
        *,
        api_key: str | None = None,
        model_name: str = DEFAULT_MODEL,
        pricing: ModelPricing,
        max_output_tokens: int = 8_000,
        timeout_sec: float = 300.0,
    ) -> None:
        self._api_key = api_key
        self.model_name = model_name
        self.prompt_version = PROMPT_VERSION
        self._pricing = pricing
        self._max_output_tokens = max_output_tokens
        self._timeout = timeout_sec

    @property
    def api_key(self) -> str:
        """The key, or a refusal that says how to fix it.

        Absent is a legitimate state for the rest of the system - the manual entry path
        (P3.2) needs no key at all, which is the point of having it - so this refuses at
        the moment of use rather than at import.
        """
        from packages.common.config import get_settings  # noqa: PLC0415 - deferred

        key = self._api_key or getattr(get_settings(), "anthropic_api_key", None)
        if not key:
            raise MissingApiKeyError(
                "ANTHROPIC_API_KEY is not set, so the reconciliation step cannot run. The "
                "deterministic half of the pipeline needs no key; the manual entry path "
                "(P3.2) needs none either."
            )
        return str(key)

    def estimate_usd(self, pages: Sequence[PageRead]) -> Decimal:
        """What this call will roughly cost, before the budget gate decides.

        Input tokens are estimated from the rendered prompt at four characters each, which
        is the usual English approximation and is close enough for a gate whose job is to
        stop a runaway loop rather than to invoice. Output is assumed to be the full
        `max_output_tokens`, deliberately: an estimate that came in under the real cost
        would let the last call of the month cross the cap, which is the one thing
        `docs/02` §10 says must not happen.
        """
        rendered = render_pages(pages)
        input_tokens = (len(SYSTEM_PROMPT) + len(rendered)) // 4
        return self._pricing.cost(input_tokens=input_tokens, output_tokens=self._max_output_tokens)

    def reconcile(
        self, pages: Sequence[PageRead], *, company: str, period_end: dt.date
    ) -> ModelCall:
        """One statement's worth of pages in, one JSON object out.

        The company and the period are stated in the user turn rather than left implicit,
        because P4.2's first constraint is *"ONE company's statements"* and a Nigerian
        annual report carries the parent's and the group's side by side.
        """
        import anthropic  # noqa: PLC0415 - `data` extra; see the class docstring

        client = anthropic.Anthropic(api_key=self.api_key, timeout=self._timeout)
        response = client.messages.create(
            model=self.model_name,
            max_tokens=self._max_output_tokens,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": self.user_prompt(pages, company, period_end)}],
        )
        text = "".join(block.text for block in response.content if block.type == "text")
        usage = response.usage
        cost = self._pricing.cost(
            input_tokens=usage.input_tokens, output_tokens=usage.output_tokens
        )
        _log.info(
            "reconciled",
            model=self.model_name,
            prompt_version=self.prompt_version,
            pages=len(pages),
            input_tokens=usage.input_tokens,
            output_tokens=usage.output_tokens,
            cost_usd=str(cost),
        )
        return ModelCall(
            response=text,
            input_tokens=usage.input_tokens,
            output_tokens=usage.output_tokens,
            cost_usd=cost,
        )

    def user_prompt(self, pages: Sequence[PageRead], company: str, period_end: dt.date) -> str:
        """The turn that carries the document and says which company and period it is for.

        Separate from `reconcile` so it can be read, diffed and tested without an API key -
        which is most of what there is to get wrong here.
        """
        return (
            f"Company: {company}\n"
            f"Period end: {period_end.isoformat()}\n"
            f"\n"
            f"Return one JSON object with the fields: company, period_end (ISO date), "
            f"currency (ISO 4217), unit_multiplier, statement, line_items, and optionally "
            f"extraction_notes. Each line item needs canonical_key, as_printed, value, "
            f"page and confidence.\n"
            f"\n"
            f"{render_pages(pages)}"
        )

"""Reading a page without guessing what is on it. P4.1, first branch.

`docs/03` P4.1's flowchart opens on a decision, and everything downstream depends on
getting it right:

    PDF arrives --> Native text layer or scanned?
      native  --> PyMuPDF4LLM / pdfplumber, text + Markdown tables - cheap
      scanned --> OCR: tesseract + OpenCV

Both wrong answers cost something, and they cost differently. A native page sent to OCR is
money and latency spent re-reading text that was already there. A **scanned page sent to
the text path returns nothing and says so in no way at all** - an empty string is a
perfectly valid result for a blank page, so the pipeline carries on, the reconciler is
handed nothing to reconcile, and the figures that page held are simply absent from the
company forever. That is the failure this module is shaped around.

## The case that makes a naive check wrong

"Has a text layer" is not a yes or no. Nigerian annual reports routinely carry pages that
are a scanned image of a statement with a *text* header stamped over it - a page number, a
running title, sometimes a footer added by the filing system. `extract_text()` on such a
page returns forty usable characters out of a page holding two hundred figures, and a check
that asks "is there any text?" answers yes with total confidence.

So the question asked here is not whether there is text but whether there is *enough* text
for the ink on the page. `MIXED` is a real answer and it means "some of this page is
readable and some of it is not, and the unreadable part is the part with the numbers in
it". It routes to OCR like a scan, and it is reported separately so a run that produces a
lot of them is visible as a toolchain problem rather than as missing data.

## Nulls, never zeros - at the first stage, not the last

`pdfplumber` returns `None` for a cell it found no text in. Those stay `None` all the way
through `to_markdown`, which renders them as an empty cell. A `0` would be a number, and a
number that arrives here is one a reconciler will believe, map to a canonical key and store
with a page citation. `SPEC.md` §4.1's rule against fabricated figures starts here, at the
point where the temptation is smallest and the habit is cheapest to keep.

## Why pdfplumber alone

`docs/03` P4.1's table gives PyMuPDF the fast text dump and pdfplumber the coordinate-level
control. Only pdfplumber is installed in CI (`pyproject.toml`'s `dev` extra, added in P3
when `packages/ingestion/documents.py` landed), so building on it keeps this testable in CI
today. PyMuPDF is a speed optimisation over the same output, and adding it is a dependency
decision with a CI cost, which belongs in the change that needs the speed.
"""

from __future__ import annotations

import io
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

import structlog

if TYPE_CHECKING:  # pragma: no cover - import only for type checking
    from collections.abc import Iterator

__all__ = [
    "BLANK",
    "MIXED",
    "NATIVE",
    "SCANNED",
    "PageRead",
    "PdfReadError",
    "classify",
    "read_pages",
    "to_markdown",
]

_log = structlog.get_logger(__name__)

#: A text layer dense enough to read the page from. Goes down the cheap path.
NATIVE = "native"
#: No usable text and something large drawn on the page. Needs OCR.
SCANNED = "scanned"
#: Some text, but far too little for a page this full - the header-stamped-on-a-scan case.
#: Needs OCR *as well*, and the text that is there is not evidence the rest was read.
MIXED = "mixed"
#: Neither text nor a large image. A separator, a tab page, the back of a cover.
BLANK = "blank"

#: Characters below which a page is not carrying a statement.
#:
#: A financial statement page runs to thousands of characters; the sparsest real one - a
#: heading and a short note - still clears a few hundred. A running header plus a page
#: number is a few dozen. One hundred sits in the gap, and the gap is wide, which is what
#: makes the threshold safe to state plainly rather than tune.
MIN_NATIVE_CHARS = 100

#: Share of the page an image must cover before it is treated as the page's content rather
#: than decoration. A logo or a signature scan is a few per cent; a scanned statement is
#: most of the sheet. Half is comfortably between them.
FULL_PAGE_IMAGE_SHARE = 0.5


class PdfReadError(ValueError):
    """The bytes are not a PDF this library can open."""


@dataclass(frozen=True)
class PageRead:
    """One page, as read, with the evidence for how it was classified.

    The counts are kept rather than discarded because `kind` is a judgement and a reader
    who disagrees with it should be able to see what it was made from. A run that produces
    unexpected `MIXED` pages is diagnosed from these numbers.
    """

    #: One-based, as a reader counts and as the `page` provenance column expects. The most
    #: likely off-by-one in the whole pipeline, so it is fixed here and documented here.
    page_number: int
    kind: str
    characters: int
    images: int
    #: The largest image's share of the page, 0.0 when there are none.
    largest_image_share: float
    text: str
    #: Rows of cells, with `None` for a cell that held no text. Never `""` and never `0`.
    tables: tuple[tuple[tuple[str | None, ...], ...], ...]

    @property
    def needs_ocr(self) -> bool:
        """`SCANNED` and `MIXED` both do. `MIXED` is the one that is easy to forget."""
        return self.kind in (SCANNED, MIXED)

    @property
    def is_readable(self) -> bool:
        """Whether the text on this page can be trusted to be the whole of it."""
        return self.kind == NATIVE


def classify(*, characters: int, largest_image_share: float) -> str:
    """Which path this page belongs on, from what was found on it.

    Separated from the reading so the rule can be tested directly on numbers, without
    building a PDF that happens to produce them. The rule is the part that has to be right;
    `pdfplumber` producing the counts is not in doubt.
    """
    covered = largest_image_share >= FULL_PAGE_IMAGE_SHARE
    if characters >= MIN_NATIVE_CHARS:
        # Enough text to read, whatever else is on the page. A statement printed over a
        # faint full-page watermark is still a statement.
        return NATIVE
    if covered:
        # The decision this module exists for. Below the threshold with the page covered,
        # the text that IS here is a header or a stamp, and treating it as the page's
        # content loses everything the image holds - silently, because a short string is
        # not an error.
        return SCANNED if characters == 0 else MIXED
    return NATIVE if characters else BLANK


def read_pages(data: bytes, *, pages: int | None = None) -> list[PageRead]:
    """Every page, classified, with its text and tables. Reads the whole file into memory.

    `pages` caps how many are read, for a caller sampling the front of a 400-page report
    rather than paying for all of it. Capping changes nothing about the pages returned.
    """
    return list(iter_pages(data, pages=pages))


def iter_pages(data: bytes, *, pages: int | None = None) -> Iterator[PageRead]:
    """`read_pages`, lazily, for a 400-page report that does not fit comfortably at once."""
    import pdfplumber  # noqa: PLC0415 - deferred so importing this module needs no PDF stack

    if pages is not None and pages <= 0:
        raise ValueError(f"pages must be positive when given, got {pages}")
    try:
        document = pdfplumber.open(io.BytesIO(data))
    except Exception as exc:  # noqa: BLE001 - pdfplumber raises several unrelated types
        raise PdfReadError(f"could not open these bytes as a PDF: {exc}") from exc
    with document:
        for index, page in enumerate(document.pages):
            if pages is not None and index >= pages:
                return
            yield _read_page(page, page_number=index + 1)


def _read_page(page: Any, *, page_number: int) -> PageRead:  # noqa: ANN401 - pdfplumber page
    text = page.extract_text() or ""
    characters = len(text.strip())
    images = list(getattr(page, "images", []) or [])
    share = _largest_image_share(page, images)
    kind = classify(characters=characters, largest_image_share=share)
    tables = _tables_of(page) if kind in (NATIVE, MIXED) else ()
    if kind == MIXED:
        # Worth a line in the log on its own. A handful across a report is the filing
        # system stamping headers; a page after page of them means the text path is
        # returning almost nothing and the run is quietly producing a fraction of the data.
        _log.warning(
            "page_text_layer_is_partial",
            page=page_number,
            characters=characters,
            image_share=round(share, 3),
        )
    return PageRead(
        page_number=page_number,
        kind=kind,
        characters=characters,
        images=len(images),
        largest_image_share=share,
        text=text,
        tables=tables,
    )


def _largest_image_share(page: Any, images: list[dict[str, Any]]) -> float:  # noqa: ANN401
    """The biggest image's area as a share of the page's.

    Clamped at 1.0: an image can be placed larger than the page it sits on, and a share
    above one would read as a corrupt measurement rather than as a scan bled off the edge.
    """
    page_area = float(page.width or 0) * float(page.height or 0)
    if page_area <= 0 or not images:
        return 0.0
    largest = 0.0
    for image in images:
        width = float(image.get("x1", 0)) - float(image.get("x0", 0))
        height = float(image.get("bottom", 0)) - float(image.get("top", 0))
        largest = max(largest, abs(width) * abs(height))
    return min(largest / page_area, 1.0)


def _tables_of(page: Any) -> tuple[tuple[tuple[str | None, ...], ...], ...]:  # noqa: ANN401
    """Tables as rows of cells, with empty cells left as `None`.

    `pdfplumber` already returns `None` for a cell it found nothing in. The only work here
    is not helpfully turning that into `""` or `0` on the way past.
    """
    try:
        found = page.extract_tables() or []
    except Exception as exc:  # noqa: BLE001 - a malformed table is not a malformed page
        # One unreadable table must not cost the page its text. The reconciler can work
        # from prose; it cannot work from a page that raised.
        _log.warning("table_extraction_failed", page=page.page_number, reason=type(exc).__name__)
        return ()
    return tuple(
        tuple(tuple(cell if cell not in (None, "") else None for cell in row) for row in table)
        for table in found
    )


def to_markdown(table: tuple[tuple[str | None, ...], ...]) -> str:
    """One table as a Markdown grid, for the text handed to the reconciler.

    `docs/03` P4.1 asks for *"text + Markdown tables"* at this stage, because a model reads
    a pipe table far more reliably than it reads columns held together by spacing.

    An empty cell stays empty. The first row becomes the header because that is what a
    Markdown table requires, **not** because this function has decided it is one - a
    borderless financial table often has its labels somewhere else entirely, and working
    out which row is the header is the reconciler's job, with the whole page in front of
    it, not this function's with one table.
    """
    if not table:
        return ""
    width = max(len(row) for row in table)
    rendered = [_row_to_markdown(row, width) for row in table]
    separator = "| " + " | ".join("---" for _ in range(width)) + " |"
    return "\n".join([rendered[0], separator, *rendered[1:]])


def _row_to_markdown(row: tuple[str | None, ...], width: int) -> str:
    cells = [_cell(row[i]) if i < len(row) else "" for i in range(width)]
    return "| " + " | ".join(cells) + " |"


def _cell(value: str | None) -> str:
    """A cell's text with the two characters that would break the grid neutralised.

    A pipe inside a cell ends the cell, and a newline ends the row. Both occur in real
    statements - "Trade and other receivables | net" wrapped across two lines is ordinary -
    and either one silently shifts every figure after it into the wrong column, which is
    the kind of wrong that survives review because the numbers are all real.
    """
    if value is None:
        return ""
    return value.replace("|", "\\|").replace("\n", " ").replace("\r", " ").strip()

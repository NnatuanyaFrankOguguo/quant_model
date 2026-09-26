"""`packages.extract.pdf`: the branch every later stage depends on. P4.1.

`docs/03` P4.1's flowchart opens on "native text layer or scanned?", and the two wrong
answers cost differently. Sending a native page to OCR costs money. Sending a **scanned**
page down the text path costs the data: an empty string is a valid result for a blank page,
so nothing raises, the reconciler is handed nothing, and that page's figures are absent
from the company permanently.

`classify` is tested on numbers directly rather than through built PDFs, because the rule
is the part that has to be right and `pdfplumber` counting characters is not in doubt. The
plumbing around it is then tested on a real Nigerian filing.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from packages.extract.pdf import (
    BLANK,
    FULL_PAGE_IMAGE_SHARE,
    MIN_NATIVE_CHARS,
    MIXED,
    NATIVE,
    SCANNED,
    PdfReadError,
    classify,
    read_pages,
    to_markdown,
)

pytestmark = pytest.mark.invariant

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"
#: A real DMO auction result. Native text, a small logo, one wide table of figures.
REAL_REPORT = FIXTURES / "pdf" / "dmo_auction_september_2026.pdf"


def minimal_pdf(pages: int) -> bytes:
    """A valid PDF with a known number of genuinely empty pages.

    Hand-built, the same way `test_documents.py` builds one, so what the test asserts does
    not depend on the library being asserted about.
    """
    objects = [
        b"1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj\n",
        (
            f"2 0 obj<</Type/Pages/Count {pages}"
            f"/Kids[{' '.join(f'{3 + i} 0 R' for i in range(pages))}]>>endobj\n"
        ).encode(),
    ]
    objects += [
        f"{3 + i} 0 obj<</Type/Page/Parent 2 0 R/MediaBox[0 0 200 200]>>endobj\n".encode()
        for i in range(pages)
    ]
    body = bytearray(b"%PDF-1.4\n")
    offsets = []
    for obj in objects:
        offsets.append(len(body))
        body += obj
    xref_at = len(body)
    body += f"xref\n0 {len(objects) + 1}\n0000000000 65535 f \n".encode()
    for offset in offsets:
        body += f"{offset:010d} 00000 n \n".encode()
    body += (
        f"trailer<</Size {len(objects) + 1}/Root 1 0 R>>\nstartxref\n{xref_at}\n%%EOF\n"
    ).encode()
    return bytes(body)


# --------------------------------------------------------------------------------------
# The rule
# --------------------------------------------------------------------------------------


def test_a_full_page_image_with_no_text_is_a_scan() -> None:
    """The ordinary scanned page. Nothing to read, something to OCR."""
    assert classify(characters=0, largest_image_share=0.95) == SCANNED


def test_a_header_stamped_over_a_scan_is_mixed_not_native() -> None:
    """The case that makes "is there any text?" the wrong question.

    A scanned statement with a running title and a page number stamped over it returns
    perhaps forty characters out of a page holding two hundred figures. Asked whether there
    is text, the honest answer is yes - and acting on it loses the whole page, quietly,
    because a short string is not an error and nothing downstream can tell the difference
    between "this page was nearly empty" and "we only read the header".
    """
    assert classify(characters=40, largest_image_share=0.92) == MIXED


def test_a_dense_page_is_native_even_under_a_full_page_watermark() -> None:
    """Text wins when there is enough of it.

    A statement printed over a faint full-page watermark or a security background is still
    a statement, and OCRing it would be paying to re-read text already in hand.
    """
    assert classify(characters=4000, largest_image_share=0.99) == NATIVE


def test_a_sparse_page_with_only_a_logo_is_native_not_mixed() -> None:
    """A section divider is a real page that genuinely holds two words.

    Routing it to OCR on the grounds of sparseness alone would send every tab page in a
    400-page report through the expensive path for nothing. The image share is what
    separates "nearly empty" from "mostly unreadable".
    """
    assert classify(characters=12, largest_image_share=0.03) == NATIVE


def test_nothing_at_all_is_blank() -> None:
    """Distinct from `SCANNED`, because a blank page needs no OCR and no worry."""
    assert classify(characters=0, largest_image_share=0.0) == BLANK


@pytest.mark.parametrize(
    "characters,share,expected",
    [
        (MIN_NATIVE_CHARS, 0.99, NATIVE),  # exactly at the threshold is enough
        (MIN_NATIVE_CHARS - 1, 0.99, MIXED),  # one short, and covered, is not
        (50, FULL_PAGE_IMAGE_SHARE, MIXED),  # exactly at the image share counts as covered
        (50, FULL_PAGE_IMAGE_SHARE - 0.01, NATIVE),  # just under, and it is decoration
    ],
)
def test_the_boundaries_fall_where_the_constants_say(
    characters: int, share: float, expected: str
) -> None:
    """Both thresholds are `>=`, and a test that says so stops the next reader guessing."""
    assert classify(characters=characters, largest_image_share=share) == expected


# --------------------------------------------------------------------------------------
# Reading a real filing
# --------------------------------------------------------------------------------------


def test_a_real_filing_reads_as_native_with_its_table() -> None:
    """The DMO auction result: text, a small logo, and one table of figures.

    The logo is the point as much as the text is. It is an image on a page that is plainly
    readable, and a rule keyed on "are there images?" rather than on how much of the page
    they cover would send this to OCR.
    """
    page = read_pages(REAL_REPORT.read_bytes())[0]
    assert page.kind == NATIVE
    assert page.is_readable
    assert not page.needs_ocr
    assert page.characters > MIN_NATIVE_CHARS
    assert page.images >= 1
    assert page.largest_image_share < FULL_PAGE_IMAGE_SHARE
    assert page.tables, "the auction table is the whole content of this page"


def test_page_numbers_start_at_one() -> None:
    """The most likely off-by-one in the pipeline, and the one that matters most.

    `page` is a provenance column: a reviewer opens the cited page to check a figure. Zero-
    based here would send every one of them to the page before the number they are checking.
    """
    pages = read_pages(minimal_pdf(3))
    assert [p.page_number for p in pages] == [1, 2, 3]


def test_an_empty_page_is_blank_rather_than_scanned() -> None:
    """No text and no image. Nothing was lost, so nothing needs OCR."""
    page = read_pages(minimal_pdf(1))[0]
    assert page.kind == BLANK
    assert not page.needs_ocr
    assert page.tables == ()


def test_the_page_cap_stops_early_without_changing_what_it_returns() -> None:
    """For sampling the front of a 400-page report rather than paying for all of it."""
    assert len(read_pages(minimal_pdf(9), pages=4)) == 4
    assert read_pages(minimal_pdf(9), pages=4) == read_pages(minimal_pdf(9))[:4]


def test_a_zero_page_cap_is_refused_rather_than_returning_nothing() -> None:
    """`pages=0` reads as "no limit" to one reader and "no pages" to another, and silently
    returning an empty list would look exactly like a PDF with nothing in it."""
    with pytest.raises(ValueError, match="must be positive"):
        read_pages(minimal_pdf(2), pages=0)


def test_bytes_that_are_not_a_pdf_raise_with_the_reason() -> None:
    """Named rather than generic, because this arrives from an operator upload and the
    person who uploaded it needs to know it was the file and not the system."""
    with pytest.raises(PdfReadError, match="could not open"):
        read_pages(b"this is not a PDF at all")


# --------------------------------------------------------------------------------------
# Markdown, and the cells that break it
# --------------------------------------------------------------------------------------


def test_an_empty_cell_stays_empty_and_never_becomes_a_zero() -> None:
    """`SPEC.md` §4.1's rule against fabricated figures, at the first stage that could.

    A `0` written here is a number, and a number that reaches the reconciler is one it will
    map to a canonical key and store with a page citation - a fabricated figure with
    complete provenance, which is the worst possible combination.
    """
    table = (("Revenue", "2024", "2023"), ("Segment B", None, "1,200"))
    rendered = to_markdown(table)
    assert "| Segment B |  | 1,200 |" in rendered
    assert "0" not in rendered.replace("1,200", "").replace("2024", "").replace("2023", "")


def test_a_pipe_inside_a_cell_does_not_end_the_cell() -> None:
    """Real labels contain them, and an unescaped one shifts every figure after it one
    column left - a wrong number that is also a real number, which survives review."""
    rendered = to_markdown((("Trade | other receivables", "500"),))
    assert r"Trade \| other receivables" in rendered
    # The property that matters is how many cells the row parses into, not how many pipe
    # characters it contains - the escaped one is still a pipe, and counting characters
    # measures the escaping rather than the alignment it protects.
    row = rendered.splitlines()[0]
    cells = re.split(r"(?<!\\)\|", row)[1:-1]
    assert len(cells) == 2, f"the label split the row into {len(cells)} cells: {cells}"
    assert cells[1].strip() == "500"  # the figure is still in the second column


def test_a_wrapped_label_does_not_end_the_row() -> None:
    """A label wrapped across two lines arrives with a newline in it, which would otherwise
    split one row into two and misalign everything below."""
    rendered = to_markdown((("Trade and other\nreceivables", "500"),))
    assert "Trade and other receivables" in rendered
    assert len(rendered.splitlines()) == 2  # the row and its separator, not three


def test_a_ragged_table_is_padded_rather_than_truncated() -> None:
    """Borderless extraction routinely returns rows of different lengths. Truncating to the
    shortest drops real figures; padding to the longest keeps every one of them."""
    rendered = to_markdown((("A", "B", "C"), ("only one",)))
    assert "| only one |  |  |" in rendered


def test_an_empty_table_renders_as_nothing_rather_than_an_empty_grid() -> None:
    """An empty grid in the prompt is a table the reconciler may try to read."""
    assert to_markdown(()) == ""

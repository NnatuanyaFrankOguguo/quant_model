"""P3.1: taking an uploaded report into the document store, and P3 check 1.

`docs/03` P3 check 1: *"Re-upload the same PDF | Same hash detected; no duplicate row"*. The
mechanism existed in `packages/common/storage.py` and was tested on bytes; nothing had ever
put a **PDF** through it, and the project held zero of them — 300 `source_documents` rows,
299 JSON and one CSV. So the check passed on a proxy.

What P3.1 asks for beyond storing bytes:

* the row carries a **page count**, read from the file rather than typed, because a figure
  citing page 143 of a 120-page report is a provenance error only a real count can catch;
* the file is **immutable**, so a re-upload is a no-op and a reissued report is a new row;
* the bytes are **actually a PDF**, since a `page` reference into an HTML error page that a
  download captured instead of the report means nothing at all.

The fixture is a real document: DMO's September 2026 FGN bond auction result, the same file
`scripts/collect_dmo.py` reads. The multi-page cases are built byte by byte so the expected
count is known rather than asserted from the same library that produced it.
"""

from __future__ import annotations

import datetime as dt
from pathlib import Path

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from packages.common.models import DataSource, SourceDocument
from packages.common.storage import LocalDiskBackend, sha256_hex
from packages.ingestion import base as ingestion_base
from packages.ingestion.documents import (
    ISSUER_UPLOAD_SOURCE,
    PDF_MEDIA_TYPE,
    NotAPdfError,
    page_count_of,
    store_uploaded_report,
)

pytestmark = pytest.mark.invariant

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"
REAL_REPORT = FIXTURES / "pdf" / "dmo_auction_september_2026.pdf"
GTCO_URL = "https://doclib.ngxgroup.com/Financial_NewsDocs/example.pdf"


def minimal_pdf(pages: int) -> bytes:
    """A valid PDF with a known number of empty pages.

    Hand-built so the expected count is independent of the library doing the counting. A
    fixture file would prove only that `pdfplumber` agrees with `pdfplumber`.
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


@pytest.fixture
def local_store(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> LocalDiskBackend:
    store = LocalDiskBackend(tmp_path / "documents")
    monkeypatch.setattr(ingestion_base, "get_storage", lambda: store)
    monkeypatch.setattr("packages.ingestion.documents.get_storage", lambda: store)
    return store


# --------------------------------------------------------------------------------------
# The page count, which is the column P3.1 adds
# --------------------------------------------------------------------------------------


@pytest.mark.parametrize("pages", [1, 2, 3, 17])
def test_the_page_count_is_read_from_the_file(pages: int) -> None:
    """Not typed by the uploader, so it can be used to check what the uploader typed."""
    assert page_count_of(minimal_pdf(pages)) == pages


def test_a_real_filing_counts_its_pages() -> None:
    """DMO's September 2026 auction result: one page, and this is the file itself."""
    assert REAL_REPORT.exists(), "the fixture PDF is missing"
    assert page_count_of(REAL_REPORT.read_bytes()) == 1


def test_the_stored_row_carries_the_count(
    db_session: Session, local_store: LocalDiskBackend
) -> None:
    stored = store_uploaded_report(db_session, minimal_pdf(9), url=GTCO_URL)
    assert stored.page_count == 9
    row = db_session.execute(
        select(SourceDocument).where(SourceDocument.id == stored.document_id)
    ).scalar_one()
    assert row.page_count == 9
    assert row.media_type == PDF_MEDIA_TYPE
    assert row.url == GTCO_URL, "the per-document half of the attribution"


# --------------------------------------------------------------------------------------
# P3 check 1: the same PDF twice
# --------------------------------------------------------------------------------------


def test_re_uploading_the_same_pdf_detects_the_hash_and_adds_no_row(
    db_session: Session, local_store: LocalDiskBackend
) -> None:
    """Check 1, stated. The second upload is a no-op that reports the row already there."""
    data = minimal_pdf(4)
    first = store_uploaded_report(db_session, data, url=GTCO_URL)
    second = store_uploaded_report(db_session, data, url="https://somewhere-else.example/x.pdf")

    assert first.created is True
    assert second.created is False, "the second upload created nothing"
    assert second.document_id == first.document_id
    assert second.sha256 == first.sha256 == sha256_hex(data)

    rows = (
        db_session.execute(select(SourceDocument).where(SourceDocument.sha256 == first.sha256))
        .scalars()
        .all()
    )
    assert len(rows) == 1, "one row for one file"
    assert rows[0].url == GTCO_URL, "the first upload's metadata is not overwritten"


def test_a_reissued_report_is_a_new_row_and_not_an_edit(
    db_session: Session, local_store: LocalDiskBackend
) -> None:
    """P3.1: *"If a company reissues its report, that is a new document, not an edit."*

    The reissue has different bytes, so a different hash, so a different row — and the
    figures already taken out of the first file still point at the first file. That is what
    makes a page reference keep resolving years later.
    """
    original = store_uploaded_report(db_session, minimal_pdf(4), url=GTCO_URL)
    reissued = store_uploaded_report(db_session, minimal_pdf(5), url=GTCO_URL)

    assert reissued.document_id != original.document_id
    assert reissued.sha256 != original.sha256
    assert reissued.created is True

    still_there = db_session.execute(
        select(SourceDocument).where(SourceDocument.id == original.document_id)
    ).scalar_one()
    assert still_there.page_count == 4, "the original is untouched, count and all"


def test_the_stored_bytes_are_retrievable_and_verify_against_the_hash(
    db_session: Session, local_store: LocalDiskBackend
) -> None:
    """A page citation is worth nothing if the file behind it cannot be fetched back."""
    data = minimal_pdf(3)
    stored = store_uploaded_report(db_session, data, url=GTCO_URL)
    assert local_store.get(stored.sha256) == data
    assert local_store.verify(stored.sha256), "the stored bytes still hash to the key"


# --------------------------------------------------------------------------------------
# What is refused, and why a filename is not evidence
# --------------------------------------------------------------------------------------


def test_bytes_that_are_not_a_pdf_are_refused(
    db_session: Session, local_store: LocalDiskBackend
) -> None:
    """A page number against an HTML error page means nothing, and downloads capture those.

    The check is on the content. The filename is the one part of an upload that nobody
    verifies, so it is the one part this does not look at.
    """
    not_pdfs = {
        "an HTML error page": b"<!DOCTYPE html><html><body>404 Not Found</body></html>",
        "a JPEG": b"\xff\xd8\xff\xe0\x00\x10JFIF" + b"\x00" * 64,
        "a CSV": b"series_code,as_of_date,value\nNG_MPR,2026-08-31,26.5\n",
        "the magic too far in": b"\x00" * 2048 + b"%PDF-1.4\n",
    }
    for description, data in not_pdfs.items():
        with pytest.raises(NotAPdfError, match="not a PDF"):
            store_uploaded_report(db_session, data, url=GTCO_URL)
        assert (
            not db_session.execute(
                select(SourceDocument).where(SourceDocument.sha256 == sha256_hex(data))
            )
            .scalars()
            .all()
        ), f"{description} must leave no row behind"


def test_an_empty_upload_is_refused(db_session: Session, local_store: LocalDiskBackend) -> None:
    with pytest.raises(NotAPdfError, match="empty"):
        store_uploaded_report(db_session, b"", url=GTCO_URL)


def test_a_file_that_starts_like_a_pdf_but_is_broken_is_refused() -> None:
    """Truncated downloads are the common case, and they do start with `%PDF-`.

    Refusing here rather than storing a file nothing can open is the difference between one
    failed upload and a permanent row whose pages can never be cited.
    """
    with pytest.raises(NotAPdfError, match="could not be opened"):
        page_count_of(b"%PDF-1.4\n" + b"garbage that is not a pdf body" * 4)


def test_storing_is_refused_when_no_data_source_row_exists(
    db_session: Session, local_store: LocalDiskBackend
) -> None:
    """`source_documents.data_source_id` is NOT NULL, and the licence lives on that row.

    A document stored against an invented source would be a file with no answer to "may we
    republish this?" — which `PROJECT_CONTEXT.md` §9.3 calls the question that kills deals.
    """
    with pytest.raises(LookupError, match="no row named"):
        store_uploaded_report(
            db_session, minimal_pdf(1), url=GTCO_URL, source_name="Some Source Nobody Seeded"
        )


# --------------------------------------------------------------------------------------
# The licence the uploads are stored under
# --------------------------------------------------------------------------------------


def test_the_upload_source_forbids_redistribution(db_session: Session) -> None:
    """Migration `0022`. An issuer publishing its report is not a grant to republish the file.

    `terms_url` is deliberately NULL: each issuer publishes under its own terms and there is
    no single page that covers them, so the column says so instead of naming an invented one.
    """
    source = db_session.execute(
        select(DataSource).where(DataSource.source_name == ISSUER_UPLOAD_SOURCE)
    ).scalar_one()
    assert source.redistribution_allowed is False
    assert source.attribution_required is True
    assert source.terms_url is None
    assert "Redistribution is NOT permitted" in (source.notes or "")


def test_an_upload_is_attributed_to_the_shared_source_row(
    db_session: Session, local_store: LocalDiskBackend
) -> None:
    """One row covers every issuer; which issuer this file came from is the document's `url`."""
    stored = store_uploaded_report(db_session, minimal_pdf(2), url=GTCO_URL)
    row = db_session.execute(
        select(SourceDocument).where(SourceDocument.id == stored.document_id)
    ).scalar_one()
    source = db_session.execute(
        select(DataSource).where(DataSource.id == row.data_source_id)
    ).scalar_one()
    assert source.source_name == ISSUER_UPLOAD_SOURCE


def test_retrieved_at_is_when_we_got_it_not_when_it_was_published(
    db_session: Session, local_store: LocalDiskBackend
) -> None:
    """Conflating the two is how a point-in-time read believes we held a report early.

    The issuer's publication date belongs on the `filings` row that cites this document.
    This column answers only "when did this reach us".
    """
    got_it = dt.datetime(2026, 9, 17, 6, 30, tzinfo=dt.UTC)
    stored = store_uploaded_report(db_session, minimal_pdf(2), url=GTCO_URL, retrieved_at=got_it)
    row = db_session.execute(
        select(SourceDocument).where(SourceDocument.id == stored.document_id)
    ).scalar_one()
    assert row.retrieved_at == got_it

    defaulted = store_uploaded_report(db_session, minimal_pdf(6), url=GTCO_URL)
    fresh = db_session.execute(
        select(SourceDocument).where(SourceDocument.id == defaulted.document_id)
    ).scalar_one()
    assert fresh.retrieved_at is not None, "an upload always records when it arrived"

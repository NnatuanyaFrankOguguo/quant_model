"""Taking an uploaded report into the document store. P3.1.

`docs/03` P3.1, in full:

    Upload a PDF; store it immutably in object storage; create a `source_documents` row with
    hash, page count, and metadata. **Immutable** means the stored file is never modified or
    replaced — every extracted figure points at a page in *this exact file*, forever. If a
    company reissues its report, that is a new document, not an edit.

Every clause of that has a consequence here.

**"This exact file, forever"** is why the bytes are checked to actually be a PDF before
anything is written. A `statement_line_items` row cites a `page`, and a page number means
nothing against a Word document, a scan renamed `.pdf`, or an HTML error page a download
captured instead of the report. The check is on the content, not the filename, because the
filename is the one part of an upload nobody verifies.

**"A new document, not an edit"** is the storage key being the hash. Re-uploading the same
bytes returns the row that already exists, untouched. Uploading a reissued report produces a
different hash and therefore a different row, and the figures taken from the first one still
point at the first one. Neither case is an UPDATE, which is what makes a page reference from
2026 still resolve in 2031.

**Page count** is read from the file rather than typed, because it is the one number that can
be checked against the document without opening it: a figure citing page 143 of a 120-page
report is a provenance error the review queue should catch, and it can only catch it if the
count came from the PDF.

The licence question is answered by `data_sources` and not here: migration `0022` seeds the
row these uploads belong to, with `redistribution_allowed` false, because an issuer
publishing its own report is not a grant to republish the file.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from packages.common.models import DataSource, SourceDocument
from packages.common.storage import get_storage
from packages.common.timez import utcnow
from packages.ingestion.base import upsert_document

__all__ = [
    "ISSUER_UPLOAD_SOURCE",
    "PDF_MEDIA_TYPE",
    "NotAPdfError",
    "StoredDocument",
    "page_count_of",
    "store_uploaded_report",
]

#: The `data_sources.source_name` migration `0022` seeds for operator uploads.
ISSUER_UPLOAD_SOURCE = "Issuer report (operator upload)"

PDF_MEDIA_TYPE = "application/pdf"

#: Every PDF begins with this. The version digits follow, and some issuers' tooling emits a
#: few bytes of preamble first, so the marker is searched for near the start rather than
#: required at offset zero — Adobe's own readers accept that and so do the parsers here.
_PDF_MAGIC = b"%PDF-"
_MAGIC_WINDOW = 1024


class NotAPdfError(ValueError):
    """The uploaded bytes are not a PDF, so a page reference into them would be meaningless."""


@dataclass(frozen=True)
class StoredDocument:
    """What the caller needs back: the row, and whether this upload created it."""

    document_id: int
    sha256: str
    page_count: int
    #: False when these exact bytes were already stored. The upload is then a no-op, which
    #: is P3 check 1: *"Re-upload the same PDF | Same hash detected; no duplicate row"*.
    created: bool


def _assert_pdf(data: bytes) -> None:
    if not data:
        raise NotAPdfError("the upload is empty")
    if _PDF_MAGIC not in data[:_MAGIC_WINDOW]:
        raise NotAPdfError(
            "the upload does not begin with %PDF- and so is not a PDF. A page number cited "
            "against it would mean nothing. Check the file, not its name."
        )


def page_count_of(data: bytes) -> int:
    """How many pages the PDF has, read from the file itself.

    Imported inside the function: `pdfplumber` is not a base dependency, and the module-level
    alternative would make every importer of `packages.ingestion` need it.
    """
    _assert_pdf(data)
    import io  # noqa: PLC0415 - kept beside the lazy pdfplumber import

    import pdfplumber  # noqa: PLC0415 - see the docstring

    try:
        with pdfplumber.open(io.BytesIO(data)) as pdf:
            pages = len(pdf.pages)
    except NotAPdfError:
        raise
    except Exception as exc:  # noqa: BLE001 - the reason is the message, not the type
        raise NotAPdfError(
            f"the upload starts like a PDF but could not be opened as one: "
            f"{type(exc).__name__}: {exc}"
        ) from exc
    if pages < 1:
        raise NotAPdfError("the PDF reports no pages, so nothing in it can be cited")
    return pages


def store_uploaded_report(
    session: Session,
    data: bytes,
    *,
    url: str | None = None,
    retrieved_at: dt.datetime | None = None,
    source_name: str = ISSUER_UPLOAD_SOURCE,
) -> StoredDocument:
    """Store an uploaded report and return its `source_documents` row.

    `url` is where the operator got the file — the issuer's own page, ideally. It is the
    per-document half of the attribution that `data_sources` cannot carry, since one row
    covers every issuer, so it is worth filling in even though the column allows NULL.

    `retrieved_at` defaults to now, which for an upload is when it reached us rather than
    when the issuer published it. The published date belongs on the `filings` row that cites
    this document, not here: this column answers "when did we get it", and conflating the two
    is how a point-in-time read starts believing we held a report before it existed.
    """
    _assert_pdf(data)
    pages = page_count_of(data)

    data_source_id = session.execute(
        select(DataSource.id).where(DataSource.source_name == source_name)
    ).scalar_one_or_none()
    if data_source_id is None:
        raise LookupError(
            f"data_sources has no row named {source_name!r}. An uploaded document cannot be "
            f"stored without one, because its licence and attribution live there "
            f"(migration 0022)."
        )

    stored = get_storage().put(data, media_type=PDF_MEDIA_TYPE)
    before = session.execute(
        select(SourceDocument.id).where(SourceDocument.sha256 == stored.sha256)
    ).scalar_one_or_none()
    document = upsert_document(
        session,
        data_source_id=data_source_id,
        url=url,
        storage_key=stored.storage_key,
        sha256=stored.sha256,
        media_type=PDF_MEDIA_TYPE,
        retrieved_at=retrieved_at or utcnow(),
        page_count=pages,
    )
    return StoredDocument(
        document_id=document.id,
        sha256=document.sha256,
        # The stored row's count, not the freshly read one. They agree for a new document,
        # and for a re-upload the row is what every existing page citation was checked
        # against — so it is the row that must be reported.
        page_count=document.page_count if document.page_count is not None else pages,
        created=before is None,
    )

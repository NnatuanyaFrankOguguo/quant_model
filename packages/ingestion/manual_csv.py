"""The manual CSV fallback. P1.7 — R-02's own recommended mitigation.

`docs/06_RISK_REGISTER.md` rates "government sites redesign without warning" as a live risk
and recommends *"manual CSV fallback wired from day one"*. `docs/10` §6.3 notes that this
recommendation was made in prose and **scheduled nowhere**, which is how a mitigation becomes
a sentence nobody implemented.

CBN, NBS and DMO have no REST API (`DATA_FOUNDATION.md` Part 2). Scrapers for them will
break, without warning, on a day nobody chose. This path is the one that always works: a
human downloads the figures (Collector task H, ~30 min/month) and drops a CSV in. The scraper
is the fast path; **the human is the guaranteed path**, and having it means a redesigned
website is an inconvenience rather than a stalled phase.

It is not throwaway work. The same upload-and-attribute path serves P3's PDF upload, and the
provenance rules are identical: the uploaded file is stored, hashed and pointed at by every
figure it produced, exactly like a scraped response. A manually-entered number with no source
document is precisely the untraceable figure `CLAUDE.md` forbids.

The CSV contract, one row per observation:

    series_code,as_of_date,known_as_of,value
    NG_CPI_YOY,2026-07-31,2026-08-15,34.2
    NG_MPR,2026-07-22,2026-07-22,27.50
    NG_CPI_CORE,2026-07-31,2026-08-15,

**`known_as_of` is mandatory and is not the date you typed it in.** It is the date the
statistics agency *published* the figure — mid-September for August CPI. Defaulting it to
today would silently claim that August's number was knowable in August, which is the
lookahead that makes a P7 backtest profitable and wrong. An empty `value` is a genuine
"no observation" and is stored as NULL, never as zero.
"""

from __future__ import annotations

import csv
import datetime as dt
import io
from decimal import Decimal, InvalidOperation
from pathlib import Path

from packages.ingestion.base import (
    Connector,
    DataSourceLicence,
    MacroRecord,
    RawResponse,
)

__all__ = ["MANUAL_SOURCES", "CsvFormatError", "ManualCsvConnector"]

REQUIRED_COLUMNS = ("series_code", "as_of_date", "known_as_of", "value")

#: The agencies this path covers, with the reviewed register row each maps to. Attribution
#: text matches migration 0004 so `register()`'s consistency check passes.
MANUAL_SOURCES = {
    "CBN": "Source: Central Bank of Nigeria",
    "NBS": "Source: National Bureau of Statistics, Nigeria",
    "DMO": "Source: Debt Management Office, Nigeria",
}


class CsvFormatError(Exception):
    """The CSV is not the agreed shape. Raised before anything is written.

    Loud and early on purpose: a partially-ingested manual file is worse than a rejected one,
    because the gaps are invisible and the human has already moved on.
    """


class ManualCsvConnector(Connector):
    """Ingest a hand-prepared CSV as if it were any other source.

    Same contract as a scraper — declare a licence, store the raw bytes, parse
    deterministically, write a `connector_runs` row — because a figure's provenance must not
    depend on how it arrived.
    """

    rate_limit_per_sec = 1000.0  # local file; the limit is meaningless but must be declared

    def __init__(self, source_name: str, *, reviewed_by: str = "nnatuanyafrankoguguo") -> None:
        if source_name not in MANUAL_SOURCES:
            raise ValueError(
                f"unknown manual source {source_name!r}; expected one of {sorted(MANUAL_SOURCES)}"
            )
        self.source_name = source_name
        self.name = f"manual_csv_{source_name.lower()}"
        self._reviewed_by = reviewed_by

    def declare_licence(self) -> DataSourceLicence:
        """The agency's terms, not "a human typed it".

        Data hand-copied from a CBN release is still CBN's data on CBN's terms. Declaring
        otherwise would be the cheapest possible way to launder a redistribution restriction,
        so the manual path claims exactly what the scraped path claims.
        """
        return DataSourceLicence(
            source_name=self.source_name,
            licence_type="ng_public_agency",
            redistribution_allowed=False,
            attribution_required=True,
            attribution_text=MANUAL_SOURCES[self.source_name],
            terms_reviewed_on=dt.date(2026, 9, 1),
            reviewed_by=self._reviewed_by,
            notes=(
                "Manual CSV path (P1.7). Figures transcribed by hand from the agency's own "
                "publication; the uploaded file is stored and hashed like any fetched "
                "response, so every figure keeps a source document."
            ),
        )

    def fetch(self, **params: object) -> RawResponse:
        """Read the CSV from disk. The 'fetch' step for a human-supplied file."""
        path = Path(str(params["path"]))
        if not path.is_file():
            raise FileNotFoundError(f"no CSV at {path}")
        data = path.read_bytes()
        return RawResponse(
            data=data,
            media_type="text/csv",
            # A file:// URL rather than None: the provenance question "where did this come
            # from" deserves an answer even when the answer is a laptop.
            url=path.resolve().as_uri(),
            http_status=None,
        )

    def parse(self, raw: RawResponse) -> list[MacroRecord]:
        """Pure and strict. Every row is validated before any row is accepted."""
        text = raw.data.decode("utf-8-sig")  # Excel writes a BOM; strip it rather than fail
        reader = csv.DictReader(io.StringIO(text))
        missing = [c for c in REQUIRED_COLUMNS if c not in (reader.fieldnames or [])]
        if missing:
            raise CsvFormatError(
                f"CSV is missing required column(s): {', '.join(missing)}. "
                f"Expected header: {','.join(REQUIRED_COLUMNS)}"
            )
        records: list[MacroRecord] = []
        for line_number, row in enumerate(reader, start=2):
            records.append(_record_from_row(row, line_number))
        return records


def _record_from_row(row: dict[str, str | None], line_number: int) -> MacroRecord:
    code = (row.get("series_code") or "").strip()
    if not code:
        raise CsvFormatError(f"line {line_number}: series_code is empty")
    as_of = _require_date(row.get("as_of_date"), "as_of_date", line_number)
    known_as_of = _require_date(row.get("known_as_of"), "known_as_of", line_number)
    if known_as_of < as_of:
        # Not a style rule. A figure published before the period it describes is either a
        # typo or a forecast, and storing it would let a point-in-time query return a number
        # the market could not have had.
        raise CsvFormatError(
            f"line {line_number}: known_as_of ({known_as_of}) precedes as_of_date "
            f"({as_of}). A figure cannot be published before the period it describes."
        )
    return MacroRecord(
        series_code=code,
        as_of_date=as_of,
        known_as_of=known_as_of,
        value=_optional_decimal(row.get("value"), line_number),
    )


def _require_date(value: str | None, column: str, line_number: int) -> dt.date:
    raw = (value or "").strip()
    if not raw:
        raise CsvFormatError(
            f"line {line_number}: {column} is empty. It is required — "
            f"known_as_of is the agency's publication date, not the date you typed this in."
        )
    try:
        return dt.date.fromisoformat(raw)
    except ValueError as exc:
        raise CsvFormatError(
            f"line {line_number}: {column}={raw!r} is not an ISO date (YYYY-MM-DD)"
        ) from exc


def _optional_decimal(value: str | None, line_number: int) -> Decimal | None:
    """Empty means genuinely absent, and absent stays NULL (SPEC §4.1)."""
    raw = (value or "").strip().replace(",", "")
    if raw in {"", ".", "-", "n/a", "N/A", "NA"}:
        return None
    try:
        return Decimal(raw)
    except InvalidOperation as exc:
        raise CsvFormatError(f"line {line_number}: value={value!r} is not a number") from exc

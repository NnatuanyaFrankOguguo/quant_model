"""The connector contract every source implements forever. P1.1.

`docs/08_DATA_CONTRACTS.md` §5, `DATA_FOUNDATION.md` §4.3. Four rules, and the point of
this module is that each is enforced by the code rather than remembered by the author:

1. **`declare_licence()` is abstract.** You cannot ship a connector without answering the
   redistribution question, and `register()` refuses a connector whose answer is missing.
   This is TG5 — `CLAUDE.md`'s "data licensing before ingestion" — made executable.
   `PROJECT_CONTEXT.md` §9.3 calls it "the question that kills deals"; a register that is
   filled in *after* two years of ingestion cannot be reconstructed.
2. **`fetch` and `parse` are separate, and raw is stored before parsing.** A parser bug six
   months from now is then fixable without re-fetching, and stays fixable after the source
   has been redesigned or has vanished. `run()` gives `parse()` no way to reach the network,
   so this cannot be quietly skipped.
3. **`parse` is pure and deterministic** — same raw bytes, same records. That is what makes
   it testable against a stored fixture instead of a live website.
4. **`run()` always writes a `connector_runs` row, including `rows_written`.** The classic
   scraper failure is not a crash: the page still loads, the parser still runs, the selector
   matches nothing, and `status` is `'ok'` with zero rows (`OPERATIONS.md` §2.3). A run that
   raises writes a row too — a connector that dies silently is the failure this table exists
   to catch.

`rows_written` counts rows **actually inserted**, never records parsed. Counting parsed
records would report a healthy number for a scraper that re-writes the same values forever,
which is precisely the failure the column exists to detect.
"""

from __future__ import annotations

import datetime as dt
from abc import ABC, abstractmethod
from collections.abc import Iterator
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any

import structlog
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from packages.common.config import redact_secrets
from packages.common.console import step
from packages.common.models import (
    ConnectorRun,
    DataSource,
    MacroObservation,
    MacroSeries,
    SourceDocument,
)
from packages.common.storage import StorageBackend, get_storage
from packages.common.timez import utcnow

__all__ = [
    "Connector",
    "ConnectorRunResult",
    "DataSourceLicence",
    "LicenceNotDeclaredError",
    "MacroRecord",
    "RawResponse",
    "record_run",
    "register",
    "store_raw",
]

_log = structlog.get_logger(__name__)

#: Rows per INSERT. PostgreSQL's wire protocol caps a single statement at 65,535 bound
#: parameters, and a `macro_observations` row binds six — so one statement tops out near
#: 10,900 rows and fails with "number of parameters must be between 0 and 65535".
#:
#: This was found the hard way. The CBN load was 6,052 rows and passed; the first FRED
#: series with a long daily history crossed the line. The failure is not a slow query or a
#: partial write — the statement is simply rejected, so the whole run writes nothing. 2,000
#: leaves room for a table that grows a column later without anyone re-deriving this number.
INSERT_BATCH_ROWS = 2000


def _batched(rows: list[dict[str, Any]], size: int) -> Iterator[list[dict[str, Any]]]:
    """Yield successive chunks. `itertools.batched` is 3.12-only; this project allows 3.11."""
    for start in range(0, len(rows), size):
        yield rows[start : start + size]


class LicenceNotDeclaredError(Exception):
    """A connector tried to register without stating its redistribution rights.

    Raised at registration, before any fetch, because the whole value of the register is
    that the answer exists *before* the data does.
    """


@dataclass(frozen=True)
class DataSourceLicence:
    """What `declare_licence()` returns — one `data_sources` row.

    `redistribution_allowed` has **no default**. That is the entire mechanism: the column is
    `NOT NULL` in the database and the field is mandatory here, so "we never decided" is not
    a reachable state. When the terms are genuinely unclear the answer is `False` plus a note
    saying why — conservative and recorded, rather than absent.
    """

    source_name: str
    licence_type: str
    redistribution_allowed: bool
    attribution_required: bool
    terms_reviewed_on: dt.date
    reviewed_by: str
    base_url: str | None = None
    attribution_text: str | None = None
    terms_url: str | None = None
    rate_limit_per_sec: float | None = None
    notes: str | None = None


@dataclass(frozen=True)
class RawResponse:
    """Exactly what came back, before anyone interpreted it."""

    data: bytes
    media_type: str
    url: str | None = None
    http_status: int | None = None
    etag: str | None = None
    last_modified: dt.datetime | None = None
    retrieved_at: dt.datetime = field(default_factory=utcnow)


@dataclass(frozen=True)
class MacroRecord:
    """One normalized macro observation.

    `as_of_date` and `known_as_of` are both required and they mean different things:
    Nigerian CPI for August is published in mid-September, so August's figure has
    `as_of_date` in August and `known_as_of` in September. A model deciding in early
    September must see July's number. Getting this right here, on easy data, is rehearsal
    for P7, where getting it wrong invents profit that never existed.
    """

    series_code: str
    as_of_date: dt.date
    known_as_of: dt.date
    value: Decimal | None
    revision: int = 1


@dataclass(frozen=True)
class ConnectorRunResult:
    connector_name: str
    status: str  # 'ok' | 'error'
    rows_written: int
    records_parsed: int
    started_at: dt.datetime
    finished_at: dt.datetime
    source_document_id: int | None = None
    http_status: int | None = None
    error: str | None = None


class Connector(ABC):
    """Base class for every data source, in every phase."""

    #: Stable identifier, used as `connector_runs.connector_name`.
    name: str = ""
    #: Declared, not remembered. EDGAR's ≤10 req/s in P2 comes with a ~10-minute IP block
    #: when exceeded (`DATA_FOUNDATION.md` §C) — that belongs in code, not in your head.
    rate_limit_per_sec: float = 1.0
    #: 1 request / 2–5s per domain when scraping a site that never agreed to be scraped.
    politeness_delay_sec: float = 0.0

    @abstractmethod
    def declare_licence(self) -> DataSourceLicence:
        """MUST state redistribution rights. Enforced by `register()`."""

    @abstractmethod
    def fetch(self, **params: object) -> RawResponse:
        """Return raw bytes. Never parses, never writes to the domain tables."""

    @abstractmethod
    def parse(self, raw: RawResponse) -> list[MacroRecord]:
        """Pure and deterministic. Given the same bytes, returns the same records."""

    def run(
        self, session: Session, *, storage: StorageBackend | None = None, **params: object
    ) -> ConnectorRunResult:
        """fetch → store raw → parse → write → `connector_runs` row.

        The order is the contract. `parse()` is handed a `RawResponse` that has already been
        persisted, so a connector physically cannot parse something it did not store.
        """
        storage = storage or get_storage()
        started_at = utcnow()
        source_document_id: int | None = None
        http_status: int | None = None
        try:
            # Each stage is a numbered step on the console. The steps observe; the
            # try/except below is what decides, exactly as it did before they existed.
            with step("fetch", connector=self.name) as fetching:
                raw = self.fetch(**params)
                http_status = raw.http_status
                fetching.result(http_status=raw.http_status, bytes=len(raw.data))
            with step("store raw") as storing:
                document = store_raw(session, raw, connector=self)
                source_document_id = document.id
                storing.result(document_id=document.id, sha256=document.sha256[:12])
            with step("parse") as parsing:
                records = self.parse(raw)
                parsing.result(records=len(records))
            with step("write") as writing:
                rows_written = self.write(session, records, source_document_id=document.id)
                session.commit()
                writing.result(records=len(records), rows_inserted=rows_written)
                if records and rows_written == 0:
                    writing.warn("every parsed record was already present")
            result = ConnectorRunResult(
                connector_name=self.name,
                status="ok",
                rows_written=rows_written,
                records_parsed=len(records),
                started_at=started_at,
                finished_at=utcnow(),
                source_document_id=source_document_id,
                http_status=http_status,
            )
        except Exception as exc:
            session.rollback()
            result = ConnectorRunResult(
                connector_name=self.name,
                status="error",
                rows_written=0,
                records_parsed=0,
                started_at=started_at,
                finished_at=utcnow(),
                source_document_id=source_document_id,
                http_status=http_status,
                # Redacted, not raw. An exception message routinely contains the request
                # that failed, and for an API-key source that request carries the key.
                # `connector_runs.error` is stored forever and read by whoever is on call.
                error=redact_secrets(f"{type(exc).__name__}: {exc}")[:2000],
            )
            _log.error("connector_failed", connector=self.name, error_type=type(exc).__name__)
        with step("record run") as recording:
            record_run(session, result)
            recording.result(status=result.status, rows_written=result.rows_written)
        if result.status == "ok" and result.rows_written == 0:
            # Not an error — re-fetching an unchanged page is normal. But it is the signature
            # of a silent scraper failure, so it is said out loud rather than inferred later
            # from a query nobody runs.
            _log.warning(
                "connector_wrote_no_rows",
                connector=self.name,
                records_parsed=result.records_parsed,
            )
        return result

    def write(
        self, session: Session, records: list[MacroRecord], *, source_document_id: int
    ) -> int:
        """Insert observations, skipping ones already present. Returns rows inserted.

        `ON CONFLICT DO NOTHING` rather than an upsert, deliberately: the primary key is
        `(series_id, as_of_date, known_as_of)`, so a *revision* is a new row with a later
        `known_as_of`, and a re-fetch of an unchanged vintage is a no-op. There is no
        reachable path here that updates an existing observation — migration 0002 puts a
        `no_update` trigger on the table so the rule holds even outside this code.
        """
        if not records:
            return 0
        series_ids = _resolve_series_ids(session, {r.series_code for r in records})
        rows = [
            {
                "series_id": series_ids[r.series_code],
                "as_of_date": r.as_of_date,
                "known_as_of": r.known_as_of,
                "value": r.value,
                "revision": r.revision,
                "source_document_id": source_document_id,
            }
            for r in records
            if r.series_code in series_ids
        ]
        if not rows:
            return 0
        inserted = 0
        for batch in _batched(rows, INSERT_BATCH_ROWS):
            statement = (
                pg_insert(MacroObservation)
                .values(batch)
                .on_conflict_do_nothing(index_elements=["series_id", "as_of_date", "known_as_of"])
                .returning(MacroObservation.as_of_date)
            )
            inserted += len(session.execute(statement).fetchall())
        return inserted


def _resolve_series_ids(session: Session, codes: set[str]) -> dict[str, int]:
    """Map series codes to ids, ignoring codes with no `macro_series` row.

    A code with no row is a configuration gap, not a data error: the series list is seeded
    deliberately (`docs/03` P1 "decide the starting series list"), so a connector emitting an
    unknown code should be visible rather than silently creating a series nobody chose.
    """
    rows = session.execute(
        select(MacroSeries.code, MacroSeries.id).where(MacroSeries.code.in_(codes))
    ).all()
    found: dict[str, int] = {code: series_id for code, series_id in rows}
    for missing in sorted(codes - set(found)):
        _log.warning("unknown_series_code", code=missing)
    return found


def store_raw(session: Session, raw: RawResponse, *, connector: Connector) -> SourceDocument:
    """Persist the raw response and return its `source_documents` row.

    Idempotent on content: the same bytes fetched twice reuse the existing row, because the
    key *is* the hash. `sha256` is `UNIQUE`, so a reissued document is a new row and never an
    edit of the old one.
    """
    storage = get_storage()
    stored = storage.put(raw.data, media_type=raw.media_type)
    existing = session.execute(
        select(SourceDocument).where(SourceDocument.sha256 == stored.sha256)
    ).scalar_one_or_none()
    if existing is not None:
        return existing
    document = SourceDocument(
        data_source_id=_data_source_id(session, connector),
        url=raw.url,
        storage_key=stored.storage_key,
        sha256=stored.sha256,
        media_type=raw.media_type,
        retrieved_at=raw.retrieved_at,
        http_status=raw.http_status,
        etag=raw.etag,
        last_modified=raw.last_modified,
    )
    session.add(document)
    session.flush()
    return document


def _data_source_id(session: Session, connector: Connector) -> int:
    licence = _validated_licence(connector)
    row = session.execute(
        select(DataSource).where(DataSource.source_name == licence.source_name)
    ).scalar_one_or_none()
    if row is None:
        raise LicenceNotDeclaredError(
            f"{connector.name}: no data_sources row named {licence.source_name!r}. "
            f"Call register() before running a connector — the licensing register is a "
            f"precondition for ingestion, not a record of it."
        )
    return row.id


def _validated_licence(connector: Connector) -> DataSourceLicence:
    """Get the licence and prove it actually answers the question."""
    try:
        licence = connector.declare_licence()
    except NotImplementedError as exc:
        raise LicenceNotDeclaredError(
            f"{connector.name}: declare_licence() not implemented"
        ) from exc
    if not isinstance(licence, DataSourceLicence):
        raise LicenceNotDeclaredError(
            f"{connector.name}: declare_licence() returned {type(licence).__name__}, "
            f"not a DataSourceLicence"
        )
    # `is True`/`is False`, not truthiness: None, "", 0 and "no" must all fail here rather
    # than resolve to a permission nobody granted.
    if licence.redistribution_allowed is not True and licence.redistribution_allowed is not False:
        raise LicenceNotDeclaredError(
            f"{connector.name}: redistribution_allowed is "
            f"{licence.redistribution_allowed!r}, which is not an answer. "
            f"NOT NULL is the whole mechanism — it forces a decision."
        )
    return licence


def register(session: Session, connector: Connector) -> int:
    """Register a connector's source, or raise. Returns the `data_sources.id`.

    A connector that cannot state its redistribution rights **never runs**: this raises
    before any network call, and `run()` cannot reach the domain tables without a
    `data_sources` row to point `source_documents` at.
    """
    licence = _validated_licence(connector)
    existing = session.execute(
        select(DataSource).where(DataSource.source_name == licence.source_name)
    ).scalar_one_or_none()
    if existing is not None:
        # The stored row is the *reviewed* register — it carries `terms_reviewed_on` and
        # `reviewed_by`, which a code constant does not. A connector claiming rights the
        # register does not grant is the exact drift this gate exists to stop, and silently
        # preferring either side would let one be edited without the other.
        if existing.redistribution_allowed is not licence.redistribution_allowed:
            raise LicenceNotDeclaredError(
                f"{connector.name}: declares redistribution_allowed="
                f"{licence.redistribution_allowed} but the reviewed data_sources row for "
                f"{licence.source_name!r} says {existing.redistribution_allowed}. "
                f"Re-review the terms and change both together, with a new "
                f"terms_reviewed_on — never just the code."
            )
        return existing.id
    row = DataSource(
        source_name=licence.source_name,
        base_url=licence.base_url,
        licence_type=licence.licence_type,
        redistribution_allowed=licence.redistribution_allowed,
        attribution_required=licence.attribution_required,
        attribution_text=licence.attribution_text,
        terms_url=licence.terms_url,
        terms_reviewed_on=licence.terms_reviewed_on,
        reviewed_by=licence.reviewed_by,
        rate_limit_per_sec=licence.rate_limit_per_sec,
        notes=licence.notes,
    )
    session.add(row)
    session.flush()
    return row.id


def record_run(session: Session, result: ConnectorRunResult) -> None:
    """Write the `connector_runs` row. Never lets bookkeeping mask the result.

    Uses its own transaction, so a failed run — which has already rolled back — still gets
    its row. A connector that fails and leaves no trace is indistinguishable from one that
    was never scheduled, and `docs/10` §5.3 is about exactly that blind spot.
    """
    try:
        session.add(
            ConnectorRun(
                connector_name=result.connector_name,
                started_at=result.started_at,
                finished_at=result.finished_at,
                status=result.status,
                rows_written=result.rows_written,
                http_status=result.http_status,
                # Redacted again at the write, not only where the result was built. This is
                # the single place every connector's error text reaches the database, so a
                # future caller that constructs a result by hand cannot route round it.
                error=redact_secrets(result.error or "") or None,
            )
        )
        session.commit()
    except Exception as exc:  # noqa: BLE001 - health bookkeeping must not mask the run
        session.rollback()
        _log.error(
            "connector_run_row_failed",
            connector=result.connector_name,
            error_type=type(exc).__name__,
        )

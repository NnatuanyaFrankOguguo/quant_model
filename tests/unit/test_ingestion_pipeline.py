"""The full connector loop against the real database. P1.1 + P1.7.

`fetch → store raw → parse → write → connector_runs row`, asserted end to end, because the
ordering is the part of the contract that unit tests of `parse()` cannot reach. In particular
this is where `rows_written` is proved to count rows *inserted* rather than records parsed —
the distinction the silent-failure detector depends on.

P4 check 14 lives here for the same reason: a connector pointed at a real, well-formed,
empty page, run through `run()` end to end, and the warning that must be heard when it
writes nothing.
"""

from __future__ import annotations

import datetime as dt
import re
from decimal import Decimal
from uuid import uuid4

import pytest
import structlog
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from packages.common.models import ConnectorRun, MacroObservation, MacroSeries, SourceDocument
from packages.common.storage import LocalDiskBackend, sha256_hex
from packages.common.timez import utcnow
from packages.ingestion import base as ingestion_base
from packages.ingestion.base import (
    Connector,
    DataSourceLicence,
    MacroRecord,
    RawResponse,
    register,
)
from packages.ingestion.edgar import EdgarSubmissionsConnector
from packages.ingestion.manual_csv import ManualCsvConnector

UA = "Test Person test@example.com"

CSV = (
    "series_code,as_of_date,known_as_of,value\n"
    "NG_CPI_YOY,2026-07-31,2026-08-15,34.2\n"
    "NG_CPI_CORE,2026-07-31,2026-08-15,\n"
    "NG_MPR,2026-07-22,2026-07-22,27.50\n"
)


@pytest.fixture
def csv_path(tmp_path):
    path = tmp_path / "nbs_july.csv"
    # write_bytes, not write_text: on Windows write_text translates "\n" to "\r\n", so the
    # bytes on disk would not equal CSV.encode() and the round-trip assertion below would
    # be testing the platform's newline policy rather than the store.
    path.write_bytes(CSV.encode("utf-8"))
    return path


@pytest.fixture
def local_store(tmp_path, monkeypatch) -> LocalDiskBackend:
    """Point the document store at a temp directory for the duration of the test."""
    store = LocalDiskBackend(tmp_path / "documents")
    monkeypatch.setattr(ingestion_base, "get_storage", lambda: store)
    return store


def _observation_count(session: Session) -> int:
    return session.execute(select(func.count()).select_from(MacroObservation)).scalar_one()


def test_run_writes_observations_document_and_health_row(
    db_session: Session, csv_path, local_store: LocalDiskBackend
) -> None:
    connector = ManualCsvConnector("NBS")
    register(db_session, connector)
    db_session.commit()

    before = _observation_count(db_session)
    result = connector.run(db_session, path=csv_path)

    assert result.status == "ok"
    assert result.records_parsed == 3
    assert result.rows_written == 3
    assert _observation_count(db_session) == before + 3

    # The raw CSV is in the store, addressed by its own hash, and pointed at by a row.
    document = db_session.execute(
        select(SourceDocument).where(SourceDocument.id == result.source_document_id)
    ).scalar_one()
    assert local_store.verify(document.sha256) is True
    assert local_store.get(document.sha256) == CSV.encode()
    assert document.media_type == "text/csv"

    # Every figure points at that exact file — provenance, not a claim about provenance.
    series_id = db_session.execute(
        select(MacroSeries.id).where(MacroSeries.code == "NG_CPI_YOY")
    ).scalar_one()
    observation = db_session.execute(
        select(MacroObservation).where(
            MacroObservation.series_id == series_id,
            MacroObservation.as_of_date == dt.date(2026, 7, 31),
        )
    ).scalar_one()
    assert observation.source_document_id == document.id
    assert observation.value == Decimal("34.2")
    # Published mid-September for a July period: the two dates differ, and that is the point.
    assert observation.known_as_of == dt.date(2026, 8, 15)

    run_row = (
        db_session.execute(
            select(ConnectorRun)
            .where(ConnectorRun.connector_name == connector.name)
            .order_by(ConnectorRun.id.desc())
        )
        .scalars()
        .first()
    )
    assert run_row is not None
    assert run_row.status == "ok"
    assert run_row.rows_written == 3


@pytest.mark.invariant
def test_absent_value_is_stored_null_never_zero(
    db_session: Session, csv_path, local_store: LocalDiskBackend
) -> None:
    """SPEC 4.1: never infer missing financial data."""
    connector = ManualCsvConnector("NBS")
    register(db_session, connector)
    connector.run(db_session, path=csv_path)

    series_id = db_session.execute(
        select(MacroSeries.id).where(MacroSeries.code == "NG_CPI_CORE")
    ).scalar_one()
    value = db_session.execute(
        select(MacroObservation.value).where(MacroObservation.series_id == series_id)
    ).scalar_one()
    assert value is None


def test_rerunning_the_same_file_writes_no_new_rows(
    db_session: Session, csv_path, local_store: LocalDiskBackend
) -> None:
    """`rows_written` counts rows INSERTED, not records parsed.

    This is the whole basis of the silent-failure detector: a connector that re-parses the
    same three records forever must report 0, not 3, or `status='ok' AND rows_written=0`
    stops meaning anything.
    """
    connector = ManualCsvConnector("NBS")
    register(db_session, connector)
    # Counted as a delta, not as a total. This used to assert the table held exactly one
    # row, which was true only while nothing else in the suite had ever committed a
    # document - and stopped being true the moment the news and NGX connectors arrived
    # with tests of their own. The claim was never about the table; it was about this
    # file being stored once.
    before = db_session.execute(select(func.count()).select_from(SourceDocument)).scalar_one()
    first = connector.run(db_session, path=csv_path)
    second = connector.run(db_session, path=csv_path)

    assert first.rows_written == 3
    assert second.records_parsed == 3
    assert second.rows_written == 0
    assert second.status == "ok"

    # The identical file is stored once — the key is the content.
    after = db_session.execute(select(func.count()).select_from(SourceDocument)).scalar_one()
    assert after - before == 1
    assert second.source_document_id == first.source_document_id


def test_a_revision_is_a_new_row_not_an_update(
    db_session: Session, tmp_path, local_store: LocalDiskBackend
) -> None:
    """A restated figure inserts a second vintage. Nothing is ever overwritten.

    `known_as_of` sits inside the primary key precisely so this works, and migration 0002's
    `no_update` trigger means it holds even for someone with a SQL client.
    """
    connector = ManualCsvConnector("NBS")
    register(db_session, connector)

    original = tmp_path / "v1.csv"
    original.write_text(
        "series_code,as_of_date,known_as_of,value\nNG_GDP_GROWTH_YOY,2026-06-30,2026-08-25,3.1\n",
        encoding="utf-8",
    )
    revised = tmp_path / "v2.csv"
    revised.write_text(
        "series_code,as_of_date,known_as_of,value\nNG_GDP_GROWTH_YOY,2026-06-30,2026-11-20,3.4\n",
        encoding="utf-8",
    )
    connector.run(db_session, path=original)
    connector.run(db_session, path=revised)

    series_id = db_session.execute(
        select(MacroSeries.id).where(MacroSeries.code == "NG_GDP_GROWTH_YOY")
    ).scalar_one()
    rows = db_session.execute(
        select(MacroObservation.known_as_of, MacroObservation.value)
        .where(MacroObservation.series_id == series_id)
        .order_by(MacroObservation.known_as_of)
    ).all()
    assert [(r.known_as_of, r.value) for r in rows] == [
        (dt.date(2026, 8, 25), Decimal("3.1")),
        (dt.date(2026, 11, 20), Decimal("3.4")),
    ]


def test_a_failing_run_still_writes_a_health_row(
    db_session: Session, tmp_path, local_store: LocalDiskBackend
) -> None:
    """A connector that dies silently is indistinguishable from one nobody scheduled."""
    connector = ManualCsvConnector("NBS")
    register(db_session, connector)
    db_session.commit()

    result = connector.run(db_session, path=tmp_path / "does_not_exist.csv")

    assert result.status == "error"
    assert result.rows_written == 0
    assert "FileNotFoundError" in (result.error or "")

    run_row = (
        db_session.execute(
            select(ConnectorRun)
            .where(ConnectorRun.connector_name == connector.name)
            .order_by(ConnectorRun.id.desc())
        )
        .scalars()
        .first()
    )
    assert run_row is not None
    assert run_row.status == "error"
    assert run_row.error is not None


def test_unknown_series_codes_are_skipped_not_invented(
    db_session: Session, tmp_path, local_store: LocalDiskBackend
) -> None:
    """A connector must not create a series nobody chose (docs/03 P1: the list is decided)."""
    connector = ManualCsvConnector("NBS")
    register(db_session, connector)

    path = tmp_path / "unknown.csv"
    path.write_text(
        "series_code,as_of_date,known_as_of,value\nNOT_A_REAL_SERIES,2026-07-31,2026-08-15,1.0\n",
        encoding="utf-8",
    )
    before_series = db_session.execute(select(func.count()).select_from(MacroSeries)).scalar_one()
    result = connector.run(db_session, path=path)

    assert result.records_parsed == 1
    assert result.rows_written == 0
    after_series = db_session.execute(select(func.count()).select_from(MacroSeries)).scalar_one()
    assert after_series == before_series


# --------------------------------------------------------------------------------------
# Batched inserts — PostgreSQL's 65,535 bound-parameter ceiling
# --------------------------------------------------------------------------------------


def test_batched_splits_evenly_and_covers_everything() -> None:
    """Pure logic, so the arithmetic is checked without touching the database."""
    from packages.ingestion.base import _batched

    rows = [{"i": i} for i in range(7)]
    batches = list(_batched(rows, 3))
    assert [len(b) for b in batches] == [3, 3, 1]
    assert [r["i"] for b in batches for r in b] == list(range(7))
    assert list(_batched([], 3)) == []


def test_write_spans_multiple_batches_and_counts_once(
    db_session: Session, local_store: LocalDiskBackend, tmp_path, monkeypatch
) -> None:
    """A load larger than one statement must insert everything and count it once.

    The real failure this guards: PostgreSQL rejects a statement with more than 65,535 bound
    parameters, and an observation row binds six — so a single INSERT tops out near 10,900
    rows. It is not a partial write. The statement is refused and the whole run stores
    nothing, which is how a 60,000-row backfill silently produced zero.

    The batch size is lowered rather than generating 11,000 rows, so the multi-batch path is
    exercised in a second instead of hammering the database to prove arithmetic.
    """
    from packages.ingestion import base as ingestion_base

    monkeypatch.setattr(ingestion_base, "INSERT_BATCH_ROWS", 3)

    connector = ManualCsvConnector("NBS")
    register(db_session, connector)

    lines = ["series_code,as_of_date,known_as_of,value"]
    for day in range(1, 11):  # 10 rows, batch size 3 -> 4 statements
        lines.append(f"NG_CPI_YOY,2026-01-{day:02d},2026-03-01,{20 + day}.0")
    path = tmp_path / "many.csv"
    path.write_bytes(("\n".join(lines) + "\n").encode())

    result = connector.run(db_session, path=path)

    assert result.status == "ok"
    assert result.records_parsed == 10
    assert result.rows_written == 10, "every batch must be counted, and counted only once"

    series_id = db_session.execute(
        select(MacroSeries.id).where(MacroSeries.code == "NG_CPI_YOY")
    ).scalar_one()
    stored = db_session.execute(
        select(func.count())
        .select_from(MacroObservation)
        .where(MacroObservation.series_id == series_id)
    ).scalar_one()
    assert stored == 10


@pytest.mark.invariant
def test_an_unchanged_value_republished_later_is_not_a_new_vintage(
    db_session: Session, tmp_path, local_store: LocalDiskBackend
) -> None:
    """A vintage is a change in what was known. The same figure on a later date is not one.

    ALFRED clips `realtime_start` to a requested window, so every observation already known
    before the window comes back dated at the window start; the DGS10 backfill stored 43,952
    such rows as vintages. The rule is general: no point-in-time query can tell a period
    whose value was reconfirmed from one that was left alone.
    """
    connector = ManualCsvConnector("NBS")
    register(db_session, connector)

    first = tmp_path / "first.csv"
    first.write_text(
        "series_code,as_of_date,known_as_of,value\nNG_GDP_GROWTH_YOY,2026-06-30,2026-08-25,3.1\n",
        encoding="utf-8",
    )
    reconfirmed = tmp_path / "reconfirmed.csv"
    reconfirmed.write_text(
        "series_code,as_of_date,known_as_of,value\nNG_GDP_GROWTH_YOY,2026-06-30,2026-11-20,3.10\n",
        encoding="utf-8",
    )
    revised = tmp_path / "revised.csv"
    revised.write_text(
        "series_code,as_of_date,known_as_of,value\nNG_GDP_GROWTH_YOY,2026-06-30,2027-02-01,3.4\n",
        encoding="utf-8",
    )
    assert connector.run(db_session, path=first).rows_written == 1
    # Same value, later date, even spelled "3.10": not written, and reported as such.
    result = connector.run(db_session, path=reconfirmed)
    assert result.status == "ok" and result.records_parsed == 1 and result.rows_written == 0
    # A different value is a revision and is written.
    assert connector.run(db_session, path=revised).rows_written == 1

    series_id = db_session.execute(
        select(MacroSeries.id).where(MacroSeries.code == "NG_GDP_GROWTH_YOY")
    ).scalar_one()
    rows = db_session.execute(
        select(MacroObservation.known_as_of, MacroObservation.value)
        .where(MacroObservation.series_id == series_id)
        .order_by(MacroObservation.known_as_of)
    ).all()
    assert [(r.known_as_of, r.value) for r in rows] == [
        (dt.date(2026, 8, 25), Decimal("3.1")),
        (dt.date(2027, 2, 1), Decimal("3.4")),
    ]


@pytest.mark.invariant
def test_an_absent_value_reconfirmed_absent_is_not_a_new_vintage(
    db_session: Session, tmp_path, local_store: LocalDiskBackend
) -> None:
    """NULL followed by NULL is a continuation too; a holiday does not become two vintages."""
    connector = ManualCsvConnector("NBS")
    register(db_session, connector)
    first = tmp_path / "first.csv"
    first.write_text(
        "series_code,as_of_date,known_as_of,value\nNG_CPI_CORE,2026-07-31,2026-08-15,\n",
        encoding="utf-8",
    )
    again = tmp_path / "again.csv"
    again.write_text(
        "series_code,as_of_date,known_as_of,value\nNG_CPI_CORE,2026-07-31,2026-09-15,\n",
        encoding="utf-8",
    )
    assert connector.run(db_session, path=first).rows_written == 1
    assert connector.run(db_session, path=again).rows_written == 0


def test_a_value_returning_to_an_earlier_one_is_still_a_revision(
    db_session: Session, tmp_path, local_store: LocalDiskBackend
) -> None:
    """Only the *latest* earlier vintage is compared: A, then B, then A again is three."""
    connector = ManualCsvConnector("NBS")
    register(db_session, connector)
    vintages = (("a", "2026-08-25", "3.1"), ("b", "2026-11-20", "3.4"), ("c", "2027-02-01", "3.1"))
    for name, known, value in vintages:
        path = tmp_path / f"{name}.csv"
        path.write_text(
            f"series_code,as_of_date,known_as_of,value\nNG_GDP_GROWTH_YOY,2026-06-30,{known},{value}\n",
            encoding="utf-8",
        )
        assert connector.run(db_session, path=path).rows_written == 1, name


def test_a_run_is_recorded_under_the_name_it_was_given(
    db_session: Session, csv_path, local_store: LocalDiskBackend
) -> None:
    """A connector serving several series records each job under its own name, so one
    failing series cannot hide behind three healthy ones."""
    connector = ManualCsvConnector("NBS")
    register(db_session, connector)
    result = connector.run(db_session, run_name="manual:nbs:july", path=csv_path)
    assert result.connector_name == "manual:nbs:july"
    recorded = db_session.execute(
        select(ConnectorRun.connector_name).order_by(ConnectorRun.id.desc()).limit(1)
    ).scalar_one()
    assert recorded == "manual:nbs:july"
    # Without a name, the connector's own name - unchanged behaviour for the manual path.
    assert connector.run(db_session, path=csv_path).connector_name == "manual_csv_nbs"


@pytest.mark.invariant
def test_a_document_written_by_another_run_is_taken_not_raised(
    db_session: Session, local_store: LocalDiskBackend
) -> None:
    """The select-then-insert in `store_raw` is a race the unique index catches.

    A genuinely separate connection commits the same document between this session's
    select and its insert - which is what two jobs waking together did on 2026-09-16 -
    and the loser must take the winner's row and carry on, with its own transaction
    still usable.
    """
    from sqlalchemy import delete, event

    from packages.common.models import DataSource

    # The same database this session uses, on a connection of its own. Not
    # `packages.common.db.engine`: that is the dev database, and a competitor committed
    # there would conflict with nothing here - the first version of this test passed a
    # green assertion for that reason.
    engine = db_session.get_bind().engine

    connector = EdgarSubmissionsConnector(user_agent=UA)
    register(db_session, connector)
    raw = RawResponse(
        data=f"race fixture {uuid4().hex}".encode(),
        media_type="application/json",
        url="https://www.sec.gov/files/company_tickers.json",
        http_status=200,
    )
    digest = sha256_hex(raw.data)
    competitor_id: list[int] = []

    def commit_a_competing_row(*_args: object) -> None:
        """Runs as this session begins its flush: the other job commits first."""
        if competitor_id:
            return
        with Session(bind=engine) as other:
            source_id = (
                other.execute(select(DataSource.id).order_by(DataSource.id)).scalars().first()
            )
            document = SourceDocument(
                data_source_id=source_id,
                url=raw.url,
                storage_key=f"documents/sha256/{digest}.json",
                sha256=digest,
                media_type="application/json",
                retrieved_at=utcnow(),
            )
            other.add(document)
            other.commit()
            competitor_id.append(document.id)

    event.listen(db_session, "before_flush", commit_a_competing_row)
    try:
        stored = ingestion_base.store_raw(db_session, raw, connector=connector)
        assert competitor_id, "the competitor must have committed for this to be the race"
        assert stored.id == competitor_id[0], "we take the row the winner wrote"
        assert stored.sha256 == digest
        # The caller's transaction survived: the failed insert cost a savepoint, not the run.
        assert (
            db_session.execute(select(func.count()).select_from(SourceDocument)).scalar_one() >= 1
        )
        db_session.flush()
    finally:
        event.remove(db_session, "before_flush", commit_a_competing_row)
        if competitor_id:
            with Session(bind=engine) as cleanup:
                cleanup.execute(delete(SourceDocument).where(SourceDocument.id == competitor_id[0]))
                cleanup.commit()


def test_missed_jobs_queue_rather_than_stampede() -> None:
    """A night of misfires must not run twenty-four EDGAR jobs at once.

    `coalesce` and `max_instances` stop one job running twice; they say nothing about
    different jobs coming due together. One worker makes them queue - which is also what
    the EDGAR connector's process-wide 10 req/s throttle assumes.
    """
    from packages.scheduler.jobs import build_jobs
    from packages.scheduler.runner import build_scheduler

    scheduler = build_scheduler(build_jobs())  # built, never started: nothing to shut down
    executor = scheduler._executors["default"]
    assert executor._pool._max_workers == 1, "jobs run one after another"
    for job in scheduler.get_jobs():
        assert job.coalesce is True and job.max_instances == 1


# --------------------------------------------------------------------------------------
# P4 check 14 — point a connector at an empty page
# --------------------------------------------------------------------------------------

#: A page that still loads and carries nothing: HTTP 200, well-formed HTML, the table
#: exactly where it has always been, and not one row inside it. This is what a scraper gets
#: the morning after a site is redesigned. Nothing about it is wrong enough to raise, which
#: is the whole reason `rows_written` is counted rather than assumed.
EMPTY_PAGE = b"""<!doctype html>
<html>
  <head><title>Monetary policy rate</title></head>
  <body>
    <h1>Monetary policy rate</h1>
    <table id="rates">
      <thead><tr><th>Date</th><th>Rate</th></tr></thead>
      <tbody></tbody>
    </table>
    <p class="note">No records for the selected period.</p>
  </body>
</html>
"""

#: The same page before the redesign, carrying two decisions the selector matches.
POPULATED_PAGE = EMPTY_PAGE.replace(
    b"<tbody></tbody>",
    b"<tbody>"
    b"<tr><td>2026-09-21</td><td>27.50</td></tr>"
    b"<tr><td>2026-09-23</td><td>27.25</td></tr>"
    b"</tbody>",
)

#: Stands in for the CSS path or XPath a real scraper carries. The only property this check
#: needs from it is the one every selector has: when the markup moves it matches nothing,
#: and it does so without complaining.
ROW_SELECTOR = re.compile(rb"<tr><td>([\d-]+)</td><td>([\d.]+)</td></tr>")


class _ScrapedPageConnector(Connector):
    """A minimal scraper: fetch a page, read the rate table out of it, write the rows.

    Real enough for the check to mean something - it reads its records out of the markup
    rather than being handed them, so an empty parse here is produced the way the real one
    is - and small enough that the only behaviour under test is what `run()` does with it.
    """

    name = "scraped_page"

    def __init__(self, page: bytes) -> None:
        self._page = page

    def declare_licence(self) -> DataSourceLicence:
        return DataSourceLicence(
            source_name="Scraped Page (test)",
            licence_type="test fixture, never redistributed",
            redistribution_allowed=False,
            attribution_required=False,
            terms_reviewed_on=dt.date(2026, 9, 1),
            reviewed_by="test",
        )

    def fetch(self, **params: object) -> RawResponse:
        return RawResponse(
            data=self._page,
            media_type="text/html",
            url="https://example.invalid/rates",
            http_status=200,
        )

    def parse(self, raw: RawResponse) -> list[MacroRecord]:
        return [
            MacroRecord(
                series_code="NG_MPR",
                as_of_date=dt.date.fromisoformat(as_of.decode()),
                # A policy rate is known on the day it is announced: the two dates coincide
                # here, which no other connector may assume.
                known_as_of=dt.date.fromisoformat(as_of.decode()),
                value=Decimal(rate.decode()),
            )
            for as_of, rate in ROW_SELECTOR.findall(raw.data)
        ]


def test_an_empty_page_is_flagged_rather_than_passing_for_a_quiet_night(
    db_session: Session, local_store: LocalDiskBackend
) -> None:
    """P4 check 14: point a connector at an empty page and `rows_written=0` is flagged.

    Every other signal this run produces says the source is healthy - HTTP 200, well-formed
    HTML, no exception, a stored document, and a `connector_runs` row reading `ok`. The only
    thing that says otherwise is `connector_wrote_no_rows`, so what is asserted here is that
    the warning was **emitted**, not that the branch which would emit it exists.

    `run()` has a second zero-row warning, `every parsed record was already present`, and it
    is deliberately absent here. The two are not interchangeable. That one fires when the
    parse produced records and the database already held every one of them - a re-fetch,
    which is normal and is covered by the test below. This one fires when the parse produced
    nothing at all. `connector_wrote_no_rows` standing alone, with no such explanation beside
    it, is the shape of a selector that stopped matching rather than of a quiet night.
    """
    connector = _ScrapedPageConnector(EMPTY_PAGE)
    register(db_session, connector)
    db_session.commit()
    before = _observation_count(db_session)

    with structlog.testing.capture_logs() as logs:
        result = connector.run(db_session)

    assert result.status == "ok", result.error
    assert result.records_parsed == 0, "the page parsed cleanly - it simply held no rows"
    assert result.rows_written == 0
    assert _observation_count(db_session) == before

    # The run is recorded, and recorded as a success, which is exactly the trap.
    run_row = (
        db_session.execute(
            select(ConnectorRun)
            .where(ConnectorRun.connector_name == connector.name)
            .order_by(ConnectorRun.id.desc())
        )
        .scalars()
        .first()
    )
    assert run_row is not None
    assert run_row.status == "ok"
    assert run_row.rows_written == 0
    assert run_row.http_status == 200

    quiet = [entry for entry in logs if entry["event"] == "connector_wrote_no_rows"]
    assert len(quiet) == 1, "the silence is said out loud, exactly once"
    assert quiet[0]["log_level"] == "warning"
    assert quiet[0]["connector"] == "scraped_page"
    assert quiet[0]["records_parsed"] == 0
    assert not [e for e in logs if e["event"] == "every parsed record was already present"], (
        "nothing was parsed, so nothing can have been present already"
    )


def test_a_refetched_page_is_flagged_too_but_says_why(
    db_session: Session, local_store: LocalDiskBackend
) -> None:
    """The other zero-row path: records parsed, every one of them already stored.

    Same flag, and it must be: `rows_written` counts rows inserted, so a connector
    re-fetching an unchanged page reports zero exactly as a broken one does, and the
    detector cannot tell them apart from the count. What tells them apart is the second
    warning, which fires here and not above - so both paths are covered, or the distinction
    is only an intention.
    """
    connector = _ScrapedPageConnector(POPULATED_PAGE)
    register(db_session, connector)
    db_session.commit()
    assert connector.run(db_session).rows_written == 2

    with structlog.testing.capture_logs() as logs:
        again = connector.run(db_session)

    assert again.status == "ok"
    assert again.records_parsed == 2, "the selector still matches; the rows are simply held"
    assert again.rows_written == 0

    quiet = [entry for entry in logs if entry["event"] == "connector_wrote_no_rows"]
    assert len(quiet) == 1 and quiet[0]["records_parsed"] == 2
    explained = [e for e in logs if e["event"] == "every parsed record was already present"]
    assert len(explained) == 1, "the line that says this zero is a re-fetch, not a failure"

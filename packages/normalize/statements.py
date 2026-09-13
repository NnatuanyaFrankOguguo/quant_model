"""The versioned statement writer: first report, unchanged re-report, restatement.

Every filing re-reports earlier periods as comparatives, so one period arrives many times.
Apple's FY2024 balance sheet appears in the FY2024 10-K and in the four filings after it.
Three cases, and each is a different write:

1. **First report** — no statement exists for `(company, type, period_type, period_end)`.
   Insert version 1, `known_as_of` = the filing date, one line item per canonical key of
   the statement's template, NULL where the filing carried no mapped figure.
2. **Unchanged re-report** — every figure the new filing carries equals the current
   version's. Nothing is written. A vintage is a change in what was known; a figure
   republished unchanged is the same vintage continuing (the same rule
   `Connector.write()` applies to macro series).
3. **Restatement** — at least one figure differs, or a figure the current version lacks is
   now reported. Insert version n+1 with `known_as_of` = the restating filing's date and
   `restatement_flag` on the rows that changed; figures the new filing did not carry are
   **carried forward** from the previous version, because "as known after this filing" is
   the whole statement, not only the lines that moved. Then set `superseded_by` on the old
   statement and each of its line items — the one write the update trigger allows.

A filing older than the current version is judged against the version that was in force
on its own filing date, not against today's. Re-run the loader and every old filing
re-reports the figures that were current when it was filed - the pre-restatement ones -
and those are an **unchanged** re-report of an older vintage, not a disagreement. Only a
filing older than the current version whose figures match *no* version known on its date
is refused as **stale**: its `known_as_of` would be earlier than the version it claims to
supersede. It is logged, and the caller decides.

**Written per filing, not per row.** The database is Neon, a few hundred milliseconds
away; one round trip per statement made a trimmed Apple fixture take a minute. The writer
loads the company's current versions once, decides every case in memory, and issues one
multi-row insert for a filing's new statements, one for their line items, and one update
per table for supersession.

`docs/08` §2.3 and §10, `docs/10` §2.9–2.10, `SPEC.md` §4.1 (point-in-time only).
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any

import structlog
from sqlalchemy import insert, select, update
from sqlalchemy.orm import Session

from packages.common.models import Statement, StatementLineItem
from packages.normalize.chart import ChartVersion

__all__ = ["ReportedStatement", "StatementWriter", "WriteOutcome"]

_log = structlog.get_logger(__name__)

INSERTED = "inserted"
UNCHANGED = "unchanged"
RESTATED = "restated"
STALE = "stale"

PeriodKey = tuple[str, str, dt.date]  # (statement_type, period_type, period_end)


@dataclass(frozen=True)
class ReportedStatement:
    """One statement for one period, as one filing reported it, already in canonical keys."""

    statement_type: str  # 'income'|'balance'|'cashflow'
    period_type: str  # 'FY'|'Q1'|...
    period_start: dt.date | None
    period_end: dt.date
    fiscal_year: int
    period_label: str
    #: canonical key -> value, for the keys the filing carried. Absent keys are absent.
    values: dict[str, Decimal | None]
    accession_no: str
    form: str
    filed: dt.date

    @property
    def key(self) -> PeriodKey:
        return (self.statement_type, self.period_type, self.period_end)


@dataclass
class WriteOutcome:
    statements_inserted: int = 0
    statements_restated: int = 0
    statements_unchanged: int = 0
    statements_stale: int = 0
    line_items_inserted: int = 0


@dataclass
class _Current:
    """The un-superseded version of one period, as the writer knows it."""

    statement_id: int
    version: int
    known_as_of: dt.date
    values: dict[str, Decimal | None]
    line_item_ids: dict[str, int] = field(default_factory=dict)


class StatementWriter:
    """Writes `ReportedStatement`s for one security under one chart version."""

    def __init__(
        self,
        session: Session,
        *,
        company_id: int,
        security_id: int,
        chart: ChartVersion,
        template: str,
        currency: str,
        source_document_id: int,
        extraction_job_id: int | None,
        extraction_method: str = "xbrl",
    ) -> None:
        self._session = session
        self._company_id = company_id
        self._security_id = security_id
        self._chart = chart
        self._template = template
        self._currency = currency
        self._source_document_id = source_document_id
        self._extraction_job_id = extraction_job_id
        self._extraction_method = extraction_method
        self.outcome = WriteOutcome()
        #: period -> [(known_as_of, version, values)] for every superseded version
        self._history: dict[PeriodKey, list[tuple[dt.date, int, dict[str, Decimal | None]]]] = {}
        self._current = self._load_current()

    def write_filing(self, reported: list[ReportedStatement], *, filing_id: int) -> dict[str, int]:
        """Apply every statement one filing reported. Returns counts per case."""
        counts = {INSERTED: 0, UNCHANGED: 0, RESTATED: 0, STALE: 0}
        planned: list[tuple[ReportedStatement, _Current | None, dict[str, Decimal | None]]] = []
        for statement in reported:
            keys = self._chart.keys_for(statement.statement_type, self._template)
            current = self._current.get(statement.key)
            if current is None:
                planned.append((statement, None, {}))
                counts[INSERTED] += 1
                continue
            changed: dict[str, Decimal | None] = {
                key: value
                for key, value in statement.values.items()
                if key in keys and value is not None and current.values.get(key) != value
            }
            if not changed:
                counts[UNCHANGED] += 1
                continue
            if statement.filed < current.known_as_of:
                in_force = self._version_in_force(statement.key, statement.filed)
                if in_force is not None and not any(
                    value is not None and in_force.get(key) != value
                    for key, value in statement.values.items()
                    if key in keys
                ):
                    # The figures that were current on the filing's date: an older
                    # vintage re-reported, which a re-run produces for every old filing.
                    counts[UNCHANGED] += 1
                    continue
                _log.warning(
                    "stale_restatement_refused",
                    statement_type=statement.statement_type,
                    period_end=str(statement.period_end),
                    filed=str(statement.filed),
                    current_known_as_of=str(current.known_as_of),
                    keys=sorted(changed),
                )
                counts[STALE] += 1
                continue
            planned.append((statement, current, changed))
            counts[RESTATED] += 1

        if planned:
            self._insert_versions(planned, filing_id=filing_id)
        self.outcome.statements_inserted += counts[INSERTED]
        self.outcome.statements_unchanged += counts[UNCHANGED]
        self.outcome.statements_restated += counts[RESTATED]
        self.outcome.statements_stale += counts[STALE]
        return counts

    # -- internals ---------------------------------------------------------------------

    def _load_current(self) -> dict[PeriodKey, _Current]:
        """Every version for the company, with its line items, in two queries.

        Un-superseded versions become the working index; superseded ones are kept as
        history so an older filing can be judged against what was in force on its date.
        """
        current: dict[PeriodKey, _Current] = {}
        by_id: dict[int, _Current] = {}
        history_keys: dict[int, tuple[PeriodKey, dt.date, int]] = {}
        rows = self._session.execute(
            select(
                Statement.id,
                Statement.statement_type,
                Statement.period_type,
                Statement.period_end,
                Statement.version,
                Statement.known_as_of,
                Statement.superseded_by,
            )
            .where(Statement.company_id == self._company_id)
            .where(Statement.is_consolidated.is_(True))
        ).all()
        for statement_id, statement_type, period_type, period_end, version, known, by in rows:
            key = (statement_type, period_type, period_end)
            entry = _Current(statement_id, version, known, {})
            by_id[statement_id] = entry
            if by is None:
                current[key] = entry
            else:
                history_keys[statement_id] = (key, known, version)
        if by_id:
            items = self._session.execute(
                select(
                    StatementLineItem.statement_id,
                    StatementLineItem.id,
                    StatementLineItem.canonical_key,
                    StatementLineItem.value,
                ).where(StatementLineItem.statement_id.in_(list(by_id)))
            ).all()
            for statement_id, item_id, canonical_key, value in items:
                by_id[statement_id].values[canonical_key] = value
                by_id[statement_id].line_item_ids[canonical_key] = item_id
        for statement_id, (key, known, version) in history_keys.items():
            self._history.setdefault(key, []).append((known, version, by_id[statement_id].values))
        for versions in self._history.values():
            versions.sort()
        return current

    def _version_in_force(self, key: PeriodKey, on: dt.date) -> dict[str, Decimal | None] | None:
        """The values of the newest version whose `known_as_of` is on or before `on`."""
        candidates = [v for v in self._history.get(key, []) if v[0] <= on]
        current = self._current.get(key)
        if current is not None and current.known_as_of <= on:
            candidates.append((current.known_as_of, current.version, current.values))
        if not candidates:
            return None
        candidates.sort()
        return candidates[-1][2]

    def _insert_versions(
        self,
        planned: list[tuple[ReportedStatement, _Current | None, dict[str, Decimal | None]]],
        *,
        filing_id: int,
    ) -> None:
        statement_rows: list[dict[str, Any]] = []
        for statement, previous, _changed in planned:
            statement_rows.append(
                {
                    "filing_id": filing_id,
                    "company_id": self._company_id,
                    "statement_type": statement.statement_type,
                    "period_type": statement.period_type,
                    "period_start": statement.period_start,
                    "period_end": statement.period_end,
                    "fiscal_year": statement.fiscal_year,
                    "calendar_year": statement.period_end.year,
                    "period_label": statement.period_label,
                    "presentation_currency": self._currency,
                    "presentation_multiplier": 1,
                    "is_audited": statement.form == "10-K",
                    "is_consolidated": True,
                    "statement_template": self._template,
                    "chart_version": self._chart.version,
                    "version": previous.version + 1 if previous else 1,
                    "restatement_flag": previous is not None,
                    "known_as_of": statement.filed,
                    "source_document_id": self._source_document_id,
                }
            )
        statement_ids = list(
            self._session.execute(
                insert(Statement).returning(Statement.id, sort_by_parameter_order=True),
                statement_rows,
            ).scalars()
        )

        item_rows: list[dict[str, Any]] = []
        item_owner: list[tuple[PeriodKey, str]] = []
        new_entries: dict[PeriodKey, _Current] = {}
        for (statement, previous, _changed), statement_id in zip(
            planned, statement_ids, strict=True
        ):
            keys = self._chart.keys_for(statement.statement_type, self._template)
            previous_values = previous.values if previous else {}
            entry = _Current(
                statement_id,
                previous.version + 1 if previous else 1,
                statement.filed,
                {},
            )
            for key in keys:
                reported_value = statement.values.get(key)
                value: Decimal | None
                if reported_value is not None:
                    value = reported_value
                    changed = previous is not None and previous_values.get(key) != reported_value
                else:
                    # Not carried by this filing: absent on a first report (NULL, never 0);
                    # carried forward from the previous version on a restatement.
                    value = previous_values.get(key) if previous is not None else None
                    changed = False
                entry.values[key] = value
                item_rows.append(
                    {
                        "statement_id": statement_id,
                        "security_id": self._security_id,
                        "canonical_key": key,
                        "chart_version": self._chart.version,
                        "value": value,
                        "currency": self._currency,
                        "unit_multiplier": 1,
                        "period_start": statement.period_start,
                        "period_end": statement.period_end,
                        "known_as_of": statement.filed,
                        "version": entry.version,
                        "restatement_flag": changed,
                        "correction_type": "restatement" if changed else "none",
                        "source_document_id": self._source_document_id,
                        "page": None,
                        "extraction_job_id": self._extraction_job_id,
                        "extraction_method": self._extraction_method,
                        "confidence": None,
                    }
                )
                item_owner.append((statement.key, key))
            new_entries[statement.key] = entry

        item_ids: list[int] = []
        if item_rows:
            item_ids = list(
                self._session.execute(
                    insert(StatementLineItem).returning(
                        StatementLineItem.id, sort_by_parameter_order=True
                    ),
                    item_rows,
                ).scalars()
            )
        for (period_key, canonical_key), item_id in zip(item_owner, item_ids, strict=True):
            new_entries[period_key].line_item_ids[canonical_key] = item_id
        self.outcome.line_items_inserted += len(item_ids)

        # Supersession - the one permitted UPDATE, batched per table.
        statement_pointers: list[dict[str, int]] = []
        item_pointers: list[dict[str, int]] = []
        for statement, previous, _changed in planned:
            if previous is None:
                continue
            new = new_entries[statement.key]
            statement_pointers.append(
                {"id": previous.statement_id, "superseded_by": new.statement_id}
            )
            for canonical_key, old_item_id in previous.line_item_ids.items():
                item_pointers.append(
                    {"id": old_item_id, "superseded_by": new.line_item_ids[canonical_key]}
                )
        if statement_pointers:
            # ORM bulk UPDATE by primary key: one executemany per table, no identity-map
            # synchronisation needed because the writer keeps its own index.
            self._session.execute(update(Statement), statement_pointers)
            self._session.execute(update(StatementLineItem), item_pointers)
        for statement, previous, _changed in planned:
            if previous is not None:
                self._history.setdefault(statement.key, []).append(
                    (previous.known_as_of, previous.version, previous.values)
                )
                self._history[statement.key].sort()
        self._current.update(new_entries)

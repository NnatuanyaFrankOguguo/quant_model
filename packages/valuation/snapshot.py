"""A company as known on a date: identity, statements, price, share count, ratios.

The reads behind the `/public/companies/*` routes, kept out of the API so that the routes
stay thin and the assembly is testable without HTTP. Every read takes a decision date and
goes through the point-in-time accessor; nothing here reads "the latest value" without
saying as of when.

Provenance travels with every figure (`CLAUDE.md`): each period carries the filing it came
from, each ratio set names the statement, the price bar and the share count it used.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Literal

from sqlalchemy import func, select, tuple_
from sqlalchemy.orm import Session

from packages.common.models import (
    Company,
    DataSource,
    Exchange,
    Filing,
    PriceHistory,
    Security,
    SecurityIdentifier,
    SharesOutstanding,
    Statement,
    StatementLineItem,
)
from packages.common.pit import LineItemAsKnown, line_items_as_known_on
from packages.normalize.chart import SOURCE_SYSTEM_BY_METHOD, ChartVersion, load_chart
from packages.normalize.periods import next_expected_filing
from packages.valuation.ratios import compute_ratios

__all__ = [
    "AbsentBecause",
    "CompanySummary",
    "PeriodStatement",
    "PriceRef",
    "RatioSnapshot",
    "SecurityRef",
    "SharesRef",
    "attribution_for",
    "find_security",
    "latest_price",
    "latest_share_count",
    "list_companies",
    "ratios_for",
    "statements_as_known_on",
]


@dataclass(frozen=True)
class SecurityRef:
    security_id: int
    company_id: int
    ticker: str
    legal_name: str
    cik: str | None
    exchange: str
    currency: str
    fiscal_year_end: int
    statement_template: str


@dataclass(frozen=True)
class CompanySummary:
    ticker: str
    legal_name: str
    cik: str | None
    exchange: str
    statement_periods: int
    latest_period_end: dt.date | None
    latest_filing_date: dt.date | None
    #: The report that should come next and the last day the SEC allows for it, derived
    #: from the newest period held and the fiscal year end (`normalize.periods`). Overdue
    #: means today is past that day and the report is not held - a freshness signal.
    next_filing_form: str | None = None
    next_filing_due_by: dt.date | None = None
    filing_overdue: bool = False


AbsentBecause = Literal["not_in_filing", "no_mapping"]


@dataclass(frozen=True)
class LineItem:
    canonical_key: str
    value: Decimal | None
    known_as_of: dt.date
    version: int
    #: Why `value` is None, when it is: 'not_in_filing' (the chart maps labels for this
    #: key and the filing carried none of them) or 'no_mapping' (the chart maps nothing
    #: for this key from this source, so no filing could have filled it). None otherwise.
    absent_because: AbsentBecause | None = None
    #: True when the version in view changed this figure; then the vintage it replaced,
    #: so a reader sees what the number was and when it was that (`docs/05` §11, Q10).
    restated: bool = False
    previous_value: Decimal | None = None
    previous_known_as_of: dt.date | None = None


@dataclass(frozen=True)
class PeriodStatement:
    """One period, all three statements, as known on the decision date."""

    period_type: str
    period_end: dt.date
    fiscal_year: int
    period_label: str
    currency: str
    known_as_of: dt.date  # the newest vintage among the period's items
    items: dict[str, LineItem] = field(default_factory=dict)
    #: filing_type, filing_date, accession_no, source_document_id - of the newest vintage
    filing_type: str | None = None
    filing_date: dt.date | None = None
    accession_no: str | None = None
    source_document_id: int | None = None


@dataclass(frozen=True)
class PriceRef:
    date: dt.date
    close_raw: Decimal
    known_as_of: dt.date
    source_document_id: int


@dataclass(frozen=True)
class SharesRef:
    as_of_date: dt.date
    shares: Decimal
    basic_or_diluted: str
    known_as_of: dt.date
    source_document_id: int


@dataclass(frozen=True)
class RatioSnapshot:
    decision_date: dt.date
    period: PeriodStatement
    price: PriceRef | None
    shares: SharesRef | None
    inputs: dict[str, Decimal | None]
    ratios: dict[str, Decimal | None]


def attribution_for(session: Session, source_name: str) -> str:
    """The attribution text the licensing register requires for a source, verbatim."""
    text = session.execute(
        select(DataSource.attribution_text).where(DataSource.source_name == source_name)
    ).scalar_one_or_none()
    return text or f"Source: {source_name}"


def find_security(session: Session, ticker: str) -> SecurityRef | None:
    """The security currently carrying `ticker`, with the identity a reader needs."""
    row = session.execute(
        select(
            Security.id,
            Company.id,
            SecurityIdentifier.id_value,
            Company.legal_name,
            Company.cik,
            Exchange.code,
            Security.currency,
            Company.fiscal_year_end,
            Company.statement_template,
        )
        .join(SecurityIdentifier, SecurityIdentifier.security_id == Security.id)
        .join(Company, Company.id == Security.company_id)
        .join(Exchange, Exchange.id == Security.exchange_id)
        .where(SecurityIdentifier.id_type == "ticker")
        .where(SecurityIdentifier.id_value == ticker.strip().upper())
        .where(SecurityIdentifier.valid_to.is_(None))
    ).first()
    return SecurityRef(*row) if row else None


def list_companies(session: Session, *, today: dt.date) -> list[CompanySummary]:
    """Every registered company under its primary ticker, and how much of it is loaded.

    EDGAR lists every ticker a registrant has - JPMorgan's exchange-traded notes, Bank of
    America's preferred series - and each is a current identifier of the same security.
    The first one EDGAR lists is the common stock, and it was inserted first, so the lowest
    identifier id per security is the primary ticker. Share classes as securities of their
    own are TG2 (P3) work.
    """
    primary = (
        select(func.min(SecurityIdentifier.id).label("id"))
        .where(SecurityIdentifier.id_type == "ticker")
        .where(SecurityIdentifier.valid_to.is_(None))
        .group_by(SecurityIdentifier.security_id)
        .subquery()
    )
    periods = (
        select(
            Statement.company_id,
            func.count(func.distinct(Statement.period_end)).label("periods"),
            func.max(Statement.period_end).label("latest_period_end"),
            func.max(Statement.known_as_of).label("latest_filing_date"),
        )
        .where(Statement.superseded_by.is_(None))
        .group_by(Statement.company_id)
        .subquery()
    )
    rows = session.execute(
        select(
            SecurityIdentifier.id_value,
            Company.legal_name,
            Company.cik,
            Exchange.code,
            periods.c.periods,
            periods.c.latest_period_end,
            periods.c.latest_filing_date,
            Company.fiscal_year_end,
        )
        .join(Security, Security.id == SecurityIdentifier.security_id)
        .join(Company, Company.id == Security.company_id)
        .join(Exchange, Exchange.id == Security.exchange_id)
        .outerjoin(periods, periods.c.company_id == Company.id)
        .where(SecurityIdentifier.id.in_(select(primary.c.id)))
        .order_by(SecurityIdentifier.id_value)
    ).all()
    companies: list[CompanySummary] = []
    for r in rows:
        latest_period_end, fye_month = r[5], r[7]
        expected = (
            next_expected_filing(latest_period_end, fye_month)
            if latest_period_end is not None and fye_month is not None
            else None
        )
        companies.append(
            CompanySummary(
                ticker=r[0],
                legal_name=r[1],
                cik=r[2],
                exchange=r[3],
                statement_periods=int(r[4] or 0),
                latest_period_end=latest_period_end,
                latest_filing_date=r[6],
                next_filing_form=expected.form if expected else None,
                next_filing_due_by=expected.due_by if expected else None,
                filing_overdue=expected is not None and today > expected.due_by,
            )
        )
    return companies


def statements_as_known_on(
    session: Session,
    *,
    security_id: int,
    decision_date: dt.date,
    period_type: str | None = None,
) -> list[PeriodStatement]:
    """Every period's figures as known on the date, newest period first."""
    items = line_items_as_known_on(session, security_id=security_id, decision_date=decision_date)
    grouped: dict[tuple[str, dt.date], list[LineItemAsKnown]] = {}
    for item in items:
        if period_type is not None and item.period_type != period_type:
            continue
        grouped.setdefault((item.period_type, item.period_end), []).append(item)

    statement_ids = {item.statement_id for group in grouped.values() for item in group}
    provenance = _filing_provenance(session, statement_ids)
    charts: dict[tuple[str, str], ChartVersion] = {}
    previous = _previous_vintages(
        session,
        security_id=security_id,
        restated=[i for group in grouped.values() for i in group if i.restatement_flag],
    )

    periods: list[PeriodStatement] = []
    for (ptype, period_end), group in grouped.items():
        newest = max(group, key=lambda i: (i.known_as_of, i.version))
        filing = provenance.get(newest.statement_id)
        periods.append(
            PeriodStatement(
                period_type=ptype,
                period_end=period_end,
                fiscal_year=newest.fiscal_year,
                period_label=newest.period_label,
                currency=newest.currency,
                known_as_of=newest.known_as_of,
                items={
                    i.canonical_key: LineItem(
                        i.canonical_key,
                        i.value,
                        i.known_as_of,
                        i.version,
                        absent_because=_absent_because(session, i, charts),
                        restated=i.restatement_flag,
                        previous_value=previous.get(_vintage_key(i), (None, None))[0],
                        previous_known_as_of=previous.get(_vintage_key(i), (None, None))[1],
                    )
                    for i in group
                },
                filing_type=filing[0] if filing else None,
                filing_date=filing[1] if filing else None,
                accession_no=filing[2] if filing else None,
                source_document_id=newest.source_document_id,
            )
        )
    periods.sort(key=lambda p: (p.period_end, p.period_type), reverse=True)
    return periods


_VintageKey = tuple[str, str, dt.date, int]  # canonical_key, period_type, period_end, version


def _vintage_key(item: LineItemAsKnown) -> _VintageKey:
    return (item.canonical_key, item.period_type, item.period_end, item.version)


def _previous_vintages(
    session: Session, *, security_id: int, restated: list[LineItemAsKnown]
) -> dict[_VintageKey, tuple[Decimal | None, dt.date]]:
    """For each restated cell, the value and date of the version it replaced.

    Keyed by the *restated* item's vintage key, so the caller looks up with the item in
    hand. One query for every restated cell in the view; versions step by one per period,
    so version - 1 is the vintage that was in force before this one.
    """
    if not restated:
        return {}
    wanted = {(i.canonical_key, i.period_type, i.period_end, i.version - 1) for i in restated}
    rows = session.execute(
        select(
            StatementLineItem.canonical_key,
            Statement.period_type,
            StatementLineItem.period_end,
            StatementLineItem.version,
            StatementLineItem.value,
            StatementLineItem.known_as_of,
        )
        .join(Statement, Statement.id == StatementLineItem.statement_id)
        .where(StatementLineItem.security_id == security_id)
        .where(Statement.is_consolidated.is_(True))
        .where(
            tuple_(
                StatementLineItem.canonical_key,
                Statement.period_type,
                StatementLineItem.period_end,
                StatementLineItem.version,
            ).in_(list(wanted))
        )
    ).all()
    return {
        (key, ptype, end, version + 1): (value, known)
        for key, ptype, end, version, value, known in rows
    }


def _absent_because(
    session: Session, item: LineItemAsKnown, charts: dict[tuple[str, str], ChartVersion]
) -> AbsentBecause | None:
    """Which kind of blank a NULL figure is. Two different answers to "why is this empty?".

    'not_in_filing': the chart maps source labels for the key and the filing carried none
    of them - the company did not report it (Apple's interest expense since FY2023).
    'no_mapping': the chart version maps nothing for the key from this source, so no filing
    could have filled it (`fx_loss_net` under chart v0.1 from XBRL). The first is the
    company's silence; the second is ours, and the screen must not blame the company for it.
    """
    if item.value is not None:
        return None
    source_system = SOURCE_SYSTEM_BY_METHOD.get(item.extraction_method)
    if source_system is None:
        return "not_in_filing"
    chart_key = (item.chart_version, source_system)
    if chart_key not in charts:
        charts[chart_key] = load_chart(
            session, version=item.chart_version, source_system=source_system
        )
    return "not_in_filing" if charts[chart_key].mappings.get(item.canonical_key) else "no_mapping"


def _filing_provenance(
    session: Session, statement_ids: set[int]
) -> dict[int, tuple[str, dt.date, str | None]]:
    if not statement_ids:
        return {}
    rows = session.execute(
        select(Statement.id, Filing.filing_type, Filing.filing_date, Filing.accession_no)
        .join(Filing, Filing.id == Statement.filing_id)
        .where(Statement.id.in_(list(statement_ids)))
    ).all()
    return {r[0]: (r[1], r[2], r[3]) for r in rows}


def latest_price(session: Session, *, security_id: int, on: dt.date) -> PriceRef | None:
    """The newest bar on or before `on`, at its newest vintage known by `on`."""
    row = session.execute(
        select(
            PriceHistory.date,
            PriceHistory.close_raw,
            PriceHistory.known_as_of,
            PriceHistory.source_document_id,
        )
        .where(PriceHistory.security_id == security_id)
        .where(PriceHistory.date <= on)
        .where(PriceHistory.known_as_of <= on)
        .order_by(PriceHistory.date.desc(), PriceHistory.known_as_of.desc())
        .limit(1)
    ).first()
    return PriceRef(*row) if row else None


def latest_share_count(
    session: Session, *, security_id: int, on: dt.date, basic_or_diluted: str = "basic"
) -> SharesRef | None:
    """The newest count as of a date on or before `on`, known by `on`."""
    row = session.execute(
        select(
            SharesOutstanding.as_of_date,
            SharesOutstanding.shares,
            SharesOutstanding.basic_or_diluted,
            SharesOutstanding.known_as_of,
            SharesOutstanding.source_document_id,
        )
        .where(SharesOutstanding.security_id == security_id)
        .where(SharesOutstanding.basic_or_diluted == basic_or_diluted)
        .where(SharesOutstanding.as_of_date <= on)
        .where(SharesOutstanding.known_as_of <= on)
        .order_by(SharesOutstanding.as_of_date.desc(), SharesOutstanding.known_as_of.desc())
        .limit(1)
    ).first()
    return SharesRef(*row) if row else None


def ratios_for(
    session: Session,
    *,
    security_id: int,
    decision_date: dt.date,
    period_label: str | None = None,
) -> RatioSnapshot | None:
    """Ratios for one period - the newest FY by default - with the price and share count
    the multiples used, all as known on the decision date. None when no statements exist."""
    periods = statements_as_known_on(session, security_id=security_id, decision_date=decision_date)
    if period_label is not None:
        chosen = next((p for p in periods if p.period_label == period_label), None)
    else:
        chosen = next((p for p in periods if p.period_type == "FY"), None)
    if chosen is None:
        return None
    inputs = {key: item.value for key, item in chosen.items.items()}
    price = latest_price(session, security_id=security_id, on=decision_date)
    shares = latest_share_count(session, security_id=security_id, on=decision_date)
    ratios = compute_ratios(
        inputs,
        price=price.close_raw if price else None,
        shares=shares.shares if shares else None,
        decision_date=decision_date,
    )
    return RatioSnapshot(
        decision_date=decision_date,
        period=chosen,
        price=price,
        shares=shares,
        inputs=inputs,
        ratios=ratios,
    )

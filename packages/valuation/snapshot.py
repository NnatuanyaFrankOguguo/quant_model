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
from typing import Any, Literal

from sqlalchemy import Select, and_, func, or_, select, tuple_
from sqlalchemy.orm import Session

from packages.common.adjust import cumulative_factor, factors_known
from packages.common.identity import CIK, current_identifiers, primary_tickers, resolve_security
from packages.common.models import (
    Company,
    CorporateAction,
    DataSource,
    Exchange,
    Filing,
    MacroSeries,
    PriceHistory,
    Security,
    SharesOutstanding,
    Statement,
    StatementLineItem,
)
from packages.common.pit import LineItemAsKnown, line_items_as_known_on
from packages.common.timez import utctoday
from packages.ingestion import macro
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
    "backdrop_for",
    "dividends_for",
    "filings_for",
    "recent_filings",
    "attribution_for",
    "find_security",
    "latest_price",
    "latest_share_count",
    "list_companies",
    "ratio_history",
    "ratios_for",
    "statements_as_known_on",
    "year_on_year",
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
    #: The same figure one fiscal year earlier, as known on the same date, and the
    #: change as a fraction of it (`docs/05` §11, Q2). Both None when either side is
    #: unknown; the fraction is also None when the prior is not positive or the value
    #: has turned negative, because a change measured across a loss or a zero misleads.
    prior_value: Decimal | None = None
    change_yoy: Decimal | None = None


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
    shares: Decimal  # every class as of the date, summed
    basic_or_diluted: str
    known_as_of: dt.date
    source_document_id: int
    share_classes: tuple[str, ...] = ("ordinary",)


@dataclass(frozen=True)
class RatioPoint:
    """One period's ratios on the day it was first published, on the figures it published.

    Strictly point-in-time on every side: version-1 figures (what the market read that
    day), the price bar and the share count known on that day. A later restatement does
    not reach back into history here - it is a different vintage, visible in `statements`.
    """

    period_label: str
    period_end: dt.date
    first_published: dt.date  # known_as_of of the period's first vintage
    price: PriceRef | None
    shares: SharesRef | None
    ratios: dict[str, Decimal | None]
    reaction: PriceReaction | None = None


@dataclass(frozen=True)
class PriceReaction:
    """What the price did around a publication day (`docs/05` §11, Q6).

    Four as-traded closes: the last one before the day, the day's own, and the first
    and fifth trading days after. The returns run from the close *before* the day,
    because a report filed after the bell moves the next session, not its own. All
    four bars must exist, known by the decision date; otherwise there is no reaction,
    never a partial one.

    The closes are as traded; the returns are on closes adjusted by the corporate actions
    known on the decision date (`packages.common.adjust`), so a split inside the window is
    the non-event it was. A window still holding an implausible one-day move after that is
    an action the tables do not hold, and is withheld - see `_IMPLAUSIBLE_DAY_RATIO`.
    """

    before: PriceRef
    on_day: PriceRef
    after_1: PriceRef
    after_5: PriceRef
    return_1d: Decimal  # after_1 / before - 1, four places
    return_5d: Decimal  # after_5 / before - 1, four places


@dataclass(frozen=True)
class MacroRef:
    """One macro reading as known on the decision date, with the series it came from."""

    code: str
    name: str
    unit: str
    value: Decimal
    as_of_date: dt.date
    known_as_of: dt.date


@dataclass(frozen=True)
class Backdrop:
    """The risk-free rate and inflation a yield is read against (`docs/05` §11, Q16).

    Values are in percent, as the series carry them. `real_risk_free` is the nominal rate
    less year-on-year inflation - the everyday approximation, named as such, not the exact
    Fisher relation. None wherever a series has no reading known on the date.
    """

    risk_free: MacroRef | None
    inflation: MacroRef | None
    inflation_basis: str
    real_risk_free: Decimal | None


#: Which series stand behind a company's yields, by its reporting currency: the sovereign
#: rate a saver could take instead, and the inflation that erodes both. Nigeria has no
#: T-bill series loaded yet, so the policy rate stands in and the series name says so.
BACKDROP_BY_CURRENCY: dict[str, tuple[str, str]] = {
    "USD": ("US_10Y_TREASURY", "US_CPI_INDEX"),
    "NGN": ("NG_MPR", "NG_CPI_YOY_CBN"),
}
_INDEX_BASIS = "index: value / value twelve months earlier - 1, in percent"
_SERIES_BASIS = "series: published year-on-year rate"


@dataclass(frozen=True)
class DividendPaid:
    """One cash dividend per share: as it traded, and in the share terms of the decision date."""

    ex_date: dt.date
    cash_amount: Decimal  # per share, as traded on the ex-date
    amount_in_todays_shares: Decimal  # cash_amount x the split factors known on the date
    currency: str | None
    known_as_of: dt.date
    source_document_id: int


@dataclass(frozen=True)
class DividendYear:
    year: int
    total: Decimal  # per share, in the decision date's share terms
    count: int
    change_yoy: Decimal | None  # fraction against the prior year's total; None on a first year
    partial: bool  # the decision date's own year, still running


@dataclass(frozen=True)
class DividendHistory:
    """`docs/05` §11, Q4: does it pay, what, and has it ever cut it.

    Per-share amounts are compared in the share terms of the decision date - a 7-for-1
    split turns 3.05 a quarter into 0.47 and is not a cut - using the adjustment factors
    known on that date. A year with no dividend among the events held is a year of zero,
    and is stated as such only inside the span the events cover.
    """

    dividends: list[DividendPaid]  # oldest first
    years: list[DividendYear]  # oldest first, from the first dividend held to the date's year
    cuts: list[DividendYear]  # the complete years whose total fell below the prior year's


@dataclass(frozen=True)
class FilingSeen:
    """One filing held, as known on the decision date (`docs/05` §11, Q9)."""

    ticker: str
    legal_name: str
    cik: str | None
    filing_type: str
    filing_date: dt.date
    period_end: dt.date
    accession_no: str | None
    known_as_of: dt.date
    statement_versions: int  # statements this filing produced - 0 for one that reported nothing new


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
    """The security `ticker` names **today**, with the identity a reader needs.

    Resolution goes through `packages.common.identity`, the only module that reads the
    identifier table (`OPERATIONS.md` §1.4).

    **Why today and not the caller's decision date.** `resolve_security` answers the dated
    question, and it is tested on real dated intervals - but the ticker rows this codebase
    holds cannot yet support it. Every one was written by the EDGAR submissions connector
    with `valid_from` set to *the day the ticker was first observed*, which that connector's
    own comment calls "a lower bound on its validity, never a claim about when it began".
    Resolving `AAPL` as of 2020 against a `valid_from` of 2026-09-13 returns nothing, so
    passing the decision date here would turn every historical read into a 404 and break
    `docs/05` §11 Q31, where a copied address reproduces the view as of the date it was seen.

    Inventing a start date to paper over that would breach `SPEC.md` §4.1 - never infer
    missing data. So the ticker stays a present-tense handle for "which company the reader
    means", and the decision date governs the figures, which is where point-in-time bites.
    Real identifier intervals are manual work (`TEAM_BRIEF.md` §2.2-F, the ticker alias
    table); when they land, this passes the decision date and the docstring above goes away.
    """
    resolved = resolve_security(session, value=ticker, as_of=utctoday())
    if resolved is None:
        return None
    ciks = current_identifiers(CIK)
    row = session.execute(
        select(
            Security.id,
            Company.id,
            Company.legal_name,
            ciks.c.id_value,
            Exchange.code,
            Security.currency,
            Company.fiscal_year_end,
            Company.statement_template,
        )
        .join(Company, Company.id == Security.company_id)
        .join(Exchange, Exchange.id == Security.exchange_id)
        .outerjoin(ciks, ciks.c.security_id == Security.id)
        .where(Security.id == resolved.security_id)
    ).first()
    if row is None:
        return None
    return SecurityRef(row[0], row[1], resolved.id_value, *row[2:])


def _filings_query(decision_date: dt.date) -> Select[tuple[Any, ...]]:
    versions = (
        select(Statement.filing_id, func.count().label("versions"))
        .group_by(Statement.filing_id)
        .subquery()
    )
    primary = primary_tickers()
    ciks = current_identifiers(CIK)
    return (
        select(
            primary.c.ticker,
            Company.legal_name,
            ciks.c.id_value,
            Filing.filing_type,
            Filing.filing_date,
            Filing.period_end,
            Filing.accession_no,
            Filing.known_as_of,
            func.coalesce(versions.c.versions, 0),
        )
        .join(Company, Company.id == Filing.company_id)
        .join(Security, Security.company_id == Company.id)
        .join(primary, primary.c.security_id == Security.id)
        .outerjoin(ciks, ciks.c.security_id == Security.id)
        .outerjoin(versions, versions.c.filing_id == Filing.id)
        .where(Filing.known_as_of <= decision_date)
        .order_by(Filing.filing_date.desc(), Filing.id.desc())
    )


def filings_for(
    session: Session, *, company_id: int, decision_date: dt.date, limit: int = 50
) -> list[FilingSeen]:
    """One company's filings known on the date, newest first."""
    rows = session.execute(
        _filings_query(decision_date).where(Filing.company_id == company_id).limit(limit)
    ).all()
    return [FilingSeen(*row) for row in rows]


def recent_filings(
    session: Session, *, since: dt.date, decision_date: dt.date, limit: int = 200
) -> list[FilingSeen]:
    """Every filing across the companies held, filed on or after `since` and known on the
    decision date, newest first - "did anything new get filed this week?"."""
    rows = session.execute(
        _filings_query(decision_date).where(Filing.filing_date >= since).limit(limit)
    ).all()
    return [FilingSeen(*row) for row in rows]


def list_companies(session: Session, *, today: dt.date) -> list[CompanySummary]:
    """Every registered company under its primary ticker, and how much of it is loaded.

    EDGAR lists every ticker a registrant has - JPMorgan's exchange-traded notes, Bank of
    America's preferred series - and each is a current identifier of the same security.
    One of them is the common stock and `security_identifiers.is_primary` says which, which
    since migration 0018 is a constrained column rather than this query guessing by lowest
    id. Share classes as securities of their own are TG2 (P3) work.
    """
    primary = primary_tickers()
    ciks = current_identifiers(CIK)
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
            primary.c.ticker,
            Company.legal_name,
            ciks.c.id_value,
            Exchange.code,
            periods.c.periods,
            periods.c.latest_period_end,
            periods.c.latest_filing_date,
            Company.fiscal_year_end,
        )
        .join(Security, Security.id == primary.c.security_id)
        .join(Company, Company.id == Security.company_id)
        .join(Exchange, Exchange.id == Security.exchange_id)
        .outerjoin(ciks, ciks.c.security_id == Security.id)
        .outerjoin(periods, periods.c.company_id == Company.id)
        .order_by(primary.c.ticker)
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

    # (period_type, fiscal_year) -> key -> value, for the year-on-year comparison.
    by_year: dict[tuple[str, int], dict[str, Decimal | None]] = {}
    for (ptype, _period_end), group in sorted(grouped.items(), key=lambda kv: kv[0][1]):
        by_year[(ptype, group[0].fiscal_year)] = {i.canonical_key: i.value for i in group}

    periods: list[PeriodStatement] = []
    for (ptype, period_end), group in grouped.items():
        newest = max(group, key=lambda i: (i.known_as_of, i.version))
        filing = provenance.get(newest.statement_id)
        prior_year = by_year.get((ptype, newest.fiscal_year - 1), {})
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
                        prior_value=prior_year.get(i.canonical_key),
                        change_yoy=year_on_year(i.value, prior_year.get(i.canonical_key)),
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


def year_on_year(value: Decimal | None, prior: Decimal | None) -> Decimal | None:
    """`(value - prior) / prior`, to four places - or None when it would mislead.

    None when either side is unknown (never zero-filled), None when the prior is zero or
    negative - a loss that halves is not "-50%", growth from nothing is not infinite - and
    None when a profit has become a loss: Intel's 2024 swing from 1,689m to -18,756m is not
    "-1,210%", it is a sign change, and the two figures say so better than a fraction can.
    The prior itself travels beside the fraction, so a reader always has both numbers.
    """
    if value is None or prior is None or prior <= 0 or value < 0:
        return None
    return ((value - prior) / prior).quantize(Decimal("0.0001"))


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
    """The newest count as of a date on or before `on`, known by `on` - every class summed.

    A multi-class company reports one count per class; a P/E needs all of them. The
    newest as-of date known on `on` is taken, and every class counted at that date (at its
    newest vintage) is summed. Classes reported on different dates are not mixed.
    """
    rows = session.execute(
        select(
            SharesOutstanding.as_of_date,
            SharesOutstanding.share_class,
            SharesOutstanding.shares,
            SharesOutstanding.basic_or_diluted,
            SharesOutstanding.known_as_of,
            SharesOutstanding.source_document_id,
        )
        .where(SharesOutstanding.security_id == security_id)
        .where(SharesOutstanding.basic_or_diluted == basic_or_diluted)
        .where(SharesOutstanding.as_of_date <= on)
        .where(SharesOutstanding.known_as_of <= on)
        .order_by(SharesOutstanding.as_of_date.desc(), SharesOutstanding.known_as_of)
    ).all()
    return _sum_classes([SharesRef(r[0], r[2], r[3], r[4], r[5], (r[1],)) for r in rows])


def _sum_classes(rows: list[SharesRef]) -> SharesRef | None:
    """Rows ordered newest as-of date first, then by vintage: the newest date's classes, summed."""
    if not rows:
        return None
    as_of = rows[0].as_of_date
    newest_per_class: dict[str, SharesRef] = {}
    for row in rows:
        if row.as_of_date != as_of:
            continue
        newest_per_class[row.share_classes[0]] = row  # ordered by vintage: the last wins
    classes = sorted(newest_per_class)
    parts = [newest_per_class[c] for c in classes]
    return SharesRef(
        as_of_date=as_of,
        shares=sum((p.shares for p in parts), Decimal(0)),
        basic_or_diluted=parts[0].basic_or_diluted,
        known_as_of=max(p.known_as_of for p in parts),
        source_document_id=parts[0].source_document_id,
        share_classes=tuple(classes),
    )


#: A period first published this long after it ended is an original report. Later than
#: that it is a comparative in a later filing - XBRL begins in mid-2009, so FY2006 first
#: appears in the FY2009 10-K - and a multiple of that day's price on those figures means
#: nothing. 90 days is the longest 10-K deadline; the rest is slack for late filers.
OWN_SEASON_DAYS = 120


def ratio_history(
    session: Session,
    *,
    security_id: int,
    decision_date: dt.date,
    period_type: str = "FY",
) -> list[RatioPoint]:
    """Every period's ratios as the market first saw them, oldest first (`docs/05` §11, Q5).

    "Is 43x expensive *for this company*?" needs the multiple on the day each annual
    report came out. Three queries for the whole history: the version-1 line items of
    every period of the type, the price bars around each first-publication date, and the
    share counts. Periods first published out of their own season are left out, because
    a comparative's first XBRL appearance is not the day the market read it.
    """
    rows = session.execute(
        select(
            StatementLineItem.period_end,
            Statement.fiscal_year,
            Statement.period_label,
            StatementLineItem.canonical_key,
            StatementLineItem.value,
            StatementLineItem.known_as_of,
        )
        .join(Statement, Statement.id == StatementLineItem.statement_id)
        .where(StatementLineItem.security_id == security_id)
        .where(Statement.is_consolidated.is_(True))
        .where(Statement.period_type == period_type)
        .where(StatementLineItem.version == 1)
        .where(StatementLineItem.known_as_of <= decision_date)
    ).all()
    if not rows:
        return []
    periods: dict[dt.date, _FirstVintage] = {}
    for period_end, _fy, label, key, value, known in rows:
        entry = periods.setdefault(period_end, _FirstVintage(label, known, {}))
        # The three statements of a period normally share one filing; if not, the day by
        # which all of them were public is the day the whole set could be read.
        entry.known = max(entry.known, known)
        entry.values[key] = value
    in_season = {
        end: entry for end, entry in periods.items() if (entry.known - end).days <= OWN_SEASON_DAYS
    }
    dates = sorted({entry.known for entry in in_season.values()})
    prices = _prices_on(session, security_id=security_id, dates=dates)
    reactions = _reactions_around(
        session, security_id=security_id, dates=dates, known_by=decision_date
    )
    shares = _share_counts_on(session, security_id=security_id, dates=dates)

    points: list[RatioPoint] = []
    for end in sorted(in_season):
        entry = in_season[end]
        price = prices.get(entry.known)
        count = shares.get(entry.known)
        points.append(
            RatioPoint(
                period_label=entry.label,
                period_end=end,
                first_published=entry.known,
                price=price,
                shares=count,
                ratios=compute_ratios(
                    entry.values,
                    price=price.close_raw if price else None,
                    shares=count.shares if count else None,
                    decision_date=entry.known,
                ),
                reaction=reactions.get(entry.known),
            )
        )
    return points


@dataclass
class _FirstVintage:
    label: str
    known: dt.date
    values: dict[str, Decimal | None]


#: Enough calendar days back from a date to hold its newest trading day through any holiday.
_PRICE_LOOKBACK_DAYS = 14


def _prices_on(
    session: Session, *, security_id: int, dates: list[dt.date]
) -> dict[dt.date, PriceRef | None]:
    """`latest_price` for many dates in one query - same rule, chosen in Python per date."""
    if not dates:
        return {}
    windows = [
        and_(
            PriceHistory.date.between(on - dt.timedelta(days=_PRICE_LOOKBACK_DAYS), on),
            PriceHistory.known_as_of <= on,
        )
        for on in dates
    ]
    rows = session.execute(
        select(
            PriceHistory.date,
            PriceHistory.close_raw,
            PriceHistory.known_as_of,
            PriceHistory.source_document_id,
        )
        .where(PriceHistory.security_id == security_id)
        .where(or_(*windows))
    ).all()
    bars = [PriceRef(*r) for r in rows]
    result: dict[dt.date, PriceRef | None] = {}
    for on in dates:
        eligible = [b for b in bars if b.date <= on and b.known_as_of <= on]
        result[on] = max(eligible, key=lambda b: (b.date, b.known_as_of)) if eligible else None
    return result


#: Calendar days after a publication day that surely hold its fifth trading day.
_REACTION_LOOKAHEAD_DAYS = 12
#: After adjustment by every action known on the decision date, a close that is still this
#: many times its predecessor (or the inverse) inside the window is an action the tables do
#: not hold - the window is withheld rather than served wrong, and the reason is this name.
#: Before migration 0015 this was the only guard; Apple's 4:1 of 2020-08-31 tripped it.
_IMPLAUSIBLE_DAY_RATIO = Decimal("1.5")


def _reactions_around(
    session: Session, *, security_id: int, dates: list[dt.date], known_by: dt.date
) -> dict[dt.date, PriceReaction]:
    """The closes around each publication day, one query, chosen per day in Python.

    Bars are taken at their newest vintage known by `known_by`, the decision date - a bar
    republished later with a different close is a different vintage, as everywhere here.
    The returns are computed on closes adjusted by the corporate actions known on that
    date (`packages.common.adjust`), so a split inside the window is a non-event, as it
    was for every holder. The closes returned are still as traded.
    """
    if not dates:
        return {}
    factors = factors_known(session, security_id=security_id, decision_date=known_by)
    windows = [
        PriceHistory.date.between(
            on - dt.timedelta(days=_PRICE_LOOKBACK_DAYS),
            on + dt.timedelta(days=_REACTION_LOOKAHEAD_DAYS),
        )
        for on in dates
    ]
    rows = session.execute(
        select(
            PriceHistory.date,
            PriceHistory.close_raw,
            PriceHistory.known_as_of,
            PriceHistory.source_document_id,
        )
        .where(PriceHistory.security_id == security_id)
        .where(PriceHistory.known_as_of <= known_by)
        .where(or_(*windows))
        .order_by(PriceHistory.date, PriceHistory.known_as_of)
    ).all()
    newest: dict[dt.date, PriceRef] = {}
    for r in rows:  # ordered by vintage, so the last write per date is the newest known
        bar = PriceRef(*r)
        newest[bar.date] = bar
    trading_days = sorted(newest)
    result: dict[dt.date, PriceReaction] = {}
    for on in dates:
        before = [d for d in trading_days if d < on]
        on_or_after = [d for d in trading_days if d >= on]
        if not before or not on_or_after or on_or_after[0] != on:
            continue  # no bar on the day itself: a report on a holiday is left alone
        after = [d for d in trading_days if d > on]
        if len(after) < 5:
            continue
        window = [newest[d] for d in [before[-1], on, *after[:5]]]
        adjusted = [bar.close_raw * cumulative_factor(bar.date, factors)[0] for bar in window]
        if any(
            not (1 / _IMPLAUSIBLE_DAY_RATIO <= later / earlier <= _IMPLAUSIBLE_DAY_RATIO)
            for earlier, later in zip(adjusted, adjusted[1:], strict=False)
        ):
            continue  # an action we do not hold, inside the window: the closes would lie
        b, d0, d1, d5 = window[0], window[1], window[2], window[6]
        result[on] = PriceReaction(
            before=b,
            on_day=d0,
            after_1=d1,
            after_5=d5,
            return_1d=(adjusted[2] / adjusted[0] - 1).quantize(Decimal("0.0001")),
            return_5d=(adjusted[6] / adjusted[0] - 1).quantize(Decimal("0.0001")),
        )
    return result


def _share_counts_on(
    session: Session, *, security_id: int, dates: list[dt.date], basic_or_diluted: str = "basic"
) -> dict[dt.date, SharesRef | None]:
    """`latest_share_count` for many dates in one query - same rule, chosen per date."""
    if not dates:
        return {}
    rows = session.execute(
        select(
            SharesOutstanding.as_of_date,
            SharesOutstanding.share_class,
            SharesOutstanding.shares,
            SharesOutstanding.basic_or_diluted,
            SharesOutstanding.known_as_of,
            SharesOutstanding.source_document_id,
        )
        .where(SharesOutstanding.security_id == security_id)
        .where(SharesOutstanding.basic_or_diluted == basic_or_diluted)
        .where(SharesOutstanding.as_of_date <= max(dates))
        .order_by(SharesOutstanding.as_of_date.desc(), SharesOutstanding.known_as_of)
    ).all()
    counts = [SharesRef(r[0], r[2], r[3], r[4], r[5], (r[1],)) for r in rows]
    result: dict[dt.date, SharesRef | None] = {}
    for on in dates:
        eligible = [c for c in counts if c.as_of_date <= on and c.known_as_of <= on]
        result[on] = _sum_classes(eligible)
    return result


#: Dividends are quoted to the tenth of a cent; six places keeps every print and drops the
#: repeating digits a 7-for-1 factor brings.
_DIVIDEND_PLACES = Decimal("0.000001")


def dividends_for(session: Session, *, security_id: int, decision_date: dt.date) -> DividendHistory:
    """Every cash dividend known on the date, newest vintage per ex-date, in today's shares."""
    rows = session.execute(
        select(
            CorporateAction.ex_date,
            CorporateAction.cash_amount,
            CorporateAction.currency,
            CorporateAction.known_as_of,
            CorporateAction.source_document_id,
        )
        .where(CorporateAction.security_id == security_id)
        .where(CorporateAction.action_type == "dividend")
        .where(CorporateAction.known_as_of <= decision_date)
        .where(CorporateAction.ex_date <= decision_date)
        .order_by(CorporateAction.ex_date, CorporateAction.known_as_of)
    ).all()
    newest: dict[dt.date, tuple[Decimal, str | None, dt.date, int]] = {}
    for ex_date, amount, currency, known, document in rows:
        if amount is None:
            continue
        newest[ex_date] = (amount, currency, known, document)  # by vintage: last wins
    factors = factors_known(session, security_id=security_id, decision_date=decision_date)
    dividends = [
        DividendPaid(
            ex_date=ex_date,
            cash_amount=amount,
            amount_in_todays_shares=(amount * cumulative_factor(ex_date, factors)[0]).quantize(
                _DIVIDEND_PLACES
            ),
            currency=currency,
            known_as_of=known,
            source_document_id=document,
        )
        for ex_date, (amount, currency, known, document) in sorted(newest.items())
    ]
    if not dividends:
        return DividendHistory(dividends=[], years=[], cuts=[])

    by_year: dict[int, list[DividendPaid]] = {}
    for paid in dividends:
        by_year.setdefault(paid.ex_date.year, []).append(paid)
    years: list[DividendYear] = []
    prior_total: Decimal | None = None
    for year in range(dividends[0].ex_date.year, decision_date.year + 1):
        paid_this_year = by_year.get(year, [])
        total = sum((p.amount_in_todays_shares for p in paid_this_year), Decimal(0))
        partial = year == decision_date.year
        years.append(
            DividendYear(
                year=year,
                total=total,
                count=len(paid_this_year),
                # A running year against a complete one is not a comparison; no fraction.
                change_yoy=None if partial else year_on_year(total, prior_total),
                partial=partial,
            )
        )
        prior_total = total
    cuts = [
        y
        for prev, y in zip(years, years[1:], strict=False)
        if not y.partial and y.total < prev.total
    ]
    return DividendHistory(dividends=dividends, years=years, cuts=cuts)


def backdrop_for(session: Session, *, currency: str, decision_date: dt.date) -> Backdrop | None:
    """The risk-free rate and inflation known on the date, for a company in `currency`.

    Every reading is the newest observation dated on or before the decision date at the
    newest vintage known by it - the same point-in-time rule the macro routes apply. An
    index series (US CPI) becomes a year-on-year rate from the reading twelve months
    earlier, itself as known on the date; a published year-on-year series is used as is.
    """
    codes = BACKDROP_BY_CURRENCY.get(currency)
    if codes is None:
        return None
    rate_code, inflation_code = codes
    risk_free = _macro_reading(session, rate_code, on=decision_date)
    inflation = _macro_reading(session, inflation_code, on=decision_date)
    basis = _SERIES_BASIS
    if inflation is not None and inflation.unit == "index":
        basis = _INDEX_BASIS
        a_year_before = _macro_reading(
            session, inflation_code, on=_a_year_before(inflation.as_of_date), known_by=decision_date
        )
        if a_year_before is None or a_year_before.value <= 0:
            inflation = None
        elif a_year_before.as_of_date != _a_year_before(inflation.as_of_date):
            inflation = None  # the month a year earlier is missing: do not stretch the window
        else:
            yoy = ((inflation.value / a_year_before.value) - 1) * 100
            inflation = MacroRef(
                code=inflation.code,
                name=f"{inflation.name}, year-on-year",
                unit="percent",
                value=yoy.quantize(Decimal("0.01")),
                as_of_date=inflation.as_of_date,
                known_as_of=max(inflation.known_as_of, a_year_before.known_as_of),
            )
    real = (
        (risk_free.value - inflation.value).quantize(Decimal("0.01"))
        if risk_free is not None and inflation is not None
        else None
    )
    return Backdrop(
        risk_free=risk_free, inflation=inflation, inflation_basis=basis, real_risk_free=real
    )


def _a_year_before(day: dt.date) -> dt.date:
    try:
        return day.replace(year=day.year - 1)
    except ValueError:  # 29 February
        return day.replace(year=day.year - 1, day=28)


def _macro_reading(
    session: Session, code: str, *, on: dt.date, known_by: dt.date | None = None
) -> MacroRef | None:
    """The newest observation dated on or before `on`, as known by `known_by` (default `on`)."""
    series = session.execute(
        select(MacroSeries).where(MacroSeries.code == code)
    ).scalar_one_or_none()
    if series is None:
        return None
    points = macro.observations(session, code, end=on, as_known_on=known_by or on, limit=1)
    if not points:
        return None
    point = points[-1]
    if point.value is None:
        return None
    return MacroRef(
        code=code,
        name=series.name,
        unit=series.unit,
        value=point.value,
        as_of_date=point.as_of_date,
        known_as_of=point.known_as_of,
    )


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

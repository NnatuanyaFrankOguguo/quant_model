"""The public router - data only, no verdicts.

Everything mounted here is reachable by an anonymous caller, and by the public
after the SEC licence changes ``licence_status``. ``PublicAPIRoute`` refuses at
import time to mount a route whose ``response_model`` is not registered as a public
legal type, so the failure lands on whoever adds the route rather than on whoever
reads the response six months later.
"""

import datetime as dt
from decimal import Decimal, InvalidOperation

from fastapi import APIRouter, Depends, HTTPException, Query

from packages.common.db import get_session
from packages.common.sec import filing_index_url
from packages.common.timez import utcnow, utctoday
from packages.compliance.mode import Mode
from packages.ingestion import macro
from packages.ingestion.edgar import CHART_VERSION
from packages.ingestion.edgar import SOURCE_NAME as EDGAR_SOURCE
from packages.ingestion.yahoo import SOURCE_NAME as PRICE_SOURCE
from packages.scheduler.jobs import expected_schedule
from packages.scheduler.runner import health_report
from packages.valuation import scenarios, snapshot
from packages.valuation.dcf import DcfAssumptions, DcfResult, dcf
from services.api.deps import get_mode
from services.api.errors import FieldedHTTPException
from services.api.middleware.assert_response import PublicAPIRoute
from services.api.routers import API_V1
from services.api.schemas import (
    Backdrop,
    BackdropReading,
    CompanyDcf,
    CompanyDividends,
    CompanyFilings,
    CompanyInfo,
    CompanyList,
    CompanyRatioHistory,
    CompanyRatios,
    CompanyScenario,
    CompanyStatements,
    ConnectorHealthReport,
    DcfAssumptionsUsed,
    DcfNumbers,
    DividendPaid,
    DividendYear,
    Figure,
    FilingSeen,
    HoldingsSummary,
    JobHealth,
    MacroObservationPoint,
    MacroObservations,
    MacroSeriesInfo,
    MacroSeriesList,
    PriceBar,
    PriceReaction,
    PriceUsed,
    PublicPing,
    RatioHistoryPoint,
    RecentFilings,
    ScenarioFxEffect,
    ScenarioInput,
    ScenarioRequest,
    SharesUsed,
    StatementPeriod,
)

#: Enough for a readable chart of any series in the set, and small enough that one request
#: is bounded work. A caller wanting more narrows the window or raises the limit to the cap.
DEFAULT_OBSERVATION_LIMIT = 2000
#: Hard ceiling, enforced by the route rather than trusted to the caller.
MAX_OBSERVATION_LIMIT = 20000

router = APIRouter(prefix=f"{API_V1}/public", tags=["public"], route_class=PublicAPIRoute)


@router.get("/ping", response_model=PublicPing)
async def ping(mode: Mode = Depends(get_mode)) -> PublicPing:
    """Return the mode the *server* derived for this caller.

    Not a constant. The value comes from the middleware, which derived it from the
    principal behind the credential and from ``licence_status`` - never from
    anything in this request. That is what makes ``docs/03`` P0.8's injection tests
    worth running: they assert on a value that actually flows through the gate.
    """
    return PublicPing(mode=mode)


@router.get("/macro/series", response_model=MacroSeriesList)
async def macro_series() -> MacroSeriesList:
    """Every macro series, with its as-of date and whether it has gone overdue.

    No `mode` parameter and no principal check: published government statistics are
    public-tier content in every mode. Access is still restricted to owner and family by
    who can obtain a token, not by what this route serves (`CLAUDE.md`'s access model).
    """
    with get_session() as session:
        summaries = macro.list_series(session)
        return MacroSeriesList(
            as_of=utctoday(),
            series=[
                MacroSeriesInfo(
                    code=s.code,
                    name=s.name,
                    unit=s.unit,
                    frequency=s.frequency,
                    base_period=s.base_period,
                    source_name=s.source_name,
                    attribution=s.attribution,
                    expected_lag_days=s.expected_lag_days,
                    observation_count=s.observation_count,
                    latest_as_of=s.latest_as_of,
                    latest_known_as_of=s.latest_known_as_of,
                    latest_value=s.latest_value,
                    days_since_as_of=s.days_since_as_of,
                    is_stale=s.is_stale,
                )
                for s in summaries
            ],
        )


@router.get("/macro/series/{code}/observations", response_model=MacroObservations)
async def macro_observations(
    code: str,
    start: dt.date | None = Query(default=None, description="Earliest period to return"),
    end: dt.date | None = Query(default=None, description="Latest period to return"),
    as_known_on: dt.date | None = Query(
        default=None,
        description=(
            "Point-in-time view: exclude vintages published after this date. Omit to see "
            "each period at its newest vintage."
        ),
    ),
    limit: int = Query(
        default=DEFAULT_OBSERVATION_LIMIT,
        ge=1,
        le=MAX_OBSERVATION_LIMIT,
        description=(
            "Maximum points to return, taking the most recent. Responses say "
            "`truncated` and `total_available` so a partial series is never mistaken "
            "for a whole one."
        ),
    ),
) -> MacroObservations:
    """The observation array for one series.

    `as_known_on` is the parameter that makes this honest. Without it a caller sees today's
    view of history, in which every restatement has always been known — which is exactly the
    lookahead that makes a P7 backtest profitable and wrong.

    **The limit is not decoration.** `US_10Y_TREASURY` holds 16,876 periods; an unbounded
    endpoint meant one request did unbounded work, which is a slow dashboard today and a
    trivial way to exhaust the server at P12. The cap is enforced by the route, so no caller
    can opt out of it.
    """
    with get_session() as session:
        summary = macro.series_summary(session, code)
        if summary is None:
            raise HTTPException(status_code=404, detail="not_found")
        page = macro.observation_page(
            session, code, start=start, end=end, as_known_on=as_known_on, limit=limit
        )
        return MacroObservations(
            code=summary.code,
            name=summary.name,
            unit=summary.unit,
            source_name=summary.source_name,
            attribution=summary.attribution,
            as_known_on=as_known_on,
            total_available=page.total_available,
            truncated=page.truncated,
            observations=[
                MacroObservationPoint(
                    as_of_date=p.as_of_date, known_as_of=p.known_as_of, value=p.value
                )
                for p in page.points
            ],
        )


# ---------------------------------------------------------------------------------------
# P2 - companies: statements, ratios, DCF. Facts and arithmetic on stated inputs.
# ---------------------------------------------------------------------------------------


@router.get("/operations/connectors", response_model=ConnectorHealthReport)
async def operations_connectors(
    window_days: int = Query(default=30, ge=1, le=365),
) -> ConnectorHealthReport:
    """Every scheduled job and manual path, judged - the operations page's one call.

    Derived from the job list the scheduler runs, so a job cannot be forgotten here;
    a job that has never run in the window is reported, because its silence is the
    failure the health check exists to catch.
    """
    checked_at = utcnow()
    with get_session() as session:
        rows = health_report(
            session, expected=expected_schedule(), window_days=window_days, now=checked_at
        )
    levels = [r.level for r in rows]
    return ConnectorHealthReport(
        checked_at=checked_at,
        window_days=window_days,
        needs_a_human=any(level != "ok" for level in levels),
        ok=levels.count("ok"),
        warning=levels.count("warning"),
        error=levels.count("error"),
        never_ran=levels.count("never_ran"),
        jobs=[
            JobHealth(
                name=r.name,
                scheduled_at_utc=r.scheduled_at_utc,
                expected=r.expected,
                last_run_at=r.last_run_at,
                last_status=r.last_status,
                runs_in_window=r.runs_in_window,
                rows_in_window=r.rows_in_window,
                level=r.level,
                finding=r.finding,
            )
            for r in rows
        ],
    )


@router.get("/summary", response_model=HoldingsSummary)
async def holdings_summary() -> HoldingsSummary:
    """How much of each kind of thing is held. Three scalars, counted in the database.

    Exists so a front page does not have to fetch every company and add the periods up
    itself - AD-3 puts a displayed figure on the server, and the count of economic series
    had no endpoint behind it at all, so it had been typed into the page by hand and had
    drifted from thirteen to a hard-coded fourteen without anything noticing.
    """
    with get_session() as session:
        counts = snapshot.holdings_summary(session)
    return HoldingsSummary(
        counted_at=utctoday(),
        companies=counts.companies,
        statement_periods=counts.statement_periods,
        macro_series=counts.macro_series,
    )


@router.get("/companies", response_model=CompanyList)
async def companies() -> CompanyList:
    """Every registered company under its primary ticker, with how much of it is loaded."""
    with get_session() as session:
        rows = snapshot.list_companies(session, today=utctoday())
    return CompanyList(
        companies=[
            CompanyInfo(
                ticker=r.ticker,
                legal_name=r.legal_name,
                cik=r.cik,
                exchange=r.exchange,
                statement_periods=r.statement_periods,
                latest_period_end=r.latest_period_end,
                latest_filing_date=r.latest_filing_date,
                next_filing_form=r.next_filing_form,
                next_filing_due_by=r.next_filing_due_by,
                filing_overdue=r.filing_overdue,
            )
            for r in rows
        ]
    )


@router.get("/companies/{ticker}/statements", response_model=CompanyStatements)
async def company_statements(
    ticker: str,
    as_known_on: dt.date | None = Query(
        default=None,
        description=(
            "Point-in-time view: figures and restatements filed after this date are unseen. "
            "Defaults to today."
        ),
    ),
    period_type: str | None = Query(
        default=None, description="FY, Q1, Q2, Q3, H1 or YTD. Omit for all."
    ),
) -> CompanyStatements:
    """A company's statements, every period, as known on a date.

    Every figure carries the filing that made it public. `null` means the company did not
    report the item - it is never zero-filled (`SPEC.md` §4.1).
    """
    decision_date = as_known_on or utctoday()
    with get_session() as session:
        ref = snapshot.find_security(session, ticker)
        if ref is None:
            raise HTTPException(status_code=404, detail="not_found")
        periods = snapshot.statements_as_known_on(
            session,
            security_id=ref.security_id,
            decision_date=decision_date,
            period_type=period_type,
        )
        attribution = snapshot.attribution_for(session, EDGAR_SOURCE)
    return CompanyStatements(
        ticker=ref.ticker,
        legal_name=ref.legal_name,
        cik=ref.cik,
        exchange=ref.exchange,
        fiscal_year_end_month=ref.fiscal_year_end,
        chart_version=CHART_VERSION,
        as_known_on=decision_date,
        attribution=attribution,
        periods=[
            StatementPeriod(
                period_type=p.period_type,
                period_end=p.period_end,
                fiscal_year=p.fiscal_year,
                period_label=p.period_label,
                currency=p.currency,
                known_as_of=p.known_as_of,
                filing_type=p.filing_type,
                filing_date=p.filing_date,
                accession_no=p.accession_no,
                filing_url=filing_index_url(ref.cik, p.accession_no),
                source_document_id=p.source_document_id,
                items={
                    key: Figure(
                        value=i.value,
                        known_as_of=i.known_as_of,
                        version=i.version,
                        absent_because=i.absent_because,
                        restated=i.restated,
                        previous_value=i.previous_value,
                        previous_known_as_of=i.previous_known_as_of,
                        prior_value=i.prior_value,
                        change_yoy=i.change_yoy,
                        correction_type=i.correction_type,
                        corrected_by=i.corrected_by,
                        corrected_at=i.corrected_at,
                        correction_reason=i.correction_reason,
                    )
                    for key, i in p.items.items()
                },
            )
            for p in periods
        ],
    )


@router.get("/companies/{ticker}/ratios", response_model=CompanyRatios)
async def company_ratios(
    ticker: str,
    period: str | None = Query(
        default=None, description="A period label such as FY2025. Defaults to the newest FY."
    ),
    as_known_on: dt.date | None = Query(
        default=None, description="Point-in-time date for statements, price and share count."
    ),
) -> CompanyRatios:
    """Ratios and trailing multiples for one period, with the price and share count used.

    The share count is the one true as of the price date, never today's - a bonus issue
    changes the denominator with no cash moving (`docs/08` §2.14). A ratio with a missing
    input is null; a P/E on a loss is null; every key is always present.
    """
    decision_date = as_known_on or utctoday()
    with get_session() as session:
        ref = snapshot.find_security(session, ticker)
        if ref is None:
            raise HTTPException(status_code=404, detail="not_found")
        snap = snapshot.ratios_for(
            session, security_id=ref.security_id, decision_date=decision_date, period_label=period
        )
        if snap is None:
            raise HTTPException(status_code=404, detail="not_found")
        attribution = snapshot.attribution_for(session, EDGAR_SOURCE)
        price_attribution = snapshot.attribution_for(session, PRICE_SOURCE)
        backdrop = snapshot.backdrop_for(
            session, currency=snap.period.currency, decision_date=decision_date
        )
        # Inside the session block, with the rest of the reads. The move comes from
        # `price_move` rather than being derived from two closes here: it is computed on
        # adjusted closes, so a split between the bars cannot turn a rise into a 75%
        # fall. AD-3 also puts the arithmetic on this side of the wire.
        move = (
            snapshot.price_move(session, security_id=ref.security_id, on=decision_date)
            if snap.price
            else None
        )
    price = (
        PriceUsed(
            date=snap.price.date,
            close_raw=snap.price.close_raw,
            known_as_of=snap.price.known_as_of,
            age_days=(decision_date - snap.price.date).days,
            source_document_id=snap.price.source_document_id,
            attribution=price_attribution,
            previous_close_raw=move.previous_close_raw if move else None,
            previous_date=move.previous_date if move else None,
            change=move.change if move else None,
            actions_between=move.actions_applied if move else 0,
        )
        if snap.price
        else None
    )
    shares = (
        SharesUsed(
            as_of_date=snap.shares.as_of_date,
            shares=snap.shares.shares,
            share_classes=list(snap.shares.share_classes),
            basic_or_diluted=snap.shares.basic_or_diluted,
            known_as_of=snap.shares.known_as_of,
            source_document_id=snap.shares.source_document_id,
        )
        if snap.shares
        else None
    )
    return CompanyRatios(
        ticker=ref.ticker,
        legal_name=ref.legal_name,
        as_known_on=decision_date,
        period_label=snap.period.period_label,
        period_end=snap.period.period_end,
        known_as_of=snap.period.known_as_of,
        filing_type=snap.period.filing_type,
        accession_no=snap.period.accession_no,
        source_document_id=snap.period.source_document_id,
        currency=snap.period.currency,
        attribution=attribution,
        price=price,
        shares=shares,
        inputs=snap.inputs,
        ratios=snap.ratios,
        backdrop=_backdrop(backdrop),
    )


def _reading(ref: snapshot.MacroRef | None) -> BackdropReading | None:
    if ref is None:
        return None
    return BackdropReading(
        code=ref.code,
        name=ref.name,
        unit=ref.unit,
        value=ref.value,
        as_of_date=ref.as_of_date,
        known_as_of=ref.known_as_of,
    )


def _backdrop(b: snapshot.Backdrop | None) -> Backdrop | None:
    if b is None:
        return None
    return Backdrop(
        risk_free=_reading(b.risk_free),
        inflation=_reading(b.inflation),
        inflation_basis=b.inflation_basis,
        real_risk_free=b.real_risk_free,
    )


#: A week, for "did anything new get filed this week?" - the default window of /filings/recent.
RECENT_FILINGS_DAYS = 7


def _filing_seen(f: snapshot.FilingSeen) -> FilingSeen:
    return FilingSeen(
        ticker=f.ticker,
        legal_name=f.legal_name,
        filing_type=f.filing_type,
        filing_date=f.filing_date,
        period_end=f.period_end,
        accession_no=f.accession_no,
        filing_url=filing_index_url(f.cik, f.accession_no),
        known_as_of=f.known_as_of,
        statement_versions=f.statement_versions,
    )


@router.get("/filings/recent", response_model=RecentFilings)
async def filings_recent(
    since: dt.date | None = Query(
        default=None, description="Filings filed on or after this date; default: the last 7 days."
    ),
    as_known_on: dt.date | None = Query(
        default=None, description="Filings known on this date; nothing after it."
    ),
) -> RecentFilings:
    """Every filing across the companies held since a date, newest first (docs/05 §11, Q9)."""
    decision_date = as_known_on or utctoday()
    start = since or decision_date - dt.timedelta(days=RECENT_FILINGS_DAYS)
    with get_session() as session:
        rows = snapshot.recent_filings(session, since=start, decision_date=decision_date)
        attribution = snapshot.attribution_for(session, EDGAR_SOURCE)
    return RecentFilings(
        since=start,
        as_known_on=decision_date,
        attribution=attribution,
        filings=[_filing_seen(f) for f in rows],
    )


@router.get("/companies/{ticker}/filings", response_model=CompanyFilings)
async def company_filings(
    ticker: str,
    as_known_on: dt.date | None = Query(
        default=None, description="Filings known on this date; nothing after it."
    ),
    limit: int = Query(default=50, ge=1, le=500),
) -> CompanyFilings:
    """One company's filings held, newest first, each with its folder on sec.gov."""
    decision_date = as_known_on or utctoday()
    with get_session() as session:
        ref = snapshot.find_security(session, ticker)
        if ref is None:
            raise HTTPException(status_code=404, detail="not_found")
        rows = snapshot.filings_for(
            session, company_id=ref.company_id, decision_date=decision_date, limit=limit
        )
        attribution = snapshot.attribution_for(session, EDGAR_SOURCE)
    return CompanyFilings(
        ticker=ref.ticker,
        legal_name=ref.legal_name,
        as_known_on=decision_date,
        attribution=attribution,
        filings=[_filing_seen(f) for f in rows],
    )


@router.get("/companies/{ticker}/dividends", response_model=CompanyDividends)
async def company_dividends(
    ticker: str,
    as_known_on: dt.date | None = Query(
        default=None, description="Dividends and splits known on this date; nothing after it."
    ),
) -> CompanyDividends:
    """Every cash dividend per share the actions hold, by year, with the cuts named.

    Amounts are compared in the share terms of the decision date, using the split factors
    known on it, so a split is not a cut. A year with no dividend among the events held
    is a year of zero, stated only inside the span the events cover.
    """
    decision_date = as_known_on or utctoday()
    with get_session() as session:
        ref = snapshot.find_security(session, ticker)
        if ref is None:
            raise HTTPException(status_code=404, detail="not_found")
        history = snapshot.dividends_for(
            session, security_id=ref.security_id, decision_date=decision_date
        )
        attribution = snapshot.attribution_for(session, PRICE_SOURCE)
    paid = [
        DividendPaid(
            ex_date=d.ex_date,
            cash_amount=d.cash_amount,
            amount_in_todays_shares=d.amount_in_todays_shares,
            currency=d.currency,
            known_as_of=d.known_as_of,
            source_document_id=d.source_document_id,
        )
        for d in history.dividends
    ]
    latest = paid[-1] if paid else None
    return CompanyDividends(
        ticker=ref.ticker,
        legal_name=ref.legal_name,
        as_known_on=decision_date,
        currency=ref.currency,
        attribution=attribution,
        pays=latest is not None and (decision_date - latest.ex_date).days <= 15 * 31,
        latest=latest,
        dividends=paid,
        years=[
            DividendYear(
                year=y.year,
                total=y.total,
                count=y.count,
                change_yoy=y.change_yoy,
                partial=y.partial,
            )
            for y in history.years
        ],
        cuts=[
            DividendYear(
                year=y.year,
                total=y.total,
                count=y.count,
                change_yoy=y.change_yoy,
                partial=y.partial,
            )
            for y in history.cuts
        ],
    )


@router.get("/companies/{ticker}/ratios/history", response_model=CompanyRatioHistory)
async def company_ratio_history(
    ticker: str,
    period_type: str = Query(default="FY", description="'FY' or a quarter such as 'Q1'"),
    as_known_on: dt.date | None = Query(
        default=None, description="Periods first published after this date are unseen."
    ),
) -> CompanyRatioHistory:
    """Ratios at every past publication date - the multiple as the market first saw it.

    Each point uses the period's first-published figures with the price and share count
    known on its filing date; nothing later reaches back. Comparatives that first appeared
    in XBRL long after their period are left out.
    """
    decision_date = as_known_on or utctoday()
    with get_session() as session:
        ref = snapshot.find_security(session, ticker)
        if ref is None:
            raise HTTPException(status_code=404, detail="not_found")
        points = snapshot.ratio_history(
            session,
            security_id=ref.security_id,
            decision_date=decision_date,
            period_type=period_type,
        )
        attribution = snapshot.attribution_for(session, EDGAR_SOURCE)
        price_attribution = snapshot.attribution_for(session, PRICE_SOURCE)
    return CompanyRatioHistory(
        ticker=ref.ticker,
        legal_name=ref.legal_name,
        as_known_on=decision_date,
        period_type=period_type,
        currency=ref.currency,
        attribution=attribution,
        price_attribution=price_attribution,
        points=[
            RatioHistoryPoint(
                period_label=p.period_label,
                period_end=p.period_end,
                first_published=p.first_published,
                price=(
                    PriceUsed(
                        date=p.price.date,
                        close_raw=p.price.close_raw,
                        known_as_of=p.price.known_as_of,
                        age_days=(p.first_published - p.price.date).days,
                        source_document_id=p.price.source_document_id,
                        attribution=price_attribution,
                    )
                    if p.price
                    else None
                ),
                shares=(
                    SharesUsed(
                        as_of_date=p.shares.as_of_date,
                        shares=p.shares.shares,
                        share_classes=list(p.shares.share_classes),
                        basic_or_diluted=p.shares.basic_or_diluted,
                        known_as_of=p.shares.known_as_of,
                        source_document_id=p.shares.source_document_id,
                    )
                    if p.shares
                    else None
                ),
                ratios=p.ratios,
                reaction=_reaction(p.reaction),
            )
            for p in points
        ],
    )


def _bar(ref: snapshot.PriceRef) -> PriceBar:
    return PriceBar(date=ref.date, close_raw=ref.close_raw, known_as_of=ref.known_as_of)


def _reaction(r: snapshot.PriceReaction | None) -> PriceReaction | None:
    if r is None:
        return None
    return PriceReaction(
        before=_bar(r.before),
        on_day=_bar(r.on_day),
        after_1=_bar(r.after_1),
        after_5=_bar(r.after_5),
        return_1d=r.return_1d,
        return_5d=r.return_5d,
    )


@router.post("/companies/{ticker}/scenario", response_model=CompanyScenario)
async def company_scenario(ticker: str, request: ScenarioRequest) -> CompanyScenario:
    """Run the caller's assumptions against the company's stored facts. P6.1, T8.

    Both sides come back - the figures as reported and the figures under the scenario -
    because a scenario on its own is a number with nothing to read it against.

    Nothing here is chosen by the system. `SPEC.md` T8's acceptance criterion is that the
    model does not pick the rates, so an absent one is a 422 naming it rather than a
    default, and a rate move naming nothing exposed to it is refused rather than costed
    at zero. A missing *fact* is named the same way: an operator who supplies forty
    figures and is told only `invalid_request` has no way to find the one at fault, which
    is what `FieldedHTTPException` exists for.

    Compute only. Saving a scenario is per principal, and this is a public route with no
    principal to save it against.
    """
    decision_date = request.as_known_on or utctoday()
    try:
        assumptions = scenarios.ScenarioAssumptions(
            growth_rates=tuple(request.growth_rates),
            discount_rate=request.discount_rate,
            terminal_growth=request.terminal_growth,
            mid_year=request.mid_year,
            base_free_cash_flow=request.base_free_cash_flow,
            net_debt=request.net_debt,
            shares=request.shares,
            overrides=dict(request.overrides),
            fx=(
                scenarios.FxShock(
                    scenario_rate=request.fx.scenario_rate,
                    base_rate=request.fx.base_rate,
                    cost_exposure=request.fx.cost_exposure,
                    revenue_exposure=request.fx.revenue_exposure,
                    foreign_debt=request.fx.foreign_debt,
                    tax_rate=request.fx.tax_rate,
                )
                if request.fx is not None
                else None
            ),
            period_label=request.period_label,
        )
    except scenarios.ScenarioRefusedError as refused:
        raise _refused(refused) from None
    except ValueError:
        raise HTTPException(status_code=422, detail="invalid_request") from None

    with get_session() as session:
        ref = snapshot.find_security(session, ticker)
        if ref is None:
            raise HTTPException(status_code=404, detail="not_found")
        try:
            facts = scenarios.facts_for(
                session,
                security_id=ref.security_id,
                inputs_as_of=decision_date,
                period_label=request.period_label,
            )
            result = scenarios.run_scenario(assumptions, facts)
        except scenarios.ScenarioRefusedError as refused:
            raise _refused(refused) from None
        except ValueError:
            raise HTTPException(status_code=422, detail="invalid_request") from None

    return CompanyScenario(
        ticker=ref.ticker,
        legal_name=ref.legal_name,
        inputs_as_of=result.facts.inputs_as_of,
        currency=result.facts.currency or ref.currency,
        period_label=result.facts.period_label,
        inputs=[
            ScenarioInput(name=item.name, value=_input_value(item.value), source=item.source)
            for item in result.inputs
        ],
        line_items_as_reported=dict(result.line_items_as_reported),
        line_items_under_scenario=dict(result.line_items_under_scenario),
        fx=(
            ScenarioFxEffect(
                base_rate=result.fx.base_rate,
                scenario_rate=result.fx.scenario_rate,
                move=result.fx.move,
                revenue_effect=result.fx.revenue_effect,
                cost_effect=result.fx.cost_effect,
                operating_pre_tax=result.fx.operating_pre_tax,
                operating_after_tax=result.fx.operating_after_tax,
                debt_revaluation=result.fx.debt_revaluation,
            )
            if result.fx is not None
            else None
        ),
        dcf=_dcf_numbers(result.dcf),
        dcf_before_fx=(
            _dcf_numbers(result.dcf_before_fx) if result.dcf_before_fx is not None else None
        ),
        ratios=dict(result.ratios),
        ratios_as_reported=dict(result.ratios_as_reported),
        code_version=result.code_version,
    )


def _refused(error: scenarios.ScenarioRefusedError) -> HTTPException:
    """A refusal, naming the fields at fault where the engine knows them.

    `docs/10` §4.7: the body still says only `invalid_request` about *what* was wrong -
    the names of the inputs are not their values - but naming them is the difference
    between an error somebody can act on and one they stop reading.
    """
    missing = getattr(error, "missing", ())
    if missing:
        return FieldedHTTPException(status_code=422, detail="invalid_request", fields=list(missing))
    return HTTPException(status_code=422, detail="invalid_request")


def _input_value(value: object) -> str | list[str] | bool | None:
    """A resolved input for the wire. Decimals become strings, as everywhere else here."""
    if value is None or isinstance(value, bool):
        return value
    if isinstance(value, tuple | list):
        return [str(part) for part in value]
    return str(value)


def _dcf_numbers(result: DcfResult) -> DcfNumbers:
    return DcfNumbers(
        projected_free_cash_flow=list(result.projected_free_cash_flow),
        discount_factors=list(result.discount_factors),
        present_values=list(result.present_values),
        sum_of_present_values=result.sum_of_present_values,
        terminal_value=result.terminal_value,
        present_value_of_terminal=result.present_value_of_terminal,
        enterprise_value=result.enterprise_value,
        equity_value=result.equity_value,
        value_per_share=result.value_per_share,
        terminal_share_of_value=result.terminal_share_of_value,
    )


@router.get("/companies/{ticker}/dcf", response_model=CompanyDcf)
async def company_dcf(
    ticker: str,
    growth: str = Query(
        description=(
            "Growth rate per projected year as fractions, comma-separated: 0.08,0.06,0.04. "
            "Yours - the model never chooses it."
        )
    ),
    discount_rate: Decimal = Query(description="Discount rate (WACC) as a fraction: 0.09"),
    terminal_growth: Decimal = Query(description="Perpetual growth after the projection"),
    base_free_cash_flow: Decimal | None = Query(
        default=None,
        description="Starting free cash flow. Defaults to the newest FY cash_from_ops - capex.",
    ),
    net_debt: Decimal | None = Query(
        default=None, description="Debt less cash. Defaults to the newest FY balance sheet."
    ),
    shares: Decimal | None = Query(
        default=None, description="Share count. Defaults to the newest known basic count."
    ),
    mid_year: bool = Query(default=False, description="Mid-year discounting convention"),
    as_known_on: dt.date | None = Query(default=None, description="Point-in-time date"),
) -> CompanyDcf:
    """Run the DCF on the caller's assumptions, joined to the company's stored facts.

    Every input is echoed with where it came from. A 422 means a default could not be read
    from the statements as known on the date; supply the figure explicitly.
    """
    decision_date = as_known_on or utctoday()
    try:
        growth_rates = tuple(Decimal(part.strip()) for part in growth.split(",") if part.strip())
    except (InvalidOperation, ValueError):
        raise HTTPException(status_code=422, detail="invalid_request") from None
    with get_session() as session:
        ref = snapshot.find_security(session, ticker)
        if ref is None:
            raise HTTPException(status_code=404, detail="not_found")
        snap = snapshot.ratios_for(
            session, security_id=ref.security_id, decision_date=decision_date
        )
        share_count = snapshot.latest_share_count(
            session, security_id=ref.security_id, on=decision_date
        )
    inputs = snap.inputs if snap else {}
    period_label = snap.period.period_label if snap else None

    fcf_source = "user"
    if base_free_cash_flow is None:
        ops, capex = inputs.get("cash_from_ops"), inputs.get("capex")
        if ops is None or capex is None or period_label is None:
            raise HTTPException(status_code=422, detail="invalid_request")
        base_free_cash_flow = ops - capex
        fcf_source = f"{period_label}: cash_from_ops - capex"
    debt_source = "user"
    if net_debt is None:
        debt, cash = inputs.get("long_term_debt"), inputs.get("cash")
        if debt is None or cash is None or period_label is None:
            raise HTTPException(status_code=422, detail="invalid_request")
        net_debt = debt - cash
        debt_source = f"{period_label}: long_term_debt - cash"
    shares_source: str | None = "user" if shares is not None else None
    if shares is None and share_count is not None:
        shares = share_count.shares
        shares_source = (
            f"shares_outstanding as of {share_count.as_of_date} ({share_count.basic_or_diluted})"
        )

    assumptions = DcfAssumptions(
        base_free_cash_flow=base_free_cash_flow,
        growth_rates=growth_rates,
        discount_rate=discount_rate,
        terminal_growth=terminal_growth,
        net_debt=net_debt,
        shares=shares,
        mid_year=mid_year,
    )
    try:
        result = dcf(assumptions)
    except ValueError:
        raise HTTPException(status_code=422, detail="invalid_request") from None
    return CompanyDcf(
        ticker=ref.ticker,
        legal_name=ref.legal_name,
        as_known_on=decision_date,
        currency=ref.currency,
        assumptions=DcfAssumptionsUsed(
            base_free_cash_flow=assumptions.base_free_cash_flow,
            base_free_cash_flow_source=fcf_source,
            growth_rates=list(assumptions.growth_rates),
            discount_rate=assumptions.discount_rate,
            terminal_growth=assumptions.terminal_growth,
            net_debt=assumptions.net_debt,
            net_debt_source=debt_source,
            shares=assumptions.shares,
            shares_source=shares_source,
            mid_year=assumptions.mid_year,
        ),
        projected_free_cash_flow=list(result.projected_free_cash_flow),
        discount_factors=list(result.discount_factors),
        present_values=list(result.present_values),
        sum_of_present_values=result.sum_of_present_values,
        terminal_value=result.terminal_value,
        present_value_of_terminal=result.present_value_of_terminal,
        enterprise_value=result.enterprise_value,
        equity_value=result.equity_value,
        value_per_share=result.value_per_share,
        terminal_share_of_value=result.terminal_share_of_value,
    )

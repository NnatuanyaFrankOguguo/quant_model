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
from packages.common.timez import utctoday
from packages.compliance.mode import Mode
from packages.ingestion import macro
from packages.ingestion.edgar import CHART_VERSION
from packages.ingestion.edgar import SOURCE_NAME as EDGAR_SOURCE
from packages.ingestion.yahoo import SOURCE_NAME as PRICE_SOURCE
from packages.valuation import snapshot
from packages.valuation.dcf import DcfAssumptions, dcf
from services.api.deps import get_mode
from services.api.middleware.assert_response import PublicAPIRoute
from services.api.routers import API_V1
from services.api.schemas import (
    CompanyDcf,
    CompanyInfo,
    CompanyList,
    CompanyRatios,
    CompanyStatements,
    DcfAssumptionsUsed,
    Figure,
    MacroObservationPoint,
    MacroObservations,
    MacroSeriesInfo,
    MacroSeriesList,
    PriceUsed,
    PublicPing,
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


@router.get("/companies", response_model=CompanyList)
async def companies() -> CompanyList:
    """Every registered company under its primary ticker, with how much of it is loaded."""
    with get_session() as session:
        rows = snapshot.list_companies(session)
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
    price = (
        PriceUsed(
            date=snap.price.date,
            close_raw=snap.price.close_raw,
            known_as_of=snap.price.known_as_of,
            age_days=(decision_date - snap.price.date).days,
            source_document_id=snap.price.source_document_id,
            attribution=price_attribution,
        )
        if snap.price
        else None
    )
    shares = (
        SharesUsed(
            as_of_date=snap.shares.as_of_date,
            shares=snap.shares.shares,
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

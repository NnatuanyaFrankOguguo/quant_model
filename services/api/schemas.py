"""Response models for the P0 API, and the public/personal type split.

The split is the point. ``docs/10_PRE_BUILD_CORRECTIONS.md`` 4.3 rejects "one type
with a nullable advice field" because that downgrades a type-level guarantee to a
runtime convention defended by a single CHECK on the write path. So the public and
personal pings are *different types*, and only the public one is registered in
:func:`packages.compliance.response_types.public_legal_types`. Copy the personal
handler into the public router and the request fails with a 500 rather than
answering.

``@register_public_type`` also walks each model's fields at import time and refuses
any advice-shaped name, so the day someone adds ``target`` to a public model the
build breaks rather than the gate.
"""

from __future__ import annotations

import datetime as dt
from datetime import date
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, Field

from packages.compliance.mode import Mode
from packages.compliance.response_types import register_public_type

__all__ = [
    "CompanyDcf",
    "CompanyInfo",
    "CompanyList",
    "CompanyRatios",
    "CompanyStatements",
    "DcfAssumptionsUsed",
    "DocumentStored",
    "ErrorBody",
    "Figure",
    "Health",
    "ManualEntryAccepted",
    "ManualStatementIn",
    "MacroObservationPoint",
    "MacroObservations",
    "MacroSeriesInfo",
    "MacroSeriesList",
    "PersonalPing",
    "PersonalSignal",
    "PriceUsed",
    "PublicPing",
    "SharesUsed",
    "StatementPeriod",
    "TypedFigureIn",
]


@register_public_type
class Health(BaseModel):
    """Liveness, plus the two facts that make it worth calling."""

    status: str = Field(description="'ok', or 'degraded' when the database is unreachable")
    version: str = Field(description="Application version")
    db: str = Field(description="'ok' or 'error'")
    migrations: str = Field(description="Current alembic revision, or 'unknown'")


class JobHealth(BaseModel):
    """One job the schedule expects, judged: ok, warning, error, or never ran."""

    name: str
    scheduled_at_utc: str | None = Field(
        default=None,
        description=(
            "'HH:MM' UTC for a job that runs once a day, '**:MM' for one that runs "
            "every hour, or null for a path a human feeds"
        ),
    )
    expected: bool
    last_run_at: dt.datetime | None = None
    last_status: str | None = None
    runs_in_window: int
    rows_in_window: int
    level: str = Field(description="'ok' | 'warning' | 'error' | 'never_ran'")
    finding: str | None = Field(default=None, description="What needs a human, when something does")


@register_public_type
class ConnectorHealthReport(BaseModel):
    """Every job, judged, plus the counts a glance needs. Operational facts only."""

    checked_at: dt.datetime
    window_days: int
    needs_a_human: bool
    ok: int
    warning: int
    error: int
    never_ran: int
    jobs: list[JobHealth]


@register_public_type
class PublicPing(BaseModel):
    """Proves the public router and mode derivation work.

    ``mode`` is the **server-derived** mode for the calling principal, not a
    constant. That distinction is the whole value of this endpoint: if it returned
    a hardcoded ``"public"``, ``docs/03`` P0.8's four injection tests would be
    asserting on a literal and would pass forever regardless of whether the gate
    worked. An entitled caller therefore sees ``"personal"`` here - which discloses
    nothing they do not already know, and keeps the tests honest.
    """

    mode: Mode


class PersonalPing(BaseModel):
    """Proves entitlement gating works. Deliberately **not** a public-legal type."""

    mode: Mode


class PersonalSignal(BaseModel):
    """The canonical advice-shaped payload. Never public-legal, in any phase.

    A placeholder in P0 - P8 fills in the real contract from
    ``docs/08_DATA_CONTRACTS.md`` 8, including ``authorised_by_backtest``. It exists
    now because the compliance suite needs a payload that *must* raise on a public
    route, and because it documents by example why ``PUBLIC_LEGAL_TYPES`` is an
    allow-list: every field below is a field a public response may never carry.
    """

    security: str
    direction: str
    calibrated_prob: float
    position_size: float
    backtest_run_id: int


class TypedFigureIn(BaseModel):
    """One figure as the operator read it off the page.

    `printed` is what the page shows, verbatim - brackets, currency mark, dash and all. An
    **empty string means the line is not on the page**, which is stored as NULL. It is not a
    zero, and `SPEC.md` 4.1 is why: a debt-to-equity of 0.0 for a company whose debt line was
    never read is an answer, confidently wrong, and indistinguishable from a real one.
    """

    canonical_key: str = Field(min_length=1)
    printed: str = ""
    page: int = Field(ge=1)


class ManualStatementIn(BaseModel):
    """One statement typed from one uploaded document. P3.2.

    There is deliberately no `reviewed_by` field. The name attached to a hand-typed figure is
    the authenticated principal's, taken by the server - a caller who could name the reviewer
    could attribute their typing to somebody else, and the whole value of the column is that
    it says who to ask.
    """

    #: The ticker, as every other company route is addressed. Not the internal
    #: `security_id`: that is a surrogate key, no client can obtain one from the public API,
    #: and widening a public response to expose it would be the wrong way round.
    ticker: str = Field(min_length=1, max_length=32)
    #: Which market, when a ticker is listed on more than one. Omitted searches them all and
    #: is refused if two answer, rather than picking whichever sorted first.
    exchange: str | None = None
    statement_type: str = Field(pattern="^(income|balance|cashflow)$")
    period_type: str = Field(min_length=1)
    period_end: dt.date
    #: When the **issuer published**, not when this was typed. It decides whether a
    #: point-in-time read on some past date is allowed to see these figures.
    known_as_of: dt.date
    currency: str = Field(min_length=3, max_length=3)
    #: As the statement's own column heading declares it: units, thousands or millions.
    scale: str
    source_document_id: int
    figures: list[TypedFigureIn] = Field(min_length=1)
    period_start: dt.date | None = None
    is_audited: bool = True
    is_consolidated: bool = True
    chart_version: str = "v1"


class ReviewQueueItem(BaseModel):
    """One thing a reviewer should look at, and why it is where it is in the list.

    `priority` is not shown for its own sake - `docs/03` P4.4 asks for a queue ordered by
    materiality because *"a FIFO queue wastes your scarcest resource - reviewer attention -
    on trivia"*. So the components come too: a reviewer who disagrees with the ordering can
    see what produced it rather than having to trust it.
    """

    company_id: int
    company_name: str
    period_type: str
    period_end: dt.date
    finding: str
    detail: str
    canonical_key: str | None
    priority: Decimal
    severity: Decimal
    #: The figure as a share of its statement's anchor. 0 when there was nothing to divide by.
    share_of_anchor: Decimal
    is_required: bool
    #: How many periods share this finding. More than one means systematic - a mapping or a
    #: definition rather than a typo - which is the most useful thing to know before opening
    #: anything.
    occurrences: int
    first_period: dt.date | None


class ReviewQueue(BaseModel):
    """What needs a human, worst first. Not registered public-legal.

    It names companies alongside figures this system believes are wrong, which is an
    internal judgement and not a fact about the company. Publishing it anonymously would
    be publishing an accusation.
    """

    generated_at: dt.datetime
    #: How many items were returned, which is not how many exist - see `limit`.
    shown: int
    limit: int
    items: list[ReviewQueueItem]


class CorrectionRateReport(BaseModel):
    """`docs/03` P4.4's headline metric: *"if it isn't falling, the extractor isn't
    learning and something is wrong with the feedback loop."*

    `restatements` is reported beside `our_corrections` and excluded from the rate. A
    company restating its own figures is the world changing its mind, not this system
    getting it wrong, and counting them would show a falling error rate every time a filer
    revised something - or a rising one, equally meaninglessly.
    """

    period_start: dt.date
    period_end: dt.date
    items_written: int
    our_corrections: int
    restatements: int
    #: `our_corrections / items_written`. `None` when nothing was written in the window,
    #: because a rate over zero items is not zero - it is unknown, and a dashboard showing
    #: 0.0% for a week nothing ran would read as the best week on record.
    correction_rate: Decimal | None


class ManualEntryAccepted(BaseModel):
    """What was written. Not registered public-legal: a personal-tier surface only."""

    statement_id: int
    line_items_written: int
    #: Figures stored as NULL because the company did not report them. Worth returning: a
    #: form that silently absorbed a mistyped key would show "12 written" either way.
    figures_absent: int
    keys: list[str]
    #: The name the server attached, echoed back so the operator can see whose it was.
    reviewed_by: str


class DocumentStored(BaseModel):
    """An uploaded report's place in the store. P3.1."""

    document_id: int
    sha256: str
    page_count: int
    #: False when these exact bytes were already held, which makes the upload a no-op.
    created: bool


class MacroSeriesInfo(BaseModel):
    """One macro series, with the two things `CLAUDE.md` requires on every figure.

    Every response carries an **as-of date** and a **staleness flag**, because a number on a
    screen with neither is a number a reader will trust for longer than it deserves.
    ``attribution`` travels with the data rather than living in a footer: the licensing
    register says attribution is required for these sources, and a client that never
    receives the text cannot display it.
    """

    code: str
    name: str
    unit: str
    frequency: str
    base_period: str | None = Field(
        default=None,
        description="'CPI 2024=100'. Rebasing changes past values, so it is part of identity.",
    )
    source_name: str
    attribution: str | None = None
    expected_lag_days: int
    observation_count: int
    latest_as_of: date | None = Field(
        default=None, description="The period the newest observation describes"
    )
    latest_known_as_of: date | None = Field(
        default=None, description="When that observation was published — not the same date"
    )
    latest_value: Decimal | None = None
    days_since_as_of: int | None = None
    is_stale: bool | None = Field(
        default=None,
        description=(
            "True when the newest period is older than expected_lag_days. **null means not "
            "applicable** — an irregular series such as the MPR, or one with no data yet — "
            "never 'fresh'."
        ),
    )


@register_public_type
class MacroSeriesList(BaseModel):
    """Published government statistics. Public-tier content in every mode.

    "Public tier" is the *content class*, not who may log in: access is still owner plus
    family until the licence changes (`CLAUDE.md`'s access model).
    """

    series: list[MacroSeriesInfo]
    as_of: date = Field(description="The date staleness was evaluated against, in UTC")


class MacroObservationPoint(BaseModel):
    """One observation at one vintage."""

    as_of_date: date = Field(description="The period this value describes")
    known_as_of: date = Field(description="The date this value was published")
    value: Decimal | None = Field(
        default=None,
        description="null means genuinely no observation. It is never zero-filled.",
    )


@register_public_type
class MacroObservations(BaseModel):
    """A series and its points, at the newest vintage visible on ``as_known_on``."""

    code: str
    name: str
    unit: str
    source_name: str
    attribution: str | None = None
    as_known_on: date | None = Field(
        default=None,
        description=(
            "When set, vintages published after this date were excluded — the "
            "point-in-time view. When null, each period shows its newest vintage."
        ),
    )
    total_available: int = Field(
        description="Periods matching the query, before any limit was applied."
    )
    truncated: bool = Field(
        description=(
            "True when fewer points were returned than exist. The points are the MOST "
            "RECENT ones; narrow the window with start/end, or raise limit, to see more. "
            "Never ignore this: a partial series charted as a whole one is a different series."
        )
    )
    observations: list[MacroObservationPoint]


class ErrorBody(BaseModel):
    """The fixed public error vocabulary (``docs/10`` 4.7).

    Error bodies, logs and Sentry sit outside all five mechanisms: an exception is
    raised before a response exists, and a traceback carrying a repr of a local
    ``PersonalMemo(verdict=...)`` would go into the 500 body. So public-mode errors
    are drawn from a closed vocabulary - ``not_found``, ``invalid_request`` (field
    *name* only, never the value), ``rate_limited``, ``forbidden``, ``internal`` -
    plus a ``request_id`` that ties the response to its ``audit_log`` row.
    """

    detail: str
    request_id: str | None = None
    fields: list[str] | None = Field(
        default=None,
        description="Names of the request fields that failed validation. Never their values.",
    )


# ---------------------------------------------------------------------------------------
# P2 - companies, statements, ratios, DCF. Facts and arithmetic on the caller's inputs;
# no field here is a verdict, and the registry refuses any that is named like one.
# ---------------------------------------------------------------------------------------


class CompanyInfo(BaseModel):
    """One registered company under its primary ticker, and how much of it is loaded."""

    ticker: str
    legal_name: str
    cik: str | None = None
    exchange: str
    statement_periods: int = Field(description="Distinct periods with a current statement")
    latest_period_end: date | None = None
    latest_filing_date: date | None = Field(
        default=None, description="known_as_of of the newest statement - when it was filed"
    )
    next_filing_form: str | None = Field(
        default=None, description="The report that should come next: '10-K' or '10-Q'"
    )
    next_filing_due_by: date | None = Field(
        default=None,
        description=(
            "The last day the SEC allows for it, for any filer category - derived from the "
            "fiscal year end, not from the company's own calendar"
        ),
    )
    filing_overdue: bool = Field(
        default=False,
        description="True when that day has passed and the report is not held - a freshness flag",
    )


@register_public_type
class CompanyList(BaseModel):
    companies: list[CompanyInfo]


@register_public_type
class HoldingsSummary(BaseModel):
    """How much of each kind of thing is held - what a front page leads with.

    Counted here rather than by the caller. A page that adds these up for itself is
    computing a displayed figure, which AD-3 puts on the server, and it also has to
    fetch every record to do it.
    """

    counted_at: date = Field(description="The day these counts were taken")
    companies: int = Field(description="Companies held under a primary ticker")
    statement_periods: int = Field(
        description=(
            "Distinct (company, period_end) pairs across statements that have not been "
            "superseded - two companies reporting the same quarter is two periods held"
        )
    )
    macro_series: int = Field(description="Economic series registered, loaded or not")


class Figure(BaseModel):
    """One line item at the vintage visible on the decision date."""

    value: Decimal | None = Field(
        default=None,
        description="null is never zero-filled; absent_because says which kind of null it is",
    )
    known_as_of: date = Field(description="The filing date that made this figure public")
    version: int = Field(description="1 for the first report; higher after a restatement")
    absent_because: Literal["not_in_filing", "no_mapping"] | None = Field(
        default=None,
        description=(
            "Set only when value is null. 'not_in_filing': the company did not report it. "
            "'no_mapping': this chart version maps nothing for the key from this source, so "
            "the blank is ours, not the company's."
        ),
    )
    restated: bool = Field(
        default=False,
        description="True when the version in view changed this figure (not a carry-forward)",
    )
    previous_value: Decimal | None = Field(
        default=None, description="When restated: the figure this version replaced"
    )
    previous_known_as_of: date | None = Field(
        default=None,
        description="When restated: the filing date that had made the old figure public",
    )
    prior_value: Decimal | None = Field(
        default=None,
        description="The same figure one fiscal year earlier, as known on the same date",
    )
    change_yoy: Decimal | None = Field(
        default=None,
        description=(
            "(value - prior) / prior as a fraction, four places. null when either side is "
            "unknown, the prior is not positive, or the value has turned negative - a change "
            "measured across a loss or a zero misleads"
        ),
    )
    correction_type: str = Field(
        default="none",
        description=(
            "'none' on an untouched figure. 'transcription' or 'extraction' means we "
            "misread it and fixed it, and the row keeps the ORIGINAL known_as_of so a "
            "point-in-time read before the fix does not return the error. 'restatement' "
            "means the company republished, and carries the new publication date."
        ),
    )
    corrected_by: str | None = Field(
        default=None, description="Who corrected this figure by hand, when one did"
    )
    corrected_at: dt.datetime | None = Field(
        default=None, description="When the correction was applied (not when it took effect)"
    )
    correction_reason: str | None = Field(
        default=None, description="Why it was corrected - required of every correction"
    )


class StatementPeriod(BaseModel):
    """One period - income, balance sheet and cash flow together - with its provenance."""

    period_type: str = Field(description="'FY'|'Q1'|'Q2'|'Q3'|'H1'|'YTD'")
    period_end: date
    fiscal_year: int
    period_label: str = Field(description="'FY2025', 'Q1-FY2026' - the company's convention")
    currency: str
    known_as_of: date = Field(description="Newest vintage among the period's figures")
    filing_type: str | None = Field(default=None, description="'10-K' or '10-Q'")
    filing_date: date | None = None
    accession_no: str | None = Field(default=None, description="EDGAR accession number")
    filing_url: str | None = Field(
        default=None,
        description="The filing's folder in the SEC archive - open it to see the source",
    )
    source_document_id: int | None = None
    items: dict[str, Figure] = Field(description="canonical key -> figure")


@register_public_type
class CompanyStatements(BaseModel):
    """A company's statements as known on a date. Restatements filed after it are unseen."""

    ticker: str
    legal_name: str
    cik: str | None = None
    exchange: str
    fiscal_year_end_month: int
    chart_version: str
    as_known_on: date = Field(description="The point-in-time date every figure respects")
    attribution: str
    periods: list[StatementPeriod]


class PriceUsed(BaseModel):
    # `dt.date`, not `date`: the field is named `date` and would shadow the type.
    date: dt.date
    close_raw: Decimal = Field(description="As traded. Never an adjusted price.")
    known_as_of: dt.date
    age_days: int = Field(
        description=(
            "Days between the bar and the decision date. A multiple on an old price is a "
            "different number from a multiple on today's; this says which you have."
        )
    )
    source_document_id: int
    attribution: str


class SharesUsed(BaseModel):
    as_of_date: date = Field(description="The date the count was true of - never today's")
    shares: Decimal = Field(description="Every class counted at that date, summed")
    share_classes: list[str] = Field(
        default_factory=list,
        description="['ordinary'] for a single-class company; the class members otherwise",
    )
    basic_or_diluted: str
    known_as_of: date
    source_document_id: int


class BackdropReading(BaseModel):
    """One macro reading, as known on the decision date, and the series it came from."""

    code: str
    name: str
    unit: str = Field(description="'percent' for every reading served here")
    value: Decimal
    as_of_date: date
    known_as_of: date


class Backdrop(BaseModel):
    """What a yield is read against: the sovereign rate a saver could take instead, and the
    inflation that erodes both. Percent, as the series carry them; the ratios beside them
    are fractions. Nothing here is a verdict - the reader makes the comparison."""

    risk_free: BackdropReading | None = None
    inflation: BackdropReading | None = Field(
        default=None, description="Year-on-year, in percent; see inflation_basis"
    )
    inflation_basis: str = Field(
        description="How the year-on-year rate was obtained: a published rate, or an index "
        "against its reading twelve months earlier"
    )
    real_risk_free: Decimal | None = Field(
        default=None,
        description="risk_free minus inflation, percent - the everyday approximation, not Fisher",
    )


@register_public_type
class CompanyRatios(BaseModel):
    """Ratios for one period, with the price and share count the multiples used.

    A ratio is a fact and ships in every mode. Any ratio with a missing input is null -
    never 0, never infinity - and every key is always present, so 'not applicable' can be
    told from 'no price was available'.
    """

    ticker: str
    legal_name: str
    as_known_on: date
    period_label: str
    period_end: date
    known_as_of: date
    filing_type: str | None = None
    accession_no: str | None = None
    source_document_id: int | None = None
    currency: str
    attribution: str
    price: PriceUsed | None = Field(
        default=None, description="null when no price on or before the date was known"
    )
    shares: SharesUsed | None = Field(
        default=None, description="null when no share count on or before the date was known"
    )
    inputs: dict[str, Decimal | None] = Field(description="The line items the ratios used")
    ratios: dict[str, Decimal | None]
    backdrop: Backdrop | None = Field(
        default=None,
        description="The risk-free rate and inflation known on the date, for the company's "
        "currency; null when no series backs that currency",
    )


class PriceBar(BaseModel):
    """One as-traded close, with the vintage it was known at."""

    date: dt.date
    close_raw: Decimal
    known_as_of: dt.date


class PriceReaction(BaseModel):
    """What the price did around a publication day. Returns run from the close before the
    day, because a report filed after the bell moves the next session, not its own."""

    before: PriceBar
    on_day: PriceBar
    after_1: PriceBar
    after_5: PriceBar
    return_1d: Decimal = Field(description="after_1 / before - 1, a fraction to four places")
    return_5d: Decimal = Field(description="after_5 / before - 1, a fraction to four places")


class RatioHistoryPoint(BaseModel):
    """One period's ratios on the day it was first published, on the figures it published."""

    period_label: str
    period_end: date
    first_published: date = Field(
        description="The filing date of the period's first vintage - the day the market read it"
    )
    price: PriceUsed | None = Field(
        default=None, description="The bar known on that day; null when none was"
    )
    shares: SharesUsed | None = Field(
        default=None, description="The count known on that day; null when none was"
    )
    ratios: dict[str, Decimal | None] = Field(
        description="Every ratio key, always present; null wherever an input was missing"
    )
    reaction: PriceReaction | None = Field(
        default=None,
        description=(
            "The closes around the publication day and the returns from the close before "
            "it; null unless all four bars exist and were known by the decision date. As "
            "traded: a window holding an implausible one-day move (a split) is withheld"
        ),
    )


class DividendPaid(BaseModel):
    """One cash dividend per share, as it traded and in the decision date's share terms."""

    ex_date: date
    cash_amount: Decimal = Field(description="Per share, gross, as traded on the ex-date")
    amount_in_todays_shares: Decimal = Field(
        description="cash_amount times the split factors known on the decision date, so "
        "amounts across a split compare like for like"
    )
    currency: str | None = None
    known_as_of: date
    source_document_id: int


class DividendYear(BaseModel):
    year: int
    total: Decimal = Field(description="Per share, in the decision date's share terms")
    count: int = Field(description="Dividends with an ex-date in the year, among those held")
    change_yoy: Decimal | None = Field(
        default=None, description="Against the prior year's total; null on the first year"
    )
    partial: bool = Field(description="True for the decision date's own year, still running")


@register_public_type
class CompanyDividends(BaseModel):
    """Does it pay, what, and has it ever cut it - from the corporate actions held.

    Per-share amounts are compared in the share terms of the decision date, using the
    split factors known on it: a 7-for-1 that turns 3.05 a quarter into 0.47 is not a cut.
    A cut is a complete year whose total fell below the prior year's. Nothing here is a
    forecast of the next payment.
    """

    ticker: str
    legal_name: str
    as_known_on: date
    currency: str
    attribution: str
    pays: bool = Field(description="At least one dividend with an ex-date in the last 15 months")
    latest: DividendPaid | None = None
    dividends: list[DividendPaid] = Field(description="Oldest first")
    years: list[DividendYear] = Field(
        description="Every year from the first dividend held to the decision date's year"
    )
    cuts: list[DividendYear] = Field(description="Complete years whose total fell")


class FilingSeen(BaseModel):
    """One filing held, with the door into the SEC archive."""

    ticker: str
    legal_name: str
    filing_type: str = Field(description="'10-K', '10-Q', ...")
    filing_date: date
    period_end: date = Field(description="The newest period the filing reported")
    accession_no: str | None = None
    filing_url: str | None = Field(default=None, description="The filing's folder on sec.gov")
    known_as_of: date
    statement_versions: int = Field(
        description="Statements this filing produced; 0 when it reported nothing new"
    )


@register_public_type
class CompanyFilings(BaseModel):
    """One company's filings, newest first, as known on the date."""

    ticker: str
    legal_name: str
    as_known_on: date
    attribution: str
    filings: list[FilingSeen]


@register_public_type
class RecentFilings(BaseModel):
    """Every filing across the companies held since a date - what is new this week."""

    since: date
    as_known_on: date
    attribution: str
    filings: list[FilingSeen] = Field(description="Newest first")


@register_public_type
class CompanyRatioHistory(BaseModel):
    """Ratios at every past publication date, so today's multiple has its own context.

    Strictly point-in-time on every side: the figures each report first published, and the
    price and share count known that day. Later restatements do not reach back into this
    history. Periods first published out of their own season - comparatives that first
    appeared in XBRL years after the fact - are left out, because a multiple of that day's
    price on those figures would mean nothing.
    """

    ticker: str
    legal_name: str
    as_known_on: date
    period_type: str
    currency: str
    attribution: str
    price_attribution: str
    points: list[RatioHistoryPoint] = Field(description="Oldest first")


class DcfAssumptionsUsed(BaseModel):
    """Every input the model ran on. The user's assumptions, and the facts they were joined to."""

    base_free_cash_flow: Decimal
    base_free_cash_flow_source: str = Field(
        description="'user' when supplied; otherwise the statement period it was read from"
    )
    growth_rates: list[Decimal]
    discount_rate: Decimal
    terminal_growth: Decimal
    net_debt: Decimal
    net_debt_source: str
    shares: Decimal | None = None
    shares_source: str | None = None
    mid_year: bool


@register_public_type
class CompanyDcf(BaseModel):
    """A discounted-cash-flow result computed from the caller's own assumptions.

    The growth, discount and terminal rates are the caller's; the model never chooses them.
    The base cash flow, net debt and share count default to the company's stored figures
    as known on the date and are echoed back so the arithmetic can be checked line by
    line. This is arithmetic on stated inputs, not an opinion about the company.
    """

    ticker: str
    legal_name: str
    as_known_on: date
    currency: str
    assumptions: DcfAssumptionsUsed
    projected_free_cash_flow: list[Decimal]
    discount_factors: list[Decimal]
    present_values: list[Decimal]
    sum_of_present_values: Decimal
    terminal_value: Decimal
    present_value_of_terminal: Decimal
    enterprise_value: Decimal
    equity_value: Decimal
    value_per_share: Decimal | None = None
    terminal_share_of_value: Decimal | None = Field(
        default=None,
        description=(
            "PV of the terminal value over enterprise value. If a 100 bp change in the "
            "discount rate barely moves the answer, look here first."
        ),
    )

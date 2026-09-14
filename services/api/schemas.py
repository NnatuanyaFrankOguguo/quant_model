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
    "ErrorBody",
    "Figure",
    "Health",
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
]


@register_public_type
class Health(BaseModel):
    """Liveness, plus the two facts that make it worth calling."""

    status: str = Field(description="'ok', or 'degraded' when the database is unreachable")
    version: str = Field(description="Application version")
    db: str = Field(description="'ok' or 'error'")
    migrations: str = Field(description="Current alembic revision, or 'unknown'")


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


@register_public_type
class CompanyList(BaseModel):
    companies: list[CompanyInfo]


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
    shares: Decimal
    basic_or_diluted: str
    known_as_of: date
    source_document_id: int


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

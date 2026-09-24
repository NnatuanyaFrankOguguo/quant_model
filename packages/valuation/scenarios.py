"""Named assumption sets: the owner's own numbers in, a DCF and a ratio set out. P6.1, T8.

`docs/03` P6.1 and `SPEC.md` T8: *user assumptions → DCF and ratio outputs*, and **no
auto-generated targets**. `DATA_FOUNDATION.md` §6.5 puts it in the negative — *"No
recommendations; no auto price targets; user-set assumptions only."* Every number in a
saved assumption set was typed by a person. Where a figure came from the company's own
statements instead, it is a *fact*, it is read point-in-time, and the result says on that
line where it came from. The engine refuses to run rather than choose a discount rate,
and it names the fields it is missing, which is what the `/companies/{ticker}/dcf` route
already does when a rate is absent.

## Nothing is stored but the assumptions and the date

`docs/08` §2.9 gives `scenarios` no result column, and carries `inputs_as_of` with the
note *"US-060: must reproduce identical output"* instead. A cached answer is one frozen
vintage that goes stale the moment a filing is restated, and it would make P6 check 7 —
*same assumptions, identical output* — a comparison of a cache with itself. So the
assumptions and the decision date are kept and **the answer is recomputed**.

That only works if every read is point-in-time, which is why `inputs_as_of` is threaded
into every read here exactly as `snapshot.py` threads `decision_date`, and why nothing in
this module defaults a date to today. Re-running a scenario reads the statements, the
price and the share count *as they were knowable on `inputs_as_of`*, so a filing published
afterwards cannot move the answer. A *correction* to a figure already known on that date
will move it — deliberately, because the correction says the old figure was never true
(`docs/10` §2.10), and that is precisely the change a cached result would have hidden.

## The layering

`docs/08` §6: compute functions take data and return data and do no I/O. Everything above
the `PERSISTENCE` banner is pure — `run_scenario(assumptions, facts)` is a function of its
two arguments and nothing else, testable against hand-written vectors with no database.
Everything below the banner reads and writes rows, and computes nothing.

## What a scenario can actually say

Three levers, and each must be typed:

1. **The DCF's own inputs** — growth, discount rate, terminal growth, and optionally the
   base cash flow, net debt and share count. Passed straight to `packages.valuation.dcf`.
2. **Line-item overrides** — *"assume revenue is ₦1.2tn, not the ₦1.0tn they reported"*.
   The user's figure replaces the reported one before anything else is computed.
3. **An exchange-rate move** (`FxShock`) — P6 check 13 and `docs/05` Q19: *"naira at
   ₦2,000/$ for an importer should hurt materially; if the model shrugs, an assumption is
   not wired through."* A rate on its own cannot hurt anybody, so a shock must also name
   **what is exposed** to it — the share of cost of sales that is priced in dollars, the
   share of revenue that is, the foreign-currency debt — and a shock with no exposure
   typed is refused rather than quietly returning the same answer as before. That refusal
   is the mechanism that stops the model shrugging.

The exchange-rate arithmetic, in full, with `move = scenario_rate / base_rate - 1`:

    cost effect        = cost_of_revenue × cost_exposure     × move      (a cost, so a loss)
    revenue effect     = revenue         × revenue_exposure  × move      (a gain)
    operating, pre-tax = revenue effect - cost effect
    operating, cash    = operating, pre-tax × (1 - tax_rate)
    debt revaluation   = foreign_debt × (scenario_rate - base_rate)

The debt revaluation is **non-cash and not tax-effected**: it raises net debt and reduces
reported profit through `fx_loss_net`, and it does not touch operating cash flow. That is
a convention, it is stated here so a reader can disagree with it, and an unrealised
translation loss is generally not deductible in Nigeria anyway. The operating effect is
the one that reaches free cash flow, and it reaches it whether the base cash flow was read
from the statements or typed by the user — a shock that could be silently bypassed by
typing a base cash flow would be the shrug this module exists to prevent.

`Decimal` throughout (`docs/08` §1.6): assumptions are stored in JSONB **as strings**, so
what comes back out of the database is the number that went in, to the digit.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation, localcontext
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from packages.common.fx import rate_on
from packages.common.models import Scenario, Security
from packages.valuation import snapshot
from packages.valuation.dcf import DcfAssumptions, DcfResult, dcf
from packages.valuation.ratios import compute_ratios

__all__ = [
    "CODE_VERSION",
    "INPUT_KEYS",
    "FxEffect",
    "FxShock",
    "MissingAssumptionsError",
    "MissingFactsError",
    "ResolvedInput",
    "ScenarioAssumptions",
    "ScenarioExistsError",
    "ScenarioFacts",
    "ScenarioRefusedError",
    "ScenarioResult",
    "StoredScenario",
    "delete_scenario",
    "facts_for",
    "list_scenarios",
    "load_scenario",
    "run_saved",
    "run_scenario",
    "save_scenario",
]

#: Bumped when the *arithmetic* changes, not on every commit — the same rule as
#: `packages.indicators.compute.CODE_VERSION`, and for the same reason: migration 0028
#: keeps this column so that "an answer produced by a version of the model that no longer
#: exists should say so rather than looking like one produced today". A git SHA would
#: change when a docstring did and would answer that question wrongly.
CODE_VERSION = "p6-scenarios-1"

#: Working precision for this module's own arithmetic; the process-wide context is
#: untouched. The same 34 places `packages.valuation.dcf` works to.
_PRECISION = 34

#: The canonical keys this engine reads or moves. An override of anything else is refused
#: rather than accepted and ignored, because a typo that changes nothing is the same
#: failure as an assumption that is not wired through.
#:
#: The first sixteen are every key `compute_ratios` reads — keep this in step with
#: `packages/valuation/ratios.py` — and the last four are the ones an exchange-rate move
#: touches on its way through the income statement.
INPUT_KEYS: tuple[str, ...] = (
    "revenue",
    "gross_profit",
    "operating_profit",
    "profit_after_tax",
    "total_assets",
    "total_liabilities",
    "total_equity",
    "current_assets",
    "current_liabilities",
    "cash",
    "long_term_debt",
    "cash_from_ops",
    "capex",
    "depreciation_amortisation",
    "interest_expense",
    "dividends_paid",
    "cost_of_revenue",
    "profit_before_tax",
    "income_tax",
    "fx_loss_net",
)

_ZERO = Decimal(0)
_ONE = Decimal(1)

#: The scale every exchange-rate *effect* is rounded to before it is added to a reported
#: figure. Millionths of a currency unit: far below anything a statement reports, and
#: small enough that the sum of the rounded parts is the rounded whole. See `_money`.
_MONEY = Decimal("0.000001")


# ======================================================================================
# Refusals
#
# All of them are `ValueError`s, so the route mapping that already turns a `ValueError`
# from the DCF into a 422 keeps working. `.missing` carries the field names, so the body
# can name them the way FastAPI's own validation error does for an absent query
# parameter: "invalid_request" alone tells the caller to guess.
# ======================================================================================


class ScenarioRefusedError(ValueError):
    """A scenario this module will not run, with the reason in the message."""


class MissingAssumptionsError(ScenarioRefusedError):
    """An assumption the user has to type is absent. Never defaulted, never inferred."""

    def __init__(self, missing: Sequence[str], message: str) -> None:
        self.missing: tuple[str, ...] = tuple(missing)
        super().__init__(message)


class MissingFactsError(ScenarioRefusedError):
    """A figure the assumptions lean on is not in the data as known on `inputs_as_of`.

    `SPEC.md` §4.1: never infer missing financial data. The caller supplies the number
    explicitly or the scenario does not run.
    """

    def __init__(self, missing: Sequence[str], message: str) -> None:
        self.missing: tuple[str, ...] = tuple(missing)
        super().__init__(message)


class ScenarioExistsError(ScenarioRefusedError):
    """That principal already has a scenario of that name for that security."""


# ======================================================================================
# The assumption set — everything a person typed
# ======================================================================================


@dataclass(frozen=True)
class FxShock:
    """An exchange-rate move and what is exposed to it. Every field is the user's.

    Rates are in units of the reporting currency per unit of the foreign one — ₦1,535/$
    and ₦2,000/$ — and only their ratio matters, so the arithmetic is the same for any
    pair. `base_rate` is the rate the reported figures were earned at; leaving it out
    means "read the rate as known on `inputs_as_of`", which is a fact and is sourced as
    one. Everything else has to be typed.
    """

    #: The rate the user is asking about. There is no default: this is the question.
    scenario_rate: Decimal
    #: The rate the reported figures were earned at. None means read it point-in-time.
    base_rate: Decimal | None = None
    #: Share of `cost_of_revenue` priced in the foreign currency, 0–1. An importer's 0.6.
    cost_exposure: Decimal | None = None
    #: Share of `revenue` priced in the foreign currency, 0–1. An exporter's 0.9.
    revenue_exposure: Decimal | None = None
    #: Debt denominated in the foreign currency, in foreign-currency units ($200m → 2e8).
    foreign_debt: Decimal | None = None
    #: Turns the pre-tax operating effect into a cash one. Required with either exposure.
    tax_rate: Decimal | None = None

    @property
    def has_operating_exposure(self) -> bool:
        return self.cost_exposure is not None or self.revenue_exposure is not None

    def validate(self) -> None:
        for name in ("scenario_rate", "base_rate"):
            rate = getattr(self, name)
            if rate is not None and rate <= 0:
                raise ScenarioRefusedError(f"fx.{name} must be positive; got {rate}")
        if not self.has_operating_exposure and self.foreign_debt is None:
            raise MissingAssumptionsError(
                ("fx.cost_exposure", "fx.revenue_exposure", "fx.foreign_debt"),
                "an exchange-rate move with nothing exposed to it cannot change any "
                "number, and a scenario that returns the same answer as before is worse "
                "than no scenario. Say what is exposed: the share of cost of sales "
                "priced in the foreign currency, the share of revenue, or the "
                "foreign-currency debt.",
            )
        for name in ("cost_exposure", "revenue_exposure"):
            share = getattr(self, name)
            if share is not None and not (_ZERO <= share <= _ONE):
                raise ScenarioRefusedError(
                    f"fx.{name} is a share of a reported line and must be between 0 and 1; "
                    f"got {share}"
                )
        if self.has_operating_exposure and self.tax_rate is None:
            raise MissingAssumptionsError(
                ("fx.tax_rate",),
                "an operating exposure moves pre-tax profit, and turning that into cash "
                "needs a tax rate. The model will not pick one.",
            )
        if self.tax_rate is not None and not (_ZERO <= self.tax_rate < _ONE):
            raise ScenarioRefusedError(
                f"fx.tax_rate must be at least 0 and below 1; got {self.tax_rate}"
            )

    def to_json(self) -> dict[str, Any]:
        return {
            key: str(value)
            for key, value in (
                ("scenario_rate", self.scenario_rate),
                ("base_rate", self.base_rate),
                ("cost_exposure", self.cost_exposure),
                ("revenue_exposure", self.revenue_exposure),
                ("foreign_debt", self.foreign_debt),
                ("tax_rate", self.tax_rate),
            )
            if value is not None
        }

    @classmethod
    def from_json(cls, payload: Mapping[str, Any]) -> FxShock:
        _reject_unknown(payload, _FX_FIELDS, "fx")
        if "scenario_rate" not in payload:
            raise MissingAssumptionsError(
                ("fx.scenario_rate",), "an exchange-rate scenario needs the rate being assumed"
            )
        return cls(
            scenario_rate=_decimal(payload["scenario_rate"], field="fx.scenario_rate"),
            base_rate=_optional(payload.get("base_rate"), field="fx.base_rate"),
            cost_exposure=_optional(payload.get("cost_exposure"), field="fx.cost_exposure"),
            revenue_exposure=_optional(
                payload.get("revenue_exposure"), field="fx.revenue_exposure"
            ),
            foreign_debt=_optional(payload.get("foreign_debt"), field="fx.foreign_debt"),
            tax_rate=_optional(payload.get("tax_rate"), field="fx.tax_rate"),
        )


_FX_FIELDS = frozenset(
    {
        "scenario_rate",
        "base_rate",
        "cost_exposure",
        "revenue_exposure",
        "foreign_debt",
        "tax_rate",
    }
)


@dataclass(frozen=True)
class ScenarioAssumptions:
    """The complete user-supplied input set — what `scenarios.assumptions` holds.

    `growth_rates`, `discount_rate` and `terminal_growth` are required and are never
    defaulted: `SPEC.md` T8's acceptance criterion is that the model does not choose them.
    `base_free_cash_flow`, `net_debt` and `shares` are optional *because a fact can stand
    in for them* — the statements as known on the decision date — and when one does, the
    result says which period it came from.
    """

    #: Growth applied to each projected year in turn, as fractions. At least one.
    growth_rates: tuple[Decimal, ...]
    #: The discount rate (WACC) as a fraction. The user's, always.
    discount_rate: Decimal
    #: Perpetual growth after the projection. Must be below the discount rate.
    terminal_growth: Decimal
    #: Discount as if cash arrives mid-year. A convention, not a figure about the company.
    mid_year: bool = False
    #: Starting free cash flow. None means `cash_from_ops - capex` from the chosen period.
    base_free_cash_flow: Decimal | None = None
    #: Debt less cash. None means `long_term_debt - cash` from the chosen period.
    net_debt: Decimal | None = None
    #: Share count for the per-share figure. None means the count known on the date.
    shares: Decimal | None = None
    #: Canonical key → the figure the user is assuming instead of the reported one.
    overrides: Mapping[str, Decimal] = field(default_factory=dict)
    #: An exchange-rate move and what is exposed to it.
    fx: FxShock | None = None
    #: Which statement period to run against. None means the newest FY known on the date.
    period_label: str | None = None

    def validate(self) -> None:
        """Refuse an assumption set before anything is read. Raises; returns nothing."""
        if not self.growth_rates:
            raise MissingAssumptionsError(
                ("growth_rates",), "at least one projected year of growth is required"
            )
        if self.discount_rate <= self.terminal_growth:
            # The same refusal `dcf` makes, made before any I/O so the caller hears it at
            # once and hears it identically whether or not the security exists.
            raise ScenarioRefusedError(
                f"discount rate {self.discount_rate} must exceed terminal growth "
                f"{self.terminal_growth}: the Gordon formula is undefined otherwise"
            )
        if self.discount_rate <= -1:
            raise ScenarioRefusedError("discount rate must be greater than -100%")
        if self.shares is not None and self.shares <= 0:
            raise ScenarioRefusedError("shares must be positive when given")
        unknown = sorted(set(self.overrides) - set(INPUT_KEYS))
        if unknown:
            raise ScenarioRefusedError(
                f"the scenario engine reads none of {unknown}, so overriding them would "
                f"change nothing. Overridable keys: {', '.join(INPUT_KEYS)}"
            )
        if self.fx is not None:
            self.fx.validate()

    def to_json(self) -> dict[str, Any]:
        """The JSONB payload. Every number a string, so what comes back is what went in.

        JSON numbers are floats on the way back through most parsers, and a discount rate
        that returns as 0.18000000000000002 is not the one that was typed. Strings make
        the round trip exact, which is the whole of P6 check 7.
        """
        payload: dict[str, Any] = {
            "growth_rates": [str(rate) for rate in self.growth_rates],
            "discount_rate": str(self.discount_rate),
            "terminal_growth": str(self.terminal_growth),
            "mid_year": self.mid_year,
        }
        for key, value in (
            ("base_free_cash_flow", self.base_free_cash_flow),
            ("net_debt", self.net_debt),
            ("shares", self.shares),
        ):
            if value is not None:
                payload[key] = str(value)
        if self.overrides:
            payload["overrides"] = {key: str(self.overrides[key]) for key in sorted(self.overrides)}
        if self.fx is not None:
            payload["fx"] = self.fx.to_json()
        if self.period_label is not None:
            payload["period_label"] = self.period_label
        return payload

    @classmethod
    def from_json(cls, payload: Mapping[str, Any]) -> ScenarioAssumptions:
        """Parse a stored or submitted assumption set, refusing anything it cannot honour."""
        _reject_unknown(payload, _ASSUMPTION_FIELDS, None)
        required = ("growth_rates", "discount_rate", "terminal_growth")
        missing = [key for key in required if key not in payload]
        if missing:
            them = "them" if len(missing) > 1 else "it"
            raise MissingAssumptionsError(
                missing,
                f"the scenario engine will not choose {', '.join(missing)} for you "
                f"(SPEC.md T8: user-set assumptions only). Supply {them}.",
            )
        raw_growth = payload["growth_rates"]
        if isinstance(raw_growth, str) or not isinstance(raw_growth, Sequence):
            raise ScenarioRefusedError(
                "growth_rates is a list of per-year fractions, one entry per projected year"
            )
        overrides_raw = payload.get("overrides") or {}
        if not isinstance(overrides_raw, Mapping):
            raise ScenarioRefusedError("overrides is a mapping of canonical key to figure")
        fx_raw = payload.get("fx")
        if fx_raw is not None and not isinstance(fx_raw, Mapping):
            raise ScenarioRefusedError("fx is a mapping - see FxShock")
        period = payload.get("period_label")
        if period is not None and not isinstance(period, str):
            raise ScenarioRefusedError(
                "period_label is the label of a statement period, e.g. FY2024"
            )
        assumptions = cls(
            growth_rates=tuple(
                _decimal(rate, field=f"growth_rates[{index}]")
                for index, rate in enumerate(raw_growth)
            ),
            discount_rate=_decimal(payload["discount_rate"], field="discount_rate"),
            terminal_growth=_decimal(payload["terminal_growth"], field="terminal_growth"),
            mid_year=bool(payload.get("mid_year", False)),
            base_free_cash_flow=_optional(
                payload.get("base_free_cash_flow"), field="base_free_cash_flow"
            ),
            net_debt=_optional(payload.get("net_debt"), field="net_debt"),
            shares=_optional(payload.get("shares"), field="shares"),
            overrides={
                str(key): _decimal(value, field=f"overrides.{key}")
                for key, value in overrides_raw.items()
            },
            fx=FxShock.from_json(fx_raw) if fx_raw is not None else None,
            period_label=period,
        )
        assumptions.validate()
        return assumptions


_ASSUMPTION_FIELDS = frozenset(
    {
        "growth_rates",
        "discount_rate",
        "terminal_growth",
        "mid_year",
        "base_free_cash_flow",
        "net_debt",
        "shares",
        "overrides",
        "fx",
        "period_label",
    }
)


def _reject_unknown(payload: Mapping[str, Any], known: frozenset[str], prefix: str | None) -> None:
    """A key nothing reads is a typo, and a typo that is ignored is an assumption lost."""
    unknown = sorted(set(payload) - known)
    if unknown:
        where = f"{prefix}." if prefix else ""
        raise ScenarioRefusedError(
            f"unknown assumption{'s' if len(unknown) > 1 else ''} "
            f"{', '.join(where + key for key in unknown)}. Nothing reads "
            f"{'them' if len(unknown) > 1 else 'it'}, so accepting "
            f"{'them' if len(unknown) > 1 else 'it'} would lose whatever was meant."
        )


def _decimal(value: Any, *, field: str) -> Decimal:
    """A Decimal from what JSON can carry. Floats come through `str` as pydantic does."""
    if isinstance(value, Decimal):
        number = value
    elif isinstance(value, bool):  # bool is an int; a flag is not a figure
        raise ScenarioRefusedError(f"{field}: {value!r} is not a number")
    elif isinstance(value, int):
        number = Decimal(value)
    elif isinstance(value, float):
        number = Decimal(str(value))
    elif isinstance(value, str):
        try:
            number = Decimal(value.strip())
        except InvalidOperation:
            raise ScenarioRefusedError(f"{field}: {value!r} is not a number") from None
    else:
        raise ScenarioRefusedError(f"{field}: {value!r} is not a number")
    if not number.is_finite():  # Decimal("NaN") and Decimal("Infinity") both parse
        raise ScenarioRefusedError(f"{field}: {value!r} is not a finite number")
    return number


def _optional(value: Any, *, field: str) -> Decimal | None:
    return None if value is None else _decimal(value, field=field)


@dataclass(frozen=True)
class StoredScenario:
    """A row of `scenarios`, with its assumptions parsed. Identity, not arithmetic."""

    id: int
    principal_id: int
    security_id: int
    name: str
    assumptions: ScenarioAssumptions
    inputs_as_of: dt.date
    code_version: str
    created_at: dt.datetime | None = None


# ======================================================================================
# The facts a scenario is joined to
# ======================================================================================


@dataclass(frozen=True)
class ScenarioFacts:
    """What the company reported, as knowable on `inputs_as_of`. No assumption in here.

    Built by `facts_for` from the point-in-time read paths, and accepted directly by
    `run_scenario`, which is how the arithmetic is testable without a database.
    """

    inputs_as_of: dt.date
    security_id: int | None = None
    #: Presentation currency of the statements these figures came from.
    currency: str | None = None
    period_label: str | None = None
    period_known_as_of: dt.date | None = None
    #: Canonical key → the figure as known on `inputs_as_of`. None is "not reported".
    line_items: Mapping[str, Decimal | None] = field(default_factory=dict)
    #: The close the multiples are struck against, and the bar it came from.
    price: Decimal | None = None
    price_date: dt.date | None = None
    shares: Decimal | None = None
    shares_as_of: dt.date | None = None
    shares_basis: str | None = None
    #: The exchange rate as known on the date, for an `FxShock` that did not type one.
    fx_rate: Decimal | None = None
    fx_pair: str | None = None
    fx_rate_as_of: dt.date | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.inputs_as_of, dt.date):
            raise TypeError("inputs_as_of must be a date - there is no default of today")

    @property
    def period_source(self) -> str:
        """How to name the statements in a provenance line."""
        if self.period_label is None:
            return "the statements"
        if self.period_known_as_of is None:
            return self.period_label
        return f"{self.period_label} (known {self.period_known_as_of})"


# ======================================================================================
# The result — the answer and everything that produced it
# ======================================================================================


@dataclass(frozen=True)
class ResolvedInput:
    """One number that entered the arithmetic, and where it came from.

    `CLAUDE.md`: show the work in every mode. `source` is `'user'` for a typed figure and
    otherwise a sentence naming the period, the bar or the rate it was read from.
    """

    name: str
    value: Decimal | tuple[Decimal, ...] | bool | None
    source: str


@dataclass(frozen=True)
class FxEffect:
    """What the exchange-rate move did, in reporting-currency units, line by line."""

    base_rate: Decimal
    scenario_rate: Decimal
    #: `scenario_rate / base_rate - 1`. Positive when the foreign currency buys more.
    move: Decimal
    revenue_effect: Decimal
    cost_effect: Decimal
    operating_pre_tax: Decimal
    operating_after_tax: Decimal
    #: Added to net debt and to `fx_loss_net`. Non-cash, and not tax-effected.
    debt_revaluation: Decimal


@dataclass(frozen=True)
class ScenarioResult:
    """The DCF, the ratios, and the whole assumption set that produced them."""

    #: The saved row this was recomputed from, when it was. None for an unsaved run.
    scenario: StoredScenario | None
    assumptions: ScenarioAssumptions
    facts: ScenarioFacts
    #: Every figure that entered the arithmetic, with its source. Never elided.
    inputs: tuple[ResolvedInput, ...]
    #: The chosen period exactly as the company reported it, as known on the date.
    line_items_as_reported: Mapping[str, Decimal | None]
    #: The same figures under the scenario: the overrides applied, then the rate move.
    line_items_under_scenario: Mapping[str, Decimal | None]
    fx: FxEffect | None
    dcf: DcfResult
    #: The same DCF without the exchange-rate move, so the move's effect is visible.
    #: None when the scenario has no `fx` block and there is nothing to compare.
    dcf_before_fx: DcfResult | None
    #: Ratios under the scenario, and as the company reported it — same price, same
    #: share count, so the only difference between the two is the assumption set.
    ratios: Mapping[str, Decimal | None]
    ratios_as_reported: Mapping[str, Decimal | None]
    #: The version of this module that produced the answer, and the one that saved the
    #: assumptions. Migration 0028: an answer from a model that no longer exists says so.
    code_version: str = CODE_VERSION

    @property
    def code_version_at_save(self) -> str | None:
        return self.scenario.code_version if self.scenario else None

    @property
    def code_version_changed(self) -> bool:
        """True when the arithmetic has moved since the assumptions were saved."""
        saved = self.code_version_at_save
        return saved is not None and saved != self.code_version


# ======================================================================================
# The arithmetic — pure, no I/O (docs/08 §6)
# ======================================================================================


def run_scenario(
    assumptions: ScenarioAssumptions,
    facts: ScenarioFacts,
    *,
    scenario: StoredScenario | None = None,
) -> ScenarioResult:
    """Assumptions and facts in, a DCF and a ratio set out. Pure and deterministic.

    Raises `MissingAssumptionsError` when a figure the user must type is absent, and
    `MissingFactsError` when one that could have been read is not in the data as known on
    `facts.inputs_as_of`. Both carry `.missing`, so a route can name the fields in its 422
    the way the DCF route already does.
    """
    assumptions.validate()
    with localcontext() as context:
        context.prec = _PRECISION
        return _run(assumptions, facts, scenario)


def _run(
    assumptions: ScenarioAssumptions,
    facts: ScenarioFacts,
    scenario: StoredScenario | None,
) -> ScenarioResult:
    inputs: list[ResolvedInput] = []

    reported: dict[str, Decimal | None] = {
        key: facts.line_items.get(key) for key in INPUT_KEYS if key in facts.line_items
    }
    # The overrides are part of the scenario, so they are applied before the rate move
    # and an exposure is a share of the *assumed* line, not the reported one.
    before = dict(reported)
    for key in sorted(assumptions.overrides):
        before[key] = assumptions.overrides[key]
        inputs.append(ResolvedInput(f"line_item.{key}", assumptions.overrides[key], "user"))

    effect, after = _apply_fx(assumptions.fx, before, facts, inputs)

    base_fcf_before = _resolve(
        assumptions.base_free_cash_flow,
        name="base_free_cash_flow_before_fx",
        derive=("cash_from_ops", "capex"),
        items=before,
        facts=facts,
        inputs=inputs,
    )
    net_debt_before = _resolve(
        assumptions.net_debt,
        name="net_debt_before_fx",
        derive=("long_term_debt", "cash"),
        items=before,
        facts=facts,
        inputs=inputs,
    )

    cash_effect = effect.operating_after_tax if effect else _ZERO
    debt_effect = effect.debt_revaluation if effect else _ZERO
    base_fcf = base_fcf_before + cash_effect
    net_debt = net_debt_before + debt_effect
    if effect is not None:
        inputs.append(
            ResolvedInput(
                "base_free_cash_flow",
                base_fcf,
                "base_free_cash_flow_before_fx + the after-tax operating effect of the rate",
            )
        )
        inputs.append(
            ResolvedInput(
                "net_debt", net_debt, "net_debt_before_fx + the revaluation of foreign debt"
            )
        )

    shares = assumptions.shares
    if shares is not None:
        inputs.append(ResolvedInput("shares", shares, "user"))
    elif facts.shares is not None:
        shares = facts.shares
        basis = f" ({facts.shares_basis})" if facts.shares_basis else ""
        inputs.append(
            ResolvedInput("shares", shares, f"shares_outstanding as of {facts.shares_as_of}{basis}")
        )
    else:
        inputs.append(ResolvedInput("shares", None, "unknown - no per-share figure"))

    inputs.append(ResolvedInput("growth_rates", assumptions.growth_rates, "user"))
    inputs.append(ResolvedInput("discount_rate", assumptions.discount_rate, "user"))
    inputs.append(ResolvedInput("terminal_growth", assumptions.terminal_growth, "user"))
    inputs.append(ResolvedInput("mid_year", assumptions.mid_year, "user"))
    if facts.price is not None:
        inputs.append(ResolvedInput("price", facts.price, f"close as traded on {facts.price_date}"))

    def _dcf(base: Decimal, debt: Decimal) -> DcfResult:
        return dcf(
            DcfAssumptions(
                base_free_cash_flow=base,
                growth_rates=assumptions.growth_rates,
                discount_rate=assumptions.discount_rate,
                terminal_growth=assumptions.terminal_growth,
                net_debt=debt,
                shares=shares,
                mid_year=assumptions.mid_year,
            )
        )

    ratio_args = {
        "price": facts.price,
        "shares": shares,
        "decision_date": facts.inputs_as_of,
    }
    return ScenarioResult(
        scenario=scenario,
        assumptions=assumptions,
        facts=facts,
        inputs=tuple(inputs),
        line_items_as_reported=reported,
        line_items_under_scenario=after,
        fx=effect,
        dcf=_dcf(base_fcf, net_debt),
        dcf_before_fx=(_dcf(base_fcf_before, net_debt_before) if effect is not None else None),
        ratios=compute_ratios(after, **ratio_args),  # type: ignore[arg-type]
        ratios_as_reported=compute_ratios(reported, **ratio_args),  # type: ignore[arg-type]
    )


def _resolve(
    typed: Decimal | None,
    *,
    name: str,
    derive: tuple[str, str],
    items: Mapping[str, Decimal | None],
    facts: ScenarioFacts,
    inputs: list[ResolvedInput],
) -> Decimal:
    """The user's figure, or `a - b` from the statements. Refuses rather than inventing one."""
    if typed is not None:
        inputs.append(ResolvedInput(name, typed, "user"))
        return typed
    minuend, subtrahend = derive
    absent = [key for key in derive if items.get(key) is None]
    if absent:
        raise MissingFactsError(
            absent,
            f"{name} was not supplied and cannot be read: {', '.join(absent)} "
            f"{'are' if len(absent) > 1 else 'is'} not in {facts.period_source} as known on "
            f"{facts.inputs_as_of}. Supply the figure, or an override for it - nothing here "
            f"estimates a missing line (SPEC.md 4.1).",
        )
    first, second = items[minuend], items[subtrahend]
    assert first is not None and second is not None  # the `absent` check above proved it
    value = first - second
    inputs.append(ResolvedInput(name, value, f"{facts.period_source}: {minuend} - {subtrahend}"))
    return value


def _apply_fx(
    shock: FxShock | None,
    before: Mapping[str, Decimal | None],
    facts: ScenarioFacts,
    inputs: list[ResolvedInput],
) -> tuple[FxEffect | None, dict[str, Decimal | None]]:
    """The rate move, its effect on each line, and the shocked figures.

    The composition identities the normaliser enforces survive this by construction:
    revenue less cost of sales still equals gross profit, and profit before tax less tax
    still equals profit after tax (`packages/normalize/validation.py`).
    """
    after = dict(before)
    if shock is None:
        return None, after

    base_rate = shock.base_rate
    if base_rate is not None:
        inputs.append(ResolvedInput("fx.base_rate", base_rate, "user"))
    else:
        base_rate = facts.fx_rate
        if base_rate is None:
            raise MissingAssumptionsError(
                ("fx.base_rate",),
                f"no {facts.fx_pair or 'exchange'} rate is on file as known on "
                f"{facts.inputs_as_of}, so the rate the reported figures were earned at "
                f"has to be typed. Without it there is no move to measure.",
            )
        inputs.append(
            ResolvedInput(
                "fx.base_rate",
                base_rate,
                f"{facts.fx_pair} as of {facts.fx_rate_as_of}, known on {facts.inputs_as_of}",
            )
        )
    inputs.append(ResolvedInput("fx.scenario_rate", shock.scenario_rate, "user"))

    move = shock.scenario_rate / base_rate - _ONE
    tax_rate = shock.tax_rate if shock.tax_rate is not None else _ZERO

    needed = [
        key
        for key, share in (
            ("cost_of_revenue", shock.cost_exposure),
            ("revenue", shock.revenue_exposure),
        )
        if share is not None and share != _ZERO and before.get(key) is None
    ]
    if needed:
        raise MissingFactsError(
            needed,
            f"the exchange-rate exposure is a share of {', '.join(needed)}, and "
            f"{'those lines are' if len(needed) > 1 else 'that line is'} not in "
            f"{facts.period_source} as known on {facts.inputs_as_of}. Supply "
            f"{'them' if len(needed) > 1 else 'it'} as an override, or express the "
            f"exposure a different way.",
        )

    cost_effect = _exposed(before.get("cost_of_revenue"), shock.cost_exposure, move)
    revenue_effect = _exposed(before.get("revenue"), shock.revenue_exposure, move)
    operating_pre_tax = revenue_effect - cost_effect
    operating_after_tax = _money(operating_pre_tax * (_ONE - tax_rate))
    # By subtraction, not by `pre_tax × tax_rate`: two independently rounded products need
    # not add back to the whole, and `profit_before_tax - income_tax = profit_after_tax` is
    # an identity the normaliser enforces on every statement it writes.
    tax_effect = operating_pre_tax - operating_after_tax
    debt_revaluation = (
        _money(shock.foreign_debt * (shock.scenario_rate - base_rate))
        if shock.foreign_debt is not None
        else _ZERO
    )
    for name, value in (
        ("fx.cost_exposure", shock.cost_exposure),
        ("fx.revenue_exposure", shock.revenue_exposure),
        ("fx.foreign_debt", shock.foreign_debt),
        ("fx.tax_rate", shock.tax_rate),
    ):
        if value is not None:
            inputs.append(ResolvedInput(name, value, "user"))

    for key, amount in (
        ("revenue", revenue_effect),
        ("cost_of_revenue", cost_effect),
        ("gross_profit", operating_pre_tax),
        ("operating_profit", operating_pre_tax),
        ("profit_before_tax", operating_pre_tax - debt_revaluation),
        ("income_tax", tax_effect),
        ("profit_after_tax", operating_after_tax - debt_revaluation),
        ("cash_from_ops", operating_after_tax),
        ("long_term_debt", debt_revaluation),
    ):
        current = after.get(key)
        if amount != _ZERO and current is not None:
            after[key] = current + amount
    if debt_revaluation != _ZERO:
        # The one line a scenario may create rather than move: a company with no
        # translation loss on file has one under this rate, and saying so is the point.
        after["fx_loss_net"] = (after.get("fx_loss_net") or _ZERO) + debt_revaluation

    return (
        FxEffect(
            base_rate=base_rate,
            scenario_rate=shock.scenario_rate,
            move=move,
            revenue_effect=revenue_effect,
            cost_effect=cost_effect,
            operating_pre_tax=operating_pre_tax,
            operating_after_tax=operating_after_tax,
            debt_revaluation=debt_revaluation,
        ),
        after,
    )


def _exposed(line: Decimal | None, share: Decimal | None, move: Decimal) -> Decimal:
    if line is None or share is None:
        return _ZERO
    return _money(line * share * move)


def _money(amount: Decimal) -> Decimal:
    """An effect rounded to `_MONEY`, so that adding it to a reported figure is exact.

    `move` is a ratio and keeps every digit; the *amounts* derived from it are money and
    are rounded once, here. Without this a 34-significant-digit effect added to a
    twelve-digit statement figure rounds differently on each line it touches, and revenue
    less cost of sales stops equalling gross profit in the thirty-fourth place — a
    difference of no financial size at all that would still break an identity check.
    """
    return amount.quantize(_MONEY)


# ======================================================================================
# PERSISTENCE — rows in, rows out, no arithmetic (docs/08 §6)
#
# Every function below takes `principal_id` and filters on it. P6 check 8: two principals
# can both have a "bear" on the same security, and neither can see or delete the other's.
# The unique constraint is `(principal_id, security_id, name)`, so the isolation is the
# schema's as well as the query's.
# ======================================================================================


def facts_for(
    session: Session,
    *,
    security_id: int,
    inputs_as_of: dt.date,
    period_label: str | None = None,
    foreign_currency: str = "USD",
) -> ScenarioFacts:
    """Everything the company reported, as knowable on `inputs_as_of`. The only read path.

    `inputs_as_of` is a decision date and is mandatory, for the reason
    `packages/common/pit.py` gives: a default of today is a wrong number in a results
    table rather than an error at the call.
    """
    if not isinstance(inputs_as_of, dt.date):
        raise TypeError("inputs_as_of must be a date - there is no default of today")

    snap = snapshot.ratios_for(
        session,
        security_id=security_id,
        decision_date=inputs_as_of,
        period_label=period_label,
    )
    if snap is None and period_label is not None:
        raise MissingFactsError(
            (period_label,),
            f"security {security_id} has no {period_label} statement as known on "
            f"{inputs_as_of}. A scenario pinned to a period it cannot read would answer "
            f"a different question every time the data changed.",
        )
    price = (
        snap.price
        if snap
        else snapshot.latest_price(session, security_id=security_id, on=inputs_as_of)
    )
    shares = (
        snap.shares
        if snap
        else snapshot.latest_share_count(session, security_id=security_id, on=inputs_as_of)
    )
    currency = snap.period.currency if snap else _security_currency(session, security_id)

    rate = None
    if currency is not None and currency.upper() != foreign_currency.upper():
        rate = rate_on(
            session,
            base=foreign_currency,
            quote=currency,
            on=inputs_as_of,
            decision_date=inputs_as_of,
        )

    return ScenarioFacts(
        inputs_as_of=inputs_as_of,
        security_id=security_id,
        currency=currency,
        period_label=snap.period.period_label if snap else None,
        period_known_as_of=snap.period.known_as_of if snap else None,
        line_items=dict(snap.inputs) if snap else {},
        price=price.close_raw if price else None,
        price_date=price.date if price else None,
        shares=shares.shares if shares else None,
        shares_as_of=shares.as_of_date if shares else None,
        shares_basis=shares.basic_or_diluted if shares else None,
        fx_rate=rate.rate if rate else None,
        fx_pair=f"{foreign_currency.upper()}/{currency}" if currency else None,
        fx_rate_as_of=rate.as_of_date if rate else None,
    )


def _security_currency(session: Session, security_id: int) -> str | None:
    return session.execute(
        select(Security.currency).where(Security.id == security_id)
    ).scalar_one_or_none()


def save_scenario(
    session: Session,
    *,
    principal_id: int,
    security_id: int,
    name: str,
    assumptions: ScenarioAssumptions,
    inputs_as_of: dt.date,
    overwrite: bool = False,
) -> StoredScenario:
    """Save an assumption set under a name, for one principal and one security.

    Flushes; the caller commits, as everywhere else in `packages/`. Refuses to replace an
    existing name unless asked to: `CLAUDE.md` forbids silent overwrites, and "bear"
    quietly meaning something else next week is exactly that.
    """
    clean = name.strip()
    if not clean:
        raise ScenarioRefusedError("a scenario is saved under a name the user chose")
    if not isinstance(inputs_as_of, dt.date) or isinstance(inputs_as_of, dt.datetime):
        raise TypeError("inputs_as_of must be a date - a decision date, not a timestamp or today")
    assumptions.validate()

    existing = _row(session, principal_id=principal_id, security_id=security_id, name=clean)
    if existing is not None and not overwrite:
        raise ScenarioExistsError(
            f"principal {principal_id} already has a scenario named {clean!r} for security "
            f"{security_id}, saved against {existing.inputs_as_of}. Pass overwrite=True to "
            f"replace it, or save under another name."
        )
    payload = assumptions.to_json()
    if existing is not None:
        existing.assumptions = payload
        existing.inputs_as_of = inputs_as_of
        existing.code_version = CODE_VERSION
        row = existing
    else:
        row = Scenario(
            principal_id=principal_id,
            security_id=security_id,
            name=clean,
            assumptions=payload,
            inputs_as_of=inputs_as_of,
            code_version=CODE_VERSION,
        )
        session.add(row)
    try:
        with session.begin_nested():
            session.flush()
    except IntegrityError as exc:
        if _sqlstate(exc) == "23505":  # another writer took the name between the two calls
            raise ScenarioExistsError(
                f"principal {principal_id} already has a scenario named {clean!r} for "
                f"security {security_id}"
            ) from exc
        raise
    return _stored(row)


def load_scenario(
    session: Session, *, principal_id: int, security_id: int, name: str
) -> StoredScenario | None:
    """One principal's scenario by name, or None. Never another principal's row."""
    row = _row(session, principal_id=principal_id, security_id=security_id, name=name.strip())
    return _stored(row) if row is not None else None


def list_scenarios(
    session: Session, *, principal_id: int, security_id: int | None = None
) -> list[StoredScenario]:
    """Every scenario this principal saved, for one security or for all of them."""
    query = select(Scenario).where(Scenario.principal_id == principal_id)
    if security_id is not None:
        query = query.where(Scenario.security_id == security_id)
    rows = session.execute(query.order_by(Scenario.security_id, Scenario.name)).scalars().all()
    return [_stored(row) for row in rows]


def delete_scenario(session: Session, *, principal_id: int, security_id: int, name: str) -> bool:
    """Delete one principal's scenario. True if a row went; False if there was none.

    The row is fetched before it is deleted, so a name this principal does not have is
    False rather than a `DELETE` that could have matched somebody else's.
    """
    row = _row(session, principal_id=principal_id, security_id=security_id, name=name.strip())
    if row is None:
        return False
    session.delete(row)
    session.flush()
    return True


def run_saved(session: Session, scenario: StoredScenario) -> ScenarioResult:
    """Recompute a saved scenario at its own `inputs_as_of`. P6 check 7 lives here.

    Nothing about *when this runs* enters the answer: the date comes from the row, and
    every read underneath it is point-in-time. Two runs a week apart return the same
    numbers unless a figure known on that date was corrected in between.
    """
    facts = facts_for(
        session,
        security_id=scenario.security_id,
        inputs_as_of=scenario.inputs_as_of,
        period_label=scenario.assumptions.period_label,
    )
    return run_scenario(scenario.assumptions, facts, scenario=scenario)


def _row(session: Session, *, principal_id: int, security_id: int, name: str) -> Scenario | None:
    return session.execute(
        select(Scenario)
        .where(Scenario.principal_id == principal_id)
        .where(Scenario.security_id == security_id)
        .where(Scenario.name == name)
    ).scalar_one_or_none()


def _stored(row: Scenario) -> StoredScenario:
    return StoredScenario(
        id=row.id,
        principal_id=row.principal_id,
        security_id=row.security_id,
        name=row.name,
        assumptions=ScenarioAssumptions.from_json(row.assumptions),
        inputs_as_of=row.inputs_as_of,
        code_version=row.code_version,
        created_at=row.created_at,
    )


def _sqlstate(exc: IntegrityError) -> str | None:
    return getattr(getattr(exc, "orig", None), "sqlstate", None)

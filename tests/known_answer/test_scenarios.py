"""P6 checks 7 and 13 on the arithmetic — `packages.valuation.scenarios`, no database.

Two things are tested here and nothing else touches a row:

* **The engine never chooses.** `SPEC.md` T8 and `DATA_FOUNDATION.md` §6.5: *no
  recommendations, no auto price targets, user-set assumptions only.* An assumption set
  without a discount rate is refused, and the refusal **names the field**, which is what
  the `/companies/{ticker}/dcf` route already does. A figure that could have been read
  from the statements and is not there is refused too, rather than estimated
  (`SPEC.md` §4.1: never infer missing financial data).
* **Check 13 — the assumptions are actually wired through.** *"Naira at ₦2,000/$ for an
  importer should hurt materially. If the model shrugs, an assumption is not wired
  through."* The importer below is a deliberately ordinary Nigerian manufacturer, and the
  figures the shock produces are computed by hand in `test_check_13_...`'s docstring
  before they are asserted.

The worked example, ₦bn, FY2024, and every figure round so the hand arithmetic is
checkable: revenue 1,000, cost of sales 600, gross 400, operating 200, PBT 180, tax 54,
PAT 126, operating cash 160, capex 40, debt 150, cash 50. 4bn shares at ₦60.
"""

from __future__ import annotations

import datetime as dt
from decimal import Decimal

import pytest

from packages.valuation.scenarios import (
    FxShock,
    MissingAssumptionsError,
    MissingFactsError,
    ScenarioAssumptions,
    ScenarioFacts,
    ScenarioRefusedError,
    run_scenario,
)

D = Decimal
BN = D(1_000_000_000)

AS_OF = dt.date(2025, 6, 30)
FILED = dt.date(2025, 3, 31)

#: The end-2024 NFEM official rate, the same figure `tests/unit/test_devaluation.py` uses.
RATE_2024 = D("1535.0")
#: The question P6 check 13 asks.
RATE_SHOCK = D(2000)

REPORTED: dict[str, Decimal | None] = {
    "revenue": 1000 * BN,
    "cost_of_revenue": 600 * BN,
    "gross_profit": 400 * BN,
    "operating_profit": 200 * BN,
    "profit_before_tax": 180 * BN,
    "income_tax": 54 * BN,
    "profit_after_tax": 126 * BN,
    "cash_from_ops": 160 * BN,
    "capex": 40 * BN,
    "depreciation_amortisation": 30 * BN,
    "interest_expense": 20 * BN,
    "dividends_paid": 20 * BN,
    "long_term_debt": 150 * BN,
    "cash": 50 * BN,
    "total_assets": 900 * BN,
    "total_liabilities": 500 * BN,
    "total_equity": 400 * BN,
    "current_assets": 350 * BN,
    "current_liabilities": 250 * BN,
}


def facts(**overrides: object) -> ScenarioFacts:
    fields: dict[str, object] = {
        "inputs_as_of": AS_OF,
        "security_id": 1,
        "currency": "NGN",
        "period_label": "FY2024",
        "period_known_as_of": FILED,
        "line_items": dict(REPORTED),
        "price": D(60),
        "price_date": dt.date(2025, 6, 27),
        "shares": 4 * BN,
        "shares_as_of": dt.date(2024, 12, 31),
        "shares_basis": "basic",
    }
    fields.update(overrides)
    return ScenarioFacts(**fields)  # type: ignore[arg-type]


def assumptions(**overrides: object) -> ScenarioAssumptions:
    fields: dict[str, object] = {
        "growth_rates": (D("0.15"), D("0.12"), D("0.10")),
        "discount_rate": D("0.24"),
        "terminal_growth": D("0.08"),
    }
    fields.update(overrides)
    return ScenarioAssumptions(**fields)  # type: ignore[arg-type]


def importer_shock(**overrides: object) -> FxShock:
    """Half of cost of sales is imported and priced in dollars; nothing is exported."""
    fields: dict[str, object] = {
        "scenario_rate": RATE_SHOCK,
        "base_rate": RATE_2024,
        "cost_exposure": D("0.5"),
        "revenue_exposure": D("0"),
        "tax_rate": D("0.30"),
    }
    fields.update(overrides)
    return FxShock(**fields)  # type: ignore[arg-type]


def close(actual: Decimal | None, expected: str, places: int = 4) -> bool:
    assert actual is not None
    return abs(actual - D(expected)) < D(10) ** -places


# --------------------------------------------------------------------------------------
# The engine does not choose (SPEC.md T8)
# --------------------------------------------------------------------------------------


def test_an_assumption_set_without_a_discount_rate_is_refused_and_the_field_is_named() -> None:
    """T8: user-set assumptions only. The 422 has to say *which* field, as /dcf does."""
    with pytest.raises(MissingAssumptionsError) as raised:
        ScenarioAssumptions.from_json({"growth_rates": ["0.10"]})
    assert raised.value.missing == ("discount_rate", "terminal_growth")
    assert "discount_rate" in str(raised.value)


def test_a_typo_in_an_assumption_name_is_refused_rather_than_ignored() -> None:
    """An assumption silently dropped is the failure check 13 is looking for."""
    with pytest.raises(ScenarioRefusedError, match="discount_rte"):
        ScenarioAssumptions.from_json(
            {
                "growth_rates": ["0.1"],
                "discount_rate": "0.24",
                "terminal_growth": "0.08",
                "discount_rte": "0.18",
            }
        )


def test_an_override_of_a_line_nothing_reads_is_refused() -> None:
    with pytest.raises(ScenarioRefusedError, match="wheat_purchases"):
        assumptions(overrides={"wheat_purchases": 10 * BN}).validate()


def test_a_base_cash_flow_that_cannot_be_read_is_refused_not_estimated() -> None:
    """SPEC.md §4.1: never infer missing financial data. The absent lines are named."""
    thin = {key: value for key, value in REPORTED.items() if key != "cash_from_ops"}
    with pytest.raises(MissingFactsError) as raised:
        run_scenario(assumptions(), facts(line_items=thin))
    assert raised.value.missing == ("cash_from_ops",)
    assert "FY2024 (known 2025-03-31)" in str(raised.value)
    # ...and it runs the moment the caller supplies the figure themselves.
    result = run_scenario(assumptions(base_free_cash_flow=120 * BN), facts(line_items=thin))
    assert close(result.dcf.value_per_share, "200.7219")


def test_an_exchange_rate_move_with_nothing_exposed_to_it_is_refused() -> None:
    """The anti-shrug rule: a rate alone cannot move a number, so it must not pretend to."""
    with pytest.raises(MissingAssumptionsError) as raised:
        FxShock(scenario_rate=RATE_SHOCK, base_rate=RATE_2024).validate()
    assert raised.value.missing == ("fx.cost_exposure", "fx.revenue_exposure", "fx.foreign_debt")


def test_an_operating_exposure_without_a_tax_rate_is_refused() -> None:
    with pytest.raises(MissingAssumptionsError) as raised:
        FxShock(scenario_rate=RATE_SHOCK, base_rate=RATE_2024, cost_exposure=D("0.5")).validate()
    assert raised.value.missing == ("fx.tax_rate",)


def test_an_exposure_whose_line_was_never_reported_is_refused() -> None:
    thin = {key: value for key, value in REPORTED.items() if key != "cost_of_revenue"}
    with pytest.raises(MissingFactsError) as raised:
        run_scenario(assumptions(fx=importer_shock()), facts(line_items=thin))
    assert raised.value.missing == ("cost_of_revenue",)


def test_a_base_rate_that_is_neither_typed_nor_on_file_is_refused() -> None:
    with pytest.raises(MissingAssumptionsError) as raised:
        run_scenario(
            assumptions(fx=importer_shock(base_rate=None)), facts(fx_rate=None, fx_pair="USD/NGN")
        )
    assert raised.value.missing == ("fx.base_rate",)


def test_the_base_rate_may_be_read_point_in_time_and_says_so() -> None:
    """A rate on file is a *fact*, sourced like one; the scenario rate is always the user's."""
    result = run_scenario(
        assumptions(fx=importer_shock(base_rate=None)),
        facts(fx_rate=RATE_2024, fx_pair="USD/NGN", fx_rate_as_of=dt.date(2024, 12, 31)),
    )
    assert result.fx is not None
    assert result.fx.base_rate == RATE_2024
    sources = {item.name: item.source for item in result.inputs}
    assert sources["fx.base_rate"] == "USD/NGN as of 2024-12-31, known on 2025-06-30"
    assert sources["fx.scenario_rate"] == "user"


# --------------------------------------------------------------------------------------
# The output carries the assumption set (CLAUDE.md: show the work)
# --------------------------------------------------------------------------------------


def test_the_result_carries_the_assumption_set_and_the_source_of_every_figure() -> None:
    given = assumptions(fx=importer_shock())
    result = run_scenario(given, facts())

    assert result.assumptions is given
    assert result.facts.inputs_as_of == AS_OF
    sources = {item.name: item.source for item in result.inputs}
    assert sources["discount_rate"] == "user"
    assert sources["growth_rates"] == "user"
    assert sources["fx.cost_exposure"] == "user"
    # The two figures the *company* supplied say which period and which bar they came from.
    assert sources["base_free_cash_flow_before_fx"] == (
        "FY2024 (known 2025-03-31): cash_from_ops - capex"
    )
    assert sources["net_debt_before_fx"] == "FY2024 (known 2025-03-31): long_term_debt - cash"
    assert sources["shares"] == "shares_outstanding as of 2024-12-31 (basic)"
    assert sources["price"] == "close as traded on 2025-06-27"
    # Nothing in the arithmetic is unattributed.
    assert all(item.source for item in result.inputs)


def test_a_typed_figure_is_marked_as_the_users() -> None:
    result = run_scenario(assumptions(base_free_cash_flow=99 * BN, shares=BN), facts())
    sources = {item.name: item.source for item in result.inputs}
    assert sources["base_free_cash_flow_before_fx"] == "user"
    assert sources["shares"] == "user"


def test_without_an_exchange_rate_move_nothing_moves() -> None:
    """A scenario that only re-rates the DCF leaves the statements exactly as reported."""
    result = run_scenario(assumptions(), facts())
    assert result.fx is None
    assert result.dcf_before_fx is None
    assert result.line_items_under_scenario == result.line_items_as_reported
    assert result.ratios == result.ratios_as_reported
    assert close(result.dcf.value_per_share, "200.7219")


def test_an_override_replaces_the_reported_figure_and_reaches_the_ratios() -> None:
    """The comparison is against what the company reported, so an override shows up in it."""
    result = run_scenario(assumptions(overrides={"revenue": 1200 * BN}), facts())
    assert result.line_items_as_reported["revenue"] == 1000 * BN
    assert result.line_items_under_scenario["revenue"] == 1200 * BN
    assert result.ratios_as_reported["gross_margin"] == D("0.4")
    assert close(result.ratios["gross_margin"], "0.3333", places=4)


# --------------------------------------------------------------------------------------
# Check 13 — ₦2,000/$ has to hurt an importer, by an amount computed by hand
# --------------------------------------------------------------------------------------


def test_check_13_the_naira_at_2000_hurts_an_importer_materially() -> None:
    """₦1,535/$ → ₦2,000/$, half of a ₦600bn cost base priced in dollars, 30% tax.

    By hand, in naira:

        move            = 2000/1535 - 1 = 465/1535 = 93/307 = 0.302931596091205211...
        cost effect     = 600bn x 0.5 x 93/307 = 27,900bn/307 = 90,879,478,827.361564
        pre-tax effect  = -90,879,478,827.361564   (nothing is exported, so no offset)
        after-tax       = x 0.7                   = -63,615,635,179.153095
        free cash flow  = 160bn - 40bn - 63.616bn =  56,384,364,820.846905
        net debt        = 150bn - 50bn            = 100,000,000,000  (no dollar debt here)

    and the DCF on 56.384bn growing 15/12/10% at 24% with 8% terminal growth, over 4bn
    shares, is ₦81.0599 against ₦200.7219 before the move: **-59.6%**. A 30% rise in the
    naira price of the dollar takes three fifths of the equity value, because the cost
    base is 60% of revenue and half of it is priced in dollars. That is what "wired
    through" looks like; a model that shrugged would return ₦200.7219 twice.
    """
    result = run_scenario(assumptions(fx=importer_shock()), facts())
    effect = result.fx
    assert effect is not None

    assert close(effect.move, "0.3029315960912052", places=16)
    assert effect.cost_effect == D("90879478827.361564")
    assert effect.revenue_effect == 0
    assert effect.operating_pre_tax == D("-90879478827.361564")
    assert effect.operating_after_tax == D("-63615635179.153095")
    assert effect.debt_revaluation == 0

    assert result.dcf.assumptions.base_free_cash_flow == D("56384364820.846905")
    assert result.dcf.assumptions.net_debt == 100 * BN
    assert result.dcf_before_fx is not None
    assert close(result.dcf_before_fx.value_per_share, "200.7219")
    assert close(result.dcf.value_per_share, "81.0599")

    before = result.dcf_before_fx.value_per_share
    after = result.dcf.value_per_share
    assert before is not None and after is not None
    change = (after - before) / before
    assert D("-0.61") < change < D("-0.58"), "a 30% rate move must not be a shrug"


def test_check_13_the_same_move_reaches_every_ratio_it_should() -> None:
    """The DCF is not the only output: the margins compress and the multiple re-rates."""
    result = run_scenario(assumptions(fx=importer_shock()), facts())

    assert close(result.ratios_as_reported["gross_margin"], "0.4000", places=4)
    assert close(result.ratios["gross_margin"], "0.3091", places=4)
    assert close(result.ratios_as_reported["operating_margin"], "0.2000", places=4)
    assert close(result.ratios["operating_margin"], "0.1091", places=4)
    assert close(result.ratios_as_reported["net_margin"], "0.1260", places=4)
    assert close(result.ratios["net_margin"], "0.0624", places=4)
    # EPS ₦31.50 -> ₦15.60, so the P/E on an unchanged ₦60 price goes 1.90 -> 3.85.
    assert close(result.ratios_as_reported["eps"], "31.5000", places=4)
    assert close(result.ratios["eps"], "15.5961", places=4)
    assert close(result.ratios_as_reported["pe"], "1.9048", places=4)
    assert close(result.ratios["pe"], "3.8471", places=4)
    # The price is a fact and the scenario does not move it.
    assert result.ratios["market_cap"] == result.ratios_as_reported["market_cap"]


def test_check_13_dollar_debt_is_revalued_into_net_debt_and_out_of_profit() -> None:
    """$100m of debt at ₦465/$ more is ₦46.5bn of translation loss - non-cash, untaxed."""
    result = run_scenario(assumptions(fx=importer_shock(foreign_debt=D(100_000_000))), facts())
    effect = result.fx
    assert effect is not None
    assert effect.debt_revaluation == D("46500000000.000000")
    assert result.dcf.assumptions.net_debt == D("146500000000.000000")
    # Non-cash: free cash flow carries the operating effect and nothing more.
    assert result.dcf.assumptions.base_free_cash_flow == D("56384364820.846905")
    assert result.line_items_under_scenario["fx_loss_net"] == D("46500000000.000000")
    assert close(result.dcf.value_per_share, "69.4349")


def test_the_same_move_helps_an_exporter_because_the_exposure_is_the_other_way_round() -> None:
    """The lever has a sign. 90% of revenue in dollars, 10% of costs, same rate move."""
    result = run_scenario(
        assumptions(
            fx=FxShock(
                scenario_rate=RATE_SHOCK,
                base_rate=RATE_2024,
                cost_exposure=D("0.1"),
                revenue_exposure=D("0.9"),
                tax_rate=D("0.30"),
            )
        ),
        facts(),
    )
    effect = result.fx
    assert effect is not None
    assert effect.operating_pre_tax > 0
    assert result.dcf_before_fx is not None
    before, after = result.dcf_before_fx.value_per_share, result.dcf.value_per_share
    assert before is not None and after is not None
    assert after > before * 2


def test_the_shock_preserves_the_identities_the_normaliser_enforces() -> None:
    """`packages/normalize/validation.py`: revenue - cost = gross, PBT - tax = PAT."""
    result = run_scenario(
        assumptions(fx=importer_shock(foreign_debt=D(100_000_000), revenue_exposure=D("0.2"))),
        facts(),
    )
    after = result.line_items_under_scenario
    assert after["revenue"] - after["cost_of_revenue"] == after["gross_profit"]  # type: ignore[operator]
    assert after["profit_before_tax"] - after["income_tax"] == after["profit_after_tax"]  # type: ignore[operator]


# --------------------------------------------------------------------------------------
# Check 7, the half of it that needs no database
# --------------------------------------------------------------------------------------


def test_check_7_the_same_assumptions_on_the_same_facts_give_identical_digits() -> None:
    """Not "equal to four places" - the same digits, which is what reproducible means."""
    first = run_scenario(assumptions(fx=importer_shock()), facts())
    second = run_scenario(assumptions(fx=importer_shock()), facts())
    assert first == second
    assert str(first.dcf.value_per_share) == str(second.dcf.value_per_share)
    assert [str(v) for v in first.dcf.present_values] == [str(v) for v in second.dcf.present_values]


def test_check_7_the_assumption_set_survives_a_json_round_trip_to_the_digit() -> None:
    """JSONB holds every number as a string: a rate that goes in as 0.18 comes back as 0.18.

    A JSON *number* would come back as a float, and `Decimal(0.18)` is
    0.1800000000000000044408920985006261... — a different discount rate, and a different
    answer, from the same saved scenario.
    """
    original = assumptions(
        fx=importer_shock(foreign_debt=D(100_000_000)),
        base_free_cash_flow=D("123456789.123456789"),
        overrides={"revenue": D("1000000000.5")},
        period_label="FY2024",
        mid_year=True,
    )
    payload = original.to_json()
    assert payload["discount_rate"] == "0.24"
    assert payload["fx"]["cost_exposure"] == "0.5"
    assert payload["base_free_cash_flow"] == "123456789.123456789"

    back = ScenarioAssumptions.from_json(payload)
    assert back == original
    assert back.to_json() == payload
    assert run_scenario(back, facts()) == run_scenario(original, facts())


def test_a_float_assumption_is_taken_the_way_pydantic_takes_one() -> None:
    """Through `str`, so 0.18 is 0.18 and not 0.18000000000000000444..."""
    parsed = ScenarioAssumptions.from_json(
        {"growth_rates": [0.1], "discount_rate": 0.18, "terminal_growth": 0.03}
    )
    assert parsed.discount_rate == D("0.18")
    assert str(parsed.to_json()["discount_rate"]) == "0.18"


def test_a_scenario_has_no_default_decision_date() -> None:
    """`packages/common/pit.py`'s rule, restated: asking for today means saying so."""
    with pytest.raises(TypeError, match="no default of today"):
        ScenarioFacts(inputs_as_of=None)  # type: ignore[arg-type]

"""Chart of accounts v1 against P3's own freeze gate. TG7, `docs/03` check 16.

`docs/03` line 1589 sets one condition before v1 may be frozen:

    confirm it can express "interest income", "net interest margin", and "loan loss
    provision". If it cannot, freezing now guarantees re-extraction later.

v0.1 failed all three, and quietly: a bank resolved to a page of blanks that looked exactly
like a bank that had not reported anything. The first three tests here are that checkpoint,
written so that a regression reopens it rather than passing a chart that cannot describe a
bank.

The rest guards the two ways a new chart version does damage without erroring:

* **a mapping lost in the carry-forward** - a v0.1 key whose mappings do not reach v1 makes
  53,710 already-stored figures unresolvable, and an unresolvable key is indistinguishable
  from a line the company never printed (`docs/08` §1.4);
* **two labels for one key at one priority** - resolution then falls to row id, so the same
  filing can yield different figures on two machines.

The Nigerian labels themselves are checked against the strings the filings actually print,
including one issuer's misspelling, because a mapping table is only worth what its strings
are worth.
"""

from __future__ import annotations

import collections
import datetime as dt
from decimal import Decimal

import pytest
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from packages.common.models import AccountMapping, ChartAccount
from packages.common.pit import LineItemAsKnown
from packages.ingestion.edgar import _chart_template
from packages.normalize.chart import SOURCE_SYSTEM_BY_METHOD, load_chart, resolve
from packages.valuation.snapshot import _absent_because

pytestmark = pytest.mark.invariant

VERSION = "v1"
NGX = "ng_ifrs_label"
XBRL = "us_gaap_xbrl"


@pytest.fixture
def ngx(db_session: Session):
    return load_chart(db_session, version=VERSION, source_system=NGX)


@pytest.fixture
def xbrl(db_session: Session):
    return load_chart(db_session, version=VERSION, source_system=XBRL)


# --------------------------------------------------------------------------------------
# P3 check 16, the freeze gate
# --------------------------------------------------------------------------------------


def test_the_chart_can_express_interest_income(ngx, xbrl) -> None:
    """Gross interest income, not just the net figure v0.1 stopped at.

    Net interest income alone cannot be decomposed: a bank whose margin fell because funding
    got dearer and one whose lending shrank show the same net number.
    """
    assert "interest_income" in ngx.accounts
    assert ngx.accounts["interest_income"].is_required, "a bank that omits it is incomplete"
    assert "interest_income" in ngx.keys_for("income", "financial")

    # GTCO prints the effective-interest wording, not the bare label.
    labels = [m.source_label for m in ngx.mappings["interest_income"]]
    assert "Interest income" in labels
    assert "Interest income calculated using the effective interest rate" in labels

    # JPMorgan and Bank of America file different tags for the same measure.
    assert [m.source_label for m in xbrl.mappings["interest_income"]] == [
        "InterestIncomeOperating",
        "InterestAndDividendIncomeOperating",
    ]


def test_the_chart_can_express_a_net_interest_margin(ngx) -> None:
    """The margin needs a numerator *and* an earning-asset base. v0.1 had neither half.

    This is the check v0.1 failed least visibly: `net_interest_income` existed, so the
    numerator looked present, while nothing on the balance sheet could be divided by.
    """
    assert "net_interest_income" in ngx.accounts

    earning_assets = (
        "loans_and_advances_to_customers",
        "loans_and_advances_to_banks",
        "investment_securities_fvoci",
        "investment_securities_amortised_cost",
        "investment_securities_fvtpl",
    )
    balance_keys = ngx.keys_for("balance", "financial")
    for key in earning_assets:
        assert key in balance_keys, f"{key} missing: no earning-asset base to divide by"

    # Computed the way the ratio engine will: GTCO's FY2025 shape, in naira millions.
    reported = {
        "Net interest income": Decimal(1_000),
        "Loans and advances to customers": Decimal(3_000),
        "Loans and advances to banks": Decimal(500),
        "Investment securities - Fair value through Other Comprehensive Income": Decimal(1_000),
        "Investment securities - Held at amortised cost": Decimal(500),
    }
    got = resolve(reported, ngx, ("net_interest_income", *earning_assets))
    base = Decimal(0)
    for key in earning_assets:
        present = got[key]
        if present is not None:
            base += present
    numerator = got["net_interest_income"]
    assert numerator is not None, "the margin has no numerator"
    assert base == Decimal(5_000)
    assert numerator / base == Decimal("0.20")
    assert got["investment_securities_fvtpl"] is None, "absent, not zero"


def test_the_chart_can_express_a_loan_loss_provision(ngx, xbrl) -> None:
    """GTCO's exact wording is "Loan impairment charges"; v0.1 had no key at all.

    `DATA_FOUNDATION` §3.4 named `impairments` and it was never built, which is why this
    asserts the key that exists rather than the key that was once written down.
    """
    assert "loan_impairment_charges" in ngx.accounts
    assert ngx.accounts["loan_impairment_charges"].is_required
    assert "Loan impairment charges" in [
        m.source_label for m in ngx.mappings["loan_impairment_charges"]
    ]
    assert ngx.accounts["loan_impairment_charges"].sign_convention == "either", (
        "a write-back is a real and signed event"
    )
    # The US path needs it too, and resolves to a real figure.
    assert resolve(
        {"FinancingReceivableExcludingAccruedInterestCreditLossExpenseReversal": Decimal(11_264)},
        xbrl,
        ["loan_impairment_charges"],
    ) == {"loan_impairment_charges": Decimal(11_264)}


def test_the_total_provision_and_the_loans_component_are_not_one_key(xbrl) -> None:
    """The trap that would have made two banks look comparable when they are not.

    JPMorgan files `ProvisionForLoanLeaseAndOtherLosses` (the total, including
    off-balance-sheet commitments) *and*
    `FinancingReceivableExcludingAccruedInterestCreditLossExpenseReversal` (loans only) for
    the same year - $14,212m and $11,264m. Bank of America stopped filing the first in 2019.
    Ranked as alternates on one key, JPMorgan would win the total, Bank of America the
    component, and a screen would rank them against each other.

    `docs/08` §2.3 allows alternate labels only where they name the same measure. These do
    not, so they are two keys, and a reader can see which one they have.
    """
    total = [m.source_label for m in xbrl.mappings["credit_loss_provision"]]
    loans = [m.source_label for m in xbrl.mappings["loan_impairment_charges"]]
    assert total == ["ProvisionForLoanLeaseAndOtherLosses"]
    assert loans == ["FinancingReceivableExcludingAccruedInterestCreditLossExpenseReversal"]
    assert not set(total) & set(loans)


# --------------------------------------------------------------------------------------
# Nothing that resolved under v0.1 may stop resolving under v1
# --------------------------------------------------------------------------------------


def test_v0_1_is_left_exactly_as_it_was(db_session: Session) -> None:
    """The 53,710 stored line items are keyed to v0.1 and must be unaffected.

    This is what `chart_version` in the primary key buys (TG7): a new vocabulary costs a
    version, never a re-extraction. If 0020 had edited v0.1 in place, figures already
    published would silently change meaning.
    """
    accounts = (
        db_session.execute(select(ChartAccount).where(ChartAccount.chart_version == "v0.1"))
        .scalars()
        .all()
    )
    mappings = (
        db_session.execute(select(AccountMapping).where(AccountMapping.chart_version == "v0.1"))
        .scalars()
        .all()
    )
    assert len(accounts) == 23 and len(mappings) == 24
    assert not [m for m in mappings if "0020" in m.added_by], "0020 must not touch v0.1"


def test_every_key_that_resolved_under_v0_1_still_resolves(db_session: Session) -> None:
    """Per source system, because a key is only reachable through a mapping.

    A v0.1 key absent from v1, or renamed, would let the carry-forward's JOIN drop its
    mappings without a word. The migration refuses to complete in that case; this proves the
    outcome rather than trusting the guard.
    """
    old = {
        (r[0], r[1])
        for r in db_session.execute(
            text(
                "SELECT source_system, canonical_key FROM account_mappings "
                "WHERE chart_version = 'v0.1'"
            )
        )
    }
    new = {
        (r[0], r[1])
        for r in db_session.execute(
            text(
                "SELECT source_system, canonical_key FROM account_mappings "
                "WHERE chart_version = 'v1'"
            )
        )
    }
    assert not old - new, f"unresolvable under v1: {sorted(old - new)}"


def test_v0_1_label_lists_carry_forward_intact(xbrl, db_session: Session) -> None:
    """A carried-forward key keeps v0.1's whole ordering, not part of it."""
    assert [m.source_label for m in xbrl.mappings["revenue"]] == [
        "Revenues",
        "RevenueFromContractWithCustomerExcludingAssessedTax",
        "SalesRevenueNet",
    ]
    assert [m.source_label for m in xbrl.mappings["cost_of_revenue"]] == [
        "CostOfRevenue",
        "CostOfGoodsAndServicesSold",
    ]


def test_a_key_v1_remaps_takes_v1_s_list_whole(xbrl) -> None:
    """`interest_expense` is the one key v1 restates, and it restates all of it.

    v0.1 put `InterestExpense` at priority 10. Both banks stopped filing that tag after
    FY2023 in favour of `InterestExpenseOperating`, so v1 leads with the current one. Had
    0020 copied v0.1's row in beside its own, two labels would sit at priority 10 and the
    winner would be whichever row was inserted first.
    """
    labels = [m.source_label for m in xbrl.mappings["interest_expense"]]
    assert labels == ["InterestExpenseOperating", "InterestExpense"]

    assert resolve({"InterestExpense": Decimal(500)}, xbrl, ["interest_expense"]) == {
        "interest_expense": Decimal(500)
    }, "an older filing still resolves"
    assert resolve(
        {"InterestExpenseOperating": Decimal(400), "InterestExpense": Decimal(500)},
        xbrl,
        ["interest_expense"],
    ) == {"interest_expense": Decimal(400)}, "when both are filed, the current tag wins"


@pytest.mark.parametrize("source_system", [NGX, XBRL])
def test_no_two_labels_for_one_key_share_a_priority(db_session: Session, source_system) -> None:
    """Otherwise `load_chart`'s tie-break is row id, and resolution is not reproducible."""
    rows = db_session.execute(
        text(
            """
            SELECT canonical_key, priority, count(*) FROM account_mappings
             WHERE chart_version = :v AND source_system = :s
             GROUP BY 1, 2 HAVING count(*) > 1 ORDER BY 1
            """
        ).bindparams(v=VERSION, s=source_system)
    ).all()
    assert not rows, f"ambiguous resolution order: {rows}"


# --------------------------------------------------------------------------------------
# The three statement shapes
# --------------------------------------------------------------------------------------


def test_the_insurance_template_exists_and_is_reachable(ngx) -> None:
    """`docs/10` §2.7 widened the template enum for insurers; no chart row ever followed."""
    assert any(a.template == "insurance" for a in ngx.accounts.values())
    income = ngx.keys_for("income", "insurance")
    assert "insurance_revenue" in income
    assert "profit_after_tax" in income, "'both' keys belong to every template"
    assert "revenue" not in income, "a non-financial key must not leak into an insurer"
    assert "interest_income" not in income, "nor a bank key"


def test_both_ifrs_17_eras_are_expressible_for_one_company(ngx) -> None:
    """AIICO changed over at FY2023, so one company has two statement shapes in the window.

    Through FY2022 the income statement opens with "Gross premium written"; from FY2023 with
    "Insurance Revenue" and an "Insurance service result". Both sit inside the extraction
    window, so a FY2022 read from the FY2022 report differs in shape from the same year
    restated as a comparative inside the FY2023 report.

    Carrying both vocabularies in one template is what makes the changeover *visible*: each
    filing fills what it prints and leaves the other era honestly absent. Dated mappings
    would have hidden it.
    """
    keys = ngx.keys_for("income", "insurance")
    assert {"gross_premium_written", "net_premium_income", "underwriting_profit"} <= set(keys)
    assert {"insurance_revenue", "insurance_service_result"} <= set(keys)

    pre = resolve(
        {"Gross premium written": Decimal(60_000), "Net premium income": Decimal(40_000)},
        ngx,
        ("gross_premium_written", "insurance_revenue"),
    )
    assert pre["gross_premium_written"] == Decimal(60_000)
    assert pre["insurance_revenue"] is None, "IFRS 17 had not arrived; absent, not zero"

    post = resolve(
        {"Insurance Revenue": Decimal(75_000), "Insurance service result": Decimal(9_000)},
        ngx,
        ("gross_premium_written", "insurance_revenue", "insurance_service_result"),
    )
    assert post["insurance_revenue"] == Decimal(75_000)
    assert post["gross_premium_written"] is None, "the line stopped existing"


def test_an_issuers_own_misspelling_is_mapped(ngx) -> None:
    """AIICO prints "comprehesive", missing the n, identically in FY2024 and FY2025.

    This is the argument for mappings being rows rather than code. Nobody would type that
    string into a parser, and a reviewer can add it in seconds without a deploy.
    """
    labels = [m.source_label for m in ngx.mappings["financial_assets_fvoci"]]
    assert "Fair value through other comprehensive income" in labels
    assert "Fair value through other comprehesive income" in labels  # noqa: SC200 - as printed

    typo_only = resolve(
        {"Fair value through other comprehesive income": Decimal(12_500)},
        ngx,
        ["financial_assets_fvoci"],
    )
    assert typo_only["financial_assets_fvoci"] == Decimal(12_500), (
        "the figure must not be lost to a typo"
    )


# --------------------------------------------------------------------------------------
# What reading the filings changed
# --------------------------------------------------------------------------------------


def test_gross_earnings_is_not_required_because_it_is_not_a_face_line(ngx) -> None:
    """GTCO's income statement opens with interest income; "Gross Earnings" is a KPI.

    v0.1 marked it required, which forced either an off-statement derivation or a false
    `not_in_filing` on every bank. It stays in the chart because the market quotes it.
    """
    account = ngx.accounts["gross_earnings"]
    assert not account.is_required
    assert "Directors' Report" in account.display_name, "say where it comes from"


def test_operating_profit_has_the_three_wordings_the_filings_use(ngx) -> None:
    """None of the three is standard, and v0.1's table expected only one of them."""
    labels = [m.source_label for m in ngx.mappings["operating_profit"]]
    for printed in (
        "Operating profit",  # MTN Nigeria
        "Results from operating activities",  # Nestle Nigeria
        "Profit from operating activities",  # Dangote Cement
    ):
        assert printed in labels


def test_finance_costs_are_not_mapped_onto_interest_expense(ngx) -> None:
    """All three industrials print "Finance costs"; none prints "Interest expense".

    They are not the same measure - finance costs carry lease interest and discount
    unwinding - so mapping them together would produce a number that looks like interest and
    is not. Same reasoning as `gross_earnings` not being `revenue`.
    """
    assert "finance_costs" in ngx.accounts and "finance_income" in ngx.accounts
    finance = {m.source_label for m in ngx.mappings["finance_costs"]}
    interest = {m.source_label for m in ngx.mappings.get("interest_expense", ())}
    assert "Finance costs" in finance
    assert not finance & interest


def test_a_telecom_reporting_by_nature_has_no_cost_of_sales(ngx) -> None:
    """MTN Nigeria presents expenses by nature and prints no cost-of-sales line at all.

    So `cost_of_revenue` and `gross_profit` must be optional for a non-financial company;
    requiring them would manufacture two missing figures for a correctly filed statement.
    """
    assert not ngx.accounts["cost_of_revenue"].is_required
    assert not ngx.accounts["gross_profit"].is_required
    got = resolve(
        {"Revenue": Decimal(3_360_000), "Operating profit": Decimal(900_000)},
        ngx,
        ("revenue", "cost_of_revenue", "gross_profit", "operating_profit"),
    )
    assert got["revenue"] == Decimal(3_360_000) and got["operating_profit"] == Decimal(900_000)
    assert got["cost_of_revenue"] is None and got["gross_profit"] is None


def test_the_ias_29_line_dangote_prints_has_somewhere_to_go(ngx) -> None:
    """ "Gain on net monetary position" - from a pan-African subsidiary, not naira accounting.

    `DATA_FOUNDATION` §3.3 ruled IAS 29 inapplicable to Nigeria and that stands. The key
    exists so the line is recorded rather than silently dropped, which would leave profit
    before tax not reconciling to the lines above it.
    """
    got = resolve({"Gain on net monetary position": Decimal(41_000)}, ngx, ["net_monetary_gain"])
    assert got["net_monetary_gain"] == Decimal(41_000)
    assert ngx.accounts["net_monetary_gain"].sign_convention == "either", "IAS 29 cuts both ways"


def test_profit_before_tax_exists_in_every_template(ngx) -> None:
    """It was missing from v0.1 entirely, though every statement read prints it."""
    assert "profit_before_tax" in ngx.accounts
    for template in ("non_financial", "financial", "insurance"):
        assert "profit_before_tax" in ngx.keys_for("income", template)
    labels = [m.source_label for m in ngx.mappings["profit_before_tax"]]
    assert "Profit before income tax expense" in labels  # GTCO
    assert "Profit/(loss) before taxation" in labels  # MTN


# --------------------------------------------------------------------------------------
# Reachability: a mapping nothing can look up is a mapping that does not exist
# --------------------------------------------------------------------------------------


def test_every_extraction_method_names_a_source_system_that_has_mappings(
    db_session: Session,
) -> None:
    """`manual` and `llm_hybrid` read printed labels, so both resolve through `ng_ifrs_label`.

    Without this the 98 Nigerian mappings are unreachable: a hand-typed statement would look
    up a source system with no rows and resolve every key to None - a full page of figures
    reported as not-in-filing.
    """
    assert SOURCE_SYSTEM_BY_METHOD == {
        "xbrl": "us_gaap_xbrl",
        "manual": "ng_ifrs_label",
        "llm_hybrid": "ng_ifrs_label",
    }
    for method, source_system in SOURCE_SYSTEM_BY_METHOD.items():
        chart = load_chart(db_session, version=VERSION, source_system=source_system)
        assert chart.mappings, f"method {method!r} resolves through an empty chart"


def test_every_required_key_can_actually_be_resolved(ngx, xbrl) -> None:
    """A required key with no mapping is a guaranteed `needs_review` on every filing."""
    by_system = {NGX: ngx, XBRL: xbrl}
    for name, chart in by_system.items():
        missing = [
            key
            for key, account in chart.accounts.items()
            if account.is_required and not chart.mappings.get(key)
        ]
        if name == XBRL:
            # The US path has no insurer in the universe and no bank balance-sheet tags for
            # the Nigerian-only keys; only the templates it serves need to be complete.
            missing = [
                k for k in missing if chart.accounts[k].template in ("both", "non_financial")
            ]
        assert not missing, f"{name}: required but unmappable: {sorted(missing)}"


def test_no_canonical_key_is_defined_twice(db_session: Session) -> None:
    keys = [
        r[0]
        for r in db_session.execute(
            text("SELECT canonical_key FROM chart_of_accounts WHERE chart_version = :v").bindparams(
                v=VERSION
            )
        )
    ]
    assert not [k for k, n in collections.Counter(keys).items() if n > 1]
    assert len(keys) == 65


def test_the_vocabularies_stay_inside_the_contract(db_session: Session) -> None:
    """`docs/08`'s enums for `statement`, `template` and `sign_convention`.

    No CHECK constraint enforces these, which is how `insurance` could be added without a
    migration to the enum - convenient here, and worth a test precisely because of that.
    """
    rows = db_session.execute(
        text(
            "SELECT DISTINCT statement, template, sign_convention FROM chart_of_accounts "
            "WHERE chart_version = :v"
        ).bindparams(v=VERSION)
    ).all()
    assert {r[0] for r in rows} <= {"income", "balance", "cashflow"}
    assert {r[1] for r in rows} <= {"both", "financial", "non_financial", "insurance"}
    assert {r[2] for r in rows} <= {"positive", "negative", "either"}


def _blank_manual_item(canonical_key: str) -> LineItemAsKnown:
    """A hand-typed Nigerian line item whose figure came back NULL."""
    return LineItemAsKnown(
        security_id=1,
        canonical_key=canonical_key,
        statement_type="income",
        period_type="FY",
        period_start=dt.date(2024, 1, 1),
        period_end=dt.date(2024, 12, 31),
        fiscal_year=2024,
        period_label="FY2024",
        value=None,
        currency="NGN",
        known_as_of=dt.date(2025, 4, 30),
        version=1,
        statement_id=1,
        source_document_id=1,
        chart_version=VERSION,
        extraction_method="manual",
        restatement_flag=False,
        correction_type="none",
        corrected_by=None,
        corrected_at=None,
        correction_reason=None,
    )


def test_a_blank_on_a_hand_typed_statement_is_not_blamed_on_the_company(
    db_session: Session,
) -> None:
    """The consequence of the method map, at the surface a reader actually sees.

    `_absent_because` promises to tell two blanks apart: `not_in_filing` is the company's
    silence, `no_mapping` is ours, and its docstring says "the screen must not blame the
    company for it". It reaches that judgement by loading the chart for the item's
    extraction method - and with `manual` absent from `SOURCE_SYSTEM_BY_METHOD` it returned
    `not_in_filing` without consulting any chart at all. Every blank on a hand-typed
    Nigerian statement would have been reported as the company having said nothing.

    Both directions are asserted, because a map that returned `no_mapping` for everything
    would pass a one-sided test while being just as wrong.
    """
    charts: dict[tuple[str, str], object] = {}
    mapped = _absent_because(db_session, _blank_manual_item("interest_income"), charts)  # type: ignore[arg-type]
    assert mapped == "not_in_filing", "the chart maps it, so the filing is what lacked it"

    unmapped = _absent_because(db_session, _blank_manual_item("rd_expense"), charts)  # type: ignore[arg-type]
    assert unmapped == "no_mapping", (
        "no Nigerian label maps to R&D, so this blank is ours and must say so"
    )


def test_an_insurer_is_not_resolved_against_the_bank_chart(ngx, xbrl) -> None:
    """`companies.statement_template` uses a sector vocabulary; the chart uses its own.

    `insurance` used to translate to `financial` "until the chart grows a third shape". v1
    grew one and an insurer still does not go there, because every `insurance` mapping is
    `ng_ifrs_label` - IFRS 17 "Insurance revenue" is the release of the contractual service
    margin plus expected claims, not a US health insurer's total revenues.

    What it must not keep doing is route to the bank chart. UnitedHealth was stored with no
    `revenue` row at all - 117 NULL rows each of `gross_earnings` and `net_interest_income`,
    keys a health insurer will never report - while the tags it does file were all mapped and
    none of them reachable.
    """
    assert _chart_template("insurance") != "financial", "the bank chart is not an insurer's"
    assert _chart_template("bank") == "financial"
    assert _chart_template("non_financial") == "non_financial"
    assert _chart_template("both") == "both"
    assert _chart_template("something_new") == "non_financial", "an unknown sector is not a bank"

    # The keys UnitedHealth's own filings can fill, under the template it now gets.
    template = _chart_template("insurance")
    income = xbrl.keys_for("income", template)
    for key in ("revenue", "operating_profit", "income_tax", "profit_after_tax"):
        assert key in income, f"{key} unreachable for an insurer"
    assert "gross_earnings" not in income, "a bank KPI, and permanently NULL for an insurer"
    assert "net_interest_income" not in income

    resolved = resolve(
        {
            "Revenues": Decimal("447567000000"),
            "OperatingIncomeLoss": Decimal("18964000000"),
            "IncomeTaxExpenseBenefit": Decimal("1890000000"),
            "NetIncomeLoss": Decimal("12056000000"),
        },
        xbrl,
        ("revenue", "operating_profit", "income_tax", "profit_after_tax"),
    )
    assert resolved["revenue"] == Decimal("447567000000"), "UnitedHealth FY2025, as filed"
    assert all(v is not None for v in resolved.values())

    # The Nigerian insurer keeps its own template, which is the one built for it.
    assert "insurance_revenue" in ngx.keys_for("income", "insurance")

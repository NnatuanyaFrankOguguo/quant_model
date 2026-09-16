"""0020 - chart of accounts v1: read against real Nigerian statements, not imagined ones. TG7.

Revision ID: 0020_p3_chart_v1
Revises: 0019_tg2_cik_into_identity
Create Date: 2026-09-17

`TEAM_BRIEF` §2.2-G, and P3's exit criterion *"chart of accounts v1 frozen and versioned"*.
v0.1 was drafted in P2 against US XBRL, where tagging is standardised, and `docs/08` §4 said
plainly what it was waiting for: *"freeze v1 in P3 once Nigerian statements have shown what it
is missing."* This is the versioning half of that, with the labels read off real audited
filings rather than recalled. The freeze itself waits on an extraction running through v1 -
see the last section.

**v0.1 is untouched.** It keeps all 23 keys and its 24 mappings, so the 53,710 line items
already stored keep resolving exactly as they did. That is the whole point of `chart_version`
being part of the key (TG7): a new vocabulary costs a version, never a re-extraction.

## P3 check 16, which v0.1 failed on all three counts

The checkpoint says: *"Before freezing v1, confirm it can express 'interest income', 'net
interest margin', and 'loan loss provision'. If it cannot, freezing now guarantees
re-extraction later."* Against v0.1:

*interest income* - v0.1 had only the *net* figure, which cannot be decomposed. v1 adds
`interest_income`, plus `interest_income_fvtpl` for the second line GTCO prints.

*net interest margin* - the numerator existed and nothing on the balance sheet could be
divided by it, so the ratio was unbuildable. v1 adds the earning-asset base:
`loans_and_advances_to_customers`, `loans_and_advances_to_banks` and the three
`investment_securities_*` keys.

*loan loss provision* - `DATA_FOUNDATION` §3.4 named an `impairments` key that was never
built. v1 adds `loan_impairment_charges`, GTCO's own wording.

v0.1's `financial` template had exactly two keys, `gross_earnings` and `net_interest_income`,
neither with a mapping. A bank resolved almost entirely to blanks, which the company page was
honestly reporting as "no XBRL tag mapped for this key yet" for Bank of America.

## What reading the filings changed

**`gross_earnings` is not a face line, and v0.1 marked it required.** GTCO's income statement
opens with two interest-income lines; "Gross Earnings" appears in the Directors' Report as a
computed KPI. Requiring it forced either an off-statement derivation or a false
`not_in_filing`. It stays in the chart, because the market quotes it, but `is_required` is now
false and the display name says where it comes from.

**"Operating profit" has three wordings and none is standard.** Nestlé prints "Results from
operating activities" (the IFRS Foundation's own illustrative phrasing, which is likely why a
global parent uses it), MTN prints "Operating profit", Dangote prints "Profit from operating
activities". v0.1's mapping table expected only the first. All three are mapped here.

**"Turnover" is legacy.** All three industrials print "Revenue". The alias is kept for older
filings but it is not what a 2025 statement says.

**"Finance costs", not "Interest expense", for a Nigerian industrial** - all three print
"Finance costs" paired with "Finance income", and none prints "Interest expense". Those are
two new keys rather than aliases of `interest_expense`, for the same reason `gross_earnings` is
not `revenue`: finance costs include lease interest and discount unwinding, so mapping them
together would produce a number that looks like interest and is not.

**`profit_before_tax` was missing from the chart entirely**, though every statement read
prints it and six of them word it differently. It is a `both` key here, and the US tag ties
out exactly against tax and net income for all three filers checked - see the mapping.
`income_tax` and `interest_expense` move to `both` for the same reason: a bank pays tax.

**MTN prints no cost of sales at all** - it presents expenses by nature, so `cost_of_revenue`
and `gross_profit` are legitimately absent for a telecom and resolve to `not_in_filing`.

**Dangote prints "Gain on net monetary position"**, an IAS 29 hyperinflation adjustment.
`DATA_FOUNDATION` §3.3 ruled IAS 29 inapplicable *to Nigeria*, and that stands - this arises
from a pan-African subsidiary, not from naira accounting. `net_monetary_gain` exists so the
line has somewhere to go instead of being silently dropped.

**Two US banks needed two different tags for one measure.** Gross interest income is
`InterestIncomeOperating` at JPMorgan (FY2025: $193,341m) and
`InterestAndDividendIncomeOperating` at Bank of America ($138,566m) - JPMorgan stopped filing
the second in 2011. Both name the same measure, so they are priority-ordered alternates, which
is exactly what `docs/08` §2.3 permits. `InterestExpense` itself stopped at FY2023 for both
banks in favour of `InterestExpenseOperating`, so both are mapped with the current one first.

**The provision trap, and why it is two keys.** JPMorgan files
`ProvisionForLoanLeaseAndOtherLosses` at $14,212m *and*
`FinancingReceivableExcludingAccruedInterestCreditLossExpenseReversal` at $11,264m for the
same year. They are not the same measure - the first is the total provision including
off-balance-sheet commitments, the second the loans component alone. Mapping them as alternates
would have given JPMorgan the total and Bank of America, which stopped filing the first in
2019, the component, and called them comparable. So `credit_loss_provision` is the total and
`loan_impairment_charges` the loans component, and GTCO's own "Loan impairment charges" maps to
the second because GTCO prints the other-assets impairment on its own separate line.

## The insurance template, which did not exist

`docs/10` §2.7 widened the template enum for insurers and no chart rows were ever written.
AIICO and Custodian are in the universe as *"the third statement shape"*, so this adds it - and
reading AIICO's filings turned up the finding with the largest consequences in this migration.

**AIICO adopted IFRS 17 with FY2023 as the changeover year, and the face of the income
statement changed completely.** Through FY2022 it opened with "Gross premium written" and ran
through claims and underwriting expenses. From FY2023 it opens with "Insurance Revenue" and
"Insurance service result". Both shapes sit inside the extraction window, so **one company has
two statement shapes across the years being extracted**, and a "FY2022" pulled from the FY2022
report differs in shape from the same year restated as a comparative inside the FY2023 report.

This is handled without dated mappings: the insurance template carries **both** vocabularies,
and a filing fills whichever it prints. A pre-2023 statement leaves the IFRS 17 keys absent and
a post-2023 statement leaves the premium keys absent, each honestly `not_in_filing`. The
alternative - one key set with dated mappings - would have made the changeover invisible in the
data, which is the opposite of what this schema is for.

**Deferred acquisition costs stop existing** under IFRS 17, folded into the contract balances
by AIICO's own policy note, so that key is pre-2023 only by nature rather than by rule.

**One mapping matches a typo on purpose.** AIICO prints "Fair value through other comprehesive
income", missing the *n*, identically in FY2024 and FY2025. Both the correct spelling and the
issuer's are mapped. This is the clearest argument for mappings being data in a table rather
than logic in code: nobody would write that string into a parser, and a reviewer can add it in
seconds.

## Sources

Labels were read from audited filings, not recalled: GTCO's FY2025 abridged result and Q3 2025
interim (gtcoplc.com, `doclib.ngxgroup.com`), AIICO's FY2025, FY2024 and FY2022 annual reports
(`doclib.ngxgroup.com`, aiicoplc.com - FY2022 as originally filed, pre-restatement), Nestlé
Nigeria's FY2025, MTN Nigeria's FY2025 and Dangote Cement's FY2025. The XBRL tags were read
from JPMorgan's and Bank of America's own `companyfacts`, newest 10-K value each.

**v1 is created, not yet frozen.** `docs/08` §4 wants the freeze once Nigerian statements have
shown what was missing, and they now have. What has not happened is the freeze's other half:
nothing has been extracted *through* v1 yet. Typing a company-year against it (`TEAM_BRIEF`
task D) is what turns "drafted from real labels" into "proven", and the operator makes that
call. Nothing is keyed to v1 until a writer asks for it, so the cost of changing it today is
still zero.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0020_p3_chart_v1"
down_revision: str | None = "0019_tg2_cik_into_identity"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

VERSION = "v1"
#: The version whose mappings are carried forward. v0.1 keeps every row it has.
PREVIOUS_VERSION = "v0.1"
XBRL = "us_gaap_xbrl"
#: Printed labels from a Nigerian IFRS statement, as opposed to an XBRL tag.
NGX = "ng_ifrs_label"

# (canonical_key, statement, template, display_name, sign_convention, is_required)
ACCOUNTS: tuple[tuple[str, str, str, str, str, bool], ...] = (
    # ---- every template: what all three statement shapes print ----------------------
    ("profit_before_tax", "income", "both", "Profit before tax", "either", True),
    ("income_tax", "income", "both", "Income tax expense", "either", True),
    ("profit_after_tax", "income", "both", "Profit after tax", "either", True),
    ("fx_loss_net", "income", "both", "Net foreign exchange gain or loss", "either", False),
    ("interest_expense", "income", "both", "Interest expense", "positive", False),
    ("total_assets", "balance", "both", "Total assets", "positive", True),
    ("total_liabilities", "balance", "both", "Total liabilities", "positive", False),
    ("total_equity", "balance", "both", "Total equity", "either", True),
    ("cash", "balance", "both", "Cash and cash equivalents", "positive", False),
    ("cash_from_ops", "cashflow", "both", "Net cash from operating activities", "either", True),
    ("dividends_paid", "cashflow", "both", "Dividends paid", "positive", False),
    # ---- non-financial ---------------------------------------------------------------
    ("revenue", "income", "non_financial", "Revenue", "positive", True),
    ("cost_of_revenue", "income", "non_financial", "Cost of sales", "positive", False),
    ("gross_profit", "income", "non_financial", "Gross profit", "either", False),
    ("operating_profit", "income", "non_financial", "Operating profit", "either", True),
    ("finance_income", "income", "non_financial", "Finance income", "positive", False),
    (
        "finance_costs",
        "income",
        "non_financial",
        "Finance costs (IFRS: wider than interest alone)",
        "positive",
        False,
    ),
    (
        "net_monetary_gain",
        "income",
        "non_financial",
        "Gain or loss on net monetary position (IAS 29)",
        "either",
        False,
    ),
    (
        "rd_expense",
        "income",
        "non_financial",
        "Research and development expense",
        "positive",
        False,
    ),
    (
        "depreciation_amortisation",
        "cashflow",
        "non_financial",
        "Depreciation and amortisation",
        "positive",
        False,
    ),
    (
        "capex",
        "cashflow",
        "non_financial",
        "Acquisition of property, plant and equipment",
        "positive",
        False,
    ),
    ("buybacks", "cashflow", "non_financial", "Repurchase of own shares", "positive", False),
    ("current_assets", "balance", "non_financial", "Total current assets", "positive", False),
    (
        "current_liabilities",
        "balance",
        "non_financial",
        "Total current liabilities",
        "positive",
        False,
    ),
    ("long_term_debt", "balance", "non_financial", "Borrowings, non-current", "positive", False),
    # ---- financial (banks) -----------------------------------------------------------
    ("interest_income", "income", "financial", "Interest income", "positive", True),
    (
        "interest_income_fvtpl",
        "income",
        "financial",
        "Interest income on assets at fair value through profit or loss",
        "positive",
        False,
    ),
    ("net_interest_income", "income", "financial", "Net interest income", "either", True),
    (
        "loan_impairment_charges",
        "income",
        "financial",
        "Loan impairment charges (loans component only)",
        "either",
        True,
    ),
    (
        "credit_loss_provision",
        "income",
        "financial",
        "Total provision for credit losses, including off-balance-sheet",
        "either",
        False,
    ),
    (
        "impairment_other_financial_assets",
        "income",
        "financial",
        "Impairment on financial assets other than loans",
        "either",
        False,
    ),
    (
        "fee_and_commission_income",
        "income",
        "financial",
        "Fee and commission income",
        "positive",
        False,
    ),
    (
        "net_fee_and_commission_income",
        "income",
        "financial",
        "Net fee and commission income",
        "either",
        False,
    ),
    ("noninterest_income", "income", "financial", "Non-interest income", "either", False),
    ("noninterest_expense", "income", "financial", "Non-interest expense", "positive", False),
    ("personnel_expenses", "income", "financial", "Personnel expenses", "positive", False),
    (
        "other_operating_expenses",
        "income",
        "financial",
        "Other operating expenses",
        "positive",
        False,
    ),
    (
        "gross_earnings",
        "income",
        "financial",
        "Gross earnings (a Directors' Report KPI, not a face line)",
        "positive",
        False,
    ),
    (
        "loans_and_advances_to_customers",
        "balance",
        "financial",
        "Loans and advances to customers",
        "positive",
        True,
    ),
    (
        "loans_and_advances_to_banks",
        "balance",
        "financial",
        "Loans and advances to banks",
        "positive",
        False,
    ),
    (
        "investment_securities_fvoci",
        "balance",
        "financial",
        "Investment securities at fair value through other comprehensive income",
        "positive",
        False,
    ),
    (
        "investment_securities_amortised_cost",
        "balance",
        "financial",
        "Investment securities held at amortised cost",
        "positive",
        False,
    ),
    (
        "investment_securities_fvtpl",
        "balance",
        "financial",
        "Investment securities at fair value through profit or loss",
        "positive",
        False,
    ),
    (
        "deposits_from_customers",
        "balance",
        "financial",
        "Deposits from customers",
        "positive",
        True,
    ),
    ("deposits_from_banks", "balance", "financial", "Deposits from banks", "positive", False),
    ("other_borrowed_funds", "balance", "financial", "Other borrowed funds", "positive", False),
    # ---- insurance, IFRS 17 (FY2023 onwards at AIICO) --------------------------------
    ("insurance_revenue", "income", "insurance", "Insurance revenue", "positive", True),
    (
        "insurance_service_expense",
        "income",
        "insurance",
        "Insurance service expense",
        "positive",
        False,
    ),
    (
        "net_expenses_from_reinsurance",
        "income",
        "insurance",
        "Net expenses from reinsurance contracts",
        "either",
        False,
    ),
    ("insurance_service_result", "income", "insurance", "Insurance service result", "either", True),
    ("net_investment_income", "income", "insurance", "Net investment income", "either", False),
    (
        "net_insurance_finance_result",
        "income",
        "insurance",
        "Net insurance finance result",
        "either",
        False,
    ),
    (
        "insurance_contract_liabilities",
        "balance",
        "insurance",
        "Insurance contract liabilities",
        "positive",
        True,
    ),
    (
        "investment_contract_liabilities",
        "balance",
        "insurance",
        "Investment contract liabilities",
        "positive",
        False,
    ),
    (
        "reinsurance_contract_assets",
        "balance",
        "insurance",
        "Reinsurance contract assets (IFRS 17 wording)",
        "positive",
        False,
    ),
    ("investment_properties", "balance", "insurance", "Investment properties", "positive", False),
    (
        "financial_assets_fvoci",
        "balance",
        "insurance",
        "Financial assets at fair value through other comprehensive income",
        "positive",
        False,
    ),
    # ---- insurance, pre-IFRS 17 (through FY2022 at AIICO) ----------------------------
    ("gross_premium_written", "income", "insurance", "Gross premium written", "positive", False),
    ("gross_premium_income", "income", "insurance", "Gross premium income", "positive", False),
    (
        "reinsurance_expenses",
        "income",
        "insurance",
        "Reinsurance expenses (premium ceded)",
        "positive",
        False,
    ),
    ("net_premium_income", "income", "insurance", "Net premium income", "either", False),
    ("underwriting_expenses", "income", "insurance", "Underwriting expenses", "positive", False),
    ("underwriting_profit", "income", "insurance", "Underwriting profit", "either", False),
    (
        "deferred_acquisition_costs",
        "balance",
        "insurance",
        "Deferred acquisition costs (gone under IFRS 17)",
        "positive",
        False,
    ),
    (
        "reinsurance_assets",
        "balance",
        "insurance",
        "Reinsurance assets (pre-IFRS 17 wording)",
        "positive",
        False,
    ),
)

# (source_system, source_label, canonical_key, priority)
# Priority orders alternates: the first present label wins. An alternate must name the SAME
# measure (`docs/08` §2.3), which is why the provision keys are separate rather than ranked.
MAPPINGS: tuple[tuple[str, str, str, int], ...] = (
    # ---- Nigerian printed labels, non-financial --------------------------------------
    (NGX, "Revenue", "revenue", 10),
    (NGX, "Turnover", "revenue", 90),  # legacy; no 2025 filing read used it
    (NGX, "Cost of sales", "cost_of_revenue", 10),
    (NGX, "Production cost of sales", "cost_of_revenue", 20),  # Dangote's own wording
    (NGX, "Gross profit", "gross_profit", 10),
    (NGX, "Operating profit", "operating_profit", 10),  # MTN
    (NGX, "Results from operating activities", "operating_profit", 20),  # Nestle
    (NGX, "Profit from operating activities", "operating_profit", 30),  # Dangote
    (NGX, "Finance income", "finance_income", 10),
    (NGX, "Finance costs", "finance_costs", 10),
    (NGX, "Net finance costs", "finance_costs", 90),  # Nestle's subtotal, last resort
    (NGX, "Gain on net monetary position", "net_monetary_gain", 10),
    (NGX, "Loss on net monetary position", "net_monetary_gain", 20),
    (NGX, "Total current assets", "current_assets", 10),
    (NGX, "Total current liabilities", "current_liabilities", 10),
    (NGX, "Interest bearing loans and borrowings", "long_term_debt", 10),
    (NGX, "Borrowings", "long_term_debt", 20),
    (NGX, "Depreciation and amortisation", "depreciation_amortisation", 10),
    (NGX, "Depreciation and amortization", "depreciation_amortisation", 20),
    (NGX, "Depreciation, amortisation and impairment", "depreciation_amortisation", 30),
    (NGX, "Acquisition of property, plant and equipment", "capex", 10),
    (NGX, "Acquisition of property and equipment", "capex", 20),  # MTN drops "plant"
    (NGX, "Additions to property, plant and equipment", "capex", 30),
    # ---- Nigerian printed labels, all templates --------------------------------------
    (NGX, "Profit before tax", "profit_before_tax", 10),
    (NGX, "Profit before income tax", "profit_before_tax", 20),
    (NGX, "Profit before income tax expense", "profit_before_tax", 30),  # GTCO
    (NGX, "Profit/(loss) before income tax", "profit_before_tax", 40),  # Nestle
    (NGX, "Profit/(loss) before taxation", "profit_before_tax", 50),  # MTN
    (NGX, "Profit before income tax from continuing operations", "profit_before_tax", 60),
    (NGX, "Income tax expense", "income_tax", 10),
    (NGX, "Income tax (expense)/credit", "income_tax", 20),
    (NGX, "Tax (expense)/credit", "income_tax", 30),  # MTN
    (NGX, "Profit for the year", "profit_after_tax", 10),
    (NGX, "Profit/(loss) for the year", "profit_after_tax", 20),
    (NGX, "Net foreign exchange gain/(loss)", "fx_loss_net", 10),  # MTN
    (NGX, "Net foreign exchange (loss)/gain", "fx_loss_net", 20),  # AIICO FY2025
    (NGX, "Net foreign exchange gain", "fx_loss_net", 30),  # AIICO FY2024
    (NGX, "Net foreign exchange loss", "fx_loss_net", 40),
    (NGX, "Total assets", "total_assets", 10),
    (NGX, "TOTAL ASSETS", "total_assets", 20),  # GTCO capitalises
    (NGX, "Total liabilities", "total_liabilities", 10),
    (NGX, "TOTAL LIABILITIES", "total_liabilities", 20),
    (NGX, "Total equity", "total_equity", 10),
    (NGX, "TOTAL EQUITY", "total_equity", 20),
    (NGX, "Cash and cash equivalents", "cash", 10),
    (NGX, "Cash and bank balances", "cash", 20),  # GTCO
    (NGX, "Cash and short-term deposits", "cash", 30),  # Nestle
    (NGX, "Net cash from operating activities", "cash_from_ops", 10),  # Nestle
    (NGX, "Net cash generated from operating activities", "cash_from_ops", 20),  # MTN, Dangote
    (NGX, "Net cash flow (used in)/generated from operating activities", "cash_from_ops", 30),
    (NGX, "Dividends paid", "dividends_paid", 10),
    (NGX, "Interest expense", "interest_expense", 10),  # GTCO prints it plainly
    # ---- Nigerian printed labels, banks ----------------------------------------------
    (NGX, "Interest income", "interest_income", 10),
    (NGX, "Interest income calculated using the effective interest rate", "interest_income", 20),
    (NGX, "Interest income calculated using the effective interest method", "interest_income", 30),
    (
        NGX,
        "Interest income on financial assets at fair value through profit or loss",
        "interest_income_fvtpl",
        10,
    ),
    (NGX, "Net interest income", "net_interest_income", 10),
    (NGX, "Loan impairment charges", "loan_impairment_charges", 10),  # GTCO
    (NGX, "Impairment charge", "loan_impairment_charges", 20),
    (NGX, "Net impairment loss on financial assets", "impairment_other_financial_assets", 10),
    (
        NGX,
        "Net impairment reversal/(charge) on other financial assets",
        "impairment_other_financial_assets",
        20,
    ),
    (NGX, "Fee and commission income", "fee_and_commission_income", 10),
    (NGX, "Net fee and commission income", "net_fee_and_commission_income", 10),
    (NGX, "Personnel expenses", "personnel_expenses", 10),
    (NGX, "Other operating expenses", "other_operating_expenses", 10),
    (NGX, "Gross earnings", "gross_earnings", 10),
    (NGX, "Gross Earnings", "gross_earnings", 20),
    (NGX, "Loans and advances to customers", "loans_and_advances_to_customers", 10),
    (NGX, "Loans and advances to banks", "loans_and_advances_to_banks", 10),
    (
        NGX,
        "Investment securities - Fair value through Other Comprehensive Income",
        "investment_securities_fvoci",
        10,
    ),
    (
        NGX,
        "Investment securities - Held at amortised cost",
        "investment_securities_amortised_cost",
        10,
    ),
    (
        NGX,
        "Investment securities - Fair value through Profit or Loss",
        "investment_securities_fvtpl",
        10,
    ),
    (NGX, "Deposits from customers", "deposits_from_customers", 10),
    (NGX, "Deposits from banks", "deposits_from_banks", 10),
    (NGX, "Other borrowed funds", "other_borrowed_funds", 10),
    # ---- Nigerian printed labels, insurance under IFRS 17 ----------------------------
    (NGX, "Insurance Revenue", "insurance_revenue", 10),
    (NGX, "Insurance revenue", "insurance_revenue", 20),
    (NGX, "Insurance Service Expense", "insurance_service_expense", 10),
    (NGX, "Net Expenses from Reinsurance Contracts", "net_expenses_from_reinsurance", 10),
    (NGX, "Insurance service result", "insurance_service_result", 10),
    (NGX, "Net investment income", "net_investment_income", 10),
    (NGX, "Net insurance finance result", "net_insurance_finance_result", 10),
    (NGX, "Net insurance finance expenses", "net_insurance_finance_result", 20),  # FY2024 wording
    (NGX, "Insurance contract liabilities", "insurance_contract_liabilities", 10),
    (NGX, "Investment contract liabilities", "investment_contract_liabilities", 10),
    (NGX, "Reinsurance contract assets", "reinsurance_contract_assets", 10),
    (NGX, "Investment properties", "investment_properties", 10),
    (
        NGX,
        "Fair value through other comprehensive income",
        "financial_assets_fvoci",
        10,
    ),
    # AIICO's own typo, identical in FY2024 and FY2025. Mapped because the filing says it.
    (
        NGX,
        "Fair value through other comprehesive income",
        "financial_assets_fvoci",
        20,
    ),
    # ---- Nigerian printed labels, insurance before IFRS 17 ---------------------------
    (NGX, "Gross premium written", "gross_premium_written", 10),
    (NGX, "Gross premium income", "gross_premium_income", 10),
    (NGX, "Reinsurance expenses", "reinsurance_expenses", 10),
    (NGX, "Net premium income", "net_premium_income", 10),
    (NGX, "Underwriting expenses", "underwriting_expenses", 10),
    (NGX, "Total underwriting expenses", "underwriting_expenses", 20),
    (NGX, "Underwriting profit", "underwriting_profit", 10),
    (NGX, "Deferred acquisition costs", "deferred_acquisition_costs", 10),
    (NGX, "Reinsurance assets", "reinsurance_assets", 10),
    # ---- US GAAP tags for the keys v1 adds to every template -------------------------
    # `profit_before_tax` is new in v1 and required, so the US path needs it too. The tag
    # ties out exactly against tax and net income for all three filers checked:
    # Apple 132,729 - 20,719 = 112,010; JPMorgan 72,595 - 15,547 = 57,048;
    # Bank of America 37,695 - 7,186 = 30,509 (FY2025, $m, from each company's companyfacts).
    # The MinorityInterest variant is historical - last filed FY2020 at JPMorgan, FY2012 at
    # Apple - so it ranks second rather than being dropped, for the older filings.
    (
        XBRL,
        "IncomeLossFromContinuingOperationsBeforeIncomeTaxesExtraordinaryItemsNoncontrollingInterest",
        "profit_before_tax",
        10,
    ),
    (
        XBRL,
        "IncomeLossFromContinuingOperationsBeforeIncomeTaxesMinorityInterest"
        "AndIncomeLossFromEquityMethodInvestments",
        "profit_before_tax",
        20,
    ),
    # ---- US GAAP tags for the bank keys, read from JPM's and BAC's companyfacts ------
    (XBRL, "InterestIncomeOperating", "interest_income", 10),  # JPM FY2025
    (XBRL, "InterestAndDividendIncomeOperating", "interest_income", 20),  # BAC FY2025
    (XBRL, "InterestIncomeExpenseNet", "net_interest_income", 10),
    (
        XBRL,
        "FinancingReceivableExcludingAccruedInterestCreditLossExpenseReversal",
        "loan_impairment_charges",
        10,
    ),
    (XBRL, "ProvisionForLoanLeaseAndOtherLosses", "credit_loss_provision", 10),
    (XBRL, "NoninterestIncome", "noninterest_income", 10),
    (XBRL, "NoninterestExpense", "noninterest_expense", 10),
    (
        XBRL,
        "FinancingReceivableExcludingAccruedInterestAfterAllowanceForCreditLoss",
        "loans_and_advances_to_customers",
        10,
    ),
    (
        XBRL,
        "DebtSecuritiesAvailableForSaleExcludingAccruedInterest",
        "investment_securities_fvoci",
        10,
    ),
    (XBRL, "HeldToMaturitySecurities", "investment_securities_amortised_cost", 10),
    (XBRL, "Deposits", "deposits_from_customers", 10),
    (XBRL, "InterestBearingDepositLiabilities", "deposits_from_customers", 90),
    # InterestExpense stopped at FY2023 for both banks; the Operating variant is current.
    (XBRL, "InterestExpenseOperating", "interest_expense", 10),
    (XBRL, "InterestExpense", "interest_expense", 20),
)


def upgrade() -> None:
    accounts = sa.table(
        "chart_of_accounts",
        sa.column("canonical_key", sa.Text),
        sa.column("chart_version", sa.Text),
        sa.column("statement", sa.Text),
        sa.column("template", sa.Text),
        sa.column("display_name", sa.Text),
        sa.column("sign_convention", sa.Text),
        sa.column("is_required", sa.Boolean),
    )
    op.bulk_insert(
        accounts,
        [
            {
                "canonical_key": key,
                "chart_version": VERSION,
                "statement": statement,
                "template": template,
                "display_name": display,
                "sign_convention": sign,
                "is_required": required,
            }
            for key, statement, template, display, sign, required in ACCOUNTS
        ],
    )

    mappings = sa.table(
        "account_mappings",
        sa.column("chart_version", sa.Text),
        sa.column("source_system", sa.Text),
        sa.column("source_label", sa.Text),
        sa.column("canonical_key", sa.Text),
        sa.column("template", sa.Text),
        sa.column("priority", sa.SmallInteger),
        sa.column("confidence", sa.Numeric),
        sa.column("added_by", sa.Text),
    )
    template_of = {key: template for key, _s, template, _d, _sc, _r in ACCOUNTS}
    op.bulk_insert(
        mappings,
        [
            {
                "chart_version": VERSION,
                "source_system": system,
                "source_label": label,
                "canonical_key": key,
                "template": template_of[key],
                "priority": priority,
                "confidence": 1.0,
                "added_by": "0020 (read from audited filings)",
            }
            for system, label, key, priority in MAPPINGS
        ],
    )

    # v0.1's mappings, carried forward so the US path resolves exactly as it does today -
    # but only for keys v1 does not itself map.
    #
    # The exclusion is the point, not a convenience. A priority list is only meaningful as a
    # whole: v0.1 maps `InterestExpense` to `interest_expense` at priority 10, and v1 puts
    # `InterestExpenseOperating` at 10 because the plain tag stopped being filed after FY2023.
    # Copying v0.1's row in beside v1's would leave two labels for one key at the same
    # priority, and which one won would come down to row id - a coin toss dressed as a rule.
    # So where v1 speaks about a (source_system, canonical_key), v1's list is complete and
    # replaces v0.1's; everywhere else v0.1's carries over untouched. For `interest_expense`,
    # v1's list is a superset, so nothing is lost.
    #
    # `template` is re-read from v1's own account row because two keys - `income_tax` and
    # `interest_expense` - moved to 'both' in this version.
    op.execute(
        sa.text(
            """
            INSERT INTO account_mappings
                   (chart_version, source_system, source_label, canonical_key,
                    template, priority, confidence, added_by)
            SELECT :new_version, m.source_system, m.source_label, m.canonical_key,
                   a.template, m.priority, m.confidence, '0020 (carried from v0.1)'
              FROM account_mappings m
              JOIN chart_of_accounts a
                ON a.canonical_key = m.canonical_key AND a.chart_version = :new_version
             WHERE m.chart_version = :old_version
               AND NOT EXISTS (
                     SELECT 1 FROM account_mappings v1
                      WHERE v1.chart_version = :new_version
                        AND v1.source_system = m.source_system
                        AND v1.canonical_key = m.canonical_key
                   )
            """
        ).bindparams(new_version=VERSION, old_version=PREVIOUS_VERSION)
    )

    # Every (source system, key) that could resolve under v0.1 must still resolve under v1.
    # The JOIN above drops a mapping silently if v1 renamed or forgot its key, and a key that
    # resolves to nothing looks exactly like a company that did not report the line - which is
    # the one confusion `docs/08` §1.4 exists to prevent. So this refuses to be that quiet.
    orphaned = (
        op.get_bind()
        .execute(
            sa.text(
                """
            SELECT DISTINCT m.source_system, m.canonical_key
              FROM account_mappings m
             WHERE m.chart_version = :old_version
               AND NOT EXISTS (
                     SELECT 1 FROM account_mappings v1
                      WHERE v1.chart_version = :new_version
                        AND v1.source_system = m.source_system
                        AND v1.canonical_key = m.canonical_key
                   )
             ORDER BY 1, 2
            """
            ).bindparams(new_version=VERSION, old_version=PREVIOUS_VERSION)
        )
        .all()
    )
    if orphaned:
        listed = ", ".join(f"{system}:{key}" for system, key in orphaned)
        raise RuntimeError(
            f"{VERSION} would leave these {PREVIOUS_VERSION} mappings unresolvable: {listed}. "
            f"Every key that resolved under {PREVIOUS_VERSION} must still resolve, or figures "
            f"already stored become indistinguishable from figures never reported."
        )


def downgrade() -> None:
    op.execute(
        sa.text("DELETE FROM account_mappings WHERE chart_version = :v").bindparams(v=VERSION)
    )
    op.execute(
        sa.text("DELETE FROM chart_of_accounts WHERE chart_version = :v").bindparams(v=VERSION)
    )

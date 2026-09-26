# Ratios known-answer worksheet

The hand computation behind `test_ratios.py`. Figures are Apple's FY2025 as stored by
P2.1 (period end 2025-09-27, known 2025-10-31), in USD millions, against a price of
$255.46 and 14,840 million diluted shares — both round, both stated, neither "today's".

| Line item | USD m |
|---|---|
| revenue | 416,161 |
| cost_of_revenue | 220,960 |
| gross_profit | 195,201 |
| operating_profit | 133,050 |
| profit_after_tax | 112,010 |
| total_assets | 359,241 |
| total_liabilities | 285,508 |
| total_equity | 73,733 |
| current_assets | 147,957 |
| current_liabilities | 165,631 |
| cash | 35,934 |
| long_term_debt | 78,328 |
| cash_from_ops | 111,482 |
| capex | 12,715 |
| depreciation_amortisation | 11,698 |
| dividends_paid | 15,421 |
| interest_expense | *not reported* |

## Profitability, returns, leverage, liquidity

| Ratio | Arithmetic | Value |
|---|---|---|
| gross_margin | 195,201 / 416,161 | 0.469052 |
| operating_margin | 133,050 / 416,161 | 0.319708 |
| net_margin | 112,010 / 416,161 | 0.269151 |
| roe | 112,010 / 73,733 | 1.519130 |
| roa | 112,010 / 359,241 | 0.311796 |
| current_ratio | 147,957 / 165,631 | 0.893293 |
| debt_to_equity | 78,328 / 73,733 | 1.062319 |
| liabilities_to_assets | 285,508 / 359,241 | 0.794753 |
| interest_coverage | 133,050 / *not reported* | **None** |
| free_cash_flow | 111,482 − 12,715 | 98,767 |
| fcf_margin | 98,767 / 416,161 | 0.237329 |
| ebitda | 133,050 + 11,698 | 144,748 |
| net_debt | 78,328 − 35,934 | 42,394 |

## Per share and multiples (price 255.46, shares 14,840 m)

| Figure | Arithmetic | Value |
|---|---|---|
| market_cap | 255.46 × 14,840 | 3,791,026.4 |
| enterprise_value | 3,791,026.4 + 42,394 | 3,833,420.4 |
| eps | 112,010 / 14,840 | 7.547844 |
| book_value_per_share | 73,733 / 14,840 | 4.968531 |
| fcf_per_share | 98,767 / 14,840 | 6.655458 |
| pe | 3,791,026.4 / 112,010 | 33.845428 |
| pb | 3,791,026.4 / 73,733 | 51.415600 |
| ps | 3,791,026.4 / 416,161 | 9.109519 |
| ev_sales | 3,833,420.4 / 416,161 | 9.211388 |
| ev_ebitda | 3,833,420.4 / 144,748 | 26.483408 |
| earnings_yield | 112,010 / 3,791,026.4 | 0.029546 |
| fcf_yield | 98,767 / 3,791,026.4 | 0.026053 |
| dividend_yield | 15,421 / 3,791,026.4 | 0.004068 |

Cross-check: 1 / pe = 1 / 33.845428 = 0.029546 = earnings_yield. ✓

## Check 7 — null propagates

- With no price: every multiple and per-share figure is **None**; the margins are unchanged.
- With profit_after_tax missing: net_margin, roe, roa, eps, pe, earnings_yield are None.
- With profit_after_tax = −1,000 (a loss): pe is **None**, not −3,791. earnings_yield is
  negative, which is a real number and is returned.
- With total_equity = 0: roe, debt_to_equity and pb divide by equity and are None — never
  infinity. book_value_per_share is 0 / shares = **0**, which is a value, not an absence.

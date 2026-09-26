# DCF known-answer worksheet

The spreadsheet reasoning behind `test_dcf.py`, done by hand so the test checks the model
against arithmetic a person can follow, not against the model's own output.

## Case A — the round-number case

Chosen so every intermediate is exact: growth equals the discount rate, so each year's
present value equals the base cash flow.

| Assumption | Value |
|---|---|
| Base free cash flow | 100 |
| Growth, years 1–3 | 10 % each |
| Discount rate | 10 % |
| Terminal growth | 2 % |
| Net debt | 50 |
| Shares | 10 |

| Year | FCF = prior × 1.10 | Discount factor = 1 / 1.10^t | PV |
|---|---|---|---|
| 1 | 110.000 | 0.909091 | 100.000 |
| 2 | 121.000 | 0.826446 | 100.000 |
| 3 | 133.100 | 0.751315 | 100.000 |
| Sum of PVs | | | **300.000** |

Terminal value = FCF₃ × (1 + g) / (r − g) = 133.1 × 1.02 / 0.08 = 135.762 / 0.08 = **1,697.025**

PV of terminal value = 1,697.025 / 1.10³ = 1,697.025 / 1.331 = **1,275.000** (exactly)

| Result | Value |
|---|---|
| Enterprise value | 300 + 1,275 = **1,575.000** |
| Equity value | 1,575 − 50 = **1,525.000** |
| Value per share | 1,525 / 10 = **152.500** |
| Terminal share of EV | 1,275 / 1,575 = **0.809524** |

## Case B — check 14: a 100 bp move in the discount rate

Same as case A with the discount rate at 9 % instead of 10 %.

| Year | FCF | DF = 1 / 1.09^t | PV |
|---|---|---|---|
| 1 | 110.000 | 0.917431 | 100.917 |
| 2 | 121.000 | 0.841680 | 101.843 |
| 3 | 133.100 | 0.772183 | 102.778 |
| Sum | | | **305.539** |

TV = 133.1 × 1.02 / (0.09 − 0.02) = 135.762 / 0.07 = **1,939.457**
PV(TV) = 1,939.457 × 0.772183 = **1,497.617**
EV = 305.539 + 1,497.617 = **1,803.156**; equity = **1,753.156**; per share = **175.316**

So a 100 bp *cut* in the discount rate lifts the value per share from 152.50 to 175.32 —
**+15.0 %** — and a 100 bp rise lowers it. The direction is right and the magnitude is
what a terminal value at 81 % of EV should produce. That is `docs/03` P2 check 14.

## Case C — mid-year convention

Case A with mid-year discounting: DF_t = 1 / 1.10^(t − 0.5) = DF_t(end-year) × √1.10.

√1.10 = 1.048809. Each PV becomes 100 × 1.048809 = 104.881; sum = 314.643. The terminal
value is still discounted from the end of year 3 (1,275.000), so EV = 1,589.643.

## Case D — what must be refused

- Terminal growth ≥ discount rate: the Gordon formula divides by zero or goes negative.
  `ValueError`, not a number.
- No projected years: `ValueError`.
- Zero or negative shares: `ValueError`; a `None` share count gives no per-share figure.

# Indicator worksheet — the conventions, written down

`docs/03` P6.2 makes known-answer tests mandatory, and says why:

> Libraries differ on smoothing conventions — Wilder versus simple, for instance — and a
> subtly different RSI is a subtly different model.

P6 check 12 asks for one RSI-14 computed by hand and compared. This worksheet is that,
generalised: for each indicator, the recurrence the project has decided it means, written
so a second implementation can be produced from this page alone.

---

## How these tests are written, and one trap

The tests compare `pandas-ta-classic` against **an independent implementation of the
recurrence below**, written from the definition rather than from the library.

They deliberately do **not** compare against a published table of values, and it is worth
recording why, because the obvious approach misleads.

StockCharts publishes an RSI-14 table for Wilder's own worked example. Checked against it,
`pandas-ta-classic` looks wrong — up to **0.10** out, systematically, on the early values.
It is not wrong. That table is computed from closing prices rounded to two decimals and
then printed to four, so the rounding is in the *reference*, not the library. The
giveaway is that one row of the table differs by 0.0002 while its neighbours differ by
0.068: the error accumulates and decays like a seeding artefact, which is exactly what it
is.

Measured 2026-09-24, `pandas-ta-classic` 0.8.32 against the independent implementation:
agreement to **ten decimal places**. It is Wilder.

A test written against the published table would have failed, and the natural response —
"the library's convention must differ, write our own" — would have replaced a correct
implementation with a hand-rolled one on the strength of a rounding artefact.

---

## RSI — Wilder (1978), *New Concepts in Technical Trading Systems*

For period `n` (default 14), over closes `p[0..N]`:

```
change[i] = p[i] - p[i-1]                     for i = 1..N
gain[i]   = max(change[i], 0)
loss[i]   = max(-change[i], 0)

# seed: a simple mean of the first n changes
avgGain[n] = (gain[1] + ... + gain[n]) / n
avgLoss[n] = (loss[1] + ... + loss[n]) / n

# thereafter: Wilder's smoothing, equivalent to an EMA with alpha = 1/n
avgGain[i] = (avgGain[i-1] * (n-1) + gain[i]) / n
avgLoss[i] = (avgLoss[i-1] * (n-1) + loss[i]) / n

RS[i]  = avgGain[i] / avgLoss[i]
RSI[i] = 100 - 100 / (1 + RS[i])
```

The first RSI value lands at index `n` of the close series; everything before it is NULL,
not zero. **`avgLoss == 0` gives RSI 100** — the series has only risen — and must not be
a division by zero.

**The seed is the whole question.** A simple mean of the first `n` changes is Wilder. An
EMA seeded on the first change instead, or `ewm(adjust=True)`, gives values that converge
to the same place but differ for the first several dozen bars — which is precisely the
region a short backtest window lives in.

### The vector

Wilder's example closes, as published:

```
44.3389 44.0902 44.1497 43.6124 44.3278 44.8264 45.0955 45.4245 45.8433 46.0826
45.8931 46.0328 45.6140 46.2820 46.2820 46.0028 46.0328 46.4116 46.2222 45.6439
46.2122 46.2521 45.7137 46.4515 45.7835 45.3548 44.0288 44.1783 44.2181 44.5672
43.4205 42.6628 43.1314
```

First value, computed by the recurrence above: **70.532789…** (the rounded published
table says 70.4642; see the trap above).

---

## Adjusted prices are not optional

P6 checks 3 and 11. The same RSI-14 on Apple around its 4-for-1 split of 2020-08-31:

| date | adjusted close | raw close | RSI (adjusted) | RSI (raw) |
|---|---|---|---|---|
| 2020-08-28 | 124.81 | 499.23 | 74.34 | 74.34 |
| **2020-08-31** | **129.04** | **129.04** | **78.27** | **15.03** |

On raw prices the split reads as a 74% collapse, and RSI records the most violent
sell-off in the security's history on a day the stock rose. A 63-point error, silent,
inherited by every feature built on it. This is the one risk `docs/03` P6 marks
🔴 FRAGILE, and the reason `indicators.price_series` is a column rather than a convention.

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

### And one more thing the tests do

Agreement to 1e-9 only means something if disagreement was *possible*. So for each
indicator where a rival convention exists, the rival is implemented too, and
`test_the_rival_conventions_differ_materially_from_what_the_library_does` asserts that
it lands well outside the tolerance — 1.95 for a differently-seeded MACD, 0.61 for a
sample-deviation Bollinger, 0.59 for an `ewm`-seeded ATR, a whole bar's volume for a
zero-seeded OBV. Without it, a known-answer test that would have passed under either
reading has measured nothing, and the convention it claims to pin is still loose.

Each section below records the rival it was checked against, so that test can be
rebuilt from this page too.

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

## The vector the other five are checked on

Not a published table — for the reason above — and not a table at all. Four lines that
generate sixty bars of OHLCV, so that a second implementation reproduces the *input*
exactly rather than inheriting somebody's rounding:

```
for i = 0 .. 59
  close[i]  = round(100 + 12*sin(i/4) + 0.45*i, 4)
  high[i]   = round(close[i] + 1.5 + 0.5*cos(i/3), 4)
  low[i]    = round(close[i] - 1.5 - 0.5*sin(i/2), 4)
  volume[i] = 1,000,000 + 25,000 * ((i*37) mod 11)
```

The first three bars, as a spot check:

| i | close | high | low | volume |
|---|---|---|---|---|
| 0 | 100.0000 | 102.0000 | 98.5000 | 1,000,000 |
| 1 | 103.4188 | 105.3913 | 101.6791 | 1,100,000 |
| 2 | 106.6531 | 108.5460 | 104.7324 | 1,200,000 |

Sixty bars because MACD-12-26-9 has no histogram until bar 33, and a known-answer test
that stops at the first value has tested a seed rather than a recurrence. Rounded to
four places so the vector is byte-identical on every libm — the test compares two
implementations against each other on one array and would hold regardless, but a vector
worth writing down is one that reproduces. High sits a full point above the close and
low a full point below, so every bar is well formed and no stochastic denominator is
accidentally zero; the degenerate cases are constructed deliberately, further down.

Each "first value" below was computed by the recurrence on this page, not read off
anything. `pandas-ta-classic` 0.8.32 agrees with all of them.

---

## MACD — Appel (1979), *The Moving Average Convergence-Divergence Method*

For fast `f` (12), slow `s` (26) and signal `g` (9), over closes `p[0..N]`, where
`EMA_n` means:

```
alpha       = 2 / (n + 1)
EMA_n[n-1]  = (x[0] + ... + x[n-1]) / n          # seed: a simple mean of the first n
EMA_n[i]    = alpha*x[i] + (1 - alpha)*EMA_n[i-1]              for i >= n
```

then:

```
macd[i]   = EMA_f(p)[i] - EMA_s(p)[i]                first value at i = s-1  (25)
signal[i] = EMA_g(macd)[i]                           first value at i = s+g-2 (33)
hist[i]   = macd[i] - signal[i]
```

**The signal EMA is seeded on the MACD line, not on the closes**, and its seed is the
mean of the first `g` values the MACD line has — `macd[s-1 .. s+g-2]` — so it begins
`g-1` bars after the MACD line does, and not one bar earlier.

First values on the vector above: `macd[25] = -1.9071674713`,
`signal[33] = 1.8678117338`, `hist[33] = 2.9478722608`.

**The seed is the whole question here too.** Three readings were live:

| seeding | `macd[25]` differs from the SMA seed by |
|---|---|
| mean of the first `n` (this one) | — |
| `ewm(adjust=False)`, from the first close | up to **1.95** |
| `ewm(adjust=True)` | up to **1.43** |

All three converge; all three disagree across the first several dozen bars, which is the
whole of a short window. The histogram is the second live question: `macd - signal`, not
`2 * (macd - signal)`, which several charting packages plot.

Measured agreement with `pandas-ta-classic` 0.8.32: **exact**, bit for bit, on all three
columns across all sixty bars.

**Degenerate cases.** None. Nothing here divides by anything the data supplies, and a
motionless security gives `macd = signal = hist = 0`, which is a true statement about a
price that did not move rather than an absence.

---

## Bollinger Bands — Bollinger, *Bollinger on Bollinger Bands*

For period `n` (20) and width `w` (2.0):

```
mid[i]   = (p[i-n+1] + ... + p[i]) / n
sd[i]    = sqrt( sum over the same window of (p[j] - mid[i])^2 / n )   # ddof = 0
lower[i] = mid[i] - w * sd[i]
upper[i] = mid[i] + w * sd[i]
```

First value at `i = n-1` (19); before that, NULL.

First values on the vector above: `lower[19] = 93.1819583622`,
`mid[19] = 106.2729250000`, `upper[19] = 119.3638916378`.

**The live question is `ddof`.** The population deviation divides by `n`; the sample
deviation divides by `n-1` and is `sqrt(20/19) = 1.0260` times larger — 2.6% further
from the centre, which on this vector is up to **0.61 of a price point**. Bollinger's
definition and the library's default are both the population deviation, and `ddof=0` is
passed explicitly anyway, because a default is a fact about a version.

Measured agreement: **3e-14**.

**Degenerate cases.** A window with no variance gives `sd = 0` and three coincident
lines at the mean. That is a correct reading of a motionless market, not an absence, and
is stored as three equal numbers.

---

## ATR — Wilder (1978), *New Concepts in Technical Trading Systems*

True range, then Wilder's smoothing of it. For period `n` (14), over highs `h`, lows `l`
and closes `p`:

```
tr[0] = undefined                                    # there is no previous close
tr[i] = max( h[i] - l[i],
             |h[i] - p[i-1]|,
             |l[i] - p[i-1]| )                       for i = 1..N

atr[n] = (tr[1] + ... + tr[n]) / n                   # seed: a simple mean of the first n
atr[i] = (atr[i-1]*(n-1) + tr[i]) / n                for i > n
```

**The first ATR lands at index `n`, the same place as the first RSI**, and for the same
structural reason rather than by coincidence: neither a change nor a true range exists
without a previous bar, so both series of differences begin at index 1, and both seeds
average `n` of them. An implementation that puts either at `n-1` has dropped a bar.

First values on the vector above: `tr[1] = 5.3913000000`, `atr[14] = 3.5940785714`.

**The live question is the seed, again, and the library's name for the smoothing is a
trap.** `pandas-ta-classic` calls it `rma`, which reads as `ewm(alpha=1/n, adjust=False)`
seeded on the first observation. It is not: measured, it is the mean-of-the-first-`n`
seed above. The `ewm` reading differs by up to **0.59** on this vector. The library also
offers `mamode='ema'` (3.6706 at bar 15 against Wilder's 3.6351) and `mamode='sma'`
(3.5067), so `mamode='rma'` is passed explicitly.

Measured agreement: **9e-16**.

**Degenerate cases.** There is no division by anything the data supplies — true range is
a maximum of three differences, and Wilder's smoothing divides by the constant `n`. A
security that did not move has an ATR of **zero, and that zero is a measurement**: the
average true range of a flat market really is nothing. It is stored, not nulled.

One wrinkle worth knowing before someone spots it in the data: `pandas-ta-classic`
returns `2.220446e-16` rather than `0.0` there, because its true range adds a float
epsilon to `high - low` so that the percentage variant — which this project does not
compute — cannot divide by zero. Immaterial at any price, but it is why a dead
security's stored ATR is a denormal rather than a round zero.

**High and low are read straight off `AdjustedBars`.** They have already been scaled by
the same split factor as the close. Re-adjusting them would put a cliff in the true
range on the ex-date, which is the 🔴 FRAGILE failure of `docs/03` P6 wearing a hat.

---

## OBV — Granville (1963), *Granville's New Key to Stock Market Profits*

```
obv[0] = v[0]
obv[i] = obv[i-1] + v[i]     if p[i] >  p[i-1]
       = obv[i-1] - v[i]     if p[i] <  p[i-1]
       = obv[i-1]            if p[i] == p[i-1]
```

No warm-up: the first bar carries a value, and every bar after it does too.

First values on the vector above: `1,000,000  2,100,000  3,300,000  4,325,000`.

**Two live questions, both about edges rather than smoothing.**

*The seed.* Granville's original starts from an arbitrary figure, and implementations
split between `0` and `+v[0]`. `pandas-ta-classic` uses `+v[0]`, so the whole series
sits one bar's volume above a zero-seeded one. OBV is read in differences and slopes, so
an additive constant changes nothing anyone asks of it — but a level from here is not
comparable with a level from a differently-seeded library, and somebody reconciling the
two will otherwise conclude one of them is broken.

*The unchanged close.* Three states, not two. An unchanged close adds **nothing**; an
implementation that treats `>=` as "up" quietly loads every flat day into the total, and
on a thin listing that is most of them. Measured: on closes `100, 100, 101, 101, 100`
with volumes `10, 20, 30, 40, 50`, the series is `10, 10, 40, 40, -10`.

Measured agreement: **exact**.

**Volume is already adjusted, in the other direction.** `adjusted_bars` *divides* volume
by the split factor where it *multiplies* prices by it — a 4-for-1 split takes the price
to a quarter and the share count to four times. Re-applying the price factor to quantity
would put a step in the running total that nobody traded. Read `bars.volume` as it comes.

**Degenerate cases.** No division anywhere. The one edge is a missing volume: pandas'
`cumsum` skips NaN, so the bar itself is NULL — correct — and the running total afterwards
continues *as if that bar had no volume at all*. Measured, on a rising series with
volumes `10, 20, NaN, 40, 50`: `10, 30, NULL, 70, 120`. The absence is recorded on the
bar; the level after it silently omits the bar. Nothing downstream should difference OBV
across a NULL.

---

## Stochastic oscillator — Lane (1950s), as `%K` and `%D`

For lookback `k` (14), `%K` smoothing `sk` (3) and `%D` smoothing `d` (3):

```
hh[i]  = max(h[i-k+1] .. h[i])                       for i >= k-1
ll[i]  = min(l[i-k+1] .. l[i])
raw[i] = 100 * (p[i] - ll[i]) / (hh[i] - ll[i])      undefined when hh[i] == ll[i]

K[i]   = (raw[i-sk+1] + ... + raw[i]) / sk           first value at i = k+sk-2  (15)
D[i]   = (K[i-d+1] + ... + K[i]) / d                 first value at i = k+sk+d-3 (17)
```

First values on the vector above: `K[15] = 18.9070264182`, `D[17] = 13.2072068653`.

**The live question is which of the three periods smooths what.** In
`pandas-ta-classic`, `k` is the lookback window, `smooth_k` is the moving average
applied to raw `%K`, and `d` is the moving average applied to that. The "fast"
stochastic is this with `smooth_k = 1`; the "slow" stochastic is what is written above.
Both smoothings are simple means (`mamode='sma'`, passed explicitly).

Measured agreement: **4e-14** on both columns.

### The degenerate case, and why the project does not take the library's answer

`hh[i] == ll[i]` — the high, the low and the close all equal, for `k` sessions running —
makes `raw[i]` a `0/0`. For a thin NGX listing this is not hypothetical.

`pandas-ta-classic` returns **0.0**. It does not choose that answer: it adds a float
epsilon to the denominator so nothing raises, and `0 / eps` is `0`. But `%K = 0` says
*the close sat at the very bottom of its range*, which is a measurement, about a market
that had no range. That is the zero-for-an-absence mistake arriving through the back
door, in a phase whose whole vocabulary exists to prevent it — so `_stoch` masks those
bars to NULL instead.

Two consequences, both load-bearing:

1. **The mask cannot be applied by value.** A `%K` of exactly `0.0` is an ordinary
   reading — the close at the low of a real range — and must survive. The test for it
   is a series that falls every day. So the mask is computed structurally, from
   `rolling(k).max(high) == rolling(k).min(low)`.
2. **It has to widen through both smoothings.** A `%K` that averaged an undefined raw
   value is undefined too, and so is a `%D` that averaged that `%K`: `sk` bars, then `d`
   more. It is a rolling OR over the degenerate flag, not a per-bar test. And it is not
   a latch — once the dead patch is `k` bars behind, values resume.

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

"""Technical indicators: computed, stored, and explicitly not signals.

`docs/03` P6.2 is emphatic, and so is `SPEC.md` 4.2: T9's acceptance is "computed +
stored", never "traded". `SPEC.md` 2C cites Park & Irwin (2007) - of 95 studies, 56
positive, but nearly all suffering "data snooping, ex post selection of trading rules"
and with simple-rule profitability in US equities largely gone after the early 1990s.

So the project's position, which this package exists to hold: **indicators are features
for a model that P7 will validate, never standalone signals.** Nothing here emits a buy,
a sell or a recommendation, and P6's exit criteria make that a hard gate rather than a
preference.
"""

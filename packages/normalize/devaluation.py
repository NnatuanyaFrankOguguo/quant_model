"""Saying out loud when a year-on-year comparison is mostly currency. P4.5.

`docs/03` P4.5 lists this among the things that *"are not edge cases, they are the normal
condition of Nigerian statements right now"*, and states the case it is written for:

    MTN Nigeria's net FX losses rose 24.98% to ₦925.36 billion (from ₦740.43 billion in
    2023) as the Naira fell from ₦907.1/$ to ₦1,535/$ by end-2024. Revenue rose 36% and the
    company still posted a ₦400.44 billion loss. **Capture FX loss as a distinct line item,
    and annotate that year-on-year comparisons are distorted by devaluation** - otherwise
    every growth metric you compute for Nigerian companies over this period is misleading
    without being wrong.

*Misleading without being wrong* is the whole problem. Nothing here is a data error. The
statements are right, the arithmetic is right, and "revenue up 36%" is a true sentence that
leaves a reader with a false impression, because over the same year the unit it is measured
in lost two fifths of its value. A validation rule cannot catch that: there is nothing to
catch. The only fix is to say it.

## The two numbers, and why both are reported

A single "the naira moved 70%" is ambiguous enough to be useless, because two different
true figures describe one move:

- **`nominal_inflation`** - `later / earlier - 1` on the price of a reference unit. The
  naira price of a dollar went 899.393 to 1535.3176 over FY2024, so `nominal_inflation` is
  +70.7%: *a figure unchanged in dollars appears 70.7% larger in naira.* This is the one
  that contaminates a growth rate, so it is the one the materiality test uses.
- **`presentation_loss`** - `earlier / later - 1`. The same move, read as what the naira
  lost: 41.4%. This is the one a reader recognises as "the naira fell by".

(Those two rates are the stored CBN series at each year end. `docs/03` P4.5 and
`tests/unit/test_devaluation.py` quote 907.1 and 1,535.0 instead, which is the same episode
rounded differently and gives +69.2% and 40.9%. Nothing depends on which pair is used; the
figures differ in the second digit and are noted here only so a reader comparing the two
does not go looking for a bug.)

They are not each other's negative and confusing them is how a plausible wrong number gets
written down. Both are computed, both are named for what they mean, and the sentence in
`note` uses each where it belongs.

## Absence of a rate is not absence of distortion

The status is three-valued on purpose. `UNKNOWN` means no rate could be found for one of
the dates, which is a different fact from `NOT_DISTORTED`, and collapsing the two would
publish "comparable" about a period nobody checked. Same distinction as `not_in_filing`
versus `no_mapping` elsewhere in this package: absence the world caused, against absence we
caused.

## What this is not

It is not an adjustment. `docs/03` P4.5 is explicit in the next paragraph that IAS 29
hyperinflation accounting is **not** triggered - the FRC ruled so in January 2025 and
reaffirmed it for FY2025 - so statements stay at historical cost and an inflation-adjusted
view is only ever a user-selectable overlay, clearly labelled as our computation. This
module changes no stored figure. It attaches a sentence.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from decimal import Decimal, localcontext

from sqlalchemy.orm import Session

from packages.common.fx import (
    DEFAULT_MAX_STALENESS_DAYS,
    NFEM_OFFICIAL,
    FxRateRef,
    rate_on,
)

__all__ = [
    "DISTORTED",
    "MATERIAL_NOMINAL_INFLATION",
    "NOT_DISTORTED",
    "UNKNOWN",
    "Devaluation",
    "devaluation_between",
]

#: The comparison carries a currency component large enough to change its story.
DISTORTED = "distorted"
#: Rates were found for both dates and the move between them was not material.
NOT_DISTORTED = "not_distorted"
#: No rate for one of the dates. Not the same as "no distortion" - see the module docstring.
UNKNOWN = "unknown"

#: A chosen threshold, and worth naming as a choice rather than a discovery.
#:
#: Ten per cent, on `nominal_inflation`. The reasoning: a growth figure a reader would call
#: healthy is single-digit to low-double-digit, so once the currency alone contributes ten
#: points the currency is a first-order term in the comparison rather than a footnote to it.
#: Below that it is a rounding argument; at and above it, quoting the growth rate without
#: the currency move leaves the reader with the wrong impression.
#:
#: It is deliberately not tuned to the Nigerian float. That episode is far past any
#: plausible threshold - FY2024 alone is +70.7% - and a number picked to catch it would be
#: uselessly loose for the ordinary years on either side.
MATERIAL_NOMINAL_INFLATION = Decimal("0.10")

#: Places kept on the two ratios. Enough that a reader can reproduce them from the rates
#: printed alongside; not so many as to imply the underlying rates are that precise.
_PLACES = Decimal("0.000001")


@dataclass(frozen=True)
class Devaluation:
    """What the currency did between two period ends, and whether it matters.

    `reason` is populated in every case, including the uninteresting ones. A caller that
    logs or displays this should never have to reconstruct why it said what it said.
    """

    status: str
    presentation: str
    reference: str
    earlier_period_end: dt.date
    later_period_end: dt.date
    #: `None` only when `status` is `UNKNOWN`.
    earlier_rate: FxRateRef | None
    later_rate: FxRateRef | None
    #: How much larger a figure unchanged in `reference` appears in `presentation`.
    nominal_inflation: Decimal | None
    #: How much of its `reference` value one `presentation` unit lost. Not the negative of
    #: `nominal_inflation` - see the module docstring.
    presentation_loss: Decimal | None
    reason: str

    @property
    def is_distorted(self) -> bool:
        """True only for `DISTORTED`. `UNKNOWN` is not a quiet yes and not a quiet no."""
        return self.status == DISTORTED

    @property
    def note(self) -> str:
        """The sentence P4.5 asks for, ready to attach to a comparison.

        Written to be read by somebody who is about to quote a growth rate, so it leads
        with the consequence rather than the exchange rate.
        """
        if self.status == UNKNOWN:
            return (
                f"Comparability against {self.reference} could not be checked for "
                f"{self.earlier_period_end} to {self.later_period_end}: {self.reason}. "
                f"This is not a statement that the comparison is sound."
            )
        assert self.nominal_inflation is not None  # noqa: S101 - narrowing; both are set together
        assert self.presentation_loss is not None  # noqa: S101
        if self.status == NOT_DISTORTED:
            return (
                f"{self.presentation} moved {abs(self.presentation_loss):.1%} against "
                f"{self.reference} between {self.earlier_period_end} and "
                f"{self.later_period_end}, below the {MATERIAL_NOMINAL_INFLATION:.0%} "
                f"threshold, so growth figures are not dominated by currency."
            )
        direction = "weakened" if self.nominal_inflation > 0 else "strengthened"
        return (
            f"Year-on-year comparisons between {self.earlier_period_end} and "
            f"{self.later_period_end} are distorted by currency: {self.presentation} "
            f"{direction} {abs(self.presentation_loss):.1%} against {self.reference}, so a "
            f"figure unchanged in {self.reference} appears "
            f"{self.nominal_inflation:+.1%} in {self.presentation}. Growth rates over this "
            f"period mix real change with currency movement and should not be quoted alone."
        )


def devaluation_between(
    session: Session,
    *,
    presentation: str,
    earlier_period_end: dt.date,
    later_period_end: dt.date,
    decision_date: dt.date,
    reference: str = "USD",
    rate_type: str = NFEM_OFFICIAL,
    max_staleness_days: int = DEFAULT_MAX_STALENESS_DAYS,
) -> Devaluation:
    """Whether a comparison between these two period ends is mostly currency.

    `decision_date` is required and has no default, for the same reason `rate_on` refuses
    one: the answer depends on which vintage of the rate was knowable, and a caller that
    has not thought about that is asking a question it does not mean.

    Raises `ValueError` if the periods are not in order. That is not a data condition to
    report - it is a caller that has swapped its arguments, and the two ratios would come
    back inverted and perfectly plausible, which is the worst way for it to be wrong.
    """
    presentation, reference = presentation.upper(), reference.upper()
    if later_period_end <= earlier_period_end:
        raise ValueError(
            f"earlier_period_end ({earlier_period_end}) must fall before later_period_end "
            f"({later_period_end}). Swapped, this returns an inverted move that reads as a "
            f"strengthening currency and is impossible to spot downstream."
        )
    if presentation == reference:
        return Devaluation(
            status=NOT_DISTORTED,
            presentation=presentation,
            reference=reference,
            earlier_period_end=earlier_period_end,
            later_period_end=later_period_end,
            earlier_rate=None,
            later_rate=None,
            nominal_inflation=Decimal(0),
            presentation_loss=Decimal(0),
            reason=(
                f"statements are presented in {presentation}, which is the reference "
                f"currency, so there is no translation to distort them"
            ),
        )

    # Priced as `presentation` units per one `reference` unit - naira per dollar - because
    # that is the direction a reader recognises and the direction `nominal_inflation` falls
    # out of without an inversion.
    earlier = rate_on(
        session,
        base=reference,
        quote=presentation,
        on=earlier_period_end,
        decision_date=decision_date,
        rate_type=rate_type,
        max_staleness_days=max_staleness_days,
    )
    later = rate_on(
        session,
        base=reference,
        quote=presentation,
        on=later_period_end,
        decision_date=decision_date,
        rate_type=rate_type,
        max_staleness_days=max_staleness_days,
    )
    missing = [
        str(period)
        for period, found in ((earlier_period_end, earlier), (later_period_end, later))
        if found is None
    ]
    if missing:
        return _unknown(
            presentation,
            reference,
            earlier_period_end,
            later_period_end,
            reason=(
                f"no {reference}/{presentation} {rate_type} rate within "
                f"{max_staleness_days} days of {' or '.join(missing)}"
            ),
        )
    assert earlier is not None and later is not None  # noqa: S101 - `missing` proved it
    if earlier.rate <= 0 or later.rate <= 0:
        # Unreachable through the CBN connector, which refuses non-positive rates on the
        # way in. Reported rather than divided by, because a zero here would raise deep in
        # a comparison and name neither the currency nor the date.
        return _unknown(
            presentation,
            reference,
            earlier_period_end,
            later_period_end,
            reason=(
                f"a stored {reference}/{presentation} rate is not positive "
                f"({earlier.rate} on {earlier.as_of_date}, {later.rate} on "
                f"{later.as_of_date}); a rate of zero is not a price"
            ),
        )

    with localcontext() as context:
        context.prec = 34
        nominal_inflation = (later.rate / earlier.rate - 1).quantize(_PLACES)
        presentation_loss = (earlier.rate / later.rate - 1).quantize(_PLACES)

    distorted = abs(nominal_inflation) >= MATERIAL_NOMINAL_INFLATION
    carried = max(earlier.age_days, later.age_days)
    reason = (
        f"{reference}/{presentation} {rate_type} went {earlier.rate} on "
        f"{earlier.as_of_date} to {later.rate} on {later.as_of_date}"
    )
    if carried:
        # A rate carried over a closed week is still the rate, and a reader deciding how
        # much to lean on a borderline call should be told how far it was carried.
        reason += f"; the further of the two was carried {carried} day(s) to reach its date"
    return Devaluation(
        status=DISTORTED if distorted else NOT_DISTORTED,
        presentation=presentation,
        reference=reference,
        earlier_period_end=earlier_period_end,
        later_period_end=later_period_end,
        earlier_rate=earlier,
        later_rate=later,
        nominal_inflation=nominal_inflation,
        presentation_loss=presentation_loss,
        reason=reason,
    )


def _unknown(
    presentation: str,
    reference: str,
    earlier_period_end: dt.date,
    later_period_end: dt.date,
    *,
    reason: str,
) -> Devaluation:
    """An honest "cannot tell", with the ratios left as `None` rather than zero.

    Zero would be a number, and a caller that forgot to check `status` would read it as
    "the currency did not move" - which is exactly the false reassurance this whole module
    exists to prevent.
    """
    return Devaluation(
        status=UNKNOWN,
        presentation=presentation,
        reference=reference,
        earlier_period_end=earlier_period_end,
        later_period_end=later_period_end,
        earlier_rate=None,
        later_rate=None,
        nominal_inflation=None,
        presentation_loss=None,
        reason=reason,
    )

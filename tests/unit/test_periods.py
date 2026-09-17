"""P3 exit check 8: a June and a December year-end are flagged as non-comparable.

`docs/03` P3, check 8: *"Compare a June and a December year-end | Flagged as
non-comparable"*. `OPERATIONS.md` §1.5 gives the rule it is checking:

    cross-company comparisons align on `period_end` within a tolerance window (default
    ±92 days), never on fiscal-year label. Any comps table or screen displays each company's
    actual `period_end` next to its figure, and flags when the spread across the comparison
    set exceeds the window. Never silently align `FY2024` to `FY2024`.

`statements` already carries `fiscal_year`, `calendar_year` and `period_label` — §1.5's
`ALTER TABLE` landed in migration `0011`. What was missing was the rule those columns exist
to serve: nothing anywhere turned two year-ends nine months apart into a refusal, so the
check had no code to run against.

**There is no comps table or screen yet** — searching `services/` and `apps/` for one finds
only prose. So this is the rule built before its consumer, on purpose: a screen written
without it would silently compare Guinness's June year to Nestlé's December one, and that is
the failure §1.5 opens by describing. When the screen arrives it calls this and prints
`reason` beside the figures.
"""

from __future__ import annotations

import datetime as dt

import pytest

from packages.normalize.periods import (
    COMPARISON_WINDOW_DAYS,
    comparability_of,
)

pytestmark = pytest.mark.invariant

#: Three real fiscal-year ends from `docs/UNIVERSE.md`, all labelled FY2025 by their issuers.
GUINNESS_FY2025 = dt.date(2025, 6, 30)  # Guinness Nigeria: June year-end
NESTLE_FY2025 = dt.date(2025, 12, 31)  # Nestlé Nigeria: December
AIRTEL_FY2025 = dt.date(2025, 3, 31)  # Airtel Africa: March


# --------------------------------------------------------------------------------------
# Check 8, stated
# --------------------------------------------------------------------------------------


def test_a_june_and_a_december_year_end_are_not_comparable() -> None:
    """The check `docs/03` names, on two real companies from the universe.

    Guinness Nigeria closes in June and Nestlé Nigeria in December. Both file an "FY2025",
    and the two periods end 184 days apart. §1.5: during a currency collapse that compares
    two different economies, not two companies.
    """
    verdict = comparability_of([GUINNESS_FY2025, NESTLE_FY2025])
    assert not verdict.comparable
    assert verdict.spread_days == 184
    assert "not comparable" in verdict.reason
    assert "184 days" in verdict.reason, "the reason must state the spread it measured"


def test_the_same_fiscal_year_label_does_not_make_two_periods_comparable() -> None:
    """§1.5: *"Never silently align `FY2024` to `FY2024`."*

    This is the clause the rule exists for. Both companies call it FY2025, so any code that
    grouped on the label would put them in one row of a comps table and show a like-for-like
    comparison that is nothing of the kind. The function takes period ends and not labels
    precisely so that a caller cannot make that mistake by passing the wrong argument.
    """
    same_label = comparability_of([GUINNESS_FY2025, NESTLE_FY2025, AIRTEL_FY2025])
    assert not same_label.comparable
    assert same_label.spread_days == 275, "March to December, all three labelled FY2025"


def test_two_year_ends_a_quarter_apart_still_compare() -> None:
    """A December and a March filer are 90 days apart, inside the window, and do compare.

    The rule is a tolerance, not a demand for identical dates. If it refused everything but
    an exact match, three of the twenty-five names in the universe could never be screened
    against the rest and the rule would be abandoned the first time it was inconvenient.
    """
    verdict = comparability_of([dt.date(2024, 12, 31), dt.date(2025, 3, 31)])
    assert verdict.comparable
    assert verdict.spread_days == 90
    assert "within the 92-day window" in verdict.reason


# --------------------------------------------------------------------------------------
# The window, and where it falls
# --------------------------------------------------------------------------------------


def test_the_default_window_is_the_one_operations_specifies() -> None:
    assert COMPARISON_WINDOW_DAYS == 92, "OPERATIONS §1.5: default ±92 days"


@pytest.mark.parametrize(
    ("spread", "comparable"),
    [(0, True), (91, True), (92, True), (93, False), (184, False)],
)
def test_the_boundary_is_inclusive(spread: int, comparable: bool) -> None:
    """ "Within ±92 days" includes 92. Off by one here silently drops a whole filer cohort."""
    start = dt.date(2025, 1, 31)
    verdict = comparability_of([start, start + dt.timedelta(days=spread)])
    assert verdict.comparable is comparable
    assert verdict.spread_days == spread


def test_a_caller_may_tighten_or_widen_the_window() -> None:
    """The 92 days is a default, not a constant of nature — §1.5 calls it "default"."""
    pair = [dt.date(2025, 1, 31), dt.date(2025, 3, 31)]  # 59 days
    assert comparability_of(pair, window_days=60).comparable
    assert not comparability_of(pair, window_days=30).comparable
    assert comparability_of(pair, window_days=0).spread_days == 59, "0 compares only identical"
    with pytest.raises(ValueError, match="must not be negative"):
        comparability_of(pair, window_days=-1)


# --------------------------------------------------------------------------------------
# It is the set that gets displayed, so it is the set that is measured
# --------------------------------------------------------------------------------------


def test_the_spread_is_the_width_of_the_whole_set_not_a_pairwise_distance() -> None:
    """Adding a fourth company can break a comparison in which no single pair is far apart.

    Four period ends 60 days apart in sequence: every neighbouring pair is comfortably
    inside the window, and the set spans 180 days. A pairwise check would call this fine and
    a reader would compare the first company against the last.
    """
    start = dt.date(2025, 1, 31)
    ends = [start + dt.timedelta(days=60 * step) for step in range(4)]
    # strict=False on purpose: pairing neighbours means the second list is one shorter.
    for earlier, later in zip(ends, ends[1:], strict=False):
        assert comparability_of([earlier, later]).comparable, "each neighbouring pair is fine"
    whole_set = comparability_of(ends)
    assert not whole_set.comparable
    assert whole_set.spread_days == 180


def test_one_period_is_trivially_comparable_and_says_so() -> None:
    """A single company is not a comparison, and must not be reported as a passed check."""
    verdict = comparability_of([NESTLE_FY2025])
    assert verdict.comparable and verdict.spread_days == 0
    assert "nothing to align" in verdict.reason


def test_an_empty_comparison_set_is_refused() -> None:
    """Returning "comparable" for nothing would be a quiet lie in exactly the wrong direction."""
    with pytest.raises(ValueError, match="at least one period end"):
        comparability_of([])


def test_the_order_the_periods_arrive_in_does_not_matter() -> None:
    """A screen builds its set in whatever order its query returned."""
    forwards = comparability_of([AIRTEL_FY2025, GUINNESS_FY2025, NESTLE_FY2025])
    backwards = comparability_of([NESTLE_FY2025, GUINNESS_FY2025, AIRTEL_FY2025])
    assert forwards == backwards
    assert forwards.period_ends == (AIRTEL_FY2025, GUINNESS_FY2025, NESTLE_FY2025)


def test_duplicate_period_ends_are_kept_rather_than_collapsed() -> None:
    """Twenty December filers are twenty rows of a comps table, and the count is displayed."""
    verdict = comparability_of([NESTLE_FY2025] * 3)
    assert verdict.period_ends == (NESTLE_FY2025,) * 3
    assert verdict.comparable and verdict.spread_days == 0
    assert "3 periods" in verdict.reason


def test_the_reason_always_names_the_dates_it_measured() -> None:
    """§1.5 requires the screen to show each actual `period_end`, so the verdict carries them.

    A bare boolean would leave a UI printing "not comparable" with nothing a reader could
    check, which is how a correct refusal gets dismissed as a bug.
    """
    for ends in ([NESTLE_FY2025], [GUINNESS_FY2025, NESTLE_FY2025]):
        verdict = comparability_of(ends)
        assert verdict.reason
        assert str(min(ends)) in verdict.reason
        assert verdict.window_days == COMPARISON_WINDOW_DAYS

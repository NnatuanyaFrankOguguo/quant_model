"""What period a fact describes: fiscal year and period type from the dates alone.

**The trap this module exists for.** EDGAR's companyfacts carries `fy` and `fp` on every fact,
and they describe the *filing* the fact appeared in, not the fact's own period. Apple's
FY2024 revenue appears twice: once in the FY2024 10-K with `fy: 2024, fp: FY`, and again as a
comparative in the FY2025 10-K with `fy: 2025, fp: FY`. Read `fy` as the period's year and
every comparative is filed under the wrong year. So the fiscal year and the period type are
derived from `start`/`end` and the company's fiscal-year-end month, and `fy`/`fp` are kept
only as the reporting context they are.

**52/53-week years.** Apple's year ends on the last Saturday of September — 2024-09-28,
2025-09-27 — and a 53-week year can spill a few days into the next month. A period end in
the first week of a month is therefore anchored back into the month it belongs to before
its month is read. `docs/08` §1.3 and `OPERATIONS.md` §1.5 on fiscal alignment.
"""

from __future__ import annotations

import calendar
import datetime as dt
from collections.abc import Iterable
from dataclasses import dataclass

__all__ = [
    "COMPARISON_WINDOW_DAYS",
    "Comparability",
    "ExpectedFiling",
    "comparability_of",
    "fiscal_year_of",
    "next_expected_filing",
    "period_label",
    "period_type_of",
    "quarter_of",
]

#: A period end within this many days of a month's start belongs to the previous month.
_SPILLOVER_DAYS = 7

#: Duration windows, inclusive, in days. Quarters are 13 weeks; years 52 or 53 weeks.
_QUARTER = (80, 100)
_HALF = (170, 195)
_NINE_MONTHS = (260, 290)
_YEAR = (350, 380)


#: The SEC's *longest* deadlines, in days after the period end: 90 for a 10-K and 45 for
#: a 10-Q, which are the non-accelerated filer's. Large accelerated filers have 60 and 40,
#: but the filer category is not stored, so the longest is used: a company is called overdue
#: only when every category of filer would be. Extensions (Form 12b-25) are not modelled.
FORM_10K_DEADLINE_DAYS = 90
FORM_10Q_DEADLINE_DAYS = 45


@dataclass(frozen=True)
class ExpectedFiling:
    """The next periodic report after the newest period held, and the last day it may be filed."""

    period_end: dt.date  # the last day of the fiscal quarter's month - a 52/53-week filer's
    form: str  # actual date is within a week of it, which the deadline's slack absorbs
    due_by: dt.date


def next_expected_filing(last_period_end: dt.date, fye_month: int) -> ExpectedFiling:
    """What should come next, from the newest period held and the fiscal year end alone.

    After a Q3 the next report is the 10-K; after anything else, a 10-Q. The expected period
    end is the month end three fiscal months on. This is an operational freshness signal
    (`docs/05` §11, Q12 and Q22) - "is a report due that we do not hold?" - and it says
    nothing about the figures: it is never written to a figure table.
    """
    anchor = _anchor(last_period_end)
    month, year = anchor.month + 3, anchor.year
    if month > 12:
        month, year = month - 12, year + 1
    period_end = dt.date(year, month, calendar.monthrange(year, month)[1])
    form = "10-K" if quarter_of(last_period_end, fye_month) == 3 else "10-Q"
    days = FORM_10K_DEADLINE_DAYS if form == "10-K" else FORM_10Q_DEADLINE_DAYS
    return ExpectedFiling(period_end=period_end, form=form, due_by=period_end + dt.timedelta(days))


def _anchor(end: dt.date) -> dt.date:
    """The date whose month names the fiscal month this period end belongs to."""
    if end.day <= _SPILLOVER_DAYS:
        return end - dt.timedelta(days=_SPILLOVER_DAYS)
    return end


def quarter_of(end: dt.date, fye_month: int) -> int:
    """1–4: which fiscal quarter ends at `end`, for a year ending in `fye_month`.

    Apple (September year end): a December quarter end is Q1, March Q2, June Q3, September
    Q4. Walmart (January): April is Q1.
    """
    if not 1 <= fye_month <= 12:
        raise ValueError(f"fiscal year-end month must be 1-12, not {fye_month}")
    months_into_year = ((_anchor(end).month - fye_month - 1) % 12) + 1
    return (months_into_year + 2) // 3


def fiscal_year_of(end: dt.date, fye_month: int) -> int:
    """The fiscal year a period ending at `end` belongs to, by the company's convention.

    A year is named for the calendar year in which it ends: Apple's year ending 2024-09-28
    is FY2024; Walmart's year ending 2025-01-31 is fiscal 2025, and its quarter ending
    2025-04-30 is Q1 of fiscal 2026.
    """
    if not 1 <= fye_month <= 12:
        raise ValueError(f"fiscal year-end month must be 1-12, not {fye_month}")
    anchor = _anchor(end)
    return anchor.year if anchor.month <= fye_month else anchor.year + 1


def period_type_of(start: dt.date | None, end: dt.date, fye_month: int) -> str | None:
    """`'FY'|'Q1'|'Q2'|'Q3'|'H1'|'YTD'`, or None for a duration this vocabulary has no word for.

    An instant (no `start`) is a balance-sheet date: `FY` at the year end, otherwise the
    quarter it closes. A duration is typed by its length — a 13-week span is the quarter it
    ends in (`Q4` at the year end, which a 10-K does not normally file as its own duration,
    but which must never be mistaken for the twelve-month `FY` figure), 26 weeks ending at
    the half is `H1`, 39 weeks is `YTD`, 52/53 weeks is `FY`.

    None means "do not store this": a transition period after a year-end change, or a
    cumulative span that is none of the above. Refusing is the honest response to a period
    the schema's vocabulary cannot name.
    """
    quarter = quarter_of(end, fye_month)
    if start is None:
        return "FY" if quarter == 4 else f"Q{quarter}"
    days = (end - start).days + 1
    if _YEAR[0] <= days <= _YEAR[1]:
        return "FY" if quarter == 4 else None
    if _QUARTER[0] <= days <= _QUARTER[1]:
        return f"Q{quarter}"
    if _HALF[0] <= days <= _HALF[1]:
        return "H1" if quarter == 2 else None
    if _NINE_MONTHS[0] <= days <= _NINE_MONTHS[1]:
        return "YTD" if quarter == 3 else None
    return None


def period_label(period_type: str, fiscal_year: int) -> str:
    """`FY2025`, `Q1-FY2026`, `H1-FY2026`, `9M-FY2026` — the company's own convention."""
    if period_type == "FY":
        return f"FY{fiscal_year}"
    if period_type == "YTD":
        return f"9M-FY{fiscal_year}"
    return f"{period_type}-FY{fiscal_year}"


#: `OPERATIONS.md` §1.5's default tolerance window, in days: *"cross-company comparisons
#: align on `period_end` within a tolerance window (default ±92 days), never on
#: fiscal-year label."* 92 days is a quarter, so two companies a quarter apart still compare
#: and two companies half a year apart do not.
COMPARISON_WINDOW_DAYS = 92


@dataclass(frozen=True)
class Comparability:
    """Whether a set of period ends may be put in one comps table, and by how much it misses.

    `spread_days` is the full width of the set, earliest to latest - not a pairwise distance.
    A screen adding a fourth company to three comparable ones can widen the spread past the
    window without any single pair being far apart, and it is the set that gets displayed.
    """

    period_ends: tuple[dt.date, ...]
    spread_days: int
    window_days: int
    comparable: bool
    #: Plain words for a UI to print beside the figures. Never empty.
    reason: str


def comparability_of(
    period_ends: Iterable[dt.date], *, window_days: int = COMPARISON_WINDOW_DAYS
) -> Comparability:
    """`OPERATIONS.md` §1.5's rule, as a function. `docs/03` P3 check 8.

    The rule: *"cross-company comparisons align on `period_end` within a tolerance window
    (default ±92 days), never on fiscal-year label. Any comps table or screen displays each
    company's actual `period_end` next to its figure, and flags when the spread across the
    comparison set exceeds the window. Never silently align `FY2024` to `FY2024`."*

    **Why the label is not enough.** Guinness Nigeria's year ends in June and Nestlé
    Nigeria's in December, so both file an "FY2025" whose periods end 184 days apart. During
    a currency collapse that is not a like-for-like comparison of two companies; it is a
    comparison of two different economies, and the naira moved far enough between mid-2023
    and end-2024 for the difference to swamp anything the ratio was meant to show. Three of
    the twenty-five names in `docs/UNIVERSE.md` are off-December - Airtel Africa and Flour
    Mills in March, Guinness in June - so this is the ordinary case, not the exotic one.

    Takes period ends rather than statements or securities so that it stays pure and the
    caller cannot accidentally pass a fiscal-year label. Raises on an empty set: comparing
    nothing is a caller bug, and returning "comparable" for it would be a quiet lie.
    """
    ends = tuple(sorted(period_ends))
    if not ends:
        raise ValueError("a comparison set needs at least one period end")
    if window_days < 0:
        raise ValueError(f"window_days must not be negative, got {window_days}")

    spread = (ends[-1] - ends[0]).days
    comparable = spread <= window_days
    if len(ends) == 1:
        reason = f"one period, ending {ends[0]}: nothing to align"
    elif comparable:
        reason = (
            f"{len(ends)} periods spanning {spread} days, from {ends[0]} to {ends[-1]}, "
            f"within the {window_days}-day window"
        )
    else:
        reason = (
            f"{len(ends)} periods spanning {spread} days, from {ends[0]} to {ends[-1]}, "
            f"which exceeds the {window_days}-day window by {spread - window_days} days - "
            f"not comparable"
        )
    return Comparability(
        period_ends=ends,
        spread_days=spread,
        window_days=window_days,
        comparable=comparable,
        reason=reason,
    )

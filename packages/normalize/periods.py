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

import datetime as dt

__all__ = ["fiscal_year_of", "period_label", "period_type_of", "quarter_of"]

#: A period end within this many days of a month's start belongs to the previous month.
_SPILLOVER_DAYS = 7

#: Duration windows, inclusive, in days. Quarters are 13 weeks; years 52 or 53 weeks.
_QUARTER = (80, 100)
_HALF = (170, 195)
_NINE_MONTHS = (260, 290)
_YEAR = (350, 380)


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

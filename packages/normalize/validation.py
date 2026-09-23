"""Arithmetic identities a correct set of statements must satisfy. P4.3.

`docs/03` P4.3 calls this *"what makes the LLM's output trustworthy, and the part that
separates a working pipeline from a plausible one"*, and lists the identities
(`DATA_FOUNDATION.md` §3.2):

* `total_assets == total_liabilities + total_equity`, within tolerance
* cash flow: `opening + net change == closing`
* cross-statement: profit after tax ties between the income statement and the cash flow
* cross-year: this year's opening balances equal last year's closing balances
* sign and unit sanity: revenue positive; flag year-on-year swings above ~5x

**It is built before the extractor on purpose.** These checks need no LLM, no API key and no
Nigerian PDF - only figures - so they can be written and proven now against the 53,710 line
items already stored, and be waiting when the extractor arrives. Running it over that data
found a real defect on the first pass; see below.

## What a failure means, and what it does not

A failed identity is **not** proof the extractor erred. It is proof that the figures as
stored do not hold together, which can be an extraction error, a chart mapping that means
something narrower than the identity assumes, or the filer's own mistake. So a result carries
the arithmetic rather than a verdict, and `needs_review` is a routing decision, not a
judgement about whose fault it is.

**The Bank of America case, which is why that distinction is in the first paragraph.** Our
FY2008 balance sheet for BAC stores `total_assets = 0` against liabilities of $1.64tn. The
figure is not an extraction error: Bank of America's own FY2010 10-K tags `Assets` as `0` for
the 2008-12-31 instant, while its FY2009 filings report $1,817,943,000,000 - which is exactly
liabilities plus equity. The filer published a zero, the newest-vintage rule imported it over
the correct earlier figure, and nothing in the pipeline noticed until this module ran. One
identity catches it in one line.

## Three outcomes, not two

`not_checkable` is separate from `failed` and the distinction is the usual one: an identity
whose inputs are absent has not been tested, and reporting that as a pass would inflate the
pass rate with checks nobody ran. Of 6,628 stored balance sheets only 940 carry all three
figures, so a validator that scored the rest as passing would be reporting mostly silence.

## Confidence

P4.3: *"Confidence = LLM self-report x validation pass rate x table quality. Below ~0.85 ->
review."* Only the middle term lives here; the other two arrive with the extractor. So this
module computes the pass rate and leaves the multiplication to its caller, rather than
inventing a self-report for figures no model produced.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from packages.common.models import Statement, StatementLineItem

__all__ = [
    "BALANCE_SHEET_BALANCES",
    "COMPOSITION_IDENTITIES",
    "CROSS_YEAR_SWING",
    "MUST_BE_POSITIVE",
    "SUBSET_RULES",
    "FAILED",
    "NOT_CHECKABLE",
    "PASSED",
    "PROFIT_TIES",
    "IdentityResult",
    "ValidationReport",
    "validate_period",
]

PASSED = "passed"
FAILED = "failed"
NOT_CHECKABLE = "not_checkable"

BALANCE_SHEET_BALANCES = "balance_sheet_balances"
PROFIT_TIES = "profit_ties_across_statements"
CROSS_YEAR_SWING = "cross_year_swing"

#: How far two figures may differ and still be called equal, as a fraction of the larger.
#: Statements are printed rounded - a balance sheet in millions rounds each line
#: independently, so a total can miss its parts by a few units without anything being wrong.
#: 0.1% is wide enough for that and far too narrow to admit a misread digit, let alone the
#: 1,000x error the unit check is for.
RELATIVE_TOLERANCE = Decimal("0.001")

#: Below this, relative tolerance is meaningless - 0.1% of zero is zero. Two figures within
#: one currency unit of each other are equal for every purpose this module has.
ABSOLUTE_TOLERANCE = Decimal(1)

#: `docs/03` P4.3: *"flag year-on-year swings above ~5x"*. A real business can quintuple; a
#: misplaced thousands multiplier always does.
#:
#: **Magnitudes are compared only when the sign is unchanged.** A unit error multiplies by a
#: thousand and keeps its sign; a business event is what flips it. The first version of this
#: check did not distinguish them, and flagged a company whose profit ran +33.4bn -> -2.7bn
#: -> +30.4bn as two magnitude errors. That is a loss year and a recovery, and a check that
#: cries wolf on every bad year is a check somebody switches off.
SWING_MULTIPLE = Decimal(5)

#: Keys the swing check watches. Stock and flow both, but only figures large and stable
#: enough that a 5x move is genuinely surprising rather than ordinary small-number noise.
SWING_KEYS: tuple[str, ...] = (
    "revenue",
    "total_assets",
    "total_equity",
    "total_liabilities",
)

#: **`profit_after_tax` is deliberately not in that list.** It was, and it produced every
#: false positive the check had on real data: six companies whose profit moved more than 5x
#: at an unchanged sign, all of them ordinary trading results. Profit is the most volatile
#: line on any statement and the least suited to a magnitude test.
#:
#: Nothing is lost by dropping it. A unit error is a property of a whole statement - if the
#: figures were read in thousands and stored as millions, *every* line moved together - so
#: the stable totals above catch it, and they catch it without a reviewer learning to ignore
#: the alert.
_EXCLUDED_FROM_SWING = ("profit_after_tax",)


# --------------------------------------------------------------------------------------
# States that cannot be true
#
# Everything above tests whether figures agree. What follows tests whether a figure is
# *possible at all*, which is a different and blunter question - and the one that caught
# Bank of America's zero. A disagreement can have an innocent explanation; a component
# larger than the total it belongs to cannot.
#
# These are declared as data rather than written as functions because the list is meant to
# grow. Every time a reviewer finds an impossible figure that got through, the fix is a line
# here, and the next occurrence is caught before anybody reads it.
# --------------------------------------------------------------------------------------

#: `(statement, minuend, subtrahend, result)` - exact arithmetic a statement must satisfy,
#: because the third line is *defined* as the first two combined. Not a tolerance question
#: about totals: if revenue less cost of sales does not equal gross profit, one of the three
#: is wrong, full stop.
COMPOSITION_IDENTITIES: tuple[tuple[str, str, str, str], ...] = (
    ("income", "revenue", "cost_of_revenue", "gross_profit"),
    ("income", "profit_before_tax", "income_tax", "profit_after_tax"),
    # A bank's net interest income is gross interest less interest paid, by definition.
    ("income", "interest_income", "interest_expense", "net_interest_income"),
)

#: `(part, whole, statement)` - a component that cannot exceed what contains it. Arithmetic,
#: not judgement: current assets are a subset of assets, and a figure that breaks this is
#: either mis-mapped, mis-scaled, or read off the wrong column.
SUBSET_RULES: tuple[tuple[str, str, str], ...] = (
    ("current_assets", "total_assets", "balance"),
    ("cash", "total_assets", "balance"),
    ("current_liabilities", "total_liabilities", "balance"),
    ("long_term_debt", "total_liabilities", "balance"),
    ("loans_and_advances_to_customers", "total_assets", "balance"),
    ("investment_securities_fvoci", "total_assets", "balance"),
    ("deposits_from_customers", "total_liabilities", "balance"),
    ("insurance_contract_liabilities", "total_liabilities", "balance"),
    ("gross_profit", "revenue", "income"),
    ("cost_of_revenue", "revenue", "income"),
)

#: `(statement, key)` - figures a going concern cannot report as zero or negative.
#:
#: `total_assets` is the one that matters and the one with a real case behind it. Bank of
#: America's FY2010 10-K tags `Assets` as 0 for the 2008-12-31 instant; a bank with $1.64tn
#: of liabilities and no assets is not a state of the world, it is a tagging error, and it
#: sat in this database unremarked until this check existed.
#:
#: `total_equity` is deliberately absent: equity genuinely can be negative, and often is
#: after years of buybacks - Boeing and McDonald's have both run there. Flagging it would be
#: flagging solvency, which is a reader's judgement and not an arithmetic fault.
MUST_BE_POSITIVE: tuple[tuple[str, str], ...] = (
    ("balance", "total_assets"),
    ("balance", "total_liabilities"),
    ("income", "revenue"),
)

#: Figures that cannot be negative, though zero is unremarkable.
MUST_NOT_BE_NEGATIVE: tuple[tuple[str, str], ...] = (
    ("balance", "cash"),
    ("balance", "current_assets"),
    ("balance", "loans_and_advances_to_customers"),
    ("balance", "deposits_from_customers"),
    ("income", "cost_of_revenue"),
)

#: A figure smaller than this is exempt from the swing check. A company whose profit goes
#: from 1 to 10 has multiplied by ten and told us nothing; the check is for magnitude errors
#: in material figures, and firing on rounding noise is how a check gets switched off.
SWING_FLOOR = Decimal(1_000_000)


@dataclass(frozen=True)
class IdentityResult:
    """One identity, its outcome, and the arithmetic behind it.

    `detail` is written to be read by whoever opens the review queue, so it states the sum
    rather than naming the rule and leaving them to reconstruct it.
    """

    name: str
    outcome: str
    detail: str
    expected: Decimal | None = None
    actual: Decimal | None = None

    @property
    def difference(self) -> Decimal | None:
        if self.expected is None or self.actual is None:
            return None
        return self.actual - self.expected


@dataclass
class ValidationReport:
    """Every identity for one company-period, and what the set of them implies."""

    company_id: int
    period_type: str
    period_end: dt.date
    results: list[IdentityResult] = field(default_factory=list)

    @property
    def checked(self) -> list[IdentityResult]:
        """The identities that had the figures they needed. The rest tested nothing."""
        return [r for r in self.results if r.outcome != NOT_CHECKABLE]

    @property
    def failures(self) -> list[IdentityResult]:
        return [r for r in self.results if r.outcome == FAILED]

    @property
    def pass_rate(self) -> Decimal | None:
        """Passed over checked, or None when nothing could be checked.

        None rather than 1.0, and rather than 0.0. A period whose figures are too sparse to
        test is not a period that passed, and it is not one that failed either - saying so
        keeps it out of a confidence score that would otherwise be built on nothing.
        """
        checked = self.checked
        if not checked:
            return None
        passed = sum(1 for r in checked if r.outcome == PASSED)
        return Decimal(passed) / Decimal(len(checked))

    @property
    def needs_review(self) -> bool:
        """Any failure routes the period to a human. P4.3: *"Any failure sets needs_review"*."""
        return bool(self.failures)


def _close_enough(left: Decimal, right: Decimal) -> bool:
    difference = abs(left - right)
    if difference <= ABSOLUTE_TOLERANCE:
        return True
    largest = max(abs(left), abs(right))
    return largest > 0 and difference / largest <= RELATIVE_TOLERANCE


def _figures(
    session: Session, *, company_id: int, period_type: str, period_end: dt.date
) -> dict[tuple[str, str], Decimal | None]:
    """(statement_type, canonical_key) -> value, for the current version of each statement.

    Keyed by statement type as well as key, because the cross-statement identity is about a
    figure appearing in two places and having to agree.
    """
    rows = session.execute(
        select(
            Statement.statement_type,
            StatementLineItem.canonical_key,
            StatementLineItem.value,
        )
        .join(StatementLineItem, StatementLineItem.statement_id == Statement.id)
        .where(Statement.company_id == company_id)
        .where(Statement.period_type == period_type)
        .where(Statement.period_end == period_end)
        .where(Statement.superseded_by.is_(None))
        .where(StatementLineItem.superseded_by.is_(None))
    ).all()
    return {(statement_type, key): value for statement_type, key, value in rows}


def _balance_sheet_balances(figures: dict[tuple[str, str], Decimal | None]) -> IdentityResult:
    assets = figures.get(("balance", "total_assets"))
    liabilities = figures.get(("balance", "total_liabilities"))
    equity = figures.get(("balance", "total_equity"))

    missing = [
        name
        for name, value in (
            ("total_assets", assets),
            ("total_liabilities", liabilities),
            ("total_equity", equity),
        )
        if value is None
    ]
    if missing:
        return IdentityResult(
            BALANCE_SHEET_BALANCES,
            NOT_CHECKABLE,
            f"needs total_assets, total_liabilities and total_equity; missing {', '.join(missing)}",
        )

    assert assets is not None and liabilities is not None and equity is not None
    expected = liabilities + equity
    outcome = PASSED if _close_enough(assets, expected) else FAILED
    return IdentityResult(
        BALANCE_SHEET_BALANCES,
        outcome,
        f"assets {assets:,} against liabilities {liabilities:,} plus equity {equity:,} "
        f"= {expected:,}, a difference of {assets - expected:,}",
        expected=expected,
        actual=assets,
    )


def _profit_ties(figures: dict[tuple[str, str], Decimal | None]) -> IdentityResult:
    """Profit after tax must agree wherever it is reported for one period.

    It is a `both`-template key, so it can appear on the income statement and again at the
    top of the cash flow. Two different numbers for one period's profit is the kind of
    disagreement that is obvious once stated and invisible in a table.
    """
    reported = {
        statement_type: value
        for (statement_type, key), value in figures.items()
        if key == "profit_after_tax" and value is not None
    }
    if len(reported) < 2:
        where = ", ".join(sorted(reported)) or "nowhere"
        return IdentityResult(
            PROFIT_TIES,
            NOT_CHECKABLE,
            f"profit_after_tax is reported in {where}; two statements are needed to compare",
        )
    values = list(reported.values())
    first = values[0]
    agree = all(_close_enough(first, other) for other in values[1:])
    stated = ", ".join(f"{name} {value:,}" for name, value in sorted(reported.items()))
    return IdentityResult(
        PROFIT_TIES,
        PASSED if agree else FAILED,
        f"profit after tax reported as {stated}",
        expected=first,
        actual=max(values, key=lambda v: abs(v - first)) if not agree else first,
    )


def _cross_year_swing(
    session: Session,
    *,
    company_id: int,
    period_type: str,
    period_end: dt.date,
    figures: dict[tuple[str, str], Decimal | None],
) -> IdentityResult:
    """Year-on-year moves beyond 5x. P4.3's *"quiet hero"* for unit errors.

    A figure 1,000x wrong will not tie to last year's, and that is a far surer signal than
    any amount of staring at the number itself: 3,360,000 is as plausible in thousands as in
    millions until it sits beside last year's 3,400,000.
    """
    previous_end = dt.date(period_end.year - 1, period_end.month, period_end.day)
    previous = _figures(
        session, company_id=company_id, period_type=period_type, period_end=previous_end
    )
    if not previous:
        return IdentityResult(
            CROSS_YEAR_SWING,
            NOT_CHECKABLE,
            f"no {period_type} statements for {previous_end} to compare against",
        )

    swings: list[str] = []
    sign_changes: list[str] = []
    compared = 0
    for key in SWING_KEYS:
        for statement_type in ("income", "balance", "cashflow"):
            now = figures.get((statement_type, key))
            before = previous.get((statement_type, key))
            if now is None or before is None or abs(before) < SWING_FLOOR:
                continue
            compared += 1
            if (now < 0) != (before < 0):
                # A business event, not a magnitude error. Worth a reviewer's eye; not worth
                # failing an arithmetic identity over.
                sign_changes.append(f"{key} went from {before:,} to {now:,}")
                continue
            multiple = abs(now) / abs(before)
            if multiple >= SWING_MULTIPLE or multiple <= 1 / SWING_MULTIPLE:
                swings.append(f"{key} moved from {before:,} to {now:,}, a factor of {multiple:.1f}")
    if compared == 0:
        return IdentityResult(
            CROSS_YEAR_SWING,
            NOT_CHECKABLE,
            f"no figure is reported for both {period_end} and {previous_end} above the "
            f"{SWING_FLOOR:,} floor",
        )
    noted = (
        " Sign changes, which are business events rather than magnitude errors: "
        + "; ".join(sign_changes)
        if sign_changes
        else ""
    )
    if swings:
        return IdentityResult(
            CROSS_YEAR_SWING,
            FAILED,
            f"{len(swings)} of {compared} figures moved by {SWING_MULTIPLE}x or more against "
            f"{previous_end} at an unchanged sign: " + "; ".join(swings) + noted,
        )
    return IdentityResult(
        CROSS_YEAR_SWING,
        PASSED,
        f"{compared} figures compared against {previous_end}, none moving by "
        f"{SWING_MULTIPLE}x or more at an unchanged sign." + noted,
    )


def _composition_identities(
    figures: dict[tuple[str, str], Decimal | None],
) -> list[IdentityResult]:
    """`a - b == c`, for the lines that are defined that way."""
    results = []
    for statement, minuend, subtrahend, result_key in COMPOSITION_IDENTITIES:
        a = figures.get((statement, minuend))
        b = figures.get((statement, subtrahend))
        c = figures.get((statement, result_key))
        name = f"{minuend}_less_{subtrahend}_is_{result_key}"
        if a is None or b is None or c is None:
            missing = [
                key
                for key, value in ((minuend, a), (subtrahend, b), (result_key, c))
                if value is None
            ]
            results.append(IdentityResult(name, NOT_CHECKABLE, f"missing {', '.join(missing)}"))
            continue
        expected = a - b
        results.append(
            IdentityResult(
                name,
                PASSED if _close_enough(c, expected) else FAILED,
                f"{minuend} {a:,} less {subtrahend} {b:,} = {expected:,}, against "
                f"{result_key} {c:,}, a difference of {c - expected:,}",
                expected=expected,
                actual=c,
            )
        )
    return results


def _subset_rules(figures: dict[tuple[str, str], Decimal | None]) -> list[IdentityResult]:
    """A component cannot exceed the total that contains it.

    The tolerance runs one way only. A part may equal its whole - a company can hold all its
    assets as cash - so the comparison is "greater than, beyond rounding", not "not equal".
    """
    results = []
    for part_key, whole_key, statement in SUBSET_RULES:
        part = figures.get((statement, part_key))
        whole = figures.get((statement, whole_key))
        name = f"{part_key}_within_{whole_key}"
        if part is None or whole is None:
            missing = [k for k, v in ((part_key, part), (whole_key, whole)) if v is None]
            results.append(IdentityResult(name, NOT_CHECKABLE, f"missing {', '.join(missing)}"))
            continue
        if part <= whole or _close_enough(part, whole):
            results.append(
                IdentityResult(name, PASSED, f"{part_key} {part:,} is within {whole_key} {whole:,}")
            )
            continue
        results.append(
            IdentityResult(
                name,
                FAILED,
                f"{part_key} is {part:,}, larger than {whole_key} at {whole:,}, by "
                f"{part - whole:,}. A part cannot exceed its whole: one of the two is "
                f"mis-mapped, mis-scaled, or read off the wrong column",
                expected=whole,
                actual=part,
            )
        )
    return results


def _impossible_values(
    figures: dict[tuple[str, str], Decimal | None],
) -> list[IdentityResult]:
    """Figures a going concern cannot report. Blunter than the identities, and it caught one."""
    results = []
    for statement, key in MUST_BE_POSITIVE:
        value = figures.get((statement, key))
        name = f"{key}_is_positive"
        if value is None:
            results.append(IdentityResult(name, NOT_CHECKABLE, f"{key} is not reported"))
        elif value > 0:
            results.append(IdentityResult(name, PASSED, f"{key} is {value:,}"))
        else:
            results.append(
                IdentityResult(
                    name,
                    FAILED,
                    f"{key} is {value:,}. A going concern does not report this as zero or "
                    f"negative - it is a tagging error, a mis-mapped line, or a figure that "
                    f"belongs somewhere else",
                    actual=value,
                )
            )
    for statement, key in MUST_NOT_BE_NEGATIVE:
        value = figures.get((statement, key))
        name = f"{key}_not_negative"
        if value is None:
            results.append(IdentityResult(name, NOT_CHECKABLE, f"{key} is not reported"))
        elif value >= 0:
            results.append(IdentityResult(name, PASSED, f"{key} is {value:,}"))
        else:
            results.append(
                IdentityResult(
                    name,
                    FAILED,
                    f"{key} is {value:,}, and cannot be negative",
                    actual=value,
                )
            )
    return results


def validate_period(
    session: Session, *, company_id: int, period_type: str, period_end: dt.date
) -> ValidationReport:
    """Every identity for one company-period, against the current version of each statement.

    Takes a period rather than a statement id because two of the identities are
    *cross-statement*: profit after tax has to agree between the income statement and the
    cash flow, and neither statement can check that alone.
    """
    figures = _figures(
        session, company_id=company_id, period_type=period_type, period_end=period_end
    )
    report = ValidationReport(company_id=company_id, period_type=period_type, period_end=period_end)
    report.results = [
        _balance_sheet_balances(figures),
        _profit_ties(figures),
        _cross_year_swing(
            session,
            company_id=company_id,
            period_type=period_type,
            period_end=period_end,
            figures=figures,
        ),
        *_composition_identities(figures),
        *_subset_rules(figures),
        *_impossible_values(figures),
    ]
    return report

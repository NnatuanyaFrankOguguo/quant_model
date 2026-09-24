"""`packages.extract.budget`: the cap that halts. P4 check 15, `docs/02` §10.

`docs/02_INFRASTRUCTURE.md` §10 states the requirement without room in it: *"At 80% of the
cap, alert. At 100%, **halt** - do not degrade silently, and do not continue billing."* P4
check 15 is the test: *"Simulate hitting the cap -> Halts; does not silently continue
billing."*

`entitlements.llm_spend_cap_usd` and the `llm_spend` table have both been in the schema
since migration `0001`, and until now nothing read either. The cap was a number in a table.
"""

from __future__ import annotations

import datetime as dt
import uuid
from decimal import Decimal

import pytest
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from packages.common.models import Entitlement, Principal
from packages.extract.budget import (
    ALERT_FRACTION,
    ALLOWED,
    HALTED,
    WARNING,
    BudgetExceededError,
    NoEntitlementError,
    check_budget,
    month_start,
    raise_if_halted,
    record_spend,
    spend_this_month,
)

pytestmark = pytest.mark.invariant

CAP = Decimal("50.00")
#: Mid-month, so a test can spend "earlier this month" and "last month" on either side.
TODAY = dt.date(2026, 9, 15)


@pytest.fixture
def principal(db_session: Session) -> int:
    """One principal with a $50 monthly cap."""
    return _principal(db_session, cap=CAP, name="zz-test-budget")


def _principal(session: Session, *, cap: Decimal | None, name: str) -> int:
    row = session.execute(
        select(Principal).where(Principal.display_name == name)
    ).scalar_one_or_none()
    if row is None:
        row = Principal(display_name=name, kind="human")
        session.add(row)
        session.flush()
    if cap is not None:
        session.add(
            Entitlement(
                principal_id=row.id,
                # Both are booleans, not tier names - `seed_dev.py` passes True.
                personal_tier=True,
                data_tier=True,
                llm_spend_cap_usd=cap,
                granted_by="tests",
            )
        )
        session.flush()
    return row.id


def _spend(
    session: Session,
    principal_id: int,
    amount: str,
    *,
    when: dt.date = TODAY,
    cache_hit: bool = False,
) -> None:
    """A billed call on a given day. Written directly so the timestamp can be chosen."""
    rid = uuid.uuid5(uuid.NAMESPACE_URL, f"{principal_id}-{amount}-{when}-{cache_hit}")
    record_spend(
        session,
        principal_id=principal_id,
        job_kind="extraction",
        model="claude-test",
        prompt_version="v1",
        input_tokens=1000,
        output_tokens=200,
        cost_usd=Decimal(amount),
        request_id=rid,
        cache_hit=cache_hit,
    )
    session.execute(
        text("UPDATE llm_spend SET ts = :ts WHERE request_id = :rid"),
        {"ts": dt.datetime(when.year, when.month, when.day, 12, tzinfo=dt.UTC), "rid": rid},
    )
    session.flush()


# --------------------------------------------------------------------------------------
# The gate
# --------------------------------------------------------------------------------------


def test_an_untouched_budget_allows(db_session: Session, principal: int) -> None:
    decision = check_budget(
        db_session, principal_id=principal, estimated_usd=Decimal("1.00"), on=TODAY
    )
    assert decision.status == ALLOWED
    assert decision.may_proceed
    assert decision.remaining_usd == CAP


def test_eighty_per_cent_alerts_without_stopping(db_session: Session, principal: int) -> None:
    """`docs/02` §10: *"At 80% of the cap, alert."* Alert, not halt - there is still room,
    and stopping here would throw away a fifth of a budget somebody paid for."""
    _spend(db_session, principal, "40.00")  # exactly 80% of 50
    decision = check_budget(
        db_session, principal_id=principal, estimated_usd=Decimal("1.00"), on=TODAY
    )
    assert decision.status == WARNING
    assert decision.may_proceed
    assert decision.fraction_used == ALERT_FRACTION


def test_the_cap_halts_rather_than_degrading(db_session: Session, principal: int) -> None:
    """P4 check 15, exactly as written: simulate hitting the cap, and it must halt.

    Not "use a cheaper model", not "truncate the prompt", not "log and carry on". The
    requirement is worded against silent degradation because every one of those is a way
    of continuing to bill while appearing to have stopped.
    """
    _spend(db_session, principal, "50.00")
    decision = check_budget(
        db_session, principal_id=principal, estimated_usd=Decimal("0.01"), on=TODAY
    )
    assert decision.status == HALTED
    assert not decision.may_proceed
    assert decision.remaining_usd == 0
    with pytest.raises(BudgetExceededError, match="Halting rather than continuing to bill"):
        raise_if_halted(db_session, principal_id=principal, estimated_usd=Decimal("0.01"), on=TODAY)


def test_the_estimate_is_part_of_the_check(db_session: Session, principal: int) -> None:
    """A call that would cross the cap is refused before it is made, not after.

    Checking `spent < cap` and then spending five dollars exceeds the cap by five dollars,
    every time, for as long as the loop runs. The ceiling has to include the call being
    asked about or it is not a ceiling.
    """
    _spend(db_session, principal, "48.00")
    assert (
        check_budget(
            db_session, principal_id=principal, estimated_usd=Decimal("1.00"), on=TODAY
        ).status
        == WARNING
    )
    assert (
        check_budget(
            db_session, principal_id=principal, estimated_usd=Decimal("5.00"), on=TODAY
        ).status
        == HALTED
    )


def test_a_zero_cap_halts_everything(db_session: Session) -> None:
    """Zero is the strictest cap, not an unset one.

    `scripts/seed_dev.py` already grants a principal exactly this. Read as "unset therefore
    unlimited" - which is what `if not cap` does - that principal would hold the only
    unbounded budget in the system.
    """
    who = _principal(db_session, cap=Decimal(0), name="zz-test-budget-zero")
    decision = check_budget(db_session, principal_id=who, estimated_usd=Decimal(0), on=TODAY)
    assert decision.status == HALTED
    assert decision.fraction_used == 1  # fully used by definition, not empty with room


def test_a_principal_with_no_entitlement_is_refused_not_defaulted(db_session: Session) -> None:
    """The charitable default here is the one that bills."""
    who = _principal(db_session, cap=None, name="zz-test-budget-ungranted")
    with pytest.raises(NoEntitlementError, match="no entitlements row"):
        check_budget(db_session, principal_id=who, on=TODAY)


def test_a_negative_estimate_is_refused(db_session: Session, principal: int) -> None:
    """It would buy room under the cap that no call is going to give back."""
    with pytest.raises(ValueError, match="negative estimate"):
        check_budget(db_session, principal_id=principal, estimated_usd=Decimal("-10"), on=TODAY)


# --------------------------------------------------------------------------------------
# What counts against the cap
# --------------------------------------------------------------------------------------


def test_last_months_spend_does_not_count_against_this_month(
    db_session: Session, principal: int
) -> None:
    """The ceiling is monthly, so it has to actually reset."""
    _spend(db_session, principal, "50.00", when=dt.date(2026, 8, 31))
    assert spend_this_month(db_session, principal_id=principal, on=TODAY) == 0
    assert check_budget(db_session, principal_id=principal, on=TODAY).status == ALLOWED


def test_a_cache_hit_costs_nothing_and_counts_for_nothing(
    db_session: Session, principal: int
) -> None:
    """Counting a free call against the cap would penalise the caching that keeps the cost
    down - and caching is one of the four mechanisms `docs/02` §10 requires."""
    _spend(db_session, principal, "0.00", cache_hit=True)
    _spend(db_session, principal, "10.00")
    assert spend_this_month(db_session, principal_id=principal, on=TODAY) == Decimal("10.00")


def test_a_cache_hit_is_still_recorded(db_session: Session, principal: int) -> None:
    """*Cost per document* is the metric §10 says to watch, and a hit that left no row
    would make the average look worse the better the cache got."""
    _spend(db_session, principal, "0.00", cache_hit=True)
    rows = db_session.execute(
        text("SELECT count(*) FROM llm_spend WHERE principal_id = :p AND cache_hit"),
        {"p": principal},
    ).scalar_one()
    assert rows == 1


def test_a_billed_cache_hit_is_refused(db_session: Session, principal: int) -> None:
    """A hit that cost money is not a hit, and a miss recorded as one is spend the cap will
    never see. Either way one of the two fields is wrong, and recording it corrupts either
    the ceiling or the metric."""
    with pytest.raises(ValueError, match="A hit that was billed is not a hit"):
        record_spend(
            db_session,
            principal_id=principal,
            job_kind="extraction",
            model="claude-test",
            prompt_version="v1",
            input_tokens=1,
            output_tokens=1,
            cost_usd=Decimal("2.00"),
            request_id=uuid.uuid4(),
            cache_hit=True,
        )


def test_a_negative_cost_is_refused(db_session: Session, principal: int) -> None:
    """A call cannot refund budget, and one that appeared to would let a loop run forever."""
    with pytest.raises(ValueError, match="cannot refund"):
        record_spend(
            db_session,
            principal_id=principal,
            job_kind="extraction",
            model="claude-test",
            prompt_version="v1",
            input_tokens=1,
            output_tokens=1,
            cost_usd=Decimal("-5.00"),
            request_id=uuid.uuid4(),
        )


def test_one_principals_spend_does_not_exhaust_anothers(db_session: Session) -> None:
    """`docs/02` §10 item 1 and `PROJECT_CONTEXT.md` §4: caps are per user, never global.

    A shared ceiling would stop one person's work for a reason belonging entirely to
    somebody else, which is both wrong and impossible to diagnose from the stopped end.
    """
    first = _principal(db_session, cap=CAP, name="zz-test-budget-a")
    second = _principal(db_session, cap=CAP, name="zz-test-budget-b")
    _spend(db_session, first, "50.00")
    assert check_budget(db_session, principal_id=first, on=TODAY).status == HALTED
    assert check_budget(db_session, principal_id=second, on=TODAY).status == ALLOWED


def test_the_month_starts_on_the_first(db_session: Session) -> None:
    """A calendar month, not a rolling thirty days - so a reader can reconcile the figure
    against an invoice."""
    assert month_start(dt.date(2026, 9, 15)) == dt.date(2026, 9, 1)
    assert month_start(dt.date(2026, 1, 1)) == dt.date(2026, 1, 1)


def test_exactly_at_the_cap_halts_even_when_nothing_more_is_asked_for(
    db_session: Session, principal: int
) -> None:
    """`docs/02` §10 says "At 100%, halt", and at 100% means at 100%.

    Written because the first version got this wrong. The gate only checked
    `spent + estimated > cap`, so a principal who had spent exactly the cap and asked
    whether they could spend nothing more was told `WARNING` - carry on. It is a question
    with one correct answer and that is not it, and every caller passing a zero estimate
    (a pre-flight check before sizing the work) would have been waved through at 100%.
    """
    _spend(db_session, principal, "50.00")
    assert check_budget(db_session, principal_id=principal, on=TODAY).status == HALTED
    assert (
        check_budget(db_session, principal_id=principal, estimated_usd=Decimal(0), on=TODAY).status
        == HALTED
    )

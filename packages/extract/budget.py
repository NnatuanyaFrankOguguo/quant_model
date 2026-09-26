"""The spend cap that has to halt rather than degrade. P4 check 15, `docs/02` §10.

`docs/02_INFRASTRUCTURE.md` §10 opens with why this is the one cost that needs a gate
rather than a dashboard:

    This is the one operating cost that can run away silently, because a loop that retries
    a failed extraction is a loop that spends money.

and closes the requirement with no room in it:

    A hard monthly ceiling with alerting. At 80% of the cap, alert. At 100%, **halt** - do
    not degrade silently, and do not continue billing.

P4 check 15 is the test: *"Simulate hitting the cap -> Halts; does not silently continue
billing."*

## What was already here and what was not

`entitlements.llm_spend_cap_usd` exists. The `llm_spend` table exists, with `principal_id`,
`cost_usd`, `cache_hit` and `request_id`. Both have been in the schema since `0001`.
**Nothing read either of them.** There was no gate, no recording, and no way for a run to
know what it had spent - so the cap was a number in a table and the ceiling was whatever
the API let through.

## Per principal, never global

`PROJECT_CONTEXT.md` §4 makes this multi-user from day one, and `docs/02` §10 item 1 is
explicit that caps are per user. A global cap would let one principal's backfill exhaust
another's month, and the second person would see extraction stop for a reason that has
nothing to do with them.

## A cap of zero means zero

`scripts/seed_dev.py` already seeds a principal with `llm_spend_cap_usd = 0`. Read as
"unset, therefore unlimited" - which is what a `if not cap` check does - that principal
would have the *only* unlimited budget in the system. Zero is a cap, it is the strictest
one, and `HALTED` is the correct answer for every call under it.

## The estimate is part of the check

Checking `spent < cap` and then making a call that costs five dollars exceeds the cap by
whatever the call cost. The gate takes the estimate and checks `spent + estimate <= cap`,
so the ceiling is a ceiling rather than a line the last call is allowed to cross.
"""

from __future__ import annotations

import datetime as dt
import uuid
from dataclasses import dataclass
from decimal import Decimal

import structlog
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from packages.common.models import Entitlement, LlmSpend
from packages.common.timez import utcnow

__all__ = [
    "ALERT_FRACTION",
    "ALLOWED",
    "HALTED",
    "WARNING",
    "BudgetDecision",
    "BudgetExceededError",
    "NoEntitlementError",
    "check_budget",
    "month_start",
    "raise_if_halted",
    "record_spend",
    "spend_this_month",
]

_log = structlog.get_logger(__name__)

#: Room for this call and everything already spent. Proceed.
ALLOWED = "allowed"
#: Proceed, but the month is nearly gone. `docs/02` §10: *"At 80% of the cap, alert."*
WARNING = "warning"
#: No room. `docs/02` §10: *"halt - do not degrade silently, and do not continue billing."*
HALTED = "halted"

#: Where the alert starts. Eighty per cent is `docs/02` §10's figure, not a choice made here.
ALERT_FRACTION = Decimal("0.80")


class BudgetExceededError(RuntimeError):
    """Raised instead of making the call. Carries the numbers a human needs to decide.

    An exception rather than a return value at the point of use, because *"do not degrade
    silently"* means a caller that ignores the answer must not be able to continue. A
    caller that wants to look before leaping asks `check_budget` and reads the decision.
    """


class NoEntitlementError(LookupError):
    """This principal has no entitlement row, so there is no cap to check against.

    Refused rather than defaulted. A missing row is an unconfigured principal, and the
    charitable default - unlimited - is the one that bills. `docs/02` §10's caps are
    per-principal, so a principal nobody has granted anything is a principal who cannot
    spend, and saying so names the fix.
    """


@dataclass(frozen=True)
class BudgetDecision:
    """What the gate decided, and the figures it decided from."""

    status: str
    principal_id: int
    cap_usd: Decimal
    spent_usd: Decimal
    estimated_usd: Decimal
    period_start: dt.date

    @property
    def remaining_usd(self) -> Decimal:
        """Never negative. A cap already exceeded has nothing left rather than less."""
        return max(self.cap_usd - self.spent_usd, Decimal(0))

    @property
    def fraction_used(self) -> Decimal:
        """Spend as a share of the cap. `1` for a zero cap, which is fully used by
        definition - and `0` would read as an empty budget with room in it."""
        if self.cap_usd <= 0:
            return Decimal(1)
        return self.spent_usd / self.cap_usd

    @property
    def may_proceed(self) -> bool:
        return self.status != HALTED

    @property
    def reason(self) -> str:
        if self.status == HALTED:
            return (
                f"principal {self.principal_id} has spent ${self.spent_usd} of a "
                f"${self.cap_usd} cap since {self.period_start}, and this call is "
                f"estimated at ${self.estimated_usd}. Halting rather than continuing to "
                f"bill - raise entitlements.llm_spend_cap_usd or wait for the month to turn."
            )
        if self.status == WARNING:
            return (
                f"principal {self.principal_id} has used {self.fraction_used:.0%} of a "
                f"${self.cap_usd} cap since {self.period_start}; ${self.remaining_usd} left"
            )
        return (
            f"principal {self.principal_id} has ${self.remaining_usd} of ${self.cap_usd} "
            f"left since {self.period_start}"
        )


def month_start(on: dt.date | None = None) -> dt.date:
    """The first of the month the cap is measured over.

    A calendar month in UTC, not a rolling thirty days. `docs/02` §10 says *"monthly"*, a
    reader checking a bill thinks in calendar months, and a rolling window would let spend
    reappear mid-month in a way nobody could reconcile against an invoice.
    """
    today = on or utcnow().date()
    return today.replace(day=1)


def spend_this_month(session: Session, *, principal_id: int, on: dt.date | None = None) -> Decimal:
    """What this principal has been billed so far this month.

    Cache hits are excluded. `docs/02` §10 item 2 makes content-hash caching one of the
    four mechanisms precisely so a repeat costs nothing, and counting a free call against
    the cap would penalise the caching that keeps the cost down. They are still recorded,
    because *cost per document* - the metric §10 says to watch - needs the denominator.
    """
    start = month_start(on)
    total = session.execute(
        select(func.coalesce(func.sum(LlmSpend.cost_usd), 0)).where(
            LlmSpend.principal_id == principal_id,
            LlmSpend.ts >= dt.datetime(start.year, start.month, start.day, tzinfo=dt.UTC),
            LlmSpend.cache_hit.is_(False),
        )
    ).scalar_one()
    return Decimal(total)


def check_budget(
    session: Session,
    *,
    principal_id: int,
    estimated_usd: Decimal = Decimal(0),
    on: dt.date | None = None,
) -> BudgetDecision:
    """Whether this principal may make a call costing about this much. Never raises on cost.

    Returns the decision rather than raising, so a caller can log a warning, pick a cheaper
    model, or queue the work. `raise_if_halted` is the version for a caller that has no
    such plan and must not proceed regardless.
    """
    if estimated_usd < 0:
        raise ValueError(
            f"estimated_usd={estimated_usd}; a negative estimate would buy room under the "
            f"cap that no call is going to give back"
        )
    cap = session.execute(
        select(Entitlement.llm_spend_cap_usd).where(Entitlement.principal_id == principal_id)
    ).scalar_one_or_none()
    if cap is None:
        raise NoEntitlementError(
            f"principal {principal_id} has no entitlements row, so there is no LLM spend "
            f"cap to check. Grant one - an unconfigured principal defaulting to unlimited "
            f"is the default that bills."
        )
    cap = Decimal(cap)
    spent = spend_this_month(session, principal_id=principal_id, on=on)
    decision = BudgetDecision(
        status=_status(cap=cap, spent=spent, estimated=estimated_usd),
        principal_id=principal_id,
        cap_usd=cap,
        spent_usd=spent,
        estimated_usd=estimated_usd,
        period_start=month_start(on),
    )
    if decision.status == HALTED:
        _log.error("llm_budget_halted", principal=principal_id, spent=str(spent), cap=str(cap))
    elif decision.status == WARNING:
        _log.warning("llm_budget_warning", principal=principal_id, spent=str(spent), cap=str(cap))
    return decision


def raise_if_halted(
    session: Session,
    *,
    principal_id: int,
    estimated_usd: Decimal = Decimal(0),
    on: dt.date | None = None,
) -> BudgetDecision:
    """`check_budget`, but a halt stops the caller rather than informing it.

    This is the one to call immediately before an API request. *"Do not degrade silently"*
    means the failure mode for a caller that forgets to read the answer has to be a
    stopped run, not a billed one.
    """
    decision = check_budget(session, principal_id=principal_id, estimated_usd=estimated_usd, on=on)
    if decision.status == HALTED:
        raise BudgetExceededError(decision.reason)
    return decision


def record_spend(
    session: Session,
    *,
    principal_id: int,
    job_kind: str,
    model: str,
    prompt_version: str,
    input_tokens: int,
    output_tokens: int,
    cost_usd: Decimal,
    request_id: uuid.UUID | None = None,
    source_document_id: int | None = None,
    cache_hit: bool = False,
) -> int:
    """Write what a call cost. Called after every one, including the free ones.

    A cache hit is recorded with its real cost - zero - rather than not recorded at all,
    because *cost per document* is the metric `docs/02` §10 says to watch and a hit that
    left no row would make the average look worse the better the cache got.

    `request_id` is *our* correlation id - the same UUID the API-request row carries - not
    the provider's. It ties spend back to the request that caused it, and it is nullable
    because a scheduled extraction has no inbound request to tie to.

    Worth stating what that leaves open: the **provider's** request id has no column here,
    so reconciling this table against an invoice is by timestamp and model rather than
    line by line. That is a gap, it is not one this module can close on its own, and
    inventing a column for it in passing would be the wrong way to decide it.
    """
    if cost_usd < 0:
        raise ValueError(f"cost_usd={cost_usd}; a call cannot refund budget")
    if cache_hit and cost_usd != 0:
        # Not an assertion about billing policy - a cache hit that cost money means the
        # cache did not hit, and one of the two fields is wrong. Recording it either way
        # corrupts the cap (a paid call excluded from it) or the metric.
        raise ValueError(
            f"cache_hit is true but cost_usd={cost_usd}. A hit that was billed is not a "
            f"hit; a miss recorded as one is spend the cap will never see."
        )
    row = LlmSpend(
        principal_id=principal_id,
        ts=utcnow(),
        job_kind=job_kind,
        model=model,
        prompt_version=prompt_version,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        cost_usd=cost_usd,
        cache_hit=cache_hit,
        source_document_id=source_document_id,
        request_id=request_id,
    )
    session.add(row)
    session.flush()
    return row.id


def _status(*, cap: Decimal, spent: Decimal, estimated: Decimal) -> str:
    """The gate itself, on three numbers, so it can be read in one place.

    A cap of zero halts. It is the strictest cap rather than an unset one, and
    `seed_dev.py` already grants a principal exactly that - read as "unlimited" it would be
    the only unbounded budget in the system.
    """
    if cap <= 0:
        return HALTED
    if spent >= cap:
        # `docs/02` §10 says "At 100%, halt", and at 100% means at 100%. Reached only via
        # `spent + estimated > cap` this returned WARNING for a principal who had spent
        # exactly the cap and asked whether they could spend nothing more - which is a
        # question with one correct answer and it is not "carry on".
        return HALTED
    if spent + estimated > cap:
        return HALTED
    if spent >= cap * ALERT_FRACTION:
        return WARNING
    return ALLOWED

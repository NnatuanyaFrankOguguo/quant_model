"""Running the morning brief for everybody who asked for one. P5.4.

The composition (`packages.brief.content`) and the reads (`packages.brief.collect`) know
nothing about when they are run. This module is where the three loose ends are tied: it
picks the principals, decides what day it is, and hands each brief to a channel.

**It is the only place in the package that looks at a clock.** Every read underneath
takes `decision_date` as a mandatory argument with no default, which is the rule
`docs/01` §5 sets and which makes a brief for a past date reproducible. A scheduled
firing has to convert "now" into a date somewhere, and doing it once, here, at the top,
is different in kind from a read path that quietly assumes today.

**One principal's failure is not the job's failure.** Each brief is composed and
delivered inside its own `try`, so a missing chat id for one family member does not stop
the owner's brief. Every outcome is returned, and the caller (`scripts/run_scheduler.py`
through `packages.scheduler.jobs`) decides what to do with a run in which nothing was
sent.
"""

from __future__ import annotations

import datetime as dt

from sqlalchemy.orm import Session

from packages.brief.collect import (
    DEFAULT_WINDOW_DAYS,
    collect_brief,
    principals_with_a_watchlist,
)
from packages.brief.delivery import (
    SENT,
    Channel,
    DeliveryOutcome,
    TelegramChannel,
    deliver,
    recipient_for,
)
from packages.common.console import step
from packages.common.db import get_session
from packages.common.timez import utctoday

__all__ = ["deliver_daily_briefs", "run_daily_brief"]


def run_daily_brief(
    session: Session,
    *,
    decision_date: dt.date,
    channel: Channel,
    window_days: int = DEFAULT_WINDOW_DAYS,
    now: dt.datetime | None = None,
) -> list[DeliveryOutcome]:
    """Compose and deliver one brief per subscribed principal, at most once each.

    Subscription is watchlist ownership - see `collect.principals_with_a_watchlist` for
    why that, and not a column nobody has added yet.

    Args:
        decision_date: the date every figure is read as known on. Mandatory.
        channel: where to send. Pass a real one; there is no default that pretends.
        window_days: how far back "new" reaches in each section.
        now: the instant to stamp a successful delivery with.

    Returns:
        One outcome per principal, in principal order. An empty list means nobody owns a
        watchlist, which is logged as a warning rather than passed over: a brief job that
        has no subscribers is not a quiet success.
    """
    outcomes: list[DeliveryOutcome] = []
    with step("Deliver the daily brief", decision_date=decision_date.isoformat()) as running:
        subscribers = principals_with_a_watchlist(session)
        if not subscribers:
            running.warn(
                "brief_has_no_subscribers",
                detail=(
                    "no enabled principal owns a watchlist, so no brief was composed; "
                    "the brief is built from a watchlist and there is nothing to build from"
                ),
            )
            running.result(principals=0, sent=0)
            return outcomes
        for principal_id, name in subscribers:
            brief = collect_brief(
                session,
                principal_id=principal_id,
                decision_date=decision_date,
                window_days=window_days,
            )
            outcome = deliver(
                session,
                brief,
                channel=channel,
                recipient=recipient_for(session, principal_id=principal_id, on=decision_date),
                now=now,
            )
            outcomes.append(outcome)
            running.note(
                "brief",
                principal_id=principal_id,
                principal=name,
                status=outcome.status,
                sent=outcome.sent,
                reason=outcome.reason,
            )
        sent = sum(1 for outcome in outcomes if outcome.status == SENT)
        running.result(principals=len(subscribers), sent=sent)
        if sent == 0:
            running.warn(
                "brief_sent_nothing",
                detail="every brief was suppressed, failed or already delivered",
            )
    return outcomes


def deliver_daily_briefs() -> list[DeliveryOutcome]:
    """The scheduler's entry point: today's brief, to Telegram, in its own session.

    `utctoday()` is called here and nowhere below. Storage and schedules are UTC (TG21),
    and at the 06:00 UTC firing - 07:00 WAT, the time `docs/03` P5.4 names - the UTC and
    Lagos calendar dates agree, so this is also the Lagos date the reader is standing on.
    """
    with get_session() as session:
        return run_daily_brief(
            session,
            decision_date=utctoday(),
            channel=TelegramChannel.from_settings(),
        )

"""Sending a brief once, or refusing out loud. P5.4.

`alert_deliveries` is the whole mechanism, and migration 0029 records why it is in P5 at
all: `docs/03` P5.4 and `SPEC.md` T7 both require the brief to be idempotent, `alerts` is
a P10 table, and a brief has no rule behind it - so `alert_id` is nullable and stays null
here. The hash is over the content (`packages.brief.content`), and the table is unique on
`(principal_id, idempotency_hash)`.

## The order of operations, which is the entire guarantee

1. Hash the content.
2. Look for a row. One that is `sent`, `pending` or `failed` means **stop** - this
   content has already been claimed by a send that may have happened.
3. **Claim it before sending**, by committing a `pending` row. The claim is durable
   before the network call, so a process killed mid-send leaves evidence that the send
   may have gone out.
4. Send.
5. Record the outcome: `sent` with `delivered_at`, or `failed`, or `suppressed`.

Step 3 is why the unique constraint matters more than the lookup in step 2: two
schedulers racing both read "no row", and exactly one of them wins the insert. The loser
gets an `IntegrityError`, treats it as "somebody else is sending this", and does not
send. `docs/03` P5.4: *"A retry after a network blip that double-sends is how a useful
bot becomes a muted one."*

## Which statuses may be retried, and why only one

* **`sent`** - it went. Never again.
* **`pending`** - claimed, outcome unknown. The message may be in the reader's phone. A
  retry here is the double-send the whole table exists to prevent, so it is refused and
  a human decides. This is the network-blip case, and it is meant to need a person.
* **`failed`** - the channel raised after an attempt was made. An HTTP call that raised
  may still have been delivered, so this is treated exactly like `pending`.
* **`suppressed`** - **nothing was attempted.** No bot token, no recipient: the refusal
  happened before any byte left. Retrying is safe by construction, and it is the state
  this project is in today. The morning a token appears, the next run delivers the brief
  that was suppressed rather than being blocked for ever by the runs that could not.

## Gated, not faked

There is no token in this environment and there is no console channel standing in for
one. A send that cannot happen records `suppressed` with `delivered_at` left NULL and
logs at error level. Nothing in this module can write `status='sent'` without also
writing `delivered_at`, and the `alert_deliveries_sent_has_a_time` CHECK is the second
lock on the same door.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from typing import Protocol, runtime_checkable

import structlog
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from packages.brief.content import Brief, content_hash, render, split_for_telegram
from packages.common.config import get_settings
from packages.common.models import AlertDelivery
from packages.common.system_config import get_config
from packages.common.timez import ensure_utc, utcnow

__all__ = [
    "FAILED",
    "PENDING",
    "SENT",
    "SUPPRESSED",
    "TELEGRAM_CHAT_ID_PREFIX",
    "Channel",
    "DeliveryOutcome",
    "DeliveryRefused",
    "TelegramChannel",
    "deliver",
    "recipient_for",
]

_log = structlog.get_logger(__name__)

#: The four values `alert_deliveries_status_known` admits.
PENDING = "pending"
SENT = "sent"
FAILED = "failed"
SUPPRESSED = "suppressed"

#: Only a delivery that never attempted anything may be tried again. See the module
#: docstring: `pending` and `failed` are both "it might have gone out".
_RETRYABLE = frozenset({SUPPRESSED})

#: `system_config` key holding one principal's Telegram chat id: `telegram_chat_id.1`.
#:
#: **This is a placeholder for a column that does not exist yet, and saying so is part of
#: the design.** The honest home for a recipient address is `principals.telegram_chat_id`,
#: and P5.4 is not the task that adds a column to `principals`. `system_config` is the
#: only writable, dated key-value store in the schema, so the address lives there until a
#: migration moves it. The dating is harmless - a chat id that changes is a new window -
#: and `get_config` already takes the date every read in this codebase takes.
TELEGRAM_CHAT_ID_PREFIX = "telegram_chat_id"


class DeliveryRefused(RuntimeError):  # noqa: N818 - "refused" is the word the table uses
    """The channel will not send, and **did not attempt to**.

    The distinction from an ordinary exception is the whole point: this one means no byte
    left the process, so the delivery is recorded `suppressed` and may be retried. A
    channel that raises this after touching the network would turn a safe retry into a
    double-send, so it must be raised before, and only before.
    """


@runtime_checkable
class Channel(Protocol):
    """Somewhere a brief can be sent. Telegram today; email and web push are named in
    `SPEC.md` §4.3 and will arrive behind this same two-method surface."""

    name: str

    def send(self, *, recipient: str, text: str) -> None:
        """Deliver `text` to `recipient`, or raise.

        Raises:
            DeliveryRefused: when the channel is not configured and nothing was attempted.
        """


@dataclass(frozen=True)
class DeliveryOutcome:
    """What happened to one principal's brief on one channel."""

    principal_id: int
    channel: str
    idempotency_hash: str
    status: str
    #: True only when the channel returned from `send` without raising. Never inferred
    #: from the status, so the two cannot disagree.
    sent: bool
    reason: str


@dataclass(frozen=True)
class TelegramChannel:
    """`python-telegram-bot`, or a refusal. `SPEC.md` §4.3, `docs/03` P5.4.

    The token is read at construction and the library is imported inside :meth:`send`,
    for the reason `packages/common/config.py` gives about every other credential in this
    project: *absent is a legitimate state*, and a connector that refuses at the moment of
    use is better than one that cannot be imported. `python-telegram-bot` lives in the
    `ui` extra, so a machine that installed neither the extra nor a token still imports
    this module, still composes briefs, and still records honest `suppressed` rows.

    **This send path has never run.** There is no bot token in this environment, so
    everything below the refusal is written from the library's documented v22 API and is
    unexercised. It is marked as such rather than quietly presented as tested.
    """

    token: str | None = None
    name: str = "telegram"

    @classmethod
    def from_settings(cls) -> TelegramChannel:
        """The channel this process can actually use, which today is the refusing one."""
        return cls(token=get_settings().telegram_bot_token)

    def send(self, *, recipient: str, text: str) -> None:
        if not self.token:
            raise DeliveryRefused(
                "no Telegram bot token is configured (TELEGRAM_BOT_TOKEN in .env), so "
                "nothing was sent; the delivery is recorded as suppressed and will be "
                "retried once a token exists"
            )
        if not recipient:
            raise DeliveryRefused(
                "no Telegram chat id is configured for this principal "
                f"({TELEGRAM_CHAT_ID_PREFIX}.<principal_id> in system_config), so nothing "
                "was sent"
            )
        import asyncio

        from telegram import Bot  # `ui` extra - imported here so its absence is not fatal

        async def _send() -> None:
            bot = Bot(token=self.token)
            async with bot:
                for chunk in split_for_telegram(text):
                    # No parse mode: a company name carrying an underscore is not a reason
                    # for a brief to fail to send. See `content.render`.
                    await bot.send_message(chat_id=recipient, text=chunk)

        asyncio.run(_send())


def recipient_for(session: Session, *, principal_id: int, on: dt.date) -> str | None:
    """This principal's Telegram chat id as configured on `on`, or None.

    None is a legitimate state and is handled as a refusal, not as a silent skip: a
    principal who owns a watchlist has asked for a brief, and the reason they are not
    getting one belongs in `alert_deliveries` where it can be seen.
    """
    value = get_config(f"{TELEGRAM_CHAT_ID_PREFIX}.{principal_id}", on=on, session=session)
    if value is None:
        return None
    return str(value)


def deliver(
    session: Session,
    brief: Brief,
    *,
    channel: Channel,
    recipient: str | None,
    now: dt.datetime | None = None,
) -> DeliveryOutcome:
    """Send one brief at most once, and record what happened either way.

    `now` timestamps the event rather than choosing what to read, which is why it is the
    one date in this package that may default to the clock. Every *figure* in the brief
    came from a mandatory `decision_date` several layers down.

    **This function commits.** The claim in step 3 of the module docstring has to be
    durable before the network call, and an uncommitted claim protects nothing. Callers
    holding a wider transaction should be aware that this closes it.
    """
    digest = content_hash(brief)
    existing = session.execute(
        select(AlertDelivery)
        .where(AlertDelivery.principal_id == brief.principal_id)
        .where(AlertDelivery.idempotency_hash == digest)
    ).scalar_one_or_none()

    if existing is not None and existing.status not in _RETRYABLE:
        _log.info(
            "brief_already_delivered",
            principal_id=brief.principal_id,
            status=existing.status,
            idempotency_hash=digest,
        )
        return DeliveryOutcome(
            principal_id=brief.principal_id,
            channel=existing.channel,
            idempotency_hash=digest,
            status=existing.status,
            sent=False,
            reason=(
                f"this exact content is already recorded against this principal as "
                f"'{existing.status}'; it is not sent again"
            ),
        )

    row = existing
    if row is None:
        row = AlertDelivery(
            alert_id=None,  # a brief has no rule behind it - migration 0029
            principal_id=brief.principal_id,
            idempotency_hash=digest,
            channel=channel.name,
            status=PENDING,
            delivered_at=None,
        )
        session.add(row)
        try:
            session.commit()
        except IntegrityError:
            # Somebody else claimed this content between the select and the insert. The
            # unique constraint is the arbiter; the loser must not send.
            session.rollback()
            _log.warning(
                "brief_claimed_concurrently",
                principal_id=brief.principal_id,
                idempotency_hash=digest,
            )
            return DeliveryOutcome(
                principal_id=brief.principal_id,
                channel=channel.name,
                idempotency_hash=digest,
                status=PENDING,
                sent=False,
                reason="another run claimed this content first; it is not sent twice",
            )
    else:
        row.channel = channel.name
        row.status = PENDING
        session.commit()

    text = render(brief)
    try:
        channel.send(recipient=recipient or "", text=text)
    except DeliveryRefused as refusal:
        row.status = SUPPRESSED
        row.delivered_at = None
        session.commit()
        _log.error(
            "brief_delivery_refused",
            principal_id=brief.principal_id,
            channel=channel.name,
            idempotency_hash=digest,
            reason=str(refusal),
        )
        return DeliveryOutcome(
            principal_id=brief.principal_id,
            channel=channel.name,
            idempotency_hash=digest,
            status=SUPPRESSED,
            sent=False,
            reason=str(refusal),
        )
    except Exception as exc:  # noqa: BLE001 - one principal's failure is not the job's
        row.status = FAILED
        row.delivered_at = None
        session.commit()
        _log.error(
            "brief_delivery_failed",
            principal_id=brief.principal_id,
            channel=channel.name,
            idempotency_hash=digest,
            error_type=type(exc).__name__,
        )
        return DeliveryOutcome(
            principal_id=brief.principal_id,
            channel=channel.name,
            idempotency_hash=digest,
            status=FAILED,
            sent=False,
            reason=(
                f"the channel raised {type(exc).__name__} after an attempt was made; the "
                f"content stays claimed because it may have been delivered"
            ),
        )

    row.status = SENT
    row.delivered_at = ensure_utc(now or utcnow())
    session.commit()
    _log.info(
        "brief_delivered",
        principal_id=brief.principal_id,
        channel=channel.name,
        idempotency_hash=digest,
        characters=len(text),
    )
    return DeliveryOutcome(
        principal_id=brief.principal_id,
        channel=channel.name,
        idempotency_hash=digest,
        status=SENT,
        sent=True,
        reason="delivered",
    )

"""The daily brief: what moved, what was filed, what was written, what was released. P5.4.

Four modules, split along the line `docs/08` §6 draws between computation and I/O:

* :mod:`packages.brief.content` - the dataclasses, the text, and the idempotency hash.
  Pure. A brief's wording and its hash are testable without a database or a network.
* :mod:`packages.brief.collect` - the point-in-time reads, scoped to one principal's
  watchlist.
* :mod:`packages.brief.delivery` - `alert_deliveries`, the send-once guarantee, and the
  channel interface. A send that cannot happen is recorded, never faked.
* :mod:`packages.brief.job` - the one place that decides what day it is.

`packages.scheduler.jobs.daily_brief_job()` wires it to 06:00 UTC, which is the 07:00 WAT
`docs/03` P5.4 asks for.
"""

from __future__ import annotations

from packages.brief.collect import DEFAULT_WINDOW_DAYS, collect_brief, watchlist_for
from packages.brief.content import Brief, content_hash, render
from packages.brief.delivery import Channel, DeliveryOutcome, DeliveryRefused, deliver
from packages.brief.job import deliver_daily_briefs, run_daily_brief

__all__ = [
    "DEFAULT_WINDOW_DAYS",
    "Brief",
    "Channel",
    "DeliveryOutcome",
    "DeliveryRefused",
    "collect_brief",
    "content_hash",
    "deliver",
    "deliver_daily_briefs",
    "render",
    "run_daily_brief",
    "watchlist_for",
]

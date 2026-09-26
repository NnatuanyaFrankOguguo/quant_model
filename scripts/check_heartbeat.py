"""The dead-man check - a job that stopped running. `docs/10` §5.3.

    .venv\\Scripts\\python.exe scripts\\check_heartbeat.py [--strict]

Exits non-zero when something needs a human, so it can be a scheduled task whose failure is
itself the alert. Hourly, beside `check_connectors.py`, which it deliberately does not
replace.

**Why a second check.** `check_connectors.py` asks how the runs that happened went. Its
query - `packages/scheduler/runner.py:check_health` - groups `connector_runs` by
`connector_name`, so a connector the scheduler stopped launching contributes no rows, no
group and no line of report. `docs/10` §5.3: *"the query returns empty - indistinguishable
from healthy."* `02 §8` claims the freshness monitor covers this; it does not, because that
monitor is defined over `macro_series.expected_lag_days` and most sources are not macro
series.

This check runs the question the other way round. It starts from `data_sources`, where the
row exists whether or not anything ran, and asks each source for evidence of a successful run
inside the interval it declares - `expected_run_interval_hours`, added by migration `0024`.
Absence finally has something to be absent from.

Three outcomes, and the exit code follows the first two:

1. **Overdue** - the last successful run is older than the declared interval. Red, exit 1.
   The report names the last *attempt* too, because a source being launched and failing needs
   a different fix from one that nothing launches any more.
2. **Never ran** - not one `connector_runs` row exists for any job feeding the source. Red,
   exit 1. This is §5.3's `HAVING max(cr.finished_at) IS NULL` branch, and the one the
   existing query cannot express at all.
3. **Unmonitored** - `expected_run_interval_hours` is NULL. Listed by name, on every run, in
   its own step, and yellow rather than red by default.

**Why NULL is a warning and not a failure.** NGX has no connector, and an uploaded issuer
report is ad-hoc by construction, so neither can be late against anything; migration `0024`
records both as NULL on purpose. Failing on them would make this check permanently red, and a
check that is always red is a check nobody reads - which would recreate, socially, the exact
blindness §5.3 is about. So the default reports them loudly and exits 0, and `--strict` makes
them fail, for CI and for the quarterly review where *"is anything unwatched?"* is the
question being asked. What NULL must never do is pass silently, and it does not: it is
printed by name whether or not anyone passed the flag.

**This check cannot report that this machine is dead.** §5.3: *"A local check cannot report
that the local machine is dead."* If `HEARTBEAT_PING_URL` is set - a free healthchecks.io
check, period 1h, grace 2h - a clean run pings it, in the same shape and with the same
never-fail handling `scripts/backup.ps1` §8 uses for the backup's own ping. Unset is a no-op
with a note. A red run deliberately skips the ping: this check failing to report in is how
the outside world learns the laptop is off, and pinging on a red run would tell it the
opposite.
"""

from __future__ import annotations

import os
import sys

from packages.common.console import configure_logging, error, step, success, warning
from packages.common.db import get_session
from packages.scheduler.jobs import expected_run_names_by_source
from packages.scheduler.runner import SourceHeartbeat, check_heartbeat

#: The healthchecks.io check this script reports in to, read from the process environment
#: exactly as `backup.ps1` reads `HEALTHCHECK_PING_URL`, and deliberately a *different*
#: check: one URL shared between the backup and the heartbeat would let either one's pings
#: cover the other one's silence, which is the failure mode both exist to end.
PING_URL_VAR = "HEARTBEAT_PING_URL"

#: Seconds. Short on purpose - the ping is a courtesy at the end of a check that has already
#: done its work, and it must never be the reason a scheduled task hangs.
PING_TIMEOUT_SEC = 15.0


def _fields(beat: SourceHeartbeat) -> dict[str, object]:
    """One console line's worth of a heartbeat: both timestamps, never only the good one."""
    return {
        "source": beat.source_name,
        "last_ok": (
            beat.last_success_at.strftime("%Y-%m-%d %H:%MZ") if beat.last_success_at else "never"
        ),
        "last_attempt": (
            beat.last_attempt_at.strftime("%Y-%m-%d %H:%MZ") if beat.last_attempt_at else "never"
        ),
        "expected_every_h": beat.expected_run_interval_hours,
        "jobs": len(beat.run_names),
    }


def _ping(url: str) -> None:
    """Report in to the external dead-man check. Never raises, never changes the exit code.

    Imported here rather than at module scope so that a missing `httpx` cannot stop the check
    that matters from running at all - the ping is the last thing this script does, and the
    least important.
    """
    import httpx

    with step("Ping the dead-man check") as pinging:
        try:
            response = httpx.get(url, timeout=PING_TIMEOUT_SEC)
            response.raise_for_status()
        except Exception as exc:  # noqa: BLE001 - a failed ping is not a failed check
            pinging.warn("ping failed; the check itself passed", error_type=type(exc).__name__)
        else:
            pinging.result(status=response.status_code)


#: The only flag this script takes. Matched exactly - see `main`.
_STRICT = "--strict"


def main(argv: list[str] | None = None) -> int:
    given = list(argv or [])
    unknown = [arg for arg in given if arg != _STRICT]
    if unknown:
        # A membership test would read `--stict` as "not strict" and run happily, and the
        # caller would believe they had asked for the stricter check and been told it
        # passed. On a script whose whole subject is a check that fails silently, a typo
        # that quietly weakens it is the one mistake worth refusing outright.
        print(  # noqa: T201 - argument errors go to the terminal, before logging starts
            f"check_heartbeat: unrecognised argument(s) {' '.join(unknown)}\n"
            f"usage: check_heartbeat.py [{_STRICT}]\n"
            f"  {_STRICT}: every source must declare expected_run_interval_hours",
            file=sys.stderr,
        )
        return 2
    strict = _STRICT in given
    configure_logging()

    with step("Query source heartbeats", strict=strict) as querying:
        run_names_by_source = expected_run_names_by_source()
        with get_session() as session:
            beats = check_heartbeat(session, run_names_by_source=run_names_by_source)
        querying.result(
            sources=len(beats),
            jobs_mapped=sum(len(names) for names in run_names_by_source.values()),
        )

    monitored = [beat for beat in beats if not beat.unmonitored]
    unmonitored = [beat for beat in beats if beat.unmonitored]
    overdue = [beat for beat in monitored if beat.overdue]

    # One line per source, coloured by what it needs: green needs nothing, red needs a human
    # now. There is no yellow here - a source is either inside its declared interval or it is
    # not, and softening that is how a deadline stops being one.
    with step("Review every source with a declared interval", sources=len(monitored)) as review:
        for beat in monitored:
            if beat.overdue:
                review.fail(beat.finding or "overdue", **_fields(beat))
            else:
                review.ok("heard from inside its interval", **_fields(beat))
        review.result(overdue=len(overdue))

    with step("Check for sources nothing is watching", sources=len(unmonitored)) as unwatched:
        for beat in unmonitored:
            unwatched.warn(beat.finding or "no interval declared", **_fields(beat))
        unwatched.result(unmonitored=len(unmonitored))

    if overdue:
        error(
            "a source has stopped being heard from",
            overdue=len(overdue),
            sources=len(beats),
            unmonitored=len(unmonitored),
        )
        return 1

    if unmonitored and strict:
        error(
            "--strict: every source must declare expected_run_interval_hours",
            unmonitored=len(unmonitored),
            sources=[beat.source_name for beat in unmonitored],
        )
        return 1

    ping_url = os.environ.get(PING_URL_VAR)
    if ping_url:
        _ping(ping_url)
    else:
        warning(
            f"{PING_URL_VAR} is not set - nothing outside this machine will notice if this "
            f"check itself stops running, which is the one failure a local check cannot "
            f"report (docs/10 section 5.3)"
        )

    success(
        "every monitored source was heard from inside its interval",
        sources=len(monitored),
        unmonitored=len(unmonitored),
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))

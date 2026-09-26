"""The silent-failure check. P1.5 / TG8, from `OPERATIONS.md` §2.3.

    .venv\\Scripts\\python.exe scripts\\check_connectors.py

Exits non-zero when something needs a human, so it can be a scheduled task whose failure is
itself the alert.

Three questions, and the third is the one people forget:

1. Did the last run **fail**?
2. Did runs **succeed and write nothing**, repeatedly? The page still loads, the parser still
   runs, the selector matches nothing, and `status` is `'ok'`.
3. Did a connector **never run at all**? There is no row to be suspicious of, so absence has
   to be checked against the list of connectors we expect rather than against the table.
"""

from __future__ import annotations

import sys

from packages.common.console import configure_logging, error, step, success
from packages.common.db import get_session
from packages.ingestion.fred import FRED_SERIES
from packages.ingestion.manual_csv import MANUAL_SOURCES
from packages.scheduler.jobs import expected_run_names
from packages.scheduler.runner import check_health

#: What we expect to see runs from — derived from the job list the scheduler actually runs,
#: plus the manual paths, which run when a human feeds them (monthly rather than daily).
#:
#: `check_health` can only report on runs that exist, so a job missing from this set would
#: disappear from the report entirely once it stopped running — the failure would look like
#: silence, which is the one failure mode this script exists to break. That is why the set
#: is derived rather than maintained: it cannot be forgotten.
EXPECTED_CONNECTORS = expected_run_names()


def main(argv: list[str] | None = None) -> int:
    window_days = 30
    if argv:
        window_days = int(argv[0])
    configure_logging()

    with step("Query connector health", window_days=window_days) as querying:
        with get_session() as session:
            health = check_health(session, window_days=window_days)
        querying.result(connectors_seen=len(health))

    # One line per connector, coloured by what it needs: green needs nothing, yellow needs
    # a look, red needs a human now.
    with step("Review every connector that ran") as reviewing:
        for row in health:
            last = row.last_run_at.strftime("%Y-%m-%d %H:%MZ") if row.last_run_at else "never"
            fields = {
                "connector": row.connector_name,
                "last_run": last,
                "last_status": row.last_status or "-",
                "runs": row.runs_in_window,
                "rows": row.rows_in_window,
            }
            if not row.unhealthy:
                reviewing.ok("healthy", **fields)
            elif row.last_status == "error":
                reviewing.fail(row.finding or "last run failed", **fields)
            else:
                reviewing.warn(row.finding or "unhealthy", **fields)

    findings = [r for r in health if r.unhealthy]
    seen = {r.connector_name for r in health}
    never_ran = sorted(EXPECTED_CONNECTORS - seen)

    with step("Check for connectors that never ran", expected=len(EXPECTED_CONNECTORS)) as absent:
        for name in never_ran:
            if name.startswith("manual_csv_"):
                # A human feeds these, monthly. Silence is a reminder, not a failure - but
                # it still turns the exit code, because the reminder is the point.
                absent.warn("no manual upload in the window", connector=name)
            else:
                absent.fail(
                    "never ran in the window: a scheduled job that never runs fails exactly "
                    "like one that runs and returns nothing, except quieter",
                    connector=name,
                )
        absent.result(never_ran=len(never_ran))

    if not findings and not never_ran:
        success("all expected connectors ran and wrote rows", connectors=len(health))
        return 0

    error(
        "connector health needs a human",
        unhealthy=len(findings),
        never_ran=len(never_ran),
        fred_series=len(FRED_SERIES),
        manual_agencies=len(MANUAL_SOURCES),
    )
    return 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))

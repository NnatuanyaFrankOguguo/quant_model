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

from packages.common.db import get_session
from packages.ingestion.cbn import (
    CbnExchangeRateConnector,
    CbnInflationConnector,
    CbnMoneyMarketConnector,
)
from packages.ingestion.fred import FRED_SERIES
from packages.ingestion.manual_csv import MANUAL_SOURCES
from packages.ingestion.nigeria_data_portal import (
    NigeriaDataPortalCpiConnector,
    NigeriaDataPortalGdpConnector,
)
from packages.scheduler.runner import check_health

#: What we expect to see runs from. FRED runs once per series; the manual paths run when a
#: human feeds them, which is monthly rather than daily.
#:
#: **Every connector must be listed here, including ones that are currently running fine.**
#: `check_health` can only report on runs that exist, so a connector missing from this set
#: disappears from the report entirely once it stops running — the failure looks like
#: silence, which is the one failure mode this script exists to break.
EXPECTED_CONNECTORS = {
    "fred",
    CbnExchangeRateConnector.name,
    CbnInflationConnector.name,
    CbnMoneyMarketConnector.name,
    NigeriaDataPortalCpiConnector.name,
    NigeriaDataPortalGdpConnector.name,
    *(f"manual_csv_{s.lower()}" for s in MANUAL_SOURCES),
}


def main(argv: list[str] | None = None) -> int:
    window_days = 30
    if argv:
        window_days = int(argv[0])

    with get_session() as session:
        health = check_health(session, window_days=window_days)

    print(f"Connector health, last {window_days} days\n")
    print(f"{'connector':24} {'last run':22} {'status':8} {'runs':>5} {'rows':>7}")
    print("-" * 72)
    for row in health:
        last = row.last_run_at.strftime("%Y-%m-%d %H:%MZ") if row.last_run_at else "never"
        print(
            f"{row.connector_name:24} {last:22} {row.last_status or '-':8} "
            f"{row.runs_in_window:>5} {row.rows_in_window:>7}"
        )

    findings = [r for r in health if r.unhealthy]
    seen = {r.connector_name for r in health}
    never_ran = sorted(EXPECTED_CONNECTORS - seen)

    print()
    for row in findings:
        print(f"UNHEALTHY  {row.connector_name}: {row.finding}")
    for name in never_ran:
        print(
            f"NEVER RAN  {name}: no run in the window. A connector that never runs fails "
            f"exactly like one that runs and returns nothing, except quieter."
        )

    if not findings and not never_ran:
        print("All expected connectors ran and wrote rows.")
        return 0

    print(
        f"\n{len(findings)} unhealthy, {len(never_ran)} never ran. "
        f"FRED_SERIES covers {len(FRED_SERIES)} series; the manual paths cover "
        f"{len(MANUAL_SOURCES)} agencies.",
        file=sys.stderr,
    )
    return 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))

r"""Run the connector schedule. P1.5 / TG8.

    .venv\Scripts\python.exe scripts
un_scheduler.py          # run forever
    .venv\Scripts\python.exe scripts
un_scheduler.py --once   # run every job now, then exit

Until this existed, `build_scheduler()` was a function nothing called — the schedule was
designed and unstartable, which is the same as not having one. `OPERATIONS.md` §2.3's whole
point is that a connector which never runs fails exactly like one that runs and returns
nothing, only quieter.

**The job list is in code, not in a crontab** — `packages/scheduler/jobs.py`. One place says
what runs and how often, and `scripts/check_connectors.py` derives what it expects from the
same list. A schedule living only in the operating system is a schedule nobody can review
in a pull request.

Times are UTC (TG21), and deliberately coarse. These sources publish monthly or daily at
best; polling more often is load on someone else's server for no new data.
"""

from __future__ import annotations

import argparse
import time

from packages.common.console import configure_logging, error, info, step, success, warning
from packages.scheduler.jobs import build_jobs
from packages.scheduler.runner import build_scheduler, run_job


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--once",
        action="store_true",
        help="Run every job immediately and exit. Use this to verify the list, or to catch up.",
    )
    args = parser.parse_args(argv)
    configure_logging()

    with step("Build the job list") as building:
        jobs = build_jobs()
        for job in jobs:
            building.note("job", id=job.identity(), at_utc=f"{job.hour:02d}:{job.minute:02d}")
        building.result(jobs=len(jobs))

    if args.once:
        # Each `run_job` is its own top-level step, numbered after the one above, with the
        # connector's fetch / store raw / parse / write / record stages nested beneath it.
        failed = [job.identity() for job in jobs if run_job(job).status != "ok"]
        if failed:
            # Non-zero on any failure, so a one-shot run is usable as a scheduled task
            # whose exit code is the alert.
            error("jobs failed", failed=len(failed), of=len(jobs), which=failed)
            return 1
        success("every job succeeded", jobs=len(jobs))
        return 0

    with step("Start the scheduler", timezone="UTC") as starting:
        scheduler = build_scheduler(jobs)
        scheduler.start()
        starting.result(jobs=len(jobs))
    info("running; each firing is logged as its own numbered flow. Ctrl+C to stop.")
    try:
        while True:
            time.sleep(60)
    except KeyboardInterrupt:
        warning("stopping on Ctrl+C")
        scheduler.shutdown(wait=False)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

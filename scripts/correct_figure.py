"""Correct one stored figure by hand, with a note saying who and why. TG10, `docs/03` P3.5.

    python scripts/correct_figure.py --ticker GTCO --key revenue --period FY \
        --period-end 2024-12-31 --value 3360000000000 \
        --by frank --reason "printed in millions; stored as thousands. Page 42."

`PROJECT_CONTEXT.md` §7 asks for "a dead-simple manual override ... with a note recording
who changed it and why", and in this project the operator's dead-simple path is a script -
the same shape as `ingest_csv.py`, the permanent human fallback for sources with no API.

**Nothing is overwritten.** The correction inserts a new statement version with the figure
changed and every sibling carried forward, and points the old rows at the new ones. The
previous value stays in the table forever; `--history` prints it.

**Two kinds of correction, and the difference is a date.** By default this records *our*
mistake, and the corrected figure carries the **original** `known_as_of` so a
point-in-time read from before the fix returns the right number rather than the typo. A
company republishing is `--type restatement` with `--known-as-of`, which is a new vintage
that a reader before that date must not see. `docs/10` §2.10 has the reasoning; getting it
backwards bakes a typo into every backtest over the period.

Run with `--dry-run` first: it resolves the figure, shows what would change, and writes
nothing.
"""

from __future__ import annotations

import argparse
import datetime as dt
import sys
from decimal import Decimal, InvalidOperation

from packages.common.console import configure_logging, error, step, success
from packages.common.db import SessionLocal
from packages.common.identity import resolve_security
from packages.common.timez import utctoday
from packages.normalize.corrections import (
    CORRECTION_TYPES,
    Correction,
    CorrectionRefusedError,
    apply_correction,
    history_of,
)


def _parse_value(raw: str) -> Decimal | None:
    """`--value` in base currency units, already scaled. `none` empties the figure.

    Scaling is `packages/common/units.py`'s job and happens exactly once, so what is typed
    here is the fully scaled figure - naira, not thousands of naira (`docs/08` §1.5).
    `none` is `docs/08` §1.4's null: the company reported nothing there.
    """
    if raw.strip().lower() in {"none", "null", "-"}:
        return None
    try:
        return Decimal(raw.replace(",", "").replace("_", "").strip())
    except InvalidOperation:
        raise SystemExit(
            f"--value {raw!r} is not a number. Give the fully scaled figure in base "
            "currency units, or 'none' to record that the company reported nothing."
        ) from None


def _arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--ticker", required=True, help="The security's current ticker")
    parser.add_argument(
        "--exchange", default=None, help="Needed only if two markets share the ticker"
    )
    parser.add_argument("--key", required=True, help="Canonical key, e.g. revenue")
    parser.add_argument("--period", required=True, help="FY, Q1, Q2, Q3, H1 or YTD")
    parser.add_argument("--period-end", required=True, help="YYYY-MM-DD")
    parser.add_argument("--value", help="The corrected figure in base units, or 'none'")
    parser.add_argument("--by", help="Who is making the correction")
    parser.add_argument("--reason", help="Why - required, and stored with the figure")
    parser.add_argument("--type", default="transcription", choices=CORRECTION_TYPES)
    parser.add_argument(
        "--known-as-of",
        default=None,
        help="Only for --type restatement: the date the company republished (YYYY-MM-DD)",
    )
    parser.add_argument("--history", action="store_true", help="Print every version and exit")
    parser.add_argument("--dry-run", action="store_true", help="Resolve and report; write nothing")
    return parser.parse_args()


def main() -> int:
    configure_logging()
    args = _arguments()
    period_end = dt.date.fromisoformat(args.period_end)
    known_as_of = dt.date.fromisoformat(args.known_as_of) if args.known_as_of else None

    with SessionLocal() as session:
        with step(f"Resolve {args.ticker}") as resolved_step:
            resolved = resolve_security(
                session, value=args.ticker, as_of=utctoday(), exchange=args.exchange
            )
            if resolved is None:
                error(f"no security carries ticker {args.ticker!r} today")
                return 1
            resolved_step.result(security_id=resolved.security_id)

        versions = history_of(
            session,
            security_id=resolved.security_id,
            canonical_key=args.key,
            period_type=args.period,
            period_end=period_end,
        )
        if not versions:
            error(
                f"{args.key!r} {args.period} ending {period_end} is not stored for "
                f"{args.ticker}. A correction edits a figure that exists."
            )
            return 1

        with step(
            f"{args.key} {args.period} {period_end}: {len(versions)} version(s) held"
        ) as shown:
            for v in versions:
                shown.note(
                    f"v{v.version}",
                    value="none" if v.value is None else f"{v.value:,}",
                    known_as_of=v.known_as_of.isoformat(),
                    correction=v.correction_type,
                    by=v.corrected_by or "-",
                    reason=v.correction_reason or "-",
                    current=v.superseded_by is None,
                )
        if args.history:
            return 0

        missing = [
            flag
            for flag, value in (
                ("--value", args.value),
                ("--by", args.by),
                ("--reason", args.reason),
            )
            if value is None
        ]
        if missing:
            error(f"a correction needs {', '.join(missing)} - who changed it and why is the point")
            return 1

        correction = Correction(
            security_id=resolved.security_id,
            canonical_key=args.key,
            period_type=args.period,
            period_end=period_end,
            value=_parse_value(args.value),
            corrected_by=args.by,
            reason=args.reason,
            correction_type=args.type,
            known_as_of=known_as_of,
        )
        if args.dry_run:
            success(
                "Dry run: nothing written. The correction would replace "
                f"{'none' if versions[-1].value is None else format(versions[-1].value, ',')} with "
                f"{'none' if correction.value is None else format(correction.value, ',')}."
            )
            return 0

        with step("Apply the correction") as applying:
            try:
                result = apply_correction(session, correction)
            except CorrectionRefusedError as refused:
                error(str(refused))
                return 1
            applying.result(
                version=result.version,
                known_as_of=result.known_as_of.isoformat(),
                carried_forward=result.carried_forward,
                superseded_line_item=result.superseded_id,
            )
        session.commit()
    success(
        f"{args.key} {args.period} {period_end} is now "
        f"{'none' if result.value is None else format(result.value, ',')}, "
        f"version {result.version}, known as of {result.known_as_of}. "
        f"The previous value is kept as line item {result.superseded_id}."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())

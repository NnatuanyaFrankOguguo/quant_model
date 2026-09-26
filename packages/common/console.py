"""Colour-coded, step-numbered console output for every flow that runs in a terminal.

Until this existed, `structlog` was used everywhere and configured nowhere. A run of the
scheduler read as a flat list of timestamps and event names: nothing said *which step of
which job* a line belonged to, a job that inserted 39 rows and one that inserted none both
logged in the same colour, and the three operator scripts used bare `print()` — two output
channels with no shared shape. This module gives every flow one shape:

    21:04:11 [info     ] > 2      Run ndp:gdp                    attempt=1
    21:04:11 [info     ] > 2.1    fetch
    21:04:13 [success  ] + 2.1    fetch                          bytes=16421 elapsed=1.94s
    21:04:13 [info     ] > 2.2    store raw
    21:04:13 [success  ] + 2.2    store raw                      document_id=16 elapsed=0.11s
    21:04:13 [info     ]   2.3    portal_rows_skipped_wrong_indicator count=57
    21:04:14 [warning  ] ! 2.4    write                          elapsed=0.30s rows_inserted=0
    21:04:14 [error    ] x 3.1    fetch                          error='ConnectError: ...'

(The real lines carry the full date; it is elided here to fit.)

**Colours, by meaning and not by module:** blue is information, green is a success, yellow
is a warning, red is an error. The colour comes from the *level*, so every existing
`_log.warning(...)` in the codebase turns yellow without being touched; "success" is the one
addition — a level that did not exist — and it is what a step's closing line, or an
explicit `success(...)`, is rendered at.

**Steps are numbered by nesting, never by hand.** `with step("fetch"):` inside
`with step("Run ndp:gdp"):` is `2.1` because it is the first child of the second top-level
step. Hand-written numbers drift the first time someone inserts a step in the middle;
generated ones cannot. Numbering lives in a `ContextVar`, so each thread — each scheduler
worker — counts on its own.

**Markers, in ASCII on purpose.** `>` a step starting, `+` finished well, `!` finished with
a warning, `x` failed, and two spaces for an ordinary log line inside a step. Unicode ticks
would look better and would raise `UnicodeEncodeError` the moment output is piped through a
`cp1252` console on Windows, which is exactly when a log is being kept.

## What this must never do

**Print a credential.** The FRED key was leaked on 2026-09-09 through terminal output: an
`httpx` exception message carried the request URL, key and all. So every string that
passes through here — event text, every value, exception text — goes through
`redact_secrets` before it is rendered, in console mode and in JSON mode alike. Tracebacks
are formatted *plain*, never with local variables: structlog's default rich formatter
prints locals, and an exception's locals routinely include the request that failed.
`httpx`/`httpcore` are held at WARNING for the same reason — their INFO line is the full URL.

**Change behaviour.** A step is a context manager around code that already exists. It logs
on entry, logs on exit, and re-raises whatever escaped. `Connector.run()` catches exactly
what it caught before; `connector_runs` rows are written exactly as before.

**Break the tests.** `cache_logger_on_first_use` stays `False` so a logger resolves
`sys.stdout` at call time, which is what lets pytest's `capsys` see structlog output.

## Modes

`LOG_FORMAT=console` (default) renders as above; `LOG_FORMAT=json` emits one JSON object per
line for a log aggregator, `step` and all, with no colour and no `success` level (a
non-standard level name would only confuse a filter — the `outcome` key carries it there).
Colour is on when the stream is a terminal, honouring the `NO_COLOR` and `FORCE_COLOR`
conventions. `LOG_LEVEL` sets the floor, `INFO` by default. Each is read from the process
environment first and then from `.env` — the same file `Settings` reads — so a setting
placed beside `DATABASE_URL` takes effect without also being exported in the shell.
"""

from __future__ import annotations

import logging
import os
import sys
import time
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from typing import Any, TextIO

import structlog
from structlog.dev import (
    BLUE,
    BRIGHT,
    DIM,
    GREEN,
    RED,
    RESET_ALL,
    YELLOW,
    Column,
    ConsoleRenderer,
    KeyValueColumnFormatter,
    LogLevelColumnFormatter,
    plain_traceback,
)
from structlog.typing import EventDict, WrappedLogger

from packages.common.config import ENV_FILE, redact_secrets

__all__ = [
    "Step",
    "configure_logging",
    "current_step",
    "error",
    "info",
    "reset_steps",
    "step",
    "success",
    "warning",
]

#: Level name → colour. `success` is ours; the rest are structlog's names.
LEVEL_COLOURS: dict[str, str] = {
    "debug": DIM,
    "info": BLUE,
    "success": GREEN,
    "warning": YELLOW,
    "warn": YELLOW,
    "error": RED,
    "critical": RED,
    "exception": RED,
    "notset": DIM,
}

MARK_START = ">"
MARK_SUCCESS = "+"
MARK_WARNING = "!"
MARK_ERROR = "x"
MARK_INSIDE = " "

_OUTCOME_MARKS = {"success": MARK_SUCCESS, "warning": MARK_WARNING, "error": MARK_ERROR}
_OUTCOME_RANK = {"success": 0, "warning": 1, "error": 2}

#: Third-party loggers and the floor they are held at, with the reason.
_QUIET_LOGGERS: dict[str, int] = {
    # Their INFO line is the request URL, which for a keyed API contains the key.
    "httpx": logging.WARNING,
    "httpcore": logging.WARNING,
    # "Added job", "Running job", "Job executed": the step lines already say this.
    "apscheduler": logging.WARNING,
}

_HANDLER_NAME = "quant_model.console"

_log = structlog.get_logger("steps")
_console = structlog.get_logger("console")


# ---------------------------------------------------------------------------------------
# Step numbering
# ---------------------------------------------------------------------------------------


@dataclass
class _Frame:
    """One open step: its number and how many children it has opened so far."""

    number: str
    children: int = 0


_ROOT: ContextVar[_Frame | None] = ContextVar("console_step_root", default=None)
_STACK: ContextVar[tuple[_Frame, ...]] = ContextVar("console_step_stack", default=())


def _root() -> _Frame:
    root = _ROOT.get()
    if root is None:
        root = _Frame(number="")
        _ROOT.set(root)
    return root


def reset_steps() -> None:
    """Start numbering again from 1. Called by `configure_logging()` and per scheduled run."""
    _ROOT.set(_Frame(number=""))
    _STACK.set(())


def current_step() -> str | None:
    """The number of the innermost open step, or None outside any step."""
    stack = _STACK.get()
    return stack[-1].number if stack else None


@dataclass
class Step:
    """Handle yielded by `step()`. Attach results, notes and warnings to the open step."""

    number: str
    title: str
    _outcome: str = "success"
    _fields: dict[str, Any] = field(default_factory=dict)
    _started: float = field(default_factory=time.perf_counter)

    def result(self, **fields: Any) -> None:
        """Fields to print on the closing line — counts, ids, sizes."""
        self._fields.update(fields)

    def note(self, event: str, **fields: Any) -> None:
        """An informational line inside this step."""
        _log.info(event, step=f"{MARK_INSIDE} {self.number}", **fields)

    def ok(self, event: str, **fields: Any) -> None:
        """A green line inside this step — one item of many that went well."""
        _log.info(event, step=f"{MARK_INSIDE} {self.number}", outcome="success", **fields)

    def warn(self, event: str, **fields: Any) -> None:
        """A warning inside this step. The closing line turns yellow unless it later fails."""
        self._degrade("warning")
        _log.warning(event, step=f"{MARK_WARNING} {self.number}", **fields)

    def fail(self, event: str, **fields: Any) -> None:
        """Record a failure without raising — for code that reports errors as results."""
        self._degrade("error")
        _log.error(event, step=f"{MARK_ERROR} {self.number}", **fields)

    @property
    def outcome(self) -> str:
        return self._outcome

    def _degrade(self, outcome: str) -> None:
        if _OUTCOME_RANK[outcome] > _OUTCOME_RANK[self._outcome]:
            self._outcome = outcome

    def _elapsed(self) -> str:
        return f"{time.perf_counter() - self._started:.2f}s"


@contextmanager
def step(title: str, **fields: Any) -> Iterator[Step]:
    """Open a numbered step around a block of work.

    Logs `> N title` on entry and `+ N title` (green), `! N title` (yellow) or `x N title`
    (red) on exit, with elapsed time and whatever `result()` attached. An exception escaping
    the block is logged red — type and redacted message, no locals — and **re-raised
    unchanged**: a step observes control flow, it never alters it.
    """
    stack = _STACK.get()
    parent = stack[-1] if stack else _root()
    parent.children += 1
    number = f"{parent.number}.{parent.children}" if parent.number else str(parent.children)
    frame = _Frame(number=number)
    token = _STACK.set((*stack, frame))
    current = Step(number=number, title=title)
    _log.info(title, step=f"{MARK_START} {number}", **fields)
    try:
        yield current
    except BaseException as exc:
        # BaseException, so a Ctrl+C mid-step is still closed out in red before it
        # propagates. Redacted: an exception message is the classic credential leak.
        _log.error(
            title,
            step=f"{MARK_ERROR} {number}",
            elapsed=current._elapsed(),
            error=redact_secrets(f"{type(exc).__name__}: {exc}")[:500],
            **current._fields,
        )
        raise
    else:
        mark = _OUTCOME_MARKS[current.outcome]
        closing = {"step": f"{mark} {number}", "elapsed": current._elapsed(), **current._fields}
        if current.outcome == "success":
            _log.info(title, outcome="success", **closing)
        elif current.outcome == "warning":
            _log.warning(title, **closing)
        else:
            _log.error(title, **closing)
    finally:
        _STACK.reset(token)


# ---------------------------------------------------------------------------------------
# Plain lines, for scripts
# ---------------------------------------------------------------------------------------


def info(event: str, **fields: Any) -> None:
    _console.info(event, **fields)


def success(event: str, **fields: Any) -> None:
    _console.info(event, outcome="success", **fields)


def warning(event: str, **fields: Any) -> None:
    _console.warning(event, **fields)


def error(event: str, **fields: Any) -> None:
    _console.error(event, **fields)


# ---------------------------------------------------------------------------------------
# Processors
# ---------------------------------------------------------------------------------------


def _attach_step(_logger: WrappedLogger, _name: str, event_dict: EventDict) -> EventDict:
    """Label an ordinary log line with the step it happened inside. Explicit `step` wins."""
    if "step" not in event_dict:
        number = current_step()
        if number is not None:
            event_dict["step"] = f"{MARK_INSIDE} {number}"
    return event_dict


def _promote_success(_logger: WrappedLogger, _name: str, event_dict: EventDict) -> EventDict:
    """Console only: `outcome=success` at info becomes the green `success` level."""
    if event_dict.get("outcome") == "success" and event_dict.get("level") == "info":
        event_dict["level"] = "success"
        del event_dict["outcome"]
    return event_dict


def _redact(_logger: WrappedLogger, _name: str, event_dict: EventDict) -> EventDict:
    """Every string that will be rendered goes through `redact_secrets`. No exceptions."""
    for key, value in list(event_dict.items()):
        if isinstance(value, str):
            event_dict[key] = redact_secrets(value)
    return event_dict


def _renderer(*, colours: bool) -> ConsoleRenderer:
    bright, reset, dim = (BRIGHT, RESET_ALL, DIM) if colours else ("", "", "")
    level_styles = (
        {level: colour + BRIGHT for level, colour in LEVEL_COLOURS.items()}
        if colours
        else dict.fromkeys(LEVEL_COLOURS, "")
    )
    return ConsoleRenderer(
        columns=[
            Column("timestamp", KeyValueColumnFormatter(None, dim, reset, value_repr=str)),
            Column("level", LogLevelColumnFormatter(level_styles, reset_style=reset)),
            Column("step", KeyValueColumnFormatter(None, bright, reset, value_repr=str, width=8)),
            Column("event", KeyValueColumnFormatter(None, bright, reset, value_repr=str, width=30)),
            Column("", KeyValueColumnFormatter(dim, "", reset, value_repr=_value_repr)),
        ],
        exception_formatter=plain_traceback,
        sort_keys=True,
    )


def _value_repr(value: object) -> str:
    """Strings with spaces are quoted so `key=value` pairs stay parseable by eye."""
    if isinstance(value, str):
        if set(value) & {" ", "\t", "=", "\r", "\n", '"', "'"}:
            return repr(value)
        return value
    return repr(value)


def _pad_missing_step(_logger: WrappedLogger, _name: str, event_dict: EventDict) -> EventDict:
    """Console only: a line outside any step gets a blank step column, so columns line up."""
    event_dict.setdefault("step", "")
    return event_dict


def _is_tty(stream: TextIO) -> bool:
    return bool(getattr(stream, "isatty", lambda: False)())


def _setting(name: str) -> str | None:
    """The process environment first, then `.env` - the same file `Settings` reads.

    `Settings` cannot be used here: it requires `DATABASE_URL`, and the console must work
    in a process that has no database at all. So the two console keys are read the way
    pydantic-settings would read them, without the rest of the model coming along.
    """
    value = os.environ.get(name)
    if value is not None:
        return value
    try:
        from dotenv import dotenv_values

        return dotenv_values(ENV_FILE).get(name) if ENV_FILE.exists() else None
    except Exception:  # noqa: BLE001 - a broken .env must not stop logging from starting
        return None


def _want_colours(stream: TextIO, override: bool | None) -> bool:
    if override is not None:
        return override
    if _setting("NO_COLOR"):
        return False
    if _setting("FORCE_COLOR"):
        return True
    return _is_tty(stream)


# ---------------------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------------------


def configure_logging(
    *,
    fmt: str | None = None,
    colours: bool | None = None,
    stream: TextIO | None = None,
    level: str | None = None,
) -> None:
    """Configure structlog and the standard library to one shape. Idempotent.

    Call once at the top of `main()` in every script. Arguments override the environment
    (`LOG_FORMAT`, `NO_COLOR`/`FORCE_COLOR`, `LOG_LEVEL`) and exist so tests can pin them.
    """
    fmt = (fmt or _setting("LOG_FORMAT") or "console").lower()
    if fmt not in {"console", "json"}:
        raise ValueError(f"LOG_FORMAT must be 'console' or 'json', not {fmt!r}")
    pinned_stream = stream
    stream = stream or sys.stdout
    level_name = (level or _setting("LOG_LEVEL") or "INFO").upper()
    min_level = logging.getLevelName(level_name)
    if not isinstance(min_level, int):
        raise ValueError(f"LOG_LEVEL {level_name!r} is not a logging level")

    shared: list[Any] = [
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        # UTC, said explicitly (TG21: schedules and storage are UTC; so is the console).
        structlog.processors.TimeStamper(fmt="%Y-%m-%d %H:%M:%SZ", utc=True),
        _attach_step,
        # Tracebacks become a string here, so redaction below covers them too.
        structlog.processors.format_exc_info,
        _redact,
    ]
    renderer: Any
    if fmt == "json":
        renderer = structlog.processors.JSONRenderer(sort_keys=True)
        tail: list[Any] = []
    else:
        use_colours = _want_colours(stream, colours)
        if use_colours and sys.platform == "win32" and _is_tty(stream):
            # Only for a real console. colorama strips ANSI from anything that is not a
            # terminal, which would silently defeat FORCE_COLOR on a pipe.
            _enable_windows_ansi()
        renderer = _renderer(colours=use_colours)
        tail = [_promote_success, _pad_missing_step]

    structlog.configure(
        processors=[*shared, *tail, renderer],
        wrapper_class=structlog.make_filtering_bound_logger(min_level),
        # With no explicit stream the logger resolves `sys.stdout` at call time, which is
        # what lets pytest's capsys see our output. A pinned stream is for tests and files.
        logger_factory=structlog.PrintLoggerFactory(file=pinned_stream),
        cache_logger_on_first_use=False,
    )

    # The standard library — alembic, apscheduler, uvicorn, sqlalchemy — through the same
    # renderer, so a foreign line looks like ours and is redacted like ours.
    formatter = structlog.stdlib.ProcessorFormatter(
        processors=[structlog.stdlib.ProcessorFormatter.remove_processors_meta, *tail, renderer],
        foreign_pre_chain=shared,
    )
    root = logging.getLogger()
    for existing in list(root.handlers):
        if existing.get_name() == _HANDLER_NAME:
            root.removeHandler(existing)
    handler = logging.StreamHandler(stream)
    handler.set_name(_HANDLER_NAME)
    handler.setFormatter(formatter)
    root.addHandler(handler)
    root.setLevel(min_level)
    for name, floor in _QUIET_LOGGERS.items():
        logging.getLogger(name).setLevel(max(floor, min_level))

    reset_steps()


def _enable_windows_ansi() -> None:
    """Legacy `conhost` needs colorama to translate ANSI; Windows Terminal does not mind."""
    try:
        import colorama

        colorama.just_fix_windows_console()
    except Exception:  # noqa: BLE001 - colour is cosmetic; never fail a run over it
        pass

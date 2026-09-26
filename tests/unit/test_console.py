"""The console layer: colour by meaning, numbering by nesting, and nothing secret printed.

Three properties are the point of this file, in order of how much they matter:

1. **Redaction is unconditional.** Event text, values, exception messages and tracebacks are
   all redacted, in console mode and in JSON mode. Tracebacks are plain — no local variables
   — because an exception's locals routinely hold the request that failed, key included.
2. **A step never changes control flow.** An exception escaping a step is logged and
   re-raised unchanged.
3. **Numbers come from nesting**, restart on reset, and are independent per thread.
"""

from __future__ import annotations

import io
import json
import logging
import re
import threading
from collections.abc import Iterator
from pathlib import Path

import pytest
import structlog
from structlog.dev import BLUE, GREEN, RED, YELLOW

from packages.common import console
from packages.common.console import (
    configure_logging,
    current_step,
    error,
    info,
    reset_steps,
    step,
    success,
    warning,
)

ESC = "\x1b["


class _Tty(io.StringIO):
    """A stream that claims to be a terminal, so colour auto-detection can be exercised."""

    def isatty(self) -> bool:
        return True


@pytest.fixture(autouse=True)
def _isolated_logging() -> Iterator[None]:
    """Every test configures its own stream; none may leak into the next test or the suite."""
    root = logging.getLogger()
    before_level = root.level
    yield
    structlog.reset_defaults()
    for handler in list(root.handlers):
        if handler.get_name() == "quant_model.console":
            root.removeHandler(handler)
    root.setLevel(before_level)
    for name in ("httpx", "httpcore", "apscheduler"):
        logging.getLogger(name).setLevel(logging.NOTSET)
    reset_steps()


def _lines(buf: io.StringIO) -> list[str]:
    return [line for line in buf.getvalue().splitlines() if line.strip()]


def _plain(line: str) -> str:
    """The line with colour codes removed — for content checks; colour is checked apart."""
    return re.sub("\x1b\\[[0-9;]*m", "", line)


# --------------------------------------------------------------------------------------
# Numbering
# --------------------------------------------------------------------------------------


def test_steps_are_numbered_by_nesting() -> None:
    buf = io.StringIO()
    configure_logging(colours=False, stream=buf)
    seen: list[str] = []
    with step("one"):
        seen.append(current_step() or "")
        with step("one-one"):
            seen.append(current_step() or "")
        with step("one-two"):
            seen.append(current_step() or "")
            with step("deep"):
                seen.append(current_step() or "")
    with step("two"):
        seen.append(current_step() or "")
    assert seen == ["1", "1.1", "1.2", "1.2.1", "2"]
    assert current_step() is None


def test_numbering_restarts_on_reset() -> None:
    configure_logging(colours=False, stream=io.StringIO())
    with step("a"):
        pass
    with step("b"):
        assert current_step() == "2"
    reset_steps()
    with step("c"):
        assert current_step() == "1"


def test_each_thread_numbers_independently() -> None:
    configure_logging(colours=False, stream=io.StringIO())
    with step("main-1"):
        pass
    results: dict[str, str | None] = {}

    def worker(name: str) -> None:
        with step(f"{name}-first"):
            results[name] = current_step()

    threads = [threading.Thread(target=worker, args=(n,)) for n in ("t1", "t2")]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert results == {"t1": "1", "t2": "1"}
    with step("main-2"):
        assert current_step() == "2"


# --------------------------------------------------------------------------------------
# Colour by meaning
# --------------------------------------------------------------------------------------


def test_levels_carry_their_colours() -> None:
    buf = io.StringIO()
    configure_logging(colours=True, stream=buf)
    info("an info line")
    success("a success line")
    warning("a warning line")
    error("an error line")
    lines = _lines(buf)
    assert len(lines) == 4
    assert BLUE in lines[0] and "info" in lines[0]
    assert GREEN in lines[1] and "success" in lines[1]
    assert YELLOW in lines[2] and "warning" in lines[2]
    assert RED in lines[3] and "error" in lines[3]
    assert GREEN not in lines[0] and BLUE not in lines[1]


def test_a_step_opens_blue_and_closes_green() -> None:
    buf = io.StringIO()
    configure_logging(colours=True, stream=buf)
    with step("fetch") as s:
        s.result(http_status=200)
    opening, closing = _lines(buf)
    assert BLUE in opening and GREEN in closing
    assert "> 1" in _plain(opening) and "fetch" in _plain(opening)
    assert "+ 1" in _plain(closing) and "http_status=200" in _plain(closing)
    assert "elapsed=" in _plain(closing)


def test_a_warned_step_closes_yellow_and_a_failed_step_closes_red() -> None:
    buf = io.StringIO()
    configure_logging(colours=True, stream=buf)
    with step("write") as s:
        s.warn("no rows written", rows_inserted=0)
    with step("run") as s:
        s.warn("slow")
        s.fail("job reported an error", error="boom")
    lines = _lines(buf)
    assert YELLOW in lines[1] and "! 1" in lines[1] and "no rows written" in lines[1]
    assert YELLOW in lines[2] and "! 1" in lines[2] and "write" in lines[2]
    # A failure outranks an earlier warning; the closing line is red.
    assert RED in lines[-1] and "x 2" in lines[-1] and "run" in lines[-1]


def test_no_colour_when_asked_for_none() -> None:
    buf = io.StringIO()
    configure_logging(colours=False, stream=buf)
    with step("plain"):
        warning("w")
        error("e")
    assert ESC not in buf.getvalue()
    assert "> 1" in buf.getvalue() and "+ 1" in buf.getvalue()


def test_colour_is_auto_on_for_a_terminal_and_no_color_wins(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("NO_COLOR", raising=False)
    monkeypatch.delenv("FORCE_COLOR", raising=False)
    tty = _Tty()
    configure_logging(stream=tty)
    info("hello")
    assert ESC in tty.getvalue()

    monkeypatch.setenv("NO_COLOR", "1")
    tty = _Tty()
    configure_logging(stream=tty)
    info("hello")
    assert ESC not in tty.getvalue()


def test_a_pipe_gets_no_colour_by_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("NO_COLOR", raising=False)
    monkeypatch.delenv("FORCE_COLOR", raising=False)
    buf = io.StringIO()  # isatty() is False
    configure_logging(stream=buf)
    info("hello")
    assert ESC not in buf.getvalue()


# --------------------------------------------------------------------------------------
# Control flow and context
# --------------------------------------------------------------------------------------


def test_an_exception_is_logged_red_and_re_raised_unchanged() -> None:
    buf = io.StringIO()
    configure_logging(colours=True, stream=buf)
    with pytest.raises(ValueError, match="boom"), step("outer"), step("inner"):
        raise ValueError("boom")
    lines = _lines(buf)
    assert RED in lines[2] and "x 1.1" in lines[2] and "ValueError: boom" in lines[2]
    assert RED in lines[3] and "x 1" in lines[3]
    assert current_step() is None, "the stack must unwind even when the body raises"


def test_lines_logged_inside_a_step_carry_its_number() -> None:
    buf = io.StringIO()
    configure_logging(colours=False, stream=buf)
    with step("parse"):
        structlog.get_logger("packages.ingestion.something").warning(
            "portal_rows_skipped_wrong_measure", count=3
        )
    inner = _lines(buf)[1]
    assert "  1 " in inner and "portal_rows_skipped_wrong_measure" in inner and "count=3" in inner


def test_a_line_outside_any_step_stays_aligned() -> None:
    buf = io.StringIO()
    configure_logging(colours=False, stream=buf)
    with step("a"):
        pass
    info("outside")
    stepped, _, outside = _lines(buf)
    assert stepped.index("a") == outside.index("outside"), "event column must line up"


# --------------------------------------------------------------------------------------
# Redaction — the property that must hold before any other
# --------------------------------------------------------------------------------------

#: Built at runtime and deliberately low-entropy, so the secret scanner in pre-commit does
#: not mistake the fixture for a real key. The redactor matches on the parameter name.
SECRET_VALUE = "fake" * 5
SECRET = f"api_key={SECRET_VALUE}"


@pytest.mark.invariant
def test_values_and_event_text_are_redacted() -> None:
    buf = io.StringIO()
    configure_logging(colours=False, stream=buf)
    info(f"request {SECRET} failed", url=f"https://x/?{SECRET}")
    out = buf.getvalue()
    assert SECRET_VALUE not in out
    assert out.count("<redacted>") == 2


@pytest.mark.invariant
def test_an_exception_message_inside_a_step_is_redacted() -> None:
    buf = io.StringIO()
    configure_logging(colours=False, stream=buf)
    with pytest.raises(ConnectionError), step("fetch"):
        raise ConnectionError(f"GET https://x/?{SECRET} failed")
    assert SECRET_VALUE not in buf.getvalue()
    assert "api_key=<redacted>" in buf.getvalue()


@pytest.mark.invariant
def test_tracebacks_are_plain_and_never_print_locals() -> None:
    """structlog's default traceback formatter prints local variables. Ours must not."""
    buf = io.StringIO()
    configure_logging(colours=False, stream=buf)
    log = structlog.get_logger("t")
    try:
        held_in_a_local = "ZZZ-LOCAL-CREDENTIAL-ZZZ"  # noqa: F841 - the point is that it exists
        raise RuntimeError("failed with the credential in scope")
    except RuntimeError:
        log.error("boom", exc_info=True)
    out = buf.getvalue()
    assert "Traceback" in out
    assert "ZZZ-LOCAL-CREDENTIAL-ZZZ" not in out


@pytest.mark.invariant
def test_json_mode_is_redacted_too() -> None:
    buf = io.StringIO()
    configure_logging(fmt="json", stream=buf)
    with step("fetch"):
        info("request", url=f"https://x/?{SECRET}")
    for line in _lines(buf):
        record = json.loads(line)
        assert SECRET_VALUE not in line
        assert "step" in record
    assert ESC not in buf.getvalue()


def test_json_mode_keeps_standard_levels() -> None:
    buf = io.StringIO()
    configure_logging(fmt="json", stream=buf)
    success("done", jobs=3)
    (record,) = [json.loads(line) for line in _lines(buf)]
    assert record["level"] == "info"
    assert record["outcome"] == "success"
    assert record["jobs"] == 3


# --------------------------------------------------------------------------------------
# Standard-library integration and configuration hygiene
# --------------------------------------------------------------------------------------


def test_stdlib_logging_is_rendered_and_redacted() -> None:
    buf = io.StringIO()
    configure_logging(colours=False, stream=buf)
    logging.getLogger("alembic.runtime.migration").info("Running upgrade %s", "0008 -> 0009")
    logging.getLogger("some.library").warning("request to https://x/?%s failed", SECRET)
    out = buf.getvalue()
    assert "Running upgrade 0008 -> 0009" in out
    assert SECRET_VALUE not in out and "api_key=<redacted>" in out


def test_url_logging_libraries_are_held_at_warning() -> None:
    """httpx's INFO line is the full request URL; for a keyed API that is the key."""
    configure_logging(colours=False, stream=io.StringIO())
    assert logging.getLogger("httpx").level == logging.WARNING
    assert logging.getLogger("httpcore").level == logging.WARNING


def test_configure_is_idempotent() -> None:
    configure_logging(colours=False, stream=io.StringIO())
    configure_logging(colours=False, stream=io.StringIO())
    ours = [h for h in logging.getLogger().handlers if h.get_name() == "quant_model.console"]
    assert len(ours) == 1


def test_log_level_floor_is_honoured() -> None:
    buf = io.StringIO()
    configure_logging(colours=False, stream=buf, level="WARNING")
    info("hidden")
    warning("shown")
    assert "hidden" not in buf.getvalue() and "shown" in buf.getvalue()


def test_bad_format_and_level_are_refused() -> None:
    with pytest.raises(ValueError, match="LOG_FORMAT"):
        configure_logging(fmt="xml", stream=io.StringIO())
    with pytest.raises(ValueError, match="LOG_LEVEL"):
        configure_logging(level="LOUD", stream=io.StringIO())


def test_markers_are_ascii() -> None:
    """A tick would raise UnicodeEncodeError on a cp1252 pipe — the moment a log is kept."""
    for mark in (
        console.MARK_START,
        console.MARK_SUCCESS,
        console.MARK_WARNING,
        console.MARK_ERROR,
        console.MARK_INSIDE,
    ):
        mark.encode("ascii")


def test_settings_come_from_the_environment_then_dot_env(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """`.env` is the file Settings reads; a console key placed there must take effect too."""
    env_file = tmp_path / ".env"
    env_file.write_text("LOG_FORMAT=json\nLOG_LEVEL=WARNING\n", encoding="utf-8")
    monkeypatch.setattr(console, "ENV_FILE", env_file)
    monkeypatch.delenv("LOG_FORMAT", raising=False)
    monkeypatch.delenv("LOG_LEVEL", raising=False)

    buf = io.StringIO()
    configure_logging(stream=buf)
    info("hidden by the .env level")
    warning("shown")
    (only,) = _lines(buf)
    assert json.loads(only)["event"] == "shown", ".env should have selected json + WARNING"

    monkeypatch.setenv("LOG_FORMAT", "console")
    buf = io.StringIO()
    configure_logging(stream=buf)
    warning("shown again")
    assert not buf.getvalue().lstrip().startswith("{"), "the environment must beat .env"

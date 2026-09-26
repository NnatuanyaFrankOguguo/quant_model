r"""Run the API.

    .venv\Scripts\python.exe scripts\run_api.py                # 127.0.0.1:8000
    .venv\Scripts\python.exe scripts\run_api.py --port 8010

Use this rather than `python -m uvicorn services.api.main:app` on Windows. The plain command
works until the first client that gives up on a request, and then the API stops answering
for good while its process stays up - which reads as "the database is slow" or "the page is
broken" rather than as a dead server.

## Why, measured rather than suspected

uvicorn picks `asyncio.ProactorEventLoop` on Windows whenever it is not running a reloader
or workers. The Proactor loop accepts connections with `AcceptEx`, and when a client resets
a connection before that accept completes, Windows reports `WinError 64` ("the specified
network name is no longer available"). CPython's handler for that case in
`BaseProactorEventLoop._start_serving` logs "Accept failed on a socket" and then calls
`sock.close()` - on the **listening** socket. One impatient client and nothing is accepted
again.

Impatient clients are not hypothetical here; the web app is one by design. `apps/web`
aborts a fetch after its budget (`AbortSignal.timeout`), Next aborts in-flight fetches on
navigation, and every `curl --max-time` in a verification script does the same. The API
died four times in one session on 2026-09-25 under exactly that load.

Reproduced on this machine against both loops, 400 connections reset per burst:

    default (Proactor)   not answering after the first burst   2 x WinError 64
    Selector             answering after three bursts           0 x WinError 64

The Selector loop does not use `AcceptEx`, so the case never arises. What it gives up on
Windows is asyncio subprocess support and more than ~512 concurrent sockets; the API uses
neither - it has no asyncio subprocesses and it serves one web app on one machine.

Everywhere else the default loop is left alone.
"""

from __future__ import annotations

import argparse
import sys

import uvicorn

#: `uvicorn.Config.get_loop_factory` treats a value that is not one of its named loops as
#: an import string for a loop factory, and `asyncio.SelectorEventLoop` is one.
WINDOWS_LOOP = "asyncio:SelectorEventLoop"


def loop_setting(platform: str = sys.platform) -> str:
    """The `loop` value for uvicorn on this platform. Separate so a test can assert it."""
    return WINDOWS_LOOP if platform == "win32" else "auto"


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the quant_model API.")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--log-level", default="warning")
    args = parser.parse_args()

    uvicorn.run(
        "services.api.main:app",
        host=args.host,
        port=args.port,
        log_level=args.log_level,
        loop=loop_setting(),
    )


if __name__ == "__main__":
    main()

"""`scripts/run_api.py` must run the API on the Selector loop on Windows.

The launcher exists because of one line in CPython: when an accept fails on the Proactor
loop, `BaseProactorEventLoop._start_serving` closes the *listening* socket. A single client
that resets its connection mid-accept - which the web app does every time a fetch outruns
its budget - leaves the API process alive and permanently deaf. Reproduced on 2026-09-25:
the Proactor loop stopped answering after one burst of 400 reset connections; the Selector
loop answered after three.

These tests run on any platform. CI is not Windows, so they assert the Windows *choice*
explicitly rather than trusting `sys.platform` to exercise it.
"""

from __future__ import annotations

import asyncio

import uvicorn

from scripts.run_api import WINDOWS_LOOP, loop_setting


def test_windows_gets_the_selector_loop() -> None:
    assert loop_setting("win32") == WINDOWS_LOOP


def test_every_other_platform_keeps_uvicorns_default() -> None:
    """The fix is for a Windows defect and is not imposed where it is not needed."""
    assert loop_setting("linux") == "auto"
    assert loop_setting("darwin") == "auto"


def test_uvicorn_resolves_the_windows_setting_to_a_selector_loop() -> None:
    """The string is only a fix if uvicorn reads it the way the launcher assumes.

    `Config.get_loop_factory` treats a non-named `loop` as an import string for a loop
    factory. If a uvicorn release stopped doing that, the launcher would quietly fall back
    to - or fail over - the loop it exists to avoid, so the resolution itself is asserted.
    """
    config = uvicorn.Config("services.api.main:app", loop=WINDOWS_LOOP)
    factory = config.get_loop_factory()
    assert factory is asyncio.SelectorEventLoop

    loop = factory()
    try:
        assert isinstance(loop, asyncio.SelectorEventLoop)
        assert not isinstance(loop, getattr(asyncio, "ProactorEventLoop", ()))
    finally:
        loop.close()

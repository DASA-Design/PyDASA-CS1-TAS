# -*- coding: utf-8 -*-
"""
Module runtime/os_timer.py
==========================

Single owner of the Windows `winmm` timer-resolution call. Anywhere else in `src/experiment/` that needs sub-15-ms `asyncio.sleep` reaches in through this module so the platform-specific call lives in exactly one place.
"""
# native python modules
from __future__ import annotations

import contextlib
import ctypes
import sys


@contextlib.contextmanager
def windows_timer_resolution(period_ms: int = 1):
    """*windows_timer_resolution()* tighten the Windows global system timer for the lifetime of the block.

    On Windows the system timer ticks every ~15 ms by default, so any `asyncio.sleep` shorter than that oversleeps and the rate driver cannot meet high target rates. Inside the `with` block, `winmm.timeBeginPeriod(period_ms)` requests a tighter floor (1 ms in practice) and the matching `timeEndPeriod` on exit releases it. No-op on non-Windows hosts and on Windows hosts where `winmm.dll` cannot be loaded. Recipe from https://stackoverflow.com/q/77895160.

    Args:
        period_ms (int, milliseconds): requested timer floor. The OS clamps to the supported range (typically 1-15 ms).

    Yields:
        None: nothing to bind in `with ... as v:`; `v` is always `None`.
    """
    if sys.platform != "win32":
        yield
        return

    try:
        _winmm = ctypes.WinDLL("winmm")
    except (OSError, AttributeError):
        # winmm unavailable -> fall back to default resolution
        yield
        return

    _winmm.timeBeginPeriod(int(period_ms))
    try:
        yield
    finally:
        _winmm.timeEndPeriod(int(period_ms))

"""Windows timer-resolution wrapper.

Tightens the OS clock floor from ~15 ms down to ~1 ms inside a `with` block so `asyncio.sleep` can hit shorter intervals. No-op on POSIX. Single owner of `winmm.timeBeginPeriod` for the whole package.
"""

from __future__ import annotations

import contextlib
import ctypes
import sys
from collections.abc import Iterator


@contextlib.contextmanager
def windows_timer_resolution(period_ms: int = 1) -> Iterator[None]:
    """Tighten the Windows global system timer for the lifetime of the block.

    On Windows the system timer ticks every ~15 ms by default, so any `asyncio.sleep` shorter than that oversleeps and the rate driver cannot meet high target rates.

    Inside the `with` block, `winmm.timeBeginPeriod(period_ms)` requests a tighter floor (1 ms in practice) and the matching `timeEndPeriod` on exit releases it.

    No-op on non-Windows hosts and on Windows hosts where `winmm.dll` cannot be loaded. Recipe from https://stackoverflow.com/q/77895160.

    Args:
        period_ms (int, optional): requested timer floor in milliseconds. The OS clamps to the supported range (typically 1-15 ms). Defaults to 1.

    Yields:
        None: nothing to bind in `with ... as v:`; `v` is always `None`.
    """
    if sys.platform != "win32":
        yield
        return
    try:
        _winmm = ctypes.WinDLL("winmm")
    except OSError:
        yield
        return
    _winmm.timeBeginPeriod(int(period_ms))
    try:
        yield
    finally:
        _winmm.timeEndPeriod(int(period_ms))

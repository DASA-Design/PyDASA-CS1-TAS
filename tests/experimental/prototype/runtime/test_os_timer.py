"""Tests for `src.experimental.prototype.runtime.os_timer`.

**TestWindowsTimerResolution**:

- `test_yields_none`: the context manager yields `None` so callers cannot accidentally bind a value.
- `test_noop_posix`: on POSIX the manager is a no-op (no DLL load attempted).
- `test_winmm_load_fail`: on Windows a `WinDLL` load failure is swallowed silently so the rest of the apparatus still runs at default timer resolution.
- `test_calls_winmm`: on Windows `timeBeginPeriod` and the matching `timeEndPeriod` are issued when `winmm.dll` loads.
- `test_releases_on_exc`: exiting via exception still triggers `timeEndPeriod`, so a transient failure inside the block does not leak the tightened resolution.
- `test_param_int`: the `period_ms` argument is coerced to `int` before reaching `winmm`, defending against floats accidentally passed from JSON config.
"""

from __future__ import annotations

import sys
from unittest.mock import MagicMock, patch

import pytest

from src.experimental.prototype.runtime.os_timer import windows_timer_resolution


class TestWindowsTimerResolution:
    """Cross-platform timer-resolution context manager."""

    def test_yields_none(self) -> None:
        """`windows_timer_resolution()` yields `None` regardless of platform; the bound name is unusable on purpose."""
        with windows_timer_resolution() as _bound:
            assert _bound is None

    def test_noop_posix(self) -> None:
        """On non-Windows platforms the manager returns immediately without trying to load `winmm.dll`."""
        with patch.object(sys, "platform", "linux"):
            with windows_timer_resolution(period_ms=1) as _bound:
                assert _bound is None

    def test_winmm_load_fail(self) -> None:
        """On Windows, a `WinDLL("winmm")` failure is caught and the manager runs as a no-op so the rest of the apparatus is unaffected."""
        with patch.object(sys, "platform", "win32"):
            with patch("src.experimental.prototype.runtime.os_timer.ctypes") as _ctypes:
                _ctypes.WinDLL.side_effect = OSError("simulated winmm failure")
                with windows_timer_resolution(period_ms=1) as _bound:
                    assert _bound is None

    def test_calls_winmm(self) -> None:
        """On Windows, the manager calls `winmm.timeBeginPeriod(period_ms)` on entry and `timeEndPeriod(period_ms)` on exit."""
        _winmm = MagicMock()
        with patch.object(sys, "platform", "win32"):
            with patch("src.experimental.prototype.runtime.os_timer.ctypes") as _ctypes:
                _ctypes.WinDLL.return_value = _winmm
                with windows_timer_resolution(period_ms=2):
                    _winmm.timeBeginPeriod.assert_called_once_with(2)
                _winmm.timeEndPeriod.assert_called_once_with(2)

    def test_releases_on_exc(self) -> None:
        """Exiting via exception still triggers `timeEndPeriod`, so a transient failure inside the block does not leak the tightened resolution."""
        _winmm = MagicMock()
        with patch.object(sys, "platform", "win32"):
            with patch("src.experimental.prototype.runtime.os_timer.ctypes") as _ctypes:
                _ctypes.WinDLL.return_value = _winmm
                _entered = False
                with pytest.raises(RuntimeError, match="boom"):
                    with windows_timer_resolution(period_ms=1):
                        _entered = True
                        _msg = "boom"
                        raise RuntimeError(_msg)
                assert _entered is True
        _winmm.timeBeginPeriod.assert_called_once_with(1)
        _winmm.timeEndPeriod.assert_called_once_with(1)

    def test_param_int(self) -> None:
        """The `period_ms` argument is coerced to `int` before reaching `winmm`, defending against floats accidentally passed from JSON config."""
        _winmm = MagicMock()
        with patch.object(sys, "platform", "win32"):
            with patch("src.experimental.prototype.runtime.os_timer.ctypes") as _ctypes:
                _ctypes.WinDLL.return_value = _winmm
                with windows_timer_resolution(period_ms=3):
                    pass
        _winmm.timeBeginPeriod.assert_called_once_with(3)
        _winmm.timeEndPeriod.assert_called_once_with(3)

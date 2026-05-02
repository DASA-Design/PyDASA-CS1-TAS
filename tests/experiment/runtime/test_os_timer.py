# -*- coding: utf-8 -*-
"""
Module test_os_timer.py
=======================

Pin `windows_timer_resolution`: it must call `winmm.timeBeginPeriod` on entry and the matching `timeEndPeriod` on exit (with the same period), even if the body raises; and it must degrade to a no-op on non-Windows hosts and on Windows hosts where `winmm.dll` cannot be loaded.

    - **TestWindowsTimerResolution** ctxmgr yield + winmm call sequence + period passthrough + exception cleanup + winmm-load-failure fallback + non-Windows skip.
"""
# native python modules
import sys
from typing import List, Tuple
from unittest.mock import MagicMock, patch

# test stack
import pytest

# module under test
from src.experiment.runtime import windows_timer_resolution
from src.experiment.runtime import os_timer as _os_timer_mod


_IS_WINDOWS = sys.platform == "win32"


def _make_winmm_recorder() -> Tuple[MagicMock, List[Tuple[str, int]]]:
    """*_make_winmm_recorder()* build a fake `winmm` DLL handle whose `timeBeginPeriod` and `timeEndPeriod` attributes append `(name, period)` tuples to a shared list, so a test can assert call order and arguments.

    Returns:
        Tuple[MagicMock, List[Tuple[str, int]]]: the fake DLL object and the call-log list (mutated in place by the recorded calls).
    """
    _calls: List[Tuple[str, int]] = []
    _fake = MagicMock()
    _fake.timeBeginPeriod.side_effect = lambda _p: _calls.append(("begin", int(_p)))
    _fake.timeEndPeriod.side_effect = lambda _p: _calls.append(("end", int(_p)))
    return _fake, _calls


class TestWindowsTimerResolution:
    """**TestWindowsTimerResolution** ctxmgr yield value + winmm call sequence + period passthrough + cleanup-on-exception + winmm-load-failure fallback + non-Windows no-op."""

    def test_yields_none(self) -> None:
        """*test_yields_none()* `with windows_timer_resolution(1) as v: ...` binds `v is None` (the ctxmgr has no payload to expose)."""
        with windows_timer_resolution(1) as _v:
            assert _v is None

    def test_winmm_begin_end_called_in_order(self) -> None:
        """*test_winmm_begin_end_called_in_order()* on a simulated Windows host the call sequence is exactly `timeBeginPeriod(1)` on entry then `timeEndPeriod(1)` on exit, with the body running between the two."""
        _fake, _calls = _make_winmm_recorder()
        with patch.object(_os_timer_mod.sys, "platform", "win32"), \
             patch.object(_os_timer_mod.ctypes, "WinDLL", return_value=_fake) as _windll:
            with windows_timer_resolution(1):
                _calls.append(("body", 1))
        _windll.assert_called_once_with("winmm")
        assert _calls == [("begin", 1), ("body", 1), ("end", 1)]

    def test_period_passthrough(self) -> None:
        """*test_period_passthrough()* the integer `period_ms` argument is forwarded verbatim to both `timeBeginPeriod` and `timeEndPeriod` (no clamping or rewriting in the wrapper)."""
        _fake, _calls = _make_winmm_recorder()
        with patch.object(_os_timer_mod.sys, "platform", "win32"), \
             patch.object(_os_timer_mod.ctypes, "WinDLL", return_value=_fake):
            with windows_timer_resolution(7):
                pass
        assert _calls == [("begin", 7), ("end", 7)]

    def test_end_called_when_body_raises(self) -> None:
        """*test_end_called_when_body_raises()* an exception inside the `with` block still triggers `timeEndPeriod` (the `try / finally` releases the timer floor before the exception propagates)."""
        _fake, _calls = _make_winmm_recorder()
        with patch.object(_os_timer_mod.sys, "platform", "win32"), \
             patch.object(_os_timer_mod.ctypes, "WinDLL", return_value=_fake):
            with pytest.raises(RuntimeError, match="boom"):
                with windows_timer_resolution(1):
                    raise RuntimeError("boom")
        assert _calls == [("begin", 1), ("end", 1)]

    def test_winmm_load_failure_falls_back_to_noop(self) -> None:
        """*test_winmm_load_failure_falls_back_to_noop()* when `ctypes.WinDLL('winmm')` raises `OSError`, the ctxmgr swallows the failure, yields control, and never reaches `timeBeginPeriod` / `timeEndPeriod`."""
        _fake, _calls = _make_winmm_recorder()
        with patch.object(_os_timer_mod.sys, "platform", "win32"), \
             patch.object(_os_timer_mod.ctypes, "WinDLL", side_effect=OSError("not found")):
            with windows_timer_resolution(1):
                _calls.append(("body", 1))
        assert _calls == [("body", 1)]
        _fake.timeBeginPeriod.assert_not_called()
        _fake.timeEndPeriod.assert_not_called()

    def test_non_windows_skips_ctypes(self) -> None:
        """*test_non_windows_skips_ctypes()* on a simulated non-Windows host the ctxmgr never touches `ctypes.WinDLL` at all (the early-return short-circuits before any DLL lookup)."""
        with patch.object(_os_timer_mod.sys, "platform", "linux"), \
             patch.object(_os_timer_mod.ctypes, "WinDLL") as _windll:
            with windows_timer_resolution(1) as _v:
                assert _v is None
        _windll.assert_not_called()

    @pytest.mark.skipif(not _IS_WINDOWS,
                        reason="real-winmm probe needs a Windows host")
    def test_real_winmm_loads_on_windows(self) -> None:
        """*test_real_winmm_loads_on_windows()* without any patching, the ctxmgr loads the real `winmm.dll` and the begin / end pair completes without raising — guards against the wrapper drifting away from the actual Windows ABI."""
        with windows_timer_resolution(1):
            pass

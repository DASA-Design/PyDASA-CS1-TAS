"""Tests for `src.experimental.prototype.runtime.watchdog`.

**TestWatchParent**:

- `test_returns_daemon_thread`: `watch_parent` returns a started daemon thread named for the parent PID so it never blocks interpreter shutdown.
- `test_parent_alive_no_exit`: while `psutil.pid_exists` reports True the watchdog never invokes the orphan callback or `os._exit`.
- `test_orphan_calls_callback_then_exit`: when the parent disappears the callback fires once and `os._exit(0)` runs after the grace period.
- `test_orphan_no_callback`: with `on_orphan=None` the watchdog skips straight to `os._exit(0)`; no exception when the graceful path is unwired.
- `test_callback_exc_swallowed`: a callback that raises does not block the hard-exit fallback.
"""

from __future__ import annotations

import threading
import time
from unittest.mock import patch

from src.experimental.prototype.runtime.watchdog import watch_parent


class TestWatchParent:
    """Parent-PID poller that force-exits on orphan."""

    def test_returns_daemon_thread(self) -> None:
        """*test_returns_daemon_thread()* returns a started daemon thread tagged with the parent PID."""
        with patch("src.experimental.prototype.runtime.watchdog.psutil.pid_exists", return_value=True):
            _t = watch_parent(99999, poll_interval_s=10.0, grace_s=10.0)
        assert isinstance(_t, threading.Thread)
        assert _t.daemon is True
        assert _t.is_alive() is True
        assert "99999" in _t.name

    def test_parent_alive_no_exit(self) -> None:
        """*test_parent_alive_no_exit()* keeps polling while the parent is alive; callback and `os._exit` stay untouched."""
        _called: list[int] = []
        _exited: list[int] = []
        with patch("src.experimental.prototype.runtime.watchdog.psutil.pid_exists", return_value=True), \
             patch("src.experimental.prototype.runtime.watchdog.os._exit", side_effect=lambda code: _exited.append(code)):
            watch_parent(12345,
                         on_orphan=lambda: _called.append(1),
                         poll_interval_s=0.02,
                         grace_s=0.0)
            time.sleep(0.1)
        assert _called == []
        assert _exited == []

    def test_orphan_calls_callback_then_exit(self) -> None:
        """*test_orphan_calls_callback_then_exit()* fires the callback once and exits with code 0 after the grace period."""
        _called: list[int] = []
        _exited: list[int] = []

        def _exists(_pid: int) -> bool:
            return False
        with patch("src.experimental.prototype.runtime.watchdog.psutil.pid_exists", side_effect=_exists), \
             patch("src.experimental.prototype.runtime.watchdog.os._exit", side_effect=lambda code: _exited.append(code)):
            watch_parent(12345,
                         on_orphan=lambda: _called.append(1),
                         poll_interval_s=0.01,
                         grace_s=0.0)
            time.sleep(0.2)
        assert _called == [1]
        assert _exited == [0]

    def test_orphan_no_callback(self) -> None:
        """*test_orphan_no_callback()* skips straight to `os._exit(0)` when no graceful callback is provided."""
        _exited: list[int] = []
        with patch("src.experimental.prototype.runtime.watchdog.psutil.pid_exists", return_value=False), \
             patch("src.experimental.prototype.runtime.watchdog.os._exit", side_effect=lambda code: _exited.append(code)):
            watch_parent(12345, poll_interval_s=0.01, grace_s=0.0)
            time.sleep(0.2)
        assert _exited == [0]

    def test_callback_exc_swallowed(self) -> None:
        """*test_callback_exc_swallowed()* lets a raising callback through and still issues `os._exit(0)`."""
        _exited: list[int] = []

        def _bad_cb() -> None:
            _msg = "callback boom"
            raise RuntimeError(_msg)
        with patch("src.experimental.prototype.runtime.watchdog.psutil.pid_exists", return_value=False), \
             patch("src.experimental.prototype.runtime.watchdog.os._exit", side_effect=lambda code: _exited.append(code)):
            watch_parent(12345,
                         on_orphan=_bad_cb,
                         poll_interval_s=0.01,
                         grace_s=0.0)
            time.sleep(0.2)
        assert _exited == [0]

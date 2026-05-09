"""Tests for `src.experimental.prototype.runtime.waitress_process`.

**TestWaitressProcess**:

- `test_alive_pre_start`: `is_alive()` returns False before `start()`.
- `test_shutdown_pre_start`: `shutdown()` is a no-op before any child is spawned.
- `test_double_start`: a second `start()` raises (one process per instance).
- `test_wait_ready_no_server`: `wait_ready` on a not-started instance raises before the deadline.
- `test_real_lifecycle`: real spawn + `wait_ready` + `shutdown` against a Flask `/healthz` app over real TCP.
- `test_atexit_shutdown`: `_shutdown_live_processes` shuts down every still-alive WeakSet entry.
- `test_kill_escalation`: `shutdown` escalates `terminate()` -> `kill()` if the child stays alive past the join window.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import httpx
import pytest

from src.experimental.prototype.runtime import waitress_process as wp
from src.experimental.prototype.runtime.waitress_process import WaitressProcess
from tests.utils.exp.apps import build_healthz_flask_app
from tests.utils.exp.ports import PORT_MOCK, free_port


class TestWaitressProcess:
    """WSGI process spawner backed by waitress (cross-platform default)."""

    def test_alive_pre_start(self) -> None:
        """A fresh instance reports `is_alive() is False` until `start()` runs."""
        _p = WaitressProcess(build_healthz_flask_app, port=PORT_MOCK)
        assert _p.is_alive() is False

    def test_shutdown_pre_start(self) -> None:
        """`shutdown()` on a never-started instance returns cleanly with no error."""
        _p = WaitressProcess(build_healthz_flask_app, port=PORT_MOCK)
        _p.shutdown()
        assert _p.is_alive() is False

    def test_double_start(self) -> None:
        """Calling `start()` twice on the same instance raises `RuntimeError`."""
        _p = WaitressProcess(build_healthz_flask_app, port=free_port())
        try:
            _p.start()
            with pytest.raises(RuntimeError, match="called twice"):
                _p.start()
        finally:
            _p.shutdown()

    def test_wait_ready_no_server(self) -> None:
        """When no child is running and `/healthz` never answers, `wait_ready` raises once the timeout elapses."""
        _p = WaitressProcess(build_healthz_flask_app,
                             port=PORT_MOCK,
                             host="0.0.0.0")
        with pytest.raises(RuntimeError):
            _p.wait_ready(timeout_s=0.2)

    def test_real_lifecycle(self) -> None:
        """Spawn a real waitress child, wait for ready, hit `/healthz` over loopback, shut down. The full cycle completes without leaking the process."""
        _port = free_port()
        _p = WaitressProcess(build_healthz_flask_app, port=_port)
        _p.start()
        try:
            _p.wait_ready(timeout_s=20.0)
            _resp = httpx.get(f"http://127.0.0.1:{_port}/healthz", timeout=2.0)
            assert _resp.status_code == 200
            assert _resp.json() == {"status": "ok"}
        finally:
            _p.shutdown()
        assert _p.is_alive() is False

    def test_atexit_shutdown(self) -> None:
        """The atexit hook iterates the live-process registry and calls `shutdown()` on each entry; a crashed run leaves no zombies."""
        _p = WaitressProcess(build_healthz_flask_app, port=PORT_MOCK + 1)
        _mock_proc = MagicMock()
        _mock_proc.is_alive.return_value = True
        _ctx = MagicMock()
        _ctx.Process.return_value = _mock_proc
        with patch.object(wp.mp, "get_context", return_value=_ctx):
            _p.start()
        assert _p in wp._LIVE_PROCESSES  # noqa: SLF001
        wp._shutdown_live_processes()  # noqa: SLF001
        _mock_proc.terminate.assert_called_once()

    def test_kill_escalation(self) -> None:
        """If a child ignores `terminate()` and stays alive past the join window, `shutdown` follows up with `kill()`."""
        _p = WaitressProcess(build_healthz_flask_app, port=PORT_MOCK + 2)
        _mock_proc = MagicMock()
        _mock_proc.is_alive.return_value = True
        _ctx = MagicMock()
        _ctx.Process.return_value = _mock_proc
        with patch.object(wp.mp, "get_context", return_value=_ctx):
            _p.start()
        _p.shutdown()
        _mock_proc.terminate.assert_called_once()
        _mock_proc.kill.assert_called_once()

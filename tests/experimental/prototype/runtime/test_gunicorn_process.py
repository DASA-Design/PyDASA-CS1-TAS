"""Tests for `src.experimental.prototype.runtime.gunicorn_process`.

The Linux-only spawner is exercised on Windows by mocking `multiprocessing.get_context` and `httpx.get`. CI on Linux validates the real-spawn path through `WaitressProcess.test_real_lifecycle` (same surface).

**TestGunicornProcess**:

- `test_construct_raises_on_windows`: the constructor raises on Windows with a message pointing at `WaitressProcess`.
- `test_construct_succeeds_on_linux`: the constructor returns a usable instance on POSIX; `is_alive()` is False until `start()`.
- `test_shutdown_before_start_noop_linux`: `shutdown()` is a no-op before any child is spawned.
- `test_lifecycle_with_mocked_spawn`: full `start` -> `wait_ready` -> `shutdown` cycle with the spawn machinery and `httpx.get` mocked.
- `test_double_start_raises_linux`: a second `start()` raises (one process per instance).
- `test_wait_ready_child_exits`: `wait_ready` raises when the child exits early; the exit code appears in the message.
- `test_wait_ready_deadline`: `wait_ready` raises a deadline error when `/healthz` never returns 200 within the timeout.
- `test_atexit_shutdown_runs`: `_shutdown_live_processes` shuts down every still-alive entry on interpreter exit.
"""

from __future__ import annotations

import sys
from unittest.mock import MagicMock, patch

import httpx
import pytest

from src.experimental.prototype.runtime import gunicorn_process as gp
from src.experimental.prototype.runtime.gunicorn_process import GunicornProcess
from tests.utils.exp.apps import build_healthz_flask_app


class TestGunicornProcess:
    """Linux-only WSGI process spawner backed by gunicorn."""

    def test_construct_raises_on_windows(self) -> None:
        """Constructing on Windows raises `RuntimeError` and the message points to `WaitressProcess`. The check fires at construction time so platform mismatches surface immediately."""
        with patch.object(sys, "platform", "win32"):
            with pytest.raises(RuntimeError, match="Linux-only"):
                GunicornProcess(build_healthz_flask_app, port=8000)

    def test_construct_succeeds_on_linux(self) -> None:
        """On POSIX the constructor returns a usable instance; `is_alive()` is False until `start()` runs."""
        with patch.object(sys, "platform", "linux"):
            _p = GunicornProcess(build_healthz_flask_app, port=8000)
            assert _p.is_alive() is False

    def test_shutdown_before_start_noop_linux(self) -> None:
        """On POSIX, calling `shutdown()` on a never-started instance returns cleanly."""
        with patch.object(sys, "platform", "linux"):
            _p = GunicornProcess(build_healthz_flask_app, port=8000)
            _p.shutdown()
            assert _p.is_alive() is False

    def test_lifecycle_with_mocked_spawn(self) -> None:
        """Drive the full `start` -> `wait_ready` -> `shutdown` cycle with the spawn machinery and `httpx.get` mocked. Verifies `is_alive` flips True after `start`, a 200 response satisfies the readiness probe, and `shutdown` issues `terminate()`."""
        with patch.object(sys, "platform", "linux"):
            _p = GunicornProcess(build_healthz_flask_app, port=8765)
            _mock_proc = MagicMock()
            _mock_proc.is_alive.return_value = True
            _mock_proc.exitcode = None
            _ctx = MagicMock()
            _ctx.Process.return_value = _mock_proc
            with patch.object(gp.mp, "get_context", return_value=_ctx):
                _p.start()
            _ctx.Process.assert_called_once()
            assert _p.is_alive() is True
            _ok = MagicMock()
            _ok.status_code = 200
            with patch.object(gp.httpx, "get", return_value=_ok):
                _p.wait_ready(timeout_s=1.0)
            assert _p.active is False
            _p.shutdown()
            _mock_proc.terminate.assert_called_once()

    def test_double_start_raises_linux(self) -> None:
        """On POSIX, calling `start()` twice on the same instance raises `RuntimeError`."""
        with patch.object(sys, "platform", "linux"):
            _p = GunicornProcess(build_healthz_flask_app, port=9001)
            _mock_proc = MagicMock()
            _mock_proc.is_alive.return_value = True
            _ctx = MagicMock()
            _ctx.Process.return_value = _mock_proc
            with patch.object(gp.mp, "get_context", return_value=_ctx):
                _p.start()
                with pytest.raises(RuntimeError, match="called twice"):
                    _p.start()

    def test_wait_ready_child_exits(self) -> None:
        """When the child exits before answering `/healthz`, `wait_ready` raises and the exit code appears in the message."""
        with patch.object(sys, "platform", "linux"):
            _p = GunicornProcess(build_healthz_flask_app, port=9002)
            _mock_proc = MagicMock()
            _mock_proc.is_alive.return_value = False
            _mock_proc.exitcode = 1
            _ctx = MagicMock()
            _ctx.Process.return_value = _mock_proc
            with patch.object(gp.mp, "get_context", return_value=_ctx):
                _p.start()
            with pytest.raises(RuntimeError, match="exited before becoming ready"):
                _p.wait_ready(timeout_s=1.0)

    def test_wait_ready_deadline(self) -> None:
        """If the child stays alive but `/healthz` never returns 200 in time, `wait_ready` raises a deadline error."""
        with patch.object(sys, "platform", "linux"):
            _p = GunicornProcess(build_healthz_flask_app, port=9003)
            _mock_proc = MagicMock()
            _mock_proc.is_alive.return_value = True
            _ctx = MagicMock()
            _ctx.Process.return_value = _mock_proc
            with patch.object(gp.mp, "get_context", return_value=_ctx):
                _p.start()
            _msg = "no answer"
            with patch.object(gp.httpx, "get", side_effect=httpx.ConnectError(_msg)):
                with pytest.raises(RuntimeError, match="did not become ready"):
                    _p.wait_ready(timeout_s=0.2)

    def test_atexit_shutdown_runs(self) -> None:
        """The atexit hook walks its WeakSet registry and shuts down every still-alive `GunicornProcess` (snapshot iteration; safe under shrinkage)."""
        with patch.object(sys, "platform", "linux"):
            _p = GunicornProcess(build_healthz_flask_app, port=9004)
            _mock_proc = MagicMock()
            _mock_proc.is_alive.return_value = True
            _ctx = MagicMock()
            _ctx.Process.return_value = _mock_proc
            with patch.object(gp.mp, "get_context", return_value=_ctx):
                _p.start()
            assert _p in gp._LIVE_PROCESSES  # noqa: SLF001
            gp._shutdown_live_processes()  # noqa: SLF001
            _mock_proc.terminate.assert_called_once()

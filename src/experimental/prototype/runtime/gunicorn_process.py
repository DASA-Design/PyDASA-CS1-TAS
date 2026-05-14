"""Run a Flask app behind gunicorn in a separate child process (Linux only).

gunicorn relies on Unix `os.fork()` and won't import on Windows (it pulls `fcntl`). The constructor raises on Windows with a message pointing the caller at `WaitressProcess`. On Linux the surface matches `UvicornProcess` and `WaitressProcess` so the `ServerAdapter` facade can pick any of the three.

Two details worth knowing:

- `gunicorn` is imported via `try / except ImportError`. On Windows the fallback substitutes `object` as the base class for `_GunicornDriver`; the constructor's platform check ensures it is never instantiated there.
- The platform check lives in `_check_linux_or_raise()` so the type checker doesn't constant-fold `sys.platform` and mark the rest of `__init__` as unreachable.

Cleanup, tuning defaults: same `WeakSet` + `atexit` pattern as the other spawners; values from `data/config/method/experimental.json::server.gunicorn.*`.
"""

from __future__ import annotations

import atexit
import multiprocessing as mp
import multiprocessing.process as mp_process
import os
import sys
import time
import weakref
from typing import Any

import httpx

from src.experimental.prototype.runtime.os_timer import windows_timer_resolution
from src.experimental.prototype.runtime.watchdog import watch_parent

try:
    from gunicorn.app.base import BaseApplication  # type: ignore[import-not-found]
except ImportError:
    # POSIX-only fallback; never instantiated on Windows.
    BaseApplication = object  # type: ignore[assignment, misc]

# Runtime fallbacks for data/config/method/experimental.json::server.gunicorn.*.
_DFLT_WORKERS = 4
_DFLT_READY_TIMEOUT_S = 10.0
_DFLT_TERMINATE_GRACE_S = 5.0
_DFLT_KILL_GRACE_S = 2.0

# Live spawners; atexit cleans these up on exit.
_LIVE_PROCESSES: weakref.WeakSet["GunicornProcess"] = weakref.WeakSet()

# zero-arg picklable callable returning a Flask / WSGI app
AppFactory = Any


class _GunicornDriver(BaseApplication):  # type: ignore[misc, valid-type]
    """Minimal `BaseApplication` wrapper bridging an in-memory app to gunicorn's API.

    gunicorn is normally invoked from the shell; this wrapper is the supported way to drive it from Python by handing in a pre-built app and an options dict. Only ever instantiated inside the spawned child on Linux; on Windows the parent's constructor raises before reaching `start()`.
    """

    def __init__(self, app: Any, options: dict[str, Any]) -> None:
        """Record the app + options, then defer to `BaseApplication.__init__`.

        Args:
            app (Any): the WSGI app gunicorn should serve.
            options (dict[str, Any]): keys forwarded into gunicorn's config (e.g. `bind`, `workers`, `loglevel`).
        """
        self._app = app
        self._options = options
        super().__init__()

    def load_config(self) -> None:
        """Push every entry of `self._options` into gunicorn's config object."""
        for _key, _val in self._options.items():
            self.cfg.set(_key, _val)

    def load(self) -> Any:
        """Return the WSGI app gunicorn should serve.

        Returns:
            Any: the Flask / WSGI app handed in at construction time.
        """
        return self._app


def _check_linux_or_raise() -> None:
    """Raise `RuntimeError` if invoked on Windows; no-op on POSIX.

    Indirected through a helper so the type checker does not constant-fold `sys.platform == "win32"` and mark the rest of `GunicornProcess.__init__` as unreachable on Windows.

    Raises:
        RuntimeError: on Windows; the message names `WaitressProcess` as the cross-platform alternative.
    """
    if sys.platform == "win32":
        _msg = ("GunicornProcess is Linux-only (gunicorn requires os.fork). "
                "Use WaitressProcess on Windows.")
        raise RuntimeError(_msg)


def _worker_main(app_factory: AppFactory,
                 host: str,
                 port: int,
                 workers: int) -> None:
    """Child-process entry point: build the Flask app and serve it via gunicorn (Linux only).

    Top-level so it is picklable by name for `multiprocessing.spawn`. Only ever runs in the spawned child on Linux; the parent's constructor raises before reaching `start()` on Windows.

    Args:
        app_factory (AppFactory): zero-arg picklable callable returning the WSGI app.
        host (str): bind address.
        port (int): TCP port.
        workers (int): pre-fork worker count.
    """
    _parent_pid = os.getppid()
    watch_parent(_parent_pid)
    _app = app_factory()
    _options = {
        "bind": f"{host}:{port}",
        "workers": int(workers),
        "loglevel": "error",
        "accesslog": None,
    }
    with windows_timer_resolution(1):
        _GunicornDriver(_app, _options).run()


class GunicornProcess:
    """Flask / WSGI process spawner backed by gunicorn (Linux only).

    On Windows the constructor raises immediately so the caller learns about the platform mismatch at config-load time, not three layers deep into a spawn. Linux callers see a public surface identical to `WaitressProcess`.

    Attributes:
        active (bool): readiness-poll loop guard.
        _proc (mp_process.BaseProcess | None): child process; None until `start` is called.
        _app_factory (AppFactory): zero-arg picklable callable invoked inside the child.
        _port (int): TCP port the child binds to.
        _host (str): bind address.
        _workers (int): pre-fork worker count.
        _ready_timeout_s (float): default deadline for `wait_ready`.
        _terminate_grace_s (float): seconds to wait after `terminate()` before escalating to `kill()`.
        _kill_grace_s (float): seconds to wait after `kill()` before giving up.
    """

    def __init__(self,
                 app_factory: AppFactory,
                 port: int,
                 *,
                 host: str = "127.0.0.1",
                 workers: int = _DFLT_WORKERS,
                 ready_timeout_s: float = _DFLT_READY_TIMEOUT_S,
                 terminate_grace_s: float = _DFLT_TERMINATE_GRACE_S,
                 kill_grace_s: float = _DFLT_KILL_GRACE_S) -> None:
        """Record the spawn arguments without forking; call `start()` to create the child.

        Args:
            app_factory (AppFactory): zero-arg picklable callable returning the Flask / WSGI app.
            port (int): TCP port.
            host (str, optional): bind address. Defaults to `"127.0.0.1"`.
            workers (int, optional): pre-fork worker count. Defaults to the runtime fallback.
            ready_timeout_s (float, optional): default deadline for `wait_ready`. Defaults to the runtime fallback.
            terminate_grace_s (float, optional): seconds between `terminate()` and `kill()`. Defaults to the runtime fallback.
            kill_grace_s (float, optional): seconds after `kill()`. Defaults to the runtime fallback.

        Raises:
            RuntimeError: when constructed on Windows; gunicorn requires `os.fork()`. The message names `WaitressProcess` as the cross-platform alternative.
        """
        _check_linux_or_raise()
        self._app_factory = app_factory
        self._port = int(port)
        self._host = str(host)
        self._workers = int(workers)
        self._ready_timeout_s = float(ready_timeout_s)
        self._terminate_grace_s = float(terminate_grace_s)
        self._kill_grace_s = float(kill_grace_s)
        self._proc: mp_process.BaseProcess | None = None
        self.active: bool = False

    def is_alive(self) -> bool:
        """Report whether the child process exists and has not yet exited.

        Returns:
            bool: False before `start` and after the child terminates; True while the worker is running.
        """
        _ans = False
        if self._proc is not None and self._proc.is_alive():
            _ans = True
        return _ans

    def start(self) -> None:
        """Fork the child via the `spawn` start method; non-blocking.

        Raises:
            RuntimeError: when called more than once on the same instance; one process per instance.
        """
        if self._proc is not None:
            _msg = "GunicornProcess.start() called twice; one process per instance"
            raise RuntimeError(_msg)
        _ctx = mp.get_context("spawn")
        self._proc = _ctx.Process(target=_worker_main,
                                  args=(self._app_factory,
                                        self._host,
                                        self._port,
                                        self._workers),
                                  daemon=True)
        self._proc.start()
        _LIVE_PROCESSES.add(self)

    def wait_ready(self, timeout_s: float | None = None) -> None:
        """Block the parent until the child answers `/healthz` with 200.

        Args:
            timeout_s (float | None, optional): seconds to wait for the first 200. Defaults to None, which uses the constructor's `ready_timeout_s`.

        Raises:
            RuntimeError: when no 200 arrives before the deadline OR the child exits before becoming ready.
        """
        if timeout_s is None:
            _timeout = self._ready_timeout_s
        else:
            _timeout = float(timeout_s)
        if self._host == "0.0.0.0":
            _probe_host = "127.0.0.1"
        else:
            _probe_host = self._host
        _url = f"http://{_probe_host}:{self._port}/healthz"
        _deadline = time.perf_counter() + _timeout
        self.active = True
        while self.active:
            if self._proc is not None and not self._proc.is_alive():
                self.active = False
                _msg = (f"gunicorn child exited before becoming ready on {_url} "
                        f"(exit code: {self._proc.exitcode})")
                raise RuntimeError(_msg)
            try:
                _r = httpx.get(_url, timeout=0.5)
                if _r.status_code == 200:
                    self.active = False
            except (httpx.HTTPError, ConnectionError, OSError):
                pass
            if self.active and time.perf_counter() >= _deadline:
                _msg = f"gunicorn did not become ready within {_timeout} s on {_url}"
                raise RuntimeError(_msg)
            if self.active:
                time.sleep(0.05)

    def shutdown(self) -> None:
        """Clear the readiness-poll guard and end the child process.

        Sends `Process.terminate()` (SIGTERM), joins for `_terminate_grace_s`, escalates to `Process.kill()` + `_kill_grace_s` join.
        """
        self.active = False
        if self._proc is None:
            return
        if self._proc.is_alive():
            self._proc.terminate()
            self._proc.join(timeout=self._terminate_grace_s)
        if self._proc.is_alive():
            self._proc.kill()
            self._proc.join(timeout=self._kill_grace_s)


def _shutdown_live_processes() -> None:
    """Atexit safety net: SIGTERM every still-alive `GunicornProcess` on interpreter exit.

    The orchestrator's normal `try/finally` already calls `shutdown()`. This hook covers the abnormal-exit cases (KeyboardInterrupt, uncaught exception, hard crash) where leaked workers would otherwise hold their TCP ports past the parent's exit.
    """
    for _proc in list(_LIVE_PROCESSES):
        try:
            _proc.shutdown()
        except Exception:
            pass


# Crash-path safety net.
atexit.register(_shutdown_live_processes)

"""Run a Flask app behind waitress in a separate child process.

WSGI counterpart to `UvicornProcess`. waitress is pure-Python and runs on Windows + Linux, so this spawner is the cross-platform default for the Flask stack.

Cleanup follows the same pattern as the other spawners: a module-level `WeakSet` + `atexit` hook kills any survivors on interpreter exit. Tuning defaults come from `data/config/method/experimental.json::server.waitress.*`.
"""

from __future__ import annotations

import atexit
import multiprocessing as mp
import multiprocessing.process as mp_process
import os
import time
import weakref
from typing import Any

import httpx
from waitress import serve

from src.experimental.prototype.runtime.watchdog import watch_parent

# Runtime fallbacks for data/config/method/experimental.json::server.waitress.*.
_DFLT_BACKLOG = 16384
_DFLT_THREADS = 8
_DFLT_READY_TIMEOUT_S = 10.0
_DFLT_TERMINATE_GRACE_S = 5.0
_DFLT_KILL_GRACE_S = 2.0

# Live spawners; atexit cleans these up on exit.
_LIVE_PROCESSES: weakref.WeakSet["WaitressProcess"] = weakref.WeakSet()

# zero-arg picklable callable returning a Flask / WSGI app
AppFactory = Any


def _worker_main(app_factory: AppFactory,
                 host: str,
                 port: int,
                 backlog: int,
                 threads: int) -> None:
    """Child-process entry point: build the Flask app and serve it via waitress.

    Top-level so it is picklable by name for `multiprocessing.spawn`.

    Args:
        app_factory (AppFactory): zero-arg picklable callable returning the WSGI app (typically a Flask instance).
        host (str): bind address.
        port (int): TCP port.
        backlog (int): kernel socket-queue depth.
        threads (int): worker thread count for the WSGI thread pool.
    """
    _parent_pid = os.getppid()
    watch_parent(_parent_pid)
    _app = app_factory()
    serve(_app,
          host=str(host),
          port=int(port),
          backlog=int(backlog),
          threads=int(threads),
          _quiet=True)


class WaitressProcess:
    """Flask / WSGI process spawner backed by waitress (cross-platform default).

    Lifecycle: `start()` -> `wait_ready()` -> `shutdown()`. Public surface mirrors `UvicornProcess` so the `ServerAdapter` facade routes to either spawner with one config flag.

    Attributes:
        active (bool): readiness-poll loop guard.
        _proc (mp_process.BaseProcess | None): child process; None until `start` is called.
        _app_factory (AppFactory): zero-arg picklable callable invoked inside the child.
        _port (int): TCP port the child binds to.
        _host (str): bind address.
        _backlog (int): kernel socket-queue depth forwarded to `waitress.serve`.
        _threads (int): worker thread count for the WSGI thread pool.
        _ready_timeout_s (float): default deadline for `wait_ready`.
        _terminate_grace_s (float): seconds to wait after `terminate()` before escalating to `kill()`.
        _kill_grace_s (float): seconds to wait after `kill()` before giving up.
    """

    def __init__(self,
                 app_factory: AppFactory,
                 port: int,
                 *,
                 host: str = "127.0.0.1",
                 backlog: int = _DFLT_BACKLOG,
                 threads: int = _DFLT_THREADS,
                 ready_timeout_s: float = _DFLT_READY_TIMEOUT_S,
                 terminate_grace_s: float = _DFLT_TERMINATE_GRACE_S,
                 kill_grace_s: float = _DFLT_KILL_GRACE_S) -> None:
        """Record the spawn arguments without forking; call `start()` to create the child.

        Args:
            app_factory (AppFactory): zero-arg picklable callable returning the Flask / WSGI app.
            port (int): TCP port.
            host (str, optional): bind address. Defaults to `"127.0.0.1"`.
            backlog (int, optional): kernel socket-queue depth. Defaults to the runtime fallback.
            threads (int, optional): worker thread count. Defaults to the runtime fallback.
            ready_timeout_s (float, optional): default deadline for `wait_ready`. Defaults to the runtime fallback.
            terminate_grace_s (float, optional): seconds between `terminate()` and `kill()`. Defaults to the runtime fallback.
            kill_grace_s (float, optional): seconds after `kill()`. Defaults to the runtime fallback.
        """
        self._app_factory = app_factory
        self._port = int(port)
        self._host = str(host)
        self._backlog = int(backlog)
        self._threads = int(threads)
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
            _msg = "WaitressProcess.start() called twice; one process per instance"
            raise RuntimeError(_msg)
        _ctx = mp.get_context("spawn")
        self._proc = _ctx.Process(target=_worker_main,
                                  args=(self._app_factory,
                                        self._host,
                                        self._port,
                                        self._backlog,
                                        self._threads),
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
                _msg = f"waitress child exited before becoming ready on {_url} "
                _msg += f"(exit code: {self._proc.exitcode})"
                raise RuntimeError(_msg)
            try:
                _r = httpx.get(_url, timeout=0.5)
                if _r.status_code == 200:
                    self.active = False
            except (httpx.HTTPError, ConnectionError, OSError):
                pass
            if self.active and time.perf_counter() >= _deadline:
                _msg = f"waitress did not become ready within {_timeout} s on {_url}"
                raise RuntimeError(_msg)
            if self.active:
                time.sleep(0.05)

    def shutdown(self) -> None:
        """Clear the readiness-poll guard and end the child process.

        Sends `Process.terminate()` (SIGTERM on POSIX, `TerminateProcess` on Windows), joins for `_terminate_grace_s`, escalates to `Process.kill()` + `_kill_grace_s` join when the child does not exit.
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
    """Atexit safety net: SIGTERM every still-alive `WaitressProcess` on interpreter exit.

    The orchestrator's normal `try/finally` already calls `shutdown()`. This hook covers the abnormal-exit cases (KeyboardInterrupt, uncaught exception, hard crash) where leaked workers would otherwise hold their TCP ports past the parent's exit.
    """
    for _proc in list(_LIVE_PROCESSES):
        try:
            _proc.shutdown()
        except Exception:
            pass


# Crash-path safety net.
atexit.register(_shutdown_live_processes)

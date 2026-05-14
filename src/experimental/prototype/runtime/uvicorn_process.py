"""Run a FastAPI app behind uvicorn in a separate child process.

The parent talks to the served app over real TCP; the child owns its own GIL and event loop. The constructor takes an app *factory* rather than a built FastAPI instance, because Windows `spawn` cannot pickle a live app with bound routes and state — the factory is invoked inside the child so the app is built there.

Cleanup: every `start()` registers the spawner in a module-level `WeakSet`, and an `atexit` hook walks it on interpreter exit to kill any leftover children. The orchestrator normally calls `shutdown()` directly through `try/finally`; the atexit hook is the fallback for crashes and `KeyboardInterrupt`.

Tuning defaults (`_DFLT_*`) come from `data/config/method/experimental.json::server.uvicorn.*` via `runtime.config.load_server_cfg("uvicorn")`; the constants in this file are fallbacks for callers that skip the loader.
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
import uvicorn

from src.experimental.prototype.runtime.watchdog import watch_parent

# Runtime fallbacks for data/config/method/experimental.json::server.uvicorn.*.
_DFLT_BACKLOG = 16384
_DFLT_READY_TIMEOUT_S = 10.0
_DFLT_TERMINATE_GRACE_S = 5.0
_DFLT_KILL_GRACE_S = 2.0

# Live spawners; atexit cleans these up on exit.
_LIVE_PROCESSES: weakref.WeakSet["UvicornProcess"] = weakref.WeakSet()

# zero-arg picklable callable returning a FastAPI app
AppFactory = Any


def _worker_main(app_factory: AppFactory,
                 host: str,
                 port: int,
                 backlog: int) -> None:
    """Child-process entry point invoked by `multiprocessing.spawn` after the parent forks.

    Top-level so it is picklable by name; closures and bound methods do not survive the spawn boundary on Windows.

    Args:
        app_factory (AppFactory): zero-arg picklable callable returning the FastAPI app to serve. Invoked inside the child so the app is built in the worker's address space.
        host (str): bind address.
        port (int): TCP port.
        backlog (int): kernel socket-queue depth.
    """
    _parent_pid = os.getppid()
    _app = app_factory()
    _config = uvicorn.Config(_app,
                             host=str(host),
                             port=int(port),
                             log_level="error",
                             access_log=False,
                             backlog=int(backlog))
    _server = uvicorn.Server(_config)
    watch_parent(_parent_pid,
                 on_orphan=lambda: setattr(_server, "should_exit", True))
    _server.run()


class UvicornProcess:
    """FastAPI / ASGI process spawner backed by uvicorn (single-worker per instance).

    Lifecycle: `start()` forks via the `spawn` start method, `wait_ready()` polls `/healthz` until 200 or deadline, `shutdown()` ends the child cleanly (terminate -> join -> kill -> join).

    Attributes:
        active (bool): readiness-poll loop guard; True while `wait_ready` is polling, False once the server has answered, the deadline has fired, or `shutdown` has been called.
        _proc (mp_process.BaseProcess | None): child process; None until `start` is called.
        _app_factory (AppFactory): zero-arg picklable callable invoked inside the child.
        _port (int): TCP port the child binds to.
        _host (str): bind address.
        _backlog (int): kernel socket-queue depth forwarded to `uvicorn.Config`.
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
                 ready_timeout_s: float = _DFLT_READY_TIMEOUT_S,
                 terminate_grace_s: float = _DFLT_TERMINATE_GRACE_S,
                 kill_grace_s: float = _DFLT_KILL_GRACE_S) -> None:
        """Record the spawn arguments without forking; call `start()` to create the child.

        Args:
            app_factory (AppFactory): zero-arg picklable callable that builds the FastAPI app in the child process. Closures, lambdas, and bound methods do not survive the spawn boundary on Windows.
            port (int): TCP port to bind on.
            host (str, optional): bind address. Defaults to `"127.0.0.1"`.
            backlog (int, optional): kernel socket-queue depth. Defaults to the runtime fallback.
            ready_timeout_s (float, optional): default deadline for `wait_ready`. Defaults to the runtime fallback.
            terminate_grace_s (float, optional): seconds between `terminate()` and `kill()`. Defaults to the runtime fallback.
            kill_grace_s (float, optional): seconds after `kill()`. Defaults to the runtime fallback.
        """
        self._app_factory = app_factory
        self._port = int(port)
        self._host = str(host)
        self._backlog = int(backlog)
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

        Pinning `spawn` keeps behaviour identical across Windows (default `spawn`) and POSIX (default `fork`); a `fork`-built child would inherit the parent's PRNG state and break per-PID seed derivation.

        Raises:
            RuntimeError: when called more than once on the same instance; one process per instance.
        """
        if self._proc is not None:
            _msg = "UvicornProcess.start() called twice; one process per instance"
            raise RuntimeError(_msg)
        _ctx = mp.get_context("spawn")
        self._proc = _ctx.Process(target=_worker_main,
                                  args=(self._app_factory,
                                        self._host,
                                        self._port,
                                        self._backlog),
                                  daemon=True)
        self._proc.start()
        _LIVE_PROCESSES.add(self)

    def wait_ready(self, timeout_s: float | None = None) -> None:
        """Block the parent until the child answers `/healthz` with 200.

        A `0.0.0.0` bind is probed against `127.0.0.1` because the parent always has a loopback route to itself; cross-host readiness is the caller's concern.

        Args:
            timeout_s (float | None, optional): seconds to wait for the first 200 from `/healthz`. Defaults to None, which uses the constructor's `ready_timeout_s`.

        Raises:
            RuntimeError: when no 200 arrives before the deadline OR the child exits before becoming ready (the latter surfaces as a separate message naming the exit code).
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
                _msg = f"uvicorn child exited before becoming ready on {_url} "
                _msg += f"(exit code: {self._proc.exitcode})"
                raise RuntimeError(_msg)
            try:
                _r = httpx.get(_url, timeout=0.5)
                if _r.status_code == 200:
                    self.active = False
            except (httpx.HTTPError, ConnectionError, OSError):
                pass
            if self.active and time.perf_counter() >= _deadline:
                _msg = f"uvicorn did not become ready within {_timeout} s on {_url}"
                raise RuntimeError(_msg)
            if self.active:
                time.sleep(0.05)

    def shutdown(self) -> None:
        """Clear the readiness-poll guard and end the child process.

        Sends `Process.terminate()` (SIGTERM on POSIX, `TerminateProcess` on Windows), joins for `_terminate_grace_s`, escalates to `Process.kill()` + `_kill_grace_s` join when the child does not exit. uvicorn handles SIGTERM gracefully on POSIX; on Windows the terminate is brutal but the daemon flag means a stuck worker dies with the parent regardless.
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
    """Atexit safety net: SIGTERM every still-alive `UvicornProcess` on interpreter exit.

    The orchestrator's normal `try/finally` already calls `shutdown()`. This hook covers the abnormal-exit cases (KeyboardInterrupt, uncaught exception, hard crash) where leaked workers would otherwise hold their TCP ports past the parent's exit. Iterates a snapshot so a `WeakSet` mutation during shutdown does not break the loop.
    """
    for _proc in list(_LIVE_PROCESSES):
        try:
            _proc.shutdown()
        except Exception:
            pass


# Crash-path safety net.
atexit.register(_shutdown_live_processes)

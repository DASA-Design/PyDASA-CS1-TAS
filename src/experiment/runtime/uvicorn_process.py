# -*- coding: utf-8 -*-
"""
Module runtime/uvicorn_process.py
=================================

OS-process variant of `UvicornThread`. Used when the case-study workload requires real TCP, separate memory, and an event loop independent of the parent: the calibration multiprocess gate, the SOA case-study mesh, and the experiment launcher under `dpl="multiprocess"`.

Public surface mirrors the thread version (`active`, `start`, `wait_ready`, `shutdown`, `is_alive`) so callers swap on the deployment mode without touching downstream code. The trade-off versus `UvicornThread`: ~0.5-1.5 s spawn cost on Windows in exchange for OS-level isolation.

Typical usage::

    from src.experiment.instances import make_gauge_factory
    from src.experiment.runtime import UvicornProcess

    proc = UvicornProcess(make_gauge_factory(spec), port=8000)
    proc.start()
    proc.wait_ready()
"""
# native python modules
from __future__ import annotations

import multiprocessing as mp
import multiprocessing.process as mp_process
import time
from typing import Callable, Optional

# web stack
import httpx
from fastapi import FastAPI


# 16384 kernel queue so high arrival bursts are not dropped before uvicorn accepts them
_DEFAULT_BACKLOG = 16384


def _worker_main(app_factory: Callable[[], FastAPI],
                 host: str,
                 port: int,
                 backlog: int) -> None:
    """*_worker_main()* child-process entry point invoked by `multiprocessing.spawn` after the parent forks.

    Top-level so it is picklable by name; closures and bound methods do not survive the spawn boundary on Windows. uvicorn is imported inside the function so the parent does not pay its load cost when only spawning.

    Args:
        app_factory (Callable[[], FastAPI]): zero-arg picklable callable that returns the FastAPI app to serve. Invoked inside the child so the app is built in the worker's address space.
        host (str): bind address.
        port (int): TCP port.
        backlog (int): kernel socket-queue depth.
    """
    import uvicorn  # noqa: WPS433

    _app = app_factory()
    _config = uvicorn.Config(_app,
                             host=str(host),
                             port=int(port),
                             log_level="error",
                             access_log=False,
                             backlog=int(backlog))
    _server = uvicorn.Server(_config)
    _server.run()


class UvicornProcess:
    """**UvicornProcess** stand a FastAPI app behind uvicorn in a daemon child process so the parent can drive it over real TCP without sharing a GIL or event loop.

    The constructor takes a zero-arg picklable factory rather than a built `FastAPI` instance because Windows `spawn` cannot pickle an app instance carrying bound routes, state, and httpx clients; the factory is invoked in the child after spawn so the app is constructed there.

    Attributes:
        active (bool): readiness-poll loop guard; True while `wait_ready` is polling, False once the server has answered, the deadline has fired, or `shutdown` has been called.
        _proc (Optional[mp_process.BaseProcess]): child process; None until `start` is called. Typed as `BaseProcess` because `mp.get_context("spawn").Process` returns a `SpawnProcess` (a sibling of `mp.Process`, not the same class) and `BaseProcess` is the common ancestor.
        _app_factory (Callable[[], FastAPI]): zero-arg picklable callable invoked inside the child.
        _port (int): TCP port the child binds to.
        _host (str): bind address (`127.0.0.1`, `0.0.0.0`, `127.0.0.X`, or LAN IP).
        _backlog (int): kernel socket-queue depth forwarded to `uvicorn.Config`.
    """

    def __init__(self,
                 app_factory: Callable[[], FastAPI],
                 port: int,
                 *,
                 host: str = "127.0.0.1",
                 backlog: int = _DEFAULT_BACKLOG) -> None:
        """*__init__()* record the spawn arguments without forking; the parent must call `start` to actually create the child process.

        Args:
            app_factory (Callable[[], FastAPI]): zero-arg picklable callable that builds the FastAPI app in the child process. Closures, lambdas, and bound methods do not survive the spawn boundary on Windows.
            port (int): TCP port to bind on.
            host (str): bind address; defaults to `127.0.0.1`.
            backlog (int): kernel socket-queue depth; defaults to 16384.
        """
        self._app_factory = app_factory
        self._port = int(port)
        self._host = str(host)
        self._backlog = int(backlog)
        self._proc: Optional[mp_process.BaseProcess] = None
        self.active: bool = False

    def is_alive(self) -> bool:
        """*is_alive()* report whether the child process exists and has not yet exited.

        Returns:
            bool: False before `start` and after the child terminates; True while the worker is running.
        """
        if self._proc is None:
            return False
        return bool(self._proc.is_alive())

    def start(self) -> None:
        """*start()* fork the child process via the `spawn` start method; non-blocking.

        Pinning `spawn` keeps behaviour identical across Windows (default `spawn`) and POSIX (default `fork`); the calibration reproducibility contract relies on it because a `fork`-built child would inherit the parent's PRNG state and break per-PID seed derivation.

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

    def wait_ready(self, timeout_s: float = 10.0) -> None:
        """*wait_ready()* block the parent until the child answers `/healthz` with 200, so the next line of the caller can issue requests without race conditions.

        A `0.0.0.0` bind is probed against `127.0.0.1` because the parent always has a loopback route to itself; cross-host readiness is the caller's concern. Default 10 s timeout (vs `UvicornThread`'s 5 s) absorbs the ~0.5-1.5 s Windows spawn cost.

        Args:
            timeout_s (float): seconds to wait for the first 200 from `/healthz`.

        Raises:
            RuntimeError: when no 200 arrives before the deadline OR the child exits before becoming ready (the latter surfaces as a separate message naming the exit code).
        """
        if self._host == "0.0.0.0":
            _probe_host = "127.0.0.1"
        else:
            _probe_host = self._host
        _url = f"http://{_probe_host}:{self._port}/healthz"
        _deadline = time.perf_counter() + float(timeout_s)
        self.active = True
        while self.active:
            if self._proc is not None and not self._proc.is_alive():
                self.active = False
                _msg = (f"uvicorn child exited before becoming ready on {_url} "
                        f"(exit code: {self._proc.exitcode})")
                raise RuntimeError(_msg)
            try:
                _r = httpx.get(_url, timeout=0.5)
                if _r.status_code == 200:
                    self.active = False
            except (httpx.HTTPError, ConnectionError, OSError):
                pass
            if self.active and time.perf_counter() >= _deadline:
                _msg = f"uvicorn did not become ready within {timeout_s} s on {_url}"
                raise RuntimeError(_msg)
            if self.active:
                time.sleep(0.05)

    def shutdown(self) -> None:
        """*shutdown()* clear the readiness-poll guard and end the child process.

        Sends `Process.terminate()` (SIGTERM on POSIX, `TerminateProcess` on Windows), joins for 5 s, then escalates to `Process.kill()` + 2 s join when the child does not exit. uvicorn handles SIGTERM gracefully on POSIX; on Windows the terminate is brutal but the daemon flag means a stuck worker dies with the parent regardless.
        """
        self.active = False
        if self._proc is None:
            return
        if self._proc.is_alive():
            self._proc.terminate()
            self._proc.join(timeout=5.0)
        if self._proc.is_alive():
            self._proc.kill()
            self._proc.join(timeout=2.0)

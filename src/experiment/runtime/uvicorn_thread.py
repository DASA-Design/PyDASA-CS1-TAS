# -*- coding: utf-8 -*-
"""
Module runtime/uvicorn_thread.py
================================

In-process FastAPI host shared by every src/experiment caller that needs a real HTTP server side-by-side with Python test or notebook code: the calibration noise-floor probe spins up a single ping app, the experiment launcher spins up one per service in the TAS mesh, and the demo scripts mount the same way for ad-hoc inspection. Centralising the bind / readiness / teardown policy keeps those callers from each rolling their own thread + httpx-poll boilerplate and silently disagreeing on the rules.
"""
# native python modules
from __future__ import annotations

import threading
import time

# web stack
import httpx
import uvicorn
from fastapi import FastAPI


# 16384 kernel queue so high arrival bursts are not dropped before uvicorn accepts them
_DEFAULT_BACKLOG = 16384


class UvicornThread(threading.Thread):
    """**UvicornThread** background HTTP server for a single FastAPI app, bound to one host:port pair and managed by the calling process.

    Lets a normal Python program (a test, a notebook cell, a CLI script) talk to a FastAPI app over real TCP without leaving the parent thread blocked. The bind address is a constructor knob so callers can keep traffic on loopback for speed, expose the server to other hosts, or pin it to a per-test alias on Windows to dodge port reuse races.

    Attributes:
        active (bool): readiness-poll loop guard; `True` while a `wait_ready()` call is polling, `False` once the server has answered, the deadline has fired, or `shutdown()` has been called.
        _server: underlying `uvicorn.Server` instance.
        _port: TCP port the server is bound to.
        _host: bind address (`127.0.0.1` / `0.0.0.0` / `127.0.0.X` / LAN IP).
    """

    def __init__(self,
                 app: FastAPI,
                 port: int,
                 *,
                 host: str = "127.0.0.1",
                 backlog: int = _DEFAULT_BACKLOG) -> None:
        """*__init__()* prepare a uvicorn server bound to `host:port` for the given FastAPI app, but do not yet open the socket; the parent must call `start()` to actually serve.

        Args:
            app (FastAPI): app to serve.
            port (int): TCP port to bind on.
            host (str): bind address; defaults to `127.0.0.1`.
            backlog (int): kernel socket-queue depth; defaults to 16384.
        """
        super().__init__(daemon=True)
        _config = uvicorn.Config(app,
                                 host=str(host),
                                 port=int(port),
                                 log_level="error",
                                 access_log=False,
                                 backlog=int(backlog))
        self._server = uvicorn.Server(_config)
        self._port = int(port)
        self._host = str(host)
        self.active: bool = False

    def run(self) -> None:
        """*run()* thread entry point invoked by `threading.Thread.start()`; blocks until `shutdown()` flips uvicorn's exit flag."""
        self._server.run()

    def wait_ready(self, timeout_s: float = 5.0) -> None:
        """*wait_ready()* block the parent thread until the server is accepting traffic, so callers can issue real requests on the next line without race conditions.

        A `0.0.0.0` bind is probed against `127.0.0.1` because the parent process always has a loopback route to itself; cross-host readiness is the caller's job and lives outside this method.

        Args:
            timeout_s (float): maximum seconds to wait for the first 200 from `/healthz`.

        Raises:
            RuntimeError: when no 200 response arrives before the deadline.
        """
        if self._host == "0.0.0.0":
            _probe_host = "127.0.0.1"
        else:
            _probe_host = self._host
        _url = f"http://{_probe_host}:{self._port}/healthz"
        _deadline = time.perf_counter() + float(timeout_s)
        self.active = True
        while self.active:
            try:
                _r = httpx.get(_url, timeout=0.5)
                if _r.status_code == 200:
                    self.active = False
            except (httpx.HTTPError, ConnectionError, OSError):
                pass
            if self.active and time.perf_counter() >= _deadline:
                _msg = f"uvicorn did not become ready within {timeout_s} s "
                _msg += f"on {_url}"
                raise RuntimeError(_msg)
            if self.active:
                time.sleep(0.05)

    def shutdown(self) -> None:
        """*shutdown()* ask uvicorn to stop accepting new connections, wait up to 5 s for the worker thread to exit, and release any concurrent `wait_ready()` poll by clearing the loop guard."""
        self.active = False
        self._server.should_exit = True
        self.join(timeout=5.0)

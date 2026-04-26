# -*- coding: utf-8 -*-
"""
Module uvicorn_thread.py
========================

Daemon thread that runs one `uvicorn.Server` on `host:port`. Shared between the calibration noise-floor probe (`src.methods.calibration`) and the experiment launcher / launch_services script (`src.experiment.launcher`, `src.scripts.launch_services`) so the lifecycle policy lives in one place.

Lifecycle:

    - `__init__(app, port, host="127.0.0.1", backlog=_DEFAULT_BACKLOG)` configure but do not start.
    - `start()` (inherited from `threading.Thread`) spawn the daemon thread; uvicorn enters its run loop.
    - `wait_ready(timeout_s=5.0)` block until `/healthz` answers 200 on the bound host:port, or raise `RuntimeError`.
    - `shutdown()` set `server.should_exit` and join the thread.
"""
# native python modules
from __future__ import annotations

import threading
import time

# web stack
import httpx
import uvicorn
from fastapi import FastAPI


# 16384 backlog so high in-flight load levels are not refused at the kernel socket queue
_DEFAULT_BACKLOG = 16384


class UvicornThread(threading.Thread):
    """**UvicornThread** daemon thread hosting one uvicorn server on `host:port`.

    Exposes `.wait_ready()` to block until `/healthz` answers and `.shutdown()` to stop cleanly. Bind host is configurable so callers can pick `127.0.0.1` (loopback fast path), `0.0.0.0` (cross-alias / cross-host), or a specific alias like `127.0.0.20`.

    Attributes:
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
        """*__init__()* configure the uvicorn server; does not start the thread.

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

    def run(self) -> None:
        """*run()* thread entry point; blocks until `shutdown()` is called."""
        self._server.run()

    def wait_ready(self, timeout_s: float = 5.0) -> None:
        """*wait_ready()* poll `/healthz` until it returns 200 or `timeout_s` fires.

        When the server is bound on `0.0.0.0`, the probe targets `127.0.0.1` because the same machine can always reach the loopback. Cross-host readiness should be polled by the caller via the registry's resolved URL.

        Args:
            timeout_s (float): seconds to wait before raising.

        Raises:
            RuntimeError: when `/healthz` did not return 200 within `timeout_s`.
        """
        if self._host == "0.0.0.0":
            _probe_host = "127.0.0.1"
        else:
            _probe_host = self._host
        _url = f"http://{_probe_host}:{self._port}/healthz"
        _start = time.perf_counter()
        _deadline = _start + float(timeout_s)
        while True:
            _now = time.perf_counter()
            if _now >= _deadline:
                break
            try:
                _r = httpx.get(_url, timeout=0.5)
                if _r.status_code == 200:
                    return
            except (httpx.HTTPError, ConnectionError, OSError):
                pass
            time.sleep(0.05)
        raise RuntimeError(
            f"uvicorn did not become ready within {timeout_s} s "
            f"on {_url}")

    def shutdown(self) -> None:
        """*shutdown()* signal uvicorn to exit and join the thread (5 s timeout)."""
        self._server.should_exit = True
        self.join(timeout=5.0)

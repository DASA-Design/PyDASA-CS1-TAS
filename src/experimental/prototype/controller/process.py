"""Spawn the controller as a uvicorn process and fire its one-shot configuration to TAS_1.

`bring_up_controller` is a context manager that:

1. Spawns a uvicorn worker hosting the controller FastAPI app on a fixed port.
2. Waits for `/healthz` to respond.
3. POSTs the run's picker / retry / window configuration to `<target_url>/config` so TAS_1 installs the matching strategy.
4. Yields the controller's base URL for the orchestrator to poll `/aggregates` against.
5. On exit, shuts the uvicorn process down cleanly.

Sample polling lives in `SamplePoller`. It runs *inside* the controller process and is started by an app-level lifespan hook in `_build_app`.
"""

from __future__ import annotations

import functools
import time
from collections.abc import AsyncIterator, Iterator
from contextlib import asynccontextmanager, contextmanager

import httpx
from fastapi import FastAPI
from flask import Flask

from src.experimental.prototype.controller.app import (
    build_controller_fastapi_app,
    build_controller_flask_app,
)
from src.experimental.prototype.controller.poller import (
    SamplePoller,
    SyncSamplePoller,
)
from src.experimental.prototype.controller.strategies import picker_name_for
from src.experimental.prototype.runtime.ports import pick_free_port
from src.experimental.prototype.runtime.server import (
    Framework,
    make_server_adapter,
)

DFLT_READY_TIMEOUT_S = 20.0


def _build_fastapi_app(*,
                       thresholds: dict[str, float],
                       window_size: int,
                       warmup_n: int,
                       target_url: str,
                       poll_interval_ms: int) -> FastAPI:
    """Build the FastAPI controller app with a lifespan that runs an async `SamplePoller` against `target_url`.

    Args:
        thresholds (dict[str, float]): `{r1_max, r2_max}`.
        window_size (int): rolling-window size.
        warmup_n (int): minimum samples before breach flags can flip.
        target_url (str): TAS_1 base URL the poller will pull from.
        poll_interval_ms (int): cadence in milliseconds.

    Returns:
        FastAPI: configured controller app whose lifespan starts and stops the poller.
    """
    _app = build_controller_fastapi_app(thresholds=thresholds,
                                        window_size=window_size,
                                        warmup_n=warmup_n)

    @asynccontextmanager
    async def _lifespan(app: FastAPI) -> AsyncIterator[None]:
        """Start the `SamplePoller` on app startup; stop it on shutdown."""
        _poller = SamplePoller(target_url=target_url,
                               poll_interval_ms=poll_interval_ms,
                               app=app)
        _poller.start()
        try:
            yield
        finally:
            await _poller.stop()

    _app.router.lifespan_context = _lifespan
    return _app


def _build_flask_app(*,
                     thresholds: dict[str, float],
                     window_size: int,
                     warmup_n: int,
                     target_url: str,
                     poll_interval_ms: int) -> Flask:
    """Build the Flask controller app and start a sync `SyncSamplePoller` daemon thread.

    Waitress has no lifespan equivalent, so the poller is launched inline and bound to the app via a custom attribute (`_sync_poller`) for diagnostic inspection. The daemon flag means the poller dies with the worker process; that is the standard teardown path (the parent terminates the worker, no graceful stop required).

    Args:
        thresholds (dict[str, float]): `{r1_max, r2_max}`.
        window_size (int): rolling-window size.
        warmup_n (int): minimum samples before breach flags can flip.
        target_url (str): TAS_1 base URL the poller will pull from.
        poll_interval_ms (int): cadence in milliseconds.

    Returns:
        Flask: configured controller app whose poll-loop thread is already running.
    """
    _app = build_controller_flask_app(thresholds=thresholds,
                                      window_size=window_size,
                                      warmup_n=warmup_n)
    _poller = SyncSamplePoller(target_url=target_url,
                               poll_interval_ms=poll_interval_ms,
                               app=_app)
    _poller.start()
    _app._sync_poller = _poller  # type: ignore[attr-defined]
    return _app


def _fire_config(target_url: str,
                 adp: str,
                 op_weights: dict[str, dict[str, float]],
                 max_attempts: int,
                 window_size: int,
                 timeout_s: float = 5.0) -> None:
    """POST the run's picker configuration to TAS_1's `/config` endpoint.

    Args:
        target_url (str): TAS_1 base URL.
        adp (str): adaptation key; mapped to a picker wire name via `picker_name_for`.
        op_weights (dict): per-operation routing weights.
        max_attempts (int): retry-capable picker total attempts.
        window_size (int): reliability-aware picker window size.
        timeout_s (float, optional): HTTP timeout. Defaults to 5.0.

    Raises:
        httpx.HTTPStatusError: when TAS_1 responds with non-2xx.
    """
    _payload = {
        "picker_name": picker_name_for(adp),
        "op_weights": op_weights,
        "max_attempts": max_attempts,
        "window_size": window_size,
    }
    with httpx.Client(timeout=timeout_s) as _http:
        _resp = _http.post(f"{target_url.rstrip('/')}/config", json=_payload)
        _resp.raise_for_status()


@contextmanager
def bring_up_controller(*,
                        target_url: str,
                        adp: str,
                        op_weights: dict[str, dict[str, float]],
                        thresholds: dict[str, float],
                        window_size: int,
                        warmup_n: int,
                        max_attempts: int,
                        poll_interval_ms: int,
                        port: int,
                        host: str = "127.0.0.1",
                        ready_timeout_s: float = DFLT_READY_TIMEOUT_S,
                        framework: Framework = "fastapi") -> Iterator[str]:
    """Spawn the controller, wait for it to be ready, fire the picker config, yield its URL.

    Args:
        target_url (str): TAS_1 base URL (the controller polls `/samples` here and POSTs `/config`).
        adp (str): adaptation key for this run.
        op_weights (dict): per-operation routing weights extracted from the active profile's `_routs`.
        thresholds (dict[str, float]): `{r1_max, r2_max}`.
        window_size (int): rolling-window size.
        warmup_n (int): minimum samples before breach flags can flip.
        max_attempts (int): retry-capable picker total attempts.
        poll_interval_ms (int): controller's poll cadence against `target_url/samples`.
        port (int): TCP port the controller binds.
        host (str, optional): bind address. Defaults to `127.0.0.1`.
        ready_timeout_s (float, optional): max seconds to wait for `/healthz`. Defaults to `DFLT_READY_TIMEOUT_S`.
        framework (Framework, optional): controller server stack. `"fastapi"` runs uvicorn + async `SamplePoller` via FastAPI's lifespan; `"flask"` runs waitress + `SyncSamplePoller` on a daemon thread. Defaults to `"fastapi"`.

    Yields:
        str: controller base URL the orchestrator polls.
    """
    _bind_port = pick_free_port(host=host, start_port=port)
    _adapter = make_server_adapter(framework, "waitress")
    if framework == "flask":
        _factory = functools.partial(_build_flask_app,
                                     thresholds=thresholds,
                                     window_size=window_size,
                                     warmup_n=warmup_n,
                                     target_url=target_url,
                                     poll_interval_ms=poll_interval_ms)
    else:
        _factory = functools.partial(_build_fastapi_app,
                                     thresholds=thresholds,
                                     window_size=window_size,
                                     warmup_n=warmup_n,
                                     target_url=target_url,
                                     poll_interval_ms=poll_interval_ms)
    _adapter.mount(_factory, port=_bind_port, host=host)
    _url = f"http://{host}:{_bind_port}"
    try:
        _adapter.wait_ready(timeout_s=ready_timeout_s)
        _wait_target_healthy(target_url=target_url, deadline_s=time.time() + ready_timeout_s)
        _fire_config(target_url=target_url,
                     adp=adp,
                     op_weights=op_weights,
                     max_attempts=max_attempts,
                     window_size=window_size)
        yield _url
    finally:
        _adapter.shutdown()


def _wait_target_healthy(*, target_url: str, deadline_s: float) -> None:
    """Poll TAS_1's `/healthz` until it returns 200 or the deadline passes.

    Args:
        target_url (str): TAS_1 base URL.
        deadline_s (float): epoch-seconds deadline.

    Raises:
        TimeoutError: when the deadline elapses before `/healthz` returns 200.
    """
    _url = f"{target_url.rstrip('/')}/healthz"
    while time.time() < deadline_s:
        try:
            with httpx.Client(timeout=1.0) as _http:
                _resp = _http.get(_url)
            if _resp.status_code == 200:
                return
        except httpx.RequestError:
            pass
        time.sleep(0.1)
    _msg = f"target {target_url!r} did not become healthy within deadline"
    raise TimeoutError(_msg)


__all__ = [
    "DFLT_READY_TIMEOUT_S",
    "bring_up_controller",
]

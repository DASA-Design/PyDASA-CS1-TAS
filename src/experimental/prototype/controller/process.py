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

from src.experimental.prototype.controller.app import build_controller_app
from src.experimental.prototype.controller.poller import SamplePoller
from src.experimental.prototype.controller.strategies import picker_name_for
from src.experimental.prototype.runtime.server import make_server_adapter

DFLT_READY_TIMEOUT_S = 5.0


def _build_app(*,
               thresholds: dict[str, float],
               window_size: int,
               warmup_n: int,
               target_url: str,
               poll_interval_ms: int) -> FastAPI:
    """Build the controller app with a lifespan that runs a `SamplePoller` against `target_url`.

    Args:
        thresholds (dict[str, float]): `{r1_max, r2_max}`.
        window_size (int): rolling-window size.
        warmup_n (int): minimum samples before breach flags can flip.
        target_url (str): TAS_1 base URL the poller will pull from.
        poll_interval_ms (int): cadence in milliseconds.

    Returns:
        FastAPI: configured controller app whose lifespan starts and stops the poller.
    """
    _app = build_controller_app(thresholds=thresholds,
                                window_size=window_size,
                                warmup_n=warmup_n)

    @asynccontextmanager
    async def _lifespan(app: FastAPI) -> AsyncIterator[None]:
        """Start the `SamplePoller` on app startup; stop it on shutdown.

        Args:
            app (FastAPI): the controller app whose state the poller mutates.

        Yields:
            None: control returns to FastAPI while the app serves requests.
        """
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
                        ready_timeout_s: float = DFLT_READY_TIMEOUT_S) -> Iterator[str]:
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

    Yields:
        str: controller base URL the orchestrator polls.
    """
    _adapter = make_server_adapter("fastapi", "waitress")
    _factory = functools.partial(_build_app,
                                 thresholds=thresholds,
                                 window_size=window_size,
                                 warmup_n=warmup_n,
                                 target_url=target_url,
                                 poll_interval_ms=poll_interval_ms)
    _adapter.mount(_factory, port=port, host=host)
    _url = f"http://{host}:{port}"
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

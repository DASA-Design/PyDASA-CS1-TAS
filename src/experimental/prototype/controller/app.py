"""Controller FastAPI app: rolling-window R1/R2 aggregator over samples pulled from TAS_1.

The app exposes three read-only routes:

- `GET /aggregates`: current `{n_seen, n_in_window, r1_value, r2_value, r1_breach, r2_breach}` over the rolling window. Breach flags stay `False` until the warm-up has been reached.
- `GET /history`: the full trajectory (one entry per sample seen during the trial). The orchestrator drains it at shutdown to write `window.parquet`.
- `GET /healthz`: readiness probe.

State on `app.state`:

- `window` (`collections.deque(maxlen=window_size)`): the last W observed samples used to compute the running R1/R2.
- `history` (`list[dict]`): every sample seen during the trial, unbounded. Each row carries the running aggregates at the time the sample arrived.
- `thresholds` (`dict[str, float]`): `{r1_max, r2_max}` from `data/reference/baseline.json` (or passed in at startup).
- `warmup_n` (`int`): minimum sample count before the breach flags can flip.
- `last_offset` (`int`): the last TAS_1 sample offset the poller has merged.

The Monitor logic (consuming samples and updating the window) lives in `controller.poller.SamplePoller`. This module is just the HTTP surface and the running-aggregate compute.
"""

from __future__ import annotations

from collections import deque
from typing import Any

from fastapi import FastAPI

from src.experimental.prototype.target.factory.healthz import add_healthz_route


class ControllerRoutes:
    """FastAPI route adapter binding the controller's state to its read-only HTTP endpoints.

    Holds references to the `FastAPI` app and the threshold / warm-up settings, exposing `/aggregates` and `/history` as bound async methods. Module-scope so its methods pickle cleanly across process boundaries and FastAPI's signature introspection stays simple.
    """

    def __init__(self,
                 *,
                 app: FastAPI,
                 thresholds: dict[str, float],
                 warmup_n: int) -> None:
        """Configure the routes.

        Args:
            app (FastAPI): the controller app; mutated state lives on `app.state`.
            thresholds (dict[str, float]): `{r1_max, r2_max}`.
            warmup_n (int): minimum sample count before breach flags can flip.
        """
        self._app = app
        self._thresholds = thresholds
        self._warmup_n = warmup_n

    async def get_aggregates(self) -> dict[str, Any]:
        """GET `/aggregates`: return the current rolling-window aggregates and breach flags.

        Returns:
            dict[str, Any]: `n_seen`, `n_in_window`, `r1_value`, `r2_value`, `r1_breach`, `r2_breach`.
        """
        _window: deque[dict[str, Any]] = self._app.state.window
        _r1, _r2 = _running_r1_r2(_window)
        _n_seen = len(self._app.state.history)
        _ans: dict[str, Any] = {
            "n_seen": _n_seen,
            "n_in_window": len(_window),
            "r1_value": _r1,
            "r2_value": _r2,
            "r1_breach": _is_breach(_r1,
                                    self._thresholds["r1_max"],
                                    _n_seen,
                                    self._warmup_n),
            "r2_breach": _is_breach(_r2,
                                    self._thresholds["r2_max"],
                                    _n_seen,
                                    self._warmup_n),
        }
        return _ans

    async def get_history(self) -> dict[str, Any]:
        """GET `/history`: return the full per-sample trajectory for `window.parquet` writing.

        Returns:
            dict[str, Any]: `{"records": [...]}`. Each record carries `req_id`, `ts`, `status`, `latency_s`, `n_in_window`, `r1_running`, `r2_running`, `r1_breach`, `r2_breach`.
        """
        _ans: dict[str, Any] = {"records": list(self._app.state.history)}
        return _ans


def build_controller_app(*,
                         thresholds: dict[str, float],
                         window_size: int,
                         warmup_n: int) -> FastAPI:
    """Build the controller FastAPI app.

    Args:
        thresholds (dict[str, float]): `{"r1_max": ..., "r2_max": ...}` from `data/reference/baseline.json`.
        window_size (int): rolling-window size W (max samples kept for running aggregates).
        warmup_n (int): minimum samples before breach flags can flip.

    Returns:
        FastAPI: configured controller app with `GET /aggregates`, `GET /history`, `GET /healthz`.
    """
    _app = FastAPI()
    _app.state.window = deque(maxlen=window_size)
    _app.state.history = []
    _app.state.thresholds = dict(thresholds)
    _app.state.warmup_n = warmup_n
    _app.state.last_offset = 0
    _routes = ControllerRoutes(app=_app,
                               thresholds=_app.state.thresholds,
                               warmup_n=warmup_n)
    add_healthz_route(_app)
    _app.add_api_route("/aggregates", _routes.get_aggregates, methods=["GET"])
    _app.add_api_route("/history", _routes.get_history, methods=["GET"])
    return _app


def ingest_samples(app: FastAPI, records: list[dict[str, Any]]) -> None:
    """Merge new TAS_1 samples into the controller's window and history.

    Called by the `SamplePoller` after each poll cycle. Each record's offset must be strictly greater than `app.state.last_offset`; out-of-order records are dropped.

    Args:
        app (FastAPI): the controller app holding the state.
        records (list[dict[str, Any]]): samples from `GET /samples?since=<last_offset>`.
    """
    _window: deque[dict[str, Any]] = app.state.window
    _history: list[dict[str, Any]] = app.state.history
    _thresholds = app.state.thresholds
    _warmup_n = app.state.warmup_n
    for _r in records:
        _offset = int(_r.get("offset", 0))
        if _offset <= app.state.last_offset:
            continue
        app.state.last_offset = _offset
        _window.append(_r)
        _r1, _r2 = _running_r1_r2(_window)
        _n_seen = len(_history) + 1
        _trace: dict[str, Any] = {
            "req_id": _r.get("req_id", ""),
            "ts": _r.get("ts", 0.0),
            "status": _r.get("status", 0),
            "latency_s": _r.get("total_latency_s", 0.0),
            "n_in_window": len(_window),
            "r1_running": _r1,
            "r2_running": _r2,
            "r1_breach": _is_breach(_r1,
                                    _thresholds["r1_max"],
                                    _n_seen,
                                    _warmup_n),
            "r2_breach": _is_breach(_r2,
                                    _thresholds["r2_max"],
                                    _n_seen,
                                    _warmup_n),
        }
        _history.append(_trace)


def _running_r1_r2(window: deque[dict[str, Any]]) -> tuple[float, float]:
    """Compute R1 (failure fraction) and R2 (mean success latency) over the rolling window.

    Args:
        window (deque): rolling buffer of TAS_1 samples.

    Returns:
        tuple[float, float]: `(r1, r2)`. Both are 0.0 when the window is empty.
    """
    _n = len(window)
    if _n == 0:
        return 0.0, 0.0
    _failures = 0
    _success_latency_sum = 0.0
    _success_count = 0
    for _s in window:
        _status = _s.get("status", 0)
        if _status == 200:
            _success_latency_sum += float(_s.get("total_latency_s", 0.0))
            _success_count += 1
        else:
            _failures += 1
    _r1 = _failures / _n
    if _success_count > 0:
        _r2 = _success_latency_sum / _success_count
    else:
        _r2 = 0.0
    return _r1, _r2


def _is_breach(value: float,
               threshold: float,
               n_seen: int,
               warmup_n: int) -> bool:
    """Return True only when the running value exceeds threshold AND warm-up has been reached.

    Args:
        value (float): running aggregate (R1 or R2).
        threshold (float): config threshold.
        n_seen (int): total samples seen so far across the trial.
        warmup_n (int): minimum sample count to consider breaches valid.

    Returns:
        bool: True iff `value > threshold AND n_seen >= warmup_n`.
    """
    _ans = (n_seen >= warmup_n) and (value > threshold)
    return _ans


__all__ = [
    "ControllerRoutes",
    "build_controller_app",
    "ingest_samples",
]

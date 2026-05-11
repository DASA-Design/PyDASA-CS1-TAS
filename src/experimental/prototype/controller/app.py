"""Controller app: rolling-window R1/R2 aggregator over samples pulled from TAS_1.

The app exposes three read-only routes:

- `GET /aggregates`: current `{n_seen, n_in_window, r1_value, r2_value, r1_breach, r2_breach}` over the rolling window. Breach flags stay `False` until the warm-up has been reached.
- `GET /history`: the full trajectory (one entry per sample seen during the trial). The orchestrator drains it at shutdown to write `window.parquet`.
- `GET /healthz`: readiness probe.

Two framework variants share `ControllerRoutesBase(ABC)`:

- `ControllerFastapiRoutes` (ASGI / uvicorn) reads / mutates the FastAPI app's `app.state` namespace; the rolling buffer and history live there.
- `ControllerFlaskRoutes` (WSGI / waitress) reads / mutates a per-app `_ControllerStateBag` because Flask has no `app.state`. The on-the-wire response shape is identical so the orchestrator polls without caring which framework backs the controller.

The Monitor logic (consuming samples and updating the window) lives in `controller.poller.SamplePoller`; it calls the framework-neutral `ingest_samples(state, records)` against either state shape.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections import deque
from typing import Any

from fastapi import FastAPI
from flask import Flask, jsonify

from src.experimental.prototype.target.factory.healthz import add_healthz_route


class _ControllerStateBag:
    """Flask-side state bag mirroring FastAPI's `app.state` namespace for the controller.

    Attributes match `app.state.*`: `window`, `history`, `thresholds`, `warmup_n`, `last_offset`.
    """

    def __init__(self,
                 *,
                 thresholds: dict[str, float],
                 window_size: int,
                 warmup_n: int) -> None:
        self.window: deque[dict[str, Any]] = deque(maxlen=window_size)
        self.history: list[dict[str, Any]] = []
        self.thresholds: dict[str, float] = dict(thresholds)
        self.warmup_n: int = warmup_n
        self.last_offset: int = 0


class ControllerRoutesBase(ABC):
    """Framework-neutral state + helpers for the controller routes.

    Subclasses (`ControllerFastapiRoutes`, `ControllerFlaskRoutes`) bind the abstract `get_aggregates` / `get_history` to ASGI / WSGI respectively. The base owns the threshold + warm-up settings; subclasses own the per-framework state reference.

    Abstract so `build_controller_*_app` callers can't accidentally instantiate the base.
    """

    def __init__(self,
                 *,
                 thresholds: dict[str, float],
                 warmup_n: int) -> None:
        """Configure the shared state.

        Args:
            thresholds (dict[str, float]): `{r1_max, r2_max}`.
            warmup_n (int): minimum sample count before breach flags can flip.
        """
        self._thresholds = thresholds
        self._warmup_n = warmup_n

    def _aggregates_payload(self,
                            window: deque[dict[str, Any]],
                            history: list[dict[str, Any]]) -> dict[str, Any]:
        """Compute the `/aggregates` response body from the live window + history; shared between FastAPI and Flask variants."""
        _r1, _r2 = _running_r1_r2(window)
        _n_seen = len(history)
        _ans: dict[str, Any] = {
            "n_seen": _n_seen,
            "n_in_window": len(window),
            "r1_value": _r1,
            "r2_value": _r2,
            "r1_breach": _is_breach(_r1, self._thresholds["r1_max"], _n_seen, self._warmup_n),
            "r2_breach": _is_breach(_r2, self._thresholds["r2_max"], _n_seen, self._warmup_n),
        }
        return _ans

    @abstractmethod
    def get_aggregates(self, *args: Any, **kwargs: Any) -> Any:
        """`GET /aggregates`: return the current rolling-window aggregates and breach flags."""
        ...

    @abstractmethod
    def get_history(self, *args: Any, **kwargs: Any) -> Any:
        """`GET /history`: return the full per-sample trajectory for `window.parquet` writing."""
        ...


class ControllerFastapiRoutes(ControllerRoutesBase):
    """FastAPI / ASGI binding for the controller routes. Reads from / mutates `app.state`."""

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
        super().__init__(thresholds=thresholds, warmup_n=warmup_n)
        self._app = app

    async def get_aggregates(self) -> dict[str, Any]:
        """GET `/aggregates`: return the current rolling-window aggregates and breach flags.

        Returns:
            dict[str, Any]: `n_seen`, `n_in_window`, `r1_value`, `r2_value`, `r1_breach`, `r2_breach`.
        """
        return self._aggregates_payload(self._app.state.window, self._app.state.history)

    async def get_history(self) -> dict[str, Any]:
        """GET `/history`: return the full per-sample trajectory for `window.parquet` writing.

        Returns:
            dict[str, Any]: `{"records": [...]}`. Each record carries `req_id`, `ts`, `status`, `latency_s`, `n_in_window`, `r1_running`, `r2_running`, `r1_breach`, `r2_breach`.
        """
        return {"records": list(self._app.state.history)}


class ControllerFlaskRoutes(ControllerRoutesBase):
    """Flask / WSGI binding for the controller routes. Reads from / mutates a `_ControllerStateBag`."""

    def __init__(self,
                 *,
                 state: _ControllerStateBag,
                 thresholds: dict[str, float],
                 warmup_n: int) -> None:
        """Configure the routes.

        Args:
            state (_ControllerStateBag): Flask-side state bag (mirror of FastAPI's `app.state`).
            thresholds (dict[str, float]): `{r1_max, r2_max}`.
            warmup_n (int): minimum sample count before breach flags can flip.
        """
        super().__init__(thresholds=thresholds, warmup_n=warmup_n)
        self._state = state

    def get_aggregates(self) -> Any:
        """GET `/aggregates`: same response shape as the FastAPI variant."""
        return jsonify(self._aggregates_payload(self._state.window, self._state.history))

    def get_history(self) -> Any:
        """GET `/history`: same response shape as the FastAPI variant."""
        return jsonify({"records": list(self._state.history)})


# Backwards-compatible alias: callers that import `ControllerRoutes` keep working.
ControllerRoutes = ControllerFastapiRoutes


def build_controller_fastapi_app(*,
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
    _routes = ControllerFastapiRoutes(app=_app,
                                      thresholds=_app.state.thresholds,
                                      warmup_n=warmup_n)
    add_healthz_route(_app)
    _app.add_api_route("/aggregates", _routes.get_aggregates, methods=["GET"])
    _app.add_api_route("/history", _routes.get_history, methods=["GET"])
    return _app


# Backwards-compatible alias: the FastAPI factory is the historical default.
build_controller_app = build_controller_fastapi_app


def build_controller_flask_app(*,
                               thresholds: dict[str, float],
                               window_size: int,
                               warmup_n: int) -> Flask:
    """Build the controller Flask app. Same routes, same on-wire response shape as the FastAPI variant.

    Args:
        thresholds (dict[str, float]): `{"r1_max": ..., "r2_max": ...}`.
        window_size (int): rolling-window size W.
        warmup_n (int): minimum samples before breach flags can flip.

    Returns:
        Flask: configured controller app with `GET /aggregates`, `GET /history`, `GET /healthz`.
    """
    _state = _ControllerStateBag(thresholds=thresholds,
                                 window_size=window_size,
                                 warmup_n=warmup_n)
    _routes = ControllerFlaskRoutes(state=_state,
                                    thresholds=_state.thresholds,
                                    warmup_n=warmup_n)
    _app = Flask(__name__)
    # Attach the state bag so external callers (poller, lifespan) can find it.
    _app.state = _state  # type: ignore[attr-defined]
    _app.add_url_rule("/aggregates", view_func=_routes.get_aggregates, methods=["GET"])
    _app.add_url_rule("/history", view_func=_routes.get_history, methods=["GET"])
    _app.add_url_rule("/healthz", view_func=lambda: ({"status": "ok"}, 200), methods=["GET"])
    return _app


def ingest_samples(app: Any, records: list[dict[str, Any]]) -> None:
    """Merge new TAS_1 samples into the controller's window and history.

    Framework-agnostic: works against either FastAPI's `app.state` namespace or the Flask-side `_ControllerStateBag` (both expose the same attribute names: `window`, `history`, `thresholds`, `warmup_n`, `last_offset`).

    Out-of-order records (offset <= `last_offset`) are dropped.

    Args:
        app (Any): the controller app holding the state. Accessed via `app.state` to get the bag.
        records (list[dict[str, Any]]): samples from `GET /samples?since=<last_offset>`.
    """
    _state = app.state
    _window: deque[dict[str, Any]] = _state.window
    _history: list[dict[str, Any]] = _state.history
    _thresholds = _state.thresholds
    _warmup_n = _state.warmup_n
    for _r in records:
        _offset = int(_r.get("offset", 0))
        if _offset <= _state.last_offset:
            continue
        _state.last_offset = _offset
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
    "ControllerFastapiRoutes",
    "ControllerFlaskRoutes",
    "ControllerRoutes",
    "ControllerRoutesBase",
    "build_controller_app",
    "build_controller_fastapi_app",
    "build_controller_flask_app",
    "ingest_samples",
]

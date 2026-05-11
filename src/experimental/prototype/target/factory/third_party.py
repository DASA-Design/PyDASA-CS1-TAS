"""Build one app per third-party atomic service (`MAS_*`, `AS_*`, `DS_*`) — FastAPI and Flask variants.

The atomic app exposes:

- `POST /`: accepts a TAS-shaped payload (`req_id`, `kind`, `operation`, `inject_failure`, `submitted_ts`, ...), runs the failure dispatcher, then drives the atomic service through admission and handler. Medical-analysis services attach a `result` field (`changeDrug` / `changeDose` / `sendAlarm`) keyed deterministically off `req_id` so the composite workflow follows a reproducible branch.
- `GET /healthz`: readiness probe.

Per-invocation work is synthesised via `await asyncio.sleep(random.expovariate(mu))`. `mu` is the service rate in req/s from the active profile's `specs` layer (`data/config/profile/{dflt,opti}.json::specs[svc_id]`), not from the catalogue.

When `csv_dir` and `run_id` are supplied, each invocation appends one row to `<csv_dir>/<svc_name>__pid<PID>.csv`. The writer is opened lazily on first call inside each worker process, so multiprocess spawners get one file per `(service, pid)` pair without inter-process coordination.

`build_atomic_fastapi_app` is the ASGI shape served by uvicorn; `build_atomic_flask_app` is the WSGI shape served by waitress. Both factories are top-level and `functools.partial`-bindable so they pickle across `multiprocessing.spawn` on Windows. The Flask variant runs the async service classes on an `AsyncLoopThread` so K + c admission is shared across waitress worker threads.
"""

from __future__ import annotations

import asyncio
import os
import random
import time
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any

from fastapi import FastAPI
from fastapi.responses import JSONResponse
from flask import Flask
from flask import Response as FlaskResponse
from flask import jsonify, request
from starlette.responses import Response

from src.experimental.common.io.csv import CsvWriter
from src.experimental.common.payload.request import FailureMechanism
from src.experimental.prototype.target.factory.async_bridge import AsyncLoopThread
from src.experimental.prototype.target.factory.failure import (
    DFLT_TIMEOUT_GRACE_S,
    apply_inject_failure,
)
from src.experimental.prototype.target.factory.healthz import add_healthz_route
from src.experimental.prototype.target.service.atomic import AtomicService

DFLT_FAILURE_MIX: dict[FailureMechanism, float] = {
    "timeout": 0.34,
    "drop": 0.33,
    "5xx": 0.33,
}

ATOMIC_CSV_COLUMNS: list[str] = [
    "req_id",
    "svc_name",
    "kind",
    "operation",
    "submitted_ts",
    "recv_ts",
    "send_ts",
    "status",
    "c_used_at_start",
    "result",
    "inject_failure",
    "run_id",
    "pid",
]

_RESULT_BUCKETS: tuple[tuple[int, str], ...] = (
    (33, "changeDrug"),
    (66, "changeDose"),
    (100, "sendAlarm"),
)


class TasAtomicService(AtomicService):
    """Concrete `AtomicService` shared by every TAS atomic shape.

    Handles the per-invocation work simulation (exponential sleep keyed off mu, the service rate from profile.specs) and attaches an analysis `result` for medical-analysis services so the composite workflow can branch.

    Attributes:
        service_name (str): inherited; catalogue id (e.g. `MAS_{1}`).
        kind (str): catalogue group (`alarm` / `medical_analysis` / `drug`).
        mu (float): service rate in req/s; mean service time = 1/mu. mu <= 0 disables the sleep (handler returns immediately).
    """

    def __init__(self,
                 *,
                 service_name: str,
                 kind: str,
                 mu: float,
                 k: int | None = None,
                 c: int | None = None) -> None:
        """Configure the atomic.

        Args:
            service_name (str): catalogue id (e.g. `MAS_{1}`).
            kind (str): catalogue group.
            mu (float): service rate in req/s. Must be >= 0; 0 disables the synthetic sleep.
            k (int | None, optional): in-flight cap. Defaults to None.
            c (int | None, optional): parallel-worker cap. Defaults to None.
        """
        super().__init__(service_name=service_name, k=k, c=c)
        self.kind = kind
        self.mu = mu

    async def _handle(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Simulate exponential service time at rate `mu`, return a TAS-shaped reply.

        Args:
            payload (dict[str, Any]): inbound request body.

        Returns:
            dict[str, Any]: reply body. Medical-analysis services include a `result` key driving the workflow branch.
        """
        _recv_ts = time.time()
        if self.mu > 0:
            _sleep_s = random.expovariate(self.mu)
            await asyncio.sleep(_sleep_s)
        _ans: dict[str, Any] = {
            "service_name": self.service_name,
            "kind": self.kind,
            "operation": payload.get("operation"),
            "recv_ts": _recv_ts,
            "send_ts": time.time(),
        }
        if self.kind == "medical_analysis":
            _ans["result"] = _pick_analysis_result(str(payload.get("req_id", "")))
        return _ans


def _pick_analysis_result(req_id: str) -> str:
    """Map a request id to one of `changeDrug` / `changeDose` / `sendAlarm` deterministically.

    Uses the case-study Section iii split (~33 / 33 / 34 %) so a re-run with the same `req_id` sequence picks the same workflow branches.

    Args:
        req_id (str): request identifier.

    Returns:
        str: bucket label.
    """
    _h = hash(req_id) % 100
    _ans = "sendAlarm"
    for _bound, _label in _RESULT_BUCKETS:
        if _h < _bound:
            _ans = _label
            break
    return _ans


_CSV_WRITERS: dict[str, CsvWriter] = {}


def _get_csv_writer(csv_dir: Path, svc_name: str) -> CsvWriter:
    """Return a per-(service, pid) `CsvWriter`, opening it lazily on first call.

    Args:
        csv_dir (Path): directory holding per-pid CSV logs.
        svc_name (str): owning service id.

    Returns:
        CsvWriter: shared writer for this service inside this worker process.
    """
    _pid = os.getpid()
    _key = f"{svc_name}::{_pid}"
    _writer = _CSV_WRITERS.get(_key)
    if _writer is None:
        _path = csv_dir / _safe_filename(svc_name, _pid)
        _writer = CsvWriter(_path, ATOMIC_CSV_COLUMNS)
        _CSV_WRITERS[_key] = _writer
    return _writer


def _status_for_failure(flag: object) -> int:
    """Return the status code recorded in the per-pid CSV for an injected failure flag.

    Args:
        flag (object): the `inject_failure` value from the request payload.

    Returns:
        int: 502 for `5xx`, 599 for `drop` (mid-stream abort, no formal status), 504 for `timeout`, 0 otherwise.
    """
    _ans = 0
    if flag == "5xx":
        _ans = 502
    elif flag == "drop":
        _ans = 599
    elif flag == "timeout":
        _ans = 504
    return _ans


def _safe_filename(svc_name: str, pid: int) -> str:
    """Build the per-pid CSV filename, replacing characters illegal on Windows file systems.

    Args:
        svc_name (str): catalogue id (may contain `{` / `}` / `,`).
        pid (int): process id.

    Returns:
        str: filesystem-safe filename.
    """
    _safe = (svc_name
             .replace("{", "")
             .replace("}", "")
             .replace(",", "")
             .replace(" ", ""))
    return f"{_safe}__pid{pid}.csv"


class AtomicRoutesBase(ABC):
    """Framework-neutral state + helpers for the atomic-service routes.

    Holds the configuration both `AtomicFastapiRoutes` (FastAPI / ASGI) and `AtomicFlaskRoutes` (Flask / WSGI) share, plus the two helpers that do not depend on the request/response shape: `_maybe_inject_failure` (server-side ε draw) and `_log_csv_row` (per-pid CSV append). Subclasses add the framework-specific `post_root` handler.

    Module-scope so route methods are pickle-friendly across `multiprocessing.spawn` on Windows. Abstract so `build_atomic_*_app` callers can't accidentally instantiate the base.
    """

    def __init__(self,
                 *,
                 svc: TasAtomicService,
                 csv_dir: Path | None,
                 run_id: str | None,
                 timeout_grace_s: float,
                 eps: float = 0.0,
                 failure_mix: dict[FailureMechanism, float] | None = None) -> None:
        """Configure the shared state.

        Args:
            svc (TasAtomicService): the atomic service this app wraps.
            csv_dir (Path | None): directory for per-pid CSV logs; None disables.
            run_id (str | None): run identifier written into every CSV row.
            timeout_grace_s (float): sleep duration when the response carries `inject_failure="timeout"`.
            eps (float, optional): per-service failure rate. Defaults to 0.0 (no server-side injection).
            failure_mix (dict[FailureMechanism, float] | None, optional): per-mechanism weights for the ε draw. Defaults to `DFLT_FAILURE_MIX`.
        """
        self._svc = svc
        self._csv_dir = csv_dir
        self._run_id = run_id
        self._timeout_grace_s = timeout_grace_s
        self._eps = eps
        if failure_mix is None:
            self._failure_mix = dict(DFLT_FAILURE_MIX)
        else:
            self._failure_mix = dict(failure_mix)

    def _maybe_inject_failure(self, payload: dict[str, Any]) -> None:
        """Set `payload['inject_failure']` from a Bernoulli draw against `eps`.

        Skips when the payload already carries a non-None flag (client-side injection wins) or when `eps <= 0`. The mechanism is drawn from `failure_mix` via `random.choices`.

        Args:
            payload (dict[str, Any]): inbound request body; mutated in place.
        """
        if payload.get("inject_failure") is not None:
            return
        if self._eps <= 0:
            return
        if random.random() >= self._eps:
            return
        _mechs = list(self._failure_mix.keys())
        _weights = [self._failure_mix[_m] for _m in _mechs]
        _pick = random.choices(_mechs, weights=_weights, k=1)[0]
        payload["inject_failure"] = _pick

    def _log_csv_row(self,
                     payload: dict[str, Any],
                     *,
                     status: int,
                     body: dict[str, Any] | None) -> None:
        """Append one per-pid CSV row capturing the request outcome.

        No-op when `csv_dir` or `run_id` was not configured at construction. Otherwise opens the writer lazily on first call inside this worker process (cached by `(svc_name, pid)`) and appends one row covering the inbound `payload` fields, the response `body` (if any), and the final `status`.

        Args:
            payload (dict[str, Any]): inbound request body.
            status (int): final HTTP status code recorded in the row.
            body (dict[str, Any] | None): response body when the handler ran; None for synthetic-failure responses (where the handler short-circuited).
        """
        if self._csv_dir is None or self._run_id is None:
            return
        _body = body or {}
        _writer = _get_csv_writer(self._csv_dir, self._svc.service_name)
        _row: dict[str, Any] = {
            "req_id": payload.get("req_id", ""),
            "svc_name": self._svc.service_name,
            "kind": self._svc.kind,
            "operation": payload.get("operation", ""),
            "submitted_ts": payload.get("submitted_ts", ""),
            "recv_ts": _body.get("recv_ts", ""),
            "send_ts": _body.get("send_ts", ""),
            "status": status,
            "c_used_at_start": _body.get("c_used_at_start", ""),
            "result": _body.get("result", ""),
            "inject_failure": payload.get("inject_failure", ""),
            "run_id": self._run_id,
            "pid": os.getpid(),
        }
        _writer.write_row(_row)

    @abstractmethod
    def post_root(self, *args: Any, **kwargs: Any) -> Any:
        """Framework-specific request handler bound to `POST /`. Subclasses pick their own signature: the FastAPI variant is async and takes the parsed payload; the Flask variant is sync and reads `flask.request`."""
        ...


class AtomicFastapiRoutes(AtomicRoutesBase):
    """FastAPI / ASGI binding: `POST /` runs the async failure dispatcher + `await svc.invoke_operation`."""

    async def post_root(self, payload: dict[str, Any]) -> Response:
        """POST `/`: draw failure, dispatch, log to per-pid CSV.

        The sequence is: (1) server-side ε draw stamps `inject_failure` when client hasn't already, (2) `apply_inject_failure` returns a synthetic failure response if the flag is set, (3) otherwise the atomic's admission gate + handler run, (4) a CSV row is appended either way.

        Args:
            payload (dict[str, Any]): inbound request body; the `inject_failure` field may be mutated by the ε draw.

        Returns:
            Response: failure response when ε / client injected a failure, otherwise a JSONResponse with the atomic's reply.
        """
        self._maybe_inject_failure(payload)
        _maybe_failure = await apply_inject_failure(payload,
                                                    timeout_grace_s=self._timeout_grace_s)
        if _maybe_failure is not None:
            _flag = payload.get("inject_failure")
            self._log_csv_row(payload,
                              status=_status_for_failure(_flag),
                              body=None)
            return _maybe_failure
        _body, _status = await self._svc.invoke_operation(payload)
        self._log_csv_row(payload, status=_status, body=_body)
        return JSONResponse(content=_body, status_code=_status)


def build_atomic_fastapi_app(*,
                             svc_name: str,
                             kind: str,
                             mu: float,
                             k: int | None = None,
                             c: int | None = None,
                             csv_dir: str | None = None,
                             run_id: str | None = None,
                             timeout_grace_s: float = DFLT_TIMEOUT_GRACE_S,
                             eps: float = 0.0,
                             failure_mix: dict[FailureMechanism, float] | None = None) -> FastAPI:
    """Build a FastAPI app for one atomic service.

    Top-level + zero-arg-after-`functools.partial` so it pickles across `multiprocessing.spawn`.

    Args:
        svc_name (str): catalogue id (e.g. `MAS_{1}`).
        kind (str): catalogue group.
        mu (float): service rate in req/s, sourced from the active profile's specs layer. The handler sleeps `random.expovariate(mu)` per invocation (no sleep when mu <= 0).
        k (int | None, optional): in-flight cap. Defaults to None.
        c (int | None, optional): parallel-worker cap. Defaults to None.
        csv_dir (str | None, optional): directory for per-pid CSV logs (string for picklability). Defaults to None (no CSV side-effect).
        run_id (str | None, optional): run identifier; written into every CSV row. Defaults to None.
        timeout_grace_s (float, optional): sleep duration when `inject_failure="timeout"`. Defaults to `DFLT_TIMEOUT_GRACE_S`.
        eps (float, optional): per-service failure rate. The route draws `random.random() < eps` per request and, when the draw lands, stamps `inject_failure` from `failure_mix`. Defaults to 0.0 (no server-side injection).
        failure_mix (dict[FailureMechanism, float] | None, optional): per-mechanism weights for the post-ε draw. Defaults to a near-uniform mix.

    Returns:
        FastAPI: configured app with POST `/` + GET `/healthz`.
    """
    _svc = TasAtomicService(service_name=svc_name,
                            kind=kind,
                            mu=mu,
                            k=k,
                            c=c)
    if csv_dir is None:
        _csv_path: Path | None = None
    else:
        _csv_path = Path(csv_dir)
    _routes = AtomicFastapiRoutes(svc=_svc,
                           csv_dir=_csv_path,
                           run_id=run_id,
                           timeout_grace_s=timeout_grace_s,
                           eps=eps,
                           failure_mix=failure_mix)
    _app = FastAPI()
    _app.add_api_route("/", _routes.post_root, methods=["POST"])
    add_healthz_route(_app)
    return _app


_DROP_PARTIAL = b'{"error": "synthetic_drop", "partial":'


def _drop_generator() -> Any:
    """Yield one partial JSON chunk then raise so waitress closes the TCP connection mid-response.

    Yields:
        bytes: partial JSON head.

    Raises:
        RuntimeError: always; waitress aborts the response, surfacing as a transport-level drop on the client.
    """
    yield _DROP_PARTIAL
    _msg = "synthetic drop mid-stream"
    raise RuntimeError(_msg)


def _sync_apply_inject_failure(payload: dict[str, Any],
                               *,
                               timeout_grace_s: float) -> FlaskResponse | None:
    """Sync (WSGI) mirror of `failure.apply_inject_failure`.

    Args:
        payload (dict[str, Any]): inbound request body; `inject_failure` decides the branch.
        timeout_grace_s (float): blocking sleep for the `timeout` mechanism.

    Returns:
        FlaskResponse | None: 502 for `5xx`, drop-streaming response for `drop`, None for `timeout` (after blocking sleep) or when the flag is absent.

    Raises:
        ValueError: when the flag is set but not in `{"timeout", "drop", "5xx"}`.
    """
    _flag_raw = payload.get("inject_failure")
    if _flag_raw is None:
        return None
    if _flag_raw == "timeout":
        time.sleep(timeout_grace_s)
        return None
    if _flag_raw == "drop":
        return FlaskResponse(_drop_generator(), mimetype="application/json")
    if _flag_raw == "5xx":
        _resp = jsonify({"error": "synthetic_5xx"})
        _resp.status_code = 502
        return _resp
    _msg = (f"unknown inject_failure flag {_flag_raw!r}; "
            "expected None, 'timeout', 'drop', or '5xx'")
    raise ValueError(_msg)


class AtomicFlaskRoutes(AtomicRoutesBase):
    """Flask / WSGI binding: `POST /` runs the sync failure dispatcher + drives `svc.invoke_operation` through the shared `AsyncLoopThread`."""

    def __init__(self,
                 *,
                 svc: TasAtomicService,
                 loop: AsyncLoopThread,
                 csv_dir: Path | None,
                 run_id: str | None,
                 timeout_grace_s: float,
                 eps: float = 0.0,
                 failure_mix: dict[FailureMechanism, float] | None = None) -> None:
        """Configure the routes; identical contract to `AtomicFastapiRoutes` plus the shared loop."""
        super().__init__(svc=svc,
                         csv_dir=csv_dir,
                         run_id=run_id,
                         timeout_grace_s=timeout_grace_s,
                         eps=eps,
                         failure_mix=failure_mix)
        self._loop = loop

    def post_root(self) -> FlaskResponse:
        """POST `/`: draw failure, dispatch on the shared loop, log to per-pid CSV.

        Returns:
            FlaskResponse: failure response when ε / client injected a failure, otherwise a JSON response with the atomic's reply.
        """
        _payload: dict[str, Any] = request.get_json(force=True, silent=True) or {}
        self._maybe_inject_failure(_payload)
        _maybe_failure = _sync_apply_inject_failure(_payload,
                                                    timeout_grace_s=self._timeout_grace_s)
        if _maybe_failure is not None:
            _flag = _payload.get("inject_failure")
            self._log_csv_row(_payload, status=_status_for_failure(_flag), body=None)
            return _maybe_failure
        _body, _status = self._loop.submit(self._svc.invoke_operation(_payload))
        self._log_csv_row(_payload, status=_status, body=_body)
        _resp = jsonify(_body)
        _resp.status_code = _status
        return _resp


def build_atomic_flask_app(*,
                           svc_name: str,
                           kind: str,
                           mu: float,
                           k: int | None = None,
                           c: int | None = None,
                           csv_dir: str | None = None,
                           run_id: str | None = None,
                           timeout_grace_s: float = DFLT_TIMEOUT_GRACE_S,
                           eps: float = 0.0,
                           failure_mix: dict[FailureMechanism, float] | None = None) -> Flask:
    """Flask twin of `build_atomic_fastapi_app`. Same contract, same on-disk schema.

    Spins up an `AsyncLoopThread` so the async `TasAtomicService` shares K + c gate state across waitress worker threads.

    Args:
        svc_name (str): catalogue id (e.g. `MAS_{1}`).
        kind (str): catalogue group.
        mu (float): service rate in req/s.
        k (int | None, optional): in-flight cap. Defaults to None.
        c (int | None, optional): parallel-worker cap. Defaults to None.
        csv_dir (str | None, optional): directory for per-pid CSV logs. Defaults to None.
        run_id (str | None, optional): run identifier. Defaults to None.
        timeout_grace_s (float, optional): sleep when `inject_failure="timeout"`. Defaults to `DFLT_TIMEOUT_GRACE_S`.
        eps (float, optional): per-service failure rate. Defaults to 0.0.
        failure_mix (dict[FailureMechanism, float] | None, optional): per-mechanism weights for the ε draw. Defaults to a near-uniform mix.

    Returns:
        Flask: configured app with POST `/` + GET `/healthz`.
    """
    _svc = TasAtomicService(service_name=svc_name, kind=kind, mu=mu, k=k, c=c)
    if csv_dir is None:
        _csv_path: Path | None = None
    else:
        _csv_path = Path(csv_dir)
    _loop = AsyncLoopThread()
    _routes = AtomicFlaskRoutes(svc=_svc,
                                loop=_loop,
                                csv_dir=_csv_path,
                                run_id=run_id,
                                timeout_grace_s=timeout_grace_s,
                                eps=eps,
                                failure_mix=failure_mix)
    _app = Flask(__name__)
    _app.add_url_rule("/", view_func=_routes.post_root, methods=["POST"])
    _app.add_url_rule("/healthz", view_func=lambda: ({"status": "ok"}, 200), methods=["GET"])
    return _app


__all__ = [
    "ATOMIC_CSV_COLUMNS",
    "AtomicFlaskRoutes",
    "AtomicFastapiRoutes",
    "AtomicRoutesBase",
    "DFLT_FAILURE_MIX",
    "TasAtomicService",
    "build_atomic_fastapi_app",
    "build_atomic_flask_app",
]

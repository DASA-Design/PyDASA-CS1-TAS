"""Build one app per internal TAS stage (`TAS_{2..6}`) — FastAPI and Flask variants. Used in expanded mode.

Each internal stage represents one operation in the published TAS workflow:

- `TAS_{2}` calls a `medical_analysis` service (`analyseData`).
- `TAS_{3}` calls an `alarm` service (`triggerAlarm`).
- `TAS_{4}` calls an `alarm` service (`sendAlarm`).
- `TAS_{5}` calls a `drug` service (`changeDrug`).
- `TAS_{6}` calls a `drug` service (`changeDose`).

Each stage runs in its own worker with an admission gate (k, c, K), optional μ-sleep (gated by `inject_internal_stage_mu`), per-pid CSV side-effect, and `apply_inject_failure` dispatch. The handler picks a third-party of the configured kind via a first-of-kind picker and dispatches via the same `ServiceClient` TAS_1 uses.

`invoke_operation` is overridden so a downstream transport error (status 0 from `ServiceClient`) surfaces as HTTP 502 to the outer caller, instead of being masked behind the inherited atomic's hardcoded 200.

`build_internal_stage_fastapi_app` is the ASGI shape served by uvicorn; `build_internal_stage_flask_app` is the WSGI shape served by waitress. The Flask variant runs the async stage on an `AsyncLoopThread` so the dispatch client + K + c gate are shared across waitress worker threads.
"""

from __future__ import annotations

import asyncio
import os
import random
import time
from abc import ABC, abstractmethod
from collections.abc import AsyncIterator, Mapping
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import FastAPI
from fastapi.responses import JSONResponse
from flask import Flask
from flask import Response as FlaskResponse
from flask import jsonify, request
from starlette.responses import Response

from src.experimental.common.io.csv import CsvWriter
from src.experimental.common.registry.cache import ServiceCache
from src.experimental.common.registry.description import ServiceDescription
from src.experimental.common.registry.service import ServiceRegistry
from src.experimental.prototype.target.factory.async_bridge import AsyncLoopThread
from src.experimental.prototype.target.factory.failure import (
    DFLT_TIMEOUT_GRACE_S,
    apply_inject_failure,
)
from src.experimental.prototype.target.factory.healthz import add_healthz_route
from src.experimental.prototype.target.factory.third_party import (
    _drop_generator,
    _safe_filename,
    _status_for_failure,
)
from src.experimental.prototype.target.service.atomic import AtomicService
from src.experimental.prototype.target.service.catalogue import load_catalogue
from src.experimental.prototype.target.service.client import (
    DFLT_TIMEOUT_S,
    ServiceClient,
)


INTERNAL_CSV_COLUMNS: list[str] = [
    "req_id",
    "svc_name",
    "kind",
    "operation",
    "submitted_ts",
    "recv_ts",
    "send_ts",
    "status",
    "c_used_at_start",
    "downstream_svc_id",
    "downstream_status",
    "inject_failure",
    "run_id",
    "pid",
]


class TasInternalAtomic(AtomicService):
    """One-call atomic stage. `_handle` picks a third-party of the configured kind and dispatches via `ServiceClient`.

    Attributes:
        service_name (str): inherited; stage id (`TAS_{2}` ... `TAS_{6}`).
        kind (str): catalogue group this stage CALLS (`medical_analysis` / `alarm` / `drug`).
        operation (str): operation name forwarded to the downstream third-party.
        mu (float): optional service rate; mean sleep = `1/mu`. mu <= 0 disables the sleep.
        k (int | None): inherited; in-flight cap.
        c (int | None): inherited; parallel-worker cap.
    """

    def __init__(self,
                 *,
                 service_name: str,
                 kind: str,
                 operation: str,
                 mu: float,
                 client: ServiceClient,
                 cache: ServiceCache,
                 catalogue_version: str | None = None,
                 k: int | None = None,
                 c: int | None = None) -> None:
        """Wire the internal-stage atomic.

        Args:
            service_name (str): stage id (`TAS_{2}` ... `TAS_{6}`).
            kind (str): catalogue group to call.
            operation (str): downstream operation name.
            mu (float): service rate. <= 0 disables the sleep.
            client (ServiceClient): pre-opened dispatch client (managed by the FastAPI lifespan).
            cache (ServiceCache): cache resolved for this stage's downstream calls.
            catalogue_version (str | None, optional): catalogue version layer to consult for the picker (None reads `_setpoint`).
            k (int | None, optional): in-flight cap. Defaults to None (no limit).
            c (int | None, optional): parallel-worker cap. Defaults to None.
        """
        super().__init__(service_name=service_name, k=k, c=c)
        self.kind = kind
        self.operation = operation
        self.mu = mu
        self._client = client
        self._cache = cache
        self._catalogue = load_catalogue(catalogue_version)

    async def invoke_operation(self,
                               payload: dict[str, Any]) -> tuple[dict[str, Any], int]:
        """Run admission, dispatch downstream, surface the real status.

        Mirrors `AtomicService.invoke_operation` but propagates the downstream status (so a downstream 502 is not masked as 200).

        Args:
            payload (dict[str, Any]): inbound request body.

        Returns:
            tuple[dict[str, Any], int]: body + status. 503 on admission denial; downstream status otherwise; 502 when the downstream had a transport error (status 0).
        """
        _admitted, _c_used = await self._gate.acquire()
        if not _admitted:
            _rejected: dict[str, Any] = {
                "error": "K_full",
                "service_name": self.service_name,
                "K": self.k,
                "in_flight": _c_used,
            }
            return _rejected, 503
        try:
            if self._gate.c_sem is not None:
                async with self._gate.c_sem:
                    _body, _status = await self._dispatch(payload)
            else:
                _body, _status = await self._dispatch(payload)
            _body["c_used_at_start"] = _c_used
            return _body, _status
        finally:
            await self._gate.release()

    async def _dispatch(self,
                        payload: dict[str, Any]) -> tuple[dict[str, Any], int]:
        """Sleep on μ if set, pick a third-party of `self.kind`, dispatch, return its `(body, status)`.

        Args:
            payload (dict[str, Any]): inbound request body forwarded to the downstream.

        Returns:
            tuple[dict[str, Any], int]: downstream body + status. Status 0 (transport error) rewrites to 502.
        """
        if self.mu > 0:
            await asyncio.sleep(random.expovariate(self.mu))
        _matches = self._catalogue.by_kind(self.kind)
        if not _matches:
            _msg = f"no services of kind {self.kind!r} in catalogue {self._catalogue.name!r}"
            _err: dict[str, Any] = {"error": "no_service_of_kind", "detail": _msg}
            return _err, 502
        _picked = _matches[0]
        _send_ts = time.time()
        _body, _status = await self._client.invoke_operation(svc_name=_picked.svc_id,
                                                             operation=self.operation,
                                                             payload=payload)
        _recv_ts = time.time()
        _body["downstream_svc_id"] = _picked.svc_id
        _body["downstream_status"] = _status
        _body["recv_ts"] = _send_ts
        _body["send_ts"] = _recv_ts
        if _status == 0:
            _status_out = 502
        else:
            _status_out = _status
        return _body, _status_out

    async def _handle(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Satisfy the abstract base. `invoke_operation` overrides the entry point, so this path is rarely hit."""
        _body, _ = await self._dispatch(payload)
        return _body


_INTERNAL_CSV_WRITERS: dict[str, CsvWriter] = {}


def _get_csv_writer(csv_dir: Path, svc_name: str) -> CsvWriter:
    """Return a per-`(stage, pid)` `CsvWriter` opened with `INTERNAL_CSV_COLUMNS`.

    Opened lazily on first call inside one worker process, then cached. Parallels `third_party._get_csv_writer` but uses the internal-stage column set (`downstream_svc_id` and `downstream_status` instead of `result`).
    """
    _pid = os.getpid()
    _key = f"{svc_name}::{_pid}"
    _writer = _INTERNAL_CSV_WRITERS.get(_key)
    if _writer is None:
        _path = csv_dir / _safe_filename(svc_name, _pid)
        _writer = CsvWriter(_path, INTERNAL_CSV_COLUMNS)
        _INTERNAL_CSV_WRITERS[_key] = _writer
    return _writer


def _log_csv_row(svc: TasInternalAtomic,
                 csv_dir: Path | None,
                 run_id: str | None,
                 payload: dict[str, Any],
                 *,
                 status: int,
                 body: dict[str, Any] | None) -> None:
    """Append one per-pid CSV row; no-op when `csv_dir` or `run_id` is missing."""
    if csv_dir is None or run_id is None:
        return
    _body = body or {}
    _writer = _get_csv_writer(csv_dir, svc.service_name)
    _row: dict[str, Any] = {
        "req_id": payload.get("req_id", ""),
        "svc_name": svc.service_name,
        "kind": svc.kind,
        "operation": payload.get("operation", svc.operation),
        "submitted_ts": payload.get("submitted_ts", ""),
        "recv_ts": _body.get("recv_ts", ""),
        "send_ts": _body.get("send_ts", ""),
        "status": status,
        "c_used_at_start": _body.get("c_used_at_start", ""),
        "downstream_svc_id": _body.get("downstream_svc_id", ""),
        "downstream_status": _body.get("downstream_status", ""),
        "inject_failure": payload.get("inject_failure", ""),
        "run_id": run_id,
        "pid": os.getpid(),
    }
    _writer.write_row(_row)


def build_internal_stage_fastapi_app(*,
                                     svc_name: str,
                                     calls_kind: str,
                                     operation: str,
                                     mu: float,
                                     atomic_url_lt: Mapping[str, str | list[str]],
                                     catalogue_version: str | None = None,
                                     k: int | None = None,
                                     c: int | None = None,
                                     csv_dir: str | None = None,
                                     run_id: str | None = None,
                                     request_timeout_s: float = DFLT_TIMEOUT_S,
                                     timeout_grace_s: float = DFLT_TIMEOUT_GRACE_S) -> FastAPI:
    """Build a FastAPI app for one internal-stage atomic (`TAS_{2..6}`).

    Top-level + zero-arg-after-`functools.partial` so it pickles across `multiprocessing.spawn`.

    Args:
        svc_name (str): stage id (`TAS_{2}` ... `TAS_{6}`).
        calls_kind (str): catalogue group this stage calls (`medical_analysis` / `alarm` / `drug`).
        operation (str): downstream operation name (e.g. `analyseData`).
        mu (float): service rate in req/s. <= 0 disables the sleep.
        atomic_url_lt (dict[str, str]): mapping `svc_id -> base URL` for the third-party atomics this stage may call.
        catalogue_version (str | None, optional): catalogue version layer to load for the picker (None reads `_setpoint`).
        k (int | None, optional): in-flight cap. Defaults to None.
        c (int | None, optional): parallel-worker cap. Defaults to None.
        csv_dir (str | None, optional): directory for per-pid CSV logs. Defaults to None.
        run_id (str | None, optional): run identifier; written into every CSV row. Defaults to None.
        request_timeout_s (float, optional): per-dispatch HTTP timeout. Defaults to `DFLT_TIMEOUT_S`.
        timeout_grace_s (float, optional): sleep duration when `inject_failure="timeout"`. Defaults to `DFLT_TIMEOUT_GRACE_S`.

    Returns:
        FastAPI: configured app with POST `/` + GET `/healthz`.
    """
    _registry = ServiceRegistry()
    for _svc_id, _value in atomic_url_lt.items():
        if isinstance(_value, str):
            _urls: tuple[str, ...] = (_value,)
        else:
            _urls = tuple(_value)
        if not _urls:
            _msg = f"atomic_url_lt[{_svc_id!r}] is empty; need at least one URL"
            raise ValueError(_msg)
        _registry.register_service(ServiceDescription(_id=_svc_id,
                                                      name=_svc_id,
                                                      endpoint=_urls[0],
                                                      urls=_urls))
    _cache = ServiceCache(_registry)
    if csv_dir is None:
        _csv_path: Path | None = None
    else:
        _csv_path = Path(csv_dir)

    @asynccontextmanager
    async def _lifespan(app: FastAPI) -> AsyncIterator[None]:
        """Open the dispatch client on startup; close it on shutdown."""
        _client = ServiceClient(client_id=svc_name,
                                cache=_cache,
                                timeout_s=request_timeout_s)
        async with _client:
            app.state.svc = TasInternalAtomic(service_name=svc_name,
                                              kind=calls_kind,
                                              operation=operation,
                                              mu=mu,
                                              client=_client,
                                              cache=_cache,
                                              catalogue_version=catalogue_version,
                                              k=k,
                                              c=c)
            yield

    _app = FastAPI(lifespan=_lifespan)
    add_healthz_route(_app)

    async def _post_root(payload: dict[str, Any]) -> Response:
        """POST `/`: failure dispatch first, then admission + downstream call, then per-pid CSV."""
        _maybe_failure = await apply_inject_failure(payload,
                                                    timeout_grace_s=timeout_grace_s)
        if _maybe_failure is not None:
            _flag = payload.get("inject_failure")
            _svc: TasInternalAtomic = _app.state.svc
            _log_csv_row(_svc, _csv_path, run_id, payload,
                         status=_status_for_failure(_flag),
                         body=None)
            return _maybe_failure
        _svc = _app.state.svc
        _body, _status = await _svc.invoke_operation(payload)
        _log_csv_row(_svc, _csv_path, run_id, payload, status=_status, body=_body)
        return JSONResponse(content=_body, status_code=_status)

    _app.add_api_route("/", _post_root, methods=["POST"])
    return _app


class InternalStageRoutesBase(ABC):
    """Framework-neutral state for the internal-stage routes; the FastAPI and Flask subclasses add the `post_root` handler appropriate for ASGI / WSGI. Abstract so `build_internal_stage_*_app` callers can't accidentally instantiate the base."""

    def __init__(self,
                 *,
                 svc: TasInternalAtomic,
                 csv_dir: Path | None,
                 run_id: str | None,
                 timeout_grace_s: float) -> None:
        """Configure the shared state."""
        self._svc = svc
        self._csv_dir = csv_dir
        self._run_id = run_id
        self._timeout_grace_s = timeout_grace_s

    @abstractmethod
    def post_root(self, *args: Any, **kwargs: Any) -> Any:
        """Framework-specific request handler bound to `POST /`. FastAPI variant: async + payload arg; Flask variant: sync, reads `flask.request`."""
        ...


class InternalStageFlaskRoutes(InternalStageRoutesBase):
    """Flask / WSGI binding: drive `svc.invoke_operation` through the shared `AsyncLoopThread`."""

    def __init__(self,
                 *,
                 svc: TasInternalAtomic,
                 loop: AsyncLoopThread,
                 csv_dir: Path | None,
                 run_id: str | None,
                 timeout_grace_s: float) -> None:
        """Configure the routes; identical contract to the FastAPI handler plus the shared loop."""
        super().__init__(svc=svc,
                         csv_dir=csv_dir,
                         run_id=run_id,
                         timeout_grace_s=timeout_grace_s)
        self._loop = loop

    def post_root(self) -> FlaskResponse:
        """POST `/`: failure dispatch first, then admission + downstream call on the shared loop, then per-pid CSV."""
        _payload: dict[str, Any] = request.get_json(force=True, silent=True) or {}
        _maybe_failure = _sync_apply_inject_failure(_payload,
                                                    timeout_grace_s=self._timeout_grace_s)
        if _maybe_failure is not None:
            _flag = _payload.get("inject_failure")
            _log_csv_row(self._svc, self._csv_dir, self._run_id, _payload,
                         status=_status_for_failure(_flag),
                         body=None)
            return _maybe_failure
        _body, _status = self._loop.submit(self._svc.invoke_operation(_payload))
        _log_csv_row(self._svc, self._csv_dir, self._run_id, _payload,
                     status=_status, body=_body)
        _resp = jsonify(_body)
        _resp.status_code = _status
        return _resp


def _sync_apply_inject_failure(payload: dict[str, Any],
                               *,
                               timeout_grace_s: float) -> FlaskResponse | None:
    """Sync (WSGI) mirror of `failure.apply_inject_failure` for the internal-stage path.

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


def build_internal_stage_flask_app(*,
                                   svc_name: str,
                                   calls_kind: str,
                                   operation: str,
                                   mu: float,
                                   atomic_url_lt: Mapping[str, str | list[str]],
                                   catalogue_version: str | None = None,
                                   k: int | None = None,
                                   c: int | None = None,
                                   csv_dir: str | None = None,
                                   run_id: str | None = None,
                                   request_timeout_s: float = DFLT_TIMEOUT_S,
                                   timeout_grace_s: float = DFLT_TIMEOUT_GRACE_S) -> Flask:
    """Flask twin of `build_internal_stage_fastapi_app`. Same contract, same on-disk schema.

    Args mirror the FastAPI factory; the Flask body runs the async `TasInternalAtomic` + `ServiceClient` pair on a dedicated `AsyncLoopThread` so the K + c admission gate plus the dispatch client share one loop across waitress worker threads.
    """
    _registry = ServiceRegistry()
    for _svc_id, _value in atomic_url_lt.items():
        if isinstance(_value, str):
            _urls: tuple[str, ...] = (_value,)
        else:
            _urls = tuple(_value)
        if not _urls:
            _msg = f"atomic_url_lt[{_svc_id!r}] is empty; need at least one URL"
            raise ValueError(_msg)
        _registry.register_service(ServiceDescription(_id=_svc_id,
                                                      name=_svc_id,
                                                      endpoint=_urls[0],
                                                      urls=_urls))
    _cache = ServiceCache(_registry)
    if csv_dir is None:
        _csv_path: Path | None = None
    else:
        _csv_path = Path(csv_dir)
    _loop = AsyncLoopThread()

    async def _open_svc() -> TasInternalAtomic:
        _client = ServiceClient(client_id=svc_name,
                                cache=_cache,
                                timeout_s=request_timeout_s)
        await _client.__aenter__()
        return TasInternalAtomic(service_name=svc_name,
                                 kind=calls_kind,
                                 operation=operation,
                                 mu=mu,
                                 client=_client,
                                 cache=_cache,
                                 catalogue_version=catalogue_version,
                                 k=k,
                                 c=c)

    _svc = _loop.submit(_open_svc())
    _routes = InternalStageFlaskRoutes(svc=_svc,
                                       loop=_loop,
                                       csv_dir=_csv_path,
                                       run_id=run_id,
                                       timeout_grace_s=timeout_grace_s)
    _app = Flask(__name__)
    _app.add_url_rule("/", view_func=_routes.post_root, methods=["POST"])
    _app.add_url_rule("/healthz", view_func=lambda: ({"status": "ok"}, 200), methods=["GET"])
    return _app


__all__ = [
    "INTERNAL_CSV_COLUMNS",
    "InternalStageFlaskRoutes",
    "InternalStageRoutesBase",
    "TasInternalAtomic",
    "build_internal_stage_fastapi_app",
    "build_internal_stage_flask_app",
]

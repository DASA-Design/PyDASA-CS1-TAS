"""Build one FastAPI app per third-party atomic service (`MAS_*`, `AS_*`, `DS_*`).

The atomic app exposes:

- `POST /`: accepts a TAS-shaped payload (`req_id`, `kind`, `operation`, `inject_failure`, `submitted_ts`, ...), runs the failure dispatcher, then drives the atomic service through admission and handler. Medical-analysis services attach a `result` field (`changeDrug` / `changeDose` / `sendAlarm`) keyed deterministically off `req_id` so the composite workflow follows a reproducible branch.
- `GET /healthz`: readiness probe.

Per-invocation work is synthesised via `await asyncio.sleep(random.expovariate(mu))`. `mu` is the service rate in req/s from the active profile's `specs` layer (`data/config/profile/{dflt,opti}.json::specs[svc_id]`), not from the catalogue.

When `csv_dir` and `run_id` are supplied, each invocation appends one row to `<csv_dir>/<svc_name>__pid<PID>.csv`. The writer is opened lazily on first call inside each worker process, so multiprocess spawners get one file per `(service, pid)` pair without inter-process coordination.

The factory is top-level and `functools.partial`-bindable so it pickles across `multiprocessing.spawn` on Windows.
"""

from __future__ import annotations

import asyncio
import os
import random
import time
from pathlib import Path
from typing import Any

from fastapi import FastAPI
from fastapi.responses import JSONResponse
from starlette.responses import Response

from src.experimental.common.io.csv import CsvWriter
from src.experimental.prototype.target.factory.failure import (
    DFLT_TIMEOUT_GRACE_S,
    apply_inject_failure,
)
from src.experimental.prototype.target.factory.healthz import add_healthz_route
from src.experimental.prototype.target.service.atomic import AtomicService

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


class AtomicRoutes:
    """FastAPI route adapter binding one `TasAtomicService` to POST `/`.

    Lives at module scope (not nested in the factory closure) so FastAPI's signature machinery and Windows pickling both work.
    """

    def __init__(self,
                 *,
                 svc: TasAtomicService,
                 csv_dir: Path | None,
                 run_id: str | None,
                 timeout_grace_s: float) -> None:
        self._svc = svc
        self._csv_dir = csv_dir
        self._run_id = run_id
        self._timeout_grace_s = timeout_grace_s

    async def post_root(self, payload: dict[str, Any]) -> Response:
        """POST `/`: failure dispatch, then admission + handler, then per-pid CSV row."""
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

    def _log_csv_row(self,
                     payload: dict[str, Any],
                     *,
                     status: int,
                     body: dict[str, Any] | None) -> None:
        """Append one per-pid CSV row; no-op when `csv_dir` or `run_id` is missing."""
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


def build_atomic_fastapi_app(*,
                             svc_name: str,
                             kind: str,
                             mu: float,
                             k: int | None = None,
                             c: int | None = None,
                             csv_dir: str | None = None,
                             run_id: str | None = None,
                             timeout_grace_s: float = DFLT_TIMEOUT_GRACE_S) -> FastAPI:
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
    _routes = AtomicRoutes(svc=_svc,
                           csv_dir=_csv_path,
                           run_id=run_id,
                           timeout_grace_s=timeout_grace_s)
    _app = FastAPI()
    _app.add_api_route("/", _routes.post_root, methods=["POST"])
    add_healthz_route(_app)
    return _app


__all__ = [
    "ATOMIC_CSV_COLUMNS",
    "TasAtomicService",
    "build_atomic_fastapi_app",
]

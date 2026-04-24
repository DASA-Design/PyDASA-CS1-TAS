# -*- coding: utf-8 -*-
"""
Module services/base.py
=======================

Shared building blocks every service reads. No queueing logic lives here on purpose. Queue behaviour emerges from FastAPI and asyncio running requests concurrently, so we do not encode it with classes or admission counters.

Exports:
    - `SvcSpec`: frozen per-service knobs (mu, eps, c, K, seed, mem_per_buffer).
    - `derive_seed(root, name)`: deterministic per-component seed derivation.
    - `SvcReq`, `SvcResp`: pydantic wire schema.
    - `LOG_COLUMNS`: frozen per-invocation CSV schema.
    - `SvcCtx`: mutable per-service state (spec, log, rng). No counters, no semaphores.
    - `make_base_app(title, healthz_fn)`: bare FastAPI app with /healthz.
    - `HttpForward(client, registry)`: async `(target, req) -> SvcResp` over HTTP.
"""
# native python modules
from __future__ import annotations

import asyncio
import csv
import random
import uuid
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Awaitable, Callable, Deque, Dict, List, Optional, TYPE_CHECKING

# web stack
import httpx
from fastapi import FastAPI
from pydantic import BaseModel, Field

if TYPE_CHECKING:
    from src.experiment.registry import SvcRegistry


# ---------------------------------------------------------------------------
# SvcSpec + seed derivation


@dataclass(frozen=True)
class SvcSpec:
    """**SvcSpec** immutable per-service knobs.

    Declares the inputs that shape emergent queue behaviour: service rate, failure rate, concurrency ceiling, capacity, seed, memory budget. Downstream models (analytic, stochastic, dimensional) read these values together with measured timestamps to quantify what actually emerged at runtime.
    """

    # LaTeX-subscript key (e.g. `TAS_{1}`)
    name: str

    # workflow tag: composite_client/medical/alarm/drug, atomic
    role: str

    # TCP port (TAS components share; third-party get their own)
    port: int

    # service rate (req/s); drives the exponential service-time sleep
    mu: float

    # Bernoulli business-failure probability per completion
    epsilon: float

    # declared concurrency ceiling (not enforced as a semaphore here)
    c: int

    # declared system capacity (not enforced as a counter here)
    K: int

    # per-service RNG seed; 0 = unseeded fallback
    seed: int = 0

    # declared buffer memory in bytes; downstream derives actual usage
    mem_per_buffer: int = 0

    # headroom factor applied over K * avg_request_size to derive `mem_per_buffer`
    MEM_HEADROOM_FACTOR: float = 1.5

    @property
    def buffer_budget_bytes(self) -> int:
        """Declared memory budget in bytes; 0 when undeclared."""
        return int(self.mem_per_buffer)


def derive_seed(root_seed: int, service_name: str) -> int:
    """*derive_seed()* stable 64-bit per-service seed from `(root, name)`.

    Folds the UTF-8 bytes of the service name through FNV-1a and XORs in the root seed. Stable across Python processes, distinct per service, distinct per root. One JSON knob (`experiment.json::seed`) then controls every stochastic draw in the apparatus.

    Args:
        root_seed (int): single seed from `experiment.json::seed`.
        service_name (str): LaTeX-subscript artifact key (e.g. `TAS_{1}`).

    Returns:
        int: 64-bit non-negative seed for `random.Random`.
    """
    _h = 0xCBF29CE484222325
    _prime = 0x100000001B3
    _mask = (1 << 64) - 1
    for _b in service_name.encode("utf-8"):
        _h ^= _b
        _h = (_h * _prime) & _mask
    _h ^= (int(root_seed) & _mask)
    _h = (_h * _prime) & _mask
    return _h


# ---------------------------------------------------------------------------
# Wire schemas


class SvcReq(BaseModel):
    """**SvcReq** pydantic wire schema for every component invocation."""

    # client UUID; stable across every hop
    request_id: str = Field(default_factory=lambda: str(uuid.uuid4()))

    # request kind; TAS_{1}'s kind-router reads this
    kind: str = "analyse"

    # payload size in bytes; feeds the memory-usage coefficient downstream
    size_bytes: int = 128

    # mock payload body produced by src.experiment.payload.generate_payload
    payload: Dict[str, Any] = Field(default_factory=dict)


class SvcResp(BaseModel):
    """**SvcResp** pydantic wire schema returned by every component."""

    # echoes the request's UUID for end-to-end tracing
    request_id: str

    # which component produced this response
    service_name: str

    # True on HTTP 200 + business success; False on Bernoulli-ε business failure
    success: bool

    # free-text diagnostic ("ok", "bernoulli failure", "terminal", etc.)
    message: str = ""


# ---------------------------------------------------------------------------
# Frozen per-invocation CSV schema. Every component logs one row per
# invocation into `app.state.<context>.log` through the @instrumented
# decorator. Downstream re-estimators depend on this order; any change
# is a breaking change.

LOG_COLUMNS = (
    "request_id", "service_name", "kind",
    "recv_ts", "start_ts", "end_ts",
    "c_used_at_start",
    "success", "status_code",
    "size_bytes",
)


# ---------------------------------------------------------------------------
# Minimal per-service state; just what the annotation needs to write
# one CSV row per invocation. No counters, no semaphores, no in_system.


@dataclass
class SvcCtx:
    """**SvcCtx** mutable per-service state.

    Carries the spec (so rows carry `service_name`), a bounded log buffer (where `@logger` appends rows), a seeded RNG (so service-time and Bernoulli draws stay reproducible under the single config seed), the bound request handler (set by `mount_atomic_svc` after the handler is built, so composite callers can dispatch siblings in-process), and an asyncio.Semaphore initialised with `spec.c` permits so the `@logger` decorator can gate concurrent admission and measure real Wq / rho instead of asyncio's natural concurrency.

    The log is a `collections.deque` with `maxlen=LOG_BUFFER_MAXLEN`; any append past that cap silently drops the OLDEST row (deque semantics) and increments `dropped_count`. A healthy run asserts `dropped_count == 0` at shutdown; a non-zero value signals the buffer was sized too small for the workload and measurements are incomplete.
    """

    # immutable per-service knobs
    spec: SvcSpec

    # CSV rows buffered until flush -- bounded deque to prevent unbounded
    # memory growth on long or high-rate runs. `maxlen` is a soft cap:
    # overflow increments `dropped_count`, which must be zero at end of
    # run (checked by the launcher). dict shape is preserved so every
    # downstream reader (`_build_svc_df_from_logs`, the schema tests)
    # stays unchanged.
    log: Deque[Dict[str, Any]] = field(init=False)

    # count of rows silently dropped because the log deque was full.
    # zero on a well-sized run; non-zero means the run needs a larger
    # buffer OR the load was higher than the calibration assumed.
    dropped_count: int = field(default=0, init=False)

    # bound on the log deque's length. Sized for ~500 krequests per
    # service across the full replicate window at the target rates in
    # `data/config/method/experiment.json`. A single run at 345 req/s
    # for 60 s x 4 hops produces ~82 k rows per service; the 500 k cap
    # leaves ~6x headroom.
    log_maxlen: int = field(default=500_000)

    # per-service RNG seeded from spec.seed
    rng: random.Random = field(init=False)

    # admission semaphore: spec.c permits gate concurrent handler execution
    # so wait-for-permit time is measurable as Wq and the simultaneous
    # in-service count is measurable as c_used_at_start
    sem: asyncio.Semaphore = field(init=False)

    # bound request handler; set by mount_atomic_svc after build
    handler: Optional[Callable[..., Any]] = field(default=None, init=False, repr=False)

    def __post_init__(self) -> None:
        if self.spec.seed:
            self.rng = random.Random(self.spec.seed)
        else:
            self.rng = random.Random()
        self.log = deque(maxlen=int(self.log_maxlen))
        # Semaphore must be created in an asyncio context, but since dataclass
        # init runs synchronously, allocate it here -- safe because the
        # launcher mounts services inside the running event loop
        self.sem = asyncio.Semaphore(max(int(self.spec.c), 1))

    def record_row(self, row: Dict[str, Any]) -> None:
        """*record_row()* append a log row; count a drop if the deque was already full.

        Called from `@logger` instead of `self.log.append(...)` so the
        overflow path is observable. `deque(maxlen=...)` silently drops the
        left-most element on append when full; we detect the drop by
        checking `len(self.log) == self.log.maxlen` before the append.

        Args:
            row (Dict[str, Any]): one CSV row in the `LOG_COLUMNS` shape.
        """
        if len(self.log) == self.log.maxlen:
            self.dropped_count += 1
        self.log.append(row)

    def drain(self) -> List[Dict[str, Any]]:
        """*drain()* swap the current log buffer for a fresh empty one and return the old contents.

        Cheap O(1) rebind so a producer appending during the swap cannot race the consumer. Used by `ExperimentLauncher.drain_all()` between probe steps; `flush_log` still reads `self.log` directly for the final disk write at replicate end.

        Returns:
            List[Dict[str, Any]]: every row buffered since the previous drain (or construction); the deque is reset to empty with the same `maxlen`.
        """
        _snapshot = list(self.log)
        self.log = deque(maxlen=int(self.log_maxlen))
        return _snapshot

    @property
    def c_in_use(self) -> int:
        """*c_in_use* number of permits currently held (server slots busy).

        `Semaphore._value` is the public-but-implementation-detail count of
        free permits; capacity minus free = in-use. Used by `@logger` to
        sample the PASTA observation `c_used_at_start`.
        """
        _free = int(getattr(self.sem, "_value", 0))
        _cap = max(int(self.spec.c), 1)
        return max(_cap - _free, 0)

    def draw_svc_time(self) -> float:
        """*draw_svc_time()* one exponential draw at rate `mu` from the seeded RNG; returns 0 when `mu == 0`."""
        if self.spec.mu <= 0:
            return 0.0
        return self.rng.expovariate(self.spec.mu)

    def draw_eps(self) -> bool:
        """*draw_eps()* one Bernoulli draw at rate `eps` from the seeded RNG; True means business failure fired."""
        return self.rng.random() < self.spec.epsilon

    def flush_log(self,
                  csv_path: Path,
                  columns: tuple[str, ...] = LOG_COLUMNS) -> int:
        """*flush_log()* write every buffered row to `csv_path` and clear the buffer.

        Always overwrites the target file so the on-disk header matches the
        current `LOG_COLUMNS` schema. Append-mode would silently misalign
        rows when an older CSV with a different column set lives at the
        same path (the user's CSVs from a stale schema would shift every
        new field one column to the right under pandas).

        Args:
            csv_path (Path): target CSV; parent directory is created if missing.
            columns (tuple): column order; defaults to `LOG_COLUMNS`.

        Returns:
            int: number of rows written.
        """
        _p = Path(csv_path)
        _p.parent.mkdir(parents=True, exist_ok=True)
        with _p.open("w", newline="", encoding="utf-8") as _fh:
            _w = csv.DictWriter(_fh, fieldnames=columns)
            _w.writeheader()
            for _row in self.log:
                _w.writerow({_k: _row.get(_k) for _k in columns})
        _n = len(self.log)
        self.log.clear()
        return _n


# ---------------------------------------------------------------------------
# FastAPI base app + HTTP forward callback


def make_base_app(title: str,
                  *,
                  healthz_fn: Optional[Callable[[], Dict[str, Any]]] = None,
                  ) -> FastAPI:
    """*make_base_app()* bare FastAPI app exposing `/healthz` and no other route.

    Practitioners attach invoke routes via `mount_atomic_svc` or `mount_composite_svc`, and attach service state via `app.state`.

    Args:
        title (str): FastAPI app title.
        healthz_fn (Optional[Callable]): callback returning the `/healthz` payload. Defaults to `{"ok": True}`.

    Returns:
        FastAPI: configured base app.
    """
    _app = FastAPI(title=title, version="1.0")

    @_app.get("/healthz")
    async def _healthz() -> Dict[str, Any]:
        if healthz_fn is None:
            return {"ok": True}
        return healthz_fn()

    return _app


# External-forward callback shape: used when a service's routing row
# picks a target that isn't local (for the composite service, "local"
# means a sibling member; for atomic, all targets are external).
ExtFwdFn = Callable[[str, SvcReq], Awaitable[SvcResp]]


class HttpForward:
    """**HttpForward** async callback `(target, req) -> SvcResp` over HTTP.

    Closes over a shared `httpx.AsyncClient` and a `SvcRegistry`. The client is routed by port to the in-process ASGI mesh by default; the launcher can swap the transport for real TCP.
    """

    def __init__(self,
                 client: httpx.AsyncClient,
                 registry: "SvcRegistry") -> None:
        self._client = client
        self._registry = registry

    async def __call__(self, target: str, req: SvcReq) -> SvcResp:
        """*__call__()* POST `req` to `target`'s invoke URL; return the parsed response.

        Args:
            target (str): downstream service name.
            req (SvcReq): request body, forwarded verbatim.

        Raises:
            httpx.HTTPStatusError: on non-2xx response (infrastructure failure).

        Returns:
            SvcResp: parsed body. Business failure (eps fired) comes back as HTTP 200 with `success=False`.
        """
        _r = await self._client.post(
            self._registry.build_invoke_url(target),
            json=req.model_dump(),
            headers={"X-Request-Id": req.request_id,
                     "X-Request-Size-Bytes": str(req.size_bytes),
                     "X-Request-Kind": req.kind})
        _r.raise_for_status()
        return SvcResp(**_r.json())

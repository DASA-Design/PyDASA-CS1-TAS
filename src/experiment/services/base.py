# -*- coding: utf-8 -*-
"""
Module services/base.py
=======================

Shared building blocks every service reads. Concurrency is gated by a c-permit semaphore (in-service) and a K counter (total in-flight); over-K arrivals get HTTP 503. The K-gate is a deployment tactic, not an M/M/c/K simulation.

Exports:
    - `SvcSpec`: frozen per-service knobs.
    - `SvcReq`, `SvcResp`: pydantic wire schema.
    - `SvcCtx`: mutable per-service state with c-semaphore + K-gate.
    - `LOG_COLUMNS`: frozen per-invocation CSV schema.
    - `derive_seed(root, name)`: deterministic per-component seed.
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
    from src.experiment.wire import SvcRegistry


# ---------------------------------------------------------------------------
# SvcSpec + seed derivation


@dataclass(frozen=True)
class SvcSpec:
    """**SvcSpec** frozen per-service knobs: `(mu, epsilon, c, K, seed, mem_per_buffer)`."""

    # LaTeX-subscript key (e.g. `TAS_{1}`)
    name: str

    # workflow tag: 'composite_client'. 'medical', 'alarm', 'drug', 'atomic'
    role: str

    # TCP port (TAS components share; third-party get their own)
    port: int

    # service rate (req/s); drives the exponential service-time sleep
    mu: float

    # Bernoulli business-failure probability per completion
    epsilon: float

    # service-side parallel handlers (M/M/c/K); alias `c_srv` below; wire-key stays `c` to mirror profile JSONs
    c: int

    # declared system capacity (not enforced as a counter here)
    K: int

    # per-service RNG seed; 0 = unseeded fallback
    seed: int = 0

    # declared buffer memory in bytes; downstream derives actual usage
    mem_per_buffer: int = 0

    # profile-wide K-gate switch; False -> try_admit always admits
    enforce_limits: bool = True

    # headroom factor applied over K * avg_request_size to derive `mem_per_buffer`
    MEM_HEADROOM_FACTOR: float = 1.5

    @property
    def buffer_budget_bytes(self) -> int:
        """*buffer_budget_bytes* declared memory budget in bytes; 0 when undeclared.

        Returns:
            int: `K * avg_req_size_b * MEM_HEADROOM_FACTOR`; 0 when undeclared.
        """
        return int(self.mem_per_buffer)

    @property
    def c_srv(self) -> int:
        """*c_srv* service-side parallel handlers (M/M/c/K); alias for `c` to clarify the role of this parameter at call sites.

        Returns:
            int: number of parallel servers in the M/M/c/K model from the configuration profile.
        """
        return self.c


def derive_seed(root_seed: int, srv_name: str) -> int:
    """*derive_seed()* return a stable 64-bit per-service seed from `(root, name)` via FNV-1a over the UTF-8 service name XORed with `root_seed`; stable across processes.

    Args:
        root_seed (int): single seed from `experiment.json::seed`.
        srv_name (str): LaTeX-subscript artifact key (e.g. `TAS_{1}`).

    Returns:
        int: 64-bit non-negative seed for `random.Random`.
    """
    _h = 0xCBF29CE484222325
    _prime = 0x100000001B3
    _mask = (1 << 64) - 1
    for _b in srv_name.encode("utf-8"):
        _h ^= _b
        _h = (_h * _prime) & _mask
    _h ^= (int(root_seed) & _mask)
    _h = (_h * _prime) & _mask
    return _h


# ---------------------------------------------------------------------------
# Wire schemas


class SvcReq(BaseModel):
    """**SvcReq** pydantic wire schema for every component invocation. Inherits `BaseModel` for body validation.
    """

    # client UUID; stable across every hop
    req_id: str = Field(default_factory=lambda: str(uuid.uuid4()))

    # request kind; TAS_{1}'s kind-router reads this
    kind: str = "analyse"

    # payload size in bytes; feeds the memory-usage coefficient downstream
    size_bytes: int = 128

    # mock payload body produced by src.experiment.payload.generate_payload
    payload: Dict[str, Any] = Field(default_factory=dict)


class SvcResp(BaseModel):
    """**SvcResp** pydantic wire schema returned by every component. Inherits `BaseModel` for body validation.
    """

    # echoes the request's UUID for end-to-end tracing
    req_id: str

    # which component produced this response
    srv_name: str

    # True on HTTP 200 + business success; False on Bernoulli-ε business failure
    success: bool

    # free-text diagnostic ("ok", "bernoulli failure", "terminal", etc.)
    message: str = ""


# ---------------------------------------------------------------------------
# frozen CSV schema; column order is a breaking-change contract
LOG_COLUMNS = (
    "req_id",
    "srv_name",
    "kind",
    "recv_ts",
    "start_ts",
    "local_end_ts",
    "end_ts",
    "c_used_at_start",
    "success",
    "status_code",
    "size_bytes",
)


# ---------------------------------------------------------------------------
# minimal per-service state for @logger


@dataclass
class SvcCtx:
    """**SvcCtx** mutable per-service state with c-semaphore + K-gate."""

    # immutable per-service knobs
    spec: SvcSpec

    # bounded CSV row buffer; overflow bumps `dropped_count`
    log: Deque[Dict[str, Any]] = field(init=False)

    # bigger than 0 means log buffer overflowed; must be 0 at shutdown
    dropped_count: int = field(default=0, init=False)

    # deque cap; 500k = ~6x headroom for a 345 req/s x 60 s x 4-hop run
    log_maxlen: int = field(default=500_000)

    # per-service RNG seeded from spec.seed
    rng: random.Random = field(init=False)

    # gates concurrent in-service handlers for spec.c_srv permits
    sem: asyncio.Semaphore = field(init=False)

    # in-flight count (waiting + in-service); gated against spec.K
    in_flight: int = field(default=0, init=False)

    # bound request handler; set by mount_atomic_svc after build
    handler: Optional[Callable[..., Any]] = field(default=None,
                                                  init=False,
                                                  repr=False)

    def __post_init__(self) -> None:
        if self.spec.seed:
            self.rng = random.Random(self.spec.seed)
        else:
            self.rng = random.Random()
        self.log = deque(maxlen=int(self.log_maxlen))
        # allocated inside the launcher's running event loop
        self.sem = asyncio.Semaphore(max(int(self.spec.c_srv), 1))

    def record_row(self, row: Dict[str, Any]) -> None:
        """*record_row()* append a log row; count a drop if the deque was already full. Silently drops the left-most element on append when full.

        Args:
            row (Dict[str, Any]): one CSV row in the `LOG_COLUMNS` shape.
        """

        if len(self.log) == self.log.maxlen:
            self.dropped_count += 1
        self.log.append(row)

    def drain(self) -> List[Dict[str, Any]]:
        """*drain()* swap the current log buffer for a fresh empty one and return the old contents. O(1) rebind; safe under concurrent appends.

        Returns:
            List[Dict[str, Any]]: all rows buffered since the previous drain (or construction).
        """
        _snapshot = list(self.log)
        # create a new deque instead of clearing the old
        self.log = deque(maxlen=int(self.log_maxlen))
        return _snapshot

    @property
    def c_in_use(self) -> int:
        """*c_in_use* number of currently busy server slots.

        Returns:
            int: number of permits currently held (server slots busy). Used by `@logger` to sample the PASTA observation `c_used_at_start`.
        """
        # gets the `Semaphore._value` to count free server slots
        _free = int(getattr(self.sem, "_value", 0))
        _cap = max(int(self.spec.c_srv), 1)
        return max(_cap - _free, 0)

    def try_admit(self) -> bool:
        """*try_admit()* check and count the in-flight requests against the spec.K max buffer capacity.

        No lock needed: under asyncio the read + increment runs as one Python step (no awaits between the compare and the bump).

        Returns:
            bool: True when admitted (counter incremented); False when rejected (counter unchanged).
        """
        # checks if there is available space
        if not self.spec.enforce_limits:
            self.in_flight += 1
            return True
        _K = int(self.spec.K)
        # completely free, border case for release() method
        if _K <= 0:
            self.in_flight += 1
            return True
        # check if the queue has space
        if self.in_flight >= _K:
            return False
        self.in_flight += 1
        return True

    def release(self) -> None:
        """*release()* decrement `in_flight` to signal that a request has completed and freed K-gate capacity."""
        # dont allow negative counter
        if self.in_flight > 0:
            self.in_flight -= 1

    def draw_svc_time(self) -> float:
        """*draw_svc_time()* simulate one service time by drawing from the seeded RNG's exponential distribution at rate `mu`.

        Returns:
            float: service time in seconds. Returns 0 when `mu` is 0 or negative (no sleep).
        """
        if self.spec.mu <= 0:
            return 0.0
        return self.rng.expovariate(self.spec.mu)

    def draw_eps(self) -> bool:
        """*draw_eps()* simulate one Bernoulli failure draw by comparing a seeded-RNG sample to `epsilon`.

        Returns:
            bool: True means the services failed, False means it succeeded. When `epsilon` is 0 or negative, always returns False (no failure)..
        """
        return self.rng.random() < self.spec.epsilon

    def flush_log(self,
                  csv_path: Path,
                  columns: tuple[str, ...] = LOG_COLUMNS) -> int:
        """*flush_log()* write all buffered log rows to a CSV at `csv_path` with the given column order, then clear the buffer. Overwrites (not appends) so a stale-schema CSV at the same path cannot misalign new rows.

        Args:
            csv_path (Path): target CSV; parent directory is created if missing.
            columns (tuple[str, ...], optional): column order; defaults to LOG_COLUMNS.

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
    """*make_base_app()* return a FastAPI app exposing only `/healthz`. Callers attach invoke routes via `mount_atomic_svc` / `mount_composite_svc` and attach service state via `app.state`.

    Args:
        title (str): FastAPI app title.
        healthz_fn (Optional[Callable[[], Dict[str, Any]]], optional): callback returning the `/healthz` payload. Defaults to None.

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


# callback shape for non-local routing targets (siblings are "local" on composite; all targets are external on atomic)
ExtFwdFn = Callable[[str, SvcReq], Awaitable[SvcResp]]


class HttpForward:
    """**HttpForward** async callback `(target, req) -> SvcResp` over HTTP. Holds a shared `httpx.AsyncClient` and a `SvcRegistry`. The client is routed by port to the in-process ASGI mesh by default; the launcher can swap the transport for real TCP.
    """

    def __init__(self,
                 client: httpx.AsyncClient,
                 registry: "SvcRegistry") -> None:
        self._client = client
        self._registry = registry

    async def __call__(self, target: str, req: SvcReq) -> SvcResp:
        """__call__ POST `req` to `target`'s invoke URL; return the parsed response.

        Args:
            target (str): downstream service name.
            req (SvcReq): request body, forwarded verbatim as JSON with extra headers for tracing and memory-usage logging.

        Raises:
            httpx.HTTPStatusError: on non-2xx response (infrastructure failure).

        Returns:
            SvcResp: parsed body. Business failure (eps fired) comes back as HTTP 200 with `success=False`.
        """
        _r = await self._client.post(
            self._registry.build_invoke_url(target),
            json=req.model_dump(),
            headers={"X-Request-Id": req.req_id,
                     "X-Request-Size-Bytes": str(req.size_bytes),
                     "X-Request-Kind": req.kind})
        _r.raise_for_status()
        return SvcResp(**_r.json())

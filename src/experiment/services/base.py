# -*- coding: utf-8 -*-
"""
Module services/base.py
=======================

Shared building blocks every service reads. No queueing logic lives
here on purpose. Queue behaviour emerges from FastAPI and asyncio
running requests concurrently, so we do not encode it with classes or
admission counters.

Exports:

    - `ServiceSpec`: frozen per-service knobs (mu, eps, c, K, seed, mem_per_buffer).
    - `derive_seed(root, name)`: deterministic per-component seed derivation.
    - `ServiceRequest`, `ServiceResponse`: pydantic wire schema.
    - `LOG_COLUMNS`: frozen per-invocation CSV schema.
    - `ServiceContext`: mutable per-service state (spec, log, rng). No counters, no semaphores.
    - `make_base_app(title, healthz_fn)`: bare FastAPI app with /healthz.
    - `HttpForward(client, registry)`: async `(target, req) -> ServiceResponse` over HTTP.
"""
# native python modules
from __future__ import annotations

import random
import uuid
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Dict, List, Optional

# web stack
import httpx
from fastapi import FastAPI
from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# ServiceSpec + seed derivation


@dataclass(frozen=True)
class ServiceSpec:
    """**ServiceSpec** immutable per-service knobs.

    Declares the inputs that shape emergent queue behaviour: service
    rate, failure rate, concurrency ceiling, capacity, seed, memory
    budget. Downstream models (analytic, stochastic, dimensional) read
    these values together with measured timestamps to quantify what
    actually emerged at runtime.
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

    Folds the UTF-8 bytes of the service name through FNV-1a and XORs
    in the root seed. Stable across Python processes, distinct per
    service, distinct per root. One JSON knob
    (`experiment.json::seed`) then controls every stochastic draw in
    the apparatus.

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


class ServiceRequest(BaseModel):
    """**ServiceRequest** pydantic wire schema for every component invocation."""

    # client UUID; stable across every hop
    request_id: str = Field(default_factory=lambda: str(uuid.uuid4()))

    # request kind; TAS_{1}'s kind-router reads this
    kind: str = "analyse"

    # payload size in bytes; feeds the memory-usage coefficient downstream
    size_bytes: int = 128

    # mock payload body produced by src.experiment.payload.generate_payload
    payload: Dict[str, Any] = Field(default_factory=dict)


class ServiceResponse(BaseModel):
    """**ServiceResponse** pydantic wire schema returned by every component."""

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
    "success", "status_code",
    "size_bytes",
)


# ---------------------------------------------------------------------------
# Minimal per-service state — just what the annotation needs to write
# one CSV row per invocation. No counters, no semaphores, no in_system.


@dataclass
class ServiceContext:
    """**ServiceContext** mutable per-service state.

    Carries exactly the three things the `@logger` decorator needs:
    the spec (so rows carry `service_name`), a log list (where rows
    are appended), and a seeded RNG (so service-time and Bernoulli
    draws stay reproducible under the single config seed).

    Holds no admission counter, no semaphore, and no `in_system`.
    Concurrency is whatever uvicorn and asyncio produce naturally
    under the declared ceiling `spec.c`.
    """

    # immutable per-service knobs
    spec: ServiceSpec

    # CSV rows buffered until flush
    log: List[Dict[str, Any]] = field(default_factory=list)

    # per-service RNG seeded from spec.seed
    rng: random.Random = field(init=False)

    def __post_init__(self) -> None:
        self.rng = random.Random(self.spec.seed) if self.spec.seed else random.Random()

    def draw_svc_time(self) -> float:
        """*draw_svc_time()* one exponential draw at rate `mu` from the seeded RNG; returns 0 when `mu == 0`."""
        return self.rng.expovariate(self.spec.mu) if self.spec.mu > 0 else 0.0

    def draw_eps(self) -> bool:
        """*draw_eps()* one Bernoulli draw at rate `eps` from the seeded RNG; True means business failure fired."""
        return self.rng.random() < self.spec.epsilon

    def flush_log(self, csv_path, columns=LOG_COLUMNS) -> int:
        """*flush_log()* append every buffered row to `csv_path` and clear the buffer.

        Args:
            csv_path (Path): target CSV; parent directory is created if missing.
            columns (tuple): column order; defaults to `LOG_COLUMNS`.

        Returns:
            int: number of rows written.
        """
        import csv as _csv
        from pathlib import Path as _Path
        _p = _Path(csv_path)
        _p.parent.mkdir(parents=True, exist_ok=True)
        _new = not _p.exists()
        with _p.open("a", newline="", encoding="utf-8") as _fh:
            _w = _csv.DictWriter(_fh, fieldnames=columns)
            if _new:
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

    Practitioners attach invoke routes via `mount_atomic_service` or
    `mount_composite_service`, and attach service state via `app.state`.

    Args:
        title (str): FastAPI app title.
        healthz_fn (Optional[Callable]): callback returning the `/healthz` payload. Defaults to `{"ok": True}`.

    Returns:
        FastAPI: configured base app.
    """
    _app = FastAPI(title=title, version="1.0")

    @_app.get("/healthz")
    async def _healthz() -> Dict[str, Any]:
        return healthz_fn() if healthz_fn is not None else {"ok": True}

    return _app


# External-forward callback shape: used when a service's routing row
# picks a target that isn't local (for the composite service, "local"
# means a sibling member; for atomic, all targets are external).
ExternalForwardFn = Callable[[str, ServiceRequest], Awaitable[ServiceResponse]]


class HttpForward:
    """**HttpForward** async callback `(target, req) -> ServiceResponse` over HTTP.

    Closes over a shared `httpx.AsyncClient` and a `ServiceRegistry`.
    The client is routed by port to the in-process ASGI mesh by
    default; the launcher can swap the transport for real TCP.
    """

    def __init__(self, client: httpx.AsyncClient, registry) -> None:
        self._client = client
        self._registry = registry

    async def __call__(self, target: str, req: ServiceRequest) -> ServiceResponse:
        """*__call__()* POST `req` to `target`'s invoke URL; return the parsed response.

        Args:
            target (str): downstream service name.
            req (ServiceRequest): request body, forwarded verbatim.

        Raises:
            httpx.HTTPStatusError: on non-2xx response (infrastructure failure).

        Returns:
            ServiceResponse: parsed body. Business failure (eps fired) comes back as HTTP 200 with `success=False`.
        """
        _r = await self._client.post(
            self._registry.build_invoke_url(target),
            json=req.model_dump(),
            headers={"X-Request-Id": req.request_id,
                     "X-Request-Size-Bytes": str(req.size_bytes),
                     "X-Request-Kind": req.kind})
        _r.raise_for_status()
        return ServiceResponse(**_r.json())

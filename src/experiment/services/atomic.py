# -*- coding: utf-8 -*-
"""
Module services/atomic.py
=========================

Atomic-service module (no class). One function,
`mount_atomic_service`, attaches the atomic-service handler to a
FastAPI app. The handler sleeps for the simulated service time, draws
a Bernoulli at rate eps, and either returns a business failure, falls
through to a "terminal" success when the routing row is empty, or
picks a next hop via the seeded RNG and forwards through
`external_forward`. The whole thing is wrapped with `@logger(ctx)` so
one CSV row lands in `ctx.log` per call.

Queueing stays emergent: concurrent requests queue naturally through
asyncio, and we do not simulate admission counters or semaphores.
"""
# native python modules
from __future__ import annotations

import asyncio
from typing import List, Tuple

# web stack
from fastapi import FastAPI

# local modules
from src.experiment.services.base import (ExternalForwardFn,
                                          ServiceContext,
                                          ServiceRequest,
                                          ServiceResponse,
                                          ServiceSpec)
from src.experiment.services.instruments import logger


def mount_atomic_service(app: FastAPI,
                         spec: ServiceSpec,
                         targets: List[Tuple[str, float]],
                         external_forward: ExternalForwardFn,
                         *,
                         route: str = "/invoke") -> ServiceContext:
    """*mount_atomic_service()* attach one POST route running the atomic handler through `@logger`.

    Args:
        app (FastAPI): app to attach the route to.
        spec (ServiceSpec): per-service knobs.
        targets (List[Tuple[str, float]]): Jackson-weighted outbound routing row in declaration order. Empty means terminal; the handler returns success immediately after service time.
        external_forward (ExternalForwardFn): async `(target, req) -> ServiceResponse`. Typically an `HttpForward` instance.
        route (str): URL path. Defaults to `"/invoke"`.

    Returns:
        ServiceContext: per-service state `(spec, log, rng)`. Attached to `app.state.ctx` so the launcher can reach `.log` for flushing.
    """
    _ctx = ServiceContext(spec=spec)
    app.state.ctx = _ctx

    _names: List[str] = [_t for _t, _ in targets]
    _weights: List[float] = [float(_w) for _, _w in targets]

    @logger(_ctx)
    async def _handler(req: ServiceRequest) -> ServiceResponse:
        # simulate service time: exponential draw at rate mu
        _svc = _ctx.draw_svc_time()
        if _svc > 0:
            await asyncio.sleep(_svc)

        # Bernoulli eps: local business failure
        if _ctx.draw_eps():
            return ServiceResponse(request_id=req.request_id,
                                   service_name=spec.name,
                                   success=False,
                                   message="bernoulli failure")

        # routing: terminal when the row is empty
        if not _names:
            return ServiceResponse(request_id=req.request_id,
                                   service_name=spec.name,
                                   success=True,
                                   message="terminal")

        # Jackson-weighted pick, then external HTTP forward
        _target = _ctx.rng.choices(_names, weights=_weights, k=1)[0]
        _inner = await external_forward(_target, req)
        return ServiceResponse(request_id=req.request_id,
                               service_name=spec.name,
                               success=_inner.success,
                               message=_inner.message)

    # FastAPI passes request via DI; we only need `req`, so we expose
    # a clean one-arg coroutine to the framework
    async def _route(req: ServiceRequest) -> ServiceResponse:
        return await _handler(req)

    app.add_api_route(route, _route, methods=["POST"],
                      response_model=ServiceResponse)
    return _ctx

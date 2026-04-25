# -*- coding: utf-8 -*-
"""
Module services/vernier.py
==========================

Vernier-service module (no class). One function, `mount_vernier_svc`, attaches a terminal echo handler to a FastAPI app for host-floor calibration. Mirrors `mount_atomic_svc` (admission semaphore, exponential service-time draw, Bernoulli epsilon, `@logger` row recording) but drops the routing axis entirely: vernier is a leaf service. The handler reads `req.payload['blob']` end-to-end so the request body actually traverses the kernel buffer + ASGI stack, making `phi` (memory-usage coefficient) informative on a constant-payload workload.

The single `SvcSpec` knob set (mu, epsilon, c, K, mem_per_buffer) is supplied by the calibration runner from `data/config/method/calibration.json` keys (`payload_size_bytes`, `sweep_grid.c[0]`, `sweep_grid.K[0]`); see `notes/scale.md` for the resolution table.

Public API:
    - `mount_vernier_svc(app, spec, payload_size_bytes, *, route='/invoke') -> SvcCtx`
"""
# native python modules
from __future__ import annotations

import asyncio

# web stack
from fastapi import FastAPI

# local modules
from src.experiment.services.base import (SvcCtx,
                                          SvcReq,
                                          SvcResp,
                                          SvcSpec)
from src.experiment.services.instruments import logger, mark_admit_time


def mount_vernier_svc(app: FastAPI,
                      spec: SvcSpec,
                      payload_size_bytes: int = 0,
                      *,
                      route: str = "/invoke") -> SvcCtx:
    """*mount_vernier_svc()* attach one POST route running a terminal echo handler through `@logger`.

    Mirrors `mount_atomic_svc`'s admission + service-time + Bernoulli step order, then returns a terminal `SvcResp` instead of forwarding to a downstream target. Reads `len(req.payload['blob'])` inside the gated section so the payload bytes are touched end-to-end and `phi` becomes a real measurement signal on a constant-payload workload.

    Args:
        app (FastAPI): app to attach the route to.
        spec (SvcSpec): per-service knobs (mu, epsilon, c, K, mem_per_buffer). Vernier honours every field; mu/epsilon are typically zero at calibration time so the loopback floor stays honest.
        payload_size_bytes (int): declared payload size echoed in `SvcResp.message`. Records the configured size for downstream cross-checks against the recorded `size_bytes` CSV column. Defaults to 0 (no declared payload).
        route (str): URL path. Defaults to `"/invoke"` so the standard `SvcReq`-bodied probes work without a route override.

    Returns:
        SvcCtx: per-service state `(spec, log, rng, sem, handler)`. Attached to `app.state.ctx` so calibration probes can reach `.log` for flushing.
    """
    _ctx = SvcCtx(spec=spec)
    app.state.ctx = _ctx

    _declared_size = int(payload_size_bytes)

    @logger(_ctx)
    async def _handler(req: SvcReq) -> SvcResp:
        # 1. admission gate. spec.c permits cap concurrent in-service; excess
        #    arrivals wait here and the wait becomes measurable Wq.
        async with _ctx.sem:
            mark_admit_time(_ctx.c_in_use)

            _svc = _ctx.draw_svc_time()
            if _svc > 0:
                await asyncio.sleep(_svc)

            # 2. Bernoulli epsilon: structurally 0 at calibration time, but
            #    the draw stays for code-path parity with mount_atomic_svc.
            if _ctx.draw_eps():
                return SvcResp(request_id=req.request_id,
                               service_name=spec.name,
                               success=False,
                               message="bernoulli failure")

            # 3. touch the payload end-to-end so the request body actually
            #    traverses the kernel buffer + ASGI stack. Without this the
            #    handler can return before the bytes leave the buffer and
            #    phi (memory-usage coefficient) measures nothing.
            _payload = req.payload or {}
            _blob = _payload.get("blob", "")
            _observed_size = len(_blob)

        # 4. terminal response; no downstream hop.
        _msg = f"terminal size_bytes={_observed_size} declared={_declared_size}"
        return SvcResp(request_id=req.request_id,
                       service_name=spec.name,
                       success=True,
                       message=_msg)

    _ctx.handler = _handler

    async def _route(req: SvcReq) -> SvcResp:
        return await _handler(req)

    app.add_api_route(route,
                      _route,
                      methods=["POST"],
                      response_model=SvcResp)
    return _ctx

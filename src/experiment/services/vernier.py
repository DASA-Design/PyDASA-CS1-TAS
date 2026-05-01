# -*- coding: utf-8 -*-
"""
Module services/vernier.py
==========================

Terminal echo service for host-floor calibration. Mirrors `mount_atomic_svc` (K-gate, c-semaphore, mu sleep, eps draw, `@logger`) minus routing; reads `req.payload['blob']` end-to-end so `phi` is measurable on constant-payload workloads.

Public API:
    - `mount_vernier_svc(app, spec, payload_size_bytes, *, route='/invoke') -> SvcCtx`
"""
# native python modules
from __future__ import annotations

import asyncio

# web stack
from fastapi import FastAPI, HTTPException

# local modules
from src.experiment.services.base import (SvcCtx,
                                          SvcReq,
                                          SvcResp,
                                          SvcSpec)
from src.experiment.services.instruments import (LogProbe,
                                                 logger,
                                                 stamp_admit)


class VernierHandler:
    """*VernierHandler* simulate one calibration probe against the host's transport floor. Each call enforces the same capacity limits as a regular service node, waits a service-time draw, may fail on the configured Bernoulli, and touches the request payload end-to-end so the memory-usage coefficient `phi` becomes measurable on a constant-payload workload. There is no downstream hop; every successful call terminates here. FastAPI uses the instance directly as a route handler and `@logger` records a CSV row around every call."""

    def __init__(self,
                 ctx: SvcCtx,
                 spec: SvcSpec,
                 declared_size: int) -> None:
        """*__init__()* bind per-service state for the lifetime of the mount.

        Args:
            ctx (SvcCtx): per-service runtime state (semaphore, RNG, log, in-flight counter). Required field for `@logger`.
            spec (SvcSpec): per-service knobs (name, mu, epsilon, c, K).
            declared_size (int): payload size echoed in `SvcResp.message` for downstream cross-checks against the recorded `size_bytes` CSV column.
        """
        self.ctx = ctx
        self.spec = spec
        self.declared_size = declared_size

    @logger
    async def __call__(self, req: SvcReq, probe: LogProbe) -> SvcResp:
        """*__call__()* handle one calibration request. The call is rejected with HTTP 503 when the K admission counter is already at capacity; otherwise the handler waits for a service permit, simulates the configured service time, optionally fails on the Bernoulli, reads the request payload, and returns the terminal success response. The K counter is decremented on every exit path so a rejected, errored, or successful call all keep the in-flight count consistent.

        Args:
            req (SvcReq): inbound calibration request; `req_id` is propagated to the emitted `SvcResp`.
            probe (LogProbe): per-invocation log where `stamp_admit` deposits timestamps; `@logger` reads it to populate the CSV row after this method returns.

        Returns:
            SvcResp: terminal success response, or Bernoulli-failure response.

        Raises:
            HTTPException: 503 when the K admission gate rejects the call.
        """
        if not self.ctx.try_admit():
            _msg = f"capacity exceeded (K={self.spec.K}) at {self.spec.name}"
            raise HTTPException(status_code=503,
                                detail=_msg)
        try:
            # c-permit gate: spec.c caps concurrent in-service; excess waiters become measurable Wq.
            async with self.ctx.sem:
                probe.admit_ts = stamp_admit()
                probe.c_used_at_start = self.ctx.c_in_use

                _svc = self.ctx.draw_svc_time()
                if _svc > 0:
                    await asyncio.sleep(_svc)

                # Bernoulli is structurally 0 at calibration time, but the draw stays for code-path parity.
                if self.ctx.draw_eps():
                    return SvcResp(req_id=req.req_id,
                                   srv_name=self.spec.name,
                                   success=False,
                                   message="bernoulli failure")

                # touch the payload end-to-end so the request body actually traverses the kernel buffer + ASGI stack; without this, phi (memory-usage coefficient) measures nothing.
                _payload = req.payload or {}
                _blob = _payload.get("blob", "")
                _observed_size = len(_blob)

            _msg = (f"terminal size_bytes={_observed_size} "
                    f"declared={self.declared_size}")
            return SvcResp(req_id=req.req_id,
                           srv_name=self.spec.name,
                           success=True,
                           message=_msg)
        finally:
            self.ctx.release()


def mount_vernier_svc(app: FastAPI,
                      spec: SvcSpec,
                      payload_size_bytes: int = 0,
                      *,
                      route: str = "/invoke") -> SvcCtx:
    """*mount_vernier_svc()* build a `VernierHandler`, register it under `route` as a POST endpoint on `app`, and store it as `ctx.handler` so calibration probes can call it directly without going through HTTP.

    Args:
        app (FastAPI): app to attach the route to.
        spec (SvcSpec): per-service knobs (mu, epsilon, c, K, mem_per_buffer). Vernier honours every field; mu/epsilon are typically zero at calibration time so the loopback floor stays honest.
        payload_size_bytes (int): declared payload size echoed in `SvcResp.message` for downstream cross-checks against the recorded `size_bytes` CSV column. Defaults to 0.
        route (str): URL path. Defaults to `"/invoke"`.

    Returns:
        SvcCtx: per-service state attached to `app.state.ctx`; `.handler` holds the `VernierHandler` instance so calibration probes can flush `.log`.
    """
    _ctx = SvcCtx(spec=spec)
    app.state.ctx = _ctx

    _vernier = VernierHandler(ctx=_ctx,
                              spec=spec,
                              declared_size=int(payload_size_bytes))
    _ctx.handler = _vernier

    app.add_api_route(route,
                      _vernier,
                      methods=["POST"],
                      response_model=SvcResp)
    return _ctx

# -*- coding: utf-8 -*-
"""
Module services/atomic.py
=========================

Atomic-service handler (sleep -> Bernoulli -> Jackson-pick -> forward) for a FastAPI app. K-gate (total in-flight requests) + c-semaphore (concurrent in-service handlers); going over-K raises HTTP 503. Composite callers can override `pick_tgt` / `dispatch`.
"""
# native python modules
from __future__ import annotations

import asyncio
from typing import Awaitable, Callable, List, Optional, Tuple

# web stack
from fastapi import FastAPI, HTTPException

# local modules
from src.experiment.services.base import (ExtFwdFn,
                                          SvcCtx,
                                          SvcReq,
                                          SvcResp,
                                          SvcSpec)
from src.experiment.services.instruments import (LogProbe,
                                                 logger,
                                                 stamp_admit,
                                                 stamp_local_end)


PickTargetFn = Callable[[SvcCtx, SvcReq], Optional[str]]
DispatchFn = Callable[[str, SvcReq], Awaitable[SvcResp]]


class AtomicHandler:
    """*AtomicHandler* simulate one service node of the queueing network. Each call enforces the node's capacity limits, waits a draw from the service-time distribution, may fail with the node's configured failure probability, and then either terminates the request or hands it off to a downstream node. FastAPI uses the instance directly as a route handler; `@logger` records a CSV row around every call so downstream metrics (rho, L, W) can be derived from the trace."""

    def __init__(self,
                 ctx: SvcCtx,
                 spec: SvcSpec,
                 names: List[str],
                 weights: List[float],
                 ext_fwd: ExtFwdFn,
                 pick_tgt: Optional[PickTargetFn],
                 dispatch: Optional[DispatchFn]) -> None:
        """*__init__()* bind per-service state for the lifetime of the mount.

        Args:
            ctx (SvcCtx): per-service runtime state (semaphore, RNG, log, in-flight counter). Required field for `@logger`.
            spec (SvcSpec): per-service knobs (name, mu, epsilon, c, K).
            names (List[str]): outbound target names extracted from the routing row.
            weights (List[float]): Jackson weights aligned with `names`.
            ext_fwd (ExtFwdFn): launcher-supplied async forward used by the default dispatch.
            pick_tgt (PickTargetFn | None): override target picking; None falls back to `_jackson_pick`.
            dispatch (DispatchFn | None): override target forwarding; None falls back to `_external_dispatch`.
        """
        self.ctx = ctx
        self.spec = spec
        self.names = names
        self.weights = weights
        self.ext_fwd = ext_fwd
        self.pick_tgt = pick_tgt
        self.dispatch = dispatch

    def _jackson_pick(self) -> Optional[str]:
        """*_jackson_pick()* return `self.ctx.rng.choices(self.names, weights=self.weights, k=1)[0]` when `self.names` is non-empty; return None otherwise so `__call__` takes the terminal branch. Used as the `pick_tgt` default when the caller of `mount_atomic_svc` doesn't pass one.

        Returns:
            Optional[str]: name drawn from `self.names` according to `self.weights`, or None when `self.names` is empty.
        """
        if not self.names:
            return None
        return self.ctx.rng.choices(self.names,
                                    weights=self.weights, k=1)[0]

    async def _external_dispatch(self,
                                 tgt: str,
                                 req: SvcReq) -> SvcResp:
        """*_external_dispatch()* return `await self.ext_fwd(tgt, req)`. Used as the `dispatch` default when the caller of `mount_atomic_svc` doesn't pass one; `self.ext_fwd` is typically an `HttpForward` instance that posts to the downstream service over HTTP.

        Args:
            tgt (str): downstream service name.
            req (SvcReq): request to relay; `req_id` is preserved end-to-end.

        Returns:
            SvcResp: response returned by the request.
        """
        return await self.ext_fwd(tgt, req)

    @logger
    async def __call__(self, req: SvcReq, probe: LogProbe) -> SvcResp:
        """*__call__()* run the full atomic pipeline for one invocation: K-admit, c-acquire, sleep, Bernoulli, pick, forward. Releases the K counter on every exit path via `finally`. The decorator threads `probe` in and reads its fields after this method returns.

        Args:
            req (SvcReq): inbound request; `req_id` is propagated through every emitted `SvcResp`.
            probe (LogProbe): per-invocation record where `stamp_admit` / `stamp_local_end` deposit timestamps; `@logger` reads it to populate the CSV row after this method returns.

        Returns:
            SvcResp: terminal/success response, Bernoulli-failure response, or wrapped downstream response.

        Raises:
            HTTPException: 503 when the K admission gate rejects the call.
        """
        if not self.ctx.try_admit():
            _msg = f"capacity exceeded (K={self.spec.K}) at {self.spec.name}"
            raise HTTPException(status_code=503,
                                detail=_msg)
        try:
            # c-permit held only around local work so composite chains do not deadlock.
            async with self.ctx.sem:
                probe.admit_ts = stamp_admit()
                probe.c_used_at_start = self.ctx.c_in_use

                _svc = self.ctx.draw_svc_time()
                if _svc > 0:
                    await asyncio.sleep(_svc)

                if self.ctx.draw_eps():
                    return SvcResp(req_id=req.req_id,
                                   srv_name=self.spec.name,
                                   success=False,
                                   message="bernoulli failure")

            # terminal branch leaves local_end_ts defaulted to end_ts.
            if self.pick_tgt is not None:
                _target = self.pick_tgt(self.ctx, req)
            else:
                _target = self._jackson_pick()
            if _target is None:
                return SvcResp(req_id=req.req_id,
                               srv_name=self.spec.name,
                               success=True,
                               message="terminal")

            # stamp_local_end brackets B_local from the downstream dispatch await.
            probe.local_end_ts = stamp_local_end()
            if self.dispatch is not None:
                _inner = await self.dispatch(_target, req)
            else:
                _inner = await self._external_dispatch(_target, req)
            return SvcResp(req_id=req.req_id,
                           srv_name=self.spec.name,
                           success=_inner.success,
                           message=_inner.message)
        finally:
            self.ctx.release()


def mount_atomic_svc(app: FastAPI,
                     spec: SvcSpec,
                     targets: List[Tuple[str, float]],
                     ext_fwd: ExtFwdFn,
                     *,
                     route: str = "/invoke",
                     pick_tgt: Optional[PickTargetFn] = None,
                     dispatch: Optional[DispatchFn] = None) -> SvcCtx:
    """*mount_atomic_svc()* build an `AtomicHandler`, register it under `route` as a POST endpoint on `app`, and store it as `ctx.handler` so composite callers can call `ctx.handler(req)` in-process without going through HTTP.

    Args:
        app (FastAPI): app to attach the route to.
        spec (SvcSpec): per-service knobs (name, mu, epsilon, c, K).
        targets (List[Tuple[str, float]]): Jackson-weighted routing row; empty -> terminal branch.
        ext_fwd (ExtFwdFn): async `(tgt, req) -> SvcResp` used by the default dispatch.
        route (str): URL path. Defaults to `"/invoke"`.
        pick_tgt (PickTargetFn | None): override target picking; None -> `_jackson_pick`.
        dispatch (DispatchFn | None): override target forwarding; None -> `_external_dispatch`.

    Returns:
        SvcCtx: per-service state attached to `app.state.ctx`; `.handler` holds the `AtomicHandler` instance.
    """
    _ctx = SvcCtx(spec=spec)
    app.state.ctx = _ctx

    _names: List[str] = [_t for _t, _ in targets]
    _weights: List[float] = [_w for _, _w in targets]

    _atomic = AtomicHandler(ctx=_ctx,
                             spec=spec,
                             names=_names,
                             weights=_weights,
                             ext_fwd=ext_fwd,
                             pick_tgt=pick_tgt,
                             dispatch=dispatch)
    _ctx.handler = _atomic

    app.add_api_route(route,
                      _atomic,
                      methods=["POST"],
                      response_model=SvcResp)
    return _ctx

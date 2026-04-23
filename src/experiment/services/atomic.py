# -*- coding: utf-8 -*-
"""
Module services/atomic.py
=========================

Atomic-service module (no class). One function, `mount_atomic_svc`, attaches a handler to a FastAPI app. The handler sleeps for the simulated service time, draws a Bernoulli at rate `epsilon`, picks a routing target, and forwards. The whole thing is wrapped with `@logger(ctx)` so one CSV row lands in `ctx.log` per call, and the built handler is stashed on `ctx.handler` so composite callers can dispatch siblings in-process without going through FastAPI.

Two optional extension points let composite callers (TAS target system) reuse this machinery without re-implementing the step order:

    - `pick_target`: replace the Jackson-weighted pick with a custom target-picker (e.g. kind-based dispatch). Return `None` to force the terminal branch.
    - `dispatch`: replace the forward step (e.g. "check an in-process handler dict first; fall back to `external_forward`").

Both default to the plain atomic behaviour used by third-party services (MAS / AS / DS). Queueing stays emergent; no admission counters or semaphores are simulated.
"""
# native python modules
from __future__ import annotations

import asyncio
from typing import Awaitable, Callable, List, Optional, Tuple

# web stack
from fastapi import FastAPI

# local modules
from src.experiment.services.base import (ExtFwdFn,
                                          SvcCtx,
                                          SvcReq,
                                          SvcResp,
                                          SvcSpec)
from src.experiment.services.instruments import logger


PickTargetFn = Callable[[SvcCtx, SvcReq], Optional[str]]
DispatchFn = Callable[[str, SvcReq], Awaitable[SvcResp]]


def mount_atomic_svc(app: FastAPI,
                     spec: SvcSpec,
                     targets: List[Tuple[str, float]],
                     external_forward: ExtFwdFn,
                     *,
                     route: str = "/invoke",
                     pick_target: Optional[PickTargetFn] = None,
                     dispatch: Optional[DispatchFn] = None) -> SvcCtx:
    """*mount_atomic_svc()* attach one POST route running the atomic handler through `@logger`.

    Args:
        app (FastAPI): app to attach the route to.
        spec (SvcSpec): per-service knobs.
        targets (List[Tuple[str, float]]): Jackson-weighted outbound routing row in declaration order. Empty means the default `pick_target` returns None, routing the request to the terminal branch.
        external_forward (ExtFwdFn): async `(target, req) -> SvcResp`. Typically an `HttpForward` instance. Used by the default `dispatch`; callers that override `dispatch` may ignore it.
        route (str): URL path. Defaults to `"/invoke"`.
        pick_target (PickTargetFn | None): override for the target-picking step. Receives `(ctx, req)` and returns the target name, or `None` to force the terminal branch. Defaults to a Jackson-weighted pick over `targets`.
        dispatch (DispatchFn | None): override for the forward step. Receives `(target, req)` and returns the target's `SvcResp`. Defaults to `await external_forward(target, req)`.

    Returns:
        SvcCtx: per-service state `(spec, log, rng, handler)`. Attached to `app.state.ctx` so atomic callers can reach `.log` for flushing; composite callers also read `.handler` for in-process sibling dispatch.
    """
    _ctx = SvcCtx(spec=spec)
    app.state.ctx = _ctx

    # default Jackson pick closes over `targets` and the ctx RNG
    _names: List[str] = [_t for _t, _ in targets]
    _weights: List[float] = [float(_w) for _, _w in targets]

    if pick_target is None:
        def pick_target(_pctx: SvcCtx,
                        _preq: SvcReq) -> Optional[str]:
            if not _names:
                return None
            return _pctx.rng.choices(_names, weights=_weights, k=1)[0]

    # default forward: delegate to the launcher-supplied external_forward
    if dispatch is None:
        async def dispatch(_dtarget: str,
                           _dreq: SvcReq) -> SvcResp:
            return await external_forward(_dtarget, _dreq)

    @logger(_ctx)
    async def _handler(req: SvcReq) -> SvcResp:
        # 1. simulate service time
        _svc = _ctx.draw_svc_time()
        if _svc > 0:
            await asyncio.sleep(_svc)

        # 2. Bernoulli epsilon: local business failure
        if _ctx.draw_eps():
            return SvcResp(request_id=req.request_id,
                           service_name=spec.name,
                           success=False,
                           message="bernoulli failure")

        # 3. pick target; None means terminal
        _target = pick_target(_ctx, req)
        if _target is None:
            return SvcResp(request_id=req.request_id,
                           service_name=spec.name,
                           success=True,
                           message="terminal")

        # 4. dispatch to the picked target
        _inner = await dispatch(_target, req)
        return SvcResp(request_id=req.request_id,
                       service_name=spec.name,
                       success=_inner.success,
                       message=_inner.message)

    _ctx.handler = _handler

    # FastAPI passes request via DI; expose a clean one-arg coroutine
    async def _route(req: SvcReq) -> SvcResp:
        return await _handler(req)

    app.add_api_route(route,
                      _route,
                      methods=["POST"],
                      response_model=SvcResp)
    return _ctx

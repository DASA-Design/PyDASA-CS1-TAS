# -*- coding: utf-8 -*-
"""
Module services/instruments.py
==============================

Aspect-oriented annotation that records one CSV row per invocation around a handler. Framework-agnostic: works on any async coroutine with signature `(req: SvcReq) -> SvcResp`. The decorator tracks timestamps and outcome; it does not admit, queue, or gate concurrency.

Queue behaviour emerges from FastAPI and asyncio running requests concurrently. We capture only the observable side (receipt, start, end, outcome) so downstream methods can derive rho, L, and W from the recorded rows.
"""
# native python modules
from __future__ import annotations

import time
from functools import wraps
from typing import Awaitable, Callable

# local modules
from src.experiment.services.base import (SvcCtx,
                                          SvcReq,
                                          SvcResp)


# signature required by the decorator's wrapped handler
HandlerFn = Callable[[SvcReq], Awaitable[SvcResp]]


def logger(ctx: SvcCtx) -> Callable[[HandlerFn], HandlerFn]:
    """*@logger(ctx)* decorator: append one row to `ctx.log` around each call.

    Writes per-invocation rows in the frozen `LOG_COLUMNS` shape. The wrapped handler's return value passes through unchanged; its `success` flag is recorded as the local outcome ONLY when the response's `service_name` matches this context. When it does not match, the response came from a downstream, so this row records local success (eps did not fire here) regardless of the rolled-up downstream value.

    If the handler raises, a failure row is appended before the exception propagates so row counts match arrival counts.

    Args:
        ctx (SvcCtx): per-service state carrying `spec`, `log`, and `rng`.

    Returns:
        Callable: decorator that wraps a handler coroutine.
    """
    def _decorator(handler: HandlerFn) -> HandlerFn:
        @wraps(handler)
        async def _wrapped(req: SvcReq) -> SvcResp:
            _recv_ts = time.time()

            # no separate queue-wait phase; start == recv
            _start_ts = _recv_ts

            try:
                _resp = await handler(req)
            except Exception as _exc:
                _end_ts = time.time()
                _status = getattr(_exc, "status_code", 500)
                ctx.log.append({
                    "request_id": req.request_id,
                    "service_name": ctx.spec.name,
                    "kind": req.kind,
                    "recv_ts": _recv_ts,
                    "start_ts": _start_ts,
                    "end_ts": _end_ts,
                    "success": False,
                    "status_code": int(_status),
                    "size_bytes": req.size_bytes,
                })
                raise

            _end_ts = time.time()

            # local outcome only; downstream success does not apply here
            if _resp.service_name == ctx.spec.name:
                _local_success = bool(_resp.success)
            else:
                _local_success = True

            ctx.log.append({
                "request_id": req.request_id,
                "service_name": ctx.spec.name,
                "kind": req.kind,
                "recv_ts": _recv_ts,
                "start_ts": _start_ts,
                "end_ts": _end_ts,
                "success": _local_success,
                "status_code": 200,
                "size_bytes": req.size_bytes,
            })
            return _resp
        return _wrapped
    return _decorator

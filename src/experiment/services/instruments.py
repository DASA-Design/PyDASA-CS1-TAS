# -*- coding: utf-8 -*-
"""
Module services/instruments.py
==============================

Aspect-oriented annotation that records one CSV row per invocation around a handler. Framework-agnostic: works on any async coroutine with signature `(req: SvcReq) -> SvcResp`. The decorator tracks timestamps and outcome; it does not admit, queue, or gate concurrency.

Queue behaviour emerges from FastAPI and asyncio running requests concurrently. We capture only the observable side (receipt, start, end, outcome) so downstream methods can derive rho, L, and W from the recorded rows.
"""
# native python modules
from __future__ import annotations

import contextvars
import time
from functools import wraps
from typing import Awaitable, Callable, Optional

# local modules
from src.experiment.services.base import (SvcCtx,
                                          SvcReq,
                                          SvcResp)


# signature required by the decorator's wrapped handler
HandlerFn = Callable[[SvcReq], Awaitable[SvcResp]]


# per-task admit-time channel: an atomic handler calls `mark_admit_time()`
# right after its semaphore acquire, so `@logger` can use that timestamp as
# `start_ts` and the difference `start_ts - recv_ts` becomes real Wq.
# Composite handlers do not gate, so they never set this and their Wq
# correctly reads as 0
_admit_var: contextvars.ContextVar[Optional[float]] = contextvars.ContextVar(
    "admit_ts", default=None)
_c_used_var: contextvars.ContextVar[Optional[int]] = contextvars.ContextVar(
    "c_used_at_admit", default=None)


def mark_admit_time(c_used: int) -> None:
    """*mark_admit_time()* publish post-admission timestamp + in-flight count.

    Atomic handlers call this from inside their `async with ctx.sem:` block;
    `@logger` reads both back when writing the row so `start_ts` reflects
    when the request actually started service (not just when it arrived)
    and `c_used_at_start` reflects admitted concurrency, not asyncio's
    natural concurrency.

    Args:
        c_used (int): in-flight count after this request acquired its permit.
    """
    _admit_var.set(time.perf_counter())
    _c_used_var.set(int(c_used))


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
            # bracketing timestamps for response-time R; the handler is
            # responsible for any admission gating around its local work
            # (composite handlers cannot be gated here without deadlocking
            # the downstream dispatch chain). Atomic handlers publish a
            # post-admit timestamp via `mark_admit_time()`; if absent
            # (composite path), Wq reads 0 -- correct for an un-gated node
            _recv_ts = time.perf_counter()
            _admit_var.set(None)
            _c_used_var.set(None)

            try:
                _resp = await handler(req)
            except Exception as _exc:
                _end_ts = time.perf_counter()
                _start_ts = _admit_var.get() or _recv_ts
                _c_used_at_start = _c_used_var.get()
                if _c_used_at_start is None:
                    _c_used_at_start = ctx.c_in_use
                _status = getattr(_exc, "status_code", 500)
                ctx.log.append({
                    "request_id": req.request_id,
                    "service_name": ctx.spec.name,
                    "kind": req.kind,
                    "recv_ts": _recv_ts,
                    "start_ts": _start_ts,
                    "end_ts": _end_ts,
                    "c_used_at_start": int(_c_used_at_start),
                    "success": False,
                    "status_code": int(_status),
                    "size_bytes": req.size_bytes,
                })
                raise

            _end_ts = time.perf_counter()
            _start_ts = _admit_var.get() or _recv_ts
            _c_used_at_start = _c_used_var.get()
            if _c_used_at_start is None:
                _c_used_at_start = ctx.c_in_use

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
                "c_used_at_start": int(_c_used_at_start),
                "success": _local_success,
                "status_code": 200,
                "size_bytes": req.size_bytes,
            })
            return _resp
        return _wrapped
    return _decorator

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


# per-task channel: atomic handlers publish post-admit ts; composites leave it None so Wq reads 0.
_admit_var: contextvars.ContextVar[Optional[float]] = contextvars.ContextVar(
    "admit_ts", default=None)
_c_used_var: contextvars.ContextVar[Optional[int]] = contextvars.ContextVar(
    "c_used_at_admit", default=None)

# per-task channel: dispatching handlers publish local-end ts; terminals leave it None so it defaults to end_ts.
_local_end_var: contextvars.ContextVar[Optional[int]] = contextvars.ContextVar(
    "local_end_ts", default=None)


# ns -> float seconds for the CSV row; hot path stamps in `perf_counter_ns` to dodge float drift.
_NS_TO_S: float = 1_000_000_000.0


def mark_admit_time(c_used: int) -> None:
    """*mark_admit_time()* publish post-admit ts + in-flight count for `@logger`'s `start_ts` and `c_used_at_start`.

    Args:
        c_used (int): in-flight count after this request acquired its permit.
    """
    _admit_var.set(time.perf_counter_ns())
    _c_used_var.set(int(c_used))


def mark_local_end() -> None:
    """*mark_local_end()* publish ts at end of local work for `@logger`'s `local_end_ts` (B_local bracket)."""
    _local_end_var.set(time.perf_counter_ns())


def logger(ctx: SvcCtx) -> Callable[[HandlerFn], HandlerFn]:
    """*@logger(ctx)* append one `LOG_COLUMNS` row to `ctx.log` per call; local-success when `_resp.service_name == ctx.spec.name` else `True`; raised exceptions land a failure row before propagating.

    Args:
        ctx (SvcCtx): per-service state carrying `spec`, `log`, and `rng`.

    Returns:
        Callable: decorator that wraps a handler coroutine.
    """
    def _decorator(handler: HandlerFn) -> HandlerFn:
        @wraps(handler)
        async def _wrapped(req: SvcReq) -> SvcResp:
            # hot-path stamps in `perf_counter_ns`; converted to float seconds only when the dict row is populated.
            _recv_ns = time.perf_counter_ns()
            _admit_var.set(None)
            _c_used_var.set(None)
            _local_end_var.set(None)

            try:
                _resp = await handler(req)
            except Exception as _exc:
                _end_ns = time.perf_counter_ns()
                _start_ns = _admit_var.get() or _recv_ns
                _local_end_ns = _local_end_var.get() or _end_ns
                _c_used_at_start = _c_used_var.get()
                if _c_used_at_start is None:
                    _c_used_at_start = ctx.c_in_use
                _status = getattr(_exc, "status_code", 500)
                _row_fail = {
                    "request_id": req.request_id,
                    "service_name": ctx.spec.name,
                    "kind": req.kind,
                    "recv_ts": _recv_ns / _NS_TO_S,
                    "start_ts": _start_ns / _NS_TO_S,
                    "local_end_ts": _local_end_ns / _NS_TO_S,
                    "end_ts": _end_ns / _NS_TO_S,
                    "c_used_at_start": int(_c_used_at_start),
                    "success": False,
                    "status_code": int(_status),
                    "size_bytes": req.size_bytes,
                }
                ctx.record_row(_row_fail)
                raise

            _end_ns = time.perf_counter_ns()
            _start_ns = _admit_var.get() or _recv_ns
            _local_end_ns = _local_end_var.get() or _end_ns
            _c_used_at_start = _c_used_var.get()
            if _c_used_at_start is None:
                _c_used_at_start = ctx.c_in_use

            # local outcome only; downstream success does not apply here
            if _resp.service_name == ctx.spec.name:
                _local_success = bool(_resp.success)
            else:
                _local_success = True

            _row_ok = {
                "request_id": req.request_id,
                "service_name": ctx.spec.name,
                "kind": req.kind,
                "recv_ts": _recv_ns / _NS_TO_S,
                "start_ts": _start_ns / _NS_TO_S,
                "local_end_ts": _local_end_ns / _NS_TO_S,
                "end_ts": _end_ns / _NS_TO_S,
                "c_used_at_start": int(_c_used_at_start),
                "success": _local_success,
                "status_code": 200,
                "size_bytes": req.size_bytes,
            }
            ctx.record_row(_row_ok)
            return _resp
        return _wrapped
    return _decorator

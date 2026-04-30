# -*- coding: utf-8 -*-
"""
Module services/instruments.py
==============================

Aspect-oriented `@logger` decorator that appends one CSV row per handler invocation. Framework-agnostic on any async `(SvcReq) -> SvcResp` coroutine; records observable timestamps + outcome only, leaving admission, queueing, and concurrency to the caller.
"""
# native python modules
from __future__ import annotations

from contextvars import ContextVar
# import contextvars
import time
from functools import wraps
from typing import Awaitable, Callable, Optional, cast

# local modules
from src.experiment.services.base import SvcCtx, SvcReq, SvcResp


HandlerFn = Callable[[SvcReq], Awaitable[SvcResp]]


# atomic handlers publish post-admit ts; composites leave None so Wq reads 0.
_admit_var: ContextVar[Optional[float]] = ContextVar("admit_ts",
                                                     default=None)
_c_used_var: ContextVar[Optional[int]] = ContextVar("c_used_at_admit",
                                                    default=None)

# dispatching handlers publish local-end ts; terminals leave None so it falls back to end_ts.
_local_end_var: ContextVar[Optional[int]] = ContextVar("local_end_ts",
                                                       default=None)


# hot path stamps in perf_counter_ns to dodge float drift; converts to float seconds at row time.
_NS_TO_S: float = 1_000_000_000.0


def mark_admit_time(c_used: int) -> None:
    """*mark_admit_time()* publish post-admit ts + in-flight count for `start_ts` and `c_used_at_start`.

    Args:
        c_used (int): in-flight count after this request acquired its permit.
    """
    _admit_var.set(time.perf_counter_ns())
    _c_used_var.set(int(c_used))


def mark_local_end() -> None:
    """*mark_local_end()* publish ts at end of local work for `local_end_ts` (B_local bracket)."""
    _local_end_var.set(time.perf_counter_ns())


def logger(ctx: SvcCtx) -> Callable[[HandlerFn], HandlerFn]:
    """*@logger(ctx)* append one `LOG_COLUMNS` row per call; local-success is `_resp.srv_name == ctx.spec.name and _resp.success`; downstream failures don't flip our flag; raised exceptions land a failure row before propagating.

    Args:
        ctx (SvcCtx): per-service state carrying `spec`, `log`, and counters.

    Returns:
        Callable: decorator that wraps a handler coroutine.
    """
    def _decorator(handler: HandlerFn) -> HandlerFn:
        @wraps(handler)
        async def _wrapped(req: SvcReq) -> SvcResp:
            _recv_ns = time.perf_counter_ns()
            _admit_var.set(None)
            _c_used_var.set(None)
            _local_end_var.set(None)

            _resp: Optional[SvcResp] = None
            _exc: Optional[BaseException] = None
            try:
                _resp = await handler(req)
            except Exception as _e:
                _exc = _e

            _end_ns = time.perf_counter_ns()
            _start_ns = _admit_var.get() or _recv_ns
            _local_end_ns = _local_end_var.get() or _end_ns
            _c_used = _c_used_var.get()
            if _c_used is None:
                _c_used = ctx.c_in_use

            if _exc is not None:
                _success = False
                _status = int(getattr(_exc, "status_code", 500))
            else:
                _resp_ok = cast(SvcResp, _resp)
                _status = 200
                if _resp_ok.srv_name == ctx.spec.name:
                    _success = bool(_resp_ok.success)
                else:
                    _success = True

            ctx.record_row({
                "req_id": req.req_id,
                "srv_name": ctx.spec.name,
                "kind": req.kind,
                "recv_ts": _recv_ns / _NS_TO_S,
                "start_ts": _start_ns / _NS_TO_S,
                "local_end_ts": _local_end_ns / _NS_TO_S,
                "end_ts": _end_ns / _NS_TO_S,
                "c_used_at_start": _c_used,
                "success": _success,
                "status_code": _status,
                "size_bytes": req.size_bytes,
            })

            if _exc is not None:
                raise _exc
            return cast(SvcResp, _resp)
        return _wrapped
    return _decorator

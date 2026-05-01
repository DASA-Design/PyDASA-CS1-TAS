# -*- coding: utf-8 -*-
"""
Module services/instruments.py
==============================

Aspect-oriented `@logger` decorator that appends one CSV row per handler invocation; records observable timestamps + outcome only and leaves admission, queueing, and concurrency to the caller. Per-invocation state flows through an explicit `LogProbe` object the decorator threads as the third arg of the wrapped method.
"""
# native python modules
from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Callable, Optional, cast

# local modules
from src.experiment.services.base import SvcCtx, SvcReq, SvcResp


# hot path stamps in perf_counter_ns to dodge float drift; converts to float seconds at row time.
_NS_TO_S: float = 1_000_000_000.0


@dataclass
class LogProbe:
    """*LogProbe* container for the three timestamp/count fields the `@logger` wrapper needs to populate a CSV row but cannot capture itself: `admit_ts` (perf_counter_ns at the moment the c-permit was acquired), `c_used_at_start` (in-flight count at that moment), and `local_end_ts` (perf_counter_ns at the end of local work, before any downstream await).

    The wrapper creates one instance per call, passes it to the wrapped method as a third arg, and reads its fields after the method returns.
    """
    # post-admit timestamp in ns; None until `stamp_admit` records it (composite handlers leave None so Wq reads 0).
    admit_ts: Optional[int] = None
    # in-flight count when this request acquired its permit; None until set.
    c_used_at_start: Optional[int] = None
    # end-of-local-work timestamp in ns; None for terminals (then end_ts is used).
    local_end_ts: Optional[int] = None


def stamp_admit() -> int:
    """*stamp_admit()* return `time.perf_counter_ns()`. Caller assigns the result to `probe.admit_ts` right after acquiring the c-permit, then assigns `probe.c_used_at_start = self.ctx.c_in_use` separately (no helper for that — it's a plain int read).

    Returns:
        int: `time.perf_counter_ns()` at the call site.
    """
    return time.perf_counter_ns()


def stamp_local_end() -> int:
    """*stamp_local_end()* return `time.perf_counter_ns()`. Caller assigns the result to `probe.local_end_ts` immediately before awaiting a downstream `dispatch` call, so `local_end_ts - start_ts` brackets the local-work portion of B and excludes downstream wait time.

    Returns:
        int: `time.perf_counter_ns()` at the call site.
    """
    return time.perf_counter_ns()


def logger(func: Callable) -> Callable:
    """*@logger* wrap an async service method so every call produces one row in the per-service log.

    The decorator records observable timing and outcome for each invocation. Timestamps come from the probe when the wrapped method has set them; otherwise the wrapper falls back to its own stamps taken on entry and exit. The local service is treated as successful unless its own response says otherwise: a downstream failure flowing through this node does not pollute the row written for this node. When the wrapped method raises, the failure is captured with the exception's HTTP status if available and a 500 default, then the exception propagates to the caller after the row is recorded. FastAPI only sees the two-argument shape, which lets it bind the request body without knowing the probe exists.

    Args:
        func (Callable): async method `(self, req, probe) -> SvcResp` to wrap.

    Returns:
        Callable: wrapped async method with FastAPI-visible signature `(self, req)`.
    """
    async def wrapper(self, req: SvcReq) -> SvcResp:
        _ctx: SvcCtx = self.ctx
        _probe = LogProbe()
        _recv_ns = time.perf_counter_ns()

        _resp: Optional[SvcResp] = None
        _exc: Optional[BaseException] = None
        try:
            _resp = await func(self, req, _probe)
        except Exception as _e:
            _exc = _e

        _end_ns = time.perf_counter_ns()
        _start_ns = _probe.admit_ts or _recv_ns
        _local_end_ns = _probe.local_end_ts or _end_ns
        _c_used = _probe.c_used_at_start
        if _c_used is None:
            _c_used = _ctx.c_in_use

        if _exc is not None:
            _success = False
            _status = int(getattr(_exc, "status_code", 500))
        else:
            _resp_ok = cast(SvcResp, _resp)
            _status = 200
            if _resp_ok.srv_name == _ctx.spec.name:
                _success = bool(_resp_ok.success)
            else:
                _success = True

        _ctx.record_row({
            "req_id": req.req_id,
            "srv_name": _ctx.spec.name,
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

    # copy identity attrs without setting __wrapped__ so FastAPI signature inspection stops here.
    wrapper.__name__ = getattr(func, "__name__", "wrapper")
    wrapper.__qualname__ = getattr(func, "__qualname__", wrapper.__name__)
    wrapper.__doc__ = func.__doc__
    wrapper.__module__ = getattr(func, "__module__", wrapper.__module__)
    return wrapper

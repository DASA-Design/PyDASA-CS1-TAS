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
    """*LogProbe* per-invocation scratchpad written by `stamp_*` helpers and read by `@logger`. The decorator creates one probe per call and threads it as the third arg of the wrapped method.
    """
    # ost-admit timestamp in ns; None until `stamp_admit` records it (composite handlers leave None so Wq reads 0).
    admit_ts: Optional[int] = None
    # in-flight count when this request acquired its permit; None until set.
    c_used_at_start: Optional[int] = None
    # end-of-local-work timestamp in ns; None for terminals (then end_ts is used).
    local_end_ts: Optional[int] = None


def stamp_admit() -> int:
    """*stamp_admit()* capture admit_ts_ns for the caller to record on its `LogProbe`. The matching `c_used_at_start` is a plain attribute assignment at the call site.

    Returns:
        int: perf_counter_ns at the moment of admission.
    """
    return time.perf_counter_ns()


def stamp_local_end() -> int:
    """*stamp_local_end()* capture local_end_ts_ns for the caller to record on its `LogProbe`.

    Returns:
        int: perf_counter_ns at end of local work (B_local bracket; before any downstream await).
    """
    return time.perf_counter_ns()


def logger(func: Callable) -> Callable:
    """*@logger* wrap an async method `(self, req, probe) -> SvcResp` and append one `LOG_COLUMNS` row to `self.ctx.log` per call. The wrapper creates a `LogProbe`, passes it in, then reads its fields after the body returns. Local-success requires `resp.srv_name == ctx.spec.name and resp.success`; exceptions land a failure row, then re-raise. FastAPI sees the wrapper's 2-arg `(self, req)` signature; `__wrapped__` is intentionally not set so signature inspection stops here.

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

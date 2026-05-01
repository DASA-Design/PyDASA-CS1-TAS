# -*- coding: utf-8 -*-
"""
Module test_instruments.py
==========================

Unit tests for `src/experiment/services/instruments.py`:

    - **TestLogger** the `@logger` decorator on a callable class with `self.ctx` appends one correctly-shaped row per call; local success is NOT contaminated by downstream failure; exceptions are recorded as failure rows.
    - **TestStampHelpers** `stamp_admit` / `stamp_local_end` return monotonic ns timestamps for the caller to record on its `LogProbe`.
"""
# native python modules
import time
from typing import Awaitable, Callable

# testing framework
import pytest

# modules under test
from src.experiment.services import (LOG_COLUMNS,
                                     SvcCtx,
                                     SvcReq,
                                     SvcResp,
                                     logger)
from src.experiment.services.instruments import (LogProbe,
                                                 stamp_admit,
                                                 stamp_local_end)

# helper modules
from tests.utils.helpers import _SpecBuilder

# helper callables
PayloadFn = Callable[[SvcReq], Awaitable[SvcResp]]


@pytest.fixture
def specs() -> _SpecBuilder:
    """*specs()* yield a callable that builds a `SvcSpec`; override defaults via kwargs at the call site."""
    return _SpecBuilder()


class _LoggedProbe:
    """*_LoggedProbe* test scaffold: `__call__(self, req, probe)` returns `await self._payload(req)`, wrapped by `@logger`. Each test passes a different `_payload` coroutine to inject the response (or exception) the decorator should observe; `self.ctx` is the SvcCtx the decorator records the row into."""

    def __init__(self, ctx: SvcCtx, payload: PayloadFn) -> None:
        self.ctx = ctx
        self._payload = payload

    @logger
    async def __call__(self, req: SvcReq, probe: LogProbe) -> SvcResp:
        return await self._payload(req)


class TestLogger:
    """**TestLogger** the decorator appends one correctly-shaped row per call."""

    @pytest.mark.asyncio
    async def test_success_row(self, specs: _SpecBuilder) -> None:
        """*test_success_row()* after one successful call: `len(ctx.log) == 1`, the row's keys are a superset of `LOG_COLUMNS`, `status_code == 200`, `success is True`, `req_id`/`srv_name`/`kind`/`size_bytes` match the request, and `end_ts >= recv_ts`."""
        _ctx = SvcCtx(spec=specs())

        async def _payload(req: SvcReq) -> SvcResp:
            return SvcResp(req_id=req.req_id,
                           srv_name=_ctx.spec.name,
                           success=True)

        _handler = _LoggedProbe(_ctx, _payload)
        _req = SvcReq(kind="analyse", size_bytes=128)
        _resp = await _handler(_req)
        assert _resp.success is True
        assert len(_ctx.log) == 1
        _row = _ctx.log[0]
        assert set(LOG_COLUMNS).issubset(_row.keys())
        assert _row["req_id"] == _req.req_id
        assert _row["srv_name"] == _ctx.spec.name
        assert _row["kind"] == "analyse"
        assert _row["success"] is True
        assert _row["status_code"] == 200
        assert _row["size_bytes"] == 128
        assert _row["end_ts"] >= _row["recv_ts"]

    @pytest.mark.asyncio
    async def test_local_success_isolated(self, specs: _SpecBuilder) -> None:
        """*test_local_success_isolated()* when `ctx.spec.name == "TAS_{2}"` and the handler returns `SvcResp(srv_name="MAS_{1}", success=False)`, the row this decorator writes for `ctx` has `success=True` (the False belongs to the downstream service, not to us)."""
        _ctx = SvcCtx(spec=specs(name="TAS_{2}"))

        async def _payload(req: SvcReq) -> SvcResp:
            return SvcResp(req_id=req.req_id,
                           srv_name="MAS_{1}",
                           success=False,
                           message="bernoulli failure")

        _handler = _LoggedProbe(_ctx, _payload)
        await _handler(SvcReq())
        assert _ctx.log[-1]["success"] is True

    @pytest.mark.asyncio
    async def test_exception_row(self, specs: _SpecBuilder) -> None:
        """*test_exception_row()* when the wrapped method raises `RuntimeError`, the wrapper appends one row with `success=False` to `ctx.log` and then re-raises, so `pytest.raises(RuntimeError)` catches the exception and `len(ctx.log) == 1` afterward."""
        _ctx = SvcCtx(spec=specs())

        async def _payload(_req: SvcReq) -> SvcResp:
            raise RuntimeError("downstream blew up")

        _handler = _LoggedProbe(_ctx, _payload)
        with pytest.raises(RuntimeError):
            await _handler(SvcReq())
        assert len(_ctx.log) == 1
        assert _ctx.log[0]["success"] is False

    @pytest.mark.asyncio
    async def test_probe_stamps_threaded(self, specs: _SpecBuilder) -> None:
        """*test_probe_stamps_threaded()* when the wrapped method writes `probe.admit_ts = stamp_admit()`, `probe.c_used_at_start = 7`, `probe.local_end_ts = stamp_local_end()`, the resulting row has `c_used_at_start == 7` and `start_ts <= local_end_ts <= end_ts` (i.e. the wrapper used the probe values, not the `recv_ts` / `end_ts` / `ctx.c_in_use` fallbacks)."""
        _ctx = SvcCtx(spec=specs())

        class _Stamped:
            def __init__(self, ctx: SvcCtx) -> None:
                self.ctx = ctx

            @logger
            async def __call__(self, req: SvcReq, probe: LogProbe) -> SvcResp:
                probe.admit_ts = stamp_admit()
                probe.c_used_at_start = 7
                probe.local_end_ts = stamp_local_end()
                return SvcResp(req_id=req.req_id,
                               srv_name=self.ctx.spec.name,
                               success=True)

        _handler = _Stamped(_ctx)
        await _handler(SvcReq())
        _row: dict = _ctx.log[0]
        assert _row["c_used_at_start"] == 7
        _con_1: bool = _row["start_ts"] <= _row["local_end_ts"]
        _con_2: bool = _row["local_end_ts"] <= _row["end_ts"]
        assert _con_1 and _con_2


class TestStampHelpers:
    """**TestStampHelpers** the `stamp_*` helpers return monotonic perf-counter ns values."""

    def test_admit_monotonic(self) -> None:
        """*test_admit_monotonic()* `t0 = perf_counter_ns(); ts = stamp_admit(); t1 = perf_counter_ns()` satisfies `t0 <= ts <= t1`."""
        _t0: int = time.perf_counter_ns()
        _ts: int = stamp_admit()
        _t1: int = time.perf_counter_ns()
        _con_1: bool = _t0 <= _ts
        _con_2: bool = _ts <= _t1
        assert _con_1 and _con_2

    def test_local_end_monotonic(self) -> None:
        """*test_local_end_monotonic()* `t0 = perf_counter_ns(); ts = stamp_local_end(); t1 = perf_counter_ns()` satisfies `t0 <= ts <= t1`."""
        _t0: int = time.perf_counter_ns()
        _ts: int = stamp_local_end()
        _t1: int = time.perf_counter_ns()
        _con_1: bool = _t0 <= _ts
        _con_2: bool = _ts <= _t1
        assert _con_1 and _con_2

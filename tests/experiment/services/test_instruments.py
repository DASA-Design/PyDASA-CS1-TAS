# -*- coding: utf-8 -*-
"""
Module test_instruments.py
==========================

Unit tests for `src/experiment/services/instruments.py`:

    - **TestLogger** the `@logger(ctx)` decorator appends one correctly-shaped row per call; local success is NOT contaminated by downstream failure; exceptions are recorded as failure rows.
"""
# testing framework
import pytest

# modules under test
from src.experiment.services import (LOG_COLUMNS,
                                     SvcCtx,
                                     SvcReq,
                                     SvcResp,
                                     SvcSpec,
                                     logger)


def _spec(**kwargs) -> SvcSpec:
    """*_spec()* build a SvcSpec with sensible defaults; override via kwargs."""
    _defaults = dict(name="MAS_{1}", role="atomic", port=8006,
                     mu=1000.0, epsilon=0.0, c=1, K=10, seed=42)
    _defaults.update(kwargs)
    return SvcSpec(**_defaults)


class TestLogger:
    """**TestLogger** the decorator appends one correctly-shaped row per call."""

    @pytest.mark.asyncio
    async def test_one_row_per_successful_call(self):
        """*test_one_row_per_successful_call()* one log row appended per call with full LOG_COLUMNS coverage + HTTP 200 + monotonic timestamps."""
        _ctx = SvcCtx(spec=_spec())

        @logger(_ctx)
        async def _handler(req: SvcReq) -> SvcResp:
            return SvcResp(request_id=req.request_id,
                                   service_name=_ctx.spec.name,
                                   success=True)

        _req = SvcReq(kind="analyse", size_bytes=128)
        _resp = await _handler(_req)
        assert _resp.success is True
        assert len(_ctx.log) == 1
        _row = _ctx.log[0]
        assert set(LOG_COLUMNS).issubset(_row.keys())
        assert _row["request_id"] == _req.request_id
        assert _row["service_name"] == _ctx.spec.name
        assert _row["kind"] == "analyse"
        assert _row["success"] is True
        assert _row["status_code"] == 200
        assert _row["size_bytes"] == 128
        assert _row["end_ts"] >= _row["recv_ts"]

    @pytest.mark.asyncio
    async def test_local_success_not_contaminated_by_downstream(self):
        """*test_local_success_not_contaminated_by_downstream()* when the handler returns a DOWNSTREAM response (different `service_name`) with `success=False`, THIS context's row stays `success=True` (local Bernoulli didn't fire)."""
        _ctx = SvcCtx(spec=_spec(name="TAS_{2}"))

        @logger(_ctx)
        async def _handler(req: SvcReq) -> SvcResp:
            # simulate a downstream that failed its own Bernoulli
            return SvcResp(request_id=req.request_id,
                                   service_name="MAS_{1}",
                                   success=False,
                                   message="bernoulli failure")

        await _handler(SvcReq())
        assert _ctx.log[-1]["success"] is True

    @pytest.mark.asyncio
    async def test_exception_recorded_as_failure_row(self):
        """*test_exception_recorded_as_failure_row()* a handler that raises still appends one log row (success=False) before the exception propagates, so row counts match arrival counts."""
        _ctx = SvcCtx(spec=_spec())

        @logger(_ctx)
        async def _handler(_req: SvcReq) -> SvcResp:
            raise RuntimeError("downstream blew up")

        with pytest.raises(RuntimeError):
            await _handler(SvcReq())
        assert len(_ctx.log) == 1
        assert _ctx.log[0]["success"] is False

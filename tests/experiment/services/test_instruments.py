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
                                     ServiceContext,
                                     ServiceRequest,
                                     ServiceResponse,
                                     ServiceSpec,
                                     logger)


def _spec(**kwargs) -> ServiceSpec:
    """*_spec()* build a ServiceSpec with sensible defaults; override via kwargs."""
    _defaults = dict(name="MAS_{1}", role="atomic", port=8006,
                     mu=1000.0, epsilon=0.0, c=1, K=10, seed=42)
    _defaults.update(kwargs)
    return ServiceSpec(**_defaults)


class TestLogger:
    """**TestLogger** the decorator appends one correctly-shaped row per call."""

    @pytest.mark.asyncio
    async def test_one_row_per_successful_call(self):
        _ctx = ServiceContext(spec=_spec())

        @logger(_ctx)
        async def _handler(req: ServiceRequest) -> ServiceResponse:
            return ServiceResponse(request_id=req.request_id,
                                   service_name=_ctx.spec.name,
                                   success=True)

        _req = ServiceRequest(kind="analyse", size_bytes=128)
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
        """When the handler returns a DOWNSTREAM response (different service_name) with success=False, THIS context's row stays success=True (local Bernoulli didn't fire)."""
        _ctx = ServiceContext(spec=_spec(name="TAS_{2}"))

        @logger(_ctx)
        async def _handler(req: ServiceRequest) -> ServiceResponse:
            # simulate a downstream that failed its own Bernoulli
            return ServiceResponse(request_id=req.request_id,
                                   service_name="MAS_{1}",
                                   success=False,
                                   message="bernoulli failure")

        await _handler(ServiceRequest())
        assert _ctx.log[-1]["success"] is True

    @pytest.mark.asyncio
    async def test_exception_recorded_as_failure_row(self):
        _ctx = ServiceContext(spec=_spec())

        @logger(_ctx)
        async def _handler(_req: ServiceRequest) -> ServiceResponse:
            raise RuntimeError("downstream blew up")

        with pytest.raises(RuntimeError):
            await _handler(ServiceRequest())
        assert len(_ctx.log) == 1
        assert _ctx.log[0]["success"] is False

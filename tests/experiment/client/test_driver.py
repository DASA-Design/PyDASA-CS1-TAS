# -*- coding: utf-8 -*-
"""
Module test_driver.py
=====================

Pin the three `RateDriver.run(rate)` exit reasons.

    - **TestRateDriver** `samples_reached`, `probe_timeout`, `cascade: ...`.
"""
# native python modules
import random
from typing import List

# test stack
import pytest

# web stack
import httpx

# modules under test
from src.experiment.client.config import CascadeCfg, ClientCfg, RampCfg
from src.experiment.client.driver import RateDriver
from src.experiment.client.guard import StopGuard
from src.experiment.client.sender import RequestSender

# shared helpers
from tests.utils.helpers import (_err_503_httpx_handler,
                                 _make_mock_async_client,
                                 _ok_httpx_handler,
                                 _one_svc_registry)


def _build_driver(client: httpx.AsyncClient,
                  *,
                  guard: StopGuard,
                  rates: List[float],
                  min_n: int = 32,
                  max_probe_s: float = 5.0) -> RateDriver:
    """*_build_driver()* assemble a one-kind `RateDriver` over `kind="TAS_{2}"`.

    Args:
        client (httpx.AsyncClient): pre-configured async client routed at the mock transport.
        guard (StopGuard): infra-failure detector reused as the ramp `cascade`.
        rates (List[float]): target rates for the ramp.
        min_n (int): per-kind sample target. Defaults to 32.
        max_probe_s (float): per-probe safety timeout in seconds. Defaults to 5.0.

    Returns:
        RateDriver: driver wired to the supplied transport, sender, and guard.
    """
    _ramp = RampCfg(min_n_per_kind=min_n,
                    max_probe_s=max_probe_s,
                    rates=rates,
                    cascade=guard.cfg)
    _cfg = ClientCfg(seed=1,
                     kind_prob={"TAS_{2}": 1.0},
                     ramp=_ramp)
    _rng = random.Random(_cfg.seed)
    _sender = RequestSender(client,
                            _one_svc_registry(),
                            _cfg,
                            _rng)
    _drv = RateDriver(sender=_sender,
                      guard=guard,
                      ramp_cfg=_ramp,
                      kind_names=["TAS_{2}"],
                      kind_prob_norm=[1.0],
                      rng=_rng)
    return _drv


class TestRateDriver:
    """**TestRateDriver** exit reasons of one probe."""

    @pytest.mark.asyncio
    async def test_samples_reached(self) -> None:
        """*test_samples_reached()* clean handler -> `stopped_reason == 'samples_reached'`, `samples_per_kind['TAS_{2}'] >= 32`, `infra_fail_rate == 0.0`."""
        async with _make_mock_async_client(_ok_httpx_handler) as _client:
            _guard = StopGuard(CascadeCfg(mode="rolling",
                                          threshold=0.5,
                                          window=50))
            _drv = _build_driver(_client, guard=_guard, rates=[100.0])
            _out = await _drv.run(100.0)
        assert _out["stopped_reason"] == "samples_reached"
        assert _out["samples_per_kind"]["TAS_{2}"] >= 32
        assert _out["infra_fail_rate"] == 0.0

    @pytest.mark.asyncio
    async def test_cascade_stops(self) -> None:
        """*test_cascade_stops()* 503 handler + `fail_fast` guard -> `stopped_reason.startswith('cascade:')`, `guard.tripped is True`."""
        async with _make_mock_async_client(_err_503_httpx_handler) as _client:
            _guard = StopGuard(CascadeCfg(mode="fail_fast"))
            _drv = _build_driver(_client, guard=_guard, rates=[100.0])
            _out = await _drv.run(100.0)
        assert _out["stopped_reason"].startswith("cascade:")
        assert _guard.tripped is True

    @pytest.mark.asyncio
    async def test_probe_timeout(self) -> None:
        """*test_probe_timeout()* `min_n=1000, max_probe_s=0.5` at `rate=1.0` -> `stopped_reason == 'probe_timeout'`."""
        async with _make_mock_async_client(_ok_httpx_handler) as _client:
            _guard = StopGuard(CascadeCfg(mode="rolling",
                                          threshold=0.5,
                                          window=50))
            _drv = _build_driver(_client,
                                 guard=_guard,
                                 rates=[1.0],
                                 min_n=1000,
                                 max_probe_s=0.5)
            _out = await _drv.run(1.0)
        assert _out["stopped_reason"] == "probe_timeout"

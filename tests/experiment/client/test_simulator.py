# -*- coding: utf-8 -*-
"""
Module test_simulator.py
========================

Pin the `ClientSimulator.run_ramp` orchestration: schedule walking, halt on first guard trip, duration-weighted client-effective rate, deterministic kind sampling under a fixed seed.

    - **TestClientSimulator** kind sampling, full schedule completion, mid-schedule stop.
"""
# native python modules
from typing import Dict, List, Tuple

# test stack
import pytest

# web stack
import httpx

# modules under test
from src.experiment.client.config import CascadeCfg, ClientCfg, RampCfg
from src.experiment.client.simulator import ClientSimulator

# shared helpers
from tests.utils.helpers import (_StatefulHttpxHandler,
                                 _make_mock_async_client,
                                 _ok_httpx_handler,
                                 _one_svc_registry)


def _make_sim(handler,
              *,
              rates: List[float],
              kind_prob: Dict[str, float],
              cascade: CascadeCfg = CascadeCfg(mode="rolling",
                                               threshold=0.10, window=50)
              ) -> Tuple[ClientSimulator, httpx.AsyncClient]:
    """*_make_sim()* assemble a `(simulator, client)` pair routed at the given mock handler.

    Args:
        handler: callable accepting `httpx.Request` and returning `httpx.Response` (used by `MockTransport`).
        rates (List[float]): target rates for the ramp.
        kind_prob (Dict[str, float]): probability mass per request kind.
        cascade (CascadeCfg): trip rule. Defaults to rolling threshold=0.10, window=50.

    Returns:
        Tuple[ClientSimulator, httpx.AsyncClient]: simulator wired to the mock client; the caller is responsible for `aclose()`.
    """
    _client = _make_mock_async_client(handler)
    _cfg = ClientCfg(seed=1,
                     kind_prob=kind_prob,
                     ramp=RampCfg(min_n_per_kind=32,
                                  max_probe_s=5.0,
                                  rates=rates,
                                  cascade=cascade))
    _sim = ClientSimulator(_client, _one_svc_registry(), _cfg)
    return _sim, _client


class TestClientSimulator:
    """**TestClientSimulator** kind sampling + ramp walking + guard-stop + effective rate."""

    def test_kind_prob_invalid(self) -> None:
        """*test_kind_prob_invalid()* `ClientCfg.kind_prob` summing to 0 raises `ValueError` at simulator construction."""
        _client = _make_mock_async_client(_ok_httpx_handler)
        with pytest.raises(ValueError, match="kind_prob"):
            ClientSimulator(_client,
                            _one_svc_registry(),
                            ClientCfg(seed=1,
                                      kind_prob={"k": 0.0}))

    def test_kind_norm_sum(self) -> None:
        """*test_kind_norm_sum()* `kind_prob_norm` always sums to 1.0 even when input weights don't."""
        _client = _make_mock_async_client(_ok_httpx_handler)
        _sim = ClientSimulator(_client,
                               _one_svc_registry(),
                               ClientCfg(seed=1,
                                         kind_prob={"a": 2.0, "b": 8.0}))
        assert sum(_sim.kind_prob_norm) == pytest.approx(1.0)

    @pytest.mark.asyncio
    async def test_full_schedule(self) -> None:
        """*test_full_schedule()* clean handler -> `saturation_rate is None`, `stopped_reason == 'schedule_complete'`, `len(probes) == len(rates)`."""
        _sim, _c = _make_sim(_ok_httpx_handler,
                             rates=[100.0, 200.0],
                             kind_prob={"TAS_{2}": 1.0})
        try:
            _out = await _sim.run_ramp()
        finally:
            await _c.aclose()
        assert _out["saturation_rate"] is None
        assert _out["stopped_reason"] == "schedule_complete"
        assert len(_out["probes"]) == 2
        assert _out["client_effective_rate"] > 0.0

    @pytest.mark.asyncio
    async def test_stops_at_saturation(self) -> None:
        """*test_stops_at_saturation()* fail-fast guard + 503 handler -> `saturation_rate == rates[0]`, `stopped_reason.startswith('cascade at rate=...')`, `len(probes) == 1`."""
        _h = _StatefulHttpxHandler(n_ok=0)
        _sim, _c = _make_sim(_h,
                             rates=[50.0, 100.0, 200.0],
                             kind_prob={"TAS_{2}": 1.0},
                             cascade=CascadeCfg(mode="fail_fast"))
        try:
            _out = await _sim.run_ramp()
        finally:
            await _c.aclose()
        assert _out["saturation_rate"] == 50.0
        assert _out["stopped_reason"].startswith("cascade at rate=50")
        assert len(_out["probes"]) == 1

# -*- coding: utf-8 -*-
"""
Module client/simulator.py
==========================

Top-level orchestrator that walks the rate schedule and reports the saturation point. Composes `RequestSender`, `StopGuard`, and `RateDriver`.
"""
# native python modules
from __future__ import annotations

import random
from typing import Any, Dict, List, Optional

# web stack
import httpx

# local modules
from src.experiment.client.config import ClientCfg
from src.experiment.client.driver import RateDriver
from src.experiment.client.guard import StopGuard
from src.experiment.client.sender import RequestSender
from src.experiment.registry import SvcRegistry


class ClientSimulator:
    """*ClientSimulator* server-side counterpart to `architecture.py::TasArchitecture`.

    Owns the seeded RNG and the kind-probability distribution; assembles a `RequestSender`, a `StopGuard`, and a `RateDriver`; iterates the configured rate list; reports per-rate probe stats plus the saturation rate (the first rate at which the guard tripped, or `None`).
    """

    def __init__(self, client: httpx.AsyncClient,
                 registry: SvcRegistry,
                 cfg: ClientCfg) -> None:
        """*__init__()* hold dependencies, normalise kind probabilities, build the inner sender + guard + driver.

        Args:
            client (httpx.AsyncClient): pre-configured async client routed at the target mesh.
            registry (SvcRegistry): URL resolver for `cfg.entry_service`.
            cfg (ClientCfg): full runtime spec.

        Raises:
            ValueError: when `cfg.kind_prob` does not sum to a positive value.
        """
        self.cfg = cfg
        self._rng = random.Random(cfg.seed)

        _kinds = sorted(cfg.kind_prob.keys())
        _total = sum(cfg.kind_prob[_k] for _k in _kinds)
        if _total <= 0:
            _msg = "ClientCfg.kind_prob must sum to > 0"
            raise ValueError(_msg)
        self.kind_names: List[str] = _kinds
        self.kind_prob_norm: List[float] = [cfg.kind_prob[_k] / _total
                                            for _k in _kinds]

        self.sender = RequestSender(client, registry, cfg, self._rng)
        self.guard = StopGuard(cfg.ramp.cascade)
        self.driver = RateDriver(sender=self.sender,
                                 guard=self.guard,
                                 ramp_cfg=cfg.ramp,
                                 kind_names=self.kind_names,
                                 kind_prob_norm=self.kind_prob_norm,
                                 rng=self._rng)

    async def run_ramp(self) -> Dict[str, Any]:
        """*run_ramp()* walk the rate schedule low-to-high; halt on the first guard trip.

        After the loop exits, computes the duration-weighted client-effective rate as `total_sent / total_duration_s`. That figure is what TAS_{1}'s measured `lambda` should match 1:1.

        Returns:
            Dict[str, Any]: keys `probes` (list of per-rate summaries), `saturation_rate` (the rate at which the guard tripped, or `None` if the schedule completed), `stopped_reason` (string), `client_effective_rate` (float).
        """
        self.guard.reset()
        _probes: List[Dict[str, Any]] = []
        _saturation: Optional[float] = None
        _stop = "schedule_complete"

        for _rate in self.cfg.ramp.rates:
            _probe = await self.driver.run(_rate)
            _probes.append(_probe)
            if self.guard.tripped:
                _saturation = _rate
                _stop = (f"cascade at rate={_rate}: "
                         f"{self.guard.reason}")
                break

        _total_sent = sum(int(_p.get("total", 0)) for _p in _probes)
        _total_dur = sum(float(_p.get("duration_s", 0.0)) for _p in _probes)
        if _total_dur > 0:
            _client_effective_rate = _total_sent / _total_dur
        else:
            _client_effective_rate = 0.0

        _result: Dict[str, Any] = {}
        _result["probes"] = _probes
        _result["saturation_rate"] = _saturation
        _result["stopped_reason"] = _stop
        _result["client_effective_rate"] = _client_effective_rate
        return _result

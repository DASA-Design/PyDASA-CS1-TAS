# -*- coding: utf-8 -*-
"""
Module experiment/users.py
==========================

Synthetic user side of the architectural experiment. Where `architecture.py` builds the FastAPI mesh, `TasUser` represents the population that hits it. Independent of `architecture.py` on purpose: the bridge that pairs the two lives in `executor.py`, so a user can be driven against any compatible transport.
"""
# native python modules
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Optional

# web stack
import httpx

# local modules
from src.experiment.client import ClientCfg, ClientSimulator
from src.experiment.wire import SvcRegistry
from src.io import load_client_cfg


@dataclass
class TasUser:
    """*TasUser* one rate-ramp run by a synthetic user population.

    Attributes:
        client (httpx.AsyncClient): pre-configured transport routed at the target mesh.
        registry (SvcRegistry): URL resolver for `entry_service`.
        method_cfg (Dict[str, Any]): parsed `data/config/method/experiment.json`.
        kind_prob (Dict[str, float]): per-kind probability mass; the loader normalises to sum 1.
        entry_service (str): entry-router service name; defaults to `TAS_{1}`.
        cfg (Optional[ClientCfg]): resolved spec; populated on `__aenter__`.
        simulator (Optional[ClientSimulator]): inner simulator; populated on `__aenter__`.
    """

    client: httpx.AsyncClient
    registry: SvcRegistry
    method_cfg: Dict[str, Any]
    kind_prob: Dict[str, float]
    entry_service: str = "TAS_{1}"
    cfg: Optional[ClientCfg] = field(default=None)
    simulator: Optional[ClientSimulator] = field(default=None)

    async def __aenter__(self) -> "TasUser":
        """*__aenter__()* prepare the user for traffic.

        Returns:
            TasUser: this same instance, so `as user` binds to the constructed object.
        """
        self.cfg = load_client_cfg(self.method_cfg,
                                   kind_prob=dict(self.kind_prob),
                                   entry_service=self.entry_service)
        self.simulator = ClientSimulator(self.client,
                                         self.registry,
                                         self.cfg)
        return self

    async def __aexit__(self, _exc_type, _exc, _tb) -> None:
        """*__aexit__()* clear stop-guard history so a follow-up block on the same transport starts clean.

        The three exception-context parameters are required by the protocol but unused: cleanup runs identically on success and on exception, and returning `None` lets in-flight exceptions propagate.

        Args:
            _exc_type: exception class or `None`; unused.
            _exc: exception instance or `None`; unused.
            _tb: traceback or `None`; unused.
        """
        if self.simulator is not None:
            self.simulator.guard.reset()

    async def run_ramp(self) -> Dict[str, Any]:
        """*run_ramp()* drive the configured rate schedule and return the run envelope.

        Raises:
            RuntimeError: when called outside an `async with TasUser(...)` block.

        Returns:
            Dict[str, Any]: keys `probes`, `saturation_rate`, `stopped_reason`, `client_effective_rate`.
        """
        if self.simulator is None:
            _msg = "TasUser.run_ramp() called outside an `async with` block"
            raise RuntimeError(_msg)
        return await self.simulator.run_ramp()

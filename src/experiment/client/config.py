# -*- coding: utf-8 -*-
"""
Module client/config.py
=======================

Typed specs for the client load generator. The JSON loader lives in `src/io/tooling.py::load_client_cfg`.
"""
# native python modules
from __future__ import annotations

# data types
from dataclasses import dataclass, field
from typing import Dict, List


@dataclass
class CascadeCfg:
    """*CascadeCfg* tells the ramp when to halt under repeated infrastructure failures."""

    # `"rolling"` = trip on rolling-window threshold; `"fail_fast"` = trip on any single infra failure
    mode: str = "rolling"

    # rolling-mode infra-fail rate above which the ramp halts
    threshold: float = 0.10

    # rolling-mode trailing-window size in number of requests
    window: int = 50


@dataclass
class RampCfg:
    """*RampCfg* describes the rate schedule walked across probes plus the per-probe stop conditions."""

    # CLT floor: probe runs until every kind hits this sample count
    min_n_per_kind: int = 32

    # per-probe safety timeout in seconds
    max_probe_s: float = 60.0

    # monotonically increasing target rates in req/s
    rates: List[float] = field(default_factory=lambda: [
        1.0, 2.0, 5.0, 10.0, 20.0, 50.0, 100.0, 200.0, 500.0
    ])

    # stop-rule applied across every probe in the schedule
    cascade: CascadeCfg = field(default_factory=CascadeCfg)


@dataclass
class ClientCfg:
    """*ClientCfg* full runtime spec consumed by `ClientSimulator`."""

    # entry service that receives the client traffic
    entry_service: str = "TAS_{1}"

    # RNG seed for kind sampling and payload generation
    seed: int = 42

    # fallback payload size in bytes when `req_sizes_by_kind` lacks the kind
    req_size_b: int = 256

    # per-kind payload sizes; keys match kind labels (`TAS_{2}`) or the `<kind>_request` alias
    req_sizes_by_kind: Dict[str, int] = field(default_factory=dict)

    # probability mass per request kind; loader normalises to sum 1
    kind_prob: Dict[str, float] = field(default_factory=dict)

    # rate schedule + stop rule
    ramp: RampCfg = field(default_factory=RampCfg)

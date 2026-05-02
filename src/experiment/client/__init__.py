# -*- coding: utf-8 -*-
"""Client-side load generator package.

Composes `records / config / guard / sender / driver / stats / simulator` into one stable public-import surface for the architectural-experiment client.

Public API:
    - `RequestRecord`: one client-side measurement.
    - `CascadeCfg` / `RampCfg` / `ClientCfg`: typed specs.
    - `ClientSimulator`: composes sender + guard + driver; walks the rate schedule.

Loaders for `ClientCfg` / `RampCfg` live in `src.io` (`load_client_cfg`, `load_ramp_cfg`); kept there to avoid a circular import (`src.io.tooling` already imports the typed specs from `src.experiment.client.config`).
"""
from src.experiment.client.config import CascadeCfg, ClientCfg, RampCfg
from src.experiment.client.records import RequestRecord
from src.experiment.client.simulator import ClientSimulator

__all__ = [
    "CascadeCfg",
    "ClientCfg",
    "ClientSimulator",
    "RampCfg",
    "RequestRecord",
]

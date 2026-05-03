# -*- coding: utf-8 -*-
"""
Module instances/gauge.py
=========================

Single-vernier FastAPI app for host-floor calibration. Sibling of `third_party.py`: where third-party builds an atomic-handler app for the TAS mesh, gauge builds a vernier-handler app for the calibration probes (terminal echo, no routing).

Typical usage::

    from src.experiment.instances import build_gauge
    from src.experiment.services import SvcSpec

    spec = SvcSpec(name="CALIB", role="atomic", port=8000,
                   mu=0.0, epsilon=0.0, c=1, K=50,
                   seed=0, mem_per_buffer=...)
    app = build_gauge(spec, payload_size_bytes=131072)
"""
# native python modules
from __future__ import annotations

from typing import Optional

# web stack
from fastapi import FastAPI

# local modules
from src.experiment.services import SvcSpec, make_base_app, mount_vernier_svc


def build_gauge(spec: SvcSpec,
                payload_size_bytes: int = 0,
                *,
                title: Optional[str] = None) -> FastAPI:
    """*build_gauge()* assemble a single-vernier echo app for calibration probes.

    Mirrors `build_third_party` for the calibration use case: terminal handler at `/invoke`, no routing, payload echoed end-to-end so `phi` is measurable on constant-payload workloads.

    Args:
        spec (SvcSpec): per-service knobs; `mu` and `epsilon` are typically 0 at calibration time so the loopback floor stays honest.
        payload_size_bytes (int): declared payload size echoed in `SvcResp.message` for cross-checks against the recorded `size_bytes` CSV column.
        title (Optional[str]): FastAPI app title; defaults to `"calibration-vernier::<spec.name>"`.

    Returns:
        FastAPI: app with `/healthz` (from `make_base_app`) and `/invoke` (from vernier); `SvcCtx` exposed on `app.state.ctx`.
    """
    if title is None:
        _title = f"calibration-vernier::{spec.name}"
    else:
        _title = title
    _app = make_base_app(_title)
    mount_vernier_svc(_app, spec, payload_size_bytes=int(payload_size_bytes))
    return _app

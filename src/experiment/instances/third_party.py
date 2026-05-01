# -*- coding: utf-8 -*-
"""
Module instances/third_party.py
===============================

CS-01 third-party-service instance (MAS / AS / DS). `build_third_party` wraps a single atomic handler in a FastAPI app via `mount_atomic_svc`. Every MAS / AS / DS gets its own port and its own `/invoke` route; the launcher reaches the per-service log through `app.state.ctx`. Empty `targets` makes the service terminal; a non-empty row picks one hop via the seeded RNG and forwards through `ext_fwd`.

Typical usage::

    from src.experiment.instances import build_third_party
    from src.experiment.services import HttpForward, SvcSpec

    spec = SvcSpec(name="MAS_{1}",
                   role="atomic",
                   port=8006,
                   mu=500.0,
                   epsilon=0.1,
                   c=2,
                   K=20,
                   seed=42)
    app = build_third_party(spec, targets=[], ext_fwd=fwd)
"""
# native python modules
from __future__ import annotations

from typing import Any, Dict, List, Tuple

# web stack
from fastapi import FastAPI

# local modules
from src.experiment.services import (ExtFwdFn,
                                     SvcSpec,
                                     make_base_app,
                                     mount_atomic_svc)


def build_third_party(spec: SvcSpec,
                      targets: List[Tuple[str, float]],
                      ext_fwd: ExtFwdFn) -> FastAPI:
    """*build_third_party()* return one FastAPI app wrapping a single MAS / AS / DS handler. Mounts the atomic handler at `/invoke` through `mount_atomic_svc`, registers a `/healthz` endpoint that echoes `(name, role, c, K)`, and exposes the `SvcCtx` on `app.state.ctx`.

    Args:
        spec (SvcSpec): per-service knobs (name, port, mu, epsilon, c, K, seed, mem_per_buffer).
        targets (List[Tuple[str, float]]): Jackson-weighted outbound row; empty makes the service terminal.
        ext_fwd (ExtFwdFn): async `(tgt, req) -> SvcResp`; typically `HttpForward`. Never called for terminal services.

    Returns:
        FastAPI: app ready to bind to `spec.port`. `app.state.ctx` exposes the `SvcCtx` so the launcher can flush its log.
    """
    def _healthz() -> Dict[str, Any]:
        return {"name": spec.name,
                "role": "third_party",
                "c": spec.c,
                "K": spec.K}

    _app = make_base_app(title=f"experiment-service::{spec.name}",
                         healthz_fn=_healthz)
    mount_atomic_svc(_app, spec, targets, ext_fwd,
                     route="/invoke")
    return _app

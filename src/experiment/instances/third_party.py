# -*- coding: utf-8 -*-
"""
Module instances/third_party.py
===============================

Build a third-party MAS / AS / DS app: one FastAPI service per port, atomic handler at `/invoke`. Empty `targets` makes the service terminal; a non-empty row picks one hop via the seeded RNG and forwards through `ext_fwd`.

Typical usage::

    from src.experiment.instances import build_third_party
    from src.experiment.services import SvcSpec

    spec = SvcSpec(name="MAS_{1}", role="atomic", port=8006,
                   mu=500.0, epsilon=0.1, c=2, K=20, seed=42)
    app = build_third_party(spec, targets=[], ext_fwd=fwd)
"""
# native python modules
from __future__ import annotations

from typing import Dict, List, Tuple

# web stack
from fastapi import FastAPI

# local modules
from src.experiment.instances.common import HealthzPayload
from src.experiment.services import (ExtFwdFn,
                                     SvcCtx,
                                     SvcSpec,
                                     make_base_app,
                                     mount_atomic_svc)


def build_third_party(spec: SvcSpec,
                      targets: List[Tuple[str, float]],
                      ext_fwd: ExtFwdFn) -> FastAPI:
    """*build_third_party()* assemble a single-handler MAS / AS / DS app.

    Args:
        spec (SvcSpec): per-service knobs.
        targets (List[Tuple[str, float]]): Jackson-weighted outbound row; empty makes the service terminal.
        ext_fwd (ExtFwdFn): forward used for non-terminal hops.

    Returns:
        FastAPI: app with `/healthz` and `/invoke`; `SvcCtx` exposed on `app.state.ctx`.
    """
    _ctxs: Dict[str, SvcCtx] = {}
    _app = make_base_app(title=f"experiment-service::{spec.name}",
                         healthz_fn=HealthzPayload("third_party", _ctxs))
    _ctx = mount_atomic_svc(_app, spec, targets, ext_fwd, route="/invoke")
    _ctxs[spec.name] = _ctx
    return _app

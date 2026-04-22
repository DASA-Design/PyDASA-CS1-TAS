# -*- coding: utf-8 -*-
"""
Module instances/third_party.py
===============================

CS-01 third-party-service instance (MAS / AS / DS). One parameterised
function, `build_third_party`, wraps a single atomic handler in a
FastAPI app via `services.atomic.mount_atomic_service`. Every MAS /
AS / DS gets its own port and its own `/invoke` route; the launcher
reaches the per-service log through `app.state.ctx`.

Terminal services (empty `targets`) return `success` immediately
after the simulated service time and the epsilon Bernoulli; non-empty
`targets` pick one hop via the seeded RNG and forward through
`external_forward` (typically `HttpForward`).

Not a class; parameterised function only. Swap case studies by
calling this with different `(spec, targets, external_forward)`
tuples.

Typical usage::

    from src.experiment.instances import build_third_party
    from src.experiment.services import HttpForward, ServiceSpec

    spec = ServiceSpec(name="MAS_{1}", role="atomic", port=8006,
                       mu=500.0, epsilon=0.1, c=2, K=20, seed=42)
    app = build_third_party(spec, targets=[], external_forward=fwd)
"""
# native python modules
from __future__ import annotations

from typing import List, Tuple

# web stack
from fastapi import FastAPI

# local modules
from src.experiment.services import (ExternalForwardFn,
                                     ServiceSpec,
                                     make_base_app,
                                     mount_atomic_service)


def build_third_party(spec: ServiceSpec,
                      targets: List[Tuple[str, float]],
                      external_forward: ExternalForwardFn) -> FastAPI:
    """*build_third_party()* assemble one FastAPI app around a MAS / AS / DS handler.

    Attaches the atomic handler at `/invoke` through
    `mount_atomic_service` and publishes a `/healthz` endpoint that
    echoes the per-service knobs the launcher needs.

    Args:
        spec (ServiceSpec): per-service knobs (name, port, mu, epsilon, c, K, seed, mem_per_buffer).
        targets (List[Tuple[str, float]]): Jackson-weighted outbound routing row in declaration order; empty for terminal services.
        external_forward (ExternalForwardFn): async `(target, req) -> ServiceResponse`; typically `HttpForward`. Never invoked for terminal services.

    Returns:
        FastAPI: app ready to bind to `spec.port`. `app.state.ctx` exposes the `ServiceContext` so the launcher can flush its log.
    """
    def _healthz():
        return {"name": spec.name,
                "role": "third_party",
                "c": spec.c,
                "K": spec.K}

    _app = make_base_app(title=f"experiment-service::{spec.name}",
                         healthz_fn=_healthz)
    mount_atomic_service(_app, spec, targets, external_forward,
                         route="/invoke")
    return _app

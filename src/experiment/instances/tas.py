# -*- coding: utf-8 -*-
"""
Module instances/tas.py
=======================

CS-01 TAS target-system instance. One parameterised function, `build_tas`, composes six atomic handlers inside a single FastAPI app via `services.composite.mount_composite_service`.

The entry member (`TAS_{1}` by default) runs kind-based dispatch against the client-supplied `kind`; every other member runs Jackson-weighted dispatch on its routing row, or falls through to a terminal `success=True` response when the row is empty.

In-process hops run directly through a shared handler dict (no HTTP for TAS-to-TAS); TAS-to-third-party hops go through the launcher-supplied `external_forward` (typically `HttpForward`). The launcher reaches each member's log through `app.state.tas_components`, a `{name: ServiceContext}` dict attached by `mount_composite_service`.

Not a class; parameterised function only. Swap case studies by calling this with different `(specs, routing_rows, kind_to_target, external_forward)` tuples.

Typical usage::

    from src.experiment.instances import build_tas
    from src.experiment.services import HttpForward, ServiceSpec

    app = build_tas(specs={"TAS_{1}": s1, "TAS_{2}": s2, ...},
                    routing_rows={"TAS_{1}": [], "TAS_{2}": [("MAS_{1}", 1.0)], ...},
                    kind_to_target={"TAS_{2}": "TAS_{2}", ...},
                    external_forward=fwd)
"""
# native python modules
from __future__ import annotations

from typing import Any, Dict, List, Tuple

# web stack
from fastapi import FastAPI

# local modules
from src.experiment.services import (ExternalForwardFn,
                                     ServiceSpec,
                                     make_base_app,
                                     mount_composite_service)


def build_tas(specs: Dict[str, ServiceSpec],
              routing_rows: Dict[str, List[Tuple[str, float]]],
              kind_to_target: Dict[str, str],
              external_forward: ExternalForwardFn,
              *,
              entry_name: str = "TAS_{1}") -> FastAPI:
    """*build_tas()* assemble ONE FastAPI app hosting the six TAS members.

    Publishes a `/healthz` endpoint that enumerates every member and mounts one `/TAS_<i>/invoke` route per member through `mount_composite_service`. The entry member runs kind-based dispatch; the others run Jackson-weighted routing or terminate.

    Args:
        specs (Dict[str, ServiceSpec]): spec per TAS member; each drives its own `ServiceContext` (c, K, mu, epsilon, seed, mem_per_buffer).
        routing_rows (Dict[str, List[Tuple[str, float]]]): routing-matrix row per member. Targets may be other TAS members (in-process) or third-party services (HTTP forward).
        kind_to_target (Dict[str, str]): `entry_name`'s kind-to-target map; a missing `kind` raises HTTP 400 inside the composite handler.
        external_forward (ExternalForwardFn): async `(target, req) -> ServiceResponse` for non-TAS targets. Never invoked for TAS-to-TAS hops.
        entry_name (str): which TAS member runs the kind-router. Keyword-only; defaults to `TAS_{1}`.

    Returns:
        FastAPI: assembled app. `app.state.tas_components` exposes the `{name: ServiceContext}` dict so the launcher can flush each member's log independently.
    """
    def _healthz() -> Dict[str, Any]:
        _ctxs = _app.state.tas_components
        return {
            "role": "tas",
            "components": [
                {"name": _n,
                 "c": _c.spec.c,
                 "K": _c.spec.K}
                for _n, _c in _ctxs.items()
            ],
        }

    _app = make_base_app(title="experiment-service::TAS",
                         healthz_fn=_healthz)
    mount_composite_service(_app,
                            specs=specs,
                            routing_rows=routing_rows,
                            kind_to_target=kind_to_target,
                            external_forward=external_forward,
                            entry_name=entry_name)
    return _app

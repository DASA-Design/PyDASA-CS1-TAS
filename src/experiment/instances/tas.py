# -*- coding: utf-8 -*-
"""
Module instances/tas.py
=======================

CS-01 TAS target-system instance. `build_tas` composes the six TAS members behind one FastAPI app via `mount_composite_svc`. The entry member (`TAS_{1}` by default) dispatches by `req.kind`; every other member runs Jackson-weighted routing on its row, or terminates when the row is empty. TAS-to-TAS hops stay in-process through a shared handler dict; TAS-to-third-party hops go through `ext_fwd`. Each member's `SvcCtx` is exposed on `app.state.tas_components` so the launcher can flush per-member logs.

Typical usage::

    from src.experiment.instances import build_tas
    from src.experiment.services import HttpForward, SvcSpec

    app = build_tas(specs={"TAS_{1}": s1, "TAS_{2}": s2, ...},
                    routing_rows={"TAS_{1}": [], "TAS_{2}": [("MAS_{1}", 1.0)], ...},
                    kind_to_tgt={"TAS_{2}": "TAS_{2}", ...},
                    ext_fwd=fwd)
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
                                     mount_composite_svc)


def build_tas(specs: Dict[str, SvcSpec],
              routing_rows: Dict[str, List[Tuple[str, float]]],
              kind_to_tgt: Dict[str, str],
              ext_fwd: ExtFwdFn,
              *,
              entry_name: str = "TAS_{1}") -> FastAPI:
    """*build_tas()* return one FastAPI app hosting the TAS members in `specs`. Mounts every member through `mount_composite_svc`, registers a `/healthz` endpoint that lists every member's name, c, and K, and exposes the per-member `SvcCtx` dict on `app.state.tas_components`.

    Args:
        specs (Dict[str, SvcSpec]): one spec per TAS member; each drives its own `SvcCtx` (c, K, mu, epsilon, seed, mem_per_buffer).
        routing_rows (Dict[str, List[Tuple[str, float]]]): one row per member; targets may be other TAS members (in-process) or third-party services (HTTP forward).
        kind_to_tgt (Dict[str, str]): the entry member's kind-to-target table; an unknown `req.kind` raises HTTP 400 from `KindPick` inside the entry handler.
        ext_fwd (ExtFwdFn): async `(tgt, req) -> SvcResp` for non-TAS targets. Never called for TAS-to-TAS hops.
        entry_name (str): which member runs the kind router. Keyword-only; defaults to `TAS_{1}`.

    Returns:
        FastAPI: assembled app. `app.state.tas_components` holds the `{name: SvcCtx}` dict so the launcher can flush each member's log independently.
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
    mount_composite_svc(_app,
                        specs=specs,
                        routing_rows=routing_rows,
                        kind_to_tgt=kind_to_tgt,
                        ext_fwd=ext_fwd,
                        entry_name=entry_name)
    return _app

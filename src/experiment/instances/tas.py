# -*- coding: utf-8 -*-
"""
Module instances/tas.py
=======================

Build the TAS target system: one FastAPI app hosting the six TAS members behind shared in-process dispatch. The entry member kind-routes by `req.kind`; siblings Jackson-route or terminate. TAS-to-TAS hops stay in-process; non-TAS targets go through `ext_fwd`.

Typical usage::

    from src.experiment.instances import build_tas

    app = build_tas(specs={"TAS_{1}": s1, ...},
                    routing_rows={"TAS_{1}": [], "TAS_{2}": [("MAS_{1}", 1.0)], ...},
                    kind_to_tgt={"TAS_{2}": "TAS_{2}", ...},
                    ext_fwd=fwd)
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
                                     mount_composite_svc)


def build_tas(specs: Dict[str, SvcSpec],
              routing_rows: Dict[str, List[Tuple[str, float]]],
              kind_to_tgt: Dict[str, str],
              ext_fwd: ExtFwdFn,
              *,
              entry_name: str = "TAS_{1}") -> FastAPI:
    """*build_tas()* assemble the composite TAS app from `specs`.

    Args:
        specs (Dict[str, SvcSpec]): one spec per TAS member.
        routing_rows (Dict[str, List[Tuple[str, float]]]): per-member routing row; targets may be siblings or third-party.
        kind_to_tgt (Dict[str, str]): entry-member kind dispatch table.
        ext_fwd (ExtFwdFn): forward used for non-TAS targets.
        entry_name (str): kind-router member; defaults to `TAS_{1}`.

    Returns:
        FastAPI: app with `/healthz` and per-member `/TAS_<i>/invoke` routes; per-member `SvcCtx` exposed on `app.state.tas_components`.
    """
    _ctxs: Dict[str, SvcCtx] = {}
    _app = make_base_app(title="experiment-service::TAS",
                         healthz_fn=HealthzPayload("tas", _ctxs))
    _ctxs.update(mount_composite_svc(_app,
                                     specs=specs,
                                     routing_rows=routing_rows,
                                     kind_to_tgt=kind_to_tgt,
                                     ext_fwd=ext_fwd,
                                     entry_name=entry_name))
    return _app

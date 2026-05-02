# -*- coding: utf-8 -*-
"""
Module instances/common.py
==========================

Shared building blocks reused across CS-01 instance assemblers (`tas.py`, `third_party.py`).
"""
# native python modules
from __future__ import annotations

from typing import Any, Dict, List

# local modules
from src.experiment.services import SvcCtx


class HealthzPayload:
    """*HealthzPayload* render the `/healthz` JSON body for an instance app. Holds the per-service `SvcCtx` map by reference so each call samples the current set of mounted services; works for both single-service apps (third-party) and multi-service apps (TAS composite)."""

    def __init__(self, role: str, ctxs: Dict[str, SvcCtx]) -> None:
        """*__init__()* bind the role label and the per-service `SvcCtx` map.

        Args:
            role (str): role label echoed under the `"role"` key.
            ctxs (Dict[str, SvcCtx]): per-service `SvcCtx` map, captured by reference. Late inserts (e.g. composite mounts that populate the dict after `make_base_app`) are picked up automatically.
        """
        self.role = role
        self.ctxs = ctxs

    def __call__(self) -> Dict[str, Any]:
        """*__call__()* render the `/healthz` JSON body. The `"components"` list is derived from the current entries in `self.ctxs` so it reflects late inserts.

        Returns:
            Dict[str, Any]: list is derived from the current entries in `self.ctxs` so it reflects late inserts.
        """
        _components: List[Dict[str, Any]] = []
        for _name, _ctx in self.ctxs.items():
            _components.append({"name": _name,
                                "c": _ctx.spec.c,
                                "K": _ctx.spec.K})
        return {"role": self.role, "components": _components}

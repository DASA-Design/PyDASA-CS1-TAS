# -*- coding: utf-8 -*-
"""Wire layer: URL resolution + outbound payload bytes.

Public API:
    - `SvcRegistry`, `RegistryEntry`: name-to-URL resolver for the experiment mesh.
    - `MockPayload`, `generate_payload`, `resolve_size_for_kind`: deterministic per-kind request payload generation.
"""
from src.experiment.wire.payload import (MockPayload,
                                         generate_payload,
                                         resolve_size_for_kind)
from src.experiment.wire.registry import RegistryEntry, SvcRegistry

__all__ = [
    "MockPayload",
    "RegistryEntry",
    "SvcRegistry",
    "generate_payload",
    "resolve_size_for_kind",
]

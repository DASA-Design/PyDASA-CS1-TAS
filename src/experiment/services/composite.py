# -*- coding: utf-8 -*-
"""
Module services/composite.py
============================

Composite-service module (no class). One function,
`mount_composite_service`, attaches N atomic handlers to one FastAPI
app and wires their in-process routing. We use it for the TAS target
system: six atomic handlers (TAS_{1..6}) behind a single port with
six per-member routes.

Each member is mounted through `services.atomic.mount_atomic_service`
with two extension kwargs:

    - `pick_target`: at the entry member, resolves the target via the
      `kind_to_target` table (raising HTTP 400 on unknown kind); every
      other member falls back to atomic's default Jackson pick.
    - `dispatch`: checks the shared `_handlers` dict first so sibling
      members dispatch to each other in-process via a direct `await`;
      non-member targets fall through to `external_forward` (typically
      `HttpForward`).

The shared `_handlers` dict closes over `dispatch` and is populated
as each member mounts; by the time a request actually runs, every
member's handler is registered, so the late-bound lookup resolves.

Queueing stays emergent, same as in `services.atomic`.
"""
# native python modules
from __future__ import annotations

import re
from typing import Any, Callable, Dict, List, Optional, Tuple

# web stack
from fastapi import FastAPI, HTTPException

# local modules
from src.experiment.services.atomic import mount_atomic_service
from src.experiment.services.base import (ExternalForwardFn,
                                          ServiceContext,
                                          ServiceRequest,
                                          ServiceResponse,
                                          ServiceSpec)


def parse_tas_idx(name: str) -> int:
    """*parse_tas_idx()* extract the numeric index from a `TAS_{i}` artifact key."""
    _m = re.match(r"^TAS_\{(\d+)\}$", name)
    if _m is None:
        raise ValueError(f"not a TAS component name: {name!r}")
    return int(_m.group(1))


def mount_composite_service(
        app: FastAPI,
        specs: Dict[str, ServiceSpec],
        routing_rows: Dict[str, List[Tuple[str, float]]],
        kind_to_target: Dict[str, str],
        external_forward: ExternalForwardFn,
        *,
        entry_name: str,
        route_for: Optional[Callable[[str], str]] = None,
) -> Dict[str, ServiceContext]:
    """*mount_composite_service()* attach N atomic members inside one FastAPI app.

    Every member is mounted via `mount_atomic_service` with a shared
    `dispatch` that prefers in-process sibling handlers over the HTTP
    `external_forward`, plus a kind-dispatch `pick_target` at the
    entry member. External hops continue to go through
    `external_forward`.

    Args:
        app (FastAPI): app to attach the routes to.
        specs (Dict[str, ServiceSpec]): spec per member, keyed by artifact name.
        routing_rows (Dict[str, List[Tuple[str, float]]]): per-member routing row. Targets may be members (in-process) or external (via forward).
        kind_to_target (Dict[str, str]): kind-based dispatch table for the entry member.
        external_forward (ExternalForwardFn): async `(target, req) -> ServiceResponse`. Called when the shared dispatch lookup misses the `_handlers` dict (non-member target).
        entry_name (str): which member runs the kind-router, typically `TAS_{1}`.
        route_for (Callable[[str], str] | None): `member_name -> URL path`. Defaults to `/TAS_<i>/invoke` based on the numeric index in the name.

    Returns:
        Dict[str, ServiceContext]: `{member_name: ServiceContext}`. Also attached to `app.state.tas_components` so the launcher can iterate for flushing.
    """
    if entry_name not in specs:
        raise ValueError(
            f"entry_name={entry_name!r} not in specs: {list(specs)}")
    if route_for is None:
        def route_for(_n: str) -> str:
            return f"/TAS_{parse_tas_idx(_n)}/invoke"

    # shared in-process handler table; populated as each member mounts.
    # `_dispatch` captures by reference, so late-bound lookups resolve
    # once every member is registered (order is mount-first, invoke-later).
    _handlers: Dict[str, Any] = {}

    async def _dispatch(_target: str,
                        _req: ServiceRequest) -> ServiceResponse:
        if _target in _handlers:
            return await _handlers[_target](_req)
        return await external_forward(_target, _req)

    def _pick_for(member_name: str):
        """Return a kind-dispatch picker for the entry member; None elsewhere (falls back to atomic's default Jackson pick)."""
        if member_name != entry_name or not kind_to_target:
            return None

        def _pick(_ctx: ServiceContext,
                  _req: ServiceRequest) -> str:
            _t = kind_to_target.get(_req.kind)
            if _t is None:
                raise HTTPException(
                    status_code=400,
                    detail=(f"unknown kind {_req.kind!r}; "
                            f"known kinds: {list(kind_to_target)}"))
            return _t

        return _pick

    _contexts: Dict[str, ServiceContext] = {}
    for _name, _spec in specs.items():
        _ctx = mount_atomic_service(
            app,
            _spec,
            routing_rows.get(_name, []),
            external_forward,
            route=route_for(_name),
            pick_target=_pick_for(_name),
            dispatch=_dispatch,
        )
        _contexts[_name] = _ctx
        _handlers[_name] = _ctx.handler

    app.state.tas_components = _contexts
    return _contexts

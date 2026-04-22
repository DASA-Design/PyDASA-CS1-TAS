# -*- coding: utf-8 -*-
"""
Module services/composite.py
============================

Composite-service module (no class). One function,
`mount_composite_service`, attaches N atomic handlers to one FastAPI
app and wires their in-process routing. We use it for the TAS target
system: six atomic handlers (TAS_{1..6}) behind a single port with
six per-component routes.

Members dispatch to each other in-process through a direct `await`,
so no HTTP hop runs between sibling members. Non-member targets go
through `external_forward`, typically an `HttpForward` instance that
reaches third-party services (MAS, AS, DS).

Every member handler is wrapped with `@logger(ctx)`, so each
component keeps its own CSV log. Queueing stays emergent, same as in
`services.atomic`.
"""
# native python modules
from __future__ import annotations

import asyncio
import re
from typing import Any, Dict, List, Tuple

# web stack
from fastapi import FastAPI, HTTPException

# local modules
from src.experiment.services.base import (ExternalForwardFn,
                                          ServiceContext,
                                          ServiceRequest,
                                          ServiceResponse,
                                          ServiceSpec)
from src.experiment.services.instruments import logger


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
        route_for=None,
) -> Dict[str, ServiceContext]:
    """*mount_composite_service()* attach N atomic-like members inside one FastAPI app.

    Each member owns its own `ServiceContext` (spec, log, rng), its
    own `@logger`-wrapped handler, and a route at
    `route_for(member_name)`. Internal hops run via `await` through a
    shared handler dict, one entry per member. External hops go
    through `external_forward`.

    Args:
        app (FastAPI): app to attach the routes to.
        specs (Dict[str, ServiceSpec]): spec per member, keyed by artifact name.
        routing_rows (Dict[str, List[Tuple[str, float]]]): per-member routing row. Targets may be members (in-process) or external (via forward).
        kind_to_target (Dict[str, str]): kind-based dispatch table for the entry member.
        external_forward (ExternalForwardFn): async `(target, req) -> ServiceResponse`. Called when the routing picks a non-member target.
        entry_name (str): which member runs the kind-router, typically `TAS_{1}`.
        route_for (Callable[[str], str] | None): `member_name -> URL path`. Defaults to `/TAS_<i>/invoke` based on the numeric index in the name.

    Returns:
        Dict[str, ServiceContext]: `{member_name: ServiceContext}`. Also attached to `app.state.tas_components` so the launcher can iterate for flushing.
    """
    if entry_name not in specs:
        raise ValueError(
            f"entry_name={entry_name!r} not in specs: {list(specs)}")
    if route_for is None:
        def route_for(_n):
            return f"/TAS_{parse_tas_idx(_n)}/invoke"

    _contexts: Dict[str, ServiceContext] = {
        _n: ServiceContext(spec=_s) for _n, _s in specs.items()
    }
    app.state.tas_components = _contexts

    # built lazily below so late-binding of `handlers[target]` works
    _handlers: Dict[str, Any] = {}

    def _make_handler(_name: str):
        _ctx = _contexts[_name]
        _row = routing_rows.get(_name, [])
        _row_names = [_t for _t, _ in _row]
        _row_weights = [float(_w) for _, _w in _row]

        @logger(_ctx)
        async def _handler(req: ServiceRequest) -> ServiceResponse:
            # simulate service time
            _svc = _ctx.draw_svc_time()
            if _svc > 0:
                await asyncio.sleep(_svc)

            # Bernoulli ε
            if _ctx.draw_eps():
                return ServiceResponse(request_id=req.request_id,
                                       service_name=_name,
                                       success=False,
                                       message="bernoulli failure")

            # kind-based dispatch at the entry member
            if _name == entry_name and kind_to_target:
                _target = kind_to_target.get(req.kind)
                if _target is None:
                    raise HTTPException(
                        status_code=400,
                        detail=(f"unknown kind {req.kind!r}; "
                                f"known kinds: {list(kind_to_target)}"))
            elif _row_names:
                _target = _ctx.rng.choices(_row_names,
                                           weights=_row_weights, k=1)[0]
            else:
                return ServiceResponse(request_id=req.request_id,
                                       service_name=_name,
                                       success=True,
                                       message="terminal")

            # in-process (sibling member) vs external (HTTP forward)
            if _target in _handlers:
                _inner = await _handlers[_target](req)
            else:
                _inner = await external_forward(_target, req)
            return ServiceResponse(request_id=req.request_id,
                                   service_name=_name,
                                   success=_inner.success,
                                   message=_inner.message)

        return _handler

    # instantiate each member's handler and register on the shared dict
    # so internal dispatches resolve via late-binding
    for _n in _contexts:
        _handlers[_n] = _make_handler(_n)

    # mount one POST route per member
    def _make_route(_name: str):
        async def _route(req: ServiceRequest) -> ServiceResponse:
            return await _handlers[_name](req)
        return _route

    for _n in _contexts:
        app.add_api_route(route_for(_n),
                          _make_route(_n),
                          methods=["POST"],
                          response_model=ServiceResponse)

    return _contexts

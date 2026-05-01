# -*- coding: utf-8 -*-
"""
Module services/composite.py
============================

Attach N atomic handlers to one FastAPI app and wire their in-process routing. Used for the TAS target system: six atomic handlers (TAS_{1..6}) behind a single port. Each member is mounted via `mount_atomic_svc` with `CompositeDispatch` (prefers in-process sibling dispatch over HTTP) and `KindPick` at the entry member (kind -> target table). Members inherit the K-bounded admission gate from `services.atomic`.
"""
# native python modules
from __future__ import annotations

import re
from typing import Any, Callable, Dict, List, Optional, Tuple

# web stack
from fastapi import FastAPI, HTTPException

# local modules
from src.experiment.services.atomic import (DispatchFn,
                                            PickTargetFn,
                                            mount_atomic_svc)
from src.experiment.services.base import (ExtFwdFn,
                                          SvcCtx,
                                          SvcReq,
                                          SvcResp,
                                          SvcSpec)


def _parse_constituent_idx(name: str) -> int:
    """*_parse_constituent_idx()* extract the numeric index from a `TAS_{i}` artifact key.

    Args:
        name (str): artifact key, e.g. `TAS_{1}`.

    Returns:
        int: numeric index `i`.

    Raises:
        ValueError: when `name` does not match the `TAS_{i}` shape.
    """
    _m = re.match(r"^TAS_\{(\d+)\}$", name)
    if _m is None:
        _msg = f"not a TAS component name: {name!r}"
        raise ValueError(_msg)
    return int(_m.group(1))


def _build_route(name: str) -> str:
    """*_build_route()* return the URL path `/TAS_<i>/invoke` for an artifact name like `TAS_{1}`.

    Args:
        name (str): member artifact key, e.g. `TAS_{1}`.

    Returns:
        str: URL path the POST route mounts at.
    """
    return f"/TAS_{_parse_constituent_idx(name)}/invoke"


class CompositeDispatch:
    """*CompositeDispatch* route a request to a same-process sibling when the target name is a key in `handlers`; otherwise call `ext_fwd` (HTTP forward). Holds `handlers` by reference so siblings registered after this object is built still resolve at call time."""

    def __init__(self,
                 handlers: Dict[str, Any],
                 ext_fwd: ExtFwdFn) -> None:
        """*__init__()* bind the in-process handler dict + the external fallback.

        Args:
            handlers (Dict[str, Any]): shared `name -> handler` table populated by `mount_composite_svc` as each atomic mounts.
            ext_fwd (ExtFwdFn): async `(tgt, req) -> SvcResp` used when the target is not a member.
        """
        self.handlers = handlers
        self.ext_fwd = ext_fwd

    async def __call__(self, tgt: str, req: SvcReq) -> SvcResp:
        """*__call__()* return `await self.handlers[tgt](req)` when `tgt` is a key in `self.handlers`; otherwise return `await self.ext_fwd(tgt, req)`.

        Args:
            tgt (str): downstream service name.
            req (SvcReq): request to relay.

        Returns:
            SvcResp: response from the sibling handler, or from `ext_fwd` when `tgt` is not a sibling.
        """
        if tgt in self.handlers:
            return await self.handlers[tgt](req)
        return await self.ext_fwd(tgt, req)


class KindPick:
    """*KindPick* return the target name listed under `req.kind` in `kind_to_tgt`; raise HTTP 400 when the kind is not in the table. Used at the entry member so the request body's `kind` field decides the next hop instead of a Jackson-weighted draw."""

    def __init__(self, kind_to_tgt: Dict[str, str]) -> None:
        """*__init__()* bind the kind dispatch table.

        Args:
            kind_to_tgt (Dict[str, str]): `kind -> target_name` mapping.
        """
        self.kind_to_tgt = kind_to_tgt

    def __call__(self, _ctx: SvcCtx, req: SvcReq) -> str:
        """*__call__()* return `self.kind_to_tgt[req.kind]`; raise HTTP 400 when `req.kind` is missing from the table.

        Args:
            _ctx (SvcCtx): per-service state (unused by kind dispatch; kept for `PickTargetFn` parity).
            req (SvcReq): inbound request whose `kind` field selects the target.

        Returns:
            str: target service name listed under `req.kind`.

        Raises:
            HTTPException: 400 when `req.kind` is not a key in `self.kind_to_tgt`.
        """
        _t = self.kind_to_tgt.get(req.kind)
        if _t is None:
            _msg = f"unknown kind {req.kind!r}; "
            _msg += f"known kinds: {list(self.kind_to_tgt)}"
            raise HTTPException(status_code=400, detail=_msg)
        return _t


def mount_composite_svc(app: FastAPI,
                        specs: Dict[str, SvcSpec],
                        routing_rows: Dict[str, List[Tuple[str, float]]],
                        kind_to_tgt: Dict[str, str],
                        ext_fwd: ExtFwdFn,
                        *,
                        entry_name: str,
                        route_for: Optional[Callable[[str], str]] = None) -> Dict[str, SvcCtx]:
    """*mount_composite_svc()* register one POST route per entry in `specs`, all sharing a single `CompositeDispatch` (sibling lookup) and a `KindPick` at `entry_name` (kind-to-target dispatch). Hops between members in `specs` stay in the same Python process; targets not in `specs` go through `ext_fwd`. Returns the per-member `SvcCtx` dict; the same dict is also stored on `app.state.tas_components`.

    Args:
        app (FastAPI): app to attach the routes to.
        specs (Dict[str, SvcSpec]): spec per member, keyed by artifact name.
        routing_rows (Dict[str, List[Tuple[str, float]]]): per-member routing row; targets may be members or external.
        kind_to_tgt (Dict[str, str]): kind-based dispatch table for the entry member.
        ext_fwd (ExtFwdFn): async `(tgt, req) -> SvcResp` for non-member targets.
        entry_name (str): which member runs the kind-router, typically `TAS_{1}`.
        route_for (Callable[[str], str] | None): `member_name -> URL path`; None -> `_build_route`.

    Returns:
        Dict[str, SvcCtx]: `{member_name: SvcCtx}`. Also attached to `app.state.tas_components` so the launcher can iterate for flushing.
    """
    if entry_name not in specs:
        _msg = f"entry_name={entry_name!r} not in specs: {list(specs)}"
        raise ValueError(_msg)

    if route_for is not None:
        _route_for = route_for
    else:
        _route_for = _build_route

    # populated as each member mounts; CompositeDispatch captures by reference, so late-bound lookups resolve once every member is registered.
    _handlers: Dict[str, Any] = {}
    _dispatch: DispatchFn = CompositeDispatch(_handlers, ext_fwd)

    if kind_to_tgt:
        _entry_pick: Optional[PickTargetFn] = KindPick(kind_to_tgt)
    else:
        _entry_pick = None

    _contexts: Dict[str, SvcCtx] = {}
    for _name, _spec in specs.items():
        if _name == entry_name:
            _pick = _entry_pick
        else:
            _pick = None

        _ctx = mount_atomic_svc(app,
                                _spec,
                                routing_rows.get(_name, []),
                                ext_fwd,
                                route=_route_for(_name),
                                pick_tgt=_pick,
                                dispatch=_dispatch)
        _contexts[_name] = _ctx
        _handlers[_name] = _ctx.handler

    app.state.tas_components = _contexts
    return _contexts

# -*- coding: utf-8 -*-
"""
Module launcher.py
==================

Assembles the full architectural-experiment mesh. The profile JSON is the
single source of truth for DASA knobs (mu, epsilon, c, K, routing); the
method JSON (`experiment.json`) carries only deployment plumbing (ports,
ramp, request sizes, role tagging).

Two composite flavours wired per the `role` field in `experiment.json`:

    - `"composite_router"` (TAS_{1}): uses `make_composite_router`. Its kind -> target map + the client's kind-weights both come from TAS_{1}'s routing-matrix row in the profile JSON.
    - `"composite"` (TAS_{2..6}): uses `make_composite_service` with the adaptation pattern. Equivalents list comes from the composite's routing-matrix row in declaration (column-index) order.

No hardcoded workflow; the routing matrix is the ONLY wiring source.

The shared `httpx.AsyncClient` routes through a `_MultiASGITransport`
dispatching per port. All port->app entries register BEFORE the client
handles any traffic (two-pass construction avoids post-hoc transport
mutation -- the shared `_port_to_app` dict on `_MultiASGITransport`
gets each composite entry added synchronously during startup, then the
client becomes reachable to callers only when `__aenter__` returns).
"""
# native python modules
from __future__ import annotations

# data types
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

# scientific stack
import numpy as np

# web stack
import httpx
from fastapi import FastAPI

# local modules
from src.experiment.instances import build_tas, build_third_party
from src.experiment.registry import ServiceRegistry
from src.experiment.services import (LOG_COLUMNS,
                                     HttpForward,
                                     ServiceSpec,
                                     derive_seed)
from src.io import NetworkConfig


# --- transport ------------------------------------------------------------


class _MultiASGITransport(httpx.AsyncBaseTransport):
    """*_MultiASGITransport* dispatches per-port ASGI apps from a single httpx client."""

    def __init__(self, port_to_app: Dict[int, FastAPI]):
        self._transports: Dict[int, httpx.ASGITransport] = {
            _port: httpx.ASGITransport(app=_app)
            for _port, _app in port_to_app.items()
        }

    async def handle_async_request(
            self, request: httpx.Request) -> httpx.Response:
        _port = request.url.port
        _t = self._transports.get(_port) if _port is not None else None
        if _t is None:
            return httpx.Response(status_code=404,
                                  json={"detail": f"no app for port {_port}"})
        return await _t.handle_async_request(request)

    async def aclose(self) -> None:
        for _t in self._transports.values():
            await _t.aclose()


# --- derivation helpers: specs + routing ---------------------------------


def _avg_request_size(sizes_by_kind: Dict[str, int]) -> int:
    """*_avg_request_size()* arithmetic mean of per-kind payload sizes; 0 when no sizes declared."""
    _vals = [int(_v) for _v in sizes_by_kind.values() if int(_v) > 0]
    if not _vals:
        return 0
    return int(sum(_vals) / len(_vals))


def _specs_from_config(cfg: NetworkConfig,
                       registry: ServiceRegistry,
                       *,
                       root_seed: int = 0,
                       avg_request_size_bytes: int = 0
                       ) -> Dict[str, ServiceSpec]:
    """*_specs_from_config()* build one `ServiceSpec` per artifact by pulling `(mu, epsilon, c, K)` from the profile JSON and `(role, port)` from the registry.

    `root_seed` is the single seed from `experiment.json::seed`. It is
    folded with each service's name via `derive_seed` so every service
    has a stable, independent RNG stream — one knob in JSON controls
    every stochastic draw in the apparatus.

    `avg_request_size_bytes` is the expected payload size per kind (from
    `method_cfg["request_size_bytes"]`). The per-service buffer budget is
    `K · avg_request_size_bytes · MEM_HEADROOM_FACTOR` (1.5× headroom
    absorbs Pydantic + FastAPI framing overhead without having to
    physically re-measure the body bytes). The apparatus enforces this
    at admission time via `HTTPException(413)` and the 1.5× headroom IS
    the reason we don't pay the per-request body-scan cost.
    """
    _specs: Dict[str, ServiceSpec] = {}
    _headroom = ServiceSpec.MEM_HEADROOM_FACTOR
    for _a in cfg.artifacts:
        if _a.key not in registry.table:
            # artifact in profile but not in experiment.json registry (e.g. a
            # swap slot inactive for this adaptation); skip silently
            continue
        _entry = registry.table[_a.key]
        _K = int(_a.K)
        _specs[_a.key] = ServiceSpec(
            name=_a.key,
            role=_entry.role,
            port=_entry.port,
            mu=float(_a.mu),
            epsilon=float(_a.epsilon),
            c=int(_a.c),
            K=_K,
            seed=derive_seed(root_seed, _a.key),
            mem_per_buffer=int(_K * int(avg_request_size_bytes) * _headroom),
        )
    return _specs


def _routing_row(cfg: NetworkConfig, name: str) -> List[Tuple[str, float]]:
    """*_routing_row()* return `(target_name, probability)` pairs for non-zero entries in `name`'s row, in declaration (column-index) order."""
    _names = [_a.key for _a in cfg.artifacts]
    _idx = _names.index(name)
    _row = np.asarray(cfg.routing[_idx], dtype=float)

    _out: List[Tuple[str, float]] = []
    for _col_idx, _p in enumerate(_row):
        if _p > 0:
            _out.append((_names[_col_idx], float(_p)))
    return _out


def _router_kind_map(cfg: NetworkConfig,
                     name: str
                     ) -> Tuple[Dict[str, str], Dict[str, float]]:
    """*_router_kind_map()* build `(kind_to_target, kind_weights)` for a router composite.

    Kind label == target artifact name (simplest, self-documenting). Weights
    normalise probabilities to sum to 1 across the row's non-zero entries.
    """
    _row = _routing_row(cfg, name)
    _total = sum(_p for _, _p in _row)
    _kind_to_target = {_t: _t for _t, _ in _row}
    _kind_weights = {_t: (_p / _total if _total > 0 else 0.0)
                     for _t, _p in _row}
    return _kind_to_target, _kind_weights


# external-forward closure is now a class in `http/forward.py`
# (`HttpForward`); the launcher instantiates it once per run.


# --- launcher -------------------------------------------------------------


@dataclass
class ExperimentLauncher:
    """*ExperimentLauncher* assembles services + shared client for one adaptation run.

    Use via `async with launcher:` to bind setup / teardown to context lifetime.

    Attributes:
        cfg (NetworkConfig): resolved profile + scenario.
        method_cfg (Dict[str, Any]): loaded `experiment.json`.
        adaptation (str): one of `"baseline"`, `"s1"`, `"s2"`, `"aggregate"`.
        base_port_override (int): override `method_cfg["base_port"]`; 0 means "use the config value". Useful for parallel test runs.
    """

    cfg: NetworkConfig
    method_cfg: Dict[str, Any]
    adaptation: str
    base_port_override: int = 0

    # populated on __aenter__
    registry: Optional[ServiceRegistry] = None
    specs: Dict[str, ServiceSpec] = field(default_factory=dict)
    apps: Dict[str, FastAPI] = field(default_factory=dict)
    client: Optional[httpx.AsyncClient] = None
    _transport: Optional[_MultiASGITransport] = None
    kind_weights: Dict[str, float] = field(default_factory=dict)
    kind_to_target: Dict[str, str] = field(default_factory=dict)

    async def __aenter__(self) -> "ExperimentLauncher":
        # 1. registry + per-artifact specs. The single `experiment.json::seed`
        #    is folded with each service name so every service has a stable,
        #    independent RNG seed derived from the one config knob.
        #    FR-2.4: `mem_per_buffer = K * avg_request_size` is baked into
        #    each spec so the memory-usage coefficient is derivable downstream.
        self.registry = ServiceRegistry.from_config(
            self.method_cfg, base_port_override=self.base_port_override)
        _root_seed = int(self.method_cfg.get("seed", 0))
        _avg_size = _avg_request_size(self.method_cfg.get("request_size_bytes", {}))
        self.specs = _specs_from_config(self.cfg, self.registry,
                                        root_seed=_root_seed,
                                        avg_request_size_bytes=_avg_size)

        # 2. identify the client-facing entry router (TAS_{1} by convention)
        #    and derive its kind weights / kind-to-target map from its
        #    routing-matrix row. Among composite_client roles (TAS_{1},
        #    TAS_{5}, TAS_{6}), the entry is the one with a non-empty
        #    outbound row — TAS_{5} and TAS_{6} are terminal.
        def _is_entry_router(_name: str) -> bool:
            _entry = self.registry.table[_name]
            if _entry.role != "composite_client":
                return False
            if _name not in self.specs:
                return False
            return bool(_routing_row(self.cfg, _name))

        _routers = [_n for _n in self.registry.table if _is_entry_router(_n)]
        if _routers:
            self.kind_to_target, self.kind_weights = _router_kind_map(
                self.cfg, _routers[0])

        # 3. transport + shared client built against an initially empty
        #    port map. Every service registers its port → app mapping into
        #    the transport synchronously before any HTTP traffic flows.
        self._transport = _MultiASGITransport({})
        self.client = httpx.AsyncClient(transport=self._transport,
                                        timeout=httpx.Timeout(10.0))

        # 4. build every service. The TAS target system is ONE FastAPI app
        #    hosting six embedded atomic components (TAS_{1..6}), built via
        #    `build_tas` over `CompositeQueue` + `mount_composite`. Third-
        #    party services (MAS / AS / DS) are built via `build_third_party`
        #    over `AtomicQueue` + `mount_atomic`. Both paths use the same
        #    `HttpForward` instance for cross-service HTTP hops.
        _forward = HttpForward(self.client, self.registry)
        _port_to_app: Dict[int, FastAPI] = {}

        # 4a. collect the six TAS component specs + their routing rows
        _tas_specs: Dict[str, ServiceSpec] = {}
        _tas_rows: Dict[str, List[Tuple[str, float]]] = {}
        for _name, _spec in self.specs.items():
            if _name.startswith("TAS_"):
                _tas_specs[_name] = _spec
                _tas_rows[_name] = _routing_row(self.cfg, _name)

        # 4b. one TAS app; every TAS component gets its own AtomicQueue
        #     inside the shared CompositeQueue (exposed via
        #     app.state.tas_components + app.state.composite).
        if _tas_specs:
            _tas_app = build_tas(_tas_specs,
                                 _tas_rows,
                                 self.kind_to_target,
                                 _forward)
            # register each TAS_{i} logical name → the same FastAPI app;
            # the registry's invoke_url() returns distinct /TAS_<i>/invoke
            # paths so each component's route routes correctly.
            _tas_port: Optional[int] = None
            for _name in _tas_specs:
                self.apps[_name] = _tas_app
                _tas_port = _tas_specs[_name].port
                _port_to_app[_tas_port] = _tas_app
            if _tas_port is not None:
                self._transport._transports[_tas_port] = httpx.ASGITransport(app=_tas_app)

        # 4c. third-party services — one app per port
        for _name, _spec in self.specs.items():
            if _name.startswith("TAS_"):
                continue
            _targets = _routing_row(self.cfg, _name)
            _app = build_third_party(_spec, _targets, _forward)
            self.apps[_name] = _app
            _port_to_app[_spec.port] = _app
            self._transport._transports[_spec.port] = httpx.ASGITransport(app=_app)

        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        if self.client is not None:
            await self.client.aclose()
        if self._transport is not None:
            await self._transport.aclose()

    def flush_logs(self,
                   output_dir: Path,
                   *,
                   replicate_id: Optional[int] = None) -> Dict[str, int]:
        """*flush_logs()* write each component's log buffer to a CSV; return per-component row counts.

        The TAS target system hosts six components (TAS_{1..6}) inside one
        FastAPI app; their states live on `app.state.tas_components`.
        Third-party services expose a single state on `app.state.service`.
        This method iterates `self.specs` (one entry per component, including
        all six TAS entries) and flushes the state from whichever attribute
        carries it.

        FR-3.8: when `replicate_id` is given, outputs nest under
        `<output_dir>/rep_<id>/<component>.csv` so every replicate of the
        same cell has its own subtree. When `None`, writes flat under
        `<output_dir>/<component>.csv`.

        Args:
            output_dir (Path): cell-level directory.
            replicate_id (Optional[int]): replicate index (0-based); when set, nests into `rep_<id>/`.

        Returns:
            Dict[str, int]: per-component row counts written.
        """
        _dir = output_dir if replicate_id is None else output_dir / f"rep_{int(replicate_id)}"
        _dir.mkdir(parents=True, exist_ok=True)
        _counts: Dict[str, int] = {}
        _flushed: set = set()
        for _name in self.specs:
            _app = self.apps.get(_name)
            if _app is None:
                continue
            # The TAS app exposes its six member contexts via
            # app.state.tas_components; a third-party app exposes its
            # single context via app.state.ctx.
            _components = getattr(_app.state, "tas_components", None)
            if _components is not None and _name in _components:
                _ctx = _components[_name]
            else:
                _ctx = getattr(_app.state, "ctx", None)
                if _ctx is None:
                    continue
            # The same context object may surface under multiple specs
            # (the TAS app is shared across TAS_{1..6}), so flush each
            # context once.
            if id(_ctx) in _flushed:
                continue
            _flushed.add(id(_ctx))
            _fname = _name.replace("{", "_").replace("}", "_").replace(",", "_")
            _path = _dir / f"{_fname}.csv"
            _counts[_name] = _ctx.flush_log(_path, LOG_COLUMNS)
        return _counts

    def lambda_z_entry(self, entry: str = "TAS_{1}") -> float:
        """*lambda_z_entry()* seeded external arrival rate at `entry`."""
        for _a in self.cfg.artifacts:
            if _a.key == entry:
                return float(_a.lambda_z)
        raise KeyError(f"entry artifact {entry!r} not in config")

    def snapshot_config(self,
                        output_dir: Path,
                        *,
                        extras: Optional[Dict[str, Any]] = None) -> Path:
        """*snapshot_config()* write `config.json` capturing the effective controlled values applied to THIS cell.

        This is the FR-3.3 snapshot: downstream analysis joins on what
        actually ran, not on the source profile. Captures:

            - per-artifact `(role, port, mu, epsilon, c, K, seed, mem_per_buffer)` — as resolved by the launcher, post any CLI / scenario overrides.
            - adaptation / profile / scenario labels.
            - routing matrix + `lambda_z` vector.
            - kind_to_target + kind_weights derived at launcher startup.
            - anything the caller passes in `extras` (e.g. seed, replicate_id, request_size_bytes, ramp metadata).

        Args:
            output_dir (Path): directory to write `config.json` into. Created if missing.
            extras (Optional[Dict[str, Any]]): extra keys folded into the snapshot (cell-level context the launcher does not own, e.g. seed, replicate_id).

        Returns:
            Path: absolute path to the written `config.json`.
        """
        import json as _json

        output_dir.mkdir(parents=True, exist_ok=True)

        _artifacts: Dict[str, Any] = {}
        for _name, _spec in self.specs.items():
            _artifacts[_name] = {
                "role": _spec.role,
                "port": _spec.port,
                "mu": _spec.mu,
                "epsilon": _spec.epsilon,
                "c": _spec.c,
                "K": _spec.K,
                "seed": _spec.seed,
                "mem_per_buffer": _spec.mem_per_buffer,
            }

        _snapshot: Dict[str, Any] = {
            "adaptation": self.adaptation,
            "profile": self.cfg.profile,
            "scenario": self.cfg.scenario,
            "label": self.cfg.label,
            "lambda_z": self.cfg.build_lam_z_vec().tolist(),
            "routing": self.cfg.routing.tolist(),
            "artifact_order": [_a.key for _a in self.cfg.artifacts],
            "artifacts": _artifacts,
            "kind_to_target": dict(self.kind_to_target),
            "kind_weights": dict(self.kind_weights),
        }
        if extras:
            _snapshot["extras"] = dict(extras)

        _path = output_dir / "config.json"
        with _path.open("w", encoding="utf-8") as _fh:
            _json.dump(_snapshot, _fh, indent=4, ensure_ascii=False)
        return _path

# -*- coding: utf-8 -*-
"""
Module launcher.py
==================

Assembles the full architectural-experiment mesh. The profile JSON is the single source of truth for DASA knobs (mu, epsilon, c, K, routing); the method JSON (`experiment.json`) carries only deployment plumbing (ports, ramp, request sizes, role tagging).

Composite flavours wired per the `role` field in `experiment.json`:

    - `composite_client` (TAS_{1}, TAS_{5}, TAS_{6}): TAS_{1} routes by request kind via `mount_composite_svc`'s `kind_to_target` table; TAS_{5} and TAS_{6} are terminal.
    - `composite_medical/alarm/drug` (TAS_{2..4}): dispatch siblings in-process via the shared `_handlers` dict from `mount_composite_svc`.

No hardcoded workflow; the routing matrix is the only wiring source.

The shared `httpx.AsyncClient` routes through a `_MultiASGITransport` that dispatches per port. Every port -> app entry registers synchronously during `__aenter__` before the client handles any traffic, so no post-hoc transport mutation can race callers.

Deployment modes (see `notes/distribute.md`): `local` (today's ASGI fast path), `loopback_aliased` (single-host honest bench via `127.0.0.X` aliases), `remote` (real LAN). The ASGI launcher implements `local` only; non-local modes raise `NotImplementedError` until `src.scripts.launch_services` ships in distribute G5.
"""
# native python modules
from __future__ import annotations

import json
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
from src.experiment.registry import SvcRegistry
from src.experiment.services import (LOG_COLUMNS,
                                     HttpForward,
                                     SvcSpec,
                                     derive_seed)
from src.io import NetCfg


# --- transport ------------------------------------------------------------


class _MultiASGITransport(httpx.AsyncBaseTransport):
    """*_MultiASGITransport* dispatches per-port ASGI apps from a single httpx client."""

    def __init__(self, port_to_app: Dict[int, FastAPI]):
        """*__init__()* wrap each `(port, app)` pair in a dedicated `httpx.ASGITransport`."""
        self._transports: Dict[int, httpx.ASGITransport] = {
            _port: httpx.ASGITransport(app=_app)
            for _port, _app in port_to_app.items()
        }

    async def handle_async_request(
            self, request: httpx.Request) -> httpx.Response:
        """*handle_async_request()* route the request to the per-port transport; return HTTP 404 when no app is registered for the URL's port."""
        _port = request.url.port
        if _port is None:
            _t = None
        else:
            _t = self._transports.get(_port)
        if _t is None:
            return httpx.Response(status_code=404,
                                  json={"detail": f"no app for port {_port}"})
        return await _t.handle_async_request(request)

    async def aclose(self) -> None:
        """*aclose()* close every per-port ASGI transport in declaration order."""
        for _t in self._transports.values():
            await _t.aclose()


# --- deployment helpers ---------------------------------------------------


# launcher_role -> set of service-registry roles that bucket spawns locally
_LAUNCHER_ROLE_BUCKETS: Dict[str, Tuple[str, ...]] = {
    "all": (
        "composite_client",
        "composite_medical",
        "composite_alarm",
        "composite_drug",
        "atomic"
    ),
    "client": (
        "composite_client",
    ),
    "composite": (
        "composite_medical",
        "composite_alarm",
        "composite_drug"
    ),
    "atomic": (
        "atomic",
    ),
    "composite-atomic": (
        "composite_medical",
        "composite_alarm",
        "composite_drug",
        "atomic"
    )
}


def pick_bind_addr(deployment: str,
                   override: Optional[str] = None) -> str:
    """*pick_bind_addr()* return the uvicorn bind address for `deployment`.

    Auto-flip rule (per `notes/distribute.md` §4.5):

        - `local` -> `127.0.0.1` (kernel loopback fast path; ~3 ms floor).
        - `loopback_aliased` -> `0.0.0.0` (each service must accept connections from a different `127.0.0.X` alias on the same machine).
        - `remote` -> `0.0.0.0` (each service must accept connections from a different LAN host).

    Args:
        deployment (str): the configured `deployment` mode.
        override (Optional[str]): explicit `--bind` override; when set, returned verbatim.

    Returns:
        str: the bind address uvicorn should listen on.
    """
    if override is not None:
        return str(override)
    if deployment == "local":
        return "127.0.0.1"
    return "0.0.0.0"


def local_services_for_role(launcher_role: str,
                            registry: SvcRegistry) -> List[str]:
    """*local_services_for_role()* return the registry names this launcher is responsible for spawning.

    Reads `_LAUNCHER_ROLE_BUCKETS` to map the role string to a set of
    `service_registry` roles, then filters the registry table to those
    roles. The empty list (`launcher_role=...` unrecognised) is returned
    so the caller fails fast on a typo.

    Args:
        launcher_role (str): one of `"all"` / `"client"` / `"composite"` / `"atomic"` / `"composite-atomic"`.
        registry (SvcRegistry): the populated registry.

    Returns:
        List[str]: service names this launcher spawns; empty when the role string is unrecognised.
    """
    _allowed_roles = _LAUNCHER_ROLE_BUCKETS.get(launcher_role, ())
    if not _allowed_roles:
        return []
    _names: List[str] = []
    for _name, _entry in registry.table.items():
        if _entry.role in _allowed_roles:
            _names.append(_name)
    return _names


# --- derivation helpers: specs + routing ---------------------------------


def _compute_avg_req_size(sizes_by_kind: Dict[str, int]) -> int:
    """*_compute_avg_req_size()* arithmetic mean of per-kind payload sizes; 0 when no sizes declared."""
    _vals = [int(_v) for _v in sizes_by_kind.values() if int(_v) > 0]
    if not _vals:
        return 0
    return int(sum(_vals) / len(_vals))


def _build_specs_from_cfg(cfg: NetCfg,
                          registry: SvcRegistry,
                          *,
                          root_seed: int = 0,
                          avg_request_size_bytes: int = 0
                          ) -> Dict[str, SvcSpec]:
    """*_build_specs_from_cfg()* build one `SvcSpec` per artifact by pulling `(mu, epsilon, c, K)` from the profile JSON and `(role, port)` from the registry.

    `root_seed` is the single seed from `experiment.json::seed`. It is folded with each service's name via `derive_seed` so every service has a stable, independent RNG stream; one knob in JSON controls every stochastic draw in the apparatus.

    `avg_request_size_bytes` is the expected payload size per kind (from `method_cfg["request_size_bytes"]`). The per-service buffer budget is `K * avg_request_size_bytes * MEM_HEADROOM_FACTOR` (1.5x headroom absorbs Pydantic + FastAPI framing overhead without having to physically re-measure the body bytes). The value lives on `SvcSpec.mem_per_buffer` so downstream analysis can derive the memory-usage coefficient.
    """
    _specs: Dict[str, SvcSpec] = {}
    _headroom = SvcSpec.MEM_HEADROOM_FACTOR
    for _a in cfg.artifacts:
        if _a.key not in registry.table:
            # artifact in profile but not in experiment.json registry (e.g. a swap slot inactive for this adaptation); skip silently
            continue
        _entry = registry.table[_a.key]
        _K = int(_a.K)
        _specs[_a.key] = SvcSpec(
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


def _read_routing_row(cfg: NetCfg, name: str) -> List[Tuple[str, float]]:
    """*_read_routing_row()* return `(target_name, probability)` pairs for non-zero entries in `name`'s row, in declaration (column-index) order."""
    _names = [_a.key for _a in cfg.artifacts]
    _idx = _names.index(name)
    _row = np.asarray(cfg.routing[_idx], dtype=float)

    _out: List[Tuple[str, float]] = []
    for _col_idx, _p in enumerate(_row):
        if _p > 0:
            _out.append((_names[_col_idx], float(_p)))
    return _out


def _build_router_kind_map(cfg: NetCfg,
                           name: str
                           ) -> Tuple[Dict[str, str], Dict[str, float]]:
    """*_build_router_kind_map()* build `(kind_to_target, kind_weights)` for a router composite.

    Kind label == target artifact name (simplest, self-documenting). Weights normalise probabilities to sum to 1 across the row's non-zero entries.
    """
    _row = _read_routing_row(cfg, name)
    _total = sum(_p for _, _p in _row)
    _kind_to_target = {_t: _t for _t, _ in _row}
    _kind_weights: Dict[str, float] = {}
    for _t, _p in _row:
        if _total > 0:
            _kind_weights[_t] = _p / _total
        else:
            _kind_weights[_t] = 0.0
    return _kind_to_target, _kind_weights


# external-forward closure is a class `HttpForward` in `services/base.py`; the launcher instantiates it once per run.


# --- launcher -------------------------------------------------------------


@dataclass
class ExperimentLauncher:
    """*ExperimentLauncher* assembles services + shared client for one adaptation run.

    Use via `async with launcher:` to bind setup / teardown to context lifetime.

    Attributes:
        cfg (NetCfg): resolved profile + scenario.
        method_cfg (Dict[str, Any]): loaded `experiment.json`.
        adaptation (str): one of `"baseline"`, `"s1"`, `"s2"`, `"aggregate"`.
        base_port_override (int): override `method_cfg["base_port"]`; 0 reads the config value. Useful for parallel test runs.
        deployment (Optional[str]): override `method_cfg["deployment"]`; `None` reads JSON. Values: `"local"` / `"loopback_aliased"` / `"remote"`. Non-local raises `NotImplementedError` from `__aenter__` until distribute G5 ships the real-uvicorn launcher.
        launcher_role (Optional[str]): override `method_cfg["launcher_role"]`; defaults to `"all"`. Selects which services this process spawns; ignored in `local` mode (which always spawns everything).
    """

    cfg: NetCfg
    method_cfg: Dict[str, Any]
    adaptation: str
    base_port_override: int = 0
    deployment: Optional[str] = None
    launcher_role: Optional[str] = None

    # populated on __aenter__
    registry: Optional[SvcRegistry] = None
    specs: Dict[str, SvcSpec] = field(default_factory=dict)
    apps: Dict[str, FastAPI] = field(default_factory=dict)
    client: Optional[httpx.AsyncClient] = None
    _transport: Optional[_MultiASGITransport] = None
    kind_weights: Dict[str, float] = field(default_factory=dict)
    kind_to_target: Dict[str, str] = field(default_factory=dict)
    # service names this launcher is responsible for spawning; populated on __aenter__
    local_services: List[str] = field(default_factory=list)

    @property
    def resolved_deployment(self) -> str:
        """*resolved_deployment()* effective deployment mode after the constructor / JSON fallback chain."""
        if self.deployment is not None:
            return str(self.deployment)
        return str(self.method_cfg.get("deployment", "local"))

    @property
    def resolved_launcher_role(self) -> str:
        """*resolved_launcher_role()* effective launcher_role; defaults to `"all"`."""
        if self.launcher_role is not None:
            return str(self.launcher_role)
        return str(self.method_cfg.get("launcher_role", "all"))

    async def __aenter__(self) -> "ExperimentLauncher":
        """*__aenter__()* assemble the mesh in 4 steps: (1) registry + specs from JSON; (2) detect the entry router and derive its kind map; (3) build the shared httpx client over an empty port map; (4) build every service app and register port -> app on the transport before returning."""
        # explicit `deployment` arg overrides the JSON; thread to SvcRegistry's per-service host resolution
        _resolved_method_cfg = dict(self.method_cfg)
        _resolved_method_cfg["deployment"] = self.resolved_deployment
        self.registry = SvcRegistry.from_config(
            _resolved_method_cfg, base_port_override=self.base_port_override)
        # populate local_services from launcher_role; `local` mode lists every entry
        self.local_services = local_services_for_role(
            self.resolved_launcher_role, self.registry)
        # non-local modes need real uvicorn TCP (distribute G5); ASGI path is local-only
        if self.resolved_deployment != "local":
            raise NotImplementedError(
                f"deployment={self.resolved_deployment!r} requires the "
                "real-uvicorn launcher (see `notes/distribute.md` G5); "
                "the in-process ASGI launcher only supports "
                "deployment='local'. Run `python -m src.scripts.launch_services` "
                "on each host instead.")
        # one experiment.json::seed folded per service name yields stable independent RNG streams; mem_per_buffer = K * avg_request_size * 1.5 sized for the memory-usage coefficient
        _root_seed = int(self.method_cfg.get("seed", 0))
        _avg_size = _compute_avg_req_size(
            self.method_cfg.get("request_size_bytes", {}))
        self.specs = _build_specs_from_cfg(self.cfg, self.registry,
                                           root_seed=_root_seed,
                                           avg_request_size_bytes=_avg_size)

        # TAS_{1} is the entry router (composite_client with a non-empty outbound row); TAS_{5} / TAS_{6} are terminal
        def _is_entry_router(_name: str) -> bool:
            _entry = self.registry.table[_name]
            if _entry.role != "composite_client":
                return False
            if _name not in self.specs:
                return False
            return bool(_read_routing_row(self.cfg, _name))

        _routers = [_n for _n in self.registry.table if _is_entry_router(_n)]
        if _routers:
            self.kind_to_target, self.kind_weights = _build_router_kind_map(
                self.cfg, _routers[0])

        # step-3 transport: empty port map filled synchronously before any HTTP traffic flows
        self._transport = _MultiASGITransport({})
        self.client = httpx.AsyncClient(transport=self._transport,
                                        timeout=httpx.Timeout(10.0))

        # step-4 build: TAS uses `build_tas` (one app, 6 components, `mount_composite_svc`); third-party uses `build_third_party` (`mount_atomic_svc`); both share one `HttpForward`
        _forward = HttpForward(self.client, self.registry)
        _port_to_app: Dict[int, FastAPI] = {}

        # step-4a: collect the six TAS component specs + their routing rows
        _tas_specs: Dict[str, SvcSpec] = {}
        _tas_rows: Dict[str, List[Tuple[str, float]]] = {}
        for _name, _spec in self.specs.items():
            if _name.startswith("TAS_"):
                _tas_specs[_name] = _spec
                _tas_rows[_name] = _read_routing_row(self.cfg, _name)

        # step-4b: one TAS app; per-component `SvcCtx` exposed at `app.state.tas_components`
        if _tas_specs:
            _tas_app = build_tas(_tas_specs,
                                 _tas_rows,
                                 self.kind_to_target,
                                 _forward)
            # every TAS_{i} maps to the same app; `build_invoke_url` returns distinct `/TAS_<i>/invoke` paths
            _tas_port: Optional[int] = None
            for _name in _tas_specs:
                self.apps[_name] = _tas_app
                _tas_port = _tas_specs[_name].port
                _port_to_app[_tas_port] = _tas_app
            if _tas_port is not None:
                self._transport._transports[_tas_port] = httpx.ASGITransport(
                    app=_tas_app)

        # step-4c: third-party services, one app per port
        for _name, _spec in self.specs.items():
            if _name.startswith("TAS_"):
                continue
            _targets = _read_routing_row(self.cfg, _name)
            _app = build_third_party(_spec, _targets, _forward)
            self.apps[_name] = _app
            _port_to_app[_spec.port] = _app
            self._transport._transports[_spec.port] = httpx.ASGITransport(
                app=_app)

        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        """*__aexit__()* close the shared httpx client and every per-port ASGI transport."""
        if self.client is not None:
            await self.client.aclose()
        if self._transport is not None:
            await self._transport.aclose()

    def collect_drop_counts(self) -> Dict[str, int]:
        """*collect_drop_counts()* report the bounded-deque overflow count per service.

        `SvcCtx.dropped_count` increments any time `@logger` appends to a full log buffer (the oldest row is silently evicted per `deque(maxlen=...)` semantics). A healthy run returns `{}`; a non-zero entry means the buffer was sized too small for the workload and some observations were lost.

        Returns:
            Dict[str, int]: `{service_name: dropped_count}` for every service with a non-zero drop count; empty when every buffer stayed within its cap.
        """
        _drops: Dict[str, int] = {}
        _seen: set = set()
        for _name in self.specs:
            _app = self.apps.get(_name)
            if _app is None:
                continue
            _components = getattr(_app.state, "tas_components", None)
            if _components is not None and _name in _components:
                _ctx = _components[_name]
            else:
                _ctx = getattr(_app.state, "ctx", None)
                if _ctx is None:
                    continue
            if id(_ctx) in _seen:
                continue
            _seen.add(id(_ctx))
            _n = int(getattr(_ctx, "dropped_count", 0))
            if _n > 0:
                _drops[_name] = _n
        return _drops

    def flush_logs(self,
                   output_dir: Path,
                   *,
                   replicate_id: Optional[int] = None) -> Dict[str, int]:
        """*flush_logs()* write each component's log buffer to a CSV; return per-component row counts.

        The TAS target system hosts six components (TAS_{1..6}) inside one FastAPI app; their states live on `app.state.tas_components`. Third-party services expose a single state on `app.state.ctx`. This method iterates `self.specs` (one entry per component, including all six TAS entries) and flushes the state from whichever attribute carries it.

        FR-3.8: when `replicate_id` is given, outputs nest under `<output_dir>/rep_<id>/<component>.csv` so every replicate of the same cell has its own subtree. When `None`, writes flat under `<output_dir>/<component>.csv`.

        Args:
            output_dir (Path): cell-level directory.
            replicate_id (Optional[int]): replicate index (0-based); when set, nests into `rep_<id>/`.

        Returns:
            Dict[str, int]: per-component row counts written.
        """
        if replicate_id is None:
            _dir = output_dir
        else:
            _dir = output_dir / f"rep_{int(replicate_id)}"
        _dir.mkdir(parents=True, exist_ok=True)
        _counts: Dict[str, int] = {}
        _flushed: set = set()
        for _name in self.specs:
            _app = self.apps.get(_name)
            if _app is None:
                continue
            # TAS app: per-component contexts at `app.state.tas_components`; third-party: single context at `app.state.ctx`
            _components = getattr(_app.state, "tas_components", None)
            if _components is not None and _name in _components:
                _ctx = _components[_name]
            else:
                _ctx = getattr(_app.state, "ctx", None)
                if _ctx is None:
                    continue
            # TAS app is shared across TAS_{1..6}; flush each context object once
            if id(_ctx) in _flushed:
                continue
            _flushed.add(id(_ctx))
            _fname = _name.replace(
                "{", "_").replace("}", "_").replace(",", "_")
            _path = _dir / f"{_fname}.csv"
            _counts[_name] = _ctx.flush_log(_path, LOG_COLUMNS)
        return _counts

    def get_lam_z_entry(self, entry: str = "TAS_{1}") -> float:
        """*get_lam_z_entry()* seeded external arrival rate at `entry`."""
        for _a in self.cfg.artifacts:
            if _a.key == entry:
                return float(_a.lambda_z)
        raise KeyError(f"entry artifact {entry!r} not in config")

    def snapshot_config(self,
                        output_dir: Path,
                        *,
                        extras: Optional[Dict[str, Any]] = None) -> Path:
        """*snapshot_config()* write `config.json` capturing the effective controlled values for THIS cell.

        Pins what actually ran for downstream analysis to join on, post any CLI / scenario overrides. Captures:

            - per-artifact `(role, port, mu, epsilon, c, K, seed, mem_per_buffer)` as resolved by the launcher.
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
            json.dump(_snapshot, _fh, indent=4, ensure_ascii=False)
        return _path

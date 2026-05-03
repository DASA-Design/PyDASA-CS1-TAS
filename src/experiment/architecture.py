# -*- coding: utf-8 -*-
"""
Module experiment/architecture.py
=================================

Server-side prototype component. Counterpart of `users.py::TasUser` (synthetic user population): the architecture builds the mesh, the user drives traffic against it; `executor.py` is the bridge that pairs the two for one cell.

Public API:
    - `class TasArchitecture` async context manager that assembles the FastAPI mesh (composite + third-party services) for one adaptation, exposes the shared `httpx.AsyncClient`, and tears the mesh down on exit. The class also owns the deployment-helper surface (`bind_addr` property, `local_services()` method).

The profile JSON is the single source of truth for DASA knobs (mu, epsilon, c, K, routing); the method JSON (`experiment.json`) carries deployment plumbing (ports, request sizes, role tagging). The architecture only assembles + inspects; it does NOT drive traffic (that is `executor.py` + `users.py`).

Composite flavours wired per the `role` field in `experiment.json`:

    - `composite_client` (TAS_{1}, TAS_{5}, TAS_{6}): TAS_{1} routes by request kind via `mount_composite_svc`'s `kind_to_tgt` table; TAS_{5} and TAS_{6} are terminal.
    - `composite_medical/alarm/drug` (TAS_{2..4}): dispatch siblings in-process via the shared `_handlers` dict from `mount_composite_svc`.

Shared `httpx.AsyncClient` over a per-port `httpx.MockTransport` handler closure; per-port apps register on `__aenter__` before any traffic flows.

Deployment modes: `localhost` (ASGI), `multiprocess` (`127.0.0.X` aliases), `remote` (LAN). Only `localhost` is implemented; non-localhost raises `NotImplementedError` until `src.scripts.launch_services` ships.
"""
# native python modules
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional, Tuple

# scientific stack
import numpy as np

# web stack
import httpx
from fastapi import FastAPI

# local modules
from src.experiment.instances import build_tas, build_third_party
from src.experiment.wire import SvcRegistry
from src.experiment.services import (LOG_COLUMNS,
                                     HttpForward,
                                     SvcSpec,
                                     derive_seed)
from src.io import NetCfg


# launcher_role -> registry-roles spawned locally
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


# --- module-level helpers -------------------------------------------------


def _compute_avg_req_size(sizes_by_kind: Dict[str, int]) -> int:
    """*_compute_avg_req_size()* mean payload size across kinds; the TAS buffer budget uses it.

    Args:
        sizes_by_kind (Dict[str, int]): per-kind request sizes in bytes.

    Returns:
        int: average; zero-valued entries are dropped, empty input yields 0.
    """
    # TODO check if this moves to another module
    _vals = [int(_v) for _v in sizes_by_kind.values() if int(_v) > 0]
    if not _vals:
        return 0
    return int(sum(_vals) / len(_vals))


# --- prototype component --------------------------------------------------


@dataclass
class TasArchitecture:
    """*TasArchitecture* the server side of one adaptation run; counterpart to `users.py::TasUser`.

    Use as `async with TasArchitecture(...) as arch:` to bind mesh setup and teardown to the block.
    """

    # experimental profile from configuration JSON
    cfg: NetCfg

    # method config from JSON; carries deployment plumbing (ports, request sizes, role tagging)
    method_cfg: Dict[str, Any]

    # adaptation scenario from JSON; one of "baseline", "s1", "s2", "aggregate"
    adaptation: str

    # override for the base port; 0 reads the config value
    base_port_ovrd: int = 0

    # override for the deployment mode; None reads the config value; values: "localhost" / "multiprocess" / "remote"
    deployment: Optional[str] = None

    # override for the launcher role; None reads the config value; values: "all" / "client" / "composite" / "atomic" / "composite-atomic"
    launcher_role: Optional[str] = None

    # registry resolved on __aenter__
    registry: Optional[SvcRegistry] = None

    # per-artifact specs resolved on __aenter__
    specs: Dict[str, SvcSpec] = field(default_factory=dict)

    # service-name -> FastAPI app; TAS_{1..6} share one app
    apps: Dict[str, FastAPI] = field(default_factory=dict)

    # shared httpx client routing per-port via MockTransport handler
    client: Optional[httpx.AsyncClient] = None

    # per-port ASGI transports keyed by registered port; populated as apps mount
    _port_tps: Dict[int, httpx.ASGITransport] = field(
        default_factory=dict)

    # entry-router kind probabilities derived from TAS_{1}'s routing row; values sum to 1
    kind_prob: Dict[str, float] = field(default_factory=dict)

    # entry-router kind label -> target artifact name
    kind_to_tgt: Dict[str, str] = field(default_factory=dict)

    @property
    def resolved_deployment(self) -> str:
        """*resolved_deployment* deployment mode in effect.

        Returns:
            str: constructor arg if set, else `method_cfg["deployment"]`, else `"localhost"`.
        """
        if self.deployment is not None:
            return str(self.deployment)
        return str(self.method_cfg.get("deployment", "localhost"))

    @property
    def resolved_launcher_role(self) -> str:
        """*resolved_launcher_role* launcher role in effect.

        Returns:
            str: constructor arg if set, else `method_cfg["launcher_role"]`, else `"all"`.
        """
        if self.launcher_role is not None:
            return str(self.launcher_role)
        return str(self.method_cfg.get("launcher_role", "all"))

    @property
    def bind_addr(self) -> str:
        """*bind_addr* uvicorn bind address selected from the deployment mode.

        Returns:
            str: `127.0.0.1` for `localhost`, `0.0.0.0` for `multiprocess` or `remote` (other aliases / LAN hosts must be reachable).
        """
        if self.resolved_deployment == "localhost":
            return "127.0.0.1"
        return "0.0.0.0"

    @staticmethod
    def services_for_role(launcher_role: str,
                          registry: SvcRegistry) -> List[str]:
        """*services_for_role()* registry names a launcher in this role spawns; callable without an entered architecture so distributed scripts can use it directly.

        Args:
            launcher_role (str): one of `"all"` / `"client"` / `"composite"` / `"atomic"` / `"composite-atomic"`.
            registry (SvcRegistry): registry to filter.

        Returns:
            List[str]: service names; empty when the role string is unrecognised.
        """
        _allowed = _LAUNCHER_ROLE_BUCKETS.get(launcher_role, ())
        if not _allowed:
            return []
        _names: List[str] = []
        for _name, _entry in registry.table.items():
            if _entry.role in _allowed:
                _names.append(_name)
        return _names

    def local_services(self) -> List[str]:
        """*local_services()* the names this architecture spawns under its resolved role.

        Returns:
            List[str]: service names; empty when the resolved role is unrecognised.

        Raises:
            RuntimeError: when called before `__aenter__`.
        """
        if self.registry is None:
            _msg = "local_services() called before __aenter__ resolved the registry"
            raise RuntimeError(_msg)
        return self.services_for_role(self.resolved_launcher_role,
                                      self.registry)

    async def __aenter__(self) -> "TasArchitecture":
        """*__aenter__()* stand the mesh up.

        Raises:
            NotImplementedError: on non-localhost deployment until the real-uvicorn launcher ships.

        Returns:
            TasArchitecture: this instance, ready for traffic.
        """
        self._gate_deployment()
        self._init_registry_and_specs()
        self._resolve_entry_router()
        self._init_routed_client()
        self._mount_apps()
        return self

    def _gate_deployment(self) -> None:
        """*_gate_deployment()* refuse modes the in-process ASGI launcher cannot serve.

        Raises:
            NotImplementedError: when the resolved deployment is not `"localhost"`.
        """
        if self.resolved_deployment == "localhost":
            return
        _msg = (
            f"deployment={self.resolved_deployment!r} requires the "
            "real-uvicorn launcher (see `notes/distribute.md` G5); "
            "the in-process ASGI launcher only supports "
            "deployment='localhost'. Run `python -m src.scripts.launch_services` "
            "on each host instead.")
        raise NotImplementedError(_msg)

    def _init_registry_and_specs(self) -> None:
        """*_init_registry_and_specs()* fill `self.registry` and `self.specs`."""
        _resolved_method_cfg = dict(self.method_cfg)
        _resolved_method_cfg["deployment"] = self.resolved_deployment
        self.registry = SvcRegistry.from_config(
            _resolved_method_cfg, base_port_ovrd=self.base_port_ovrd)
        _root_seed = int(self.method_cfg.get("seed", 0))
        _avg_size = _compute_avg_req_size(
            self.method_cfg.get("request_size_bytes", {}))
        self.specs = self._build_specs(root_seed=_root_seed,
                                       avg_req_size_b=_avg_size)

    def _resolve_entry_router(self) -> None:
        """*_resolve_entry_router()* fill `self.kind_to_tgt` and `self.kind_prob` from the first deployed `composite_client` with a non-empty row; leave both empty otherwise."""
        if self.registry is None:
            return
        _entry_router: Optional[str] = None
        for _name, _entry in self.registry.table.items():
            if _entry.role != "composite_client":
                continue
            if _name not in self.specs:
                continue
            if self._read_routing_row(_name):
                _entry_router = _name
                break
        if _entry_router is None:
            return
        _kt, _kw = self._build_router_kind_map(_entry_router)
        self.kind_to_tgt = _kt
        self.kind_prob = _kw

    def _init_routed_client(self) -> None:
        """*_init_routed_client()* build `self.client`: a shared `httpx.AsyncClient` that routes per request to the ASGI transport registered for the destination port (404 on miss)."""
        async def _route_by_port(request: httpx.Request) -> httpx.Response:
            _port = request.url.port
            if _port is None:
                _t = None
            else:
                _t = self._port_tps.get(_port)
            if _t is None:
                return httpx.Response(
                    status_code=404,
                    json={"detail": f"no app for port {_port}"})
            return await _t.handle_async_request(request)

        self.client = httpx.AsyncClient(
            transport=httpx.MockTransport(_route_by_port),
            limits=httpx.Limits(max_connections=4096,
                                max_keepalive_connections=2048),
            timeout=httpx.Timeout(connect=5.0,
                                  read=30.0,
                                  write=10.0,
                                  pool=10.0))

    def _mount_apps(self) -> None:
        """*_mount_apps()* register every service app behind the shared client: one TAS app for TAS_{1..6}, one app per third-party."""
        if self.client is None or self.registry is None:
            return
        _forward = HttpForward(self.client, self.registry)
        self._mount_tas_app(_forward)
        self._mount_third_party_apps(_forward)

    def _mount_tas_app(self, forward: HttpForward) -> None:
        """*_mount_tas_app()* mount one shared FastAPI app for every `TAS_*` spec on the entry port.

        Args:
            forward (HttpForward): downstream-call helper bound to the shared client and registry.
        """
        _tas_specs: Dict[str, SvcSpec] = {}
        _tas_rows: Dict[str, List[Tuple[str, float]]] = {}
        for _name, _spec in self.specs.items():
            if _name.startswith("TAS_"):
                _tas_specs[_name] = _spec
                _tas_rows[_name] = self._read_routing_row(_name)
        if not _tas_specs:
            return
        _tas_app = build_tas(_tas_specs,
                             _tas_rows,
                             self.kind_to_tgt,
                             forward)
        _tas_port: Optional[int] = None
        for _name, _spec in _tas_specs.items():
            self.apps[_name] = _tas_app
            _tas_port = _spec.port
        if _tas_port is not None:
            self._port_tps[_tas_port] = httpx.ASGITransport(app=_tas_app)

    def _mount_third_party_apps(self, forward: HttpForward) -> None:
        """*_mount_third_party_apps()* mount one FastAPI app per non-TAS spec.

        Args:
            forward (HttpForward): downstream-call helper bound to the shared client and registry.
        """
        for _name, _spec in self.specs.items():
            if _name.startswith("TAS_"):
                continue
            _targets = self._read_routing_row(_name)
            _app = build_third_party(_spec, _targets, forward)
            self.apps[_name] = _app
            self._port_tps[_spec.port] = httpx.ASGITransport(app=_app)

    async def __aexit__(self, _exc_type, _exc, _tb) -> None:
        """*__aexit__()* close the shared httpx client and every per-port ASGI transport.

        The three exception-context parameters are required by the protocol but unused: cleanup runs identically on success and on exception, and returning `None` lets in-flight exceptions propagate.

        Args:
            _exc_type: exception class or `None`; unused.
            _exc: exception instance or `None`; unused.
            _tb: traceback or `None`; unused.
        """
        if self.client is not None:
            await self.client.aclose()
        for _t in self._port_tps.values():
            await _t.aclose()

    def _build_specs(self,
                     *,
                     root_seed: int = 0,
                     avg_req_size_b: int = 0) -> Dict[str, SvcSpec]:
        """*_build_specs()* one `SvcSpec` per registered artifact, taking `(mu, epsilon, c, K)` from the profile and `(role, port)` from the registry.

        Args:
            root_seed (int): folded per service via `derive_seed` for stable independent RNG streams.
            avg_req_size_b (int, bytes): expected per-kind payload size; sets `mem_per_buffer = K * avg * MEM_HEADROOM_FACTOR`.

        Returns:
            Dict[str, SvcSpec]: one entry per artifact present in both profile and registry; swap-slot artifacts inactive in the current adaptation are skipped silently.
        """
        _specs: Dict[str, SvcSpec] = {}
        _headroom = SvcSpec.MEM_HEADROOM_FACTOR
        _registry = self.registry
        if _registry is None:
            _msg = "_build_specs() called before __aenter__ resolved the registry"
            raise RuntimeError(_msg)
        for _a in self.cfg.artifacts:
            if _a.key not in _registry.table:
                continue
            _entry = _registry.table[_a.key]
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
                mem_per_buffer=int(_K * int(avg_req_size_b) * _headroom),
                enforce_limits=bool(self.cfg.enforce_limits),
            )
        return _specs

    def _read_routing_row(self, name: str) -> List[Tuple[str, float]]:
        """*_read_routing_row()* non-zero `(target_name, probability)` entries from one row of the routing matrix.

        Args:
            name (str): artifact key whose row to read.

        Returns:
            List[Tuple[str, float]]: pairs in column-declaration order; empty when the row has no non-zero entries.
        """
        _names = [_a.key for _a in self.cfg.artifacts]
        _idx = _names.index(name)
        _row = np.asarray(self.cfg.routing[_idx], dtype=float)
        _out: List[Tuple[str, float]] = []
        for _col_idx, _p in enumerate(_row):
            if _p > 0:
                _out.append((_names[_col_idx], float(_p)))
        return _out

    def _build_router_kind_map(self, name: str
                               ) -> Tuple[Dict[str, str], Dict[str, float]]:
        """*_build_router_kind_map()* derive the kind tables for a router composite from its routing row.

        The kind label is the target artifact name (self-documenting); weights are normalised so the row sums to 1. Zero-row safe (returns all-zero weights).

        Args:
            name (str): router artifact key.

        Returns:
            Tuple[Dict[str, str], Dict[str, float]]: `(kind_to_tgt, kind_prob)`.
        """
        _row = self._read_routing_row(name)
        _total = sum(_p for _, _p in _row)
        _kt = {_t: _t for _t, _ in _row}
        _kw: Dict[str, float] = {}
        for _t, _p in _row:
            if _total > 0:
                _kw[_t] = _p / _total
            else:
                _kw[_t] = 0.0
        return _kt, _kw

    def _iter_component_ctxs(self) -> Iterator[Tuple[str, Any]]:
        """*_iter_component_ctxs()* yield each deployed component's `SvcCtx` once, deduplicating the shared TAS context across TAS_{1..6}.

        Yields:
            Tuple[str, Any]: `(service_name, SvcCtx)` per unique deployed component.
        """
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
            yield _name, _ctx

    def collect_drop_counts(self) -> Dict[str, int]:
        """*collect_drop_counts()* per-service log-buffer overflow count; a non-zero entry means the bounded deque silently evicted observations.

        Returns:
            Dict[str, int]: `{service_name: dropped_count}`; empty when every buffer stayed within its cap.
        """
        _drops: Dict[str, int] = {}
        for _name, _ctx in self._iter_component_ctxs():
            _n = int(getattr(_ctx, "dropped_count", 0))
            if _n > 0:
                _drops[_name] = _n
        return _drops

    def flush_logs(self,
                   output_dir: Path,
                   *,
                   replicate_id: Optional[int] = None) -> Dict[str, int]:
        """*flush_logs()* drain each component's log buffer to a per-service CSV; with `replicate_id` set, files nest under `<output_dir>/rep_<id>/`.

        Args:
            output_dir (Path): cell-level output directory.
            replicate_id (Optional[int]): 0-based replicate index; when set, nests into `rep_<id>/`.

        Returns:
            Dict[str, int]: `{service_name: rows_written}`.
        """
        if replicate_id is None:
            _dir = output_dir
        else:
            _dir = output_dir / f"rep_{int(replicate_id)}"
        _dir.mkdir(parents=True, exist_ok=True)
        _counts: Dict[str, int] = {}
        for _name, _ctx in self._iter_component_ctxs():
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
        _msg = f"entry artifact {entry!r} not in config"
        raise KeyError(_msg)

    def snapshot_config(self,
                        output_dir: Path,
                        *,
                        extras: Optional[Dict[str, Any]] = None) -> Path:
        """*snapshot_config()* freeze the resolved cell configuration to `<output_dir>/config.json` so downstream analysis can join on what actually ran (per-artifact specs, scenario labels, routing matrix, lambda_z, kind tables; `extras` folded under an `extras` key).

        Args:
            output_dir (Path): directory to write `config.json` into; created if missing.
            extras (Optional[Dict[str, Any]]): cell-level fields the architecture itself does not own (seed, replicate index, ramp metadata).

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
            "kind_to_target": dict(self.kind_to_tgt),
            "kind_weights": dict(self.kind_prob),
        }
        if extras:
            _snapshot["extras"] = dict(extras)
        _path = output_dir / "config.json"
        with _path.open("w", encoding="utf-8") as _fh:
            json.dump(_snapshot, _fh, indent=4, ensure_ascii=False)
        return _path

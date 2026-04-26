# -*- coding: utf-8 -*-
"""
Module launch_services.py
=========================

Real-uvicorn launcher for non-local deployments. Spawns one TCP-listening uvicorn server per service this machine is responsible for, polls every entry's `/healthz` (local + remote) until the mesh is ready, then blocks until SIGINT (or `--duration` seconds elapse).

Reads the same `data/config/method/experiment.json` every machine ships; the only per-machine difference is the `--launcher-role` flag.

Usage:

    # 2-machine layout (client on A, services on B)
    # on machine A (the driver):
    python -m src.methods.experiment --deployment=remote --launcher-role=client

    # on machine B (services):
    python -m src.scripts.launch_services --launcher-role=composite-atomic

    # 3-machine layout
    # on machine B (composite):
    python -m src.scripts.launch_services --launcher-role=composite

    # on machine C (atomics):
    python -m src.scripts.launch_services --launcher-role=atomic

    # single-host honest bench (loopback aliases):
    python -m src.scripts.launch_services --deployment=loopback_aliased

The launcher unlocks `loopback_aliased` and `remote` modes that the in-process ASGI launcher (`src.experiment.launcher.ExperimentLauncher`) cannot serve because it short-circuits HTTP via `_MultiASGITransport`.
"""
# native python modules
from __future__ import annotations

import argparse
import asyncio
import sys
import time
from typing import Any, Dict, List, Optional, Tuple

# web stack
import httpx
from fastapi import FastAPI

# local modules
from src.experiment.instances import build_tas, build_third_party
from src.experiment.launcher import (local_services_for_role,
                                     pick_bind_addr)
from src.experiment.registry import SvcRegistry
from src.experiment.services import (HttpForward,
                                     SvcSpec,
                                     derive_seed)
from src.experiment.uvicorn_thread import UvicornThread
from src.io import load_method_cfg, load_profile


_VALID_DEPLOYMENTS = ("local", "loopback_aliased", "remote")
_VALID_ROLES = ("all", "client", "composite", "atomic", "composite-atomic")


def _build_specs(cfg: Any,
                 registry: SvcRegistry,
                 root_seed: int,
                 avg_request_size_bytes: int) -> Dict[str, SvcSpec]:
    """*_build_specs()* mirror `ExperimentLauncher._build_specs_from_cfg` at module scope so this script does not depend on the launcher's private helper.

    Args:
        cfg: resolved profile + scenario.
        registry (SvcRegistry): populated registry.
        root_seed (int): root seed from `experiment.json::seed`.
        avg_request_size_bytes (int): drives `mem_per_buffer = K * avg * MEM_HEADROOM_FACTOR`.

    Returns:
        Dict[str, SvcSpec]: one SvcSpec per artifact present in both profile and registry.
    """
    _specs: Dict[str, SvcSpec] = {}
    _headroom = SvcSpec.MEM_HEADROOM_FACTOR
    for _a in cfg.artifacts:
        if _a.key not in registry.table:
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


def _wait_remote_health(registry: SvcRegistry,
                        local_names: set,
                        timeout_s: float = 60.0,
                        verbose: bool = True) -> None:
    """*_wait_remote_health()* poll `/healthz` on every NON-local service until it answers 200 or `timeout_s` fires.

    The launcher's own `UvicornThread.wait_ready` covers local services; this helper covers the remote ones. Together they form the whole-mesh health barrier (`notes/distribute.md` §4.2 risk row "Health barrier hangs because remote machine is not up yet" — bumped to 60 s by default).

    Args:
        registry (SvcRegistry): populated registry.
        local_names (set): names this launcher spawned locally.
        timeout_s (float): wall-clock cap per service.
        verbose (bool): when True, print one line per probed service.

    Raises:
        RuntimeError: when a remote service did not answer within `timeout_s`.
    """
    _start = time.perf_counter()
    _deadline = _start + float(timeout_s)
    for _name in registry.list_names():
        if _name in local_names:
            continue
        _url = registry.build_healthz_url(_name)
        if verbose:
            print(f"  waiting on remote {_name} -> {_url}")
        while True:
            _now = time.perf_counter()
            if _now >= _deadline:
                raise RuntimeError(
                    f"remote service {_name!r} at {_url} did not "
                    f"answer /healthz within {timeout_s} s")
            try:
                _r = httpx.get(_url, timeout=1.0)
                if _r.status_code == 200:
                    break
            except (httpx.HTTPError, ConnectionError, OSError):
                pass
            time.sleep(0.5)


def _spawn_one_app(name: str,
                   app: FastAPI,
                   port: int,
                   bind_host: str,
                   verbose: bool) -> UvicornThread:
    """*_spawn_one_app()* start a `UvicornThread` and wait for `/healthz`.

    Args:
        name (str): service name (used in log lines only).
        app (FastAPI): app to serve.
        port (int): TCP port.
        bind_host (str): bind address resolved from `pick_bind_addr`.
        verbose (bool): when True, print one line on start.

    Returns:
        UvicornThread: started, ready-to-serve thread.
    """
    if verbose:
        print(f"  starting {name} on {bind_host}:{port}")
    _t = UvicornThread(app, port, host=bind_host)
    _t.start()
    _t.wait_ready(timeout_s=10.0)
    return _t


def _build_apps_for_local(cfg: Any,
                          registry: SvcRegistry,
                          specs: Dict[str, SvcSpec],
                          local_names: set,
                          httpx_client: httpx.AsyncClient
                          ) -> List[Tuple[str, FastAPI, int]]:
    """*_build_apps_for_local()* assemble FastAPI apps for the services this launcher spawns.

    TAS components share one app via `build_tas`; third-party services each get their own via `build_third_party`. The shared `httpx_client` carries cross-service hops to remote uvicorn instances over real TCP (no ASGI shortcut).

    Args:
        cfg: resolved profile + scenario.
        registry (SvcRegistry): populated registry.
        specs (Dict[str, SvcSpec]): one SvcSpec per active artifact.
        local_names (set): subset of names this launcher spawns.
        httpx_client (httpx.AsyncClient): shared client used by every `HttpForward`.

    Returns:
        List[Tuple[str, FastAPI, int]]: `(label, app, port)` triples ready for uvicorn spawn.
    """
    import numpy as np
    _forward = HttpForward(httpx_client, registry)

    _names_in_artifact_order = [_a.key for _a in cfg.artifacts]

    def _routing_row(_name: str) -> List[Tuple[str, float]]:
        _idx = _names_in_artifact_order.index(_name)
        _row = np.asarray(cfg.routing[_idx], dtype=float)
        _out: List[Tuple[str, float]] = []
        for _col_idx, _p in enumerate(_row):
            if _p > 0:
                _out.append((_names_in_artifact_order[_col_idx], float(_p)))
        return _out

    def _kind_map_for(_name: str) -> Dict[str, str]:
        _row = _routing_row(_name)
        return {_t: _t for _t, _ in _row}

    _ans: List[Tuple[str, FastAPI, int]] = []

    # collect TAS specs that are local on this host
    _local_tas_specs: Dict[str, SvcSpec] = {}
    _local_tas_rows: Dict[str, List[Tuple[str, float]]] = {}
    for _name, _spec in specs.items():
        if _name not in local_names:
            continue
        if _name.startswith("TAS_"):
            _local_tas_specs[_name] = _spec
            _local_tas_rows[_name] = _routing_row(_name)

    # one TAS app for all TAS components on this host (shared port)
    if _local_tas_specs:
        # entry-router kind map: take the first TAS_{i} composite_client with a non-empty row, fallback to any TAS_{1} row
        _entry_kind_map: Dict[str, str] = {}
        for _name, _spec in _local_tas_specs.items():
            if registry.table[_name].role == "composite_client":
                _row = _routing_row(_name)
                if _row:
                    _entry_kind_map = _kind_map_for(_name)
                    break
        _tas_app = build_tas(_local_tas_specs,
                             _local_tas_rows,
                             _entry_kind_map,
                             _forward)
        # all TAS_{i} share one port; use the first member's port
        _tas_port = next(iter(_local_tas_specs.values())).port
        _ans.append(("TAS_*", _tas_app, _tas_port))

    # third-party services: one app per port
    for _name, _spec in specs.items():
        if _name not in local_names:
            continue
        if _name.startswith("TAS_"):
            continue
        _app = build_third_party(_spec, _routing_row(_name), _forward)
        _ans.append((_name, _app, _spec.port))

    return _ans


async def _serve_until_signal(threads: List[UvicornThread],
                              duration_s: Optional[float],
                              verbose: bool) -> None:
    """*_serve_until_signal()* hold the process open until SIGINT or `duration_s` elapses.

    Args:
        threads (List[UvicornThread]): live uvicorn threads (for shutdown on exit).
        duration_s (Optional[float]): when set, exit cleanly after this many seconds (used by tests / scripted smokes).
        verbose (bool): when True, print the wait banner.
    """
    if duration_s is not None:
        if verbose:
            print(f"  serving for {duration_s:.1f} s "
                  "(use SIGINT to stop sooner) ...")
        try:
            await asyncio.wait_for(asyncio.Future(), timeout=float(duration_s))
        except asyncio.TimeoutError:
            pass
    else:
        if verbose:
            print("  serving (Ctrl-C to stop) ...")
        try:
            await asyncio.Future()
        except (asyncio.CancelledError, KeyboardInterrupt):
            pass


def main(argv: Optional[List[str]] = None) -> int:
    """*main()* CLI entry point.

    Args:
        argv (Optional[List[str]]): explicit argv for tests; defaults to `sys.argv[1:]`.

    Returns:
        int: exit code (0 on clean shutdown, non-zero on configuration error).
    """
    _parser = argparse.ArgumentParser(
        prog="launch_services",
        description=("Spawn the subset of TAS services this machine "
                     "owns. Reads data/config/method/experiment.json."))
    _parser.add_argument(
        "--launcher-role",
        choices=_VALID_ROLES, default="all",
        help=("which bucket runs locally on this host; the other buckets "
              "are reached via hosts.<bucket> in the JSON config"))
    _parser.add_argument(
        "--deployment",
        choices=_VALID_DEPLOYMENTS, default=None,
        help=("deployment mode override; defaults to method_cfg['deployment']"))
    _parser.add_argument(
        "--bind",
        default=None,
        help=("explicit bind address override; unset, defaults are "
              "local -> 127.0.0.1, others -> 0.0.0.0"))
    _parser.add_argument("--adaptation", default="baseline",
                         choices=["baseline", "s1", "s2", "aggregate"])
    _parser.add_argument("--profile", default=None)
    _parser.add_argument("--scenario", default=None)
    _parser.add_argument("--duration", type=float, default=None,
                         help=("exit cleanly after N seconds; default is "
                               "to block on SIGINT"))
    _parser.add_argument("--verbose", action="store_true", default=True)
    _args = _parser.parse_args(argv)

    _mcfg = load_method_cfg("experiment")
    _dpl = _args.deployment or str(_mcfg.get("deployment", "local"))
    if _dpl not in _VALID_DEPLOYMENTS:
        print(f"ERROR: unknown deployment {_dpl!r}; "
              f"valid {_VALID_DEPLOYMENTS}", file=sys.stderr)
        return 2

    _resolved_mcfg = dict(_mcfg)
    _resolved_mcfg["deployment"] = _dpl
    _registry = SvcRegistry.from_config(_resolved_mcfg)
    _local_names = set(local_services_for_role(_args.launcher_role,
                                               _registry))
    _bind = pick_bind_addr(_dpl, override=_args.bind)

    if _args.verbose:
        print(f"launch_services: deployment={_dpl} "
              f"launcher_role={_args.launcher_role} bind={_bind}")
        print(f"local services ({len(_local_names)}): "
              f"{sorted(_local_names)}")

    _cfg = load_profile(adaptation=_args.adaptation,
                        profile=_args.profile,
                        scenario=_args.scenario)
    _root_seed = int(_mcfg.get("seed", 0))
    _sizes = dict(_mcfg.get("request_size_bytes", {}))
    _avg_size = 0
    _vals = [int(_v) for _v in _sizes.values() if int(_v) > 0]
    if _vals:
        _avg_size = int(sum(_vals) / len(_vals))
    _specs = _build_specs(_cfg, _registry, _root_seed, _avg_size)

    # shared httpx client routes cross-service hops over real TCP (no ASGI)
    _client = httpx.AsyncClient(timeout=httpx.Timeout(10.0))
    _apps = _build_apps_for_local(_cfg, _registry, _specs,
                                  _local_names, _client)

    _threads: List[UvicornThread] = []
    try:
        for _label, _app, _port in _apps:
            _threads.append(_spawn_one_app(_label, _app, _port, _bind,
                                           _args.verbose))
        # wait for any remote services declared in registry; tolerant of
        # `composite-atomic` running solo when no driver is up yet
        if _dpl != "local" and _args.launcher_role != "all":
            _wait_remote_health(_registry, _local_names,
                                timeout_s=60.0,
                                verbose=_args.verbose)
        if _args.verbose:
            print("launch_services: mesh ready")
        asyncio.run(_serve_until_signal(_threads, _args.duration,
                                        _args.verbose))
    except KeyboardInterrupt:
        if _args.verbose:
            print("\n  SIGINT received")
    finally:
        if _args.verbose:
            print("  shutting down ...")
        for _t in _threads:
            _t.shutdown()
        # close httpx client; the asyncio loop is already done
        try:
            asyncio.run(_client.aclose())
        except RuntimeError:
            pass
        if _args.verbose:
            print("  done")
    return 0


if __name__ == "__main__":
    sys.exit(main())

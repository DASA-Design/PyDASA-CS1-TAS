# -*- coding: utf-8 -*-
"""Experiment-stage orchestrator.

`run_experiment` mounts the TAS mesh, drives one open-loop trial through the controller, and writes the per-request flow JSONL, per-pid CSV, `verdict.json`, `window.parquet`, and a `runs.parquet` summary row. The private helpers bridge `profile.specs` to the `MeshSpec` list and run the producer / consumer driver.

Re-exported from `src.methods.experimental` for back-compat.
"""

from __future__ import annotations

import asyncio
import functools
import time
from pathlib import Path
from typing import Any

import httpx

from src.experimental.common.io.parquet import append_run_summary
from src.experimental.common.io.runs import make_run_id, make_run_paths
from src.experimental.procedure.bounds import (
    BoundsReport,
    validate_experimental_limits,
)
from src.experimental.procedure.deployment import (
    PORT_STRIDE,
    Dpl,
    Framework,
    MeshSpec,
    WsgiServer,
    bring_up_mesh,
)
from src.experimental.prototype.client.users import User
from src.experimental.prototype.controller import (
    bring_up_controller,
    compute_verdict,
    extract_op_weights,
    load_controller_cfg,
    write_verdict_json,
    write_window_parquet,
)
from src.experimental.prototype.runtime.async_loop import run_async_safe
from src.experimental.prototype.runtime.config import load_experimental_cfg
from src.experimental.prototype.runtime.os_timer import windows_timer_resolution
from src.experimental.prototype.target.config import load_target_cfg
from src.experimental.prototype.target.factory.internal_stage import (
    build_internal_stage_fastapi_app,
    build_internal_stage_flask_app,
)
from src.experimental.prototype.target.factory.tas import (
    build_tas_fastapi_app,
    build_tas_flask_app,
)
from src.experimental.prototype.target.factory.third_party import (
    build_atomic_fastapi_app,
    build_atomic_flask_app,
)
from src.experimental.prototype.target.service.catalogue import (
    load_catalogue,
    load_failure_modes,
)
from src.io.config import load_profile, load_reference

# Internal-stage atomic ids spawned only when target_granularity='expanded'.
_INTERNAL_STAGE_IDS: tuple[str, ...] = (
    "TAS_{2}",
    "TAS_{3}",
    "TAS_{4}",
    "TAS_{5}",
    "TAS_{6}",
)


def _build_mesh_specs(*,
                      catalogue_version: str | None,
                      workflow_name: str,
                      host: str,
                      base_port: int,
                      atomic_admission: dict[str, Any],
                      flows_path: Path,
                      csv_dir: Path,
                      run_id: str,
                      request_timeout_s: float,
                      mu_lt: dict[str, float],
                      eps_lt: dict[str, float] | None = None,
                      failure_modes_cfg: Any = None,
                      target_granularity: str = "collapsed",
                      inject_internal_stage_mu: bool = False,
                      stage_routes: dict[str, dict[str, str]] | None = None,
                      admission_lt: dict[str, dict[str, int]] | None = None,
                      framework: Framework = "fastapi",
                      workers_lt: dict[str, int] | None = None,
                      tas_workers: int = 1,
                      ) -> tuple[list[MeshSpec], list[str], list[str]]:
    """Lay out the TAS mesh.

    Collapsed mode (default): TAS_1 composite + 7 third-party atomics on consecutive ports.
    Expanded mode: TAS_1 + 5 internal-stage atomics (TAS_{2..6}) + 7 third-party atomics. Internal stages slot between TAS_1 and the third-parties; the orchestrator threads `internal_url_lt` into the TAS_1 factory so its workflow engine can dispatch to them.

    Args:
        catalogue_version (str | None): version layer to load (None reads `_setpoint`).
        workflow_name (str): workflow stem to load. `tas` for collapsed, `tas_expanded` for expanded.
        host (str): bind address shared by every spawner.
        base_port (int): port for the composite TAS app.
        atomic_admission (dict[str, Any]): admission caps applied as the global default when `admission_lt` is None or missing a key (`{"k": ..., "c": ...}`).
        flows_path (Path): per-request JSONL output path.
        csv_dir (Path): per-pid CSV output directory.
        run_id (str): identifier written into every record.
        request_timeout_s (float): per-dispatch HTTP timeout.
        mu_lt (dict[str, float]): `svc_id -> mu` from the profile specs layer.
        eps_lt (dict[str, float] | None, optional): `svc_id -> epsilon` (per-call failure rate). Defaults to None (no injected failures).
        failure_modes_cfg (Any, optional): failure-mode config supplying each atomic's failure mechanism mix. Defaults to None.
        target_granularity (str, optional): `collapsed` (default) or `expanded`.
        inject_internal_stage_mu (bool, optional): when True (and expanded mode), TAS_{2..6} sleep on their published mu. Defaults to False.
        stage_routes (dict | None, optional): per-stage `calls_kind` + `operation` map (used in expanded mode). Required when `target_granularity="expanded"`.
        admission_lt (dict | None, optional): `{svc_id: {"c": int, "k": int}}` from `profile.specs`. When set, each atomic gets its per-svc cap; falls through to `atomic_admission` per-key when the profile is silent. Defaults to None (use the global `atomic_admission` for every atomic).
        framework (Framework, optional): server stack picking the FastAPI or Flask app factories. Defaults to `"fastapi"`.
        workers_lt (dict[str, int] | None, optional): per-svc `w_proc` from `profile.specs`; scales each atomic's `(c, K)`. Defaults to None (`w_proc = 1` everywhere).
        tas_workers (int, optional): number of TAS composite worker processes; `> 1` spreads request flows across processes for multi-core parallelism. Defaults to 1.

    Returns:
        tuple[list[MeshSpec], list[str], list[str]]: spec list + sorted third-party atomic ids + sorted internal-stage ids (empty list in collapsed mode).

    Raises:
        KeyError: when the profile does not declare a mu for some catalogue service.
        ValueError: when `target_granularity="expanded"` and `stage_routes` is None.
    """
    _catalogue = load_catalogue(catalogue_version)
    # Spawn only the catalogue entries the active profile declares (keyed by mu_lt).
    _atomic_ids = sorted(_id for _id in _catalogue.entries if _id in mu_lt)
    _is_expanded = target_granularity == "expanded"
    if _is_expanded and stage_routes is None:
        _msg = "stage_routes is required when target_granularity='expanded'"
        raise ValueError(_msg)

    # One process per atomic; w_proc scales (c, K) so deployed capacity matches the old multi-worker mesh.
    # Services bind on the PORT_STRIDE grid by spec index: TAS at index 0,
    # internal stages next (expanded only), then the third-party atomics.
    if _is_expanded:
        _first_atomic_idx = 1 + len(_INTERNAL_STAGE_IDS)
    else:
        _first_atomic_idx = 1

    _atomic_url_lt: dict[str, list[str]] = {}
    for _i, _svc_id in enumerate(_atomic_ids):
        _port = base_port + (_first_atomic_idx + _i) * PORT_STRIDE
        _atomic_url_lt[_svc_id] = [f"http://{host}:{_port}"]

    _internal_url_lt: dict[str, list[str]] | None = None
    if _is_expanded:
        _internal_url_lt = {}
        for _i, _stage_id in enumerate(_INTERNAL_STAGE_IDS):
            _port = base_port + (1 + _i) * PORT_STRIDE
            _internal_url_lt[_stage_id] = [f"http://{host}:{_port}"]

    if framework == "flask":
        _build_tas = build_tas_flask_app
        _build_atomic = build_atomic_flask_app
        _build_internal = build_internal_stage_flask_app
    else:
        _build_tas = build_tas_fastapi_app
        _build_atomic = build_atomic_fastapi_app
        _build_internal = build_internal_stage_fastapi_app
    _dflt_k = atomic_admission.get("k")
    _dflt_c = atomic_admission.get("c")

    _tas_factory = functools.partial(
        _build_tas,
        url_lt=_atomic_url_lt,
        catalogue_version=catalogue_version,
        workflow_name=workflow_name,
        flows_path=str(flows_path),
        run_id=run_id,
        timeout_s=request_timeout_s,
        internal_url_lt=_internal_url_lt,
    )
    _specs: list[MeshSpec] = [MeshSpec(svc_id="TAS",
                                       app_factory=_tas_factory,
                                       workers=max(1, tas_workers))]

    if _is_expanded:
        # Internal stages (TAS_{2..6}) come right after TAS_1 on consecutive ports.
        for _stage_id in _INTERNAL_STAGE_IDS:
            if _stage_id not in mu_lt:
                _msg = (f"profile specs layer is missing mu for internal stage {_stage_id!r}; "
                        "expanded mode requires TAS_{2..6} mu in the profile")
                raise KeyError(_msg)
            _route = (stage_routes or {}).get(_stage_id)
            if _route is None:
                _msg = f"stage_routes missing entry for {_stage_id!r}"
                raise ValueError(_msg)
            _stage_mu = mu_lt[_stage_id] if inject_internal_stage_mu else 0.0
            _stage_k, _stage_c = _effective_admission(_stage_id, admission_lt,
                                                      _dflt_k, _dflt_c, workers_lt)
            _stage_factory = functools.partial(
                _build_internal,
                svc_name=_stage_id,
                calls_kind=_route["calls_kind"],
                operation=_route["operation"],
                mu=_stage_mu,
                atomic_url_lt=_atomic_url_lt,
                catalogue_version=catalogue_version,
                k=_stage_k,
                c=_stage_c,
                csv_dir=str(csv_dir),
                run_id=run_id,
                request_timeout_s=request_timeout_s,
            )
            _specs.append(MeshSpec(svc_id=_stage_id,
                                   app_factory=_stage_factory,
                                   workers=1))

    for _svc_id in _atomic_ids:
        _entry = _catalogue.lookup(_svc_id)
        if eps_lt is None:
            _eps = 0.0
        else:
            _eps = float(eps_lt.get(_svc_id, 0.0))
        if failure_modes_cfg is None:
            _failure_mix = None
        else:
            _failure_mix = dict(failure_modes_cfg.mix_for(_svc_id))
        _svc_k, _svc_c = _effective_admission(_svc_id, admission_lt,
                                              _dflt_k, _dflt_c, workers_lt)
        _atomic_factory = functools.partial(
            _build_atomic,
            svc_name=_svc_id,
            kind=_entry.kind,
            mu=mu_lt[_svc_id],
            k=_svc_k,
            c=_svc_c,
            csv_dir=str(csv_dir),
            run_id=run_id,
            eps=_eps,
            failure_mix=_failure_mix,
        )
        _specs.append(MeshSpec(svc_id=_svc_id,
                               app_factory=_atomic_factory,
                               workers=1))
    if _is_expanded:
        _internal_stage_ids = list(_INTERNAL_STAGE_IDS)
    else:
        _internal_stage_ids = []
    return _specs, _atomic_ids, _internal_stage_ids


def _resolve_admission(svc_id: str,
                       admission_lt: dict[str, dict[str, int]] | None,
                       dflt_k: Any,
                       dflt_c: Any) -> tuple[int | None, int | None]:
    """Look up `(k, c)` for one svc; fall through to the global default.

    Args:
        svc_id (str): artifact id to resolve.
        admission_lt (dict | None): per-svc admission map from `profile.specs`.
        dflt_k (Any): `atomic_admission["k"]` from `target.json`.
        dflt_c (Any): `atomic_admission["c"]` from `target.json`.

    Returns:
        tuple[int | None, int | None]: `(k, c)` for this svc.
    """
    _k: int | None
    _c: int | None
    if admission_lt is not None and svc_id in admission_lt:
        _entry = admission_lt[svc_id]
        _k = int(_entry["k"])
        _c = int(_entry["c"])
    else:
        if dflt_k is None:
            _k = None
        else:
            _k = int(dflt_k)
        if dflt_c is None:
            _c = None
        else:
            _c = int(dflt_c)
    return _k, _c


def _w_proc(svc_id: str, workers_lt: dict[str, int] | None) -> int:
    """Return the worker-process multiplier (`w_proc`) for one service.

    Args:
        svc_id (str): artifact id to look up.
        workers_lt (dict[str, int] | None): per-svc `w_proc` from `profile.specs`; None means 1 everywhere.

    Returns:
        int: `w_proc` for this service, clamped to a minimum of 1.
    """
    if workers_lt is None:
        return 1
    return max(1, int(workers_lt.get(svc_id, 1)))


def _effective_admission(svc_id: str,
                         admission_lt: dict[str, dict[str, int]] | None,
                         dflt_k: Any,
                         dflt_c: Any,
                         workers_lt: dict[str, int] | None) -> tuple[int | None, int | None]:
    """Return aggregate `(K, c) = (K_specs, c_specs) * w_proc` for one service.

    One process per atomic exposes an effective M/M/c/K queue whose `c` and `K` are the per-spec values scaled by the worker-process count, so deployed capacity matches the old multi-worker mesh.

    Args:
        svc_id (str): artifact id to resolve.
        admission_lt (dict[str, dict[str, int]] | None): per-svc `{c, k}` from `profile.specs`.
        dflt_k (Any): global `atomic_admission["k"]` fallback.
        dflt_c (Any): global `atomic_admission["c"]` fallback.
        workers_lt (dict[str, int] | None): per-svc `w_proc`; None means 1.

    Returns:
        tuple[int | None, int | None]: aggregate `(K, c)`; an element is None when its base value is None.
    """
    _base_k, _base_c = _resolve_admission(svc_id, admission_lt, dflt_k, dflt_c)
    _w = _w_proc(svc_id, workers_lt)
    _agg_k = None if _base_k is None else int(_base_k) * _w
    _agg_c = None if _base_c is None else int(_base_c) * _w
    return _agg_k, _agg_c


def _thresholds_from_reference() -> dict[str, float]:
    """Read R1 / R2 numeric thresholds from `data/reference/baseline.json`.

    Returns:
        dict[str, float]: `{"r1_max": <float>, "r2_max": <float>}`.
    """
    _ref = load_reference("baseline")
    _reqs = _ref["requirements"]
    _ans: dict[str, float] = {
        "r1_max": float(_reqs["R1"]["threshold"]),
        "r2_max": float(_reqs["R2"]["threshold"]),
    }
    return _ans


def _op_weights_from_profile(adp: str,
                             stage_routes: dict[str, dict[str, str]]) -> dict[str, dict[str, float]]:
    """Extract per-operation routing weights from the active profile's `_routs[adp]`.

    The orchestrator threads these into the controller's one-shot `POST /config` so the picker (when `_routs`-aware) draws weighted-random over the right service set.

    Args:
        adp (str): adaptation key (selects which profile + scenario to load).
        stage_routes (dict[str, dict[str, str]]): `target.json::stage_routes`-shaped mapping. Drives which row of `_routs` becomes which operation's weights.

    Returns:
        dict[str, dict[str, float]]: `{operation: {svc_id: weight}}` with weights summing to 1 per operation.
    """
    _net = load_profile(adaptation=adp, source="artifacts")
    _node_ids = [_a.key for _a in _net.artifacts]
    _routs = {_net.scenario: _net.routing.tolist()}
    _ans = extract_op_weights(_routs, _node_ids, stage_routes, scenario=_net.scenario)
    return _ans


def _fetch_controller_history(controller_url: str,
                              timeout_s: float = 5.0) -> list[dict[str, Any]]:
    """Drain the controller's `/history` for the just-finished trial.

    Args:
        controller_url (str): controller base URL.
        timeout_s (float, optional): HTTP timeout. Defaults to 5.0.

    Returns:
        list[dict[str, Any]]: per-sample trajectory records. Empty on transport error.
    """
    _ans: list[dict[str, Any]] = []
    try:
        with httpx.Client(timeout=timeout_s) as _http:
            _resp = _http.get(f"{controller_url.rstrip('/')}/history")
        if _resp.status_code == 200:
            _records = _resp.json().get("records", [])
            if isinstance(_records, list):
                _ans = _records
    except httpx.RequestError:
        pass
    return _ans


_STOP_PREDICATES: dict[str, tuple[str, ...]] = {
    "baseline": ("r1_breach", "r2_breach"),
    "s1": ("r1_breach",),
    "s2": ("r2_breach",),
    "aggregate": ("r1_breach", "r2_breach"),
}

# Transport-level outcomes that signal the apparatus broke rather than the
# architecture failing. Mirrors `StopGuard._is_infra_failure`'s apparatus-vs-
# architecture split, minus 503: a full M/M/c/K admission queue is modelled
# architecture behaviour, not an apparatus fault. The per-consumer consecutive
# count in `_consume_payloads` is what separates a dead worker (an unbroken run)
# from interleaved injected-failure-mechanism hits (which never run long).
_INFRA_OUTCOMES: frozenset[str] = frozenset({"timeout", "drop"})
_DFLT_INFRA_THRESHOLD = 20


def _is_infra_outcome(outcome: str) -> bool:
    """Return True when `outcome` is a transport-level (apparatus) failure.

    Args:
        outcome (str): the `RequestRecord.outcome` label.

    Returns:
        bool: True for `timeout` / `drop`; False for `success` / `5xx`.
    """
    return outcome in _INFRA_OUTCOMES


def _should_stop_from_aggregates(adp: str, agg: dict[str, Any]) -> tuple[bool, str]:
    """Apply the strategy-specific breach predicate to one `/aggregates` response.

    Baseline + aggregate use OR semantics (either breach halts the trial — a single failed requirement is enough evidence). `s1` only watches R1 (its design objective is availability). `s2` only watches R2 (performance).

    Args:
        adp (str): adaptation key.
        agg (dict[str, Any]): payload returned by the controller's `GET /aggregates`.

    Returns:
        tuple[bool, str]: `(stop, reason)` where `reason` is `""` when not stopping. When both axes breach simultaneously, `reason` reports the first axis listed in the predicate.
    """
    _r1, _r2 = bool(agg.get("r1_breach", False)), bool(agg.get("r2_breach", False))
    _stop = False
    _reason = ""
    _checks = _STOP_PREDICATES.get(adp, ())
    if "r1_breach" in _checks and _r1:
        _stop, _reason = True, "r1_breach"
    elif "r2_breach" in _checks and _r2:
        _stop, _reason = True, "r2_breach"
    return _stop, _reason


def _eps_lt_from_profile(adp: str) -> dict[str, float]:
    """Read per-service epsilon (failure rate) from the active profile's specs layer.

    Args:
        adp (str): adaptation key (selects which profile + scenario to load).

    Returns:
        dict[str, float]: epsilon setpoint per artifact id.
    """
    _net = load_profile(adaptation=adp, source="specs")
    _ans: dict[str, float] = {}
    for _artifact in _net.artifacts:
        _ans[_artifact.key] = float(_artifact.epsilon)
    return _ans


def _mu_lt_from_profile(adp: str) -> dict[str, float]:
    """Read mu (service rate, req/s) per service from the active profile's specs layer.

    Args:
        adp (str): adaptation key (selects which profile + scenario to load).

    Returns:
        dict[str, float]: mu setpoint per artifact id.
    """
    _net = load_profile(adaptation=adp, source="specs")
    _ans: dict[str, float] = {}
    for _artifact in _net.artifacts:
        _ans[_artifact.key] = float(_artifact.mu)
    return _ans


def _resolve_granularity_for_paths(target_cfg: dict[str, Any],
                                   override: str | None) -> str:
    """Resolve the effective granularity for path / variant decisions.

    Args:
        target_cfg (dict[str, Any]): the on-disk `target.json` block.
        override (str | None): caller-supplied granularity override.

    Returns:
        str: `collapsed` or `expanded`.
    """
    if override is not None:
        return override
    return str(target_cfg.get("target_granularity", "collapsed"))


def _variant_suffix_for(*,
                        framework: Framework,
                        granularity: str) -> str:
    """Return the variant suffix for a `(framework, granularity)` pair.

    Every combination, canonical or not, gets an explicit `<framework>_<granularity>` suffix so the on-disk layout makes the experimental knobs visible at a glance (`baseline_fastapi_collapsed/` instead of bare `baseline/`).

    Args:
        framework (Framework): server stack.
        granularity (str): resolved granularity (`collapsed` or `expanded`).

    Returns:
        str: `<framework>_<granularity>`.
    """
    return f"{framework}_{granularity}"


def _build_mesh_admission(*,
                          atomic_ids: list[str],
                          admission_lt: dict[str, dict[str, int]],
                          mu_lt: dict[str, float],
                          eps_lt: dict[str, float],
                          atomic_admission: dict[str, Any],
                          internal_stage_ids: list[str] | None = None,
                          include_composite: bool = True,
                          workers_lt: dict[str, int] | None = None) -> dict[str, dict[str, Any]]:
    """Build the `{svc_id: {c, K, mu, eps}}` block echoed into `verdict.json::mesh`.

    Stage 9 (the yoly chart) reads this to verify the four methods used identical M/M/c/K parameters. Per-svc values come from `admission_lt` multiplied by `workers_lt[svc_id]` so the row reflects the apparatus's effective M/M/c/K (single process per atomic, aggregate handler slots = `c_specs * w_proc`, aggregate capacity = `K_specs * w_proc`). The global `atomic_admission` fills in for ids the profile is silent on; missing `workers_lt` entries default to 1.

    Args:
        atomic_ids (list[str]): third-party atomic ids actually spawned.
        admission_lt (dict): per-svc `{c, k}` from `profile.specs`.
        mu_lt (dict): per-svc `mu` from `profile.specs`.
        eps_lt (dict): per-svc `epsilon` from `profile.specs`.
        atomic_admission (dict): global default `{k, c}` from `target.json`.
        internal_stage_ids (list[str] | None, optional): internal-stage ids spawned in expanded mode (`TAS_{2..6}`). Each gets its own row. Defaults to None.
        include_composite (bool, optional): when True, prepend a `TAS_{1}` row with the composite's `(c, K, mu, eps)` from `profile.specs`. Defaults to True.
        workers_lt (dict | None, optional): per-svc `w_proc` from `profile.specs`. When set, the rows report aggregate `(c * w_proc, K * w_proc)`. Defaults to None (rows report base `(c, K)`).

    Returns:
        dict[str, dict[str, Any]]: rows for the composite (when included), every internal stage, and every third-party atomic. Keys preserve the natural mesh order: TAS_{1}, TAS_{2..6}, atomics sorted.
    """
    _dflt_k = atomic_admission.get("k")
    _dflt_c = atomic_admission.get("c")
    _ans: dict[str, dict[str, Any]] = {}
    _composite_id = "TAS_{1}"
    if include_composite and _composite_id in mu_lt:
        _k, _c = _effective_admission(_composite_id, admission_lt,
                                      _dflt_k, _dflt_c, workers_lt)
        _ans[_composite_id] = {
            "c": _c,
            "K": _k,
            "mu": float(mu_lt.get(_composite_id, 0.0)),
            "eps": float(eps_lt.get(_composite_id, 0.0)),
        }
    if internal_stage_ids:
        for _stage_id in internal_stage_ids:
            if _stage_id not in mu_lt:
                continue
            _k, _c = _effective_admission(_stage_id, admission_lt,
                                          _dflt_k, _dflt_c, workers_lt)
            _ans[_stage_id] = {
                "c": _c,
                "K": _k,
                "mu": float(mu_lt.get(_stage_id, 0.0)),
                "eps": float(eps_lt.get(_stage_id, 0.0)),
            }
    for _svc_id in atomic_ids:
        _k, _c = _effective_admission(_svc_id, admission_lt,
                                      _dflt_k, _dflt_c, workers_lt)
        _ans[_svc_id] = {
            "c": _c,
            "K": _k,
            "mu": float(mu_lt.get(_svc_id, 0.0)),
            "eps": float(eps_lt.get(_svc_id, 0.0)),
        }
    return _ans


def _workers_lt_from_profile(adp: str) -> dict[str, int]:
    """Read per-service worker counts (`w_proc`) from the active profile's specs layer.

    Args:
        adp (str): adaptation key (selects which profile + scenario to load).

    Returns:
        dict[str, int]: worker-process count per artifact id. Defaults to 1 when the spec is silent.
    """
    _net = load_profile(adaptation=adp, source="specs")
    _ans: dict[str, int] = {}
    for _artifact in _net.artifacts:
        try:
            _ans[_artifact.key] = max(1, int(_artifact.w_proc))
        except KeyError:
            _ans[_artifact.key] = 1
    return _ans


def _admission_lt_from_profile(adp: str) -> dict[str, dict[str, int]]:
    """Read per-service (c, K) from the active profile's specs layer.

    Parallels `_mu_lt_from_profile` / `_eps_lt_from_profile`. Stage 9 (the yoly chart) needs every method to compute over the same M/M/c/K parameters; this lift surfaces them so the experimental mesh runs over the same `(c, K)` analytic / dim / stoch use.

    Args:
        adp (str): adaptation key (selects which profile + scenario to load).

    Returns:
        dict[str, dict[str, int]]: `{svc_id: {"c": <int>, "k": <int>}}` per artifact id.
    """
    _net = load_profile(adaptation=adp, source="specs")
    _ans: dict[str, dict[str, int]] = {}
    for _artifact in _net.artifacts:
        _ans[_artifact.key] = {"c": int(_artifact.c), "k": int(_artifact.K)}
    return _ans


async def _drive_trial(*,
                       tas_urls: list[str],
                       n_requests: int,
                       request_rate_per_s: float,
                       p_alarm: float,
                       request_timeout_s: float,
                       seed: int | None,
                       controller_url: str | None = None,
                       adp: str = "baseline",
                       poll_every_n: int = 0,
                       consumer_pool_size: int = 64,
                       max_queue_depth: int = 1000,
                       drain_timeout_s: float = 60.0,
                       infra_threshold: int = _DFLT_INFRA_THRESHOLD) -> tuple[list[dict[str, Any]], str]:
    """Drive `n_requests` against the composite TAS via an open-loop producer / consumer.

    Decouples *offered load* from *consumed throughput*: one **dispatcher** coroutine pushes ticks onto an `asyncio.Queue` at the configured `request_rate_per_s` regardless of how fast the server replies, and `consumer_pool_size` **consumer** coroutines drain the queue, each running its own `User` instance + `httpx.AsyncClient` against one of the `tas_urls` (round-robin assignment). Each consumer handles at most one in-flight request at a time, so the in-flight ceiling is exactly `consumer_pool_size` — pick it below httpx's `max_connections = 100` default and the transport never throttles.

    When the server saturates, the queue grows; once it hits `max_queue_depth` the dispatcher blocks at `queue.put()`, so the apparatus's offered-rate undershoot becomes visible in `verdict.operational.X_0_req_per_s` rather than being hidden by closed-loop self-pacing.

    Args:
        tas_urls (list[str]): one or more TAS_{1} base URLs (one per worker).
        n_requests (int): total dispatch budget.
        request_rate_per_s (float): offered rate. 0 = no pacing (flood).
        p_alarm (float): probability the next request is an alarm.
        request_timeout_s (float): per-request timeout.
        seed (int | None): RNG seed for kind selection (offset per consumer so each draws a distinct stream).
        controller_url (str | None, optional): controller base URL for breach polling. Defaults to None.
        adp (str, optional): adaptation key (drives the stop predicate). Defaults to `"baseline"`.
        poll_every_n (int, optional): dispatch count between breach polls (0 disables). Defaults to 0.
        consumer_pool_size (int, optional): number of concurrent consumer coroutines (= in-flight ceiling). Defaults to 64.
        max_queue_depth (int, optional): bounded queue size; dispatcher blocks when full. Defaults to 1000.
        drain_timeout_s (float, optional): max seconds to wait for in-flight consumers to finish after the dispatcher exits. Defaults to 60.0.
        infra_threshold (int, optional): consecutive transport-level failures on a single consumer that trip the `infra_failure` stop (the apparatus broke; the run's R1 / R2 numbers are not a verdict on the architecture). Defaults to 20.

    Returns:
        tuple[list[dict[str, Any]], str]: per-request summaries + stop_reason (`"n_reached"` / `"r1_breach"` / `"r2_breach"` / `"infra_failure"`).
    """
    if not tas_urls:
        _msg = "_drive_trial requires at least one TAS URL"
        raise ValueError(_msg)
    _pool = max(1, consumer_pool_size)
    _queue: asyncio.Queue[int | None] = asyncio.Queue(maxsize=max(1, max_queue_depth))
    _summaries: list[dict[str, Any]] = []
    _summaries_lock = asyncio.Lock()
    _stop_event = asyncio.Event()
    _stop_reason_box: list[str] = ["n_reached"]
    _breach_http: httpx.AsyncClient | None = None
    if controller_url is not None and poll_every_n > 0:
        _breach_http = httpx.AsyncClient(timeout=2.0)
    try:
        _consumers = []
        for _ci in range(_pool):
            _url = tas_urls[_ci % len(tas_urls)]
            _consumer_seed: int | None
            if seed is None:
                _consumer_seed = None
            else:
                _consumer_seed = seed + _ci
            _consumers.append(asyncio.create_task(_consume_payloads(
                consumer_id=_ci,
                base_url=_url,
                queue=_queue,
                summaries=_summaries,
                summaries_lock=_summaries_lock,
                stop_event=_stop_event,
                stop_reason_box=_stop_reason_box,
                infra_threshold=infra_threshold,
                p_alarm=p_alarm,
                request_timeout_s=request_timeout_s,
                seed=_consumer_seed,
            )))
        await _dispatch_at_rate(
            queue=_queue,
            n_requests=n_requests,
            rate=request_rate_per_s,
            stop_event=_stop_event,
            stop_reason_box=_stop_reason_box,
            breach_http=_breach_http,
            controller_url=controller_url,
            adp=adp,
            poll_every_n=poll_every_n,
        )
        # Signal each consumer to exit (one sentinel per slot).
        for _ in range(_pool):
            await _queue.put(None)
        try:
            await asyncio.wait_for(asyncio.gather(*_consumers, return_exceptions=True),
                                   timeout=drain_timeout_s)
        except asyncio.TimeoutError:
            for _c in _consumers:
                if not _c.done():
                    _c.cancel()
            await asyncio.gather(*_consumers, return_exceptions=True)
    finally:
        if _breach_http is not None:
            await _breach_http.aclose()
    return _summaries, _stop_reason_box[0]


async def _dispatch_at_rate(*,
                            queue: asyncio.Queue[int | None],
                            n_requests: int,
                            rate: float,
                            stop_event: asyncio.Event,
                            stop_reason_box: list[str],
                            breach_http: httpx.AsyncClient | None,
                            controller_url: str | None,
                            adp: str,
                            poll_every_n: int) -> None:
    """Push `n_requests` ticks onto `queue` at a fixed `rate`, then return.

    Pacing uses absolute targets (`start + i / rate`) so Windows' coarse `asyncio.sleep` granularity does not accumulate drift. Blocking at a full `queue.put()` surfaces consumer back-pressure as an offered-rate undershoot.

    Args:
        queue (asyncio.Queue[int | None]): tick queue the consumer pool drains.
        n_requests (int): total dispatch budget.
        rate (float): offered rate in req/s; 0 floods with no pacing.
        stop_event (asyncio.Event): set to halt dispatch early.
        stop_reason_box (list[str]): single-slot box a breach writes its reason into.
        breach_http (httpx.AsyncClient | None): client for breach polling; None disables it.
        controller_url (str | None): controller base URL for breach polling.
        adp (str): adaptation key (drives the stop predicate).
        poll_every_n (int): dispatch count between breach polls; 0 disables polling.
    """
    if rate > 0:
        _start = asyncio.get_event_loop().time()
    else:
        _start = 0.0
    for _i in range(n_requests):
        if stop_event.is_set():
            break
        await queue.put(_i)
        if rate > 0:
            _target = _start + (_i + 1) / rate
            _now = asyncio.get_event_loop().time()
            if _target > _now:
                await asyncio.sleep(_target - _now)
        if breach_http is not None and poll_every_n > 0 and ((_i + 1) % poll_every_n == 0):
            _stop, _reason = await _check_breach(breach_http,
                                                 controller_url or "",
                                                 adp)
            if _stop:
                stop_reason_box[0] = _reason
                stop_event.set()
                break


async def _consume_payloads(*,
                            consumer_id: int,
                            base_url: str,
                            queue: asyncio.Queue[int | None],
                            summaries: list[dict[str, Any]],
                            summaries_lock: asyncio.Lock,
                            stop_event: asyncio.Event,
                            p_alarm: float,
                            request_timeout_s: float,
                            seed: int | None,
                            stop_reason_box: list[str] | None = None,
                            infra_threshold: int = _DFLT_INFRA_THRESHOLD) -> None:
    """Drain `queue` and fire one request per tick; append the per-request summary under a lock.

    Each consumer owns its own `User` + `httpx.AsyncClient` so the per-consumer pool is isolated; the consumer holds at most one in-flight request at a time, so the trial's in-flight ceiling equals `consumer_pool_size`. Exits on a `None` sentinel (clean shutdown) or when `stop_event` is set (breach or infra early-stop).

    The consumer keeps a private consecutive-infra counter: each transport-level outcome (`timeout` / `drop`) or escaped exception increments it, any clean outcome resets it. A dead worker produces an unbroken run of failures on the one consumer pinned to it, so reaching `infra_threshold` consecutive failures trips the `infra_failure` stop; interleaved injected-failure-mechanism hits never run long enough to reach it.

    Args:
        consumer_id (int): index of this consumer in the pool.
        base_url (str): the TAS_{1} URL this consumer drives.
        queue (asyncio.Queue[int | None]): tick queue; `None` is the shutdown sentinel.
        summaries (list[dict[str, Any]]): shared per-request summary list.
        summaries_lock (asyncio.Lock): guards appends to `summaries`.
        stop_event (asyncio.Event): set to halt every consumer + the dispatcher.
        p_alarm (float): probability the next request is an alarm.
        request_timeout_s (float): per-request timeout.
        seed (int | None): RNG seed for kind selection.
        stop_reason_box (list[str] | None, optional): single-slot box the infra stop writes `"infra_failure"` into. None disables reason recording (the stop still fires). Defaults to None.
        infra_threshold (int, optional): consecutive transport-level failures that trip the infra stop. Defaults to 20.
    """
    _consec_infra = 0
    async with User(client_id=f"trial-c{consumer_id}",
                    base_url=base_url,
                    endpoint_path="/",
                    seed=seed,
                    p_alarm=p_alarm,
                    timeout_s=request_timeout_s,
                    sequential_req_ids=True) as _user:
        while True:
            _tick = await queue.get()
            try:
                if _tick is None or stop_event.is_set():
                    break
                _infra_hit = False
                try:
                    _record = await _user.run_one()
                except Exception:
                    # An exception escaping run_one is an unexpected apparatus fault.
                    _infra_hit = True
                else:
                    if _is_infra_outcome(_record.outcome):
                        _infra_hit = True
                    async with summaries_lock:
                        summaries.append({
                            "req_id": _record.req_id,
                            "kind": _record.kind,
                            "outcome": _record.outcome,
                            "status": _record.status_code,
                            "latency_s": _record.total_latency_s,
                        })
                if _infra_hit:
                    _consec_infra += 1
                else:
                    _consec_infra = 0
                if _consec_infra >= infra_threshold and not stop_event.is_set():
                    if stop_reason_box is not None:
                        stop_reason_box[0] = "infra_failure"
                    stop_event.set()
            finally:
                queue.task_done()


async def _check_breach(http: httpx.AsyncClient,
                        controller_url: str,
                        adp: str) -> tuple[bool, str]:
    """Poll the controller's `/aggregates` and apply the strategy-specific stop predicate.

    Args:
        http (httpx.AsyncClient): shared async client.
        controller_url (str): controller base URL.
        adp (str): adaptation key.

    Returns:
        tuple[bool, str]: `(stop, reason)`. Transport errors return `(False, "")` so a flaky controller doesn't cut the trial short.
    """
    _ans: tuple[bool, str] = (False, "")
    try:
        _resp = await http.get(f"{controller_url.rstrip('/')}/aggregates")
    except Exception:
        return _ans
    if _resp.status_code != 200:
        return _ans
    try:
        _agg = _resp.json()
    except ValueError:
        return _ans
    _ans = _should_stop_from_aggregates(adp, _agg)
    return _ans


def run_experiment(*,
                   adp: str = "baseline",
                   dpl: Dpl = "localhost",
                   framework: Framework = "fastapi",
                   wsgi_server: WsgiServer = "waitress",
                   write: bool = True,
                   run_id: str | None = None,
                   target_cfg: dict[str, Any] | None = None,
                   skip_bounds_check: bool = False,
                   target_granularity: str | None = None,
                   inject_internal_stage_mu: bool | None = None,
                   tas_workers: int | None = None) -> dict[str, Any]:
    """Mount the TAS topology, drive one trial, write the per-request + per-service logs.

    Reads `target.json` for bindings, validates the planned operating point against the `experimental.json::trial` ceiling (unless skipped), brings the mesh up, drives `trial.n_requests` requests through one synthetic user, and appends a row to `runs.parquet`.

    Args:
        adp (str, optional): adaptation key (`baseline` / `s1` / `s2` / `aggregate`). Defaults to `"baseline"`.
        dpl (Dpl, optional): deployment mode. Defaults to `"localhost"`.
        framework (Framework, optional): server stack. Defaults to `"fastapi"`.
        wsgi_server (WsgiServer, optional): WSGI engine when `framework="flask"`. Defaults to `"waitress"`.
        write (bool, optional): persist outputs to disk. Defaults to True.
        run_id (str | None, optional): explicit run id. Defaults to a fresh `<adp>_<ts>_<nonce>` id.
        target_cfg (dict[str, Any] | None, optional): pre-loaded target config. Defaults to reading the on-disk JSON.
        skip_bounds_check (bool, optional): skip the ceiling check. Defaults to False.
        target_granularity (str | None, optional): `collapsed` or `expanded`. Overrides `target.json::target_granularity` when set; falls through to the JSON value when None.
        inject_internal_stage_mu (bool | None, optional): when True (and expanded), TAS_{2..6} sleep on mu. Overrides `target.json::inject_internal_stage_mu` when set; falls through to the JSON value when None.
        tas_workers (int | None, optional): number of TAS composite worker processes. Overrides `target.json::tas_workers` when set; falls through to the JSON value when None.

    Returns:
        dict[str, Any]: run summary (`run_id`, `adp`, `dpl`, `n_requests`, `outcome_counts`, `paths`, `bounds`, `target_granularity`).
    """
    if target_cfg is None:
        _cfg = load_target_cfg()
    else:
        _cfg = target_cfg
    _exp_cfg = load_experimental_cfg()
    _ctrl_cfg_full = load_controller_cfg()
    if run_id is None:
        _run_id = make_run_id(prefix=adp)
    else:
        _run_id = run_id

    _resolved_granularity = _resolve_granularity_for_paths(_cfg, target_granularity)
    _variant_suffix = _variant_suffix_for(framework=framework,
                                          granularity=_resolved_granularity)
    _paths = make_run_paths(adp=adp,
                            run_id=_run_id,
                            variant_suffix=_variant_suffix)
    _paths.ensure()

    _bounds_report = _maybe_check_bounds(trial_cfg=_exp_cfg["trial"],
                                         atomic_admission=_cfg["atomic_admission"],
                                         skip=skip_bounds_check)

    _mu_lt = _mu_lt_from_profile(adp)
    _eps_lt = _eps_lt_from_profile(adp)
    _admission_lt = _admission_lt_from_profile(adp)
    _workers_lt = _workers_lt_from_profile(adp)
    _failure_modes_cfg = load_failure_modes()

    _granularity = _resolved_granularity
    if inject_internal_stage_mu is not None:
        _inject_mu = inject_internal_stage_mu
    else:
        _inject_mu = bool(_cfg.get("inject_internal_stage_mu", False))

    if tas_workers is not None:
        _tas_workers = max(1, tas_workers)
    else:
        _tas_workers = max(1, int(_cfg.get("tas_workers", 1)))

    # Pick the workflow file matching the chosen mode.
    _workflows_map = _cfg.get("workflows")
    if isinstance(_workflows_map, dict) and _granularity in _workflows_map:
        _workflow_name = str(_workflows_map[_granularity])
    else:
        # Backwards compat: legacy `workflow_name` field.
        _workflow_name = str(_cfg.get("workflow_name", "tas"))

    _stage_routes = _cfg.get("stage_routes") if _granularity == "expanded" else None

    _specs, _atomic_ids, _internal_stage_ids = _build_mesh_specs(
        catalogue_version=_cfg.get("catalogue_version"),
        workflow_name=_workflow_name,
        host=_cfg["host"],
        base_port=int(_cfg["tas_base_port"]),
        atomic_admission=_cfg["atomic_admission"],
        flows_path=_paths.flows,
        csv_dir=_paths.csv_dir,
        run_id=_run_id,
        request_timeout_s=float(_cfg["request_timeout_s"]),
        mu_lt=_mu_lt,
        eps_lt=_eps_lt,
        failure_modes_cfg=_failure_modes_cfg,
        target_granularity=_granularity,
        inject_internal_stage_mu=_inject_mu,
        stage_routes=_stage_routes,
        admission_lt=_admission_lt,
        framework=framework,
        workers_lt=_workers_lt,
        tas_workers=_tas_workers,
    )
    _mesh_admission = _build_mesh_admission(atomic_ids=_atomic_ids,
                                            admission_lt=_admission_lt,
                                            mu_lt=_mu_lt,
                                            eps_lt=_eps_lt,
                                            atomic_admission=_cfg["atomic_admission"],
                                            internal_stage_ids=_internal_stage_ids,
                                            include_composite=True,
                                            workers_lt=_workers_lt)

    _trial = _exp_cfg["trial"]
    _kind_p = _trial["kind_probability"]
    _ctrl_cfg = _ctrl_cfg_full
    _strat_cfg = _ctrl_cfg_full.get("strategies", {})
    _thresholds = _thresholds_from_reference()
    _stage_routes_for_weights = _cfg.get("stage_routes") or {}
    _op_weights = _op_weights_from_profile(adp, _stage_routes_for_weights)
    _window_size = int(_strat_cfg.get("window_size", 100))
    _warmup_n = int(_ctrl_cfg.get("warmup_n", 100))
    _max_attempts = int(_strat_cfg.get("max_attempts", 3))
    _poll_interval_ms = int(_ctrl_cfg.get("poll_interval_ms", 100))
    _ctrl_port = int(_ctrl_cfg.get("port", 9001))
    _ctrl_ready_timeout_s = float(_ctrl_cfg.get("ready_timeout_s", 5.0))
    _r1_r2_stop_enabled = bool(_ctrl_cfg.get("r1_r2_stop_enabled", True))
    _poll_every_n_raw = int(_ctrl_cfg.get("orchestrator_poll_every_n", 10))
    if _r1_r2_stop_enabled:
        _poll_every_n = _poll_every_n_raw
    else:
        _poll_every_n = 0

    _summaries: list[dict[str, Any]] = []
    _stop_reason = "n_reached"
    _history: list[dict[str, Any]] = []
    _started_ts = time.time()
    with bring_up_mesh(_specs,
                       framework=framework,
                       wsgi_server=wsgi_server,
                       host=_cfg["host"],
                       base_port=int(_cfg["tas_base_port"]),
                       ready_timeout_s=float(_cfg["ready_timeout_s"])) as _urls:
        _tas_urls: list[str] = _urls["TAS"]
        # Controller polls only worker 0's /samples; the verdict reads the shared flow JSONL.
        _ctrl_target = _tas_urls[0]
        with bring_up_controller(target_url=_ctrl_target,
                                 adp=adp,
                                 op_weights=_op_weights,
                                 thresholds=_thresholds,
                                 window_size=_window_size,
                                 warmup_n=_warmup_n,
                                 max_attempts=_max_attempts,
                                 poll_interval_ms=_poll_interval_ms,
                                 port=_ctrl_port,
                                 host=_cfg["host"],
                                 ready_timeout_s=_ctrl_ready_timeout_s,
                                 framework=framework) as _ctrl_url:
            with windows_timer_resolution(1):
                _summaries, _stop_reason = run_async_safe(lambda: _drive_trial(
                    tas_urls=_tas_urls,
                    n_requests=int(_trial["n_requests"]),
                    request_rate_per_s=float(_trial["request_rate_per_s"]),
                    p_alarm=float(_kind_p["alarm"]),
                    request_timeout_s=float(_cfg["request_timeout_s"]),
                    seed=_trial.get("seed"),
                    controller_url=_ctrl_url,
                    adp=adp,
                    poll_every_n=_poll_every_n,
                    consumer_pool_size=int(_trial.get("consumer_pool_size", 64)),
                    max_queue_depth=int(_trial.get("max_queue_depth", 1000)),
                    drain_timeout_s=float(_trial.get("drain_timeout_s", 60.0)),
                    infra_threshold=int(_trial.get("infra_consecutive_threshold",
                                                   _DFLT_INFRA_THRESHOLD)),
                ))
            _history = _fetch_controller_history(_ctrl_url)
    _finished_ts = time.time()

    _outcome_counts = _count_outcomes(_summaries)
    _verdict = compute_verdict(flows_path=_paths.flows,
                               adp=adp,
                               run_id=_run_id,
                               stop_reason=_stop_reason,
                               n_planned=int(_trial["n_requests"]),
                               thresholds=_thresholds,
                               client_n_requests=len(_summaries),
                               mesh_admission=_mesh_admission)
    if write:
        write_verdict_json(_verdict, _paths.verdict_json)
        if _history:
            write_window_parquet(_history, _paths.window_parquet)
    _row: dict[str, Any] = {
        "run_id": _run_id,
        "adp": adp,
        "dpl": dpl,
        "framework": framework,
        "target_granularity": _granularity,
        "inject_internal_stage_mu": _inject_mu,
        "tas_workers": _tas_workers,
        "n_requests": len(_summaries),
        "n_success": _outcome_counts.get("success", 0),
        "n_timeout": _outcome_counts.get("timeout", 0),
        "n_drop": _outcome_counts.get("drop", 0),
        "n_5xx": _outcome_counts.get("5xx", 0),
        "stop_reason": _stop_reason,
        "started_ts": _started_ts,
        "finished_ts": _finished_ts,
        "bounds_passed": _bounds_report.passed if _bounds_report else None,
    }
    if write:
        append_run_summary(_paths.runs_parquet, _row)

    _ans: dict[str, Any] = {
        "run_id": _run_id,
        "adp": adp,
        "dpl": dpl,
        "framework": framework,
        "target_granularity": _granularity,
        "inject_internal_stage_mu": _inject_mu,
        "tas_workers": _tas_workers,
        "n_requests": len(_summaries),
        "outcome_counts": _outcome_counts,
        "atomic_ids": _atomic_ids,
        "internal_stage_ids": _internal_stage_ids,
        "observable_svc_ids": ["TAS_{1}"] + _internal_stage_ids + _atomic_ids,
        "paths": {
            "flows": str(_paths.flows),
            "csv_dir": str(_paths.csv_dir),
            "runs_parquet": str(_paths.runs_parquet),
            "verdict_json": str(_paths.verdict_json),
            "window_parquet": str(_paths.window_parquet),
        },
        "bounds": _bounds_report,
        "summaries": _summaries,
        "verdict": _verdict,
        "stop_reason": _stop_reason,
    }
    return _ans


def _maybe_check_bounds(*,
                        trial_cfg: dict[str, Any],
                        atomic_admission: dict[str, Any],
                        skip: bool) -> BoundsReport | None:
    """Check the planned `(c, r, w)` against the `experimental.json::trial` ceiling.

    The ceiling (`r_max` / `c_max` / `w_max`) is read straight from `trial_cfg`, so the experiment is self-contained: no calibration-envelope file is consulted. A null axis in the config is unbounded (that axis is skipped).

    Args:
        trial_cfg (dict[str, Any]): `trial` block from `experimental.json` (carries `request_rate_per_s` and the `r_max` / `c_max` / `w_max` ceiling).
        atomic_admission (dict[str, Any]): admission caps from `target.json` (supplies the planned `c`).
        skip (bool): if True, return None without checking.

    Returns:
        BoundsReport | None: per-axis verdicts, or None when the check was skipped.
    """
    if skip:
        return None
    _limits: dict[str, Any] = {
        "c_max": trial_cfg.get("c_max"),
        "r_max": trial_cfg.get("r_max"),
        "w_max": trial_cfg.get("w_max"),
    }
    _exp_cfg: dict[str, Any] = {
        "r": float(trial_cfg.get("request_rate_per_s", 0)),
    }
    _c = atomic_admission.get("c")
    if isinstance(_c, (int, float)):
        _exp_cfg["c"] = float(_c)
    return validate_experimental_limits(_exp_cfg, _limits, raise_on_fail=True)


def _count_outcomes(summaries: list[dict[str, Any]]) -> dict[str, int]:
    """Tally `outcome` values across the per-request summaries.

    Args:
        summaries (list[dict[str, Any]]): per-request summary dicts from `_drive_trial`.

    Returns:
        dict[str, int]: count of each distinct `outcome` label.
    """
    _counts: dict[str, int] = {}
    for _row in summaries:
        _key = str(_row.get("outcome", "?"))
        _counts[_key] = _counts.get(_key, 0) + 1
    return _counts

# -*- coding: utf-8 -*-
"""Experimental method orchestrator.

Two things to run, one CLI:

- `run_calibration` measures the host floor and writes a calibration envelope.
- `run_experiment` mounts the TAS service mesh, drives a trial, writes the per-request flow + per-service CSV + summary row.

`run(stage=...)` picks one or both. CLI::

    python -m src.methods.experimental --stage calibration --dpl localhost
    python -m src.methods.experimental --stage experiment --adaptation baseline --dpl multiprocess
"""

from __future__ import annotations

import argparse
import asyncio
import functools
import time
from pathlib import Path
from typing import Any, cast

from src.experimental.common.io.parquet import append_run_summary
from src.experimental.common.io.runs import make_run_id, make_run_paths
from src.experimental.procedure.bounds import (
    BoundsReport,
    validate_experimental_limits,
)
from src.io.config import load_profile
from src.experimental.procedure.deployment import (
    Dpl,
    Framework,
    MeshSpec,
    WsgiServer,
    bring_up,
    bring_up_mesh,
)
from src.experimental.prototype.calibration import (
    envelope_path,
    load_calibration_cfg,
    make_envelope,
    make_multi_proc_driver,
    probe_handler_scaling,
    probe_jitter,
    probe_loopback,
    probe_rate,
    probe_timer,
    probe_workers_scaling,
    stamp_gate,
    write_envelope,
)
from src.experimental.prototype.calibration.envelope import (
    DFLT_RESULTS_BASE as _CALIBRATION_RESULTS_BASE,
    read_envelope,
)
from src.experimental.prototype.calibration.vernier import (
    build_vernier_fastapi_app,
    build_vernier_flask_app,
)
from src.experimental.prototype.client.users import User
from src.experimental.prototype.controller import (
    bring_up_controller,
    compute_verdict,
    extract_op_weights,
    write_verdict_json,
    write_window_parquet,
)
from src.experimental.prototype.runtime.async_loop import run_async_safe
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
from src.io.config import load_reference


def run_calibration(*,
                    dpl: Dpl = "localhost",
                    framework: Framework = "fastapi",
                    wsgi_server: WsgiServer = "waitress",
                    write: bool = True,
                    run_id: str | None = None,
                    cfg: dict[str, Any] | None = None) -> dict[str, Any]:
    """Measure the host floor and return a calibration envelope.

    Runs the four host-floor probes, brings up the vernier, drives the rate sweep, stamps the gate verdict, and (optionally) writes the envelope to `data/results/calibration/<dpl>/`.

    Args:
        dpl (Dpl, optional): deployment mode. Defaults to `"localhost"`.
        framework (Framework, optional): server stack. Defaults to `"fastapi"`.
        wsgi_server (WsgiServer, optional): WSGI engine when `framework="flask"`. Defaults to `"waitress"`.
        write (bool, optional): persist the envelope to disk. Defaults to True.
        run_id (str | None, optional): explicit run id. Defaults to a fresh `calib_<ts>_<nonce>` id.
        cfg (dict[str, Any] | None, optional): pre-loaded calibration config. Defaults to reading the on-disk JSON.

    Returns:
        dict[str, Any]: the populated envelope.
    """
    if cfg is None:
        _cfg = load_calibration_cfg()
    else:
        _cfg = cfg
    _vernier_cfg = _cfg.get("vernier", {})
    _hs_cfg = _cfg.get("hoststats", {})
    _rate_cfg = _cfg.get("rate", {})
    _ws_cfg_raw = _cfg.get("workers_scaling", {})
    _gate_cfg = _cfg.get("gate", {})
    _dpl_cfg = _cfg.get("dpl", {})
    _k = _vernier_cfg.get("K")
    _c = _vernier_cfg.get("c")

    if run_id is None:
        _run_id = make_run_id(prefix="calib")
    else:
        _run_id = run_id

    # functools.partial keeps the factory zero-arg + picklable across mp.spawn.
    if framework == "flask":
        _wsgi: str | None = wsgi_server
        _app_factory: Any = functools.partial(build_vernier_flask_app,
                                              k=_k,
                                              c=_c)
    else:
        _wsgi = None
        _app_factory = functools.partial(build_vernier_fastapi_app,
                                         k=_k,
                                         c=_c)

    _envelope = make_envelope(run_id=_run_id,
                              dpl=dpl,
                              framework=framework,
                              wsgi_server=_wsgi)

    # 1. Host-floor probes (apparatus-independent); kwargs threaded from JSON.
    # `handler_scaling` only runs on localhost (per-handler concurrency is mode-independent;
    # rerunning it on multiprocess wastes time without adding information).
    _envelope["timer"] = probe_timer(**_hs_cfg.get("timer", {}))
    _envelope["jitter"] = probe_jitter(**_hs_cfg.get("jitter", {}))
    _envelope["loopback"] = probe_loopback(**_hs_cfg.get("loopback", {}))
    if dpl == "localhost":
        _envelope["handler_scaling"] = probe_handler_scaling(**_hs_cfg.get("handler_scaling", {}))

    # 2a. Per-worker rate saturation: probe_rate always runs at workers=1 so
    # its result is the per-worker saturation curve (independent of the parallel
    # axis explored separately by probe_workers_scaling).
    _dpl_cfg_rate = dict(_dpl_cfg)
    _dpl_cfg_rate["workers"] = 1
    with bring_up(dpl,
                  app_factory=_app_factory,
                  framework=framework,
                  wsgi_server=wsgi_server,
                  **_dpl_cfg_rate) as _urls:
        _target_urls = [f"{_url}/" for _url in _urls]
        _envelope["rate"] = probe_rate(target_urls=_target_urls, **_rate_cfg)

    # 2b. Parallel-limit calibration; multiprocess only.
    if dpl == "multiprocess":
        _envelope["workers_scaling"] = _run_workers_scaling(
            ws_cfg=_ws_cfg_raw,
            saturation_rate=_envelope["rate"].get("saturation_rate"),
            dpl=dpl,
            app_factory=_app_factory,
            framework=framework,
            wsgi_server=wsgi_server,
            dpl_cfg=_dpl_cfg)

    # 3. Gate verdict + close-out.
    stamp_gate(_envelope, **_gate_cfg)
    _envelope["finished_ts"] = time.time()

    if write:
        _path = envelope_path(dpl=dpl,
                              host=_envelope["host"],
                              run_id=_run_id)
        write_envelope(_path, _envelope)

    return _envelope


class _BringUpFactory:
    """Adapter that lets the workers ramp ask for `n` target URLs without knowing how the mesh is brought up.

    Pre-bind the deployment knobs once; calling the instance with `n_workers` returns the matching `bring_up` context manager. Module-scope (not a closure) so it pickles across `multiprocessing.spawn`.
    """

    def __init__(self,
                 *,
                 dpl: Dpl,
                 app_factory: Any,
                 framework: Framework,
                 wsgi_server: WsgiServer,
                 dpl_cfg: dict[str, Any]) -> None:
        self._dpl = dpl
        self._app_factory = app_factory
        self._framework = framework
        self._wsgi_server = wsgi_server
        self._dpl_cfg = dpl_cfg

    def __call__(self, n_workers: int) -> Any:
        """Return a `bring_up` context manager configured for `n_workers` worker processes.

        Args:
            n_workers (int): worker count for the multiprocess spawner.

        Returns:
            Any: live `bring_up` context manager (Iterator[list[str]]).
        """
        _bring_kw = dict(self._dpl_cfg)
        _bring_kw["workers"] = n_workers
        # cast at the call site: `**_bring_kw` widens the typed args to Any in pyright's view, so
        # we re-tag the Literal-typed knobs explicitly before they reach `bring_up`.
        _ctx = bring_up(cast(Dpl, self._dpl),
                        app_factory=self._app_factory,
                        framework=cast(Framework, self._framework),
                        wsgi_server=cast(WsgiServer, self._wsgi_server),
                        **_bring_kw)
        return _ctx


def _run_workers_scaling(*,
                         ws_cfg: dict[str, Any],
                         saturation_rate: int | float | None,
                         dpl: Dpl,
                         app_factory: Any,
                         framework: Framework,
                         wsgi_server: WsgiServer,
                         dpl_cfg: dict[str, Any]) -> dict[str, Any]:
    """Run the workers ramp against a freshly mounted vernier mesh.

    Picks `rate_per_worker` from the prior rate sweep's saturation (when present), falling back to whatever the config says.

    Args:
        ws_cfg (dict[str, Any]): pre-loaded `workers_scaling` config block.
        saturation_rate (int | float | None): per-worker saturation rate from the rate sweep.
        dpl (Dpl): deployment mode (must be `'multiprocess'`).
        app_factory (Any): zero-arg picklable callable returning the vernier app.
        framework (Framework): server stack.
        wsgi_server (WsgiServer): WSGI engine when `framework='flask'`.
        dpl_cfg (dict[str, Any]): the JSON `dpl` block (host, base_port, ready_timeout_s).

    Returns:
        dict[str, Any]: the populated `workers_scaling` envelope block.
    """
    _kw = dict(ws_cfg)
    _factor = _kw.pop("rate_per_worker_factor", 0.7)
    _n_clients = _kw.pop("n_clients", 1)
    if saturation_rate is not None:
        _kw["rate_per_worker"] = max(1, int(_factor * float(saturation_rate)))
    _make_targets = _BringUpFactory(dpl=dpl,
                                    app_factory=app_factory,
                                    framework=framework,
                                    wsgi_server=wsgi_server,
                                    dpl_cfg=dpl_cfg)
    _driver = make_multi_proc_driver(_n_clients)
    _ans = probe_workers_scaling(make_targets=_make_targets,
                                 driver=_driver,
                                 **_kw)
    return _ans


def find_latest_envelope(dpl: Dpl,
                         base: Path = _CALIBRATION_RESULTS_BASE) -> Path | None:
    """Return the most recent calibration envelope for `dpl`, or None if none recorded yet.

    Args:
        dpl (Dpl): deployment mode.
        base (Path, optional): calibration results base. Defaults to the standard tree.

    Returns:
        Path | None: latest envelope path, or None when nothing has been written for this mode.
    """
    _dir = base / dpl
    if not _dir.exists():
        return None
    _files = sorted(_dir.glob("*.json"), key=lambda _p: _p.stat().st_mtime)
    if not _files:
        return None
    return _files[-1]


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
        target_granularity (str, optional): `collapsed` (default) or `expanded`.
        inject_internal_stage_mu (bool, optional): when True (and expanded mode), TAS_{2..6} sleep on their published mu. Defaults to False.
        stage_routes (dict | None, optional): per-stage `calls_kind` + `operation` map (used in expanded mode). Required when `target_granularity="expanded"`.
        admission_lt (dict | None, optional): `{svc_id: {"c": int, "k": int}}` from `profile.specs`. When set, each atomic gets its per-svc cap; falls through to `atomic_admission` per-key when the profile is silent. Defaults to None (use the global `atomic_admission` for every atomic).

    Returns:
        tuple[list[MeshSpec], list[str], list[str]]: spec list + sorted third-party atomic ids + sorted internal-stage ids (empty list in collapsed mode).

    Raises:
        KeyError: when the profile does not declare a mu for some catalogue service.
        ValueError: when `target_granularity="expanded"` and `stage_routes` is None.
    """
    _catalogue = load_catalogue(catalogue_version)
    # Spawn only the catalogue entries the active profile declares (mu_lt is keyed by
    # artifact id). Different adp values can declare different service sets while
    # sharing one catalogue layer that covers the union.
    _atomic_ids = sorted(_id for _id in _catalogue.entries if _id in mu_lt)
    _is_expanded = target_granularity == "expanded"
    if _is_expanded and stage_routes is None:
        _msg = "stage_routes is required when target_granularity='expanded'"
        raise ValueError(_msg)

    # Port layout: each service consumes `workers` consecutive ports. TAS_{1} first,
    # then internal stages (expanded only), then third-party atomics. `workers_lt`
    # defaults each entry to 1 when unset.
    def _workers_for(svc_id: str) -> int:
        if workers_lt is None:
            return 1
        return max(1, int(workers_lt.get(svc_id, 1)))

    _composite_id = "TAS_{1}"
    _composite_workers = _workers_for(_composite_id)
    _tas_first_port = base_port

    if _is_expanded:
        _internal_first_port = _tas_first_port + _composite_workers
        _internal_total_workers = sum(_workers_for(_sid) for _sid in _INTERNAL_STAGE_IDS)
        _atomic_first_port = _internal_first_port + _internal_total_workers
    else:
        _internal_first_port = _tas_first_port + _composite_workers  # unused in collapsed
        _atomic_first_port = _tas_first_port + _composite_workers

    _atomic_url_lt: dict[str, list[str]] = {}
    _offset = 0
    for _svc_id in _atomic_ids:
        _w = _workers_for(_svc_id)
        _atomic_url_lt[_svc_id] = [f"http://{host}:{_atomic_first_port + _offset + _wi}"
                                        for _wi in range(_w)]
        _offset += _w

    _internal_url_lt: dict[str, list[str]] | None = None
    if _is_expanded:
        _internal_url_lt = {}
        _offset = 0
        for _stage_id in _INTERNAL_STAGE_IDS:
            _w = _workers_for(_stage_id)
            _internal_url_lt[_stage_id] = [f"http://{host}:{_internal_first_port + _offset + _wi}"
                                                for _wi in range(_w)]
            _offset += _w

    if framework == "flask":
        _build_tas = build_tas_flask_app
        _build_atomic = build_atomic_flask_app
        _build_internal = build_internal_stage_flask_app
    else:
        _build_tas = build_tas_fastapi_app
        _build_atomic = build_atomic_fastapi_app
        _build_internal = build_internal_stage_fastapi_app
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
                                       workers=_composite_workers)]

    _dflt_k = atomic_admission.get("k")
    _dflt_c = atomic_admission.get("c")

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
            _stage_k, _stage_c = _resolve_admission(_stage_id, admission_lt, _dflt_k, _dflt_c)
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
                                   workers=_workers_for(_stage_id)))

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
        _svc_k, _svc_c = _resolve_admission(_svc_id, admission_lt, _dflt_k, _dflt_c)
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
                               workers=_workers_for(_svc_id)))
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
    import httpx
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
    "baseline": ("r1_and_r2_breach",),
    "s1": ("r1_breach",),
    "s2": ("r2_breach",),
    "aggregate": ("r1_breach", "r2_breach"),
}


def _should_stop_from_aggregates(adp: str, agg: dict[str, Any]) -> tuple[bool, str]:
    """Apply the strategy-specific breach predicate to one `/aggregates` response.

    Args:
        adp (str): adaptation key.
        agg (dict[str, Any]): payload returned by the controller's `GET /aggregates`.

    Returns:
        tuple[bool, str]: `(stop, reason)` where `reason` is `""` when not stopping.
    """
    _r1, _r2 = bool(agg.get("r1_breach", False)), bool(agg.get("r2_breach", False))
    _stop = False
    _reason = ""
    _checks = _STOP_PREDICATES.get(adp, ())
    if "r1_and_r2_breach" in _checks and _r1 and _r2:
        _stop, _reason = True, "r1_and_r2_breach"
    elif "r1_breach" in _checks and _r1:
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
                        granularity: str) -> str | None:
    """Return the variant suffix for a `(framework, granularity)` pair.

    The canonical `fastapi` + `collapsed` pair is the headline; everything else gets a suffix so it doesn't overwrite the headline results.

    Args:
        framework (Framework): server stack.
        granularity (str): resolved granularity (`collapsed` or `expanded`).

    Returns:
        str | None: `<framework>__<granularity>` for variant runs; None for the canonical headline pair.
    """
    if framework == "fastapi" and granularity == "collapsed":
        return None
    return f"{framework}__{granularity}"


def _build_mesh_admission(*,
                          atomic_ids: list[str],
                          admission_lt: dict[str, dict[str, int]],
                          mu_lt: dict[str, float],
                          eps_lt: dict[str, float],
                          atomic_admission: dict[str, Any],
                          internal_stage_ids: list[str] | None = None,
                          include_composite: bool = True) -> dict[str, dict[str, Any]]:
    """Build the `{svc_id: {c, K, mu, eps}}` block echoed into `verdict.json::mesh`.

    Stage 9 (the yoly chart) reads this to verify the four methods used identical M/M/c/K parameters. Per-svc values come from `admission_lt`; the global `atomic_admission` fills in for ids the profile is silent on.

    Args:
        atomic_ids (list[str]): third-party atomic ids actually spawned.
        admission_lt (dict): per-svc `{c, k}` from `profile.specs`.
        mu_lt (dict): per-svc `mu` from `profile.specs`.
        eps_lt (dict): per-svc `epsilon` from `profile.specs`.
        atomic_admission (dict): global default `{k, c}` from `target.json`.
        internal_stage_ids (list[str] | None, optional): internal-stage ids spawned in expanded mode (`TAS_{2..6}`). Each gets its own row. Defaults to None.
        include_composite (bool, optional): when True, prepend a `TAS_{1}` row with the composite's `(c, K, mu, eps)` from `profile.specs`. Defaults to True.

    Returns:
        dict[str, dict[str, Any]]: rows for the composite (when included), every internal stage, and every third-party atomic. Keys preserve the natural mesh order: TAS_{1}, TAS_{2..6}, atomics sorted.
    """
    _dflt_k = atomic_admission.get("k")
    _dflt_c = atomic_admission.get("c")
    _ans: dict[str, dict[str, Any]] = {}
    _composite_id = "TAS_{1}"
    if include_composite and _composite_id in mu_lt:
        _k, _c = _resolve_admission(_composite_id, admission_lt, _dflt_k, _dflt_c)
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
            _k, _c = _resolve_admission(_stage_id, admission_lt, _dflt_k, _dflt_c)
            _ans[_stage_id] = {
                "c": _c,
                "K": _k,
                "mu": float(mu_lt.get(_stage_id, 0.0)),
                "eps": float(eps_lt.get(_stage_id, 0.0)),
            }
    for _svc_id in atomic_ids:
        _k, _c = _resolve_admission(_svc_id, admission_lt, _dflt_k, _dflt_c)
        _ans[_svc_id] = {
            "c": _c,
            "K": _k,
            "mu": float(mu_lt.get(_svc_id, 0.0)),
            "eps": float(eps_lt.get(_svc_id, 0.0)),
        }
    return _ans


def _workers_lt_from_profile(adp: str) -> dict[str, int]:
    """Read per-service worker counts (`w`) from the active profile's specs layer.

    Args:
        adp (str): adaptation key (selects which profile + scenario to load).

    Returns:
        dict[str, int]: worker count per artifact id. Defaults to 1 when the spec is silent.
    """
    _net = load_profile(adaptation=adp, source="specs")
    _ans: dict[str, int] = {}
    for _artifact in _net.artifacts:
        try:
            _ans[_artifact.key] = max(1, int(_artifact.w))
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
                       poll_every_n: int = 0) -> tuple[list[dict[str, Any]], str]:
    """Drive up to `n_requests` against the composite TAS; halt early on a breach.

    When `tas_urls` has more than one entry (multi-worker TAS_{1}), the trial spawns one `User` per URL. Each user runs `n_requests / N` requests at `request_rate_per_s / N` pacing so the aggregate rate matches the configured value while load distributes across the workers. A single shared breach-flag stops every user as soon as the first one observes a breach.

    Args:
        tas_urls (list[str]): one or more TAS_{1} base URLs (one per worker).
        n_requests (int): aggregate request budget across all users.
        request_rate_per_s (float): aggregate pacing rate (0 = no pacing). Split evenly across users.
        p_alarm (float): probability the next request is an alarm.
        request_timeout_s (float): per-request timeout.
        seed (int | None): RNG seed for kind selection (offset per user so each draws a distinct stream).
        controller_url (str | None, optional): controller base URL. None disables the breach poll. Defaults to None.
        adp (str, optional): adaptation key (drives the stop predicate). Defaults to `"baseline"`.
        poll_every_n (int, optional): aggregate request count between breach polls (0 disables). Defaults to 0.

    Returns:
        tuple[list[dict[str, Any]], str]: per-request summaries + stop_reason (`"n_reached"` / `"r1_breach"` / `"r2_breach"` / `"r1_and_r2_breach"`).
    """
    if not tas_urls:
        _msg = "_drive_trial requires at least one TAS URL"
        raise ValueError(_msg)
    _n_users = len(tas_urls)
    _per_user_n = max(1, n_requests // _n_users)
    if request_rate_per_s > 0:
        _per_user_rate = request_rate_per_s / _n_users
    else:
        _per_user_rate = 0.0
    _summaries: list[dict[str, Any]] = []
    _summaries_lock = asyncio.Lock()
    _stop_event = asyncio.Event()
    _stop_reason_box: list[str] = ["n_reached"]
    import httpx
    _http: httpx.AsyncClient | None = None
    if controller_url is not None and poll_every_n > 0:
        _http = httpx.AsyncClient(timeout=2.0)
    _per_user_poll = max(1, poll_every_n // _n_users) if poll_every_n > 0 else 0
    try:
        _tasks = []
        for _ui, _url in enumerate(tas_urls):
            _user_seed: int | None
            if seed is None:
                _user_seed = None
            else:
                _user_seed = seed + _ui
            _tasks.append(_drive_one_user(client_id=f"trial-user-{_ui}",
                                          base_url=_url,
                                          n_requests=_per_user_n,
                                          per_user_rate=_per_user_rate,
                                          p_alarm=p_alarm,
                                          request_timeout_s=request_timeout_s,
                                          seed=_user_seed,
                                          summaries=_summaries,
                                          summaries_lock=_summaries_lock,
                                          stop_event=_stop_event,
                                          stop_reason_box=_stop_reason_box,
                                          breach_http=_http,
                                          controller_url=controller_url,
                                          adp=adp,
                                          per_user_poll=_per_user_poll))
        await asyncio.gather(*_tasks)
    finally:
        if _http is not None:
            await _http.aclose()
    return _summaries, _stop_reason_box[0]


async def _drive_one_user(*,
                          client_id: str,
                          base_url: str,
                          n_requests: int,
                          per_user_rate: float,
                          p_alarm: float,
                          request_timeout_s: float,
                          seed: int | None,
                          summaries: list[dict[str, Any]],
                          summaries_lock: asyncio.Lock,
                          stop_event: asyncio.Event,
                          stop_reason_box: list[str],
                          breach_http: "httpx.AsyncClient | None",
                          controller_url: str | None,
                          adp: str,
                          per_user_poll: int) -> None:
    """Drive one `User` against `base_url`; flush its records into a shared list under a lock.

    Stops early when `stop_event` is set (a sibling user observed a breach) or when its own budget is exhausted.
    """
    if per_user_rate > 0:
        _gap_s = 1.0 / per_user_rate
    else:
        _gap_s = 0.0
    async with User(client_id=client_id,
                    base_url=base_url,
                    endpoint_path="/",
                    seed=seed,
                    p_alarm=p_alarm,
                    timeout_s=request_timeout_s,
                    sequential_req_ids=True) as _user:
        for _i in range(n_requests):
            if stop_event.is_set():
                break
            _record = await _user.run_one()
            async with summaries_lock:
                summaries.append({
                    "req_id": _record.req_id,
                    "kind": _record.kind,
                    "outcome": _record.outcome,
                    "status": _record.status_code,
                    "latency_s": _record.total_latency_s,
                })
            _done_count = _i + 1
            if breach_http is not None and per_user_poll > 0 and (_done_count % per_user_poll == 0):
                _stop, _reason = await _check_breach(breach_http,
                                                     controller_url or "",
                                                     adp)
                if _stop:
                    stop_reason_box[0] = _reason
                    stop_event.set()
                    break
            if _gap_s > 0:
                await asyncio.sleep(_gap_s)


async def _check_breach(http: "httpx.AsyncClient",
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
                   envelope: dict[str, Any] | None = None,
                   skip_bounds_check: bool = False,
                   target_granularity: str | None = None,
                   inject_internal_stage_mu: bool | None = None) -> dict[str, Any]:
    """Mount the TAS topology, drive one trial, write the per-request + per-service logs.

    Reads `target.json` for bindings, validates the planned operating point against the latest calibration envelope (unless skipped), brings the mesh up, drives `trial.n_requests` requests through one synthetic user, and appends a row to `runs.parquet`.

    Args:
        adp (str, optional): adaptation key (`baseline` / `s1` / `s2` / `aggregate`). Defaults to `"baseline"`.
        dpl (Dpl, optional): deployment mode. Defaults to `"localhost"`.
        framework (Framework, optional): server stack. Defaults to `"fastapi"`.
        wsgi_server (WsgiServer, optional): WSGI engine when `framework="flask"`. Defaults to `"waitress"`.
        write (bool, optional): persist outputs to disk. Defaults to True.
        run_id (str | None, optional): explicit run id. Defaults to a fresh `<adp>_<ts>_<nonce>` id.
        target_cfg (dict[str, Any] | None, optional): pre-loaded target config. Defaults to reading the on-disk JSON.
        envelope (dict[str, Any] | None, optional): explicit calibration envelope. Defaults to auto-discover the latest for `dpl`.
        skip_bounds_check (bool, optional): skip the envelope check. Defaults to False.
        target_granularity (str | None, optional): `collapsed` or `expanded`. Overrides `target.json::target_granularity` when set; falls through to the JSON value when None.
        inject_internal_stage_mu (bool | None, optional): when True (and expanded), TAS_{2..6} sleep on mu. Overrides `target.json::inject_internal_stage_mu` when set; falls through to the JSON value when None.

    Returns:
        dict[str, Any]: run summary (`run_id`, `adp`, `dpl`, `n_requests`, `outcome_counts`, `paths`, `bounds`, `target_granularity`).
    """
    if target_cfg is None:
        _cfg = load_target_cfg()
    else:
        _cfg = target_cfg
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

    _bounds_report = _maybe_check_bounds(dpl=dpl,
                                         envelope=envelope,
                                         trial_cfg=_cfg["trial"],
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
    )
    _mesh_admission = _build_mesh_admission(atomic_ids=_atomic_ids,
                                            admission_lt=_admission_lt,
                                            mu_lt=_mu_lt,
                                            eps_lt=_eps_lt,
                                            atomic_admission=_cfg["atomic_admission"],
                                            internal_stage_ids=_internal_stage_ids,
                                            include_composite=True)

    _trial = _cfg["trial"]
    _kind_p = _trial["kind_probability"]
    _ctrl_cfg = _cfg.get("controller", {})
    _strat_cfg = _cfg.get("strategies", {})
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
        # Controller polls only the first TAS_{1} worker's /samples; each worker has its
        # own buffer so cross-worker sample merging would need a shared store. The final
        # verdict is computed from the shared flow JSONL (every worker appends), so the
        # /samples gap only affects early-stop breach detection, not the verdict numbers.
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
        "n_requests": len(_summaries),
        "n_success": _outcome_counts.get("success", 0),
        "n_timeout": _outcome_counts.get("timeout", 0),
        "n_drop": _outcome_counts.get("drop", 0),
        "n_5xx": _outcome_counts.get("5xx", 0),
        "started_ts": _started_ts,
        "finished_ts": _finished_ts,
        "envelope_run_id": _bounds_report.envelope_run_id if _bounds_report else None,
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
                        dpl: Dpl,
                        envelope: dict[str, Any] | None,
                        trial_cfg: dict[str, Any],
                        atomic_admission: dict[str, Any],
                        skip: bool) -> BoundsReport | None:
    """Check the planned `(c, r, w)` against the latest calibration envelope, when one exists.

    Args:
        dpl (Dpl): deployment mode (drives envelope lookup).
        envelope (dict[str, Any] | None): explicit envelope override.
        trial_cfg (dict[str, Any]): trial block from `target.json`.
        atomic_admission (dict[str, Any]): admission caps from `target.json`.
        skip (bool): if True, return None without checking.

    Returns:
        BoundsReport | None: per-axis verdicts, or None when nothing was checked.
    """
    if skip:
        return None
    if envelope is None:
        _path = find_latest_envelope(dpl)
        if _path is None:
            return None
        envelope = read_envelope(_path)
    _exp_cfg: dict[str, Any] = {
        "r": float(trial_cfg.get("request_rate_per_s", 0)),
    }
    _c = atomic_admission.get("c")
    if isinstance(_c, (int, float)):
        _exp_cfg["c"] = float(_c)
    return validate_experimental_limits(_exp_cfg, envelope, raise_on_fail=True)


def _count_outcomes(summaries: list[dict[str, Any]]) -> dict[str, int]:
    """Tally `outcome` values across the summaries."""
    _counts: dict[str, int] = {}
    for _row in summaries:
        _key = str(_row.get("outcome", "?"))
        _counts[_key] = _counts.get(_key, 0) + 1
    return _counts


def run(*,
        stage: str = "calibration",
        adp: str = "baseline",
        dpl: Dpl = "localhost",
        framework: Framework = "fastapi",
        wsgi_server: WsgiServer = "waitress",
        write: bool = True,
        run_id: str | None = None,
        cfg: dict[str, Any] | None = None,
        skip_bounds_check: bool = False,
        target_granularity: str | None = None,
        inject_internal_stage_mu: bool | None = None) -> dict[str, Any]:
    """Run calibration, an experiment trial, or both.

    Args:
        stage (str, optional): `"calibration"`, `"experiment"`, or `"both"`. Defaults to `"calibration"`.
        adp (str, optional): adaptation key (used by experiment stages). Defaults to `"baseline"`.
        dpl (Dpl, optional): deployment mode.
        framework (Framework, optional): server stack.
        wsgi_server (WsgiServer, optional): WSGI engine when `framework="flask"`.
        write (bool, optional): persist outputs to disk. Defaults to True.
        run_id (str | None, optional): explicit run id.
        cfg (dict[str, Any] | None, optional): pre-loaded calibration config (calibration stages only).
        skip_bounds_check (bool, optional): skip the envelope check (experiment stages only). Defaults to False.
        target_granularity (str | None, optional): `collapsed` / `expanded` override (experiment stages only). None falls through to `target.json`.
        inject_internal_stage_mu (bool | None, optional): TAS_{2..6} mu-sleep override (experiment stages only). None falls through to `target.json`.

    Returns:
        dict[str, Any]: envelope, experiment summary, or `{"calibration": ..., "experiment": ...}`.

    Raises:
        ValueError: on an unknown stage.
    """
    if stage == "calibration":
        return run_calibration(dpl=dpl,
                               framework=framework,
                               wsgi_server=wsgi_server,
                               write=write,
                               run_id=run_id,
                               cfg=cfg)
    if stage == "experiment":
        return run_experiment(adp=adp,
                              dpl=dpl,
                              framework=framework,
                              wsgi_server=wsgi_server,
                              write=write,
                              run_id=run_id,
                              skip_bounds_check=skip_bounds_check,
                              target_granularity=target_granularity,
                              inject_internal_stage_mu=inject_internal_stage_mu)
    if stage == "both":
        _calib = run_calibration(dpl=dpl,
                                 framework=framework,
                                 wsgi_server=wsgi_server,
                                 write=write,
                                 run_id=run_id,
                                 cfg=cfg)
        _exp = run_experiment(adp=adp,
                              dpl=dpl,
                              framework=framework,
                              wsgi_server=wsgi_server,
                              write=write,
                              envelope=_calib,
                              skip_bounds_check=skip_bounds_check,
                              target_granularity=target_granularity,
                              inject_internal_stage_mu=inject_internal_stage_mu)
        return {"calibration": _calib, "experiment": _exp}
    _msg = f"unknown stage {stage!r}; expected 'calibration', 'experiment', or 'both'"
    raise ValueError(_msg)


def main() -> None:
    """CLI entry: parse flags and run the chosen stage."""
    _parser = argparse.ArgumentParser(prog="src.methods.experimental",
                                      description="Experimental method orchestrator (calibration + experiment).")
    _parser.add_argument("--stage",
                         choices=["calibration", "experiment", "both"],
                         default="calibration")
    _parser.add_argument("--adaptation",
                         choices=["baseline", "s1", "s2", "aggregate"],
                         default="baseline",
                         dest="adp")
    _parser.add_argument("--dpl",
                         choices=["localhost", "multiprocess", "remote"],
                         default="localhost")
    _parser.add_argument("--framework",
                         choices=["fastapi", "flask"],
                         default="fastapi")
    _parser.add_argument("--wsgi-server",
                         choices=["waitress", "gunicorn"],
                         default="waitress",
                         dest="wsgi_server")
    _parser.add_argument("--write",
                         action=argparse.BooleanOptionalAction,
                         default=True)
    _parser.add_argument("--skip-bounds-check",
                         action="store_true",
                         dest="skip_bounds_check")
    _parser.add_argument("--target-granularity",
                         choices=["collapsed", "expanded"],
                         dest="target_granularity",
                         default=None,
                         help="override target.json::target_granularity for the experiment stage.")
    _parser.add_argument("--inject-internal-stage-mu",
                         action=argparse.BooleanOptionalAction,
                         dest="inject_internal_stage_mu",
                         default=None,
                         help="override target.json::inject_internal_stage_mu for the experiment stage.")
    _args = _parser.parse_args()
    # argparse `choices=...` constrains the value at runtime to the literal set,
    # but the static type stays `str`; cast back to the Literal aliases the run()
    # signature expects.
    _result = run(stage=str(_args.stage),
                  adp=str(_args.adp),
                  dpl=cast(Dpl, _args.dpl),
                  framework=cast(Framework, _args.framework),
                  wsgi_server=cast(WsgiServer, _args.wsgi_server),
                  write=bool(_args.write),
                  skip_bounds_check=bool(_args.skip_bounds_check),
                  target_granularity=_args.target_granularity,
                  inject_internal_stage_mu=_args.inject_internal_stage_mu)
    if _args.stage == "calibration":
        _print_calibration_report(_result)
    elif _args.stage == "experiment":
        _print_experiment_summary(_result)
    else:
        _print_calibration_report(_result["calibration"])
        _print_experiment_summary(_result["experiment"])


_REPORT_LEGEND_LINES = (
    "Latency:  Reported figures equal the measured value\nminus the loopback floor (median), \nwith the jitter p99 as the precision band.",
    "Floors:   Background noise sources we cannot control \n(clock, scheduler, kernel TCP path); \nthe precision band is their RMS sum.",
    "Envelope: Operating limits where the apparatus's measurements\n remain trustworthy (concurrency knee + rate saturation knee).",
)

# Mathtext-to-terminal substitutions: gate.summary headlines use mathtext (`$\pm$`, `$\mu$s`,
# `$\leq$`) so they render correctly in the matplotlib panel; for stdout we swap them for the
# Unicode glyphs that any modern terminal can display.
_TERMINAL_SUBSTITUTIONS = (
    (r"$\pm$", "+/-"),
    (r"$\mu$s", "us"),
    (r"$\mu$", "u"),
    (r"$\leq$", "<="),
)


def _to_terminal(text: str) -> str:
    """Render a mathtext headline as plain text for the terminal.

    Args:
        text (str): headline that may contain mathtext (e.g. `$\\pm$ 0.05 $\\mu$s`).

    Returns:
        str: ASCII / Unicode equivalent (e.g. `+/- 0.05 us`).
    """
    _ans = text
    for _src, _dst in _TERMINAL_SUBSTITUTIONS:
        _ans = _ans.replace(_src, _dst)
    # Strip any leftover bare `$...$` mathtext segments (e.g. `$c=8$` -> `c=8`).
    _ans = _ans.replace("$", "")
    return _ans


def _print_calibration_report(envelope: dict[str, Any]) -> None:
    """Print the calibration report (matches the figure's Report panel layout).

    Args:
        envelope (dict[str, Any]): populated calibration envelope (must include `gate`).
    """
    _gate = envelope["gate"]
    _band = (_gate.get("precision_band_us") or {}).get("total_us")
    _range = _gate.get("verifiable_range", {}) or {}
    _summary = _gate.get("summary", {}) or {}
    _c_max = _range.get("c_max")
    _r_max = _range.get("r_max_req_s")
    _w_max = _range.get("w_max")

    if _band is None:
        _band_str = "n/a"
    else:
        _band_str = f"+/- {_band:.2f} us"
    if _c_max is None:
        _c_str = "n/a"
    else:
        _c_str = f"c <= {int(_c_max)}"
    if _r_max is None:
        _r_str = "n/a"
    else:
        _r_str = f"r <= {int(_r_max)} req/s"
    if _w_max is None:
        _w_str = "n/a"
    else:
        _w_str = f"w <= {int(_w_max)}"

    print()
    print(f"host: {envelope.get('host', '?')}     dpl: {envelope.get('dpl', '?')}")
    print(f"run:  {envelope.get('run_id', '?')}")
    print(f"Allowed noise floor: +/- {_gate['noise_floor_pct']:.1f} %")
    print()
    print(f"Precision band   {_band_str}")
    print()
    print(f"Operating range  {_c_str}")
    print(f"                 {_r_str}")
    print(f"                 {_w_str}")
    print()
    print("Floors")
    for _name, _label in (("timer", "Timer"), ("jitter", "Jitter"), ("loopback", "Loopback")):
        _hl = _to_terminal(_summary.get(_name, {}).get("headline", "n/a"))
        print(f"   {_label:<11} {_hl}")
    print()
    print("Envelope")
    for _name, _label in (("scaling", "Scaling"), ("rate", "Rate sweep"), ("workers", "Workers")):
        _hl = _to_terminal(_summary.get(_name, {}).get("headline", "n/a"))
        print(f"   {_label:<11} {_hl}")
    print()
    print("-" * 64)
    for _line in _REPORT_LEGEND_LINES:
        print(_line)


def _print_experiment_summary(result: dict[str, Any]) -> None:
    """Print one experiment-run summary block.

    Args:
        result (dict[str, Any]): dict returned by `run_experiment(...)`.
    """
    _counts = result.get("outcome_counts", {})
    _bounds: BoundsReport | None = result.get("bounds")
    print()
    print(f"adp:  {result.get('adp', '?')}     dpl: {result.get('dpl', '?')}")
    print(f"run:  {result.get('run_id', '?')}")
    print(f"requests: {result.get('n_requests', 0)}")
    print(f"  success: {_counts.get('success', 0)}")
    print(f"  timeout: {_counts.get('timeout', 0)}")
    print(f"  drop:    {_counts.get('drop', 0)}")
    print(f"  5xx:     {_counts.get('5xx', 0)}")
    print()
    print("paths:")
    for _label, _path in (result.get("paths") or {}).items():
        print(f"  {_label:<13} {_path}")
    if _bounds is not None:
        print()
        print(f"envelope:        run={_bounds.envelope_run_id}  passed={_bounds.passed}")
        for _check in _bounds.checks:
            print(f"  {_check.message}")


if __name__ == "__main__":
    main()

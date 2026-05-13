# -*- coding: utf-8 -*-
"""Calibration-stage orchestrator.

Measure the host's noise floor + per-worker saturation and write a calibration envelope under `data/results/calibration/<dpl>/`. The public entry is `run_calibration(dpl=...)`; this module is the thin runner around `src.experimental.prototype.calibration` primitives (timer / jitter / loopback / handler / rate / workers probes + gate stamping + envelope I/O).

Earlier this code lived in `src.methods.experimental`; it moved here as part of stage 8.0 so `src/methods/experimental.py` shrinks to a thin CLI / notebook facade. Symbols (including `find_latest_envelope`) are re-exported from `src.methods.experimental` for back-compat.
"""

from __future__ import annotations

import functools
import time
from pathlib import Path
from typing import Any, cast

from src.experimental.common.io.runs import make_run_id
from src.experimental.procedure.deployment import (
    Dpl,
    Framework,
    WsgiServer,
    bring_up,
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
)
from src.experimental.prototype.calibration.vernier import (
    build_vernier_fastapi_app,
    build_vernier_flask_app,
)


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

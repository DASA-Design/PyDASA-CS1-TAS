# -*- coding: utf-8 -*-
"""Experimental method orchestrator for the CS-01 TAS case study.

Two entry points the notebook and the CLI both call:

- `run_calibration(...)`: drive the full calibration loop and return the envelope.
- `run(stage, ...)`: dispatcher; only `stage="calibration"` is wired today.

CLI::

    python -m src.methods.experimental --stage calibration --dpl localhost
    python -m src.methods.experimental --stage calibration --dpl multiprocess --framework flask
"""

from __future__ import annotations

import argparse
import functools
import time
from typing import Any

from src.experimental.common.io.runs import make_run_id
from src.experimental.procedure.deployment import Dpl, Framework, WsgiServer, bring_up
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
    """Run the calibration procedure end-to-end and return the populated envelope.

    Steps:

        1. Build the envelope skeleton.
        2. Run the four host-floor probes (timer / jitter / loopback / handler scaling); apparatus-independent.
        3. Bring up the vernier under `dpl`; drive the rate sweep against its URLs (round-robin under `multiprocess`).
        4. Stamp the gate verdict; write the envelope to `data/results/calibration/<dpl>/` when `write=True`.

    Args:
        dpl (Dpl, optional): deployment mode. Defaults to `"localhost"`.
        framework (Framework, optional): server stack. Defaults to `"fastapi"`.
        wsgi_server (WsgiServer, optional): WSGI engine when `framework="flask"`. Defaults to `"waitress"`.
        write (bool, optional): write the envelope to disk. Defaults to True.
        run_id (str | None, optional): explicit run id. Defaults to None, which mints a fresh `make_run_id(prefix="calib")`.
        cfg (dict[str, Any] | None, optional): pre-loaded calibration config. Defaults to None (loads `data/config/method/prototype/calibration.json`).

    Returns:
        dict[str, Any]: the populated envelope (also on disk if `write=True`).
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
    """Bind `bring_up` keyword args once; expose a `make_targets`-shaped `(n_workers) -> ctxmgr` callable.

    Holds the deployment-side parameters (`dpl`, `framework`, `wsgi_server`, `app_factory`, `dpl_cfg`) so the workers ramp can ask for n target URLs without seeing those details. Replaces the closure inside `_run_workers_scaling` with a module-scope class that's picklable + grep-able.
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
        """Return the `bring_up` context manager configured for `n_workers` worker processes."""
        _bring_kw = dict(self._dpl_cfg)
        _bring_kw["workers"] = n_workers
        _ctx = bring_up(self._dpl,
                        app_factory=self._app_factory,
                        framework=self._framework,
                        wsgi_server=self._wsgi_server,
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
    """Run `probe_workers_scaling` with a `bring_up`-backed `make_targets`.

    Auto-derives `rate_per_worker` from `probe_rate`'s saturation when available; otherwise falls back to the absolute `rate_per_worker` in `ws_cfg`.

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


def run(*,
        stage: str = "calibration",
        dpl: Dpl = "localhost",
        framework: Framework = "fastapi",
        wsgi_server: WsgiServer = "waitress",
        write: bool = True,
        run_id: str | None = None,
        cfg: dict[str, Any] | None = None) -> dict[str, Any]:
    """Top-level dispatcher for the experimental method.

    Only `stage="calibration"` is wired today; the experiment + sweep paths land later.

    Args:
        stage (str, optional): one of `"calibration"`, `"experiment"`, `"both"`. Defaults to `"calibration"`.
        dpl (Dpl, optional): deployment mode.
        framework (Framework, optional): server stack.
        wsgi_server (WsgiServer, optional): WSGI engine when `framework="flask"`.
        write (bool, optional): write outputs to disk. Defaults to True.
        run_id (str | None, optional): explicit run id.

    Returns:
        dict[str, Any]: the populated envelope (calibration path).

    Raises:
        NotImplementedError: when `stage != "calibration"`; the experiment path is not yet wired.
        ValueError: when `stage` is not a recognised value.
    """
    _ans: dict[str, Any]
    if stage == "calibration":
        _ans = run_calibration(dpl=dpl,
                               framework=framework,
                               wsgi_server=wsgi_server,
                               write=write,
                               run_id=run_id,
                               cfg=cfg)
    elif stage in ("experiment", "both"):
        _msg = f"stage={stage!r} is not yet wired; only 'calibration' is supported"
        raise NotImplementedError(_msg)
    else:
        _msg = f"unknown stage {stage!r}; expected 'calibration', 'experiment', or 'both'"
        raise ValueError(_msg)
    return _ans


def main() -> None:
    """CLI entry: parse args and call `run()`; print the gate verdict on stdout."""
    _parser = argparse.ArgumentParser(prog="src.methods.experimental",
                                      description="Experimental method orchestrator (calibration path).")
    _parser.add_argument("--stage",
                         choices=["calibration", "experiment", "both"],
                         default="calibration")
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
    _args = _parser.parse_args()
    _envelope = run(stage=_args.stage,
                    dpl=_args.dpl,
                    framework=_args.framework,
                    wsgi_server=_args.wsgi_server,
                    write=_args.write)
    _print_calibration_report(_envelope)


_REPORT_LEGEND_LINES = (
    "Latency:  Reported figures equal the measured value\nminus the loopback floor (median), \nwith the jitter p99 as the precision band.",
    "Floors:   Background noise sources we cannot control \n(clock, scheduler, kernel TCP path); \nthe precision band is their RMS sum.",
    "Envelope: Operating limits where the apparatus's measurements\n remain trustworthy (concurrency knee + rate saturation knee).",
)


def _print_calibration_report(envelope: dict[str, Any]) -> None:
    """Print the calibration report to stdout, matching the figure's Report panel.

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
        _hl = _summary.get(_name, {}).get("headline", "n/a")
        print(f"   {_label:<11} {_hl}")
    print()
    print("Envelope")
    for _name, _label in (("scaling", "Scaling"), ("rate", "Rate sweep"), ("workers", "Workers")):
        _hl = _summary.get(_name, {}).get("headline", "n/a")
        print(f"   {_label:<11} {_hl}")
    print()
    print("-" * 64)
    for _line in _REPORT_LEGEND_LINES:
        print(_line)


if __name__ == "__main__":
    main()

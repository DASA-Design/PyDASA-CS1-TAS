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
import time
from typing import Any

from src.experimental.common.io.runs import make_run_id
from src.experimental.procedure.deployment import Dpl, Framework, WsgiServer, bring_up
from src.experimental.prototype.calibration import (
    envelope_path,
    make_envelope,
    probe_handler_scaling,
    probe_jitter,
    probe_loopback,
    probe_rate,
    probe_timer,
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
                    run_id: str | None = None) -> dict[str, Any]:
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

    Returns:
        dict[str, Any]: the populated envelope (also on disk if `write=True`).
    """
    if run_id is None:
        _run_id = make_run_id(prefix="calib")
    else:
        _run_id = run_id

    if framework == "flask":
        _wsgi: str | None = wsgi_server
        _app_factory: Any = build_vernier_flask_app
    else:
        _wsgi = None
        _app_factory = build_vernier_fastapi_app

    _envelope = make_envelope(run_id=_run_id,
                              dpl=dpl,
                              framework=framework,
                              wsgi_server=_wsgi)

    # 1. Host-floor probes (apparatus-independent).
    _envelope["timer"] = probe_timer()
    _envelope["jitter"] = probe_jitter()
    _envelope["loopback"] = probe_loopback()
    _envelope["handler_scaling"] = probe_handler_scaling()

    # 2. Bring up the vernier; run the rate sweep across all worker URLs.
    with bring_up(dpl,
                  app_factory=_app_factory,
                  framework=framework,
                  wsgi_server=wsgi_server) as _urls:
        _target_urls = [f"{_url}/" for _url in _urls]
        _envelope["rate"] = probe_rate(target_urls=_target_urls)

    # 3. Gate verdict + close-out.
    stamp_gate(_envelope)
    _envelope["finished_ts"] = time.time()

    if write:
        _path = envelope_path(dpl=dpl,
                              host=_envelope["host"],
                              run_id=_run_id)
        write_envelope(_path, _envelope)

    return _envelope


def run(*,
        stage: str = "calibration",
        dpl: Dpl = "localhost",
        framework: Framework = "fastapi",
        wsgi_server: WsgiServer = "waitress",
        write: bool = True,
        run_id: str | None = None) -> dict[str, Any]:
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
                               run_id=run_id)
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
    _gate = _envelope["gate"]
    if _gate["passed"]:
        _verdict = "PASS"
    else:
        _verdict = "FAIL"
    print(f"\nCalibration {_verdict} on dpl={_args.dpl} framework={_args.framework}.")
    print(f"\tNoise floor:\t{_gate['noise_floor_pct']} %")
    for _name, _check in _gate["checks"].items():
        if _check["passed"]:
            _status = "ok"
        else:
            _status = "fail"
        print(f"\t[{_status}]\t{_name}:\t{_check.get('reason', '?')}")


if __name__ == "__main__":
    main()

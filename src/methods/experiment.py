# -*- coding: utf-8 -*-
"""
Module experiment.py
====================

Method 4 of the CS-01 TAS pipeline; FastAPI mesh + ramped client through `TAS_{1}`, emits the standard envelope (per-node df + network aggregate + R1/R2/R3 verdict). Output split by deployment (`localhost` / `multiprocess` / `remote`).

Public API:
    - `run(adp, prf, scn, wrt, method_cfg=None, skip_calibration=False, verbose=True, dpl=None, launcher_role=None)` standard orchestrator contract.
    - `main()` CLI entry point.

CLI::

    python -m src.methods.experiment --adaptation baseline
    python -m src.methods.experiment --adaptation s1 --profile opti
    python -m src.methods.experiment --deployment multiprocess
    python -m src.methods.experiment --deployment remote --launcher-role client
"""
# native python modules
from __future__ import annotations

import argparse
import json
import tempfile
from pathlib import Path

# data types
from typing import Any, Dict, List, Optional

# scientific stack
import pandas as pd

# local modules
from src.analytic import aggregate_net, check_reqs
from src.experiment.executor import build_svc_df_from_logs, execute_one
from src.experiment.runtime import run_async_safe
from src.experiment.services import derive_seed
from src.io import (NetCfg,
                    calibration_age_hours,
                    calibration_band_us,
                    calibration_floor_us,
                    load_latest_calibration,
                    load_method_cfg,
                    load_profile)


_ROOT = Path(__file__).resolve().parents[2]
_RESULTS_DIR = _ROOT / "data" / "results" / "experiment"

# deployment modes recognised by the experiment runner; mirrors the SvcRegistry / TasArchitecture enum
_VALID_DEPLOYMENTS = ("localhost", "multiprocess", "remote")

# Hours after which a calibration is considered stale (warning only)
_CALIB_STALE_HOURS: float = 24.0


def _resolve_baseline(*,
                      skip: bool,
                      verbose: bool = True) -> Optional[Dict[str, Any]]:
    """*_resolve_baseline()* load the most recent host calibration; enforces the pre-run noise-floor gate.

    Args:
        skip (bool): bypass the gate; returns `None` with a loud warning.
        verbose (bool): when False, suppress stale / skip warnings.

    Returns:
        Optional[Dict[str, Any]]: parsed calibration envelope, or `None` when skipped.

    Raises:
        RuntimeError: when `skip=False` and no calibration file exists for the current host.
    """
    if skip:
        if verbose:
            _msg = "WARNING: --skip-calibration; raw latencies are not host-adjusted."
            print(_msg)
        return None

    _env = load_latest_calibration()
    if _env is None:
        _msg = "No host calibration; run `python -m src.methods.calibration` "
        _msg += "or pass --skip-calibration."
        raise RuntimeError(_msg)
    _age = calibration_age_hours(_env)
    if verbose and _age > _CALIB_STALE_HOURS:
        print(f"WARNING: calibration {_age:.1f} h old (>{_CALIB_STALE_HOURS:.0f} h); consider re-running.")
    return _env


def _build_baseline_block(envelope: Optional[Dict[str, Any]]
                          ) -> Dict[str, Any]:
    """*_build_baseline_block()* summarise a calibration envelope for the result envelope.

    Stored alongside every experiment run so downstream reporting can apply the `reported = measured - loopback_median +/- jitter_p99` convention without re-reading the calibration JSON.

    Args:
        envelope (Optional[Dict[str, Any]]): calibration envelope, or `None` when the gate was skipped.

    Returns:
        Dict[str, Any]: summary block with `baseline_ref`, `loopback_median_us`, `jitter_p99_us`, `age_hours`, `applied`.
    """
    if envelope is None:
        return {
            "baseline_ref": None,
            "loopback_median_us": 0.0,
            "jitter_p99_us": 0.0,
            "age_hours": None,
            "applied": False,
        }
    _ref = envelope.get("output_path")
    _floor = calibration_floor_us(envelope)
    _band = calibration_band_us(envelope)
    _age = calibration_age_hours(envelope)
    return {
        "baseline_ref": _ref,
        "loopback_median_us": _floor,
        "jitter_p99_us": _band,
        "age_hours": _age,
        "applied": True,
    }


def run(adp: Optional[str] = None,
        prf: Optional[str] = None,
        scn: Optional[str] = None,
        wrt: bool = True,
        method_cfg: Optional[Dict[str, Any]] = None,
        skip_calibration: bool = False,
        verbose: bool = True,
        dpl: Optional[str] = None,
        launcher_role: Optional[str] = None) -> Dict[str, Any]:
    """*run()* execute the architectural experiment for one (profile, scenario) pair.

    Enforces the per-host calibration gate: a noise-floor calibration for the current host must exist under `data/results/experiment/calibration/` before the run starts, or `skip_calibration=True` must be set to bypass with a warning. The resolved baseline is attached to the result envelope as the `baseline` block so downstream reporting can apply the `reported = measured - loopback_median +/- jitter_p99` convention.

    Output paths: `data/results/experiment/<deployment>/<scenario>/<profile>/...` with `<deployment>` in `localhost` / `multiprocess` / `remote`.

    Args:
        adp (Optional[str]): adaptation value; one of `baseline`, `s1`, `s2`, `aggregate`.
        prf (Optional[str]): profile stem (`dflt` / `opti`).
        scn (Optional[str]): explicit scenario name.
        wrt (bool): if True, write artifacts under `data/results/experiment/<deployment>/<scenario>/`. Defaults to True.
        method_cfg (Optional[Dict[str, Any]]): inline config override; used by `_QUICK_CFG` tests to skip the JSON read.
        skip_calibration (bool): when True, bypass the calibration gate; a warning is printed and `baseline.applied` is False on the result.
        verbose (bool): when False, suppress the calibration stale / skip warnings; metric output is unaffected.
        dpl (Optional[str]): deployment mode override; `None` reads `method_cfg["deployment"]` (default `"localhost"`). Recognised: `"localhost"` / `"multiprocess"` / `"remote"`. Non-localhost modes require the real-uvicorn launcher (`notes/distribute.md` G5); the in-process ASGI launcher only supports `localhost` until then.
        launcher_role (Optional[str]): subset of services this driver is responsible for spawning; `None` reads `method_cfg["launcher_role"]` (default `"all"`). Recognised: `"all"` / `"client"` / `"composite"` / `"atomic"` / `"composite-atomic"`.

    Returns:
        Dict[str, Any]: result envelope with `config`, `method_config`, `nodes`, `network`, `requirements`, `probes`, `saturation_rate`, `stopped_reason`, `client_effective_rate`, `log_drop_counts`, `replicates`, `baseline`, `paths`, `deployment`.

    Raises:
        RuntimeError: when `skip_calibration` is False and no calibration exists for the current host.
        ValueError: when `dpl` is not one of the recognised deployment modes.
    """
    _baseline_env = _resolve_baseline(skip=skip_calibration, verbose=verbose)
    _baseline_block = _build_baseline_block(_baseline_env)

    _cfg = load_profile(adaptation=adp, profile=prf, scenario=scn,
                        source="specs")
    if method_cfg is not None:
        _mcfg = method_cfg
    else:
        _mcfg = load_method_cfg("experiment")
    _adp = adp or "baseline"

    # deployment + launcher_role: explicit param > method_cfg > default
    if dpl is not None:
        _dpl = str(dpl)
    else:
        _dpl = str(_mcfg.get("deployment", "localhost"))
    if _dpl not in _VALID_DEPLOYMENTS:
        raise ValueError(
            f"dpl={_dpl!r} not recognised; valid modes are "
            f"{_VALID_DEPLOYMENTS}")
    if launcher_role is not None:
        _role = str(launcher_role)
    else:
        _role = str(_mcfg.get("launcher_role", "all"))

    # per-replicate seed derived from root_seed + 'rep_<k>'; R=1 keeps flat log-dir layout
    _replications = int(_mcfg.get("replications", 1))
    _root_seed = int(_mcfg.get("seed", 0))
    _replicates: List[Dict[str, Any]] = []

    for _k in range(_replications):
        if _replications == 1:
            _rep_seed = _root_seed
        else:
            _rep_seed = int(derive_seed(_root_seed, f"rep_{_k}"))
        _rep_mcfg = dict(_mcfg)
        _rep_mcfg["seed"] = _rep_seed

        if wrt:
            # deployment axis splits the artifact tree: localhost/, multiprocess/, remote/
            _base_dir = _RESULTS_DIR / _dpl / _cfg.scenario / _cfg.profile
            if _replications == 1:
                _log_dir = _base_dir
            else:
                _log_dir = _base_dir / f"rep_{_k}"
            _log_dir.mkdir(parents=True, exist_ok=True)
            _run_out = run_async_safe(lambda: execute_one(_cfg,
                                                          _rep_mcfg,
                                                          _adp,
                                                          _log_dir,
                                                          _dpl,
                                                          _role))
            _nds = build_svc_df_from_logs(_cfg,
                                           _log_dir,
                                           _run_out["duration_s"])
        else:
            with tempfile.TemporaryDirectory() as _tmp_str:
                _log_dir = Path(_tmp_str)
                _run_out = run_async_safe(
                    lambda: execute_one(_cfg,
                                        _rep_mcfg,
                                        _adp,
                                        _log_dir,
                                        _dpl,
                                        _role))
                _nds = build_svc_df_from_logs(_cfg,
                                              _log_dir,
                                              _run_out["duration_s"])

        _net = aggregate_net(_nds)
        _req = check_reqs(_nds)
        if wrt:
            _rep_log_dir = str(_log_dir)
        else:
            _rep_log_dir = None
        _replicates.append({
            "replicate_id": _k,
            "seed": _rep_seed,
            "nodes": _nds,
            "network": _net,
            "requirements": _req,
            "probes": _run_out["probes"],
            "saturation_rate": _run_out["saturation_rate"],
            "stopped_reason": _run_out["stopped_reason"],
            "client_effective_rate": _run_out.get(
                "client_effective_rate", 0.0),
            "log_drop_counts": _run_out.get("log_drop_counts", {}),
            "log_dir": _rep_log_dir,
        })

    # top-level fields = replicate 0 for back-compat with flat-envelope consumers; cross-replicate aggregation lives in 07-comparison.ipynb
    _first = _replicates[0]

    _paths: Dict[str, str] = {}
    if wrt:
        _run_out_first = {
            "probes": _first["probes"],
            "saturation_rate": _first["saturation_rate"],
            "stopped_reason": _first["stopped_reason"],
        }
        _paths = _write_results(_cfg, _mcfg, _first["nodes"],
                                _first["network"], _first["requirements"],
                                _run_out_first,
                                baseline=_baseline_block,
                                deployment=_dpl)

    _ans = {
        "config": _cfg,
        "method_config": _mcfg,
        "nodes": _first["nodes"],
        "network": _first["network"],
        "requirements": _first["requirements"],
        "probes": _first["probes"],
        "saturation_rate": _first["saturation_rate"],
        "stopped_reason": _first["stopped_reason"],
        "client_effective_rate": _first.get("client_effective_rate", 0.0),
        "log_drop_counts": _first.get("log_drop_counts", {}),
        "replicates": _replicates,
        "baseline": _baseline_block,
        "paths": _paths,
        "deployment": _dpl,
        "launcher_role": _role,
    }

    # P1.2 invariant: log-buffer overflow == lost observations; warn loud so the operator notices
    if verbose and _ans["log_drop_counts"]:
        print(f"WARNING: per-service log buffer overflowed: "
              f"{_ans['log_drop_counts']}. Raise `SvcCtx.log_maxlen` "
              "or shorten the probe window.")

    return _ans


def _write_results(cfg: NetCfg,
                   method_cfg: Dict[str, Any],
                   nds: pd.DataFrame,
                   net: pd.DataFrame,
                   req: dict,
                   run_out: Dict[str, Any],
                   baseline: Optional[Dict[str, Any]] = None,
                   deployment: str = "localhost") -> Dict[str, str]:
    """*_write_results()* serialise the run envelope to `<results>/<deployment>/<scenario>/<profile>.json`.

    Args:
        cfg (NetCfg): resolved profile + scenario.
        method_cfg (Dict[str, Any]): method config; copied verbatim into the envelope.
        nds (pd.DataFrame): per-service metrics frame.
        net (pd.DataFrame): network aggregate (one row).
        req (dict): R1 / R2 / R3 verdict dict.
        run_out (Dict[str, Any]): async runtime output (probes, saturation, counts).
        baseline (Optional[Dict[str, Any]]): calibration summary block from `_build_baseline_block`.
        deployment (str): `localhost` / `multiprocess` / `remote`; segment in the output path.

    Returns:
        Dict[str, str]: on-disk paths keyed by `profile` and `requirements`.
    """
    _out_dir = _RESULTS_DIR / deployment / cfg.scenario
    _out_dir.mkdir(parents=True, exist_ok=True)

    # strip per-probe `records` (not JSON-serialisable; per-service CSVs cover the same data)
    _probes_out: List[Dict[str, Any]] = []
    for _p in run_out["probes"]:
        _slim = {_k: _v for _k, _v in _p.items() if _k != "records"}
        _probes_out.append(_slim)

    _doc = {
        "profile": cfg.profile,
        "scenario": cfg.scenario,
        "label": cfg.label,
        "method": "experiment",
        "method_config": method_cfg,
        "deployment": deployment,
        "baseline": baseline or {"applied": False,
                                 "baseline_ref": None,
                                 "loopback_median_us": 0.0,
                                 "jitter_p99_us": 0.0,
                                 "age_hours": None},
        "network": net.iloc[0].to_dict(),
        "nodes": nds.to_dict(orient="records"),
        "probes": _probes_out,
        "saturation_rate": run_out["saturation_rate"],
        "stopped_reason": run_out["stopped_reason"],
        "routing": cfg.routing.tolist(),
        "lambda_z": cfg.build_lam_z_vec().tolist(),
    }

    _profile_path = _out_dir / f"{cfg.profile}.json"
    with _profile_path.open("w", encoding="utf-8") as _fh:
        json.dump(_doc, _fh, indent=4, ensure_ascii=False)

    _req_path = _out_dir / "requirements.json"
    with _req_path.open("w", encoding="utf-8") as _fh:
        json.dump(req, _fh, indent=4, ensure_ascii=False)

    _ans = {"profile": str(_profile_path.relative_to(_ROOT)),
            "requirements": str(_req_path.relative_to(_ROOT))}
    return _ans


def main() -> None:
    """*main()* CLI entry point.

    Parses flags, calls `run()`, and prints a one-screen summary plus the paths of any written files.

    Side Effects:
        Prints summary lines to stdout. When `--no-write` is NOT set, writes `<deployment>/<scenario>/<profile>.json` and `<deployment>/<scenario>/requirements.json` under `data/results/experiment/`, plus per-service CSV logs in the same scenario directory.
    """
    _parser = argparse.ArgumentParser(
        description="Architectural experiment for CS-01 TAS.")

    _parser.add_argument("--adaptation",
                         choices=["baseline", "s1", "s2", "aggregate"],
                         default=None,
                         help="adaptation state")
    _parser.add_argument("--profile",
                         choices=["dflt", "opti"],
                         default=None,
                         help="explicit profile file stem")
    _parser.add_argument("--scenario",
                         default=None,
                         help="explicit scenario name")
    _parser.add_argument("--no-write",
                         action="store_true",
                         help="skip writing result files")
    _parser.add_argument("--skip-calibration",
                         action="store_true",
                         help=("bypass the pre-run calibration gate; "
                               "a warning is printed and the baseline "
                               "is NOT subtracted from reported latencies"))
    _parser.add_argument("--deployment",
                         choices=list(_VALID_DEPLOYMENTS),
                         default=None,
                         help=("deployment mode override; defaults to "
                               "method_cfg['deployment'] (typically 'localhost'). "
                               "Non-localhost modes require launch_services.py."))
    _parser.add_argument("--launcher-role",
                         choices=["all", "client", "composite", "atomic",
                                  "composite-atomic"],
                         default=None,
                         help=("subset of services this driver spawns; "
                               "only meaningful in non-localhost deployments"))

    _args = _parser.parse_args()

    _result = run(adp=_args.adaptation,
                  prf=_args.profile,
                  scn=_args.scenario,
                  wrt=not _args.no_write,
                  skip_calibration=_args.skip_calibration,
                  dpl=_args.deployment,
                  launcher_role=_args.launcher_role)

    _cfg = _result["config"]
    _net = _result["network"].iloc[0]
    _req = _result["requirements"]

    print(f"profile={_cfg.profile}  scenario={_cfg.scenario}")
    print(f"label: {_cfg.label}")
    _base = _result.get("baseline", {})
    if _base.get("applied"):
        _floor_ms = float(_base["loopback_median_us"]) / 1000.0
        _band_ms = float(_base["jitter_p99_us"]) / 1000.0
        _age = _base.get("age_hours")
        print(f"baseline: loopback_median={_floor_ms:.3f}ms  "
              f"jitter_p99={_band_ms:.3f}ms  "
              f"age={_age:.1f}h  "
              f"ref={_base.get('baseline_ref')}")
        print("reported = measured - loopback_median +/- jitter_p99")
    else:
        print("baseline: NOT APPLIED (--skip-calibration)")
    print(f"  nodes={int(_net['nodes'])}  "
          f"avg_rho={_net['avg_rho']:.4f}  "
          f"max_rho={_net['max_rho']:.4f}  "
          f"W_net={_net['W_net']:.6f}s")

    print("requirements:")
    for _k, _v in _req.items():
        if _v["pass"]:
            _status = "PASS"
        else:
            _status = "FAIL"
        _val = _v["value"]
        if isinstance(_val, (int, float)):
            _val_str = f"{_val:.6g}"
        else:
            _val_str = "n/a"
        print(f"  {_k}: {_status}  ({_v['metric']}={_val_str})")

    print("ramp probes:")
    for _p in _result["probes"]:
        print(f"  rate={_p['rate']:>8.1f}  n={_p['total']:>4d}  "
              f"infra_fail={_p['infra_fail_rate']:.3f}  "
              f"biz_fail={_p['business_fail_rate']:.3f}  "
              f"stopped={_p['stopped_reason']}")
    if _result["saturation_rate"] is not None:
        print(f"saturation at rate={_result['saturation_rate']}")

    if _result["paths"]:
        for _k, _p in _result["paths"].items():
            print(f"  wrote {_k}: {_p}")


if __name__ == "__main__":
    main()

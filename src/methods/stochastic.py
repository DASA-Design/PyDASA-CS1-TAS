# -*- coding: utf-8 -*-
"""
Module stochastic.py
====================

Stochastic (SimPy DES) method orchestrator for the CS-01 TAS case study. Mirrors the analytic method's contract call-for-call so the two can be compared directly downstream.

Public API:
    - `run(adp, prf, scn, wrt)` loads a resolved `NetworkConfig` (same `profile/*.json` as analytic) plus the stochastic method config (`data/config/method/stochastic.json`), runs the DES engine (`src.stochastic.solve_network`), and returns per-node metrics + network aggregate + R1 / R2 / R3 verdict.

Aggregation and threshold checks reuse `src.analytic.metrics` (`aggregate_network` / `check_requirements`) since the math is identical across the two methods.

*IMPORTANT:* the engine runs in SimPy SECONDS; the method config declares the horizon and warmup in INVOCATIONS. Conversion happens in `src.stochastic.simulation.solve_network`.

CLI::

    python -m src.methods.stochastic --adaptation baseline
    python -m src.methods.stochastic --adaptation s1 --profile opti
    python -m src.methods.stochastic  # uses _setpoint
"""
# native python modules
from __future__ import annotations

import argparse
import json
from pathlib import Path

# data types
from typing import Any, Dict, Optional

# scientific stack
import pandas as pd

# local modules
from src.analytic.metrics import aggregate_network, check_requirements
from src.io import NetworkConfig, load_method_config, load_profile
from src.stochastic import solve_network


_ROOT = Path(__file__).resolve().parents[2]
_RESULTS_DIR = _ROOT / "data" / "results" / "stochastic"


def run(adp: Optional[str] = None,
        prf: Optional[str] = None,
        scn: Optional[str] = None,
        wrt: bool = True,
        method_cfg: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """*run()* solve the stochastic Jackson network for one (profile, scenario) pair.

    Optionally writes the JSON artifacts to disk.

    Args:
        adp (Optional[str]): adaptation value; one of `baseline`, `s1`, `s2`, `aggregate`. Resolves to (profile, scenario) via `src.io.load_profile`.
        prf (Optional[str]): profile file stem (`dflt` or `opti`); overrides `adp`'s implied profile when paired with `scn`.
        scn (Optional[str]): explicit scenario name within the profile.
        wrt (bool): if True, write JSON artifacts under `data/results/stochastic/<scenario>/`. Defaults to True.
        method_cfg (Optional[Dict[str, Any]]): inline override for the stochastic method parameters (`seed`, `horizon_invocations`, `warmup_invocations`, `replications`, ...). When `None`, loads `data/config/method/stochastic.json`. Useful for tests that want a tiny horizon so the run finishes in seconds.

    Returns:
        Dict[str, Any]: result dict with keys:

            - `config` (NetworkConfig): resolved config.
            - `method_config` (Dict): stochastic method parameters.
            - `nodes` (pd.DataFrame): per-node frame (analytic schema plus `_std` columns).
            - `network` (pd.DataFrame): network aggregate (one row).
            - `requirements` (Dict): R1 / R2 / R3 verdict dict.
            - `paths` (Dict[str, str]): written file paths; empty when `wrt=False`.
    """
    # load the profile (artifact nodes + routing); method config is either passed in (tests) or loaded from disk (CLI / notebook)
    _cfg = load_profile(adaptation=adp, profile=prf, scenario=scn)
    if method_cfg is not None:
        _method_cfg = method_cfg
    else:
        _method_cfg = load_method_config("stochastic")

    # run the DES engine end-to-end
    _nds = solve_network(_cfg, _method_cfg)
    _net = aggregate_network(_nds)
    _req = check_requirements(_nds)

    # write the result envelope when requested
    _paths: Dict[str, str] = {}
    if wrt:
        _paths = _write_results(_cfg, _method_cfg, _nds, _net, _req)

    return {
        "config": _cfg,
        "method_config": _method_cfg,
        "nodes": _nds,
        "network": _net,
        "requirements": _req,
        "paths": _paths,
    }


def _write_results(cfg: NetworkConfig,
                   method_cfg: Dict[str, Any],
                   nds: pd.DataFrame,
                   net: pd.DataFrame,
                   req: dict) -> Dict[str, str]:
    """*_write_results()* serialise the solver outputs to disk in the PyDASA-style envelope used across methods.

    Args:
        cfg (NetworkConfig): resolved network configuration.
        method_cfg (Dict[str, Any]): stochastic method params; copied verbatim into the result envelope so the run is fully self-describing on disk.
        nds (pd.DataFrame): per-node metrics frame.
        net (pd.DataFrame): network aggregate (one row).
        req (dict): R1 / R2 / R3 verdict dict.

    Returns:
        Dict[str, str]: on-disk paths of the two written files, keyed by `profile` and `requirements`, relative to the repo root.
    """
    _out_dir = _RESULTS_DIR / cfg.scenario
    _out_dir.mkdir(parents=True, exist_ok=True)

    # topology carried alongside metrics so the blob is self-contained for later path reconstruction
    _doc = {
        "profile": cfg.profile,
        "scenario": cfg.scenario,
        "label": cfg.label,
        "method": "stochastic",
        "method_config": method_cfg,
        "network": net.iloc[0].to_dict(),
        "nodes": nds.to_dict(orient="records"),
        "routing": cfg.routing.tolist(),
        "lambda_z": cfg.build_lam_z_vec().tolist(),
    }

    _profile_path = _out_dir / f"{cfg.profile}.json"
    with _profile_path.open("w", encoding="utf-8") as _fh:
        json.dump(_doc, _fh, indent=4, ensure_ascii=False)

    _req_path = _out_dir / "requirements.json"
    with _req_path.open("w", encoding="utf-8") as _fh:
        json.dump(req, _fh, indent=4, ensure_ascii=False)

    return {
        "profile": str(_profile_path.relative_to(_ROOT)),
        "requirements": str(_req_path.relative_to(_ROOT)),
    }


def main() -> None:
    """*main()* CLI entry point.

    Parses command-line flags, calls `run()`, and prints a concise one-screen summary plus the paths of any written files.
    """
    _parser = argparse.ArgumentParser(
        description="Stochastic SimPy DES solver for CS-01 TAS.",)

    _parser.add_argument(
        "--adaptation",
        choices=["baseline", "s1", "s2", "aggregate"],
        default=None,
        help=("adaptation state (resolves to profile + scenario); "
              "defaults to the profile's _setpoint"),)

    _parser.add_argument(
        "--profile",
        choices=["dflt", "opti"],
        default=None,
        help="explicit profile file stem (overrides adaptation's profile)",)

    _parser.add_argument(
        "--scenario",
        default=None,
        help="explicit scenario name within the profile",)

    _parser.add_argument(
        "--no-write",
        action="store_true",
        help="skip writing result files (useful for dry runs)",)

    _args = _parser.parse_args()

    _result = run(
        adp=_args.adaptation,
        prf=_args.profile,
        scn=_args.scenario,
        wrt=not _args.no_write,)

    _cfg = _result["config"]
    _net = _result["network"].iloc[0]
    _req = _result["requirements"]
    _mc = _result["method_config"]

    # header block
    print(f"profile={_cfg.profile}  scenario={_cfg.scenario}")
    print(f"label: {_cfg.label}")
    print(f"seed={_mc['seed']}  reps={_mc['replications']}  "
          f"horizon={_mc['horizon_invocations']} inv.  "
          f"warmup={_mc['warmup_invocations']} inv.")

    # network-wide summary
    print(f"  nodes={int(_net['nodes'])}  "
          f"avg_rho={_net['avg_rho']:.4f}  "
          f"max_rho={_net['max_rho']:.4f}  "
          f"W_net={_net['W_net']:.6f}s")

    # R1 / R2 / R3 verdict
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

    # written-file paths
    if _result["paths"]:
        for _k, _p in _result["paths"].items():
            print(f"  wrote {_k}: {_p}")


if __name__ == "__main__":
    main()

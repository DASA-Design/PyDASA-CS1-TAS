# -*- coding: utf-8 -*-
"""
Module analytic.py
==================

Analytic method orchestrator for the CS-01 TAS case study.

Loads a resolved `NetworkConfig`, solves the Jackson network in closed form via M/M/c/K at each node, emits node + network metrics as a single PyDASA-style JSON, and writes an R1 / R2 / R3 verdict alongside.

Public API:
    - `run(adp, prf, scn, wrt)` standard orchestrator contract.
    - `main()` CLI entry point.

*IMPORTANT:* the written result blob carries the full `routing` matrix and `lambda_z` vector so downstream consumers can reconstruct node paths without re-opening the config files.

CLI::

    python -m src.methods.analytic --adaptation baseline
    python -m src.methods.analytic --adaptation s1 --profile opti
    python -m src.methods.analytic  # uses _setpoint

# TODO: wire a real cost model (from the service catalogue) through the verdict writer so R3 carries a numeric value.
"""
# native python modules
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Dict, Optional

# scientific stack
import pandas as pd

# local modules
from src.analytic import aggregate_network, check_requirements, solve_network
from src.io import NetworkConfig, load_profile


_ROOT = Path(__file__).resolve().parents[2]
_RESULTS_DIR = _ROOT / "data" / "results" / "analytic"


def _build_vars_from_nodes(nds: pd.DataFrame,
                           cfg: NetworkConfig) -> Dict[str, dict]:
    """*_build_vars_from_nodes()* turn the solved node DataFrame into a PACS-style `variables` dict.

    One entry per artifact; each carries the original config variables plus updated `_setpoint` / `_data` on the output variables (lambda, chi, L, Lq, W, Wq) from the solver. `chi` is the effective throughput `lambda * (1 - epsilon)`.

    Args:
        nds (pd.DataFrame): per-node metrics frame produced by `solve_network()`.
        cfg (NetworkConfig): resolved network configuration; provides the PACS Variable dict for each artifact.

    Returns:
        Dict[str, dict]: PACS-style `variables` block keyed by artifact key. Each entry carries `name`, `type`, `lambda_z`, `L_z`, `rho`, and a `vars` sub-dict with refreshed setpoints.
    """
    _out: Dict[str, dict] = {}

    # walk artifacts in declared order; row index matches node id
    for _i, _a in enumerate(cfg.artifacts):
        _row = nds.iloc[_i]

        # copy the config variables so we do not mutate the input dict
        _vars = {_sym: dict(_var) for _sym, _var in _a.vars.items()}

        # LaTeX subscript form of the artifact key (after the key migration this is just `_a.key` verbatim, e.g. `TAS_{1}`)
        _sub = _a._sub()

        # calculate output-variable refresh values from the solver row. Variable names follow the post-migration convention: `L_{q, ...}` / `W_{q, ...}` (split q-subscript, valid LaTeX)
        _updates = {
            f"\\lambda_{{{_sub}}}": float(_row["lambda"]),
            f"L_{{{_sub}}}": float(_row["L"]),
            f"L_{{q, {_sub}}}": float(_row["Lq"]),
            f"W_{{{_sub}}}": float(_row["W"]),
            f"W_{{q, {_sub}}}": float(_row["Wq"]),
        }

        # chi = lambda * (1 - epsilon); effective throughput under faults
        _eps = _a.vars.get(f"\\epsilon_{{{_sub}}}", {}).get("_setpoint", 0.0)
        _updates[f"\\chi_{{{_sub}}}"] = float(_row["lambda"]) * (1 - _eps)

        # refresh `_setpoint` and `_data` in place on the copied Vars
        for _sym, _val in _updates.items():
            if _sym in _vars:
                _vars[_sym]["_setpoint"] = _val
                _vars[_sym]["_data"] = [_val]

        # record the per-artifact entry in the output dict
        _out[_a.key] = {
            "name": _a.name,
            "type": _a.type_,
            "lambda_z": _a.lambda_z,
            "L_z": _a.L_z,
            "rho": float(_row["rho"]),
            "vars": _vars,
        }

    return _out


def run(adp: Optional[str] = None,
        prf: Optional[str] = None,
        scn: Optional[str] = None,
        wrt: bool = True) -> Dict[str, Any]:
    """*run()* solve the analytic Jackson network for one (profile, scenario) pair.

    Optionally writes the JSON artifacts to disk.

    Args:
        adp (Optional[str]): adaptation value; one of `baseline`, `s1`, `s2`, `aggregate`. Resolves to (profile, scenario) via `src.io.load_profile`.
        prf (Optional[str]): profile file stem (`dflt` or `opti`); overrides `adp`'s implied profile when paired with `scn`.
        scn (Optional[str]): explicit scenario name within the profile.
        wrt (bool): if True, write JSON artifacts to `data/results/analytic/<scenario>/`. Defaults to True.

    Returns:
        Dict[str, Any]: result dict with keys:

            - `config` (NetworkConfig): resolved config (for display).
            - `nodes` (pd.DataFrame): per-node DataFrame.
            - `network` (pd.DataFrame): network aggregate (one row).
            - `requirements` (Dict): R1 / R2 / R3 verdict dict.
            - `paths` (Dict[str, str]): written file paths; empty when `wrt=False`.
    """
    # resolve the config then solve the network end-to-end
    _cfg = load_profile(adaptation=adp, profile=prf, scenario=scn)
    _nds = solve_network(_cfg)
    _net = aggregate_network(_nds)
    _req = check_requirements(_nds)

    # write results only when the caller asked for it
    _paths: Dict[str, str] = {}
    if wrt:
        _paths = _write_results(_cfg, _nds, _net, _req)

    return {
        "config": _cfg,
        "nodes": _nds,
        "network": _net,
        "requirements": _req,
        "paths": _paths,
    }


def _write_results(cfg: NetworkConfig,
                   nds: pd.DataFrame,
                   net: pd.DataFrame,
                   req: dict) -> Dict[str, str]:
    """*_write_results()* serialises the solver outputs to disk in the PACS-style result envelope.

    Args:
        cfg (NetworkConfig): resolved network configuration.
        nds (pd.DataFrame): per-node metrics frame.
        net (pd.DataFrame): network aggregate frame (one row).
        req (dict): R1 / R2 / R3 verdict dict.

    Returns:
        Dict[str, str]: on-disk paths of the two written files, keyed by `profile` and `requirements`, relative to the repo root.
    """
    # prepare the scenario-scoped output directory
    _out_dir = _RESULTS_DIR / cfg.scenario
    _out_dir.mkdir(parents=True, exist_ok=True)

    # assemble the result envelope. topology (routing + lambda_z) is carried alongside metrics so the blob is self-contained for later path reconstruction without re-reading the config file.
    _doc = {
        "profile": cfg.profile,
        "scenario": cfg.scenario,
        "label": cfg.label,
        "method": "analytic",
        "network": net.iloc[0].to_dict(),
        "variables": _build_vars_from_nodes(nds, cfg),
        "routing": cfg.routing.tolist(),
        "lambda_z": cfg.build_lam_z_vec().tolist(),
    }

    # write the per-profile result blob
    _profile_path = _out_dir / f"{cfg.profile}.json"
    with _profile_path.open("w", encoding="utf-8") as _fh:
        json.dump(_doc, _fh, indent=4, ensure_ascii=False)

    # write the R1 / R2 / R3 verdict (profile-agnostic, one per run)
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
    # build the argument parser with the four CLI flags
    _parser = argparse.ArgumentParser(
        description="Analytic Jackson-network solver for CS-01 TAS.",)

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

    # run the solver end-to-end with the parsed flags
    _result = run(
        adp=_args.adaptation,
        prf=_args.profile,
        scn=_args.scenario,
        wrt=not _args.no_write,)

    # unpack the result blob for the summary print
    _cfg = _result["config"]
    _net = _result["network"].iloc[0]
    _req = _result["requirements"]

    # header: which (profile, scenario) was solved
    print(f"profile={_cfg.profile}  scenario={_cfg.scenario}")
    print(f"label: {_cfg.label}")

    # network-wide summary line
    print(f"  nodes={int(_net['nodes'])}  "
          f"avg_rho={_net['avg_rho']:.4f}  "
          f"max_rho={_net['max_rho']:.4f}  "
          f"W_net={_net['W_net']:.6f}s")

    # per-requirement PASS / FAIL with the numeric value
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

    # written-file paths (only when wrt=True)
    if _result["paths"]:
        for _k, _p in _result["paths"].items():
            print(f"  wrote {_k}: {_p}")


if __name__ == "__main__":
    main()

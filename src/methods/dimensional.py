# -*- coding: utf-8 -*-
"""
Module dimensional.py
=====================

Dimensional method orchestrator for the CS-01 TAS case study. Walks the 13 (or 16) artifacts in a resolved `NetCfg`, builds a PyDASA `AnalysisEngine` per artifact, derives Pi-groups via Buckingham's theorem, applies the operationally meaningful coefficient specs (theta, sigma, eta, phi) from `data/config/method/dimensional.json`, runs a symbolic sensitivity pass at the variable means, and emits a PyDASA-style JSON.

The dimensional method is static (no `requirements.json`); it characterises the design space, while R1 / R2 verdicts come from the analytic / stochastic methods and are aggregated by `comparison`.

Public API:
    - `run(adp, prf, scn, wrt)` resolves the profile + method config, loops artifacts, and returns per-artifact `pi_groups`, `coefficients`, `sensitivity` blocks.

Private helpers:
    - `_analyse_artifact(artifact, schema, ...)` full DA workflow on one artifact.
    - `_write_results(cfg, method_cfg, results)` serialises the envelope to `data/results/dimensional/<scenario>/<profile>.json`.

CLI::

    python -m src.methods.dimensional --adaptation baseline
    python -m src.methods.dimensional --adaptation s1 --profile opti
    python -m src.methods.dimensional  # uses _setpoint
"""
# native python modules
from __future__ import annotations

import argparse
import json
from pathlib import Path

# data types
from typing import Any, Dict, Optional

# pydasa library
from pydasa.dimensional.vaschy import Schema

# local modules
from src.analytic import solve_network
from src.dimensional import (analyse_symbolic,
                             build_engine,
                             build_schema,
                             derive_coefs)
from src.io import ArtifactSpec, NetCfg, load_method_cfg, load_profile


_ROOT = Path(__file__).resolve().parents[2]
_RESULTS_DIR = _ROOT / "data" / "results" / "dimensional"


def _refresh_artifact_vars(cfg: NetCfg, nds) -> None:
    """*_refresh_artifact_vars()* overwrite per-artifact operational variables with values from the analytic solve.

    The dimensional method runs on `cfg.artifacts`, whose `vars` come straight from the profile JSON. For nodes that the profile carries as placeholders (typical when a node is inactive under one adaptation but active under another), the placeholder propagates into PyDASA's `_std_setpoint`/`_mean` and produces wrong coefficient setpoints. This refresh replaces lambda, chi, L, Lq, W, Wq with the values just computed by `solve_network()` so PyDASA reads the actual operating point.

    Args:
        cfg (NetCfg): resolved network configuration (artifacts list is mutated in place).
        nds (pd.DataFrame): per-node metrics frame from `src.analytic.solve_network`.
    """
    for _i, _a in enumerate(cfg.artifacts):
        _row = nds.iloc[_i]
        _sub = _a.format_sub()
        _eps = _a.vars.get(f"\\epsilon_{{{_sub}}}", {}).get("_setpoint", 0.0)
        _d_req = _a.vars.get(f"d_{{{_sub}}}", {}).get("_setpoint", 0.0)
        _updates = {
            f"\\lambda_{{{_sub}}}": float(_row["lambda"]),
            f"L_{{{_sub}}}": float(_row["L"]),
            f"L_{{q, {_sub}}}": float(_row["Lq"]),
            f"W_{{{_sub}}}": float(_row["W"]),
            f"W_{{q, {_sub}}}": float(_row["Wq"]),
            f"\\chi_{{{_sub}}}": float(_row["lambda"]) * (1 - _eps),
            f"M_{{act_{{{_sub}}}}}": float(_row["L"]) * _d_req,
        }
        for _sym, _val in _updates.items():
            if _sym in _a.vars:
                _a.vars[_sym]["_setpoint"] = _val
                _a.vars[_sym]["_std_setpoint"] = _val
                _a.vars[_sym]["_mean"] = _val
                _a.vars[_sym]["_std_mean"] = _val
                _a.vars[_sym]["_data"] = [_val]


def _analyse_artifact(artifact: ArtifactSpec,
                      schema: Schema,
                      coef_specs: list[dict[str, Any]],
                      sens_cfg: dict[str, Any]) -> Dict[str, Any]:
    """*_analyse_artifact()* run the full DA workflow on one artifact.

    Builds an engine from the artifact's Variable dict, derives Pi-groups, applies the named coefficient specs, evaluates setpoints, and runs one symbolic sensitivity pass.

    Args:
        artifact (ArtifactSpec): one resolved artifact from the `NetCfg`.
        schema (Schema): framework schema built once for the full run.
        coef_specs (list[dict[str, Any]]): coefficient specs from the method config.
        sens_cfg (dict[str, Any]): sensitivity sub-config keyed by `val_type` and `cat`.

    Returns:
        Dict[str, Any]: per-artifact block with `name`, `type`, `lambda_z`, `L_z`, `pi_groups`, `coefficients`, `sensitivity`.
    """
    _eng = build_engine(artifact.key, artifact.vars, schema)
    _eng.run_analysis()
    # raw Pi-groups need an explicit setpoint pass; PyDASA leaves them lazy after run_analysis
    _pi_keys = [_k for _k in _eng.coefficients.keys() if _k.startswith("\\Pi_")]
    for _k in _pi_keys:
        _eng.coefficients[_k].calculate_setpoint()
    _der = derive_coefs(_eng, coef_specs, artifact_key=artifact.key)
    for _c in _der.values():
        _c.calculate_setpoint()
    _sens = analyse_symbolic(_eng, schema,
                             val_type=sens_cfg.get("val_type", "mean"),
                             cat=sens_cfg.get("cat", "SYM"))
    _pi_out = {_k: {"expr": str(_eng.coefficients[_k].pi_expr),
                    "setpoint": _eng.coefficients[_k].setpoint,
                    "var_dims": dict(_eng.coefficients[_k].var_dims)}
               for _k in _pi_keys}

    _co_out = {_s: {"expr": str(_c.pi_expr),
                    "setpoint": _c.setpoint,
                    "var_dims": dict(_c.var_dims),
                    "name": _c.name,
                    "description": _c.description}
               for _s, _c in _der.items()}

    return {
        "name": artifact.name,
        "type": artifact.type_,
        "lambda_z": artifact.lambda_z,
        "L_z": artifact.L_z,
        "pi_groups": _pi_out,
        "coefficients": _co_out,
        "sensitivity": _sens,
    }


def run(adp: Optional[str] = None,
        prf: Optional[str] = None,
        scn: Optional[str] = None,
        wrt: bool = True,
        method_cfg: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """*run()* analyse every artifact of one (profile, scenario) pair dimensionally.

    Optionally writes the JSON artifact to disk.

    Args:
        adp (Optional[str]): adaptation value; one of `baseline`, `s1`, `s2`, `aggregate`. Resolves to (profile, scenario) via `src.io.load_profile`.
        prf (Optional[str]): profile file stem (`dflt` or `opti`); overrides `adp`'s implied profile when paired with `scn`.
        scn (Optional[str]): explicit scenario name within the profile.
        wrt (bool): if True, write JSON artifact to `data/results/dimensional/<scenario>/<profile>.json`. Defaults to True.
        method_cfg (Optional[Dict[str, Any]]): inline override for the dimensional method parameters (`fdus`, `coefficients`, `sensitivity`, ...). When `None`, loads `data/config/method/dimensional.json`. Useful for tests that want a trimmed coefficient spec.

    Returns:
        Dict[str, Any]: result dict with keys:

            - `config` (NetCfg): resolved config.
            - `method_config` (Dict): dimensional method parameters.
            - `artifacts` (Dict[str, Dict]): per-artifact analysis blocks keyed by artifact key.
            - `paths` (Dict[str, str]): written file paths; empty when `wrt=False`.
    """
    _cfg = load_profile(adaptation=adp, profile=prf, scenario=scn)
    if method_cfg is not None:
        _mcfg = method_cfg
    else:
        _mcfg = load_method_cfg("dimensional")
    # Solve the analytic Jackson network first so we can refresh the operational variables (lambda, chi, L, Lq, W, Wq) on every artifact before PyDASA reads them. The config profile may carry placeholder values for swap-out nodes (e.g., L = 6 at MAS_{3}/AS_{3}/DS_{3} in opti.json, which are inactive under S2/aggregate but active under S1); without this refresh, those placeholders propagate into PyDASA's coefficient setpoints and produce spurious dimensional readings.
    _nds = solve_network(_cfg)
    _refresh_artifact_vars(_cfg, _nds)
    # one schema reused across every artifact: PyDASA validates the framework once
    _sch = build_schema(_mcfg["fdus"])
    _arts: Dict[str, Dict[str, Any]] = {}
    for _a in _cfg.artifacts:
        _arts[_a.key] = _analyse_artifact(_a, _sch,
                                          _mcfg["coefficients"],
                                          _mcfg["sensitivity"])
    _paths: Dict[str, str] = {}
    if wrt:
        _paths = _write_results(_cfg, _mcfg, _arts)

    return {
        "config": _cfg,
        "method_config": _mcfg,
        "artifacts": _arts,
        "paths": _paths,
    }


def _write_results(cfg: NetCfg,
                   method_cfg: Dict[str, Any],
                   artifacts: Dict[str, Dict[str, Any]]) -> Dict[str, str]:
    """*_write_results()* serialise the dimensional-analysis outputs to disk in the PACS-style result envelope.

    Args:
        cfg (NetCfg): resolved network configuration.
        method_cfg (Dict[str, Any]): dimensional method params; copied verbatim into the result envelope so the run is self-describing on disk.
        artifacts (Dict[str, Dict[str, Any]]): per-artifact analysis blocks.

    Returns:
        Dict[str, str]: on-disk paths of the written file, keyed by `profile`, relative to the repo root.
    """
    _out_dir = _RESULTS_DIR / cfg.scenario
    _out_dir.mkdir(parents=True, exist_ok=True)
    # routing + lambda_z embedded so the blob reconstructs cross-artifact without re-reading configs
    _doc = {
        "profile": cfg.profile,
        "scenario": cfg.scenario,
        "label": cfg.label,
        "method": "dimensional",
        "method_config": method_cfg,
        "artifacts": artifacts,
        "routing": cfg.routing.tolist(),
        "lambda_z": cfg.build_lam_z_vec().tolist(),
    }

    _profile_path = _out_dir / f"{cfg.profile}.json"
    with _profile_path.open("w", encoding="utf-8") as _fh:
        json.dump(_doc, _fh, indent=4, ensure_ascii=False)

    return {"profile": str(_profile_path.relative_to(_ROOT))}


def main() -> None:
    """*main()* CLI entry point.

    Parses command-line flags, calls `run()`, and prints a concise one-screen summary plus the path of any written file.
    """
    _parser = argparse.ArgumentParser(
        description="Dimensional-analysis solver for CS-01 TAS.",)
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
    _arts = _result["artifacts"]
    _mc = _result["method_config"]
    print(f"profile={_cfg.profile}  scenario={_cfg.scenario}")
    print(f"label: {_cfg.label}")
    print(f"framework={_mc['fdus'][0]['_fwk']}  "
          f"fdus={len(_mc['fdus'])}  "
          f"coefficients={len(_mc['coefficients'])}  "
          f"sensitivity={_mc['sensitivity']['cat']}@{_mc['sensitivity']['val_type']}")
    print(f"artifacts ({len(_arts)}):")
    for _k, _a in _arts.items():
        _co = _a["coefficients"]
        _vals = "  ".join(
            f"{_sym.split('_')[0].lstrip(chr(92))}={_co[_sym]['setpoint']:.4g}"
            for _sym in _co.keys()
        )
        print(f"  {_k:<14} {_vals}")
    if _result["paths"]:
        for _k, _p in _result["paths"].items():
            print(f"  wrote {_k}: {_p}")


if __name__ == "__main__":
    main()

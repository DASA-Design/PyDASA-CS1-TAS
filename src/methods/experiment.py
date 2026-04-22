# -*- coding: utf-8 -*-
"""
Module experiment.py
====================

Architectural experiment orchestrator: method 4 of the CS-01 TAS
pipeline.

Spins up a FastAPI microservice replication of the TAS topology,
drives a deterministic-rate client ramp through `TAS_{1}`, collects
per-invocation logs per service, and produces the standard envelope
shape (per-node DataFrame + network aggregate + R1 / R2 / R3
verdict).

The experiment validates DASA's **technology-agnosticism**: the
analytic / dimensional predictions should hold on a completely
independent stack. It does NOT reproduce the original authors'
ReSeP / Java numbers.

Public API:
    - `run(adp, prf, scn, wrt, method_cfg=None)` standard
      orchestrator contract.
    - `main()` CLI entry point.

CLI::

    python -m src.methods.experiment --adaptation baseline
    python -m src.methods.experiment --adaptation s1 --profile opti
"""
# native python modules
from __future__ import annotations

import argparse
import asyncio
import json
import tempfile
from pathlib import Path

# data types
from typing import Any, Dict, List, Optional

# scientific stack
import numpy as np
import pandas as pd

# local modules
from src.analytic.metrics import aggregate_network, check_requirements
from src.experiment.client import ClientConfig
from src.experiment.client import ClientSimulator
from src.experiment.client import build_ramp_cfg
from src.experiment.launcher import ExperimentLauncher
from src.io import NetworkConfig, load_method_config, load_profile


_ROOT = Path(__file__).resolve().parents[2]
_RESULTS_DIR = _ROOT / "data" / "results" / "experiment"


def _service_df_from_logs(cfg: NetworkConfig,
                          log_dir: Path,
                          duration_s: float) -> pd.DataFrame:
    """*_service_df_from_logs()* build a per-service metrics DataFrame from the flushed CSV logs.

    Cleanly separates two failure modes:

        - `epsilon`: Bernoulli business failure
          `count(200 AND success=False) / count(200)`. Directly
          comparable to the profile's `_setpoint` for epsilon (what
          R1 validates).
        - `buffer_reject_rate`: `count(503) / count(all)`. Capacity
          overflow, not a reliability signal.

    Both are stored on the DataFrame; downstream R1 checks use
    `epsilon` only.

    Args:
        cfg (NetworkConfig): resolved profile + scenario.
        log_dir (Path): directory carrying `<service>.csv` files.
        duration_s (float): wall-clock duration the measurement
            covers; used to compute lambda.

    Returns:
        pd.DataFrame: one row per artifact with the analytic-schema
            columns plus `buffer_reject_rate`.
    """
    _rows: List[Dict[str, Any]] = []

    for _idx, _a in enumerate(cfg.artifacts):
        _fname = _a.key.replace("{", "_").replace("}", "_").replace(",", "_")
        _csv = log_dir / f"{_fname}.csv"

        _lam = 0.0
        _rho = 0.0
        _L = 0.0
        _Lq = 0.0
        _W = 0.0
        _Wq = 0.0
        _eps = 0.0
        _bfr = 0.0

        if _csv.exists():
            _df = pd.read_csv(_csv)
            _n = len(_df)

            # split by failure mode
            _completed = _df[_df["status_code"] == 200]
            _business_fails = _completed[~_completed["success"].astype(bool)]
            _infra_fails = _df[_df["status_code"] != 200]

            # lambda = total invocations received per second
            _lam = _n / duration_s if duration_s > 0 else 0.0

            # epsilon is business-level only; compares to profile's setpoint
            _eps = (len(_business_fails) / len(_completed)
                    if len(_completed) > 0 else 0.0)

            # buffer_reject_rate tracks infrastructure overflow separately
            _bfr = len(_infra_fails) / _n if _n > 0 else 0.0

            # timing from successful completions only (failed ones have no meaningful W)
            _succ = _completed[_completed["success"]]
            if len(_succ) > 0:
                _start = pd.to_numeric(_succ["start_ts"], errors="coerce")
                _end = pd.to_numeric(_succ["end_ts"], errors="coerce")
                _recv = pd.to_numeric(_succ["recv_ts"], errors="coerce")
                _W = float(np.nanmean(_end - _recv))
                _Wq = float(np.nanmean(_start - _recv))

            _L = _lam * _W
            _Lq = _lam * _Wq

            # utilisation via c_used_at_start (PASTA: Poisson arrivals see
            # time averages, so arrival-time samples approximate time average)
            if len(_succ) > 0 and "c_used_at_start" in _succ.columns:
                _used = pd.to_numeric(_succ["c_used_at_start"], errors="coerce")
                _rho = float(np.nanmean(_used) / max(int(_a.c), 1))

        _rows.append({
            "node": _idx,
            "key": _a.key,
            "name": _a.name,
            "type": _a.type_,
            "lambda": _lam,
            "mu": float(_a.mu),
            "c": int(_a.c),
            "K": int(_a.K),
            "rho": _rho,
            "L": _L,
            "Lq": _Lq,
            "W": _W,
            "Wq": _Wq,
            "epsilon": _eps,
            "buffer_reject_rate": _bfr,
        })

    return pd.DataFrame(_rows)


async def _async_run(cfg: NetworkConfig,
                     method_cfg: Dict[str, Any],
                     adp: str,
                     log_dir: Path) -> Dict[str, Any]:
    """*_async_run()* drive one adaptation end-to-end: launch mesh, snapshot effective config (FR-3.3), run ramp, flush logs.

    Args:
        cfg (NetworkConfig): resolved profile + scenario.
        method_cfg (Dict[str, Any]): experiment method config.
        adp (str): adaptation label (`baseline` / `s1` / `s2` /
            `aggregate`).
        log_dir (Path): directory that receives the per-service CSVs
            and the config snapshot.

    Returns:
        Dict[str, Any]: ramp output plus `duration_s` and
            `service_log_counts`.
    """
    async with ExperimentLauncher(cfg=cfg,
                                  method_cfg=method_cfg,
                                  adaptation=adp) as _lnc:
        # client config derived from method_cfg + launcher's kind-weights
        # (which the launcher computed from the profile's routing matrix)
        _seed = int(method_cfg["seed"])
        _sizes_by_kind = dict(method_cfg.get("request_size_bytes", {}))
        # scalar fallback kept for back-compat with tests that don't define
        # a full sizes-by-kind map; defaults to the analyse_request size
        _req_size = int(_sizes_by_kind.get("analyse_request", 256))
        _client_cfg = ClientConfig(
            entry_service="TAS_{1}",
            seed=_seed,
            request_size_bytes=_req_size,
            request_sizes_by_kind=_sizes_by_kind,
            kind_weights=dict(_lnc.kind_weights),
            ramp=build_ramp_cfg(method_cfg["ramp"]),
        )
        _sim = ClientSimulator(_lnc.client, _lnc.registry, _client_cfg)

        # FR-3.3: emit config.json BEFORE the ramp starts so if the run
        # crashes the snapshot still reflects what was about to run.
        td = dict(method_cfg.get("request_size_bytes", {}))
        _lnc.snapshot_config(log_dir,
                             extras={
                                 "seed": _seed,
                                 "request_size_bytes": _req_size,
                                 "request_size_bytes_by_kind": td,
                                 "ramp": method_cfg.get("ramp", {}),
                                 "entry_service": "TAS_{1}",
                             })

        _ramp_out = await _sim.run_ramp()
        _counts = _lnc.flush_logs(log_dir)

    # total wall-clock duration across all probes
    _duration = float(sum(_p.get("duration_s", 0.0)
                          for _p in _ramp_out["probes"]))
    ans = {
        "probes": _ramp_out["probes"],
        "saturation_rate": _ramp_out["saturation_rate"],
        "stopped_reason": _ramp_out["stopped_reason"],
        "duration_s": _duration,
        "service_log_counts": _counts,
    }

    return ans


def run(adp: Optional[str] = None,
        prf: Optional[str] = None,
        scn: Optional[str] = None,
        wrt: bool = True,
        method_cfg: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """*run()* execute the architectural experiment for one (profile, scenario) pair.

    Args:
        adp (Optional[str]): adaptation value; one of `baseline`,
            `s1`, `s2`, `aggregate`.
        prf (Optional[str]): profile stem (`dflt` / `opti`).
        scn (Optional[str]): explicit scenario name.
        wrt (bool): if True, write artifacts under
            `data/results/experiment/<scenario>/`. Defaults to True.
        method_cfg (Optional[Dict[str, Any]]): inline config override;
            used by `_QUICK_CFG` tests to skip the JSON read.

    Returns:
        Dict[str, Any]: result envelope with `config`,
            `method_config`, `nodes`, `network`, `requirements`,
            `probes`, `saturation_rate`, `stopped_reason`, `paths`.
    """
    _cfg = load_profile(adaptation=adp, profile=prf, scenario=scn)
    _mcfg = (method_cfg if method_cfg is not None
             else load_method_config("experiment"))
    _adp = adp or "baseline"

    if wrt:
        _log_dir = _RESULTS_DIR / _cfg.scenario / _cfg.profile
        _log_dir.mkdir(parents=True, exist_ok=True)
        _run_out = asyncio.run(_async_run(_cfg, _mcfg, _adp, _log_dir))
        _nds = _service_df_from_logs(_cfg, _log_dir, _run_out["duration_s"])
    else:
        with tempfile.TemporaryDirectory() as _tmp_str:
            _log_dir = Path(_tmp_str)
            _run_out = asyncio.run(_async_run(_cfg, _mcfg, _adp, _log_dir))
            _nds = _service_df_from_logs(_cfg, _log_dir,
                                         _run_out["duration_s"])

    _net = aggregate_network(_nds)
    _req = check_requirements(_nds)

    _paths: Dict[str, str] = {}
    if wrt:
        _paths = _write_results(_cfg, _mcfg, _nds, _net, _req, _run_out)

    ans = {
        "config": _cfg,
        "method_config": _mcfg,
        "nodes": _nds,
        "network": _net,
        "requirements": _req,
        "probes": _run_out["probes"],
        "saturation_rate": _run_out["saturation_rate"],
        "stopped_reason": _run_out["stopped_reason"],
        "paths": _paths,
    }
    return ans


def _write_results(cfg: NetworkConfig,
                   method_cfg: Dict[str, Any],
                   nds: pd.DataFrame,
                   net: pd.DataFrame,
                   req: dict,
                   run_out: Dict[str, Any]) -> Dict[str, str]:
    """*_write_results()* serialise the experiment outputs to the scenario-scoped directory.

    Args:
        cfg (NetworkConfig): resolved profile + scenario.
        method_cfg (Dict[str, Any]): experiment method config,
            copied verbatim into the envelope so the run is
            self-describing on disk.
        nds (pd.DataFrame): per-service metrics frame.
        net (pd.DataFrame): network aggregate (one row).
        req (dict): R1 / R2 / R3 verdict dict.
        run_out (Dict[str, Any]): async runtime output (probes,
            saturation, counts).

    Returns:
        Dict[str, str]: on-disk paths keyed by `profile` and
            `requirements`, relative to the repo root.
    """
    _out_dir = _RESULTS_DIR / cfg.scenario
    _out_dir.mkdir(parents=True, exist_ok=True)

    # strip the per-probe `records` (list of InvocationRecord dataclasses)
    # from the embedded envelope; they are not JSON-serialisable in bulk and
    # per-service CSVs already cover the same data
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
        "network": net.iloc[0].to_dict(),
        "nodes": nds.to_dict(orient="records"),
        "probes": _probes_out,
        "saturation_rate": run_out["saturation_rate"],
        "stopped_reason": run_out["stopped_reason"],
        "routing": cfg.routing.tolist(),
        "lambda_z": cfg.lambda_z_vector().tolist(),
    }

    _profile_path = _out_dir / f"{cfg.profile}.json"
    with _profile_path.open("w", encoding="utf-8") as _fh:
        json.dump(_doc, _fh, indent=4, ensure_ascii=False)

    _req_path = _out_dir / "requirements.json"
    with _req_path.open("w", encoding="utf-8") as _fh:
        json.dump(req, _fh, indent=4, ensure_ascii=False)

    ans = {"profile": str(_profile_path.relative_to(_ROOT)),
           "requirements": str(_req_path.relative_to(_ROOT))}
    return ans


def main() -> None:
    """*main()* CLI entry point.

    Parses flags, calls `run()`, and prints a one-screen summary
    plus the paths of any written files.
    """
    _parser = argparse.ArgumentParser(
        description="Architectural experiment for CS-01 TAS.",)

    _parser.add_argument("--adaptation",
                         choices=["baseline", "s1", "s2", "aggregate"],
                         default=None,
                         help="adaptation state",)
    _parser.add_argument("--profile",
                         choices=["dflt", "opti"],
                         default=None,
                         help="explicit profile file stem",)
    _parser.add_argument("--scenario",
                         default=None,
                         help="explicit scenario name",)
    _parser.add_argument("--no-write",
                         action="store_true",
                         help="skip writing result files",)

    _args = _parser.parse_args()

    _result = run(adp=_args.adaptation,
                  prf=_args.profile,
                  scn=_args.scenario,
                  wrt=not _args.no_write,)

    _cfg = _result["config"]
    _net = _result["network"].iloc[0]
    _req = _result["requirements"]

    print(f"profile={_cfg.profile}  scenario={_cfg.scenario}")
    print(f"label: {_cfg.label}")
    print(f"  nodes={int(_net['nodes'])}  "
          f"avg_rho={_net['avg_rho']:.4f}  "
          f"max_rho={_net['max_rho']:.4f}  "
          f"W_net={_net['W_net']:.6f}s")

    print("requirements:")
    for _k, _v in _req.items():
        _status = "PASS" if _v["pass"] else "FAIL"
        _val = _v["value"]
        _val_str = f"{_val:.6g}" if isinstance(_val, (int, float)) else "n/a"
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

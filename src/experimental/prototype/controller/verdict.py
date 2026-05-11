"""Post-trial R1/R2 verdict over the flow JSONL.

Walks the per-run flow records and computes the operational variables (`A`, `C`, `F`, `T`, `X_0`, `R`) per Denning & Buzen 1978. R1 is the failure fraction `F / A`; R2 is the mean total latency over successful requests (the operational `R`). These are the numbers stage 9 compares against analytic, dimensional, and stochastic.

Two artefacts land on disk: `verdict.json` (the final R1 / R2 + pass flags + stop reason) and `window.parquet` (the per-sample trajectory drained from the controller's `/history` for downstream plotting).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def _walk_flows(flows_path: Path) -> list[dict[str, Any]]:
    """Read one JSON object per line from the flow JSONL. Skips blank or malformed lines silently so partial files don't break the verdict.

    Args:
        flows_path (Path): per-run flow JSONL produced by `build_tas_fastapi_app`.

    Returns:
        list[dict[str, Any]]: parsed records; empty when the file is missing.
    """
    _records: list[dict[str, Any]] = []
    if not flows_path.exists():
        return _records
    with flows_path.open(encoding="utf-8") as _fh:
        for _line in _fh:
            _stripped = _line.strip()
            if not _stripped:
                continue
            try:
                _record = json.loads(_stripped)
            except ValueError:
                continue
            if isinstance(_record, dict):
                _records.append(_record)
    return _records


def _is_failure(record: dict[str, Any]) -> bool:
    """Decide whether one flow record counts as a failure.

    A record is a failure when its final TAS status is anything other than 200. Engine-side `error` bodies already surface as non-200 (the engine rewrites status 0 to 502) so checking status is sufficient.

    Args:
        record (dict[str, Any]): one parsed flow record.

    Returns:
        bool: True when the record represents a failed request.
    """
    _status = record.get("status", 0)
    _ans = _status != 200
    return _ans


def compute_verdict(*,
                    flows_path: Path,
                    adp: str,
                    run_id: str,
                    stop_reason: str,
                    n_planned: int,
                    thresholds: dict[str, float],
                    client_n_requests: int | None = None,
                    mesh_admission: dict[str, dict[str, Any]] | None = None) -> dict[str, Any]:
    """Walk the flow JSONL and emit the operational-analysis verdict dict.

    Args:
        flows_path (Path): per-run JSONL written by `build_tas_fastapi_app`.
        adp (str): adaptation key for the run.
        run_id (str): run identifier (written into the verdict).
        stop_reason (str): orchestrator-recorded stop reason.
        n_planned (int): the run's `target.json::trial.n_requests`.
        thresholds (dict[str, float]): `{"r1_max": ..., "r2_max": ...}` from `data/reference/baseline.json`.
        client_n_requests (int | None, optional): client-side A; if supplied, the flow-balance residual is `(client_n_requests - A_server) / max(client_n_requests, 1)`. Defaults to None.
        mesh_admission (dict | None, optional): `{svc_id: {c, K, mu, eps}}` actually applied at mesh bring-up. When set, gets echoed into the verdict under `mesh` so stage 9 can verify the four methods used identical QN parameters. Defaults to None.

    Returns:
        dict[str, Any]: verdict dict carrying `adp`, `run_id`, `thresholds`, `operational` (A, C, F, T_s, X_0_req_per_s, R_s), `r1`, `r2`, `stop_reason`, `n_planned`, `n_completed`, `flow_balance_residual`, and (when supplied) `mesh`.
    """
    _records = _walk_flows(flows_path)
    _A = len(_records)
    _failures: list[dict[str, Any]] = []
    _successes: list[dict[str, Any]] = []
    for _r in _records:
        if _is_failure(_r):
            _failures.append(_r)
        else:
            _successes.append(_r)
    _F = len(_failures)
    _C = len(_successes)
    if _A == 0:
        _t_first = 0.0
        _t_last = 0.0
    else:
        _t_first = min(float(_r.get("tas_recv_ts", 0.0)) for _r in _records)
        _t_last = max(float(_r.get("tas_send_ts", 0.0)) for _r in _records)
    _T_s = max(0.0, _t_last - _t_first)
    if _T_s > 0:
        _X_0 = _C / _T_s
    else:
        _X_0 = 0.0
    if _C > 0:
        _R_s = sum(float(_r.get("total_latency_s", 0.0)) for _r in _successes) / _C
    else:
        _R_s = 0.0
    if _A > 0:
        _r1_value = _F / _A
    else:
        _r1_value = 0.0
    _r2_value = _R_s
    _r1_max = thresholds["r1_max"]
    _r2_max = thresholds["r2_max"]
    _r1_pass = _r1_value <= _r1_max
    _r2_pass = _r2_value <= _r2_max
    if client_n_requests is not None and client_n_requests > 0:
        _residual = (client_n_requests - _A) / client_n_requests
    else:
        _residual = 0.0
    _ans: dict[str, Any] = {
        "adp": adp,
        "run_id": run_id,
        "thresholds": {"r1_max": _r1_max, "r2_max": _r2_max},
        "operational": {
            "A": _A,
            "C": _C,
            "F": _F,
            "T_s": _T_s,
            "X_0_req_per_s": _X_0,
            "R_s": _R_s,
        },
        "r1": {
            "value": _r1_value,
            "threshold": _r1_max,
            "units": "fraction",
            "pass": _r1_pass,
        },
        "r2": {
            "value": _r2_value,
            "threshold": _r2_max,
            "units": "seconds",
            "pass": _r2_pass,
        },
        "stop_reason": stop_reason,
        "n_planned": n_planned,
        "n_completed": _A,
        "flow_balance_residual": _residual,
    }
    if mesh_admission is not None:
        _ans["mesh"] = mesh_admission
    return _ans


def write_verdict_json(verdict: dict[str, Any], out_path: Path) -> None:
    """Write the verdict dict as pretty-printed JSON.

    Args:
        verdict (dict[str, Any]): output of `compute_verdict`.
        out_path (Path): destination file (parent dirs created as needed).
    """
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", encoding="utf-8") as _fh:
        json.dump(verdict, _fh, indent=4, sort_keys=False)


def write_window_parquet(history: list[dict[str, Any]], out_path: Path) -> None:
    """Write the controller's `/history` trajectory to a parquet file.

    One row per probe sample, carrying the per-sample running aggregates so stage-7+ plotters can render the R1 / R2 trajectory.

    Args:
        history (list[dict[str, Any]]): records returned by the controller's `GET /history`. Expected keys per record: `req_id`, `ts`, `status`, `latency_s`, `n_in_window`, `r1_running`, `r2_running`, `r1_breach`, `r2_breach`.
        out_path (Path): destination parquet file (parent dirs created as needed).
    """
    import pandas as pd

    out_path.parent.mkdir(parents=True, exist_ok=True)
    _df = pd.DataFrame(history)
    _df.to_parquet(out_path, index=False)


__all__ = [
    "compute_verdict",
    "write_verdict_json",
    "write_window_parquet",
]

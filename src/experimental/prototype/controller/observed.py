"""Aggregate per-pid CSVs into the same `nodes` DataFrame shape analytic produces.

Each atomic service drops one CSV per process under `RunPaths.csv_dir/<svc>__pid<PID>.csv`. The columns are declared in `target/factory/third_party.py::ATOMIC_CSV_COLUMNS`: `req_id`, `svc_name`, `kind`, `operation`, `submitted_ts`, `recv_ts`, `send_ts`, `status`, `c_used_at_start`, `result`, `inject_failure`, `run_id`, `pid`.

`observed_nodes_from_run` walks those rows and computes the operational variables (`A`, `C`, `lambda`, `R`, `W`, `L`, `rho`) per Denning & Buzen 1978 so the notebook can hand the result to the same `plot_qn_topology` / `plot_node_heatmap` / `plot_node_diffmap` plotters analytic uses. Lives in `controller/` rather than `view/` because it's data aggregation, not plotting.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pandas as pd


def observed_nodes_from_run(*,
                            csv_dir: Path,
                            atomic_ids: list[str],
                            mesh_admission: dict[str, dict[str, Any]],
                            kind_lt: dict[str, str],
                            window_s: float,
                            run_id: str | None = None) -> pd.DataFrame:
    """Aggregate per-pid CSVs into a nodes DataFrame matching analytic's shape.

    Operational derivations (per row in the output):

    - `A_i` = total invocations counted in the svc's CSV rows.
    - `C_i` = successful invocations (status == 200).
    - `lambda_i = A_i / window_s` (operational arrival rate).
    - `R_i = mean(send_ts - recv_ts)` over successful rows (mean service residence time).
    - `W_i = R_i` (operational response time).
    - `L_i = lambda_i * R_i` (Little's law).
    - `rho_i = lambda_i / (c_i * mu_i)` (utilisation; +inf when `c_i * mu_i = 0`).

    Args:
        csv_dir (Path): per-pid CSV directory (from `RunPaths.csv_dir`).
        atomic_ids (list[str]): ordered svc ids actually spawned for this run.
        mesh_admission (dict[str, dict[str, Any]]): per-svc `{c, K, mu, eps}` block written into `verdict.json::mesh`.
        kind_lt (dict[str, str]): per-svc kind (`alarm` / `medical_analysis` / `drug`) for the `name` column.
        window_s (float): trial duration in seconds (`verdict.json::operational.T_s`).
        run_id (str | None, optional): when set, rows with a different `run_id` are filtered out (per-pid CSVs are append-only across runs, so this scoping is required for repeat invocations against the same `csv_dir`). Defaults to None (no filter).

    Returns:
        pd.DataFrame: one row per atomic id with columns `node`, `key`, `name`, `type`, `lambda`, `mu`, `c`, `K`, `rho`, `L`, `W`, `A`, `C`, `F`.
    """
    _rows: list[dict[str, Any]] = []
    for _i, _svc_id in enumerate(atomic_ids):
        _df = _load_svc_rows(csv_dir, _svc_id)
        if run_id is not None and not _df.empty and "run_id" in _df.columns:
            _df = _df[_df["run_id"] == run_id]
        _entry = mesh_admission.get(_svc_id, {})
        _c = _entry.get("c")
        _K = _entry.get("K")
        _mu = float(_entry.get("mu", 0.0))
        _A = len(_df)
        if _A > 0:
            _ok = _df[_df["status"] == 200]
            _C = len(_ok)
            _F = _A - _C
        else:
            _ok = _df
            _C = 0
            _F = 0
        if window_s > 0:
            _lam = _A / window_s
        else:
            _lam = 0.0
        if _C > 0:
            _R = float((_ok["send_ts"] - _ok["recv_ts"]).mean())
        else:
            _R = 0.0
        _W = _R
        _L = _lam * _R
        _rho = _compute_rho(_lam, _c, _mu)
        _rows.append({
            "node": _i,
            "key": _svc_id,
            "name": kind_lt.get(_svc_id, ""),
            "type": "M/M/c/K",
            "lambda": _lam,
            "mu": _mu,
            "c": _c,
            "K": _K,
            "rho": _rho,
            "L": _L,
            "W": _W,
            "A": _A,
            "C": _C,
            "F": _F,
        })
    return pd.DataFrame(_rows)


def _load_svc_rows(csv_dir: Path, svc_id: str) -> pd.DataFrame:
    """Concatenate every per-pid CSV for one svc into a single DataFrame.

    The atomic factory sanitises `{`/`}`/`,`/` ` out of the catalogue id when picking the CSV filename (see `target.factory.third_party._safe_filename`); this lookup mirrors that rule so the aggregator finds the files on disk.

    Args:
        csv_dir (Path): per-pid CSV directory.
        svc_id (str): catalogue id (e.g. `AS_{1}`).

    Returns:
        pd.DataFrame: concatenated rows; empty DataFrame when no files match.
    """
    _safe = _sanitise(svc_id)
    _files = sorted(csv_dir.glob(f"{_safe}__pid*.csv"))
    if not _files:
        return pd.DataFrame()
    _parts: list[pd.DataFrame] = []
    for _path in _files:
        _parts.append(pd.read_csv(_path))
    return pd.concat(_parts, ignore_index=True)


def _sanitise(svc_id: str) -> str:
    """Strip LaTeX-style braces and other Windows-illegal chars so the filename matches what the atomic writer emits."""
    _ans = (svc_id
            .replace("{", "")
            .replace("}", "")
            .replace(",", "")
            .replace(" ", ""))
    return _ans


def _compute_rho(lam: float, c: Any, mu: float) -> float:
    """Compute utilisation `rho = lambda / (c * mu)`; returns +inf when capacity is non-positive."""
    _ans: float
    if c is None or mu <= 0:
        _ans = float("inf")
    else:
        _cap = float(c) * mu
        if _cap <= 0:
            _ans = float("inf")
        else:
            _ans = lam / _cap
    return _ans


__all__ = [
    "observed_nodes_from_run",
]

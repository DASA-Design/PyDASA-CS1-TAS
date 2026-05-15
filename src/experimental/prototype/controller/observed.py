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
                            run_id: str | None = None,
                            composite_op: dict[str, Any] | None = None,
                            composite_id: str = "TAS_{1}") -> pd.DataFrame:
    """Aggregate per-pid CSVs into a nodes DataFrame matching analytic's shape.

    Operational derivations (per row in the output):

    - `A_i` = total invocations counted in the svc's CSV rows.
    - `C_i` = successful invocations (status == 200).
    - `lambda_i = A_i / window_s` (operational arrival rate).
    - `R_i = mean(send_ts - recv_ts)` over successful rows (mean service residence time).
    - `W_i = R_i` (operational response time).
    - `L_i = lambda_i * R_i` (Little's law).
    - `rho_i = lambda_i / (c_i * mu_i)` (utilisation; +inf when `c_i * mu_i = 0`).

    When `composite_op` is supplied, a synthetic row is prepended for the composite TAS service. The composite writes flow JSONL rather than per-pid CSV, so its operational metrics come from `verdict.operational` (A / C / F / T_s / X_0_req_per_s / R_s) instead of the CSV aggregation. This lets the same row schema cover both atomic and composite services so the analytic plotters can render a uniform topology.

    Args:
        csv_dir (Path): per-pid CSV directory (from `RunPaths.csv_dir`).
        atomic_ids (list[str]): ordered svc ids that drop per-pid CSVs (third-party atomics + internal stages in expanded mode).
        mesh_admission (dict[str, dict[str, Any]]): per-svc `{c, K, mu, eps}` block written into `verdict.json::mesh`.
        kind_lt (dict[str, str]): per-svc kind (`alarm` / `medical_analysis` / `drug`) for the `name` column.
        window_s (float): trial duration in seconds (`verdict.json::operational.T_s`).
        run_id (str | None, optional): when set, rows with a different `run_id` are filtered out (per-pid CSVs are append-only across runs, so this scoping is required for repeat invocations against the same `csv_dir`). Defaults to None (no filter).
        composite_op (dict[str, Any] | None, optional): the `verdict.operational` block. When set, prepend a synthetic row for the composite using its `A` / `C` / `F` / `R_s` instead of CSV aggregation. Defaults to None.
        composite_id (str, optional): svc id for the synthetic composite row. Defaults to `"TAS_{1}"`.

    Returns:
        pd.DataFrame: one row per svc with columns `node`, `key`, `name`, `type`, `lambda`, `mu`, `c`, `K`, `rho`, `L`, `W`, `A`, `C`, `F`. Composite row (when included) is at index 0.
    """
    _rows: list[dict[str, Any]] = []
    if composite_op is not None:
        _rows.append(_composite_row(composite_id=composite_id,
                                    composite_op=composite_op,
                                    mesh_admission=mesh_admission,
                                    kind_lt=kind_lt,
                                    node_idx=0))
    _start_idx = len(_rows)
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
            "node": _start_idx + _i,
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


def _composite_row(*,
                   composite_id: str,
                   composite_op: dict[str, Any],
                   mesh_admission: dict[str, dict[str, Any]],
                   kind_lt: dict[str, str],
                   node_idx: int) -> dict[str, Any]:
    """Synthesise a nodes-DataFrame row for the composite service from its operational block.

    The composite writes flow JSONL rather than per-pid CSV, so the standard CSV aggregation does not see it. Pull `A` / `C` / `F` / `R_s` from `verdict.operational` and pull `c` / `K` / `mu` from `mesh_admission`.

    Args:
        composite_id (str): svc id used as the row's `key`.
        composite_op (dict[str, Any]): `verdict.operational` block (`A`, `C`, `F`, `T_s`, `X_0_req_per_s`, `R_s`).
        mesh_admission (dict[str, dict[str, Any]]): per-svc `{c, K, mu, eps}` block; the row pulls the composite's entry for `c` / `K` / `mu`.
        kind_lt (dict[str, str]): per-svc kind map (the composite's kind, if known, lands in `name`).
        node_idx (int): row index for the `node` column.

    Returns:
        dict[str, Any]: single nodes-DataFrame row for the composite.
    """
    _A = int(composite_op.get("A", 0))
    _C = int(composite_op.get("C", 0))
    _F = int(composite_op.get("F", 0))
    _T_s = float(composite_op.get("T_s", 0.0))
    _R = float(composite_op.get("R_s", 0.0))
    _lam = _A / _T_s if _T_s > 0 else 0.0
    _entry = mesh_admission.get(composite_id, {})
    _c = _entry.get("c")
    _K = _entry.get("K")
    _mu = float(_entry.get("mu", 0.0))
    _L = _lam * _R
    _rho = _compute_rho(_lam, _c, _mu)
    return {
        "node": node_idx,
        "key": composite_id,
        "name": kind_lt.get(composite_id, "composite"),
        "type": "M/M/c/K",
        "lambda": _lam,
        "mu": _mu,
        "c": _c,
        "K": _K,
        "rho": _rho,
        "L": _L,
        "W": _R,
        "A": _A,
        "C": _C,
        "F": _F,
    }


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
        # A worker SIGTERMed before its CsvWriter wrote anything can leave a
        # header-only or zero-byte file; pandas raises EmptyDataError on the
        # latter. Skip files with no data rows so one dead worker does not
        # abort the whole aggregation.
        try:
            _df = pd.read_csv(_path)
        except pd.errors.EmptyDataError:
            continue
        if not _df.empty:
            _parts.append(_df)
    if not _parts:
        return pd.DataFrame()
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

"""Tests for `src.experimental.prototype.controller.observed`.

**TestObservedNodesFromRun**: aggregator turns per-pid CSVs into an analytic-shaped nodes DataFrame.

- *test_basic_aggregation()*: lambda / R / W / L match the operational formulas; rho = lambda / (c * mu).
- *test_multiple_pids_concat()*: two pid files for one svc concatenate; A is their total row count.
- *test_failure_rows_excluded_from_R()*: 5xx rows count in A and F but the response-time mean is over C only.
- *test_missing_svc_returns_zero_row()*: an atomic id with no CSV files still gets a row (A = 0, lambda = 0, W = 0).
- *test_curly_braces_stripped_for_filename()*: svc id `AS_{1}` reads from disk file `AS_1__pid<PID>.csv` (matches the atomic factory's `_safe_filename`).
- *test_run_id_filter_excludes_stale_rows()*: when `run_id=` is set, rows from prior runs in the same CSV are filtered out.
"""

from __future__ import annotations

import math
from pathlib import Path
from typing import Any

import pandas as pd

from src.experimental.prototype.controller.observed import (
    observed_nodes_from_run,
)

_DFLT_ROW: dict[str, Any] = {
    "req_id": "r",
    "svc_name": "",
    "kind": "",
    "operation": "",
    "submitted_ts": 0.0,
    "recv_ts": 0.0,
    "send_ts": 0.0,
    "status": 200,
    "c_used_at_start": 1,
    "result": "",
    "inject_failure": "",
    "run_id": "r",
    "pid": 0,
}


def _row(**overrides: Any) -> dict[str, Any]:
    """Build one atomic-CSV row from `_DFLT_ROW`, overlaying `overrides`."""
    _ans = dict(_DFLT_ROW)
    _ans.update(overrides)
    return _ans


def _write_csv(csv_dir: Path,
               safe_svc_name: str,
               pid: int,
               rows: list[dict[str, Any]]) -> None:
    """Drop one per-pid CSV at the path the atomic factory would write.

    `safe_svc_name` is the curly-brace-stripped form (e.g. `MAS_1`, not `MAS_{1}`) so the filename matches `_safe_filename` in `factory.third_party`.
    """
    _df = pd.DataFrame(rows)
    _path = csv_dir / f"{safe_svc_name}__pid{pid}.csv"
    _df.to_csv(_path, index=False)


def _mesh(svc_id: str,
          c: int = 1,
          K: int = 10,
          mu: float = 180.0,
          eps: float = 0.0) -> dict[str, dict[str, Any]]:
    """Build a single-entry `mesh_admission` block for `svc_id`."""
    return {svc_id: {"c": c, "K": K, "mu": mu, "eps": eps}}


class TestObservedNodesFromRun:
    """Aggregator turns per-pid CSVs into an analytic-shaped nodes DataFrame."""

    def test_basic_aggregation(self, tmp_path: Path) -> None:
        """*test_basic_aggregation()* lambda, R, W, L match the operational formulas; rho = lam / (c * mu)."""
        _rows = [_row(svc_name="MAS_{1}", kind="medical_analysis",
                      operation="analyseData", send_ts=0.01, pid=100),
                 _row(svc_name="MAS_{1}", kind="medical_analysis",
                      operation="analyseData", submitted_ts=0.5,
                      recv_ts=0.5, send_ts=0.52, pid=100)]
        _write_csv(tmp_path, "MAS_1", 100, _rows)
        _df = observed_nodes_from_run(csv_dir=tmp_path,
                                      atomic_ids=["MAS_{1}"],
                                      mesh_admission=_mesh("MAS_{1}", c=1, mu=180.0),
                                      kind_lt={"MAS_{1}": "medical_analysis"},
                                      window_s=1.0)
        _r = _df.iloc[0]
        assert _r["key"] == "MAS_{1}"
        assert _r["A"] == 2
        assert _r["C"] == 2
        assert _r["F"] == 0
        assert math.isclose(_r["lambda"], 2.0)
        assert math.isclose(_r["W"], 0.015, abs_tol=1e-9)
        assert math.isclose(_r["L"], 0.03, abs_tol=1e-9)
        assert math.isclose(_r["rho"], 2.0 / (1 * 180.0), abs_tol=1e-9)
        assert _r["c"] == 1
        assert _r["K"] == 10

    def test_multiple_pids_concat(self, tmp_path: Path) -> None:
        """*test_multiple_pids_concat()* two pid files for one svc concatenate; A is their total row count."""
        _rows_a = [_row(svc_name="AS_{1}", kind="alarm",
                        operation="triggerAlarm", send_ts=0.005, pid=200)
                   for _ in range(3)]
        _rows_b = [_row(svc_name="AS_{1}", kind="alarm",
                        operation="triggerAlarm", send_ts=0.005, pid=201)
                   for _ in range(2)]
        _write_csv(tmp_path, "AS_1", 200, _rows_a)
        _write_csv(tmp_path, "AS_1", 201, _rows_b)
        _df = observed_nodes_from_run(csv_dir=tmp_path,
                                      atomic_ids=["AS_{1}"],
                                      mesh_admission=_mesh("AS_{1}", c=3, mu=250.0),
                                      kind_lt={"AS_{1}": "alarm"},
                                      window_s=5.0)
        _r = _df.iloc[0]
        assert _r["A"] == 5
        assert math.isclose(_r["lambda"], 1.0)

    def test_failure_rows_excluded_from_R(self, tmp_path: Path) -> None:
        """*test_failure_rows_excluded_from_R()* 5xx rows count in A and F but the response-time mean is over C only."""
        _rows = [_row(svc_name="DS_{1}", kind="drug",
                      operation="changeDose", send_ts=0.020, pid=300),
                 _row(svc_name="DS_{1}", kind="drug",
                      operation="changeDose", send_ts=5.0,
                      status=503, inject_failure="5xx", pid=300)]
        _write_csv(tmp_path, "DS_1", 300, _rows)
        _df = observed_nodes_from_run(csv_dir=tmp_path,
                                      atomic_ids=["DS_{1}"],
                                      mesh_admission=_mesh("DS_{1}", c=3, mu=250.0),
                                      kind_lt={"DS_{1}": "drug"},
                                      window_s=1.0)
        _r = _df.iloc[0]
        assert _r["A"] == 2
        assert _r["C"] == 1
        assert _r["F"] == 1
        assert math.isclose(_r["W"], 0.020, abs_tol=1e-9)

    def test_missing_svc_returns_zero_row(self, tmp_path: Path) -> None:
        """*test_missing_svc_returns_zero_row()* an atomic id with no CSV files still gets a row (A = 0, lambda = 0, W = 0)."""
        _df = observed_nodes_from_run(csv_dir=tmp_path,
                                      atomic_ids=["MAS_{1}"],
                                      mesh_admission=_mesh("MAS_{1}", c=1, mu=180.0),
                                      kind_lt={"MAS_{1}": "medical_analysis"},
                                      window_s=1.0)
        _r = _df.iloc[0]
        assert _r["A"] == 0
        assert _r["lambda"] == 0.0
        assert _r["W"] == 0.0
        assert _r["L"] == 0.0

    def test_curly_braces_stripped_for_filename(self, tmp_path: Path) -> None:
        """*test_curly_braces_stripped_for_filename()* svc id `AS_{1}` reads from disk file `AS_1__pid<PID>.csv`."""
        _rows = [_row(svc_name="AS_{1}", kind="alarm",
                      operation="triggerAlarm", send_ts=0.01,
                      run_id="rid", pid=400)]
        _write_csv(tmp_path, "AS_1", 400, _rows)
        _df = observed_nodes_from_run(csv_dir=tmp_path,
                                      atomic_ids=["AS_{1}"],
                                      mesh_admission=_mesh("AS_{1}", c=3, mu=250.0),
                                      kind_lt={"AS_{1}": "alarm"},
                                      window_s=1.0)
        assert _df.iloc[0]["A"] == 1

    def test_run_id_filter_excludes_stale_rows(self, tmp_path: Path) -> None:
        """*test_run_id_filter_excludes_stale_rows()* when `run_id=` is set, rows from prior runs in the same CSV are filtered out."""
        _rows = [_row(req_id="old", svc_name="AS_{1}", kind="alarm",
                      operation="triggerAlarm", send_ts=0.01,
                      run_id="prior", pid=500),
                 _row(req_id="new", svc_name="AS_{1}", kind="alarm",
                      operation="triggerAlarm", send_ts=0.02,
                      run_id="current", pid=500)]
        _write_csv(tmp_path, "AS_1", 500, _rows)
        _df = observed_nodes_from_run(csv_dir=tmp_path,
                                      atomic_ids=["AS_{1}"],
                                      mesh_admission=_mesh("AS_{1}", c=3, mu=250.0),
                                      kind_lt={"AS_{1}": "alarm"},
                                      window_s=1.0,
                                      run_id="current")
        _r = _df.iloc[0]
        assert _r["A"] == 1
        assert math.isclose(_r["W"], 0.02, abs_tol=1e-9)

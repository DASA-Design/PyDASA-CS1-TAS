"""Multi-trial apparatus benchmark: runner + aggregator.

The benchmark runs the full `4 adaptations x 2 frameworks x 2 granularities
= 16 cells` grid `n_trials` times each, so the trial-to-trial variance
(typically +/- 30 %) stays visible instead of hiding behind a single-shot
measurement. It is an apparatus-characterisation activity, sibling to
calibration: calibration measures the host noise floor, the benchmark
measures the apparatus's sustained-throughput envelope.

Public functions:

- `run_bench`: run the 16-cell x N-trial grid, write the per-trial CSV.
- `summarize_bench`: collapse the per-trial CSV into a per-cell distribution + R1/R2 verdict table.
- `save_bench_summary`: write the aggregated table to disk.
- `profile_stages`: per-stage timing breakdown of one cell's flow JSONL.

Per-trial CSVs and the aggregated summary land under `BENCH_DATA_DIR`;
figures land under `BENCH_IMG_DIR`. Both sit beside the calibration
results since they describe the apparatus, not a DASA method run.
"""

from __future__ import annotations

import csv
import json
import statistics as stats
import time
from collections import defaultdict
from pathlib import Path

import pandas as pd

from src.experimental.procedure.experiment import run_experiment
from src.experimental.prototype.runtime.cleanup import cleanup_calibration_ports
from src.io.config import load_method_cfg, load_reference

# The benchmark is an apparatus probe: data + figures sit beside calibration.
BENCH_DATA_DIR = Path("data") / "results" / "calibration" / "bench"
BENCH_IMG_DIR = Path("data") / "img" / "calibration" / "bench"

_EXPERIMENT_DIR = Path("data") / "results" / "experimental"
_BENCH_GLOB = "_bench_*.csv"

ADAPTATIONS = ("baseline", "s1", "s2", "aggregate")
FRAMEWORKS = ("fastapi", "flask")
GRANULARITIES = ("collapsed", "expanded")

# Port ranges swept clean between trials to avoid TIME_WAIT / orphan collisions.
_CLEANUP_PORTS = list(range(8001, 8050)) + list(range(9001, 9050))

_BENCH_FIELDS = (
    "adp", "framework", "granularity", "trial",
    "X_0", "R_s_ms", "T_s", "A", "C", "F",
    "r1", "r2_ms", "stop", "error",
)


# ----------------------------------------------------------------------------
# Runner
# ----------------------------------------------------------------------------
def _run_one_trial(adp: str,
                   framework: str,
                   granularity: str) -> dict:
    """Run one experimental trial; return its headline metrics, or an error row.

    Args:
        adp (str): adaptation key.
        framework (str): `"fastapi"` or `"flask"`.
        granularity (str): `"collapsed"` or `"expanded"`.

    Returns:
        dict: headline metrics (`X_0`, `R_s_ms`, `T_s`, `A`, `C`, `F`, `r1`, `r2_ms`, `stop`) on success, or `{"error": <msg>}` on failure.
    """
    cleanup_calibration_ports(ports=_CLEANUP_PORTS,
                              verbose=False)
    _cell = f"{adp}_{framework}_{granularity}"
    _verdict_path = _EXPERIMENT_DIR / _cell / "verdict.json"
    _result: dict = {}
    try:
        run_experiment(adp=adp, framework=framework,
                       target_granularity=granularity, skip_bounds_check=True)
        if not _verdict_path.exists():
            _result = {"error": f"verdict.json missing for {_cell}"}
        else:
            _v = json.loads(_verdict_path.read_text(encoding="utf-8"))
            _op = _v["operational"]
            _result = {
                "X_0": _op["X_0_req_per_s"],
                "R_s_ms": _op["R_s"] * 1000.0,
                "T_s": _op["T_s"],
                "A": _op["A"],
                "C": _op["C"],
                "F": _op["F"],
                "r1": _v["r1"]["value"],
                "r2_ms": _v["r2"]["value"] * 1000.0,
                "stop": _v["stop_reason"],
            }
    except Exception as _err:
        _result = {"error": f"{type(_err).__name__}: {_err}"}
    return _result


def run_bench(n_trials: int = 5,
              out_dir: Path = BENCH_DATA_DIR,
              verbose: bool = True) -> Path:
    """Run the 16-cell x `n_trials` benchmark grid; write the per-trial CSV.

    Each `(adaptation, framework, granularity)` cell runs `n_trials` times.
    Leftover worker processes are killed between trials so a stuck port does
    not poison the next run. Each row is flushed as it is written, so an
    interrupted run still leaves a usable partial CSV.

    Args:
        n_trials (int, optional): trials per cell. Defaults to 5.
        out_dir (Path, optional): destination directory. Defaults to `BENCH_DATA_DIR`.
        verbose (bool, optional): print per-trial progress. Defaults to True.

    Returns:
        Path: the written per-trial CSV (`_bench_<UTC-timestamp>.csv`).
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    _ts = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    _csv_path = out_dir / f"_bench_{_ts}.csv"

    with _csv_path.open("w", newline="", encoding="utf-8") as _fh:
        _writer = csv.DictWriter(_fh, fieldnames=list(_BENCH_FIELDS))
        _writer.writeheader()
        for _adp in ADAPTATIONS:
            for _fw in FRAMEWORKS:
                for _gr in GRANULARITIES:
                    _cell = f"{_adp}/{_fw}/{_gr}"
                    if verbose:
                        print(f"=== {_cell} ===", flush=True)
                    for _trial in range(1, n_trials + 1):
                        _result = _run_one_trial(_adp, _fw, _gr)
                        _row = {"adp": _adp, "framework": _fw,
                                "granularity": _gr, "trial": _trial}
                        if "error" in _result:
                            _row["error"] = _result["error"]
                            if verbose:
                                print(f"  trial {_trial}: ERROR {_result['error']}",
                                      flush=True)
                        else:
                            _row.update(_result)
                            if verbose:
                                print(f"  trial {_trial}: X_0={_result['X_0']:.1f} "
                                      f"R_s={_result['R_s_ms']:.0f}ms "
                                      f"r1={_result['r1']:.3f}", flush=True)
                        _writer.writerow(_row)
                        _fh.flush()
    return _csv_path


# ----------------------------------------------------------------------------
# Aggregator
# ----------------------------------------------------------------------------
def _load_design_params() -> dict[str, float]:
    """Read the R1 / R2 thresholds and the design arrival rate from config.

    R1 / R2 come from `data/reference/baseline.json`; `lambda_z` is the design
    arrival rate at the composite (`trial.request_rate_per_s` in the
    experimental method config).

    Returns:
        dict[str, float]: `r1_max` (fraction), `r2_max_ms` (milliseconds), `lambda_z` (req/s).
    """
    _reqs = load_reference("baseline")["requirements"]
    _trial = load_method_cfg("experimental")["trial"]
    return {
        "r1_max": float(_reqs["R1"]["threshold"]),
        "r2_max_ms": float(_reqs["R2"]["threshold"]) * 1000.0,
        "lambda_z": float(_trial["request_rate_per_s"]),
    }


def _latest_bench_csv(bench_dir: Path = BENCH_DATA_DIR) -> Path | None:
    """Return the most recent `_bench_<ts>.csv` under `bench_dir`, or None when absent."""
    _matches = sorted(bench_dir.glob(_BENCH_GLOB))
    if not _matches:
        return None
    return _matches[-1]


def summarize_bench(csv_path: Path | None = None) -> pd.DataFrame:
    """Collapse the per-trial benchmark CSV into a per-cell distribution + verdict table.

    The R1 / R2 thresholds and the design `lambda_z` are loaded from config and
    attached to the returned frame's `.attrs` so the plotters need no config of
    their own.

    Args:
        csv_path (Path | None, optional): explicit per-trial CSV. Defaults to None (the most recent `_bench_*.csv` under `BENCH_DATA_DIR`).

    Returns:
        pd.DataFrame: one row per `(adaptation, framework, granularity)` cell, in canonical order, with columns n, X_0 min / p50 / max / stdev / cv_pct, R_s_p50_ms, r1_p50, r2_p50_ms, R1_pass, R2_pass. `.attrs` carries `r1_max`, `r2_max_ms`, `lambda_z`.

    Raises:
        FileNotFoundError: when `csv_path` is None and no `_bench_*.csv` exists.
    """
    if csv_path is None:
        csv_path = _latest_bench_csv()
        if csv_path is None:
            _msg = f"no {_BENCH_GLOB} found under {BENCH_DATA_DIR}"
            raise FileNotFoundError(_msg)
    _params = _load_design_params()
    _r1_max = _params["r1_max"]
    _r2_max_ms = _params["r2_max_ms"]
    with csv_path.open(encoding="utf-8") as _fh:
        _rows = [row for row in csv.DictReader(_fh) if row.get("X_0")]

    _out: list[dict] = []
    for _adp in ADAPTATIONS:
        for _fw in FRAMEWORKS:
            for _gr in GRANULARITIES:
                _sel = [row for row in _rows
                        if row["adp"] == _adp
                        and row["framework"] == _fw
                        and row["granularity"] == _gr]
                if not _sel:
                    continue
                _x0 = [float(r["X_0"]) for r in _sel]
                _rs = [float(r["R_s_ms"]) for r in _sel]
                _r1_vals = [float(r["r1"]) for r in _sel]
                _r2_vals = [float(r["r2_ms"]) for r in _sel]
                _x0_mean = stats.fmean(_x0)
                _x0_stdev = stats.stdev(_x0) if len(_x0) > 1 else 0.0
                _r1_p50 = stats.median(_r1_vals)
                _r2_p50 = stats.median(_r2_vals)
                _td = {
                    "adaptation": _adp,
                    "framework": _fw,
                    "granularity": _gr,
                    "n": len(_sel),
                    "X_0_min": min(_x0),
                    "X_0_p50": stats.median(_x0),
                    "X_0_max": max(_x0),
                    "X_0_stdev": _x0_stdev,
                    "X_0_cv_pct": (100.0 * _x0_stdev / _x0_mean) if _x0_mean > 0 else 0.0,
                    "R_s_p50_ms": stats.median(_rs),
                    "r1_p50": _r1_p50,
                    "r2_p50_ms": _r2_p50,
                    "R1_pass": _r1_p50 <= _r1_max,
                    "R2_pass": _r2_p50 <= _r2_max_ms,
                }
                _out.append(_td)
    _df = pd.DataFrame(_out)
    _df.attrs.update(_params)
    return _df


def save_bench_summary(df: pd.DataFrame,
                       out_dir: Path = BENCH_DATA_DIR,
                       stem: str = "bench_summary") -> Path:
    """Write the aggregated DataFrame to `<out_dir>/<stem>.csv`, creating dirs.

    Args:
        df (pd.DataFrame): aggregated table from `summarize_bench`.
        out_dir (Path, optional): destination directory. Defaults to `BENCH_DATA_DIR`.
        stem (str, optional): output filename stem. Defaults to `"bench_summary"`.

    Returns:
        Path: the written CSV path.
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    _path = out_dir / f"{stem}.csv"
    df.to_csv(_path, index=False)
    return _path


# ----------------------------------------------------------------------------
# Per-stage profiler
# ----------------------------------------------------------------------------
def profile_stages(cell: str) -> pd.DataFrame:
    """Break one cell's flow JSONL into per-stage timing (mean / p50 / p95 / p99 ms).

    Reads the most recent non-empty flow JSONL for `cell` and decomposes each successful request into: composite-admit, per-atomic-call (composite-side roundtrip), per-atomic-service (atomic `_handle` time, joined from the per-pid CSVs), inter-step engine-branching gaps, and composite-post (JSONL write + sample append + response build).

    Args:
        cell (str): cell directory name, e.g. `"baseline_fastapi_collapsed"`.

    Returns:
        pd.DataFrame: one row per stage with columns stage, mean_ms, p50_ms, p95_ms, p99_ms, n. Empty DataFrame when no usable flow data exists.
    """
    _flows_dir = _EXPERIMENT_DIR / cell / "flows"
    _flows = sorted(_flows_dir.glob("*.jsonl"))
    _latest = None
    for _p in reversed(_flows):
        if _p.stat().st_size > 1000:
            _latest = _p
            break
    if _latest is None:
        return pd.DataFrame()
    _run_id = _latest.stem

    # Per-(req_id, svc) atomic-side recv/send timestamps from the per-pid CSVs.
    _atomic_lt: dict[tuple[str, str], tuple[float, float]] = {}
    for _csv in (_EXPERIMENT_DIR / cell / "csv").glob("*.csv"):
        try:
            with _csv.open(encoding="utf-8") as _fh:
                for _row in csv.DictReader(_fh):
                    if _row.get("run_id") != _run_id:
                        continue
                    try:
                        _recv = float(_row.get("recv_ts", "") or 0)
                        _send = float(_row.get("send_ts", "") or 0)
                    except ValueError:
                        continue
                    if _recv > 0 and _send > 0:
                        _atomic_lt[(_row.get("req_id", ""), _row.get("svc_name", ""))] = (_recv, _send)
        except (OSError, csv.Error):
            continue

    _stages: dict[str, list[float]] = defaultdict(list)
    for _line in _latest.read_text(encoding="utf-8").splitlines():
        try:
            _rec = json.loads(_line)
        except json.JSONDecodeError:
            continue
        if _rec.get("status") != 200:
            continue
        _steps = _rec.get("steps") or []
        if not _steps:
            continue
        _tas_recv = _rec.get("tas_recv_ts")
        _tas_send = _rec.get("tas_send_ts")
        if not (_tas_recv and _tas_send):
            continue
        _req_id = str(_rec.get("req_id", ""))
        _stages["composite_admit"].append((_steps[0]["send_ts"] - _tas_recv) * 1000.0)
        for _i, _step in enumerate(_steps):
            _svc = _step["svc_id"]
            _total = (_step["recv_ts"] - _step["send_ts"]) * 1000.0
            _stages[f"atomic_call_{_i + 1}__{_svc}"].append(_total)
            _key = (_req_id, _svc)
            if _key in _atomic_lt:
                _a_recv, _a_send = _atomic_lt[_key]
                _stages[f"atomic_service_{_i + 1}__{_svc}"].append((_a_send - _a_recv) * 1000.0)
            if _i + 1 < len(_steps):
                _gap = (_steps[_i + 1]["send_ts"] - _step["recv_ts"]) * 1000.0
                _stages[f"inter_step_{_i + 1}_to_{_i + 2}"].append(_gap)
        _stages["composite_post"].append((_tas_send - _steps[-1]["recv_ts"]) * 1000.0)
        _stages["total_handler"].append((_tas_send - _tas_recv) * 1000.0)

    def _pctl(xs: list[float], p: float) -> float:
        _s = sorted(xs)
        _idx = max(0, min(len(_s) - 1, int(round(p / 100 * (len(_s) - 1)))))
        return _s[_idx]

    _out: list[dict] = []
    for _stage in sorted(_stages):
        _vals = _stages[_stage]
        if not _vals:
            continue
        _out.append({
            "stage": _stage,
            "mean_ms": stats.fmean(_vals),
            "p50_ms": _pctl(_vals, 50),
            "p95_ms": _pctl(_vals, 95),
            "p99_ms": _pctl(_vals, 99),
            "n": len(_vals),
        })
    return pd.DataFrame(_out)


__all__ = [
    "ADAPTATIONS",
    "BENCH_DATA_DIR",
    "BENCH_IMG_DIR",
    "FRAMEWORKS",
    "GRANULARITIES",
    "profile_stages",
    "run_bench",
    "save_bench_summary",
    "summarize_bench",
]

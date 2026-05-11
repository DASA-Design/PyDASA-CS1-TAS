"""Demo: run all four adaptation strategies back-to-back and print a comparison.

Four trial runs over real localhost TCP:

1. `baseline`: no adaptation. Weighted-random pick per `_routs`; no retry.
2. `s1` (retry on failure): weighted-random first pick; on failure, weighted-random over remaining equivalents; up to `max_attempts` total.
3. `s2` (prefer-reliable): argmin observed failure rate over the equivalent set; no retry.
4. `aggregate` (S1 + S2): reliability-ranked chain truncated to `max_attempts`.

Each run uses the same trial knobs (small `n_requests` for a quick demo) and the on-disk `target.json` config; only `adp` is overridden per run. The mesh layout helpers (port resolution + worker-PID extraction from the per-pid CSV filenames) are imported from `tests.demo.granularity` so both demos share the same probe of the running mesh.

Run from the project root:

    python -m tests.demo.experiment

Outputs:
- One stdout block per run with adp, n_requests, outcome counts, latency p50 / p95 / max.
- Per-run worker table (svc, OS PID, host:port) reused from `granularity`.
- Per-run verdict block: R1 / R2 measured values + pass flags + stop_reason (once the controller and orchestrator wiring lands; until then prints `verdict not yet wired`).
- A side-by-side comparison table at the end.
- Full run summaries land under `_sandbox/demo_experiment/experiment.json`.
- Each run's flow JSONL + per-pid CSV land under `data/results/experimental/<adp>/`.
"""

from __future__ import annotations

import json
import statistics
from copy import deepcopy
from pathlib import Path
from typing import Any

from src.experimental.prototype.target.config import load_target_cfg
from src.methods.experimental import run_experiment
from tests.demo.granularity import (
    DEMO_BASE_PORT,
    gather_workers,
    print_workers,
)

DEMO_REQUESTS = 100
SCRATCH_DIR = Path("_sandbox/demo_experiment")


def run_one(label: str,
            adp: str) -> dict[str, Any]:
    """Run one trial under the given adaptation strategy.

    Args:
        label (str): display label for the stdout heading.
        adp (str): adaptation key (`baseline` / `s1` / `s2` / `aggregate`).

    Returns:
        dict[str, Any]: full result dict from `run_experiment`.
    """
    _cfg = deepcopy(load_target_cfg())
    _cfg["trial"]["n_requests"] = DEMO_REQUESTS
    _cfg["trial"]["request_rate_per_s"] = 0  # no pacing
    _cfg["tas_base_port"] = DEMO_BASE_PORT
    print(f"\n=== running adp: {label} ===")
    _result = run_experiment(adp=adp,
                             dpl="localhost",
                             target_cfg=_cfg,
                             skip_bounds_check=True,
                             write=True)
    return _result


def summarise(label: str, result: dict[str, Any]) -> dict[str, Any]:
    """Reduce one run's full result to a small summary block.

    Args:
        label (str): display label for the run.
        result (dict[str, Any]): output of `run_one`.

    Returns:
        dict[str, Any]: small dict carrying label, adp, run_id, outcome counts, latency p50 / p95 / max / mean in ms, and the verdict block when the orchestrator has wired it in.
    """
    _summaries = result.get("summaries", [])
    _latencies: list[float] = []
    for _s in _summaries:
        _val = _s.get("latency_s")
        if _val is not None:
            _latencies.append(_val)
    _outcome_counts = result.get("outcome_counts", {})
    _ans: dict[str, Any] = {
        "label": label,
        "adp": result["adp"],
        "run_id": result["run_id"],
        "n_requests": result["n_requests"],
        "outcomes": dict(_outcome_counts),
        "n_atomic_ids": len(result.get("atomic_ids", [])),
        "verdict": result.get("verdict"),
    }
    if _latencies:
        _sorted = sorted(_latencies)
        _ans["latency_p50_ms"] = round(statistics.median(_sorted) * 1000.0, 2)
        _ans["latency_max_ms"] = round(_sorted[-1] * 1000.0, 2)
        _ans["latency_mean_ms"] = round(statistics.fmean(_sorted) * 1000.0, 2)
        # Nearest-rank p95: index = ceil(0.95 * n) - 1, clamped.
        _p95_idx = max(0, min(len(_sorted) - 1, -(-95 * len(_sorted) // 100) - 1))
        _ans["latency_p95_ms"] = round(_sorted[_p95_idx] * 1000.0, 2)
    else:
        _ans["latency_p50_ms"] = None
        _ans["latency_p95_ms"] = None
        _ans["latency_max_ms"] = None
        _ans["latency_mean_ms"] = None
    return _ans


def print_one(summary: dict[str, Any]) -> None:
    """Print one run's headline numbers to stdout.

    Args:
        summary (dict[str, Any]): output of `summarise`.
    """
    print(f"\trun_id:\t\t{summary['run_id']}")
    print(f"\tadp:\t\t{summary['adp']}")
    print(f"\trequests:\t\t{summary['n_requests']}  outcomes: {summary['outcomes']}")
    if summary['latency_p50_ms'] is not None:
        print(f"\tlatency:\t\tp50={summary['latency_p50_ms']} ms  "
              f"p95={summary['latency_p95_ms']} ms  "
              f"max={summary['latency_max_ms']} ms  "
              f"mean={summary['latency_mean_ms']} ms")


def print_verdict(summary: dict[str, Any]) -> None:
    """Print the per-run verdict block (R1 / R2 + pass flags + stop_reason).

    The orchestrator populates `result["verdict"]` from `compute_verdict` once the controller wiring lands. Until then this prints a placeholder so the demo flow is visible end-to-end.

    Args:
        summary (dict[str, Any]): output of `summarise`.
    """
    _v = summary.get("verdict")
    if _v is None:
        print("\tverdict:\t\tnot yet wired (orchestrator still pending)")
        return
    _r1 = _v.get("r1", {})
    _r2 = _v.get("r2", {})
    _op = _v.get("operational", {})
    print(f"\tverdict:\t\tR1={_r1.get('value', 0.0):.5f} (threshold {_r1.get('threshold')}, "
          f"pass={_r1.get('pass')})")
    print(f"\t\t\tR2={_r2.get('value', 0.0):.5f} s (threshold {_r2.get('threshold')}, "
          f"pass={_r2.get('pass')})")
    print(f"\t\t\tstop_reason={_v.get('stop_reason')}  "
          f"completed={_v.get('n_completed')}/{_v.get('n_planned')}  "
          f"X_0={_op.get('X_0_req_per_s', 0.0):.2f} req/s  "
          f"T={_op.get('T_s', 0.0):.2f} s")


def print_table(rows: list[dict[str, Any]]) -> None:
    """Print a side-by-side comparison table over all runs.

    Args:
        rows (list[dict[str, Any]]): list of summary blocks from `summarise`, in run order.
    """
    print("\n=== comparison ===")
    _header = (f"{'adp':<22} {'n':>4}  {'success':>8}  {'R1':>8}  {'R2_ms':>8}  "
               f"{'stop_reason':<16}")
    print(_header)
    print("-" * len(_header))
    for _r in rows:
        _label = _r["label"]
        _n = _r["n_requests"]
        _ok = _r["outcomes"].get("success", 0)
        _v = _r.get("verdict") or {}
        _r1_val = (_v.get("r1") or {}).get("value")
        _r2_val = (_v.get("r2") or {}).get("value")
        _stop = _v.get("stop_reason", "?")
        _r1_str = "?" if _r1_val is None else f"{_r1_val:.5f}"
        _r2_str = "?" if _r2_val is None else f"{_r2_val * 1000:.2f}"
        print(f"{_label:<22} {_n:>4}  {_ok:>8}  {_r1_str:>8}  {_r2_str:>8}  {_stop:<16}")


def save(rows: list[dict[str, Any]]) -> Path:
    """Write the full comparison summary to disk.

    Args:
        rows (list[dict[str, Any]]): list of summary blocks from `summarise`.

    Returns:
        Path: file path the JSON was written to (overwrites on rerun).
    """
    SCRATCH_DIR.mkdir(parents=True, exist_ok=True)
    _out = SCRATCH_DIR / "experiment.json"
    with _out.open("w", encoding="utf-8") as _fh:
        json.dump(rows, _fh, indent=4)
    return _out


def main() -> None:
    """Run four trials (one per adp), print each, print a comparison table, save the summary JSON.

    Each adp spawns its own service set per the active profile's `_nodes` (baseline / s1 use dflt's MAS_3, AS_3, DS_3; s2 / aggregate use opti's MAS_4, AS_4, DS_1). All four runs are full restarts.
    """
    _runs: list[tuple[str, str]] = [
        ("baseline",            "baseline"),
        ("s1 retry",            "s1"),
        ("s2 prefer-reliable",  "s2"),
        ("aggregate (S1 + S2)", "aggregate"),
    ]
    _summaries: list[dict[str, Any]] = []
    for _label, _adp in _runs:
        _result = run_one(_label, _adp)
        _summary = summarise(_label, _result)
        _workers = gather_workers(_result)
        _summary["workers"] = _workers
        print_one(_summary)
        print_workers(_workers)
        print_verdict(_summary)
        _summaries.append(_summary)
    print_table(_summaries)
    _out = save(_summaries)
    print(f"\n=== summary saved to {_out} ===")


if __name__ == "__main__":
    main()

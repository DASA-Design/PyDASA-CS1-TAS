"""Demo: run all three target-granularity modes back-to-back and print a comparison.

Three trial runs over real localhost TCP:

1. `collapsed`: 8-spawner mesh; TAS_{2..6} are inline workflow code.
2. `expanded` with `inject_internal_stage_mu=False`: 13-spawner mesh; internal stages are real but skip the mu sleep.
3. `expanded` with `inject_internal_stage_mu=True`: 13-spawner mesh; internal stages also sleep on mu.

Each run uses the same trial knobs (small `n_requests` for a quick demo) and the on-disk `target.json` config; only `target_granularity` and `inject_internal_stage_mu` are overridden per run.

Run from the project root:

    python -m tests.demo.granularity

Outputs:
- One stdout block per run with mode, n_requests, outcome counts, latency p50 / p95 / max.
- Per-run worker table: svc, OS PID, host:port (parsed from per-pid CSVs and flow JSONL).
- A side-by-side comparison table at the end.
- Full run summaries land under `_sandbox/demo_granularity/granularity.json`.
- Each run's flow JSONL + per-pid CSV land under `data/results/experimental/baseline/`.
"""

from __future__ import annotations

import json
import re
import statistics
from copy import deepcopy
from pathlib import Path
from typing import Any

from src.experimental.prototype.target.config import load_target_cfg
from src.methods.experimental import run_experiment

DEMO_REQUESTS = 5
DEMO_BASE_PORT = 8001
DEMO_HOST = "127.0.0.1"
SCRATCH_DIR = Path("_sandbox/demo_granularity")
INTERNAL_STAGE_IDS = ("TAS_{2}", "TAS_{3}", "TAS_{4}", "TAS_{5}", "TAS_{6}")
_PID_FNAME_RE = re.compile(r"^(?P<svc>.+)__pid(?P<pid>\d+)\.csv$")


def run_one(label: str,
            target_granularity: str,
            inject_internal_stage_mu: bool) -> dict[str, Any]:
    """Run one trial under the given granularity + mu policy.

    Args:
        label (str): display label for the stdout heading.
        target_granularity (str): `collapsed` or `expanded`.
        inject_internal_stage_mu (bool): when True (and expanded), TAS_{2..6} sleep on mu.

    Returns:
        dict[str, Any]: full result dict from `run_experiment` (run_id, summaries, outcome_counts, paths, ...).
    """
    _cfg = deepcopy(load_target_cfg())
    _cfg["trial"]["n_requests"] = DEMO_REQUESTS
    _cfg["trial"]["request_rate_per_s"] = 0  # no pacing
    _cfg["tas_base_port"] = DEMO_BASE_PORT
    print(f"\n=== running mode: {label} ===")
    _result = run_experiment(adp="baseline",
                             dpl="localhost",
                             target_cfg=_cfg,
                             target_granularity=target_granularity,
                             inject_internal_stage_mu=inject_internal_stage_mu,
                             skip_bounds_check=True,
                             write=True)
    return _result


def summarise(label: str, result: dict[str, Any]) -> dict[str, Any]:
    """Reduce one run's full result to a small summary block.

    Args:
        label (str): display label for the run.
        result (dict[str, Any]): output of `run_one`.

    Returns:
        dict[str, Any]: small dict carrying label, run_id, outcome counts, and latency p50 / p95 / max / mean in ms (None when no requests were timed).
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
        "target_granularity": result["target_granularity"],
        "inject_internal_stage_mu": result["inject_internal_stage_mu"],
        "run_id": result["run_id"],
        "n_requests": result["n_requests"],
        "outcomes": dict(_outcome_counts),
        "n_atomic_ids": len(result.get("atomic_ids", [])),
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


def _port_layout(granularity: str,
                 atomic_ids: list[str],
                 base_port: int) -> dict[str, int]:
    """Reconstruct the `svc_id -> port` mapping the orchestrator used for one run.

    Mirrors `_build_mesh_specs` in `src/methods/experimental.py`: TAS at `base_port`; in expanded mode the five internal stages occupy the next five ports, then the third-party atomics.

    Args:
        granularity (str): `collapsed` or `expanded`.
        atomic_ids (list[str]): sorted third-party atomic ids from the result dict.
        base_port (int): `tas_base_port` from the config.

    Returns:
        dict[str, int]: `svc_id -> TCP port`.
    """
    _ans: dict[str, int] = {"TAS": base_port}
    if granularity == "expanded":
        _internal_first = base_port + 1
        for _idx, _stage_id in enumerate(INTERNAL_STAGE_IDS):
            _ans[_stage_id] = _internal_first + _idx
        _atomic_first = base_port + 1 + len(INTERNAL_STAGE_IDS)
    else:
        _atomic_first = base_port + 1
    for _idx, _svc_id in enumerate(atomic_ids):
        _ans[_svc_id] = _atomic_first + _idx
    return _ans


def _tas_pid_from_flows(flows_path: Path) -> int | None:
    """Read the first JSONL flow record and return its `pid` (TAS_1's OS PID).

    Args:
        flows_path (Path): path to the per-run flows JSONL.

    Returns:
        int | None: PID, or None when the file is missing or has no parseable record.
    """
    if not flows_path.exists():
        return None
    with flows_path.open(encoding="utf-8") as _fh:
        for _line in _fh:
            _line = _line.strip()
            if not _line:
                continue
            try:
                _rec = json.loads(_line)
            except ValueError:
                continue
            _pid = _rec.get("pid")
            if isinstance(_pid, int):
                return _pid
            break
    return None


def gather_workers(result: dict[str, Any]) -> list[dict[str, Any]]:
    """Walk the run's CSV dir + flows JSONL to collect `(svc, pid, host, port)` per worker.

    Args:
        result (dict[str, Any]): output of `run_one`.

    Returns:
        list[dict[str, Any]]: one row per worker, ordered TAS first then by port.
    """
    _paths = result.get("paths", {})
    _csv_dir = Path(_paths.get("csv_dir", ""))
    _flows_path = Path(_paths.get("flows", ""))
    _atomic_ids: list[str] = sorted(result.get("atomic_ids", []))
    _ports = _port_layout(result["target_granularity"], _atomic_ids, DEMO_BASE_PORT)
    _safe_to_id: dict[str, str] = {}
    for _svc_id in _ports:
        _safe = _svc_id.replace("{", "").replace("}", "").replace(",", "").replace(" ", "")
        _safe_to_id[_safe] = _svc_id
    _pids: dict[str, int] = {}
    if _csv_dir.exists():
        for _f in _csv_dir.glob("*__pid*.csv"):
            _m = _PID_FNAME_RE.match(_f.name)
            if _m is None:
                continue
            _safe = _m.group("svc")
            _svc_id = _safe_to_id.get(_safe, _safe)
            _pids[_svc_id] = int(_m.group("pid"))
    _tas_pid = _tas_pid_from_flows(_flows_path)
    if _tas_pid is not None:
        _pids["TAS"] = _tas_pid
    _rows: list[dict[str, Any]] = []
    for _svc_id, _port in sorted(_ports.items(), key=lambda _kv: _kv[1]):
        _rows.append({
            "svc": _svc_id,
            "pid": _pids.get(_svc_id),
            "host": DEMO_HOST,
            "port": _port,
            "url": f"http://{DEMO_HOST}:{_port}",
        })
    return _rows


def print_workers(rows: list[dict[str, Any]]) -> None:
    """Print one worker per line: `svc  pid  host:port`."""
    if not rows:
        return
    print("\tworkers:")
    print(f"\t\t{'svc':<12} {'pid':>8}  {'host:port'}")
    print(f"\t\t{'-' * 12} {'-' * 8}  {'-' * 21}")
    for _r in rows:
        _pid_str = "?" if _r["pid"] is None else str(_r["pid"])
        _hp = f"{_r['host']}:{_r['port']}"
        print(f"\t\t{_r['svc']:<12} {_pid_str:>8}  {_hp}")


def print_one(summary: dict[str, Any]) -> None:
    """Print one run's headline numbers to stdout.

    Args:
        summary (dict[str, Any]): output of `summarise`.
    """
    print(f"\trun_id:\t\t{summary['run_id']}")
    print(f"\tgranular.:\t\t{summary['target_granularity']}")
    print(f"\tmu inject:\t\t{summary['inject_internal_stage_mu']}")
    print(f"\trequests:\t\t{summary['n_requests']}  outcomes: {summary['outcomes']}")
    if summary['latency_p50_ms'] is not None:
        print(f"\tlatency:\t\tp50={summary['latency_p50_ms']} ms  "
              f"p95={summary['latency_p95_ms']} ms  "
              f"max={summary['latency_max_ms']} ms  "
              f"mean={summary['latency_mean_ms']} ms")


def print_table(rows: list[dict[str, Any]]) -> None:
    """Print a side-by-side comparison table over all runs.

    Args:
        rows (list[dict[str, Any]]): list of summary blocks from `summarise`, in run order.
    """
    print("\n=== comparison ===")
    _header = f"{'mode':<28} {'n':>4}  {'success':>8}  {'p50_ms':>8}  {'p95_ms':>8}  {'max_ms':>8}"
    print(_header)
    print("-" * len(_header))
    for _r in rows:
        _label = _r["label"]
        _n = _r["n_requests"]
        _ok = _r["outcomes"].get("success", 0)
        _p50 = _r["latency_p50_ms"]
        if _p50 is None:
            _p50 = 0.0
        _p95 = _r["latency_p95_ms"]
        if _p95 is None:
            _p95 = 0.0
        _max = _r["latency_max_ms"]
        if _max is None:
            _max = 0.0
        print(f"{_label:<28} {_n:>4}  {_ok:>8}  {_p50:>8.2f}  {_p95:>8.2f}  {_max:>8.2f}")


def save(rows: list[dict[str, Any]]) -> Path:
    """Write the full comparison summary to disk.

    Args:
        rows (list[dict[str, Any]]): list of summary blocks from `summarise`.

    Returns:
        Path: file path the JSON was written to (overwrites on rerun).
    """
    SCRATCH_DIR.mkdir(parents=True, exist_ok=True)
    _out = SCRATCH_DIR / "granularity.json"
    with _out.open("w", encoding="utf-8") as _fh:
        json.dump(rows, _fh, indent=4)
    return _out


def main() -> None:
    """Run three trials, print each, print a comparison table, save the summary JSON."""
    _runs: list[tuple[str, str, bool]] = [
        ("collapsed", "collapsed", False),
        ("expanded (mu off)", "expanded", False),
        ("expanded (mu on)", "expanded", True),
    ]
    _summaries: list[dict[str, Any]] = []
    for _label, _granularity, _mu in _runs:
        _result = run_one(_label, _granularity, _mu)
        _summary = summarise(_label, _result)
        _workers = gather_workers(_result)
        _summary["workers"] = _workers
        print_one(_summary)
        print_workers(_workers)
        _summaries.append(_summary)
    print_table(_summaries)
    _out = save(_summaries)
    print(f"\n=== summary saved to {_out} ===")


if __name__ == "__main__":
    main()

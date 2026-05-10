"""Parallel-limit calibration: walk the worker count to find the efficiency knee."""

from __future__ import annotations

from collections.abc import Callable
from contextlib import AbstractContextManager
from typing import Any

from src.experimental.prototype.calibration.rate import RateDriver, _drive_at_rate

# Runtime fallbacks for data/config/method/prototype/calibration.json::workers_scaling.*.
_DFLT_WORKERS_START = 1
_DFLT_WORKERS_STOP = 32
_DFLT_WORKERS_STEP = 1
_DFLT_PER_STEP_S = 5.0
_DFLT_RATE_PER_WORKER = 200
_DFLT_MIN_EFF_PCT = 80.0

MakeTargetsFn = Callable[[int], AbstractContextManager[list[str]]]


def make_workers_ramp(*,
                      start: int,
                      stop: int,
                      step: int) -> list[int]:
    """Build an additive worker-count ramp from `start` to `stop` (inclusive) by `step`.

    Args:
        start (int): first worker count.
        stop (int): last worker count (inclusive when reachable from `start` by `step`).
        step (int): increment between consecutive counts; must be positive.

    Returns:
        list[int]: ordered list of worker counts.

    Raises:
        ValueError: when `step <= 0`.
    """
    if step <= 0:
        _msg = f"step must be positive; got {step}"
        raise ValueError(_msg)
    _ans: list[int] = []
    _n = start
    while _n <= stop:
        _ans.append(_n)
        _n += step
    return _ans


def detect_efficiency_knee(per_step_stats: list[dict[str, Any]],
                           *,
                           min_eff_pct: float) -> dict[str, Any]:
    """Scan per-step stats; return the highest n whose efficiency stayed at or above `min_eff_pct`.

    Args:
        per_step_stats (list[dict[str, Any]]): per-step rows; each carries `n_workers` and `efficiency_pct`.
        min_eff_pct (float): minimum acceptable per-worker efficiency (percent).

    Returns:
        dict[str, Any]: keys `stable_workers` (int | None) and `reason` (str). `stable_workers=None` when even the first row fails or no rows were recorded.
    """
    _ans: dict[str, Any] = {
        "stable_workers": None,
        "reason": "no steps recorded",
    }
    _stable: int | None = None
    _broken_at: int | None = None
    _broken_eff: float = 0.0
    for _row in per_step_stats:
        if _broken_at is not None:
            continue
        _eff = _row.get("efficiency_pct", 0.0)
        _n = _row["n_workers"]
        if _eff >= min_eff_pct:
            _stable = _n
        else:
            _broken_at = _n
            _broken_eff = _eff
    if _broken_at is not None and _stable is None:
        _ans["reason"] = (
            f"no parallel headroom; n={_broken_at} efficiency "
            f"{_broken_eff:.1f}% < {min_eff_pct:.1f}%"
        )
    elif _broken_at is not None:
        _ans["stable_workers"] = _stable
        _ans["reason"] = (
            f"efficiency knee at n={_broken_at} "
            f"({_broken_eff:.1f}% < {min_eff_pct:.1f}%)"
        )
    elif _stable is not None:
        _ans["stable_workers"] = _stable
        _ans["reason"] = f"all steps within efficiency band (max n={_stable})"
    return _ans


def probe_workers_scaling(*,
                          start: int = _DFLT_WORKERS_START,
                          stop: int = _DFLT_WORKERS_STOP,
                          step: int = _DFLT_WORKERS_STEP,
                          per_step_s: float = _DFLT_PER_STEP_S,
                          rate_per_worker: int = _DFLT_RATE_PER_WORKER,
                          min_eff_pct: float = _DFLT_MIN_EFF_PCT,
                          make_targets: MakeTargetsFn,
                          driver: RateDriver | None = None) -> dict[str, Any]:
    """Walk worker count from `start` to `stop`; halt when per-worker efficiency drops below `min_eff_pct`.

    For each n, enters `make_targets(n)`, drives `n * rate_per_worker` req/s for `per_step_s`, records per-step stats, exits the context manager. The n=1 row's `per_worker_rps` is the baseline used to compute `efficiency_pct` on later rows.

    Args:
        start (int, optional): first worker count. Defaults to 1.
        stop (int, optional): inclusive ramp ceiling. Defaults to 32.
        step (int, optional): additive increment. Defaults to 1.
        per_step_s (float, optional): seconds to drive at each step. Defaults to 5.0.
        rate_per_worker (int, optional): per-worker target rate (req/s). Defaults to 200.
        min_eff_pct (float, optional): efficiency floor; first n below this halts the ramp. Defaults to 80.0.
        make_targets (MakeTargetsFn): given n, returns a context manager yielding the n target URLs.
        driver (RateDriver | None, optional): rate driver. Defaults to None (real httpx via `_drive_at_rate`).

    Returns:
        dict[str, Any]: envelope-ready block. Keys: `ramp`, `per_step`, `rate_per_worker`, `per_step_s`, `min_eff_pct`, `stable_workers`, `reason`.
    """
    if driver is None:
        _driver: RateDriver = _drive_at_rate
    else:
        _driver = driver
    _ramp = make_workers_ramp(start=start, stop=stop, step=step)
    _per_step: list[dict[str, Any]] = []
    _baseline_rps: float | None = None
    _stopped = False
    _i = 0
    while _i < len(_ramp) and not _stopped:
        _n = _ramp[_i]
        with make_targets(_n) as _urls:
            _stats = _driver(_urls, _n * rate_per_worker, per_step_s)
        _row = _build_per_step_row(_n, rate_per_worker, per_step_s, _stats, _baseline_rps)
        if _baseline_rps is None:
            _baseline_rps = _row["per_worker_rps"]
        _per_step.append(_row)
        if _row["efficiency_pct"] < min_eff_pct:
            _stopped = True
        _i += 1
    _verdict = detect_efficiency_knee(_per_step, min_eff_pct=min_eff_pct)
    _ans: dict[str, Any] = {
        "ramp": _ramp,
        "per_step": _per_step,
        "rate_per_worker": rate_per_worker,
        "per_step_s": per_step_s,
        "min_eff_pct": min_eff_pct,
        "stable_workers": _verdict["stable_workers"],
        "reason": _verdict["reason"],
    }
    return _ans


def _build_per_step_row(n: int,
                        rate_per_worker: int,
                        per_step_s: float,
                        driver_stats: dict[str, Any],
                        baseline_rps: float | None) -> dict[str, Any]:
    """Compose one per-step row: driver stats + derived `actual_rps` / `per_worker_rps` / `efficiency_pct`.

    Args:
        n (int): worker count at this step.
        rate_per_worker (int): per-worker drive rate.
        per_step_s (float): drive duration.
        driver_stats (dict[str, Any]): output of the rate driver.
        baseline_rps (float | None): per-worker rps recorded at n=1; None on the first step (sets efficiency to 100%).

    Returns:
        dict[str, Any]: the per-step row, ready to append to `per_step`.
    """
    _ans: dict[str, Any] = dict(driver_stats)
    _ans["n_workers"] = n
    _ans["rate_target"] = n * rate_per_worker
    _total = float(_ans.get("total", 0))
    if per_step_s > 0:
        _actual_rps = _total / per_step_s
    else:
        _actual_rps = 0.0
    if n > 0:
        _per_worker_rps = _actual_rps / n
    else:
        _per_worker_rps = 0.0
    _ans["actual_rps"] = _actual_rps
    _ans["per_worker_rps"] = _per_worker_rps
    if baseline_rps is None or baseline_rps <= 0:
        _ans["efficiency_pct"] = 100.0
    else:
        _ans["efficiency_pct"] = (_per_worker_rps / baseline_rps) * 100.0
    return _ans


__all__ = [
    "MakeTargetsFn",
    "detect_efficiency_knee",
    "make_workers_ramp",
    "probe_workers_scaling",
]

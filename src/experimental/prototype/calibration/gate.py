"""Calibration report: precision band, verifiable range, envel gates, summary headlines."""

from __future__ import annotations

import math
from typing import Any

# Runtime fallback for data/config/method/prototype/calibration.json::gate.noise_floor_pct.
_DFLT_NOISE_BASE_PCT = 5.0

# Probe blocks the gate reads.
HOST_FLOOR_PROBES = ("timer", "jitter", "loopback", "handler_scaling")


def verdict(envel: dict[str, Any],
            *,
            noise_floor_pct: float = _DFLT_NOISE_BASE_PCT) -> dict[str, Any]:
    """Build the calibration report dict from a populated envel.

    Computes the precision band (RMS of the floor std-devs), the verifiable range (highest c within the band + saturation rate), the per-block envel gates, and the per-row summary headlines.

    Args:
        envel (dict[str, Any]): populated calibration envel (probes + rate sweep).
        noise_floor_pct (float, optional): per-side tolerance for the envel gates. Defaults to 5.0.

    Returns:
        dict[str, Any]: keys `passed`, `noise_floor_pct`, `precision_band_us`, `verifiable_range`, `gates`, `floors`, `summary`.
    """
    _floors = _floor_block(envel)
    _band = _precision_band(_floors)
    _gates = {
        "handler_scaling": _gate_handler_scaling(envel.get("handler_scaling", {}), noise_floor_pct),
        "saturation_knee": _gate_saturation(envel.get("rate", {})),
        "workers_scaling": _gate_workers(envel.get("workers_scaling", {})),
    }
    _range = _verifiable_range(envel, noise_floor_pct)
    _summary = _summary_block(envel, _gates, _range)
    _all_passed = True
    for _g in _gates.values():
        if not _g["passed"]:
            _all_passed = False
    _ans: dict[str, Any] = {
        "passed": _all_passed,
        "noise_floor_pct": noise_floor_pct,
        "precision_band_us": _band,
        "verifiable_range": _range,
        "gates": _gates,
        "floors": _floors,
        "summary": _summary,
    }
    return _ans


def stamp_gate(envel: dict[str, Any],
               *,
               noise_floor_pct: float = _DFLT_NOISE_BASE_PCT) -> dict[str, Any]:
    """Compute the report and stamp it into `envel["gate"]`.

    Args:
        envel (dict[str, Any]): the calibration envel; mutated in place.
        noise_floor_pct (float, optional): per-side tolerance. Defaults to 5.0.

    Returns:
        dict[str, Any]: the report dict (also stored at `envel["gate"]`).
    """
    _v = verdict(envel, noise_floor_pct=noise_floor_pct)
    envel["gate"] = _v
    return _v


def _floor_block(envel: dict[str, Any]) -> dict[str, dict[str, float | None]]:
    """Extract each floor's central value + std-dev (us) for the precision-band calculation.

    Args:
        envel (dict[str, Any]): populated calibration envel (must include timer / jitter / loopback blocks).

    Returns:
        dict[str, dict[str, float | None]]: keys `timer`, `jitter`, `loopback`, each mapping to `{value_us, std_us}`. Missing fields fall through as None.
    """
    _timer = envel.get("timer", {})
    _jitter = envel.get("jitter", {})
    _loopback = envel.get("loopback", {})
    _ans: dict[str, dict[str, float | None]] = {
        "timer": {
            "value_us": _to_us_or_none(_timer.get("median_ns"), 1_000.0),
            "std_us": _to_us_or_none(_timer.get("std_ns"), 1_000.0),
        },
        "jitter": {
            "value_us": _signed_or_none(_jitter.get("median_us"), _jitter.get("target_us")),
            "std_us": _to_us_or_none(_jitter.get("std_us"), 1.0),
        },
        "loopback": {
            "value_us": _to_us_or_none(_loopback.get("median_us"), 1.0),
            "std_us": _to_us_or_none(_loopback.get("std_us"), 1.0),
        },
    }
    return _ans


def _to_us_or_none(value: Any, divisor: float) -> float | None:
    """Coerce `value / divisor` to float, or None if `value` is missing.

    Args:
        value (Any): numeric input or None.
        divisor (float): unit-conversion divisor (1.0 for us, 1000.0 for ns).

    Returns:
        float | None: converted value, or None when `value` is None.
    """
    _ans: float | None
    if value is None:
        _ans = None
    else:
        _ans = float(value) / divisor
    return _ans


def _signed_or_none(measured: Any, target: Any) -> float | None:
    """Return `measured - target` (us), or None if either side is missing.

    Args:
        measured (Any): observed value.
        target (Any): reference value to subtract.

    Returns:
        float | None: signed difference, or None when either operand is None.
    """
    _ans: float | None
    if measured is None or target is None:
        _ans = None
    else:
        _ans = float(measured) - float(target)
    return _ans


def _precision_band(floors: dict[str, dict[str, float | None]]) -> dict[str, float | None]:
    """Compute the precision band as the quadrature sum of the floor std-devs (us).

    Args:
        floors (dict[str, dict[str, float | None]]): output of `_floor_block`.

    Returns:
        dict[str, float | None]: keys `timer_std_us`, `jitter_std_us`, `loopback_std_us`, `total_us`. `total_us` is None when any floor std is missing.
    """
    _components: dict[str, float | None] = {}
    for _name in ("timer", "jitter", "loopback"):
        _components[_name] = floors[_name]["std_us"]
    _missing_any = False
    _sum_sq = 0.0
    for _v in _components.values():
        if _v is None:
            _missing_any = True
        else:
            _sum_sq += float(_v) ** 2
    _total: float | None
    if _missing_any:
        _total = None
    else:
        _total = math.sqrt(_sum_sq)
    _ans: dict[str, float | None] = {
        "timer_std_us": _components["timer"],
        "jitter_std_us": _components["jitter"],
        "loopback_std_us": _components["loopback"],
        "total_us": _total,
    }
    return _ans


def _gate_handler_scaling(block: dict[str, Any],
                          noise_floor_pct: float) -> dict[str, Any]:
    """Envelope gate: report the highest concurrency whose median stays within +/- noise_floor_pct of c=1.

    Mirrors the saturation gate. The gate fails only when even the first non-trivial concurrency already drifts (no headroom at all).

    Args:
        block (dict[str, Any]): the `handler_scaling` envel block (`{concurs, stats}`).
        noise_floor_pct (float): per-side tolerance for the drift check.

    Returns:
        dict[str, Any]: gate dict with keys `passed`, `value_pct`, `limit_pct`, `reason`.
    """
    _ans: dict[str, Any]
    _c_max = _max_stable_concurrency(block, noise_floor_pct)
    _stats = block.get("stats", {})
    _cs = _sorted_concurs(_stats)
    if _c_max is None:
        _ans = _missing("handler scaling")
    elif len(_cs) >= 2 and _c_max == _cs[0]:
        _ans = {
            "passed": False,
            "value_pct": None,
            "limit_pct": noise_floor_pct,
            "reason": f"no concurrency headroom; c={_cs[1]} already drifts > noise floor",
        }
    else:
        _ans = {
            "passed": True,
            "value_pct": None,
            "limit_pct": noise_floor_pct,
            "reason": f"knee at c={_c_max}",
        }
    return _ans


def _gate_workers(block: dict[str, Any]) -> dict[str, Any]:
    """Envelope gate: the workers ramp must report a stable parallel limit.

    Empty block (skipped on `dpl='localhost'`) is treated as `passed=True` with reason `not applicable` so the overall verdict isn't penalised by mode.

    Args:
        block (dict[str, Any]): the `workers_scaling` envel block.

    Returns:
        dict[str, Any]: gate dict with keys `passed`, `value_pct`, `limit_pct`, `reason`.
    """
    _ans: dict[str, Any]
    if not block:
        _ans = {
            "passed": True,
            "value_pct": None,
            "limit_pct": None,
            "reason": "not applicable (single-worker mode)",
        }
    else:
        _stable = block.get("stable_workers")
        if _stable is None:
            _ans = {
                "passed": False,
                "value_pct": None,
                "limit_pct": block.get("min_eff_pct"),
                "reason": str(block.get("reason", "no parallel headroom")),
            }
        else:
            _ans = {
                "passed": True,
                "value_pct": None,
                "limit_pct": block.get("min_eff_pct"),
                "reason": f"stable up to n={_stable}",
            }
    return _ans


def _gate_saturation(rate_block: dict[str, Any]) -> dict[str, Any]:
    """Envelope gate: the rate sweep must report a saturation knee.

    Args:
        rate_block (dict[str, Any]): the `rate` envel block.

    Returns:
        dict[str, Any]: gate dict with keys `passed`, `value_pct`, `limit_pct`, `reason`.
    """
    _ans: dict[str, Any]
    if not rate_block:
        _ans = _missing("saturation knee")
    else:
        _sat = rate_block.get("saturation_rate")
        if _sat is None:
            _ans = {
                "passed": False,
                "value_pct": None,
                "limit_pct": None,
                "reason": "no saturation knee detected within sweep range",
            }
        else:
            _ans = {
                "passed": True,
                "value_pct": None,
                "limit_pct": None,
                "reason": f"saturation at {_sat} req/s",
            }
    return _ans


def _verifiable_range(envel: dict[str, Any],
                      noise_floor_pct: float) -> dict[str, Any]:
    """Compute the operating envel: max stable concurrency, saturation rate, and parallel-worker limit.

    Args:
        envel (dict[str, Any]): populated calibration envel.
        noise_floor_pct (float): per-side tolerance for the concurrency drift check.

    Returns:
        dict[str, Any]: keys `c_max` (int | None), `r_max_req_s` (number | None), `w_max` (int | None).
    """
    _ans: dict[str, Any] = {
        "c_max": _max_stable_concurrency(envel.get("handler_scaling", {}), noise_floor_pct),
        "r_max_req_s": envel.get("rate", {}).get("saturation_rate"),
        "w_max": envel.get("workers_scaling", {}).get("stable_workers"),
    }
    return _ans


def _max_stable_concurrency(block: dict[str, Any],
                            noise_floor_pct: float) -> int | None:
    """Walk concurrencies in ascending order; return the highest c whose median stays within the band of c=1.

    Args:
        block (dict[str, Any]): the `handler_scaling` envel block.
        noise_floor_pct (float): per-side drift tolerance (percent).

    Returns:
        int | None: highest stable concurrency, or None when the block has fewer than two concurrencies or its base median is non-positive.
    """
    _ans: int | None = None
    _stats = block.get("stats", {})
    _cs = _sorted_concurs(_stats)
    if len(_cs) >= 2:
        _low = _stats[str(_cs[0])].get("median_us", 0.0)
        if _low > 0:
            _max = _cs[0]
            _stopped = False
            _i = 1
            while _i < len(_cs) and not _stopped:
                _c = _cs[_i]
                _v = _stats[str(_c)].get("median_us", 0.0)
                _pct = abs((_v - _low) / _low * 100.0)
                if _pct <= noise_floor_pct:
                    _max = _c
                else:
                    _stopped = True
                _i += 1
            _ans = _max
    return _ans


def _sorted_concurs(stats: dict[str, Any]) -> list[int]:
    """Return the concurrency keys of `stats` as a sorted int list.

    Args:
        stats (dict[str, Any]): per-concurrency stats dict (keys are stringified ints).

    Returns:
        list[int]: ascending-sorted concurrency values; empty list when `stats` is empty.
    """
    _ans: list[int] = []
    if stats:
        for _k in stats.keys():
            _ans.append(int(_k))
        _ans.sort()
    return _ans


def _missing(label: str) -> dict[str, Any]:
    """Build a sentinel gate dict for the case where source data is absent.

    Args:
        label (str): short name of the gate (used in the `reason` line).

    Returns:
        dict[str, Any]: gate dict with `passed=False`, `value_pct=None`, `limit_pct=None`, and a `<label>: missing data` reason.
    """
    _ans: dict[str, Any] = {
        "passed": False,
        "value_pct": None,
        "limit_pct": None,
        "reason": f"{label}: missing data",
    }
    return _ans


def _summary_block(envel: dict[str, Any],
                   gates: dict[str, dict[str, Any]],
                   verifiable_range: dict[str, Any]) -> dict[str, dict[str, str]]:
    """Build the per-plot summary headlines (one short string per probe + rate).

    Args:
        envel (dict[str, Any]): populated calibration envel.
        gates (dict[str, dict[str, Any]]): freshly computed envel gates.
        verifiable_range (dict[str, Any]): output of `_verifiable_range`.

    Returns:
        dict[str, dict[str, str]]: keys `timer`, `jitter`, `loopback`, `scaling`, `rate`, each mapping to `{"headline": ...}`.
    """
    _ans: dict[str, dict[str, str]] = {
        "timer": _summarise_timer(envel.get("timer", {})),
        "jitter": _summarise_jitter(envel.get("jitter", {})),
        "loopback": _summarise_loopback(envel.get("loopback", {})),
        "scaling": _summarise_scaling(envel.get("handler_scaling", {}),
                                      gates["handler_scaling"]["passed"],
                                      verifiable_range.get("c_max")),
        "rate": _summarise_rate(envel.get("rate", {})),
        "workers": _summarise_workers(envel.get("workers_scaling", {})),
    }
    return _ans


def _summarise_timer(block: dict[str, Any]) -> dict[str, str]:
    """Build the timer headline: clock-noise std-dev rendered as `$\\pm$ X $\\mu$s` mathtext.

    Args:
        block (dict[str, Any]): the `timer` envel block (`{samples_n, median_ns, std_ns, ...}`).

    Returns:
        dict[str, str]: `{"headline": ...}`; `"n/a"` when `std_ns` is missing.
    """
    _headline = "n/a"
    _std_ns = block.get("std_ns")
    if _std_ns is not None:
        _std_us = float(_std_ns) / 1000.0
        _headline = rf"$\pm$ {_std_us:.2f} $\mu$s"
    return {"headline": _headline}


def _summarise_jitter(block: dict[str, Any]) -> dict[str, str]:
    """Build the jitter headline: median offset vs target, with std-dev as a `$\\pm$` band.

    Args:
        block (dict[str, Any]): the `jitter` envel block (`{target_us, median_us, std_us, ...}`).

    Returns:
        dict[str, str]: `{"headline": ...}`; `"n/a"` when target / median is missing or non-positive.
    """
    _headline = "n/a"
    _target = block.get("target_us")
    _med = block.get("median_us")
    _std = block.get("std_us")
    if _target is not None and _med is not None and float(_target) > 0:
        _target_f = float(_target)
        _offset = float(_med) - _target_f
        _ms = _target_f / 1000
        if _std is None:
            _headline = rf"{_offset:+.0f} $\mu$s @ {_ms:.0f} ms"
        else:
            _headline = rf"{_offset:+.0f} $\pm$ {float(_std):.0f} $\mu$s @ {_ms:.0f} ms"
    return {"headline": _headline}


def _summarise_loopback(block: dict[str, Any]) -> dict[str, str]:
    """Build the loopback headline: median round-trip + std-dev band, with payload size when known.

    Args:
        block (dict[str, Any]): the `loopback` envel block (`{median_us, std_us, payload_bytes, ...}`).

    Returns:
        dict[str, str]: `{"headline": ...}`; `"n/a"` when median is missing.
    """
    _headline = "n/a"
    _med = block.get("median_us")
    _std = block.get("std_us")
    _payload = block.get("payload_bytes")
    if _med is not None:
        if _payload is None:
            _kib = ""
        else:
            _kib = f" @ {float(_payload) / 1024:.0f} KiB"
        if _std is None:
            _headline = rf"{float(_med):.0f} $\mu$s{_kib}"
        else:
            _headline = rf"{float(_med):.0f} $\pm$ {float(_std):.0f} $\mu$s{_kib}"
    return {"headline": _headline}


def _summarise_scaling(block: dict[str, Any],
                       passed: bool,
                       c_max: int | None) -> dict[str, str]:
    """Build the handler-scaling headline: knee concurrency + drift at the knee.

    Args:
        block (dict[str, Any]): the `handler_scaling` envel block.
        passed (bool): the freshly computed handler-scaling gate verdict.
        c_max (int | None): highest stable concurrency from `_max_stable_concurrency`.

    Returns:
        dict[str, str]: `{"headline": ...}`; `"no headroom"` when the gate failed; `"n/a"` when stats are missing.
    """
    _headline = "n/a"
    _stats = block.get("stats", {})
    _cs = _sorted_concurs(_stats)
    if len(_cs) >= 2:
        _low = float(_stats[str(_cs[0])].get("median_us", 0.0))
        if _low > 0:
            if not passed or c_max is None:
                _headline = "no headroom"
            else:
                _hi_med = float(_stats[str(c_max)].get("median_us", 0.0))
                _drift = (_hi_med - _low) / _low * 100.0
                _headline = rf"knee at $c={c_max}$ ({_drift:+.1f}%)"
    return {"headline": _headline}


def _summarise_rate(block: dict[str, Any]) -> dict[str, str]:
    """Build the rate-sweep headline: saturation rate or 'no knee within ramp'.

    Args:
        block (dict[str, Any]): the `rate` envel block (`{saturation_rate, ...}`).

    Returns:
        dict[str, str]: `{"headline": ...}`; `"n/a"` when the block is empty.
    """
    _headline = "n/a"
    if block:
        _sat = block.get("saturation_rate")
        if _sat is None:
            _headline = "no knee within ramp"
        else:
            _headline = f"saturated @ {_sat} req/s"
    return {"headline": _headline}


def _summarise_workers(block: dict[str, Any]) -> dict[str, str]:
    """Build the workers-scaling headline: stable parallel-worker count + efficiency at the knee.

    Args:
        block (dict[str, Any]): the `workers_scaling` envel block.

    Returns:
        dict[str, str]: `{"headline": ...}`; `"n/a"` when the block is empty (localhost mode); `"no parallel headroom"` when even n=1 fails efficiency.
    """
    _headline = "n/a"
    if block:
        _stable = block.get("stable_workers")
        if _stable is None:
            _headline = "no parallel headroom"
        else:
            _eff = _eff_at_n(block.get("per_step", []), _stable)
            if _eff is None:
                _headline = rf"stable up to $w={_stable}$"
            else:
                _headline = rf"stable up to $w={_stable}$ ({_eff:.0f}%)"
    return {"headline": _headline}


def _eff_at_n(per_step: list[dict[str, Any]],
              n_workers: int) -> float | None:
    """Find the efficiency_pct value of the row whose `n_workers` matches `n_workers`.

    Args:
        per_step (list[dict[str, Any]]): per-step rows from the workers ramp.
        n_workers (int): the worker count to look up.

    Returns:
        float | None: matching `efficiency_pct`, or None when no row matches.
    """
    _ans: float | None = None
    for _row in per_step:
        if _ans is None and _row.get("n_workers") == n_workers:
            _ans = _row.get("efficiency_pct")
    return _ans


__all__ = [
    "HOST_FLOOR_PROBES",
    "stamp_gate",
    "verdict",
]

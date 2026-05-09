"""Pre-run gate: noise-floor verdict on the calibration envelope.

Reads the four host-floor probe blocks (timer, jitter, loopback, handler_scaling) and applies a percent-spread rule per probe. Returns an overall `passed` flag plus per-probe diagnostics.

Per-probe spread metrics (each compares a stressed value to its baseline):

- `timer`: `max_ns` over `median_ns` (clock consistency).
- `jitter`: `median_us` over `target_us` (scheduler precision).
- `loopback`: `p99_us` over `median_us` (round-trip tail vs typical).
- `handler_scaling`: highest-c `median_us` over lowest-c `median_us` (event-loop saturation).

Rate-saturation is verdicted in `rate.detect_saturation`, not here. Threshold from `data/config/method/prototype/calibration.json::gate.noise_floor_pct`; default fallback `5.0` (5 %).
"""

from __future__ import annotations

from typing import Any

# Runtime fallback for data/config/method/prototype/calibration.json::gate.noise_floor_pct.
_DFLT_NOISE_FLOOR_PCT = 5.0

# Probe blocks the gate reads (rate-saturation is handled separately).
HOST_FLOOR_PROBES = ("timer", "jitter", "loopback", "handler_scaling")


def verdict(envelope: dict[str, Any],
            *,
            noise_floor_pct: float = _DFLT_NOISE_FLOOR_PCT) -> dict[str, Any]:
    """Apply the noise-floor rule across the four host-floor probes; return overall + per-probe.

    Args:
        envelope (dict[str, Any]): the calibration envelope (as built by `make_envelope`, populated by the probes).
        noise_floor_pct (float, optional): per-probe percent-spread limit. Defaults to 5.0.

    Returns:
        dict[str, Any]: keys `passed` (bool — True iff every probe passed), `noise_floor_pct` (float — the limit used), `checks` (dict — per-probe `{passed, value_pct, limit_pct, reason}` blocks).
    """
    _checks: dict[str, dict[str, Any]] = {}
    for _name in HOST_FLOOR_PROBES:
        _checks[_name] = _check_probe(_name, envelope.get(_name, {}), noise_floor_pct)
    _all_passed = all(_c["passed"] for _c in _checks.values())
    _ans: dict[str, Any] = {
        "passed": _all_passed,
        "noise_floor_pct": noise_floor_pct,
        "checks": _checks,
    }
    return _ans


def stamp_gate(envelope: dict[str, Any],
               *,
               noise_floor_pct: float = _DFLT_NOISE_FLOOR_PCT) -> dict[str, Any]:
    """Compute the verdict and stamp it into `envelope["gate"]`.

    Convenience for the notebook + orchestrator: one call mutates the envelope in place and returns the same verdict dict that landed under `envelope["gate"]`.

    Args:
        envelope (dict[str, Any]): the calibration envelope; mutated in place.
        noise_floor_pct (float, optional): per-probe percent-spread limit. Defaults to 5.0.

    Returns:
        dict[str, Any]: the verdict dict (also stored at `envelope["gate"]`).
    """
    _v = verdict(envelope, noise_floor_pct=noise_floor_pct)
    envelope["gate"] = _v
    return _v


def _check_probe(name: str,
                 block: dict[str, Any],
                 noise_floor_pct: float) -> dict[str, Any]:
    """Dispatch to the per-probe rule.

    Args:
        name (str): probe name; one of `HOST_FLOOR_PROBES`.
        block (dict[str, Any]): the probe's envelope block.
        noise_floor_pct (float): percent-spread limit.

    Returns:
        dict[str, Any]: the check block (`passed`, `value_pct`, `limit_pct`, `reason`).

    Raises:
        ValueError: if `name` is not a known probe.
    """
    _ans: dict[str, Any]
    if name == "timer":
        _ans = _check_timer(block, noise_floor_pct)
    elif name == "jitter":
        _ans = _check_jitter(block, noise_floor_pct)
    elif name == "loopback":
        _ans = _check_loopback(block, noise_floor_pct)
    elif name == "handler_scaling":
        _ans = _check_handler_scaling(block, noise_floor_pct)
    else:
        _msg = f"unknown probe {name!r}; expected one of {HOST_FLOOR_PROBES}"
        raise ValueError(_msg)
    return _ans

def _check_timer(block: dict[str, Any], noise_floor_pct: float) -> dict[str, Any]:
    """Timer probe rule: `max_ns` should be within `noise_floor_pct` of `median_ns`."""
    _ans: dict[str, Any]
    if not block or "median_ns" not in block or "max_ns" not in block:
        _ans = _missing()
    elif block["median_ns"] <= 0:
        _ans = _missing()
    else:
        _ans = _spread_check(block["max_ns"], block["median_ns"], noise_floor_pct, "timer max/median")
    return _ans


def _check_jitter(block: dict[str, Any], noise_floor_pct: float) -> dict[str, Any]:
    """Jitter probe rule: `median_us` should be within `noise_floor_pct` of `target_us`."""
    _ans: dict[str, Any]
    if not block or "median_us" not in block or "target_us" not in block:
        _ans = _missing()
    elif block["target_us"] <= 0:
        _ans = _missing()
    else:
        _ans = _spread_check(block["median_us"], block["target_us"], noise_floor_pct, "jitter median/target")
    return _ans


def _check_loopback(block: dict[str, Any], noise_floor_pct: float) -> dict[str, Any]:
    """Loopback probe rule: `p99_us` should be within `noise_floor_pct` of `median_us`."""
    _ans: dict[str, Any]
    if not block or "median_us" not in block or "p99_us" not in block:
        _ans = _missing()
    elif block["median_us"] <= 0:
        _ans = _missing()
    else:
        _ans = _spread_check(block["p99_us"], block["median_us"], noise_floor_pct, "loopback p99/median")
    return _ans


def _check_handler_scaling(block: dict[str, Any], noise_floor_pct: float) -> dict[str, Any]:
    """Handler-scaling rule: median latency at the highest concurrency should be within `noise_floor_pct` of the lowest concurrency's median."""
    _ans: dict[str, Any]
    _stats = block.get("stats", {})
    if not _stats:
        _ans = _missing()
    else:
        _cs = sorted(int(_k) for _k in _stats.keys())
        if len(_cs) < 2:
            _ans = _missing()
        else:
            _low = _stats[str(_cs[0])].get("median_us", 0.0)
            _high = _stats[str(_cs[-1])].get("median_us", 0.0)
            if _low <= 0:
                _ans = _missing()
            else:
                _ans = _spread_check(_high, _low, noise_floor_pct, f"handler c={_cs[-1]} vs c={_cs[0]}")
    return _ans


def _spread_check(numerator: float,
                  denominator: float,
                  noise_floor_pct: float,
                  label: str) -> dict[str, Any]:
    """Compute `(numerator - denominator) / denominator * 100` and verdict against `noise_floor_pct`.

    Args:
        numerator (float): the "stressed" value (e.g. p99 latency, max delta).
        denominator (float): the baseline (e.g. median).
        noise_floor_pct (float): percent-spread limit.
        label (str): human-readable tag for the `reason` line.

    Returns:
        dict[str, Any]: `passed`, `value_pct`, `limit_pct`, `reason`.
    """
    _pct = (numerator - denominator) / denominator * 100.0
    _ans: dict[str, Any] = {
        "passed": _pct <= noise_floor_pct,
        "value_pct": _pct,
        "limit_pct": noise_floor_pct,
        "reason": f"{label}: {_pct:.2f}% (limit {noise_floor_pct:.2f}%)",
    }
    return _ans


def _missing() -> dict[str, Any]:
    """Sentinel block when a probe's data is absent or unusable.

    Returns:
        dict[str, Any]: `passed=False`, `value_pct=None`, `limit_pct=None`, `reason="missing data"`. Treats absence as a failure so the gate never declares pass on an unknown apparatus.
    """
    _ans: dict[str, Any] = {
        "passed": False,
        "value_pct": None,
        "limit_pct": None,
        "reason": "missing data",
    }
    return _ans


__all__ = [
    "HOST_FLOOR_PROBES",
    "stamp_gate",
    "verdict",
]

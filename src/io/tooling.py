# -*- coding: utf-8 -*-
"""
Module io/tooling.py
====================

Loader + small derivation helpers for the per-host noise-floor calibration JSON produced by `src.scripts.calibration.run`.

Every `experiment` run is gated on having a recent calibration for the current host so measured latencies can be reported as `value - loopback_median +/- jitter_p99`. This module owns the filesystem lookup, timestamp parsing, and the two numeric accessors the reporting path needs.

Public API:
    - `find_latest_calibration(host)` -> newest JSON path for the given host, or None.
    - `load_latest_calibration(host)` -> parsed envelope, or None.
    - `calibration_floor_us(envelope)` -> loopback median in microseconds.
    - `calibration_band_us(envelope)` -> jitter p99 in microseconds.
    - `calibration_age_hours(envelope)` -> hours since the envelope was written.
"""
# native python modules
from __future__ import annotations

import json
import socket
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional


_CALIB_DIR = (Path(__file__).resolve().parents[2] / "data" / "results" / "experiment" / "calibration")


def find_latest_calibration(host: Optional[str] = None) -> Optional[Path]:
    """*find_latest_calibration()* return the newest calibration JSON path for `host`.

    Calibration envelopes are written to `data/results/experiment/calibration/<hostname>_<YYYYMMDD_HHMMSS>.json`. When `host` is `None`, the current host's name (`socket.gethostname()`) is used; calibrations written on other machines are skipped so a local run never picks up a file from a different hardware profile.

    Args:
        host (Optional[str]): hostname prefix to match; defaults to `socket.gethostname()`.

    Returns:
        Optional[Path]: newest matching path, or `None` when the directory is absent or empty.
    """
    if not _CALIB_DIR.exists():
        return None
    if host is None:
        _host = socket.gethostname()
    else:
        _host = str(host)
    # hostname is normalised the same way `src.scripts.calibration`
    # builds its output path, so the match stays symmetric.
    _host_norm = _host.replace(" ", "-")
    _prefix = f"{_host_norm}_"
    _candidates: List[Path] = []
    for _p in _CALIB_DIR.glob("*.json"):
        if _p.name.startswith(_prefix):
            _candidates.append(_p)
    if not _candidates:
        return None
    _candidates.sort(key=lambda _x: _x.stat().st_mtime)
    return _candidates[-1]


def load_latest_calibration(host: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """*load_latest_calibration()* parse and return the newest calibration envelope for `host`.

    Args:
        host (Optional[str]): hostname prefix to match; defaults to `socket.gethostname()`.

    Returns:
        Optional[Dict[str, Any]]: parsed envelope with an extra `output_path` key, or `None` when no matching file exists.
    """
    _path = find_latest_calibration(host=host)
    if _path is None:
        return None
    with _path.open(encoding="utf-8") as _fh:
        _envelope = json.load(_fh)
    _envelope["output_path"] = str(_path)
    return _envelope


def calibration_floor_us(envelope: Dict[str, Any]) -> float:
    """*calibration_floor_us()* return the loopback-median microseconds from the envelope.

    This is the irreducible host overhead that every measured experiment latency carries; subtract it from raw measurements before reporting.

    Args:
        envelope (Dict[str, Any]): calibration envelope from `load_latest_calibration`.

    Returns:
        float: loopback median in microseconds, or 0.0 when the loopback block is absent.
    """
    _loopback = envelope.get("loopback")
    if not isinstance(_loopback, dict):
        return 0.0
    return float(_loopback.get("median_us", 0.0))


def calibration_band_us(envelope: Dict[str, Any]) -> float:
    """*calibration_band_us()* return the jitter-p99 microseconds from the envelope.

    Interpreted as the measurement-uncertainty band on every reported latency.

    Args:
        envelope (Dict[str, Any]): calibration envelope from `load_latest_calibration`.

    Returns:
        float: jitter p99 in microseconds, or 0.0 when the jitter block is absent.
    """
    _jitter = envelope.get("jitter")
    if not isinstance(_jitter, dict):
        return 0.0
    return float(_jitter.get("p99_us", 0.0))


def rate_sweep_calibrated_rate(envelope: Dict[str, Any]) -> Optional[float]:
    """*rate_sweep_calibrated_rate()* highest sustainable rate from the rate-sweep block.

    Returns the `calibrated_rate` recorded by the rate-saturation probe (the highest rate whose mean loss was at or below `target_loss_pct`), or `None` when the block is absent (no rate sweep was run) or when no rate cleared the bar.

    Args:
        envelope (Dict[str, Any]): calibration envelope from `load_latest_calibration`.

    Returns:
        Optional[float]: highest sustainable rate in req/s, or `None`.
    """
    _rs = envelope.get("rate_sweep")
    if not isinstance(_rs, dict):
        return None
    _cal = _rs.get("calibrated_rate")
    if _cal is None:
        return None
    return float(_cal)


def rate_sweep_loss_at(envelope: Dict[str, Any],
                       target_rate: float) -> Optional[float]:
    """*rate_sweep_loss_at()* mean loss percentage at a specific target rate.

    Looks up the aggregate for `target_rate` in the envelope's rate-sweep block and returns its `mean_loss_pct`. Returns `None` when the rate was not measured or when the block is absent.

    Args:
        envelope (Dict[str, Any]): calibration envelope from `load_latest_calibration`.
        target_rate (float): target rate in req/s.

    Returns:
        Optional[float]: mean loss percent at `target_rate`, or `None`.
    """
    _rs = envelope.get("rate_sweep")
    if not isinstance(_rs, dict):
        return None
    _aggs = _rs.get("aggregates")
    if not isinstance(_aggs, dict):
        return None
    _key = str(target_rate)
    _agg = _aggs.get(_key)
    if _agg is None:
        # fallback for int-valued keys (e.g. "100" vs "100.0")
        _rate_float = float(target_rate)
        _rate_int = int(_rate_float)
        _key_int = str(_rate_int)
        _agg = _aggs.get(_key_int)
    if _agg is None:
        return None
    _loss = _agg.get("mean_loss_pct", 0.0)
    return float(_loss)


def calibration_age_hours(envelope: Dict[str, Any]) -> float:
    """*calibration_age_hours()* return the age of the calibration in hours.

    Reads the envelope's `timestamp` (ISO-8601, second precision) and subtracts from `datetime.now()`. Callers use this to flag stale baselines.

    Args:
        envelope (Dict[str, Any]): calibration envelope from `load_latest_calibration`.

    Returns:
        float: hours since the envelope was written; `float("inf")` when the timestamp is missing or unparseable.
    """
    _ts = envelope.get("timestamp")
    if not _ts:
        return float("inf")
    try:
        _when = datetime.fromisoformat(str(_ts))
    except ValueError:
        return float("inf")
    _now = datetime.now()
    _delta = _now - _when
    _seconds = _delta.total_seconds()
    return _seconds / 3600.0

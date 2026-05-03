# -*- coding: utf-8 -*-
"""
Module io/tooling.py
====================

Loader + small derivation helpers for the per-host noise-floor calibration JSON produced by `src.methods.calibration.run`, plus the typed-spec loader for the client load generator.

Every `experiment` run is gated on having a recent calibration for the current host so measured latencies can be reported as `value - loopback_median +/- jitter_p99`. This module owns the filesystem lookup, timestamp parsing, and the small set of numeric accessors the reporting path needs.

Public API (in code-body order):
    - `find_latest_calibration(host)` -> newest JSON path for the given host, or None.
    - `load_latest_calibration(host)` -> parsed envelope, or None.
    - `calibration_floor_us(envelope)` -> loopback median in microseconds.
    - `calibration_band_us(envelope)` -> jitter p99 in microseconds.
    - `rate_sweep_calibrated_rate(envelope)` -> highest sustainable rate (req/s) recorded by the rate-sweep block, or None.
    - `rate_sweep_loss_at(envelope, target_rate)` -> mean loss percent at `target_rate`, or None when the rate was not measured.
    - `load_dim_card(host, payload_size_bytes)` -> dimensional card dict for the latest envelope (lazy-derived if absent on disk), or None.
    - `calibration_age_hours(envelope)` -> hours since the envelope was written.
    - `load_ramp_cfg(ramp_block)` -> validated `RampCfg` from the raw `experiment.json::ramp` dict.
    - `load_client_cfg(method_cfg, *, kind_prob, entry_service)` -> full `ClientCfg` from a method config dict + arch-derived kind probabilities.
"""
# native python modules
from __future__ import annotations

import json
import socket
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

# local modules
from src.experiment.client.config import CascadeCfg, ClientCfg, RampCfg


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
    # match the `<hostname>_<YYYYMMDD_HHMMSS>.json` shape `src.methods.calibration.run` writes
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

    Raises:
        json.JSONDecodeError: when the on-disk calibration JSON is malformed (the file resolved fine but the contents do not parse).
        OSError: on filesystem failure while opening the resolved path.
    """
    _path = find_latest_calibration(host=host)
    if _path is None:
        return None
    with _path.open(encoding="utf-8") as _fh:
        _env = json.load(_fh)
    _env["output_path"] = str(_path)
    return _env


def calibration_floor_us(envelope: Dict[str, Any]) -> float:
    """*calibration_floor_us()* return the loopback-median microseconds from the envelope.

    This is the irreducible host overhead that every measured experiment latency carries; subtract it from raw measurements before reporting.

    Args:
        envelope (Dict[str, Any]): calibration envelope from `load_latest_calibration`.

    Returns:
        float: loopback median in microseconds, or 0.0 when the loopback block (or its `median_us` field) is absent.
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
        float: jitter p99 in microseconds, or 0.0 when the jitter block (or its `p99_us` field) is absent.
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
        # fall back to int-stringified key ("100" instead of "100.0") since older envelopes used int rates
        _rate_int = int(float(target_rate))
        _agg = _aggs.get(str(_rate_int))
    if _agg is None:
        return None
    _loss = _agg.get("mean_loss_pct", 0.0)
    return float(_loss)


def load_dim_card(host: Optional[str] = None,
                  *,
                  payload_size_bytes: int = 0) -> Optional[Dict[str, Any]]:
    """*load_dim_card()* fetch the Route-B dimensional card from the latest calibration envelope for `host`.

    When the envelope on disk already carries a `dimensional_card` block (the default once `src.methods.calibration.run` has been re-baked), it is returned verbatim. Otherwise the card is derived on the fly via `src.methods.calibration.derive_calib_coefs(envelope, payload_size_bytes)` so older envelopes without the block stay usable.

    Args:
        host (Optional[str]): hostname prefix; defaults to `socket.gethostname()`.
        payload_size_bytes (int): per-request body size for the phi coefficient when the card has to be derived; ignored when a pre-baked block is on disk.

    Returns:
        Optional[Dict[str, Any]]: dim-card dict (LaTeX-subscripted coefficient arrays + `meta` provenance), or `None` when no calibration exists for the host or when neither a pre-baked block nor the source blocks (`handler_scaling` + `loopback`) are present.

    Raises:
        json.JSONDecodeError: propagated from `load_latest_calibration` when the on-disk envelope is malformed.
        Exception: any error raised by the lazy `derive_calib_coefs` path (e.g. PyDASA pipeline failure) propagates unmodified.
    """
    _env = load_latest_calibration(host=host)
    if _env is None:
        return None
    _card = _env.get("dimensional_card")
    if isinstance(_card, dict) and _card:
        return _card
    # lazy import: calibration drags in fastapi/uvicorn/httpx, which the experiment-gate path does not need
    from src.methods.calibration import derive_calib_coefs
    _derived = derive_calib_coefs(_env,
                                  payload_size_bytes=payload_size_bytes)
    if not _derived:
        return None
    return _derived


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
    _delta = datetime.now() - _when
    return _delta.total_seconds() / 3600.0


# ---------------------------------------------------------------------------
# Client load-generator config loader


def _validate_ramp_block(ramp: Dict[str, Any]) -> None:
    """*_validate_ramp_block()* gate the raw `ramp` sub-dict of `experiment.json`.

    Accepts one of three drive specs (mutually exclusive): `rates` (direct list), `rho_grid` (utilisation list inverted upstream by the executor), or `anchor: "lambda_z"` (single rate read from `cfg.artifacts[entry].lambda_z` upstream by the executor).

    Raises:
        ValueError: when more than one drive spec is supplied, when none is supplied, or when any field is out of the supported range.
    """
    _n = int(ramp.get("min_samples_per_kind", 32))
    if _n < 32:
        _msg = f"ramp.min_samples_per_kind must be >= 32 for CLT validity; got {_n}"
        raise ValueError(_msg)

    _rates = ramp.get("rates", [])
    _rho_grid = ramp.get("rho_grid", [])
    _anchor = ramp.get("anchor")
    _spec_count = sum(bool(_x) for _x in (_rates, _rho_grid, _anchor))
    if _spec_count > 1:
        _msg = "ramp accepts exactly one of 'rates' / 'rho_grid' / 'anchor'"
        raise ValueError(_msg)
    if _spec_count == 0:
        _msg = ("ramp must specify 'rates' (explicit), "
                "'rho_grid' (utilisation-anchored), "
                "or 'anchor' (lambda_z-anchored)")
        raise ValueError(_msg)
    if _anchor is not None and _anchor != "lambda_z":
        _msg = f"ramp.anchor must be 'lambda_z' when set; got {_anchor!r}"
        raise ValueError(_msg)

    if _rates:
        if any(float(_r) <= 0 for _r in _rates):
            _msg = "ramp.rates must be a list of positive floats"
            raise ValueError(_msg)
        if _rates != sorted(_rates):
            _msg = "ramp.rates must be monotonically increasing"
            raise ValueError(_msg)

    if _rho_grid:
        if any(not 0.0 < float(_r) < 1.0 for _r in _rho_grid):
            _msg = "ramp.rho_grid values must be in (0, 1)"
            raise ValueError(_msg)
        if _rho_grid != sorted(_rho_grid):
            _msg = "ramp.rho_grid must be monotonically increasing"
            raise ValueError(_msg)

    _cas = ramp.get("cascade", {})
    _mode = _cas.get("mode", "rolling")
    if _mode not in ("rolling", "fail_fast"):
        _msg = f"cascade.mode must be 'rolling' or 'fail_fast', got {_mode!r}"
        raise ValueError(_msg)
    if _mode == "rolling":
        _w = int(_cas.get("window", 50))
        _t = float(_cas.get("threshold", 0.10))
        if _w < 10:
            _msg = f"cascade.window must be >= 10, got {_w}"
            raise ValueError(_msg)
        if not 0.0 < _t < 1.0:
            _msg = f"cascade.threshold must be in (0, 1), got {_t}"
            raise ValueError(_msg)


def load_ramp_cfg(ramp: Dict[str, Any]) -> RampCfg:
    """*load_ramp_cfg()* validate and materialise the `ramp` block into a `RampCfg`.

    Args:
        ramp (Dict[str, Any]): raw `ramp` block from the method config.

    Returns:
        RampCfg: populated ramp spec.

    Raises:
        ValueError: propagated from `_validate_ramp_block`.
    """
    _validate_ramp_block(ramp)
    _cas = ramp.get("cascade", {})
    return RampCfg(
        min_n_per_kind=int(ramp.get("min_samples_per_kind", 32)),
        max_probe_s=float(ramp.get("max_probe_window_s", 60.0)),
        rates=[float(_r) for _r in ramp.get("rates", [])],
        cascade=CascadeCfg(
            mode=_cas.get("mode", "rolling"),
            threshold=float(_cas.get("threshold", 0.10)),
            window=int(_cas.get("window", 50)),
        ),
    )


def load_client_cfg(method_cfg: Dict[str, Any],
                    *,
                    kind_prob: Dict[str, float],
                    entry_service: str = "TAS_{1}") -> ClientCfg:
    """*load_client_cfg()* build a full `ClientCfg` from a method-config dict.

    `kind_prob` is injected by the caller because it is derived from the live `TasArchitecture` (entry-router routing row), not from the JSON.

    Args:
        method_cfg (Dict[str, Any]): parsed `data/config/method/experiment.json`.
        kind_prob (Dict[str, float]): kind probability map from the architecture.
        entry_service (str): entry-router service name; defaults to `TAS_{1}`.

    Returns:
        ClientCfg: spec ready for `ClientSimulator(...)`.

    Raises:
        ValueError: propagated from `load_ramp_cfg`.
        KeyError: when `method_cfg` is missing `seed`.
    """
    _seed = int(method_cfg["seed"])
    _sizes_by_kind = dict(method_cfg.get("request_size_bytes", {}))
    _req_size = int(_sizes_by_kind.get("analyse_request", 256))
    _ramp_block = dict(method_cfg.get("ramp", {}))
    return ClientCfg(
        entry_service=entry_service,
        seed=_seed,
        req_size_b=_req_size,
        req_sizes_by_kind=_sizes_by_kind,
        kind_prob=dict(kind_prob),
        ramp=load_ramp_cfg(_ramp_block),
    )

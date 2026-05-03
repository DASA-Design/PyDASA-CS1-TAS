# -*- coding: utf-8 -*-
"""
Module calibration/rate.py
==========================

Rate-saturation discovery probe. Drives the standalone vernier ping/echo service at N target rates with `trials_per_rate` trials each; returns per-rate aggregates plus the highest rate whose mean loss is at or below the configured threshold. One vernier instance is reused across the whole sweep, decoupled from the TAS profile entirely; full-mesh saturation testing belongs in the experiment notebook, not here.

Public API:
    - `run_rate_sweep(rates, trials_per_rate, max_probe_s, target_loss_pct, ...)`: sync entry; returns the rate-sweep envelope block.
    - `find_highest_sustainable_rate(aggregates, threshold_pct)`: post-processing helper.
    - `batch_size_for(rate)`: per-tick send-batch derivation; reported in the verbose banner so an operator can correlate rate loss with batch behaviour.
"""
# native python modules
from __future__ import annotations

import asyncio
import time
from typing import Any, Dict, List, Optional, Tuple, cast

# scientific stack
import numpy as np

# web stack
import httpx

# local modules
from src.calibration.hoststats import (_DEFAULT_HTTPX_TIMEOUT_S,
                                       _DEFAULT_PAYLOAD_SIZE_BYTES,
                                       _build_probe_body,
                                       stats_from_us_array)
from src.experiment.instances import make_gauge_factory
from src.experiment.runtime import UvicornThread, run_async_safe
from src.experiment.services import SvcSpec


# scheduler tick (s) the auto-batch derivation amortises over; mirrors `ClientSimulator._probe_at_rate`
_TARGET_TICK_S: float = 0.020

# defaults match data/config/method/calibration.json::rate_sweep; the orchestrator (Stage C9) passes JSON-loaded values explicitly
_DEFAULT_RATE_SWEEP_RATES: Tuple[float, ...] = (10.0, 50.0, 200.0, 300.0, 400.0)
_DEFAULT_RATE_SWEEP_TRIALS: int = 5
_DEFAULT_RATE_SWEEP_PROBE_S: float = 1.5
_DEFAULT_RATE_SWEEP_TARGET_LOSS_PCT: float = 2.5
_DEFAULT_INTER_TRIAL_DELAY_S: float = 1.5
_DEFAULT_PORT: int = 8765
_DEFAULT_READY_TIMEOUT_S: float = 2.0


def batch_size_for(rate: float) -> int:
    """*batch_size_for()* per-scheduler-tick send-batch size at a given target rate.

    The client wakes on a `_TARGET_TICK_S` cadence and fires `round(_TARGET_TICK_S / interarrival)` requests per wake to amortise per-iteration overhead. NOT the M/M/c/K system capacity.

    Args:
        rate (float): target rate in req/s.

    Returns:
        int: batch size; clamped to >= 1.
    """
    if rate <= 0:
        return 1
    _interarrival = 1.0 / rate
    _batch = int(round(_TARGET_TICK_S / _interarrival))
    return max(1, _batch)


async def _post_one(client: httpx.AsyncClient,
                    body: Dict[str, Any],
                    rtts_ns: List[int]) -> None:
    """*_post_one()* one POST `/invoke` bracketed by `perf_counter_ns`; appends elapsed ns to `rtts_ns` on success.

    Transient connection errors (httpx.HTTPError, ConnectionError, OSError) are silently dropped; the caller's stats reflect successful samples only.

    Args:
        client (httpx.AsyncClient): shared client; the caller controls keep-alive limits.
        body (Dict[str, Any]): pre-built request body reused across calls.
        rtts_ns (List[int]): shared list; appended to on success.
    """
    _t1 = time.perf_counter_ns()
    try:
        await client.post("/invoke", json=body)
        rtts_ns.append(time.perf_counter_ns() - _t1)
    except (httpx.HTTPError, ConnectionError, OSError):
        pass


async def _drive_lambda_step(port: int,
                             target_rate: float,
                             window_s: float,
                             body: Dict[str, Any]) -> Dict[str, float]:
    """*_drive_lambda_step()* fire at `target_rate` for `window_s` seconds and return latency stats.

    Absolute-deadline scheduling: each request anchors on `_start + idx * interarrival` so the actual arrival rate tracks the target across the window. Each request runs as its own task so observed latencies reflect concurrent in-flight, not serialised arrivals.

    Args:
        port (int): vernier server port.
        target_rate (float): target arrivals per second.
        window_s (float): wall-clock probe window in seconds.
        body (Dict[str, Any]): pre-built `SvcReq.model_dump()` reused per request.

    Returns:
        Dict[str, float]: percentile stats keyed identically to a `handler_scaling[<level>]` entry.
    """
    _interarrival = 1.0 / max(float(target_rate), 1e-6)
    _base = f"http://127.0.0.1:{port}"
    _rtts_ns: List[int] = []
    _limits = httpx.Limits(max_connections=4096, max_keepalive_connections=4096)
    _timeout = httpx.Timeout(_DEFAULT_HTTPX_TIMEOUT_S)
    async with httpx.AsyncClient(base_url=_base,
                                 limits=_limits,
                                 timeout=_timeout) as _client:
        _start = time.perf_counter()
        _deadline = _start + float(window_s)
        _idx = 0
        _tasks: List[asyncio.Task[None]] = []
        _running = True
        while _running:
            _now = time.perf_counter()
            if _now >= _deadline:
                _running = False
                continue
            _target_t = _start + _idx * _interarrival
            _wait = _target_t - _now
            if _wait > 0:
                await asyncio.sleep(_wait)
            _tasks.append(asyncio.create_task(
                _post_one(_client, body, _rtts_ns)))
            _idx += 1
        if _tasks:
            await asyncio.gather(*_tasks, return_exceptions=True)

    if not _rtts_ns:
        return stats_from_us_array(np.asarray([], dtype=np.float64))
    _us = np.asarray(_rtts_ns, dtype=np.int64) / 1000.0
    return stats_from_us_array(_us)


def _summarise_trial(rate: float,
                     stats: Dict[str, float],
                     window_s: float) -> Dict[str, float]:
    """*_summarise_trial()* per-trial achieved-rate + loss summary.

    `samples` is the count of completed `POST /invoke` requests in the probe window. Achieved rate = samples / window_s. Loss is the gap fraction relative to target.

    Args:
        rate (float): target rate driven in this trial (req/s).
        stats (Dict[str, float]): one entry from `_drive_lambda_step` (handler_scaling-shaped).
        window_s (float): wall-clock window the probe ran for (seconds).

    Returns:
        Dict[str, float]: `{target, effective, gap, loss_pct}`.
    """
    _samples = float(stats.get("samples", 0.0))
    if window_s > 0:
        _eff = _samples / window_s
    else:
        _eff = 0.0
    _target = float(rate)
    _gap = _target - _eff
    if rate > 0:
        _loss = _gap / rate * 100.0
    else:
        _loss = 0.0
    return {
        "target": _target,
        "effective": _eff,
        "gap": _gap,
        "loss_pct": _loss,
    }


def _aggregate_trials(trials: List[Dict[str, float]]) -> Dict[str, float]:
    """*_aggregate_trials()* roll up N trials at one target rate into mean / range / mean-loss.

    Args:
        trials (List[Dict[str, float]]): per-trial summaries from `_summarise_trial`.

    Returns:
        Dict[str, float]: `{target, mean, lo, hi, mean_loss_pct, n}`. Empty input yields all zeros.
    """
    _effs: List[float] = []
    for _t in trials:
        _effs.append(float(_t["effective"]))
    _n = len(_effs)
    if _n == 0:
        return {
            "target": 0.0, "mean": 0.0, "lo": 0.0, "hi": 0.0,
            "mean_loss_pct": 0.0, "n": 0,
        }
    _mean = sum(_effs) / _n
    _lo = min(_effs)
    _hi = max(_effs)
    _target = float(trials[0]["target"])
    if _target > 0:
        _mean_loss = (_target - _mean) / _target * 100.0
    else:
        _mean_loss = 0.0
    return {
        "target": _target, "mean": _mean, "lo": _lo, "hi": _hi,
        "mean_loss_pct": _mean_loss, "n": _n,
    }


def _print_rate_header(rate: float) -> None:
    """*_print_rate_header()* one-line banner per rate (target, interarrival, send batch)."""
    _interarrival_ms = 1000.0 / rate
    _batch = batch_size_for(rate)
    print(f"--- target rate {rate:>6.1f} req/s  "
          f"(interarrival {_interarrival_ms:.2f} ms, batch={_batch}) ---",
          flush=True)


def _print_rate_aggregate(agg: Dict[str, float]) -> None:
    """*_print_rate_aggregate()* one-line aggregate across all trials at a rate."""
    _mean = agg["mean"]
    _lo = agg["lo"]
    _hi = agg["hi"]
    _loss = agg["mean_loss_pct"]
    print(f"  >>> mean={_mean:>7.2f}  "
          f"range=[{_lo:>6.2f}, {_hi:>6.2f}]  "
          f"mean_loss={_loss:>+6.2f}%",
          flush=True)


def find_highest_sustainable_rate(aggregates: Dict[float, Dict[str, float]],
                                  threshold_pct: float
                                  ) -> Optional[float]:
    """*find_highest_sustainable_rate()* highest rate whose `|mean_loss_pct| <= threshold_pct`.

    Walks the aggregates in ascending rate order; returns the last rate that cleared the bar. The absolute value handles over-delivery as well as under-delivery; both surface as a failed precondition.

    Args:
        aggregates (Dict[float, Dict[str, float]]): per-rate aggregate from `_aggregate_trials`.
        threshold_pct (float): maximum allowed `|mean_loss|` in percent.

    Returns:
        Optional[float]: highest passing rate, or None when no rate cleared the bar.
    """
    _sorted = sorted(aggregates.items(), key=lambda _kv: _kv[0])
    _best: Optional[float] = None
    for _rate, _agg in _sorted:
        _loss = abs(float(_agg.get("mean_loss_pct", 0.0)))
        if _loss <= threshold_pct:
            _best = _rate
    return _best


def _vernier_spec(port: int, payload_size_bytes: int) -> SvcSpec:
    """*_vernier_spec()* canonical rate-sweep vernier spec: `c=1, K=10, mu=0, epsilon=0`.

    Args:
        port (int): TCP port.
        payload_size_bytes (int): drives `mem_per_buffer = payload * K * MEM_HEADROOM_FACTOR`.

    Returns:
        SvcSpec: vernier spec named `"CALIB_RATE"`.
    """
    _K = 10
    return SvcSpec(name="CALIB_RATE",
                   role="atomic",
                   port=int(port),
                   mu=0.0,
                   epsilon=0.0,
                   c=1,
                   K=_K,
                   seed=0,
                   mem_per_buffer=int(payload_size_bytes * _K
                                      * SvcSpec.MEM_HEADROOM_FACTOR))


async def _run_rate_sweep_async(rates: List[float],
                                trials_per_rate: int,
                                window_s: float,
                                inter_trial_delay_s: float,
                                port: int,
                                payload_size_bytes: int,
                                ready_timeout_s: float,
                                verbose: bool
                                ) -> Dict[float, List[Dict[str, float]]]:
    """*_run_rate_sweep_async()* spin up one vernier and drive it across rates x trials.

    Single uvicorn instance reused across the whole sweep. Each trial calls `_drive_lambda_step(rate, window_s)` and converts the returned `samples` count into an achieved rate via `_summarise_trial`.

    Args:
        rates (List[float]): target rates (req/s) to drive.
        trials_per_rate (int): trials per rate.
        window_s (float): wall-clock window per trial.
        inter_trial_delay_s (float): quiet seconds between rates (skipped before the first rate).
        port (int): TCP port for the vernier.
        payload_size_bytes (int): per-request body size.
        ready_timeout_s (float): seconds to wait for uvicorn readiness.
        verbose (bool): when True, print per-rate banners + aggregate lines.

    Returns:
        Dict[float, List[Dict[str, float]]]: `{rate: [trial_summary, ...]}` keyed by target rate.
    """
    _trials_by_rate: Dict[float, List[Dict[str, float]]] = {}
    _spec = _vernier_spec(port, payload_size_bytes)
    _factory = make_gauge_factory(_spec, payload_size_bytes=payload_size_bytes)
    _server = UvicornThread(_factory(), port=port)
    _server.start()
    try:
        _server.wait_ready(timeout_s=ready_timeout_s)
        _body = _build_probe_body(payload_size_bytes)
        for _r_idx, _rate in enumerate(rates):
            if _r_idx > 0 and inter_trial_delay_s > 0.0:
                await asyncio.sleep(inter_trial_delay_s)
            if verbose:
                print()
                _print_rate_header(_rate)
            _trials: List[Dict[str, float]] = []
            for _trial in range(int(trials_per_rate)):
                _stats = await _drive_lambda_step(port=port,
                                                  target_rate=float(_rate),
                                                  window_s=float(window_s),
                                                  body=_body)
                _trials.append(_summarise_trial(_rate, _stats, window_s))
            _trials_by_rate[_rate] = _trials
    finally:
        _server.shutdown()
    return _trials_by_rate


def run_rate_sweep(*,
                   rates: Tuple[float, ...] = _DEFAULT_RATE_SWEEP_RATES,
                   trials_per_rate: int = _DEFAULT_RATE_SWEEP_TRIALS,
                   max_probe_s: float = _DEFAULT_RATE_SWEEP_PROBE_S,
                   target_loss_pct: float = _DEFAULT_RATE_SWEEP_TARGET_LOSS_PCT,
                   calibrate: bool = False,
                   inter_trial_delay_s: float = _DEFAULT_INTER_TRIAL_DELAY_S,
                   port: int = _DEFAULT_PORT,
                   payload_size_bytes: int = _DEFAULT_PAYLOAD_SIZE_BYTES,
                   ready_timeout_s: float = _DEFAULT_READY_TIMEOUT_S,
                   verbose: bool = True) -> Dict[str, Any]:
    """*run_rate_sweep()* drive the standalone vernier at N target rates with `trials_per_rate` trials each.

    Characterises pure host-transport saturation: how fast the host's loopback + uvicorn + FastAPI stack sustains traffic with zero application logic in the way. One vernier instance is reused across the whole sweep. When `calibrate=True`, additionally reports the highest rate whose `|mean_loss| <= target_loss_pct`.

    Args:
        rates (Tuple[float, ...]): target rates (req/s) to drive.
        trials_per_rate (int): trials per rate for aggregation.
        max_probe_s (float): wall-clock window per trial (seconds). Achieved rate = samples / max_probe_s.
        target_loss_pct (float): pass bar for the `calibrate` result.
        calibrate (bool): when True, include the highest-sustainable-rate finding in the result.
        inter_trial_delay_s (float): quiet seconds between rates (skipped before the first rate).
        port (int): TCP port for the vernier.
        payload_size_bytes (int): per-request body size for the probe.
        ready_timeout_s (float): seconds to wait for uvicorn readiness.
        verbose (bool): when True, print per-rate banners + aggregate lines.

    Returns:
        Dict[str, Any]: `{rates, trials_per_rate, max_probe_window_s, target_loss_pct, aggregates, per_trial, calibrated_rate (if calibrate), elapsed_s}`. `aggregates` and `per_trial` are keyed by stringified rates for JSON-friendliness.
    """
    _t0 = time.perf_counter()
    _rates_list: List[float] = sorted(set(float(_r) for _r in rates))

    async def _orchestrator() -> Dict[float, List[Dict[str, float]]]:
        return await _run_rate_sweep_async(
            rates=_rates_list,
            trials_per_rate=int(trials_per_rate),
            window_s=float(max_probe_s),
            inter_trial_delay_s=float(inter_trial_delay_s),
            port=int(port),
            payload_size_bytes=int(payload_size_bytes),
            ready_timeout_s=float(ready_timeout_s),
            verbose=bool(verbose),
        )

    _trials_by_rate = cast(
        Dict[float, List[Dict[str, float]]],
        run_async_safe(_orchestrator),  # type: ignore[arg-type]
    )

    _aggregates: Dict[float, Dict[str, float]] = {}
    _per_trial: Dict[float, List[Dict[str, float]]] = {}
    for _rate in _rates_list:
        _trials = _trials_by_rate.get(_rate, [])
        _agg = _aggregate_trials(_trials)
        _aggregates[_rate] = _agg
        _per_trial[_rate] = _trials
        if verbose:
            _print_rate_aggregate(_agg)

    _t_end = time.perf_counter()
    _elapsed = round(_t_end - _t0, 3)

    _aggregates_json: Dict[str, Dict[str, float]] = {}
    for _rate_key, _agg_val in _aggregates.items():
        _aggregates_json[str(_rate_key)] = _agg_val
    _per_trial_json: Dict[str, List[Dict[str, float]]] = {}
    for _rate_key, _trials_val in _per_trial.items():
        _per_trial_json[str(_rate_key)] = _trials_val

    _ans: Dict[str, Any] = {
        "rates": _rates_list,
        "trials_per_rate": int(trials_per_rate),
        "max_probe_window_s": float(max_probe_s),
        "target_loss_pct": float(target_loss_pct),
        "aggregates": _aggregates_json,
        "per_trial": _per_trial_json,
        "elapsed_s": _elapsed,
    }
    if calibrate:
        _ans["calibrated_rate"] = find_highest_sustainable_rate(
            _aggregates, float(target_loss_pct))
    return _ans

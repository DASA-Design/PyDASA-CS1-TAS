# -*- coding: utf-8 -*-
"""
Module calibration/stability.py
===============================

Apparatus-self-consistency probe. For each `(n_con_usr, c)` cell in the 2D grid, runs `trials_per_cell` independent trials of `measure_handler_scaling` against a vernier configured with that `c`, collects the per-trial median, scores the cell by `error_metric`, then selects the per-level `c` via `selection_rule`.

The selected per-level `c` array (`selected_c_per_n_con_usr`) feeds the rest of the calibration when `c_per_n_con_usr` is null in config: the `min_c_meeting_target` rule answers "what is the smallest server-side parallelism that holds the per-level CI inside the precondition gate's 5%?".

Public API:
    - `run_handler_stability_sweep(n_con_usr, c_grid, trials_per_cell, ...)`: sync entry; returns the stability-sweep envelope block.
    - `aggregate_stability_cell(trial_medians_us, error_metric)`: pure cell-level scoring helper.
    - `select_c_per_n_con_usr(cells, n_grid, c_grid, target_error_pct, selection_rule)`: pure per-level selector.
"""
# native python modules
from __future__ import annotations

import asyncio
import time
from typing import Any, Dict, List, Tuple, cast

# scientific stack
import numpy as np

# local modules
from src.calibration.hoststats import (_DEFAULT_PAYLOAD_SIZE_BYTES,
                                       _DEFAULT_SAMPLES_PER_LEVEL,
                                       measure_handler_scaling)
from src.experiment.instances import make_gauge_factory
from src.experiment.runtime import UvicornThread, run_async_safe
from src.experiment.services import SvcSpec


# defaults match data/config/method/calibration.json::handler_stability_sweep
_DEFAULT_HSS_C_GRID: Tuple[int, ...] = (1, 2, 4, 8, 16, 32, 64, 128)
_DEFAULT_HSS_TRIALS: int = 5
_DEFAULT_HSS_TARGET_ERROR_PCT: float = 2.5
_DEFAULT_HSS_ERROR_METRIC: str = "relative_std_of_median"
_DEFAULT_HSS_SELECTION_RULE: str = "min_c_meeting_target"
_DEFAULT_HSS_INTER_CELL_DELAY_S: float = 1.0
_DEFAULT_PORT: int = 8765
_DEFAULT_READY_TIMEOUT_S: float = 2.0
_DEFAULT_LOOPBACK_WARMUP: int = 500
_DEFAULT_UVICORN_BACKLOG: int = 16384


def aggregate_stability_cell(trial_medians_us: List[float],
                             error_metric: str) -> Dict[str, float]:
    """*aggregate_stability_cell()* score a single `(n_con_usr, c)` cell.

    The cell holds one median latency per trial; the metric collapses those into a single relative-error number for the selector. Currently `relative_std_of_median` is the only metric implemented; unknown metrics return `error_pct=NaN` so the selector logs a warning rather than crashing.

    Args:
        trial_medians_us (List[float]): per-trial median latency (us).
        error_metric (str): metric name. Supported: `"relative_std_of_median"` -> `std(trials) / mean(trials) * 100`.

    Returns:
        Dict[str, float]: `{mean_median_us, std_median_us, error_pct, n_trials}`. Empty or single-sample cells produce `error_pct=NaN`.
    """
    _n = len(trial_medians_us)
    if _n == 0:
        return {
            "mean_median_us": 0.0,
            "std_median_us": 0.0,
            "error_pct": float("nan"),
            "n_trials": 0,
        }
    _arr = np.asarray(trial_medians_us, dtype=float)
    _mean = float(_arr.mean())
    if _n > 1:
        _std = float(_arr.std(ddof=1))
    else:
        _std = 0.0
    if error_metric == "relative_std_of_median":
        if _mean > 0.0 and _n > 1:
            _err = _std / _mean * 100.0
        else:
            _err = float("nan")
    else:
        _err = float("nan")
    return {
        "mean_median_us": _mean,
        "std_median_us": _std,
        "error_pct": _err,
        "n_trials": int(_n),
    }


def select_c_per_n_con_usr(cells: Dict[Tuple[int, int], Dict[str, float]],
                           n_con_usr_grid: List[int],
                           c_grid: List[int],
                           target_error_pct: float,
                           selection_rule: str) -> List[int]:
    """*select_c_per_n_con_usr()* derive the per-level `c` array from the swept cells.

    Walks each `n_con_usr` level in `n_con_usr_grid`; collects every cell at that level keyed by `c`. Applies the rule:

        - `"min_c_meeting_target"`: smallest `c` whose `error_pct <= target_error_pct`. Falls back to `argmin_error` when no `c` clears the bar.
        - `"argmin_error"`: `c` with the minimum `error_pct` regardless of the target.

    Empty rows fall back to the smallest c in `c_grid`.

    Args:
        cells (Dict[Tuple[int, int], Dict[str, float]]): `{(n, c): cell_stats}` from `aggregate_stability_cell`.
        n_con_usr_grid (List[int]): the levels in the order they appear in the output array.
        c_grid (List[int]): the c values that were swept; iterated in ascending order.
        target_error_pct (float): the gate (e.g. 2.5).
        selection_rule (str): `"min_c_meeting_target"` or `"argmin_error"`.

    Returns:
        List[int]: per-level chosen c (length == `len(n_con_usr_grid)`).
    """
    _selected: List[int] = []
    _c_sorted = sorted(int(_c) for _c in c_grid)
    for _n in n_con_usr_grid:
        _row: List[Tuple[int, float]] = []
        for _c in _c_sorted:
            _cell = cells.get((int(_n), int(_c)))
            if _cell is None:
                continue
            _err = float(_cell.get("error_pct", float("nan")))
            _row.append((int(_c), _err))
        if not _row:
            _selected.append(int(_c_sorted[0]))
            continue
        if selection_rule == "min_c_meeting_target":
            _meeting: List[Tuple[int, float]] = []
            for _c_val, _err in _row:
                if not np.isnan(_err) and _err <= float(target_error_pct):
                    _meeting.append((_c_val, _err))
            if _meeting:
                _selected.append(min(_c for _c, _ in _meeting))
                continue
            _valid = [(_c, _err) for _c, _err in _row if not np.isnan(_err)]
            if _valid:
                _selected.append(min(_valid, key=lambda _kv: _kv[1])[0])
            else:
                _selected.append(int(_c_sorted[0]))
        else:
            _valid = [(_c, _err) for _c, _err in _row if not np.isnan(_err)]
            if _valid:
                _selected.append(min(_valid, key=lambda _kv: _kv[1])[0])
            else:
                _selected.append(int(_c_sorted[0]))
    return _selected


def _vernier_spec_for_c(c_srv: int,
                        port: int,
                        payload_size_bytes: int) -> SvcSpec:
    """*_vernier_spec_for_c()* build a vernier spec with custom server-side parallelism for one cell.

    `K` is set to `_DEFAULT_UVICORN_BACKLOG` so K-overflow rejection is effectively off during the probe (we measure the server's response under stable load, not under saturation).

    Args:
        c_srv (int): server-side handler count for this cell.
        port (int): TCP port.
        payload_size_bytes (int): drives `mem_per_buffer = payload * K * MEM_HEADROOM_FACTOR`.

    Returns:
        SvcSpec: vernier spec named `"CALIB_HSS_c<c_srv>"`.
    """
    _K = int(_DEFAULT_UVICORN_BACKLOG)
    return SvcSpec(name=f"CALIB_HSS_c{c_srv}",
                   role="atomic",
                   port=int(port),
                   mu=0.0,
                   epsilon=0.0,
                   c=int(c_srv),
                   K=_K,
                   seed=0,
                   mem_per_buffer=int(payload_size_bytes * _K
                                      * SvcSpec.MEM_HEADROOM_FACTOR))


async def _run_handler_stability_sweep_async(n_con_usr: List[int],
                                             c_grid: List[int],
                                             trials_per_cell: int,
                                             samples_per_level: int,
                                             warmup: int,
                                             port: int,
                                             payload_size_bytes: int,
                                             ready_timeout_s: float,
                                             inter_cell_delay_s: float,
                                             verbose: bool
                                             ) -> Dict[Tuple[int, int], List[float]]:
    """*_run_handler_stability_sweep_async()* run the 2D `(n_con_usr × c)` probe.

    Outer loop iterates `c_grid`; for each `c`, mounts a fresh vernier with that handler count and runs `trials_per_cell` independent trials of `measure_handler_scaling` over the full `n_con_usr` ladder. Per-trial per-level median latency is collected.

    Args:
        n_con_usr (List[int]): client-side concurrent-user load levels.
        c_grid (List[int]): server-side handler counts to sweep.
        trials_per_cell (int): independent trials per `(n, c)` cell.
        samples_per_level (int): forwarded to `measure_handler_scaling`.
        warmup (int): warmup requests per trial.
        port (int): TCP port for the vernier.
        payload_size_bytes (int): per-request body size.
        ready_timeout_s (float): seconds to wait for uvicorn readiness.
        inter_cell_delay_s (float): quiet seconds between c values (vernier rebind cushion).
        verbose (bool): when True, print per-c banner + per-trial progress.

    Returns:
        Dict[Tuple[int, int], List[float]]: `{(n_con_usr, c): [trial_median_us, ...]}`.
    """
    _trial_medians: Dict[Tuple[int, int], List[float]] = {}
    _n_tuple: Tuple[int, ...] = tuple(int(_n) for _n in n_con_usr)
    for _c_idx, _c_val in enumerate(sorted(int(_c) for _c in c_grid)):
        if _c_idx > 0 and inter_cell_delay_s > 0.0:
            await asyncio.sleep(inter_cell_delay_s)
        if verbose:
            print(f"\n--- handler-stability sweep: c={_c_val} "
                  f"({_c_idx + 1}/{len(c_grid)}) ---", flush=True)
        _spec = _vernier_spec_for_c(int(_c_val), port, payload_size_bytes)
        _factory = make_gauge_factory(_spec, payload_size_bytes=payload_size_bytes)
        _server = UvicornThread(_factory(), port=port)
        _server.start()
        try:
            _server.wait_ready(timeout_s=ready_timeout_s)
            for _trial in range(int(trials_per_cell)):
                if verbose:
                    print(f"  trial {_trial + 1}/{trials_per_cell} ...",
                          end="", flush=True)
                _stats_per_n = await measure_handler_scaling(
                    port=port,
                    n_con_usr=_n_tuple,
                    warmup=int(warmup),
                    per_worker=None,
                    samples_per_level=int(samples_per_level),
                    inter_level_delay_s=0.0,
                    payload_size_bytes=int(payload_size_bytes),
                )
                for _n_key_str, _stats in _stats_per_n.items():
                    _n_int = int(_n_key_str)
                    _key = (_n_int, int(_c_val))
                    _med = float(_stats.get("median_us", 0.0))
                    _trial_medians.setdefault(_key, []).append(_med)
                if verbose:
                    print(" done", flush=True)
        finally:
            _server.shutdown()
    return _trial_medians


def run_handler_stability_sweep(*,
                                n_con_usr: Tuple[int, ...] = (1, 2, 4, 8, 16, 32, 64, 96, 128),
                                c_grid: Tuple[int, ...] = _DEFAULT_HSS_C_GRID,
                                trials_per_cell: int = _DEFAULT_HSS_TRIALS,
                                target_error_pct: float = _DEFAULT_HSS_TARGET_ERROR_PCT,
                                error_metric: str = _DEFAULT_HSS_ERROR_METRIC,
                                selection_rule: str = _DEFAULT_HSS_SELECTION_RULE,
                                samples_per_level: int = _DEFAULT_SAMPLES_PER_LEVEL,
                                warmup: int = _DEFAULT_LOOPBACK_WARMUP,
                                port: int = _DEFAULT_PORT,
                                payload_size_bytes: int = _DEFAULT_PAYLOAD_SIZE_BYTES,
                                ready_timeout_s: float = _DEFAULT_READY_TIMEOUT_S,
                                inter_cell_delay_s: float = _DEFAULT_HSS_INTER_CELL_DELAY_S,
                                verbose: bool = True
                                ) -> Dict[str, Any]:
    """*run_handler_stability_sweep()* drive the 2D `(n_con_usr × c)` probe and select per-level c.

    For each `(n_con_usr, c)` cell, runs `trials_per_cell` independent trials of `measure_handler_scaling`, collects per-trial median, scores by `error_metric`, then selects the per-level c via `selection_rule`.

    Args:
        n_con_usr (Tuple[int, ...]): concurrent-user load levels.
        c_grid (Tuple[int, ...]): server-side handler counts to sweep.
        trials_per_cell (int): independent trials per cell (CLT floor 5).
        target_error_pct (float): error gate for `min_c_meeting_target`.
        error_metric (str): cell scoring metric; currently `"relative_std_of_median"`.
        selection_rule (str): `"min_c_meeting_target"` (default; falls back to `argmin_error` when no c clears the bar) or `"argmin_error"`.
        samples_per_level (int): forwarded to `measure_handler_scaling`.
        warmup (int): forwarded to `measure_handler_scaling`.
        port (int): TCP port for the vernier.
        payload_size_bytes (int): per-request body size.
        ready_timeout_s (float): seconds to wait for uvicorn readiness.
        inter_cell_delay_s (float): quiet seconds between c values (vernier rebind cushion).
        verbose (bool): per-c banners + per-cell progress prints.

    Returns:
        Dict[str, Any]: `{n_con_usr_grid, c_grid, cells, selected_c_per_n_con_usr, target_error_pct, error_metric, selection_rule, trials_per_cell, elapsed_s}`. `cells` is keyed by `"n=<n>,c=<c>"` strings (JSON-friendly) and each value carries the `aggregate_stability_cell` shape.
    """
    _t0 = time.perf_counter()
    _n_list: List[int] = sorted(int(_n) for _n in n_con_usr)
    _c_list: List[int] = sorted(int(_c) for _c in c_grid)

    async def _orchestrator() -> Dict[Tuple[int, int], List[float]]:
        return await _run_handler_stability_sweep_async(
            n_con_usr=_n_list,
            c_grid=_c_list,
            trials_per_cell=int(trials_per_cell),
            samples_per_level=int(samples_per_level),
            warmup=int(warmup),
            port=int(port),
            payload_size_bytes=int(payload_size_bytes),
            ready_timeout_s=float(ready_timeout_s),
            inter_cell_delay_s=float(inter_cell_delay_s),
            verbose=bool(verbose),
        )

    _trial_medians = cast(
        Dict[Tuple[int, int], List[float]],
        run_async_safe(_orchestrator),  # type: ignore[arg-type]
    )

    _cells: Dict[Tuple[int, int], Dict[str, float]] = {}
    for _key, _trials in _trial_medians.items():
        _cells[_key] = aggregate_stability_cell(_trials, error_metric)

    _selected = select_c_per_n_con_usr(
        cells=_cells,
        n_con_usr_grid=_n_list,
        c_grid=_c_list,
        target_error_pct=float(target_error_pct),
        selection_rule=str(selection_rule),
    )

    if verbose:
        print("\n--- handler-stability selection ---", flush=True)
        for _n, _c_sel in zip(_n_list, _selected):
            _err = _cells.get((_n, _c_sel), {}).get("error_pct", float("nan"))
            print(f"  n_con_usr={_n:>5}  ->  c={_c_sel:>4}  "
                  f"(error_pct={_err:.2f}%)", flush=True)

    _cells_json: Dict[str, Dict[str, float]] = {}
    for (_n_k, _c_k), _val in _cells.items():
        _cells_json[f"n={_n_k},c={_c_k}"] = _val

    _t_end = time.perf_counter()
    return {
        "n_con_usr_grid": _n_list,
        "c_grid": _c_list,
        "trials_per_cell": int(trials_per_cell),
        "target_error_pct": float(target_error_pct),
        "error_metric": str(error_metric),
        "selection_rule": str(selection_rule),
        "cells": _cells_json,
        "selected_c_per_n_con_usr": _selected,
        "elapsed_s": round(_t_end - _t0, 3),
    }

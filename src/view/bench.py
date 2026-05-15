# -*- coding: utf-8 -*-
"""Plotters for the multi-trial apparatus benchmark.

Three panels rendering the per-cell benchmark (adaptations x frameworks x
granularities):

- `plot_verdict_matrix`: side-by-side R1 / R2 PASS-FAIL heatmaps; cell colour encodes the verdict, the median value is overlaid.
- `plot_x0_distribution`: per-cell `X_0` median bars with min-max range caps, grouped by adaptation, with the `lambda_z` design line.
- `plot_rs_by_stack`: per-cell `R_s` median bars on a log axis against the R2 threshold line.

All three consume the aggregated frame from `src.experimental.procedure.bench.summarize_bench`. The cell axes (adaptations, stacks) and the R1 / R2 thresholds + design `lambda_z` are read off the frame itself (`.attrs`), so the plotters carry no benchmark constants of their own. Each returns the `matplotlib.figure.Figure`; the caller owns the lifecycle and `_save_figure` writes PNG + SVG when `file_path` is given.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
from matplotlib.figure import Figure

from src.view.common import (
    _NEUTRAL_BAR,
    _TEXT_BLACK,
    _generate_color_map,
    _save_figure,
)


def _stack_label(framework: str, granularity: str) -> str:
    """Return the compact `framework/granularity` axis-tick label."""
    return f"{framework}/{granularity}"


def _bench_axes(df: pd.DataFrame) -> tuple[list[str], list[tuple[str, str]]]:
    """Return the cell axes: the adaptations and the `(framework, granularity)` stacks, in the frame's order.

    Args:
        df (pd.DataFrame): aggregated table from `summarize_bench`.

    Returns:
        tuple[list[str], list[tuple[str, str]]]: adaptations and stacks.
    """
    _adps = list(dict.fromkeys(df["adaptation"]))
    _stacks = list(dict.fromkeys(zip(df["framework"], df["granularity"])))
    return _adps, _stacks


def _bench_params(df: pd.DataFrame) -> tuple[float, float, float]:
    """Return `(r1_max, r2_max_ms, lambda_z)` from the frame's `.attrs`.

    Args:
        df (pd.DataFrame): aggregated table from `summarize_bench`.

    Returns:
        tuple[float, float, float]: R1 ceiling (fraction), R2 ceiling (ms), design arrival rate (req/s).

    Raises:
        ValueError: when the frame lacks the attrs; pass a frame straight from `summarize_bench`.
    """
    try:
        return (float(df.attrs["r1_max"]),
                float(df.attrs["r2_max_ms"]),
                float(df.attrs["lambda_z"]))
    except KeyError as _err:
        _msg = f"benchmark frame missing .attrs[{_err}]; use summarize_bench()"
        raise ValueError(_msg) from _err


def _cell_row(df: pd.DataFrame,
              adp: str,
              framework: str,
              granularity: str) -> pd.Series | None:
    """Return the single row matching `(adp, framework, granularity)`, or None when the cell is absent.

    Args:
        df (pd.DataFrame): aggregated table from `summarize_bench`.
        adp (str): adaptation key.
        framework (str): `"fastapi"` or `"flask"`.
        granularity (str): `"collapsed"` or `"expanded"`.

    Returns:
        pd.Series | None: the matching row, or None.
    """
    _sel = df[(df["adaptation"] == adp)
              & (df["framework"] == framework)
              & (df["granularity"] == granularity)]
    if _sel.empty:
        return None
    return _sel.iloc[0]


def plot_verdict_matrix(df: pd.DataFrame,
                        *,
                        title: str | None = None,
                        file_path: str | None = None,
                        fname: str = "verdict_matrix",
                        verbose: bool = False) -> Figure:
    """Render the R1 / R2 PASS-FAIL grid as two side-by-side heatmaps.

    Cell colour encodes PASS (green) / FAIL (red); the median value is
    overlaid (`r1` as a fraction, `r2` in ms).

    Args:
        df (pd.DataFrame): aggregated table from `summarize_bench`.
        title (str | None, optional): figure super-title. Defaults to a standard title.
        file_path (str | None, optional): destination directory; combined with `fname` to save PNG + SVG.
        fname (str, optional): output filename stem. Defaults to `"verdict_matrix"`.
        verbose (bool, optional): when True, `_save_figure` logs the saved paths. Defaults to False.

    Returns:
        Figure: the rendered figure; the caller owns the lifecycle.
    """
    _adps, _stacks = _bench_axes(df)
    _r1_max, _r2_max_ms, _ = _bench_params(df)
    _fig, _axes = plt.subplots(1, 2, figsize=(13, 5), facecolor="white")
    for _ax, _req, _key, _thresh, _thr_lbl in (
        (_axes[0], "R1", "r1_p50", _r1_max,
         rf"$r_{{1}} \leq {_r1_max:g}$"),
        (_axes[1], "R2", "r2_p50_ms", _r2_max_ms,
         rf"$r_{{2}} \leq {_r2_max_ms:g}$ ms"),
    ):
        _grid = np.full((len(_adps), len(_stacks)), np.nan)
        _labels = np.full_like(_grid, "", dtype=object)
        for _i, _adp in enumerate(_adps):
            for _j, (_fw, _gr) in enumerate(_stacks):
                _row = _cell_row(df, _adp, _fw, _gr)
                if _row is None:
                    continue
                _val = float(_row[_key])
                _grid[_i, _j] = _val
                _verdict = "PASS" if _val <= _thresh else "FAIL"
                if _req == "R1":
                    _labels[_i, _j] = f"{_val:.3f}\n{_verdict}"
                else:
                    _labels[_i, _j] = f"{_val:.0f}ms\n{_verdict}"
        _ax.imshow(np.where(_grid <= _thresh, 1.0, 0.0),
                   cmap="RdYlGn", vmin=0, vmax=1, aspect="auto")
        for _i in range(len(_adps)):
            for _j in range(len(_stacks)):
                if _labels[_i, _j]:
                    _ax.text(_j, _i, _labels[_i, _j], ha="center", va="center",
                             color=_TEXT_BLACK, fontsize=9)
        _ax.set_xticks(range(len(_stacks)))
        _ax.set_xticklabels([_stack_label(_f, _g) for _f, _g in _stacks],
                            rotation=20, ha="right", color=_TEXT_BLACK)
        _ax.set_yticks(range(len(_adps)))
        _ax.set_yticklabels(_adps, color=_TEXT_BLACK)
        _ax.set_title(f"{_req} verdict ({_thr_lbl})",
                      color=_TEXT_BLACK, fontweight="bold")
        _ax.tick_params(colors=_TEXT_BLACK)
    _fig.suptitle(title or "Benchmark: R1 / R2 verdict matrix",
                  color=_TEXT_BLACK, fontsize=15, fontweight="bold")
    _fig.tight_layout()
    _save_figure(_fig, file_path, fname, verbose)
    return _fig


def plot_x0_distribution(df: pd.DataFrame,
                         *,
                         title: str | None = None,
                         file_path: str | None = None,
                         fname: str = "x0_distribution",
                         verbose: bool = False) -> Figure:
    """Render per-cell `X_0` median bars with min-max range caps.

    One bar group per adaptation, one bar per stack. Bar height is the median
    `X_0`; the error cap spans observed min-to-max so trial-to-trial variance
    is visible. A dashed line marks the `lambda_z` design point.

    Args:
        df (pd.DataFrame): aggregated table from `summarize_bench`.
        title (str | None, optional): figure title. Defaults to a standard title.
        file_path (str | None, optional): destination directory.
        fname (str, optional): output filename stem. Defaults to `"x0_distribution"`.
        verbose (bool, optional): when True, `_save_figure` logs the saved paths. Defaults to False.

    Returns:
        Figure: the rendered figure; the caller owns the lifecycle.
    """
    _adps, _stacks = _bench_axes(df)
    _, _, _lambda_z = _bench_params(df)
    _palette = _generate_color_map(_stacks)
    _fig, _ax = plt.subplots(figsize=(12, 5), facecolor="white")
    _x = np.arange(len(_adps))
    _bar_w = 0.8 / max(len(_stacks), 1)
    _offset = (len(_stacks) - 1) / 2.0
    for _k, (_fw, _gr) in enumerate(_stacks):
        _p50: list[float] = []
        _err_lo: list[float] = []
        _err_hi: list[float] = []
        for _adp in _adps:
            _row = _cell_row(df, _adp, _fw, _gr)
            if _row is None:
                _p50.append(0.0)
                _err_lo.append(0.0)
                _err_hi.append(0.0)
                continue
            _med = float(_row["X_0_p50"])
            _p50.append(_med)
            _err_lo.append(_med - float(_row["X_0_min"]))
            _err_hi.append(float(_row["X_0_max"]) - _med)
        _ax.bar(_x + (_k - _offset) * _bar_w, _p50, _bar_w,
                yerr=[_err_lo, _err_hi], capsize=4,
                color=_palette[_k], edgecolor=_TEXT_BLACK, linewidth=0.5,
                label=_stack_label(_fw, _gr))
    _ax.axhline(_lambda_z, color=_NEUTRAL_BAR, linestyle="--", linewidth=1,
                label=rf"$\lambda_{{z}} = {_lambda_z:g}$ (design)")
    _ax.set_xticks(_x)
    _ax.set_xticklabels(_adps, color=_TEXT_BLACK)
    _ax.set_ylabel(r"$X_{0}$  $[\mathrm{req/s}]$  (p50, min-max caps)",
                   color=_TEXT_BLACK)
    _ax.set_title(title or "Benchmark: X_0 distribution per cell",
                  color=_TEXT_BLACK, fontweight="bold")
    _ax.tick_params(colors=_TEXT_BLACK)
    _ax.legend(loc="upper left", fontsize=9, framealpha=0.92)
    _ax.grid(True, axis="y", alpha=0.25)
    _fig.tight_layout()
    _save_figure(_fig, file_path, fname, verbose)
    return _fig


def plot_rs_by_stack(df: pd.DataFrame,
                     *,
                     title: str | None = None,
                     file_path: str | None = None,
                     fname: str = "rs_by_stack",
                     verbose: bool = False) -> Figure:
    """Render per-cell `R_s` median bars on a log axis against the R2 threshold.

    Bars are grouped by adaptation, one per stack, log-scaled so the
    order-of-magnitude gap between framework stacks is legible. A dashed line
    marks the R2 response-time ceiling.

    Args:
        df (pd.DataFrame): aggregated table from `summarize_bench`.
        title (str | None, optional): figure title. Defaults to a standard title.
        file_path (str | None, optional): destination directory.
        fname (str, optional): output filename stem. Defaults to `"rs_by_stack"`.
        verbose (bool, optional): when True, `_save_figure` logs the saved paths. Defaults to False.

    Returns:
        Figure: the rendered figure; the caller owns the lifecycle.
    """
    _adps, _stacks = _bench_axes(df)
    _, _r2_max_ms, _ = _bench_params(df)
    _palette = _generate_color_map(_stacks)
    _fig, _ax = plt.subplots(figsize=(12, 5), facecolor="white")
    _x = np.arange(len(_adps))
    _bar_w = 0.8 / max(len(_stacks), 1)
    _offset = (len(_stacks) - 1) / 2.0
    for _k, (_fw, _gr) in enumerate(_stacks):
        _vals: list[float] = []
        for _adp in _adps:
            _row = _cell_row(df, _adp, _fw, _gr)
            if _row is None:
                _vals.append(0.0)
            else:
                _vals.append(float(_row["R_s_p50_ms"]))
        _ax.bar(_x + (_k - _offset) * _bar_w, _vals, _bar_w,
                color=_palette[_k], edgecolor=_TEXT_BLACK, linewidth=0.5,
                label=_stack_label(_fw, _gr))
    _ax.axhline(_r2_max_ms, color=_NEUTRAL_BAR, linestyle="--", linewidth=1,
                label=rf"R2 ceiling = {_r2_max_ms:g} ms")
    _ax.set_xticks(_x)
    _ax.set_xticklabels(_adps, color=_TEXT_BLACK)
    _ax.set_ylabel(r"$R_{s}$ p50  $[\mathrm{ms}]$  (log scale)",
                   color=_TEXT_BLACK)
    _ax.set_yscale("log")
    _ax.set_title(title or "Benchmark: R_s by stack vs R2 threshold",
                  color=_TEXT_BLACK, fontweight="bold")
    _ax.tick_params(colors=_TEXT_BLACK)
    _ax.legend(loc="upper left", fontsize=9, framealpha=0.92)
    _ax.grid(True, axis="y", alpha=0.25, which="both")
    _fig.tight_layout()
    _save_figure(_fig, file_path, fname, verbose)
    return _fig


__all__ = ["plot_rs_by_stack", "plot_verdict_matrix", "plot_x0_distribution"]

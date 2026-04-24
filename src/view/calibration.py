# -*- coding: utf-8 -*-
"""
Module calibration.py
=====================

Visualisation for the per-host noise-floor calibration envelope produced by `src.scripts.calibration.run` (the JSON under `data/results/experiment/calibration/`).

Two plotters. Required inputs are positional, everything else keyword-only after `*,`; both return the `matplotlib.figure.Figure` and persist to disk when both `file_path` and `fname` are supplied.

    - `plot_calib_scaling(handler)` standalone line plot of the empty-handler latency at increasing concurrency levels; the single figure that makes the FastAPI / event-loop saturation story legible.
    - `plot_calib_dashboard(envelope)` 2x2 summary card combining the timer / jitter / loopback headline bars with the handler-scaling line chart; self-contained figure suitable for inclusion in a report appendix.

Shared text colour, save helper, and palette constants come from the existing view-package helpers so every plotter renders consistently (near-black `#010101` text, PNG + SVG saved in one call).
"""
# native python modules
from __future__ import annotations

from typing import Any, Dict, Optional

# scientific stack
import matplotlib.pyplot as plt
import numpy as np
from matplotlib import cm
from matplotlib.figure import Figure

# shared view helpers (text colour + PNG/SVG persistence)
from src.view.qn_diagram import (
    _TEXT_BLACK,
    _save_figure,
)


# full-name glossary for acronym-heavy axis labels and legend entries;
# every plot in this module uses these strings so the meaning of
# `mean`, `p50`, `p99`, `max`, `std` is explicit on the figure itself.
_STAT_NAMES = {
    "min": "Minimum",
    "mean": "Mean",
    "median": "Median (50th percentile, p50)",
    "p50": "Median (50th percentile, p50)",
    "p95": "95th percentile (p95)",
    "p99": "99th percentile (p99)",
    "max": "Maximum",
    "std": "Standard deviation",
}

# Neutral ordinal palette. Calibration stats are percentiles (ordered by
# rank), not signed deltas, so a single neutral blue is used for all bar
# panels and a sequential Blues gradient encodes rank on the percentile
# lines (light = low percentile, dark = high percentile).
_NEUTRAL_BAR = "#5B8DC9"
_PCTL_GRADIENT = (cm.Blues(0.45), cm.Blues(0.70), cm.Blues(0.92))


# rcParams: near-black text on a white background so SVG output survives
# dark-theme previews.
plt.rcParams.update({
    "figure.facecolor": "white",
    "axes.facecolor": "white",
    "savefig.facecolor": "white",
    "text.color": _TEXT_BLACK,
    "axes.labelcolor": _TEXT_BLACK,
    "axes.edgecolor": _TEXT_BLACK,
    "axes.titlecolor": _TEXT_BLACK,
    "xtick.color": _TEXT_BLACK,
    "ytick.color": _TEXT_BLACK,
    "grid.color": "lightgray",
    "font.size": 10,
    "axes.labelsize": 12,
    "xtick.labelsize": 10,
    "ytick.labelsize": 10,
    "legend.fontsize": 10,
})


_LBL_STYLE = dict(fontweight="bold", color=_TEXT_BLACK)
_TITLE_STYLE = dict(fontsize=14, fontweight="bold", pad=15, color=_TEXT_BLACK)
_SUPTITLE_STYLE = dict(fontsize=15, fontweight="bold", color=_TEXT_BLACK)


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------


def _sort_concurrency_items(handler: Dict[str, Dict[str, float]]):
    """*_sort_concurrency_items()* iterate `(int(level), stats)` pairs sorted by concurrency level.

    Args:
        handler (dict): the `handler_scaling` block of a calibration envelope.

    Returns:
        list[tuple[int, dict]]: `[(c_int, stats_dict), ...]` sorted ascending by `c_int`.
    """
    _pairs = []
    for _k, _stats in handler.items():
        _pairs.append((int(_k), _stats))
    _pairs.sort(key=lambda _p: _p[0])
    return _pairs


def _draw_stat_bars(ax: plt.Axes,
                    values: Dict[str, float],
                    order: list,
                    unit: str,
                    title: str) -> None:
    """*_draw_stat_bars()* horizontal bar chart of `values` in `order`; each bar labelled with its full stat name and numeric value in `unit`.

    Args:
        ax: matplotlib axis to draw into.
        values (dict): stat-key -> numeric value (e.g. `{"mean_us": 627.7, ...}`).
        order (list): ordered list of stat short keys (`["min", "median", "p95", "p99"]`).
        unit (str): unit string appended to the value ("ns" / "us").
        title (str): axis title.
    """
    _ys = list(range(len(order)))
    _labels = []
    _vals = []
    for _key in order:
        _long = _STAT_NAMES.get(_key, _key)
        _labels.append(_long)
        # accept values keyed as `<key>_<unit>` or plain `<key>`
        _full_key = f"{_key}_{unit.replace('µ', 'u')}"
        if _full_key in values:
            _v = float(values[_full_key])
        elif _key in values:
            _v = float(values[_key])
        elif _key == "median" and f"p50_{unit}" in values:
            _v = float(values[f"p50_{unit}"])
        else:
            _v = float("nan")
        _vals.append(_v)

    # single neutral blue for every bar; these stats are ordered
    # percentiles, not signed deltas, so a sign-coded palette does not
    # apply.
    ax.barh(_ys, _vals, color=_NEUTRAL_BAR,
            edgecolor=_TEXT_BLACK, linewidth=0.6)
    ax.set_yticks(_ys)
    ax.set_yticklabels(_labels, fontsize=10, color=_TEXT_BLACK)
    ax.invert_yaxis()  # first entry on top
    ax.set_xlabel(f"[{unit}]", **_LBL_STYLE)
    ax.set_title(title, **_TITLE_STYLE)
    ax.grid(True, axis="x", linestyle="--", alpha=0.5, color="#555555")

    # annotate each bar with its value; placed at 1 % of axis width inside
    # the bar so dark bars still show the annotation clearly.
    for _y, _v in zip(_ys, _vals):
        if not np.isfinite(_v):
            continue
        ax.text(_v, _y, f"  {_v:,.1f} {unit}",
                va="center", ha="left", fontsize=9, color=_TEXT_BLACK)


def _draw_scaling_axis(ax: plt.Axes,
                       handler: Dict[str, Dict[str, float]],
                       *,
                       log_y: bool = True) -> None:
    """*_draw_scaling_axis()* plot median / p95 / p99 latency vs concurrency on one axis.

    Args:
        ax: matplotlib axis to draw into.
        handler (dict): `handler_scaling` block from the calibration envelope.
        log_y (bool): log-scale y-axis; recommended because latencies span several decades.
    """
    _pairs = _sort_concurrency_items(handler)
    _xs = [_c for _c, _ in _pairs]
    _median = [float(_s.get("median_us", np.nan)) for _, _s in _pairs]
    _p95 = [float(_s.get("p95_us", np.nan)) for _, _s in _pairs]
    _p99 = [float(_s.get("p99_us", np.nan)) for _, _s in _pairs]

    # sequential Blues gradient: light = low percentile (p50), dark =
    # high percentile (p99). Encodes rank without implying sign.
    _c_median, _c_p95, _c_p99 = _PCTL_GRADIENT
    ax.plot(_xs, _median, marker="o", linewidth=2.0, color=_c_median,
            label=_STAT_NAMES["median"])
    ax.plot(_xs, _p95, marker="s", linewidth=1.8, color=_c_p95,
            label=_STAT_NAMES["p95"])
    ax.plot(_xs, _p99, marker="^", linewidth=2.0, color=_c_p99,
            label=_STAT_NAMES["p99"])

    ax.set_xlabel("Concurrency (in-flight requests)", **_LBL_STYLE)
    ax.set_ylabel("Latency [microseconds]", **_LBL_STYLE)
    ax.set_xscale("log")
    if log_y:
        ax.set_yscale("log")
    ax.grid(True, which="both", linestyle="--", alpha=0.5, color="#555555")
    ax.legend(loc="upper left", framealpha=0.9)

    # annotate every point with its median value so the magnitude reads
    # without having to map back to the log-scale axis.
    for _x, _m in zip(_xs, _median):
        if not np.isfinite(_m):
            continue
        ax.annotate(f"{_m:,.0f} us",
                    xy=(_x, _m), xytext=(6, 6), textcoords="offset points",
                    fontsize=9, color=_TEXT_BLACK)


# ---------------------------------------------------------------------------
# Public plotters
# ---------------------------------------------------------------------------


def plot_calib_scaling(handler: Dict[str, Dict[str, float]],
                       *,
                       title: Optional[str] = None,
                       file_path: Optional[str] = None,
                       fname: Optional[str] = None,
                       verbose: bool = False) -> Figure:
    """*plot_calib_scaling()* standalone line plot of empty-handler latency vs concurrency.

    Three lines per figure: Median (50th percentile), 95th percentile, 99th percentile. x-axis is the concurrency level (in-flight requests); y-axis is latency in microseconds on a log scale (latencies span several decades between c=1 and c=100). Each median point is annotated with its numeric value. This is the single-figure summary that makes the FastAPI / event-loop queueing saturation visible at a glance.

    Args:
        handler (dict): `handler_scaling` block from the calibration envelope; shape `{"<c>": {"median_us": ..., "p95_us": ..., "p99_us": ..., ...}, ...}`.
        title (Optional[str]): axis title; defaults to `"Empty-handler scaling (loopback /ping)"`.
        file_path (Optional[str]): directory to save into.
        fname (Optional[str]): filename stem or name (extension ignored); both PNG and SVG written.
        verbose (bool): if True, prints one save-path message per format.

    Returns:
        Figure: the matplotlib figure.
    """
    _fig, _ax = plt.subplots(figsize=(9, 5.5), facecolor="white")
    _draw_scaling_axis(_ax, handler)
    _ax.set_title(title or "Empty-handler scaling (loopback /ping)",
                  **_TITLE_STYLE)
    _fig.tight_layout()
    _save_figure(_fig, file_path, fname, verbose=verbose)
    return _fig


def plot_calib_dashboard(envelope: Dict[str, Any],
                         *,
                         title: Optional[str] = None,
                         file_path: Optional[str] = None,
                         fname: Optional[str] = None,
                         verbose: bool = False) -> Figure:
    """*plot_calib_dashboard()* 2x2 summary card of one calibration envelope.

    Panel layout (row-major):
        - (0, 0) Timer resolution: bar chart of `min_ns / median_ns / mean_ns / std_ns`.
        - (0, 1) Scheduling jitter: bar chart of `mean / p50 / p99 / max` in microseconds.
        - (1, 0) Loopback latency: bar chart of `min / median / p95 / p99` in microseconds.
        - (1, 1) Empty-handler scaling: same three-line plot as `plot_calib_scaling`.

    The figure title (suptitle) carries the host identity, timestamp, and the "reported = measured - loopback_median +/- jitter_p99" interpretation formula so a reader can apply the baseline without the accompanying notebook text.

    Args:
        envelope (dict): the full calibration envelope (`host_profile`, `timer`, `jitter`, `loopback`, `handler_scaling`, ...).
        title (Optional[str]): override the suptitle; defaults to a composed host + timestamp + formula line.
        file_path (Optional[str]): directory to save into.
        fname (Optional[str]): filename stem or name (extension ignored); both PNG and SVG written.
        verbose (bool): if True, prints one save-path message per format.

    Returns:
        Figure: the matplotlib figure.
    """
    _fig, _axes = plt.subplots(2, 2, figsize=(15, 10), facecolor="white")

    # Panel (0, 0): timer resolution in nanoseconds
    _timer = envelope.get("timer", {})
    _draw_stat_bars(
        _axes[0, 0],
        values=_timer,
        order=["min", "median", "mean", "std"],
        unit="ns",
        title="Timer resolution (perf_counter_ns back-to-back)",
    )

    # Panel (0, 1): scheduling jitter in microseconds
    _jitter = envelope.get("jitter", {})
    if _jitter:
        _draw_stat_bars(
            _axes[0, 1],
            values=_jitter,
            order=["mean", "p50", "p99", "max"],
            unit="us",
            title="Scheduling jitter (time.sleep(0.001) actual - 1 ms)",
        )
    else:
        _axes[0, 1].axis("off")
        _axes[0, 1].text(0.5, 0.5, "jitter probe skipped",
                         ha="center", va="center", fontsize=14,
                         color=_TEXT_BLACK)

    # Panel (1, 0): loopback latency in microseconds
    _loopback = envelope.get("loopback", {})
    if _loopback:
        _draw_stat_bars(
            _axes[1, 0],
            values=_loopback,
            order=["min", "median", "p95", "p99"],
            unit="us",
            title="Loopback latency (GET /ping, idle)",
        )
    else:
        _axes[1, 0].axis("off")
        _axes[1, 0].text(0.5, 0.5, "loopback probe skipped",
                         ha="center", va="center", fontsize=14,
                         color=_TEXT_BLACK)

    # Panel (1, 1): handler scaling line plot
    _handler = envelope.get("handler_scaling") or {}
    if _handler:
        _draw_scaling_axis(_axes[1, 1], _handler)
        _axes[1, 1].set_title("Empty-handler scaling (loopback /ping)",
                              **_TITLE_STYLE)
    else:
        _axes[1, 1].axis("off")
        _axes[1, 1].text(0.5, 0.5, "handler-scaling probe skipped",
                         ha="center", va="center", fontsize=14,
                         color=_TEXT_BLACK)

    # suptitle: host identity + timestamp + how to apply the baseline.
    # This is what turns the figure into a self-contained artefact.
    _hp = envelope.get("host_profile", {})
    _host = _hp.get("hostname", "unknown")
    _ts = envelope.get("timestamp", "")
    if title:
        _suptitle = title
    else:
        _suptitle = (
            f"Host noise-floor calibration: {_host}  |  {_ts}\n"
            "Reported latency = measured - loopback.median  +/- jitter.p99"
        )
    _fig.suptitle(_suptitle, **_SUPTITLE_STYLE)

    _fig.tight_layout(rect=(0.0, 0.0, 1.0, 0.94))
    _save_figure(_fig, file_path, fname, verbose=verbose)
    return _fig

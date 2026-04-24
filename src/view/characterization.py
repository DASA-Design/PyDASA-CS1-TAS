# -*- coding: utf-8 -*-
"""
Module view/characterization.py
===============================

Visualisation for the per-host noise-floor calibration envelope produced by `src.methods.calibration.run` (the JSON under `data/results/experiment/calibration/`).

Two plotters. Required inputs are positional, everything else keyword-only after `*,`; both return the `matplotlib.figure.Figure` and persist to disk when both `file_path` and `fname` are supplied.

    - `plot_calib_scaling(handler)` standalone line plot of the empty-handler latency at increasing concurrent-user load levels (`n_con_usr`); the single figure that makes the FastAPI / event-loop saturation story legible.
    - `plot_calib_dashboard(envelope)` 2x2 summary card combining the timer / jitter / loopback headline bars with the handler-scaling line chart; self-contained figure suitable for inclusion in a report appendix.

Shared text colour, save helper, and palette constants come from the existing view-package helpers so every plotter renders consistently (near-black `#010101` text, PNG + SVG saved in one call).
"""
# native python modules
from __future__ import annotations

from typing import Any, Dict, Optional, List

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


# glossary expansions for the acronym stats; every plotter uses these so figures are self-explanatory
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

# neutral ordinal palette; percentile rank, not signed delta, so sequential-not-diverging
_NEUTRAL_BAR = "#7E5BC9"
_PCTL_GRADIENT = (cm.Purples(0.45), cm.Purples(0.70), cm.Purples(0.92))


# near-black text on white so SVG survives dark-theme previews
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


def _sort_n_con_usr_items(handler: Dict[str, Dict[str, float]]
                          ) -> List[tuple]:
    """*_sort_n_con_usr_items()* iterate `(int(n_con_usr), stats)` pairs sorted by concurrent-user load.

    Args:
        handler (dict): the `handler_scaling` block of a calibration envelope.

    Returns:
        list[tuple[int, dict]]: `[(n_con_usr, stats_dict), ...]` sorted ascending by `n_con_usr`.
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

    # single neutral fill; ordered percentiles don't carry a sign
    ax.barh(_ys, _vals, color=_NEUTRAL_BAR,
            edgecolor=_TEXT_BLACK, linewidth=0.6)
    ax.set_yticks(_ys)
    ax.set_yticklabels(_labels, fontsize=10, color=_TEXT_BLACK)
    ax.invert_yaxis()  # first entry on top
    ax.set_xlabel(f"[{unit}]", **_LBL_STYLE)
    ax.set_title(title, **_TITLE_STYLE)
    ax.grid(True, axis="x", linestyle="--", alpha=0.5, color="#555555")

    # annotate each bar; offset inside so the label stays legible on dark bars
    for _y, _v in zip(_ys, _vals):
        if not np.isfinite(_v):
            continue
        ax.text(_v, _y, f"  {_v:,.1f} {unit}",
                va="center", ha="left", fontsize=9, color=_TEXT_BLACK)


def _draw_scaling_axis(ax: plt.Axes,
                       handler: Dict[str, Dict[str, float]],
                       *,
                       log_y: bool = True) -> None:
    """*_draw_scaling_axis()* plot median / p95 / p99 latency vs `n_con_usr` on one axis.

    Args:
        ax: matplotlib axis to draw into.
        handler (dict): `handler_scaling` block from the calibration envelope.
        log_y (bool): log-scale y-axis; recommended because latencies span several decades.
    """
    _pairs = _sort_n_con_usr_items(handler)
    _xs = [_c for _c, _ in _pairs]
    _median = [float(_s.get("median_us", np.nan)) for _, _s in _pairs]
    _p95 = [float(_s.get("p95_us", np.nan)) for _, _s in _pairs]
    _p99 = [float(_s.get("p99_us", np.nan)) for _, _s in _pairs]

    # sequential gradient: light = p50, dark = p99 (rank without sign)
    _c_median, _c_p95, _c_p99 = _PCTL_GRADIENT
    ax.plot(_xs, _median, marker="o", linewidth=2.0, color=_c_median,
            label=_STAT_NAMES["median"])
    ax.plot(_xs, _p95, marker="s", linewidth=1.8, color=_c_p95,
            label=_STAT_NAMES["p95"])
    ax.plot(_xs, _p99, marker="^", linewidth=2.0, color=_c_p99,
            label=_STAT_NAMES["p99"])

    ax.set_xlabel("n_con_usr (concurrent users, in-flight requests)",
                  **_LBL_STYLE)
    ax.set_ylabel("Latency [microseconds]", **_LBL_STYLE)
    ax.set_xscale("log")
    if log_y:
        ax.set_yscale("log")
    ax.grid(True, which="both", linestyle="--", alpha=0.5, color="#555555")
    ax.legend(loc="upper left", framealpha=0.9)

    # annotate each point so the magnitude is readable off the log-scale axis
    for _x, _m in zip(_xs, _median):
        if not np.isfinite(_m):
            continue
        ax.annotate(f"{_m:,.0f} us",
                    xy=(_x, _m), xytext=(6, 6), textcoords="offset points",
                    fontsize=9, color=_TEXT_BLACK)


# ---------------------------------------------------------------------------
# Public plotters
# ---------------------------------------------------------------------------


def plot_calib_rate_sweep(rate_sweep: Dict[str, Any],
                          *,
                          title: Optional[str] = None,
                          file_path: Optional[str] = None,
                          fname: Optional[str] = None,
                          verbose: bool = False) -> Figure:
    """*plot_calib_rate_sweep()* standalone plot of effective rate + mean loss vs target rate.

    Two curves on one axis: the identity line `effective = target` (reference) and the measured effective-rate curve with min/max error bars across trials. A second y-axis carries the mean-loss percentage per rate. A horizontal dashed line marks the `target_loss_pct` bar; the `calibrated_rate` (highest passing rate) is annotated as a vertical marker.

    Args:
        rate_sweep (dict): `rate_sweep` block from the calibration envelope; shape `{"aggregates": {"<rate>": {...}}, "target_loss_pct": ..., "calibrated_rate": ...}`.
        title (Optional[str]): axis title; defaults to `"Rate saturation (client effective vs target)"`.
        file_path (Optional[str]): directory to save into.
        fname (Optional[str]): filename stem or name (extension ignored); both PNG and SVG written.
        verbose (bool): if True, prints one save-path message per format.

    Returns:
        Figure: the matplotlib figure.
    """
    _aggs = rate_sweep.get("aggregates", {})
    _target_loss = float(rate_sweep.get("target_loss_pct", 0.0))
    _calibrated = rate_sweep.get("calibrated_rate")

    _pairs = []
    for _k, _v in _aggs.items():
        _pairs.append((float(_k), _v))
    _pairs.sort(key=lambda _p: _p[0])
    _xs = [_p[0] for _p in _pairs]
    _means = [float(_p[1].get("mean", 0.0)) for _p in _pairs]
    _los = [float(_p[1].get("lo", 0.0)) for _p in _pairs]
    _his = [float(_p[1].get("hi", 0.0)) for _p in _pairs]
    _losses = [float(_p[1].get("mean_loss_pct", 0.0)) for _p in _pairs]

    _fig, _ax = plt.subplots(figsize=(9, 5.5), facecolor="white")

    # identity reference line: `effective == target`
    if _xs:
        _lo_ref = min(_xs)
        _hi_ref = max(_xs)
        _ax.plot([_lo_ref, _hi_ref], [_lo_ref, _hi_ref],
                 linestyle=":", color="#888888", linewidth=1.5,
                 label="Identity (effective = target)")

    # measured effective-rate curve with min/max as asymmetric error bars
    _err_lo: List[float] = []
    _err_hi: List[float] = []
    for _i, _m in enumerate(_means):
        _err_lo.append(max(_m - _los[_i], 0.0))
        _err_hi.append(max(_his[_i] - _m, 0.0))
    _c_mean, _, _ = _PCTL_GRADIENT
    _ax.errorbar(_xs, _means, yerr=[_err_lo, _err_hi],
                 marker="o", linewidth=2.0, color=_c_mean,
                 ecolor=_c_mean, capsize=4, capthick=1.2,
                 label="Measured effective (mean)")
    for _x, _m in zip(_xs, _means):
        _ax.annotate(f"{_m:.1f}",
                     xy=(_x, _m), xytext=(6, 6),
                     textcoords="offset points",
                     fontsize=9, color=_TEXT_BLACK)

    _ax.set_xlabel("Target rate [req/s]", **_LBL_STYLE)
    _ax.set_ylabel("Effective rate [req/s]", **_LBL_STYLE)
    _ax.grid(True, which="both", linestyle="--",
             alpha=0.5, color="#555555")
    _ax.legend(loc="upper left", framealpha=0.9)

    # secondary axis: mean loss % per rate
    _ax2 = _ax.twinx()
    _ax2.plot(_xs, _losses, marker="s", linewidth=1.5,
              color="#C9603C", label="Mean loss (%)")
    _ax2.axhline(_target_loss, linestyle="--",
                 color="#C9603C", linewidth=1.0, alpha=0.6)
    _ax2.set_ylabel("Mean loss [%]", color="#C9603C", fontweight="bold")
    _ax2.tick_params(axis="y", colors="#C9603C")
    _ax2.annotate(f"target {_target_loss:.1f}%",
                  xy=(max(_xs or [0.0]), _target_loss),
                  xytext=(-6, 4), textcoords="offset points",
                  ha="right", fontsize=9, color="#C9603C")

    # calibrated-rate vertical marker
    if _calibrated is not None:
        _ax.axvline(float(_calibrated), linestyle="-",
                    color=_TEXT_BLACK, linewidth=1.0, alpha=0.5)
        _ax.annotate(f"calibrated = {float(_calibrated):.1f} req/s",
                     xy=(float(_calibrated), max(_means or [0.0])),
                     xytext=(6, -14), textcoords="offset points",
                     fontsize=9, color=_TEXT_BLACK)

    _ax.set_title(title or "Rate saturation (client effective vs target)",
                  **_TITLE_STYLE)
    _fig.tight_layout()
    _save_figure(_fig, file_path, fname, verbose=verbose)
    return _fig


def plot_calib_scaling(handler: Dict[str, Dict[str, float]],
                       *,
                       title: Optional[str] = None,
                       file_path: Optional[str] = None,
                       fname: Optional[str] = None,
                       verbose: bool = False) -> Figure:
    """*plot_calib_scaling()* standalone line plot of empty-handler latency vs `n_con_usr`.

    Three lines per figure: Median (50th percentile), 95th percentile, 99th percentile. x-axis is the `n_con_usr` level (concurrent users / in-flight requests against a single-worker `c_srv=1` service); y-axis is latency in microseconds on a log scale (latencies span several decades between `n_con_usr=1` and `n_con_usr=10000`). Each median point is annotated with its numeric value. This is the single-figure summary that makes the FastAPI / event-loop queueing saturation visible at a glance.

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

    # suptitle carries host + timestamp + apply-formula so the figure stands alone
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

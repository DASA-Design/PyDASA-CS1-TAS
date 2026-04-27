# -*- coding: utf-8 -*-
"""
Module view/characterization.py
===============================

Calibration plotters for the per-host noise-floor envelope produced by `src.methods.calibration.run` (the JSON under `data/results/experiment/calibration/`).

Thin orchestrator: every helper, constant, palette, and layout primitive lives in `src.view.common`. Each public function picks a `FigureLayout` and calls `build_stacked_figure(layout)`. The body is populated via the calibration helpers in `common`. Axis cosmetics are caller-driven through `AxisSpec` kwargs.

Three plotters, all conform to the design contract (title strip / body grid / footer strip; footer width clipped to body width):

    - `plot_calib_handler_scaling(handler, ...)` standalone line plot of the empty-handler latency at increasing concurrent-user load levels (`n_con_usr`); the single figure that makes the FastAPI / event-loop saturation story legible.
    - `plot_calib_dashboard(envelope, ...)` 2x2 summary card combining the timer / jitter / loopback headline bars with the handler-scaling line chart; self-contained figure suitable for inclusion in a report appendix.
    - `plot_calib_rate_sweep(rate_sweep, ...)` standalone plot of effective rate + mean loss vs target rate; identity reference, error bars, calibrated-rate marker, secondary loss axis.
"""
# native python modules
from __future__ import annotations

from typing import Any, Dict, List, Optional

# scientific stack
from matplotlib.figure import Figure

# shared view helpers (every helper + constant lives in common; this module only orchestrates)
from src.view.common import (
    AxisSpec,
    BodySpec,
    FigureLayout,
    _PCTL_GRADIENT,
    _TEXT_BLACK,
    _TITLE_STYLE,
    _draw_handler_scaling_axis,
    _draw_stat_bars,
    _pick_axis_spec,
    _pick_layout,
    _pick_title,
    _save_figure,
    attach_axis_spec,
    build_stacked_figure,
    render_footer_legend,
    render_footer_summary,
)


# ---------------------------------------------------------------------------
# Public plotters
# ---------------------------------------------------------------------------


def plot_calib_handler_scaling(handler: Dict[str, Dict[str, float]],
                               *,
                               xspec: Optional[AxisSpec] = None,
                               yspec: Optional[AxisSpec] = None,
                               layout: Optional[FigureLayout] = None,
                               title: Optional[str] = None,
                               file_path: Optional[str] = None,
                               fname: Optional[str] = None,
                               verbose: bool = False) -> Figure:
    """*plot_calib_handler_scaling()* standalone line plot of empty-handler latency vs `n_con_usr`.

    Three lines: median (50th percentile), 95th percentile, 99th percentile. The body is a single 2D panel whose axis cosmetics (scale / lim / ticks / tick_format / grid) come from `xspec` and `yspec`. Defaults match the historical figure: `xscale=log`, `yscale=log`, no manual limits.

    Args:
        handler (dict): `handler_scaling` block from the calibration envelope; shape `{"<n_con_usr>": {"median_us": ..., "p95_us": ..., "p99_us": ..., ...}, ...}`.
        xspec (Optional[AxisSpec]): x-axis spec (scale / lim / ticks / tick_format / grid). Defaults to log-scale, no manual limits, project grid on.
        yspec (Optional[AxisSpec]): y-axis spec; same defaults as `xspec`.
        layout (Optional[FigureLayout]): full layout override. Defaults to a 1x1 2D body with a centred legend footer.
        title (Optional[str]): figure title; defaults to `"Empty-handler scaling (loopback /ping)"`.
        file_path (Optional[str]): directory to save into.
        fname (Optional[str]): filename stem or name (extension ignored); both PNG and SVG written.
        verbose (bool): if True, prints one save-path message per format.

    Raises:
        ValueError: If `_save_figure` fails for either format.

    Returns:
        Figure: the matplotlib figure.

    Example::

        plot_calib_handler_scaling(envelope["handler_scaling"],
                                   title="Empty-handler scaling",
                                   file_path="data/img/experiment/calibration",
                                   fname="scaling")
    """
    _xspec = _pick_axis_spec(
        xspec,
        AxisSpec(scale="log",
                 label="concurrent users, in-flight requests"))
    _yspec = _pick_axis_spec(
        yspec,
        AxisSpec(scale="log", label=r"Latency [$\mu$s]"))

    _resolved_title = _pick_title(title, "Empty-handler scaling (loopback /ping)")
    # title strip + body + legend strip sit flush; outer_hspace near zero closes the dead band
    _default_layout = FigureLayout(title=_resolved_title,
                                   title_h=0.10,
                                   body=BodySpec(shape=(1, 1),
                                                 panel_kind="2d"),
                                   footer_h=0.18,
                                   footer_kind="legend",
                                   figsize=(12, 9),
                                   outer_hspace=0.04)
    _layout = _pick_layout(layout, _default_layout)

    _fig, _regions = build_stacked_figure(_layout)
    _ax = _regions["body_axes"][0]

    _draw_handler_scaling_axis(_ax, handler, log_y=(_yspec.scale == "log"))
    attach_axis_spec(_ax, _xspec, _yspec)

    # lift legend handles to the footer; remove the panel-internal legend the helper installed
    _h, _l = _ax.get_legend_handles_labels()
    if _ax.get_legend() is not None:
        _ax.get_legend().remove()
    if _regions["footer_ax"] is not None and _h:
        render_footer_legend(_regions["footer_ax"],
                             _h,
                             _l,
                             ncol=min(len(_l), 3))

    _save_figure(_fig, file_path, fname, verbose=verbose)
    return _fig


def plot_calib_dashboard(envelope: Dict[str, Any],
                         *,
                         layout: Optional[FigureLayout] = None,
                         title: Optional[str] = None,
                         file_path: Optional[str] = None,
                         fname: Optional[str] = None,
                         verbose: bool = False) -> Figure:
    """*plot_calib_dashboard()* 2x2 summary card of one calibration envelope.

    Body panel layout (row-major):

        - (0, 0) Timer resolution: bar chart of `min_ns / median_ns / mean_ns / std_ns`.
        - (0, 1) Scheduling jitter: bar chart of `mean / p50 / p99 / max` in microseconds.
        - (1, 0) Loopback latency: bar chart of `min / median / p95 / p99` in microseconds.
        - (1, 1) Empty-handler scaling: same three-line plot as `plot_calib_handler_scaling`.

    The footer carries the host identity, timestamp, and the "reported = measured - loopback_median +/- jitter_p99" interpretation formula so a reader can apply the baseline without the accompanying notebook text.

    Args:
        envelope (dict): full calibration envelope (`host_profile`, `timer`, `jitter`, `loopback`, `handler_scaling`, ...).
        layout (Optional[FigureLayout]): full layout override. Defaults to a 2x2 2D body with a multi-line summary footer.
        title (Optional[str]): figure title; defaults to a composed host + timestamp line.
        file_path (Optional[str]): directory to save into.
        fname (Optional[str]): filename stem or name (extension ignored); both PNG and SVG written.
        verbose (bool): if True, prints one save-path message per format.

    Raises:
        ValueError: If `_save_figure` fails for either format.

    Returns:
        Figure: the matplotlib figure.

    Example::

        plot_calib_dashboard(envelope,
                             file_path="data/img/experiment/calibration",
                             fname="dashboard")
    """
    _hp = envelope.get("host_profile", {})
    _host = _hp.get("hostname", "unknown")
    _ts = envelope.get("timestamp", "")
    _default_title = f"Host noise-floor calibration: {_host}  |  {_ts}"

    _resolved_title = _pick_title(title, _default_title)
    # title strip + 2x2 body + summary footer sit flush; outer_hspace near zero closes the dead band between the suptitle and the panel grid (and between the bottom row and the formula reminder)
    _default_layout = FigureLayout(title=_resolved_title,
                                   title_h=0.10,
                                   body=BodySpec(shape=(2, 2),
                                                 panel_kind="2d",
                                                 wspace=0.35,
                                                 hspace=0.55),
                                   footer_h=0.12,
                                   footer_kind="summary",
                                   figsize=(17, 15),
                                   outer_hspace=0.04)
    _layout = _pick_layout(layout, _default_layout)

    _fig, _regions = build_stacked_figure(_layout)
    _axes = _regions["body_axes"]

    # Panel (0, 0): timer resolution in nanoseconds
    _timer = envelope.get("timer", {})
    _draw_stat_bars(_axes[0],
                    values=_timer,
                    order=["min", "median", "mean", "std"],
                    unit="ns",
                    title="Timer resolution (perf_counter_ns back-to-back)")

    # Panel (0, 1): scheduling jitter in microseconds
    _jitter = envelope.get("jitter", {})
    if _jitter:
        _draw_stat_bars(_axes[1],
                        values=_jitter,
                        order=["mean", "p50", "p99", "max"],
                        unit="us",
                        title="Scheduling jitter (time.sleep(0.001) actual - 1 ms)")
    else:
        _axes[1].axis("off")
        _axes[1].text(0.5, 0.5, "jitter probe skipped",
                      ha="center",
                      va="center",
                      fontsize=14,
                      color=_TEXT_BLACK)

    # Panel (1, 0): loopback latency in microseconds
    _loopback = envelope.get("loopback", {})
    if _loopback:
        _draw_stat_bars(_axes[2],
                        values=_loopback,
                        order=["min", "median", "p95", "p99"],
                        unit="us",
                        title="Loopback latency (GET /ping, idle)")
    else:
        _axes[2].axis("off")
        _axes[2].text(0.5, 0.5, "loopback probe skipped",
                      ha="center",
                      va="center",
                      fontsize=14,
                      color=_TEXT_BLACK)

    # Panel (1, 1): handler scaling line plot
    _handler = envelope.get("handler_scaling", {})
    if _handler:
        _draw_handler_scaling_axis(_axes[3], _handler)
        _axes[3].set_title("Empty-handler scaling (loopback /ping)",
                           **_TITLE_STYLE)
    else:
        _axes[3].axis("off")
        _axes[3].text(0.5, 0.5, "handler-scaling probe skipped",
                      ha="center",
                      va="center",
                      fontsize=14,
                      color=_TEXT_BLACK)

    # footer: apply-formula reminder
    if _regions["footer_ax"] is not None:
        render_footer_summary(
            _regions["footer_ax"],
            ["Reported latency = measured - loopback.median  +/-  jitter.p99"],
            anchor="center")

    _save_figure(_fig, file_path, fname, verbose=verbose)
    return _fig


def plot_calib_rate_sweep(rate_sweep: Dict[str, Any],
                          *,
                          xspec: Optional[AxisSpec] = None,
                          yspec: Optional[AxisSpec] = None,
                          layout: Optional[FigureLayout] = None,
                          title: Optional[str] = None,
                          file_path: Optional[str] = None,
                          fname: Optional[str] = None,
                          verbose: bool = False) -> Figure:
    """*plot_calib_rate_sweep()* standalone plot of effective rate + mean loss vs target rate.

    Two curves on one axis: the identity reference `effective = target` and the measured effective-rate curve with min/max error bars across trials. A second y-axis carries the mean-loss percentage per rate. A horizontal dashed line marks the `target_loss_pct` bar; the `calibrated_rate` (highest passing rate) is annotated as a vertical marker.

    Args:
        rate_sweep (dict): `rate_sweep` block from the calibration envelope; shape `{"aggregates": {"<rate>": {...}}, "target_loss_pct": ..., "calibrated_rate": ...}`.
        xspec (Optional[AxisSpec]): x-axis spec; defaults to linear with the standard label.
        yspec (Optional[AxisSpec]): primary y-axis spec; defaults to linear with the standard label.
        layout (Optional[FigureLayout]): full layout override. Defaults to a 1x1 2D body with a centred legend footer.
        title (Optional[str]): figure title; defaults to `"Rate saturation (client effective vs target)"`.
        file_path (Optional[str]): directory to save into.
        fname (Optional[str]): filename stem or name (extension ignored); both PNG and SVG written.
        verbose (bool): if True, prints one save-path message per format.

    Raises:
        ValueError: If `_save_figure` fails for either format.

    Returns:
        Figure: the matplotlib figure.

    Example::

        plot_calib_rate_sweep(envelope["rate_sweep"],
                              title="Client rate saturation",
                              file_path="data/img/experiment/calibration",
                              fname="rate_sweep")
    """
    _xspec = _pick_axis_spec(
        xspec, AxisSpec(scale="linear", label="Target rate [req/s]"))
    _yspec = _pick_axis_spec(
        yspec, AxisSpec(scale="linear", label="Effective rate [req/s]"))

    _resolved_title = _pick_title(title, "Rate saturation (client effective vs target)")
    _default_layout = FigureLayout(title=_resolved_title,
                                   title_h=0.10,
                                   body=BodySpec(shape=(1, 1),
                                                 panel_kind="2d"),
                                   footer_h=0.18,
                                   footer_kind="legend",
                                   figsize=(12, 9))
    _layout = _pick_layout(layout, _default_layout)

    _fig, _regions = build_stacked_figure(_layout)
    _ax = _regions["body_axes"][0]

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

    # identity reference line
    if _xs:
        _lo_ref = min(_xs)
        _hi_ref = max(_xs)
        _ax.plot([_lo_ref, _hi_ref], [_lo_ref, _hi_ref],
                 linestyle=":",
                 color="#888888",
                 linewidth=1.5,
                 label="Identity (effective = target)")

    # measured effective-rate curve with min/max error bars
    _err_lo: List[float] = []
    _err_hi: List[float] = []
    for _i, _m in enumerate(_means):
        _err_lo.append(max(_m - _los[_i], 0.0))
        _err_hi.append(max(_his[_i] - _m, 0.0))
    _c_mean, _, _ = _PCTL_GRADIENT
    _ax.errorbar(_xs, _means,
                 yerr=[_err_lo, _err_hi],
                 marker="o",
                 linestyle="--",
                 linewidth=2.0,
                 color=_c_mean,
                 ecolor=_c_mean,
                 capsize=4,
                 capthick=1.2,
                 label="Measured effective (mean)")
    for _x, _m in zip(_xs, _means):
        _ax.annotate(f"{_m:.1f}",
                     xy=(_x, _m),
                     xytext=(6, 6),
                     textcoords="offset points",
                     fontsize=9,
                     color=_TEXT_BLACK)

    attach_axis_spec(_ax, _xspec, _yspec)

    # secondary axis: mean loss % per rate
    _ax2 = _ax.twinx()
    _ax2.plot(_xs, _losses,
              marker="s",
              linestyle="--",
              linewidth=1.5,
              color="#C9603C",
              label="Mean loss (%)")
    _ax2.axhline(_target_loss,
                 linestyle="--",
                 color="#C9603C",
                 linewidth=1.0,
                 alpha=0.6)
    _ax2.set_ylabel("Mean loss [%]", color="#C9603C", fontweight="bold")
    _ax2.tick_params(axis="y", colors="#C9603C")

    # target-loss anchor on the primary x-axis (resolved without an inline ternary)
    if _xs:
        _target_x_anchor = max(_xs)
    else:
        _target_x_anchor = 0.0
    _ax2.annotate(f"target {_target_loss:.1f}%",
                  xy=(_target_x_anchor, _target_loss),
                  xytext=(-6, 4),
                  textcoords="offset points",
                  ha="right",
                  fontsize=9,
                  color="#C9603C")

    # calibrated-rate vertical marker
    if _calibrated is not None:
        if _means:
            _calib_y_anchor = max(_means)
        else:
            _calib_y_anchor = 0.0
        _ax.axvline(float(_calibrated),
                    linestyle="-",
                    color=_TEXT_BLACK,
                    linewidth=1.0,
                    alpha=0.5)
        _ax.annotate(f"calibrated = {float(_calibrated):.1f} req/s",
                     xy=(float(_calibrated), _calib_y_anchor),
                     xytext=(6, -14),
                     textcoords="offset points",
                     fontsize=9,
                     color=_TEXT_BLACK)

    # combined legend in the footer (primary + secondary axis handles)
    _h1, _l1 = _ax.get_legend_handles_labels()
    _h2, _l2 = _ax2.get_legend_handles_labels()
    _handles = _h1 + _h2
    _labels = _l1 + _l2
    if _regions["footer_ax"] is not None and _handles:
        render_footer_legend(_regions["footer_ax"],
                             _handles,
                             _labels,
                             ncol=min(len(_labels), 4))

    _save_figure(_fig, file_path, fname, verbose=verbose)
    return _fig

# -*- coding: utf-8 -*-
"""Plotters for the calibration envelope.

Five per-probe panels plus a 2x3 summary grid (with a Report panel) and an overlay variant for cross-deployment comparison:

- `plot_timer`: clock-tick `Min`, `phi` (median), `chi-hat` (mean), `Max`; std-dev `s^2` rendered as +/- error caps.
- `plot_jitter`: `chi-hat`, `phi`, `p_{95}`, `p_{99}` relative to target sleep; `s^2` as caps.
- `plot_loopback`: `Min`, `phi`, `p_{95}`, `p_{99}`; precision band `[phi - s^2, phi + s^2]` shaded behind bars.
- `plot_handler_scaling`: linear latency vs concurrency; three traces (`phi`, `p_{95}`, `p_{99}`) + p95-p99 fill.
- `plot_rate_sweep`: latency + loss-rate vs rate; verifiable region (below saturation) shaded green.
- `plot_calibration_summary`: 2x3 grid of all five panels + a Report block (precision band, verifiable range, envelope gates, floors).
- `plot_envelope_overlay`: same 2x3 grid with two envelopes overlaid.

`plot_rate_sweep` and `plot_handler_scaling` subtract the loopback median floor from displayed values by default (`subtract_floor=True`); the panels measure service work on top of the floor, not the floor itself. Toggle off for raw inspection. Footer text states the formula.
"""

from __future__ import annotations

from typing import Any

import matplotlib.pyplot as plt
from matplotlib.axes import Axes
from matplotlib.figure import Figure

from src.view.common import (
    _NEUTRAL_BAR,
    _PCTL_GRADIENT,
    _TEXT_BLACK,
    _generate_color_map,
    _save_figure,
)


# Per-trace tints for handler scaling (phi / p99 traces; the p95 trace inherits the panel colour).
_PHI_COLOR, _, _P99_COLOR = _PCTL_GRADIENT

_TIGHT_RECT: tuple[float, float, float, float] = (0.0, 0.0, 1.0, 0.97)


def plot_timer(envelope: dict[str, Any],
               *,
               title: str | None = None,
               file_path: str | None = None,
               fname: str = "timer",
               verbose: bool = False) -> Figure:
    """Horizontal bar chart of timer min / phi / chi-hat / s^2 / max (ns)."""
    _fig, _ax = plt.subplots(figsize=(6, 3.5))
    _draw_timer(_ax, envelope.get("timer", {}), title=title)
    _fig.tight_layout()
    _save_figure(_fig, file_path, fname, verbose)
    return _fig


def plot_jitter(envelope: dict[str, Any],
                *,
                title: str | None = None,
                file_path: str | None = None,
                fname: str = "jitter",
                verbose: bool = False) -> Figure:
    """Horizontal bar chart of asyncio.sleep chi-hat / phi / p_{95} / p_{99} / s^2 against the target sleep."""
    _fig, _ax = plt.subplots(figsize=(6, 3.5))
    _draw_jitter(_ax, envelope.get("jitter", {}), title=title)
    _fig.tight_layout()
    _save_figure(_fig, file_path, fname, verbose)
    return _fig


def plot_loopback(envelope: dict[str, Any],
                  *,
                  title: str | None = None,
                  file_path: str | None = None,
                  fname: str = "loopback",
                  verbose: bool = False) -> Figure:
    """Horizontal bar chart of TCP loopback Min / phi / p_{95} / p_{99} (us)."""
    _fig, _ax = plt.subplots(figsize=(6, 3.5))
    _draw_loopback(_ax, envelope.get("loopback", {}), title=title)
    _fig.tight_layout()
    _save_figure(_fig, file_path, fname, verbose)
    return _fig


def plot_handler_scaling(envelope: dict[str, Any],
                         *,
                         title: str | None = None,
                         file_path: str | None = None,
                         fname: str = "handler_scaling",
                         verbose: bool = False,
                         subtract_floor: bool = True) -> Figure:
    """Log-log latency (us) vs concurrency, three traces (phi, p_{95}, p_{99})."""
    _fig, _ax = plt.subplots(figsize=(7, 4))
    _draw_handler_scaling(_ax,
                          envelope.get("handler_scaling", {}),
                          loopback=envelope.get("loopback", {}),
                          title=title,
                          subtract_floor=subtract_floor)
    _fig.tight_layout()
    _save_figure(_fig, file_path, fname, verbose)
    return _fig


def plot_rate_sweep(envelope: dict[str, Any],
                    *,
                    title: str | None = None,
                    file_path: str | None = None,
                    fname: str = "rate_sweep",
                    verbose: bool = False,
                    subtract_floor: bool = True) -> Figure:
    """Twin-axis plot of p_{95} latency (us) + loss percent vs target rate."""
    _fig, _ax = plt.subplots(figsize=(7, 4))
    _draw_rate_sweep(_ax,
                     envelope.get("rate", {}),
                     loopback=envelope.get("loopback", {}),
                     title=title,
                     subtract_floor=subtract_floor)
    _fig.tight_layout()
    _save_figure(_fig, file_path, fname, verbose)
    return _fig


def plot_calibration_summary(envelope: dict[str, Any],
                             *,
                             title: str | None = None,
                             file_path: str | None = None,
                             fname: str = "summary",
                             verbose: bool = False,
                             subtract_floor: bool = True) -> Figure:
    """2x3 grid: timer, jitter, loopback, handler scaling, rate sweep, gate verdict text."""
    _fig, _axes = plt.subplots(2, 3, figsize=(18, 9))
    _loopback = envelope.get("loopback", {})
    _draw_timer(_axes[0, 0], envelope.get("timer", {}))
    _draw_jitter(_axes[0, 1], envelope.get("jitter", {}))
    _draw_loopback(_axes[0, 2], _loopback)
    _draw_handler_scaling(_axes[1, 0],
                          envelope.get("handler_scaling", {}),
                          loopback=_loopback,
                          subtract_floor=subtract_floor)
    _draw_rate_sweep(_axes[1, 1],
                     envelope.get("rate", {}),
                     loopback=_loopback,
                     subtract_floor=subtract_floor)
    _draw_report(_axes[1, 2], envelope.get("gate", {}), envelope=envelope)
    if title is None:
        _title = (f"Calibration: {envelope.get('host', '?')}, "
                  f"dpl={envelope.get('dpl', '?')}")
    else:
        _title = title
    _fig.suptitle(_title, color=_TEXT_BLACK, fontsize=15, fontweight="bold")
    _fig.tight_layout(rect=_TIGHT_RECT)
    _save_figure(_fig, file_path, fname, verbose)
    return _fig


def plot_envelope_overlay(envelopes: dict[str, dict[str, Any]],
                          *,
                          title: str | None = None,
                          file_path: str | None = None,
                          fname: str = "overlay",
                          verbose: bool = False,
                          subtract_floor: bool = True) -> Figure:
    """2x3 grid overlaying multiple envelopes for cross-deployment comparison."""
    _fig, _axes = plt.subplots(2, 3, figsize=(18, 9))
    _items = list(envelopes.items())
    _palette = _generate_color_map(_items)
    _total = len(_items)
    for _i, (_label, _env) in enumerate(_items):
        _color = _palette[_i]
        _loopback = _env.get("loopback", {})
        _draw_timer(_axes[0, 0], _env.get("timer", {}),
                    color=_color, label=_label, idx=_i, total=_total)
        _draw_jitter(_axes[0, 1], _env.get("jitter", {}),
                     color=_color, label=_label, idx=_i, total=_total)
        _draw_loopback(_axes[0, 2], _loopback,
                       color=_color, label=_label, idx=_i, total=_total)
        _draw_handler_scaling(_axes[1, 0],
                              _env.get("handler_scaling", {}),
                              loopback=_loopback,
                              color=_color,
                              label=_label,
                              subtract_floor=subtract_floor)
        _draw_rate_sweep(_axes[1, 1],
                         _env.get("rate", {}),
                         loopback=_loopback,
                         color=_color,
                         label=_label,
                         subtract_floor=subtract_floor)
    _draw_report_overlay(_axes[1, 2], envelopes)
    # Report panel has only text; skip its legend to silence "no artists" warning.
    _sub_imgs = (
        _axes[0, 0],
        _axes[0, 1],
        _axes[0, 2],
        _axes[1, 0],
        _axes[1, 1]
    )
    for _ax in _sub_imgs:
        _ax.legend(fontsize=9)
    if title is None:
        _title = "Calibration overlay"
    else:
        _title = title
    _fig.suptitle(_title, color=_TEXT_BLACK, fontsize=15, fontweight="bold")
    _fig.tight_layout(rect=_TIGHT_RECT)
    _save_figure(_fig, file_path, fname, verbose)
    return _fig


# ---- Per-axis drawers (private; shared by single-panel plotters and the grid) ----

def _draw_timer(ax: Axes,
                block: dict[str, Any],
                *,
                title: str | None = None,
                color: Any = _NEUTRAL_BAR,
                label: str | None = None,
                idx: int = 0,
                total: int = 1) -> None:
    """Horizontal bars: Min, phi, chi-hat, Max in ns; s^2 rendered as +/- error caps on each bar."""
    _labels = ["Min", r"$\phi$", r"$\hat{\chi}$", "Max"]
    _vals = [block.get("min_ns", 0),
             block.get("median_ns", 0),
             block.get("mean_ns", 0.0),
             block.get("max_ns", 0)]
    _std = float(block.get("std_ns", 0.0))
    _draw_grouped_barh(ax, _labels, _vals, "ns",
                       color=color, label=label, idx=idx, total=total,
                       xerr=_std)
    ax.set_xlabel(r"$[\mathrm{ns}]$  (caps: $s^{2}$)", color=_TEXT_BLACK)
    if title is None:
        _t = f"Timer (n={block.get('samples_n', 0)})"
    else:
        _t = title
    ax.set_title(_t, color=_TEXT_BLACK, fontweight="bold")
    ax.grid(axis="x", linestyle=":", alpha=0.5)


def _draw_jitter(ax: Axes,
                 block: dict[str, Any],
                 *,
                 title: str | None = None,
                 color: Any = _NEUTRAL_BAR,
                 label: str | None = None,
                 idx: int = 0,
                 total: int = 1) -> None:
    """Horizontal bars: chi-hat, phi, p_{95}, p_{99} relative to target sleep (us); s^2 rendered as +/- error caps."""
    _target_us = block.get("target_us", 0)
    _labels = [r"$\hat{\chi}$", r"$\phi$", r"$p_{95}$", r"$p_{99}$"]
    # Show jitter relative to the target so values centre near zero when the host is quiet.
    _vals = [block.get("mean_us", 0.0) - _target_us,
             block.get("median_us", 0.0) - _target_us,
             block.get("p95_us", 0.0) - _target_us,
             block.get("p99_us", 0.0) - _target_us]
    _std = float(block.get("std_us", 0.0))
    _draw_grouped_barh(ax, _labels, _vals, r"$\mu s$",
                       color=color, label=label, idx=idx, total=total,
                       xerr=_std)
    ax.set_xlabel(r"$[\mu s]$ (actual $-$ target; caps: $s^{2}$)", color=_TEXT_BLACK)
    if title is None:
        _t = f"Jitter (target {_target_us / 1000:.0f} ms)"
    else:
        _t = title
    ax.set_title(_t, color=_TEXT_BLACK, fontweight="bold")
    ax.grid(axis="x", linestyle=":", alpha=0.5)


def _draw_loopback(ax: Axes,
                   block: dict[str, Any],
                   *,
                   title: str | None = None,
                   color: Any = _NEUTRAL_BAR,
                   label: str | None = None,
                   idx: int = 0,
                   total: int = 1) -> None:
    """Horizontal bars: Min, phi, p_{95}, p_{99} (us); precision band [phi - s^2, phi + s^2] shaded behind the bars."""
    _labels = ["Min", r"$\phi$", r"$p_{95}$", r"$p_{99}$"]
    _phi = float(block.get("median_us", 0.0))
    _std = float(block.get("std_us", 0.0))
    _vals = [block.get("min_us", 0.0),
             _phi,
             block.get("p95_us", 0.0),
             block.get("p99_us", 0.0)]
    # Translucent band centred on the median; only drawn for the first envelope so overlays do not paint twice.
    if idx == 0 and _std > 0.0:
        ax.axvspan(_phi - _std, _phi + _std,
                   color=color, alpha=0.12, zorder=0,
                   label=r"$\phi \pm s^{2}$")
    _draw_grouped_barh(ax, _labels, _vals, r"$\mu s$",
                       color=color, label=label, idx=idx, total=total,
                       xerr=_std)
    ax.set_xlabel(r"$[\mu s]$  (band + caps: $s^{2}$)", color=_TEXT_BLACK)
    _payload = block.get("payload_bytes", 0)
    if title is None:
        _t = f"Loopback ({_payload:,} B)"
    else:
        _t = title
    ax.set_title(_t, color=_TEXT_BLACK, fontweight="bold")
    ax.grid(axis="x", linestyle=":", alpha=0.5)


def _draw_handler_scaling(ax: Axes,
                          block: dict[str, Any],
                          *,
                          loopback: dict[str, Any] | None = None,
                          title: str | None = None,
                          color: Any = _NEUTRAL_BAR,
                          label: str | None = None,
                          subtract_floor: bool = True) -> None:
    """Latency vs concurrency, three traces (phi, p_{95}, p_{99}).

    Linear axes for typical default sweeps (c <= ~32). Log-log makes sense only when concurrency spans multiple decades (e.g. 1..1000); at small ranges it hides the signal. Loopback floor subtracted by default so the panel shows handler work, not kernel noise.
    """
    _stats = block.get("stats", {})
    _cs = sorted(int(_k) for _k in _stats.keys())
    if not _cs:
        ax.set_title(title or "Handler scaling", color=_TEXT_BLACK, fontweight="bold")
        return
    _floor = _resolve_floor_us(loopback, subtract_floor)
    _phi = [max(_stats[str(_c)].get("median_us", 0.0) - _floor, 0.0) for _c in _cs]
    _p95 = [max(_stats[str(_c)].get("p95_us", 0.0) - _floor, 0.0) for _c in _cs]
    _p99 = [max(_stats[str(_c)].get("p99_us", 0.0) - _floor, 0.0) for _c in _cs]
    if label is None:
        _phi_label, _p95_label, _p99_label = r"$\phi$", r"$p_{95}$", r"$p_{99}$"
    else:
        _phi_label = f"{label}: $\\phi$"
        _p95_label = f"{label}: $p_{{95}}$"
        _p99_label = f"{label}: $p_{{99}}$"
    # Translucent fill between p95 and p99 highlights the tail variability as a precision band.
    ax.fill_between(_cs, _p95, _p99, color=color, alpha=0.12,
                    label=r"$p_{95} \rightarrow p_{99}$" if label is None else None)
    ax.plot(_cs, _phi, marker="o", color=_PHI_COLOR,
            linestyle="--", label=_phi_label)
    ax.plot(_cs, _p95, marker="s", color=color,
            linestyle="--", label=_p95_label)
    ax.plot(_cs, _p99, marker="^", color=_P99_COLOR,
            linestyle="--", label=_p99_label)
    # Annotate the highest-c point on the median trace.
    ax.annotate(_fmt_us(_phi[-1]),
                xy=(_cs[-1], _phi[-1]),
                xytext=(5, 5),
                textcoords="offset points",
                fontsize=9, color=_TEXT_BLACK)
    # Linear axes; log-log only earns its keep when concurrency spans multiple decades.
    ax.set_xscale("linear")
    ax.set_yscale("linear")
    ax.set_xlabel(r"concurrency $c$", color=_TEXT_BLACK)
    ax.set_ylabel(r"Latency $[\mu s]$", color=_TEXT_BLACK)
    if title is None:
        _t = "Handler scaling"
    else:
        _t = title
    ax.set_title(_t, color=_TEXT_BLACK, fontweight="bold")
    ax.grid(linestyle=":", alpha=0.5)
    ax.legend(loc="upper left", fontsize=10)


def _draw_rate_sweep(ax: Axes,
                     block: dict[str, Any],
                     *,
                     loopback: dict[str, Any] | None = None,
                     title: str | None = None,
                     color: Any = _NEUTRAL_BAR,
                     label: str | None = None,
                     subtract_floor: bool = True) -> None:
    """Twin-axis: p_{95} latency on left (us), loss percent on right (%). Loopback floor subtracted from latency."""
    _per = block.get("per_rate", [])
    _rates = [_row.get("rate", 0) for _row in _per]
    _floor = _resolve_floor_us(loopback, subtract_floor)
    _p95 = [max(_row.get("p95_us", 0.0) - _floor, 0.0) for _row in _per]
    _loss = [_row.get("loss_pct", 0.0) for _row in _per]
    _sat = block.get("saturation_rate")
    # Verifiable range: rates below saturation are inside the calibrated envelope; shade them.
    if _rates and _sat is not None:
        ax.axvspan(min(_rates), _sat, color="#4CAF50", alpha=0.07, zorder=0)
        ax.axvline(_sat, color="#C44536", linestyle="--", linewidth=1.2,
                   alpha=0.7, label=f"saturation ({_sat} req/s)")
    if _rates:
        _lat_label = label or r"$p_{95}$ latency"
        ax.plot(_rates, _p95, marker="o", color=color,
                linestyle="-", linewidth=2, label=_lat_label)
    ax.set_xlabel("target rate (req/s)", color=_TEXT_BLACK)
    ax.set_ylabel(r"$p_{95}$ latency $[\mu s]$", color=_TEXT_BLACK)
    if title is None:
        _sat = block.get("saturation_rate")
        if _sat is None:
            _t = "Rate sweep"
        else:
            _t = f"Rate sweep (sat. {_sat} req/s)"
    else:
        _t = title
    ax.set_title(_t, color=_TEXT_BLACK, fontweight="bold")
    ax.grid(linestyle=":", alpha=0.5)

    # Reuse the twin axis across overlay calls so multiple envelopes share one right y-axis.
    _ax2 = getattr(ax, "_loss_axis", None)
    if _ax2 is None:
        _ax2 = ax.twinx()
        ax._loss_axis = _ax2  # type: ignore[attr-defined]
        _ax2.set_ylabel("loss (%)", color=_TEXT_BLACK)
    if _rates:
        _ax2.plot(_rates, _loss, marker="x", color="#F0AB7E",
                  linestyle="--", alpha=0.85, label="loss %")


# Layout constants (axes-fraction units) for the Report panel.
_REPORT_FONTSIZE = 8
_REPORT_LINE_H = 0.034
_REPORT_LABEL_X = 0.02
_REPORT_VALUE_X = 0.36
_REPORT_ROW_LABEL_X = 0.05
_REPORT_ROW_VALUE_X = 0.20
_REPORT_LEGEND_BODY_X = 0.14

_REPORT_LEGEND_ROWS = (
    ("Latency:",
     ("Reported figures equal the measured value",
      "minus the loopback floor (median), with the",
      "jitter p99 as the precision band.")),
    ("Floors:",
     ("Background noise sources we cannot control",
      "(clock, scheduler, kernel TCP path); the",
      "precision band is their RMS sum.")),
    ("Envelope:",
     ("Operating limits where the apparatus's",
      "measurements remain trustworthy (concurrency",
      "knee + rate saturation knee).")),
)


def _draw_report(ax: Axes,
                 gate_block: dict[str, Any],
                 *,
                 envelope: dict[str, Any] | None = None) -> None:
    """Text-only Report panel: header strip + precision band + operating range + per-row headlines + static legend.

    Each row is rendered as two `ax.text()` calls (bold label + regular value) so headers and per-row labels stand out without breaking the monospace alignment of the values.
    """
    ax.axis("off")

    _band = (gate_block.get("precision_band_us") or {}).get("total_us")
    _range = gate_block.get("verifiable_range", {}) or {}
    _summary = gate_block.get("summary", {}) or {}
    _limit = gate_block.get("noise_floor_pct", 0.0)

    _y = 0.99
    _y = _draw_header_rows(ax, envelope, _limit, _y)
    _y = _draw_band_rows(ax, _band, _range, _y)
    _y = _draw_floor_rows(ax, _summary, _y)
    _y = _draw_envelope_rows(ax, _summary, _y)
    _draw_legend_rows(ax, _y)

    ax.set_title("Calibration Report", color=_NEUTRAL_BAR, fontweight="bold")


def _draw_header_rows(ax: Axes,
                      envelope: dict[str, Any] | None,
                      limit: Any,
                      y: float) -> float:
    """Header strip: HOST / DEPLOYMENT MODE / RUN / ALLOWED NOISE FLOOR rows."""
    _y = y
    if envelope is not None:
        _y = _put_kv(ax, "HOST:", str(envelope.get("host", "?")), _y)
        _y = _put_kv(ax, "DEPLOYMENT MODE:", str(envelope.get("dpl", "?")), _y)
        _y = _put_kv(ax, "RUN:", str(envelope.get("run_id", "?")), _y)
        if isinstance(limit, (int, float)):
            _y = _put_kv(ax, "ALLOWED NOISE FLOOR:",
                         f"± {float(limit):.1f} %", _y)
        _y -= _REPORT_LINE_H * 0.5
    return _y


def _draw_band_rows(ax: Axes,
                    band: float | None,
                    range_block: dict[str, Any],
                    y: float) -> float:
    """Precision band + operating range rows."""
    if band is None:
        _band_str = "n/a"
    else:
        _band_str = rf"$\pm$ {band:.2f} $\mu$s"
    _y = _put_kv(ax, "PRECISION BAND:", _band_str, y)
    _y -= _REPORT_LINE_H * 0.5

    _c_max = range_block.get("c_max")
    _r_max = range_block.get("r_max_req_s")
    if _c_max is None:
        _c_str = "n/a"
    else:
        _c_str = rf"$c \leq {int(_c_max)}$"
    if _r_max is None:
        _r_str = "n/a"
    else:
        _r_str = rf"$r \leq {int(_r_max)}$ req/s"
    _y = _put_kv(ax, "OPERATING RANGE:", _c_str, _y)
    _y = _put_kv(ax, "", _r_str, _y)
    _y -= _REPORT_LINE_H * 0.5
    return _y


def _draw_floor_rows(ax: Axes,
                     summary: dict[str, Any],
                     y: float) -> float:
    """FLOORS section: bold section label + three indented data rows (Timer / Jitter / Loopback)."""
    _y = _put_section(ax, "FLOORS:", y)
    for _name, _label in (("timer", "Timer:"), ("jitter", "Jitter:"), ("loopback", "Loopback:")):
        _hl = summary.get(_name, {}).get("headline", "n/a")
        _y = _put_row(ax, _label, _hl, _y)
    _y -= _REPORT_LINE_H * 0.5
    return _y


def _draw_envelope_rows(ax: Axes,
                        summary: dict[str, Any],
                        y: float) -> float:
    """ENVELOPE section: bold section label + two indented data rows (Scaling / Rate sweep)."""
    _y = _put_section(ax, "ENVELOPE:", y)
    for _name, _label in (("scaling", "Scaling:"), ("rate", "Rate sweep:")):
        _hl = summary.get(_name, {}).get("headline", "n/a")
        _y = _put_row(ax, _label, _hl, _y)
    _y -= _REPORT_LINE_H * 0.5
    return _y


def _draw_legend_rows(ax: Axes, y: float) -> None:
    """Static three-block legend explaining Latency / Floors / Envelope; bold labels, regular body."""
    _y = y
    ax.text(_REPORT_LABEL_X, _y, "─" * 64,
            transform=ax.transAxes, va="top",
            fontsize=_REPORT_FONTSIZE, color=_TEXT_BLACK, family="monospace")
    _y -= _REPORT_LINE_H
    for _label, _body_lines in _REPORT_LEGEND_ROWS:
        ax.text(_REPORT_LABEL_X, _y, _label,
                transform=ax.transAxes, va="top",
                fontsize=_REPORT_FONTSIZE, fontweight="bold",
                color=_TEXT_BLACK, family="monospace")
        for _line in _body_lines:
            ax.text(_REPORT_LEGEND_BODY_X, _y, _line,
                    transform=ax.transAxes, va="top",
                    fontsize=_REPORT_FONTSIZE,
                    color=_TEXT_BLACK, family="monospace")
            _y -= _REPORT_LINE_H


def _put_kv(ax: Axes, label: str, value: str, y: float) -> float:
    """Render one bold uppercase header label + regular value on the same row; return the next y."""
    if label:
        ax.text(_REPORT_LABEL_X, y, label,
                transform=ax.transAxes, va="top",
                fontsize=_REPORT_FONTSIZE, fontweight="bold",
                color=_TEXT_BLACK, family="monospace")
    ax.text(_REPORT_VALUE_X, y, value,
            transform=ax.transAxes, va="top",
            fontsize=_REPORT_FONTSIZE,
            color=_TEXT_BLACK, family="monospace")
    return y - _REPORT_LINE_H


def _put_section(ax: Axes, label: str, y: float) -> float:
    """Render a bold uppercase section label on its own row; return the next y."""
    ax.text(_REPORT_LABEL_X, y, label,
            transform=ax.transAxes, va="top",
            fontsize=_REPORT_FONTSIZE, fontweight="bold",
            color=_TEXT_BLACK, family="monospace")
    return y - _REPORT_LINE_H


def _put_row(ax: Axes, label: str, value: str, y: float) -> float:
    """Render an indented bold sentence-case row label + regular value; return the next y."""
    ax.text(_REPORT_ROW_LABEL_X, y, label,
            transform=ax.transAxes, va="top",
            fontsize=_REPORT_FONTSIZE, fontweight="bold",
            color=_TEXT_BLACK, family="monospace")
    ax.text(_REPORT_ROW_VALUE_X, y, value,
            transform=ax.transAxes, va="top",
            fontsize=_REPORT_FONTSIZE,
            color=_TEXT_BLACK, family="monospace")
    return y - _REPORT_LINE_H


def _draw_report_overlay(ax: Axes,
                         envelopes: dict[str, dict[str, Any]]) -> None:
    """Overlay Report panel: borderless table (rows = attributes, columns = envelopes) + legend.

    Each row pairs an attribute label with one value per envelope, all rendered as separate `ax.text()` calls so bold labels coexist with regular values without breaking monospace alignment. The static three-block legend renders below the table.
    """
    ax.axis("off")
    _items = list(envelopes.items())
    _names = [str(_label) for _label, _ in _items]
    _y = 0.99
    _y = _put_overlay_columns(ax, _names, _y)
    _y -= _REPORT_LINE_H * 0.3

    _y = _put_overlay_row(ax, "PRECISION BAND:",
                          [_overlay_band(_env) for _, _env in _items],
                          _y, indent=False)
    _y -= _REPORT_LINE_H * 0.3

    _y = _put_section(ax, "OPERATING RANGE:", _y)
    _y = _put_overlay_row(ax, "c max:",
                          [_overlay_c_max(_env) for _, _env in _items],
                          _y, indent=True)
    _y = _put_overlay_row(ax, "r max:",
                          [_overlay_r_max(_env) for _, _env in _items],
                          _y, indent=True)
    _y -= _REPORT_LINE_H * 0.3

    _y = _put_section(ax, "FLOORS:", _y)
    for _name, _label in (("timer", "Timer:"), ("jitter", "Jitter:"), ("loopback", "Loopback:")):
        _y = _put_overlay_row(ax, _label,
                              [_overlay_headline(_env, _name) for _, _env in _items],
                              _y, indent=True)
    _y -= _REPORT_LINE_H * 0.3

    _y = _put_section(ax, "ENVELOPE:", _y)
    for _name, _label in (("scaling", "Scaling:"), ("rate", "Rate sweep:")):
        _y = _put_overlay_row(ax, _label,
                              [_overlay_headline(_env, _name) for _, _env in _items],
                              _y, indent=True)

    _draw_legend_rows(ax, _y)
    ax.set_title("Calibration Reports", color=_NEUTRAL_BAR, fontweight="bold")


def _overlay_columns_x(n: int) -> list[float]:
    """Compute the left edge of each value column in the overlay table.

    Args:
        n (int): number of envelope columns.

    Returns:
        list[float]: x positions (axes-fraction); evenly spaced from 0.30 to 1.0.
    """
    _ans: list[float] = []
    if n > 0:
        _start = 0.30
        _width = (1.0 - _start) / n
        _i = 0
        while _i < n:
            _ans.append(_start + _i * _width)
            _i += 1
    return _ans


def _put_overlay_columns(ax: Axes, names: list[str], y: float) -> float:
    """Render the column-header row (uppercase bold envelope names).

    Args:
        ax (Axes): target axis.
        names (list[str]): envelope labels (one per column).
        y (float): top y-coordinate (axes-fraction).

    Returns:
        float: next y-coordinate after the row.
    """
    _xs = _overlay_columns_x(len(names))
    for _x, _name in zip(_xs, names, strict=True):
        ax.text(_x, y, _name.upper(),
                transform=ax.transAxes, va="top",
                fontsize=_REPORT_FONTSIZE, fontweight="bold",
                color=_TEXT_BLACK, family="monospace")
    return y - _REPORT_LINE_H


def _put_overlay_row(ax: Axes,
                     label: str,
                     values: list[str],
                     y: float,
                     *,
                     indent: bool) -> float:
    """Render one table row: bold label + one value per envelope column.

    Args:
        ax (Axes): target axis.
        label (str): row label (rendered bold).
        values (list[str]): per-envelope value strings; length must match the column count.
        y (float): top y-coordinate.
        indent (bool): True for nested rows under a section header (uses `_REPORT_ROW_LABEL_X`).

    Returns:
        float: next y-coordinate after the row.
    """
    if indent:
        _x_label = _REPORT_ROW_LABEL_X
    else:
        _x_label = _REPORT_LABEL_X
    ax.text(_x_label, y, label,
            transform=ax.transAxes, va="top",
            fontsize=_REPORT_FONTSIZE, fontweight="bold",
            color=_TEXT_BLACK, family="monospace")
    _xs = _overlay_columns_x(len(values))
    for _x, _val in zip(_xs, values, strict=True):
        ax.text(_x, y, _val,
                transform=ax.transAxes, va="top",
                fontsize=_REPORT_FONTSIZE,
                color=_TEXT_BLACK, family="monospace")
    return y - _REPORT_LINE_H


def _overlay_band(env: dict[str, Any]) -> str:
    """Format the precision band for an overlay table cell.

    Args:
        env (dict[str, Any]): one envelope.

    Returns:
        str: `$\\pm$ X.XX $\\mu$s`, or `n/a` when the band is missing.
    """
    _band = (env.get("gate", {}).get("precision_band_us") or {}).get("total_us")
    _ans = "n/a"
    if _band is not None:
        _ans = rf"$\pm$ {float(_band):.2f} $\mu$s"
    return _ans


def _overlay_c_max(env: dict[str, Any]) -> str:
    """Format `c_max` as `$c \\leq N$` for an overlay table cell.

    Args:
        env (dict[str, Any]): one envelope.

    Returns:
        str: mathtext expression, or `n/a` when c_max is missing.
    """
    _c = env.get("gate", {}).get("verifiable_range", {}).get("c_max")
    _ans = "n/a"
    if _c is not None:
        _ans = rf"$c \leq {int(_c)}$"
    return _ans


def _overlay_r_max(env: dict[str, Any]) -> str:
    """Format `r_max` as `$r \\leq N$ req/s` for an overlay table cell.

    Args:
        env (dict[str, Any]): one envelope.

    Returns:
        str: mathtext expression, or `n/a` when r_max is missing.
    """
    _r = env.get("gate", {}).get("verifiable_range", {}).get("r_max_req_s")
    _ans = "n/a"
    if _r is not None:
        _ans = rf"$r \leq {int(_r)}$ req/s"
    return _ans


def _overlay_headline(env: dict[str, Any], name: str) -> str:
    """Pull `gate.summary[name].headline` for an overlay table cell.

    Args:
        env (dict[str, Any]): one envelope.
        name (str): summary key (`timer` / `jitter` / `loopback` / `scaling` / `rate`).

    Returns:
        str: headline string, or `n/a` when missing.
    """
    return env.get("gate", {}).get("summary", {}).get(name, {}).get("headline", "n/a")


# ---- Internal helpers ----

def _resolve_floor_us(loopback: dict[str, Any] | None,
                      subtract_floor: bool) -> float:
    """Return the loopback median (us) to subtract from displayed latency, or 0.0 when subtraction is disabled."""
    if not subtract_floor or loopback is None:
        return 0.0
    return float(loopback.get("median_us", 0.0))


def _draw_grouped_barh(ax: Axes,
                       labels: list[str],
                       values: list[float],
                       unit: str,
                       *,
                       color: str,
                       label: str | None,
                       idx: int,
                       total: int,
                       xerr: float = 0.0) -> None:
    """Draw one envelope's row of horizontal bars at offset `idx` of `total`.

    Single-envelope panels pass `idx=0, total=1` and get the original layout. Overlay panels pass `idx=0..N-1, total=N` so each label slot is split into N thinner sub-bars stacked vertically; this avoids value-label overlap when two envelopes share the same row.

    `xerr` (>= 0) renders symmetric +/- caps on every bar (in the same units as `values`); it carries the probe's standard deviation so the precision is visible without spending a separate row on `s^2`.
    """
    _n = len(labels)
    _height = 0.8 / total
    _offset = (idx - (total - 1) / 2.0) * _height
    _ys = [_i + _offset for _i in range(_n)]
    if xerr > 0.0:
        _err_kw: dict[str, Any] = {
            "xerr": xerr,
            "error_kw": {"ecolor": _TEXT_BLACK, "capsize": 3, "elinewidth": 1.0},
        }
    else:
        _err_kw = {}
    _bars = ax.barh(_ys, values, height=_height, color=color, alpha=0.85,
                    label=label, **_err_kw)
    for _bar, _val in zip(_bars, values, strict=True):
        ax.text(_bar.get_width() + xerr,
                _bar.get_y() + _bar.get_height() / 2,
                f"  {_fmt_value(_val)} {unit}",
                va="center", ha="left",
                fontsize=9, color=_TEXT_BLACK)
    if idx == 0:
        ax.set_yticks(list(range(_n)))
        ax.set_yticklabels(labels)
        ax.invert_yaxis()


def _fmt_value(value: float) -> str:
    """Format a numeric value with thousands separators and one decimal place when fractional."""
    if abs(value - round(value)) < 1e-6:
        return f"{int(round(value)):,}"
    return f"{value:,.1f}"


def _fmt_us(value: float) -> str:
    """Format a microsecond value as `<n> us` (mathtext mu)."""
    return f"{_fmt_value(value)} $\\mu s$"


__all__ = [
    "plot_calibration_summary",
    "plot_envelope_overlay",
    "plot_handler_scaling",
    "plot_jitter",
    "plot_loopback",
    "plot_rate_sweep",
    "plot_timer",
]

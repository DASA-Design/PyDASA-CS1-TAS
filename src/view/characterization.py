# -*- coding: utf-8 -*-
"""Plotters for the calibration envelope.

Six per-probe panels plus a 2x3 summary grid and an overlay variant for comparing two envelopes (e.g. `localhost` vs `multiprocess`):

- `plot_timer`: clock-tick min / median / max.
- `plot_jitter`: asyncio.sleep median / p95 / p99 vs target.
- `plot_loopback`: TCP round-trip median / p95 / p99.
- `plot_handler_scaling`: median latency vs concurrency.
- `plot_rate_sweep`: latency + loss-rate vs target rate.
- `plot_calibration_summary`: 2x3 grid of all five panels + a gate-verdict block.
- `plot_envelope_overlay`: same 2x3 grid with two envelopes overlaid.

All plotters follow the project's `src/view/<family>.py` contract: keyword-only after positional inputs, return `matplotlib.figure.Figure`, persist via `_save_figure` (writes PNG + SVG).
"""

from __future__ import annotations

from typing import Any

import matplotlib.pyplot as plt
from matplotlib.axes import Axes
from matplotlib.figure import Figure

from src.view.common import (
    _BAR_BLUE,
    _BAR_ORANGE,
    _TEXT_BLACK,
    _save_figure,
)


def plot_timer(envelope: dict[str, Any],
               *,
               title: str | None = None,
               file_path: str | None = None,
               fname: str = "timer",
               verbose: bool = False) -> Figure:
    """Bar chart of timer min / median / max delta (ns) from one envelope.

    Args:
        envelope (dict[str, Any]): the calibration envelope.
        title (str | None, optional): axis title. Defaults to None (auto-built from sample count).
        file_path (str | None, optional): destination directory. Defaults to None (no save).
        fname (str, optional): output filename stem. Defaults to `"timer"`.
        verbose (bool, optional): print save messages. Defaults to False.

    Returns:
        Figure: the matplotlib figure (caller owns the lifecycle).
    """
    _fig, _ax = plt.subplots(figsize=(5, 3))
    _draw_timer(_ax, envelope.get("timer", {}), title=title)
    _save_figure(_fig, file_path, fname, verbose)
    return _fig


def plot_jitter(envelope: dict[str, Any],
                *,
                title: str | None = None,
                file_path: str | None = None,
                fname: str = "jitter",
                verbose: bool = False) -> Figure:
    """Bar chart of `asyncio.sleep` median / p95 / p99 (us) against the target sleep.

    Args:
        envelope (dict[str, Any]): the calibration envelope.
        title (str | None, optional): axis title.
        file_path (str | None, optional): destination directory.
        fname (str, optional): output filename stem.
        verbose (bool, optional): print save messages.

    Returns:
        Figure: the matplotlib figure.
    """
    _fig, _ax = plt.subplots(figsize=(5, 3))
    _draw_jitter(_ax, envelope.get("jitter", {}), title=title)
    _save_figure(_fig, file_path, fname, verbose)
    return _fig


def plot_loopback(envelope: dict[str, Any],
                  *,
                  title: str | None = None,
                  file_path: str | None = None,
                  fname: str = "loopback",
                  verbose: bool = False) -> Figure:
    """Bar chart of TCP loopback round-trip median / p95 / p99 (us)."""
    _fig, _ax = plt.subplots(figsize=(5, 3))
    _draw_loopback(_ax, envelope.get("loopback", {}), title=title)
    _save_figure(_fig, file_path, fname, verbose)
    return _fig


def plot_handler_scaling(envelope: dict[str, Any],
                         *,
                         title: str | None = None,
                         file_path: str | None = None,
                         fname: str = "handler_scaling",
                         verbose: bool = False) -> Figure:
    """Line plot of median handler latency (us) vs concurrency level."""
    _fig, _ax = plt.subplots(figsize=(5, 3))
    _draw_handler_scaling(_ax, envelope.get("handler_scaling", {}), title=title)
    _save_figure(_fig, file_path, fname, verbose)
    return _fig


def plot_rate_sweep(envelope: dict[str, Any],
                    *,
                    title: str | None = None,
                    file_path: str | None = None,
                    fname: str = "rate_sweep",
                    verbose: bool = False) -> Figure:
    """Twin-axis plot of p95 latency (us) + loss percent (%) vs target rate (req/s)."""
    _fig, _ax = plt.subplots(figsize=(6, 3.5))
    _draw_rate_sweep(_ax, envelope.get("rate", {}), title=title)
    _save_figure(_fig, file_path, fname, verbose)
    return _fig


def plot_calibration_summary(envelope: dict[str, Any],
                             *,
                             title: str | None = None,
                             file_path: str | None = None,
                             fname: str = "summary",
                             verbose: bool = False) -> Figure:
    """2x3 grid: timer, jitter, loopback, handler scaling, rate sweep, gate verdict text."""
    _fig, _axes = plt.subplots(2, 3, figsize=(15, 8))
    _draw_timer(_axes[0, 0], envelope.get("timer", {}))
    _draw_jitter(_axes[0, 1], envelope.get("jitter", {}))
    _draw_loopback(_axes[0, 2], envelope.get("loopback", {}))
    _draw_handler_scaling(_axes[1, 0], envelope.get("handler_scaling", {}))
    _draw_rate_sweep(_axes[1, 1], envelope.get("rate", {}))
    _draw_verdict(_axes[1, 2], envelope.get("gate", {}))
    if title is None:
        _title = f"Calibration: {envelope.get('host', '?')}, dpl={envelope.get('dpl', '?')}"
    else:
        _title = title
    _fig.suptitle(_title, color=_TEXT_BLACK, fontsize=14)
    _fig.tight_layout()
    _save_figure(_fig, file_path, fname, verbose)
    return _fig


def plot_envelope_overlay(envelopes: dict[str, dict[str, Any]],
                          *,
                          title: str | None = None,
                          file_path: str | None = None,
                          fname: str = "overlay",
                          verbose: bool = False) -> Figure:
    """2x3 grid overlaying multiple envelopes for cross-deployment comparison.

    Args:
        envelopes (dict[str, dict[str, Any]]): mapping label -> envelope (e.g. `{"localhost": env_a, "multiprocess": env_b}`); colours assigned per label, blue then orange.
        title (str | None, optional): figure title.
        file_path (str | None, optional): destination directory.
        fname (str, optional): output filename stem.
        verbose (bool, optional): print save messages.

    Returns:
        Figure: the matplotlib figure.
    """
    _fig, _axes = plt.subplots(2, 3, figsize=(15, 8))
    _palette = [_BAR_BLUE, _BAR_ORANGE]
    _items = list(envelopes.items())
    for _i, (_label, _env) in enumerate(_items):
        _color = _palette[_i % len(_palette)]
        _draw_timer(_axes[0, 0], _env.get("timer", {}), color=_color, label=_label)
        _draw_jitter(_axes[0, 1], _env.get("jitter", {}), color=_color, label=_label)
        _draw_loopback(_axes[0, 2], _env.get("loopback", {}), color=_color, label=_label)
        _draw_handler_scaling(_axes[1, 0], _env.get("handler_scaling", {}), color=_color, label=_label)
        _draw_rate_sweep(_axes[1, 1], _env.get("rate", {}), color=_color, label=_label)
    _draw_verdict_overlay(_axes[1, 2], envelopes)
    # Verdict panel has only text; skip its legend to silence "no artists" warning.
    for _ax in (_axes[0, 0], _axes[0, 1], _axes[0, 2], _axes[1, 0], _axes[1, 1]):
        _ax.legend(fontsize=8)
    if title is None:
        _title = "Calibration overlay"
    else:
        _title = title
    _fig.suptitle(_title, color=_TEXT_BLACK, fontsize=14)
    _fig.tight_layout()
    _save_figure(_fig, file_path, fname, verbose)
    return _fig


# ---- Per-axis drawers (private; shared by single-panel plotters and the grid) ----

def _draw_timer(ax: Axes,
                block: dict[str, Any],
                *,
                title: str | None = None,
                color: str = _BAR_BLUE,
                label: str | None = None) -> None:
    """Draw the timer panel onto `ax`."""
    _vals = [block.get("min_ns", 0),
             block.get("median_ns", 0),
             block.get("max_ns", 0)]
    _labels = ["min", "median", "max"]
    ax.bar(_labels, _vals, color=color, alpha=0.7, label=label)
    ax.set_ylabel("delta (ns)", color=_TEXT_BLACK)
    if title is None:
        _t = f"Timer resolution (n={block.get('samples_n', 0)})"
    else:
        _t = title
    ax.set_title(_t, color=_TEXT_BLACK)


def _draw_jitter(ax: Axes,
                 block: dict[str, Any],
                 *,
                 title: str | None = None,
                 color: str = _BAR_BLUE,
                 label: str | None = None) -> None:
    """Draw the jitter panel onto `ax`."""
    _vals = [block.get("median_us", 0.0),
             block.get("p95_us", 0.0),
             block.get("p99_us", 0.0)]
    _labels = ["p50", "p95", "p99"]
    _target = block.get("target_us", 0)
    ax.bar(_labels, _vals, color=color, alpha=0.7, label=label)
    if _target > 0:
        ax.axhline(y=_target, color=_TEXT_BLACK, linestyle="--", linewidth=1, label=f"target {_target} us")
    ax.set_ylabel("elapsed (us)", color=_TEXT_BLACK)
    if title is None:
        _t = f"Jitter, target={_target} us"
    else:
        _t = title
    ax.set_title(_t, color=_TEXT_BLACK)


def _draw_loopback(ax: Axes,
                   block: dict[str, Any],
                   *,
                   title: str | None = None,
                   color: str = _BAR_BLUE,
                   label: str | None = None) -> None:
    """Draw the loopback panel onto `ax`."""
    _vals = [block.get("median_us", 0.0),
             block.get("p95_us", 0.0),
             block.get("p99_us", 0.0)]
    _labels = ["p50", "p95", "p99"]
    ax.bar(_labels, _vals, color=color, alpha=0.7, label=label)
    ax.set_ylabel("round-trip (us)", color=_TEXT_BLACK)
    if title is None:
        _t = f"Loopback ({block.get('payload_bytes', 0)} B)"
    else:
        _t = title
    ax.set_title(_t, color=_TEXT_BLACK)


def _draw_handler_scaling(ax: Axes,
                          block: dict[str, Any],
                          *,
                          title: str | None = None,
                          color: str = _BAR_BLUE,
                          label: str | None = None) -> None:
    """Draw the handler-scaling panel onto `ax`."""
    _stats = block.get("stats", {})
    _cs = sorted(int(_k) for _k in _stats.keys())
    _medians = [_stats[str(_c)].get("median_us", 0.0) for _c in _cs]
    _p95 = [_stats[str(_c)].get("p95_us", 0.0) for _c in _cs]
    if _cs:
        ax.plot(_cs, _medians, marker="o", color=color, label=label or "median")
        ax.plot(_cs, _p95, marker="x", color=color, linestyle="--", alpha=0.5)
    ax.set_xlabel("concurrency c", color=_TEXT_BLACK)
    ax.set_ylabel("latency (us)", color=_TEXT_BLACK)
    if title is None:
        _t = "Handler scaling"
    else:
        _t = title
    ax.set_title(_t, color=_TEXT_BLACK)


def _draw_rate_sweep(ax: Axes,
                     block: dict[str, Any],
                     *,
                     title: str | None = None,
                     color: str = _BAR_BLUE,
                     label: str | None = None) -> None:
    """Draw the rate-sweep panel onto `ax`. Twin axis: latency on left, loss% on right."""
    _per = block.get("per_rate", [])
    _rates = [_row.get("rate", 0) for _row in _per]
    _p95 = [_row.get("p95_us", 0.0) for _row in _per]
    _loss = [_row.get("loss_pct", 0.0) for _row in _per]

    if _rates:
        ax.plot(_rates, _p95, marker="o", color=color, label=label or "p95 latency")
    ax.set_xlabel("target rate (req/s)", color=_TEXT_BLACK)
    ax.set_ylabel("p95 latency (us)", color=_TEXT_BLACK)
    if title is None:
        _sat = block.get("saturation_rate")
        if _sat is None:
            _t = "Rate sweep (no saturation)"
        else:
            _t = f"Rate sweep (saturated at {_sat} req/s)"
    else:
        _t = title
    ax.set_title(_t, color=_TEXT_BLACK)

    _ax2 = ax.twinx()
    if _rates:
        _ax2.plot(_rates, _loss, marker="x", color=_BAR_ORANGE, alpha=0.7, label="loss %")
    _ax2.set_ylabel("loss (%)", color=_TEXT_BLACK)


def _draw_verdict(ax: Axes,
                  gate_block: dict[str, Any]) -> None:
    """Draw a text-only verdict panel onto `ax`."""
    ax.axis("off")
    if gate_block.get("passed"):
        _verdict = "PASS"
        _color = _BAR_BLUE
    else:
        _verdict = "FAIL"
        _color = _BAR_ORANGE
    _lines = [f"Gate: {_verdict}",
              f"noise floor: {gate_block.get('noise_floor_pct', '?')} %",
              ""]
    for _name, _check in gate_block.get("checks", {}).items():
        if _check.get("passed"):
            _status = "ok"
        else:
            _status = "fail"
        _lines.append(f"[{_status}] {_name}")
    ax.text(0.05, 0.95, "\n".join(_lines),
            transform=ax.transAxes,
            verticalalignment="top",
            fontsize=10,
            color=_TEXT_BLACK,
            family="monospace")
    ax.set_title("Verdict", color=_color)


def _draw_verdict_overlay(ax: Axes,
                          envelopes: dict[str, dict[str, Any]]) -> None:
    """Draw a stacked verdict block onto `ax`, one short summary per envelope."""
    ax.axis("off")
    _lines: list[str] = []
    for _label, _env in envelopes.items():
        _gate = _env.get("gate", {})
        if _gate.get("passed"):
            _verdict = "PASS"
        else:
            _verdict = "FAIL"
        _lines.append(f"{_label}: {_verdict}")
    ax.text(0.05, 0.95, "\n".join(_lines),
            transform=ax.transAxes,
            verticalalignment="top",
            fontsize=10,
            color=_TEXT_BLACK,
            family="monospace")
    ax.set_title("Verdicts", color=_TEXT_BLACK)


__all__ = [
    "plot_calibration_summary",
    "plot_envelope_overlay",
    "plot_handler_scaling",
    "plot_jitter",
    "plot_loopback",
    "plot_rate_sweep",
    "plot_timer",
]

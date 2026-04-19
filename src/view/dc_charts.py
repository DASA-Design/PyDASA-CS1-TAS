# -*- coding: utf-8 -*-
"""
Module dc_charts.py
===================

Dimensionless-coefficient charts for the CS-01 TAS case study. Sibling
module to `src.view.qn_diagram` -- that one renders queue-network state
(topology, rho/L/W heatmaps, per-metric bars); this one renders the
coefficient cloud (theta, sigma, eta, phi) across a configuration sweep.

Five plotters, ported from `__OLD__/src/notebooks/src/display.py`:

    - `plot_yoly_chart(title, coeff_data, ...)` single-queue 2D grid (theta-sigma, theta-eta, sigma-eta, theta-phi).
    - `plot_system_behaviour(title, subtitle, coeff_data, ...)` single 3D yoly scatter of one queue / system.
    - `plot_arts_distributions(title, coeff_data, ...)` 3x3 grid, per-node 2x2 histograms of theta / sigma / eta / phi.
    - `plot_yoly_arts_behaviour(title, coeff_data, ...)` 3x3 grid, per-node 3D yoly clouds.
    - `plot_yoly_arts_charts(title, coeff_data, ...)` 3x3 grid, per-node 2D planes (4 per node).

*IMPORTANT:* this module reuses `_save_figure` and `_generate_color_map`
from `src.view.qn_diagram` so saving + palette stay identical. Every text
element uses `_TEXT_BLACK = "#010101"` (never pure black) so SVG output is
visible under dark-theme viewers.

# TODO: phase 3b.2 populates the five plotter bodies; this scaffold carries
# the shared constants + helpers + `NotImplementedError` stubs.
"""
# native python modules
from __future__ import annotations

# data types
from typing import Any, Dict, List, Optional, Union

# scientific stack
import matplotlib.pyplot as plt
import numpy as np
from matplotlib.figure import Figure
from matplotlib.ticker import FuncFormatter

# local modules (reused across the view family so the save routine and the
# palette generator stay identical; the `_` prefix in `qn_diagram` is the
# project's module-private marker, not a strict private import guard)
from src.view.qn_diagram import _TEXT_BLACK, _generate_color_map, _save_figure


# ---------------------------------------------------------------------------
# rcParams: ensure every text element in this module honours _TEXT_BLACK and
# every saved figure has a white background regardless of the caller's theme
# ---------------------------------------------------------------------------

plt.rcParams.update({
    "text.color": _TEXT_BLACK,
    "axes.labelcolor": _TEXT_BLACK,
    "axes.edgecolor": _TEXT_BLACK,
    "axes.titlecolor": _TEXT_BLACK,
    "xtick.color": _TEXT_BLACK,
    "ytick.color": _TEXT_BLACK,
    "figure.facecolor": "white",
    "axes.facecolor": "white",
    "savefig.facecolor": "white",
})


# ---------------------------------------------------------------------------
# Shared style constants (2D + 3D)
# ---------------------------------------------------------------------------


# 2D grid style for scatter axes (yoly 2D panels, histograms)
_GRID_STY_2D = dict(alpha=0.5,
                    color=_TEXT_BLACK,
                    linewidth=0.8,
                    linestyle="--")


# 3D grid style: applied by `_style_3d_panes` directly (matplotlib does not
# expose grid kwargs on the 3D axes constructor path)
_GRID_STY_3D = dict(alpha=0.5,
                    color=_TEXT_BLACK,
                    linewidth=0.8)


# bold, project-black label style for axis titles + tick labels
_LBL_STYLE = dict(fontweight="bold", color=_TEXT_BLACK)


# overall figure title (reused across meta-grid plotters)
_TITLE_STYLE = dict(fontsize=14, fontweight="bold", pad=20)


# 2D tick style (yoly 2D panels, histograms)
_TICK_STYLE = dict(colors=_TEXT_BLACK, which="both", labelsize=11)


# 3D tick / label variants -- "GRID" inside a 3x3 meta-grid (smaller font),
# "SINGLE" for a standalone figure (larger font)
_TICK_STY_3D_GRID = dict(colors=_TEXT_BLACK, which="both", labelsize=10, pad=8)
_TICK_STY_3D_SINGLE = dict(colors=_TEXT_BLACK, which="both", labelsize=11, pad=10)

_LBL_STY_3D_GRID = dict(fontsize=13,
                        labelpad=22,
                        fontweight="bold",
                        color=_TEXT_BLACK)
_LBL_STY_3D_SINGLE = dict(fontsize=15,
                          labelpad=24,
                          fontweight="bold",
                          color=_TEXT_BLACK)

_LBL_STY_2D_GRID = dict(fontsize=12,
                        labelpad=12,
                        fontweight="bold",
                        color=_TEXT_BLACK)
_LBL_STY_2D_SINGLE = dict(fontsize=15,
                          labelpad=14,
                          fontweight="bold",
                          color=_TEXT_BLACK)


# styling for the per-point `K` annotation on yoly endpoints (3D vs 2D)
_K_LBL_STY_3D = dict(fontsize=14,
                     color=_TEXT_BLACK,
                     fontweight="bold",
                     alpha=0.95,
                     ha="center",
                     va="bottom")

_K_LBL_STY_2D = dict(fontsize=12,
                     color=_TEXT_BLACK,
                     fontweight="bold",
                     alpha=0.9,
                     ha="center",
                     va="bottom")


# bounding-box around K annotations (semi-transparent rounded rectangle)
_K_BBOX = dict(facecolor="white",
               edgecolor="gray",
               alpha=0.8,
               pad=1.5,
               boxstyle="round,pad=0.2")


# ---------------------------------------------------------------------------
# Private helpers (ported from __OLD__/src/notebooks/src/display.py)
# ---------------------------------------------------------------------------


def _sci_tick_fmt(x: float, sig: int = 2) -> str:
    """*_sci_tick_fmt()* formats `x` in scientific notation with `sig` significant figures.

    Args:
        x (float): the tick value.
        sig (int): number of significant figures. Defaults to `2`.

    Returns:
        str: formatted string (`"0"` when `x == 0`, else e-notation like `"3.4e-02"`).
    """
    # anchor zero so `"0.0e+00"` does not clutter axes that include the origin
    if x == 0:
        return "0"

    _decimals = max(sig - 1, 0)
    return f"{x:.{_decimals}e}"


def _style_3d_panes(ax: Any) -> None:
    """*_style_3d_panes()* harmonises the look of the three panes of a matplotlib 3D axes.

    Sets the pane facecolor to whitesmoke, the edge to project-black, and
    forces the 3D grid colour + linestyle to match the 2D convention so
    saved figures render identically across 2D and 3D panels.

    Args:
        ax (Any): matplotlib 3D axes object.
    """
    # one pass over the three axis objects; each owns its own pane + grid
    for _axis in (ax.xaxis, ax.yaxis, ax.zaxis):
        _axis.pane.set_facecolor("whitesmoke")
        _axis.pane.set_edgecolor(_TEXT_BLACK)
        _axis._axinfo["grid"]["color"] = _TEXT_BLACK
        _axis._axinfo["grid"]["linewidth"] = 0.8
        _axis._axinfo["grid"]["linestyle"] = "--"


def _apply_sci_format(ax: Any,
                      *,
                      axes_list: Optional[List[str]] = None,
                      sig: int = 2) -> None:
    """*_apply_sci_format()* applies a scientific-notation tick formatter to selected axes.

    Args:
        ax (Any): matplotlib axes (2D or 3D).
        axes_list (Optional[List[str]]): which axes to format. Defaults to `["x", "y"]`; pass `["x", "y", "z"]` for 3D.
        sig (int): significant figures passed through to `_sci_tick_fmt`. Defaults to `2`.
    """
    # default axes list covers 2D plots; 3D callers pass ["x", "y", "z"]
    _axes = axes_list if axes_list is not None else ["x", "y"]

    # one formatter per axis; the lambda snapshots `sig` via default arg so
    # callers in a loop do not all share the last-seen value
    for _axis_name in _axes:
        _fmt = FuncFormatter(lambda x, _, s=sig: _sci_tick_fmt(x, s))
        getattr(ax, f"{_axis_name}axis").set_major_formatter(_fmt)


def _apply_logscale(ax: Any,
                    logscale: Union[bool, List[bool]],
                    *,
                    axes_list: Optional[List[str]] = None) -> None:
    """*_apply_logscale()* toggles log scale on selected axes from a bool or per-axis list.

    Args:
        ax (Any): matplotlib axes (2D or 3D).
        logscale (Union[bool, List[bool]]): `True` to log every axis in `axes_list`; a list of bools to set each axis independently. Extra entries beyond `len(axes_list)` are ignored.
        axes_list (Optional[List[str]]): which axes to consider. Defaults to `["x", "y"]`; pass `["x", "y", "z"]` for 3D.
    """
    # default axes list covers 2D plots; 3D callers pass ["x", "y", "z"]
    _axes = axes_list if axes_list is not None else ["x", "y"]

    # normalise the bool / list input to a parallel list of flags
    if isinstance(logscale, bool):
        _flags = [logscale] * len(_axes)
    else:
        _flags = list(logscale)

    # apply the per-axis flag; scikit-learn-style `set_xscale("log")` etc.
    for _axis_name, _flag in zip(_axes, _flags):
        if _flag:
            getattr(ax, f"set_{_axis_name}scale")("log")


def _get_path_params(data: Dict[str, Any], path_tag: str) -> str:
    """*_get_path_params()* builds a legend label summarising `c` and `mu` values for one path in a multi-path coefficient dict.

    Args:
        data (Dict[str, Any]): coefficient dict (nested: top-level keys are per-path symbols like `c_{<tag>}` / `\\mu_{<tag>}`).
        path_tag (str): the path subscript (e.g. `"R"` for read-path, `"W"` for write-path).

    Returns:
        str: label like `"c=1,2,4, mu=900,1800"`. Empty string if neither key is populated.
    """
    # look up the per-path arrays; missing keys yield empty arrays, not errors
    _c_key = f"c_{{{path_tag}}}"
    _mu_key = f"\\mu_{{{path_tag}}}"
    _c_vals = np.array(data.get(_c_key, []))
    _mu_vals = np.array(data.get(_mu_key, []))

    # build the label piece-wise so empty categories are omitted cleanly
    _parts: List[str] = []

    if len(_c_vals) > 0:
        _uniq_c = np.unique(_c_vals)
        _c_str = ", ".join(str(int(_v)) for _v in _uniq_c)
        _parts.append(f"c={_c_str}")

    if len(_mu_vals) > 0:
        _uniq_mu = np.unique(_mu_vals)
        _mu_str = ", ".join(str(int(_v)) for _v in _uniq_mu)
        _parts.append(f"mu={_mu_str}")

    return ", ".join(_parts)


def _generate_marker_map(uniq_vals: Union[List[Any], np.ndarray]) -> Dict[Any, str]:
    """*_generate_marker_map()* assigns a matplotlib marker shape to each unique value, cycling through a 14-shape palette.

    Args:
        uniq_vals (Union[List[Any], np.ndarray]): the distinct values to map.

    Returns:
        Dict[Any, str]: `{value: marker}` in the sorted order of `uniq_vals`.
    """
    # 14-shape rotation (sufficient for any plausible CS-01 sweep cardinality)
    _markers = ["o", "s", "^", "v", "<", ">", "D",
                "p", "*", "h", "+", "x", "|", "_"]

    # sort the unique values so the marker assignment is deterministic
    return {_v: _markers[_i % len(_markers)]
            for _i, _v in enumerate(sorted(uniq_vals))}


# ---------------------------------------------------------------------------
# Public plotters: stubs only in Phase 3b.1; bodies land in Phase 3b.2
# ---------------------------------------------------------------------------


def plot_yoly_chart(coeff_data: Dict[str, Any],
                    *,
                    labels: Optional[Dict[str, str]] = None,
                    paths: Optional[Dict[str, str]] = None,
                    logscale: Union[bool, List[bool]] = False,
                    title: Optional[str] = None,
                    file_path: Optional[str] = None,
                    fname: Optional[str] = None,
                    verbose: bool = False) -> Figure:
    """*plot_yoly_chart()* single-queue 2D yoly diagram: 2x2 grid of coefficient planes (theta-sigma, theta-eta, sigma-eta, theta-phi).

    STUB. Body lands in Phase 3b.2.

    Raises:
        NotImplementedError: always (scaffolding only).
    """
    raise NotImplementedError("plot_yoly_chart: body not yet implemented (Phase 3b.2)")


def plot_system_behaviour(coeff_data: Dict[str, Any],
                          *,
                          labels: Optional[Dict[str, str]] = None,
                          paths: Optional[Dict[str, str]] = None,
                          logscale: Union[bool, List[bool]] = False,
                          title: Optional[str] = None,
                          subtitle: Optional[str] = None,
                          file_path: Optional[str] = None,
                          fname: Optional[str] = None,
                          verbose: bool = False) -> Figure:
    """*plot_system_behaviour()* single 3D yoly scatter of one queue or one whole-system coefficient cloud (theta x sigma x eta, coloured by (c, mu)).

    STUB. Body lands in Phase 3b.2.

    Raises:
        NotImplementedError: always (scaffolding only).
    """
    raise NotImplementedError("plot_system_behaviour: body not yet implemented (Phase 3b.2)")


def plot_arts_distributions(coeff_data: Dict[str, Dict[str, Any]],
                            *,
                            labels: Optional[Dict[str, str]] = None,
                            title: Optional[str] = None,
                            file_path: Optional[str] = None,
                            fname: Optional[str] = None,
                            verbose: bool = False) -> Figure:
    """*plot_arts_distributions()* 3x3 grid of per-node coefficient distributions (4 histograms per node: theta, sigma, eta, phi, with mean lines).

    STUB. Body lands in Phase 3b.2.

    Raises:
        NotImplementedError: always (scaffolding only).
    """
    raise NotImplementedError("plot_arts_distributions: body not yet implemented (Phase 3b.2)")


def plot_yoly_arts_behaviour(coeff_data: Dict[str, Dict[str, Any]],
                             *,
                             labels: Optional[Dict[str, str]] = None,
                             paths: Optional[Dict[str, str]] = None,
                             logscale: Union[bool, List[bool]] = False,
                             title: Optional[str] = None,
                             file_path: Optional[str] = None,
                             fname: Optional[str] = None,
                             verbose: bool = False) -> Figure:
    """*plot_yoly_arts_behaviour()* 3x3 grid of per-node 3D yoly clouds (theta x sigma x eta, coloured by (c, mu), with K-endpoint annotations).

    STUB. Body lands in Phase 3b.2.

    Raises:
        NotImplementedError: always (scaffolding only).
    """
    raise NotImplementedError("plot_yoly_arts_behaviour: body not yet implemented (Phase 3b.2)")


def plot_yoly_arts_charts(coeff_data: Dict[str, Dict[str, Any]],
                          *,
                          labels: Optional[Dict[str, str]] = None,
                          paths: Optional[Dict[str, str]] = None,
                          logscale: Union[bool, List[bool]] = False,
                          title: Optional[str] = None,
                          file_path: Optional[str] = None,
                          fname: Optional[str] = None,
                          verbose: bool = False) -> Figure:
    """*plot_yoly_arts_charts()* 3x3 grid of per-node 2D yoly planes (4 planes per node: theta-sigma, theta-eta, sigma-eta, theta-phi).

    STUB. Body lands in Phase 3b.2.

    Raises:
        NotImplementedError: always (scaffolding only).
    """
    raise NotImplementedError("plot_yoly_arts_charts: body not yet implemented (Phase 3b.2)")

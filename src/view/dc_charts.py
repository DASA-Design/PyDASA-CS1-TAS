# -*- coding: utf-8 -*-
"""
Module dc_charts.py
===================

Dimensionless-coefficient charts for the CS-01 TAS case study. Sibling module to `src.view.qn_diagram`; the latter renders queue-network state (topology, rho/L/W heatmaps, per-metric bars), this one renders the coefficient cloud (theta, sigma, eta, phi) across a configuration sweep.

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

# TODO (phase 3b.2): populate the remaining plotter bodies; scaffold carries shared constants + helpers + stubs.
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

# shared view helpers (save + palette kept identical across qn_diagram + dc_charts)
from src.view.qn_diagram import _TEXT_BLACK, _generate_color_map, _save_figure


# ---------------------------------------------------------------------------
# rcParams: near-black text + white canvas so SVG survives dark-theme previews
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


# 3D grid style; applied by `_style_3d_panes` (matplotlib 3D axes has no grid kwargs)
_GRID_STY_3D = dict(alpha=0.5,
                    color=_TEXT_BLACK,
                    linewidth=0.8)


# bold, project-black label style for axis titles + tick labels
_LBL_STYLE = dict(fontweight="bold", color=_TEXT_BLACK)


# overall figure title (reused across meta-grid plotters)
_TITLE_STYLE = dict(fontsize=14, fontweight="bold", pad=20)


# 2D tick style (yoly 2D panels, histograms)
_TICK_STYLE = dict(colors=_TEXT_BLACK, which="both", labelsize=11)


# 3D tick / label variants; "GRID" for 3x3 meta-grids (smaller), "SINGLE" for standalone figures (larger)
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
    # 2D default; 3D callers pass ["x", "y", "z"]
    if axes_list is not None:
        _axes = axes_list
    else:
        _axes = ["x", "y"]

    # lambda snapshots `sig` via default arg so loop callers don't share the last value
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
    # 2D default; 3D callers pass ["x", "y", "z"]
    if axes_list is not None:
        _axes = axes_list
    else:
        _axes = ["x", "y"]

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


def _find_key(data: Dict[str, Any], starts_with: str) -> str:
    """*_find_key()* returns the first key in `data` that starts with `starts_with`.

    Lets yoly plotters look up coefficient arrays by semantic prefix (`"\\theta"`, `"c_"`, etc.) without knowing the artifact subscript in advance.

    Args:
        data (Dict[str, Any]): coefficient / sweep dict.
        starts_with (str): required key prefix.

    Raises:
        KeyError: If no key matches the prefix.

    Returns:
        str: the matched key.
    """
    # first-match; deterministic only if the caller has a deterministic dict order
    for _k in data.keys():
        if _k.startswith(starts_with):
            return _k

    _msg = f"no key in data starts with {starts_with!r}"
    raise KeyError(_msg)


# ---------------------------------------------------------------------------
# Default coefficient labels (math-mode wrapped so mathtext renders symbols)
# ---------------------------------------------------------------------------


_DEFAULT_LABELS: Dict[str, str] = {
    "theta": r"Occupancy ($\boldsymbol{\theta}$)",
    "sigma": r"Stall ($\boldsymbol{\sigma}$)",
    "eta": r"Effective-Yield ($\boldsymbol{\eta}$)",
    "phi": r"Memory-Use ($\boldsymbol{\phi}$)",
}


# the 4 panels of a single-queue 2D yoly chart, ordered (panel_title, x_key, y_key)
_YOLY_PANELS = [
    (r"Plane: $\boldsymbol{\theta}$ vs $\boldsymbol{\sigma}$", "theta", "sigma"),
    (r"Plane: $\boldsymbol{\theta}$ vs $\boldsymbol{\eta}$", "theta", "eta"),
    (r"Plane: $\boldsymbol{\sigma}$ vs $\boldsymbol{\eta}$", "sigma", "eta"),
    (r"Plane: $\boldsymbol{\theta}$ vs $\boldsymbol{\phi}$", "theta", "phi"),
]


# ---------------------------------------------------------------------------
# public plotters; `plot_yoly_chart` is done, the other four stay NotImplementedError stubs
# ---------------------------------------------------------------------------


def _panel_single_mode(ax: Any,
                       coeff_data: Dict[str, Any],
                       x_key: str,
                       y_key: str) -> bool:
    """*_panel_single_mode()* populates one 2D panel in single-queue mode (colour by `c`, marker by `mu`).

    Args:
        ax (Any): matplotlib 2D axes to populate.
        coeff_data (Dict[str, Any]): single-queue sweep dict; keys use artifact-subscript form (`\\theta_{X}`, `c_{X}`, `\\mu_{X}`, `K_{X}`, ...).
        x_key (str): short coefficient name for the x-axis (`"theta"`, `"sigma"`).
        y_key (str): short coefficient name for the y-axis.

    Returns:
        bool: True when at least one label was registered (caller adds a legend).
    """
    # locate the coefficient / control arrays by semantic prefix
    _x_full = _find_key(coeff_data, f"\\{x_key}")
    _y_full = _find_key(coeff_data, f"\\{y_key}")
    _c_full = _find_key(coeff_data, "c_")
    _mu_full = _find_key(coeff_data, "\\mu")
    _K_full = _find_key(coeff_data, "K_")

    _x = np.asarray(coeff_data[_x_full], dtype=float)
    _y = np.asarray(coeff_data[_y_full], dtype=float)
    _c = np.asarray(coeff_data[_c_full], dtype=float)
    _mu = np.asarray(coeff_data[_mu_full], dtype=float)
    _K = np.asarray(coeff_data[_K_full], dtype=float)

    _uniq_c = np.unique(_c)
    _uniq_mu = np.unique(_mu)
    _uniq_K = np.unique(_K)

    # wrap qn_diagram's list return as a dict for .get(c_val, default) lookups
    _sorted_c = _uniq_c.tolist()
    _cmap = dict(zip(_sorted_c, _generate_color_map(_sorted_c)))
    _mmap = _generate_marker_map(_uniq_mu.tolist())

    # y-range scaled offset for K-endpoint annotations
    if len(_y) > 0:
        _y_range = float(_y.max() - _y.min())
    else:
        _y_range = 1.0
    _y_off = _y_range * 0.04

    # track which (c, mu) combos + K values have been labelled to avoid duplicates
    _seen_combos: set = set()
    _seen_K: set = set()

    # cartesian over (c, mu, K); each combination becomes one scatter call
    for _c_val in _uniq_c:
        for _mu_val in _uniq_mu:
            for _K_val in _uniq_K:
                # intermediate boolean arrays so the mask avoids multi-line binary ops
                _c_hit = np.abs(_c - _c_val) < 0.1
                _mu_hit = np.abs(_mu - _mu_val) < 0.1
                _K_hit = np.abs(_K - _K_val) < 0.1
                _mask = _c_hit & _mu_hit & _K_hit
                if not np.any(_mask):
                    continue

                # first (c, mu) combo gets the legend label, subsequent K values skip it
                _combo = (_c_val, _mu_val)
                _label = None
                if _combo not in _seen_combos:
                    _label = f"c={int(_c_val)}, mu={int(_mu_val)}"
                    _seen_combos.add(_combo)

                ax.scatter(_x[_mask], _y[_mask],
                           c=_cmap.get(_c_val, _TEXT_BLACK),
                           marker=_mmap.get(_mu_val, "o"),
                           s=40, alpha=0.6,
                           edgecolors=_TEXT_BLACK, linewidths=0.2,
                           label=_label, rasterized=True)

                # annotate one K-endpoint per K value (first occurrence only)
                if _K_val not in _seen_K:
                    _idxs = np.where(_mask)[0]
                    if len(_idxs) > 0:
                        _end = _idxs[-1]
                        ax.text(float(_x[_end]),
                                float(_y[_end]) + _y_off,
                                f"K={int(_K_val)}",
                                bbox=_K_BBOX,
                                **_K_LBL_STY_2D)
                        _seen_K.add(_K_val)

    return len(_seen_combos) > 0


def _panel_multi_path(ax: Any,
                      coeff_data: Dict[str, Any],
                      x_key: str,
                      y_key: str,
                      paths: Dict[str, str]) -> bool:
    """*_panel_multi_path()* populates one 2D panel in multi-path mode (colour + marker per path).

    Args:
        ax (Any): matplotlib 2D axes to populate.
        coeff_data (Dict[str, Any]): sweep dict carrying per-path arrays keyed by `\\<coef>_{<path_tag>}`.
        x_key (str): short coefficient name for the x-axis.
        y_key (str): short coefficient name for the y-axis.
        paths (Dict[str, str]): `{display_name: path_tag}` map (e.g. `{"Read": "R_{PACS}", "Write": "W_{PACS}"}`).

    Returns:
        bool: True when at least one label was registered.
    """
    # consistent colour + marker per path name across every panel
    _path_names = sorted(paths.keys())
    _cmap = dict(zip(_path_names, _generate_color_map(_path_names)))
    _mmap = _generate_marker_map(_path_names)

    _has_label = False
    _seen_K: set = set()

    for _name, _tag in paths.items():
        _x = np.asarray(coeff_data.get(f"\\{x_key}_{{{_tag}}}", []), dtype=float)
        _y = np.asarray(coeff_data.get(f"\\{y_key}_{{{_tag}}}", []), dtype=float)
        _K = np.asarray(coeff_data.get(f"K_{{{_tag}}}", []), dtype=float)

        if len(_x) == 0 or len(_y) == 0:
            continue

        # path legend label carries the (c, mu) summary for the path
        _params = _get_path_params(coeff_data, _tag)
        if _params:
            _path_lbl = f"{_name} ({_params})"
        else:
            _path_lbl = _name

        # y-range scaled offset for K-endpoint annotations
        if len(_y) > 0:
            _y_range = float(_y.max() - _y.min())
        else:
            _y_range = 1.0
        _y_off = _y_range * 0.04

        # split the path into K slices so we can annotate endpoints
        if len(_K) > 0:
            _uniq_K = np.unique(_K)
        else:
            _uniq_K = np.array([])
        if len(_uniq_K) > 0:
            _K_ends = {_uniq_K[0], _uniq_K[-1]}
        else:
            _K_ends = set()
        _first_slice = True

        if len(_uniq_K) > 0:
            for _K_val in _uniq_K:
                _mask = np.abs(_K - _K_val) < 0.1
                if not np.any(_mask):
                    continue

                # legend label only on the first slice so the entry is unique
                if _first_slice:
                    _label = _path_lbl
                else:
                    _label = None
                _first_slice = False

                ax.scatter(_x[_mask], _y[_mask],
                           c=_cmap.get(_name, _TEXT_BLACK),
                           marker=_mmap.get(_name, "o"),
                           s=40, alpha=0.6,
                           edgecolors=_TEXT_BLACK, linewidths=0.2,
                           label=_label, rasterized=True)

                # annotate K endpoints (first and last K) once per panel
                if _K_val in _K_ends and _K_val not in _seen_K:
                    _idxs = np.where(_mask)[0]
                    if len(_idxs) > 0:
                        _end = _idxs[-1]
                        ax.text(float(_x[_end]),
                                float(_y[_end]) + _y_off,
                                f"K={int(_K_val)}",
                                bbox=_K_BBOX,
                                **_K_LBL_STY_2D)
                        _seen_K.add(_K_val)
        else:
            # no K column: single scatter group for the whole path
            ax.scatter(_x, _y,
                       c=_cmap.get(_name, _TEXT_BLACK),
                       marker=_mmap.get(_name, "o"),
                       s=40, alpha=0.6,
                       edgecolors=_TEXT_BLACK, linewidths=0.2,
                       label=_path_lbl, rasterized=True)

        _has_label = True

    return _has_label


def _resolve_groups(paths: Optional[Dict[str, str]],
                    scenarios: Optional[Dict[str, str]]) -> tuple[Optional[Dict[str, str]], str]:
    """*_resolve_groups()* chooses between the `paths=` (PACS idiom) and `scenarios=` (TAS idiom) kwargs.

    Both kwargs drive the same plotter behaviour (one colour + marker per
    named group) but live under different names so each case study reads in
    its own vocabulary:

    - PACS: `paths={"Read": "R_{PACS}", "Write": "W_{PACS}"}`
    - CS-01 TAS: `scenarios={"Before": "baseline_{TAS_{1}}", "After": "aggregate_{TAS_{1}}"}`

    Args:
        paths (Optional[Dict[str, str]]): PACS-idiom grouping.
        scenarios (Optional[Dict[str, str]]): TAS-idiom grouping.

    Raises:
        ValueError: If both kwargs are non-None.

    Returns:
        tuple[Optional[Dict[str, str]], str]: `(groups, legend_title)`; `groups` is the chosen dict (or None for single-mode) and `legend_title` is the label to use on the panel legend.
    """
    # mutual exclusion: only one vocabulary at a time
    if paths is not None and scenarios is not None:
        _msg = ("plot_yoly_chart: pass `paths=` OR `scenarios=`, not both "
                "(they are aliases; pick the one that matches your case-study idiom)")
        raise ValueError(_msg)

    if paths is not None:
        return paths, "Path"
    if scenarios is not None:
        return scenarios, "Scenario"
    return None, "System Configuration"


def plot_yoly_chart(coeff_data: Dict[str, Any],
                    *,
                    labels: Optional[Dict[str, str]] = None,
                    paths: Optional[Dict[str, str]] = None,
                    scenarios: Optional[Dict[str, str]] = None,
                    logscale: Union[bool, List[bool]] = False,
                    title: Optional[str] = None,
                    file_path: Optional[str] = None,
                    fname: Optional[str] = None,
                    verbose: bool = False) -> Figure:
    """*plot_yoly_chart()* single-queue 2D yoly diagram: 2x2 grid of coefficient planes.

    Panels are (theta, sigma), (theta, eta), (sigma, eta), (theta, phi). Three
    rendering modes, selected by the caller's grouping kwarg:

    - **Single-queue** (default, both groupings `None`): looks up theta / sigma / eta / phi / c / mu / K arrays in `coeff_data` by semantic prefix. Each point is coloured by its `c` value and shaped by its `mu` value; K-endpoints get inline annotations.
    - **Multi-path** (`paths=` given, PACS idiom): one colour + marker per named path. Each path carries its own subscripted arrays, e.g. `\\theta_{R_{PACS}}` for the Read path.
    - **Multi-scenario** (`scenarios=` given, TAS idiom): identical logic to multi-path but reads as before/after adaptation. Example: `scenarios={"Before": "baseline_{TAS_{1}}", "After": "aggregate_{TAS_{1}}"}`.

    `paths=` and `scenarios=` are mutually exclusive aliases.

    Args:
        coeff_data (Dict[str, Any]): sweep dict keyed by LaTeX-subscripted symbols.
        labels (Optional[Dict[str, str]]): display labels for the four coefficients, keyed by short name (`"theta"`, `"sigma"`, `"eta"`, `"phi"`). Missing keys fall back to `_DEFAULT_LABELS`.
        paths (Optional[Dict[str, str]]): PACS-idiom grouping (`{display_name: path_tag}`).
        scenarios (Optional[Dict[str, str]]): TAS-idiom grouping; identical semantics to `paths=` but titled "Scenario" in the legend.
        logscale (Union[bool, List[bool]]): if True, log-scale both panel axes; a 2-list selects `[x_log, y_log]` independently.
        title (Optional[str]): figure title.
        file_path (Optional[str]): directory to save into.
        fname (Optional[str]): filename (with extension); `_save_figure` writes both `.png` (300 dpi) and `.svg`.
        verbose (bool): if True, prints one save message per format.

    Raises:
        ValueError: If both `paths=` and `scenarios=` are provided.

    Returns:
        Figure: the matplotlib figure (caller owns lifecycle; `plt.show()` / `plt.close()` not called inside).
    """
    # pick whichever grouping vocabulary the caller supplied (one or neither)
    _groups, _legend_title = _resolve_groups(paths, scenarios)

    # resolved labels for the two axes per panel (short-name lookup; default wins when absent)
    _lbl_map = {**_DEFAULT_LABELS, **(labels or {})}

    # 2x2 grid with generous spacing so legends + K-boxes do not collide
    _fig = plt.figure(figsize=(18, 16), facecolor="white")
    _gs = _fig.add_gridspec(2, 2, hspace=0.25, wspace=0.25)
    _axes = [_fig.add_subplot(_gs[_i, _j]) for _i in range(2) for _j in range(2)]

    # populate each panel; scatter `label=...` is lifted into one figure-level legend later
    _legend_axes: Optional[Any] = None
    for _idx, (_panel_title, _x_key, _y_key) in enumerate(_YOLY_PANELS):
        _ax = _axes[_idx]
        _ax.set_facecolor("white")

        if _groups:
            _has_legend = _panel_multi_path(_ax, coeff_data,
                                            _x_key, _y_key, _groups)
        else:
            _has_legend = _panel_single_mode(_ax, coeff_data, _x_key, _y_key)

        # remember the first axes that produced legend handles
        if _has_legend and _legend_axes is None:
            _legend_axes = _ax

        # cosmetic pass: grid, ticks, spines, sci format, log toggle
        _ax.grid(True, **_GRID_STY_2D)
        _ax.tick_params(**_TICK_STYLE)
        for _spine in _ax.spines.values():
            _spine.set_edgecolor(_TEXT_BLACK)
        # sigma clusters at 1.0 (Little's-law identity); bump precision so ticks don't collapse to "1.0e+00"
        if _x_key != "sigma":
            _x_axes = ["x"]
        else:
            _x_axes = []
        if _y_key != "sigma":
            _y_axes = ["y"]
        else:
            _y_axes = []
        if _x_axes or _y_axes:
            _apply_sci_format(_ax, axes_list=_x_axes + _y_axes)
        _sigma_axes = [_n for _n, _k in (("x", _x_key), ("y", _y_key))
                       if _k == "sigma"]
        if _sigma_axes:
            _apply_sci_format(_ax, axes_list=_sigma_axes, sig=4)
        _apply_logscale(_ax, logscale)

        # axis + panel titles from the resolved label map
        _ax.set_xlabel(_lbl_map[_x_key], **_LBL_STY_2D_SINGLE)
        _ax.set_ylabel(_lbl_map[_y_key], **_LBL_STY_2D_SINGLE)
        _ax.set_title(_panel_title, fontsize=17, pad=-10, **_LBL_STYLE)

    # one figure-level legend along the bottom strip reserved by subplots_adjust
    if _legend_axes is not None:
        _handles, _labels = _legend_axes.get_legend_handles_labels()
        _fig.subplots_adjust(bottom=0.10, right=0.97)
        _fig.legend(_handles, _labels,
                    loc="lower center",
                    bbox_to_anchor=(0.5, 0.01),
                    ncol=min(len(_labels), 8),
                    fontsize=12,
                    framealpha=0.9,
                    title=_legend_title,
                    title_fontsize=13)

    # figure title bound above the top row (y=0.995 per OLD convention)
    if title:
        _fig.suptitle(title, fontsize=25, y=0.995, **_LBL_STYLE)

    # persist via the shared saver (PNG + SVG in one call)
    _save_figure(_fig, file_path, fname, verbose)
    return _fig


def _panel_3d_single(ax: Any, coeff_data: Dict[str, Any]) -> bool:
    """*_panel_3d_single()* populates one 3D axes in single-queue mode (colour by `c`, marker by `mu`).

    Args:
        ax (Any): matplotlib 3D axes.
        coeff_data (Dict[str, Any]): single-queue sweep dict (same shape as `_panel_single_mode`).

    Returns:
        bool: True when at least one (c, mu) combo was plotted.
    """
    # semantic-prefix lookup so the caller need not know the artifact subscript
    _theta = np.asarray(coeff_data[_find_key(coeff_data, "\\theta")], dtype=float)
    _sigma = np.asarray(coeff_data[_find_key(coeff_data, "\\sigma")], dtype=float)
    _eta = np.asarray(coeff_data[_find_key(coeff_data, "\\eta")], dtype=float)
    _c = np.asarray(coeff_data[_find_key(coeff_data, "c_")], dtype=float)
    _mu = np.asarray(coeff_data[_find_key(coeff_data, "\\mu")], dtype=float)
    _K = np.asarray(coeff_data[_find_key(coeff_data, "K_")], dtype=float)

    _uniq_c = np.unique(_c)
    _uniq_mu = np.unique(_mu)
    _uniq_K = np.unique(_K)

    # qn_diagram helper returns a List in input order; wrap in a dict
    _sorted_c = _uniq_c.tolist()
    _cmap = dict(zip(_sorted_c, _generate_color_map(_sorted_c)))
    _mmap = _generate_marker_map(_uniq_mu.tolist())

    # z-range scaled offset for K-endpoint annotations (eta axis)
    if len(_eta) > 0:
        _z_range = float(_eta.max() - _eta.min())
    else:
        _z_range = 1.0
    _z_off = _z_range * 0.05

    _seen_combos: set = set()
    _seen_K: set = set()

    for _c_val in _uniq_c:
        for _mu_val in _uniq_mu:
            for _K_val in _uniq_K:
                # intermediate booleans so the mask avoids multi-line binary ops
                _c_hit = np.abs(_c - _c_val) < 0.1
                _mu_hit = np.abs(_mu - _mu_val) < 0.1
                _K_hit = np.abs(_K - _K_val) < 0.1
                _mask = _c_hit & _mu_hit & _K_hit
                if not np.any(_mask):
                    continue

                # first (c, mu) combo gets the legend label
                _combo = (_c_val, _mu_val)
                _label = None
                if _combo not in _seen_combos:
                    _label = f"c={int(_c_val)}, mu={int(_mu_val)}"
                    _seen_combos.add(_combo)

                ax.scatter(_theta[_mask], _sigma[_mask], _eta[_mask],
                           c=_cmap.get(_c_val, _TEXT_BLACK),
                           marker=_mmap.get(_mu_val, "o"),
                           s=20, alpha=0.6,
                           edgecolors=_TEXT_BLACK, linewidths=0.1,
                           label=_label, rasterized=True)

                # annotate one K-endpoint per K value (first occurrence only)
                if _K_val not in _seen_K:
                    _idxs = np.where(_mask)[0]
                    if len(_idxs) > 0:
                        _end = _idxs[-1]
                        ax.text(float(_theta[_end]),
                                float(_sigma[_end]),
                                float(_eta[_end]) + _z_off,
                                f"K={int(_K_val)}",
                                bbox=_K_BBOX,
                                **_K_LBL_STY_3D)
                        _seen_K.add(_K_val)

    return len(_seen_combos) > 0


def _panel_3d_groups(ax: Any,
                     coeff_data: Dict[str, Any],
                     groups: Dict[str, str]) -> bool:
    """*_panel_3d_groups()* populates one 3D axes in grouped mode (paths or scenarios).

    Args:
        ax (Any): matplotlib 3D axes.
        coeff_data (Dict[str, Any]): sweep dict with per-group arrays keyed by `\\<coef>_{<tag>}`.
        groups (Dict[str, str]): `{display_name: tag}` map (paths or scenarios).

    Returns:
        bool: True when at least one group produced a labelled scatter.
    """
    # consistent colour + marker per group name
    _names = sorted(groups.keys())
    _cmap = dict(zip(_names, _generate_color_map(_names)))
    _mmap = _generate_marker_map(_names)

    _has_label = False
    _seen_K: set = set()

    # single z-range for annotation offset, drawn from whichever groups have data
    _all_eta: List[float] = []
    for _tag in groups.values():
        _eta_arr = coeff_data.get(f"\\eta_{{{_tag}}}", [])
        _all_eta.extend(np.asarray(_eta_arr, dtype=float).tolist())
    if len(_all_eta) > 1:
        _z_range = max(_all_eta) - min(_all_eta)
    else:
        _z_range = 1.0
    _z_off = _z_range * 0.05

    for _name, _tag in groups.items():
        _theta = np.asarray(coeff_data.get(f"\\theta_{{{_tag}}}", []), dtype=float)
        _sigma = np.asarray(coeff_data.get(f"\\sigma_{{{_tag}}}", []), dtype=float)
        _eta = np.asarray(coeff_data.get(f"\\eta_{{{_tag}}}", []), dtype=float)
        _K = np.asarray(coeff_data.get(f"K_{{{_tag}}}", []), dtype=float)

        if len(_theta) == 0 or len(_sigma) == 0 or len(_eta) == 0:
            continue

        # legend label carries the (c, mu) summary for the group
        _params = _get_path_params(coeff_data, _tag)
        if _params:
            _group_lbl = f"{_name} ({_params})"
        else:
            _group_lbl = _name

        if len(_K) > 0:
            _uniq_K = np.unique(_K)
        else:
            _uniq_K = np.array([])
        if len(_uniq_K) > 0:
            _K_ends = {_uniq_K[0], _uniq_K[-1]}
        else:
            _K_ends = set()
        _first_slice = True

        if len(_uniq_K) > 0:
            for _K_val in _uniq_K:
                _mask = np.abs(_K - _K_val) < 0.1
                if not np.any(_mask):
                    continue

                if _first_slice:
                    _label = _group_lbl
                else:
                    _label = None
                _first_slice = False

                ax.scatter(_theta[_mask], _sigma[_mask], _eta[_mask],
                           c=_cmap.get(_name, _TEXT_BLACK),
                           marker=_mmap.get(_name, "o"),
                           s=20, alpha=0.6,
                           edgecolors=_TEXT_BLACK, linewidths=0.1,
                           label=_label, rasterized=True)

                # annotate K endpoints (first + last) once per axes
                if _K_val in _K_ends and _K_val not in _seen_K:
                    _idxs = np.where(_mask)[0]
                    if len(_idxs) > 0:
                        _end = _idxs[-1]
                        ax.text(float(_theta[_end]),
                                float(_sigma[_end]),
                                float(_eta[_end]) + _z_off,
                                f"K={int(_K_val)}",
                                bbox=_K_BBOX,
                                **_K_LBL_STY_3D)
                        _seen_K.add(_K_val)
        else:
            # no K column: single scatter for the whole group
            ax.scatter(_theta, _sigma, _eta,
                       c=_cmap.get(_name, _TEXT_BLACK),
                       marker=_mmap.get(_name, "o"),
                       s=20, alpha=0.6,
                       edgecolors=_TEXT_BLACK, linewidths=0.1,
                       label=_group_lbl, rasterized=True)

        _has_label = True

    return _has_label


def plot_system_behaviour(coeff_data: Dict[str, Any],
                          *,
                          labels: Optional[Dict[str, str]] = None,
                          paths: Optional[Dict[str, str]] = None,
                          scenarios: Optional[Dict[str, str]] = None,
                          logscale: Union[bool, List[bool]] = False,
                          title: Optional[str] = None,
                          subtitle: Optional[str] = None,
                          file_path: Optional[str] = None,
                          fname: Optional[str] = None,
                          verbose: bool = False) -> Figure:
    """*plot_system_behaviour()* single 3D yoly scatter of one artifact / system coefficient cloud (theta, sigma, eta).

    Three rendering modes share the 3D axes:

    - **Single-queue** (both groupings `None`): colour by `c`, marker by `mu`, K-endpoints annotated.
    - **Multi-path** (`paths=`, PACS idiom): one colour + marker per named path.
    - **Multi-scenario** (`scenarios=`, TAS idiom): one colour + marker per named adaptation (before / after, etc.). Mutually exclusive with `paths=`.

    Args:
        coeff_data (Dict[str, Any]): sweep dict keyed by LaTeX-subscripted symbols.
        labels (Optional[Dict[str, str]]): display labels for the three axes, keyed by short name (`"theta"`, `"sigma"`, `"eta"`). Missing keys fall back to `_DEFAULT_LABELS`.
        paths (Optional[Dict[str, str]]): PACS-idiom grouping.
        scenarios (Optional[Dict[str, str]]): TAS-idiom grouping (aliases `paths=`).
        logscale (Union[bool, List[bool]]): bool toggles log scale on all three axes; 3-list selects `[x_log, y_log, z_log]`.
        title (Optional[str]): figure-wide title (fontsize 19).
        subtitle (Optional[str]): axes-level subtitle (fontsize 17).
        file_path (Optional[str]): directory to save into.
        fname (Optional[str]): filename (with extension); `_save_figure` writes both `.png` (300 dpi) and `.svg`.
        verbose (bool): if True, prints one save message per format.

    Raises:
        ValueError: If both `paths=` and `scenarios=` are provided.

    Returns:
        Figure: the matplotlib figure.
    """
    # pick grouping vocabulary (paths / scenarios / neither)
    _groups, _legend_title = _resolve_groups(paths, scenarios)

    # resolved axis labels (short-name lookup; default wins when absent)
    _lbl_map = {**_DEFAULT_LABELS, **(labels or {})}

    # single 3D axes on a square-ish canvas
    _fig = plt.figure(figsize=(17, 14), facecolor="white")
    _ax = _fig.add_subplot(111, projection="3d")
    _ax.set_facecolor("white")

    # populate the cloud via the matching mode
    if _groups:
        _has_legend = _panel_3d_groups(_ax, coeff_data, _groups)
    else:
        _has_legend = _panel_3d_single(_ax, coeff_data)

    # axis labels (project conventions: bold, mathtext-aware)
    _ax.set_xlabel(_lbl_map["theta"], **_LBL_STY_3D_SINGLE)
    _ax.set_ylabel(_lbl_map["sigma"], **_LBL_STY_3D_SINGLE)
    _ax.set_zlabel(_lbl_map["eta"], **_LBL_STY_3D_SINGLE)

    # 3D cosmetics: log toggle, pane styling, grid, sci format, ticks
    _apply_logscale(_ax, logscale, axes_list=["x", "y", "z"])
    _ax.view_init(elev=30, azim=110)
    _style_3d_panes(_ax)
    _ax.grid(True, **_GRID_STY_3D)
    _apply_sci_format(_ax, axes_list=["x", "z"])
    # sigma clusters at 1.0 (Little's-law); bump precision so ticks don't collapse to "1.0e+00"
    _apply_sci_format(_ax, axes_list=["y"], sig=4)
    for _axis_name in ("x", "y", "z"):
        _ax.tick_params(axis=_axis_name, **_TICK_STY_3D_SINGLE)

    # axes subtitle (fontsize 17) + figure title (fontsize 19)
    if subtitle:
        _ax.set_title(subtitle, fontsize=17, **_LBL_STYLE)

    if _has_legend:
        _ax.legend(loc="upper left",
                   bbox_to_anchor=(1.05, 0.6),
                   fontsize=12,
                   title=_legend_title,
                   title_fontsize=13,
                   framealpha=0.9)

    if title:
        _fig.suptitle(title, fontsize=19, y=0.95, **_LBL_STYLE)

    # persist via the shared saver (PNG + SVG in one call)
    _save_figure(_fig, file_path, fname, verbose)
    return _fig


def _short_coef_name(full_sym: str) -> Optional[str]:
    """*_short_coef_name()* returns `"theta"` / `"sigma"` / `"eta"` / `"phi"` for a backslash-prefixed coefficient symbol, or `None` when none of the four match.

    Args:
        full_sym (str): full LaTeX symbol (e.g. `\\theta_{TAS_{1}}`).

    Returns:
        Optional[str]: short coefficient name, or `None` if unmatched.
    """
    # match `\<short>` (not bare) so `\eta` doesn't collide with the trailing `eta` in `\theta`
    for _short in ("theta", "sigma", "eta", "phi"):
        if f"\\{_short}" in full_sym:
            return _short
    return None


def _node_coef_map(node_block: Dict[str, Any]) -> Dict[str, str]:
    """*_node_coef_map()* returns `{short_name: full_symbol}` over the four derived coefficients present on one node block.

    Args:
        node_block (Dict[str, Any]): per-node dict (keys are coefficient symbols, values are sweep arrays).

    Returns:
        Dict[str, str]: e.g. `{"theta": "\\theta_{TAS_{1}}", ...}`. Missing coefficients are simply omitted.
    """
    # only match backslash-prefixed symbols so non-coefficient entries are skipped
    _derived = [_k for _k in node_block.keys() if _k.startswith("\\")]

    _coef_map: Dict[str, str] = {}
    for _full in _derived:
        _short = _short_coef_name(_full)
        if _short is not None and _short not in _coef_map:
            _coef_map[_short] = _full

    return _coef_map


def plot_arts_distributions(coeff_data: Dict[str, Dict[str, Any]],
                            *,
                            labels: Optional[Dict[str, str]] = None,
                            names: Optional[Dict[str, str]] = None,
                            title: Optional[str] = None,
                            file_path: Optional[str] = None,
                            fname: Optional[str] = None,
                            verbose: bool = False) -> Figure:
    """*plot_arts_distributions()* per-node coefficient distributions as histograms arranged in a 3x(ceil(N/3)) meta-grid of nodes; each node cell carries a 2x2 subgrid with one histogram per derived coefficient.

    Layout:

    - Outer grid: `3` rows by `ceil(n_nodes / 3)` columns. Short last row is centred.
    - Inner grid per node: `2 x ceil(n_coeffs / 2)` (`2x2` when all four coefficients are present).
    - Each histogram: 50 bins, mean line overlay, title with mean + std, legend with mean value.

    Args:
        coeff_data (Dict[str, Dict[str, Any]]): nested dict `{node_key: {full_symbol: array}}`. Outer keys are artifact identifiers; inner keys are backslash-prefixed coefficient symbols (e.g. `\\theta_{TAS_{1}}`) whose values are 1-D arrays from a configuration sweep.
        labels (Optional[Dict[str, str]]): display labels per short coefficient name (`"theta"`, `"sigma"`, `"eta"`, `"phi"`). Missing keys fall back to `_DEFAULT_LABELS`.
        names (Optional[Dict[str, str]]): display-name override per node key (e.g. `{"TAS_{1}": "Dispatch"}`). Missing keys fall back to the node key itself.
        title (Optional[str]): figure title.
        file_path (Optional[str]): directory to save into.
        fname (Optional[str]): filename (with extension); `_save_figure` writes both `.png` (300 dpi) and `.svg`.
        verbose (bool): if True, prints one save message per format.

    Returns:
        Figure: the matplotlib figure.
    """
    # resolved axis labels + node display names (short-name lookup wins over defaults)
    _lbl_map = {**_DEFAULT_LABELS, **(labels or {})}
    _name_map = names or {}

    # node inventory drives the outer grid shape
    _node_keys = list(coeff_data.keys())
    _n_nodes = len(_node_keys)
    if _n_nodes == 0:
        # empty input: return a bare figure so the caller gets a sensible object
        _fig = plt.figure(figsize=(8, 6), facecolor="white")
        if title:
            _fig.suptitle(title, fontsize=25, y=0.995, **_LBL_STYLE)
        return _fig

    # 3 rows x ceil(N/3) cols (shared with plot_yoly_arts_*)
    _n_rows, _n_cols, _last_row_idx, _n_last_row = _grid_layout(_n_nodes)

    _fig = plt.figure(figsize=(26, 26), facecolor="white")
    # outer-grid hspace leaves room for per-cell headers anchored via `get_position()` later
    _fig.subplots_adjust(top=0.93, bottom=0.04, left=0.06, right=0.97,
                         hspace=0.55, wspace=0.30)
    _gs_main = _fig.add_gridspec(_n_rows, _n_cols,
                                 hspace=0.55,
                                 wspace=0.30,
                                 figure=_fig)

    # walk every node and populate its subgrid
    for _nd_idx, _node in enumerate(_node_keys):
        _nd_row, _nd_col = _node_grid_pos(_nd_idx, _n_rows, _n_cols,
                                          _last_row_idx, _n_last_row)

        _node_block = coeff_data[_node]
        _coef_map = _node_coef_map(_node_block)
        _n_coeffs = len(_coef_map)
        if _n_coeffs == 0:
            continue

        # palette by coefficient index (qn_diagram helper returns List aligned with input)
        _col_lt = _generate_color_map(list(range(_n_coeffs)))

        # inner subgrid: 2 rows x ceil(n_coeffs/2) cols -> 2x2 for the usual 4 coefficients
        _n_inner_cols = (_n_coeffs + 1) // 2
        _gs_node = _gs_main[_nd_row, _nd_col].subgridspec(2, _n_inner_cols,
                                                          hspace=0.45,
                                                          wspace=0.45)

        # anchor header to the gridspec cell top so it never overlaps the inner subgrid title
        _cell_pos = _gs_main[_nd_row, _nd_col].get_position(_fig)
        _title_x = (_cell_pos.x0 + _cell_pos.x1) / 2.0
        _title_y = _cell_pos.y1 + 0.008
        _fig.text(_title_x, _title_y,
                  _node_header(_node, _name_map),
                  ha="center", va="bottom",
                  fontsize=15, fontweight="bold", color=_TEXT_BLACK,
                  transform=_fig.transFigure)

        # populate one histogram per coefficient in declared order
        _short_names = list(_coef_map.keys())
        for _c_idx, _short in enumerate(_short_names):
            _row = _c_idx // _n_inner_cols
            _col = _c_idx % _n_inner_cols

            _ax = _fig.add_subplot(_gs_node[_row, _col])
            _ax.set_facecolor("white")

            _full = _coef_map[_short]
            _data = np.asarray(_node_block[_full], dtype=float)
            _color = _col_lt[_c_idx]

            # 50-bin histogram with dark edge so bars render cleanly against white
            _ax.hist(_data,
                     bins=50,
                     color=_color,
                     alpha=0.7,
                     edgecolor=_TEXT_BLACK)

            # mean reference line with numeric legend entry
            _mean = float(np.mean(_data))
            _std = float(np.std(_data))
            _ax.axvline(_mean,
                        color=_color,
                        linestyle="-",
                        linewidth=2,
                        label=f"Mean: {_mean:.4e}")

            # axis labels + per-axes title (shows mean + std)
            _ax.set_xlabel(_lbl_map.get(_short, _short),
                           fontsize=11, fontweight="bold", color=_TEXT_BLACK)
            _ax.set_ylabel("Frequency",
                           fontsize=11, fontweight="bold", color=_TEXT_BLACK)
            _ax.set_title(f"mean={_mean:.3g}  std={_std:.3g}",
                          fontsize=11, fontweight="bold", color=_TEXT_BLACK,
                          pad=4)

            # cosmetic pass: sci-notation on x, tick style, legend, grid, spines
            _ax.ticklabel_format(axis="x", style="sci", scilimits=(0, 0))
            _ax.tick_params(**_TICK_STYLE)
            _ax.legend(loc="best", fontsize=11, framealpha=0.9)
            _ax.grid(True, alpha=0.8, color=_TEXT_BLACK, linewidth=1.0)
            for _spine in _ax.spines.values():
                _spine.set_edgecolor(_TEXT_BLACK)

    # figure title above every node header
    if title:
        _fig.suptitle(title, fontsize=25, y=0.995, **_LBL_STYLE)

    _save_figure(_fig, file_path, fname, verbose)
    return _fig


def _grid_layout(n_nodes: int, n_rows: int = 3) -> tuple:
    """*_grid_layout()* computes a row-major `(n_rows, n_cols)` grid with last-row centring offsets.

    Args:
        n_nodes (int): number of nodes to lay out.
        n_rows (int): outer-grid row count; column count is `ceil(n_nodes / n_rows)`. Defaults to `3`.

    Returns:
        tuple: `(n_rows, n_cols, last_row_idx, n_last_row)`. `n_last_row` is the count of nodes that land in the final row (== `n_cols` when the grid is full).
    """
    # column count derived from ceiling division so every node has a slot
    _n_cols = (n_nodes + n_rows - 1) // n_rows
    _last_row_idx = n_rows - 1
    _n_last_row = n_nodes - _last_row_idx * _n_cols
    if _n_last_row <= 0:
        _n_last_row = _n_cols
    return n_rows, _n_cols, _last_row_idx, _n_last_row


def _node_grid_pos(nd_idx: int,
                   n_rows: int,
                   n_cols: int,
                   last_row_idx: int,
                   n_last_row: int) -> tuple:
    """*_node_grid_pos()* returns `(row, col)` for the n-th node, applying horizontal centring on a short last row.

    Args:
        nd_idx (int): node index in the outer iteration.
        n_rows (int): outer-grid row count.
        n_cols (int): outer-grid column count.
        last_row_idx (int): row index of the final outer row.
        n_last_row (int): number of nodes that land in the final row.

    Returns:
        tuple: `(row, col)` matplotlib gridspec coordinates.
    """
    _row = nd_idx // n_cols
    _raw_col = nd_idx % n_cols
    if _row == last_row_idx and n_last_row < n_cols:
        _col_offset = (n_cols - n_last_row) // 2
        return _row, _raw_col + _col_offset
    return _row, _raw_col


def _node_header(node_key: str,
                 name_map: Dict[str, str]) -> str:
    """*_node_header()* assembles the per-node header string (mathtext-wrapped node key, with an optional human display name)."""
    _node_math = f"${node_key}$"
    if node_key in name_map:
        return f"{name_map[node_key]} ({_node_math})"
    return _node_math


def plot_yoly_arts_behaviour(coeff_data: Dict[str, Dict[str, Any]],
                             *,
                             labels: Optional[Dict[str, str]] = None,
                             names: Optional[Dict[str, str]] = None,
                             paths: Optional[Dict[str, str]] = None,
                             scenarios: Optional[Dict[str, str]] = None,
                             logscale: Union[bool, List[bool]] = False,
                             title: Optional[str] = None,
                             file_path: Optional[str] = None,
                             fname: Optional[str] = None,
                             verbose: bool = False) -> Figure:
    """*plot_yoly_arts_behaviour()* per-node 3D yoly clouds laid out in a 3x(ceil(N/3)) outer grid.

    Each cell carries a 3D scatter of theta x sigma x eta for one artifact.
    Three rendering modes (single / paths / scenarios) flow through to every
    cell; the same grouping vocabulary applies uniformly across the grid.

    Args:
        coeff_data (Dict[str, Dict[str, Any]]): nested dict `{node_key: {full_symbol: array}}`. Outer keys are artifact identifiers; inner dicts are the per-artifact sweep blocks.
        labels (Optional[Dict[str, str]]): display labels per short coefficient name (`"theta"`, `"sigma"`, `"eta"`). Missing keys fall back to `_DEFAULT_LABELS`.
        names (Optional[Dict[str, str]]): human display-name override per node key (e.g. `{"TAS_{1}": "Dispatch"}`). Missing keys fall back to the node key itself, mathtext-wrapped.
        paths (Optional[Dict[str, str]]): PACS-idiom grouping; one colour + marker per named path within every node cell.
        scenarios (Optional[Dict[str, str]]): TAS-idiom grouping; aliases `paths=`. Mutually exclusive with it.
        logscale (Union[bool, List[bool]]): per-axis log toggle, applied to every cell.
        title (Optional[str]): figure title.
        file_path (Optional[str]): directory to save into.
        fname (Optional[str]): filename (with extension); `_save_figure` writes both `.png` (300 dpi) and `.svg`.
        verbose (bool): if True, prints one save message per format.

    Raises:
        ValueError: If both `paths=` and `scenarios=` are provided.

    Returns:
        Figure: the matplotlib figure.
    """
    # pick grouping vocabulary (paths / scenarios / neither)
    _groups, _legend_title = _resolve_groups(paths, scenarios)

    # resolved axis labels + node display names
    _lbl_map = {**_DEFAULT_LABELS, **(labels or {})}
    _name_map = names or {}

    # node inventory drives the outer-grid shape
    _node_keys = list(coeff_data.keys())
    _n_nodes = len(_node_keys)
    if _n_nodes == 0:
        _fig = plt.figure(figsize=(8, 6), facecolor="white")
        if title:
            _fig.suptitle(title, fontsize=27, y=0.995, **_LBL_STYLE)
        return _fig

    # 3 x ceil(N/3) outer grid; final row centred when short
    _n_rows, _n_cols, _last_row_idx, _n_last_row = _grid_layout(_n_nodes)

    _fig = plt.figure(figsize=(34, 29), facecolor="white")
    _fig.subplots_adjust(top=0.92, bottom=0.05,
                         left=0.02, right=0.98,
                         hspace=0.15, wspace=0.10)
    _gs_main = _fig.add_gridspec(_n_rows, _n_cols, figure=_fig)

    # populate one 3D cell per node; remember the first labelled axes for the figure legend
    _legend_axes: Optional[Any] = None
    for _nd_idx, _node in enumerate(_node_keys):
        _nd_row, _nd_col = _node_grid_pos(_nd_idx, _n_rows, _n_cols,
                                          _last_row_idx, _n_last_row)

        _ax = _fig.add_subplot(_gs_main[_nd_row, _nd_col], projection="3d")
        _ax.set_facecolor("white")

        _node_block = coeff_data[_node]

        # populate the 3D cloud via the matching mode (silently skips on empty)
        if _groups:
            _has_legend = _panel_3d_groups(_ax, _node_block, _groups)
        else:
            try:
                _has_legend = _panel_3d_single(_ax, _node_block)
            except KeyError:
                # missing canonical sweep key; leave cell empty but keep header for layout balance
                _has_legend = False

        if _has_legend and _legend_axes is None:
            _legend_axes = _ax

        # axis labels (smaller font for the grid context)
        _ax.set_xlabel(_lbl_map["theta"], **_LBL_STY_3D_GRID)
        _ax.set_ylabel(_lbl_map["sigma"], **_LBL_STY_3D_GRID)
        _ax.set_zlabel(_lbl_map["eta"], **_LBL_STY_3D_GRID)

        # 3D cosmetics: log toggle, view, pane styling, grid, sci format, ticks
        _apply_logscale(_ax, logscale, axes_list=["x", "y", "z"])
        _ax.view_init(elev=25, azim=105)
        _style_3d_panes(_ax)
        _ax.grid(True, **_GRID_STY_3D)
        _apply_sci_format(_ax, axes_list=["x", "z"])
        # sigma clusters at 1.0 (Little's-law); bump precision so ticks don't collapse to "1.0e+00"
        _apply_sci_format(_ax, axes_list=["y"], sig=4)
        for _axis_name in ("x", "y", "z"):
            _ax.tick_params(axis=_axis_name, **_TICK_STY_3D_GRID)

        # per-cell title (mathtext-wrapped node key + optional human name)
        _ax.set_title(_node_header(_node, _name_map),
                      fontsize=19, pad=10, **_LBL_STYLE)

    # one figure-level legend along the bottom strip (reserved by subplots_adjust)
    if _legend_axes is not None:
        _handles, _labels = _legend_axes.get_legend_handles_labels()
        _fig.legend(_handles, _labels,
                    loc="lower center",
                    bbox_to_anchor=(0.5, 0.01),
                    ncol=min(len(_labels), 6),
                    fontsize=14,
                    framealpha=0.9,
                    title=_legend_title,
                    title_fontsize=15)
        _fig.subplots_adjust(bottom=0.10)

    if title:
        _fig.suptitle(title, fontsize=27, y=0.995, **_LBL_STYLE)

    _save_figure(_fig, file_path, fname, verbose)
    return _fig


def plot_yoly_arts_charts(coeff_data: Dict[str, Dict[str, Any]],
                          *,
                          labels: Optional[Dict[str, str]] = None,
                          names: Optional[Dict[str, str]] = None,
                          paths: Optional[Dict[str, str]] = None,
                          scenarios: Optional[Dict[str, str]] = None,
                          logscale: Union[bool, List[bool]] = False,
                          title: Optional[str] = None,
                          file_path: Optional[str] = None,
                          fname: Optional[str] = None,
                          verbose: bool = False) -> Figure:
    """*plot_yoly_arts_charts()* per-node 2D yoly planes laid out in a 3x(ceil(N/3)) outer grid; each cell carries a 2x2 subgrid of coefficient planes.

    Inner panels per node match `plot_yoly_chart`: (theta, sigma), (theta, eta),
    (sigma, eta), (theta, phi). Three rendering modes (single / paths /
    scenarios) flow through every panel of every node.

    Args:
        coeff_data (Dict[str, Dict[str, Any]]): nested dict `{node_key: {full_symbol: array}}`. Outer keys are artifact identifiers; inner dicts are the per-artifact sweep blocks.
        labels (Optional[Dict[str, str]]): display labels per short coefficient name (`"theta"`, `"sigma"`, `"eta"`, `"phi"`). Missing keys fall back to `_DEFAULT_LABELS`.
        names (Optional[Dict[str, str]]): human display-name override per node key. Missing keys fall back to the mathtext-wrapped node key.
        paths (Optional[Dict[str, str]]): PACS-idiom grouping; one colour + marker per named path within every panel.
        scenarios (Optional[Dict[str, str]]): TAS-idiom grouping; aliases `paths=`. Mutually exclusive with it.
        logscale (Union[bool, List[bool]]): per-axis log toggle, applied to every panel of every cell.
        title (Optional[str]): figure title.
        file_path (Optional[str]): directory to save into.
        fname (Optional[str]): filename (with extension); `_save_figure` writes both `.png` (300 dpi) and `.svg`.
        verbose (bool): if True, prints one save message per format.

    Raises:
        ValueError: If both `paths=` and `scenarios=` are provided.

    Returns:
        Figure: the matplotlib figure.
    """
    # pick grouping vocabulary (paths / scenarios / neither)
    _groups, _legend_title = _resolve_groups(paths, scenarios)

    # resolved axis labels + node display names
    _lbl_map = {**_DEFAULT_LABELS, **(labels or {})}
    _name_map = names or {}

    # node inventory drives the outer-grid shape
    _node_keys = list(coeff_data.keys())
    _n_nodes = len(_node_keys)
    if _n_nodes == 0:
        _fig = plt.figure(figsize=(8, 6), facecolor="white")
        if title:
            _fig.suptitle(title, fontsize=27, y=0.995, **_LBL_STYLE)
        return _fig

    # 3 x ceil(N/3) outer grid; final row centred when short
    _n_rows, _n_cols, _last_row_idx, _n_last_row = _grid_layout(_n_nodes)

    _fig = plt.figure(figsize=(34, 29), facecolor="white")
    _fig.subplots_adjust(top=0.92, bottom=0.05,
                         left=0.06, right=0.96,
                         hspace=0.35, wspace=0.30)
    _gs_main = _fig.add_gridspec(_n_rows, _n_cols, figure=_fig)

    # populate each node's 2x2 subgrid; lift labels from the first labelled cell for one figure legend
    _legend_axes: Optional[Any] = None
    for _nd_idx, _node in enumerate(_node_keys):
        _nd_row, _nd_col = _node_grid_pos(_nd_idx, _n_rows, _n_cols,
                                          _last_row_idx, _n_last_row)

        _gs_node = _gs_main[_nd_row, _nd_col].subgridspec(2, 2,
                                                          hspace=0.55,
                                                          wspace=0.60)
        _node_block = coeff_data[_node]

        # populate the 4 yoly panels for this node
        for _p_idx, (_panel_title, _x_key, _y_key) in enumerate(_YOLY_PANELS):
            _row = _p_idx // 2
            _col = _p_idx % 2
            _ax = _fig.add_subplot(_gs_node[_row, _col])
            _ax.set_facecolor("white")

            # populate via the matching mode (silently skip on missing keys)
            if _groups:
                _has_legend = _panel_multi_path(_ax, _node_block,
                                                _x_key, _y_key, _groups)
            else:
                try:
                    _has_legend = _panel_single_mode(_ax, _node_block,
                                                     _x_key, _y_key)
                except KeyError:
                    _has_legend = False

            if _has_legend and _legend_axes is None:
                _legend_axes = _ax

            # cosmetic pass: grid, ticks, spines, sci format, log toggle
            _ax.grid(True, **_GRID_STY_2D)
            _ax.tick_params(**_TICK_STYLE)
            for _spine in _ax.spines.values():
                _spine.set_edgecolor(_TEXT_BLACK)
            # sigma clusters at 1.0 (Little's-law identity); bump precision so ticks don't collapse to "1.0e+00"
            if _x_key != "sigma":
                _x_axes = ["x"]
            else:
                _x_axes = []
            if _y_key != "sigma":
                _y_axes = ["y"]
            else:
                _y_axes = []
            if _x_axes or _y_axes:
                _apply_sci_format(_ax, axes_list=_x_axes + _y_axes)
            _sigma_axes = [_n for _n, _k in (("x", _x_key), ("y", _y_key))
                           if _k == "sigma"]
            if _sigma_axes:
                _apply_sci_format(_ax, axes_list=_sigma_axes, sig=4)
            _apply_logscale(_ax, logscale)

            # smaller axis-label font for the grid context
            _ax.set_xlabel(_lbl_map[_x_key], **_LBL_STY_2D_GRID)
            _ax.set_ylabel(_lbl_map[_y_key], **_LBL_STY_2D_GRID)
            _ax.set_title(_panel_title, fontsize=13, **_LBL_STYLE)

        # anchor header to the gridspec cell top so it never overlaps the inner subgrid title
        _cell_pos = _gs_main[_nd_row, _nd_col].get_position(_fig)
        _title_x = (_cell_pos.x0 + _cell_pos.x1) / 2.0
        _title_y = _cell_pos.y1 + 0.012
        _fig.text(_title_x, _title_y,
                  _node_header(_node, _name_map),
                  ha="center", va="bottom",
                  fontsize=17, fontweight="bold", color=_TEXT_BLACK,
                  transform=_fig.transFigure)

    # one figure-level legend along the bottom strip reserved by subplots_adjust
    if _legend_axes is not None:
        _handles, _labels = _legend_axes.get_legend_handles_labels()
        _fig.legend(_handles, _labels,
                    loc="lower center",
                    bbox_to_anchor=(0.5, 0.01),
                    ncol=min(len(_labels), 6),
                    fontsize=14,
                    framealpha=0.9,
                    title=_legend_title,
                    title_fontsize=15)
        _fig.subplots_adjust(bottom=0.08)

    if title:
        _fig.suptitle(title, fontsize=27, y=0.995, **_LBL_STYLE)

    _save_figure(_fig, file_path, fname, verbose)
    return _fig

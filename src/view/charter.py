# -*- coding: utf-8 -*-
"""
Module view/charter.py
======================

Dimensionless-coefficient charters (yoly family) for the CS-01 TAS case study. Sibling to `src.view.diagrams` (queueing topology, heatmaps, network bars); this module renders the coefficient cloud (theta, sigma, eta, phi) across a configuration sweep.

Thin orchestrator: every helper, constant, palette, scatter primitive, and layout helper lives in `src.view.common`. Each public function picks a `FigureLayout` and calls `build_stacked_figure(layout)`. The body is populated via the migrated `_paint_*_yoly` + `_compute_*` helpers; the footer is applied via `render_footer_*`. Axis cosmetics are caller-driven through `AxisSpec` kwargs.

Five plotters, all conform to the design contract (title strip / body grid / footer strip; footer width clipped to body width):

    - `plot_yoly_chart(coeff_data, ...)` single-queue 2D yoly chart: 2x2 grid of coefficient planes (theta-sigma, theta-eta, sigma-eta, theta-phi).
    - `plot_yoly_space(coeff_data, ...)` single 3D yoly cloud (theta x sigma x eta) for one artifact / system.
    - `plot_yoly_arts_hist(coeff_data, ...)` per-node coefficient distributions: 3 x ceil(N/3) outer grid of nodes, each cell a 2x2 histogram subgrid.
    - `plot_yoly_arts_behaviour(coeff_data, ...)` per-node 3D yoly clouds laid out in a 3 x ceil(N/3) outer grid.
    - `plot_yoly_arts_charts(coeff_data, ...)` per-node 2D yoly planes laid out in a 3 x ceil(N/3) outer grid; each cell carries a 2x2 inner subgrid of coefficient planes.

`plot_yoly_space` was named `plot_system_behaviour` in the OLD module; the rename matches the `plot_yoly_*` family. `plot_yoly_arts_hist` was named `plot_arts_distributions`; same family-prefix consistency. Backwards-compatible aliases live in `src/view/__init__.py`.
"""
# native python modules
from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple, Union

# scientific stack
import numpy as np
from matplotlib.figure import Figure

# shared view helpers (every helper + constant lives in common; this module only orchestrates)
from src.view.common import (
    BodySpec,
    FigureLayout,
    _DEFAULT_LABELS,
    _GRID_PANEL,
    _GRID_PANEL_3D,
    _LBL_STY_2D_GRID,
    _LBL_STY_2D_SINGLE,
    _LBL_STY_3D_GRID,
    _LBL_STY_3D_SINGLE,
    _LBL_STYLE,
    _SUPTITLE_STYLE,
    _TEXT_BLACK,
    _TICK_STY_3D_GRID,
    _TICK_STY_3D_SINGLE,
    _TICK_STYLE,
    _YOLY_PANELS,
    _apply_logscale,
    _apply_sci_format,
    _build_coef_map,
    _compute_grid_dims,
    _compute_node_pos,
    _format_node_header,
    _generate_color_map,
    _paint_groups_2d_yoly,
    _paint_groups_3d_yoly,
    _paint_single_2d_yoly,
    _paint_single_3d_yoly,
    _pick_layout,
    _resolve_groups,
    _save_figure,
    _style_3d_panes,
    build_stacked_figure,
)


# ---------------------------------------------------------------------------
# Local helpers (charter-specific; not shared with characterization or diagrams)
# ---------------------------------------------------------------------------


def _resolve_yoly_inputs(labels: Optional[Dict[str, str]],
                         paths: Optional[Dict[str, str]],
                         scenarios: Optional[Dict[str, str]]
                         ) -> Tuple[Optional[Dict[str, str]],
                                    str,
                                    Dict[str, str]]:
    """*_resolve_yoly_inputs()* return the trio every yoly plotter needs at the top of its body.

    Args:
        labels (Optional[Dict[str, str]]): caller-supplied coefficient-label override.
        paths (Optional[Dict[str, str]]): PACS-idiom grouping.
        scenarios (Optional[Dict[str, str]]): TAS-idiom grouping.

    Raises:
        ValueError: If both `paths=` and `scenarios=` are provided (propagated from `_resolve_groups`).

    Returns:
        Tuple[Optional[Dict[str, str]], str, Dict[str, str]]: `(groups, legend_title, lbl_map)`.
    """
    _groups, _legend_title = _resolve_groups(paths, scenarios)
    _lbl_map = {**_DEFAULT_LABELS, **(labels or {})}
    return _groups, _legend_title, _lbl_map


def _resolve_name_map(names: Optional[Dict[str, str]]) -> Dict[str, str]:
    """*_resolve_name_map()* return `names` when given, else an empty dict.

    Args:
        names (Optional[Dict[str, str]]): caller-supplied node-name override.

    Returns:
        Dict[str, str]: the caller's dict or an empty fallback.
    """
    if names is not None:
        return names
    return {}


def _handle_empty_meta_grid(fig: Figure,
                            body_ax: Any,
                            file_path: Optional[str],
                            fname: Optional[str],
                            verbose: bool) -> Figure:
    """*_handle_empty_meta_grid()* close an empty meta-grid figure cleanly when the caller passed an empty `coeff_data`.

    Args:
        fig (Figure): figure returned by `build_stacked_figure`.
        body_ax (Any): body host axis (will be hidden).
        file_path (Optional[str]): directory to save into; persistence delegated to `_save_figure`.
        fname (Optional[str]): filename stem.
        verbose (bool): if True, prints one save-path message per format.

    Returns:
        Figure: the (now-empty) figure.
    """
    body_ax.axis("off")
    _save_figure(fig, file_path, fname, verbose=verbose)
    return fig


def _anchor_cell_header(fig: Figure,
                        gs_cell: Any,
                        text: str,
                        *,
                        fontsize: int,
                        dy: float = 0.008) -> None:
    """*_anchor_cell_header()* draw a per-cell header anchored to the gridspec cell's top edge in figure coordinates.

    Args:
        fig (Figure): figure to draw on.
        gs_cell (Any): gridspec cell (`gs_main[row, col]`); must support `.get_position(fig)`.
        text (str): header text (mathtext OK).
        fontsize (int): text font size.
        dy (float): vertical offset above the cell's top edge in figure-fraction units. Defaults to 0.008.
    """
    _cell_pos = gs_cell.get_position(fig)
    _title_x = (_cell_pos.x0 + _cell_pos.x1) / 2.0
    _title_y = _cell_pos.y1 + dy
    fig.text(_title_x, _title_y, text,
             ha="center",
             va="bottom",
             fontsize=fontsize,
             fontweight="bold",
             color=_TEXT_BLACK,
             transform=fig.transFigure)


def _apply_yoly_panel_axes(ax: Any,
                           x_key: str,
                           y_key: str,
                           lbl_map: Dict[str, str],
                           lbl_style: Dict[str, Any],
                           panel_title: str,
                           logscale: Union[bool, List[bool]]) -> None:
    """*_apply_yoly_panel_axes()* set grid, ticks, spines, sci format, log toggle, axis labels, and panel title on a single yoly 2D panel.

    Sigma values track theta closely (Little's law: lambda*W = L on a static system). Bumping sigma's scientific format to 4 significant figures keeps small values from collapsing to "1.0e+00".

    Args:
        ax (Any): matplotlib 2D axes.
        x_key (str): short coefficient name on the x-axis (`"theta"`, `"sigma"`, ...).
        y_key (str): short coefficient name on the y-axis.
        lbl_map (Dict[str, str]): coefficient -> display-label map.
        lbl_style (Dict[str, Any]): style dict for axis labels (`_LBL_STY_2D_SINGLE` or `_LBL_STY_2D_GRID`).
        panel_title (str): panel title string.
        logscale (Union[bool, List[bool]]): per-axis log toggle.
    """
    ax.grid(True, **_GRID_PANEL)
    ax.tick_params(**_TICK_STYLE)
    for _spine in ax.spines.values():
        _spine.set_edgecolor(_TEXT_BLACK)

    # uniform 2-sig-fig sci format on every axis of every panel; the legacy sig=4 special-case for sigma was needed when sigma ~ theta on closed-form solves (Little's law identity), but after the sigma = lambda*W/K formula correction sigma differs enough to read clearly at sig=2
    _apply_sci_format(ax, axes_list=["x", "y"])
    _apply_logscale(ax, logscale)

    ax.set_xlabel(lbl_map[x_key], **lbl_style)
    ax.set_ylabel(lbl_map[y_key], **lbl_style)
    ax.set_title(panel_title,
                 fontsize=17,
                 pad=-10,
                 **_LBL_STYLE)


def _apply_yoly_3d_axes(ax: Any,
                        lbl_map: Dict[str, str],
                        lbl_style: Dict[str, Any],
                        tick_style: Dict[str, Any],
                        elev: float,
                        azim: float,
                        logscale: Union[bool, List[bool]]) -> None:
    """*_apply_yoly_3d_axes()* set axis labels, log toggle, view angle, pane styling, grid, sci format, and ticks on a 3D yoly axes.

    Args:
        ax (Any): matplotlib 3D axes.
        lbl_map (Dict[str, str]): coefficient -> display-label map.
        lbl_style (Dict[str, Any]): label-style dict (`_LBL_STY_3D_SINGLE` or `_LBL_STY_3D_GRID`).
        tick_style (Dict[str, Any]): tick-style dict (`_TICK_STY_3D_SINGLE` or `_TICK_STY_3D_GRID`).
        elev (float): viewing elevation passed to `ax.view_init`.
        azim (float): viewing azimuth passed to `ax.view_init`.
        logscale (Union[bool, List[bool]]): per-axis log toggle.
    """
    ax.set_xlabel(lbl_map["theta"], **lbl_style)
    ax.set_ylabel(lbl_map["sigma"], **lbl_style)
    ax.set_zlabel(lbl_map["eta"], **lbl_style)

    _apply_logscale(ax, logscale, axes_list=["x", "y", "z"])
    ax.view_init(elev=elev, azim=azim)
    _style_3d_panes(ax)
    ax.grid(True, **_GRID_PANEL_3D)
    # uniform 2-sig-fig sci format across all three 3D axes; matches the 2D panel formatter
    _apply_sci_format(ax, axes_list=["x", "y", "z"])
    for _axis_name in ("x", "y", "z"):
        ax.tick_params(axis=_axis_name, **tick_style)


def _lift_legend_to_footer(legend_axes: Optional[Any],
                           footer_ax: Optional[Any],
                           legend_title: str,
                           ncol_cap: int = 6) -> None:
    """*_lift_legend_to_footer()* copy legend handles + labels from a body axis into the footer axis.

    Args:
        legend_axes (Optional[Any]): the body axis whose handles should be lifted; None is a no-op.
        footer_ax (Optional[Any]): footer axis returned by `build_stacked_figure`; None is a no-op.
        legend_title (str): legend title (e.g. "Scenario", "Path").
        ncol_cap (int): maximum column count for the footer legend. Defaults to 6.
    """
    if legend_axes is None or footer_ax is None:
        return
    _handles, _labels = legend_axes.get_legend_handles_labels()
    if not _handles:
        return
    _ncol = min(len(_labels), ncol_cap)
    footer_ax.legend(_handles, _labels,
                     loc="center",
                     ncol=_ncol,
                     fontsize=12,
                     framealpha=0.9,
                     title=legend_title,
                     title_fontsize=13)


# ---------------------------------------------------------------------------
# Public plotters
# ---------------------------------------------------------------------------


def plot_yoly_chart(coeff_data: Dict[str, Any],
                    *,
                    labels: Optional[Dict[str, str]] = None,
                    paths: Optional[Dict[str, str]] = None,
                    scenarios: Optional[Dict[str, str]] = None,
                    logscale: Union[bool, List[bool]] = False,
                    layout: Optional[FigureLayout] = None,
                    title: Optional[str] = None,
                    file_path: Optional[str] = None,
                    fname: Optional[str] = None,
                    verbose: bool = False) -> Figure:
    """*plot_yoly_chart()* single-queue 2D yoly chart: 2x2 grid of coefficient planes.

    Panels (row-major): (theta, sigma), (theta, eta), (sigma, eta), (theta, phi). Three rendering modes selected by the caller's grouping kwarg:

        - **Single-queue** (default, both groupings None): looks up theta / sigma / eta / phi / c / mu / K arrays in `coeff_data` by semantic prefix. Each point is coloured by its `c` value and shaped by its `mu` value; K-endpoints get inline annotations.
        - **Multi-path** (`paths=`, PACS idiom): one colour + marker per named path; per-path arrays keyed by `\\<coef>_{<path_tag>}`.
        - **Multi-scenario** (`scenarios=`, TAS idiom): same as multi-path under different naming. Mutually exclusive with `paths=`.

    Args:
        coeff_data (Dict[str, Any]): sweep dict keyed by LaTeX-subscripted symbols.
        labels (Optional[Dict[str, str]]): display labels per short coefficient name. Missing keys fall back to `_DEFAULT_LABELS`.
        paths (Optional[Dict[str, str]]): PACS-idiom grouping `{display_name: path_tag}`.
        scenarios (Optional[Dict[str, str]]): TAS-idiom grouping; aliases `paths=`.
        logscale (Union[bool, List[bool]]): per-axis log toggle, applied to every panel.
        layout (Optional[FigureLayout]): full layout override. Defaults to a 2x2 2D body with a centred legend footer.
        title (Optional[str]): figure title.
        file_path (Optional[str]): directory to save into.
        fname (Optional[str]): filename stem; both PNG and SVG written.
        verbose (bool): if True, prints one save-path message per format.

    Raises:
        ValueError: If both `paths=` and `scenarios=` are provided.

    Returns:
        Figure: the matplotlib figure.

    Example::

        plot_yoly_chart(coeff_data,
                        scenarios={"Before": "baseline_{TAS_{1}}",
                                   "After":  "aggregate_{TAS_{1}}"},
                        title="TAS_{1} adaptation trajectory",
                        file_path="data/img/dimensional/yoly",
                        fname="trajectory")
    """
    _groups, _legend_title, _lbl_map = _resolve_yoly_inputs(labels, paths, scenarios)

    # narrower + taller. title_h and footer_h trimmed so each strip wraps its text content tightly: the title strip ends just below the suptitle, and the footer strip ends just below the legend. outer_hspace near zero closes the inter-region gap. Footer legend uses mode="expand" (in render_footer_legend) to clip to body width.
    _default_layout = FigureLayout(title=title,
                                   title_h=0.045,
                                   body=BodySpec(shape=(2, 2),
                                                 panel_kind="2d",
                                                 wspace=0.32,
                                                 hspace=0.22),
                                   footer_h=0.18,
                                   footer_kind="legend",
                                   figsize=(16, 22),
                                   outer_hspace=0.025)
    _layout = _pick_layout(layout, _default_layout)

    _fig, _regions = build_stacked_figure(_layout)
    _axes = _regions["body_axes"]

    _legend_axes: Optional[Any] = None
    for _idx, (_panel_title, _x_key, _y_key) in enumerate(_YOLY_PANELS):
        _ax = _axes[_idx]
        if _groups:
            _has_legend = _paint_groups_2d_yoly(_ax, coeff_data,
                                                _x_key, _y_key, _groups)
        else:
            _has_legend = _paint_single_2d_yoly(_ax, coeff_data,
                                                _x_key, _y_key)
        if _has_legend and _legend_axes is None:
            _legend_axes = _ax

        _apply_yoly_panel_axes(_ax,
                               _x_key, _y_key,
                               _lbl_map,
                               _LBL_STY_2D_SINGLE,
                               _panel_title,
                               logscale)

    # cap at 4 columns so 30+ scenario combos fold into many rows (taller, not wider)
    _lift_legend_to_footer(_legend_axes,
                           _regions["footer_ax"],
                           _legend_title,
                           ncol_cap=4)

    _save_figure(_fig, file_path, fname, verbose=verbose)
    return _fig


def plot_yoly_space(coeff_data: Dict[str, Any],
                    *,
                    labels: Optional[Dict[str, str]] = None,
                    paths: Optional[Dict[str, str]] = None,
                    scenarios: Optional[Dict[str, str]] = None,
                    logscale: Union[bool, List[bool]] = False,
                    layout: Optional[FigureLayout] = None,
                    title: Optional[str] = None,
                    subtitle: Optional[str] = None,
                    file_path: Optional[str] = None,
                    fname: Optional[str] = None,
                    verbose: bool = False) -> Figure:
    """*plot_yoly_space()* single 3D yoly cloud (theta x sigma x eta) for one artifact / system.

    Three rendering modes share the 3D axes:

        - **Single-queue** (both groupings None): colour by `c`, marker by `mu`, K-endpoints annotated.
        - **Multi-path** (`paths=`, PACS idiom): one colour + marker per named path.
        - **Multi-scenario** (`scenarios=`, TAS idiom): one colour + marker per named adaptation. Mutually exclusive with `paths=`.

    Args:
        coeff_data (Dict[str, Any]): sweep dict keyed by LaTeX-subscripted symbols.
        labels (Optional[Dict[str, str]]): display labels per short coefficient name (`"theta"`, `"sigma"`, `"eta"`).
        paths (Optional[Dict[str, str]]): PACS-idiom grouping.
        scenarios (Optional[Dict[str, str]]): TAS-idiom grouping; aliases `paths=`.
        logscale (Union[bool, List[bool]]): bool toggles log scale on all three axes; 3-list selects `[x_log, y_log, z_log]`.
        layout (Optional[FigureLayout]): full layout override. Defaults to a 1x1 3D body with a centred legend footer.
        title (Optional[str]): figure title.
        subtitle (Optional[str]): axes-level subtitle (drawn inside the body axis).
        file_path (Optional[str]): directory to save into.
        fname (Optional[str]): filename stem; both PNG and SVG written.
        verbose (bool): if True, prints one save-path message per format.

    Raises:
        ValueError: If both `paths=` and `scenarios=` are provided.

    Returns:
        Figure: the matplotlib figure.

    Example::

        plot_yoly_space(coeff_data,
                        title="System behaviour cloud",
                        subtitle="TAS_{1} (baseline)",
                        file_path="data/img/dimensional/space",
                        fname="cloud_baseline")
    """
    _groups, _legend_title, _lbl_map = _resolve_yoly_inputs(labels, paths, scenarios)

    # title strip carries either the suptitle alone or suptitle stacked above subtitle. We pass title=None to build_stacked_figure when both are set so it doesn't auto-draw at strip centre; both lines are then drawn manually into the same dedicated title_ax with explicit y-positions in axes coords (no figure-coord arithmetic, no overlap risk).
    _has_subtitle = bool(subtitle)
    _title_h = 0.10 if _has_subtitle else 0.05
    _default_layout = FigureLayout(title=None if _has_subtitle else title,
                                   title_h=_title_h,
                                   body=BodySpec(shape=(1, 1),
                                                 panel_kind="3d"),
                                   footer_h=0.10,
                                   footer_kind="legend",
                                   figsize=(17, 14),
                                   outer_hspace=0.02)
    _layout = _pick_layout(layout, _default_layout)

    _fig, _regions = build_stacked_figure(_layout)
    _ax = _regions["body_axes"][0]

    if _has_subtitle and title:
        # main title in the upper half of the title strip; subtitle in the lower half. Both in axes coords on the dedicated title_ax (transparent, off) so they never collide with the body or each other
        _title_ax = _regions["title_ax"]
        _title_ax.text(0.5, 0.72, title,
                       ha="center", va="center",
                       transform=_title_ax.transAxes,
                       **_SUPTITLE_STYLE)
        _title_ax.text(0.5, 0.22, subtitle,
                       ha="center", va="center",
                       transform=_title_ax.transAxes,
                       fontsize=18,
                       fontstyle="italic",
                       **_LBL_STYLE)

    if _groups:
        _has_legend = _paint_groups_3d_yoly(_ax, coeff_data, _groups)
    else:
        _has_legend = _paint_single_3d_yoly(_ax, coeff_data)

    _apply_yoly_3d_axes(_ax,
                        _lbl_map,
                        _LBL_STY_3D_SINGLE,
                        _TICK_STY_3D_SINGLE,
                        elev=30,
                        azim=110,
                        logscale=logscale)

    if _has_legend:
        _lift_legend_to_footer(_ax,
                               _regions["footer_ax"],
                               _legend_title,
                               ncol_cap=6)

    _save_figure(_fig, file_path, fname, verbose=verbose)
    return _fig


def plot_yoly_arts_hist(coeff_data: Dict[str, Dict[str, Any]],
                        *,
                        labels: Optional[Dict[str, str]] = None,
                        names: Optional[Dict[str, str]] = None,
                        layout: Optional[FigureLayout] = None,
                        title: Optional[str] = None,
                        file_path: Optional[str] = None,
                        fname: Optional[str] = None,
                        verbose: bool = False) -> Figure:
    """*plot_yoly_arts_hist()* per-node coefficient distributions as histograms arranged in a 3 x ceil(N/3) meta-grid; each node cell carries a 2x2 inner subgrid (one histogram per derived coefficient).

    Each histogram uses 50 bins, draws a mean reference line, and annotates the title with mean + std. The outer grid centres a short last row.

    Args:
        coeff_data (Dict[str, Dict[str, Any]]): nested `{node_key: {full_symbol: array}}`.
        labels (Optional[Dict[str, str]]): display labels per short coefficient name. Missing keys fall back to `_DEFAULT_LABELS`.
        names (Optional[Dict[str, str]]): human display-name override per node key (e.g. `{"TAS_{1}": "Dispatch"}`).
        layout (Optional[FigureLayout]): full layout override. Defaults to a 1x1 2D body with no footer (the meta-grid lives inside the body axis via subgridspec).
        title (Optional[str]): figure title.
        file_path (Optional[str]): directory to save into.
        fname (Optional[str]): filename stem; both PNG and SVG written.
        verbose (bool): if True, prints one save-path message per format.

    Returns:
        Figure: the matplotlib figure.

    Example::

        plot_yoly_arts_hist(coeff_data,
                            title="Per-node coefficient distributions",
                            file_path="data/img/dimensional/hist",
                            fname="dist_baseline")
    """
    # histogram x-axis stays symbol-only (no parenthesised name) to keep the dense per-comp grid readable; the operational name lives in the legend label / subplot title instead
    _hist_symbols = {
        "theta": r"$\mathbf{\theta}$",
        "sigma": r"$\mathbf{\sigma}$",
        "eta":   r"$\mathbf{\eta}$",
        "phi":   r"$\mathbf{\phi}$",
    }
    _lbl_map = {**_hist_symbols, **(labels or {})}
    _name_map = _resolve_name_map(names)

    _node_keys = list(coeff_data.keys())
    _n_nodes = len(_node_keys)

    _default_layout = FigureLayout(title=title,
                                   title_h=0.045,
                                   body=BodySpec(shape=(1, 1),
                                                 panel_kind="2d"),
                                   footer_h=0.0,
                                   footer_kind="none",
                                   figsize=(26, 26),
                                   outer_hspace=0.025)
    _layout = _pick_layout(layout, _default_layout)

    _fig, _regions = build_stacked_figure(_layout)
    _body_ax = _regions["body_axes"][0]

    if _n_nodes == 0:
        return _handle_empty_meta_grid(_fig, _body_ax,
                                       file_path, fname, verbose)

    # the body axis acts as a host for the subgridspec; hide its frame, keep its bbox
    _body_ax.axis("off")

    _n_rows, _n_cols, _last_row_idx, _n_last_row = _compute_grid_dims(_n_nodes)
    _gs_main = _body_ax.get_subplotspec().subgridspec(_n_rows, _n_cols,
                                                      hspace=0.30,
                                                      wspace=0.25)

    for _nd_idx, _node in enumerate(_node_keys):
        _nd_row, _nd_col = _compute_node_pos(_nd_idx,
                                             _n_rows, _n_cols,
                                             _last_row_idx, _n_last_row)

        _node_block = coeff_data[_node]
        _coef_map = _build_coef_map(_node_block)
        _n_coeffs = len(_coef_map)
        if _n_coeffs == 0:
            continue

        _col_lt = _generate_color_map(list(range(_n_coeffs)))
        _n_inner_cols = (_n_coeffs + 1) // 2
        _gs_node = _gs_main[_nd_row, _nd_col].subgridspec(2, _n_inner_cols,
                                                          hspace=0.65,
                                                          wspace=0.40)

        _anchor_cell_header(_fig,
                            _gs_main[_nd_row, _nd_col],
                            _format_node_header(_node, _name_map),
                            fontsize=15,
                            dy=0.008)

        _short_names = list(_coef_map.keys())
        for _c_idx, _short in enumerate(_short_names):
            _row = _c_idx // _n_inner_cols
            _col = _c_idx % _n_inner_cols
            _ax = _fig.add_subplot(_gs_node[_row, _col])
            _ax.set_facecolor("white")

            _full = _coef_map[_short]
            _data = np.asarray(_node_block[_full], dtype=float)
            _color = _col_lt[_c_idx]

            _ax.hist(_data,
                     bins=50,
                     color=_color,
                     alpha=0.7,
                     edgecolor=_TEXT_BLACK)

            # sample median (more robust than mean to K-block tail clustering) and sample variance
            _median = float(np.median(_data))
            # variance (s^2), not the population std (s or \sigma).
            _var = float(np.var(_data))
            _ax.axvline(_median,
                        color=_color,
                        linestyle="-",
                        linewidth=2,
                        label=rf"$\widetilde{{X}}={_median:.3e}$")

            _ax.set_xlabel(_lbl_map.get(_short, _short),
                           fontsize=11,
                           fontweight="bold",
                           color=_TEXT_BLACK)
            _ax.set_ylabel("Frequency",
                           fontsize=11,
                           fontweight="bold",
                           color=_TEXT_BLACK)
            _ax.set_title(rf"$\widetilde{{X}}={_median:.3e}\,\,\,s^{{2}}={_var:.3e}$",
                          fontsize=10,
                          fontweight="bold",
                          color=_TEXT_BLACK,
                          pad=2)

            _ax.ticklabel_format(axis="x", style="sci", scilimits=(0, 0))
            _ax.tick_params(**_TICK_STYLE)
            _ax.legend(loc="best", fontsize=11, framealpha=0.9)
            _ax.grid(True,
                     alpha=0.8,
                     color=_TEXT_BLACK,
                     linewidth=1.0)
            for _spine in _ax.spines.values():
                _spine.set_edgecolor(_TEXT_BLACK)

    _save_figure(_fig, file_path, fname, verbose=verbose)
    return _fig


def plot_yoly_arts_behaviour(coeff_data: Dict[str, Dict[str, Any]],
                             *,
                             labels: Optional[Dict[str, str]] = None,
                             names: Optional[Dict[str, str]] = None,
                             paths: Optional[Dict[str, str]] = None,
                             scenarios: Optional[Dict[str, str]] = None,
                             logscale: Union[bool, List[bool]] = False,
                             layout: Optional[FigureLayout] = None,
                             title: Optional[str] = None,
                             file_path: Optional[str] = None,
                             fname: Optional[str] = None,
                             verbose: bool = False) -> Figure:
    """*plot_yoly_arts_behaviour()* per-node 3D yoly clouds laid out in a 3 x ceil(N/3) outer grid.

    Each cell carries a 3D scatter of theta x sigma x eta for one artifact. Three rendering modes (single / paths / scenarios) flow through to every cell with the same vocabulary.

    Args:
        coeff_data (Dict[str, Dict[str, Any]]): nested `{node_key: {full_symbol: array}}`.
        labels (Optional[Dict[str, str]]): display labels per short coefficient name.
        names (Optional[Dict[str, str]]): node display-name override.
        paths (Optional[Dict[str, str]]): PACS-idiom grouping.
        scenarios (Optional[Dict[str, str]]): TAS-idiom grouping; aliases `paths=`.
        logscale (Union[bool, List[bool]]): per-axis log toggle, applied to every cell.
        layout (Optional[FigureLayout]): full layout override.
        title (Optional[str]): figure title.
        file_path (Optional[str]): directory to save into.
        fname (Optional[str]): filename stem; both PNG and SVG written.
        verbose (bool): if True, prints one save-path message per format.

    Raises:
        ValueError: If both `paths=` and `scenarios=` are provided.

    Returns:
        Figure: the matplotlib figure.

    Example::

        plot_yoly_arts_behaviour(coeff_data,
                                 scenarios={"Before": "baseline",
                                            "After":  "aggregate"},
                                 title="Per-node 3D yoly trajectories",
                                 file_path="data/img/dimensional/beh",
                                 fname="beh_overlay")
    """
    _groups, _legend_title, _lbl_map = _resolve_yoly_inputs(labels, paths, scenarios)
    _name_map = _resolve_name_map(names)

    _node_keys = list(coeff_data.keys())
    _n_nodes = len(_node_keys)

    _default_layout = FigureLayout(title=title,
                                   title_h=0.045,
                                   body=BodySpec(shape=(1, 1),
                                                 panel_kind="2d"),
                                   footer_h=0.06,
                                   footer_kind="legend",
                                   figsize=(34, 29),
                                   outer_hspace=0.025)
    _layout = _pick_layout(layout, _default_layout)

    _fig, _regions = build_stacked_figure(_layout)
    _body_ax = _regions["body_axes"][0]

    if _n_nodes == 0:
        return _handle_empty_meta_grid(_fig, _body_ax,
                                       file_path, fname, verbose)

    _body_ax.axis("off")
    _n_rows, _n_cols, _last_row_idx, _n_last_row = _compute_grid_dims(_n_nodes)
    _gs_main = _body_ax.get_subplotspec().subgridspec(_n_rows, _n_cols,
                                                      hspace=0.10,
                                                      wspace=0.08)

    _legend_axes: Optional[Any] = None
    for _nd_idx, _node in enumerate(_node_keys):
        _nd_row, _nd_col = _compute_node_pos(_nd_idx,
                                             _n_rows, _n_cols,
                                             _last_row_idx, _n_last_row)

        _ax = _fig.add_subplot(_gs_main[_nd_row, _nd_col], projection="3d")
        _ax.set_facecolor("white")

        _node_block = coeff_data[_node]

        if _groups:
            _has_legend = _paint_groups_3d_yoly(_ax, _node_block, _groups)
        else:
            try:
                _has_legend = _paint_single_3d_yoly(_ax, _node_block)
            except KeyError:
                _has_legend = False
        if _has_legend and _legend_axes is None:
            _legend_axes = _ax

        _apply_yoly_3d_axes(_ax,
                            _lbl_map,
                            _LBL_STY_3D_GRID,
                            _TICK_STY_3D_GRID,
                            elev=25,
                            azim=105,
                            logscale=logscale)

        _ax.set_title(_format_node_header(_node, _name_map),
                      fontsize=19,
                      pad=10,
                      **_LBL_STYLE)

    _lift_legend_to_footer(_legend_axes,
                           _regions["footer_ax"],
                           _legend_title,
                           ncol_cap=6)

    _save_figure(_fig, file_path, fname, verbose=verbose)
    return _fig


def plot_yoly_arts_charts(coeff_data: Dict[str, Dict[str, Any]],
                          *,
                          labels: Optional[Dict[str, str]] = None,
                          names: Optional[Dict[str, str]] = None,
                          paths: Optional[Dict[str, str]] = None,
                          scenarios: Optional[Dict[str, str]] = None,
                          logscale: Union[bool, List[bool]] = False,
                          layout: Optional[FigureLayout] = None,
                          title: Optional[str] = None,
                          file_path: Optional[str] = None,
                          fname: Optional[str] = None,
                          verbose: bool = False) -> Figure:
    """*plot_yoly_arts_charts()* per-node 2D yoly planes laid out in a 3 x ceil(N/3) outer grid; each cell carries a 2x2 inner subgrid of coefficient planes.

    Inner panels per node match `plot_yoly_chart`: (theta, sigma), (theta, eta), (sigma, eta), (theta, phi). Three rendering modes (single / paths / scenarios) flow through every panel of every node.

    Args:
        coeff_data (Dict[str, Dict[str, Any]]): nested `{node_key: {full_symbol: array}}`.
        labels (Optional[Dict[str, str]]): display labels per short coefficient name.
        names (Optional[Dict[str, str]]): node display-name override.
        paths (Optional[Dict[str, str]]): PACS-idiom grouping.
        scenarios (Optional[Dict[str, str]]): TAS-idiom grouping; aliases `paths=`.
        logscale (Union[bool, List[bool]]): per-axis log toggle, applied to every panel of every cell.
        layout (Optional[FigureLayout]): full layout override.
        title (Optional[str]): figure title.
        file_path (Optional[str]): directory to save into.
        fname (Optional[str]): filename stem; both PNG and SVG written.
        verbose (bool): if True, prints one save-path message per format.

    Raises:
        ValueError: If both `paths=` and `scenarios=` are provided.

    Returns:
        Figure: the matplotlib figure.

    Example::

        plot_yoly_arts_charts(coeff_data,
                              scenarios={"Before": "baseline",
                                         "After":  "aggregate"},
                              title="Per-node 2D yoly planes",
                              file_path="data/img/dimensional/charts",
                              fname="planes_overlay")
    """
    _groups, _legend_title, _lbl_map = _resolve_yoly_inputs(labels, paths, scenarios)
    _name_map = _resolve_name_map(names)

    _node_keys = list(coeff_data.keys())
    _n_nodes = len(_node_keys)

    _default_layout = FigureLayout(title=title,
                                   title_h=0.045,
                                   body=BodySpec(shape=(1, 1),
                                                 panel_kind="2d"),
                                   footer_h=0.06,
                                   footer_kind="legend",
                                   figsize=(34, 29),
                                   outer_hspace=0.025)
    _layout = _pick_layout(layout, _default_layout)

    _fig, _regions = build_stacked_figure(_layout)
    _body_ax = _regions["body_axes"][0]

    if _n_nodes == 0:
        return _handle_empty_meta_grid(_fig, _body_ax,
                                       file_path, fname, verbose)

    _body_ax.axis("off")
    _n_rows, _n_cols, _last_row_idx, _n_last_row = _compute_grid_dims(_n_nodes)
    _gs_main = _body_ax.get_subplotspec().subgridspec(_n_rows, _n_cols,
                                                      hspace=0.25,
                                                      wspace=0.22)

    _legend_axes: Optional[Any] = None
    for _nd_idx, _node in enumerate(_node_keys):
        _nd_row, _nd_col = _compute_node_pos(_nd_idx,
                                             _n_rows, _n_cols,
                                             _last_row_idx, _n_last_row)

        _gs_node = _gs_main[_nd_row, _nd_col].subgridspec(2, 2,
                                                          hspace=0.45,
                                                          wspace=0.45)
        _node_block = coeff_data[_node]

        for _p_idx, (_panel_title, _x_key, _y_key) in enumerate(_YOLY_PANELS):
            _row = _p_idx // 2
            _col = _p_idx % 2
            _ax = _fig.add_subplot(_gs_node[_row, _col])
            _ax.set_facecolor("white")

            if _groups:
                _has_legend = _paint_groups_2d_yoly(_ax, _node_block,
                                                    _x_key, _y_key, _groups)
            else:
                try:
                    _has_legend = _paint_single_2d_yoly(_ax, _node_block,
                                                        _x_key, _y_key)
                except KeyError:
                    _has_legend = False

            if _has_legend and _legend_axes is None:
                _legend_axes = _ax

            _apply_yoly_panel_axes(_ax,
                                   _x_key, _y_key,
                                   _lbl_map,
                                   _LBL_STY_2D_GRID,
                                   _panel_title,
                                   logscale)

        _anchor_cell_header(_fig,
                            _gs_main[_nd_row, _nd_col],
                            _format_node_header(_node, _name_map),
                            fontsize=17,
                            dy=0.012)

    _lift_legend_to_footer(_legend_axes,
                           _regions["footer_ax"],
                           _legend_title,
                           ncol_cap=6)

    _save_figure(_fig, file_path, fname, verbose=verbose)
    return _fig

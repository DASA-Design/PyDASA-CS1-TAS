# -*- coding: utf-8 -*-
"""
Module view/diagrams.py
=======================

Queue-network and dimensionless-topology diagrams plus per-node heatmaps, delta maps, CI bands, and network-wide bar charts for the CS-01 TAS case study.

Sibling to `src.view.charter` (yoly coefficient clouds). This module renders queue-network state and aggregate metrics.

Thin orchestrator: every helper, constant, palette, graph builder, and table / summary primitive lives in `src.view.common`. Each public function picks a `FigureLayout` and calls `build_stacked_figure(layout)`. The body is populated via the migrated `_draw_qn_topology_axis` / `_draw_dim_topology_axis` / `_add_*` helpers; the footer carries a per-node table, a parameter glossary, or a network summary depending on the family.

Seven plotters, all conform to the design contract (title strip / body grid / footer strip; footer width clipped to body width):

    - `plot_qn_topology(routs, ndss, names, ...)` queue-network topology for one or N scenarios. Single-scenario callers may pass scalars; the body grid degenerates to 1x1 with the per-node table in the footer.
    - `plot_dim_topology(rout, nds, ...)` dimensionless topology for one scenario; nodes coloured by a chosen coefficient column (default `eta`).
    - `plot_node_heatmap(ndss, names, nodes, ...)` per-node heatmap across N scenarios; one body row per scenario, columns per metric.
    - `plot_node_diffmap(deltas, nodes, ...)` per-node delta heatmap (single panel) with a symmetric colour scale centred on 0 %.
    - `plot_node_ci(nds, ...)` per-node mean with a confidence-interval band, optional reference overlay.
    - `plot_arch_bars(nets, names, ...)` network-wide grouped-bar chart across N scenarios.
    - `plot_arch_delta(deltas, ...)` network-wide percent-change bar chart between two scenarios.

`plot_qn_topology_grid` was a separate function in the OLD module. Its logic now lives inside `plot_qn_topology` via the length-1 list (single-scenario) collapse. Backwards-compatible aliases live in `src/view/__init__.py`. Renames: `plot_nd_* -> plot_node_*`, `plot_net_* -> plot_arch_*`.
"""
# native python modules
from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple, Union

# scientific stack
import matplotlib.colors as mcolors
import matplotlib.patches as mpatches
import networkx as nx
import numpy as np
import pandas as pd
import seaborn as sns
from matplotlib import cm
from matplotlib.figure import Figure

# shared view helpers (every helper + constant lives in common; this module only orchestrates)
from src.view.common import (
    BodySpec,
    DIM_GLOSSARY_DEFAULT,
    FigureLayout,
    QN_GLOSSARY_DEFAULT,
    _BAR_BLUE,
    _BAR_ORANGE,
    _DIM_COEF_SYMS,
    _GRID_BARS,
    _HEATMAP_CMAP,
    _LBL_STYLE,
    _TEXT_BLACK,
    _TOPOLOGY_CMAP,
    _Z_SCORES,
    _add_dim_network_summary,
    _add_dim_node_table,
    _add_param_glossary,
    _add_qn_network_summary,
    _add_qn_node_table,
    _bfs_layout_shared,
    _build_topology_graph,
    _draw_dim_topology_axis,
    _draw_qn_topology_axis,
    _format_value,
    _generate_color_map,
    _pick_layout,
    _resolve_labels,
    _resolve_metrics,
    _save_figure,
    build_stacked_figure,
    render_footer_legend,
)


# ---------------------------------------------------------------------------
# Local helpers (diagrams-specific; not shared with characterization or charter)
# ---------------------------------------------------------------------------


def _resolve_node_names(ndss: List[pd.DataFrame],
                        nd_names: Optional[List[str]]) -> List[str]:
    """*_resolve_node_names()* return the per-node display-name list, defaulting to the first frame's `key` column when not supplied.

    Args:
        ndss (List[pd.DataFrame]): per-scenario node frames.
        nd_names (Optional[List[str]]): caller-supplied display names.

    Returns:
        List[str]: caller's list when given, else `ndss[0]["key"]` as a list, else `["Node 0", ...]`.
    """
    if nd_names is not None:
        return list(nd_names)
    if "key" in ndss[0].columns:
        return ndss[0]["key"].tolist()
    _n = len(ndss[0])
    return [f"Node {_i}" for _i in range(_n)]


def _normalise_qn_lists(routs: Union[List[np.ndarray], np.ndarray],
                        ndss: Union[List[pd.DataFrame], pd.DataFrame],
                        names: Optional[Union[List[str], str]],
                        nets: Optional[Union[List[pd.DataFrame],
                                             pd.DataFrame]]
                        ) -> Tuple[List[np.ndarray],
                                   List[pd.DataFrame],
                                   List[str],
                                   Optional[List[pd.DataFrame]]]:
    """*_normalise_qn_lists()* wrap scalar inputs into length-1 lists so a single-scenario caller and an N-scenario caller share one downstream code path.

    Args:
        routs (Union[List[np.ndarray], np.ndarray]): per-scenario routing matrices, or a single matrix.
        ndss (Union[List[pd.DataFrame], pd.DataFrame]): per-scenario node frames, or a single frame.
        names (Optional[Union[List[str], str]]): per-scenario display names, or a single name, or None.
        nets (Optional[Union[List[pd.DataFrame], pd.DataFrame]]): per-scenario network-wide frames, or a single frame, or None.

    Returns:
        Tuple[List[np.ndarray], List[pd.DataFrame], List[str], Optional[List[pd.DataFrame]]]: `(routs_list, ndss_list, names_list, nets_list)`.
    """
    if not isinstance(routs, list):
        _routs_list: List[np.ndarray] = [routs]
        _ndss_list: List[pd.DataFrame] = [ndss]  # type: ignore[list-item]
        if nets is not None and not isinstance(nets, list):
            _nets_list: Optional[List[pd.DataFrame]] = [nets]
        elif nets is not None:
            _nets_list = list(nets)
        else:
            _nets_list = None
    else:
        _routs_list = list(routs)
        _ndss_list = list(ndss)  # type: ignore[arg-type]
        if nets is not None:
            _nets_list = list(nets)
        else:
            _nets_list = None

    if names is None:
        _names_list: List[str] = ["" for _ in _routs_list]
    elif isinstance(names, str):
        _names_list = [names]
    else:
        _names_list = list(names)

    return _routs_list, _ndss_list, _names_list, _nets_list


def _validate_parallel_lists(routs: List[Any],
                             ndss: List[pd.DataFrame],
                             names: List[str],
                             nets: Optional[List[pd.DataFrame]] = None) -> None:
    """*_validate_parallel_lists()* raise when the parallel-list inputs disagree on length.

    Args:
        routs (List[Any]): per-scenario routing matrices.
        ndss (List[pd.DataFrame]): per-scenario node frames.
        names (List[str]): per-scenario display names.
        nets (Optional[List[pd.DataFrame]]): optional per-scenario network frames; when given, must match `routs` length.

    Raises:
        ValueError: If the lists do not have matching lengths.
    """
    if not (len(routs) == len(ndss) == len(names)):
        _msg = "routs, ndss, and names must have matching lengths; "
        _msg += f"got {len(routs)}, {len(ndss)}, {len(names)}"
        raise ValueError(_msg)
    if nets is not None and len(nets) != len(routs):
        _msg = f"nets length ({len(nets)}) must match routs "
        _msg += f"length ({len(routs)})"
        raise ValueError(_msg)


def _filter_rows_by_node(df: pd.DataFrame,
                         nodes: List[str],
                         cname: str) -> List[pd.Series]:
    """*_filter_rows_by_node()* return the rows of `df` whose `cname` value matches each requested node, in the caller's node order.

    Args:
        df (pd.DataFrame): source frame.
        nodes (List[str]): requested node identifiers (drives row order).
        cname (str): column holding the node identifier.

    Returns:
        List[pd.Series]: per-node row series; missing nodes are silently skipped.
    """
    _rows: List[pd.Series] = []
    for _node in nodes:
        _sub = df[df[cname] == _node]
        if not _sub.empty:
            _rows.append(_sub.iloc[0])
    return _rows


def _add_topology_colorbar(fig: Figure,
                           target_ax: Any,
                           vmin: float,
                           vmax: float,
                           label: str) -> None:
    """*_add_topology_colorbar()* attach a `coolwarm` colourbar to `target_ax` (or a list of axes), normalised to `[vmin, vmax]`.

    Args:
        fig (Figure): matplotlib figure to draw on.
        target_ax (Any): axis or list of axes the colourbar anchors against.
        vmin (float): scale lower bound.
        vmax (float): scale upper bound; clamped to be >= vmin + 1e-9.
        label (str): colourbar label (mathtext OK).
    """
    if vmax <= vmin:
        vmax = vmin + 1e-9
    _sm = cm.ScalarMappable(cmap=_TOPOLOGY_CMAP,
                            norm=mcolors.Normalize(vmin=vmin, vmax=vmax))
    _sm.set_array([])
    _cbar = fig.colorbar(_sm,
                         ax=target_ax,
                         shrink=0.6,
                         pad=0.02)
    _cbar.set_label(label,
                    color=_TEXT_BLACK,
                    fontsize=14,
                    fontweight="bold")
    _cbar.ax.tick_params(colors=_TEXT_BLACK)


# ---------------------------------------------------------------------------
# Public plotters -- topology
# ---------------------------------------------------------------------------


def plot_qn_topology(routs: Union[List[np.ndarray], np.ndarray],
                     ndss: Union[List[pd.DataFrame], pd.DataFrame],
                     names: Optional[Union[List[str], str]] = None,
                     *,
                     nets: Optional[Union[List[pd.DataFrame],
                                          pd.DataFrame]] = None,
                     glossary: Optional[List[str]] = None,
                     nd_names: Optional[List[str]] = None,
                     layout: Optional[FigureLayout] = None,
                     title: Optional[str] = None,
                     file_path: Optional[str] = None,
                     fname: Optional[str] = None,
                     verbose: bool = False) -> Figure:
    """*plot_qn_topology()* queueing-network topology for one or N scenarios; nodes coloured by `rho`, edges labelled with routing probabilities.

    Single-scenario callers may pass scalars (`rout`, `nds`, `name`, `nets`) directly; multi-scenario callers pass parallel lists. The body grid is `(1, K)` where K is the number of scenarios. A shared BFS layout and shared rho colourbar keep the panels visually comparable. Single-scenario layouts route the per-node QN metrics table into the footer; multi-scenario keeps the footer empty (panels share the colourbar instead).

    Args:
        routs (Union[List[np.ndarray], np.ndarray]): per-scenario routing matrices, or a single matrix.
        ndss (Union[List[pd.DataFrame], pd.DataFrame]): per-scenario node frames, or a single frame.
        names (Optional[Union[List[str], str]]): per-scenario display names. Single scenario may pass a string. Defaults to `[""]`.
        nets (Optional[Union[List[pd.DataFrame], pd.DataFrame]]): per-scenario network-wide frames from `aggregate_net()`. When given, each panel gets a network summary overlay.
        glossary (Optional[List[str]]): parameter glossary lines (LaTeX OK) drawn once on the first panel; defaults to `QN_GLOSSARY_DEFAULT`. Pass `[]` to suppress.
        nd_names (Optional[List[str]]): per-node display names. Defaults to the first frame's `key` column.
        layout (Optional[FigureLayout]): full layout override.
        title (Optional[str]): figure title.
        file_path (Optional[str]): directory to save into.
        fname (Optional[str]): filename stem; both PNG and SVG written.
        verbose (bool): if True, prints one save-path message per format.

    Raises:
        ValueError: If the parallel lists disagree on length.

    Returns:
        Figure: the matplotlib figure.

    Example::

        # single-scenario (scalars, auto-wrapped)
        plot_qn_topology(rout, nds, "baseline", nets=net,
                         file_path="data/img/analytic/baseline",
                         fname="topology")

        # N-scenario row (parallel lists)
        plot_qn_topology([rout1, rout2], [nds1, nds2], ["baseline", "aggregate"],
                         nets=[net1, net2],
                         file_path="data/img/analytic",
                         fname="topology_compare")
    """
    _routs_list, _ndss_list, _names_list, _nets_list = _normalise_qn_lists(
        routs, ndss, names, nets)
    _validate_parallel_lists(_routs_list, _ndss_list, _names_list, _nets_list)

    _k = len(_routs_list)
    _resolved_names = _resolve_node_names(_ndss_list, nd_names)
    _pos = _bfs_layout_shared(_routs_list)

    _shared_rho_max: Optional[float] = None
    if all("rho" in _df.columns for _df in _ndss_list):
        _shared_rho_max = max(float(_df["rho"].max()) for _df in _ndss_list)
        _shared_rho_max = max(_shared_rho_max, 1e-9)

    # single-scenario default routes the per-node table into the footer; multi-scenario keeps the footer empty so the panels share the colourbar instead
    _is_single = (_k == 1)
    if _is_single:
        _default_footer_h = 0.30
        _default_footer_kind = "table"
        # generous canvas (22" wide) but trimmed height so the title strip, body, and table sit tight against each other; combined with outer_hspace near zero this removes the dead band between sections.
        _fig_w = 22.0
        _fig_h = 24.0
    else:
        _default_footer_h = 0.0
        _default_footer_kind = "none"
        _fig_w = max(14.0, 12.0 * _k)
        _fig_h = 14.0

    # title strip + body + table sit flush; outer_hspace kept near zero so the title sits just above the graph and the table just below it
    _default_layout = FigureLayout(title=title,
                                   title_h=0.05,
                                   body=BodySpec(shape=(1, _k),
                                                 panel_kind="2d",
                                                 wspace=0.20),
                                   footer_h=_default_footer_h,
                                   footer_kind=_default_footer_kind,
                                   figsize=(_fig_w, _fig_h),
                                   outer_hspace=0.04)
    _layout = _pick_layout(layout, _default_layout)

    _fig, _regions = build_stacked_figure(_layout)
    _axes = _regions["body_axes"]

    _gloss = glossary if glossary is not None else QN_GLOSSARY_DEFAULT
    for _i, (_ax, _rout, _nds, _name) in enumerate(zip(_axes,
                                                       _routs_list,
                                                       _ndss_list,
                                                       _names_list)):
        _graph = _build_topology_graph(_rout, _resolved_names)
        _draw_qn_topology_axis(_ax, _graph, _pos, _nds, _resolved_names,
                               rho_max=_shared_rho_max)
        if _name:
            _ax.set_title(_name, fontsize=13, **_LBL_STYLE)
        if _i == 0 and _gloss:
            _add_param_glossary(_ax, _gloss, corner="lower right")
        if _nets_list is not None:
            _add_qn_network_summary(_ax,
                                    _nets_list[_i].iloc[0],
                                    corner="upper right")

    if _shared_rho_max is not None:
        _add_topology_colorbar(_fig, _axes, 0.0, _shared_rho_max,
                               r"Utilisation $(\rho)$")

    _footer_ax = _regions["footer_ax"]
    if _is_single and _footer_ax is not None:
        _add_qn_node_table(_footer_ax, _ndss_list[0], _resolved_names)

    _save_figure(_fig, file_path, fname or "qn_topology", verbose=verbose)
    return _fig


def plot_dim_topology(rout: np.ndarray,
                      nds: pd.DataFrame,
                      *,
                      color_by: str = "eta",
                      glossary: Optional[List[str]] = None,
                      nd_names: Optional[List[str]] = None,
                      layout: Optional[FigureLayout] = None,
                      title: Optional[str] = None,
                      file_path: Optional[str] = None,
                      fname: Optional[str] = None,
                      verbose: bool = False) -> Figure:
    """*plot_dim_topology()* dimensionless topology for one scenario; nodes coloured by a chosen coefficient column (default `eta`, min-max normalised), labelled with the artifact key + its theta value.

    The footer carries a per-node coefficient table (Component, theta, sigma, eta, phi).

    Args:
        rout (np.ndarray): `(n, n)` routing-probability matrix.
        nds (pd.DataFrame): per-node coefficients frame (output of `coefs_to_nodes()`).
        color_by (str): coefficient column driving node colours. Defaults to `"eta"`.
        glossary (Optional[List[str]]): parameter glossary lines; defaults to `DIM_GLOSSARY_DEFAULT`. Pass `[]` to suppress.
        nd_names (Optional[List[str]]): per-node display names. Defaults to `nds["key"]`.
        layout (Optional[FigureLayout]): full layout override.
        title (Optional[str]): figure title.
        file_path (Optional[str]): directory to save into.
        fname (Optional[str]): filename stem; both PNG and SVG written.
        verbose (bool): if True, prints one save-path message per format.

    Returns:
        Figure: the matplotlib figure.

    Example::

        plot_dim_topology(rout, nds, color_by="eta",
                          title="Dimensionless topology (baseline)",
                          file_path="data/img/dimensional/baseline",
                          fname="topology")
    """
    _resolved_names = _resolve_node_names([nds], nd_names)
    _graph = _build_topology_graph(rout, _resolved_names)
    _pos = nx.bfs_layout(_graph, start=0)

    # mirrors plot_qn_topology single-scenario layout: title flush with body, table flush below
    _default_layout = FigureLayout(title=title,
                                   title_h=0.05,
                                   body=BodySpec(shape=(1, 1),
                                                 panel_kind="2d"),
                                   footer_h=0.30,
                                   footer_kind="table",
                                   figsize=(22, 24),
                                   outer_hspace=0.04)
    _layout = _pick_layout(layout, _default_layout)

    _fig, _regions = build_stacked_figure(_layout)
    _ax = _regions["body_axes"][0]

    _draw_dim_topology_axis(_ax, _graph, _pos, nds, _resolved_names,
                            color_by=color_by)

    if color_by in nds.columns:
        _vals = nds[color_by].to_numpy(dtype=float)
        _sym = _DIM_COEF_SYMS.get(color_by, color_by)
        _add_topology_colorbar(_fig, _ax,
                               float(_vals.min()), float(_vals.max()),
                               rf"${_sym}$ (dimensionless)")

    _add_dim_network_summary(_ax, nds, corner="upper right")
    _gloss = glossary if glossary is not None else DIM_GLOSSARY_DEFAULT
    if _gloss:
        _add_param_glossary(_ax, _gloss, corner="lower right")

    _footer_ax = _regions["footer_ax"]
    if _footer_ax is not None:
        _add_dim_node_table(_footer_ax, nds, _resolved_names)

    _save_figure(_fig, file_path, fname or "dim_topology", verbose=verbose)
    return _fig


# ---------------------------------------------------------------------------
# Public plotters -- heatmaps + delta + CI
# ---------------------------------------------------------------------------


def plot_node_heatmap(ndss: List[pd.DataFrame],
                      names: List[str],
                      nodes: List[str],
                      *,
                      metrics: Optional[List[str]] = None,
                      labels: Optional[List[str]] = None,
                      cname: str = "key",
                      layout: Optional[FigureLayout] = None,
                      title: Optional[str] = None,
                      file_path: Optional[str] = None,
                      fname: Optional[str] = None,
                      verbose: bool = False) -> Figure:
    """*plot_node_heatmap()* per-node heatmap across N scenarios, one body row per scenario, with per-metric normalisation so scenarios compare visually.

    Args:
        ndss (List[pd.DataFrame]): per-scenario node frames.
        names (List[str]): per-scenario display names.
        nodes (List[str]): node identifiers (rows of each heatmap).
        metrics (Optional[List[str]]): columns to include. Defaults to every numeric column in the first frame.
        labels (Optional[List[str]]): display labels for the metric columns.
        cname (str): column holding the node identifier. Defaults to `"key"`.
        layout (Optional[FigureLayout]): full layout override.
        title (Optional[str]): figure title.
        file_path (Optional[str]): directory to save into.
        fname (Optional[str]): filename stem; both PNG and SVG written.
        verbose (bool): if True, prints one save-path message per format.

    Raises:
        ValueError: If `ndss` is empty or its length does not match `names`.

    Returns:
        Figure: the matplotlib figure.

    Example::

        plot_node_heatmap([nds_baseline, nds_aggregate],
                          ["baseline", "aggregate"],
                          nodes=["TAS_{1}", "MAS_{1}", "AS_{1}"],
                          metrics=["rho", "L", "W"],
                          file_path="data/img/analytic",
                          fname="heatmap_compare")
    """
    if not isinstance(ndss, list) or len(ndss) == 0:
        raise ValueError("ndss must be a non-empty list of DataFrames")
    if not isinstance(names, list) or len(names) != len(ndss):
        _msg = f"names length ({len(names)}) must match ndss "
        _msg += f"length ({len(ndss)})"
        raise ValueError(_msg)

    _metrics = _resolve_metrics(ndss[0], metrics)
    if metrics is None and "node" in _metrics:
        _metrics.remove("node")
    _labels = _resolve_labels(_metrics, labels)

    # global per-metric min/max for shared normalisation
    _minmax: Dict[str, Tuple[float, float]] = {}
    for _m in _metrics:
        _vals: List[float] = []
        for _df in ndss:
            _sub = _df[_df[cname].isin(nodes)]
            _vals.extend(_sub[_m].dropna().tolist())
        _minmax[_m] = (float(np.min(_vals)), float(np.max(_vals)))

    _k = len(ndss)
    # 50 % less title->body spacing per request: 0.32 * 0.50 = 0.16; +10 % MORE inter-panel hspace inside the body: 0.36 * 1.10 = 0.40
    _default_layout = FigureLayout(title=title,
                                   title_h=0.05,
                                   body=BodySpec(shape=(_k, 1),
                                                 panel_kind="2d",
                                                 hspace=0.40),
                                   footer_h=0.0,
                                   footer_kind="none",
                                   figsize=(max(12, len(_metrics) * 1.4),
                                            4 * _k + 1),
                                   outer_hspace=0.16)
    _layout = _pick_layout(layout, _default_layout)

    _fig, _regions = build_stacked_figure(_layout)
    _axes = _regions["body_axes"]

    for _df, _name, _ax in zip(ndss, names, _axes):
        _filt = _df[_df[cname].isin(nodes)].copy()
        if _filt.empty:
            _ax.text(0.5, 0.5, f"No data for {_name}",
                     ha="center", fontsize=14)
            continue

        _rows = []
        for _node in nodes:
            _row_df = _filt[_filt[cname] == _node]
            if _row_df.empty:
                continue
            _row: Dict[str, Any] = {cname: _node}
            for _m in _metrics:
                if _m in _row_df.columns:
                    _row[_m] = float(_row_df[_m].iloc[0])
                else:
                    _row[_m] = np.nan
            _rows.append(_row)
        if not _rows:
            _ax.text(0.5, 0.5, f"No matching nodes for {_name}",
                     ha="center", fontsize=14)
            continue

        _plot_df = pd.DataFrame(_rows).set_index(cname)
        _norm = _plot_df.copy()
        for _m in _metrics:
            _lo, _hi = _minmax[_m]
            if _hi > _lo:
                _norm[_m] = (_plot_df[_m] - _lo) / (_hi - _lo)
            else:
                _norm[_m] = 0.5

        sns.heatmap(_norm,
                    ax=_ax,
                    cmap=_HEATMAP_CMAP,
                    center=0.5,
                    vmin=0,
                    vmax=1,
                    annot=_plot_df,
                    fmt=".2e",
                    linewidths=0.5,
                    cbar_kws={"shrink": 0.8})

        _ax.set_title(f"{_name} per-node metrics",
                      fontsize=13, **_LBL_STYLE)
        _ax.set_xticklabels(_labels,
                            rotation=45,
                            ha="right",
                            fontweight="bold",
                            color=_TEXT_BLACK)
        _ax.set_yticklabels(
            [f"${_t.get_text()}$" for _t in _ax.get_yticklabels()],
            color=_TEXT_BLACK)

    _save_figure(_fig, file_path, fname or "heatmap", verbose=verbose)
    return _fig


def plot_node_diffmap(deltas: pd.DataFrame,
                      nodes: List[str],
                      *,
                      metrics: Optional[List[str]] = None,
                      labels: Optional[List[str]] = None,
                      cname: str = "key",
                      layout: Optional[FigureLayout] = None,
                      title: Optional[str] = None,
                      file_path: Optional[str] = None,
                      fname: Optional[str] = None,
                      verbose: bool = False) -> Figure:
    """*plot_node_diffmap()* per-node delta heatmap (single panel) coloured by the delta value on a diverging symmetric colour scale so 0 % sits at the colormap midpoint.

    Args:
        deltas (pd.DataFrame): delta frame with one row per node; the `cname` column identifies the node and the metric columns hold per-node percent changes.
        nodes (List[str]): node identifiers to include.
        metrics (Optional[List[str]]): columns to plot. Defaults to every numeric column.
        labels (Optional[List[str]]): display labels for the metric columns.
        cname (str): column holding the node identifier. Defaults to `"key"`.
        layout (Optional[FigureLayout]): full layout override.
        title (Optional[str]): figure title.
        file_path (Optional[str]): directory to save into.
        fname (Optional[str]): filename stem; both PNG and SVG written.
        verbose (bool): if True, prints one save-path message per format.

    Raises:
        ValueError: If `cname` or any of `metrics` is missing from `deltas`.

    Returns:
        Figure: the matplotlib figure.

    Example::

        plot_node_diffmap(deltas, nodes=["TAS_{1}", "MAS_{1}"],
                          metrics=["rho", "L", "W"],
                          title="aggregate vs baseline",
                          file_path="data/img/analytic/aggregate",
                          fname="nd_diffmap_vs_baseline")
    """
    if cname not in deltas.columns:
        raise ValueError(f"Node-name column {cname!r} not found in deltas")

    _metrics = _resolve_metrics(deltas, metrics)
    if cname in _metrics:
        _metrics.remove(cname)
    _missing = [_m for _m in _metrics if _m not in deltas.columns]
    if _missing:
        raise ValueError(f"Missing metric columns in deltas: {_missing}")
    _labels = _resolve_labels(_metrics, labels)

    # build the matrix in the caller's exact node order; nodes missing from `deltas` get a NaN row so the heatmap height is always len(nodes), not len(matched_nodes). The downstream `_mask = np.isnan(_matrix)` already suppresses text-drawing on NaN cells, so missing-node rows render as masked colourbar fill.
    _by_node = {row[cname]: row for _, row in deltas.iterrows()}
    _matrix = np.full((len(nodes), len(_metrics)), np.nan, dtype=float)
    for _i, _node in enumerate(nodes):
        _row = _by_node.get(_node)
        if _row is None:
            continue
        for _j, _m in enumerate(_metrics):
            _v = _row.get(_m)
            if _v is not None and not (isinstance(_v, float) and np.isnan(_v)):
                _matrix[_i, _j] = float(_v)
    _nd_names = list(nodes)

    if np.all(np.isnan(_matrix)):
        _msg = "No matching nodes found in deltas; "
        _msg += f"available: {list(deltas[cname].unique())}"
        raise ValueError(_msg)

    _vmax = float(np.nanmax(np.abs(_matrix)))
    if np.isnan(_vmax) or _vmax == 0:
        _vmax = 1.0
    _vmin = -_vmax

    # 50 % less title->body spacing per request: 0.28 * 0.50 = 0.14
    _default_layout = FigureLayout(title=title,
                                   title_h=0.06,
                                   body=BodySpec(shape=(1, 1),
                                                 panel_kind="2d"),
                                   footer_h=0.0,
                                   footer_kind="none",
                                   figsize=(max(10, len(_metrics) * 1.6),
                                            len(_nd_names) * 0.55 + 3),
                                   outer_hspace=0.14)
    _layout = _pick_layout(layout, _default_layout)

    _fig, _regions = build_stacked_figure(_layout)
    _ax = _regions["body_axes"][0]

    _mask = np.isnan(_matrix)
    _im = _ax.imshow(_matrix,
                     cmap=_HEATMAP_CMAP,
                     aspect="auto",
                     vmin=_vmin,
                     vmax=_vmax)
    _cbar = _fig.colorbar(_im, ax=_ax, pad=0.02)
    _cbar.set_label("Relative Change (%)",
                    rotation=270,
                    labelpad=18,
                    color=_TEXT_BLACK,
                    fontsize=12,
                    fontweight="bold")
    _cbar.ax.tick_params(colors=_TEXT_BLACK)

    for _i in range(len(_nd_names)):
        for _j in range(len(_metrics)):
            if _mask[_i, _j]:
                continue
            _v = _matrix[_i, _j]
            if abs(_v) >= 0.1:
                _text = f"{_v:.2f}"
            else:
                _text = f"{_v:.3f}"
            _ax.text(_j, _i, _text,
                     ha="center",
                     va="center",
                     color=_TEXT_BLACK,
                     fontweight="bold",
                     fontsize=10)

    _ax.set_xticks(np.arange(len(_metrics)))
    _ax.set_yticks(np.arange(len(_nd_names)))
    _ax.set_xticklabels(_labels,
                        rotation=45,
                        ha="right",
                        fontweight="bold",
                        color=_TEXT_BLACK)
    _ax.set_yticklabels([f"${_n}$" for _n in _nd_names], color=_TEXT_BLACK)
    _ax.set_xticks(np.arange(-0.5, len(_metrics), 1), minor=True)
    _ax.set_yticks(np.arange(-0.5, len(_nd_names), 1), minor=True)
    _ax.grid(which="minor", color="white", linestyle="-", linewidth=1.5)
    _ax.tick_params(which="minor", length=0)

    _save_figure(_fig, file_path, fname or "nd_diffmap", verbose=verbose)
    return _fig


def plot_node_ci(nds: pd.DataFrame,
                 *,
                 metric: str = "rho",
                 reference: Optional[pd.DataFrame] = None,
                 reference_name: str = "analytic",
                 stochastic_name: str = "stochastic",
                 metric_label: Optional[str] = None,
                 confidence: float = 0.95,
                 reps: Optional[int] = None,
                 layout: Optional[FigureLayout] = None,
                 title: Optional[str] = None,
                 file_path: Optional[str] = None,
                 fname: Optional[str] = None,
                 verbose: bool = False) -> Figure:
    """*plot_node_ci()* per-node mean with a confidence-interval band; optional reference overlay (e.g. analytic vs stochastic cross-method check).

    The CI half-width is `z * sigma / sqrt(reps)` when `reps` is given (a proper CI on the mean), else `z * sigma` (a one-z band of rep-to-rep spread). `z` is pulled from `_Z_SCORES[confidence]`.

    Args:
        nds (pd.DataFrame): stochastic per-node frame; must have a `key` column, the `<metric>` column (mean across reps), and its `<metric>_std` companion.
        metric (str): which metric to plot (default `"rho"`).
        reference (Optional[pd.DataFrame]): optional reference frame (analytic, etc.) with the same `key` + `<metric>` columns.
        reference_name (str): legend label for the reference series.
        stochastic_name (str): legend label for the stochastic series.
        metric_label (Optional[str]): display label for the y-axis. Defaults to `"${metric}$"`.
        confidence (float): confidence level in {0.90, 0.95, 0.99}.
        reps (Optional[int]): replication count; when given, scales the CI half-width as `z * sigma / sqrt(reps)`.
        layout (Optional[FigureLayout]): full layout override.
        title (Optional[str]): figure title.
        file_path (Optional[str]): directory to save into.
        fname (Optional[str]): filename stem; both PNG and SVG written.
        verbose (bool): if True, prints one save-path message per format.

    Raises:
        ValueError: If `confidence` is not in `_Z_SCORES`, or the required columns are missing.

    Returns:
        Figure: the matplotlib figure.

    Example::

        plot_node_ci(nds_stochastic, metric="rho",
                     reference=nds_analytic, reps=20,
                     title="Per-node rho (95% CI)",
                     file_path="data/img/stochastic/baseline",
                     fname="rho_ci")
    """
    _std_col = f"{metric}_std"
    for _col in ("key", metric, _std_col):
        if _col not in nds.columns:
            raise ValueError(f"plot_node_ci: missing required column {_col!r} in nds")

    if confidence not in _Z_SCORES:
        _msg = f"plot_node_ci: unsupported confidence={confidence!r}; "
        _msg += f"allowed: {sorted(_Z_SCORES.keys())}"
        raise ValueError(_msg)
    _z = _Z_SCORES[confidence]

    _keys = nds["key"].tolist()
    _means = nds[metric].to_numpy(dtype=float)
    _stds = nds[_std_col].to_numpy(dtype=float)

    if reps is not None and reps > 0:
        _halfwidth = _z * _stds / np.sqrt(reps)
        _band_label = rf"{int(confidence * 100)}% CI (reps={reps})"
    else:
        _halfwidth = _z * _stds
        _band_label = rf"$\pm {_z:.2f}\sigma$ band"

    _default_layout = FigureLayout(title=title,
                                   title_h=0.06,
                                   body=BodySpec(shape=(1, 1),
                                                 panel_kind="2d"),
                                   footer_h=0.0,
                                   footer_kind="none",
                                   figsize=(max(10, 0.7 * len(_keys) + 3), 7))
    _layout = _pick_layout(layout, _default_layout)

    _fig, _regions = build_stacked_figure(_layout)
    _ax = _regions["body_axes"][0]
    _x = np.arange(len(_keys))

    _ax.errorbar(_x, _means, yerr=_halfwidth,
                 fmt="o",
                 capsize=5,
                 capthick=1.5,
                 elinewidth=1.5,
                 markersize=8,
                 color=_BAR_BLUE,
                 ecolor=_TEXT_BLACK,
                 label=f"{stochastic_name} mean  ({_band_label})")

    if reference is not None:
        if "key" not in reference.columns:
            raise ValueError("plot_node_ci: reference frame missing 'key' column")
        if metric not in reference.columns:
            raise ValueError(f"plot_node_ci: reference frame missing {metric!r} column")
        _ref_by_key = dict(zip(reference["key"], reference[metric]))
        _ref_vals = [_ref_by_key.get(_k, np.nan) for _k in _keys]
        _ax.plot(_x, _ref_vals,
                 linestyle="none",
                 marker="x",
                 markersize=10,
                 markeredgewidth=2,
                 color=_BAR_ORANGE,
                 label=f"{reference_name} mean")

    _ax.set_xticks(_x)
    _ax.set_xticklabels([f"${_k}$" for _k in _keys],
                        rotation=45,
                        ha="right",
                        fontweight="bold",
                        color=_TEXT_BLACK)
    _ax.set_ylabel(metric_label or f"${metric}$",
                   color=_TEXT_BLACK,
                   fontsize=13,
                   fontweight="bold")
    _ax.grid(**_GRID_BARS)
    _ax.legend(loc="best", frameon=True, fancybox=True, shadow=True)

    _save_figure(_fig, file_path, fname or "node_ci", verbose=verbose)
    return _fig


# ---------------------------------------------------------------------------
# Public plotters -- network-wide (architecture) bar charts
# ---------------------------------------------------------------------------


def plot_arch_bars(nets: List[pd.DataFrame],
                   names: List[str],
                   *,
                   metrics: Optional[List[str]] = None,
                   labels: Optional[List[str]] = None,
                   logscale: bool = True,
                   layout: Optional[FigureLayout] = None,
                   title: Optional[str] = None,
                   file_path: Optional[str] = None,
                   fname: Optional[str] = None,
                   verbose: bool = False) -> Figure:
    """*plot_arch_bars()* grouped-bar chart of network-wide (architecture) metrics across N scenarios.

    Args:
        nets (List[pd.DataFrame]): per-scenario single-row network frames.
        names (List[str]): per-scenario display names.
        metrics (Optional[List[str]]): columns to plot. Defaults to every numeric column in the first frame.
        labels (Optional[List[str]]): display labels for the metric columns.
        logscale (bool): if True, use a log y-axis (helps when metrics span several orders of magnitude).
        layout (Optional[FigureLayout]): full layout override.
        title (Optional[str]): figure title.
        file_path (Optional[str]): directory to save into.
        fname (Optional[str]): filename stem; both PNG and SVG written.
        verbose (bool): if True, prints one save-path message per format.

    Raises:
        ValueError: If `nets` is empty or its length does not match `names`.

    Returns:
        Figure: the matplotlib figure.

    Example::

        plot_arch_bars([net_baseline, net_aggregate],
                       ["baseline", "aggregate"],
                       title="Network-wide metrics",
                       file_path="data/img/analytic",
                       fname="arch_bars")
    """
    if not isinstance(nets, list) or len(nets) == 0:
        raise ValueError("nets must be a non-empty list of DataFrames")
    if not isinstance(names, list) or len(names) != len(nets):
        _msg = f"names length ({len(names)}) must match nets "
        _msg += f"length ({len(nets)})"
        raise ValueError(_msg)

    _metrics = _resolve_metrics(nets[0], metrics)
    _labels = _resolve_labels(_metrics, labels)

    _k = len(nets)
    _group_w = 1.2
    _bar_w = _group_w / (_k * 1.3)
    _bar_space = _bar_w * 0.2
    _group_space = 1.5

    _positions: List[List[float]] = []
    for _i in range(_k):
        if _i == 0:
            _positions.append([_j * _group_space for _j in range(len(_metrics))])
        else:
            _positions.append([_x + _bar_w + _bar_space for _x in _positions[_i - 1]])

    _scenario_colors = _generate_color_map(names)

    # 50 % less title<->body spacing per request: 0.24 * 0.50 = 0.12
    _default_layout = FigureLayout(title=title,
                                   title_h=0.10,
                                   body=BodySpec(shape=(1, 1),
                                                 panel_kind="2d"),
                                   footer_h=0.22,
                                   footer_kind="legend",
                                   figsize=(max(14, len(_metrics) * 2.0), 13),
                                   outer_hspace=0.12)
    _layout = _pick_layout(layout, _default_layout)

    _fig, _regions = build_stacked_figure(_layout)
    _ax = _regions["body_axes"][0]

    for _i, (_df, _name) in enumerate(zip(nets, names)):
        _values: List[float] = []
        for _m in _metrics:
            if _m in _df.columns:
                _values.append(float(_df[_m].iloc[0]))
            else:
                _values.append(np.nan)
        _ax.bar(_positions[_i], _values,
                width=_bar_w,
                label=_name,
                color=_scenario_colors[_i],
                alpha=0.85,
                edgecolor="black",
                linewidth=0.5)

        for _j, _v in enumerate(_values):
            if np.isnan(_v):
                continue
            _text = _format_value(_v)
            _y = _v * 1.05
            if _v >= 0:
                _va = "bottom"
            else:
                _va = "top"
            _ax.text(_positions[_i][_j], _y, _text,
                     ha="center",
                     va=_va,
                     fontsize=10,
                     rotation=90,
                     fontweight="light",
                     color=_TEXT_BLACK,
                     bbox=dict(boxstyle="round,pad=0.2",
                               fc="white",
                               ec="none",
                               alpha=0.75))

    if logscale:
        _ax.set_yscale("log")
    _ax.grid(**_GRID_BARS)

    # headroom for the rotated value labels above each bar (linear scale only; log scale auto-pads via decade boundaries)
    if not logscale:
        _ymin, _ymax = _ax.get_ylim()
        _ax.set_ylim(_ymin, _ymax * 1.30)

    _centers = [
        _positions[0][_i] + (_positions[-1][_i] - _positions[0][_i]) / 2
        for _i in range(len(_metrics))
    ]
    _ax.set_xticks(_centers)
    _ax.set_xticklabels(_labels,
                        rotation=30,
                        ha="right",
                        fontweight="bold",
                        color=_TEXT_BLACK)

    _yaxis_label = "Value"
    if logscale:
        _yaxis_label += " (log scale)"
    _ax.set_ylabel(_yaxis_label, **_LBL_STYLE)

    # lift legend to footer via the shared helper
    _h, _l = _ax.get_legend_handles_labels()
    if _l:
        _legend_ncol = min(len(_l), 8)
    else:
        _legend_ncol = None
    render_footer_legend(_regions["footer_ax"],
                         _h,
                         _l,
                         ncol=_legend_ncol,
                         title="Scenario")

    _save_figure(_fig, file_path, fname or "arch_bars", verbose=verbose)
    return _fig


def plot_arch_delta(deltas: pd.DataFrame,
                    *,
                    metrics: Optional[List[str]] = None,
                    labels: Optional[List[str]] = None,
                    layout: Optional[FigureLayout] = None,
                    title: Optional[str] = None,
                    file_path: Optional[str] = None,
                    fname: Optional[str] = None,
                    verbose: bool = False) -> Figure:
    """*plot_arch_delta()* percent-change bar chart for the network-wide (architecture) deltas between two scenarios.

    Colouring is sign-only (R15): negative deltas (decrease) draw pastel blue, positive deltas (increase) draw pastel orange. Whether a decrease / increase is desirable is a domain concern left to the caller.

    Args:
        deltas (pd.DataFrame): single-row frame with one column per metric; values are fractional deltas (e.g. `0.05` = +5%).
        metrics (Optional[List[str]]): columns to plot. Defaults to every numeric column.
        labels (Optional[List[str]]): display labels for the columns.
        layout (Optional[FigureLayout]): full layout override.
        title (Optional[str]): figure title.
        file_path (Optional[str]): directory to save into.
        fname (Optional[str]): filename stem; both PNG and SVG written.
        verbose (bool): if True, prints one save-path message per format.

    Returns:
        Figure: the matplotlib figure.

    Example::

        plot_arch_delta(net_deltas,
                        title="aggregate vs baseline",
                        file_path="data/img/analytic/aggregate",
                        fname="arch_delta_vs_baseline")
    """
    _metrics = _resolve_metrics(deltas, metrics)
    _labels = _resolve_labels(_metrics, labels)
    _values = [float(deltas[_m].iloc[0]) * 100 for _m in _metrics]

    _colors: List[str] = []
    for _v in _values:
        if _v < 0:
            _colors.append(_BAR_BLUE)
        else:
            _colors.append(_BAR_ORANGE)

    # 30 % less title->body spacing per request: 0.40 * 0.70 = 0.28
    _default_layout = FigureLayout(title=title,
                                   title_h=0.06,
                                   body=BodySpec(shape=(1, 1),
                                                 panel_kind="2d"),
                                   footer_h=0.0,
                                   footer_kind="none",
                                   figsize=(12, 8),
                                   outer_hspace=0.28)
    _layout = _pick_layout(layout, _default_layout)

    _fig, _regions = build_stacked_figure(_layout)
    _ax = _regions["body_axes"][0]

    _bars = _ax.bar(range(len(_metrics)), _values,
                    color=_colors,
                    edgecolor="black",
                    linewidth=0.5,
                    alpha=0.85)

    for _b, _v in zip(_bars, _values):
        if abs(_b.get_height()) >= 1:
            _y = _b.get_height() / 2
        else:
            _y = _b.get_height()
        if _v >= 0:
            _va = "bottom"
        else:
            _va = "top"
        _ax.text(_b.get_x() + _b.get_width() / 2.0, _y,
                 f"{_v:.2f}%",
                 ha="center",
                 va=_va,
                 fontsize=11,
                 fontweight="light",
                 color=_TEXT_BLACK)

    _ax.axhline(y=0, color="black", linestyle="-", alpha=0.3)
    _ax.set_xticks(range(len(_metrics)))
    _ax.set_xticklabels(_labels,
                        rotation=30,
                        ha="right",
                        fontweight="bold",
                        color=_TEXT_BLACK)
    _ax.set_ylabel("Percent change (%)", **_LBL_STYLE)
    _ax.grid(**_GRID_BARS)

    _legend = [
        mpatches.Patch(facecolor=_BAR_BLUE, alpha=0.85, label="Decrease"),
        mpatches.Patch(facecolor=_BAR_ORANGE, alpha=0.85, label="Increase"),
    ]
    _ax.legend(handles=_legend, loc="best")

    _y_lo = min(min(_values) * 1.1, -2.0)
    _y_hi = max(max(_values) * 1.1, 2.0)
    _ax.set_ylim(_y_lo, _y_hi)

    _save_figure(_fig, file_path, fname or "arch_delta", verbose=verbose)
    return _fig

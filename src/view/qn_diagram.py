# -*- coding: utf-8 -*-
"""
Module qn_diagram.py
====================

Queue-network visualisation for the CS-01 TAS case study.

Five plotters with a uniform parameter-IO convention (keyword-only args after the required positional inputs; every plotter returns the `matplotlib.figure.Figure` and persists to disk when both `file_path` and `fname` are supplied):

    - `plot_qn_topology(rout, nds, ...)` single-scenario architecture diagram (topology + rho colouring + edge labels).
    - `plot_qn_topology_grid(routs, ndss, names, ...)` N scenarios arranged in a row of topologies with a shared rho colourbar.
    - `plot_nd_heatmap(ndss, names, nodes, ...)` per-node heatmap across N scenarios; one subplot per scenario.
    - `plot_net_bars(nets, names, ...)` network-wide grouped-bar chart across N scenarios.
    - `plot_net_delta(deltas, ...)` network-wide percent-change bar chart between two scenarios.

*IMPORTANT:* node colouring uses `coolwarm` (cool = low rho, warm = high rho) so the hottest node is visually obvious; the heatmap uses `viridis` for per-metric normalised comparison across scenarios.

# TODO: port `plot_nd_diffmap` (per-node delta heatmap) from
#       `__OLD__/src/view/plots.py` once the comparison method needs it.
"""
# native python modules
# forward references + postpone eval type hints
from __future__ import annotations

import os

# data types
from typing import List, Optional

# scientific stack
import matplotlib.pyplot as plt
import networkx as nx
import numpy as np
import pandas as pd
import seaborn as sns
from matplotlib import cm
from matplotlib.figure import Figure


# -- Shared styling constants (reused across every plotter) --
_GRID_STYLE = dict(axis="y", linestyle="--", alpha=0.7)
_LBL_STYLE = dict(fontweight="bold", color="black")
_TITLE_STYLE = dict(fontsize=14, fontweight="bold", pad=20)
_SUPTITLE_STYLE = dict(fontsize=16, fontweight="bold")

# bar chart colours for the delta view
_BAR_GREEN = "#4CAF50"   # improvement
_BAR_RED = "#FF5252"     # degradation

# colourmaps
_TOPOLOGY_CMAP = cm.coolwarm
_HEATMAP_CMAP = "viridis"
_BARS_CMAP_NAME = "tab10"


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------


def _save_figure(fig: Figure,
                 file_path: Optional[str],
                 fname: Optional[str],
                 verbose: bool = False) -> None:
    """*_save_figure()* persist the figure when both `file_path` and `fname` are given; no-op otherwise.

    Args:
        fig (Figure): matplotlib figure to save.
        file_path (Optional[str]): destination directory (created if missing).
        fname (Optional[str]): output filename (with extension).
        verbose (bool): if True, prints a one-line save message.

    Raises:
        ValueError: If `fig.savefig` fails.
    """
    if not (file_path and fname):
        return

    # ensure the destination directory exists
    os.makedirs(file_path, exist_ok=True)
    _full_path = os.path.join(file_path, fname)

    if verbose:
        print(f"Saving plot to: {_full_path}")

    try:
        fig.savefig(_full_path,
                    facecolor="white",
                    bbox_inches="tight",
                    dpi=300)
    except Exception as _e:
        _msg = f"Error saving plot: {_e}. "
        _msg += f"file_path: {file_path!r}, fname: {fname!r}"
        raise ValueError(_msg)

    if verbose:
        print(f"Plot saved successfully to: {_full_path}")


def _resolve_metrics(df: pd.DataFrame,
                     metrics: Optional[List[str]]) -> List[str]:
    """*_resolve_metrics()* default to every numeric column in `df` when `metrics` is None.
    """
    if metrics is not None:
        return list(metrics)
    return df.select_dtypes(include="number").columns.tolist()


def _resolve_labels(metrics: List[str],
                    labels: Optional[List[str]]) -> List[str]:
    """*_resolve_labels()* default `labels` to the metric names when the caller does not supply a custom mapping.
    """
    if labels is not None:
        return list(labels)
    return list(metrics)


def _format_value(value: float) -> str:
    """*_format_value()* pick a reasonable format string for a bar label based on the value magnitude.

    Args:
        value (float): numeric value to format.

    Returns:
        str: formatted string (scientific for very small or very large magnitudes, otherwise 2-3 decimal places).
    """
    if np.isnan(value):
        return "nan"
    _abs = abs(value)
    if _abs < 0.01:
        return f"{value:.2e}"
    if _abs < 1:
        return f"{value:.3f}"
    if _abs > 10000:
        return f"{value:.2e}"
    return f"{value:.2f}"


def _bfs_layout_shared(routs: List[np.ndarray]) -> dict:
    """*_bfs_layout_shared()* compute a single BFS layout over the union of all routing matrices so every subplot in a grid uses the same node positions.

    Args:
        routs (List[np.ndarray]): list of routing matrices (same N x N shape for every entry).

    Returns:
        dict: node-index -> (x, y) position dict from `networkx.bfs_layout(G, start=0)`.
    """
    _n = routs[0].shape[0]

    # build the superset graph: edge (i, j) present if ANY routing
    # matrix has P[i, j] > 0
    _union = nx.DiGraph()
    for _i in range(_n):
        _union.add_node(_i)
    for _r in routs:
        for _i in range(_n):
            for _j in range(_n):
                if _r[_i, _j] > 0:
                    _union.add_edge(_i, _j)

    return nx.bfs_layout(_union, start=0)


def _build_topology_graph(rout: np.ndarray,
                          nd_names: List[str]) -> nx.DiGraph:
    """*_build_topology_graph()* convert a routing matrix into a `networkx.DiGraph` with edge weights and display labels.

    Args:
        rout (np.ndarray): `(n, n)` routing probability matrix. nd_names (List[str]): per-node display names, aligned with the matrix row / column order.

    Returns:
        nx.DiGraph: directed graph with `weight` on every edge.
    """
    _n = rout.shape[0]
    _graph = nx.DiGraph()

    # add all nodes first so isolated ones still show up
    for _i in range(_n):
        _graph.add_node(_i, name=nd_names[_i])

    # add edges for every non-zero routing probability
    for _i in range(_n):
        for _j in range(_n):
            if rout[_i, _j] > 0:
                _graph.add_edge(_i, _j, weight=float(rout[_i, _j]))

    return _graph


def _draw_topology_axis(ax,
                        graph: nx.DiGraph,
                        pos: dict,
                        nds: pd.DataFrame,
                        nd_names: List[str],
                        edge_label_threshold: float = 0.01) -> None:
    """*_draw_topology_axis()* draw one queue-network topology into a given axis, coloured by `rho` when the column is present.

    Args:
        ax: matplotlib axis to draw into.
        graph (nx.DiGraph): prebuilt topology graph.
        pos (dict): BFS (or similar) layout positions.
        nds (pd.DataFrame): per-node metrics frame.
        nd_names (List[str]): display names aligned with the graph.
        edge_label_threshold (float): routing probabilities below this are drawn without a numeric label to keep the diagram readable.
    """
    _n = len(nd_names)

    # node colours from rho when available; solid sky-blue otherwise
    if "rho" in nds.columns:
        _rhos = nds["rho"].to_numpy(dtype=float)
        _node_colors = [_TOPOLOGY_CMAP(_r) for _r in _rhos]
    else:
        _node_colors = ["skyblue"] * _n

    # draw nodes, edges, and both label layers
    nx.draw_networkx_nodes(graph, pos,
                           node_size=1500,
                           node_color=_node_colors,
                           alpha=0.9,
                           ax=ax)
    nx.draw_networkx_edges(graph, pos,
                           width=1.5,
                           alpha=0.7,
                           edge_color="black",
                           arrows=True,
                           arrowsize=18,
                           arrowstyle="-|>",
                           connectionstyle="arc3,rad=0.2",
                           ax=ax)

    # edge labels only when the routing weight is visually meaningful
    _edge_lbl = {
        (_i, _j): f"{_d['weight']:.2f}"
        for _i, _j, _d in graph.edges(data=True)
        if _d["weight"] >= edge_label_threshold
    }
    nx.draw_networkx_edge_labels(graph, pos,
                                 edge_labels=_edge_lbl,
                                 font_size=10,
                                 font_color="black",
                                 font_weight="light",
                                 bbox=dict(facecolor="white",
                                           edgecolor="none",
                                           alpha=0.9,
                                           pad=0.3),
                                 label_pos=0.4,
                                 ax=ax)

    # node labels on top
    nx.draw_networkx_labels(graph, pos,
                            labels={_i: nd_names[_i] for _i in range(_n)},
                            font_size=11,
                            font_weight="bold",
                            ax=ax)

    # axis cosmetics: hide ticks, tighten margins
    ax.set_axis_off()


# ---------------------------------------------------------------------------
# Public plotters
# ---------------------------------------------------------------------------


def plot_qn_topology(rout: np.ndarray,
                     nds: pd.DataFrame,
                     *,
                     nd_names: Optional[List[str]] = None,
                     title: Optional[str] = None,
                     file_path: Optional[str] = None,
                     fname: Optional[str] = None,
                     verbose: bool = False) -> Figure:
    """*plot_qn_topology()* draw the queueing-network topology for one scenario, with nodes coloured by `rho` and edge labels showing routing probabilities.

    Args:
        rout (np.ndarray): `(n, n)` routing-probability matrix.
        nds (pd.DataFrame): per-node metrics frame aligned with `rout`. `rho` column drives node colouring when present.
        nd_names (Optional[List[str]]): per-node display names. Defaults to `nds["key"]` when present, else `"Node {i}"`.
        title (Optional[str]): figure title. Defaults to `"Queue-Network Topology"`.
        file_path (Optional[str]): directory to save the figure into. fname (Optional[str]): filename (with extension) for the save. verbose (bool): if True, prints a one-line save message.

    Returns:
        Figure: the matplotlib figure (caller decides whether to close or further mutate it).
    """
    _n = rout.shape[0]

    # resolve display names; prefer the `key` column when available
    if nd_names is None:
        if "key" in nds.columns:
            nd_names = nds["key"].tolist()
        else:
            nd_names = [f"Node {_i}" for _i in range(_n)]

    # build the topology and BFS layout from the entry node (0)
    _graph = _build_topology_graph(rout, nd_names)
    _pos = nx.bfs_layout(_graph, start=0)

    # create the figure + axis and delegate the drawing to the helper
    _fig, _ax = plt.subplots(figsize=(14, 9), facecolor="white")
    _ax.set_facecolor("white")
    _draw_topology_axis(_ax, _graph, _pos, nds, nd_names)

    _ax.set_title(title or "Queue-Network Topology", **_TITLE_STYLE)
    _fig.tight_layout()

    _save_figure(_fig, file_path, fname, verbose=verbose)
    return _fig


def plot_qn_topology_grid(routs: List[np.ndarray],
                          ndss: List[pd.DataFrame],
                          names: List[str],
                          *,
                          nd_names: Optional[List[str]] = None,
                          title: Optional[str] = None,
                          file_path: Optional[str] = None,
                          fname: Optional[str] = None,
                          verbose: bool = False) -> Figure:
    """*plot_qn_topology_grid()* draw N scenarios side-by-side with a shared BFS layout and a single rho colourbar.

    Args:
        routs (List[np.ndarray]): per-scenario routing matrices. ndss (List[pd.DataFrame]): per-scenario node frames (aligned with `routs` by index).
        names (List[str]): per-scenario display names for subplot titles.
        nd_names (Optional[List[str]]): per-node display names. Defaults to the first frame's `key` column when present.
        title (Optional[str]): overall figure title (suptitle).
        file_path (Optional[str]): directory to save into.
        fname (Optional[str]): filename (with extension).
        verbose (bool): if True, prints a one-line save message.

    Raises:
        ValueError: If the three lists do not have matching lengths.

    Returns:
        Figure: the matplotlib figure.
    """
    # validate the parallel-list inputs
    if not (len(routs) == len(ndss) == len(names)):
        _msg = "routs, ndss, and names must have matching lengths; "
        _msg += f"got {len(routs)}, {len(ndss)}, {len(names)}"
        raise ValueError(_msg)

    _k = len(routs)
    _n = routs[0].shape[0]

    # resolve display names from the first frame when none supplied
    if nd_names is None:
        if "key" in ndss[0].columns:
            nd_names = ndss[0]["key"].tolist()
        else:
            nd_names = [f"Node {_i}" for _i in range(_n)]

    # one shared BFS layout so every subplot uses the same positions
    _pos = _bfs_layout_shared(routs)

    # create the grid; width scales with the number of scenarios
    _fig, _axes = plt.subplots(1, _k,
                               figsize=(max(8, 7 * _k), 9),
                               facecolor="white")
    if _k == 1:
        _axes = [_axes]

    # draw each scenario into its own axis
    for _ax, _rout, _nds, _name in zip(_axes, routs, ndss, names):
        _ax.set_facecolor("white")
        _graph = _build_topology_graph(_rout, nd_names)
        _draw_topology_axis(_ax, _graph, _pos, _nds, nd_names)
        _ax.set_title(_name, fontsize=13, **_LBL_STYLE)

    # shared rho colourbar anchored to the right of the grid
    _sm = cm.ScalarMappable(cmap=_TOPOLOGY_CMAP,
                            norm=plt.Normalize(vmin=0.0, vmax=1.0))
    _sm.set_array([])
    _cbar = _fig.colorbar(_sm, ax=_axes, shrink=0.75, pad=0.02)
    _cbar.set_label("rho", **_LBL_STYLE)

    if title:
        _fig.suptitle(title, **_SUPTITLE_STYLE)

    _save_figure(_fig, file_path, fname, verbose=verbose)
    return _fig


def plot_nd_heatmap(ndss: List[pd.DataFrame],
                    names: List[str],
                    nodes: List[str],
                    *,
                    metrics: Optional[List[str]] = None,
                    labels: Optional[List[str]] = None,
                    cname: str = "key",
                    title: Optional[str] = None,
                    file_path: Optional[str] = None,
                    fname: Optional[str] = None,
                    verbose: bool = False) -> Figure:
    """*plot_nd_heatmap()* per-node heatmap across N scenarios, one subplot per scenario, with per-metric normalisation so scenarios can be compared visually.

    Args:
        ndss (List[pd.DataFrame]): per-scenario node frames.
        names (List[str]): per-scenario display names.
        nodes (List[str]): node identifiers (rows of the heatmap).
        metrics (Optional[List[str]]): columns to include. Defaults to every numeric column in the first frame.
        labels (Optional[List[str]]): display labels for the metric columns. Defaults to the metric names.
        cname (str): column holding the node identifier in each frame. Defaults to `"key"`.
        title (Optional[str]): overall figure title.
        file_path (Optional[str]): directory to save into.
        fname (Optional[str]): filename (with extension).
        verbose (bool): if True, prints a one-line save message.

    Raises:
        ValueError: If `ndss` is empty or its length does not match `names`.

    Returns:
        Figure: the matplotlib figure.
    """
    # validate the parallel-list inputs
    if not isinstance(ndss, list) or len(ndss) == 0:
        _msg = "ndss must be a non-empty list of DataFrames"
        raise ValueError(_msg)
    if not isinstance(names, list) or len(names) != len(ndss):
        _msg = f"names length ({len(names)}) must match ndss "
        _msg += f"length ({len(ndss)})"
        raise ValueError(_msg)

    # resolve metric / label defaults
    _metrics = _resolve_metrics(ndss[0], metrics)
    # drop the `node` column if the caller did not explicitly ask for it
    if metrics is None and "node" in _metrics:
        _metrics.remove("node")
    _labels = _resolve_labels(_metrics, labels)

    # per-metric global min / max across every scenario for shared normalisation
    _minmax = {}
    for _m in _metrics:
        _vals: List[float] = []
        for _df in ndss:
            _sub = _df[_df[cname].isin(nodes)]
            _vals.extend(_sub[_m].dropna().tolist())
        _minmax[_m] = (float(np.min(_vals)), float(np.max(_vals)))

    # one subplot row per scenario; vertical stack keeps node axis aligned
    _k = len(ndss)
    _fig, _axes = plt.subplots(_k, 1,
                               figsize=(max(12, len(_metrics) * 1.4), 4 * _k),
                               sharex=True,
                               constrained_layout=True,
                               facecolor="white")
    if _k == 1:
        _axes = [_axes]

    for _df, _name, _ax in zip(ndss, names, _axes):
        # filter and order rows by the requested node list
        _filt = _df[_df[cname].isin(nodes)].copy()
        if _filt.empty:
            _ax.text(0.5, 0.5, f"No data for {_name}",
                     ha="center", fontsize=14)
            continue

        # build the per-scenario matrix in the caller's node order
        _rows = []
        for _k_node in nodes:
            _row_df = _filt[_filt[cname] == _k_node]
            if _row_df.empty:
                continue
            _row = {cname: _k_node}
            for _m in _metrics:
                _row[_m] = (float(_row_df[_m].iloc[0])
                            if _m in _row_df.columns else np.nan)
            _rows.append(_row)

        if not _rows:
            _ax.text(0.5, 0.5, f"No matching nodes for {_name}",
                     ha="center", fontsize=14)
            continue

        _plot_df = pd.DataFrame(_rows).set_index(cname)

        # normalise each column against the global min / max
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
                    vmin=0, vmax=1,
                    annot=_plot_df,
                    fmt=".3g",
                    linewidths=0.5,
                    cbar_kws={"shrink": 0.8})

        _ax.set_title(f"{_name} per-node metrics",
                      fontsize=13, **_LBL_STYLE)
        _ax.set_xticklabels(_labels, rotation=45, ha="right")

    if title:
        _fig.suptitle(title, **_SUPTITLE_STYLE)

    _save_figure(_fig, file_path, fname, verbose=verbose)
    return _fig


def plot_net_bars(nets: List[pd.DataFrame],
                  names: List[str],
                  *,
                  metrics: Optional[List[str]] = None,
                  labels: Optional[List[str]] = None,
                  title: Optional[str] = None,
                  logscale: bool = True,
                  file_path: Optional[str] = None,
                  fname: Optional[str] = None,
                  verbose: bool = False) -> Figure:
    """*plot_net_bars()* grouped-bar chart of network-wide metrics across N scenarios.

    Args:
        nets (List[pd.DataFrame]): per-scenario single-row network frames produced by `aggregate_network()`.
        names (List[str]): per-scenario display names.
        metrics (Optional[List[str]]): columns to plot. Defaults to every numeric column in the first frame.
        labels (Optional[List[str]]): display labels for the metric columns. Defaults to the metric names.
        title (Optional[str]): figure title.
        logscale (bool): if True, use a log y-axis (helps when metrics span several orders of magnitude, as W vs L).
        file_path (Optional[str]): directory to save into.
        fname (Optional[str]): filename (with extension).
        verbose (bool): if True, prints a one-line save message.

    Raises:
        ValueError: If `nets` is empty or its length does not match `names`.

    Returns:
        Figure: the matplotlib figure.
    """
    # validate the parallel-list inputs
    if not isinstance(nets, list) or len(nets) == 0:
        _msg = "nets must be a non-empty list of DataFrames"
        raise ValueError(_msg)
    if not isinstance(names, list) or len(names) != len(nets):
        _msg = f"names length ({len(names)}) must match nets "
        _msg += f"length ({len(nets)})"
        raise ValueError(_msg)

    # resolve metric / label defaults
    _metrics = _resolve_metrics(nets[0], metrics)
    _labels = _resolve_labels(_metrics, labels)

    # bar-group geometry
    _k = len(nets)
    _group_w = 1.2
    _bar_w = _group_w / (_k * 1.3)
    _bar_space = _bar_w * 0.2
    _group_space = 1.5

    # compute x positions for every (scenario, metric) pair
    _positions: List[List[float]] = []
    for _i in range(_k):
        if _i == 0:
            _positions.append([_j * _group_space for _j in range(len(_metrics))])
        else:
            _positions.append([_x + _bar_w + _bar_space for _x in _positions[_i - 1]])

    _cmap = plt.get_cmap(_BARS_CMAP_NAME, _k)

    _fig, _ax = plt.subplots(figsize=(max(12, len(_metrics) * 1.5), 8),
                             facecolor="white")
    _ax.set_facecolor("white")

    # draw bars + annotate each
    for _i, (_df, _name) in enumerate(zip(nets, names)):
        _values = [
            float(_df[_m].iloc[0]) if _m in _df.columns else np.nan
            for _m in _metrics
        ]
        _ax.bar(_positions[_i], _values,
                width=_bar_w,
                label=_name,
                color=_cmap(_i),
                alpha=0.85,
                edgecolor="black",
                linewidth=0.5)

        for _j, _v in enumerate(_values):
            if np.isnan(_v):
                continue
            _text = _format_value(_v)
            _y = _v * 1.05 if _v >= 0 else _v * 1.05
            _va = "bottom" if _v >= 0 else "top"
            _ax.text(_positions[_i][_j], _y, _text,
                     ha="center", va=_va,
                     fontsize=10, rotation=90,
                     fontweight="light", color="black",
                     bbox=dict(boxstyle="round,pad=0.2",
                               fc="white", ec="none", alpha=0.75))

    # cosmetic: log scale, grid, legend, x-tick centering
    if logscale:
        _ax.set_yscale("log")
    _ax.grid(**_GRID_STYLE)

    _centers = [
        _positions[0][_i] + (_positions[-1][_i] - _positions[0][_i]) / 2
        for _i in range(len(_metrics))
    ]
    _ax.set_xticks(_centers)
    _ax.set_xticklabels(_labels, rotation=30, ha="right")

    _ax.set_ylabel("Value" + (" (log scale)" if logscale else ""), **_LBL_STYLE)
    _ax.set_title(title or "Network Metrics Comparison", **_TITLE_STYLE)
    _ax.legend(loc="upper center", frameon=True, fancybox=True, shadow=True)

    _fig.tight_layout()
    _save_figure(_fig, file_path, fname, verbose=verbose)
    return _fig


def plot_net_delta(deltas: pd.DataFrame,
                   *,
                   metrics: Optional[List[str]] = None,
                   labels: Optional[List[str]] = None,
                   title: Optional[str] = None,
                   file_path: Optional[str] = None,
                   fname: Optional[str] = None,
                   verbose: bool = False) -> Figure:
    """*plot_net_delta()* percent-change bar chart for the network-wide deltas between two scenarios.

    Negative values are drawn green (improvement) and positive values red (degradation); sign convention assumes each metric is a cost (smaller is better) except `total_throughput`, where positive is treated as improvement.

    Args:
        deltas (pd.DataFrame): single-row frame with one column per metric; values are fractional deltas (e.g. `0.05` = +5%).
        metrics (Optional[List[str]]): columns to plot. Defaults to every numeric column.
        labels (Optional[List[str]]): display labels for the columns.
        title (Optional[str]): figure title.
        file_path (Optional[str]): directory to save into.
        fname (Optional[str]): filename (with extension).
        verbose (bool): if True, prints a one-line save message.

    Returns:
        Figure: the matplotlib figure.
    """
    # resolve metric / label defaults
    _metrics = _resolve_metrics(deltas, metrics)
    _labels = _resolve_labels(_metrics, labels)

    # pull the delta values as percentages
    _values = [float(deltas[_m].iloc[0]) * 100 for _m in _metrics]

    # colour each bar: negative = improvement (green); positive = degradation (red).
    # total_throughput flips the sign convention (more throughput is good).
    _colors: List[str] = []
    for _m, _v in zip(_metrics, _values):
        if _m == "total_throughput":
            _colors.append(_BAR_GREEN if _v >= 0 else _BAR_RED)
        else:
            _colors.append(_BAR_GREEN if _v < 0 else _BAR_RED)

    _fig, _ax = plt.subplots(figsize=(12, 7), facecolor="white")
    _ax.set_facecolor("white")

    _bars = _ax.bar(range(len(_metrics)), _values, color=_colors,
                    edgecolor="black", linewidth=0.5, alpha=0.85)

    # annotate each bar with its percent value
    for _b, _v in zip(_bars, _values):
        _y = (_b.get_height() / 2) if abs(_b.get_height()) >= 1 else _b.get_height()
        _ax.text(_b.get_x() + _b.get_width() / 2.0, _y,
                 f"{_v:.2f}%",
                 ha="center",
                 va="bottom" if _v >= 0 else "top",
                 fontsize=11, fontweight="light", color="black")

    # cosmetics: zero baseline, ticks, labels, grid, legend
    _ax.axhline(y=0, color="black", linestyle="-", alpha=0.3)
    _ax.set_xticks(range(len(_metrics)))
    _ax.set_xticklabels(_labels, rotation=30, ha="right")
    _ax.set_ylabel("Percent change (%)", **_LBL_STYLE)
    _ax.set_title(title or "Network Metrics Delta", **_TITLE_STYLE)
    _ax.grid(**_GRID_STYLE)

    _legend = [
        plt.Rectangle((0, 0), 1, 1, facecolor=_BAR_GREEN, alpha=0.85,
                      label="Improvement"),
        plt.Rectangle((0, 0), 1, 1, facecolor=_BAR_RED, alpha=0.85,
                      label="Degradation"),
    ]
    _ax.legend(handles=_legend, loc="best")

    # pad the y-range so annotations do not clip at the edges
    _y_lo = min(min(_values) * 1.1, -2.0)
    _y_hi = max(max(_values) * 1.1, 2.0)
    _ax.set_ylim(_y_lo, _y_hi)

    _fig.tight_layout()
    _save_figure(_fig, file_path, fname, verbose=verbose)
    return _fig

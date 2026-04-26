# -*- coding: utf-8 -*-
"""
Module qn_diagram.py
====================

Queue-network visualisation for the CS-01 TAS case study.

Eight plotters with a uniform parameter-IO convention (keyword-only args after the required positional inputs; every plotter returns the `matplotlib.figure.Figure` and persists to disk when both `file_path` and `fname` are supplied):

    - `plot_qn_topology(rout, nds, ...)` single-scenario architecture diagram (topology + rho colouring + edge labels).
    - `plot_qn_topology_grid(routs, ndss, names, ...)` N scenarios arranged in a row of topologies with a shared rho colourbar.
    - `plot_dim_topology(rout, coefs, ...)` single-scenario dimensionless topology diagram; nodes coloured by `theta` (or any coefficient column), labelled with the four per-node coefficients, table below.
    - `plot_nd_heatmap(ndss, names, nodes, ...)` per-node heatmap across N scenarios; one subplot per scenario.
    - `plot_nd_diffmap(deltas, nodes, ...)` per-node delta heatmap (single panel) with a symmetric colour scale centred on 0 %.
    - `plot_nd_ci(nds, *, metric, reference, ...)` per-node mean with a 95 % CI band (stochastic), optional analytic reference overlay.
    - `plot_net_bars(nets, names, ...)` network-wide grouped-bar chart across N scenarios.
    - `plot_net_delta(deltas, ...)` network-wide percent-change bar chart between two scenarios.

*IMPORTANT:* node colouring uses `coolwarm` (cool = low rho, warm = high rho) so the hottest node is visually obvious; the heatmap uses `viridis` for per-metric normalised comparison across scenarios.

"""
# native python modules
from __future__ import annotations

import os
from pathlib import Path
from typing import List, Optional

# scientific stack
import matplotlib.pyplot as plt
import networkx as nx
import numpy as np
import pandas as pd
import seaborn as sns
from matplotlib import cm, colormaps
from matplotlib import colors as mcolors
from matplotlib.figure import Figure


# Force black-on-white rendering regardless of the ambient matplotlib
# style / Jupyter theme. We use the near-black `#010101` rather than
# pure `"black"` on purpose: matplotlib's SVG backend treats pure
# black as the SVG-spec default and OMITS the fill attribute entirely,
# which makes dark-theme SVG viewers (e.g. VSCode preview) render the
# text in their inherited foreground colour (often white, i.e.
# invisible on white paper). `#010101` is visually identical to black
# but non-default, which forces matplotlib to write an explicit
# `style="fill:#010101"` on every text element.
_TEXT_BLACK = "#010101"

plt.rcParams.update({
    "figure.facecolor": "white",
    "axes.facecolor": "white",
    "savefig.facecolor": "white",
    "text.color": _TEXT_BLACK,
    "axes.labelcolor": _TEXT_BLACK,
    "axes.edgecolor": _TEXT_BLACK,
    "xtick.color": _TEXT_BLACK,
    "ytick.color": _TEXT_BLACK,
    "grid.color": "lightgray",
    "font.size": 10,
    "axes.labelsize": 12,
    "xtick.labelsize": 10,
    "ytick.labelsize": 10,
    "legend.fontsize": 10,
})


# -- Shared styling constants (reused across every plotter) --
_GRID_STYLE = dict(axis="y", linestyle="--", alpha=0.7, color="#555555")
_LBL_STYLE = dict(fontweight="bold", color=_TEXT_BLACK)
_TITLE_STYLE = dict(fontsize=14, fontweight="bold", pad=20)
_SUPTITLE_STYLE = dict(fontsize=16, fontweight="bold")

# bar chart colours for the delta view. Neutral direction semantics:
# pastel blue for a metric that decreased, pastel orange for one that
# increased. Interpretation (good / bad) is a domain concern and is
# left to the caller; the colour rule here is sign-only.
_BAR_BLUE = "#33ACD1"    # decrease (negative delta)
_BAR_ORANGE = "#EDD175"  # increase (positive delta)

# colourmaps
_TOPOLOGY_CMAP = cm.coolwarm
_HEATMAP_CMAP = "coolwarm"   # same family as topology node colouring


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------


def _save_figure(fig: Figure,
                 file_path: Optional[str],
                 fname: Optional[str],
                 verbose: bool = False) -> None:
    """*_save_figure()* persist the figure as BOTH `.png` (raster, 300 dpi) and `.svg` (vector) when both `file_path` and `fname` are given; no-op otherwise. Any extension on `fname` is stripped; the stem is reused for both formats.

    Args:
        fig (Figure): matplotlib figure to save.
        file_path (Optional[str]): destination directory (created if missing).
        fname (Optional[str]): output filename; extension (if any) is ignored, the stem drives both `.png` and `.svg` outputs.
        verbose (bool): if True, prints one save message per format.

    Raises:
        ValueError: If `fig.savefig` fails for either format.
    """
    if not (file_path and fname):
        return

    # ensure the destination directory exists
    os.makedirs(file_path, exist_ok=True)

    # caller can pass "topology.png" or "topology"; either way, save both formats
    _stem = Path(fname).with_suffix("").name

    # one raster (.png, 300 dpi) + one vector (.svg) version
    for _ext, _extra in (("png", {"dpi": 300}), ("svg", {})):
        _full_path = os.path.join(file_path, f"{_stem}.{_ext}")
        if verbose:
            print(f"Saving plot to: {_full_path}")
        try:
            fig.savefig(_full_path,
                        facecolor="white",
                        bbox_inches="tight",
                        **_extra)
        except Exception as _e:
            _msg = f"Error saving {_ext}: {_e}. "
            _msg += f"file_path: {file_path!r}, stem: {_stem!r}"
            raise ValueError(_msg)

    if verbose:
        print(f"Plot saved successfully ({_stem}.png + {_stem}.svg)")


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


def _generate_color_map(values: List) -> List[str]:
    """*_generate_color_map()* build a vibrant colour palette for N distinct values using the same recipe as `__OLD__/src/notebooks/src/display.py::_generate_color_map`:

        - n <= 12  -> `rainbow`   (high saturation, wide hue spread)
        - n <= 20  -> `Spectral`  (perceptually smoother)
        - n >  20  -> `turbo`     (dense distinct steps)

    The RGB tuples round-trip through HSV as a hook for future saturation / value boosting; the alpha channel is preserved.

    Args:
        values (List): list of items (strings, ints, ...) needing
            one distinct colour each. Length drives the colormap
            choice.

    Returns:
        List[str]: hex colour strings aligned 1:1 with `values` (same
            order the caller supplied).
    """
    _n = len(values)
    if _n <= 12:
        _cmap = colormaps["rainbow"]
    elif _n <= 20:
        _cmap = colormaps["Spectral"]
    else:
        _cmap = colormaps["turbo"]

    # spread N samples across the full colormap range; reversed so the
    # first item gets the warm end (matches the old display.py spacing)
    _rgba = _cmap(np.linspace(1.0, 0.0, max(_n, 1)))

    # RGB -> HSV -> RGB pass (no-op today; left as a hook for future
    # saturation boosting, mirroring the old helper's comment)
    _rgb = mcolors.rgb_to_hsv(_rgba[:, :3])
    _boosted = mcolors.hsv_to_rgb(_rgb)

    # re-attach the alpha channel + emit hex strings
    _rgba_out = np.column_stack([_boosted, _rgba[:, 3]])
    return [mcolors.rgb2hex(_c) for _c in _rgba_out]


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


def _draw_topology_axis(ax: plt.Axes,
                        graph: nx.DiGraph,
                        pos: dict,
                        nds: pd.DataFrame,
                        nd_names: List[str],
                        edge_label_threshold: float = 0.01,
                        rho_max: Optional[float] = None) -> None:
    """*_draw_topology_axis()* draw one queue-network topology into a given axis, coloured by `rho` when the column is present.

    Args:
        ax: matplotlib axis to draw into.
        graph (nx.DiGraph): prebuilt topology graph.
        pos (dict): BFS (or similar) layout positions.
        nds (pd.DataFrame): per-node metrics frame.
        nd_names (List[str]): display names aligned with the graph.
        edge_label_threshold (float): routing probabilities below this are drawn without a numeric label to keep the diagram readable.
        rho_max (Optional[float]): shared scale for node colouring in multi-panel plots; defaults to the frame's own `rho.max()` so a single-scenario diagram always has one red node.
    """
    _n = len(nd_names)

    # node colours from rho (normalised so the hottest node saturates
    # to red). Grid plots pass `rho_max` so both subplots share a
    # colour scale; single plots default to the frame's own max.
    if "rho" in nds.columns:
        _rhos = nds["rho"].to_numpy(dtype=float)
        if rho_max is not None:
            _scale = rho_max
        else:
            _scale = float(_rhos.max())
        _scale = max(_scale, 1e-9)
        _node_colors = [_TOPOLOGY_CMAP(_r / _scale) for _r in _rhos]
    else:
        _node_colors = ["skyblue"] * _n

    # draw nodes first
    nx.draw_networkx_nodes(graph, pos,
                           node_size=1500,
                           node_color=_node_colors,
                           alpha=0.9,
                           ax=ax)

    # draw all edges with one uniform connection style (matches
    # `__OLD__/src/view/plots.py::plot_queue_network`). Networkx
    # renders self-loops as compact loops right on the node, so they
    # never overlap with cross-edges that pass through adjacent
    # regions of the diagram.
    nx.draw_networkx_edges(graph, pos,
                           width=1.5,
                           alpha=0.7,
                           edge_color=_TEXT_BLACK,
                           arrows=True,
                           arrowsize=20,
                           arrowstyle="-|>",
                           connectionstyle="arc3,rad=0.2",
                           ax=ax)

    # edge labels: keep only weights above the visual-noise threshold.
    # One dict covers both cross-edges and self-loops since every
    # edge now shares the same connection style.
    _edge_lbl = {
        (_u, _v): f"{_d['weight']:.2f}"
        for _u, _v, _d in graph.edges(data=True)
        if _d["weight"] >= edge_label_threshold
    }
    nx.draw_networkx_edge_labels(graph, pos,
                                 edge_labels=_edge_lbl,
                                 font_size=11,
                                 font_color=_TEXT_BLACK,
                                 font_weight="light",
                                 bbox=dict(facecolor="white",
                                           edgecolor="none",
                                           alpha=0.9,
                                           pad=0.3),
                                 label_pos=0.5,
                                 connectionstyle="arc3,rad=0.2",
                                 ax=ax)

    # Two-line node label, both lines rendered bold via `\mathbf{...}` inside `$...$` so subscripts render as proper math:
    #   line 1: the artifact key (e.g. $\mathbf{TAS_{1}}$)
    #   line 2: $\mathbf{L = 3.82}$ — avg number in system (L from Little's law).
    # Colouring still tracks `rho` (via `_node_colors` above); the label reports L so the reader sees queue occupancy in absolute units.
    _labels = {}
    for _i in range(_n):
        _name = nd_names[_i]
        _parts = [rf"$\mathbf{{{_name}}}$"]
        if "L" in nds.columns:
            _parts.append(rf"$\mathbf{{L = {nds['L'].iloc[_i]:.2f}}}$")
        _labels[_i] = "\n".join(_parts)
    nx.draw_networkx_labels(graph, pos,
                            labels=_labels,
                            font_size=12,
                            font_weight="bold",
                            font_color=_TEXT_BLACK,
                            ax=ax)

    # axis cosmetics: hide ticks, tighten margins
    ax.set_axis_off()


# Convenience default glossary for queueing-network topology plots.
# Callers import this from `src.view.qn_diagram` and pass it through
# `plot_qn_topology(..., glossary=QN_GLOSSARY_DEFAULT)` when they want
# the overlay; other methods (stochastic, dimensional, ...) can define
# their own list with the same format. The plotter itself stays
# domain-agnostic.
QN_GLOSSARY_DEFAULT = [
    "LEGEND",
    r"$\lambda$: Arrival rate (req/s)",
    r"$\mu$: Service rate (req/s)",
    r"$\rho$: Utilisation",
    r"$L$: Avg number in system",
    r"$L_q$: Avg queue length",
    r"$W$: Avg time in system (s)",
    r"$W_q$: Avg wait time (s)",
]


def _add_param_glossary(ax: plt.Axes,
                        glossary: List[str],
                        *,
                        corner: str = "lower right") -> None:
    """*_add_param_glossary()* overlay a caller-supplied parameter glossary (LaTeX lines) in the chosen corner of a topology axis.

    Args:
        ax: matplotlib axis (graph subplot).
        glossary (List[str]): lines to render verbatim (each one a
            short LaTeX snippet or plain string).
        corner (str): `"lower right"`, `"lower left"`, `"upper right"`,
            or `"upper left"`. Anchors the text box to that corner in
            axis-relative coordinates.
    """
    _text = "\n".join(glossary)
    _y = 0.02 if "lower" in corner else 0.98
    _x = 0.98 if "right" in corner else 0.02
    _ha = "right" if "right" in corner else "left"
    _va = "bottom" if "lower" in corner else "top"
    _props = dict(boxstyle="round,pad=0.4", facecolor="white",
                  alpha=0.85, edgecolor="gray")
    ax.text(_x, _y, _text,
            transform=ax.transAxes,
            fontsize=14,
            color=_TEXT_BLACK,
            verticalalignment=_va,
            horizontalalignment=_ha,
            bbox=_props)


def _add_network_summary(ax: plt.Axes,
                         net: pd.Series,
                         *,
                         corner: str = "upper right") -> None:
    """*_add_network_summary()* overlay the network-wide aggregate metrics (avg_mu, avg_rho, L_net, Lq_net, W_net, Wq_net, total_throughput) as a text box in the chosen corner.

    Args:
        ax: matplotlib axis (graph subplot).
        net (pd.Series): single row from `aggregate_net()`.
        corner (str): anchor corner; see `_add_param_glossary()`.
    """
    # Each line renders the symbol in bold via `\mathbf{...}` while
    # the numeric value + [unit] stay at normal weight (outside the
    # `$...$`).
    _lines = [
        r"$\mathbf{NETWORK}$",
        rf"$\mathbf{{\overline{{\mu}}}}$: {net['avg_mu']:.2f} [req/s]",
        rf"$\mathbf{{\overline{{\rho}}}}$: {net['avg_rho']:.3f}",
        rf"$\mathbf{{L_{{net}}}}$: {net['L_net']:.2f} [req]",
        rf"$\mathbf{{L_{{q,net}}}}$: {net['Lq_net']:.2f} [req]",
        rf"$\mathbf{{\overline{{W}}}}$: {net['W_net']:.4e} [s/req]",
        rf"$\mathbf{{\overline{{W_q}}}}$: {net['Wq_net']:.4e} [s/req]",
        rf"$\mathbf{{TP_{{net}}}}$: {net['total_throughput']:.2f} [req/s]",
    ]
    _text = "\n".join(_lines)
    _y = 0.98 if "upper" in corner else 0.02
    _x = 0.98 if "right" in corner else 0.02
    _va = "top" if "upper" in corner else "bottom"
    _ha = "right" if "right" in corner else "left"
    _props = dict(boxstyle="round,pad=0.5", facecolor="lightblue",
                  alpha=0.85, edgecolor="steelblue")
    ax.text(_x, _y, _text,
            transform=ax.transAxes,
            fontsize=14,
            color=_TEXT_BLACK,
            verticalalignment=_va,
            horizontalalignment=_ha,
            bbox=_props)


def _add_node_table(ax: plt.Axes, nds: pd.DataFrame, nd_names: List[str]) -> None:
    """*_add_node_table()* draw a per-node metrics table (name, lambda, mu, rho, L, Lq, W, Wq) into a dedicated axis below the topology.

    Args:
        ax: matplotlib axis reserved for the table (axis is hidden).
        nds (pd.DataFrame): per-node metrics frame.
        nd_names (List[str]): display names aligned with the rows.
    """
    ax.set_axis_off()

    # header row + one data row per node; LaTeX-mathtext labels mirror
    # the glossary ordering so table and legend line up.
    _header = ["Component",
               r"$\lambda$ [req/s]",
               r"$\mu$ [req/s]",
               r"$\rho$",
               r"$L$ [req]",
               r"$L_q$ [req]",
               r"$W$ [s/req]",
               r"$W_q$ [s/req]"]
    _rows = [_header]
    for _i in range(len(nd_names)):
        _row = nds.iloc[_i]
        _rows.append([
            # wrap the artifact key in `$...$` so mathtext renders the
            # subscript (e.g. `TAS_{1}` -> proper `TAS` + subscript `1`)
            f"${nd_names[_i]}$",
            f"{_row['lambda']:.2f}",
            f"{_row['mu']:.2f}",
            f"{_row['rho']:.3f}",
            f"{_row['L']:.2f}",
            f"{_row['Lq']:.2f}",
            f"{_row['W']:.4e}",
            f"{_row['Wq']:.4e}",
        ])

    _table = ax.table(cellText=_rows, loc="center", cellLoc="center",
                      colWidths=[0.14] + [0.11] * 7)
    _table.auto_set_font_size(False)
    _table.set_fontsize(12)
    _table.scale(1, 1.25)

    # header row styling
    for _j in range(len(_header)):
        _table[(0, _j)].set_facecolor("#E4EBF1")
        _table[(0, _j)].set_text_props(weight="bold")


# ---------------------------------------------------------------------------
# Public plotters
# ---------------------------------------------------------------------------


def plot_qn_topology(rout: np.ndarray,
                     nds: pd.DataFrame,
                     *,
                     net: Optional[pd.DataFrame] = None,
                     glossary: Optional[List[str]] = None,
                     nd_names: Optional[List[str]] = None,
                     title: Optional[str] = None,
                     file_path: Optional[str] = None,
                     fname: Optional[str] = None,
                     verbose: bool = False) -> Figure:
    """*plot_qn_topology()* draw the queueing-network topology for one scenario, with nodes coloured by `rho`, edge labels showing routing probabilities, a rho colourbar, a parameter glossary, an optional network-wide summary overlay, and a per-node metrics table below the graph.

    Args:
        rout (np.ndarray): `(n, n)` routing-probability matrix.
        nds (pd.DataFrame): per-node metrics frame aligned with `rout`. `rho` column drives node colouring when present.
        net (Optional[pd.DataFrame]): single-row frame from `aggregate_net()`. When given, its values are overlaid as a network-wide summary box on the topology.
        nd_names (Optional[List[str]]): per-node display names. Defaults to `nds["key"]` when present, else `"Node {i}"`.
        title (Optional[str]): figure title. Defaults to `"Queue-Network Topology"`.
        file_path (Optional[str]): directory to save the figure into.
        fname (Optional[str]): filename (with extension) for the save.
        verbose (bool): if True, prints a one-line save message.

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

    # two stacked subplots (matches __OLD__/src/view/plots.py
    # `plot_queue_network`): graph 3/4, metrics table 1/4. figsize and
    # the (4,1) split are chosen so the table has room for 13 rows
    # without overlapping the graph.
    _fig = plt.figure(figsize=(18, 22), facecolor="white")
    _ax_graph = plt.subplot2grid((4, 1), (0, 0), rowspan=3)
    _ax_table = plt.subplot2grid((4, 1), (3, 0), rowspan=1)
    _ax_graph.set_facecolor("white")
    _ax_table.set_facecolor("white")

    # draw the topology into the graph axis
    _draw_topology_axis(_ax_graph, _graph, _pos, nds, nd_names)

    # rho colourbar anchored to the right of the graph axis. vmax
    # tracks the frame's max rho (matches the reference diagram).
    if "rho" in nds.columns:
        _max_rho = max(float(nds["rho"].max()), 1e-9)
        _sm = cm.ScalarMappable(cmap=_TOPOLOGY_CMAP,
                                norm=plt.Normalize(vmin=0.0, vmax=_max_rho))
        _sm.set_array([])
        _cbar = _fig.colorbar(_sm, ax=_ax_graph, shrink=0.6, pad=0.02)
        _cbar.set_label(r"Utilisation $(\rho)$",
                        color=_TEXT_BLACK, fontsize=14, fontweight="bold")
        _cbar.ax.tick_params(colors=_TEXT_BLACK)

    # overlays (positions match __OLD__/src/view/plots.py exactly):
    #   - network summary at top-center of the graph axis
    #   - parameter glossary at bottom-right of the graph axis
    if net is not None:
        _add_network_summary(_ax_graph, net.iloc[0], corner="upper right")
    _gloss = glossary if glossary is not None else QN_GLOSSARY_DEFAULT
    if _gloss:
        _add_param_glossary(_ax_graph, _gloss, corner="lower right")

    # per-node metrics table at the bottom of the figure
    _add_node_table(_ax_table, nds, nd_names)

    # graph axis title (large, bold; matches `Queue Network Visualisation` from the old function but lets the caller override)
    _ax_graph.set_title(title or "Queue Network Visualisation",
                        fontsize=24, fontweight="bold", color=_TEXT_BLACK,
                        va="center", ha="center", pad=20)

    # subtitle above the metrics table; figtext (not ax) so it sits in
    # the gap between the two subplots
    plt.figtext(0.50, 0.27, "Node Metrics Table",
                fontsize=18, fontweight="bold",
                va="center", ha="center", color=_TEXT_BLACK)

    _fig.tight_layout()

    _save_figure(_fig, file_path, fname, verbose=verbose)
    return _fig


# ---------------------------------------------------------------------------
# Dimensional-topology support (shared with plot_dim_topology below)
# ---------------------------------------------------------------------------


# Per-node dimensionless-coefficient columns emitted by `coefs_to_nodes()`;
# declaration order drives label lines and table columns.
_DIM_COEF_COLS = ("theta", "sigma", "eta", "phi")

# LaTeX symbol for each coefficient (used in node labels, table headers, and
# the colourbar label).
_DIM_COEF_SYMS = {
    "theta": r"\theta",
    "sigma": r"\sigma",
    "eta": r"\eta",
    "phi": r"\phi",
}

# Default glossary for the dimensional topology plot. Callers can pass their
# own list via `plot_dim_topology(..., glossary=...)`. Fractions use
# `\frac{}{}` so the legend stays tight horizontally.
DIM_GLOSSARY_DEFAULT = [
    "LEGEND",
    r"$\theta = \frac{L}{K}$: Occupancy (queue fill ratio)",
    r"$\sigma = \frac{W\lambda}{K}$: Stall (queueing share of capacity)",
    r"$\eta = \frac{\chi \cdot K}{\mu \cdot c}$: Effective-yield (utilisation headroom)",
    r"$\phi = \frac{M_{act}}{M_{buf}}$: Memory-usage (buffer fill)",
]

# Short human-readable name for each coefficient; used in the NETWORK
# summary overlay line format `$\bar{sym}$ (Name): value`.
_DIM_COEF_NAMES = {
    "theta": "Occupancy",
    "sigma": "Stall",
    "eta": "Effective-yield",
    "phi": "Memory-usage",
}


def _draw_dim_topology_axis(ax: plt.Axes,
                            graph: nx.DiGraph,
                            pos: dict,
                            nds: pd.DataFrame,
                            nd_names: List[str],
                            *,
                            color_by: str = "eta",
                            edge_label_threshold: float = 0.01,
                            color_min: Optional[float] = None,
                            color_max: Optional[float] = None) -> None:
    """*_draw_dim_topology_axis()* draw the dimensionless topology into a given axis; nodes coloured by `color_by` using data-driven min-max normalisation, with a compact 2-line label per node showing the artifact key and its $\\theta$ value.

    Args:
        ax: matplotlib axis to draw into.
        graph (nx.DiGraph): prebuilt topology graph.
        pos (dict): BFS (or similar) layout positions.
        nds (pd.DataFrame): per-node coefficients frame (output of `coefs_to_nodes()`).
        nd_names (List[str]): display names aligned with the graph.
        color_by (str): column driving the node colour. Defaults to `"eta"` (effective-yield), which is unbounded and benefits from min-max normalisation.
        edge_label_threshold (float): routing probabilities below this are drawn without a numeric label.
        color_min (Optional[float]): shared colour-scale lower bound; defaults to `nds[color_by].min()`.
        color_max (Optional[float]): shared colour-scale upper bound; defaults to `nds[color_by].max()`.
    """
    _n = len(nd_names)

    # node colours from the selected coefficient. Unlike rho / theta (bounded to [0, 1]), eta can exceed 1, so we normalise across the data's own [min, max] so the hottest node always saturates to red and the coolest to blue regardless of absolute magnitude.
    if color_by in nds.columns:
        _vals = nds[color_by].to_numpy(dtype=float)
        if color_min is not None:
            _vmin = color_min
        else:
            _vmin = float(_vals.min())
        if color_max is not None:
            _vmax = color_max
        else:
            _vmax = float(_vals.max())
        _span = max(_vmax - _vmin, 1e-9)
        _node_colors = [_TOPOLOGY_CMAP((_v - _vmin) / _span) for _v in _vals]
    else:
        _node_colors = ["skyblue"] * _n

    # nodes
    nx.draw_networkx_nodes(graph, pos,
                           node_size=1800,
                           node_color=_node_colors,
                           alpha=0.9,
                           ax=ax)

    # edges (uniform connection style; same as the queueing-network view)
    nx.draw_networkx_edges(graph, pos,
                           width=1.5,
                           alpha=0.7,
                           edge_color=_TEXT_BLACK,
                           arrows=True,
                           arrowsize=20,
                           arrowstyle="-|>",
                           connectionstyle="arc3,rad=0.2",
                           ax=ax)

    # edge labels: routing probability (same threshold as plot_qn_topology)
    _edge_lbl = {
        (_u, _v): f"{_d['weight']:.2f}"
        for _u, _v, _d in graph.edges(data=True)
        if _d["weight"] >= edge_label_threshold
    }
    nx.draw_networkx_edge_labels(graph, pos,
                                 edge_labels=_edge_lbl,
                                 font_size=11,
                                 font_color=_TEXT_BLACK,
                                 font_weight="light",
                                 bbox=dict(facecolor="white",
                                           edgecolor="none",
                                           alpha=0.9,
                                           pad=0.3),
                                 label_pos=0.5,
                                 connectionstyle="arc3,rad=0.2",
                                 ax=ax)

    # node labels: artifact key on line 1, theta on line 2 in scientific notation (2 digits after the decimal point). Full per-coefficient breakdown lives in the table below; the graph stays readable.
    _labels: dict = {}
    for _i in range(_n):
        _name = nd_names[_i]
        _parts = [rf"$\mathbf{{{_name}}}$"]
        if "theta" in nds.columns:
            _val = float(nds["theta"].iloc[_i])
            _parts.append(rf"$\mathbf{{\theta = {_val:.2e}}}$")
        _labels[_i] = "\n".join(_parts)
    nx.draw_networkx_labels(graph, pos,
                            labels=_labels,
                            font_size=12,
                            font_weight="bold",
                            font_color=_TEXT_BLACK,
                            ax=ax)

    ax.set_axis_off()


def _add_dim_node_table(ax: plt.Axes,
                        nds: pd.DataFrame,
                        nd_names: List[str]) -> None:
    """*_add_dim_node_table()* draw a per-node coefficient table (Component, theta, sigma, eta, phi) into a dedicated axis below the dimensional topology graph.

    Args:
        ax: matplotlib axis reserved for the table (axis is hidden).
        nds (pd.DataFrame): per-node coefficients frame.
        nd_names (List[str]): display names aligned with the rows.
    """
    ax.set_axis_off()

    # header: Component + one column per present coefficient in declared order
    _present_cols = [_c for _c in _DIM_COEF_COLS if _c in nds.columns]
    _header = ["Component"]
    for _c in _present_cols:
        _sym = _DIM_COEF_SYMS[_c]
        _header.append(rf"${_sym}$")

    _rows = [_header]
    for _i in range(len(nd_names)):
        _row = nds.iloc[_i]
        _cells = [f"${nd_names[_i]}$"]
        for _c in _present_cols:
            # Scientific notation with 2 digits after the decimal point. Dimensional coefficients span multiple orders of magnitude across scenarios (`phi` ~ 1e-3 baseline vs ~ 1e-1 under heavy load); `.2e` keeps every cell at uniform width and preserves 3 significant figures.
            _cells.append(f"{float(_row[_c]):.2e}")
        _rows.append(_cells)

    # Table is compact: Component column narrower than coefficient columns (keys are short), and coefficient columns themselves trimmed so the whole table doesn't overflow the figure. Unused width becomes left/right margin.
    _col_widths = [0.12] + [0.12] * len(_present_cols)
    _table = ax.table(cellText=_rows, loc="center", cellLoc="center",
                      colWidths=_col_widths)
    _table.auto_set_font_size(False)
    _table.set_fontsize(12)
    _table.scale(1, 1.25)

    # header row styling
    for _j in range(len(_header)):
        _table[(0, _j)].set_facecolor("#E4EBF1")
        _table[(0, _j)].set_text_props(weight="bold")


def _add_dim_network_summary(ax: plt.Axes,
                             nds: pd.DataFrame,
                             *,
                             corner: str = "upper right") -> None:
    """*_add_dim_network_summary()* overlay the architecture-wide coefficient averages (mean of each $\\theta$ / $\\sigma$ / $\\eta$ / $\\phi$ column across every component) as a text box in the chosen corner of the graph axis.

    Args:
        ax: matplotlib axis (graph subplot).
        nds (pd.DataFrame): per-node coefficients frame. Every present coefficient gets an averaged line; absent columns are skipped.
        corner (str): anchor corner; see `_add_param_glossary()`.
    """
    # Header line matches the queueing summary's "NETWORK" banner for visual parity with the QN view. Each coefficient line reads `$\bar{sym}$ (Name): value` so the reader immediately sees what the averaged symbol means.
    _lines = [r"$\mathbf{NETWORK}$"]
    for _c in _DIM_COEF_COLS:
        if _c in nds.columns:
            _sym = _DIM_COEF_SYMS[_c]
            _name = _DIM_COEF_NAMES.get(_c, _c)
            _mean = float(nds[_c].mean())
            _lines.append(
                rf"$\mathbf{{\overline{{{_sym}}}}}$ ({_name}): {_mean:.2e}")
    _text = "\n".join(_lines)
    _y = 0.98 if "upper" in corner else 0.02
    _x = 0.98 if "right" in corner else 0.02
    _va = "top" if "upper" in corner else "bottom"
    _ha = "right" if "right" in corner else "left"
    _props = dict(boxstyle="round,pad=0.5", facecolor="lightblue",
                  alpha=0.85, edgecolor="steelblue")
    ax.text(_x, _y, _text,
            transform=ax.transAxes,
            fontsize=14,
            color=_TEXT_BLACK,
            verticalalignment=_va,
            horizontalalignment=_ha,
            bbox=_props)


def plot_dim_topology(rout: np.ndarray,
                      nds: pd.DataFrame,
                      *,
                      color_by: str = "eta",
                      glossary: Optional[List[str]] = None,
                      nd_names: Optional[List[str]] = None,
                      title: Optional[str] = None,
                      file_path: Optional[str] = None,
                      fname: Optional[str] = None,
                      verbose: bool = False) -> Figure:
    """*plot_dim_topology()* draw the dimensionless topology for one scenario; nodes coloured by a chosen coefficient column (default `eta`, min-max normalised), labelled with the artifact key + its $\\theta$ value, edge labels show routing probabilities, a colourbar tracks the colouring coefficient, a network-wide coefficient-average overlay sits top-right, a glossary explains the four dimensionless groups, and a per-node coefficient table sits below the graph.

    Mirrors `plot_qn_topology` in layout (3/4 graph + 1/4 table, same BFS layout, same edge style) so the dimensional view and the queueing view align visually side-by-side when compared across a method matrix.

    Args:
        rout (np.ndarray): `(n, n)` routing-probability matrix.
        nds (pd.DataFrame): per-node coefficients frame from `src.dimensional.coefs_to_nodes`; expected columns include `key` plus one or more of `theta`, `sigma`, `eta`, `phi`.
        color_by (str): coefficient column driving node colours. Defaults to `"eta"` (effective-yield); normalisation uses the data's own min / max span so the hottest node saturates to red and the coolest to blue.
        glossary (Optional[List[str]]): parameter glossary lines (LaTeX OK). When None, `DIM_GLOSSARY_DEFAULT` is used; pass `[]` to suppress.
        nd_names (Optional[List[str]]): per-node display names. Defaults to `nds["key"]` when present, else `"Node {i}"`.
        title (Optional[str]): figure title. Defaults to `"Dimensionless Topology"`.
        file_path (Optional[str]): directory to save the figure into.
        fname (Optional[str]): filename (with extension) for the save.
        verbose (bool): if True, prints a one-line save message.

    Returns:
        Figure: the matplotlib figure.
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

    # stacked layout matching plot_qn_topology: graph (3/4) + table (1/4)
    _fig = plt.figure(figsize=(18, 22), facecolor="white")
    _ax_graph = plt.subplot2grid((4, 1), (0, 0), rowspan=3)
    _ax_table = plt.subplot2grid((4, 1), (3, 0), rowspan=1)
    _ax_graph.set_facecolor("white")
    _ax_table.set_facecolor("white")

    # draw the dimensionless topology
    _draw_dim_topology_axis(_ax_graph, _graph, _pos, nds, nd_names,
                            color_by=color_by)

    # colourbar tracks the colouring coefficient with data-driven min/max so the bar scale matches the node colouring exactly (the chosen coefficient, eta by default, can exceed 1, so a fixed [0,1] cap would distort the colouring).
    if color_by in nds.columns:
        _vals = nds[color_by].to_numpy(dtype=float)
        _vmin = float(_vals.min())
        _vmax = float(_vals.max())
        if _vmax <= _vmin:
            _vmax = _vmin + 1e-9
        _sm = cm.ScalarMappable(cmap=_TOPOLOGY_CMAP,
                                norm=plt.Normalize(vmin=_vmin, vmax=_vmax))
        _sm.set_array([])
        _cbar = _fig.colorbar(_sm, ax=_ax_graph, shrink=0.6, pad=0.02)
        _sym = _DIM_COEF_SYMS.get(color_by, color_by)
        _cbar.set_label(rf"${_sym}$ (dimensionless)",
                        color=_TEXT_BLACK, fontsize=14, fontweight="bold")
        _cbar.ax.tick_params(colors=_TEXT_BLACK)

    # architecture-average overlay at top-right (mirrors the queueing view's network-summary box, but reports mean(theta), mean(sigma), mean(eta), mean(phi) across every component).
    _add_dim_network_summary(_ax_graph, nds, corner="upper right")

    # glossary overlay (bottom-right); empty list suppresses
    _gloss = glossary if glossary is not None else DIM_GLOSSARY_DEFAULT
    if _gloss:
        _add_param_glossary(_ax_graph, _gloss, corner="lower right")

    # per-node coefficient table at the bottom of the figure
    _add_dim_node_table(_ax_table, nds, nd_names)

    _ax_graph.set_title(title or "Dimensionless Topology",
                        fontsize=24, fontweight="bold", color=_TEXT_BLACK,
                        va="center", ha="center", pad=20)

    # "Node Coefficient Table" heading sits below the graph axis (at 0.24 figure-y rather than 0.27) so it does not overlap the legend overlay anchored to the graph axis's lower-right corner. The legend lives in axes coords (0 to 1 inside the graph axis); the figtext lives in figure coords.
    plt.figtext(0.50, 0.24, "Node Coefficient Table",
                fontsize=18, fontweight="bold",
                va="center", ha="center", color=_TEXT_BLACK)

    _fig.tight_layout()

    _save_figure(_fig, file_path, fname, verbose=verbose)
    return _fig


def plot_qn_topology_grid(routs: List[np.ndarray],
                          ndss: List[pd.DataFrame],
                          names: List[str],
                          *,
                          nets: Optional[List[pd.DataFrame]] = None,
                          glossary: Optional[List[str]] = None,
                          nd_names: Optional[List[str]] = None,
                          title: Optional[str] = None,
                          file_path: Optional[str] = None,
                          fname: Optional[str] = None,
                          verbose: bool = False) -> Figure:
    """*plot_qn_topology_grid()* draw N scenarios side-by-side with a shared BFS layout, a shared rho colourbar, and optional per-subplot network-wide summary + parameter glossary overlays.

    Args:
        routs (List[np.ndarray]): per-scenario routing matrices.
        ndss (List[pd.DataFrame]): per-scenario node frames (aligned with `routs` by index).
        names (List[str]): per-scenario display names for subplot titles.
        nets (Optional[List[pd.DataFrame]]): per-scenario network-wide frames from `aggregate_net()`. When given, each subplot gets a network summary overlay.
        glossary (Optional[List[str]]): parameter glossary lines (LaTeX OK) drawn once on the first subplot. When None, no glossary overlay is rendered.
        nd_names (Optional[List[str]]): per-node display names. Defaults to the first frame's `key` column when present.
        title (Optional[str]): overall figure title (suptitle).
        file_path (Optional[str]): directory to save into.
        fname (Optional[str]): filename (with extension).
        verbose (bool): if True, prints a one-line save message.

    Raises:
        ValueError: If the required lists do not have matching lengths.

    Returns:
        Figure: the matplotlib figure.
    """
    # validate the parallel-list inputs
    if not (len(routs) == len(ndss) == len(names)):
        _msg = "routs, ndss, and names must have matching lengths; "
        _msg += f"got {len(routs)}, {len(ndss)}, {len(names)}"
        raise ValueError(_msg)
    if nets is not None and len(nets) != len(routs):
        _msg = f"nets length ({len(nets)}) must match routs "
        _msg += f"length ({len(routs)})"
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

    # shared rho scale so both subplots use the same colour normalisation
    # (and the hottest node across every scenario is the one that maps
    # to red, not the hottest within each subplot independently)
    _shared_rho_max = None
    if all("rho" in _df.columns for _df in ndss):
        _shared_rho_max = max(float(_df["rho"].max()) for _df in ndss)
        _shared_rho_max = max(_shared_rho_max, 1e-9)

    # create the grid; width scales with the number of scenarios
    _fig, _axes = plt.subplots(1, _k,
                               figsize=(max(8, 8 * _k), 10),
                               facecolor="white")
    if _k == 1:
        _axes = [_axes]

    # draw each scenario into its own axis; overlay glossary + summary box
    for _i, (_ax, _rout, _nds, _name) in enumerate(zip(_axes, routs, ndss, names)):
        _ax.set_facecolor("white")
        _graph = _build_topology_graph(_rout, nd_names)
        _draw_topology_axis(_ax, _graph, _pos, _nds, nd_names,
                            rho_max=_shared_rho_max)
        _ax.set_title(_name, fontsize=13, **_LBL_STYLE)

        # glossary only on the first subplot (would be redundant otherwise);
        # defaults to QN_GLOSSARY_DEFAULT when the caller does not pass one.
        # Pass `glossary=[]` to suppress the overlay entirely.
        if _i == 0:
            _gloss = glossary if glossary is not None else QN_GLOSSARY_DEFAULT
            if _gloss:
                _add_param_glossary(_ax, _gloss, corner="lower right")
        if nets is not None:
            _add_network_summary(_ax, nets[_i].iloc[0], corner="upper right")

    # shared rho colourbar anchored to the right of the grid; vmax matches the shared normalisation so the colourbar and the node colours tell the same story
    if _shared_rho_max is not None:
        _cbar_max = _shared_rho_max
    else:
        _cbar_max = 1.0
    _sm = cm.ScalarMappable(cmap=_TOPOLOGY_CMAP,
                            norm=plt.Normalize(vmin=0.0, vmax=_cbar_max))
    _sm.set_array([])
    _cbar = _fig.colorbar(_sm, ax=_axes, shrink=0.75, pad=0.02)
    _cbar.set_label(r"Utilisation $(\rho)$", **_LBL_STYLE)

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
        _ax.set_xticklabels(_labels, rotation=45, ha="right",
                            fontweight="bold", color=_TEXT_BLACK)
        # Wrap y-tick labels in `$...$` so keys like `TAS_{1}` render
        # as math-subscripts (TAS_{1}) via matplotlib mathtext instead
        # of showing the curly braces literally.
        _ax.set_yticklabels(
            [f"${_t.get_text()}$" for _t in _ax.get_yticklabels()],
            color=_TEXT_BLACK,
        )

    if title:
        _fig.suptitle(title, **_SUPTITLE_STYLE)

    _save_figure(_fig, file_path, fname, verbose=verbose)
    return _fig


def plot_nd_diffmap(deltas: pd.DataFrame,
                    nodes: List[str],
                    *,
                    metrics: Optional[List[str]] = None,
                    labels: Optional[List[str]] = None,
                    cname: str = "key",
                    title: Optional[str] = None,
                    file_path: Optional[str] = None,
                    fname: Optional[str] = None,
                    verbose: bool = False) -> Figure:
    """*plot_nd_diffmap()* per-node delta heatmap (single panel). One cell per `(node, metric)` pair, coloured by the delta value on a diverging symmetric colour scale so 0 % sits at the colormap midpoint and equal-magnitude positive / negative changes read as equal-intensity colours.

    Args:
        deltas (pd.DataFrame): delta frame with one row per node; the `cname` column identifies the node and the metric columns hold per-node percent changes.
        nodes (List[str]): node identifiers to include (ordered by row).
        metrics (Optional[List[str]]): columns to plot. Defaults to every numeric column.
        labels (Optional[List[str]]): display labels for the metric columns. Defaults to the metric names.
        cname (str): column holding the node identifier. Defaults to `"key"`.
        title (Optional[str]): figure title.
        file_path (Optional[str]): directory to save into.
        fname (Optional[str]): filename (with extension).
        verbose (bool): if True, prints one save message per format.

    Raises:
        ValueError: If `cname` or any of `metrics` is missing from `deltas`.

    Returns:
        Figure: the matplotlib figure.
    """
    # validate required columns up front
    if cname not in deltas.columns:
        _msg = f"Node-name column {cname!r} not found in deltas"
        raise ValueError(_msg)

    # resolve metric / label defaults, then check they are present
    _metrics = _resolve_metrics(deltas, metrics)
    if cname in _metrics:
        _metrics.remove(cname)
    _missing = [_m for _m in _metrics if _m not in deltas.columns]
    if _missing:
        _msg = f"Missing metric columns in deltas: {_missing}"
        raise ValueError(_msg)
    _labels = _resolve_labels(_metrics, labels)

    # filter + order rows by the caller's node list
    _rows = []
    for _k_node in nodes:
        _sub = deltas[deltas[cname] == _k_node]
        if not _sub.empty:
            _rows.append(_sub.iloc[0])
    if not _rows:
        _msg = "No matching nodes found in deltas; "
        _msg += f"available: {list(deltas[cname].unique())}"
        raise ValueError(_msg)

    _plot_df = pd.DataFrame(_rows).reset_index(drop=True)
    _nd_names = _plot_df[cname].tolist()
    _matrix = _plot_df[_metrics].to_numpy(dtype=float)

    # symmetric colour scale centred on 0 so positive / negative deltas
    # read as equal-intensity; fall back to 1.0 if the frame is empty
    _vmax = float(np.nanmax(np.abs(_matrix)))
    if np.isnan(_vmax) or _vmax == 0:
        _vmax = 1.0
    _vmin = -_vmax

    # figure height scales with the node count so 13-row cases stay
    # readable without tiny cells
    _fig, _ax = plt.subplots(
        figsize=(max(10, len(_metrics) * 1.6), len(_nd_names) * 0.55 + 2),
        facecolor="white")
    _ax.set_facecolor("white")

    # draw the heatmap with a diverging cmap; NaN cells get masked
    _mask = np.isnan(_matrix)
    _im = _ax.imshow(_matrix, cmap=_HEATMAP_CMAP, aspect="auto",
                     vmin=_vmin, vmax=_vmax)

    # colourbar on the right
    _cbar = _fig.colorbar(_im, ax=_ax, pad=0.02)
    _cbar.set_label("Relative Change (%)",
                    rotation=270, labelpad=18,
                    color=_TEXT_BLACK, fontsize=12, fontweight="bold")
    _cbar.ax.tick_params(colors=_TEXT_BLACK)

    # annotate each cell with its numeric delta; skip NaN cells
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
                     ha="center", va="center",
                     color=_TEXT_BLACK, fontweight="bold", fontsize=10)

    # tick labels: metric names on x, node names on y
    _ax.set_xticks(np.arange(len(_metrics)))
    _ax.set_yticks(np.arange(len(_nd_names)))
    _ax.set_xticklabels(_labels, rotation=45, ha="right",
                        fontweight="bold", color=_TEXT_BLACK)
    # Wrap y-tick labels in `$...$` so keys like `TAS_{1}` render as
    # math-subscripts via matplotlib mathtext (instead of printing the
    # curly braces literally).
    _ax.set_yticklabels([f"${_n}$" for _n in _nd_names],
                        color=_TEXT_BLACK)

    # minor grid lines between cells to separate them visually
    _ax.set_xticks(np.arange(-0.5, len(_metrics), 1), minor=True)
    _ax.set_yticks(np.arange(-0.5, len(_nd_names), 1), minor=True)
    _ax.grid(which="minor", color="white", linestyle="-", linewidth=1.5)
    _ax.tick_params(which="minor", length=0)

    _ax.set_title(title or "Per-node Delta Heatmap",
                  fontsize=14, fontweight="bold", color=_TEXT_BLACK, pad=20)

    _fig.tight_layout()
    _save_figure(_fig, file_path, fname, verbose=verbose)
    return _fig


# z-scores for common two-sided confidence levels; used by plot_nd_ci
# to turn `<metric>_std` into an error-bar half-width.
_Z_SCORES = {
    0.90: 1.645,
    0.95: 1.960,
    0.99: 2.576,
}


def plot_nd_ci(nds: pd.DataFrame,
               *,
               metric: str = "rho",
               reference: Optional[pd.DataFrame] = None,
               reference_name: str = "analytic",
               stochastic_name: str = "stochastic",
               metric_label: Optional[str] = None,
               confidence: float = 0.95,
               reps: Optional[int] = None,
               title: Optional[str] = None,
               file_path: Optional[str] = None,
               fname: Optional[str] = None,
               verbose: bool = False) -> Figure:
    """*plot_nd_ci()* per-node mean with a confidence-interval band, suitable for visualising the stochastic-method output where every metric carries a `<metric>_std` companion from the replication std-dev.

    When `reference` is supplied, its per-node value for the same metric is overlaid as a second marker series; that makes the plot a direct stochastic-vs-analytic cross-method check; the reference should fall INSIDE the stochastic error bars when the two methods agree.

    The CI half-width is `z * sigma / sqrt(reps)` when `reps` is given (a proper CI on the mean), or `z * sigma` otherwise (a "one-z-band" of rep-to-rep spread). `z` is pulled from `_Z_SCORES[confidence]`.

    Args:
        nds (pd.DataFrame): stochastic per-node frame; must have a
            `key` column, the `<metric>` column (mean across reps),
            and its `<metric>_std` companion.
        metric (str): which metric to plot (default `"rho"`).
        reference (Optional[pd.DataFrame]): optional reference frame
            (e.g. analytic solution) with the same `key` + `<metric>`
            columns. Values are matched by `key`.
        reference_name (str): legend label for the reference series.
        stochastic_name (str): legend label for the stochastic series.
        metric_label (Optional[str]): display label for the y-axis;
            LaTeX-friendly. Defaults to `"${metric}$"`.
        confidence (float): confidence level in {0.90, 0.95, 0.99}.
        reps (Optional[int]): number of replications; when given, the
            CI half-width scales as `z * sigma / sqrt(reps)` (CI on
            the mean). When None, the band is `z * sigma`.
        title (Optional[str]): figure title.
        file_path (Optional[str]): directory to save into.
        fname (Optional[str]): filename (with extension).
        verbose (bool): if True, prints one save message per format.

    Raises:
        ValueError: if `confidence` is not in `_Z_SCORES`, or the
            required columns are missing from `nds`.

    Returns:
        Figure: the matplotlib figure.
    """
    # validate required columns up front
    _std_col = f"{metric}_std"
    for _col in ("key", metric, _std_col):
        if _col not in nds.columns:
            _msg = f"plot_nd_ci: missing required column {_col!r} in nds"
            raise ValueError(_msg)

    # resolve the z-score for the requested confidence level
    if confidence not in _Z_SCORES:
        _msg = f"plot_nd_ci: unsupported confidence={confidence!r}; "
        _msg += f"allowed: {sorted(_Z_SCORES.keys())}"
        raise ValueError(_msg)
    _z = _Z_SCORES[confidence]

    # pull the stochastic mean + std columns into aligned arrays
    _keys = nds["key"].tolist()
    _means = nds[metric].to_numpy(dtype=float)
    _stds = nds[_std_col].to_numpy(dtype=float)

    # turn per-rep sigma into the error-bar half-width
    if reps is not None and reps > 0:
        _halfwidth = _z * _stds / np.sqrt(reps)
        _band_label = rf"{int(confidence * 100)}% CI (reps={reps})"
    else:
        _halfwidth = _z * _stds
        _band_label = rf"$\pm {_z:.2f}\sigma$ band"

    # figure + axis
    _fig, _ax = plt.subplots(
        figsize=(max(10, 0.7 * len(_keys) + 3), 6),
        facecolor="white",
    )
    _ax.set_facecolor("white")
    _x = np.arange(len(_keys))

    # stochastic mean with error bars
    _ax.errorbar(
        _x, _means, yerr=_halfwidth,
        fmt="o", capsize=5, capthick=1.5, elinewidth=1.5, markersize=8,
        color=_BAR_BLUE, ecolor=_TEXT_BLACK,
        label=f"{stochastic_name} mean  ({_band_label})",
    )

    # optional reference overlay (matched by `key`)
    if reference is not None:
        if "key" not in reference.columns:
            _msg = "plot_nd_ci: reference frame missing 'key' column"
            raise ValueError(_msg)
        if metric not in reference.columns:
            _msg = f"plot_nd_ci: reference frame missing {metric!r} column"
            raise ValueError(_msg)
        _ref_by_key = dict(zip(reference["key"], reference[metric]))
        _ref_vals = [_ref_by_key.get(_k, np.nan) for _k in _keys]
        _ax.plot(
            _x, _ref_vals,
            linestyle="none", marker="x", markersize=10, markeredgewidth=2,
            color=_BAR_ORANGE,
            label=f"{reference_name} mean",
        )

    # axis cosmetics: keys on x as mathtext subscripts, metric symbol on y
    _ax.set_xticks(_x)
    _ax.set_xticklabels([f"${_k}$" for _k in _keys],
                        rotation=45, ha="right",
                        fontweight="bold", color=_TEXT_BLACK)
    _ax.set_ylabel(metric_label or f"${metric}$",
                   color=_TEXT_BLACK, fontsize=13, fontweight="bold")
    _ax.grid(**_GRID_STYLE)
    _ax.legend(loc="best", frameon=True, fancybox=True, shadow=True)

    _ax.set_title(
        title or f"Per-node {metric} (stochastic "
                 f"{int(confidence * 100)}% CI)",
        **_TITLE_STYLE,
    )

    _fig.tight_layout()
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
        nets (List[pd.DataFrame]): per-scenario single-row network frames produced by `aggregate_net()`.
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

    # vibrant per-scenario palette (rainbow / Spectral / turbo, picked
    # based on scenario count; ported from __OLD__/src/notebooks/src/
    # display.py::_generate_color_map)
    _scenario_colors = _generate_color_map(names)

    _fig, _ax = plt.subplots(figsize=(max(12, len(_metrics) * 1.5), 8),
                             facecolor="white")
    _ax.set_facecolor("white")

    # draw bars + annotate each
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
            # same offset on both sides of zero; the bar's orientation picks the va.
            _y = _v * 1.05
            if _v >= 0:
                _va = "bottom"
            else:
                _va = "top"
            _ax.text(_positions[_i][_j], _y, _text,
                     ha="center", va=_va,
                     fontsize=10, rotation=90,
                     fontweight="light", color=_TEXT_BLACK,
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
    _ax.set_xticklabels(_labels, rotation=30, ha="right",
                        fontweight="bold", color=_TEXT_BLACK)

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

    Colouring is neutral and sign-only: negative deltas (the metric decreased) are drawn pastel blue, positive deltas (the metric increased) are drawn pastel orange. Whether a decrease / increase is "good" or "bad" is a domain concern; the caller interprets the colours in context (e.g. for `total_throughput`, an increase is desirable; for `W_net`, a decrease is desirable).

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

    # uniform sign-only colour rule: negative delta (below the zero baseline) -> decrease -> pastel blue; positive delta -> increase -> pastel orange. No per-metric special cases, so the caller-supplied metric order does not change the colouring; domain interpretation (good / bad) is left to the caller.
    _colors: List[str] = []
    for _v in _values:
        if _v < 0:
            _colors.append(_BAR_BLUE)
        else:
            _colors.append(_BAR_ORANGE)

    _fig, _ax = plt.subplots(figsize=(12, 7), facecolor="white")
    _ax.set_facecolor("white")

    _bars = _ax.bar(range(len(_metrics)), _values, color=_colors,
                    edgecolor="black", linewidth=0.5, alpha=0.85)

    # annotate each bar with its percent value
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
                 fontsize=11, fontweight="light", color=_TEXT_BLACK)

    # cosmetics: zero baseline, ticks, labels, grid, legend
    _ax.axhline(y=0, color="black", linestyle="-", alpha=0.3)
    _ax.set_xticks(range(len(_metrics)))
    _ax.set_xticklabels(_labels, rotation=30, ha="right",
                        fontweight="bold", color=_TEXT_BLACK)
    _ax.set_ylabel("Percent change (%)", **_LBL_STYLE)
    _ax.set_title(title or "Network Metrics Delta", **_TITLE_STYLE)
    _ax.grid(**_GRID_STYLE)

    _legend = [
        plt.Rectangle((0, 0), 1, 1, facecolor=_BAR_BLUE, alpha=0.85,
                      label="Decrease"),
        plt.Rectangle((0, 0), 1, 1, facecolor=_BAR_ORANGE, alpha=0.85,
                      label="Increase"),
    ]
    _ax.legend(handles=_legend, loc="best")

    # pad the y-range so annotations do not clip at the edges
    _y_lo = min(min(_values) * 1.1, -2.0)
    _y_hi = max(max(_values) * 1.1, 2.0)
    _ax.set_ylim(_y_lo, _y_hi)

    _fig.tight_layout()
    _save_figure(_fig, file_path, fname, verbose=verbose)
    return _fig

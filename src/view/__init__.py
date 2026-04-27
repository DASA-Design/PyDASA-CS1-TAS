# -*- coding: utf-8 -*-
"""Plotting helpers for the CS-01 TAS case study.

Four-module split (live since 2026-04-27):

    - `common.py`            shared design-contract primitives + family-private helpers
    - `characterization.py`  calibration plotters (per-host noise-floor envelope)
    - `charter.py`           yoly coefficient charts (theta, sigma, eta, phi)
    - `diagrams.py`          queueing topology + per-node heatmaps + architecture bars

The `*__OLD__.py` reference oracles were dropped on 2026-04-27 once notebooks
migrated to the new family-prefixed names. See `notes/view_refactor.md` for the
full migration record.
"""

# shared design-contract primitives + project-wide constants
from src.view.common import (
    AxisSpec,
    BodySpec,
    DIM_GLOSSARY_DEFAULT,
    FigureLayout,
    QN_GLOSSARY_DEFAULT,
    attach_axis_spec,
    build_stacked_figure,
    render_footer_legend,
    render_footer_summary,
    render_footer_table,
)
# calibration family
from src.view.characterization import (
    plot_calib_dashboard,
    plot_calib_handler_scaling,
    plot_calib_rate_sweep,
)
# yoly family
from src.view.charter import (
    plot_yoly_arts_behaviour,
    plot_yoly_arts_charts,
    plot_yoly_arts_hist,
    plot_yoly_chart,
    plot_yoly_space,
)
# topology + heatmap + bars + CI family
from src.view.diagrams import (
    plot_arch_bars,
    plot_arch_delta,
    plot_dim_topology,
    plot_node_ci,
    plot_node_diffmap,
    plot_node_heatmap,
    plot_qn_topology,
)

__all__ = [
    # design-contract primitives
    "AxisSpec",
    "BodySpec",
    "FigureLayout",
    "attach_axis_spec",
    "build_stacked_figure",
    "render_footer_legend",
    "render_footer_summary",
    "render_footer_table",
    # public defaults
    "DIM_GLOSSARY_DEFAULT",
    "QN_GLOSSARY_DEFAULT",
    # public plotters (family-prefixed)
    "plot_arch_bars",
    "plot_arch_delta",
    "plot_calib_dashboard",
    "plot_calib_handler_scaling",
    "plot_calib_rate_sweep",
    "plot_dim_topology",
    "plot_node_ci",
    "plot_node_diffmap",
    "plot_node_heatmap",
    "plot_qn_topology",
    "plot_yoly_arts_behaviour",
    "plot_yoly_arts_charts",
    "plot_yoly_arts_hist",
    "plot_yoly_chart",
    "plot_yoly_space",
]

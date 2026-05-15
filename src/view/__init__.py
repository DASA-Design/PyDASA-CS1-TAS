# -*- coding: utf-8 -*-
"""Plotting helpers for the CS-01 TAS case study.

Module split:

- `common.py`: shared design-contract primitives + family-private helpers.
- `charter.py`: yoly coefficient charts (theta, sigma, eta, phi).
- `diagrams.py`: queueing topology + per-node heatmaps + architecture bars.
- `characterization.py`: calibration envelope diagnostics.
- `bench.py`: multi-trial benchmark distribution + R1/R2 verdict matrix plotters.
"""

# shared design-contract primitives + project-wide constants
from src.view.bench import (
    plot_rs_by_stack,
    plot_verdict_matrix,
    plot_x0_distribution,
)
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
    plot_calibration_summary,
    plot_envelope_overlay,
    plot_handler_scaling,
    plot_jitter,
    plot_loopback,
    plot_rate_sweep,
    plot_timer,
    plot_workers_scaling,
)
# yoly family
from src.view.charter import (
    plot_yoly_arts_behaviour,
    plot_yoly_arts_charts,
    plot_yoly_arts_hist,
    plot_yoly_arts_with_op_points,
    plot_yoly_chart,
    plot_yoly_space,
    plot_yoly_with_op_points,
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
    "plot_calibration_summary",
    "plot_dim_topology",
    "plot_envelope_overlay",
    "plot_handler_scaling",
    "plot_jitter",
    "plot_loopback",
    "plot_node_ci",
    "plot_node_diffmap",
    "plot_node_heatmap",
    "plot_qn_topology",
    "plot_rate_sweep",
    "plot_rs_by_stack",
    "plot_timer",
    "plot_verdict_matrix",
    "plot_workers_scaling",
    "plot_x0_distribution",
    "plot_yoly_arts_behaviour",
    "plot_yoly_arts_charts",
    "plot_yoly_arts_hist",
    "plot_yoly_arts_with_op_points",
    "plot_yoly_chart",
    "plot_yoly_space",
    "plot_yoly_with_op_points",
]

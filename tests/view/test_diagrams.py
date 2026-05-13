"""Tests for `src.view.diagrams` heatmap / diffmap behaviour.

Covers two contracts that callers rely on:

- `plot_node_heatmap` aligns rows by position; each panel's y-axis labels come from its own `cname` column. Shorter panels NaN-pad so heights stay aligned across scenarios.
- `plot_node_diffmap` accepts a per-row `y_labels` override for the case where the adaptation deploys different keys than `nodes` at swap slots.
"""

from __future__ import annotations

from pathlib import Path

import matplotlib
import pandas as pd
import pytest
from matplotlib.figure import Figure

from src.view.diagrams import plot_node_diffmap, plot_node_heatmap


matplotlib.use("Agg")


def _ndss_pair() -> tuple[pd.DataFrame, pd.DataFrame]:
    """Two per-scenario node frames that share three keys and disagree on one swap slot.

    Returns:
        tuple[pd.DataFrame, pd.DataFrame]: `(baseline_df, swap_df)`. The swap frame
            replaces `MAS_{3}` with `MAS_{4}` at the same row position.
    """
    _common = [
        {"key": "TAS_{1}", "rho": 0.1, "L": 1.0, "W": 0.01},
        {"key": "MAS_{1}", "rho": 0.2, "L": 2.0, "W": 0.02},
    ]
    _baseline = pd.DataFrame(_common + [{"key": "MAS_{3}", "rho": 0.3, "L": 3.0, "W": 0.03}])
    _swap = pd.DataFrame(_common + [{"key": "MAS_{4}", "rho": 0.4, "L": 4.0, "W": 0.04}])
    return _baseline, _swap


class TestPlotNodeHeatmap:
    """**TestPlotNodeHeatmap** contracts for `src.view.plot_node_heatmap`.

    - *test_panel_heights_stay_aligned()* rows align by position; every panel renders the same row count.
    - *test_per_panel_keys_label_y_axis()* each panel's y-axis tick labels come from its own `cname` column, so swap-slot rows carry the panel's actual service key.
    - *test_persists_png_and_svg()* both formats land when `file_path` + `fname` are given.
    """

    def test_panel_heights_stay_aligned(self) -> None:
        """*test_panel_heights_stay_aligned()* swap panel renders the same row count as the baseline panel even though it carries different keys."""
        _bl, _sw = _ndss_pair()
        _fig = plot_node_heatmap(
            ndss=[_bl, _sw],
            names=["baseline", "swap"],
            metrics=["rho", "L", "W"],
        )
        assert isinstance(_fig, Figure)
        _fig.canvas.draw()
        # build_stacked_figure prepends a title axis; body panels start at index 1.
        _panel_axes = _fig.axes[1:3]
        for _ax in _panel_axes:
            _labels = [_t.get_text() for _t in _ax.get_yticklabels() if _t.get_text()]
            assert len(_labels) == len(_bl)

    def test_per_panel_keys_label_y_axis(self, tmp_path: Path) -> None:
        """*test_per_panel_keys_label_y_axis()* each panel's y-axis carries its own `key` column values; swap-slot rows differ per panel."""
        _bl, _sw = _ndss_pair()
        _fig = plot_node_heatmap(
            ndss=[_bl, _sw],
            names=["baseline", "swap"],
            metrics=["rho", "L", "W"],
            file_path=str(tmp_path),
            fname="heatmap_pair",
        )
        _fig.canvas.draw()
        _bl_labels = [_t.get_text() for _t in _fig.axes[1].get_yticklabels()]
        _sw_labels = [_t.get_text() for _t in _fig.axes[2].get_yticklabels()]
        # Mathtext-wrapped keys appear per panel: baseline -> MAS_{3}, swap -> MAS_{4}.
        assert "$MAS_{3}$" in _bl_labels
        assert "$MAS_{4}$" in _sw_labels

    def test_persists_png_and_svg(self, tmp_path: Path) -> None:
        """*test_persists_png_and_svg()* both formats written when `file_path` is set."""
        _bl, _sw = _ndss_pair()
        plot_node_heatmap(ndss=[_bl, _sw],
                          names=["baseline", "swap"],
                          metrics=["rho", "L", "W"],
                          file_path=str(tmp_path),
                          fname="hm_smoke")
        assert (tmp_path / "hm_smoke.png").exists()
        assert (tmp_path / "hm_smoke.svg").exists()


class TestPlotNodeDiffmap:
    """**TestPlotNodeDiffmap** contracts for `src.view.plot_node_diffmap`.

    - *test_y_labels_overrides_default()* `y_labels` replaces the default y-axis ticks (which come from `nodes`).
    - *test_y_labels_validates_length()* a `y_labels` length mismatch raises `ValueError`.
    """

    def test_y_labels_overrides_default(self, tmp_path: Path) -> None:
        """*test_y_labels_overrides_default()* the y-axis shows the override labels in mathtext form."""
        _deltas = pd.DataFrame([
            {"key": "slot_0", "rho": 0.1, "L": 0.2, "W": 0.05},
            {"key": "slot_1", "rho": -0.1, "L": -0.2, "W": -0.05},
        ])
        _fig = plot_node_diffmap(deltas=_deltas,
                                 nodes=["slot_0", "slot_1"],
                                 metrics=["rho", "L", "W"],
                                 y_labels=["TAS_{1}", "MAS_{4}"],
                                 file_path=str(tmp_path),
                                 fname="dm_labels")
        _fig.canvas.draw()
        # axes[0] is the title strip; the body panel is at index 1.
        _ax = _fig.axes[1]
        _texts = [_t.get_text() for _t in _ax.get_yticklabels()]
        assert "$TAS_{1}$" in _texts
        assert "$MAS_{4}$" in _texts

    def test_y_labels_validates_length(self) -> None:
        """*test_y_labels_validates_length()* mismatched `y_labels` length raises `ValueError`."""
        _deltas = pd.DataFrame([
            {"key": "slot_0", "rho": 0.1},
            {"key": "slot_1", "rho": -0.1},
        ])
        with pytest.raises(ValueError, match="y_labels length"):
            plot_node_diffmap(deltas=_deltas,
                              nodes=["slot_0", "slot_1"],
                              y_labels=["only_one"])

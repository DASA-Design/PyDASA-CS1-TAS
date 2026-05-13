"""Tests for the yoly + dimensional-operating-point overlay.

Covers the two-piece feature added to overlay the dimensional method's
architecture-level coefficient point onto the yoly sweep:

- `src.dimensional.load_dim_op_points` — reads saved per-adp dimensional JSONs and aggregates each to a `{theta, sigma, eta, phi}` 4-tuple via `coefs_to_net` (mean over per-node coefficients), matching what `03-dimensional.ipynb` displays.
- `src.view.plot_yoly_with_op_points` — wraps `plot_yoly_chart` (`kind="chart"`) or `plot_yoly_space` (`kind="space"`), adds star markers + a dim-grey trajectory line + adp tags on every body panel.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict

import matplotlib
import numpy as np
import pytest
from matplotlib.figure import Figure

from src.dimensional import load_dim_op_points, load_dim_op_points_per_node
from src.view import plot_yoly_arts_with_op_points, plot_yoly_with_op_points


matplotlib.use("Agg")


def _synth_arch_sweep(tag: str = "TAS", n: int = 8) -> Dict[str, Any]:
    """Build a minimal architecture-level sweep dict the yoly plotters can consume.

    Args:
        tag (str): architecture subscript baked into every key (e.g. `\\theta_{<tag>}`).
        n (int): number of sweep points per coefficient.

    Returns:
        Dict[str, Any]: keys `\\theta_{tag}`, `\\sigma_{tag}`, `\\eta_{tag}`, `\\phi_{tag}`, `c_{tag}`, `\\mu_{tag}`, `K_{tag}`, each mapped to an `n`-element float array. Values are arbitrary but non-degenerate so seaborn / matplotlib do not collapse the axis ranges.
    """
    _rng = np.random.default_rng(seed=0)
    _ans: Dict[str, Any] = {}
    for _coef in ("theta", "sigma", "eta", "phi"):
        _ans[f"\\{_coef}_{{{tag}}}"] = _rng.uniform(0.05, 0.5, size=n)
    _ans[f"c_{{{tag}}}"] = np.array([1] * n, dtype=int)
    _ans[f"\\mu_{{{tag}}}"] = np.array([1.0] * n)
    _ans[f"K_{{{tag}}}"] = np.array([10] * n, dtype=int)
    return _ans


def _synth_op_points() -> Dict[str, Dict[str, float]]:
    """Two-adp operating-point dict matching the wrapper's input contract."""
    return {
        "baseline":  {"theta": 0.10, "sigma": 0.05, "eta": 0.20, "phi": 0.10},
        "aggregate": {"theta": 0.30, "sigma": 0.15, "eta": 0.40, "phi": 0.30},
    }


class TestPlotYolyOverlay:
    """**TestPlotYolyOverlay** contracts for `src.view.plot_yoly_with_op_points`.

    - *test_chart_overlay()* the 2x2 yoly chart wrapper produces a Figure with four body axes; each body panel carries one trajectory line + the per-adp star scatters.
    - *test_space_overlay()* the 3D yoly space wrapper produces a Figure with one 3D body axis carrying the overlay markers.
    - *test_invalid_kind_raises()* unknown `kind` values raise `ValueError`.
    """

    def test_chart_overlay(self, tmp_path: Path) -> None:
        """*test_chart_overlay()* every panel renders the trajectory line + N star scatters."""
        _arch = _synth_arch_sweep()
        _ops = _synth_op_points()
        _fig = plot_yoly_with_op_points(_arch,
                                        _ops,
                                        kind="chart",
                                        file_path=str(tmp_path),
                                        fname="hm_overlay")
        assert isinstance(_fig, Figure)
        _fig.canvas.draw()
        _body = [_ax for _ax in _fig.axes
                 if getattr(_ax, "axison", False)
                 and getattr(_ax, "name", "") != "3d"]
        assert len(_body) == 4
        # Each body axis should carry at least 1 line (the trajectory) and one scatter
        # collection per adp (matplotlib stores scatter as a PathCollection).
        for _ax in _body:
            assert len(_ax.lines) >= 1, "trajectory line missing on a panel"
            assert len(_ax.collections) >= len(_ops), "missing per-adp star scatters"
        assert (tmp_path / "hm_overlay.png").exists()
        assert (tmp_path / "hm_overlay.svg").exists()

    def test_space_overlay(self, tmp_path: Path) -> None:
        """*test_space_overlay()* the 3D body axis carries the overlay trajectory + per-adp scatters."""
        _arch = _synth_arch_sweep()
        _ops = _synth_op_points()
        _fig = plot_yoly_with_op_points(_arch,
                                        _ops,
                                        kind="space",
                                        file_path=str(tmp_path),
                                        fname="sp_overlay")
        assert isinstance(_fig, Figure)
        _fig.canvas.draw()
        _body = [_ax for _ax in _fig.axes if getattr(_ax, "name", "") == "3d"]
        assert len(_body) == 1
        _ax = _body[0]
        assert len(_ax.lines) >= 1, "3D trajectory line missing"
        # Each adp contributes one Path3DCollection.
        assert len(_ax.collections) >= len(_ops)

    def test_invalid_kind_raises(self) -> None:
        """*test_invalid_kind_raises()* unknown `kind` is rejected before any plotting."""
        with pytest.raises(ValueError, match="kind must be"):
            plot_yoly_with_op_points(_synth_arch_sweep(),
                                     _synth_op_points(),
                                     kind="bogus")  # type: ignore[arg-type]


class TestLoadDimOpPoints:
    """**TestLoadDimOpPoints** contracts for `src.dimensional.load_dim_op_points`.

    - *test_loader_roundtrip()* synthesise a per-adp dimensional JSON in `tmp_path`, run the loader against the `base=` override, assert the returned dict carries the expected 4-tuple per adp.
    - *test_missing_raises()* a missing per-adp JSON raises `FileNotFoundError`.
    """

    def _write_dim_json(self, root: Path, adp: str, profile: str,
                        coefs: Dict[str, float]) -> None:
        """Write a minimal dimensional result JSON the loader can read.

        Args:
            root (Path): per-method results root (the loader's `base=` argument).
            adp (str): adaptation key.
            profile (str): `dflt` for baseline, `opti` otherwise.
            coefs (Dict[str, float]): `{theta, sigma, eta, phi}` setpoints to bake into the synthesised TAS_{1} artifact (the loader averages across artifacts; one is enough).
        """
        _dir = root / adp
        _dir.mkdir(parents=True, exist_ok=True)
        _payload = {
            "profile": profile,
            "scenario": adp,
            "method": "dimensional",
            "artifacts": {
                "TAS_{1}": {
                    "name": "TAS_{1}",
                    "type": "M/M/s/K",
                    "coefficients": {
                        f"\\{_c}_{{TAS_{{1}}}}": {
                            "setpoint": float(coefs[_c]),
                            "expr": "synthetic",
                            "var_dims": {},
                            "name": _c,
                            "description": "test",
                        }
                        for _c in ("theta", "sigma", "eta", "phi")
                    },
                    "sensitivity": {},
                },
            },
        }
        (_dir / f"{profile}.json").write_text(json.dumps(_payload))

    def test_loader_roundtrip(self, tmp_path: Path) -> None:
        """*test_loader_roundtrip()* the loader returns the expected 4-tuple per adp; baseline reads `dflt.json`, others read `opti.json`."""
        self._write_dim_json(tmp_path, "baseline", "dflt",
                             {"theta": 0.1, "sigma": 0.2, "eta": 0.3, "phi": 0.4})
        self._write_dim_json(tmp_path, "aggregate", "opti",
                             {"theta": 0.5, "sigma": 0.6, "eta": 0.7, "phi": 0.8})
        _out = load_dim_op_points(["baseline", "aggregate"], base=tmp_path)
        assert list(_out.keys()) == ["baseline", "aggregate"]
        assert _out["baseline"] == pytest.approx(
            {"theta": 0.1, "sigma": 0.2, "eta": 0.3, "phi": 0.4})
        assert _out["aggregate"] == pytest.approx(
            {"theta": 0.5, "sigma": 0.6, "eta": 0.7, "phi": 0.8})

    def test_missing_raises(self, tmp_path: Path) -> None:
        """*test_missing_raises()* missing per-adp JSON surfaces as `FileNotFoundError`."""
        with pytest.raises(FileNotFoundError, match="dimensional result not found"):
            load_dim_op_points(["baseline"], base=tmp_path)


def _synth_per_node_sweep(node_keys: list, tag_per_node: bool = True,
                          n: int = 8) -> Dict[str, Any]:
    """Build a nested per-node sweep dict the `plot_yoly_arts_*` plotters consume.

    Args:
        node_keys (list): artifact keys to populate.
        tag_per_node (bool): if True, each node's symbols carry its own subscript (the production shape); when False, all nodes share a `tag` subscript (defensive coverage).
        n (int): sweep length per coefficient.

    Returns:
        Dict[str, Any]: `{node_key: {full_symbol: ndarray}}`.
    """
    _rng = np.random.default_rng(seed=1)
    _ans: Dict[str, Dict[str, Any]] = {}
    for _k in node_keys:
        _sub: Dict[str, Any] = {}
        _tag = _k if tag_per_node else "TAS"
        for _coef in ("theta", "sigma", "eta", "phi"):
            _sub[f"\\{_coef}_{{{_tag}}}"] = _rng.uniform(0.05, 0.5, size=n)
        _sub[f"c_{{{_tag}}}"] = np.array([1] * n, dtype=int)
        _sub[f"\\mu_{{{_tag}}}"] = np.array([1.0] * n)
        _sub[f"K_{{{_tag}}}"] = np.array([10] * n, dtype=int)
        _ans[_k] = _sub
    return _ans


class TestPlotYolyArtsOverlay:
    """**TestPlotYolyArtsOverlay** contracts for `src.view.plot_yoly_arts_with_op_points`.

    - *test_per_node_overlay()* every node cell receives the per-adp star scatters; cells whose adp dict lacks the node simply skip the marker.
    """

    def test_per_node_overlay(self, tmp_path: Path) -> None:
        """*test_per_node_overlay()* the per-node wrapper renders one 3D cell per node, each with overlay artefacts."""
        _node_keys = ["TAS_{1}", "MAS_{1}"]
        _sweep = _synth_per_node_sweep(_node_keys)
        _ops: Dict[str, Dict[str, Dict[str, float]]] = {
            "baseline": {_k: {"theta": 0.1, "sigma": 0.1, "eta": 0.2, "phi": 0.1}
                         for _k in _node_keys},
            "aggregate": {_k: {"theta": 0.3, "sigma": 0.2, "eta": 0.4, "phi": 0.3}
                          for _k in _node_keys},
        }
        _fig = plot_yoly_arts_with_op_points(_sweep,
                                             _ops,
                                             file_path=str(tmp_path),
                                             fname="arts_overlay")
        _fig.canvas.draw()
        _cells = [_ax for _ax in _fig.axes if getattr(_ax, "name", "") == "3d"]
        assert len(_cells) == len(_node_keys)
        for _ax in _cells:
            assert len(_ax.lines) >= 1, "trajectory line missing on a cell"
            assert len(_ax.collections) >= len(_ops)


class TestLoadDimOpPointsPerNode:
    """**TestLoadDimOpPointsPerNode** contracts for `load_dim_op_points_per_node`.

    - *test_per_node_roundtrip()* synthesised JSON round-trips through the loader; output exposes per-adp `{node_key: 4-tuple}`.
    """

    def test_per_node_roundtrip(self, tmp_path: Path) -> None:
        """*test_per_node_roundtrip()* writes a 2-artifact synthetic JSON and reads it back."""
        _payload = {
            "profile": "dflt",
            "scenario": "baseline",
            "method": "dimensional",
            "artifacts": {
                "TAS_{1}": {
                    "name": "TAS_{1}", "type": "M/M/s/K",
                    "coefficients": {
                        "\\theta_{TAS_{1}}": {"setpoint": 0.1, "expr": "", "var_dims": {}, "name": "theta", "description": ""},
                        "\\sigma_{TAS_{1}}": {"setpoint": 0.2, "expr": "", "var_dims": {}, "name": "sigma", "description": ""},
                        "\\eta_{TAS_{1}}":   {"setpoint": 0.3, "expr": "", "var_dims": {}, "name": "eta",   "description": ""},
                        "\\phi_{TAS_{1}}":   {"setpoint": 0.4, "expr": "", "var_dims": {}, "name": "phi",   "description": ""},
                    },
                    "sensitivity": {},
                },
                "MAS_{1}": {
                    "name": "MAS_{1}", "type": "M/M/s/K",
                    "coefficients": {
                        "\\theta_{MAS_{1}}": {"setpoint": 0.5, "expr": "", "var_dims": {}, "name": "theta", "description": ""},
                        "\\sigma_{MAS_{1}}": {"setpoint": 0.6, "expr": "", "var_dims": {}, "name": "sigma", "description": ""},
                        "\\eta_{MAS_{1}}":   {"setpoint": 0.7, "expr": "", "var_dims": {}, "name": "eta",   "description": ""},
                        "\\phi_{MAS_{1}}":   {"setpoint": 0.8, "expr": "", "var_dims": {}, "name": "phi",   "description": ""},
                    },
                    "sensitivity": {},
                },
            },
        }
        _dir = tmp_path / "baseline"
        _dir.mkdir(parents=True)
        (_dir / "dflt.json").write_text(json.dumps(_payload))
        _out = load_dim_op_points_per_node(["baseline"], base=tmp_path)
        assert list(_out.keys()) == ["baseline"]
        assert set(_out["baseline"].keys()) == {"TAS_{1}", "MAS_{1}"}
        assert _out["baseline"]["TAS_{1}"] == pytest.approx(
            {"theta": 0.1, "sigma": 0.2, "eta": 0.3, "phi": 0.4})
        assert _out["baseline"]["MAS_{1}"] == pytest.approx(
            {"theta": 0.5, "sigma": 0.6, "eta": 0.7, "phi": 0.8})

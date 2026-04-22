# -*- coding: utf-8 -*-
"""
Module test_jackson.py
======================

Sanity checks for the Jackson traffic-equation solver and rho-indexed helpers in `src.analytic.jackson`. The `solve_network()` wrapper is exercised end-to-end by the analytic method test suite.

    - **TestJacksonSolver** small worked examples where the expected per-node arrival rates are obvious from flow conservation.
    - **TestPerArtifactLambdas** the per-artifact lambda vector is linear in lambda_z (Jackson linearity).
    - **TestPerArtifactRhos** `rho_i = lam_i / (c_i * mu_i)` finite for well-formed profiles; monotone in lambda_z.
    - **TestLambdaZForRho** FR-3.5 closed-form inversion; bottleneck hits target rho exactly.
    - **TestBuildRhoGrid** rho-grid to lambda-grid map for the experiment orchestrator.

# TODO: add a regression case for a 3-node cycle with external arrivals at multiple nodes, once that topology is actually used.
"""
# scientific stack
import numpy as np

# testing framework
import pytest

# modules under test
from src.analytic.jackson import (build_rho_grid,
                                  lambda_z_for_rho,
                                  per_artifact_lambdas,
                                  per_artifact_rhos,
                                  solve_jackson_lambdas)
from src.io import load_profile


class TestJacksonSolver:
    """**TestJacksonSolver** verifies `solve_jackson_lambdas()` returns per-node arrival rates expected from flow conservation on small, hand-checkable topologies."""

    def test_two_node_feedforward(self):
        """*test_two_node_feedforward()* node 0 routes everything to node 1 (p=1). External arrivals enter node 0 only. Expected: lamb_0 = lamb_ext, lamb_1 = p * lamb_0."""
        # Routing matrix: row = source, col = dest. All flow 0 -> 1.
        _P = np.array([[0.0, 1.0],
                       [0.0, 0.0]])
        _lambdas = solve_jackson_lambdas(_P, [10.0, 0.0])

        # node 0 sees the full external rate; node 1 inherits all of it
        assert _lambdas[0] == pytest.approx(10.0)
        assert _lambdas[1] == pytest.approx(10.0)

    def test_two_node_split(self):
        """*test_two_node_split()* node 0 routes 70 % of its flow to node 1 and 30 % to the exit. External arrivals only at node 0."""
        _P = np.array([[0.0, 0.7],
                       [0.0, 0.0]])
        _lambdas = solve_jackson_lambdas(_P, [100.0, 0.0])

        # node 0 carries the full 100; node 1 receives 70 % of it
        assert _lambdas[0] == pytest.approx(100.0)
        assert _lambdas[1] == pytest.approx(70.0)

    def test_no_external_no_flow(self):
        """*test_no_external_no_flow()* with zero external arrivals, every node's effective arrival rate must be zero regardless of the routing matrix."""
        _P = np.array([[0.0, 0.5],
                       [0.5, 0.0]])
        _lambdas = solve_jackson_lambdas(_P, [0.0, 0.0])

        # no arrivals anywhere => the whole system is idle
        assert np.allclose(_lambdas, 0.0)

    def test_shape_preserved(self):
        """*test_shape_preserved()* the solver's output vector must match the input dimensionality (13-node TAS baseline)."""
        _P = np.zeros((13, 13))
        _lambdas = solve_jackson_lambdas(_P, np.zeros(13))

        # shape must match the number of nodes in the network
        assert _lambdas.shape == (13,)


# ---- rho-indexed helpers ------------------------------------------------


@pytest.fixture(scope="module")
def _cfg():
    """*_cfg()* module-cached baseline profile used by every rho-indexed helper test."""
    return load_profile(adaptation="baseline")


class TestPerArtifactLambdas:
    """**TestPerArtifactLambdas** Jackson lambda vector is linear in lambda_z."""

    def test_zero_entry_gives_zero_everywhere(self, _cfg):
        """*test_zero_entry_gives_zero_everywhere()* with zero external entry rate, every artifact's lambda must be zero."""
        _lams = per_artifact_lambdas(_cfg, 0.0)
        assert np.allclose(_lams, 0.0)

    def test_linear_in_lambda_z(self, _cfg):
        """*test_linear_in_lambda_z()* doubling lambda_z doubles every lambda_i (Jackson linearity)."""
        _a = per_artifact_lambdas(_cfg, 10.0)
        _b = per_artifact_lambdas(_cfg, 20.0)
        assert np.allclose(_b, 2.0 * _a, rtol=1e-9)


class TestPerArtifactRhos:
    """**TestPerArtifactRhos** `rho_i = lam_i / (c_i * mu_i)`; finite for well-formed profiles."""

    def test_all_finite_at_reasonable_lambda(self, _cfg):
        """*test_all_finite_at_reasonable_lambda()* every artifact's rho is finite at a plausible entry rate (no zero-capacity edge cases)."""
        _rhos = per_artifact_rhos(_cfg, 10.0)
        assert np.all(np.isfinite(_rhos))

    def test_monotone_in_lambda_z(self, _cfg):
        """*test_monotone_in_lambda_z()* every component's rho is non-decreasing in lambda_z."""
        _lo = per_artifact_rhos(_cfg, 5.0)
        _hi = per_artifact_rhos(_cfg, 50.0)
        assert np.all(_hi >= _lo - 1e-12)


class TestLambdaZForRho:
    """**TestLambdaZForRho** FR-3.5 closed-form inversion; bottleneck hits target rho exactly."""

    @pytest.mark.parametrize("_rho_target", [0.05, 0.20, 0.50, 0.80, 0.95])
    def test_bottleneck_hits_target(self, _cfg, _rho_target):
        """*test_bottleneck_hits_target()* inverted lambda_z makes the identified bottleneck hit rho_target exactly, and no other artifact exceeds that value."""
        _lam_z, _bottleneck, _per_unit = lambda_z_for_rho(_cfg, _rho_target)
        assert _lam_z > 0
        assert _per_unit > 0
        _rhos = per_artifact_rhos(_cfg, _lam_z)
        assert _rhos[_bottleneck] == pytest.approx(_rho_target, rel=1e-9)
        assert _rhos.max() == pytest.approx(_rho_target, rel=1e-9)

    def test_rejects_invalid_targets(self, _cfg):
        """*test_rejects_invalid_targets()* rho_target outside the open interval (0, 1) raises `ValueError`; the endpoints are included in the rejection set."""
        with pytest.raises(ValueError, match="must be in"):
            lambda_z_for_rho(_cfg, 0.0)
        with pytest.raises(ValueError, match="must be in"):
            lambda_z_for_rho(_cfg, 1.0)
        with pytest.raises(ValueError, match="must be in"):
            lambda_z_for_rho(_cfg, 1.5)


class TestBuildRhoGrid:
    """**TestBuildRhoGrid** rho-grid to lambda-grid map for the orchestrator."""

    def test_experiment_md_grid_produces_increasing_lambda(self, _cfg):
        """*test_experiment_md_grid_produces_increasing_lambda()* the full `notes/experiment.md` rho-grid maps to a monotonically increasing lambda_z sequence, with every tuple's rho matching its index."""
        _rho_grid = [0.05, 0.10, 0.20, 0.30, 0.40, 0.45, 0.50, 0.55,
                     0.60, 0.65, 0.70, 0.75, 0.80, 0.85, 0.90, 0.95]
        _grid = build_rho_grid(_cfg, _rho_grid)
        assert len(_grid) == len(_rho_grid)
        _lams = [_l for _, _l, _ in _grid]
        # Jackson linearity: rho monotone -> lambda_z monotone
        assert _lams == sorted(_lams)
        # every triple's rho matches its index
        for (_rho_got, _lam, _b), _rho_expected in zip(_grid, _rho_grid):
            assert _rho_got == pytest.approx(_rho_expected)
            assert _lam > 0
            assert isinstance(_b, int)

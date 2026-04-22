# -*- coding: utf-8 -*-
"""
Module test_rho_inversion.py
============================

Pins FR-3.5: given a target bottleneck utilisation `ρ`, the helper
returns the entry rate `λ_z` that makes the bottleneck artifact hit
`ρ` under the profile's Jackson routing.
"""
# native python modules

# testing framework
import pytest

# scientific stack
import numpy as np

# modules under test
from src.analytic.jackson import (build_rho_grid,
                                  lambda_z_for_rho,
                                  per_artifact_lambdas,
                                  per_artifact_rhos)
from src.io import load_profile


@pytest.fixture(scope="module")
def _cfg():
    return load_profile(adaptation="baseline")


class TestPerArtifactLambdas:
    """**TestPerArtifactLambdas** Jackson λ vector is linear in λ_z."""

    def test_zero_entry_gives_zero_everywhere(self, _cfg):
        _lams = per_artifact_lambdas(_cfg, 0.0)
        assert np.allclose(_lams, 0.0)

    def test_linear_in_lambda_z(self, _cfg):
        _a = per_artifact_lambdas(_cfg, 10.0)
        _b = per_artifact_lambdas(_cfg, 20.0)
        # doubling λ_z doubles every λ_i
        assert np.allclose(_b, 2.0 * _a, rtol=1e-9)


class TestPerArtifactRhos:
    """**TestPerArtifactRhos** ρ_i = λ_i / (c_i μ_i); finite for well-formed profiles."""

    def test_all_finite_at_reasonable_lambda(self, _cfg):
        _rhos = per_artifact_rhos(_cfg, 10.0)
        assert np.all(np.isfinite(_rhos))

    def test_monotone_in_lambda_z(self, _cfg):
        _lo = per_artifact_rhos(_cfg, 5.0)
        _hi = per_artifact_rhos(_cfg, 50.0)
        # every component's ρ should be at least as large at higher λ_z
        assert np.all(_hi >= _lo - 1e-12)


class TestLambdaZForRho:
    """**TestLambdaZForRho** closed-form inversion; bottleneck hits target ρ exactly."""

    @pytest.mark.parametrize("_rho_target", [0.05, 0.20, 0.50, 0.80, 0.95])
    def test_bottleneck_hits_target(self, _cfg, _rho_target):
        _lam_z, _bottleneck, _per_unit = lambda_z_for_rho(_cfg, _rho_target)
        # sanity
        assert _lam_z > 0
        assert _per_unit > 0
        # verify: at this λ_z, the identified bottleneck artifact has ρ ≈ target
        _rhos = per_artifact_rhos(_cfg, _lam_z)
        assert _rhos[_bottleneck] == pytest.approx(_rho_target, rel=1e-9)
        # and no other artifact exceeds the target (it IS the bottleneck)
        assert _rhos.max() == pytest.approx(_rho_target, rel=1e-9)

    def test_rejects_invalid_targets(self, _cfg):
        with pytest.raises(ValueError, match="must be in"):
            lambda_z_for_rho(_cfg, 0.0)
        with pytest.raises(ValueError, match="must be in"):
            lambda_z_for_rho(_cfg, 1.0)
        with pytest.raises(ValueError, match="must be in"):
            lambda_z_for_rho(_cfg, 1.5)


class TestBuildGrid:
    """**TestBuildGrid** ρ-grid → λ-grid map for the orchestrator."""

    def test_experiment_md_grid_produces_increasing_lambda(self, _cfg):
        _rho_grid = [0.05, 0.10, 0.20, 0.30, 0.40, 0.45, 0.50, 0.55,
                     0.60, 0.65, 0.70, 0.75, 0.80, 0.85, 0.90, 0.95]
        _grid = build_rho_grid(_cfg, _rho_grid)
        assert len(_grid) == len(_rho_grid)
        _lams = [_l for _, _l, _ in _grid]
        # Jackson linearity: ρ monotone → λ_z monotone
        assert _lams == sorted(_lams)
        # every triple's rho matches its index
        for (_rho_got, _lam, _b), _rho_expected in zip(_grid, _rho_grid):
            assert _rho_got == pytest.approx(_rho_expected)
            assert _lam > 0
            assert isinstance(_b, int)

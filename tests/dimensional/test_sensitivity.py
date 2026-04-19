# -*- coding: utf-8 -*-
"""
Module test_sensitivity.py
==========================

Symbolic sensitivity shape + sign checks on TAS_{1} at variable means.

PyDASA keys sensitivity entries as `SEN_{<coeff_symbol>}`; the short aliases
below hide that prefix so the sign tests stay readable.

    - **TestSensitivityShape**: the wrapper returns a nested `{SEN_{coeff}: {var: float}}` dict with only numeric leaves and contains entries for every derived coefficient.
    - **TestSensitivitySigns**: partial derivatives have the expected sign for the four derived coefficients (θ, σ, η, φ). Signs, not magnitudes; magnitudes depend on evaluation point and drift with config tweaks.
"""
from numbers import Real

_THETA = "SEN_{\\theta_{TAS_{1}}}"
_SIGMA = "SEN_{\\sigma_{TAS_{1}}}"
_ETA = "SEN_{\\eta_{TAS_{1}}}"
_PHI = "SEN_{\\phi_{TAS_{1}}}"


class TestSensitivityShape:
    """Shape contract: dict of dicts, all leaves numeric."""

    def test_returns_dict(self, sensitivity_results):
        assert isinstance(sensitivity_results, dict)

    def test_contains_derived_coefficients(self, sensitivity_results):
        _keys = set(sensitivity_results.keys())
        for _derived in (_THETA, _SIGMA, _ETA, _PHI):
            assert _derived in _keys, f"missing sensitivity for {_derived}"

    def test_all_leaves_are_numeric(self, sensitivity_results):
        for _coeff_sym, _var_map in sensitivity_results.items():
            assert isinstance(_var_map, dict)
            for _var_sym, _val in _var_map.items():
                assert isinstance(_val, Real), (
                    f"{_coeff_sym} / {_var_sym} is {type(_val).__name__}, expected Real"
                )


class TestSensitivitySigns:
    """Expected signs of partial derivatives at the mean operating point."""

    def test_theta_partial_L_positive(self, sensitivity_results):
        # θ = L/K → ∂θ/∂L = 1/K > 0
        assert sensitivity_results[_THETA]["L_{TAS_{1}}"] > 0

    def test_theta_partial_K_negative(self, sensitivity_results):
        # θ = L/K → ∂θ/∂K = -L/K² < 0
        assert sensitivity_results[_THETA]["K_{TAS_{1}}"] < 0

    def test_eta_partial_mu_negative(self, sensitivity_results):
        # η = χK/(μc) → ∂η/∂μ = -χK/(μ²c) < 0
        assert sensitivity_results[_ETA]["\\mu_{TAS_{1}}"] < 0

    def test_eta_partial_K_positive(self, sensitivity_results):
        # η = χK/(μc) → ∂η/∂K = χ/(μc) > 0
        assert sensitivity_results[_ETA]["K_{TAS_{1}}"] > 0

    def test_sigma_partial_L_negative(self, sensitivity_results):
        # σ = λW/L → ∂σ/∂L = -λW/L² < 0
        assert sensitivity_results[_SIGMA]["L_{TAS_{1}}"] < 0

    def test_sigma_partial_W_positive(self, sensitivity_results):
        # σ = λW/L → ∂σ/∂W = λ/L > 0
        assert sensitivity_results[_SIGMA]["W_{TAS_{1}}"] > 0

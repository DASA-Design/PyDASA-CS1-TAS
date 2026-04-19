# -*- coding: utf-8 -*-
"""
Module test_coefficients.py
===========================

Coefficient derivation + numerical agreement with by-hand formulas.

Semantic pin: PyDASA's `Coefficient.calculate_setpoint()` evaluates at each variable's `_mean` (not `_setpoint`). For TAS_{1} most variables have `_mean == _setpoint`, but `c` has `_setpoint=1` and `_mean=2`; η therefore uses c=2 and by-hand checks must mirror that.

    - **TestCoefficientDerivation**: the four expected derived coefficients are created per artifact.
    - **TestCoefficientValues**: numerical setpoints match by-hand closed form to 6 decimals for TAS_{1}.
    - **TestExpressionGuardrails**: malformed expr_patterns raise clearly.
"""
import pytest

from src.dimensional import build_engine, derive_coefficients


# --- TAS_{1} reference values (from dflt.json._mean) ---
_LAMBDA_M = 345.0
_MU_M = 900.0
_CHI_M = 345.0
_C_M = 2.0           # NOTE: _setpoint=1, _mean=2. PyDASA uses _mean.
_K_M = 10.0
_DELTA_M = 1064.0
_L_M = 6.0
_W_M = 0.001801802
_M_ACT_M = _L_M * _DELTA_M    # migration script: _mean == _setpoint == L·delta
_M_BUF_M = _K_M * _DELTA_M    # migration script: _mean == _setpoint == K·delta


class TestCoefficientDerivation:
    """Four named coefficients produced for every artifact."""

    def test_four_derived_for_tas1(self, engine_ready):
        _, _derived = engine_ready
        assert len(_derived) == 4

    def test_derived_symbols(self, engine_ready):
        _, _derived = engine_ready
        _expected = {
            "\\theta_{TAS_{1}}",
            "\\sigma_{TAS_{1}}",
            "\\eta_{TAS_{1}}",
            "\\phi_{TAS_{1}}",
        }
        assert set(_derived.keys()) == _expected

    def test_all_artifacts_get_four_coefficients(
        self, schema, method_cfg, dflt_profile
    ):
        """Every artifact in dflt.json yields 4 derived coefficients."""
        _artifacts = dflt_profile["artifacts"]
        for _artifact_key, _artifact in _artifacts.items():
            _engine = build_engine(_artifact_key, _artifact["vars"], schema)
            _engine.run_analysis()
            _derived = derive_coefficients(
                _engine, method_cfg["coefficients"], artifact_key=_artifact_key
            )
            assert len(_derived) == 4, (
                f"{_artifact_key}: expected 4 derived coefficients, got {len(_derived)}"
            )


class TestCoefficientValues:
    """Numerical setpoints match the by-hand formulas at `_mean` values."""

    def test_theta_equals_L_over_K(self, engine_ready):
        _, _derived = engine_ready
        _theta = _derived["\\theta_{TAS_{1}}"].setpoint
        _expected = _L_M / _K_M
        assert _theta == pytest.approx(_expected, abs=1e-6)

    def test_sigma_equals_little_residual(self, engine_ready):
        _, _derived = engine_ready
        _sigma = _derived["\\sigma_{TAS_{1}}"].setpoint
        _expected = _LAMBDA_M * _W_M / _L_M
        assert _sigma == pytest.approx(_expected, abs=1e-6)

    def test_eta_equals_chi_K_over_mu_c(self, engine_ready):
        """Pins the `_mean`-based evaluation (c=2, not c_setpoint=1)."""
        _, _derived = engine_ready
        _eta = _derived["\\eta_{TAS_{1}}"].setpoint
        _expected = _CHI_M * _K_M / (_MU_M * _C_M)
        assert _eta == pytest.approx(_expected, abs=1e-6)

    def test_phi_equals_memory_ratio(self, engine_ready):
        _, _derived = engine_ready
        _phi = _derived["\\phi_{TAS_{1}}"].setpoint
        _expected = _M_ACT_M / _M_BUF_M
        assert _phi == pytest.approx(_expected, abs=1e-6)

    def test_phi_collapses_to_L_over_K(self, engine_ready):
        """Since M_act = L·δ and M_buf = K·δ, φ should equal θ."""
        _, _derived = engine_ready
        _phi = _derived["\\phi_{TAS_{1}}"].setpoint
        _theta = _derived["\\theta_{TAS_{1}}"].setpoint
        assert _phi == pytest.approx(_theta, abs=1e-9)


class TestExpressionGuardrails:
    """Malformed expr_patterns raise clear errors."""

    def test_out_of_range_pi_index_raises(self, schema, tas1_vars):
        _engine = build_engine("TAS_{1}", tas1_vars, schema)
        _engine.run_analysis()
        _bad_spec = [
            {
                "symbol": "bogus",
                "expr_pattern": "{pi[99]}",
                "name": "Bogus",
                "description": "should fail",
            }
        ]
        with pytest.raises(IndexError, match="pi\\[99\\]"):
            derive_coefficients(_engine, _bad_spec, artifact_key="TAS_{1}")

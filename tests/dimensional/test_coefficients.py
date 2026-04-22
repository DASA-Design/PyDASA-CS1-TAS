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


def _std_mean(engine, sym: str) -> float:
    """*_std_mean()* returns `_std_mean` for a variable on the engine; this is the field PyDASA actually reads during `calculate_setpoint()`."""
    return float(engine.variables[sym]._std_mean)


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
    """Numerical setpoints match the by-hand formulas evaluated at PyDASA's `_std_mean`.

    Values are read from the engine at test time so the tests track whatever
    is in `data/config/profile/dflt.json`; in particular the seeded values
    written by `src.utils.seed_dim_from_analytic` after the analytic solver
    is run.
    """

    def test_theta_equals_L_over_K(self, engine_ready):
        _eng, _derived = engine_ready
        _theta = _derived["\\theta_{TAS_{1}}"].setpoint
        _expected = _std_mean(_eng, "L_{TAS_{1}}") / _std_mean(_eng, "K_{TAS_{1}}")
        assert _theta == pytest.approx(_expected, rel=1e-6)

    def test_sigma_equals_little_residual(self, engine_ready):
        _eng, _derived = engine_ready
        _sigma = _derived["\\sigma_{TAS_{1}}"].setpoint
        _lam = _std_mean(_eng, "\\lambda_{TAS_{1}}")
        _w = _std_mean(_eng, "W_{TAS_{1}}")
        _L = _std_mean(_eng, "L_{TAS_{1}}")
        _expected = _lam * _w / _L
        assert _sigma == pytest.approx(_expected, rel=1e-6)

    def test_sigma_close_to_unity_after_seed(self, engine_ready):
        """Sanity check: Little's law -> lambda*W = L -> sigma ~ 1 at the seeded operating point."""
        _, _derived = engine_ready
        _sigma = _derived["\\sigma_{TAS_{1}}"].setpoint
        assert _sigma == pytest.approx(1.0, abs=0.01)

    def test_eta_equals_chi_K_over_mu_c(self, engine_ready):
        _eng, _derived = engine_ready
        _eta = _derived["\\eta_{TAS_{1}}"].setpoint
        _chi = _std_mean(_eng, "\\chi_{TAS_{1}}")
        _K = _std_mean(_eng, "K_{TAS_{1}}")
        _mu = _std_mean(_eng, "\\mu_{TAS_{1}}")
        _c = _std_mean(_eng, "c_{TAS_{1}}")
        _expected = _chi * _K / (_mu * _c)
        assert _eta == pytest.approx(_expected, rel=1e-6)

    def test_phi_equals_memory_ratio(self, engine_ready):
        _eng, _derived = engine_ready
        _phi = _derived["\\phi_{TAS_{1}}"].setpoint
        _m_act = _std_mean(_eng, "M_{act_{TAS_{1}}}")
        _m_buf = _std_mean(_eng, "M_{buf_{TAS_{1}}}")
        _expected = _m_act / _m_buf
        assert _phi == pytest.approx(_expected, rel=1e-6)

    def test_phi_collapses_to_L_over_K(self, engine_ready):
        """Since M_act = L·delta and M_buf = K·delta, phi should equal theta."""
        _, _derived = engine_ready
        _phi = _derived["\\phi_{TAS_{1}}"].setpoint
        _theta = _derived["\\theta_{TAS_{1}}"].setpoint
        assert _phi == pytest.approx(_theta, rel=1e-9)


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

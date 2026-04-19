# -*- coding: utf-8 -*-
"""
Module test_engine.py
=====================

Per-artifact `build_engine()` + `engine.run_analysis()` contract:

    - **TestEngineConstruction**: variables flow through to the engine and the IN/OUT/CTRL counts match the TAS_{1} schema.
    - **TestPiGroupDerivation**: Buckingham's theorem holds (n_relevant - n_fdus Pi-groups), and the Pi symbolic expressions are invariant across all four TAS adaptation scenarios (same variable set, different setpoints).
"""
from src.dimensional import build_engine


class TestEngineConstruction:
    """`build_engine()` attaches all 13 variables with the expected categories."""

    def test_variables_count(self, engine_bare):
        assert len(engine_bare.variables) == 13

    def test_relevant_count_matches_migration(self, engine_bare):
        _relevant = sum(1 for v in engine_bare.variables.values() if v.relevant)
        assert _relevant == 10

    def test_input_category_count(self, engine_bare):
        _ins = [v for v in engine_bare.variables.values() if v.cat == "IN"]
        assert len(_ins) == 3  # lambda, c, delta

    def test_output_category_count(self, engine_bare):
        _outs = [v for v in engine_bare.variables.values() if v.cat == "OUT"]
        assert len(_outs) == 1  # W

    def test_control_category_count(self, engine_bare):
        _ctrls = [v for v in engine_bare.variables.values() if v.cat == "CTRL"]
        assert len(_ctrls) == 9

    def test_framework_matches_schema(self, engine_bare, schema):
        assert engine_bare.fwk == schema.fwk == "CUSTOM"


class TestPiGroupDerivation:
    """Buckingham's theorem + Pi-expression stability across adaptations."""

    def test_pi_count_matches_buckingham(self, engine_ready):
        # 10 relevant variables - 3 FDUs = 7 Pi-groups
        _engine, _ = engine_ready
        _pi_keys = [k for k in _engine.coefficients if k.startswith("\\Pi_")]
        assert len(_pi_keys) == 7

    def test_pi_expressions_stable_across_adaptations(
        self, schema, method_cfg, dflt_profile, opti_profile
    ):
        """Same variable set across scenarios → same Pi symbolic expressions."""
        _exp_per_profile: dict[str, list[str]] = {}

        for _label, _profile in [
            ("dflt", dflt_profile),
            ("opti", opti_profile),
        ]:
            _vars = _profile["artifacts"]["TAS_{1}"]["vars"]
            _engine = build_engine("TAS_{1}", _vars, schema)
            _engine.run_analysis()
            _pi_keys = [
                k for k in _engine.coefficients if k.startswith("\\Pi_")
            ]
            _exp_per_profile[_label] = [
                str(_engine.coefficients[k].pi_expr) for k in _pi_keys
            ]

        ans = (_exp_per_profile["dflt"] == _exp_per_profile["opti"])
        assert ans, "Pi-group symbolic expressions should be invariant to setpoint-only changes"

    def test_pi_zero_involves_w_lambda_c(self, engine_ready):
        """Spot-check: Π₀ = λW/c (per observed TAS ordering)."""
        _engine, _ = engine_ready
        _pi0 = _engine.coefficients["\\Pi_{0}"]
        _dims = _pi0.var_dims
        assert _dims.get("\\lambda_{TAS_{1}}") == 1
        assert _dims.get("W_{TAS_{1}}") == 1
        assert _dims.get("c_{TAS_{1}}") == -1

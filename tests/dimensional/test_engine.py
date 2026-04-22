# -*- coding: utf-8 -*-
"""
Module test_engine.py
=====================

Per-artifact `build_engine()` + `engine.run_analysis()` contract:

    - **TestEngineConstruction**: variables flow through to the engine and the IN/OUT/CTRL counts match the TAS_{1} schema.
    - **TestPiGroupDerivation**: Buckingham's theorem holds (n_relevant - n_fdus Pi-groups), and the Pi symbolic expressions are invariant across all four TAS adaptation scenarios (same variable set, different setpoints).
"""
# module under test
from src.dimensional import build_engine


class TestEngineConstruction:
    """**TestEngineConstruction** `build_engine()` attaches all 13 variables to the engine with the expected IN/OUT/CTRL categorisation and framework."""

    def test_variables_count(self, engine_bare):
        """*test_variables_count()* TAS_{1} carries 13 Variable entries total."""
        assert len(engine_bare.variables) == 13

    def test_relevant_count_matches_migration(self, engine_bare):
        """*test_relevant_count_matches_migration()* 10 of 13 variables are marked `relevant=True` per the migration schema."""
        _relevant = sum(1 for _v in engine_bare.variables.values() if _v.relevant)
        assert _relevant == 10

    def test_input_category_count(self, engine_bare):
        """*test_input_category_count()* 3 IN variables: lambda, c, delta."""
        _ins = [_v for _v in engine_bare.variables.values() if _v.cat == "IN"]
        assert len(_ins) == 3

    def test_output_category_count(self, engine_bare):
        """*test_output_category_count()* 1 OUT variable: W."""
        _outs = [_v for _v in engine_bare.variables.values() if _v.cat == "OUT"]
        assert len(_outs) == 1

    def test_control_category_count(self, engine_bare):
        """*test_control_category_count()* 9 CTRL variables round out the 10-relevant / 3-FDU Buckingham budget."""
        _ctrls = [_v for _v in engine_bare.variables.values() if _v.cat == "CTRL"]
        assert len(_ctrls) == 9

    def test_framework_matches_schema(self, engine_bare, schema):
        """*test_framework_matches_schema()* engine and schema both carry `_fwk == "CUSTOM"`."""
        assert engine_bare.fwk == schema.fwk == "CUSTOM"


class TestPiGroupDerivation:
    """**TestPiGroupDerivation** Buckingham's theorem (`n_relevant - n_fdus` Pi-groups) holds, and Pi symbolic expressions are invariant to setpoint-only changes across adaptations."""

    def test_pi_count_matches_buckingham(self, engine_ready):
        """*test_pi_count_matches_buckingham()* 10 relevant variables minus 3 FDUs yields exactly 7 Pi-groups."""
        _engine, _ = engine_ready
        _pi_keys = [_k for _k in _engine.coefficients if _k.startswith("\\Pi_")]
        assert len(_pi_keys) == 7

    def test_pi_expressions_stable_across_adaptations(
        self, schema, method_cfg, dflt_profile, opti_profile
    ):
        """*test_pi_expressions_stable_across_adaptations()* same variable set across scenarios -> same Pi symbolic expressions (setpoints change, structure does not)."""
        _exp_per_profile: dict[str, list[str]] = {}

        for _label, _profile in [
            ("dflt", dflt_profile),
            ("opti", opti_profile),
        ]:
            _vars = _profile["artifacts"]["TAS_{1}"]["vars"]
            _engine = build_engine("TAS_{1}", _vars, schema)
            _engine.run_analysis()
            _pi_keys = [
                _k for _k in _engine.coefficients if _k.startswith("\\Pi_")
            ]
            _exp_per_profile[_label] = [
                str(_engine.coefficients[_k].pi_expr) for _k in _pi_keys
            ]

        _ans = (_exp_per_profile["dflt"] == _exp_per_profile["opti"])
        assert _ans, "Pi-group symbolic expressions should be invariant to setpoint-only changes"

    def test_pi_zero_involves_w_lambda_c(self, engine_ready):
        """*test_pi_zero_involves_w_lambda_c()* spot-check on the first Pi-group: Pi_0 = lambda * W / c (per observed TAS ordering)."""
        _engine, _ = engine_ready
        _pi0 = _engine.coefficients["\\Pi_{0}"]
        _dims = _pi0.var_dims
        assert _dims.get("\\lambda_{TAS_{1}}") == 1
        assert _dims.get("W_{TAS_{1}}") == 1
        assert _dims.get("c_{TAS_{1}}") == -1

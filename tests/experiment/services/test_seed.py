# -*- coding: utf-8 -*-
"""
Module test_seed.py
===================

Pins the "single config seed controls every stochastic draw" invariant.

    - **TestDeriveSeed** `derive_seed(root, name)` is stable, deterministic, and discriminative.
    - **TestServiceStateRNG** two ServiceStates built from the same spec produce identical draw sequences; different specs diverge.
    - **TestLauncherThreadsSeed** the launcher folds `method_cfg["seed"]` into every service spec.
"""
# native python modules

# testing framework
import pytest

# modules under test
from src.experiment.services import (SvcCtx,
                                     SvcSpec,
                                     derive_seed)

# downstream tests below use the pre-refactor name `ServiceState`; alias it
# to the new lightweight `SvcCtx` so assertions keep working.
ServiceState = SvcCtx


class TestDeriveSeed:
    """**TestDeriveSeed** deterministic, stable, discriminative per-service seed derivation."""

    def test_same_root_same_name_same_seed(self):
        assert derive_seed(42, "TAS_{1}") == derive_seed(42, "TAS_{1}")

    def test_different_names_diverge(self):
        assert derive_seed(42, "TAS_{1}") != derive_seed(42, "TAS_{2}")

    def test_different_roots_diverge(self):
        assert derive_seed(42, "TAS_{1}") != derive_seed(7, "TAS_{1}")

    def test_nonnegative_64bit(self):
        _s = derive_seed(42, "MAS_{3}")
        assert 0 <= _s < (1 << 64)

    def test_stable_across_calls(self):
        """No PYTHONHASHSEED-style randomisation leakage."""
        _results = [derive_seed(42, "TAS_{1}") for _ in range(5)]
        assert len(set(_results)) == 1


class TestServiceStateRNG:
    """**TestServiceStateRNG** per-service RNG is seeded from `spec.seed`; same spec -> identical draw sequence."""

    def _spec(self, name: str, seed: int) -> SvcSpec:
        return SvcSpec(name=name, role="atomic", port=9000,
                           mu=100.0, epsilon=0.1, c=1, K=10,
                           seed=seed)

    def test_same_seed_identical_draws(self):
        _s1 = ServiceState(spec=self._spec("MAS_{1}", 12345))
        _s2 = ServiceState(spec=self._spec("MAS_{1}", 12345))
        _draws_1 = [_s1.draw_svc_time() for _ in range(20)]
        _draws_2 = [_s2.draw_svc_time() for _ in range(20)]
        assert _draws_1 == _draws_2

    def test_different_seed_diverges(self):
        _s1 = ServiceState(spec=self._spec("MAS_{1}", 12345))
        _s2 = ServiceState(spec=self._spec("MAS_{1}", 99999))
        _draws_1 = [_s1.draw_svc_time() for _ in range(20)]
        _draws_2 = [_s2.draw_svc_time() for _ in range(20)]
        assert _draws_1 != _draws_2

    def test_fail_draw_deterministic_under_seed(self):
        _s1 = ServiceState(spec=self._spec("MAS_{1}", 7))
        _s2 = ServiceState(spec=self._spec("MAS_{1}", 7))
        _d1 = [_s1.draw_eps() for _ in range(50)]
        _d2 = [_s2.draw_eps() for _ in range(50)]
        assert _d1 == _d2

    def test_seed_zero_falls_back_to_non_seeded(self):
        """seed=0 means "no controlled seed"; draws are not required to match across states."""
        _s1 = ServiceState(spec=self._spec("MAS_{1}", 0))
        _s2 = ServiceState(spec=self._spec("MAS_{1}", 0))
        # both functional (no exceptions); draws may or may not match.
        assert isinstance(_s1.draw_svc_time(), float)
        assert isinstance(_s2.draw_svc_time(), float)


class TestLauncherThreadsSeed:
    """**TestLauncherThreadsSeed** method_cfg::seed flows into every service spec via derive_seed."""

    @pytest.mark.asyncio
    async def test_every_service_has_derived_seed(self):
        from src.experiment.launcher import ExperimentLauncher
        from src.io import load_method_cfg, load_profile

        _cfg = load_profile(adaptation="baseline")
        _mcfg = load_method_cfg("experiment")
        _root = int(_mcfg["seed"])

        async with ExperimentLauncher(cfg=_cfg, method_cfg=_mcfg,
                                      adaptation="baseline") as _lnc:
            assert _lnc.specs, "launcher built no specs"
            for _name, _spec in _lnc.specs.items():
                _expected = derive_seed(_root, _name)
                assert _spec.seed == _expected, (
                    f"{_name} seed={_spec.seed} != derive_seed({_root}, {_name})={_expected}")
            # every service has a distinct seed
            _seeds = [_s.seed for _s in _lnc.specs.values()]
            assert len(set(_seeds)) == len(_seeds)

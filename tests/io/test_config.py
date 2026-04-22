# -*- coding: utf-8 -*-
"""
Module test_config.py
=====================

Sanity checks for the profile + scenario loader in `src.io.config`.

Each class groups tests by the contract under verification:

    - **TestResolution**: the four adaptation aliases (`baseline`, `s1`, `s2`, `aggregate`) resolve to the correct (profile, scenario) pair and the expected artifacts land at the three swap slots.
    - **TestSetpointFallback**: the `_setpoint` fallback path kicks in when the caller omits `adaptation` or `scenario`.
    - **TestArtifactSpec**: the `ArtifactSpec` properties (`mu`, the setpoint lookup, `lambda_z`) read the PACS Variable dict correctly, including the opti-profile service swaps.
    - **TestErrors**: unknown adaptations and unknown scenarios raise clear errors before the solver is touched.

# TODO: extend with a regression case for a profile that omits `_labels[scenario]` (optional field) once we add new scenarios.
"""
# native python modules
# (none)

# testing framework
import pytest

# module under test
from src.io import load_profile


class TestResolution:
    """**TestResolution** verifies the four adaptation aliases resolve to the correct (profile, scenario) pair and surface the right artifacts at the three swap slots (5, 8, 10)."""

    def test_baseline_hits_dflt(self):
        """*test_baseline_hits_dflt()* `baseline` -> (`dflt`, `baseline`) with all 13 nodes present."""
        _cfg = load_profile(adaptation="baseline")
        assert _cfg.profile == "dflt"
        assert _cfg.scenario == "baseline"
        assert _cfg.n_nodes == 13

    def test_s1_hits_opti_with_dflt_swap_services(self):
        """*test_s1_hits_opti_with_dflt_swap_services()* `s1` uses the opti routing with the dflt services at the swap slots."""
        _cfg = load_profile(adaptation="s1")
        assert _cfg.profile == "opti"
        assert _cfg.scenario == "s1"

        # swap slots must show the dflt-variant keys under s1
        _keys = _cfg.list_node_keys()
        assert _keys[5] == "MAS_{3}"
        assert _keys[8] == "AS_{3}"
        assert _keys[10] == "DS_{3}"

    def test_s2_hits_opti_with_opti_swap_services(self):
        """*test_s2_hits_opti_with_opti_swap_services()* `s2` keeps the dflt routing but swaps in the opti services at the three slots."""
        _cfg = load_profile(adaptation="s2")
        assert _cfg.profile == "opti"

        # swap slots must show the opti-variant keys under s2
        _keys = _cfg.list_node_keys()
        assert _keys[5] == "MAS_{4}"
        assert _keys[8] == "AS_{4}"
        assert _keys[10] == "DS_{1}"

    def test_aggregate(self):
        """*test_aggregate()* `aggregate` combines opti routing + opti services at the swap slots."""
        _cfg = load_profile(adaptation="aggregate")
        assert _cfg.scenario == "aggregate"

        # opti variants at the swap slots (spot check)
        _keys = _cfg.list_node_keys()
        assert _keys[5] == "MAS_{4}"
        assert _keys[10] == "DS_{1}"


class TestSetpointFallback:
    """**TestSetpointFallback** verifies that the loader falls back to the profile's declared `_setpoint` when the caller does not pin a scenario explicitly."""

    def test_no_args_hits_dflt_baseline(self):
        """*test_no_args_hits_dflt_baseline()* with no args, the hard default is (`dflt`, `baseline`)."""
        _cfg = load_profile()
        assert _cfg.profile == "dflt"
        assert _cfg.scenario == "baseline"

    def test_profile_only_uses_setpoint(self):
        """*test_profile_only_uses_setpoint()* `--profile opti` alone falls through to `opti.json::environments._setpoint` which is `aggregate`."""
        _cfg = load_profile(profile="opti")
        assert _cfg.profile == "opti"
        assert _cfg.scenario == "aggregate"


class TestArtifactSpec:
    """**TestArtifactSpec** verifies that the per-artifact spec resolves its PyDASA Variable-dict setpoints correctly across both profiles (in particular, the dflt / opti service swap at slot 5)."""

    def test_mu_readable_at_dflt_mas_3(self):
        """*test_mu_readable_at_dflt_mas_3()* MAS_3 in the dflt profile has mu = 150 req/s (published baseline value)."""
        _cfg = load_profile(adaptation="baseline")
        _mas_3 = next(_a for _a in _cfg.artifacts if _a.key == "MAS_{3}")
        assert _mas_3.mu == 150.0

    def test_mu_readable_at_opti_mas_4(self):
        """*test_mu_readable_at_opti_mas_4()* MAS_4 in the opti profile (the upgrade slot) has mu = 880 req/s."""
        _cfg = load_profile(adaptation="aggregate")
        _mas_4 = next(_a for _a in _cfg.artifacts if _a.key == "MAS_{4}")
        assert _mas_4.mu == 880.0

    def test_lambda_z_only_at_entry(self):
        """*test_lambda_z_only_at_entry()* only TAS_1 carries external arrivals (345 req/s); every other artifact has lambda_z = 0."""
        _cfg = load_profile(adaptation="baseline")

        # collect artifacts that actually receive external traffic
        _entries = [_a for _a in _cfg.artifacts if _a.lambda_z > 0]
        assert len(_entries) == 1
        assert _entries[0].key == "TAS_{1}"
        assert _entries[0].lambda_z == 345.0


class TestErrors:
    """**TestErrors** verifies that bad inputs fail loud at load time, before any solver is touched."""

    def test_unknown_adaptation(self):
        """*test_unknown_adaptation()* an adaptation string that is not in `_ADAPTATION_TO_SOURCE` must raise `ValueError`."""
        with pytest.raises(ValueError, match="unknown adaptation"):
            load_profile(adaptation="xyz")

    def test_unknown_scenario_in_profile(self):
        """*test_unknown_scenario_in_profile()* a scenario name that is not declared in the profile's `_scenarios` list must raise."""
        with pytest.raises(ValueError, match="not in"):
            load_profile(profile="dflt", scenario="bogus")

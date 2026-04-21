# -*- coding: utf-8 -*-
"""
Module test_experiment.py
=========================

End-to-end tests for the experiment-method orchestrator in `src.methods.experiment`.
Uses `_QUICK_CFG` (one low rate, `min_samples_per_kind=32` at CLT floor) so the
suite stays under ~20 s.

    - **TestExperimentEndToEnd** baseline + s1 adaptations solve end-to-end, produce 13 nodes, and expose the R1 / R2 / R3 verdict schema.
    - **TestResultEnvelope** the written envelope is well-formed and carries the ramp `probes` list.

*IMPORTANT:* tests use an in-process ASGI mesh (no real port binding), so the run
time reflects compute + event-loop overhead, not TCP round trips. That is a
deliberate unit-test trade-off; the notebook can opt into real ports via
`uvicorn.Server` if / when needed.
"""
# native python modules
import json

# testing framework
import pytest

# modules under test
from src.methods.experiment import run as run_experiment


# abbreviated config for tests: one low rate, cascade disabled by a loose
# threshold so a noisy probe does not trip it. Must still respect the
# client-side CLT floor (min_samples_per_kind >= 32).
_QUICK_CFG = {
    "base_port": 18000,
    "host": "127.0.0.1",
    "healthz_timeout_s": 10,
    "duration_s": 4,
    "warmup_s": 0,
    "seed": 42,
    "replications": 1,
    "ramp": {
        "min_samples_per_kind": 32,
        "max_probe_window_s": 20.0,
        "rates": [2.0],
        "cascade": {"mode": "rolling", "threshold": 0.5, "window": 50},
    },
    "request_size_bytes": {
        "analyse_request": 256,
        "alarm_request": 128,
        "drug_request": 192,
        "response_default": 128,
    },
    "service_registry": {
        "TAS_{1}": {"port_offset": 0, "role": "composite_router"},
        "TAS_{2}": {"port_offset": 0, "role": "composite"},
        "TAS_{3}": {"port_offset": 0, "role": "composite"},
        "TAS_{4}": {"port_offset": 0, "role": "composite"},
        "TAS_{5}": {"port_offset": 0, "role": "composite"},
        "TAS_{6}": {"port_offset": 0, "role": "composite"},
        "MAS_{1}": {"port_offset": 6, "role": "atomic"},
        "MAS_{2}": {"port_offset": 7, "role": "atomic"},
        "MAS_{3}": {"port_offset": 8, "role": "atomic"},
        "AS_{1}": {"port_offset": 9, "role": "atomic"},
        "AS_{2}": {"port_offset": 10, "role": "atomic"},
        "AS_{3}": {"port_offset": 11, "role": "atomic"},
        "DS_{3}": {"port_offset": 12, "role": "atomic"},
        "MAS_{4}": {"port_offset": 13, "role": "atomic"},
        "AS_{4}": {"port_offset": 14, "role": "atomic"},
        "DS_{1}": {"port_offset": 15, "role": "atomic"},
    },
}


@pytest.fixture(scope="module")
def _result_baseline():
    """*_result_baseline()* module-scoped baseline run; cached so every test reuses the same experiment."""
    return run_experiment(adp="baseline", wrt=False, method_cfg=_QUICK_CFG)


@pytest.fixture(scope="module")
def _result_s1():
    """*_result_s1()* module-scoped s1 (Retry) run."""
    return run_experiment(adp="s1", wrt=False, method_cfg=_QUICK_CFG)


class TestExperimentEndToEnd:
    """**TestExperimentEndToEnd** the orchestrator returns the same envelope shape as analytic / stochastic."""

    @pytest.fixture(params=["baseline", "s1"])
    def _result(self, request, _result_baseline, _result_s1):
        return _result_baseline if request.param == "baseline" else _result_s1

    def test_runs_and_produces_thirteen_nodes(self, _result):
        _nds = _result["nodes"]
        assert len(_nds) == 13

    def test_requirements_shape(self, _result):
        _req = _result["requirements"]
        assert set(_req.keys()) == {"R1", "R2", "R3"}
        for _k in ("R1", "R2", "R3"):
            assert "pass" in _req[_k]
            assert "value" in _req[_k]
            assert "metric" in _req[_k]

    def test_probes_present(self, _result):
        _probes = _result["probes"]
        assert len(_probes) >= 1
        for _p in _probes:
            assert "rate" in _p
            assert "total" in _p
            assert "infra_fail_rate" in _p
            assert "business_fail_rate" in _p
            assert "samples_per_kind" in _p
            assert "stats_per_kind" in _p
            assert "stopped_reason" in _p

    def test_buffer_reject_rate_column_present(self, _result):
        """Business failure (epsilon) and infrastructure failure (buffer_reject_rate) are split."""
        _nds = _result["nodes"]
        assert "epsilon" in _nds.columns
        assert "buffer_reject_rate" in _nds.columns

    def test_entry_service_received_traffic(self, _result):
        """*TAS_{1}* must have non-zero measured lambda (it's the entry point)."""
        _nds = _result["nodes"]
        _tas1 = _nds[_nds["key"] == "TAS_{1}"]
        assert len(_tas1) == 1
        assert float(_tas1.iloc[0]["lambda"]) > 0.0


class TestResultEnvelope:
    """**TestResultEnvelope** the on-disk envelope is well-formed when `wrt=True`."""

    def test_wrt_true_writes_json(self, tmp_path, monkeypatch):
        from src.methods import experiment as _mod
        monkeypatch.setattr(_mod, "_ROOT", tmp_path)
        monkeypatch.setattr(_mod, "_RESULTS_DIR", tmp_path / "experiment")

        _result = run_experiment(adp="baseline", wrt=True,
                                 method_cfg=_QUICK_CFG)
        assert "profile" in _result["paths"]

        _path = tmp_path / "experiment" / "baseline" / "dflt.json"
        assert _path.exists()
        _doc = json.loads(_path.read_text(encoding="utf-8"))
        assert _doc["method"] == "experiment"
        assert _doc["scenario"] == "baseline"
        assert len(_doc["nodes"]) == 13
        assert "probes" in _doc
        # per-probe `records` are stripped before persistence (not JSON-safe)
        for _p in _doc["probes"]:
            assert "records" not in _p

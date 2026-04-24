# -*- coding: utf-8 -*-
"""
Module test_experiment.py
=========================

End-to-end tests for the experiment-method orchestrator in `src.methods.experiment`. Uses `_QUICK_CFG` (one low rate, `min_samples_per_kind=32` at the CLT floor) so the suite stays under ~20 s.

Each class groups tests by the contract under verification:

    - **TestExperimentEndToEnd**: `baseline` and `s1` adaptations solve end-to-end, produce 13 nodes, and expose the R1 / R2 / R3 verdict schema plus the ramp `probes` stats.
    - **TestResultEnvelope**: the written envelope is well-formed and carries the ramp `probes` list (with per-probe `records` stripped before persistence).

*IMPORTANT:* tests use an in-process ASGI mesh (no real port binding), so the run time reflects compute + event-loop overhead, not TCP round trips. This is a deliberate unit-test trade-off; the notebook can opt into real ports via `uvicorn.Server` if needed.
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
        "TAS_{1}": {"port_offset": 0, "role": "composite_client"},
        "TAS_{2}": {"port_offset": 0, "role": "composite_medical"},
        "TAS_{3}": {"port_offset": 0, "role": "composite_alarm"},
        "TAS_{4}": {"port_offset": 0, "role": "composite_drug"},
        "TAS_{5}": {"port_offset": 0, "role": "composite_client"},
        "TAS_{6}": {"port_offset": 0, "role": "composite_client"},
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
    return run_experiment(adp="baseline", wrt=False, method_cfg=_QUICK_CFG,
                           skip_calibration=True, verbose=False)


@pytest.fixture(scope="module")
def _result_s1():
    """*_result_s1()* module-scoped s1 (Retry) run."""
    return run_experiment(adp="s1", wrt=False, method_cfg=_QUICK_CFG,
                          skip_calibration=True, verbose=False)


class TestExperimentEndToEnd:
    """**TestExperimentEndToEnd** the orchestrator returns the same envelope shape as analytic / stochastic."""

    @pytest.fixture(params=["baseline", "s1"])
    def _result(self, request, _result_baseline, _result_s1):
        """*_result()* parametrised indirection so each test body stays fixture-free; returns the right per-adaptation result."""
        return _result_baseline if request.param == "baseline" else _result_s1

    def test_runs_and_produces_thirteen_nodes(self, _result):
        """*test_runs_and_produces_thirteen_nodes()* every adaptation returns a 13-node frame."""
        _nds = _result["nodes"]
        assert len(_nds) == 13

    def test_requirements_shape(self, _result):
        """*test_requirements_shape()* verdict dict exposes R1, R2, R3 with the writer-critical fields."""
        _req = _result["requirements"]
        assert set(_req.keys()) == {"R1", "R2", "R3"}
        for _k in ("R1", "R2", "R3"):
            assert "pass" in _req[_k]
            assert "value" in _req[_k]
            assert "metric" in _req[_k]

    def test_probes_present(self, _result):
        """*test_probes_present()* ramp output carries at least one probe with the full stats schema."""
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
        """*test_buffer_reject_rate_column_present()* business failure (epsilon) and infrastructure failure (buffer_reject_rate) are split into distinct columns."""
        _nds = _result["nodes"]
        assert "epsilon" in _nds.columns
        assert "buffer_reject_rate" in _nds.columns

    def test_entry_service_received_traffic(self, _result):
        """*test_entry_service_received_traffic()* TAS_{1} must carry non-zero measured lambda since it is the entry point."""
        _nds = _result["nodes"]
        _tas1 = _nds[_nds["key"] == "TAS_{1}"]
        assert len(_tas1) == 1
        assert float(_tas1.iloc[0]["lambda"]) > 0.0


class TestRhoGridPath:
    """**TestRhoGridPath** (FR-3.5) `ramp.rho_grid` is inverted to rates via the analytic Jackson solver and every probe carries the rho-target metadata."""

    @pytest.fixture(scope="class")
    def _rho_result(self):
        """*_rho_result()* module-scoped baseline run with a one-point rho-grid instead of `rates`."""
        _cfg = dict(_QUICK_CFG)
        _cfg["ramp"] = {
            "min_samples_per_kind": 32,
            "max_probe_window_s": 20.0,
            "rho_grid": [0.20],
            "cascade": {"mode": "rolling", "threshold": 0.5, "window": 50},
        }
        return run_experiment(adp="baseline", wrt=False, method_cfg=_cfg,
                              skip_calibration=True, verbose=False)

    def test_probe_has_rho_target_metadata(self, _rho_result):
        """*test_probe_has_rho_target_metadata()* every probe carries `rho_target`, `lambda_z_inverted`, and `bottleneck_artifact_idx` when the rho-grid path is used."""
        _probes = _rho_result["probes"]
        assert len(_probes) == 1
        _p = _probes[0]
        assert _p["rho_target"] == pytest.approx(0.20)
        assert _p["lambda_z_inverted"] > 0.0
        assert isinstance(_p["bottleneck_artifact_idx"], int)

    def test_rates_match_inverted_lambda(self, _rho_result):
        """*test_rates_match_inverted_lambda()* the probe's raw `rate` equals the inverted `lambda_z_inverted` (end-to-end round-trip)."""
        _p = _rho_result["probes"][0]
        assert _p["rate"] == pytest.approx(_p["lambda_z_inverted"])


class TestRampValidation:
    """**TestRampValidation** (FR-3.5) `validate_ramp` rejects ambiguous or empty `rates`/`rho_grid` combinations."""

    def test_both_rates_and_rho_grid_raises(self):
        """*test_both_rates_and_rho_grid_raises()* supplying both is ambiguous and raises."""
        from src.experiment.client import validate_ramp
        with pytest.raises(ValueError, match="either 'rates' or 'rho_grid'"):
            validate_ramp({"min_samples_per_kind": 32,
                           "rates": [1.0],
                           "rho_grid": [0.2]})

    def test_neither_raises(self):
        """*test_neither_raises()* missing both knobs raises."""
        from src.experiment.client import validate_ramp
        with pytest.raises(ValueError, match="'rates' .* or 'rho_grid'"):
            validate_ramp({"min_samples_per_kind": 32})

    def test_rho_grid_out_of_range_raises(self):
        """*test_rho_grid_out_of_range_raises()* values outside (0, 1) are rejected."""
        from src.experiment.client import validate_ramp
        with pytest.raises(ValueError, match="in \\(0, 1\\)"):
            validate_ramp({"min_samples_per_kind": 32,
                           "rho_grid": [1.2]})

    def test_rho_grid_non_monotonic_raises(self):
        """*test_rho_grid_non_monotonic_raises()* unsorted grids are rejected."""
        from src.experiment.client import validate_ramp
        with pytest.raises(ValueError, match="monotonically increasing"):
            validate_ramp({"min_samples_per_kind": 32,
                           "rho_grid": [0.5, 0.2]})


class TestSeededReproducibility:
    """**TestSeededReproducibility** (FR-3.7) two runs at the same config seed produce identical request_id sequences."""

    def test_request_ids_match_across_runs(self):
        """*test_request_ids_match_across_runs()* `request_id` is derived from the client's seeded RNG, not an unseeded `uuid.uuid4()`."""
        _res_a = run_experiment(adp="baseline", wrt=False,
                                method_cfg=_QUICK_CFG,
                                skip_calibration=True, verbose=False)
        _res_b = run_experiment(adp="baseline", wrt=False,
                                method_cfg=_QUICK_CFG,
                                skip_calibration=True, verbose=False)
        _ids_a = [_r.request_id
                  for _p in _res_a["probes"]
                  for _r in _p["records"]]
        _ids_b = [_r.request_id
                  for _p in _res_b["probes"]
                  for _r in _p["records"]]
        assert _ids_a == _ids_b
        assert len(_ids_a) > 0


class TestReplicates:
    """**TestReplicates** (FR-3.8) `replications > 1` produces per-replicate entries with distinct seeds, distinct request_id sequences, and (when `wrt=True`) per-replicate `rep_<k>/` log dirs."""

    @pytest.fixture(scope="class")
    def _result_r2(self):
        """*_result_r2()* module-scoped baseline run with `replications=2`."""
        _cfg = dict(_QUICK_CFG)
        _cfg["replications"] = 2
        return run_experiment(adp="baseline", wrt=False, method_cfg=_cfg,
                              skip_calibration=True, verbose=False)

    def test_replicates_list_has_two_entries(self, _result_r2):
        """*test_replicates_list_has_two_entries()* envelope exposes exactly two replicate payloads."""
        _reps = _result_r2["replicates"]
        assert len(_reps) == 2
        assert [_r["replicate_id"] for _r in _reps] == [0, 1]

    def test_replicates_have_distinct_seeds(self, _result_r2):
        """*test_replicates_have_distinct_seeds()* per-replicate seeds differ (derived via `derive_seed(root, "rep_<k>")`)."""
        _reps = _result_r2["replicates"]
        assert _reps[0]["seed"] != _reps[1]["seed"]

    def test_replicates_have_distinct_request_ids(self, _result_r2):
        """*test_replicates_have_distinct_request_ids()* distinct seeds -> distinct request_id sequences (independence)."""
        _reps = _result_r2["replicates"]
        _ids_0 = [_r.request_id
                  for _p in _reps[0]["probes"]
                  for _r in _p["records"]]
        _ids_1 = [_r.request_id
                  for _p in _reps[1]["probes"]
                  for _r in _p["records"]]
        assert _ids_0 != _ids_1
        assert len(_ids_0) > 0 and len(_ids_1) > 0

    def test_top_level_shape_matches_replicate_zero(self, _result_r2):
        """*test_top_level_shape_matches_replicate_zero()* back-compat: flat `nodes`/`probes` fields mirror replicate 0."""
        _rep0 = _result_r2["replicates"][0]
        assert _result_r2["probes"] is _rep0["probes"]
        assert _result_r2["saturation_rate"] == _rep0["saturation_rate"]


class TestResultEnvelope:
    """**TestResultEnvelope** the on-disk envelope is well-formed when `wrt=True`."""

    def test_wrt_true_writes_json(self, tmp_path, monkeypatch):
        """*test_wrt_true_writes_json()* writing to a tmp_path results dir produces a well-formed JSON file with probes but no inline records."""
        from src.methods import experiment as _mod
        monkeypatch.setattr(_mod, "_ROOT", tmp_path)
        monkeypatch.setattr(_mod, "_RESULTS_DIR", tmp_path / "experiment")

        _result = run_experiment(adp="baseline", wrt=True,
                                 method_cfg=_QUICK_CFG,
                                 skip_calibration=True, verbose=False)
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


class TestCalibrationGate:
    """**TestCalibrationGate** `run()` refuses to start without a calibration for the current host unless `skip_calibration=True` is explicitly set, and the resolved calibration is surfaced on the result envelope."""

    def test_missing_calibration_raises_runtime_error(self, tmp_path,
                                                      monkeypatch):
        """*test_missing_calibration_raises_runtime_error()* pointing the loader at an empty directory and calling `run()` without the skip flag raises `RuntimeError` with a clear pointer to `src/scripts/calibration.py`."""
        from src.io import calibration as _cal
        monkeypatch.setattr(_cal, "_CALIB_DIR", tmp_path / "calibration")
        with pytest.raises(RuntimeError,
                           match="No calibration envelope found"):
            run_experiment(adp="baseline", wrt=False,
                           method_cfg=_QUICK_CFG, verbose=False)

    def test_skip_flag_bypasses_gate_and_marks_baseline_not_applied(
            self, tmp_path, monkeypatch):
        """*test_skip_flag_bypasses_gate_and_marks_baseline_not_applied()* `skip_calibration=True` runs even with no calibration on disk; the result envelope's `baseline` block is present with `applied=False` and zeroed floor/band."""
        from src.io import calibration as _cal
        monkeypatch.setattr(_cal, "_CALIB_DIR", tmp_path / "calibration")
        _res = run_experiment(adp="baseline", wrt=False,
                              method_cfg=_QUICK_CFG,
                              skip_calibration=True, verbose=False)
        assert "baseline" in _res
        _base = _res["baseline"]
        assert _base["applied"] is False
        assert _base["baseline_ref"] is None
        assert _base["loopback_median_us"] == 0.0
        assert _base["jitter_p99_us"] == 0.0

    def test_present_calibration_attaches_baseline_block(self, tmp_path,
                                                         monkeypatch):
        """*test_present_calibration_attaches_baseline_block()* when a fresh calibration exists for the current host, `run()` attaches a populated `baseline` block (`applied=True`, real floor / band values, pointer to the JSON)."""
        import json as _json
        import socket
        from datetime import datetime
        from src.io import calibration as _cal
        _dir = tmp_path / "calibration"
        _dir.mkdir()
        monkeypatch.setattr(_cal, "_CALIB_DIR", _dir)
        _host = socket.gethostname().replace(" ", "-")
        _env = {
            "host_profile": {"hostname": _host},
            "timer": {"min_ns": 100},
            "jitter": {"p99_us": 1300.0},
            "loopback": {"median_us": 2050.0},
            "handler_scaling": {},
            "timestamp": datetime.now().isoformat(timespec="seconds"),
        }
        _path = _dir / f"{_host}_testfixture.json"
        with _path.open("w", encoding="utf-8") as _fh:
            _json.dump(_env, _fh)

        _res = run_experiment(adp="baseline", wrt=False,
                              method_cfg=_QUICK_CFG, verbose=False)
        _base = _res["baseline"]
        assert _base["applied"] is True
        assert _base["loopback_median_us"] == pytest.approx(2050.0)
        assert _base["jitter_p99_us"] == pytest.approx(1300.0)
        assert _base["baseline_ref"] is not None
        assert _base["baseline_ref"].endswith(_path.name)

# -*- coding: utf-8 -*-
"""
Module test_client.py
=====================

Unit tests for `src.experiment.client`. Use `httpx.MockTransport` so
nothing depends on spinning up the real apparatus; every test runs in
well under a second.

    - **TestInvocationRecord** `(status_code, success)` maps to `infra_failure` / `business_failure` / `response_time_s` derived properties.
    - **TestCascadeConfigDefaults** dataclass defaults.
    - **TestRampConfigDefaults** dataclass defaults.
    - **TestClientConfigKindWeights** `ClientConfig` kind-weights validation fires at `ClientSimulator.__init__` time, not at dataclass construction.
    - **TestPickKind** `_pick_kind` respects the declared weights under a seeded RNG and is deterministic given the same seed.
    - **TestValidateRamp** min_samples_per_kind floor, rates monotonicity, cascade mode, threshold and window bounds.
    - **TestBuildRampCfg** builds a `RampConfig` plus `CascadeConfig` from a dict; validates first.
    - **TestCascadeDetectorFailFast** trips on the first infra failure.
    - **TestCascadeDetectorRolling** trips only once the threshold is breached over a full window.
    - **TestSendOne** payload blob, `size_bytes`, and `X-Request-*` headers propagate to the outbound request.
    - **TestProbeStopsOnCascade** `_probe_at_rate` reports `cascade: ...` when the detector trips.
"""
# native python modules
import asyncio
import json
from typing import Any, Dict, List, Tuple

# testing framework
import pytest

# web stack
import httpx

# modules under test
from src.experiment.client import (CascadeConfig,
                                   ClientConfig,
                                   ClientSimulator,
                                   InvocationRecord,
                                   RampConfig,
                                   _CascadeDetector,
                                   build_ramp_cfg,
                                   validate_ramp)
from src.experiment.registry import ServiceRegistry


# ---------- small helpers ------------------------------------------------


def _registry() -> ServiceRegistry:
    return ServiceRegistry.from_config({
        "host": "127.0.0.1",
        "base_port": 9000,
        "service_registry": {
            "TAS_{1}": {"port_offset": 0, "role": "composite_client"},
        },
    })


def _mock_client(handler) -> httpx.AsyncClient:
    _transport = httpx.MockTransport(handler)
    return httpx.AsyncClient(transport=_transport, base_url="http://test")


def _ok_handler(request: httpx.Request) -> httpx.Response:
    """*_ok_handler()* every inbound request gets HTTP 200 + success=True."""
    _body = {
        "request_id": request.headers.get("X-Request-Id", "unknown"),
        "service_name": "TAS_{1}",
        "success": True,
        "message": "ok",
    }
    return httpx.Response(200, json=_body)


# ---------------------- InvocationRecord -------------------------------


class TestInvocationRecord:
    """**TestInvocationRecord** derived-property semantics of the client-side record."""

    def test_response_time_s_never_negative(self):
        _r = InvocationRecord(request_id="x", kind="analyse",
                              send_ts=100.0, recv_ts=99.9,
                              status_code=200, success=True)
        assert _r.response_time_s == 0.0

    def test_response_time_s_positive(self):
        _r = InvocationRecord(request_id="x", kind="analyse",
                              send_ts=100.0, recv_ts=100.25,
                              status_code=200, success=True)
        assert _r.response_time_s == pytest.approx(0.25)

    def test_infra_failure_on_5xx(self):
        _r = InvocationRecord(request_id="x", kind="analyse",
                              status_code=503, success=False)
        assert _r.infra_failure is True
        assert _r.business_failure is False

    def test_infra_failure_on_transport_exception(self):
        _r = InvocationRecord(request_id="x", kind="analyse",
                              status_code=-1, success=False)
        assert _r.infra_failure is True

    def test_business_failure_on_200_success_false(self):
        _r = InvocationRecord(request_id="x", kind="analyse",
                              status_code=200, success=False)
        assert _r.business_failure is True
        assert _r.infra_failure is False

    def test_clean_200_success(self):
        _r = InvocationRecord(request_id="x", kind="analyse",
                              status_code=200, success=True)
        assert _r.infra_failure is False
        assert _r.business_failure is False


# ------------------- dataclass defaults ---------------------------------


class TestCascadeConfigDefaults:
    """**TestCascadeConfigDefaults** safe defaults: rolling mode, 10% over 50 responses."""

    def test_defaults(self):
        _c = CascadeConfig()
        assert _c.mode == "rolling"
        assert _c.threshold == 0.10
        assert _c.window == 50


class TestRampConfigDefaults:
    """**TestRampConfigDefaults** CLT-floor sample count, sane 60s probe window."""

    def test_defaults(self):
        _r = RampConfig()
        assert _r.min_samples_per_kind == 32
        assert _r.max_probe_window_s == 60.0
        assert _r.rates[0] == 1.0
        assert isinstance(_r.cascade, CascadeConfig)


# ------------------- ClientConfig kind-weights -------------------------


class TestClientConfigKindWeights:
    """**TestClientConfigKindWeights** validation fires at `ClientSimulator.__init__`, not at `ClientConfig` construction."""

    def test_empty_kind_weights_rejected_at_simulator_construction(self):
        _cfg = ClientConfig(kind_weights={})
        with pytest.raises(ValueError, match="must sum to > 0"):
            ClientSimulator(_mock_client(_ok_handler), _registry(), _cfg)

    def test_zero_weight_rejected_at_simulator_construction(self):
        _cfg = ClientConfig(kind_weights={"TAS_{2}": 0.0})
        with pytest.raises(ValueError, match="must sum to > 0"):
            ClientSimulator(_mock_client(_ok_handler), _registry(), _cfg)


# ------------------- _pick_kind -----------------------------------------


class TestPickKind:
    """**TestPickKind** seeded + weighted draws; deterministic under fixed seed."""

    def test_single_kind_always_returned(self):
        _cfg = ClientConfig(seed=1, kind_weights={"TAS_{2}": 1.0})
        _sim = ClientSimulator(_mock_client(_ok_handler), _registry(), _cfg)
        for _ in range(20):
            assert _sim._pick_kind() == "TAS_{2}"

    def test_weighted_draws_approx_match_weights(self):
        _cfg = ClientConfig(seed=42, kind_weights={"A": 0.75, "B": 0.25})
        _sim = ClientSimulator(_mock_client(_ok_handler), _registry(), _cfg)
        _counts: Dict[str, int] = {"A": 0, "B": 0}
        for _ in range(10_000):
            _counts[_sim._pick_kind()] += 1
        # 75/25 draw: expect ~7500 A, ~2500 B with generous +/-300 tolerance
        assert abs(_counts["A"] - 7500) < 300
        assert abs(_counts["B"] - 2500) < 300

    def test_deterministic_under_same_seed(self):
        _cfg = ClientConfig(seed=7, kind_weights={"A": 0.5, "B": 0.5})
        _s1 = ClientSimulator(_mock_client(_ok_handler), _registry(), _cfg)
        _s2 = ClientSimulator(_mock_client(_ok_handler), _registry(), _cfg)
        _draws_1 = [_s1._pick_kind() for _ in range(50)]
        _draws_2 = [_s2._pick_kind() for _ in range(50)]
        assert _draws_1 == _draws_2


# ------------------- validate_ramp --------------------------------------


class TestValidateRamp:
    """**TestValidateRamp** every knob is range-checked before a run starts."""

    def _base(self, **over) -> Dict[str, Any]:
        _r = {"min_samples_per_kind": 32, "max_probe_window_s": 5.0,
              "rates": [10.0, 20.0, 50.0],
              "cascade": {"mode": "rolling", "threshold": 0.10, "window": 50}}
        _r.update(over)
        return _r

    def test_valid_config_passes(self):
        validate_ramp(self._base())

    def test_rejects_min_samples_below_clt_floor(self):
        with pytest.raises(ValueError, match="min_samples_per_kind"):
            validate_ramp(self._base(min_samples_per_kind=16))

    def test_rejects_empty_rates(self):
        with pytest.raises(ValueError, match="rates"):
            validate_ramp(self._base(rates=[]))

    def test_rejects_non_positive_rate(self):
        with pytest.raises(ValueError, match="rates"):
            validate_ramp(self._base(rates=[10.0, 0.0, 50.0]))

    def test_rejects_non_monotone_rates(self):
        with pytest.raises(ValueError, match="monotonically"):
            validate_ramp(self._base(rates=[50.0, 10.0, 20.0]))

    def test_rejects_unknown_cascade_mode(self):
        with pytest.raises(ValueError, match="cascade.mode"):
            validate_ramp(self._base(cascade={"mode": "random"}))

    def test_rejects_small_rolling_window(self):
        with pytest.raises(ValueError, match="cascade.window"):
            validate_ramp(self._base(cascade={"mode": "rolling",
                                              "threshold": 0.1, "window": 5}))

    def test_rejects_threshold_out_of_range(self):
        with pytest.raises(ValueError, match="threshold"):
            validate_ramp(self._base(cascade={"mode": "rolling",
                                              "threshold": 1.5, "window": 50}))


class TestBuildRampCfg:
    """**TestBuildRampCfg** constructs `RampConfig` + `CascadeConfig` from a dict."""

    def test_construction_round_trip(self):
        _cfg = build_ramp_cfg({
            "min_samples_per_kind": 40,
            "max_probe_window_s": 12.0,
            "rates": [5.0, 10.0, 25.0],
            "cascade": {"mode": "fail_fast", "threshold": 0.5, "window": 30},
        })
        assert _cfg.min_samples_per_kind == 40
        assert _cfg.max_probe_window_s == 12.0
        assert _cfg.rates == [5.0, 10.0, 25.0]
        assert _cfg.cascade.mode == "fail_fast"


# ------------------- cascade detector -----------------------------------


def _rec(status_code: int, success: bool = True) -> InvocationRecord:
    return InvocationRecord(request_id="x", kind="analyse",
                            status_code=status_code, success=success)


class TestCascadeDetectorFailFast:
    """**TestCascadeDetectorFailFast** trips on the first infra failure and stays tripped."""

    def test_no_trip_on_clean_traffic(self):
        _d = _CascadeDetector(CascadeConfig(mode="fail_fast"))
        for _ in range(100):
            _d.observe(_rec(200, True))
        assert _d.tripped is False

    def test_no_trip_on_business_failure(self):
        _d = _CascadeDetector(CascadeConfig(mode="fail_fast"))
        for _ in range(100):
            _d.observe(_rec(200, False))
        assert _d.tripped is False

    def test_trip_on_503(self):
        _d = _CascadeDetector(CascadeConfig(mode="fail_fast"))
        _d.observe(_rec(200, True))
        _d.observe(_rec(503, False))
        assert _d.tripped is True
        assert "503" in _d.trip_reason

    def test_trip_on_transport_exception(self):
        _d = _CascadeDetector(CascadeConfig(mode="fail_fast"))
        _d.observe(_rec(-1, False))
        assert _d.tripped is True


class TestCascadeDetectorRolling:
    """**TestCascadeDetectorRolling** threshold only compares AFTER the window is full."""

    def test_below_threshold_no_trip(self):
        _d = _CascadeDetector(CascadeConfig(mode="rolling",
                                            threshold=0.5, window=10))
        # 4 infra of 10 -> 0.4 < 0.5 -> no trip
        for _ in range(4):
            _d.observe(_rec(503, False))
        for _ in range(6):
            _d.observe(_rec(200, True))
        assert _d.tripped is False

    def test_above_threshold_trip_only_after_window_fills(self):
        _d = _CascadeDetector(CascadeConfig(mode="rolling",
                                            threshold=0.3, window=10))
        # first 9 are infra; window not full yet -> no trip
        for _ in range(9):
            _d.observe(_rec(503, False))
            assert _d.tripped is False
        # 10th fills the window -> 9/10 = 0.9 > 0.3 -> trip
        _d.observe(_rec(503, False))
        assert _d.tripped is True
        assert "rolling" in _d.trip_reason


# ------------------- _send_one ------------------------------------------


class TestSendOne:
    """**TestSendOne** built request carries the right payload, size, headers."""

    @pytest.mark.asyncio
    async def test_payload_size_matches_configured(self):
        _captured: List[Tuple[str, Dict[str, Any], Dict[str, str]]] = []

        def _handler(request: httpx.Request) -> httpx.Response:
            _body = json.loads(request.content)
            _headers = {_k: _v for _k, _v in request.headers.items()}
            _captured.append((str(request.url), _body, _headers))
            return _ok_handler(request)

        _cfg = ClientConfig(seed=1, kind_weights={"TAS_{2}": 1.0},
                            request_sizes_by_kind={"TAS_{2}": 256})
        _sim = ClientSimulator(_mock_client(_handler), _registry(), _cfg)
        _rec = await _sim._send_one("TAS_{2}")

        assert _rec.status_code == 200
        assert _rec.success is True
        assert len(_captured) == 1
        _url, _body, _headers = _captured[0]
        assert _url.endswith("/TAS_1/invoke")
        assert _body["kind"] == "TAS_{2}"
        assert _body["size_bytes"] == 256
        assert len(_body["payload"]["blob"]) == 256
        assert _headers.get("x-request-size-bytes") == "256"
        assert _headers.get("x-request-kind") == "TAS_{2}"
        assert _headers.get("x-request-id") == _rec.request_id

    @pytest.mark.asyncio
    async def test_infra_failure_recorded_on_500(self):
        def _handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(500, json={"detail": "boom"})

        _cfg = ClientConfig(seed=1, kind_weights={"TAS_{2}": 1.0},
                            request_sizes_by_kind={"TAS_{2}": 64})
        _sim = ClientSimulator(_mock_client(_handler), _registry(), _cfg)
        _rec = await _sim._send_one("TAS_{2}")
        assert _rec.status_code == 500
        assert _rec.infra_failure is True


# ------------------- _probe_at_rate -------------------------------------


class TestProbeStopsOnCascade:
    """**TestProbeStopsOnCascade** a probe at a rate stops + reports cascade when the detector trips mid-probe."""

    @pytest.mark.asyncio
    async def test_cascade_stops_probe(self):
        # every request returns 503 -> fail_fast trips on the first observation
        def _handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(503, json={"detail": "buffer full"})

        _cfg = ClientConfig(
            seed=1,
            kind_weights={"TAS_{2}": 1.0},
            request_sizes_by_kind={"TAS_{2}": 64},
            ramp=RampConfig(min_samples_per_kind=32, max_probe_window_s=5.0,
                            rates=[10.0],
                            cascade=CascadeConfig(mode="fail_fast")),
        )
        _sim = ClientSimulator(_mock_client(_handler), _registry(), _cfg)
        _detector = _CascadeDetector(_cfg.ramp.cascade)
        _probe = await _sim._probe_at_rate(10.0, _detector)
        assert "cascade" in _probe["stopped_reason"]
        assert _detector.tripped is True

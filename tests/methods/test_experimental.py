"""Tests for `src.methods.experimental`.

**TestExperimental**: top-level `run()` dispatcher, per-svc admission lifts (`profile.specs` -> mesh wire format), and the open-loop producer / consumer trial driver.

- *test_run_dispatches_calibration()*: `stage='calibration'` delegates to `run_calibration` and returns its result unchanged.
- *test_run_dispatches_experiment()*: `stage='experiment'` delegates to `run_experiment` and returns its result unchanged.
- *test_run_dispatches_both()*: `stage='both'` calls `run_calibration` then `run_experiment`, threads the envelope into the second call, and returns both keyed by stage.
- *test_run_unknown_stage_raises()*: an unknown stage name is rejected immediately rather than silently doing nothing.
- *test_admission_lt_baseline_carries_c_and_k()*: `_admission_lt_from_profile('baseline')` returns one entry per artifact with int `c` and `k`.
- *test_resolve_admission_per_svc_wins()*: per-svc lookup overrides the global default; missing ids fall through.
- *test_mesh_admission_block_shape()*: `_build_mesh_admission` carries `{c, K, mu, eps}` per atomic id.
- *test_dispatch_flood_no_pacing()*: rate=0 pushes exactly `n_requests` ticks onto the queue.
- *test_dispatch_pacing_is_drift_corrected()*: at rate=R, dispatch completes in ~n/R seconds (drift-corrected, not cumulative-sleep).
- *test_dispatch_stop_event_halts()*: setting `stop_event` mid-dispatch exits early; fewer than `n_requests` ticks pushed.
- *test_dispatch_breach_poll_sets_reason()*: a mocked breach trips `stop_reason_box[0]` to the breach reason.
- *test_consumer_sentinel_exits_cleanly()*: a `None` tick exits the consumer without calling `run_one`.
- *test_consumer_records_into_summaries()*: each tick produces one entry in the shared summaries list.
- *test_drive_trial_drain_timeout_cancels_hanging_consumer()*: a consumer that never exits is cancelled after `drain_timeout_s`.

The full calibration + experiment paths are integration code; `tests/demo/calibration.py` exercises them end-to-end and the notebook is the human-facing check.
"""

from __future__ import annotations

import asyncio
import time
from types import SimpleNamespace
from typing import Any
from unittest.mock import patch

import pytest

from src.methods import experimental


class _FakeUser:
    """Async-context-manager User stand-in. `run_one()` returns a fixed record-like object so consumer tests don't boot httpx."""

    def __init__(self, *_args: Any, **_kwargs: Any) -> None:
        self.client_id = _kwargs.get("client_id", "fake")
        self.calls = 0

    async def __aenter__(self) -> "_FakeUser":
        return self

    async def __aexit__(self, *_args: Any) -> None:
        return None

    async def run_one(self) -> Any:
        self.calls += 1
        return SimpleNamespace(req_id=f"{self.client_id}-r{self.calls}",
                               kind="alarm",
                               outcome="success",
                               status_code=200,
                               total_latency_s=0.001)


class _HangingUser(_FakeUser):
    """`run_one()` awaits forever so drain-timeout behaviour can be exercised."""

    async def run_one(self) -> Any:
        await asyncio.Event().wait()  # never resolves
        return SimpleNamespace(req_id="never", kind="alarm", outcome="success",
                               status_code=200, total_latency_s=0.0)


class TestExperimental:
    """Top-level `run()` dispatcher, admission lifts, and open-loop trial driver."""

    def test_run_dispatches_calibration(self) -> None:
        """*test_run_dispatches_calibration()* `stage='calibration'` delegates to `run_calibration` and returns its result unchanged."""
        _sentinel: dict[str, Any] = {"sentinel": True}
        with patch.object(experimental,
                          "run_calibration",
                          return_value=_sentinel) as _mocked:
            _ans = experimental.run(stage="calibration",
                                    dpl="localhost",
                                    framework="fastapi",
                                    wsgi_server="waitress",
                                    write=False)
        assert _ans is _sentinel
        _mocked.assert_called_once()

    def test_run_dispatches_experiment(self) -> None:
        """*test_run_dispatches_experiment()* `stage='experiment'` delegates to `run_experiment` and returns its result unchanged."""
        _sentinel: dict[str, Any] = {"sentinel": True}
        with patch.object(experimental,
                          "run_experiment",
                          return_value=_sentinel) as _mocked:
            _ans = experimental.run(stage="experiment",
                                    adp="baseline",
                                    dpl="localhost",
                                    write=False)
        assert _ans is _sentinel
        _mocked.assert_called_once()

    def test_run_dispatches_both(self) -> None:
        """*test_run_dispatches_both()* `stage='both'` calls `run_calibration` then `run_experiment` (envelope is threaded into the second call) and returns both keyed by stage."""
        _calib: dict[str, Any] = {"calib": True, "gate": {"verifiable_range": {}}}
        _exp: dict[str, Any] = {"exp": True}
        with patch.object(experimental,
                          "run_calibration",
                          return_value=_calib) as _calib_mock, patch.object(
                              experimental,
                              "run_experiment",
                              return_value=_exp) as _exp_mock:
            _ans = experimental.run(stage="both",
                                    adp="baseline",
                                    dpl="localhost",
                                    write=False)
        assert _ans == {"calibration": _calib, "experiment": _exp}
        _calib_mock.assert_called_once()
        _exp_mock.assert_called_once()
        # The experiment must reuse the freshly produced envelope rather than re-discovering one.
        assert _exp_mock.call_args.kwargs["envelope"] is _calib

    def test_run_unknown_stage_raises(self) -> None:
        """*test_run_unknown_stage_raises()* an unknown stage name is rejected immediately rather than silently doing nothing."""
        with pytest.raises(ValueError, match="unknown stage"):
            experimental.run(stage="nonsense")

    def test_admission_lt_baseline_carries_c_and_k(self) -> None:
        """*test_admission_lt_baseline_carries_c_and_k()* `_admission_lt_from_profile('baseline')` returns one entry per artifact with int `c` and `k`."""
        _lt = experimental._admission_lt_from_profile("baseline")
        assert "MAS_{1}" in _lt
        _entry = _lt["MAS_{1}"]
        assert isinstance(_entry["c"], int)
        assert isinstance(_entry["k"], int)
        assert _entry["c"] == 1
        assert _entry["k"] == 10

    def test_resolve_admission_per_svc_wins(self) -> None:
        """*test_resolve_admission_per_svc_wins()* per-svc lookup overrides the global default; missing ids fall through."""
        _lt = {"MAS_{1}": {"c": 7, "k": 42}}
        assert experimental._resolve_admission("MAS_{1}", _lt, 1, 1) == (42, 7)
        assert experimental._resolve_admission("OTHER", _lt, 5, 9) == (5, 9)
        assert experimental._resolve_admission("OTHER", _lt, None, None) == (None, None)

    def test_mesh_admission_block_shape(self) -> None:
        """*test_mesh_admission_block_shape()* `_build_mesh_admission` carries `{c, K, mu, eps}` per atomic id."""
        _admission_lt = {"MAS_{1}": {"c": 1, "k": 10}}
        _mu_lt = {"MAS_{1}": 180.0}
        _eps_lt = {"MAS_{1}": 0.12}
        _block = experimental._build_mesh_admission(
            atomic_ids=["MAS_{1}"],
            admission_lt=_admission_lt,
            mu_lt=_mu_lt,
            eps_lt=_eps_lt,
            atomic_admission={"k": None, "c": None},
        )
        assert _block["MAS_{1}"] == {"c": 1, "K": 10, "mu": 180.0, "eps": 0.12}

    @pytest.mark.asyncio
    async def test_dispatch_flood_no_pacing(self) -> None:
        """*test_dispatch_flood_no_pacing()* `rate=0` pushes exactly `n_requests` integer ticks onto the queue with no pacing delay."""
        _queue: asyncio.Queue[int | None] = asyncio.Queue()
        _stop_event = asyncio.Event()
        _reason_box: list[str] = ["n_reached"]
        await experimental._dispatch_at_rate(
            queue=_queue,
            n_requests=5,
            rate=0,
            stop_event=_stop_event,
            stop_reason_box=_reason_box,
            breach_http=None,
            controller_url=None,
            adp="baseline",
            poll_every_n=0,
        )
        _ticks: list[int | None] = []
        while not _queue.empty():
            _ticks.append(_queue.get_nowait())
        assert _ticks == [0, 1, 2, 3, 4]
        assert _reason_box[0] == "n_reached"

    @pytest.mark.asyncio
    async def test_dispatch_pacing_is_drift_corrected(self) -> None:
        """*test_dispatch_pacing_is_drift_corrected()* at `rate=20`, pushing 20 ticks takes ~1 s. The dispatcher computes absolute targets (`start + i/rate`), so cumulative `asyncio.sleep` granularity doesn't drift the schedule."""
        _queue: asyncio.Queue[int | None] = asyncio.Queue()
        _stop_event = asyncio.Event()
        _reason_box: list[str] = ["n_reached"]
        _t0 = time.perf_counter()
        await experimental._dispatch_at_rate(
            queue=_queue,
            n_requests=20,
            rate=20.0,
            stop_event=_stop_event,
            stop_reason_box=_reason_box,
            breach_http=None,
            controller_url=None,
            adp="baseline",
            poll_every_n=0,
        )
        _elapsed = time.perf_counter() - _t0
        # 20 ticks at 20 req/s -> ~1s; allow generous bounds for CI / Windows jitter.
        assert 0.7 < _elapsed < 1.8
        assert _queue.qsize() == 20

    @pytest.mark.asyncio
    async def test_dispatch_stop_event_halts(self) -> None:
        """*test_dispatch_stop_event_halts()* setting `stop_event` mid-dispatch exits the loop early; fewer than `n_requests` ticks land on the queue."""
        _queue: asyncio.Queue[int | None] = asyncio.Queue()
        _stop_event = asyncio.Event()
        _reason_box: list[str] = ["n_reached"]

        async def _trip_stop_event_soon() -> None:
            await asyncio.sleep(0.05)
            _stop_event.set()

        _trip = asyncio.create_task(_trip_stop_event_soon())
        await experimental._dispatch_at_rate(
            queue=_queue,
            n_requests=1000,
            rate=20.0,  # would take 50 s un-stopped
            stop_event=_stop_event,
            stop_reason_box=_reason_box,
            breach_http=None,
            controller_url=None,
            adp="baseline",
            poll_every_n=0,
        )
        await _trip
        assert _queue.qsize() < 1000  # early-exit, not full run

    @pytest.mark.asyncio
    async def test_dispatch_breach_poll_sets_reason(self) -> None:
        """*test_dispatch_breach_poll_sets_reason()* the dispatcher calls `_check_breach` every `poll_every_n` ticks; a positive verdict sets `stop_reason_box[0]` and exits."""
        _queue: asyncio.Queue[int | None] = asyncio.Queue()
        _stop_event = asyncio.Event()
        _reason_box: list[str] = ["n_reached"]
        _http = SimpleNamespace()  # _check_breach is patched; concrete object irrelevant.

        async def _fake_check_breach(_http_arg: Any, _url: str, _adp: str) -> tuple[bool, str]:
            return True, "r1_breach"

        with patch("src.experimental.procedure.experiment._check_breach", _fake_check_breach):
            await experimental._dispatch_at_rate(
                queue=_queue,
                n_requests=100,
                rate=0,
                stop_event=_stop_event,
                stop_reason_box=_reason_box,
                breach_http=_http,  # type: ignore[arg-type]
                controller_url="http://controller",
                adp="baseline",
                poll_every_n=5,
            )
        assert _reason_box[0] == "r1_breach"
        assert _stop_event.is_set()

    @pytest.mark.asyncio
    async def test_consumer_sentinel_exits_cleanly(self,
                                                   monkeypatch: pytest.MonkeyPatch) -> None:
        """*test_consumer_sentinel_exits_cleanly()* a `None` tick on the queue exits the consumer immediately without invoking `run_one`."""
        monkeypatch.setattr("src.experimental.procedure.experiment.User", _FakeUser)
        _queue: asyncio.Queue[int | None] = asyncio.Queue()
        await _queue.put(None)
        _summaries: list[dict[str, Any]] = []
        await experimental._consume_payloads(
            consumer_id=0,
            base_url="http://x",
            queue=_queue,
            summaries=_summaries,
            summaries_lock=asyncio.Lock(),
            stop_event=asyncio.Event(),
            p_alarm=0.25,
            request_timeout_s=1.0,
            seed=None,
        )
        assert _summaries == []  # no ticks consumed

    @pytest.mark.asyncio
    async def test_consumer_records_into_summaries(self,
                                                   monkeypatch: pytest.MonkeyPatch) -> None:
        """*test_consumer_records_into_summaries()* each non-sentinel tick produces one entry in the shared summaries list with the expected schema."""
        monkeypatch.setattr("src.experimental.procedure.experiment.User", _FakeUser)
        _queue: asyncio.Queue[int | None] = asyncio.Queue()
        for _i in range(3):
            await _queue.put(_i)
        await _queue.put(None)
        _summaries: list[dict[str, Any]] = []
        await experimental._consume_payloads(
            consumer_id=7,
            base_url="http://x",
            queue=_queue,
            summaries=_summaries,
            summaries_lock=asyncio.Lock(),
            stop_event=asyncio.Event(),
            p_alarm=0.25,
            request_timeout_s=1.0,
            seed=None,
        )
        assert len(_summaries) == 3
        assert {"req_id", "kind", "outcome", "status", "latency_s"} <= set(_summaries[0])
        assert _summaries[0]["status"] == 200

    @pytest.mark.asyncio
    async def test_drive_trial_drain_timeout_cancels_hanging_consumer(self,
                                                                     monkeypatch: pytest.MonkeyPatch) -> None:
        """*test_drive_trial_drain_timeout_cancels_hanging_consumer()* a consumer whose `run_one` never resolves is cancelled after `drain_timeout_s`; `_drive_trial` returns instead of hanging."""
        monkeypatch.setattr("src.experimental.procedure.experiment.User", _HangingUser)
        _t0 = time.perf_counter()
        _summaries, _reason = await experimental._drive_trial(
            tas_urls=["http://x"],
            n_requests=2,
            request_rate_per_s=0,
            p_alarm=0.25,
            request_timeout_s=1.0,
            seed=None,
            controller_url=None,
            adp="baseline",
            poll_every_n=0,
            consumer_pool_size=1,
            max_queue_depth=4,
            drain_timeout_s=0.3,
        )
        _elapsed = time.perf_counter() - _t0
        assert _reason == "n_reached"
        # Drain timeout fires; trial returns rather than hanging forever on the stuck consumer.
        assert _elapsed < 2.0

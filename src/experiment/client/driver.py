# -*- coding: utf-8 -*-
"""
Module client/driver.py
=======================

Pace HTTP sends at a target rate on absolute deadlines under the Windows asyncio rate-precision recipe.
"""
# native python modules
from __future__ import annotations

import asyncio
import random
import time
from typing import Any, Dict, List, Tuple

# web stack
import httpx

# local modules
from src.experiment.client.config import RampCfg
from src.experiment.client.guard import StopGuard
from src.experiment.client.records import RequestRecord
from src.experiment.client.sender import RequestSender
from src.experiment.client.stats import compute_probe_stats


# 20 ms tick amortises the ~3 ms per-iter overhead K-fold
_TARGET_TICK_S: float = 0.020


class RateDriver:
    """*RateDriver* loop that paces one probe at one target request rate.

    Owns the async loop and the in-flight task list; calls a `RequestSender` to issue work and a `StopGuard` to decide when the probe is done.
    """

    def __init__(self, sender: RequestSender,
                 guard: StopGuard,
                 ramp_cfg: RampCfg,
                 kind_names: List[str],
                 kind_prob_norm: List[float],
                 rng: random.Random) -> None:
        """*__init__()* bind dependencies and seed the run-state.

        Args:
            sender (RequestSender): builds and dispatches one request.
            guard (StopGuard): infrastructure-failure detector.
            ramp_cfg (RampCfg): per-rate probe spec.
            kind_names (List[str]): kind labels parallel to `kind_prob_norm`.
            kind_prob_norm (List[float]): normalised kind probabilities.
            rng (random.Random): seeded source for kind sampling.
        """
        self.sender = sender
        self.guard = guard
        self.ramp_cfg = ramp_cfg
        self.kind_names = kind_names
        self.kind_prob_norm = kind_prob_norm
        self.rng = rng

        # mutated by the run-loop; stays False outside `run()`
        self.active: bool = False
        self.stop_reason: str = "samples_reached"

    def _pick_kind(self) -> str:
        """*_pick_kind()* sample one label from `kind_names` weighted by `kind_prob_norm`."""
        return self.rng.choices(self.kind_names,
                                weights=self.kind_prob_norm,
                                k=1)[0]

    async def _drain_done(self,
                          in_flight: List[asyncio.Task]
                          ) -> Tuple[List[RequestRecord], List[asyncio.Task]]:
        """*_drain_done()* partition `in_flight` into completed records and still-pending tasks.

        Args:
            in_flight (List[asyncio.Task]): tasks possibly completed since the last drain.

        Returns:
            Tuple[List[RequestRecord], List[asyncio.Task]]: completed records and pending tasks.
        """
        _collected: List[RequestRecord] = []
        _still_pending: List[asyncio.Task] = []
        for _t in in_flight:
            if _t.done():
                _collected.append(await _t)
            else:
                _still_pending.append(_t)
        return _collected, _still_pending

    def _check_stop(self,
                    probe_start: float,
                    max_s: float,
                    counts: Dict[str, int],
                    target: int) -> bool:
        """*_check_stop()* evaluate the three exit conditions and update `self.active` / `self.stop_reason`.

        Args:
            probe_start (float): perf-counter timestamp at probe entry.
            max_s (float, seconds): per-probe safety timeout.
            counts (Dict[str, int]): per-kind 200-count.
            target (int): per-kind sample target.

        Returns:
            bool: True while the loop should keep running, False once an exit condition has fired.
        """
        if self.guard.tripped:
            self.stop_reason = f"cascade: {self.guard.reason}"
            self.active = False
        elif time.perf_counter() - probe_start > max_s:
            self.stop_reason = "probe_timeout"
            self.active = False
        elif all(_c >= target for _c in counts.values()):
            self.active = False
        return self.active

    def _fold_records(self,
                      collected: List[RequestRecord],
                      records: List[RequestRecord],
                      counts: Dict[str, int]) -> None:
        """*_fold_records()* extend `records`, bump per-kind 200-counts, and feed the guard.

        Args:
            collected (List[RequestRecord]): newly drained records.
            records (List[RequestRecord]): cumulative record store (mutated in place).
            counts (Dict[str, int]): per-kind 200-count (mutated in place).
        """
        for _rec in collected:
            records.append(_rec)
            if _rec.status_code == 200:
                counts[_rec.kind] = counts.get(_rec.kind, 0) + 1
            self.guard.observe(_rec)

    def _fire_batch(self,
                    in_flight: List[asyncio.Task],
                    counts: Dict[str, int],
                    batch_size: int,
                    target: int,
                    send_idx: int) -> int:
        """*_fire_batch()* schedule up to `batch_size` sends; flip `self.active` to False once every kind has reached `target`.

        Args:
            in_flight (List[asyncio.Task]): pending-task list (mutated in place).
            counts (Dict[str, int]): per-kind 200-count (read-only here).
            batch_size (int): cap on sends issued this tick.
            target (int): per-kind sample target.
            send_idx (int): running send counter.

        Returns:
            int: updated `send_idx`.
        """
        _new_idx = send_idx
        for _ in range(batch_size):
            _all_done = all(_c >= target for _c in counts.values())
            if _all_done:
                self.active = False
                return _new_idx
            _kind = self._pick_kind()
            _t = asyncio.create_task(self.sender.send_one(_kind))
            in_flight.append(_t)
            _new_idx += 1
        return _new_idx

    async def run(self, rate: float) -> Dict[str, Any]:
        """*run()* execute one probe at `rate` req/s and return the aggregated summary.

        Exits on three conditions, set by `_check_stop`: per-kind sample target met, `max_probe_s` elapsed, or guard tripped.

        Args:
            rate (float, req/s): deterministic target rate.

        Returns:
            Dict[str, Any]: probe summary as built by `compute_probe_stats`.
        """
        _target = int(self.ramp_cfg.min_n_per_kind)
        _max_s = float(self.ramp_cfg.max_probe_s)
        if rate > 0:
            _interarrival = 1.0 / rate
        else:
            _interarrival = _max_s

        _records: List[RequestRecord] = []
        _in_flight: List[asyncio.Task] = []
        _counts: Dict[str, int] = {_k: 0 for _k in self.kind_names}
        _probe_start = time.perf_counter()
        self.stop_reason = "samples_reached"
        self.active = True

        _batch_size = max(1, int(round(_TARGET_TICK_S / _interarrival)))
        _send_idx = 0

        while self._check_stop(_probe_start, _max_s, _counts, _target):
            _deadline = _probe_start + _send_idx * _interarrival
            _wait = _deadline - time.perf_counter()
            if _wait > 0:
                _loop = asyncio.get_event_loop()
                await _loop.run_in_executor(None, time.sleep, _wait)
            else:
                await asyncio.sleep(0)

            _send_idx = self._fire_batch(_in_flight,
                                         _counts,
                                         _batch_size,
                                         _target,
                                         _send_idx)

            _collected, _in_flight = await self._drain_done(_in_flight)
            self._fold_records(_collected, _records, _counts)

        for _t in _in_flight:
            try:
                _rec = await _t
            except (httpx.HTTPError, ConnectionError, OSError,
                    asyncio.TimeoutError, ValueError, RuntimeError):
                continue
            self._fold_records([_rec], _records, _counts)

        _duration = time.perf_counter() - _probe_start
        _summary = compute_probe_stats(_records,
                                       _counts,
                                       _duration,
                                       rate,
                                       self.stop_reason,
                                       self.kind_names)
        return _summary

# -*- coding: utf-8 -*-
"""
Module calibration/controller.py
================================

Composition layer for the calibration package. The grid dataclasses (`HostSweepGrid`, `DasaSweepGrid`) capture the JSON-side configuration as immutable typed records; `SweepController` holds them plus a `StopConditions` and a `dpl`, then composes the host-floor probes (`hoststats`), rate-saturation discovery (`rate`), and apparatus self-consistency (`stability`) into a single host-side envelope.

The `dpl` axis switches the underlying transport: `"localhost"` uses `UvicornThread` (in-process loopback for fast iteration); `"multiprocess"` uses `UvicornProcess` (real OS-process loopback with separate event loop). Per-service code is identical across both modes; only the gauge launcher differs.

Public API:
    - `HostSweepGrid`: frozen dataclass holding the host-floor probe knobs (n_con_usr ladder, rates, sample counts, payload size).
    - `DasaSweepGrid`: frozen dataclass holding the DASA-profile sweep knobs (c, K, mu_factor).
    - `SweepController`: orchestrates the host-floor probe sequence and writes the envelope.

The `run_dasa_sweep` method raises `NotImplementedError` until Stage C8 lands `src/dimensional/dasaprof.py`; the controller's role here is to compose what C5+C6 already provide, not to recompute the dimensional card.
"""
# native python modules
from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, Optional, Tuple, cast

# local modules
from src.calibration.conditionals import StopConditions
from src.calibration.envelope import write_envelope
from src.calibration.hoststats import (measure_handler_scaling,
                                       measure_jitter,
                                       measure_loopback,
                                       measure_timer,
                                       snapshot_host_profile)
from src.calibration.rate import run_rate_sweep
from src.calibration.stability import run_handler_stability_sweep
from src.experiment.instances import make_gauge_factory
from src.experiment.runtime import (UvicornProcess,
                                    UvicornThread,
                                    run_async_safe)
from src.experiment.services import SvcSpec


_VALID_DPL: Tuple[str, ...] = ("localhost", "multiprocess")


@dataclass(frozen=True)
class HostSweepGrid:
    """**HostSweepGrid** host-floor probe configuration: closed-loop ladder, open-loop rates, sample counts, payload size.

    Frozen so an instance can be safely shared across the sweep without accidental in-flight mutation. Defaults match `data/config/method/calibration.json` so a default-constructed grid produces the same envelope an unconfigured run would.

    Attributes:
        n_con_usr (Tuple[int, ...]): closed-loop client concurrency ladder driven by `measure_handler_scaling`.
        rates (Tuple[float, ...]): open-loop target rates (req/s) driven by `run_rate_sweep`.
        payload_size_bytes (int): per-request body size; locked decision Q-C keeps this at 128000.
        samples_per_level (int): per-`n_con_usr` sample budget for `measure_handler_scaling`.
        timer_samples (int): back-to-back read count for `measure_timer`.
        jitter_samples (int): sleep-cycle count for `measure_jitter`.
        loopback_samples (int): post-warmup request count for `measure_loopback`.
        loopback_warmup (int): pre-timing warmup count for `measure_loopback`.
        rate_trials_per_rate (int): trials per rate for the rate sweep aggregation.
        rate_max_probe_s (float): wall-clock window per rate trial.
        rate_target_loss_pct (float): pass bar for the calibrated highest-sustainable rate.
        run_rate_sweep (bool): when False, skip the open-loop rate-saturation block (host-floor probes still run).
        run_stability_sweep (bool): when False, skip the apparatus self-consistency block.
    """

    n_con_usr: Tuple[int, ...] = (1, 10, 32, 64, 96, 128)
    rates: Tuple[float, ...] = (10.0, 50.0, 200.0, 300.0, 400.0)
    payload_size_bytes: int = 128000
    samples_per_level: int = 1024
    timer_samples: int = 100000
    jitter_samples: int = 2000
    loopback_samples: int = 5000
    loopback_warmup: int = 500
    rate_trials_per_rate: int = 5
    rate_max_probe_s: float = 1.5
    rate_target_loss_pct: float = 2.5
    run_rate_sweep: bool = True
    run_stability_sweep: bool = True

    @classmethod
    def from_config(cls, cfg: Dict[str, Any]) -> "HostSweepGrid":
        """*from_config()* hydrate from a parsed `calibration.json` (full file, not just one block).

        Reads the host-floor knobs at top level plus the `rate_sweep` sub-block. Missing keys fall back to the dataclass defaults so a partial JSON still loads.

        Args:
            cfg (Dict[str, Any]): parsed `calibration.json`; typical keys include `n_con_usr`, `samples_per_level`, `payload_size_bytes`, `timer_samples`, `jitter_samples`, `loopback_samples`, `loopback_warmup`, plus a nested `rate_sweep` dict.

        Returns:
            HostSweepGrid: all fields resolved with config-or-default values.
        """
        _rs = cfg.get("rate_sweep") or {}
        return cls(
            n_con_usr=tuple(int(_n) for _n in cfg.get("n_con_usr", cls.n_con_usr)),
            rates=tuple(float(_r) for _r in _rs.get("rates", cls.rates)),
            payload_size_bytes=int(cfg.get("payload_size_bytes",
                                           cls.payload_size_bytes)),
            samples_per_level=int(cfg.get("samples_per_level",
                                          cls.samples_per_level)),
            timer_samples=int(cfg.get("timer_samples", cls.timer_samples)),
            jitter_samples=int(cfg.get("jitter_samples", cls.jitter_samples)),
            loopback_samples=int(cfg.get("loopback_samples", cls.loopback_samples)),
            loopback_warmup=int(cfg.get("loopback_warmup", cls.loopback_warmup)),
            rate_trials_per_rate=int(_rs.get("trials_per_rate",
                                             cls.rate_trials_per_rate)),
            rate_max_probe_s=float(_rs.get("max_probe_window_s",
                                           cls.rate_max_probe_s)),
            rate_target_loss_pct=float(_rs.get("target_loss_pct",
                                               cls.rate_target_loss_pct)),
            run_rate_sweep=not bool(cfg.get("skip_rate_sweep", False)),
            run_stability_sweep=not bool(cfg.get("skip_handler_stability_sweep",
                                                 False)),
        )


@dataclass(frozen=True)
class DasaSweepGrid:
    """**DasaSweepGrid** DASA-profile sweep grid: parallel workers, queue slots, mu multipliers.

    Frozen so an instance can be safely shared. Consumed by Stage C8's `derive_calib_coefs` to tile the per-`n_con_usr` observables across the cartesian.

    Attributes:
        c (Tuple[int, ...]): parallel-worker counts swept (M/M/c/K c-axis); per locked decision Q-D, may exceed `os.cpu_count()` (intentional contention regime).
        K (Tuple[int, ...]): queue-slot counts swept (M/M/c/K K-axis).
        mu_factor (Tuple[float, ...]): mu multipliers applied to the host-anchored mu (loopback-derived); 1.0 = host mu unmodified.
    """

    c: Tuple[int, ...] = (8, 16, 32)
    K: Tuple[int, ...] = (64, 128, 256)
    mu_factor: Tuple[float, ...] = (0.5, 1.0, 1.5, 2.0)

    @classmethod
    def from_config(cls, cfg: Dict[str, Any]) -> "DasaSweepGrid":
        """*from_config()* hydrate from a parsed `calibration.json::sweep_grid` block.

        Args:
            cfg (Dict[str, Any]): parsed `calibration.json`; reads the `sweep_grid` sub-dict.

        Returns:
            DasaSweepGrid: all fields resolved with config-or-default values.
        """
        _sg = cfg.get("sweep_grid") or {}
        return cls(
            c=tuple(int(_c) for _c in _sg.get("c", cls.c)),
            K=tuple(int(_k) for _k in _sg.get("K", cls.K)),
            mu_factor=tuple(float(_m) for _m in _sg.get("mu_factor",
                                                        cls.mu_factor)),
        )


@dataclass
class SweepController:
    """**SweepController** orchestrate the host-floor probe sequence for one `dpl`.

    Holds three configuration objects (`host_grid`, `dasa_grid`, `stop`) plus the `dpl` axis value that selects the gauge transport. The `run_host_sweep` method composes all five host-floor blocks (timer / jitter / loopback / handler_scaling / optional rate_sweep / optional handler_stability_sweep) into one envelope dict; `write` then persists via `envelope.write_envelope` under `data/results/calibration/<dpl>/`.

    `run_dasa_sweep` raises `NotImplementedError` until Stage C8 ships `src/dimensional/dasaprof.py`.

    Attributes:
        host_grid (HostSweepGrid): host-floor probe knobs.
        dasa_grid (DasaSweepGrid): DASA-profile sweep knobs (consumed by C8).
        stop (StopConditions): per-iteration halt thresholds (consumed by C8 sweep cells).
        dpl (str): deployment-axis value; one of `"localhost"`, `"multiprocess"`.
        port (int): TCP port the gauge binds to (single port reused across host-floor probes).
        ready_timeout_s (float): seconds to wait for gauge readiness on `start`.
        inter_level_delay_s (float): forwarded to `measure_handler_scaling`.
        verbose (bool): when True, propagate per-probe progress prints to stdout.
    """

    host_grid: HostSweepGrid
    dasa_grid: DasaSweepGrid
    stop: StopConditions
    dpl: str
    port: int = 8765
    ready_timeout_s: float = 2.0
    inter_level_delay_s: float = 1.0
    verbose: bool = True

    def __post_init__(self) -> None:
        """*__post_init__()* validate `dpl` against `_VALID_DPL`.

        Raises:
            ValueError: when `dpl` is not in `_VALID_DPL`.
        """
        if self.dpl not in _VALID_DPL:
            _msg = f"dpl={self.dpl!r} not recognised; valid: {_VALID_DPL}"
            raise ValueError(_msg)

    def _gauge_spec(self) -> SvcSpec:
        """*_gauge_spec()* canonical host-floor vernier spec: `c=1, K=10, mu=0, epsilon=0`.

        Returns:
            SvcSpec: vernier spec named `"CALIB_HOST"`.
        """
        _K = 10
        return SvcSpec(name="CALIB_HOST",
                       role="atomic",
                       port=int(self.port),
                       mu=0.0,
                       epsilon=0.0,
                       c=1,
                       K=_K,
                       seed=0,
                       mem_per_buffer=int(self.host_grid.payload_size_bytes
                                          * _K * SvcSpec.MEM_HEADROOM_FACTOR))

    def _spawn_gauge(self) -> Any:
        """*_spawn_gauge()* start a gauge per the `dpl` axis: `UvicornThread` for localhost, `UvicornProcess` for multiprocess.

        The returned object exposes the same `start` / `wait_ready` / `shutdown` surface in both branches; callers do not need to know which transport landed.

        Returns:
            UvicornThread | UvicornProcess: started server; the caller is responsible for `wait_ready` and `shutdown`.
        """
        _spec = self._gauge_spec()
        _factory = make_gauge_factory(
            _spec, payload_size_bytes=self.host_grid.payload_size_bytes)
        if self.dpl == "localhost":
            _server = UvicornThread(_factory(), port=self.port)
        else:
            _server = UvicornProcess(_factory, port=self.port)
        _server.start()
        return _server

    async def _run_loopback_and_scaling(self
                                        ) -> Tuple[Dict[str, float],
                                                   Dict[str, Dict[str, float]]]:
        """*_run_loopback_and_scaling()* spawn a single gauge and run loopback + handler-scaling against it.

        The two probes share one server lifecycle so the gauge spawn cost is paid once. Loopback runs first to characterise the steady-state floor; handler-scaling then climbs the n_con_usr ladder against the same instance.

        Returns:
            Tuple[Dict[str, float], Dict[str, Dict[str, float]]]: `(loopback_stats, handler_scaling_stats_by_n)`.
        """
        _server = self._spawn_gauge()
        try:
            _server.wait_ready(timeout_s=self.ready_timeout_s)
            _loop_stats = await measure_loopback(
                self.port,
                samples=self.host_grid.loopback_samples,
                warmup=self.host_grid.loopback_warmup,
                payload_size_bytes=self.host_grid.payload_size_bytes,
            )
            _scaling_stats = await measure_handler_scaling(
                self.port,
                n_con_usr=self.host_grid.n_con_usr,
                warmup=self.host_grid.loopback_warmup,
                samples_per_level=self.host_grid.samples_per_level,
                inter_level_delay_s=self.inter_level_delay_s,
                payload_size_bytes=self.host_grid.payload_size_bytes,
            )
        finally:
            _server.shutdown()
        return _loop_stats, _scaling_stats

    def run_host_sweep(self) -> Dict[str, Any]:
        """*run_host_sweep()* compose the host-floor envelope and return it (caller writes to disk via `write`).

        Sequence: `snapshot_host_profile` -> `measure_timer` -> `measure_jitter` -> spawn gauge -> `measure_loopback` -> `measure_handler_scaling` -> shutdown gauge -> optional `run_rate_sweep` -> optional `run_handler_stability_sweep`. The two optional blocks each spin up their own gauge so any state leak from the host-floor probes does not contaminate them.

        Returns:
            Dict[str, Any]: envelope with `host_profile`, `timer`, `jitter`, `loopback`, `handler_scaling`, `dpl`, `host_grid` (provenance), `elapsed_s`, plus `rate_sweep` and `handler_stability_sweep` when enabled.
        """
        _t0 = time.perf_counter()
        _envelope: Dict[str, Any] = {
            "host_profile": snapshot_host_profile(),
            "dpl": self.dpl,
            "host_grid": {
                "n_con_usr": list(self.host_grid.n_con_usr),
                "rates": list(self.host_grid.rates),
                "payload_size_bytes": self.host_grid.payload_size_bytes,
                "samples_per_level": self.host_grid.samples_per_level,
            },
        }

        _envelope["timer"] = measure_timer(self.host_grid.timer_samples)
        _envelope["jitter"] = measure_jitter(self.host_grid.jitter_samples)

        async def _orchestrator() -> Tuple[Dict[str, float],
                                            Dict[str, Dict[str, float]]]:
            return await self._run_loopback_and_scaling()

        _loop, _scaling = cast(
            Tuple[Dict[str, float], Dict[str, Dict[str, float]]],
            run_async_safe(_orchestrator),  # type: ignore[arg-type]
        )
        _envelope["loopback"] = _loop
        _envelope["handler_scaling"] = _scaling

        if self.host_grid.run_rate_sweep:
            _envelope["rate_sweep"] = run_rate_sweep(
                rates=self.host_grid.rates,
                trials_per_rate=self.host_grid.rate_trials_per_rate,
                max_probe_s=self.host_grid.rate_max_probe_s,
                target_loss_pct=self.host_grid.rate_target_loss_pct,
                calibrate=True,
                port=self.port,
                payload_size_bytes=self.host_grid.payload_size_bytes,
                ready_timeout_s=self.ready_timeout_s,
                verbose=self.verbose,
            )

        if self.host_grid.run_stability_sweep:
            _envelope["handler_stability_sweep"] = run_handler_stability_sweep(
                n_con_usr=self.host_grid.n_con_usr,
                samples_per_level=self.host_grid.samples_per_level,
                warmup=self.host_grid.loopback_warmup,
                port=self.port,
                payload_size_bytes=self.host_grid.payload_size_bytes,
                ready_timeout_s=self.ready_timeout_s,
                verbose=self.verbose,
            )

        _envelope["elapsed_s"] = round(time.perf_counter() - _t0, 3)
        return _envelope

    def run_dasa_sweep(self,
                       envelope: Dict[str, Any],
                       deriver: Optional[Callable[..., Dict[str, Any]]] = None
                       ) -> Dict[str, Any]:
        """*run_dasa_sweep()* attach a Route-B dimensional card to the envelope by calling the injected `deriver`.

        Until Stage C8 lands `src/dimensional/dasaprof.derive_calib_coefs`, no default deriver is wired in; callers must inject one or accept the `NotImplementedError`. After C8, the orchestrator at `src/methods/calibration.py` will pass `deriver=derive_calib_coefs` so the controller stays decoupled from the dimensional layer (its only job here is composition).

        Args:
            envelope (Dict[str, Any]): host envelope produced by `run_host_sweep`; the deriver reads `handler_scaling` + `loopback` from it.
            deriver (Optional[Callable]): function accepting `(envelope, payload_size_bytes, K_values)` and returning the dimensional-card dict. When None, raises.

        Returns:
            Dict[str, Any]: the input envelope with a `dimensional_card` key attached.

        Raises:
            NotImplementedError: when `deriver` is None (Stage C8 not yet wired).
        """
        if deriver is None:
            _msg = ("run_dasa_sweep deferred until Stage C8 wires "
                    "src/dimensional/dasaprof.derive_calib_coefs")
            raise NotImplementedError(_msg)
        envelope["dimensional_card"] = deriver(
            envelope,
            payload_size_bytes=self.host_grid.payload_size_bytes,
            K_values=list(self.dasa_grid.K),
        )
        return envelope

    def write(self, envelope: Dict[str, Any]) -> str:
        """*write()* persist the envelope under `data/results/calibration/<dpl>/<host>_<ts>.json`.

        Delegates to `src.calibration.envelope.write_envelope`; mutates the envelope by stamping `dpl` and `output_path`.

        Args:
            envelope (Dict[str, Any]): in-memory envelope produced by `run_host_sweep` (and optionally `run_dasa_sweep`).

        Returns:
            str: resolved path the envelope was written to.
        """
        _path = write_envelope(envelope, self.dpl)
        return str(_path)

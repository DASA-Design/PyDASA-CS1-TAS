"""Target-config builder for unittests.

`make_target_cfg(**overrides)` returns a dict shaped like `data/config/method/prototype/target.json` with sensible test defaults. Tests pass it via `run_experiment(target_cfg=...)` so the on-disk file is not read during test runs.
"""

from __future__ import annotations

from typing import Any

DEFAULT_WORKFLOWS: dict[str, str] = {
    "collapsed": "tas",
    "expanded": "tas_expanded",
}

DEFAULT_STAGE_ROUTES: dict[str, dict[str, str]] = {
    "TAS_{2}": {
        "calls_kind": "medical_analysis",
        "operation": "analyseData",
    },
    "TAS_{3}": {
        "calls_kind": "alarm",
        "operation": "triggerAlarm",
    },
    "TAS_{4}": {
        "calls_kind": "alarm",
        "operation": "sendAlarm",
    },
    "TAS_{5}": {
        "calls_kind": "drug",
        "operation": "changeDrug",
    },
    "TAS_{6}": {
        "calls_kind": "drug",
        "operation": "changeDose",
    },
}

DEFAULT_STRATEGIES: dict[str, Any] = {
    "max_attempts": 3,
    "window_size": 100,
}

DEFAULT_CONTROLLER: dict[str, Any] = {
    "port": 19001,
    "ready_timeout_s": 5.0,
    "poll_interval_ms": 50,
    "warmup_n": 10,
    "r1_r2_stop_enabled": True,
    "orchestrator_poll_every_n": 5,
    "samples_buffer_size": 1024,
}


def make_target_cfg(*,
                    catalogue_version: str = "weyns_2015",
                    workflows: dict[str, str] | None = None,
                    target_granularity: str = "collapsed",
                    inject_internal_stage_mu: bool = False,
                    stage_routes: dict[str, dict[str, str]] | None = None,
                    tas_base_port: int = 18001,
                    host: str = "127.0.0.1",
                    ready_timeout_s: float = 5.0,
                    request_timeout_s: float = 1.0,
                    atomic_admission: dict[str, Any] | None = None,
                    trial: dict[str, Any] | None = None,
                    strategies: dict[str, Any] | None = None,
                    controller: dict[str, Any] | None = None) -> dict[str, Any]:
    """Build a target-config dict shaped like the on-disk `target.json`.

    Args:
        catalogue_version (str, optional): catalogue version layer. Defaults to `weyns_2015`.
        workflows (dict[str, str] | None, optional): mode -> workflow stem map. Defaults to `{"collapsed": "tas", "expanded": "tas_expanded"}`.
        target_granularity (str, optional): `collapsed` or `expanded`. Defaults to `collapsed`.
        inject_internal_stage_mu (bool, optional): whether `TAS_{2..6}` sleep on mu. Defaults to False.
        stage_routes (dict | None, optional): per-stage `calls_kind` + `operation` map. Defaults to the standard TAS_{2..6} mapping.
        tas_base_port (int, optional): first TCP port. Defaults to 18001 (test-band).
        host (str, optional): bind address. Defaults to 127.0.0.1.
        ready_timeout_s (float, optional): per-spawner readiness timeout. Defaults to 5 s.
        request_timeout_s (float, optional): per-dispatch HTTP timeout. Defaults to 1 s.
        atomic_admission (dict[str, Any] | None, optional): admission caps. Defaults to unbounded.
        trial (dict[str, Any] | None, optional): trial-block overrides. Defaults to a minimal 3-request schedule.

    Returns:
        dict[str, Any]: target-config dict with the same key shape as the on-disk JSON.
    """
    if atomic_admission is None:
        _admission = {"k": None, "c": None}
    else:
        _admission = atomic_admission
    if trial is None:
        _trial: dict[str, Any] = {
            "n_requests": 3,
            "request_rate_per_s": 0,
            "kind_probability": {"alarm": 0.5, "medical_analysis": 0.5},
        }
    else:
        _trial = trial
    if workflows is None:
        _workflows = dict(DEFAULT_WORKFLOWS)
    else:
        _workflows = workflows
    if stage_routes is None:
        _stage_routes: dict[str, Any] = {_k: dict(_v) for _k, _v in DEFAULT_STAGE_ROUTES.items()}
    else:
        _stage_routes = stage_routes
    if strategies is None:
        _strategies = dict(DEFAULT_STRATEGIES)
    else:
        _strategies = strategies
    if controller is None:
        _controller = dict(DEFAULT_CONTROLLER)
    else:
        _controller = controller
    _ans = {
        "catalogue_version": catalogue_version,
        "workflows": _workflows,
        "target_granularity": target_granularity,
        "inject_internal_stage_mu": inject_internal_stage_mu,
        "stage_routes": _stage_routes,
        "tas_base_port": tas_base_port,
        "host": host,
        "ready_timeout_s": ready_timeout_s,
        "request_timeout_s": request_timeout_s,
        "atomic_admission": _admission,
        "trial": _trial,
        "strategies": _strategies,
        "controller": _controller,
    }
    return _ans


__all__ = [
    "DEFAULT_CONTROLLER",
    "DEFAULT_STAGE_ROUTES",
    "DEFAULT_STRATEGIES",
    "DEFAULT_WORKFLOWS",
    "make_target_cfg",
]

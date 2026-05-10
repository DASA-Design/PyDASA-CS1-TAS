"""Target-config builder for unittests.

`make_target_cfg(**overrides)` returns a dict shaped like `data/config/method/prototype/target.json` with sensible test defaults. Tests pass it via `run_experiment(target_cfg=...)` so the on-disk file is not read during test runs.
"""

from __future__ import annotations

from typing import Any


def make_target_cfg(*,
                    catalogue_version: str = "weyns_2015",
                    workflow_name: str = "tas",
                    tas_base_port: int = 18001,
                    host: str = "127.0.0.1",
                    ready_timeout_s: float = 5.0,
                    request_timeout_s: float = 1.0,
                    atomic_admission: dict[str, Any] | None = None,
                    trial: dict[str, Any] | None = None) -> dict[str, Any]:
    """Build a target-config dict shaped like the on-disk `target.json`.

    Args:
        catalogue_version (str, optional): catalogue version layer. Defaults to `weyns_2015`.
        workflow_name (str, optional): workflow stem. Defaults to `tas`.
        tas_base_port (int, optional): first TCP port. Defaults to 18001 (test-band so it does not clash with the experiment-time 8001 default).
        host (str, optional): bind address. Defaults to 127.0.0.1.
        ready_timeout_s (float, optional): per-spawner readiness timeout. Defaults to 5 s (tighter than the experiment-time 20 s).
        request_timeout_s (float, optional): per-dispatch HTTP timeout. Defaults to 1 s.
        atomic_admission (dict[str, Any] | None, optional): admission caps. Defaults to `{"k": None, "c": None}` (unbounded).
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
    _ans = {
        "catalogue_version": catalogue_version,
        "workflow_name": workflow_name,
        "tas_base_port": tas_base_port,
        "host": host,
        "ready_timeout_s": ready_timeout_s,
        "request_timeout_s": request_timeout_s,
        "atomic_admission": _admission,
        "trial": _trial,
    }
    return _ans


__all__ = [
    "make_target_cfg",
]

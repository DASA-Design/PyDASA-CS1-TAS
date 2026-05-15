"""Loader for `data/config/method/prototype/controller.json`.

Reads the MAPE-K controller knobs (port, poll cadence, R1/R2 early-stop gate, sample-buffer size) plus the per-strategy picker knobs (max_attempts, window_size). The JSON is the source of truth; `src/methods/experimental.py::run_experiment` calls this loader at trial start and threads the resolved values into the controller bootstrap.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

DFLT_CONTROLLER_CFG_PATH = (
    Path("data") / "config" / "method" / "prototype" / "controller.json"
)


def load_controller_cfg(path: Path = DFLT_CONTROLLER_CFG_PATH) -> dict[str, Any]:
    """Load the controller-config JSON from disk.

    Args:
        path (Path, optional): config-file path. Defaults to `data/config/method/prototype/controller.json`.

    Returns:
        dict[str, Any]: parsed JSON with controller knobs at top level (`port`, `ready_timeout_s`, `poll_interval_ms`, `warmup_n`, `r1_r2_stop_enabled`, `orchestrator_poll_every_n`, `samples_buffer_size`) plus a nested `strategies` block (`max_attempts`, `window_size`).
    """
    _text = path.read_text(encoding="utf-8")
    _cfg = json.loads(_text)
    return _cfg


__all__ = ["DFLT_CONTROLLER_CFG_PATH", "load_controller_cfg"]

"""Loader for the calibration JSON config (`data/config/method/prototype/calibration.json`)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

DFLT_CALIBRATION_CFG_PATH = (
    Path("data") / "config" / "method" / "prototype" / "calibration.json"
)


def load_calibration_cfg(path: Path = DFLT_CALIBRATION_CFG_PATH) -> dict[str, Any]:
    """Load the calibration-config JSON from disk.

    Args:
        path (Path, optional): config-file path. Defaults to `data/config/method/prototype/calibration.json`.

    Returns:
        dict[str, Any]: parsed JSON. Top-level keys: `hoststats` (per-probe sub-blocks `timer` / `jitter` / `loopback` / `handler_scaling`), `rate`, `gate`.
    """
    _text = path.read_text(encoding="utf-8")
    _cfg = json.loads(_text)
    return _cfg

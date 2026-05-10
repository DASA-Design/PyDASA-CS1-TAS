"""Loader for the target-system config JSON.

Reads the raw dict; the orchestrator pulls `catalogue_version`, `workflows`, `tas_base_port`, `host`, admission caps, and the `trial` block.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

DFLT_TGT_CFG_DIR = Path("data/config/method/prototype")
DFLT_TGT_CFG_FILE = "target.json"


def load_target_cfg(path: Path | None = None) -> dict[str, Any]:
    """Load the target-system config JSON.

    Args:
        path (Path | None, optional): override file path. Defaults to `DFLT_TGT_CFG_DIR / DFLT_TGT_CFG_FILE`.

    Returns:
        dict[str, Any]: parsed config.

    Raises:
        FileNotFoundError: if the file does not exist.
    """
    if path is None:
        _path = DFLT_TGT_CFG_DIR / DFLT_TGT_CFG_FILE
    else:
        _path = path
    if not _path.exists():
        _msg = f"target config not found: {_path}"
        raise FileNotFoundError(_msg)
    with _path.open(encoding="utf-8") as _fh:
        _ans: dict[str, Any] = json.load(_fh)
    return _ans


__all__ = [
    "DFLT_TGT_CFG_DIR",
    "DFLT_TGT_CFG_FILE",
    "load_target_cfg",
]

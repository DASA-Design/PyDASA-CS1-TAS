"""Loader for `data/config/method/experimental.json`.

Reads the orchestrator-level run knobs: seed, framework, server tuning per spawner, dpl, run_label, and the `trial` block (n_requests, request_rate_per_s, consumer_pool_size, kind_probability, drain_timeout_s, atomic_response_time_overrides). The JSON is the source of truth; each spawner also keeps `_DFLT_*` constants as fallbacks for callers that skip the loader.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

DFLT_EXP_CFG_PATH = (
    Path("data") / "config" / "method" / "experimental.json"
)


def load_experimental_cfg(path: Path = DFLT_EXP_CFG_PATH) -> dict[str, Any]:
    """Load the orchestrator-level experimental-config JSON from disk.

    Args:
        path (Path, optional): config-file path. Defaults to `data/config/method/experimental.json`.

    Returns:
        dict[str, Any]: parsed JSON. Top-level keys: `seed`, `framework`, `server`, `dpl`, `run_label`. The `server` sub-dict carries `wsgi_server` plus per-spawner blocks `uvicorn`, `waitress`, `gunicorn`.
    """
    _text = path.read_text(encoding="utf-8")
    _cfg = json.loads(_text)
    return _cfg


def load_server_cfg(name: str,
                    path: Path = DFLT_EXP_CFG_PATH) -> dict[str, Any]:
    """Return the runtime sub-block for one spawner.

    Args:
        name (str): one of `"uvicorn"`, `"waitress"`, `"gunicorn"`.
        path (Path, optional): config-file path. Defaults to `data/config/method/experimental.json`.

    Returns:
        dict[str, Any]: the matching sub-block (e.g. `{"backlog": 16384, "ready_timeout_s": 10.0, ...}`).

    Raises:
        KeyError: if `name` is not present under `server`.
    """
    _cfg = load_experimental_cfg(path)
    _block: dict[str, Any] = _cfg["server"][name]
    return _block

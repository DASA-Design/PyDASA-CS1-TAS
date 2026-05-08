"""Loader for `data/config/method/prototype/client.json`.

The orchestrator (`src/methods/experimental.py`, stage 9) calls `load_client_cfg()` once at run start and threads the resolved values into `User`, `Sender`, `StopGuard`, and `Stats` constructors. Stage 2 keeps small fallback constants in each module (so callers that bypass the loader still get sensible behaviour), but the JSON file is the source of truth from stage 9 onward.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

DFLT_CLIENT_CFG_PATH = (
    Path("data") / "config" / "method" / "prototype" / "client.json"
)


def load_client_cfg(path: Path = DFLT_CLIENT_CFG_PATH) -> dict[str, Any]:
    """Load the client-config JSON from disk.

    Args:
        path (Path, optional): config-file path. Defaults to `data/config/method/prototype/client.json`.

    Returns:
        dict[str, Any]: parsed JSON. Top-level keys: `users`, `ramp`, `sender`, `guard`, `stats` (plus a `_note` field that callers ignore).
    """
    _text = path.read_text(encoding="utf-8")
    _cfg = json.loads(_text)
    return _cfg

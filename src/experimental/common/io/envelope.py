"""Read and write the calibration envelope JSON.

Each calibration run writes one **envelope** file under
`data/results/calibration/<dpl>/` containing the host-floor probe outputs
(timer, jitter, loopback, handler-scaling) and the pre-run gate verdict.
This module owns both ends of that file: `write_envelope` serialises the
envelope dict to disk; `read_envelope` loads it back. Keeping the two
functions next to each other in one module means schema changes need only
one edit.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def write_envelope(path: Path, envelope: dict[str, Any]) -> None:
    """Serialise an envelope dict to disk as pretty-printed JSON.

    Args:
        path (Path): destination path; parent directories are created if missing.
        envelope (dict[str, Any]): envelope dict (host_profile, timer, jitter, loopback, ...).
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as _fh:
        json.dump(envelope, _fh, indent=2, sort_keys=True)


def read_envelope(path: Path) -> dict[str, Any]:
    """Load an envelope from disk.

    Args:
        path (Path): existing JSON file.

    Returns:
        dict[str, Any]: the deserialised envelope dict.
    """
    with path.open("r", encoding="utf-8") as _fh:
        _envelope = json.load(_fh)
    return _envelope

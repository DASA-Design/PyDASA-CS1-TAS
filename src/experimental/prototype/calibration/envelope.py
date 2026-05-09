"""Per-dpl envelope JSON serde for calibration runs.

The envelope is one top-level dict carrying everything a calibration run produced: run metadata, the four host-floor probe blocks (timer / jitter / loopback / handler scaling), the rate-saturation block, and the gate verdict. The 00-calibration notebook reads it back to render figures and decide whether the apparatus is fit to host an experiment.

Disk layout: `data/results/calibration/<dpl>/<host>_<run_id>.json`. Pretty-printed JSON with sorted keys (the underlying `common/io/envelope.py` writer handles formatting).
"""

from __future__ import annotations

import socket
import time
from pathlib import Path
from typing import Any

from src.experimental.common.io.envelope import read_envelope, write_envelope

DFLT_RESULTS_BASE = Path("data") / "results" / "calibration"
ENVELOPE_VER = "1.0"

# Probe + verdict block names; each module fills its own.
PROBE_SECTIONS = (
    "timer",
    "jitter",
    "loopback",
    "handler_scaling",
    "rate",
    "gate"
)


def make_envelope(*,
                  run_id: str,
                  dpl: str,
                  framework: str,
                  host: str | None = None,
                  wsgi_server: str | None = None) -> dict[str, Any]:
    """Build the empty envelope skeleton with run metadata filled in.

    Each probe block (`timer`, `jitter`, `loopback`, `handler_scaling`, `rate`, `gate`) starts as an empty dict; the calibration modules populate them in turn. `started_ts` is stamped now; `finished_ts` stays `None` until the run closes.

    Args:
        run_id (str): unique run identifier (typically from `common.io.runs.make_run_id`).
        dpl (str): deployment mode — `"localhost"` / `"multiprocess"` / `"remote"`.
        framework (str): `"fastapi"` or `"flask"`.
        host (str | None, optional): host identifier. Defaults to None, which uses `socket.gethostname()`.
        wsgi_server (str | None, optional): WSGI engine name when `framework="flask"`. Defaults to None.

    Returns:
        dict[str, Any]: the envelope skeleton, ready for probe modules to populate.
    """
    if host is None:
        _host = socket.gethostname()
    else:
        _host = host
    _ans: dict[str, Any] = {
        "version": ENVELOPE_VER,
        "run_id": run_id,
        "host": _host,
        "dpl": dpl,
        "framework": framework,
        "wsgi_server": wsgi_server,
        "started_ts": time.time(),
        "finished_ts": None,
    }
    for _section in PROBE_SECTIONS:
        _ans[_section] = {}
    return _ans


def envelope_path(dpl: str,
                  host: str,
                  run_id: str,
                  base: Path = DFLT_RESULTS_BASE) -> Path:
    """Resolve the on-disk path for one envelope.

    Layout: `<base>/<dpl>/<host>_<run_id>.json`. Parent directory is created lazily by `write_envelope`; this function does not touch the filesystem.

    Args:
        dpl (str): deployment mode.
        host (str): host identifier (matches the envelope's `host` field).
        run_id (str): the run identifier used in the envelope.
        base (Path, optional): results-tree base. Defaults to `data/results/calibration/`.

    Returns:
        Path: absolute or repo-relative path the writer should target.
    """
    return base / dpl / f"{host}_{run_id}.json"


__all__ = [
    "DFLT_RESULTS_BASE",
    "ENVELOPE_VER",
    "PROBE_SECTIONS",
    "envelope_path",
    "make_envelope",
    "read_envelope",
    "write_envelope",
]

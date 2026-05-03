# -*- coding: utf-8 -*-
"""
Module calibration/envelope.py
==============================

Per-`dpl` JSON I/O for calibration envelopes. Resolves output paths under `data/results/calibration/<dpl>/<host>_<YYYYMMDD_HHMMSS>.json` so localhost and multiprocess calibrations cannot accidentally overwrite each other; reads back the newest envelope for the current host so the experiment gate can verify a recent calibration exists.

Path shape (locked decision Q-B in `notes/calibration.md`): the previous `data/results/experiment/calibration/` location was sub-namespaced under the experiment method's results tree, which conflicts with the layering rule that calibration is a precondition gate, not an experiment output. The new shape sits at the same level as `data/results/experiment/` and `data/results/analytic/`.

Public API:
    - `output_path(dpl, host, stamp)`: build the per-dpl path without writing.
    - `write_envelope(envelope, dpl, host, stamp)`: write the envelope and stamp `output_path` onto it; returns the resolved path.
    - `find_latest(dpl, host)`: newest envelope for `(dpl, host)`, or None.
    - `load_latest(dpl, host)`: parsed envelope with `output_path` attached, or None.
"""
# native python modules
from __future__ import annotations

import json
import socket
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional


_HERE = Path(__file__).resolve()
_ROOT = _HERE.parents[2]
_CALIB_ROOT = _ROOT / "data" / "results" / "calibration"

_VALID_DPL = ("localhost", "multiprocess")


def _normalise_host(host: Optional[str]) -> str:
    """*_normalise_host()* return `host` (or `socket.gethostname()` when None) with spaces replaced by hyphens.

    Calibration JSONs land at `<host>_<stamp>.json` and Windows hostnames may contain spaces; the prefix glob in `find_latest` matches on `<normalised_host>_` so the writer and reader must agree on the normalisation rule.

    Args:
        host (Optional[str]): hostname; defaults to `socket.gethostname()`.

    Returns:
        str: hostname with spaces replaced by hyphens.
    """
    if host is None:
        _h = socket.gethostname()
    else:
        _h = str(host)
    return _h.replace(" ", "-")


def _validate_dpl(dpl: str) -> None:
    """*_validate_dpl()* raise `ValueError` when `dpl` is not in `_VALID_DPL`.

    Args:
        dpl (str): deployment-axis value to validate.

    Raises:
        ValueError: when `dpl` is not one of `_VALID_DPL`.
    """
    if dpl not in _VALID_DPL:
        _msg = f"dpl={dpl!r} not recognised; valid: {_VALID_DPL}"
        raise ValueError(_msg)


def output_path(dpl: str,
                host: Optional[str] = None,
                stamp: Optional[str] = None) -> Path:
    """*output_path()* build the per-`dpl` calibration JSON path without creating any file.

    Path shape: `data/results/calibration/<dpl>/<host>_<YYYYMMDD_HHMMSS>.json`. The parent directory is NOT created here; `write_envelope` creates it on demand.

    Args:
        dpl (str): deployment-axis value; one of `"localhost"`, `"multiprocess"`.
        host (Optional[str]): hostname; defaults to `socket.gethostname()` (with spaces normalised to hyphens).
        stamp (Optional[str]): timestamp string; defaults to `datetime.now().strftime("%Y%m%d_%H%M%S")`.

    Returns:
        Path: resolved per-dpl path.

    Raises:
        ValueError: when `dpl` is not recognised.
    """
    _validate_dpl(dpl)
    _host_norm = _normalise_host(host)
    if stamp is None:
        _stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    else:
        _stamp = str(stamp)
    return _CALIB_ROOT / dpl / f"{_host_norm}_{_stamp}.json"


def write_envelope(envelope: Dict[str, Any],
                   dpl: str,
                   host: Optional[str] = None,
                   stamp: Optional[str] = None) -> Path:
    """*write_envelope()* serialise the envelope to disk under the per-`dpl` path and stamp the resolved path onto the envelope as `output_path`.

    Mutates `envelope` in place by adding `dpl` and `output_path` keys. Creates the per-dpl directory if absent. Writes via temp file + atomic rename so a crashed write does not leave a half-written JSON in the directory the gate scans.

    Args:
        envelope (Dict[str, Any]): in-memory calibration envelope; the `dpl` key is added (or overwritten) so loaders can confirm the file's intended deployment without reparsing the path.
        dpl (str): deployment-axis value; one of `"localhost"`, `"multiprocess"`.
        host (Optional[str]): hostname; defaults to `socket.gethostname()`.
        stamp (Optional[str]): timestamp string; defaults to `datetime.now().strftime("%Y%m%d_%H%M%S")`.

    Returns:
        Path: resolved path the envelope was written to.

    Raises:
        ValueError: when `dpl` is not recognised.
        OSError: on filesystem failure during directory creation, write, or rename.
    """
    _validate_dpl(dpl)
    _path = output_path(dpl, host=host, stamp=stamp)
    _path.parent.mkdir(parents=True, exist_ok=True)
    envelope["dpl"] = dpl
    envelope["output_path"] = str(_path)
    _tmp = _path.with_suffix(_path.suffix + ".tmp")
    with _tmp.open("w", encoding="utf-8") as _fh:
        json.dump(envelope, _fh, indent=2, default=str)
    _tmp.replace(_path)
    return _path


def find_latest(dpl: str,
                host: Optional[str] = None) -> Optional[Path]:
    """*find_latest()* return the newest envelope path for `(dpl, host)`, or None when none exists.

    Sorts matching files by modification time (the writer renames the temp atomically so mtime tracks completion). Returns None when the per-dpl directory is absent or no file matches the host prefix.

    Args:
        dpl (str): deployment-axis value; one of `"localhost"`, `"multiprocess"`.
        host (Optional[str]): hostname prefix to match; defaults to `socket.gethostname()`.

    Returns:
        Optional[Path]: newest matching path, or None when no file matches.

    Raises:
        ValueError: when `dpl` is not recognised.
    """
    _validate_dpl(dpl)
    _dir = _CALIB_ROOT / dpl
    if not _dir.exists():
        return None
    _host_norm = _normalise_host(host)
    _prefix = f"{_host_norm}_"
    _candidates: List[Path] = []
    for _p in _dir.glob("*.json"):
        if _p.name.startswith(_prefix):
            _candidates.append(_p)
    if not _candidates:
        return None
    _candidates.sort(key=lambda _x: _x.stat().st_mtime)
    return _candidates[-1]


def load_latest(dpl: str,
                host: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """*load_latest()* parse and return the newest envelope for `(dpl, host)`, or None.

    Stamps the resolved file path onto the parsed dict as `output_path` so downstream consumers (the experiment gate, the dim-card derivation) record provenance without re-running the lookup.

    Args:
        dpl (str): deployment-axis value; one of `"localhost"`, `"multiprocess"`.
        host (Optional[str]): hostname prefix; defaults to `socket.gethostname()`.

    Returns:
        Optional[Dict[str, Any]]: parsed envelope with `output_path` attached, or None when no file exists.

    Raises:
        ValueError: when `dpl` is not recognised.
        json.JSONDecodeError: when the file resolved fine but its contents do not parse.
        OSError: on filesystem failure while opening the resolved path.
    """
    _path = find_latest(dpl, host=host)
    if _path is None:
        return None
    with _path.open(encoding="utf-8") as _fh:
        _env = json.load(_fh)
    _env["output_path"] = str(_path)
    return _env

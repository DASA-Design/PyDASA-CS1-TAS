"""Run-id generator + run-folder layout helpers.

Every experimental run has a stable id (`<UTC-ts>_<short-hash>`) that ties together the calibration envelope, per-request flow JSONL, per-service CSV logs, run summary parquet entry, and process logs.

The `RunPaths` dataclass resolves all paths in one place so refactors only touch this module.
"""

from __future__ import annotations

import secrets
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

DFLT_RESULTS_BASE = Path("data/results")


def make_run_id(prefix: str = "") -> str:
    """Build a unique run id of the form `<UTC-ts>_<short-hash>`.

    Args:
        prefix (str): optional label prepended (e.g. `s1`, `aggregate`); separated by `__`. Defaults to empty.

    Returns:
        str: run-id string. Same call yields different output (uses a fresh secret-token nonce).
    """
    _ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    _nonce = secrets.token_hex(4)
    _rid = f"{_ts}_{_nonce}"
    if prefix:
        _rid = f"{prefix}__{_rid}"
    return _rid


@dataclass(frozen=True)
class RunPaths:
    """All filesystem paths for one experimental run.

    Attributes:
        run_id (str): the run identifier.
        adp (str): adaptation key (`baseline` / `s1` / `s2` / `aggregate`).
        root (Path): `data/results/experimental/<adp>/`.
        flows (Path): per-request flow JSONL file path.
        csv_dir (Path): directory holding per-service per-pid CSV logs.
        runs_parquet (Path): cross-run summary parquet path (one row per run).
        adaptation_reqs (Path): R1 + R2 verdict JSON path.
        logs_dir (Path): per-process Python-logging output directory.
    """

    run_id: str
    adp: str
    root: Path
    flows: Path
    csv_dir: Path
    runs_parquet: Path
    adaptation_reqs: Path
    logs_dir: Path

    def ensure(self) -> None:
        """Create every directory that holds a per-run artefact."""
        self.root.mkdir(parents=True, exist_ok=True)
        self.flows.parent.mkdir(parents=True, exist_ok=True)
        self.csv_dir.mkdir(parents=True, exist_ok=True)
        self.logs_dir.mkdir(parents=True, exist_ok=True)


def make_run_paths(adp: str, run_id: str, base: Path = DFLT_RESULTS_BASE) -> RunPaths:
    """Resolve every path used by one experimental run.

    Args:
        adp (str): adaptation key.
        run_id (str): run identifier (from `make_run_id`).
        base (Path, optional): results base. Defaults to `DFLT_RESULTS_BASE`.

    Returns:
        RunPaths: populated paths bundle. Caller must invoke `.ensure()` before writing.
    """
    _root = base / "experimental" / adp
    _paths = RunPaths(
        run_id=run_id,
        adp=adp,
        root=_root,
        flows=_root / "flows" / f"{run_id}.jsonl",
        csv_dir=_root / "csv",
        runs_parquet=_root / "runs.parquet",
        adaptation_reqs=_root / "adaptation-reqs.json",
        logs_dir=_root / "logs" / run_id,
    )
    return _paths

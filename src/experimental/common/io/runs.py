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
    """Build a unique run id of the form `<UTC-ts>_<short-hash>`, optionally prefixed.

    Args:
        prefix (str): optional label prepended (e.g. `s1`, `aggregate`); separated by `_`. Defaults to empty.

    Returns:
        str: run-id string. Same call yields different output (uses a fresh secret-token nonce).
    """
    _ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    _nonce = secrets.token_hex(4)
    _rid = f"{_ts}_{_nonce}"
    if prefix:
        _rid = f"{prefix}_{_rid}"
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
        verdict_json (Path): post-trial verdict (R1 / R2 + operational variables + stop reason). Bit-comparable across `adp` runs.
        window_parquet (Path): per-sample trajectory drained from the controller's `/history`. Inputs for stage-7+ R1 / R2 trajectory plots.
        logs_dir (Path): per-process Python-logging output directory.
    """

    run_id: str
    adp: str
    root: Path
    flows: Path
    csv_dir: Path
    runs_parquet: Path
    verdict_json: Path
    window_parquet: Path
    logs_dir: Path

    def ensure(self) -> None:
        """Create every directory that holds a per-run artefact."""
        self.root.mkdir(parents=True, exist_ok=True)
        self.flows.parent.mkdir(parents=True, exist_ok=True)
        self.csv_dir.mkdir(parents=True, exist_ok=True)
        self.window_parquet.parent.mkdir(parents=True, exist_ok=True)
        self.logs_dir.mkdir(parents=True, exist_ok=True)


def make_run_paths(adp: str,
                   run_id: str,
                   base: Path = DFLT_RESULTS_BASE,
                   variant_suffix: str | None = None) -> RunPaths:
    """Resolve every path used by one experimental run.

    Args:
        adp (str): adaptation key.
        run_id (str): run identifier (from `make_run_id`).
        base (Path, optional): results base. Defaults to `DFLT_RESULTS_BASE`.
        variant_suffix (str | None, optional): variant-axis tag appended to the adp folder via a `_` separator (e.g. `fastapi_expanded`). When set, the run lands under `data/results/experimental/<adp>_<variant_suffix>/`. None keeps the canonical headline path. Defaults to None.

    Returns:
        RunPaths: populated paths bundle. Caller must invoke `.ensure()` before writing.
    """
    if variant_suffix is None:
        _folder = adp
    else:
        _folder = f"{adp}_{variant_suffix}"
    _root = base / "experimental" / _folder
    _paths = RunPaths(
        run_id=run_id,
        adp=adp,
        root=_root,
        flows=_root / "flows" / f"{run_id}.jsonl",
        csv_dir=_root / "csv",
        runs_parquet=_root / "runs.parquet",
        verdict_json=_root / "verdict.json",
        window_parquet=_root / "window" / f"{run_id}.parquet",
        logs_dir=_root / "logs" / run_id,
    )
    return _paths

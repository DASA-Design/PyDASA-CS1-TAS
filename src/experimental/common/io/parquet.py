"""Append and read the cross-run summary parquet table.

The orchestrator writes one row per experimental run to a shared
`runs.parquet` (R1 and R2 verdicts plus summary stats), which the analysis
notebook then loads as a single DataFrame. `append_run_summary` is a
read-modify-write: it loads the existing parquet (if any), appends the new
row, and rewrites the file. This is not atomic across concurrent writers,
but the orchestrator serialises runs at one level above this module, so
collisions cannot occur in practice. `read_runs_parquet` is the matching
loader used by notebooks and verdict analysis.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pandas as pd


def append_run_summary(path: Path, row: dict[str, Any]) -> None:
    """Append one run-summary row to a parquet file.

    Reads the existing parquet (if any), appends the row, writes the result back.

    Args:
        path (Path): target parquet path; parent directories are created if missing.
        row (dict[str, Any]): dict whose keys become DataFrame columns.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    _new = pd.DataFrame([row])
    if path.exists():
        _existing = pd.read_parquet(path)
        _df = pd.concat([_existing, _new], ignore_index=True)
    else:
        _df = _new
    _df.to_parquet(path, index=False)


def read_runs_parquet(path: Path) -> pd.DataFrame:
    """Load `runs.parquet` as a DataFrame.

    Args:
        path (Path): existing parquet file.

    Returns:
        pd.DataFrame: one row per run.
    """
    _df = pd.read_parquet(path)
    return _df

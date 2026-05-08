"""Tests for `src.experimental.common.io.parquet`.

**TestParquet**:

- `test_append_creates_file`: confirms the first append writes a one-row parquet so the cross-run summary table starts populated as soon as the orchestrator finishes one run.
- `test_append_extends_existing`: confirms a second append produces two rows so subsequent runs accumulate into the same `runs.parquet`.
- `test_read_returns_dataframe`: confirms the reader returns a pandas `DataFrame` so notebook code can use it directly without a conversion step.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from src.experimental.common.io.parquet import append_run_summary, read_runs_parquet


class TestParquet:
    """Per-run summary parquet writer and reader."""

    def test_append_creates_file(self, tmp_path: Path) -> None:
        """The first call to `append_run_summary` against a non-existent path produces a parquet file with exactly one row, so the cross-run table begins existing as soon as the first run lands.

        Args:
            tmp_path (Path): pytest's per-test temporary directory.
        """
        _path = tmp_path / "runs.parquet"
        append_run_summary(_path, {"run_id": "r1", "r1_pass": True})
        _df = read_runs_parquet(_path)
        assert len(_df) == 1
        assert _df.iloc[0]["run_id"] == "r1"

    def test_append_extends_existing(self, tmp_path: Path) -> None:
        """A second `append_run_summary` against the same path read-modifies-writes to produce two rows, so successive runs accumulate into one cross-run table the analysis notebook can load whole.

        Args:
            tmp_path (Path): pytest's per-test temporary directory.
        """
        _path = tmp_path / "runs.parquet"
        append_run_summary(_path, {"run_id": "r1", "r1_pass": True})
        append_run_summary(_path, {"run_id": "r2", "r1_pass": False})
        _df = read_runs_parquet(_path)
        assert sorted(_df["run_id"].tolist()) == ["r1", "r2"]

    def test_read_returns_dataframe(self, tmp_path: Path) -> None:
        """`read_runs_parquet` returns a pandas `DataFrame` (not a list or dict), so notebook code can chain `.query` / `.groupby` / plot calls without an explicit conversion step.

        Args:
            tmp_path (Path): pytest's per-test temporary directory.
        """
        _path = tmp_path / "runs.parquet"
        append_run_summary(_path, {"run_id": "r1"})
        _df = read_runs_parquet(_path)
        assert isinstance(_df, pd.DataFrame)

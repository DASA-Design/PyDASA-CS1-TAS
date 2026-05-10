"""Tests for `src.experimental.common.io.runs`.

**TestRuns**:

- `test_run_id_unique`: confirms the run-id generator is non-repeating across consecutive calls so each run gets a stable, unique handle.
- `test_run_id_prefix`: confirms a non-empty prefix is preserved verbatim with a single `_` separator (so adaptation labels survive into filenames).
- `test_run_paths_layout`: confirms every path in `RunPaths` resolves under `<base>/experimental/<adp>/...` and matches the canonical filenames the orchestrator expects.
- `test_run_paths_ensure_creates_dirs`: confirms `RunPaths.ensure()` materialises the flow, csv, and logs directories so subsequent writers find them in place.
"""

from __future__ import annotations

from pathlib import Path

from src.experimental.common.io.runs import (
    RunPaths,
    make_run_id,
    make_run_paths,
)


class TestRuns:
    """Run-id generator and `RunPaths` layout helpers."""

    def test_run_id_unique(self) -> None:
        """Two successive `make_run_id()` calls return distinct strings; the secret-token nonce guarantees the second draw differs from the first."""
        _a = make_run_id()
        _b = make_run_id()
        assert _a != _b

    def test_run_id_prefix(self) -> None:
        """A non-empty prefix is prepended verbatim with a single `_` separator, so adaptation labels (`s1`, `aggregate`, ...) appear at the start of the run id."""
        _rid = make_run_id("s1")
        assert _rid.startswith("s1_")
        # Ensure no double underscore (legacy format) leaks back in.
        assert not _rid.startswith("s1__")

    def test_run_paths_layout(self, tmp_path: Path) -> None:
        """`make_run_paths` resolves the canonical run-folder layout: every path lands under `<base>/experimental/<adp>/...` with the expected filenames for flows, csv, parquet, requirements, and logs.

        Args:
            tmp_path (Path): pytest's per-test temporary directory used as the layout `base`.
        """
        _paths = make_run_paths("baseline", "rid123", base=tmp_path)
        assert _paths.root == tmp_path / "experimental" / "baseline"
        assert _paths.flows == _paths.root / "flows" / "rid123.jsonl"
        assert _paths.csv_dir == _paths.root / "csv"
        assert _paths.runs_parquet == _paths.root / "runs.parquet"
        assert _paths.adaptation_reqs == _paths.root / "adaptation-reqs.json"
        assert _paths.logs_dir == _paths.root / "logs" / "rid123"
        assert isinstance(_paths, RunPaths)

    def test_run_paths_ensure_creates_dirs(self, tmp_path: Path) -> None:
        """`RunPaths.ensure()` creates the flow-parent, csv, and logs directories so writers can open files immediately without their own `mkdir` calls.

        Args:
            tmp_path (Path): pytest's per-test temporary directory used as the layout `base`.
        """
        _paths = make_run_paths("s1", "rid456", base=tmp_path)
        _paths.ensure()
        assert _paths.flows.parent.is_dir()
        assert _paths.csv_dir.is_dir()
        assert _paths.logs_dir.is_dir()

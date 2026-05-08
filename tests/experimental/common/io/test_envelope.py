"""Tests for `src.experimental.common.io.envelope`.

**TestEnvelope**:

- `test_round_trip`: confirms `write_envelope` then `read_envelope` returns the same dict so calibration data survives the disk hop.
- `test_creates_parent_dirs`: confirms the writer creates missing parent directories so callers do not need to `mkdir` ahead of time.
- `test_read_missing_raises`: confirms a missing file raises `FileNotFoundError` so callers can handle the absence as a normal error rather than getting a confusing decode failure.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from src.experimental.common.io.envelope import read_envelope, write_envelope


class TestEnvelope:
    """Apparatus envelope JSON serde."""

    def test_round_trip(self,
                        tmp_path: Path,
                        sample_envelope: dict[str, Any]) -> None:
        """Writing the envelope to disk and reading it back reproduces the original dict, demonstrating the JSON encoder and decoder agree on the schema.

        Args:
            tmp_path (Path): pytest's per-test temporary directory.
            sample_envelope (dict[str, Any]): canonical envelope from conftest.
        """
        _path = tmp_path / "env.json"
        write_envelope(_path, sample_envelope)
        assert read_envelope(_path) == sample_envelope

    def test_creates_parent_dirs(self,
                                 tmp_path: Path,
                                 sample_envelope: dict[str, Any]) -> None:
        """A path with non-existent intermediate directories writes successfully because the writer calls `mkdir(parents=True)` before opening the file.

        Args:
            tmp_path (Path): pytest's per-test temporary directory.
            sample_envelope (dict[str, Any]): canonical envelope from conftest.
        """
        _path = tmp_path / "deep" / "nested" / "env.json"
        write_envelope(_path, sample_envelope)
        assert _path.exists()

    def test_read_missing_raises(self, tmp_path: Path) -> None:
        """Opening a non-existent envelope path surfaces `FileNotFoundError` rather than a misleading JSON-decode error, so callers see a clear failure mode.

        Args:
            tmp_path (Path): pytest's per-test temporary directory.
        """
        with pytest.raises(FileNotFoundError):
            read_envelope(tmp_path / "missing.json")

"""Tests for `src.experimental.common.io.csv`.

**TestCsvWriter**:

- `test_header_on_first_open`: confirms a new file gets a header line so any reader can self-describe its columns.
- `test_no_duplicate_header_on_reopen`: confirms reopening an existing file appends without a second header line so multi-process workers can share one CSV.
- `test_write_row_round_trip`: confirms a written row's content is recoverable from the file so downstream loaders see the exact values written.
- `test_unknown_column_raises`: confirms an extra key triggers `ValueError` so schema drift is caught at write time rather than producing a silently malformed file.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from src.experimental.common.io.csv import CsvWriter


class TestCsvWriter:
    """Append-only CSV writer with fixed schema."""

    def test_header_on_first_open(
        self,
        tmp_path: Path,
        sample_csv_columns: list[str],
        sample_csv_row: dict[str, Any],
    ) -> None:
        """Opening a non-existent file writes the comma-joined column list as the first line, so a reader can recover the schema by inspecting line 1 alone.

        Args:
            tmp_path (Path): pytest's per-test temporary directory.
            sample_csv_columns (list[str]): canonical CSV column schema from conftest.
            sample_csv_row (dict[str, Any]): canonical CSV row from conftest, written once.
        """
        _path = tmp_path / "svc.csv"
        with CsvWriter(_path, sample_csv_columns) as _w:
            _w.write_row(sample_csv_row)
        _lines = _path.read_text(encoding="utf-8").splitlines()
        assert _lines[0] == ",".join(sample_csv_columns)

    def test_no_duplicate_header_on_reopen(
        self,
        tmp_path: Path,
        sample_csv_columns: list[str],
        sample_csv_row: dict[str, Any],
    ) -> None:
        """Opening an existing file appends data rows without writing a second header, so multi-process workers writing to the same per-service CSV produce one well-formed table.

        Args:
            tmp_path (Path): pytest's per-test temporary directory.
            sample_csv_columns (list[str]): canonical CSV column schema from conftest.
            sample_csv_row (dict[str, Any]): canonical CSV row from conftest, written twice across two reopens.
        """
        _path = tmp_path / "svc.csv"
        with CsvWriter(_path, sample_csv_columns) as _w:
            _w.write_row(sample_csv_row)
        with CsvWriter(_path, sample_csv_columns) as _w:
            _w.write_row(sample_csv_row)
        _lines = _path.read_text(encoding="utf-8").splitlines()
        assert len(_lines) == 3
        assert _lines.count(",".join(sample_csv_columns)) == 1

    def test_write_row_round_trip(
        self,
        tmp_path: Path,
        sample_csv_columns: list[str],
        sample_csv_row: dict[str, Any],
    ) -> None:
        """A written row's `req_id` and integer field appear verbatim in the file, demonstrating the writer preserves both string and numeric values without surprising coercion.

        Args:
            tmp_path (Path): pytest's per-test temporary directory.
            sample_csv_columns (list[str]): canonical CSV column schema from conftest.
            sample_csv_row (dict[str, Any]): canonical CSV row from conftest.
        """
        _path = tmp_path / "svc.csv"
        with CsvWriter(_path, sample_csv_columns) as _w:
            _w.write_row(sample_csv_row)
        _content = _path.read_text(encoding="utf-8")
        assert sample_csv_row["req_id"] in _content
        assert str(sample_csv_row["c_used_at_start"]) in _content

    def test_unknown_column_raises(
        self,
        tmp_path: Path,
        sample_csv_columns: list[str],
        sample_csv_row: dict[str, Any],
    ) -> None:
        """A row containing a key not declared in `columns` raises `ValueError`, surfacing schema drift at write time so the file never receives a malformed row.

        Args:
            tmp_path (Path): pytest's per-test temporary directory.
            sample_csv_columns (list[str]): canonical CSV column schema from conftest.
            sample_csv_row (dict[str, Any]): canonical CSV row from conftest, augmented with an extra key to trigger the rejection.
        """
        _path = tmp_path / "svc.csv"
        _bad_row = {**sample_csv_row, "z_unknown": 99}
        with CsvWriter(_path, sample_csv_columns) as _w, pytest.raises(ValueError, match="unknown CSV columns"):
            _w.write_row(_bad_row)

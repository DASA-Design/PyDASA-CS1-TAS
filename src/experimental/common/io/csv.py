"""CSV writer for per-service per-pid invocation logs.

One row per invocation seen from one service's perspective; one file per (service, pid) pair. Columns are fixed at construction so the loader can merge files of the same shape.
"""

from __future__ import annotations

import csv
from pathlib import Path
from types import TracebackType
from typing import Any, Self


class CsvWriter:
    """Append-only CSV writer with a fixed column schema.

    Attributes:
        _path (Path): destination file.
        _columns (list[str]): column names; written as header on first open.
        _fh (TextIO): open append-mode handle, flushed on every write.
        _writer (csv.DictWriter): underlying csv writer wired to `_columns`.
    """

    def __init__(self, path: Path, columns: list[str]) -> None:
        """Open the destination file in append mode and write the header if new.

        Args:
            path (Path): target file. Parent directories are created if missing.
            columns (list[str]): column names; written as header line on first open.
        """
        path.parent.mkdir(parents=True, exist_ok=True)
        _is_new = not path.exists()
        self._path = path
        self._columns = list(columns)
        self._fh = path.open("a", newline="", encoding="utf-8")
        self._writer = csv.DictWriter(self._fh, fieldnames=self._columns)
        if _is_new:
            self._writer.writeheader()
            self._fh.flush()

    def write_row(self, row: dict[str, Any]) -> None:
        """Append one row.

        Args:
            row (dict[str, Any]): dict whose keys are a subset of the configured `columns`. Missing keys are written as empty fields; extra keys raise.

        Raises:
            ValueError: if `row` contains a key not declared in `columns`.
        """
        _extra = set(row) - set(self._columns)
        if _extra:
            _msg = f"unknown CSV columns: {sorted(_extra)} not in {self._columns}"
            raise ValueError(_msg)
        self._writer.writerow(row)
        self._fh.flush()

    def close(self) -> None:
        """Flush and close the file handle. Idempotent: safe to call twice."""
        if not self._fh.closed:
            self._fh.flush()
            self._fh.close()

    def __enter__(self) -> Self:
        """Enter the context manager.

        Returns:
            Self: this writer, ready to receive `write_row()` calls.
        """
        return self

    def __exit__(self,
                 _exc_type: type[BaseException] | None,
                 _exc: BaseException | None,
                 _tb: TracebackType | None,) -> None:
        """Exit the context manager: flush + close, propagating any exception."""
        self.close()

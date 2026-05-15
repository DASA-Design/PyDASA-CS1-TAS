"""CSV writer for per-service per-pid invocation logs.

One row per invocation seen from one service's perspective; one file per
(service, pid) pair. Columns are fixed at construction so the loader can
merge files of the same shape. The writer is append-only and flushes on
every row.

Per-row flush is deliberate. On Windows the apparatus tears atomic workers
down with `TerminateProcess` - an uncatchable hard kill that runs no atexit
hook, no signal handler, no `finally`. Any in-memory batch buffer dies with
the worker. Each atomic handles only a few dozen requests per trial (well
under any sane batch threshold), so a buffered writer would lose the entire
per-atomic CSV. Profiling (2026-05-15) confirmed the per-row write is not a
throughput bottleneck; the binding cost is the HTTP roundtrip.
"""

from __future__ import annotations

import csv
from pathlib import Path
from types import TracebackType
from typing import Any, Self


class CsvWriter:
    """Append-only CSV writer with a fixed column schema; flushes every row.

    Attributes:
        _path (Path): destination file.
        _columns (list[str]): column names; written as header on first open of a new file.
        _fh (TextIO): open append-mode handle, flushed on every write.
        _writer (csv.DictWriter): underlying csv writer wired to `_columns`.
    """

    def __init__(self, path: Path, columns: list[str]) -> None:
        """Open the destination file in append mode and write the header if new.

        The per-pid CSV is single-writer (one file per (service, pid) pair), so
        writing the header eagerly on a new file carries no multi-header risk
        and guarantees the file is never a zero-byte artifact `pd.read_csv`
        cannot parse.

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
        """Append one row and flush immediately.

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
        """Exit the context manager: flush + close, propagating any exception.

        Args:
            _exc_type (type[BaseException] | None): exception type if raised in the block, else None.
            _exc (BaseException | None): exception instance if raised in the block, else None.
            _tb (TracebackType | None): traceback if raised in the block, else None.
        """
        self.close()

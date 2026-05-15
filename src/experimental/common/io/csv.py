"""CSV writer for per-service per-pid invocation logs (batched, periodic flush).

One row per invocation seen from one service's perspective; one file per
(service, pid) pair. Columns are fixed at construction so the loader can
merge files of the same shape.

Rows buffer in RAM and dump to disk every `_BATCH_SIZE` rows (and on
`close()`). The periodic flush bounds data loss on abrupt worker
termination - the apparatus calls `Process.terminate()` on workers without
running Python's atexit hooks, so a writer that only flushes on `close()`
loses every row from the last batch when workers are killed at trial end.
"""

from __future__ import annotations

import csv
import io
from pathlib import Path
from types import TracebackType
from typing import Any, Self

_BATCH_SIZE = 100


class CsvWriter:
    """Append-only CSV writer with a fixed column schema; batches writes, flushes every `_BATCH_SIZE` rows.

    Attributes:
        _path (Path): destination file.
        _columns (list[str]): column names; written as header on first flush of a new file.
        _fh (TextIO): open append-mode handle.
        _batch (list[dict[str, Any]]): in-memory rows awaiting flush.
        _header_written (bool): True once the header line has been emitted on disk.
    """

    def __init__(self, path: Path, columns: list[str]) -> None:
        """Open the destination file in append mode; defer the header to first flush of a new file.

        Args:
            path (Path): target file. Parent directories are created if missing.
            columns (list[str]): column names; written as header line on first flush of a new file.
        """
        path.parent.mkdir(parents=True, exist_ok=True)
        self._path = path
        self._columns = list(columns)
        self._header_written = path.exists()
        self._fh = path.open("a", newline="", encoding="utf-8")
        self._batch: list[dict[str, Any]] = []

    def write_row(self, row: dict[str, Any]) -> None:
        """Buffer one row; flush the batch every `_BATCH_SIZE` calls.

        Args:
            row (dict[str, Any]): dict whose keys are a subset of the configured `columns`. Missing keys are written as empty fields; extra keys raise.

        Raises:
            ValueError: if `row` contains a key not declared in `columns`.
        """
        _extra = set(row) - set(self._columns)
        if _extra:
            _msg = f"unknown CSV columns: {sorted(_extra)} not in {self._columns}"
            raise ValueError(_msg)
        self._batch.append(row)
        if len(self._batch) >= _BATCH_SIZE:
            self._flush_batch()

    def _flush_batch(self) -> None:
        """Append the in-memory batch to the file in one I/O call; clear the buffer."""
        if not self._batch:
            return
        _buf = io.StringIO()
        _writer = csv.DictWriter(_buf, fieldnames=self._columns)
        if not self._header_written:
            _writer.writeheader()
            self._header_written = True
        for _row in self._batch:
            _writer.writerow(_row)
        self._fh.write(_buf.getvalue())
        self._fh.flush()
        self._batch.clear()

    def close(self) -> None:
        """Drain any buffered rows, then flush and close the file handle. Idempotent."""
        if self._fh.closed:
            return
        self._flush_batch()
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
        """Exit the context manager: drain + flush + close, propagating any exception.

        Args:
            _exc_type (type[BaseException] | None): exception type if raised in the block, else None.
            _exc (BaseException | None): exception instance if raised in the block, else None.
            _tb (TracebackType | None): traceback if raised in the block, else None.
        """
        self.close()

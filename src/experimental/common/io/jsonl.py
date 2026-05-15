"""JSONL writer for per-request flow records (batched, with periodic flush).

One line per end-to-end request, newline-separated. Streamable, grep-able,
schema-flexible.

Records buffer in RAM and dump to disk every `_BATCH_SIZE` records (and on
`close()`). The periodic flush bounds data loss on abrupt worker
termination - the apparatus calls `Process.terminate()` on workers without
running Python's atexit hooks, so a writer that only flushes on `close()`
loses every record from the last batch when workers are killed at trial end.

`_BATCH_SIZE = 100` balances throughput (each fsync amortised over 100
records) against durability (at most 100 records lost on abrupt teardown,
typically a fraction of one second of trial output).
"""

from __future__ import annotations

import json
from pathlib import Path
from types import TracebackType
from typing import Any, Self

_BATCH_SIZE = 100


class JsonlWriter:
    """Append-only JSONL writer; batches writes, flushes every `_BATCH_SIZE` records.

    Attributes:
        _path (Path): destination file.
        _fh (TextIO): open append-mode handle.
        _batch (list[str]): in-memory buffer of serialised JSON lines awaiting flush.
    """

    def __init__(self, path: Path) -> None:
        """Open the destination file in append mode, creating parent dirs.

        Args:
            path (Path): target file. Parent directories are created if missing.
        """
        path.parent.mkdir(parents=True, exist_ok=True)
        self._path = path
        self._fh = path.open("a", encoding="utf-8")
        self._batch: list[str] = []

    def write(self, record: dict[str, Any]) -> None:
        """Serialise one record and buffer it; flush the batch every `_BATCH_SIZE` calls.

        Args:
            record (dict[str, Any]): any JSON-serialisable dict.
        """
        self._batch.append(json.dumps(record, separators=(",", ":")))
        if len(self._batch) >= _BATCH_SIZE:
            self._flush_batch()

    def _flush_batch(self) -> None:
        """Append the in-memory batch to the open file in one I/O call; clear the buffer."""
        if not self._batch:
            return
        self._fh.write("\n".join(self._batch))
        self._fh.write("\n")
        self._fh.flush()
        self._batch.clear()

    def close(self) -> None:
        """Drain any buffered records, then flush and close the file handle. Idempotent."""
        if self._fh.closed:
            return
        self._flush_batch()
        self._fh.close()

    def __enter__(self) -> Self:
        """Enter the context manager.

        Returns:
            Self: this writer, ready to receive `write()` calls.
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

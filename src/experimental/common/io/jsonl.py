"""JSONL writer for per-request flow records.

One line per end-to-end request, newline-separated. Streamable, grep-able,
schema-flexible. The writer is append-only and flushes on every record.

Per-record flush is deliberate, not a missed optimisation. On Windows the
apparatus tears workers down with `TerminateProcess` (a hard kill that runs
no atexit hook, no signal handler, no `finally` block), so any in-memory
batch buffer is lost when the worker dies at trial end. The per-pid atomic
CSVs and the composite flow JSONL must therefore reach disk synchronously.
Profiling (2026-05-15) confirmed the per-record write is not a throughput
bottleneck - the binding cost is the composite-to-atomic HTTP roundtrip.
"""

from __future__ import annotations

from pathlib import Path
from types import TracebackType
from typing import Any, Self

import orjson


class JsonlWriter:
    """Append-only JSONL writer for per-request flow records.

    Attributes:
        _path (Path): destination file.
        _fh (TextIO): open append-mode handle, flushed on every write and closed by `close()` or context-manager exit.
    """

    def __init__(self, path: Path) -> None:
        """Open the destination file in append mode, creating parent dirs.

        Args:
            path (Path): target file. Parent directories are created if missing.
        """
        path.parent.mkdir(parents=True, exist_ok=True)
        self._path = path
        self._fh = path.open("a", encoding="utf-8")

    def write(self, record: dict[str, Any]) -> None:
        """Serialise one record with orjson and append it as a line; flush immediately.

        Args:
            record (dict[str, Any]): any JSON-serialisable dict.
        """
        # orjson.dumps returns bytes; decode to str for the text-mode handle.
        # ~4-8x faster than stdlib json.dumps for small dicts.
        self._fh.write(orjson.dumps(record).decode("utf-8"))
        self._fh.write("\n")
        self._fh.flush()

    def close(self) -> None:
        """Flush and close the file handle. Idempotent: safe to call twice."""
        if not self._fh.closed:
            self._fh.flush()
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
        """Exit the context manager: flush + close, propagating any exception.

        Args:
            _exc_type (type[BaseException] | None): exception type if raised in the block, else None.
            _exc (BaseException | None): exception instance if raised in the block, else None.
            _tb (TracebackType | None): traceback if raised in the block, else None.
        """
        self.close()

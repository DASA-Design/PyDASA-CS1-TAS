"""JSONL writer for per-request flow records.

One line per end-to-end request, newline-separated. Streamable, grep-able, schema-flexible. The writer is append-only and flushes on every record so a crashing process leaves complete prefix data on disk.
"""

from __future__ import annotations

import json
from pathlib import Path
from types import TracebackType
from typing import Any, Self


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
        """Serialise one record and append it as a line.

        Args:
            record (dict[str, Any]): any JSON-serialisable dict.
        """
        _line = json.dumps(record, separators=(",", ":"))
        self._fh.write(_line)
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
        """Exit the context manager: flush + close, propagating any exception."""
        self.close()

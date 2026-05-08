"""Static checks that the experimental layout's import rules hold.

The rules:

- `common/` is acyclic: it imports nothing from `procedure/` or `prototype/`.
- `common/transport/` (the in-memory test transport) is imported only from `tests/`; production code under `src/` never references it.

**TestImportBarriers**:

- `test_common_acyclic`: confirms `common/` has no imports from `procedure/` or `prototype/` so the dependency graph stays a DAG with `common/` at the bottom.
- `test_transport_tests_only`: confirms production code under `src/` does not import `common.transport`, preventing the OLD build's anti-pattern of using the in-memory transport for measurement runs.
"""

from __future__ import annotations

import re
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
COMMON_DIR = PROJECT_ROOT / "src" / "experimental" / "common"
SRC_DIR = PROJECT_ROOT / "src"
TRANSPORT_PKG = SRC_DIR / "experimental" / "common" / "transport"

FORBIDDEN_PROC_PROTO = re.compile(
    r"\b(?:from|import)\s+src\.experimental\.(?:procedure|prototype)\b",
)
FORBIDDEN_TRANSPORT_IMPORT = re.compile(
    r"\b(?:from|import)\s+src\.experimental\.common\.transport\b",
)


def _python_files(root: Path) -> list[Path]:
    """Return every `.py` file under `root`, skipping bytecode caches.

    Args:
        root (Path): directory to walk recursively.

    Returns:
        list[Path]: list of source-file paths (no `__pycache__` entries).
    """
    _files: list[Path] = []
    for _path in root.rglob("*.py"):
        if "__pycache__" in _path.parts:
            continue
        _files.append(_path)
    return _files


class TestImportBarriers:
    """Static checks that the layout's import rules hold."""

    def test_common_acyclic(self) -> None:
        """Every `.py` file under `common/` is scanned for imports from `procedure/` or `prototype/`; the test fails if any forbidden import is found, keeping the dependency graph a DAG with `common/` as a leaf."""
        _hits: list[str] = []
        for _path in _python_files(COMMON_DIR):
            _text = _path.read_text(encoding="utf-8")
            for _i, _line in enumerate(_text.splitlines(), start=1):
                if FORBIDDEN_PROC_PROTO.search(_line):
                    _hits.append(f"{_path}:{_i}: {_line.strip()}")
        assert _hits == [], f"common/ must be acyclic: forbidden imports found: {_hits}"

    def test_transport_tests_only(self) -> None:
        """Every `.py` file under `src/` (excluding the `common/transport/` package's own modules) is scanned for any import of `src.experimental.common.transport`; the test fails if production code references the in-memory test transport, preventing the OLD build's apparatus-as-MockTransport anti-pattern from creeping back."""
        _hits: list[str] = []
        for _path in _python_files(SRC_DIR):
            if TRANSPORT_PKG in _path.parents or _path == TRANSPORT_PKG:
                continue
            _text = _path.read_text(encoding="utf-8")
            for _i, _line in enumerate(_text.splitlines(), start=1):
                if FORBIDDEN_TRANSPORT_IMPORT.search(_line):
                    _hits.append(f"{_path}:{_i}: {_line.strip()}")
        assert _hits == [], (
            "common/transport/ may only be imported from tests/; "
            f"forbidden imports found in src/: {_hits}"
        )

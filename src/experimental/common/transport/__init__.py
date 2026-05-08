"""In-memory HTTP transport for tests ONLY.

Production runs (notebooks, methods, calibration sweeps) use real TCP. The mock transport here exists so pytest can route `httpx` calls into a test-mounted ASGI/WSGI app without spawning OS processes.

**Import barrier (enforced at every stage stop-gate):** this subpackage is imported only from `tests/`. Never from `src/experimental/prototype/`, `src/experimental/procedure/`, or `src/methods/`.
"""

from src.experimental.common.transport.mock import make_test_transport

__all__ = ["make_test_transport"]

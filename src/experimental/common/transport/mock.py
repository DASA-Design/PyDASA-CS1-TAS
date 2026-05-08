"""In-memory httpx transport factory for FastAPI or Flask test clients.

- **WHY THIS EXISTS.** Production runs use real TCP; pytest cannot spawn one OS process per service per test. `make_test_transport(app, framework)` wraps a FastAPI or Flask app in the matching `httpx` transport so requests dispatch in-process.
- **TESTS-ONLY BARRIER.** Imported only from `tests/`; never from production paths. Enforced by `tests/experimental/test_import_barriers.py::test_transport_tests_only`.
- **TYPING.** Overloaded: `"fastapi"` returns `httpx.AsyncBaseTransport` (pair with `AsyncClient`); `"flask"` returns `httpx.BaseTransport` (pair with `Client`).
"""

from __future__ import annotations

from typing import Any, Literal, overload

import httpx

Framework = Literal["fastapi", "flask"]


@overload
def make_test_transport(
    app: Any,
    framework: Literal["fastapi"]) -> httpx.AsyncBaseTransport: ...

@overload
def make_test_transport(
    app: Any,
    framework: Literal["flask"]) -> httpx.BaseTransport: ...

def make_test_transport(
    app: Any,
    framework: Framework,
) -> httpx.AsyncBaseTransport | httpx.BaseTransport:
    """Return the in-memory httpx transport for the given app + framework.

    Args:
        app (Any): an ASGI callable (FastAPI app) or a WSGI callable (Flask app).
        framework (Framework): one of `"fastapi"` (ASGI) or `"flask"` (WSGI).

    Returns:
        httpx.AsyncBaseTransport | httpx.BaseTransport: an `ASGITransport` (FastAPI) for use with `httpx.AsyncClient`, or a `WSGITransport` (Flask) for use with `httpx.Client`.

    Raises:
        ValueError: if `framework` is neither `"fastapi"` nor `"flask"`.
    """
    if framework == "fastapi":
        _asgi = httpx.ASGITransport(app=app)
        return _asgi
    if framework == "flask":
        _wsgi = httpx.WSGITransport(app=app)
        return _wsgi
    _msg = f"unknown framework {framework!r}; expected 'fastapi' or 'flask'"
    raise ValueError(_msg)

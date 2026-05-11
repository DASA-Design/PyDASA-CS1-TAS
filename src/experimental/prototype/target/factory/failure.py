"""Per-request failure dispatcher used by the atomic and composite route adapters.

The route honours the request payload's `inject_failure` flag (`timeout` / `drop` / `5xx` / None); the client RNG sets the flag per the catalogue's `failure_mechanism_mix`.

- `timeout`: server sleeps `timeout_grace_s` (default 30 s, past the client's 5 s timeout). Client records `Outcome="timeout"`.
- `drop`: server streams a partial JSON body, then the generator raises; uvicorn aborts the connection and httpx surfaces a `RemoteProtocolError` mapped to `Outcome="drop"`.
- `5xx`: server returns HTTP 502 immediately. Client records `Outcome="5xx"`.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator
from typing import Any

from fastapi.responses import JSONResponse, StreamingResponse
from starlette.responses import Response

from src.experimental.common.payload.request import FailureMechanism

DFLT_TIMEOUT_GRACE_S = 30.0
_DROP_MARKER = "synthetic drop mid-stream"


def _is_synthetic_drop(exc: BaseException | None) -> bool:
    """Walk an exception (including `BaseExceptionGroup` sub-exceptions and `__cause__` / `__context__` links) and return True when any leaf is the synthetic drop `RuntimeError`.

    Args:
        exc (BaseException | None): root exception from the log record's `exc_info`.

    Returns:
        bool: True when the synthetic-drop marker appears anywhere in the tree.
    """
    if exc is None:
        return False
    if isinstance(exc, RuntimeError) and _DROP_MARKER in str(exc):
        return True
    if isinstance(exc, BaseExceptionGroup):
        for _sub in exc.exceptions:
            if _is_synthetic_drop(_sub):
                return True
    if exc.__cause__ is not None and _is_synthetic_drop(exc.__cause__):
        return True
    if exc.__context__ is not None and _is_synthetic_drop(exc.__context__):
        return True
    return False


class _SyntheticDropFilter(logging.Filter):
    """Logging filter that suppresses uvicorn-error records caused by the synthetic-drop abort.

    Drops are the expected mechanism for `inject_failure="drop"`: the response generator raises a `RuntimeError` mid-stream so uvicorn closes the TCP connection (the client sees `RemoteProtocolError`). Without this filter, every drop produces a noisy traceback on stderr that has no diagnostic value.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        """Return False to drop the record when its `exc_info` traces back to the synthetic drop.

        Args:
            record (logging.LogRecord): the log record uvicorn emitted.

        Returns:
            bool: True to keep, False to drop.
        """
        if record.exc_info is None:
            return True
        _exc = record.exc_info[1]
        _ans = not _is_synthetic_drop(_exc)
        return _ans


_FILTER_INSTALLED = False


def _install_synthetic_drop_filter() -> None:
    """Attach `_SyntheticDropFilter` to the `uvicorn.error` logger once per process."""
    global _FILTER_INSTALLED
    if _FILTER_INSTALLED:
        return
    logging.getLogger("uvicorn.error").addFilter(_SyntheticDropFilter())
    _FILTER_INSTALLED = True


_install_synthetic_drop_filter()


async def timeout_request(grace_s: float = DFLT_TIMEOUT_GRACE_S) -> None:
    """Sleep `grace_s` seconds so the client times out.

    Args:
        grace_s (float, optional): sleep duration. Defaults to `DFLT_TIMEOUT_GRACE_S`.
    """
    await asyncio.sleep(grace_s)


async def _aborted_body() -> AsyncIterator[bytes]:
    """Yield a partial JSON body and raise so uvicorn closes the connection mid-response.

    Yields:
        bytes: one chunk of partial JSON before the abort.

    Raises:
        RuntimeError: always; uvicorn aborts the response, surfacing as `httpx.RemoteProtocolError` on the client.
    """
    yield b'{"error": "synthetic_drop", "partial":'
    _msg = "synthetic drop mid-stream"
    raise RuntimeError(_msg)


def drop_request() -> Response:
    """Return a streaming response that aborts mid-body so the client sees a transport-level drop.

    Returns:
        Response: streaming response with content-type `application/json`. The first chunk lands; the second chunk raises and uvicorn closes the TCP connection without finishing the body. The client maps the resulting `RemoteProtocolError` to `Outcome="drop"`.
    """
    return StreamingResponse(_aborted_body(), media_type="application/json")


def fivexx_request() -> JSONResponse:
    """Return an HTTP 502 response.

    Returns:
        JSONResponse: status 502 with a planted error body.
    """
    return JSONResponse(content={"error": "synthetic_5xx"}, status_code=502)


async def apply_inject_failure(payload: dict[str, Any],
                               *,
                               timeout_grace_s: float = DFLT_TIMEOUT_GRACE_S) -> Response | None:
    """Inspect `payload['inject_failure']`; trigger the matching mechanism when set.

    Args:
        payload (dict[str, Any]): inbound request body.
        timeout_grace_s (float, optional): sleep duration for the `timeout` mechanism. Defaults to `DFLT_TIMEOUT_GRACE_S`.

    Returns:
        Response | None: 502 response for `5xx`, mid-body abort for `drop`, None for `timeout` (after sleeping) or when the flag is absent.

    Raises:
        ValueError: when the flag is set but not in `{"timeout", "drop", "5xx"}`.
    """
    _flag_raw = payload.get("inject_failure")
    _ans: Response | None = None
    if _flag_raw is not None:
        _flag: FailureMechanism = _flag_raw
        if _flag == "timeout":
            await timeout_request(timeout_grace_s)
        elif _flag == "drop":
            _ans = drop_request()
        elif _flag == "5xx":
            _ans = fivexx_request()
        else:
            _msg = (f"unknown inject_failure flag {_flag_raw!r}; "
                    "expected None, 'timeout', 'drop', or '5xx'")
            raise ValueError(_msg)
    return _ans


__all__ = [
    "DFLT_TIMEOUT_GRACE_S",
    "apply_inject_failure",
    "drop_request",
    "fivexx_request",
    "timeout_request",
]

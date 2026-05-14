"""Per-request failure dispatcher used by the atomic and composite route adapters.

The route honours the request payload's `inject_failure` flag (`timeout` / `drop` / `5xx` / None); the client RNG sets the flag per the catalogue's `failure_mechanism_mix`. **All three mechanisms return immediately at the server** -- none holds the HTTP handler beyond normal processing time -- so the apparatus's observed throughput is bounded by the queueing model under study, not by the failure simulation itself.

- `timeout`: server returns HTTP 504 (Gateway Timeout) immediately. The client maps status 504 -> `Outcome="timeout"` in `sender._dispatch`. Models an upstream-timeout failure mode (RFC 7231 504 = "didn't receive a timely response from an upstream server") rather than a hung-server scenario; observably identical at the response-measure level (failed request, classified as timeout) and removes the consumer-block tax that a sleep-based simulation imposes.
- `drop`: server streams a partial JSON body, then the generator raises; uvicorn aborts the connection and httpx surfaces a `RemoteProtocolError` mapped to `Outcome="drop"`.
- `5xx`: server returns HTTP 502 immediately. Client records `Outcome="5xx"`.
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from typing import Any

from fastapi.responses import JSONResponse, StreamingResponse
from starlette.responses import Response

from src.experimental.common.payload.request import FailureMechanism

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


def timeout_request() -> JSONResponse:
    """Return an HTTP 504 (Gateway Timeout) response immediately.

    No sleep, no connection hold: the client receives a 504 status in one roundtrip and maps it to `Outcome="timeout"` via `sender._dispatch`. Older versions of this function slept `timeout_grace_s` to simulate a hung server and force `httpx.TimeoutException` on the client; that approach taxed every timeout-failure request with the client's `request_timeout_s` of consumer-block wait, capping apparatus throughput below the queueing model's prediction.

    Returns:
        JSONResponse: status 504 with a planted error body. The body is informational; the client classifies by status code, not body.
    """
    return JSONResponse(content={"error": "synthetic_timeout"}, status_code=504)


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


async def apply_inject_failure(payload: dict[str, Any]) -> Response | None:
    """Inspect `payload['inject_failure']`; return the matching mechanism's response when set.

    All three mechanisms return immediately at the server: 504 for `timeout`, mid-body abort for `drop`, 502 for `5xx`. None of them sleeps. The client distinguishes outcomes by inspecting the response (or the exception type httpx raises): 504 -> "timeout", `RemoteProtocolError` -> "drop", other 5xx -> "5xx".

    Args:
        payload (dict[str, Any]): inbound request body.

    Returns:
        Response | None: planted failure response when the flag is set; None when the flag is absent and the route should fall through to the normal handler.

    Raises:
        ValueError: when the flag is set but not in `{"timeout", "drop", "5xx"}`.
    """
    _flag_raw = payload.get("inject_failure")
    _ans: Response | None = None
    if _flag_raw is not None:
        _flag: FailureMechanism = _flag_raw
        if _flag == "timeout":
            _ans = timeout_request()
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
    "apply_inject_failure",
    "drop_request",
    "fivexx_request",
    "timeout_request",
]

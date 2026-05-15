"""Tests for `src.experimental.prototype.target.factory.failure`.

**TestApplyInjectFailure**:

- `test_none`: a payload without `inject_failure` returns None.
- `test_5xx`: a `'5xx'` flag returns a `JSONResponse` with status 502.
- `test_drop_streams`: a `'drop'` flag returns a streaming response whose body raises mid-iteration.
- `test_timeout`: a `'timeout'` flag returns a `JSONResponse` with status 504 immediately.
- `test_unknown_flag`: an unknown flag raises `ValueError`.

**TestSyntheticDropFilter**:

- `test_drops_synthetic`: a log record with the synthetic-drop `RuntimeError` is suppressed.
- `test_drops_nested_excgroup`: a record whose `exc_info` contains a `BaseExceptionGroup` wrapping the synthetic drop is suppressed.
- `test_keeps_unrelated`: a record with an unrelated `RuntimeError` survives.
- `test_keeps_no_exc_info`: a record with no `exc_info` (regular log line) survives.
"""

from __future__ import annotations

import logging

import pytest
from starlette.responses import StreamingResponse

from src.experimental.prototype.target.factory.failure import (
    _SyntheticDropFilter,
    apply_inject_failure,
)


class TestApplyInjectFailure:
    """`apply_inject_failure` flag-driven dispatch."""

    @pytest.mark.asyncio
    async def test_none(self) -> None:
        """*test_none()* a payload with no `inject_failure` returns None so the route continues to the handler."""
        _ans = await apply_inject_failure({})
        assert _ans is None

    @pytest.mark.asyncio
    async def test_5xx(self) -> None:
        """*test_5xx()* a `'5xx'` flag returns a `JSONResponse` with status 502."""
        _ans = await apply_inject_failure({"inject_failure": "5xx"})
        assert _ans is not None
        assert _ans.status_code == 502

    @pytest.mark.asyncio
    async def test_drop_streams(self) -> None:
        """*test_drop_streams()* a `'drop'` flag returns a `StreamingResponse` whose body iterator raises after one chunk so uvicorn aborts the response."""
        _ans = await apply_inject_failure({"inject_failure": "drop"})
        assert isinstance(_ans, StreamingResponse)
        _iter = aiter(_ans.body_iterator)  # type: ignore[arg-type]
        _first = await anext(_iter)
        # Starlette types body chunks as `str | bytes`; normalise so the `in` check is well-typed.
        if isinstance(_first, str):
            _first = _first.encode()
        assert b"synthetic_drop" in _first
        with pytest.raises(RuntimeError, match="synthetic drop"):
            await anext(_iter)

    @pytest.mark.asyncio
    async def test_timeout(self,
                           monkeypatch: pytest.MonkeyPatch) -> None:
        """*test_timeout()* a `'timeout'` flag returns a `JSONResponse` with status 504 after the shared `FAILURE_RETURN_DELAY_S`."""
        monkeypatch.setattr("src.experimental.prototype.target.factory.failure.FAILURE_RETURN_DELAY_S",
                            0.0)
        _ans = await apply_inject_failure({"inject_failure": "timeout"})
        assert _ans is not None
        assert _ans.status_code == 504

    @pytest.mark.asyncio
    async def test_unknown_flag(self) -> None:
        """*test_unknown_flag()* an unknown flag raises `ValueError`."""
        with pytest.raises(ValueError):
            await apply_inject_failure({"inject_failure": "weird"})


def _record_with_exc(exc: BaseException) -> logging.LogRecord:
    """Build a log record with `exc_info` set to `exc`.

    Args:
        exc (BaseException): the exception to attach.

    Returns:
        logging.LogRecord: record with `exc_info=(type, exc, tb)`.
    """
    _exc_info = (type(exc), exc, exc.__traceback__)
    return logging.LogRecord(
        name="uvicorn.error",
        level=logging.ERROR,
        pathname=__file__,
        lineno=0,
        msg="Exception in ASGI application",
        args=(),
        exc_info=_exc_info,
    )


class TestSyntheticDropFilter:
    """`_SyntheticDropFilter` recognises the synthetic-drop marker in exception trees."""

    def test_drops_synthetic(self) -> None:
        """*test_drops_synthetic()* a record carrying the synthetic-drop `RuntimeError` is filtered out."""
        _filter = _SyntheticDropFilter()
        _rec = _record_with_exc(RuntimeError("synthetic drop mid-stream"))
        assert _filter.filter(_rec) is False

    def test_drops_nested_excgroup(self) -> None:
        """*test_drops_nested_excgroup()* a `BaseExceptionGroup` wrapping the synthetic drop is filtered out."""
        _filter = _SyntheticDropFilter()
        _inner = RuntimeError("synthetic drop mid-stream")
        _group = BaseExceptionGroup("unhandled errors in a TaskGroup", [_inner])
        _rec = _record_with_exc(_group)
        assert _filter.filter(_rec) is False

    def test_keeps_unrelated(self) -> None:
        """*test_keeps_unrelated()* a record with an unrelated `RuntimeError` survives."""
        _filter = _SyntheticDropFilter()
        _rec = _record_with_exc(RuntimeError("totally different problem"))
        assert _filter.filter(_rec) is True

    def test_keeps_no_exc_info(self) -> None:
        """*test_keeps_no_exc_info()* a record with no exception info survives (regular log line)."""
        _filter = _SyntheticDropFilter()
        _rec = logging.LogRecord(
            name="uvicorn.error",
            level=logging.INFO,
            pathname=__file__,
            lineno=0,
            msg="just a normal log line",
            args=(),
            exc_info=None,
        )
        assert _filter.filter(_rec) is True

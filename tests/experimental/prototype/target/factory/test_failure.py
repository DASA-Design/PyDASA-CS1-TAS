"""Tests for `src.experimental.prototype.target.factory.failure`.

**TestApplyInjectFailure**:

- `test_none`: a payload without `inject_failure` returns None.
- `test_5xx`: a `'5xx'` flag returns a `JSONResponse` with status 502.
- `test_drop_streams`: a `'drop'` flag returns a streaming response whose body raises mid-iteration.
- `test_timeout`: a `'timeout'` flag sleeps for `timeout_grace_s`.
- `test_unknown_flag`: an unknown flag raises `ValueError`.
"""

from __future__ import annotations

import pytest
from starlette.responses import StreamingResponse

from src.experimental.prototype.target.factory.failure import (
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
        assert b"synthetic_drop" in _first
        with pytest.raises(RuntimeError, match="synthetic drop"):
            await anext(_iter)

    @pytest.mark.asyncio
    async def test_timeout(self,
                           monkeypatch: pytest.MonkeyPatch) -> None:
        """*test_timeout()* a `'timeout'` flag awaits `asyncio.sleep(grace_s)`; the test patches `sleep` to assert the call."""
        _calls: list[float] = []

        async def _fake_sleep(_t: float) -> None:
            _calls.append(_t)

        monkeypatch.setattr("src.experimental.prototype.target.factory.failure.asyncio.sleep",
                            _fake_sleep)
        _ans = await apply_inject_failure({"inject_failure": "timeout"},
                                          timeout_grace_s=0.5)
        assert _ans is None
        assert _calls == [0.5]

    @pytest.mark.asyncio
    async def test_unknown_flag(self) -> None:
        """*test_unknown_flag()* an unknown flag raises `ValueError`."""
        with pytest.raises(ValueError):
            await apply_inject_failure({"inject_failure": "weird"})

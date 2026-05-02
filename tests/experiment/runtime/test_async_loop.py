# -*- coding: utf-8 -*-
"""
Module test_async_loop.py
=========================

Pin the three behaviours of `run_async_safe`: works from a sync CLI context, works under an ambient asyncio loop, and surfaces coroutine exceptions to the sync caller.

    - **TestRunAsyncSafe** sync-CLI / ambient-loop / exception-propagation paths.
"""
# native python modules
import asyncio
from typing import Any, Dict

# testing framework
import pytest

# module under test
from src.experiment.runtime import run_async_safe


async def _ok_coro() -> Dict[str, Any]:
    """*_ok_coro()* yields the loop once, then resolves to a fixed dict.

    Returns:
        Dict[str, Any]: literal `{"answer": 42}`.
    """
    await asyncio.sleep(0)
    _ans: Dict[str, Any] = {"answer": 42}
    return _ans


async def _raise_coro() -> Dict[str, Any]:
    """*_raise_coro()* always raises on first step; the return type exists only to satisfy the `coro_factory` contract.

    Raises:
        ValueError: always; message is `"boom"`.

    Returns:
        Dict[str, Any]: never returns.
    """
    raise ValueError("boom")


class TestRunAsyncSafe:
    """**TestRunAsyncSafe** sync-CLI branch + ambient-loop branch + coroutine-exception propagation."""

    def test_sync_cli_branch(self) -> None:
        """*test_sync_cli_branch()* no ambient loop -> `run_async_safe(_ok_coro) == {"answer": 42}`."""
        _out = run_async_safe(_ok_coro)
        assert _out == {"answer": 42}

    @pytest.mark.asyncio
    async def test_ambient_loop_branch(self) -> None:
        """*test_ambient_loop_branch()* under pytest-asyncio's ambient loop, the same call still returns `{"answer": 42}` (offloaded to a worker thread)."""
        _out = run_async_safe(_ok_coro)
        assert _out == {"answer": 42}

    def test_coro_exception_propagates(self) -> None:
        """*test_coro_exception_propagates()* `run_async_safe(_raise_coro)` re-raises `ValueError("boom")` to the sync caller."""
        with pytest.raises(ValueError, match="boom"):
            run_async_safe(_raise_coro)

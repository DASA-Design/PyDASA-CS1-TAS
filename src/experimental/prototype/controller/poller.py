"""SamplePoller: asyncio task that pulls samples from TAS_1's `/samples` endpoint.

Spawned at controller startup; runs until cancelled. Every `poll_interval_ms`, calls `GET <target_url>/samples?since=<last_offset>` and feeds the new records to `controller.app.ingest_samples`. Transient HTTP errors are swallowed so a brief TAS_1 outage doesn't crash the controller; the next poll picks up wherever it left off.
"""

from __future__ import annotations

import asyncio
import contextlib
from typing import Any

import httpx
from fastapi import FastAPI

from src.experimental.prototype.controller.app import ingest_samples


class SamplePoller:
    """Periodic puller that merges new TAS_1 samples into the controller window.

    Attributes:
        target_url (str): TAS_1 base URL (e.g. `http://127.0.0.1:8001`).
        poll_interval_s (float): seconds between polls.
        app (FastAPI): the controller FastAPI app (state mutated in place).
    """

    def __init__(self,
                 *,
                 target_url: str,
                 poll_interval_ms: int,
                 app: FastAPI,
                 http_timeout_s: float = 2.0) -> None:
        """Configure the poller.

        Args:
            target_url (str): TAS_1 base URL.
            poll_interval_ms (int): poll cadence in milliseconds.
            app (FastAPI): controller app whose state receives the ingested samples.
            http_timeout_s (float, optional): per-poll HTTP timeout. Defaults to 2.0.
        """
        self.target_url = target_url.rstrip("/")
        self.poll_interval_s = poll_interval_ms / 1000.0
        self.app = app
        self._http_timeout_s = http_timeout_s
        self._task: asyncio.Task[None] | None = None
        self._stop_event = asyncio.Event()

    async def _poll_loop(self) -> None:
        """Poll TAS_1 until `_stop_event` is set.

        Opens one `httpx.AsyncClient` for the lifetime of the loop and reuses it across every poll. Between polls, awaits `_stop_event` with `poll_interval_s` timeout so shutdown is responsive.
        """
        async with httpx.AsyncClient(timeout=self._http_timeout_s) as _http:
            while not self._stop_event.is_set():
                await self._poll_once(_http)
                try:
                    await asyncio.wait_for(self._stop_event.wait(),
                                           timeout=self.poll_interval_s)
                except asyncio.TimeoutError:
                    pass

    async def _poll_once(self, http: httpx.AsyncClient) -> None:
        """Run one `GET /samples?since=<last_offset>` and merge any new records.

        Transport errors, non-200 responses, and malformed JSON are all swallowed silently; the records list stays empty and the next poll retries from the same offset.

        Args:
            http (httpx.AsyncClient): shared client for the poll loop.
        """
        _records: list[dict[str, Any]] = []
        _since = self.app.state.last_offset
        _url = f"{self.target_url}/samples"
        try:
            _resp = await http.get(_url, params={"since": _since})
            if _resp.status_code == 200:
                try:
                    _body: dict[str, Any] = _resp.json()
                except ValueError:
                    _body = {}
                _raw_records = _body.get("records", [])
                if isinstance(_raw_records, list):
                    _records = _raw_records
        except httpx.RequestError:
            pass
        if _records:
            ingest_samples(self.app, _records)

    def start(self) -> None:
        """Spawn the poll-loop task. Idempotent: a second call with the previous task still alive is a no-op."""
        if self._task is None or self._task.done():
            self._stop_event.clear()
            self._task = asyncio.create_task(self._poll_loop())

    async def stop(self) -> None:
        """Signal the poll loop to stop and wait for the task to exit.

        Safe to call multiple times. Suppresses `asyncio.CancelledError` from the join so the caller's teardown logic stays clean.
        """
        self._stop_event.set()
        if self._task is not None:
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
            self._task = None


__all__ = [
    "SamplePoller",
]

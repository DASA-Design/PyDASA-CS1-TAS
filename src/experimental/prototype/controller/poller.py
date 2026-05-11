"""SamplePoller variants that pull samples from TAS_1's `/samples` endpoint.

- `SamplePoller` (asyncio) runs inside FastAPI's lifespan; spawned at controller startup, cancelled on shutdown.
- `SyncSamplePoller` (threading) runs inside a daemon thread for the Flask / waitress controller (which has no lifespan equivalent).

Both call `GET <target_url>/samples?since=<last_offset>` every `poll_interval_ms` and feed the new records to `controller.app.ingest_samples`. Transient HTTP errors are swallowed; the next poll picks up wherever it left off.
"""

from __future__ import annotations

import asyncio
import contextlib
import threading
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


class SyncSamplePoller:
    """Threading-based sample poller for the Flask / waitress controller.

    Waitress has no lifespan equivalent, so the Flask controller factory starts this on a daemon thread when the app is built. Idempotent `start` / `stop`; the daemon flag means a stuck poller dies with the worker process.

    Attributes:
        target_url (str): TAS_1 base URL.
        poll_interval_s (float): seconds between polls.
        app (Any): controller app exposing `app.state` with `window` / `history` / `last_offset` etc.
    """

    def __init__(self,
                 *,
                 target_url: str,
                 poll_interval_ms: int,
                 app: Any,
                 http_timeout_s: float = 2.0) -> None:
        """Configure the poller.

        Args:
            target_url (str): TAS_1 base URL.
            poll_interval_ms (int): poll cadence in milliseconds.
            app (Any): controller app whose state receives the ingested samples.
            http_timeout_s (float, optional): per-poll HTTP timeout. Defaults to 2.0.
        """
        self.target_url = target_url.rstrip("/")
        self.poll_interval_s = poll_interval_ms / 1000.0
        self.app = app
        self._http_timeout_s = http_timeout_s
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None

    def _poll_loop(self) -> None:
        """Sync mirror of `SamplePoller._poll_loop` using a blocking `httpx.Client`."""
        with httpx.Client(timeout=self._http_timeout_s) as _http:
            while not self._stop_event.is_set():
                self._poll_once(_http)
                self._stop_event.wait(self.poll_interval_s)

    def _poll_once(self, http: httpx.Client) -> None:
        """Run one `GET /samples?since=<last_offset>` and merge any new records.

        Transport errors, non-200 responses, and malformed JSON are all swallowed; the next poll retries from the same offset.

        Args:
            http (httpx.Client): shared sync client for the poll loop.
        """
        _records: list[dict[str, Any]] = []
        _since = self.app.state.last_offset
        _url = f"{self.target_url}/samples"
        try:
            _resp = http.get(_url, params={"since": _since})
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
        """Spawn the daemon poll-loop thread. Idempotent: a second call with the thread still alive is a no-op."""
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._poll_loop, daemon=True)
        self._thread.start()

    def stop(self, join_timeout_s: float = 2.0) -> None:
        """Signal the poll loop to stop and join the daemon thread.

        Args:
            join_timeout_s (float, optional): max seconds to wait for the thread to exit. Defaults to 2.0.
        """
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=join_timeout_s)
            self._thread = None


__all__ = [
    "SamplePoller",
    "SyncSamplePoller",
]

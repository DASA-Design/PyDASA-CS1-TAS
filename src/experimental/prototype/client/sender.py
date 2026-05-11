"""`Sender`: build a `Request`, POST it, return a completed `RequestRecord`.

It owns the request-construction recipe (including the request-id mint) and the `User` class drives it iteratively. The catalogue + adaptation strategy decide whether `inject_failure` is set on a given request.
"""

from __future__ import annotations

import time
import uuid

import httpx

from src.experimental.common.payload.blob import make_blob
from src.experimental.common.payload.request import (
    FailureMechanism,
    Request,
)
from src.experimental.prototype.client.records import Outcome, RequestRecord


class Sender:
    """One-request dispatcher; pairs request construction with wire send.

    Attributes:
        _client (httpx.AsyncClient): caller-owned HTTP client; the sender does not open or close it.
        _client_id (str): synthetic-user id propagated into every `Request` and `RequestRecord`.
        _endpoint (str): URL the sender POSTs each request to.
        _payload_size_bytes (int): blob size for every request (typically 1024 or 4096).
        _blob_seed (int | None): seed for the blob generator; same `(seed, size)` returns identical bytes. None lets the RNG draw fresh bytes per call.
        _timeout_s (float): wall-clock cap before the sender records a timeout outcome.
    """

    def __init__(self,
                 client: httpx.AsyncClient,
                 client_id: str,
                 endpoint: str,
                 payload_size_bytes: int,
                 blob_seed: int | None = None,
                 timeout_s: float = 5.0) -> None:
        """Configure the sender against a caller-owned `httpx.AsyncClient`.

        Args:
            client (httpx.AsyncClient): the open, shared HTTP client.
            client_id (str): synthetic-user id stamped on every emitted record.
            endpoint (str): URL the sender POSTs to.
            payload_size_bytes (int): blob size in bytes; must be > 0.
            blob_seed (int | None, optional): seed for the deterministic blob generator. Defaults to None.
            timeout_s (float, optional): per-request wall-clock cap. Defaults to 5.0.
        """
        self._client = client
        self._client_id = client_id
        self._endpoint = endpoint
        self._payload_size_bytes = payload_size_bytes
        self._blob_seed = blob_seed
        self._timeout_s = timeout_s

    def build_request(self,
                      kind: str,
                      inject_failure: FailureMechanism | None = None,
                      req_id: str | None = None) -> Request:
        """Construct one `Request` ready for transport.

        Args:
            kind (str): workflow entry point; usually `KIND_ALARM` or `KIND_MED_ANSYS`.
            inject_failure (FailureMechanism | None, optional): planted failure mechanism. Defaults to None.
            req_id (str | None, optional): explicit request id; tests pin it for reproducibility. Defaults to None, which mints a UUID4 hex string.

        Returns:
            Request: frozen payload, base64-blob ready, with `submitted_ts` set to the current `time.time()`.
        """
        if req_id is None:
            _id = uuid.uuid4().hex
        else:
            _id = req_id
        _req = Request(req_id=_id,
                       kind=kind,
                       client_id=self._client_id,
                       submitted_ts=time.time(),
                       inject_failure=inject_failure,
                       blob=make_blob(self._payload_size_bytes,
                                      seed=self._blob_seed))
        return _req

    async def send(self, request: Request) -> RequestRecord:
        """POST one request and return the completed record.

        Args:
            request (Request): payload built via `build_request` (or constructed by the caller).

        Returns:
            RequestRecord: completion log entry. `outcome` is one of `success`, `timeout`, `drop`, or `5xx`. `total_latency_s` is wall-clock elapsed seconds.
        """
        _outcome, _status_code = await self._dispatch(request)
        _completed = time.time()
        _delta = _completed - request.submitted_ts
        _record = RequestRecord(req_id=request.req_id,
                                kind=request.kind,
                                client_id=request.client_id,
                                submitted_ts=request.submitted_ts,
                                completed_ts=_completed,
                                total_latency_s=_delta,
                                outcome=_outcome,
                                status_code=_status_code,
                                hops=[])
        return _record

    async def _dispatch(self, request: Request) -> tuple[Outcome, int]:
        """Issue the HTTP POST and map the result to a (outcome, status) pair.

        Args:
            request (Request): the payload to send.

        Returns:
            tuple[Outcome, int]: outcome label plus HTTP status code (0 on transport-level failures).
        """
        try:
            _resp = await self._client.post(self._endpoint,
                                            json=request.to_dict(),
                                            timeout=self._timeout_s)
        except httpx.TimeoutException:
            return "timeout", 0
        except httpx.RequestError:
            return "drop", 0
        if _resp.status_code >= 500:
            return "5xx", _resp.status_code
        return "success", _resp.status_code

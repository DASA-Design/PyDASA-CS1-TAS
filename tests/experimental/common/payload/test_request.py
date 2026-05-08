"""Tests for `src.experimental.common.payload.request`.

**TestRequest**:

- `test_round_trip`: confirms `to_dict` then `from_dict` reproduces the original `Request` so the wire schema is bit-stable.
- `test_blob_b64_encoding`: confirms the bytes blob survives the JSON-friendly base64 encoding so kB payloads can ride through HTTP without escaping headaches.
- `test_inject_failure_can_be_none`: confirms a `None` failure flag round-trips cleanly so the success path does not get accidentally encoded as a string.
- `test_inject_failure_mechanisms`: confirms each named mechanism (`timeout`, `drop`, `5xx`) and the `alarm` request kind round-trip so the controller's `ServiceProfile` reads the right flag from the payload.
"""

from __future__ import annotations

import pytest

from src.experimental.common.payload.request import (
    KIND_ALARM,
    KIND_MED_ANSYS,
    FailureMechanism,
    Request,
)


@pytest.fixture
def sample_request() -> Request:
    """Return one canonical `Request` instance for round-trip tests.

    Returns:
        Request: a `medical_analysis` request with no failure flag and a small fixed blob.
    """
    _req = Request(
        req_id="u47-r0312",
        kind=KIND_MED_ANSYS,
        client_id="user-47",
        submitted_ts=1736282400.123,
        inject_failure=None,
        blob=b"\x00\x01\x02hello",
    )
    return _req


class TestRequest:
    """Typed request schema with base64 blob transport."""

    def test_round_trip(self, sample_request: Request) -> None:
        """`Request.from_dict(req.to_dict())` returns a value equal to the original, demonstrating the wire encoding is lossless across every field including the blob.

        Args:
            sample_request (Request): canonical request from the module-local fixture.
        """
        _restored = Request.from_dict(sample_request.to_dict())
        assert _restored == sample_request

    def test_blob_b64_encoding(self, sample_request: Request) -> None:
        """The dict produced by `to_dict()` contains a `blob_b64` string field whose decoding yields the original bytes, so kB payloads ride through JSON without binary-escape headaches.

        Args:
            sample_request (Request): canonical request from the module-local fixture.
        """
        _payload = sample_request.to_dict()
        assert "blob_b64" in _payload
        assert isinstance(_payload["blob_b64"], str)
        assert Request.from_dict(_payload).blob == sample_request.blob

    def test_inject_failure_can_be_none(self, sample_request: Request) -> None:
        """A `None` failure flag survives the round trip as `None` rather than `\"None\"` or omitted, so the success path is never accidentally encoded as a string the server might try to dispatch.

        Args:
            sample_request (Request): canonical request from the module-local fixture (already has `inject_failure=None`).
        """
        assert sample_request.inject_failure is None
        _restored = Request.from_dict(sample_request.to_dict())
        assert _restored.inject_failure is None

    def test_inject_failure_mechanisms(self, sample_request: Request) -> None:
        """Each named mechanism (`timeout`, `drop`, `5xx`) round-trips intact, and the `alarm` kind also preserves its label, so the receiving `ServiceProfile` can dispatch failure injection from the payload's flag.

        Args:
            sample_request (Request): canonical request, mutated per-iteration to attach each failure mechanism.
        """
        _mechanisms: tuple[FailureMechanism, ...] = ("timeout", "drop", "5xx")
        for _mech in _mechanisms:
            _flagged = Request(
                req_id=sample_request.req_id,
                kind=sample_request.kind,
                client_id=sample_request.client_id,
                submitted_ts=sample_request.submitted_ts,
                inject_failure=_mech,
                blob=sample_request.blob,
            )
            assert Request.from_dict(_flagged.to_dict()).inject_failure == _mech
        _alarm = Request(
            req_id="r1",
            kind=KIND_ALARM,
            client_id="c1",
            submitted_ts=1.0,
            inject_failure=None,
            blob=b"x",
        )
        assert Request.from_dict(_alarm.to_dict()).kind == KIND_ALARM

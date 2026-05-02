# -*- coding: utf-8 -*-
"""
Module test_payload.py
======================

Pin the mock-payload generator (`src.experiment.wire.payload`) contracts: dataclass behaviour, exact byte size, RNG determinism, negative-size rejection, and `resolve_size_for_kind` lookup rules.

    - **TestMockPayload** dataclass behaviour, exact byte-size, RNG determinism, negative-size rejection, and `resolve_size_for_kind` lookup rules (exact / alias / `response_default` / caller default).
"""
# native python modules
import random

# testing framework
import pytest

# module under test
from src.experiment.wire import (MockPayload,
                                 generate_payload,
                                 resolve_size_for_kind)


class TestMockPayload:
    """**TestMockPayload** dataclass + generator + lookup contracts."""

    def test_frozen_dataclass(self) -> None:
        """*test_frozen_dataclass()* assigning to `MockPayload.kind` after construction raises (frozen=True)."""
        _p = MockPayload(kind="analyse_request", size_bytes=4, blob="abcd")
        with pytest.raises(Exception):
            _p.kind = "other"  # type: ignore[misc]

    def test_to_dict_round_trip(self) -> None:
        """*test_to_dict_round_trip()* `to_dict()` returns `{"kind", "size_bytes", "blob"}` matching the dataclass fields verbatim."""
        _p = generate_payload("drug_request", 64, rng=random.Random(7))
        _d = _p.to_dict()
        assert _d == {"kind": "drug_request",
                      "size_bytes": 64,
                      "blob": _p.blob}

    @pytest.mark.parametrize("_n", [0, 1, 16, 128, 256, 1024, 4096])
    def test_blob_byte_size(self, _n: int) -> None:
        """*test_blob_byte_size()* for every `_n` in the parametric set, `len(blob) == _n` and `len(blob.encode("utf-8")) == _n`."""
        _p = generate_payload("analyse_request", _n)
        assert isinstance(_p, MockPayload)
        assert len(_p.blob) == _n
        # every character in the ASCII alphabet is 1 byte in UTF-8
        assert len(_p.blob.encode("utf-8")) == _n

    def test_seeded_deterministic(self) -> None:
        """*test_seeded_deterministic()* two separate `random.Random(42)` instances feeding the same call produce byte-identical blobs."""
        _rng_a = random.Random(42)
        _rng_b = random.Random(42)
        _a = generate_payload("alarm_request", 128, rng=_rng_a)
        _b = generate_payload("alarm_request", 128, rng=_rng_b)
        assert _a.blob == _b.blob

    def test_seeds_independent(self) -> None:
        """*test_seeds_independent()* `random.Random(1)` and `random.Random(2)` produce distinct blobs (independence sanity check)."""
        _a = generate_payload("analyse_request", 128, rng=random.Random(1))
        _b = generate_payload("analyse_request", 128, rng=random.Random(2))
        assert _a.blob != _b.blob

    def test_negative_size_raises(self) -> None:
        """*test_negative_size_raises()* `size_bytes=-1` raises `ValueError("size_bytes must be >= 0, ...")`."""
        with pytest.raises(ValueError, match="size_bytes must be >= 0"):
            generate_payload("analyse_request", -1)

    def test_exact_key_match(self) -> None:
        """*test_exact_key_match()* `resolve_size_for_kind({"analyse_request": 256, ...}, "analyse_request") == 256`."""
        _map = {"analyse_request": 256, "alarm_request": 128}
        assert resolve_size_for_kind(_map, "analyse_request") == 256

    def test_kind_request_alias(self) -> None:
        """*test_kind_request_alias()* the bare label `"analyse"` resolves via the `"analyse_request"` alias."""
        _map = {"analyse_request": 256}
        assert resolve_size_for_kind(_map, "analyse") == 256

    def test_response_default_fallback(self) -> None:
        """*test_response_default_fallback()* when neither the literal key nor its `_request` alias is present, the `response_default` entry is returned."""
        _map = {"response_default": 42}
        assert resolve_size_for_kind(_map, "unknown_kind") == 42

    def test_default_fallback(self) -> None:
        """*test_default_fallback()* empty map + missing `response_default` returns the caller-supplied `default` (here `99`)."""
        assert resolve_size_for_kind({}, "whatever", default=99) == 99

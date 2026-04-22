# -*- coding: utf-8 -*-
"""
Module test_payload.py
======================

Unit tests for the mock-payload generator (`src.experiment.payload`).
Pins FR-2.3 behaviour:

    - **TestMockPayload** frozen dataclass + `to_dict` round-trip.
    - **TestGeneratePayload** exact byte size, determinism under a seeded
      RNG, and negative-size rejection.
    - **TestResolveSizeForKind** exact keys, `<kind>_request` aliases,
      `response_default` fallback, and caller-supplied default.
"""
# native python modules
import random

# testing framework
import pytest

# module under test
from src.experiment.payload import (MockPayload,
                                    generate_payload,
                                    resolve_size_for_kind)


class TestMockPayload:
    """**TestMockPayload** dataclass contract: frozen, `to_dict` round-trip."""

    def test_frozen_dataclass(self):
        _p = MockPayload(kind="analyse_request", size_bytes=4, blob="abcd")
        with pytest.raises(Exception):
            _p.kind = "other"  # type: ignore[misc]

    def test_to_dict_round_trip(self):
        _p = generate_payload("drug_request", 64, rng=random.Random(7))
        _d = _p.to_dict()
        assert _d == {"kind": "drug_request",
                      "size_bytes": 64,
                      "blob": _p.blob}


class TestGeneratePayload:
    """**TestGeneratePayload** blob size + determinism + input validation."""

    @pytest.mark.parametrize("_n", [0, 1, 16, 128, 256, 1024, 4096])
    def test_blob_is_exact_byte_size(self, _n):
        _p = generate_payload("analyse_request", _n)
        assert isinstance(_p, MockPayload)
        assert len(_p.blob) == _n
        # every character in the ASCII alphabet is 1 byte in UTF-8
        assert len(_p.blob.encode("utf-8")) == _n

    def test_seeded_rng_is_deterministic(self):
        _rng_a = random.Random(42)
        _rng_b = random.Random(42)
        _a = generate_payload("alarm_request", 128, rng=_rng_a)
        _b = generate_payload("alarm_request", 128, rng=_rng_b)
        assert _a.blob == _b.blob

    def test_different_seeds_produce_different_blobs(self):
        _a = generate_payload("analyse_request", 128, rng=random.Random(1))
        _b = generate_payload("analyse_request", 128, rng=random.Random(2))
        assert _a.blob != _b.blob

    def test_negative_size_raises(self):
        with pytest.raises(ValueError, match="size_bytes must be >= 0"):
            generate_payload("analyse_request", -1)


class TestResolveSizeForKind:
    """**TestResolveSizeForKind** resolves per-kind payload size from a config map."""

    def test_exact_key_match(self):
        _map = {"analyse_request": 256, "alarm_request": 128}
        assert resolve_size_for_kind(_map, "analyse_request") == 256

    def test_kind_request_alias(self):
        """Kind label `analyse` resolves to `analyse_request` in the map."""
        _map = {"analyse_request": 256}
        assert resolve_size_for_kind(_map, "analyse") == 256

    def test_response_default_fallback(self):
        _map = {"response_default": 42}
        assert resolve_size_for_kind(_map, "unknown_kind") == 42

    def test_default_when_nothing_matches(self):
        assert resolve_size_for_kind({}, "whatever", default=99) == 99

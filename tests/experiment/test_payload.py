# -*- coding: utf-8 -*-
"""
Module test_payload.py
======================

Unit tests for the mock-payload generator (`src.experiment.payload`).
Pins FR-2.3 behaviour:

    - Generated blob is exactly `size_bytes` bytes (UTF-8 == char count).
    - Generation is deterministic under a seeded RNG.
    - Negative sizes are rejected.
    - `size_for_kind` resolves exact keys, `<kind>_request` aliases, and a fallback default.
"""
# native python modules
import random

# testing framework
import pytest

# module under test
from src.experiment.payload import MockPayload, generate, size_for_kind


class TestGenerate:
    """**TestGenerate** blob size + determinism + input validation."""

    @pytest.mark.parametrize("_n", [0, 1, 16, 128, 256, 1024, 4096])
    def test_blob_is_exact_byte_size(self, _n):
        _p = generate("analyse_request", _n)
        assert isinstance(_p, MockPayload)
        assert len(_p.blob) == _n
        # all characters in the ASCII alphabet => 1 byte each in UTF-8
        assert len(_p.blob.encode("utf-8")) == _n

    def test_seeded_rng_is_deterministic(self):
        _rng_a = random.Random(42)
        _rng_b = random.Random(42)
        _a = generate("alarm_request", 128, rng=_rng_a)
        _b = generate("alarm_request", 128, rng=_rng_b)
        assert _a.blob == _b.blob

    def test_different_seeds_produce_different_blobs(self):
        _a = generate("analyse_request", 128, rng=random.Random(1))
        _b = generate("analyse_request", 128, rng=random.Random(2))
        assert _a.blob != _b.blob

    def test_negative_size_raises(self):
        with pytest.raises(ValueError, match="size_bytes must be >= 0"):
            generate("analyse_request", -1)

    def test_to_dict_roundtrip(self):
        _p = generate("drug_request", 64, rng=random.Random(7))
        _d = _p.to_dict()
        assert _d == {"kind": "drug_request",
                      "size_bytes": 64,
                      "blob": _p.blob}


class TestSizeForKind:
    """**TestSizeForKind** resolves per-kind payload size from a config map."""

    def test_exact_key_match(self):
        _map = {"analyse_request": 256, "alarm_request": 128}
        assert size_for_kind(_map, "analyse_request") == 256

    def test_kind_request_alias(self):
        """A kind label `analyse` resolves to `analyse_request` in the map."""
        _map = {"analyse_request": 256}
        assert size_for_kind(_map, "analyse") == 256

    def test_response_default_fallback(self):
        _map = {"response_default": 42}
        assert size_for_kind(_map, "unknown_kind") == 42

    def test_default_when_nothing_matches(self):
        assert size_for_kind({}, "whatever", default=99) == 99

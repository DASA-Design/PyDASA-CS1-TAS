"""Tests for `src.experimental.common.payload.blob`.

**TestBlob**:

- `test_size_correct`: confirms the returned bytes have the requested length so callers receive the kB-scale payload they asked for.
- `test_seeded_deterministic`: confirms the same `(seed, size)` pair returns identical bytes across calls so flagged-failure experiments are bit-reproducible.
- `test_different_seeds_differ`: confirms distinct seeds produce distinct bytes so per-run randomisation does not collide.
- `test_seed_none_fresh_per_call`: confirms passing `seed=None` produces a fresh sequence each call so dev / ad-hoc runs are not stuck on a hidden default.
- `test_zero_size_raises`: confirms a non-positive size is rejected with a clear `ValueError` rather than silently returning an empty buffer.
"""

from __future__ import annotations

import pytest

from src.experimental.common.payload.blob import make_blob


class TestBlob:
    """Generated random-byte blob generator."""

    def test_size_correct(self) -> None:
        """`make_blob(1024, seed=1)` returns exactly 1024 bytes; the writer respects the requested size so handlers can plan memory budgets accurately."""
        assert len(make_blob(1024, seed=1)) == 1024

    def test_seeded_deterministic(self) -> None:
        """Two calls with the same `(seed, size)` return byte-identical output, so an experiment fixed at a given seed produces the same payload stream across runs and processes."""
        _a = make_blob(512, seed=42)
        _b = make_blob(512, seed=42)
        assert _a == _b

    def test_different_seeds_differ(self) -> None:
        """Two seeds that differ produce distinct byte streams, demonstrating the seed actually feeds the RNG rather than being ignored."""
        _a = make_blob(512, seed=1)
        _b = make_blob(512, seed=2)
        assert _a != _b

    def test_seed_none_fresh_per_call(self) -> None:
        """Passing `seed=None` lets the RNG draw fresh entropy each call, so two unseeded calls of 512 random bytes are vanishingly unlikely to collide; this is the path dev / ad-hoc runs use to skip reproducibility."""
        _a = make_blob(512)
        _b = make_blob(512)
        assert _a != _b

    def test_zero_size_raises(self) -> None:
        """A zero or negative `size_bytes` raises `ValueError` rather than producing an empty buffer, surfacing misuse at the call site instead of corrupting downstream measurements."""
        with pytest.raises(ValueError, match="positive"):
            make_blob(0, seed=1)
        with pytest.raises(ValueError, match="positive"):
            make_blob(-5, seed=1)

"""Generated random-byte blob for request payloads.

A blob lets every request carry kB-scale bytes that load the handler's memory paths like real traffic. Pass an integer `seed` for reproducibility (same `(seed, size_bytes)` returns identical bytes), or leave `seed=None` for a fresh sequence per call.
"""

from __future__ import annotations

import random


def make_blob(size_bytes: int, seed: int | None = None) -> bytes:
    """Build a random-byte blob.

    Args:
        size_bytes (int): number of bytes; must be > 0.
        seed (int | None, optional): integer seed for the local RNG. Defaults to None, which lets the RNG draw fresh bytes per call.

    Returns:
        bytes: byte string of length `size_bytes`. With a fixed `seed`, the same `(seed, size_bytes)` returns identical bytes across processes and runs.

    Raises:
        ValueError: if `size_bytes` is not positive.
    """
    if size_bytes <= 0:
        _msg = f"size_bytes must be positive, got {size_bytes}"
        raise ValueError(_msg)
    _rng = random.Random(seed)
    _blob = _rng.randbytes(size_bytes)
    return _blob

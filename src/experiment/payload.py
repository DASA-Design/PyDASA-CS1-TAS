# -*- coding: utf-8 -*-
"""
Module payload.py
=================

Mock-payload generator used by the client simulator to produce dummy request bodies of a configured byte size per kind.

Each client-generated request carries a real payload of declared size. Downstream services never probe process memory (`psutil`); the payload bytes and the `X-Request-Size-Bytes` header ARE the memory-usage signal. The `memory-usage` dimensional coefficient is derived downstream from the product of per-kind payload size and per-component in-flight count L.

Public API:
    - `MockPayload(kind, size_bytes, blob)` the produced dataclass.
    - `generate_payload(kind, size_bytes, rng)` factory; deterministic under seed.
    - `resolve_size_for_kind(sizes_by_kind, kind, default)` config lookup helper.
"""
# native python modules
from __future__ import annotations

import random
import string

# data types
from dataclasses import dataclass
from typing import Any, Dict, Optional


# ASCII-only alphabet so one character equals one UTF-8 byte
_ALPHABET = string.ascii_letters + string.digits


@dataclass(frozen=True)
class MockPayload:
    """*MockPayload* one generated dummy payload.

    Attributes:
        kind (str): request kind this payload was generated for.
        size_bytes (int): declared payload size in bytes.
        blob (str): ASCII-only string of exactly `size_bytes` bytes.
    """
    # request kind label, e.g. "analyse_request", "alarm_request", "drug_request", "response_default"
    kind: str
    # declared payload size in bytes generated in UTF-8
    size_bytes: int
    # ASCII-only string of exactly `size_bytes` bytes
    blob: str

    def to_dict(self) -> Dict[str, Any]:
        """*to_dict()* return a plain dict suitable for `SvcReq.payload`."""
        return {"kind": self.kind,
                "size_bytes": self.size_bytes,
                "blob": self.blob}


def generate_payload(kind: str,
                     size_bytes: int,
                     rng: Optional[random.Random] = None) -> MockPayload:
    """*generate_payload()* build a MockPayload of exactly `size_bytes` bytes for `kind`.

    Draws from an ASCII-only alphabet so the UTF-8 encoding of the blob equals its character count, making the declared byte size exact.

    Args:
        kind (str): request kind label the payload belongs to.
        size_bytes (int): requested payload size in bytes; must be `>= 0`.
        rng (Optional[random.Random]): dedicated RNG for reproducibility. When `None`, a fresh `random.Random()` is used.

    Raises:
        ValueError: if `size_bytes < 0`.

    Returns:
        MockPayload: payload with a blob of exactly `size_bytes` ASCII bytes.
    """
    if size_bytes < 0:
        raise ValueError(f"size_bytes must be >= 0, got {size_bytes}")

    if rng is None:
        _rng = random.Random()
    else:
        _rng = rng

    # one char equals one UTF-8 byte under the ASCII alphabet
    _blob = "".join(_rng.choices(_ALPHABET, k=int(size_bytes)))
    return MockPayload(kind=kind, size_bytes=int(size_bytes), blob=_blob)


def resolve_size_for_kind(sizes_by_kind: Dict[str, int],
                          kind: str,
                          default: int = 256) -> int:
    """*resolve_size_for_kind()* look up the declared payload size for `kind`.

    Matches the method config's `request_size_bytes` map (keys like `analyse_request`, `alarm_request`, `drug_request`, `response_default`). The client uses kind labels that equal target artifact names (`TAS_{2}`, `TAS_{3}`, ...), so this helper also accepts a `<kind>_request` alias for readability.

    Args:
        sizes_by_kind (Dict[str, int]): method-config's request-size map.
        kind (str): kind label.
        default (int): fallback when neither `kind` nor `<kind>_request` is present.

    Returns:
        int: size in bytes to generate for this kind.
    """
    if kind in sizes_by_kind:
        return int(sizes_by_kind[kind])
    _alias = f"{kind}_request"
    if _alias in sizes_by_kind:
        return int(sizes_by_kind[_alias])
    return int(sizes_by_kind.get("response_default", default))

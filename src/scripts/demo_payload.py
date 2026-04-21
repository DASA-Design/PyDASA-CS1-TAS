# -*- coding: utf-8 -*-
"""
demo_payload.py
===============

Show what `src.experiment.payload.generate` produces for each declared
request kind. Prints the mock-payload dataclass, its ASCII blob (first
80 chars), measured UTF-8 byte count, and verifies reproducibility
under a fixed seed.

Run:
    python scripts/demo/demo_payload.py
"""
import random
import sys
from pathlib import Path

# ensure we can `from src...` when run from repo root
_HERE = Path(__file__).resolve()
_ROOT = _HERE.parents[2]
sys.path.insert(0, str(_ROOT))

from src.experiment.payload import MockPayload, generate, size_for_kind  # noqa: E402
from src.io import load_method_config  # noqa: E402


def _banner(_s: str) -> None:
    print()
    print("=" * 72)
    print(f"  {_s}")
    print("=" * 72)


def main() -> None:
    # 1. show the per-kind size map read from the method config
    _banner("1. per-kind payload sizes declared in experiment.json")
    _mcfg = load_method_config("experiment")
    _sizes = dict(_mcfg.get("request_size_bytes", {}))
    for _k, _v in _sizes.items():
        print(f"  {_k:<20}  {_v} bytes")

    # 2. generate one payload per declared kind, dump to stdout
    _banner("2. generate(kind, size_bytes, rng)  →  MockPayload")
    _rng = random.Random(42)
    for _kind, _size in _sizes.items():
        _p: MockPayload = generate(_kind, _size, rng=_rng)
        _ascii_ok = all(ord(_c) < 128 for _c in _p.blob)
        _byte_len = len(_p.blob.encode("utf-8"))
        print(f"\n  kind={_kind!r}  size_bytes={_p.size_bytes}")
        print(f"    blob (first 80 chars): {_p.blob[:80]!r}...")
        print(f"    len(blob)={len(_p.blob)}  utf-8 bytes={_byte_len}"
              f"  ASCII-only={_ascii_ok}")
        print(f"    to_dict()={_p.to_dict()['kind']!r} / "
              f"size={_p.to_dict()['size_bytes']}")

    # 3. show size_for_kind() alias resolution
    _banner("3. size_for_kind() resolves exact keys + <kind>_request aliases")
    _map = {"analyse_request": 256, "alarm_request": 128, "response_default": 64}
    for _probe in ["analyse_request", "analyse", "unknown_kind", "alarm"]:
        print(f"  size_for_kind({_probe!r}) = {size_for_kind(_map, _probe)}")

    # 4. show reproducibility under seed
    _banner("4. reproducibility: same seed → identical blob")
    _a = generate("analyse", 64, rng=random.Random(7))
    _b = generate("analyse", 64, rng=random.Random(7))
    _c = generate("analyse", 64, rng=random.Random(99))
    print(f"  seed=7  first 40 chars: {_a.blob[:40]!r}")
    print(f"  seed=7  first 40 chars: {_b.blob[:40]!r}   → {'match' if _a.blob == _b.blob else 'DIFFER'}")
    print(f"  seed=99 first 40 chars: {_c.blob[:40]!r}   → {'match' if _a.blob == _c.blob else 'differ'}")


if __name__ == "__main__":
    main()

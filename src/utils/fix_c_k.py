# -*- coding: utf-8 -*-
"""
Module fix_c_k.py
=================

One-shot repair that forces every artifact in
`data/config/profile/{dflt,opti}.json` to match the canonical values
from `__OLD__/data/config/cs1/{default,optimal}_qn_model.csv`:

    c (server count)      := 1    (was drifting to 2 in places)
    K (system capacity)   := 10   (opti.json had K=6 for all slots)

Reasons for the drift: the original import from CSV set `c` from the
per-node column but something later doubled it; `K` was probably
tightened while testing. Both break the Jackson comparison because
they halve every utilisation and shrink queue capacity, so the
diffmap magnitudes diverge from the reference.

Usage:

    venv/Scripts/python.exe -m src.utils.fix_c_k [--dry-run]
"""
# native python modules
from __future__ import annotations

import argparse
import json
from pathlib import Path

# data types
from typing import List


_ROOT = Path(__file__).resolve().parents[2]
_PROFILE_DIR = _ROOT / "data" / "config" / "profile"

_CANONICAL_C = 1
_CANONICAL_K = 10


def _fix_profile(doc: dict) -> List[str]:
    """*_fix_profile()* set every artifact's `c` and `K` setpoints to
    the canonical values. Returns a log of what changed.
    """
    _changes: List[str] = []

    for _key, _spec in doc.get("artifacts", {}).items():
        _vars = _spec.get("vars", {})

        # server count: c_{ARTIFACT_KEY}
        _c_var = f"c_{{{_key}}}"
        if _c_var in _vars:
            _current = _vars[_c_var].get("_setpoint")
            if _current != _CANONICAL_C:
                _vars[_c_var]["_setpoint"] = _CANONICAL_C
                if "_data" in _vars[_c_var]:
                    _vars[_c_var]["_data"] = [_CANONICAL_C]
                _changes.append(
                    f"  {_key}: c {_current} -> {_CANONICAL_C}"
                )

        # capacity: K_{ARTIFACT_KEY}
        _k_var = f"K_{{{_key}}}"
        if _k_var in _vars:
            _current = _vars[_k_var].get("_setpoint")
            if _current != _CANONICAL_K:
                _vars[_k_var]["_setpoint"] = _CANONICAL_K
                if "_data" in _vars[_k_var]:
                    _vars[_k_var]["_data"] = [_CANONICAL_K]
                _changes.append(
                    f"  {_key}: K {_current} -> {_CANONICAL_K}"
                )

    return _changes


def main() -> None:
    """*main()* CLI entry: load each profile, force c/K, persist."""
    _parser = argparse.ArgumentParser(
        description="Fix c/K setpoints to match __OLD__ CSV canonical values.",
    )
    _parser.add_argument(
        "--dry-run",
        action="store_true",
        help="report changes without writing the files",
    )
    _args = _parser.parse_args()

    for _path in sorted(_PROFILE_DIR.glob("*.json")):
        print(f"\n=== {_path.relative_to(_ROOT)} ===")
        with _path.open(encoding="utf-8") as _fh:
            _doc = json.load(_fh)

        _changes = _fix_profile(_doc)
        if not _changes:
            print("  no changes (already canonical)")
            continue

        for _line in _changes:
            print(_line)

        if _args.dry_run:
            print(f"  [dry-run] not writing {_path.name}")
            continue

        with _path.open("w", encoding="utf-8") as _fh:
            json.dump(_doc, _fh, indent=4, ensure_ascii=False)
        print(f"  wrote {_path.name} ({len(_changes)} changes)")


if __name__ == "__main__":
    main()

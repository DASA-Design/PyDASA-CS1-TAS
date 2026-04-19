# -*- coding: utf-8 -*-
"""
Module rename_keys.py
=====================

One-shot migration that rewrites the artifact and variable keys in
`data/config/profile/{dflt,opti}.json` to the LaTeX-subscript naming
convention.

Three transformations are applied in place:

    1. Artifact keys:        `TAS_1`            -> `TAS_{1}`
                             `MAS_3`            -> `MAS_{3}`
                             ... (every prefix_index pattern)

    2. `_nodes[scenario]`:   each list item is renamed via the same
                             artifact-key map so positional slots
                             still resolve to a known artifact.

    3. Variable keys:        `Lq_{TAS_{1}}`     -> `L_{q, TAS_{1}}`
                             `Wq_{TAS_{1}}`     -> `W_{q, TAS_{1}}`
                             (the q-subscript is split out into the
                             outer subscript so the variable is valid
                             LaTeX, not the previous compressed form).

*IMPORTANT:* run this once. After the rewrite, the artifact key IS the
LaTeX subscript form, so any consumer that previously did the
`TAS_1` -> `TAS_{1}` split (e.g. `ArtifactSpec._sub()`) needs to stop
re-applying the transformation -- otherwise it will produce
`TAS_{{1}}` (double braces).

Usage:

    venv/Scripts/python.exe -m src.utils.rename_keys [--dry-run]
"""
# native python modules
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

# data types
from typing import Dict, List, Tuple


_ROOT = Path(__file__).resolve().parents[2]
_PROFILE_DIR = _ROOT / "data" / "config" / "profile"


# matches an artifact key like "TAS_1", "MAS_3", "AS_4", "DS_1"
_KEY_RE = re.compile(r"^([A-Za-z]+)_(\d+)$")


def _new_artifact_key(old: str) -> str:
    """*_new_artifact_key()* converts a flat artifact key into its
    LaTeX-subscript form: `TAS_1` -> `TAS_{1}`. Returns the key
    unchanged if it does not match the prefix_index pattern.
    """
    _m = _KEY_RE.match(old)
    if not _m:
        return old
    return f"{_m.group(1)}_{{{_m.group(2)}}}"


def _build_artifact_map(artifacts: Dict[str, dict]) -> Dict[str, str]:
    """*_build_artifact_map()* returns `{old_key: new_key}` for every
    top-level artifact in the profile.
    """
    return {_k: _new_artifact_key(_k) for _k in artifacts.keys()}


def _rename_var_key(old: str) -> str:
    """*_rename_var_key()* applies the q-subscript split so the
    variable name becomes valid LaTeX:

        `Lq_{TAS_{1}}`  -> `L_{q, TAS_{1}}`
        `Wq_{TAS_{1}}`  -> `W_{q, TAS_{1}}`

    Variables that do not start with `Lq_{` or `Wq_{` are returned
    unchanged.
    """
    if old.startswith("Lq_{") and old.endswith("}"):
        # Lq_{<inner>} -> L_{q, <inner>}
        _inner = old[len("Lq_{"):-1]
        return f"L_{{q, {_inner}}}"
    if old.startswith("Wq_{") and old.endswith("}"):
        _inner = old[len("Wq_{"):-1]
        return f"W_{{q, {_inner}}}"
    return old


def _rewrite_profile(doc: dict) -> Tuple[dict, List[str]]:
    """*_rewrite_profile()* applies all three transformations to one
    parsed JSON envelope and returns `(new_doc, change_log)`.

    Args:
        doc (dict): the parsed profile JSON (`artifacts` + `environments`).

    Returns:
        Tuple[dict, List[str]]: the rewritten doc + a list of
            human-readable change descriptions for printing.
    """
    _changes: List[str] = []

    # -------- step 1: build the artifact-key rename map --------
    _key_map = _build_artifact_map(doc["artifacts"])
    for _old, _new in _key_map.items():
        if _old != _new:
            _changes.append(f"artifact: {_old!r} -> {_new!r}")

    # -------- step 2: rebuild the artifacts block --------
    _new_artifacts: Dict[str, dict] = {}
    for _old_key, _spec in doc["artifacts"].items():
        _new_key = _key_map[_old_key]

        # rebuild this artifact's `vars` block with renamed q-subscript vars
        _new_vars: Dict[str, dict] = {}
        for _vname, _vbody in _spec.get("vars", {}).items():
            _new_vname = _rename_var_key(_vname)
            if _new_vname != _vname:
                _changes.append(f"  var on {_new_key}: {_vname!r} -> {_new_vname!r}")
            _new_vars[_new_vname] = _vbody

        # copy the artifact body and swap in the renamed vars
        _new_spec = dict(_spec)
        if "vars" in _new_spec:
            _new_spec["vars"] = _new_vars
        _new_artifacts[_new_key] = _new_spec

    # -------- step 3: rebuild `_nodes[scenario]` lists --------
    _env = dict(doc["environments"])
    _new_nodes: Dict[str, List[str]] = {}
    for _scn, _slot_keys in _env.get("_nodes", {}).items():
        _renamed = [_key_map.get(_k, _k) for _k in _slot_keys]
        _new_nodes[_scn] = _renamed
        if _renamed != list(_slot_keys):
            _changes.append(f"_nodes[{_scn!r}]: rebuilt with new keys")
    _env["_nodes"] = _new_nodes

    # -------- final assembly --------
    _new_doc = dict(doc)
    _new_doc["artifacts"] = _new_artifacts
    _new_doc["environments"] = _env

    return _new_doc, _changes


def main() -> None:
    """*main()* CLI entry: load each profile, rewrite, and persist (or
    dry-run when `--dry-run` is set).
    """
    _parser = argparse.ArgumentParser(
        description="Rename artifact and variable keys to the LaTeX "
                    "subscript convention.",
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

        _new_doc, _changes = _rewrite_profile(_doc)

        if not _changes:
            print("  no changes (already migrated)")
            continue

        for _line in _changes:
            print(f"  {_line}")

        if _args.dry_run:
            print(f"  [dry-run] not writing {_path.name}")
            continue

        with _path.open("w", encoding="utf-8") as _fh:
            json.dump(_new_doc, _fh, indent=4, ensure_ascii=False)
        print(f"  wrote {_path.name} ({len(_changes)} changes)")


if __name__ == "__main__":
    main()

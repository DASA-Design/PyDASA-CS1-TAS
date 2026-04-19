# -*- coding: utf-8 -*-
"""
Module config.py
================

Profile + scenario loader for the CS-01 TAS case study.

Resolves a `(profile, scenario)` selection into a flat `NetworkConfig` by reading the PACS-style JSONs under `data/config/profile/`. Expected envelope shape:

    environments._setpoint  -> default scenario when --adaptation is absent
    environments._nodes -> {scenario: [artifact_key, ... 13 entries]}
    environments._routs -> {scenario: [[13x13 matrix]]}
    environments._labels -> {scenario: str}
    artifacts[<key>] -> {name, type, lambda_z, L_z, vars: {sym: {...}}}

*IMPORTANT:* for the `opti` profile, `_nodes[scenario]` at the three swap slots picks different artifacts per scenario:

    - slot  5: s1 -> MAS_3 (dflt);  s2 / aggregate -> MAS_4 (opti)
    - slot  8: s1 -> AS_3  (dflt);  s2 / aggregate -> AS_4  (opti)
    - slot 10: s1 -> DS_3  (dflt);  s2 / aggregate -> DS_1  (opti)

# TODO: validate row-stochasticity on the routing matrix at load time once we add more scenarios (keeps typos from reaching the solver).
"""
# native python modules
# forward references + postpone eval type hints
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

# data types
from typing import Any, Dict, List, Optional, Tuple

# scientific stack
import numpy as np


_ROOT = Path(__file__).resolve().parents[2]
_PROFILE_DIR = _ROOT / "data" / "config" / "profile"
_METHOD_DIR = _ROOT / "data" / "config" / "method"
_REFERENCE_DIR = _ROOT / "data" / "reference"


# adaptation value -> (profile file stem, scenario name within that profile)
_ADAPTATION_TO_SOURCE: Dict[str, Tuple[str, str]] = {
    "baseline": ("dflt", "baseline"),
    "s1": ("opti", "s1"),
    "s2": ("opti", "s2"),
    "aggregate": ("opti", "aggregate"),
}


@dataclass(frozen=True)
class ArtifactSpec:
    """**ArtifactSpec** captures one node's full spec, resolved from the profile + scenario load.

    Attributes:
        key (str): artifact key in the PACS envelope (e.g. `TAS_1`).
        name (str): human-readable name.
        type_ (str): queue model string (e.g. `M/M/c/K`).
        lambda_z (float): external arrival rate entering this node.
        L_z (float): external queue length initialisation (currently 0).
        vars (Dict[str, dict]): PyDASA `Variable`-dict block, keyed by LaTeX symbol (e.g. `\\mu_{TAS_{1}}`).
    """

    # :attr: key
    key: str
    """Artifact key in the PACS envelope (e.g. `TAS_1`)."""

    # :attr: name
    name: str
    """Human-readable name."""

    # :attr: type_
    type_: str
    """Queue model string (e.g. `M/M/c/K`)."""

    # :attr: lambda_z
    lambda_z: float
    """External arrival rate entering this node."""

    # :attr: L_z
    L_z: float
    """External queue length initialisation (currently 0)."""

    # :attr: vars
    vars: Dict[str, dict]
    """PyDASA `Variable`-dict block, keyed by LaTeX symbol."""

    def _setpoint(self, prefix: str) -> float:
        """*_setpoint()* returns the `_setpoint` of the first variable whose LaTeX symbol starts with `prefix`.

        Args:
            prefix (str): LaTeX-symbol prefix including the artifact's own subscript (e.g. `\\mu_{TAS_{1}}`).

        Raises:
            KeyError: If no variable on this artifact matches the prefix.

        Returns:
            float: the setpoint value of the matching variable.
        """
        # walk the variable dict and return the first match
        for _sym, _var in self.vars.items():
            if _sym.startswith(prefix):
                return float(_var["_setpoint"])
        raise KeyError(f"no variable with prefix {prefix!r} on {self.key}")

    def _sub(self) -> str:
        """*_sub()* returns the LaTeX subscript form of the artifact key.

        Since `data/config/profile/*.json` was migrated to store keys
        already in LaTeX form (e.g. `TAS_{1}`), this is just an identity
        pass-through kept for API compatibility with callers that were
        written against the old `TAS_1` flat-key convention.

        Returns:
            str: the artifact key verbatim (already a LaTeX subscript).
        """
        return self.key

    @property
    def mu(self) -> float:
        """*mu* service rate setpoint for this artifact."""
        return self._setpoint(f"\\mu_{{{self._sub()}}}")

    @property
    def c(self) -> int:
        """*c* server count setpoint for this artifact."""
        return int(self._setpoint(f"c_{{{self._sub()}}}"))

    @property
    def K(self) -> int:
        """*K* system capacity setpoint for this artifact."""
        return int(self._setpoint(f"K_{{{self._sub()}}}"))

    @property
    def epsilon(self) -> float:
        """*epsilon* per-node failure rate setpoint for this artifact."""
        return self._setpoint(f"\\epsilon_{{{self._sub()}}}")


@dataclass(frozen=True)
class NetworkConfig:
    """**NetworkConfig** is the normalised view of a resolved (profile, scenario) pair.

    `artifacts` is a list of 13 entries in the positional order given by `environments._nodes[scenario]`. `routing` is the 13x13 matrix aligned with that order.

    Attributes:
        profile (str): profile file stem (`dflt` or `opti`).
        scenario (str): scenario name within the profile.
        label (str): human-readable scenario label (from `_labels`).
        artifacts (List[ArtifactSpec]): 13 resolved artifact specs.
        routing (np.ndarray): 13x13 routing-probability matrix, `row = source`, `col = dest`.
    """

    # :attr: profile
    profile: str
    """Profile file stem (`dflt` or `opti`)."""

    # :attr: scenario
    scenario: str
    """Scenario name within the profile."""

    # :attr: label
    label: str
    """Human-readable scenario label (from `_labels`)."""

    # :attr: artifacts
    artifacts: List[ArtifactSpec]
    """13 resolved artifact specs in positional order."""

    # :attr: routing
    routing: np.ndarray
    """NxN routing-probability matrix (row=source, col=dest)."""

    @property
    def n_nodes(self) -> int:
        """*n_nodes* number of artifacts in this configuration."""
        return len(self.artifacts)

    def node_keys(self) -> List[str]:
        """*node_keys()* returns the artifact keys in positional order.

        Returns:
            List[str]: list of artifact keys aligned with `routing`.
        """
        return [_a.key for _a in self.artifacts]

    def lambda_z_vector(self) -> np.ndarray:
        """*lambda_z_vector()* returns the external arrivals per node.

        Returns:
            np.ndarray: `(n_nodes,)` vector of external arrival rates.
        """
        return np.array([_a.lambda_z for _a in self.artifacts], dtype=float)


def _resolve_source(
    adaptation: Optional[str],
    profile: Optional[str],
    scenario: Optional[str],
) -> Tuple[str, str]:
    """*_resolve_source()* maps the user-facing arguments to the (profile_stem, scenario_name) tuple read from disk.

    Precedence:

        1. Explicit (profile, scenario) wins if both are given.
        2. `adaptation` maps via `_ADAPTATION_TO_SOURCE`.
        3. `profile` alone -> use that profile's `_setpoint` scenario.
        4. Nothing given -> default to `("dflt", "baseline")`.

    Args:
        adaptation (Optional[str]): adaptation value or None.
        profile (Optional[str]): profile file stem or None.
        scenario (Optional[str]): scenario name or None.

    Raises:
        ValueError: If `adaptation` is given but not in the registry.

    Returns:
        Tuple[str, str]: `(profile_stem, scenario_name)`.
    """
    # 1. both explicit -> use as-is
    if profile and scenario:
        return profile, scenario

    # 2. adaptation shorthand -> registry lookup
    if adaptation:
        if adaptation not in _ADAPTATION_TO_SOURCE:
            _allowed = sorted(_ADAPTATION_TO_SOURCE.keys())
            _msg = f"unknown adaptation {adaptation!r}; "
            _msg += f"allowed: {_allowed}"
            raise ValueError(_msg)
        return _ADAPTATION_TO_SOURCE[adaptation]

    # 3. profile only -> read its _setpoint scenario from disk
    if profile:
        _doc = _read_profile(profile)
        return profile, _doc["environments"]["_setpoint"]

    # 4. nothing given -> hard default
    return "dflt", "baseline"


def _read_profile(profile_stem: str) -> Dict[str, Any]:
    """*_read_profile()* loads the raw PACS-style JSON for a profile.

    Args:
        profile_stem (str): profile file stem (e.g. `dflt`, `opti`).

    Raises:
        FileNotFoundError: If the profile file does not exist.

    Returns:
        Dict[str, Any]: parsed JSON envelope.
    """
    _path = _PROFILE_DIR / f"{profile_stem}.json"
    if not _path.exists():
        raise FileNotFoundError(f"profile not found: {_path}")
    with _path.open(encoding="utf-8") as _fh:
        return json.load(_fh)


def load_profile(
    adaptation: Optional[str] = None,
    profile: Optional[str] = None,
    scenario: Optional[str] = None,
) -> NetworkConfig:
    """*load_profile()* loads a resolved `NetworkConfig` for one
    `(profile, scenario)` pair.

    Args:
        adaptation (Optional[str]): one of `baseline`, `s1`, `s2`, `aggregate`. Maps to `(profile, scenario)` via `_ADAPTATION_TO_SOURCE`.
        profile (Optional[str]): profile file stem (`dflt` or `opti`). Overrides `adaptation`'s implied profile if both given with `scenario`.
        scenario (Optional[str]): explicit scenario name within the profile. Defaults to the profile's`environments._setpoint` when absent.

    Raises:
        ValueError: If the scenario is not declared in the profile, or the routing matrix shape does not match the node count.

    Returns:
        NetworkConfig: 13 resolved artifacts + the aligned routing matrix for the requested scenario.
    """
    # resolve user args into a concrete (profile, scenario) pair
    _profile, _scenario = _resolve_source(adaptation, profile, scenario)

    # load the raw envelope and pick out its environments block
    _doc = _read_profile(_profile)
    _env = _doc["environments"]

    # reject scenarios that are not declared in the profile
    if _scenario not in _env["_scenarios"]:
        _msg = f"scenario {_scenario!r} not in {_profile}.json "
        _msg += f"(available: {_env['_scenarios']})"
        raise ValueError(_msg)

    # unpack the per-scenario pieces
    _node_keys = _env["_nodes"][_scenario]
    _routing = np.array(_env["_routs"][_scenario], dtype=float)
    _label = _env["_labels"].get(_scenario, "")

    # resolve each positional slot to a concrete ArtifactSpec
    _artifacts: List[ArtifactSpec] = []
    for _key in _node_keys:
        _a = _doc["artifacts"][_key]
        _artifacts.append(ArtifactSpec(
            key=_key,
            name=_a["name"],
            type_=_a["type"],
            lambda_z=float(_a["lambda_z"]),
            L_z=float(_a["L_z"]),
            vars=_a["vars"],
        ))

    # sanity-check that routing and node count agree
    if _routing.shape != (len(_artifacts), len(_artifacts)):
        _msg = f"routing matrix shape {_routing.shape} does not match "
        _msg += f"node count {len(_artifacts)} for scenario {_scenario!r}"
        raise ValueError(_msg)

    return NetworkConfig(
        profile=_profile,
        scenario=_scenario,
        label=_label,
        artifacts=_artifacts,
        routing=_routing,
    )


def load_method_config(name: str) -> Dict[str, Any]:
    """*load_method_config()* loads `data/config/method/<name>.json` (e.g. `stochastic`, `experiment`).

    Args:
        name (str): method config file stem.

    Raises:
        FileNotFoundError: If the method config does not exist.

    Returns:
        Dict[str, Any]: parsed JSON contents.
    """
    _path = _METHOD_DIR / f"{name}.json"
    if not _path.exists():
        raise FileNotFoundError(f"method config not found: {_path}")
    with _path.open(encoding="utf-8") as _fh:
        return json.load(_fh)


def load_reference(name: str = "baseline") -> Dict[str, Any]:
    """*load_reference()* loads `data/reference/<name>.json`.

    These files hold case-study ground truth or validation targets that must not live inside the Python (e.g. the Camara 2023 R1 / R2 / R3 thresholds in `baseline.json`). Consumed by `src.analytic.metrics` and any other module that needs an external reference value.

    Args:
        name (str): reference file stem. Defaults to `"baseline"`.

    Raises:
        FileNotFoundError: If the reference file does not exist.

    Returns:
        Dict[str, Any]: parsed JSON contents.
    """
    _path = _REFERENCE_DIR / f"{name}.json"
    if not _path.exists():
        raise FileNotFoundError(f"reference file not found: {_path}")
    with _path.open(encoding="utf-8") as _fh:
        return json.load(_fh)

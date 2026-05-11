"""Adaptation strategy pickers + per-operation routing weights.

A picker is a callable `(svc_kind, operation, catalogue) -> list[entry]`. The workflow engine tries entries in order; failures fall through to the next; the last response is always returned to the client so errors are visible.

Four strategies, one per `adp` value (`baseline`, `s1`, `s2`, `aggregate`). Two honour the architectural routing weights from the profile (`baseline`, `s1`); two override them with online reliability ranking (`s2`, `aggregate`).
"""

from __future__ import annotations

import random
from collections import deque
from collections.abc import Callable
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from src.experimental.prototype.target.service.catalogue import (
        ServiceCatalogue,
        ServiceCatalogueEntry,
    )

StrategyPicker = Callable[
    [str, str, "ServiceCatalogue"],
    "list[ServiceCatalogueEntry]",
]


def extract_op_weights(routs: dict[str, list[list[float]]],
                       nodes: list[str],
                       stage_routes: dict[str, dict[str, str]],
                       scenario: str = "baseline") -> dict[str, dict[str, float]]:
    """Pull per-operation routing weights from `_routs[scenario]`.

    For each stage in `stage_routes`, read the row of the routing matrix indexed by that stage and turn its off-diagonal columns into a normalised weight table keyed by the stage's operation.

    Args:
        routs (dict): parsed `_routs` block (`environments._routs`).
        nodes (list[str]): node ids in the order matching the matrix axes.
        stage_routes (dict): `target.json::stage_routes` mapping.
        scenario (str, optional): which scenario to read. Defaults to `"baseline"`.

    Returns:
        dict[str, dict[str, float]]: `{operation: {svc_id: weight}}` with weights summing to 1 per operation.

    Raises:
        KeyError: when `scenario` is missing from `routs`.
    """
    if scenario not in routs:
        _msg = f"_routs has no scenario {scenario!r}; known: {sorted(routs)}"
        raise KeyError(_msg)
    _matrix = routs[scenario]
    _node_idx = {_n: _i for _i, _n in enumerate(nodes)}
    _ans: dict[str, dict[str, float]] = {}
    for _stage_id, _meta in stage_routes.items():
        _op = _operation_or_none(_stage_id, _meta)
        if _op is None:
            continue
        _row_idx = _node_idx.get(_stage_id)
        if _row_idx is None:
            continue
        _weights = _weights_from_row(_matrix[_row_idx], _row_idx, nodes)
        if _weights:
            _ans[_op] = _weights
    return _ans


def _operation_or_none(stage_id: str, meta: object) -> str | None:
    """Return the operation string from one `stage_routes` entry, or None when the entry is metadata or malformed.

    Args:
        stage_id (str): the entry key.
        meta (object): the entry value.

    Returns:
        str | None: operation name when valid; None otherwise.
    """
    _ans: str | None = None
    if not stage_id.startswith("_") and isinstance(meta, dict):
        _op = meta.get("operation")
        if isinstance(_op, str):
            _ans = _op
    return _ans


def _weights_from_row(row: list[float],
                      diagonal_idx: int,
                      nodes: list[str]) -> dict[str, float]:
    """Turn one routing-matrix row into a normalised `{svc_id: weight}` table.

    The diagonal column is dropped (per-service epsilon, not routing). Zero columns are dropped. The remaining weights are normalised to sum to 1.

    Args:
        row (list[float]): one row of the routing matrix.
        diagonal_idx (int): index of the diagonal column.
        nodes (list[str]): node ids matching the column axis.

    Returns:
        dict[str, float]: normalised weight table; empty when the row has no positive off-diagonal entries.
    """
    _weights: dict[str, float] = {}
    for _col_idx, _w in enumerate(row):
        if _col_idx == diagonal_idx:
            continue
        if _w > 0:
            _weights[nodes[_col_idx]] = float(_w)
    _total = sum(_weights.values())
    _ans: dict[str, float] = {}
    if _total > 0:
        _ans = {_k: _v / _total for _k, _v in _weights.items()}
    return _ans


class FirstOfKindPicker:
    """Baseline: one weighted-random pick per `op_weights[operation]`; no retry.

    Maps to `adp="baseline"`. Honours the architectural routing weights so the experimental baseline matches what analytic / dimensional / stochastic predict.
    """

    def __init__(self,
                 *,
                 op_weights: dict[str, dict[str, float]],
                 rng: random.Random | None = None) -> None:
        """Configure the picker.

        Args:
            op_weights (dict): `{operation: {svc_id: weight}}` from `extract_op_weights`.
            rng (random.Random | None, optional): explicit RNG (test seam). Defaults to a fresh `Random()`.
        """
        self._op_weights = op_weights
        if rng is None:
            self._rng = random.Random()
        else:
            self._rng = rng

    def __call__(self,
                 svc_kind: str,
                 operation: str,
                 catalogue: ServiceCatalogue) -> list[ServiceCatalogueEntry]:
        """Return a single-element chain holding the weighted-random pick.

        Args:
            svc_kind (str): catalogue group of the step.
            operation (str): operation key into `op_weights`.
            catalogue (ServiceCatalogue): loaded catalogue.

        Returns:
            list[ServiceCatalogueEntry]: one entry; falls back to `catalogue.by_kind(svc_kind)[0]` when no weights match.
        """
        _weights = self._op_weights.get(operation, {})
        _ans = _weighted_pick_one(weights=_weights,
                                  catalogue=catalogue,
                                  svc_kind=svc_kind,
                                  rng=self._rng)
        return _ans


class RetryOnFailurePicker:
    """S1: weighted-random pick, then weighted-random retries over remaining equivalents up to `max_attempts` total.

    Maps to `adp="s1"`. Honours the architectural weights both for the first pick and for each retry (the failed svc_id is dropped, the remaining weights are renormalised, and another weighted-random pick is drawn).
    """

    def __init__(self,
                 *,
                 op_weights: dict[str, dict[str, float]],
                 max_attempts: int,
                 rng: random.Random | None = None) -> None:
        """Configure the picker.

        Args:
            op_weights (dict): per-operation weights from `extract_op_weights`.
            max_attempts (int): total tries; 1 disables retry.
            rng (random.Random | None, optional): explicit RNG. Defaults to a fresh `Random()`.
        """
        self._op_weights = op_weights
        self._max_attempts = max_attempts
        if rng is None:
            self._rng = random.Random()
        else:
            self._rng = rng

    def __call__(self,
                 svc_kind: str,
                 operation: str,
                 catalogue: ServiceCatalogue) -> list[ServiceCatalogueEntry]:
        """Return up to `max_attempts` weighted-random draws without replacement.

        Args:
            svc_kind (str): catalogue group of the step.
            operation (str): operation key into `op_weights`.
            catalogue (ServiceCatalogue): loaded catalogue.

        Returns:
            list[ServiceCatalogueEntry]: ordered chain; falls back to `catalogue.by_kind(svc_kind)` truncated to `max_attempts` when no weights match.
        """
        _weights = dict(self._op_weights.get(operation, {}))
        _by_id = {_e.svc_id: _e for _e in catalogue.entries.values()}
        _chain: list[ServiceCatalogueEntry] = []
        _attempts_left = self._max_attempts
        while _attempts_left > 0 and _weights:
            _ids = [_k for _k in _weights if _k in _by_id]
            if not _ids:
                _weights = {}
                continue
            _ws = [_weights[_k] for _k in _ids]
            _picked = self._rng.choices(_ids, weights=_ws, k=1)[0]
            _chain.append(_by_id[_picked])
            _weights.pop(_picked, None)
            _attempts_left -= 1
        if not _chain:
            _chain = list(catalogue.by_kind(svc_kind))[:self._max_attempts]
        return _chain


class PreferReliablePicker:
    """S2: argmin observed failure rate over the equivalent set; no retry.

    Maps to `adp="s2"`. Ignores `_routs`. Reliability is observed online via `observe(svc_id, success)` over a rolling window; the picker biases toward the most-reliable equivalent service.
    """

    def __init__(self, *, window_size: int) -> None:
        """Configure the picker.

        Args:
            window_size (int): max observations kept per svc_id.
        """
        self._window_size = window_size
        self._observations: dict[str, deque[bool]] = {}

    def observe(self, svc_id: str, success: bool) -> None:
        """Record one attempt outcome for `svc_id`.

        The workflow engine calls this after each attempt. Maintains a rolling window of the last `window_size` outcomes per service.

        Args:
            svc_id (str): id of the service that handled the attempt.
            success (bool): True if the attempt returned a 2xx with no `error` body.
        """
        _w = self._observations.get(svc_id)
        if _w is None:
            _w = deque(maxlen=self._window_size)
            self._observations[svc_id] = _w
        _w.append(success)

    def failure_rate(self, svc_id: str) -> float:
        """Return the observed failure rate for `svc_id` over the rolling window.

        Args:
            svc_id (str): catalogue key.

        Returns:
            float: failures divided by observations; 0 when no observations exist yet, so unseen services tie for best until they fail.
        """
        _w = self._observations.get(svc_id)
        _ans = 0.0
        if _w:
            _failures = sum(1 for _s in _w if not _s)
            _ans = _failures / len(_w)
        return _ans

    def __call__(self,
                 svc_kind: str,
                 operation: str,
                 catalogue: ServiceCatalogue) -> list[ServiceCatalogueEntry]:
        """Return a single-element chain with the most-reliable equivalent service.

        Args:
            svc_kind (str): catalogue group of the step.
            operation (str): ignored.
            catalogue (ServiceCatalogue): loaded catalogue.

        Returns:
            list[ServiceCatalogueEntry]: one entry; empty when the catalogue has no service of that kind.
        """
        del operation
        _candidates = list(catalogue.by_kind(svc_kind))
        _ans: list[ServiceCatalogueEntry] = []
        if _candidates:
            _ranked = sorted(_candidates, key=lambda _e: self.failure_rate(_e.svc_id))
            _ans = [_ranked[0]]
        return _ans


class RetryAndPreferReliablePicker:
    """Aggregate: reliability-ranked chain truncated to `max_attempts`; ignores `_routs`.

    Maps to `adp="aggregate"`. Same online reliability tracking as `PreferReliablePicker`, but returns the whole ranked chain so the engine retries best, then second-best, then onward.
    """

    def __init__(self, *, max_attempts: int, window_size: int) -> None:
        """Configure the picker.

        Args:
            max_attempts (int): total tries.
            window_size (int): max observations kept per svc_id.
        """
        self._max_attempts = max_attempts
        self._window_size = window_size
        self._observations: dict[str, deque[bool]] = {}

    def observe(self, svc_id: str, success: bool) -> None:
        """Record one attempt outcome for `svc_id`.

        Args:
            svc_id (str): id of the service that handled the attempt.
            success (bool): True if the attempt returned a 2xx with no `error` body.
        """
        _w = self._observations.get(svc_id)
        if _w is None:
            _w = deque(maxlen=self._window_size)
            self._observations[svc_id] = _w
        _w.append(success)

    def failure_rate(self, svc_id: str) -> float:
        """Return the observed failure rate for `svc_id` over the rolling window.

        Args:
            svc_id (str): catalogue key.

        Returns:
            float: failures divided by observations; 0 when no observations exist yet.
        """
        _w = self._observations.get(svc_id)
        _ans = 0.0
        if _w:
            _failures = sum(1 for _s in _w if not _s)
            _ans = _failures / len(_w)
        return _ans

    def __call__(self,
                 svc_kind: str,
                 operation: str,
                 catalogue: ServiceCatalogue) -> list[ServiceCatalogueEntry]:
        """Return the reliability-ranked equivalent set truncated to `max_attempts`.

        Args:
            svc_kind (str): catalogue group of the step.
            operation (str): ignored.
            catalogue (ServiceCatalogue): loaded catalogue.

        Returns:
            list[ServiceCatalogueEntry]: best first; empty when the catalogue has no service of that kind.
        """
        del operation
        _candidates = list(catalogue.by_kind(svc_kind))
        _ans: list[ServiceCatalogueEntry] = []
        if _candidates:
            _ranked = sorted(_candidates, key=lambda _e: self.failure_rate(_e.svc_id))
            _ans = _ranked[:self._max_attempts]
        return _ans


def _weighted_pick_one(*,
                       weights: dict[str, float],
                       catalogue: ServiceCatalogue,
                       svc_kind: str,
                       rng: random.Random) -> list[ServiceCatalogueEntry]:
    """Draw one weighted-random pick. Fall back to `catalogue.by_kind(svc_kind)[0]` when no usable weights exist.

    Args:
        weights (dict[str, float]): `{svc_id: weight}` table.
        catalogue (ServiceCatalogue): loaded catalogue.
        svc_kind (str): kind used for the fallback.
        rng (random.Random): explicit RNG.

    Returns:
        list[ServiceCatalogueEntry]: single-element list with the picked entry; empty only when the catalogue has no entry for the kind.
    """
    _by_id = {_e.svc_id: _e for _e in catalogue.entries.values()}
    _ids = [_k for _k in weights if _k in _by_id]
    _ans: list[ServiceCatalogueEntry] = []
    if _ids:
        _ws = [weights[_k] for _k in _ids]
        _picked = rng.choices(_ids, weights=_ws, k=1)[0]
        _ans = [_by_id[_picked]]
    else:
        _by_kind = list(catalogue.by_kind(svc_kind))
        if _by_kind:
            _ans = [_by_kind[0]]
    return _ans


_ADP_TO_PICKER_NAME: dict[str, str] = {
    "baseline": "first_of_kind",
    "s1": "retry_on_failure",
    "s2": "prefer_reliable",
    "aggregate": "retry_and_prefer_reliable",
}


def picker_name_for(adp: str) -> str:
    """Return the wire name for the picker that `adp` resolves to.

    Args:
        adp (str): `baseline` / `s1` / `s2` / `aggregate`.

    Returns:
        str: matching picker wire name (used by TAS_1's `/config` payload).

    Raises:
        KeyError: when `adp` is unknown.
    """
    if adp not in _ADP_TO_PICKER_NAME:
        _msg = f"unknown adp {adp!r}; expected one of {sorted(_ADP_TO_PICKER_NAME)}"
        raise KeyError(_msg)
    _ans = _ADP_TO_PICKER_NAME[adp]
    return _ans


def make_picker(adp: str,
                *,
                op_weights: dict[str, dict[str, float]],
                max_attempts: int,
                window_size: int,
                rng: random.Random | None = None) -> StrategyPicker:
    """Build the picker matching `adp`.

    Args:
        adp (str): `baseline` / `s1` / `s2` / `aggregate`.
        op_weights (dict): per-operation routing weights. Honoured by baseline / s1; ignored by s2 / aggregate.
        max_attempts (int): total attempts for retry-capable pickers.
        window_size (int): rolling-window size for reliability-aware pickers.
        rng (random.Random | None, optional): RNG seam for weighted-random pickers.

    Returns:
        StrategyPicker: picker instance whose `__call__` matches the engine's contract.
    """
    _name = picker_name_for(adp)
    _ans = picker_from_wire(_name,
                            op_weights=op_weights,
                            max_attempts=max_attempts,
                            window_size=window_size,
                            rng=rng)
    return _ans


def picker_from_wire(name: str,
                     *,
                     op_weights: dict[str, dict[str, float]],
                     max_attempts: int,
                     window_size: int,
                     rng: random.Random | None = None) -> StrategyPicker:
    """Build a picker from its wire name (consumed by TAS_1's `POST /config`).

    Args:
        name (str): one of `first_of_kind` / `retry_on_failure` / `prefer_reliable` / `retry_and_prefer_reliable`.
        op_weights (dict): per-operation weights (only used by `_routs`-honouring pickers).
        max_attempts (int): total attempts for retry-capable pickers.
        window_size (int): rolling-window size for reliability-aware pickers.
        rng (random.Random | None, optional): RNG seam.

    Returns:
        StrategyPicker: configured picker instance.

    Raises:
        ValueError: when `name` is not a known wire name.
    """
    if name == "first_of_kind":
        _ans: StrategyPicker = FirstOfKindPicker(op_weights=op_weights, rng=rng)
    elif name == "retry_on_failure":
        _ans = RetryOnFailurePicker(op_weights=op_weights,
                                    max_attempts=max_attempts,
                                    rng=rng)
    elif name == "prefer_reliable":
        _ans = PreferReliablePicker(window_size=window_size)
    elif name == "retry_and_prefer_reliable":
        _ans = RetryAndPreferReliablePicker(max_attempts=max_attempts,
                                            window_size=window_size)
    else:
        _msg = (f"unknown picker name {name!r}; expected one of "
                f"{sorted(_ADP_TO_PICKER_NAME.values())}")
        raise ValueError(_msg)
    return _ans


__all__ = [
    "FirstOfKindPicker",
    "PreferReliablePicker",
    "RetryAndPreferReliablePicker",
    "RetryOnFailurePicker",
    "StrategyPicker",
    "extract_op_weights",
    "make_picker",
    "picker_from_wire",
    "picker_name_for",
]

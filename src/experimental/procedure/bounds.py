"""Guard that refuses to run an experiment beyond its configured operating ceiling.

`validate_experimental_limits` checks the planned `(c, r, w)` against the `c_max` / `r_max` / `w_max` ceiling from `experimental.json::trial` and either raises or returns a per-axis report. The ceiling lives in the experiment's own config, so the check consults no calibration-envelope file.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


class EnvelopeExceededError(RuntimeError):
    """Raised when a check fails and `raise_on_fail=True`."""


@dataclass(frozen=True)
class BoundCheck:
    """One per-axis verdict.

    Attributes:
        axis (str): `c`, `r`, or `w`.
        requested (float | None): planned value, or None if not requested.
        limit (float | None): configured ceiling, or None if the config set no ceiling on this axis.
        passed (bool): True when the request fits, or when either side is missing (no constraint).
        message (str): human-readable verdict.
    """

    axis: str
    requested: float | None
    limit: float | None
    passed: bool
    message: str


@dataclass(frozen=True)
class BoundsReport:
    """Per-axis verdicts for one validation pass.

    Attributes:
        passed (bool): True only if every axis passes.
        checks (list[BoundCheck]): per-axis verdicts.
    """

    passed: bool
    checks: list[BoundCheck] = field(default_factory=list)


def validate_experimental_limits(exp_cfg: dict[str, Any],
                                 limits: dict[str, Any],
                                 *,
                                 raise_on_fail: bool = True) -> BoundsReport:
    """Check the planned operating point against the configured ceiling.

    Reads `c`, `r`, `w` from `exp_cfg` (any may be omitted) and `c_max`, `r_max`, `w_max` from `limits` (the `experimental.json::trial` ceiling block). Each axis is checked independently; a missing request or ceiling skips that axis.

    Args:
        exp_cfg (dict[str, Any]): planned operating point (`c`, `r`, `w`).
        limits (dict[str, Any]): configured ceiling (`c_max`, `r_max`, `w_max`).
        raise_on_fail (bool, optional): raise on the first failing axis. Defaults to True.

    Returns:
        BoundsReport: per-axis verdicts.

    Raises:
        EnvelopeExceededError: any axis fails and `raise_on_fail=True`.
    """
    _checks: list[BoundCheck] = [
        _check_axis(axis="c",
                    requested=_get_float(exp_cfg, "c"),
                    limit=_get_float(limits, "c_max")),
        _check_axis(axis="r",
                    requested=_get_float(exp_cfg, "r"),
                    limit=_get_float(limits, "r_max")),
        _check_axis(axis="w",
                    requested=_get_float(exp_cfg, "w"),
                    limit=_get_float(limits, "w_max")),
    ]
    _pass = all(_c.passed for _c in _checks)
    _report = BoundsReport(passed=_pass, checks=_checks)
    if not _pass and raise_on_fail:
        _failed: list[BoundCheck] = []
        for _check in _checks:
            if not _check.passed:
                _failed.append(_check)
        _msg = "experiment exceeds configured ceiling: " + "; ".join(_c.message for _c in _failed)
        raise EnvelopeExceededError(_msg)
    return _report


def _get_float(source: dict[str, Any], key: str) -> float | None:
    """Return `source[key]` coerced to float, or None if absent / non-numeric.

    Args:
        source (dict[str, Any]): dict to read from.
        key (str): key to look up.

    Returns:
        float | None: the value as a float, or None when it is missing, a bool, or not a number.
    """
    _val = source.get(key)
    _ans: float | None = None
    if _val is None:
        _ans = None
    elif isinstance(_val, bool):
        _ans = None
    elif isinstance(_val, (int, float)):
        _ans = float(_val)
    return _ans


def _check_axis(axis: str,
                requested: float | None,
                limit: float | None) -> BoundCheck:
    """Return the verdict for one axis's `(requested, limit)` pair.

    Args:
        axis (str): axis label (`c`, `r`, or `w`).
        requested (float | None): planned value, or None when not requested.
        limit (float | None): configured ceiling, or None when no ceiling is set.

    Returns:
        BoundCheck: the per-axis verdict; passes when the request fits or either side is missing.
    """
    _pass: bool = True
    _msg: str = ""
    if requested is None:
        _msg = f"{axis}: not requested; skipping"
    elif limit is None:
        _msg = f"{axis}: config set no ceiling; skipping"
    elif requested <= limit:
        _msg = f"{axis}: requested {requested:g} <= ceiling {limit:g}"
    else:
        _pass = False
        _msg = f"{axis}: requested {requested:g} > ceiling {limit:g}"
    return BoundCheck(axis=axis,
                      requested=requested,
                      limit=limit,
                      passed=_pass,
                      message=_msg)


__all__ = [
    "BoundCheck",
    "BoundsReport",
    "EnvelopeExceededError",
    "validate_experimental_limits",
]

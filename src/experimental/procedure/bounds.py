"""Refuse to run an experiment that would exceed the calibration envelope.

Calibration records the apparatus's verifiable operating range:

- `c_max`: handler-scaling knee (per-worker concurrent in-flight requests).
- `r_max_req_s`: per-worker rate-saturation knee (req/s).
- `w_max`: parallel-workers knee (process count).

`validate_experimental_limits` checks the planned `(c, r, w)` against those limits and either raises or returns a per-axis report. It is the procedure-side guard that keeps the experiment honest about what it can claim to measure.
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
        limit (float | None): envelope cap, or None if the envelope did not record one.
        passed (bool): True when the request fits, when either side is missing (no constraint), or the calibration disabled the check.
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
        envelope_run_id (str | None): id of the envelope used, for traceability.
    """

    passed: bool
    checks: list[BoundCheck] = field(default_factory=list)
    envelope_run_id: str | None = None


def validate_experimental_limits(exp_cfg: dict[str, Any],
                                 envelope: dict[str, Any],
                                 *,
                                 raise_on_fail: bool = True) -> BoundsReport:
    """Check the planned operating point against the calibration envelope.

    Reads `c`, `r`, `w` from `exp_cfg` (any may be omitted) and `gate.verifiable_range.{c_max, r_max_req_s, w_max}` from `envelope`. Each axis is checked independently; a missing request or limit skips that axis.

    Args:
        exp_cfg (dict[str, Any]): experiment knobs (`c`, `r`, `w`).
        envelope (dict[str, Any]): calibration envelope.
        raise_on_fail (bool, optional): raise on the first failing axis. Defaults to True.

    Returns:
        BoundsReport: per-axis verdicts.

    Raises:
        EnvelopeExceededError: any axis fails and `raise_on_fail=True`.
    """
    _gate = envelope.get("gate") or {}
    _range = _gate.get("verifiable_range") or {}
    _checks: list[BoundCheck] = [
        _check_axis(axis="c",
                    requested=_get_float(exp_cfg, "c"),
                    limit=_get_float(_range, "c_max")),
        _check_axis(axis="r",
                    requested=_get_float(exp_cfg, "r"),
                    limit=_get_float(_range, "r_max_req_s")),
        _check_axis(axis="w",
                    requested=_get_float(exp_cfg, "w"),
                    limit=_get_float(_range, "w_max")),
    ]
    _pass = all(_c.passed for _c in _checks)
    _report = BoundsReport(passed=_pass,
                           checks=_checks,
                           envelope_run_id=envelope.get("run_id"))
    if not _pass and raise_on_fail:
        _failed = [_c for _c in _checks if not _c.passed]
        _msg = "experiment exceeds calibration envelope: " + "; ".join(_c.message for _c in _failed)
        raise EnvelopeExceededError(_msg)
    return _report


def _get_float(source: dict[str, Any], key: str) -> float | None:
    """Return `source[key]` as a float, or None if missing / non-numeric."""
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
    """Verdict on one `(requested, limit)` pair."""
    _pass: bool = True
    _msg: str = ""
    if requested is None:
        _msg = f"{axis}: not requested; skipping"
    elif limit is None:
        _msg = f"{axis}: envelope did not record a limit; skipping"
    elif requested <= limit:
        _msg = f"{axis}: requested {requested:g} <= envelope {limit:g}"
    else:
        _pass = False
        _msg = f"{axis}: requested {requested:g} > envelope {limit:g}"
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

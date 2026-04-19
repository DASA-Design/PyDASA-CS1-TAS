"""Config-driven derivation of operationally meaningful coefficients."""

from __future__ import annotations

import re
from typing import Any

from pydasa.workflows.phenomena import AnalysisEngine

_PI_PATTERN = re.compile(r"\{pi\[(\d+)\]\}")


def _resolve_expr(expr_pattern: str, pi_keys: list[str]) -> str:
    """Substitute `{pi[i]}` placeholders with the i-th Pi coefficient key.

    Example: `"{pi[1]}**(-1) * {pi[2]}"` with pi_keys=["\\Pi_{0}", "\\Pi_{1}", "\\Pi_{2}"]
    -> `"\\Pi_{1}**(-1) * \\Pi_{2}"`.
    """
    def _sub(match: re.Match[str]) -> str:
        _i = int(match.group(1))
        if _i >= len(pi_keys):
            raise IndexError(
                f"expr_pattern references pi[{_i}] but only {len(pi_keys)} "
                "Pi-groups were derived; check variable/FDU counts."
            )
        return pi_keys[_i]

    return _PI_PATTERN.sub(_sub, expr_pattern)


def derive_coefficients(
    engine: AnalysisEngine,
    specs: list[dict[str, Any]],
    *,
    artifact_key: str,
) -> dict[str, Any]:
    """Derive named coefficients from an engine's Pi-groups per the spec list.

    Must be called AFTER `engine.run_analysis()`.

    Args:
        engine: AnalysisEngine with Pi-groups already derived.
        specs: list of coefficient specs from `dimensional.json`. Each spec has
            `symbol` (e.g. "theta"), `expr_pattern` (with `{pi[i]}` placeholders),
            `name`, `description`. The symbol is suffixed with the artifact key
            so the final coefficient symbol becomes `\\theta_{TAS_{1}}`.
        artifact_key: artifact identifier in LaTeX subscript form.

    Returns:
        Dict `{full_symbol: Coefficient}` for the derived coefficients only
        (not the raw Pi-groups, which remain in `engine.coefficients`).
    """
    _pi_keys = [k for k in engine.coefficients.keys() if k.startswith("\\Pi_")]
    _derived: dict[str, Any] = {}

    for _spec in specs:
        _symbol = _spec["symbol"]
        _full_sym = f"\\{_symbol}_{{{artifact_key}}}"
        _expr = _resolve_expr(_spec["expr_pattern"], _pi_keys)

        _coeff = engine.derive_coefficient(
            expr=_expr,
            symbol=_full_sym,
            name=f"{artifact_key} {_spec['name']} coefficient",
            description=_spec["description"],
            idx=-1,
        )
        _derived[_full_sym] = _coeff

    return _derived

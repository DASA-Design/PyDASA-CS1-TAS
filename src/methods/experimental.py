# -*- coding: utf-8 -*-
"""Experimental method facade.

Thin CLI + notebook entry. Two things to run, one CLI:

- `run_calibration` measures the host floor and writes a calibration envelope.
- `run_experiment` mounts the TAS service mesh, drives a trial, writes the per-request flow + per-service CSV + summary row.

`run(stage=...)` picks one or both. CLI::

    python -m src.methods.experimental --stage calibration --dpl localhost
    python -m src.methods.experimental --stage experiment --adaptation baseline --dpl multiprocess

All business logic lives under `src.experimental.procedure.{experiment,tuning}`; this module re-exports the public surface (plus the private helpers tests reach into via attribute access on `experimental.<symbol>`) so existing callers keep working unchanged.
"""

from __future__ import annotations

import argparse
from typing import Any, cast

from src.experimental.procedure.bounds import BoundsReport
from src.experimental.procedure.deployment import (
    Dpl,
    Framework,
    WsgiServer,
)
# Public surface re-exports + private symbols the test harness patches via
# `monkeypatch.setattr(experimental, "<name>", ...)`. The functions themselves
# live in `procedure.experiment` / `procedure.tuning`; importing them here keeps
# the historical `from src.methods.experimental import ...` import paths alive.
from src.experimental.procedure.experiment import (
    _INTERNAL_STAGE_IDS,
    _STOP_PREDICATES,
    _admission_lt_from_profile,
    _build_mesh_admission,
    _build_mesh_specs,
    _check_breach,
    _consume_payloads,
    _count_outcomes,
    _dispatch_at_rate,
    _drive_trial,
    _eps_lt_from_profile,
    _fetch_controller_history,
    _maybe_check_bounds,
    _mu_lt_from_profile,
    _op_weights_from_profile,
    _resolve_admission,
    _resolve_granularity_for_paths,
    _should_stop_from_aggregates,
    _thresholds_from_reference,
    _variant_suffix_for,
    _workers_lt_from_profile,
    run_experiment,
)
from src.experimental.procedure.experiment import User  # type: ignore[attr-defined]  # noqa: F401  (test monkeypatch target)
from src.experimental.procedure.tuning import (
    _BringUpFactory,
    _run_workers_scaling,
    find_latest_envelope,
    run_calibration,
)

__all__ = [
    "BoundsReport",
    "Dpl",
    "Framework",
    "WsgiServer",
    "find_latest_envelope",
    "main",
    "run",
    "run_calibration",
    "run_experiment",
]


def run(*,
        stage: str = "calibration",
        adp: str = "baseline",
        dpl: Dpl = "localhost",
        framework: Framework = "fastapi",
        wsgi_server: WsgiServer = "waitress",
        write: bool = True,
        run_id: str | None = None,
        cfg: dict[str, Any] | None = None,
        skip_bounds_check: bool = False,
        target_granularity: str | None = None,
        inject_internal_stage_mu: bool | None = None) -> dict[str, Any]:
    """Run calibration, an experiment trial, or both.

    Args:
        stage (str, optional): `"calibration"`, `"experiment"`, or `"both"`. Defaults to `"calibration"`.
        adp (str, optional): adaptation key (used by experiment stages). Defaults to `"baseline"`.
        dpl (Dpl, optional): deployment mode.
        framework (Framework, optional): server stack.
        wsgi_server (WsgiServer, optional): WSGI engine when `framework="flask"`.
        write (bool, optional): persist outputs to disk. Defaults to True.
        run_id (str | None, optional): explicit run id.
        cfg (dict[str, Any] | None, optional): pre-loaded calibration config (calibration stages only).
        skip_bounds_check (bool, optional): skip the envelope check (experiment stages only). Defaults to False.
        target_granularity (str | None, optional): `collapsed` / `expanded` override (experiment stages only). None falls through to `target.json`.
        inject_internal_stage_mu (bool | None, optional): TAS_{2..6} mu-sleep override (experiment stages only). None falls through to `target.json`.

    Returns:
        dict[str, Any]: envelope, experiment summary, or `{"calibration": ..., "experiment": ...}`.

    Raises:
        ValueError: on an unknown stage.
    """
    if stage == "calibration":
        return run_calibration(dpl=dpl,
                               framework=framework,
                               wsgi_server=wsgi_server,
                               write=write,
                               run_id=run_id,
                               cfg=cfg)
    if stage == "experiment":
        return run_experiment(adp=adp,
                              dpl=dpl,
                              framework=framework,
                              wsgi_server=wsgi_server,
                              write=write,
                              run_id=run_id,
                              skip_bounds_check=skip_bounds_check,
                              target_granularity=target_granularity,
                              inject_internal_stage_mu=inject_internal_stage_mu)
    if stage == "both":
        _calib = run_calibration(dpl=dpl,
                                 framework=framework,
                                 wsgi_server=wsgi_server,
                                 write=write,
                                 run_id=run_id,
                                 cfg=cfg)
        _exp = run_experiment(adp=adp,
                              dpl=dpl,
                              framework=framework,
                              wsgi_server=wsgi_server,
                              write=write,
                              envelope=_calib,
                              skip_bounds_check=skip_bounds_check,
                              target_granularity=target_granularity,
                              inject_internal_stage_mu=inject_internal_stage_mu)
        return {"calibration": _calib, "experiment": _exp}
    _msg = f"unknown stage {stage!r}; expected 'calibration', 'experiment', or 'both'"
    raise ValueError(_msg)


def main() -> None:
    """CLI entry: parse flags and run the chosen stage."""
    _parser = argparse.ArgumentParser(prog="src.methods.experimental",
                                      description="Experimental method orchestrator (calibration + experiment).")
    _parser.add_argument("--stage",
                         choices=["calibration", "experiment", "both"],
                         default="calibration")
    _parser.add_argument("--adaptation",
                         choices=["baseline", "s1", "s2", "aggregate"],
                         default="baseline",
                         dest="adp")
    _parser.add_argument("--dpl",
                         choices=["localhost", "multiprocess", "remote"],
                         default="localhost")
    _parser.add_argument("--framework",
                         choices=["fastapi", "flask"],
                         default="fastapi")
    _parser.add_argument("--wsgi-server",
                         choices=["waitress", "gunicorn"],
                         default="waitress",
                         dest="wsgi_server")
    _parser.add_argument("--write",
                         action=argparse.BooleanOptionalAction,
                         default=True)
    _parser.add_argument("--skip-bounds-check",
                         action="store_true",
                         dest="skip_bounds_check")
    _parser.add_argument("--target-granularity",
                         choices=["collapsed", "expanded"],
                         dest="target_granularity",
                         default=None,
                         help="override target.json::target_granularity for the experiment stage.")
    _parser.add_argument("--inject-internal-stage-mu",
                         action=argparse.BooleanOptionalAction,
                         dest="inject_internal_stage_mu",
                         default=None,
                         help="override target.json::inject_internal_stage_mu for the experiment stage.")
    _args = _parser.parse_args()
    # argparse `choices=...` constrains the value at runtime to the literal set,
    # but the static type stays `str`; cast back to the Literal aliases the run()
    # signature expects.
    _result = run(stage=str(_args.stage),
                  adp=str(_args.adp),
                  dpl=cast(Dpl, _args.dpl),
                  framework=cast(Framework, _args.framework),
                  wsgi_server=cast(WsgiServer, _args.wsgi_server),
                  write=bool(_args.write),
                  skip_bounds_check=bool(_args.skip_bounds_check),
                  target_granularity=_args.target_granularity,
                  inject_internal_stage_mu=_args.inject_internal_stage_mu)
    if _args.stage == "calibration":
        _print_calibration_report(_result)
    elif _args.stage == "experiment":
        _print_experiment_summary(_result)
    else:
        _print_calibration_report(_result["calibration"])
        _print_experiment_summary(_result["experiment"])


_REPORT_LEGEND_LINES = (
    "Latency:  Reported figures equal the measured value\nminus the loopback floor (median), \nwith the jitter p99 as the precision band.",
    "Floors:   Background noise sources we cannot control \n(clock, scheduler, kernel TCP path); \nthe precision band is their RMS sum.",
    "Envelope: Operating limits where the apparatus's measurements\n remain trustworthy (concurrency knee + rate saturation knee).",
)

# Mathtext-to-terminal substitutions: gate.summary headlines use mathtext (`$\pm$`, `$\mu$s`,
# `$\leq$`) so they render correctly in the matplotlib panel; for stdout we swap them for the
# Unicode glyphs that any modern terminal can display.
_TERMINAL_SUBSTITUTIONS = (
    (r"$\pm$", "+/-"),
    (r"$\mu$s", "us"),
    (r"$\mu$", "u"),
    (r"$\leq$", "<="),
)


def _to_terminal(text: str) -> str:
    """Render a mathtext headline as plain text for the terminal.

    Args:
        text (str): headline that may contain mathtext (e.g. `$\\pm$ 0.05 $\\mu$s`).

    Returns:
        str: ASCII / Unicode equivalent (e.g. `+/- 0.05 us`).
    """
    _ans = text
    for _src, _dst in _TERMINAL_SUBSTITUTIONS:
        _ans = _ans.replace(_src, _dst)
    # Strip any leftover bare `$...$` mathtext segments (e.g. `$c=8$` -> `c=8`).
    _ans = _ans.replace("$", "")
    return _ans


def _print_calibration_report(envelope: dict[str, Any]) -> None:
    """Print the calibration report (matches the figure's Report panel layout).

    Args:
        envelope (dict[str, Any]): populated calibration envelope (must include `gate`).
    """
    _gate = envelope["gate"]
    _band = (_gate.get("precision_band_us") or {}).get("total_us")
    _range = _gate.get("verifiable_range", {}) or {}
    _summary = _gate.get("summary", {}) or {}
    _c_max = _range.get("c_max")
    _r_max = _range.get("r_max_req_s")
    _w_max = _range.get("w_max")

    if _band is None:
        _band_str = "n/a"
    else:
        _band_str = f"+/- {_band:.2f} us"
    if _c_max is None:
        _c_str = "n/a"
    else:
        _c_str = f"c <= {int(_c_max)}"
    if _r_max is None:
        _r_str = "n/a"
    else:
        _r_str = f"r <= {int(_r_max)} req/s"
    if _w_max is None:
        _w_str = "n/a"
    else:
        _w_str = f"w <= {int(_w_max)}"

    print()
    print(f"host: {envelope.get('host', '?')}     dpl: {envelope.get('dpl', '?')}")
    print(f"run:  {envelope.get('run_id', '?')}")
    print(f"Allowed noise floor: +/- {_gate['noise_floor_pct']:.1f} %")
    print()
    print(f"Precision band   {_band_str}")
    print()
    print(f"Operating range  {_c_str}")
    print(f"                 {_r_str}")
    print(f"                 {_w_str}")
    print()
    print("Floors")
    for _name, _label in (("timer", "Timer"), ("jitter", "Jitter"), ("loopback", "Loopback")):
        _hl = _to_terminal(_summary.get(_name, {}).get("headline", "n/a"))
        print(f"   {_label:<11} {_hl}")
    print()
    print("Envelope")
    for _name, _label in (("scaling", "Scaling"), ("rate", "Rate sweep"), ("workers", "Workers")):
        _hl = _to_terminal(_summary.get(_name, {}).get("headline", "n/a"))
        print(f"   {_label:<11} {_hl}")
    print()
    print("-" * 64)
    for _line in _REPORT_LEGEND_LINES:
        print(_line)


def _print_experiment_summary(result: dict[str, Any]) -> None:
    """Print one experiment-run summary block.

    Args:
        result (dict[str, Any]): dict returned by `run_experiment(...)`.
    """
    _counts = result.get("outcome_counts", {})
    _bounds: BoundsReport | None = result.get("bounds")
    print()
    print(f"adp:  {result.get('adp', '?')}     dpl: {result.get('dpl', '?')}")
    print(f"run:  {result.get('run_id', '?')}")
    print(f"requests: {result.get('n_requests', 0)}")
    print(f"  success: {_counts.get('success', 0)}")
    print(f"  timeout: {_counts.get('timeout', 0)}")
    print(f"  drop:    {_counts.get('drop', 0)}")
    print(f"  5xx:     {_counts.get('5xx', 0)}")
    print()
    print("paths:")
    for _label, _path in (result.get("paths") or {}).items():
        print(f"  {_label:<13} {_path}")
    if _bounds is not None:
        print()
        print(f"envelope:        run={_bounds.envelope_run_id}  passed={_bounds.passed}")
        for _check in _bounds.checks:
            print(f"  {_check.message}")


if __name__ == "__main__":
    main()

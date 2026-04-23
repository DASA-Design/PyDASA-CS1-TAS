# -*- coding: utf-8 -*-
"""
demo_rate.py
============

Inspect how accurately the client drives target rates against the in-process
mesh. For each target rate in a sweep, runs N short single-probe experiments
and prints, per trial:

    - effective client rate (`client_effective_rate` from run envelope)
    - measured TAS_{1} lambda (operational `A / T` from the per-node DF)
    - gap = target - effective; loss% = gap / target

The two effective values should match exactly: every request the client
issues lands at the entry service `TAS_{1}`. A growing target-effective
gap means we are hitting the mesh's sustainable-throughput ceiling
(asyncio chain saturation, httpx pool, OS-timer floor).

The sweep also reports the auto-batch K used by `_probe_at_rate` at each
rate (batch size derived from `_TARGET_TICK_S / interarrival`), so you can
correlate loss with batch behaviour.

Calibration mode (`--calibrate <pct>`) sweeps targets and reports the
highest rate whose mean loss is below `pct`% across `--trials` trials.
Useful for picking a notebook ramp rate that the prototype can actually
sustain.

Run:
    # default sweep, 3 trials per rate, baseline adaptation
    python src/scripts/demo_rate.py

    # custom rate list + adaptation
    python src/scripts/demo_rate.py --rates 50,100,200,345 --adp baseline

    # find the highest rate the mesh sustains at <= 1% loss
    python src/scripts/demo_rate.py --calibrate 1.0

    # tighter sample requirement per trial
    python src/scripts/demo_rate.py --rates 200 --trials 5 --samples 64
"""
# native python modules
import argparse
import sys
from pathlib import Path
from typing import Optional

import nest_asyncio


_HERE = Path(__file__).resolve()
_ROOT = _HERE.parents[2]
sys.path.insert(0, str(_ROOT))

# noqa imports below run AFTER sys.path tweak
from src.io import load_method_cfg, load_profile             # noqa: E402
from src.methods.experiment import run as run_experiment    # noqa: E402


nest_asyncio.apply()


# default rate sweep stays in the regime where the mesh does not
# saturate (loss <= 2 % per trial). Higher rates (345/500) are still
# available via `--rates 50,100,200,345,500` but they push the executor
# pool + httpx connection pool hard, spin the CPU fan, and the high-rate
# trials usually fail the <= 1 % accuracy bar anyway -- not useful as a
# default. See `notes/devlog.md` for the rate-vs-loss bench numbers.
_DEFAULT_RATES = [50, 100, 200]
_DEFAULT_ADAPTATION = "baseline"
_DEFAULT_TRIALS = 3
_DEFAULT_SAMPLES = 32
_DEFAULT_PROBE_S = 4.0

# must mirror src.experiment.client._probe_at_rate's _TARGET_TICK_S so the
# K column the demo prints matches what the run actually uses
_TARGET_TICK_S = 0.020


def _banner(s: str) -> None:
    """*_banner()* print a centred header band to stdout."""
    print()
    print("=" * 78)
    print(f"  {s}")
    print("=" * 78)


def _parse_rates(arg: str) -> list[float]:
    """*_parse_rates()* parse a comma-separated rate list, e.g. `'100,200,345'`."""
    return [float(_r.strip()) for _r in arg.split(",") if _r.strip()]


def _batch_size_for(rate: float) -> int:
    """*_batch_size_for()* mirror the auto-batch derivation in `_probe_at_rate`."""
    if rate <= 0:
        return 1
    _interarrival = 1.0 / rate
    return max(1, int(round(_TARGET_TICK_S / _interarrival)))


def _lambda_z_at(adp: str, entry: str = "TAS_{1}") -> float:
    """*_lambda_z_at()* read the seeded external arrival rate at `entry`."""
    _cfg = load_profile(adaptation=adp)
    for _a in _cfg.artifacts:
        if _a.key == entry:
            return float(_a.lambda_z)
    raise KeyError(f"artifact {entry!r} not in {adp!r}")


def _run_one_probe(rate: float,
                   adaptation: str,
                   min_samples: int,
                   max_probe_s: float) -> dict:
    """*_run_one_probe()* run one ramp probe at `rate` against `adaptation`.

    Args:
        rate (float): single target rate to drive (req/s).
        adaptation (str): `baseline` / `s1` / `s2` / `aggregate`.
        min_samples (int): per-kind sample target (>= 32 for CLT).
        max_probe_s (float): probe wall-clock cap.

    Returns:
        dict: result envelope from `run_experiment` (config, nodes, network, requirements, probes, client_effective_rate, ...).
    """
    _mcfg = load_method_cfg("experiment")
    _mcfg["ramp"] = {
        "min_samples_per_kind": int(min_samples),
        "max_probe_window_s": float(max_probe_s),
        "rates": [float(rate)],
        "cascade": {"mode": "rolling", "threshold": 0.10, "window": 50},
    }
    return run_experiment(adp=adaptation, wrt=False, method_cfg=_mcfg)


def _summarise_trial(rate: float, result: dict) -> dict:
    """*_summarise_trial()* extract the headline rate metrics from one run envelope."""
    _eff = float(result.get("client_effective_rate", 0.0))
    _nds = result["nodes"]
    _entry = _nds.loc[_nds["key"] == "TAS_{1}"]
    if _entry.empty:
        _lam_tas1 = 0.0
    else:
        _lam_tas1 = float(_entry.iloc[0]["lambda"])
    _gap = rate - _eff
    if rate > 0:
        _loss_pct = _gap / rate * 100.0
    else:
        _loss_pct = 0.0
    return {
        "target": float(rate),
        "effective": _eff,
        "tas1_lambda": _lam_tas1,
        "gap": _gap,
        "loss_pct": _loss_pct,
    }


def _print_trial_row(trial: int, summary: dict) -> None:
    """*_print_trial_row()* one-liner per trial."""
    print(f"  trial{trial}: effective={summary['effective']:8.2f}  "
          f"TAS_1.lambda={summary['tas1_lambda']:8.2f}  "
          f"gap={summary['gap']:+7.2f}  loss={summary['loss_pct']:+6.2f}%")


def _aggregate(trials: list[dict]) -> dict:
    """*_aggregate()* mean / min / max / mean_loss across trials at one rate."""
    _eff_vals = [_t["effective"] for _t in trials]
    _mean = sum(_eff_vals) / len(_eff_vals)
    _lo = min(_eff_vals)
    _hi = max(_eff_vals)
    _target = trials[0]["target"]
    if _target > 0:
        _mean_loss = (_target - _mean) / _target * 100.0
    else:
        _mean_loss = 0.0
    return {"mean": _mean,
            "lo": _lo,
            "hi": _hi,
            "target": _target,
            "mean_loss_pct": _mean_loss}


def _print_aggregate_row(agg: dict) -> None:
    """*_print_aggregate_row()* aggregate across trials at one rate."""
    print(f"  >>> mean={agg['mean']:8.2f}  "
          f"range=[{agg['lo']:7.2f}, {agg['hi']:7.2f}]  "
          f"mean_loss={agg['mean_loss_pct']:+6.2f}%")


def _sweep(rates: list[float],
           adaptation: str,
           trials: int,
           min_samples: int,
           max_probe_s: float) -> dict[float, dict]:
    """*_sweep()* run `trials` probes per rate; return `{rate: aggregate}`."""
    _result: dict[float, dict] = {}
    for _rate in rates:
        print()
        _interarrival_ms = 1000 / _rate
        _K = _batch_size_for(_rate)
        print(f"--- target rate {_rate} req/s "
              f"(interarrival {_interarrival_ms:.2f} ms, K={_K}) ---")
        _trials: list[dict] = []
        for _i in range(trials):
            _res = _run_one_probe(_rate, adaptation, min_samples, max_probe_s)
            _summary = _summarise_trial(_rate, _res)
            _trials.append(_summary)
            _print_trial_row(_i, _summary)
        _agg = _aggregate(_trials)
        _print_aggregate_row(_agg)
        _result[_rate] = _agg
    return _result


def _calibrate(threshold_pct: float,
               adaptation: str,
               trials: int,
               min_samples: int,
               max_probe_s: float,
               candidates: list[float]) -> Optional[float]:
    """*_calibrate()* find the highest rate whose mean loss is below `threshold_pct`%.

    Walks `candidates` in increasing order; the highest one that meets the
    threshold across `trials` trials is returned. `None` when every
    candidate exceeds the threshold (mesh too constrained).

    Args:
        threshold_pct (float): max allowed mean loss in %.
        adaptation (str): `baseline` / `s1` / `s2` / `aggregate`.
        trials (int): trials per candidate.
        min_samples (int): per-kind sample target.
        max_probe_s (float): probe wall-clock cap.
        candidates (list[float]): rates to evaluate, ascending.

    Returns:
        Optional[float]: the highest passing rate, or `None`.
    """
    _aggs = _sweep(sorted(candidates), adaptation,
                   trials, min_samples, max_probe_s)
    _best: Optional[float] = None
    for _rate, _agg in _aggs.items():
        if abs(_agg["mean_loss_pct"]) <= threshold_pct:
            _best = _rate
    return _best


def _build_argparser() -> argparse.ArgumentParser:
    """*_build_argparser()* build the CLI surface."""
    _p = argparse.ArgumentParser(
        prog="demo_rate",
        description=("Inspect client effective-rate accuracy against the "
                     "in-process mesh. Reports per-trial and aggregate "
                     "loss; optional --calibrate mode picks the highest "
                     "rate the mesh sustains under a loss threshold."))
    _p.add_argument("--rates", type=str, default=None,
                    help=("comma-separated target rates in req/s "
                          f"(default: {','.join(str(_r) for _r in _DEFAULT_RATES)})"))
    _p.add_argument("--adp", type=str, default=_DEFAULT_ADAPTATION,
                    choices=("baseline", "s1", "s2", "aggregate"),
                    help=f"adaptation to drive (default: {_DEFAULT_ADAPTATION})")
    _p.add_argument("--trials", type=int, default=_DEFAULT_TRIALS,
                    help=f"trials per rate (default: {_DEFAULT_TRIALS})")
    _p.add_argument("--samples", type=int, default=_DEFAULT_SAMPLES,
                    help=("min_samples_per_kind per probe; >= 32 for CLT "
                          f"(default: {_DEFAULT_SAMPLES})"))
    _p.add_argument("--max-probe-s", type=float, default=_DEFAULT_PROBE_S,
                    help=("probe wall-clock cap in seconds "
                          f"(default: {_DEFAULT_PROBE_S})"))
    _p.add_argument("--with-lambda-z", action="store_true",
                    help=("append the seeded TAS_{1} lambda_z to the rate "
                          "sweep so target == analytic operating point"))
    _p.add_argument("--calibrate", type=float, default=None, metavar="PCT",
                    help=("instead of plain sweep, find the highest rate "
                          "whose mean loss is below PCT%% across all trials"))
    return _p


def main(argv: Optional[list[str]] = None) -> None:
    """*main()* CLI entry point."""
    _args = _build_argparser().parse_args(argv)

    if _args.rates:
        _rates = _parse_rates(_args.rates)
    else:
        _rates = list(_DEFAULT_RATES)

    if _args.with_lambda_z:
        _lz = _lambda_z_at(_args.adp)
        if _lz not in _rates:
            _rates.append(_lz)
        _rates = sorted(set(_rates))

    _banner(f"adaptation={_args.adp!r}  trials={_args.trials}  "
            f"min_samples={_args.samples}  probe_window={_args.max_probe_s}s")
    _tick_ms = _TARGET_TICK_S * 1000
    print(f"  target rates : {_rates}")
    print(f"  K formula    : round(_TARGET_TICK_S / interarrival)  "
          f"with _TARGET_TICK_S = {_tick_ms:.0f} ms")
    print("  primitive    : run_in_executor(time.sleep)  + "
          "winmm.timeBeginPeriod(1) for the run lifetime")
    if _args.with_lambda_z:
        print(f"  seeded lambda_z @ TAS_1 ({_args.adp}): "
              f"{_lambda_z_at(_args.adp):.2f} req/s")

    if _args.calibrate is not None:
        _banner(f"CALIBRATE: highest rate with mean loss <= "
                f"{_args.calibrate:.2f}%")
        _best = _calibrate(_args.calibrate, _args.adp, _args.trials,
                           _args.samples, _args.max_probe_s, _rates)
        print()
        if _best is None:
            print(f"  >>> no rate in {_rates} met the threshold; "
                  f"the mesh is too constrained at {_args.adp!r}")
        else:
            print(f"  >>> highest sustainable rate at <= "
                  f"{_args.calibrate:.2f}% loss: {_best:.2f} req/s "
                  f"(adaptation={_args.adp!r})")
        return

    _sweep(_rates, _args.adp, _args.trials,
           _args.samples, _args.max_probe_s)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        # clean exit on Ctrl-C; suppress the asyncio / IOCP traceback
        print("\n\n[interrupted]")
        sys.exit(130)

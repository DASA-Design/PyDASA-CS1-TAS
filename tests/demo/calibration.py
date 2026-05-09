"""Demo: run the calibration end-to-end on `dpl=localhost` and print the gate verdict.

Runnable script (not a pytest test). Calls `run_calibration` exactly the way the notebook will, but with `write=False` so nothing lands under `data/results/`. Prints the verdict + per-probe results.

Run from the project root:

    python -m tests.demo.calibration

Takes ~1 minute on a typical Windows dev box (the rate sweep dominates).
"""

from __future__ import annotations

import time

from src.methods.experimental import run_calibration


def main() -> None:
    """Run calibration on localhost; print the verdict + per-probe results."""
    print("\n=== Calibration: dpl=localhost framework=fastapi ===")
    _t0 = time.perf_counter()
    _env = run_calibration(dpl="localhost", framework="fastapi", write=False)
    _elapsed_s = time.perf_counter() - _t0

    _gate = _env["gate"]
    if _gate["passed"]:
        _verdict = "PASS"
    else:
        _verdict = "FAIL"
    print(f"\n--- Verdict: {_verdict} (in {_elapsed_s:.1f} s) ---")
    print(f"\tNoise floor:\t{_gate['noise_floor_pct']} %")
    for _name, _check in _gate["checks"].items():
        if _check["passed"]:
            _status = "ok"
        else:
            _status = "fail"
        print(f"\t[{_status}]\t{_name}:\t{_check.get('reason', '?')}")

    _rate = _env["rate"]
    if _rate["saturated"]:
        _sat = f"saturated at {_rate['saturation_rate']} req/s ({_rate['reason']})"
    else:
        _sat = "did not saturate within the ramp"
    print(f"\n--- Rate sweep: {_sat} ---")
    print(f"\tRamp:\t{_rate['ramp']}")
    print(f"\tTested:\t{len(_rate['per_rate'])} rates")


if __name__ == "__main__":
    main()

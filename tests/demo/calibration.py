"""Demo: run the calibration end-to-end on `dpl=localhost` and print the gate verdict.

Runnable script (not a pytest test). Calls `run_calibration` exactly the way the notebook will, but with `write=False` so nothing lands under `data/results/`. Prints the verdict + per-probe results.

Run from the project root:

    python -m tests.demo.calibration

Takes ~1 minute on a typical Windows dev box (the rate sweep dominates).
"""

from __future__ import annotations

import time

from src.methods.experimental import _print_calibration_report, run_calibration


def main() -> None:
    """Run calibration on localhost; print the interpretive calibration report."""
    print("\n=== Calibration: dpl=localhost framework=fastapi ===")
    _t0 = time.perf_counter()
    _env = run_calibration(dpl="localhost",
                           framework="fastapi",
                           write=False)
    _elapsed_s = time.perf_counter() - _t0
    _print_calibration_report(_env)
    print(f"\n(elapsed: {_elapsed_s:.1f} s, {len(_env['rate']['per_rate'])} rates tested)")


if __name__ == "__main__":
    main()

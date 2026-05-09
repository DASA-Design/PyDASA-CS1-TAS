"""Demo: spawn a real vernier and send three ping/echo requests over real localhost TCP.

Runnable script (not a pytest test). Spins up `UvicornProcess` running `build_vernier_fastapi_app` on a free localhost port, sends three echo requests via `httpx`, prints each response body + round-trip latency, and tears the process down.

Run from the project root:

    python -m tests.demo.vernier

The `-m` form puts the project root on `sys.path` so `from src.experimental...` and `from tests.utils...` imports resolve. The vernier runs only for the duration of the script; nothing persists.
"""

from __future__ import annotations

import time

import httpx

from src.experimental.prototype.calibration.vernier import build_vernier_fastapi_app
from src.experimental.prototype.runtime.uvicorn_process import UvicornProcess
from tests.utils.exp.ports import free_port

DEMO_REQUESTS = 3


def main() -> None:
    """Spawn the vernier on a free port, drive `DEMO_REQUESTS` echoes, print results, shut down."""
    _port = free_port()
    _url = f"http://127.0.0.1:{_port}"
    _proc = UvicornProcess(build_vernier_fastapi_app, port=_port)
    print(f"\n=== Vernier on {_url} ===")
    _proc.start()
    try:
        _proc.wait_ready(timeout_s=20.0)
        with httpx.Client(timeout=2.0) as _client:
            for _i in range(DEMO_REQUESTS):
                _t0 = time.perf_counter()
                _resp = _client.post(_url + "/",
                                     json={"req_id": f"demo-{_i}",
                                           "submitted_ts": time.time()})
                _rtt_us = (time.perf_counter() - _t0) * 1_000_000.0
                print(f"\n--- Request {_i} ---")
                print(f"\tStatus:\t{_resp.status_code}")
                print(f"\tRTT:\t{_rtt_us:.1f} us")
                print(f"\tBody:\t{_resp.json()}")
    finally:
        _proc.shutdown()
    print("\n=== shutdown OK ===")


if __name__ == "__main__":
    main()

"""Demo: drive one synthetic user through one request over real localhost TCP.

Runnable script (not a pytest test). Spins up a stdlib `http.server.ThreadingHTTPServer` echo on a free localhost port in a background thread (the same `start_echo_server` helper the test suite uses), instantiates a `User`, runs three requests through real HTTP / TCP / kernel scheduling, prints every emitted `RequestRecord` plus the final `Stats.summary()`, and tears the server down.

Run from the project root:

    python -m tests.demo.client

The `-m` form puts the project root on `sys.path` so `from src.experimental...` and `from tests.utils...` imports resolve. The server binds to `127.0.0.1:0` (a free port assigned by the kernel) and runs only for the duration of the script; nothing persists.
"""

from __future__ import annotations

import asyncio
import json

from src.experimental.prototype.client.guard import StopGuard
from src.experimental.prototype.client.users import User
from tests.utils.exp.apps import start_echo_server

DEMO_REQUESTS = 3
DEMO_PAYLOAD_BYTES = 256
DEMO_SEED = 42


async def _drive_user(base_url: str) -> None:
    """Drive one `User` through `DEMO_REQUESTS` requests against `base_url` and print outputs.

    Args:
        base_url (str): full URL to the local echo server.
    """
    _guard = StopGuard(max_requests=DEMO_REQUESTS)
    async with User(client_id="demo-user",
                    base_url=base_url,
                    endpoint_path="/",
                    payload_size_bytes=DEMO_PAYLOAD_BYTES,
                    seed=DEMO_SEED,
                    guard=_guard,
                    sequential_req_ids=True) as _user:
        print(f"\n=== Driving {DEMO_REQUESTS} requests against {base_url} ===")
        _records = await _user.run_until_stop(max_iters=DEMO_REQUESTS + 5)
        for _r in _records:
            print("\n--- RequestRecord ---")
            print(json.dumps(_r.to_dict(), indent=2))
        print("\n=== Stats summary ===")
        print(json.dumps(_user.stats.summary(), indent=2))
        print(f"\n=== Stop reason: {_user.guard.stop_reason.value} ===")


def main() -> None:
    """Spin up the echo server, drive the user, tear the server down.

    Server runs only for the duration of the script. The thread is daemonised so a Ctrl-C interrupts cleanly even if the foreground task is mid-await.
    """
    _server, _thread, _base_url = start_echo_server()
    try:
        asyncio.run(_drive_user(_base_url))
    finally:
        _server.shutdown()
        _server.server_close()
        _thread.join(timeout=2.0)


if __name__ == "__main__":
    main()

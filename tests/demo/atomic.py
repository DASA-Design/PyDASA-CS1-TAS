"""Demo: drive one atomic service end-to-end through real localhost TCP.

Spins up one `MAS_{1}` service via `build_atomic_fastapi_app` mounted on a real `UvicornProcess` (port 8050), POSTs three requests through real HTTP, prints the per-request response, and tears the server down.

Run from the project root:

    python -m tests.demo.atomic
"""

from __future__ import annotations

import asyncio
import functools
import json
import shutil
from pathlib import Path

import httpx

from src.experimental.procedure.deployment import bring_up
from src.experimental.prototype.target.factory.third_party import (
    build_atomic_fastapi_app,
)

DEMO_PORT = 8042
DEMO_REQUESTS = 3


async def _drive(url: str, csv_dir: Path) -> None:
    """POST `DEMO_REQUESTS` requests to `<url>/` and print each response.

    Args:
        url (str): atomic-service base URL.
        csv_dir (Path): where the per-pid CSV log will land.
    """
    async with httpx.AsyncClient(base_url=url, timeout=5.0) as _http:
        # create a request with no failure injection
        for _i in range(DEMO_REQUESTS):
            _payload = {
                "req_id": f"demo-r{_i}",
                "kind": "medical_analysis",
                "operation": "analyseData",
                "client_id": "demo-user",
                "submitted_ts": 0.0,
            }
            # wait for the response or timeout; print the response or the error
            _resp = await _http.post("/", json=_payload)
            print(f"\n--- response {_i + 1} (status={_resp.status_code}) ---")
            print(json.dumps(_resp.json(), indent=4))
    # list the CSV log files to show that the service wrote them
    print(f"\n=== per-pid CSV in {csv_dir} ===")
    for _csv in sorted(csv_dir.glob("*.csv")):
        print(f"  {_csv.name} ({_csv.stat().st_size} bytes)")


def main() -> None:
    """Mount the atomic on `127.0.0.1:DEMO_PORT`, drive `DEMO_REQUESTS` requests, tear down."""
    _scratch = Path("_sandbox/demo_atomic")
    if _scratch.exists():
        shutil.rmtree(_scratch)
    _csv_dir = _scratch / "csv"
    _csv_dir.mkdir(parents=True,
                   exist_ok=True)
    # creates an atomic service config
    _factory = functools.partial(build_atomic_fastapi_app,
                                 svc_name="MAS_{1}",
                                 kind="medical_analysis",
                                 mu=50.0,
                                 csv_dir=str(_csv_dir),
                                 run_id="demo-atomic")
    # bring up the service, drive it, tear down in the context manager
    with bring_up("localhost",
                  app_factory=_factory,
                  base_port=DEMO_PORT) as _urls:
        # context manager handles cleanup even if the drive code raisees
        asyncio.run(_drive(_urls[0], _csv_dir))


if __name__ == "__main__":
    main()

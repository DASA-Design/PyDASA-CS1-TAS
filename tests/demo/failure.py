"""Demo: exercise each failure mechanism (timeout / drop / 5xx) against one atomic service.

Spins up one `AS_{1}` service, sends three requests with `inject_failure` set to each mechanism, and prints how the client maps the server-side mechanism to an outcome. Documents the round-trip for the three failure-injection paths the catalogue's `failure_mechanism_mix` will sample at stage 8.

Run from the project root:

    python -m tests.demo.failure
"""

from __future__ import annotations

import asyncio
import functools
import json

import httpx

from src.experimental.procedure.deployment import bring_up
from src.experimental.prototype.target.factory.third_party import (
    build_atomic_fastapi_app,
)

DEMO_PORT = 7042


async def _send_one(http: httpx.AsyncClient,
                    inject_failure: str | None) -> None:
    """POST one request with the given `inject_failure` flag and print the outcome.

    Args:
        http (httpx.AsyncClient): shared client.
        inject_failure (str | None): mechanism flag to plant on the request.
    """
    _payload = {
        "req_id": f"demo-{inject_failure or 'success'}",
        "kind": "alarm",
        "operation": "triggerAlarm",
        "client_id": "demo-user",
        "submitted_ts": 0.0,
        "inject_failure": inject_failure,
    }
    _outcome: dict[str, object] = {"inject_failure": inject_failure}
    try:
        _resp = await http.post("/", json=_payload)
    except httpx.TimeoutException:
        _outcome["client_outcome"] = "timeout"
    except httpx.RequestError as _err:
        _outcome["client_outcome"] = "drop"
        _outcome["error"] = type(_err).__name__
    else:
        if _resp.status_code < 500:
            _outcome["client_outcome"] = "success"
        else:
            _outcome["client_outcome"] = "5xx"
        _outcome["status"] = _resp.status_code
    print(json.dumps(_outcome))


async def _drive(url: str) -> None:
    """Drive the three failure mechanisms in sequence."""
    async with httpx.AsyncClient(base_url=url, timeout=2.0) as _http:
        # creating one erronous request for each mechanism
        await _send_one(_http, None)
        await _send_one(_http, "5xx")
        await _send_one(_http, "drop")
        await _send_one(_http, "timeout")


def main() -> None:
    """Mount the atomic, drive each mechanism, tear down."""
    # Tighter timeout so the demo finishes quickly when the timeout flag fires.
    _factory = functools.partial(build_atomic_fastapi_app,
                                 svc_name="AS_{1}",
                                 kind="alarm",
                                 mu=200.0,
                                 timeout_grace_s=4.0)
    with bring_up("localhost",
                  app_factory=_factory,
                  base_port=DEMO_PORT) as _urls:
        asyncio.run(_drive(_urls[0]))


if __name__ == "__main__":
    main()

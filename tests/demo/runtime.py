"""Demo: FastAPI (uvicorn) + Flask (waitress) side-by-side over real localhost TCP.

Runnable script (not a pytest test): spawns one FastAPI process via `UvicornProcess` and one Flask process via `WaitressProcess`, hits `/healthz` on each over real HTTP, prints the responses, and tears them down. Confirms the cross-stack adapter contract holds at the wire level.

Run from the project root:

    python -m tests.demo.runtime

The `-m` form is required so `from src.experimental...` and `from tests.utils...` imports resolve. Both servers bind to free localhost ports assigned by the kernel and run only for the duration of the script.
"""

from __future__ import annotations

import socket

import httpx

from src.experimental.prototype.runtime.uvicorn_process import UvicornProcess
from src.experimental.prototype.runtime.waitress_process import WaitressProcess
from tests.utils.exp.apps import (
    build_healthz_fastapi_app,
    build_healthz_flask_app,
)


def _free_port() -> int:
    """Return a free TCP port on `127.0.0.1` (kernel-assigned).

    Returns:
        int: a port likely free at the moment of the bind.
    """
    _sock = socket.socket(socket.AF_INET,
                          socket.SOCK_STREAM)
    _sock.bind(("127.0.0.1", 0))
    _port = _sock.getsockname()[1]
    _sock.close()
    return _port


def _exercise_fastapi(port: int) -> None:
    """Spawn a uvicorn-backed FastAPI process, hit `/healthz`, shut it down.

    Args:
        port (int): TCP port to bind on.
    """
    print(f"\n=== FastAPI (uvicorn) on 127.0.0.1:{port} ===")
    _p = UvicornProcess(build_healthz_fastapi_app, port=port)
    _p.start()
    try:
        _p.wait_ready(timeout_s=20.0)
        _resp = httpx.get(f"http://127.0.0.1:{port}/healthz",
                          timeout=2.0)
        print(f"\tGET /healthz -> {_resp.status_code} {_resp.json()}")
    finally:
        _p.shutdown()
    print("\tshutdown OK")


def _exercise_flask(port: int) -> None:
    """Spawn a waitress-backed Flask process, hit `/healthz`, shut it down.

    Args:
        port (int): TCP port to bind on.
    """
    print(f"\n=== Flask (waitress) on 127.0.0.1:{port} ===")
    _p = WaitressProcess(build_healthz_flask_app, port=port)
    _p.start()
    try:
        _p.wait_ready(timeout_s=20.0)
        _resp = httpx.get(f"http://127.0.0.1:{port}/healthz",
                          timeout=2.0)
        print(f"\tGET /healthz -> {_resp.status_code} {_resp.json()}")
    finally:
        _p.shutdown()
    print("\tshutdown OK")


def main() -> None:
    """Run the FastAPI and Flask demos in sequence so the same console session sees both stacks."""
    _exercise_fastapi(_free_port())
    _exercise_flask(_free_port())


if __name__ == "__main__":
    main()

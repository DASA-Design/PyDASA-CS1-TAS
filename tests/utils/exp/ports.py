"""Port helpers for tests that need a free localhost TCP port.

`free_port()` binds a transient socket to `127.0.0.1:0`, reads the kernel-assigned port, then closes the socket so the spawner can rebind. A brief race is possible if another process binds the same port between close and the spawner's bind; acceptable for the test scope.

`PORT_MOCK` is a fixed sentinel used by tests that construct a spawner without ever binding (mock-spawn paths, no-spawn lifecycle inspections). It sits well above the registered system-port range and away from common host services.
"""

from __future__ import annotations

import socket

PORT_MOCK = 9042


def free_port() -> int:
    """Return a free TCP port on `127.0.0.1` (kernel-assigned).

    Returns:
        int: a port likely free at the moment of the bind.
    """
    _sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    _sock.bind(("127.0.0.1", 0))
    _port = _sock.getsockname()[1]
    _sock.close()
    return _port

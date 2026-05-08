"""Shared test utilities for `src.experimental` test modules.

Helpers split by concern:

- `apps`: FastAPI / stdlib HTTP server factories (echo, planted-5xx, healthz).
- `transports`: synthetic `httpx.AsyncBaseTransport` implementations that always raise (timeout / drop).
- `factories`: synthetic-record + synthetic-request constructors used by aggregator + guard tests.

Importing from this package keeps test modules short and removes near-duplicate `_build_echo_app`, `_make_record`, `_TimeoutTransport` declarations from every test file.
"""

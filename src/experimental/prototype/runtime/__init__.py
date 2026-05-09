"""Runtime plumbing for the experimental method (FastAPI + Flask side-by-side).

Modules:

- `os_timer`: Windows `winmm.timeBeginPeriod` wrapper (no-op on Linux).
- `async_loop`: Jupyter-safe sync entry point for asyncio coroutines.
- `server`: `ServerAdapter` ABC + concrete `FastAPIAdapter` / `FlaskAdapter` plus the `Handler` protocol both adapters honour.
- `uvicorn_process`: ASGI server process for the FastAPI variant (uvicorn).
- `waitress_process`: WSGI server process for the Flask variant on Windows + Linux (waitress).
- `gunicorn_process`: WSGI process for the Flask variant (Linux only; Windows callers get `WaitressProcess`).
- `config`: loader for `data/config/method/experimental.json::server.*` (per-spawner runtime tuning).
"""

from src.experimental.prototype.runtime.async_loop import CoroFactory, run_async_safe
from src.experimental.prototype.runtime.config import (
    DFLT_EXPERIMENTAL_CFG_PATH,
    load_experimental_cfg,
    load_server_cfg,
)
from src.experimental.prototype.runtime.gunicorn_process import GunicornProcess
from src.experimental.prototype.runtime.os_timer import windows_timer_resolution
from src.experimental.prototype.runtime.server import (
    FastAPIAdapter,
    FlaskAdapter,
    FlaskProcess,
    Handler,
    ServerAdapter,
    make_server_adapter,
)
from src.experimental.prototype.runtime.uvicorn_process import UvicornProcess
from src.experimental.prototype.runtime.waitress_process import WaitressProcess

__all__ = [
    "DFLT_EXPERIMENTAL_CFG_PATH",
    "CoroFactory",
    "FastAPIAdapter",
    "FlaskAdapter",
    "FlaskProcess",
    "GunicornProcess",
    "Handler",
    "ServerAdapter",
    "UvicornProcess",
    "WaitressProcess",
    "load_experimental_cfg",
    "load_server_cfg",
    "make_server_adapter",
    "run_async_safe",
    "windows_timer_resolution",
]

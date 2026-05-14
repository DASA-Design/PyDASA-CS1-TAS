"""Runtime plumbing for the experimental method (FastAPI + Flask side-by-side).

Modules:

- `os_timer`: Windows `winmm.timeBeginPeriod` wrapper (no-op on Linux).
- `async_loop`: Jupyter-safe sync entry point for asyncio coroutines.
- `server`: `ServerAdapter` ABC + concrete `FastAPIAdapter` / `FlaskAdapter` plus the `Handler` protocol both adapters honour.
- `uvicorn_process`: ASGI server process for the FastAPI variant (uvicorn).
- `waitress_process`: WSGI server process for the Flask variant on Windows + Linux (waitress).
- `gunicorn_process`: WSGI process for the Flask variant (Linux only; Windows callers get `WaitressProcess`).
- `watchdog`: parent-PID poller that force-exits workers when their parent dies abnormally (the `daemon=True` flag only covers clean exits).
- `cleanup`: notebook-callable utility that kills any process holding a calibration / experimental port.
- `config`: loader for `data/config/method/experimental.json::server.*` (per-spawner runtime tuning).
"""

from src.experimental.prototype.runtime.async_loop import CoroFactory, run_async_safe
from src.experimental.prototype.runtime.cleanup import (
    DFLT_CALIB_PORT_RANGE,
    cleanup_calibration_ports,
)
from src.experimental.prototype.runtime.config import (
    DFLT_EXP_CFG_PATH,
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
from src.experimental.prototype.runtime.watchdog import watch_parent

__all__ = [
    "DFLT_CALIB_PORT_RANGE",
    "DFLT_EXP_CFG_PATH",
    "CoroFactory",
    "FastAPIAdapter",
    "FlaskAdapter",
    "FlaskProcess",
    "GunicornProcess",
    "Handler",
    "ServerAdapter",
    "UvicornProcess",
    "WaitressProcess",
    "cleanup_calibration_ports",
    "load_experimental_cfg",
    "load_server_cfg",
    "make_server_adapter",
    "run_async_safe",
    "watch_parent",
    "windows_timer_resolution",
]

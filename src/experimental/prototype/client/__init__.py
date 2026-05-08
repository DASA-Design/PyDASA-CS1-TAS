"""Client-side load generator: synthetic users driving HTTP requests.

Modules:

- `records`: `RequestRecord` dataclass written one-per-request to the JSONL flow log.
- `sender`: `Sender` class that builds a `Request` and POSTs it via `httpx`.
- `guard`: `StopGuard` class with three stop conditions (infra failure, request budget, quality threshold).
- `stats`: `Stats` class aggregating per-window latency and outcome counts.
- `users`: `User` async context manager driving one synthetic user end-to-end.
- `config`: loader for `data/config/method/prototype/client.json` (the source of truth for client defaults from stage 9 onward).

Stage 2 wires everything except the failure-flag draw (stages 6 + 8 wire that based on the catalogue and adaptation strategies).
"""

from src.experimental.prototype.client.config import (
    DFLT_CLIENT_CFG_PATH,
    load_client_cfg,
)
from src.experimental.prototype.client.guard import StopGuard, StopReason
from src.experimental.prototype.client.records import RequestRecord
from src.experimental.prototype.client.sender import Sender
from src.experimental.prototype.client.stats import Stats
from src.experimental.prototype.client.users import User

__all__ = [
    "DFLT_CLIENT_CFG_PATH",
    "RequestRecord",
    "Sender",
    "StopGuard",
    "StopReason",
    "Stats",
    "User",
    "load_client_cfg",
]

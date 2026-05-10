"""Apparatus characterisation: vernier ping/echo + host-floor probes + rate sweep + envelope I/O + gate.

Modules (built one per stage-4 step):

- `vernier`: ping/echo atomic handler + FastAPI / Flask app factories. The single-service load target the rest of the package measures against.
- `hoststats` (next): timer / jitter / loopback / handler-scaling probes.
- `rate` (next): rate-saturation discovery driving the vernier.
- `envelope` (next): per-dpl envelope JSON serde.
- `gate` (next): pre-run noise-floor verdict.

The whole package together produces one calibration envelope JSON per `dpl` mode under `data/results/calibration/<dpl>/`. The 00-calibration.ipynb notebook is the end-to-end consumer; modules are individually unit-tested for logic, not for procedural results.
"""

from src.experimental.prototype.calibration.config import (
    DFLT_CALIBRATION_CFG_PATH,
    load_calibration_cfg,
)
from src.experimental.prototype.calibration.envelope import (
    DFLT_RESULTS_BASE,
    ENVELOPE_VER,
    PROBE_SECTIONS,
    envelope_path,
    make_envelope,
    read_envelope,
    write_envelope,
)
from src.experimental.prototype.calibration.gate import (
    HOST_FLOOR_PROBES,
    stamp_gate,
    verdict,
)
from src.experimental.prototype.calibration.hoststats import (
    probe_handler_scaling,
    probe_jitter,
    probe_loopback,
    probe_timer,
)
from src.experimental.prototype.calibration.rate import (
    RateDriver,
    detect_saturation,
    drive_at_rate,
    make_lambda_ramp,
    probe_rate,
)
from src.experimental.prototype.calibration.vernier import (
    build_vernier_fastapi_app,
    build_vernier_flask_app,
    echo,
)
from src.experimental.prototype.calibration.multi_proc_driver import (
    make_multi_proc_driver,
)
from src.experimental.prototype.calibration.workers import (
    MakeTargetsFn,
    detect_efficiency_knee,
    make_workers_ramp,
    probe_workers_scaling,
)

__all__ = [
    "DFLT_CALIBRATION_CFG_PATH",
    "DFLT_RESULTS_BASE",
    "ENVELOPE_VER",
    "HOST_FLOOR_PROBES",
    "MakeTargetsFn",
    "PROBE_SECTIONS",
    "RateDriver",
    "build_vernier_fastapi_app",
    "build_vernier_flask_app",
    "detect_efficiency_knee",
    "detect_saturation",
    "drive_at_rate",
    "echo",
    "envelope_path",
    "load_calibration_cfg",
    "make_envelope",
    "make_lambda_ramp",
    "make_multi_proc_driver",
    "make_workers_ramp",
    "probe_handler_scaling",
    "probe_jitter",
    "probe_loopback",
    "probe_rate",
    "probe_timer",
    "probe_workers_scaling",
    "read_envelope",
    "stamp_gate",
    "verdict",
    "write_envelope",
]

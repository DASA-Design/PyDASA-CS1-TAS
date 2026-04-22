# -*- coding: utf-8 -*-
"""
demo_registry.py
================

Show what `ServiceRegistry.from_config(method_cfg)` builds, and how
`build_invoke_url` / `build_healthz_url` resolve each service name
into a URL. The six TAS_{i} components share a port and get distinct
`/TAS_<i>/invoke` routes; third-party services each have their own
port and `/invoke`.

Role vocabulary in use (per `experiment.json`):

    composite_client   TAS_{1} ingress + TAS_{5} / TAS_{6} egress
    composite_medical  TAS_{2} (routes to MAS)
    composite_alarm    TAS_{3} (routes to AS)
    composite_drug     TAS_{4} (routes to DS)
    atomic             MAS_{*} / AS_{*} / DS_{*} (third-party leaves)

Run:
    python src/scripts/demo_registry.py
"""
import sys
from pathlib import Path

_HERE = Path(__file__).resolve()
_ROOT = _HERE.parents[2]
sys.path.insert(0, str(_ROOT))

from src.experiment.registry import ServiceRegistry  # noqa: E402
from src.io import load_method_config  # noqa: E402


def _banner(s: str) -> None:
    """*_banner()* print a centred header band to stdout."""
    print()
    print("=" * 72)
    print(f"  {s}")
    print("=" * 72)


def main() -> None:
    """*main()* walk through every public registry helper with live output."""
    _mcfg = load_method_config("experiment")

    _banner("1. raw registry block from experiment.json")
    print(f"  host        = {_mcfg.get('host')}")
    print(f"  base_port   = {_mcfg.get('base_port')}")
    print(f"  entries     = {len(_mcfg['service_registry'])}")
    for _name, _spec in _mcfg["service_registry"].items():
        print(f"    {_name:<14}  offset={_spec['port_offset']}  "
              f"role={_spec['role']!r}")

    _banner("2. ServiceRegistry.from_config() resolves offsets to concrete ports")
    _reg = ServiceRegistry.from_config(_mcfg)
    print(f"  host={_reg.host}  base_port={_reg.base_port}")
    for _name, _entry in _reg.table.items():
        print(f"    {_name:<14}  port={_entry.port}  role={_entry.role!r}")

    _banner("3. URL resolution; TAS components SHARE a port and have distinct paths")
    for _name in _reg.table:
        _inv = _reg.build_invoke_url(_name)
        _hz = _reg.build_healthz_url(_name)
        print(f"    {_name:<14}  invoke  -> {_inv}")
        print(f"                  healthz -> {_hz}")

    _banner("4. role filter helpers (one per CS-01 workflow stage)")
    for _role in ("composite_client", "composite_medical",
                  "composite_alarm", "composite_drug", "atomic"):
        print(f"  {_role:<20}: {list(_reg.filter_names_role(_role))}")


if __name__ == "__main__":
    main()

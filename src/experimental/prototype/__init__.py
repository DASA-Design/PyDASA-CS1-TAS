"""One-execution apparatus for the experimental method.

Subpackages (built stage by stage):

- `client/` (stage 2): synthetic-user load generator (records, sender, guard, stats, users).
- `runtime/` (stage 3): FastAPI / Flask process spawners, server adapter, asyncio bridge.
- `calibration/` (stage 4): apparatus characterisation + ping-echo vernier.
- `target/` (stage 6): managed subsystem (Weyns 2015 Fig. 2 published classes).
- `controller/` (stage 7): managing subsystem (probes, effectors, service profile).
"""

"""Cross-cutting utilities for the experimental method.

Subpackages:
    io: JSONL / CSV / Parquet writers, envelope JSON serde, run paths.
    payload: typed request schema plus deterministic blob generator.
    transport: in-memory HTTP transport for tests (NEVER imported from production).
    registry: ServiceRegistry, ServiceCache, ServiceDescription (Weyns 2015 Fig. 2).

Acyclic by rule: nothing in this package imports from `procedure/` or `prototype/`.
"""

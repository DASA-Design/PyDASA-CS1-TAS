"""
Module helpers.py
=================

Shared fixtures, builders, and callable mocks for service / instance tests.
"""
# native python modules
from typing import List, Tuple

# modules for tests
from src.experiment.architecture import TasArchitecture
from src.experiment.services import LOG_COLUMNS, SvcReq, SvcResp, SvcSpec


class _SpecBuilder:
    """*_SpecBuilder* callable that builds a `SvcSpec` with sensible defaults; tests call it like `spec_builder(name=...)`."""

    def __call__(self, *,
                 name: str = "MAS_{1}",
                 role: str = "atomic",
                 port: int = 8006,
                 mu: float = 1000.0,
                 epsilon: float = 0.0,
                 c: int = 1,
                 K: int = 10,
                 seed: int = 42) -> SvcSpec:
        specs = SvcSpec(name=name,
                        role=role,
                        port=port,
                        mu=mu,
                        epsilon=epsilon,
                        c=c,
                        K=K,
                        seed=seed)
        return specs


async def _no_forward(_tgt: str, _req: SvcReq) -> SvcResp:
    """*_no_forward()* raise `AssertionError` on call; used as `ext_fwd` for terminal / in-process-only paths."""
    raise AssertionError(f"unexpected external forward to {_tgt!r}")


class _RecordedForward:
    """*_RecordedForward* append `(target, req.req_id)` to `self.calls` and return a success `SvcResp`."""

    def __init__(self, calls: List[Tuple[str, str]]) -> None:
        self.calls = calls

    async def __call__(self, target: str, req: SvcReq) -> SvcResp:
        self.calls.append((target, req.req_id))
        return SvcResp(req_id=req.req_id,
                       srv_name=target,
                       success=True,
                       message="recorded")


def _seed_one_row_per_tas_member(arch: TasArchitecture) -> None:
    """*_seed_one_row_per_tas_member()* append one stub `LOG_COLUMNS`-shaped row to every TAS member's log; deduplicates by `id(app.state.tas_components)`."""
    _seen: set = set()
    for _name, _app in arch.apps.items():
        if not _name.startswith("TAS_"):
            continue
        _members = _app.state.tas_components
        if id(_members) in _seen:
            continue
        _seen.add(id(_members))
        for _ctx in _members.values():
            _ctx.log.append({_col: 0 for _col in LOG_COLUMNS})

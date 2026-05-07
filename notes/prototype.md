# Prototype — apparatus design for the new software-architecture experiment

> Scaffold. Filled in as the refactor lands under [`src/experimental/`](../src/experimental/). Replaces the closed prior-build docs preserved at [`__OLD__/notes/`](../__OLD__/notes/): `prototype.md`, `prototype-constraints.md`, `prototype-v2.md`, `soa-refactor.md`, `calibration.md`.

## Scope

What this document specifies:

- The new prototype's apparatus layout: per-service contract, deployment modes, lifecycle.
- The four constraints (`c`, `K`, `μ`, calibration boundary) — what is enforced, why, and what does NOT undermine the proof. Carry forward the four-constraints table from the archived [`__OLD__/notes/prototype-constraints.md`](../__OLD__/notes/prototype-constraints.md) once the new constraints are settled.
- The calibration gate — host noise floor, irreducible jitter, per-worker μ ceiling. New build's contract still TBD.
- The deployment axis — process-distribution count, transport stack, log-collection strategy.
- The data convention — config inputs, result envelopes, figure outputs.

What this document does NOT specify:

- The methodology and hypotheses — see [`notes/procedure.md`](procedure.md).
- The case study — see [`notes/case-study.md`](case-study.md).

## Status

Refactor in progress. Empty scaffolding under [`src/experimental/`](../src/experimental/) (`__init__.py` + `procedure/`, `prototype/` subpackages). Prior FastAPI-mesh build retired into [`__OLD__/src/experiment/`](../__OLD__/src/experiment/) as read-only reference; tests, notebooks, configs, and results all archived alongside.

## Apparatus contract (TBD)

> Per-service handler protocol, request/response shape, admission gating, logging schema, calibration contract, runtime layout — to be specified by the new build. Reference baseline available at [`__OLD__/src/experiment/`](../__OLD__/src/experiment/).

## Deployment modes (TBD)

> Reference enumeration from the archived build (preserved at [`__OLD__/notes/soa-refactor.md`](../__OLD__/notes/soa-refactor.md) §"Goal-state architecture"): `localhost` (in-process MockTransport, dev/test), `multiprocess` (one-host real TCP), `remote` (LAN-distributed). The new build's axis may differ.

## Calibration (TBD)

> Reference baseline at [`__OLD__/notes/calibration.md`](../__OLD__/notes/calibration.md). The new build's gating contract — what is measured, what threshold gates the experiment, what the report-`reported = measured − loopback_median ± jitter_p99`-correction looks like — still TBD.

## Constraints — what enforcing `c`, `K`, `μ` does NOT undermine

> Carry forward the four-constraints defensive analysis (wind-tunnel jig, shake-table, detector-calibration analogues) from [`__OLD__/notes/prototype-constraints.md`](../__OLD__/notes/prototype-constraints.md). The new build's constraints may diverge in implementation but the methodological frame should still apply.

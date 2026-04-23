# Experiment Method — Prototype Requirements

Functional requirements for the **apparatus**. The experimental-design
discipline is in `.claude/skills/design/experimental-design.md`; the
CS-01 procedure the apparatus serves is in `notes/experiment.md`.

This document answers one question: **what must the apparatus do so
that its raw measurements are comparable to the other methods'
predictions?** Anything about *what to compare, how many samples, or
how to decide the hypothesis* lives in `notes/experiment.md`.

## 1. What the prototype is

A FastAPI microservice replication of the TAS queue network that runs
one `(profile, adaptation, λ, seed)` cell per invocation, enforces
per-component M/M/c/K discipline, and emits raw per-invocation logs +
per-component aggregates on disk. The grid (ρ-sweep × adaptations ×
profiles × replicates) is driven by the orchestrator in
`src/methods/experiment.py`.

## 2. Structure

Three levels:

- **Level 1 — service components**: TAS target system (TAS 1..6),
  third-party services (MAS, AS, DS), client simulator.
- **Level 2 — cross-cutting components**: service registry, request
  template, activity logger, mock-payload generator, experiment-data
  sink, config loader.
- **Level 3 — experiment execution**: grid driver, per-cell lifecycle,
  stop-condition, λ-ramp.

## 3. Level 1 — service components

### FR-1.1 — TAS target system (TAS 1..6)

Routing composites wired per the active scenario's routing matrix. No
autonomic-controller logic; each TAS_i runs a fixed rule:

- **TAS_1** — kind router: the client tags each request with a kind
  (derived from TAS_1's routing-matrix row weights at the launcher);
  TAS_1 forwards to the target named by that kind.
- **TAS_2** — medical-analysis dispatcher: equivalent-set composite over
  `{MAS_1, MAS_2, MAS_3}`; the active adaptation pattern (baseline/s1/s2/
  aggregate) decides how equivalents are invoked.
- **TAS_3** — alarm dispatcher: equivalent-set composite over
  `{AS_1, AS_2, AS_3}`; same pattern rule as TAS_2.
- **TAS_4** — relay: forwards the MAS response to the next stop per its
  routing-matrix row (DS_3 in the main path).
- **TAS_5** — relay: forwards the AS response back to the external user.
- **TAS_6** — relay: forwards the DS response back to the external user.

**Dispatch semantics.** The routing matrix is **Jackson-style
probabilistic routing** — every non-terminal row sums to ≈1.0 across
all four adaptations, so each request traverses **one path** through
the network. Cross-request concurrency is provided by asyncio: every
component processes many in-flight requests in parallel up to its `c`
semaphore. Single-request parallelism exists only inside
equivalent-dispatcher composites (TAS_2/TAS_3) when the active pattern
is `s2` or `aggregate`, which fires all equivalents concurrently via
`asyncio.wait(FIRST_COMPLETED)`.

**Adaptation-axis behaviour comes from the scenario, not from TAS code.**
`baseline / s1 / s2 / aggregate` populate different routing rows in
`_routs` and different equivalent sets in `_nodes`; the TAS composite
reads the active scenario and acts. No scenario-specific `if` branches
in the apparatus.

**Check**: switching `baseline → aggregate` changes only the profile's
scenario-indexed entries; the TAS code paths are identical.
`cfg.routing.sum(axis=1)` on every non-terminal row yields values in
`[0.99, 1.0]` for every `(profile, adaptation)` combination, confirming
Jackson-style routing.

**Open semantic point**: if a request's class *should* fan out at TAS_1
(e.g. emergency → alarm branch AND medical branch simultaneously), that
is a routing-matrix semantics change (row-sum > 1 = fan-out) and NOT an
apparatus change — today's matrix does not encode it.

### FR-1.2 — Third-party services (MAS, AS, DS)

Leaf atomic services. Each one:

- Sleeps `random.expovariate(μ)` to enforce the configured service rate.
- Gates concurrency with `asyncio.Semaphore(c)`.
- Admits at most `K` in-system jobs; arrivals while full return an
  infrastructure-failure signal.
- Runs a Bernoulli trial at rate `ε` on completion; on fire, returns a
  business-failure signal.
- Holds an explicit per-service memory budget (see FR-2.4).

**Failure-mode channels are distinguishable end-to-end**:

| Mode | Wire signal |
|---|---|
| Business (`ε` fired) | HTTP 200 + `body.success = False` |
| Infrastructure (K-drop / timeout / 5xx) | HTTP 503 / transport exception |

Patterns may retry the business channel; infrastructure propagates
without retry.

**Check**: unit tests pin each invariant independently; at a seeded
run, `μ̂` and `ε̂` recovered from logs match configured values within CI
(FR-3.2).

### FR-1.3 — Client simulator

Generates requests, drives the cell to completion, persists the cell's
raw output.

- **Request generation**: picks the request kind (emergency vs normal)
  per the probabilities in the active scenario's kind-weights row;
  wraps each request in a mock payload (FR-2.3).
- **Interarrival**: deterministic `1 / λ` at the cell's configured λ;
  Poisson emerges naturally from downstream routing + service-time
  variability.
- **Scenario-driven config**: reads the cell's `(profile, adaptation)`
  and configures itself from `_labels[scenario]` and `_nodes[scenario]`;
  no per-adaptation code branches in the client.
- **Stop condition**: continue until the sample floor is met (every
  kind has ≥ `min_samples_per_kind` successful completions) or the
  probe window `max_probe_window_s` fires.
- **Journey recording**: saves the journey (timestamps in/out of every
  component, payload bytes, component-state snapshots) *on response*,
  one row per completed request. No intermediate per-service writes —
  recording happens at the client only to minimise instrumentation
  noise.

**Check**: running two cells at the same seed produces identical
request sequences (kinds, payload bytes, journey trees) modulo scheduler
jitter on timestamps; per-kind completion ratios match the scenario's
kind-weights row within sampling error.

## 4. Level 2 — cross-cutting components

### FR-2.1 — Service registry

A single name → `(host, port)` resolver. TAS composites use it to reach
third-party services; the client uses it to reach TAS_1. Ports and host
are read from the method config (plumbing only); nothing scientific
lives here.

### FR-2.2 — Request template + activity logger

One shared dataclass / Pydantic model propagated through every
component. It carries:

- `request_id` (UUID, client-generated)
- `kind` (emergency / normal / etc)
- `payload_size_bytes` (FR-2.3)
- `journey` — append-only list of `(component, recv_ts, start_ts,
  end_ts, component_config_snapshot, bytes_in_flight)` entries

The **activity logger** is the aspect-oriented decorator that appends
one `journey` entry as the request enters and leaves each component.
It is the ONLY instrumentation path — no component writes to a log
directly.

Recording happens at the client on response (FR-2.5). The in-transit
journey list rides in the request body/header as it flows through the
mesh.

### FR-2.3 — Mock-payload generator

Produces a dummy payload of a requested byte size (drawn from the
method config's `request_size_bytes` per kind) as part of each
client-generated request. The payload size is what drives the
bytes-in-flight measurement used for the `memory-usage` dimensional
coefficient.

Lives in the client simulator; downstream services read the size from
the header (`X-Request-Size-Bytes`) and never call `psutil` or probe
process memory.

### FR-2.4 — Explicit FastAPI memory budget per service

Each service declares its buffer memory as a first-class config
parameter alongside `(c, K, μ, ε)`: `mem_per_buffer = K ·
avg_request_size`. The apparatus enforces it (e.g. refuses to start if
the declared budget is less than expected buffer payload).

This makes memory-usage observable at the service level and prevents
the `memory-usage` coefficient from being silently confounded by FastAPI
/ uvicorn internal buffering.

### FR-2.5 — Experiment-data sink (raw rows only)

Accumulates journey records on response into an in-memory pandas
DataFrame (polars optional later; stick to pandas for now — matches
the rest of the repo). At cell end, the sink flushes to disk:

- `journey.csv` — one row per completed request, with a column per
  component visited (entry/exit timestamps, c_used_at_start,
  queue_depth_at_recv, success flag, status code, payload size).
- `config.json` — effective controlled values actually applied
  (FR-3.3).

**No aggregates, no per-component summaries, no re-estimates, no
invariant checks, no residuals, no plots, no verdicts are computed by
the apparatus.** All of that is downstream work (`06-comparison.ipynb`
and helpers under `src/dimensional/` / `src/comparison/`). The
apparatus's only job is to hand the notebook a clean, complete set of
raw journey rows and the effective config that produced them.

### FR-2.6 — Experiment-config loader

Single loader used by all levels. Locates and reads the relevant
JSONs:

- `data/config/profile/<dflt|opti>.json` — scientific inputs.
- `data/config/method/experiment.json` — plumbing (ports, seeds,
  sample floor, R, payload sizes).

Resolves the `(profile, adaptation)` pair to a concrete
`(μ, ε, c, K, χ, routing, kind_weights, nodes)` tuple the apparatus
consumes.

## 5. Level 3 — experiment execution

### FR-3.1 — Reads configuration from JSON

The orchestrator (Level 3) and the apparatus (Level 1/2) both read
from the same loader (FR-2.6). No hand-written path munging, no
environment-variable short-circuits.

### FR-3.2 — Raw journey rows sufficient to re-estimate every controlled input downstream

The apparatus does **not** compute re-estimates, invariants, or the
Little's-law check. Those calculations live in `06-comparison.ipynb`
(and any helpers under `src/dimensional/` or `src/comparison/`). The
apparatus's obligation is only to persist enough raw journey data that
the downstream notebook can compute:

- `μ̂ = 1 / mean(end_ts − start_ts)` per service (needs `start_ts`, `end_ts` per invocation)
- `ε̂ = count(body.success == False) / count(HTTP 200)` per service (needs `success`, `status_code` per invocation)
- `c_max_used` (needs `c_used_at_start` per invocation)
- `K_max_observed` (needs `queue_depth_at_recv` per invocation)
- `χ̂ = count(successful_completions) / count(arrivals)` per service
- Little's-law per component: `L ≈ λ · W`

**Check**: every downstream re-estimator and invariant listed above can
be computed from `journey.csv` + `config.json` alone, with no missing
columns and no ambiguity about arrival vs completion events.

### FR-3.3 — Effective-value config snapshot

At cell start, `config.json` captures the **effective** values of every
controlled input as applied to the running mesh — λ, routing matrix,
per-node `(c, K, μ, ε, χ)`, payload-size-per-kind, seed, replicate_id.
Downstream analysis joins on this snapshot, not on the source profile.

**Check**: two runs at the same `(profile, adaptation, λ, seed)` differ
only in `replicate_id`.

### FR-3.4 — Output schema matches the analytic schema

The per-component aggregate in `<profile>.json` uses the same column
names, units, and dtypes as `data/results/analytic/<scenario>/<profile>.json`
so `06-comparison.ipynb` inner-joins on `(profile, adaptation, artifact)`
without rename shims.

Concrete column list is owned jointly with the analytic method; locked
in when the column schema is pinned there. **Open**: the exact column
list needs to be written down.

### FR-3.5 — Ramp the arrival rate

The orchestrator consumes a pre-computed λ schedule (one λ per
target-ρ point, inverted from the analytical model's prediction). At
each λ it runs `R` replicates with distinct seeds. Once all replicates
pass the stop condition (FR-3.6) the orchestrator steps to the next λ.

The apparatus itself does **not** sweep; one cell per invocation.

### FR-3.6 — Stop condition per cell

A cell ends when:

- **Sample floor met**: every request kind has ≥ `min_samples_per_kind`
  successful completions (drives σ tight enough for χ²), OR
- **Probe window elapsed**: `max_probe_window_s` seconds have passed;
  cell is marked **under-powered** in its metadata.

Both numbers come from the method config; the apparatus does not
choose them.

### FR-3.7 — Seeded reproducibility

One integer seed per cell controls every random draw (client kind
picks, per-service `ε` Bernoulli, per-service `μ` exponential).
Two runs at the same seed produce identical request sequences, payload
bytes, and success/failure outcomes — only asyncio scheduler jitter on
timestamps may differ.

### FR-3.8 — Replicates per cell

Each `(profile, adaptation, λ)` runs `R` times with distinct seeds.
Per-replicate outputs live under `rep_<k>/`. Cross-replicate aggregation
(mean, SE, CI) is **not** the apparatus's job; that math lives in
`06-comparison.ipynb` reading the `R` subdirectories.

`R` is pinned in `notes/experiment.md` (default 10, bumped to 30 if
downstream analysis finds CIs too wide).

### FR-3.9 — Hermetic default, real TCP optional

Default mode: services run as in-process ASGI apps behind a
multiplexing `httpx.AsyncClient`. No real TCP binding.

Rationale: the hypothesis is about whether DASA's coefficients transfer
to a different stack (FastAPI + asyncio), not whether they transfer
through a TCP pipe. Real TCP adds kernel-stack noise that widens CIs
and lengthens every cell by 3–5× without testing a DASA-relevant
question.

Real-TCP mode (via `uvicorn.Server`) is kept as an optional toggle for
a future experiment (*does real networking change the coefficients?*)
but is not used in CS-01.

## 6. Non-goals

The apparatus does NOT:

- Implement MAPE-K / ActivFORMS / UPPAAL or any autonomic controller.
- Perform any statistical calculation — no aggregates, no means, no SEs,
  no CIs, no re-estimates of configured inputs, no invariant checks,
  no Little's-law test, no residuals, no χ², no verdicts. All of that
  lives downstream in `06-comparison.ipynb` and its helpers.
- Compute dimensional coefficients (that is `src/dimensional/`'s job
  given the raw output).
- Invert `ρ → λ` (orchestrator's job via the analytical model).
- Reproduce the Weyns & Calinescu 2015 Java / ReSeP published numbers.
- Measure on hardware matching the paper's testbed.
- Choose operating points, tolerances, sample counts, or replicate
  counts at runtime.

## 7. Open points

1. **Shared output-schema column list (FR-3.4)** — concrete column names, units, dtypes to be pinned jointly with the analytic method. Blocks `06-comparison.ipynb`.
2. **Payload-size distribution** — the method config declares a size *per kind*; is it a fixed value per kind, or a distribution? A single fixed value makes `memory-usage` deterministic at the payload level; a distribution adds variance. Default: fixed per kind.
3. **Memory-budget enforcement (FR-2.4)** — runtime check that FastAPI's buffered bytes never exceed `K · avg_request_size`, or just a configured value logged to `config.json` without runtime enforcement? Default: logged + declared; runtime enforcement deferred.
4. **Real-TCP toggle shape (FR-3.9)** — a method-config flag or a separate module entry point? Default: method-config flag, default `false`.

## 8. Implementation status — gap inventory (2026-04-21)

Delta between the FR list above and `src/experiment/` as it stands. `✓` =
conforms; `~` = exists but drifts; `✗` = missing entirely.

### Level 1 — service components

| FR | Status | Where | Gap |
|---|---|---|---|
| FR-1.1 TAS composites (TAS 1..6) | `✓` | `services/composite.py` — `make_composite_router` + `make_composite_service` | **Resolved by inspection (2026-04-21):** routing-matrix rows sum to ≈1.0 for every `(profile, adaptation)` — Jackson-style routing. No per-request fan-out in the topology. Current code (kind-router for TAS_1, equivalent-dispatcher for TAS_2..6) matches the topology exactly. Cross-request concurrency via asyncio is already there. Only single-request parallelism is `s2`/`aggregate` firing equivalents concurrently inside TAS_2/TAS_3. |
| FR-1.2 Third-party services (MAS / AS / DS) | `✓` | `services/atomic.py` + `services/base.py` | M/M/c/K + ε + failure-channel split already in `log_request`. |
| FR-1.3 Client simulator | `~` | `client.py` | Kind draws + deterministic interarrival + stop condition all there. Missing: (a) journey-on-response recording (currently uses per-service CSVs, not client-accumulated journey rows), (b) mock-payload wrapping (FR-2.3), (c) explicit scenario-driven reconfigure per cell. |

### Level 2 — cross-cutting components

| FR | Status | Where | Gap |
|---|---|---|---|
| FR-2.1 Service registry | `✓` | `registry.py` | Done. |
| FR-2.2 Request template + activity logger | `~` | `services/base.py` — `ServiceRequest` + `@log_request` | `ServiceRequest.payload` field exists but `journey` list is not carried through requests. Logger writes to per-service in-memory buffers, not to a client-accumulated journey. Needs journey-propagation via request body. |
| FR-2.3 Mock-payload generator | `✗` | *nowhere* | No payload generator. `ServiceRequest.size_bytes` is a declared integer, not a real payload of that size. Must add a generator in the client. |
| FR-2.4 Explicit FastAPI memory budget | `✗` | *nowhere* | `ServiceSpec` has `mu, epsilon, c, K, cost` — no memory-budget field. Needs `mem_per_buffer` added to spec + startup-time validation. |
| FR-2.5 Experiment-data sink (pandas) | `~` | `services/base.py::flush_log` + `launcher.py::flush_logs` | Flushes per-service CSVs at shutdown. Not client-centric; no in-memory pandas accumulator. Journey-style output is missing. Needs a client-side sink that collects journey rows on response. |
| FR-2.6 Experiment-config loader | `✓` | `src/io/` + `src.experiment.client.build_ramp_cfg` | Profile + method config loading already works. |

### Level 3 — experiment execution

| FR | Status | Where | Gap |
|---|---|---|---|
| FR-3.1 Reads configuration from JSON | `✓` | `src/io/` + `src/methods/experiment.py` | Done. |
| FR-3.2 Raw journey rows sufficient for downstream re-estimates | `~` | `services/base.py::log_request` | Per-service CSVs carry most needed columns (`start_ts, end_ts, success, status_code, c_used_at_start, queue_depth_at_recv`). No statistical calculation expected in the apparatus — downstream computes μ̂, ε̂, χ̂, Little's-law. Gap is only in column completeness + journey-row consolidation. |
| FR-3.3 Effective-value `config.json` snapshot | `✗` | *nowhere* | No per-run config snapshot is written. Currently the resolved config is only in memory. |
| FR-3.4 Output schema matches analytic | `~` | `src/methods/experiment.py::_service_df_from_logs` | Currently aggregates in the method module. Per the raw-rows-only rule (FR-2.5), aggregation should move out of the apparatus into `06-comparison.ipynb`; the apparatus keeps only the raw-journey schema. Schema pinning happens downstream. |
| FR-3.5 Ramp arrival rate | `~` | `client.py::run_ramp` | Consumes a `rates` list; the list is still shaped like a saturation sweep, not a ρ-indexed grid. λ-from-ρ inversion has no home yet. |
| FR-3.6 Stop condition per cell | `✓` | `client.py::_probe_at_rate` | `min_samples_per_kind` + `max_probe_window_s` both enforced; under-powered flag emitted. |
| FR-3.7 Seeded reproducibility | `~` | `client.py::ClientSimulator.__init__` | Client uses one seed; per-service `ε` / `μ` draws use Python's default `random` (process-global state). Needs per-service `random.Random(seed_i)` derived from the cell seed to get true determinism. |
| FR-3.8 Replicates per cell | `✗` | *nowhere* | Single-seed runs only. Per-replicate directory layout absent. Cross-replicate aggregation is downstream work and is **not** an apparatus gap. |
| FR-3.9 Hermetic default + real-TCP toggle | `~` | `launcher.py::_MultiASGITransport` | ASGI-in-process is the default and works. No real-TCP alternative exists yet. Acceptable for CS-01; FR just needs documenting that the toggle is deferred. |

### Summary of gaps

| Priority | Gap | Why it matters |
|---|---|---|
| P0 | **FR-3.3** `config.json` snapshot | Blocks downstream re-estimates; small change. |
| P0 | **FR-2.3 + FR-2.4 + FR-2.5** payload generator + memory budget + raw-rows sink | Memory-usage coefficient is unmeasurable without these; apparatus must emit the raw columns. |
| P0 | **FR-3.2** raw-column completeness (start/end/success/c_used/queue_depth) | Downstream re-estimators need these; mostly already present — just audit + seal the schema. |
| ✓ | **FR-1.1** ~~explicit TAS parallel dispatch~~ | Resolved 2026-04-21: routing matrix is Jackson-style; no fan-out to implement. |
| P1 | **FR-3.7** per-service seeded RNG | Without it, "seeded reproducibility" is partial. |
| P1 | **FR-3.8** per-replicate directory layout | Needed so the grid can write `R` subtrees; cross-replicate math is downstream. |
| P1 | **FR-3.5** ρ-indexed grid + λ-from-ρ inversion helper | Blocks the validity-envelope procedure. |
| P2 | **FR-1.3 + FR-2.2** journey-on-response recording | Refactor to match the request-template design; current per-service CSVs work but are noisier. |
| P2 | **FR-3.4** raw-row schema lock | Pin the journey-row columns so downstream doesn't need to guess. |
| P3 | **FR-3.9** real-TCP toggle | Deferred; CS-01 doesn't need it. |

### Implementation order proposed

Phase 2a (foundations) ✓ DONE: FR-3.3 (`config.json`) → FR-2.3 (payload gen) → FR-2.4 (memory budget) → FR-3.7 (per-service RNG).
Phase 2b (raw-row completeness) ✓ DONE: FR-3.2 (audit columns) → FR-3.4 (lock the journey-row schema) → FR-3.8 (per-replicate layout).
Phase 2c (semantics): FR-1.1 ✓ resolved-by-inspection (Jackson routing; no code change) → FR-3.5 (ρ-grid + λ-inversion helper).
Phase 2d (polish): FR-1.3/FR-2.2 (journey-on-response sink refactor).

All statistical work (re-estimates, invariant checks, aggregation, CIs,
Little's-law verification, residuals, χ²) is **out of the apparatus
scope** and lives in `06-comparison.ipynb` / `src/comparison/`.

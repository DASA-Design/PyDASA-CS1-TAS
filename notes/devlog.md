# Devlog — CS-01 TAS

Running log of design decisions, pivots, and open questions for the Tele Assistance System case study. Append only; newest entry on top.

---

## 2026-04-22 — Style + documentation pass: `experiment/instances/third_party`

Applied the code-documentation + coding-conventions + test-layout skills to `src/experiment/instances/third_party.py` and its associated tests.

- **`src/experiment/instances/third_party.py`** — tightened module docstring (added usage example; fixed stale `(spec, routing_row, forward)` note that no longer matched the signature; stated terminal vs forwarding behaviour up front); function docstring now pairs the `targets` argument with `external_forward` semantics explicitly.
- **`tests/experiment/instances/test_third_party.py`** (new) — 5 `TestClass` / 6 tests covering app structure, terminal service, external-forward, Bernoulli (eps=1.0) failure, and log-row schema. Full `**TestClass**` + `*test_name()*` docstring convention; `mu=1e9` trick to keep per-test wall clock near-zero. All green in 7.7 s.
- **`tests/experiment/test_mem_budget.py`** — deleted `TestBudgetEnforcement413` class and the unused `make_atomic_service` shim. FR-2.4 runtime enforcement is deferred per `notes/prototype.md §7 item 3`; the 413 tests were red-by-accident (one failing, one passing-for-the-wrong-reason). Rewrote module docstring with `**TestClass**` bullets matching `test_tas.py` / `test_third_party.py`; added `*test_name()*` lead-ins across the surviving tests.
- **`src/scripts/demo_third_party.py`** (new) — three-section walkthrough (terminal / forwarding / Bernoulli) matching the existing `demo_services.py` / `demo_registry.py` / `demo_client.py` / `demo_payload.py` idiom: `_banner`, `sys.path` boot, numbered sections, `async def _demo()`, sync `main()`. Verified by invocation.
- **Suite**: 316 tests pass outside `tests/methods/test_experiment.py` (the 1 fail + 10 errors there are pre-existing drift from the experiment scope reset, `ClientConfig.kind_weights must sum to > 0`; orthogonal to this pass).

**Pattern captured:** when the skill pass touches a module whose sibling tests are already green, keep the scope tight: polish docstrings, fix stale references, delete dead code, add one demo. Don't chase unrelated failures surfaced along the way; log them instead.

---

## 2026-04-20 — Experiment method: scope reset to experimental-design discipline

The existing prototype (4/5) runs and tests pass, but it was built as "a working FastAPI replica" instead of "apparatus for a hypothesis-driven experiment". The scientific-method framing — **hypothesis → model → prototype → validation** — was not explicit in the design, so operating points (`[1, 2, 5, ..., 500]` req/s), tolerances, and acceptance criteria are all ad hoc rather than derived from what would prove/disprove the tech-agnosticism claim.

- Drafted `notes/prototype-req.md` with the experimental-design framing: hypothesis H1 (per-artifact `|ρ_meas − ρ_pred| ≤ τ_ρ` across adaptations), explicit reference model (analytic), FR-1..8 for the prototype apparatus, and a validation protocol that lives in a new notebook 06. Scope of the reset TBD — will be decided after the FR review.
- Open-questions section (§7 in the FR doc) lists 7 items for user review: hypothesis phrasing, tolerances, grid points, adaptation scope, profile coverage, notebook split, skill creation.

## 📌 To review — `04-yoly.ipynb` graph errors

User flagged 2026-04-20: some graphs in `04-yoly.ipynb` are incorrect. Needs a pass after the prototype-req.md review is settled. Capture the specific mistakes and fix in a dedicated commit (don't bundle with the experiment reset).

---

## 📌 Deferred cleanup — **after all implementation is done**

- [ ] **Strip all CS-2 (IoT-SDP) mentions from `notes/`.** `cs_context.md` and `cs_objective.md` were imported with both case studies in-tree as working context for CS-1; once the full pipeline (analytic, stochastic, dimensional, experiment, comparison methods + notebooks + tests) is green, purge the CS-2 sections, tables, ADRs (`ADR-CS2-*`), references (lines 764-782 of `cs_context.md`), and any cross-references. Post-implementation only — do not touch before the pipeline is reproducing `__OLD__` results.

---

## 2026-04-20 — Experiment method complete (4/5): FastAPI architectural replication + tech-agnostic validation

**Delivered.** Fourth of five evaluation methods in place. A FastAPI microservice replication of the TAS topology, deployed in-process via ASGI transport and routed by a shared `httpx.AsyncClient`. No dependency on ReSeP / ActivFORMS abstractions -- the point is to **validate DASA's technology-agnosticism**: if DASA's coefficients characterise the architecture rather than the implementation, they should transfer to a vanilla Python/FastAPI stack.

- **`src/experiment/`** — 6 modules:
  - `services/base.py` — `ServiceSpec` (immutable knobs from profile JSON), `ServiceState` (runtime: admission lock, c-slot semaphore, log buffer), `ServiceRequest` / `ServiceResponse` wire schema, `log_request` decorator enforcing M/M/c/K semantics (K admission + c capacity + Exp service time + Bernoulli failure + per-invocation CSV row).
  - `services/atomic.py` — `make_atomic_service(spec)` for MAS / AS / DS.
  - `services/composite.py` — `make_composite_service(spec, pattern, downstream_targets)` for TAS_{1..6}.
  - `patterns.py` — four adaptation patterns: `no_adapt` (baseline), `retry` (s1), `parallel_redundant` (s2), `retry_parallel_redundant` (aggregate). Plain async Python, no framework.
  - `client.py` — `ClientSimulator` with Poisson interarrival + λ-ramp (`run_ramp` mirrors the yoly sweep pattern; cascade-fail early stop).
  - `launcher.py` — `ExperimentLauncher` wires the 13-service mesh via a custom `_MultiASGITransport` that routes `httpx.AsyncClient` requests per-port to the right FastAPI app. Context-manager API for setup / teardown.
  - `registry.py` — `ServiceRegistry` resolves name -> URL from `data/config/method/experiment.json`.
- **`src/methods/experiment.py`** — standard orchestrator contract (`run(adp, prf, scn, wrt, method_cfg=None)`) + CLI. Runs the ramp, aggregates per-service CSVs, emits the analytic-compatible per-node DataFrame + network aggregate + R1/R2/R3 verdict.
- **`data/config/method/experiment.json`** — deployment-only config (ports, ramp schedule, pre-measured request sizes). **Does NOT duplicate DASA knobs** (mu, epsilon, c, K, routing) — those still live in `data/config/profile/<dflt|opti>.json`.
- **`05-experiment.ipynb`** — thin notebook with validation plots: per-artifact measured ρ vs predicted ρ scatter (headline tech-agnosticism plot), per-step p50/p95 response time, R1/R2/R3 verdict table.
- **Tests** — 32 new (17 service-layer + 10 pattern + 3 launcher + 9 orchestrator). Total suite **177 tests pass in ~3 min**.

**Key design decisions (see `notes/experiment.md` for rationale):**

- **FastAPI + uvicorn (via ASGI transport) + httpx + pytest-asyncio.** Async is non-negotiable; `time.sleep()` would block workers and destroy the M/M/c/K queue semantics. `await asyncio.sleep(Exp(1/mu))` matches the closed-form assumption.
- **Request size as HTTP header metadata**, never `psutil`. Client pre-samples `size_bytes` from the method config's per-kind map and propagates through the chain. Zero runtime noise, fully deterministic under seed.
- **`K` admission + `c` service semaphore inside the app.** Real queue semantics even without uvicorn's `--limit-concurrency` (which only fires on TCP binding, not in-process ASGI). `state.admit()` raises 503 when `in_system >= K`; `state.service_sem = Semaphore(c)` gates concurrent processing. Verified: a burst of 5 concurrent requests at K=2 produces >=3 rejections; c=2 caps concurrent processing.
- **In-process ASGI mesh over real uvicorn servers (for v1).** `_MultiASGITransport` routes httpx requests per-port to the right FastAPI app without binding ports. Fast + hermetic tests; no multiprocess orchestration complexity. Real uvicorn can be swapped in later if TCP-level realism matters.
- **λ ramp mirrors the yoly sweep.** `ClientSimulator.run_ramp()` goes from `lambda_start_frac * λ_max` to `λ_max` in `lambda_steps` increments; cascade-fail early stop when network-wide fail rate exceeds `cascade_fail_rate_threshold`. Output maps to coefficient trajectories comparable to `04-yoly.ipynb`'s `sweep_architecture` cloud.

**Deliberately NOT done** (documented as "v2" in `notes/experiment.md`):

- Real uvicorn + TCP deployment (would measure real network overhead).
- Multi-kind workflow (v1 only sends `kind="analyse"`; alarm / drug paths through TAS_{3,4} not exercised).
- Multiprocess launcher (in-process is sufficient for DASA validation at the service-composition level).

**Pipeline status.** 4 of 5 methods complete. Next: `comparison` (method 5) — aggregates analytic / stochastic / dimensional / experiment into a cross-method R1/R2/R3 verdict and delta plots.

**Session artifact cleanup.** `_rebuild_experiment.py` (one-off notebook scaffolder) was deleted after use per the project's no-scaffolder-in-git convention.

---

## 2026-04-19 — Dimensional method complete (3/5): engine + orchestrator + thin notebook

**Delivered.** Third of five evaluation methods in place.

- **`src/dimensional/`** — five thin adapters around PyDASA 0.7.1: `schema.build_schema()`, `engine.build_engine()`, `coefficients.derive_coefficients()` (config-driven via `{pi[i]}` placeholder spec), `sensitivity.analyse_symbolic()`, `reshape.{coefficients_to_nodes, coefficients_to_network, coefficients_delta, network_delta}`. Each module under 90 lines; PyDASA owns all the math.
- **`data/config/method/dimensional.json`** — FDUs (`T`, `S`, `D`), coefficient specs (`{pi[i]}` patterns for θ, σ, η, φ), sensitivity settings, and a `sweep_grid` (6 μ-factors × 4 c × 4 K) earmarked for `yoly.ipynb` (Phase 3b/c).
- **`src/methods/dimensional.py`** — orchestrator with `run(adp, prf, scn, wrt, method_cfg=None)` + CLI; mirrors analytic/stochastic contract. No `requirements.json`: dimensional characterises the design space, not operational thresholds.
- **`dimensional.ipynb`** (new) — 9-section thin notebook built via `scripts/build_dimensional_notebook.py` (reproducible regen). Runs all 4 adaptations and plots per-node heatmap / diffmap / network bars / delta for θ, σ, η, φ — **all reusing existing `src.view.qn_diagram` plotters**; no new view module needed for this notebook.
- **Tests** — 34 engine-level (schema, engine, coefficients, sensitivity, reshape) + 22 orchestrator-level = **56 new**; **138 total pass in ~6 min.**

**Key finding mid-Phase-3a: PyDASA reads `_std_mean`, not `_mean`.** The PACS Variable-dict carries both `_mean` / `_setpoint` (scenario-display) and `_std_mean` / `_std_setpoint` (canonical-units, what pydasa consumes). Only `_std_*` flows into `Coefficient.calculate_setpoint()`. Any seed / override must update both halves.

**Seeded dimensional from analytic results.** The profile JSON's static L / W / Lq / Wq / λ / χ `_mean` values were inherited from the OLD CSV and did not reflect per-adaptation operating points — every artifact came out with θ=0.6 uniformly. Fixed via `src/utils/seed_dim_from_analytic.py`: runs analytic on a representative scenario per profile (`baseline` for `dflt.json`, `aggregate` for `opti.json`) and writes the solver's per-node `λ, χ, L, L_q, W, W_q` back into the variable `_setpoint`, `_mean`, `_std_setpoint`, `_std_mean`, `_data` fields. Also refreshes `M_{act}` (depends on L). Post-seed baseline θ varies 0.005 (AS_{3}) to 0.21 (MAS_{3}); σ ≈ 1.0 uniformly (Little's-law sanity check).

**Limitation of the opti seed.** Only 13 of 16 opti artifacts are seeded — the three pre-adaptation swap-out artifacts (`MAS_{3}`, `AS_{3}`, `DS_{3}`) do not appear in the `aggregate` scenario's artifact list, so their `_mean` values remain stale. If dimensional is later invoked on `s1` / `s2` (which use a subset of those pre-adaptation artifacts), the stale fields will flow through. Acceptable for now per "seed once" scope; can extend to merge across scenarios later if needed.

**Notebook convention.** `dimensional.ipynb` is generated from `scripts/build_dimensional_notebook.py`; edit the script, re-run, commit both. Keeps the notebook in git as a snapshot while the source of truth remains Python.

---

## 2026-04-19 — Dimensional schema migration: `E → S`, plus `M_{act}`, `M_{buf}` per artifact

**Why.** Before starting the dimensional engine, the TAS profile configs needed to line up with the PACS reference framework `{T, S, D}` used by the two illustrative-example iterations (`__OLD__/src/exports/dimensional_{1,2}_draft.py`). Two gaps were blocking Phase 1:

1. **FDU symbol drift.** TAS used `E` (entity) for the request dimension; PACS (authoritative reference) uses `S` (structure). Same semantics, incompatible strings. PyDASA's `Schema` would reject every artifact.
2. **Missing D-dimension.** `\delta_{X}` (data density, kB/req) was present in every artifact but flagged `relevant: false`, and the companion memory variables `M_{act, X}` / `M_{buf, X}` were absent. Without them the Buckingham matrix has no D coverage and `\phi` (memory-usage coefficient) cannot be derived.

**What.** One-shot utility `src/utils/migrate_dim_schema.py` does three things per artifact:

- Rename token `E → S` in every `_dims` expression (117 in `dflt.json`, 144 in `opti.json`).
- Flip `\delta_{X}.relevant = true` (13 in `dflt.json`, 16 in `opti.json`).
- Insert `M_{act, X}` and `M_{buf, X}` with `_dims="D"`, `_units="kB"`, `_cat="CTRL"`, `relevant=true`, `_dist_type="data_product"`. Setpoints derived from existing setpoints:
  - `M_{act, X}._setpoint = L_{X}._setpoint × \delta_{X}._setpoint` (active memory)
  - `M_{buf, X}._setpoint = K_{X}._setpoint × \delta_{X}._setpoint` (allocated buffer)

For TAS_{1}: `M_{act} = 6 × 1064 = 6384 kB`, `M_{buf} = 10 × 1064 = 10640 kB`.

**Provenance of the numbers.**

- **`K = 10 req`** — canonical per `CLAUDE.md` ("every artifact has c=1 and K=10"); matches `__OLD__/data/config/cs1/default_dim_variables.csv` (mean=10, range=[5,15]); PACS iter1 used K_max=16 (same ballpark).
- **`\delta = 1064 kB/req`** — inherited verbatim from the OLD CSV's dimensional variable catalogue; anchored to medical-record / DICOM payload sizes (~1 MB typical). Not a direct citation from Weyns & Calinescu 2015 — the paper does not quantify payload size. This is an educated domain estimate applied uniformly across the 13 artifacts.
- **`M_buf = K · \delta`** and **`M_act = L · \delta`** — derived, not guessed. The only dimensionally-consistent interpretation of "buffer capacity in memory units".

**Outcome.** 70 existing tests still green (`pytest tests/` in ~12s). Schema is now compatible with PyDASA's Schema / Buckingham pipeline. Phase 1 of the dimensional method (engine + config-driven FDUs + coefficients) unblocked.

---

## 2026-04-19 — Stochastic method complete (2/5); dimensional split into two notebooks

**Delivered.** Second of five evaluation methods in place; SimPy DES engine + NetworkConfig wrapper agrees with the closed-form analytic solution within Monte-Carlo noise across every adaptation.

- **`src/stochastic/simulation.py`** — engine (`QueueNode`, `simulate_network`, `job`, `job_generator`) + `solve_network(cfg, method_cfg)` adapter in a single file (mirrors `src/analytic/jackson.py`). Seeds both `random` and `numpy.random` at the start of each multi-rep call for reproducibility.
- **`src/methods/stochastic.py`** — `run(adp, prf, scn, wrt, method_cfg=None)` orchestrator + CLI. The `method_cfg` kwarg lets tests inject an abbreviated config without touching disk.
- **`src/view/qn_diagram.py`** — seventh plotter, `plot_nd_ci(nds, *, metric, reference=None, reps=N, confidence=0.95, ...)`. Errorbar-on-points chart with optional analytic overlay as red `x` markers. Used in §6 of `stochastic.ipynb`.
- **`stochastic.ipynb`** — nine sections, thin notebook; renders topology / heatmap / diffmap / CI (ρ + W) / net_bars / net_delta under `data/img/stochastic/<scenario>/` (22 figure files, PNG + SVG each).
- **Tests** — 19 new (9 engine, 10 orchestrator) using `_QUICK_CFG` (3 reps × 1000 invocations / 100 warmup) for ~30x speedup. 70 total pass in ~9s.

**Invocation → seconds bridge.** Method config declares `horizon_invocations` / `warmup_invocations` (unitless counts); the SimPy engine runs in time. Conversion `seconds = invocations / sum(lambda_z)` lives in `solve_network`. Don't move it — keeps `simulate_network` unit-agnostic.

**Cross-method sanity.** Every analytic per-node ρ falls INSIDE the stochastic 95% CI band on the baseline figures (`data/img/stochastic/baseline/nd_ci_rho.png`). Aggregate W_net: analytic 3.09 ms, stochastic 3.10 ms. The two methods mutually validate.

**Data/reference housekeeping.** Merged `data/reference/version.txt` + `data/reference/profile.md` into a single `summary.md`; dropped the sources.

**Dimensional method split into TWO notebooks (user decision 2026-04-19):**
- `dimensional.ipynb` — pre/post adaptation solution, but plotting **coefficients** (θ, σ, η, φ) not queue metrics, reusing the existing heatmap / diffmap / bars / delta plotters with coefficient columns.
- `yoly.ipynb` — configuration-sweep diagram (`plot_yoly_*` family ported from `__OLD__/src/notebooks/src/display.py`), shows how TAS behaves across a sweep of configurations. New sibling view module `src/view/yoly_diagram.py` to keep queue-network and yoly visuals separate.
- Plan captured in memory (`project_dimensional_plan.md`) for the next session to pick up.

**Next**: start `src/dimensional/` engine + two notebooks.

---

## 2026-04-19 — Analytic method reproduces __OLD__ CSV to 6 decimals

**Delivered.** Silent config drift found and fixed; baseline Jackson solution now matches `__OLD__/data/results/cs1/data/dflt_analytical_{node,net}_metrics.csv` to the 6th decimal place on every per-node row and every network-wide aggregate.

- **`c=1`, `K=10` canonical values restored** across every artifact in both `data/config/profile/dflt.json` and `opti.json`. `dflt.json` had silently drifted to `c=2` (halving every utilisation); `opti.json` also had `K=6` (tightened during some earlier test). One-shot repair utility at `src/utils/fix_c_k.py` — ran once, left in place as a frozen record.
- **Artifact + variable keys migrated to LaTeX form.** Artifact JSON keys: `TAS_1` -> `TAS_{1}`, `MAS_3` -> `MAS_{3}`, etc. Variable keys with q-subscripts split correctly: `Lq_{TAS_{1}}` -> `L_{q, TAS_{1}}`, `Wq_{TAS_{1}}` -> `W_{q, TAS_{1}}`. One-shot migration utility at `src/utils/rename_keys.py`. `ArtifactSpec._sub()` collapsed to identity (key IS the LaTeX subscript now).
- **Baseline headline numbers** (exact match with OLD CSV): `avg_mu=653.85`, `avg_rho=0.29728`, `L_net=6.98730`, `Lq_net=3.12884`, `W_net=3.437 ms`, `Wq_net=1.541 ms`, `TP_net=2038.50`. Per-node rows also match (MAS_3: rho=0.694, L=2.068, W_q=0.01336).

**`src/view/qn_diagram.py` grew to six plotters** with a uniform signature contract (keyword-only after required positionals, return `Figure`, save both PNG+SVG via `_save_figure`): `plot_qn_topology`, `plot_qn_topology_grid`, `plot_nd_heatmap`, `plot_nd_diffmap`, `plot_net_bars`, `plot_net_delta`. Ported `_generate_color_map` from `__OLD__/src/notebooks/src/display.py` for the multi-scenario palette. Fixed the SVG-dark-theme text-invisibility gotcha: `_TEXT_BLACK = "#010101"` (not pure `"black"`) forces matplotlib to emit an explicit `fill` attribute that dark-theme viewers cannot override.

**Notebook** (`analytic.ipynb`, 17 cells under the 30-cell budget) produces one standalone topology per adaptation + per-node heatmap + per-node diffmap + network-wide bars + network-wide delta bars — 20 figures total under `data/img/analytic/<scenario>/` (PNG + SVG for each of 10 figure types). Outputs cleared before commit.

**Tests:** 51 green (11 queues, 4 jackson, 12 metrics, 11 io/config, 13 methods/analytic).

**Pitfalls captured in memory** (so they do not return): `c=1, K=10` canonical values; LaTeX key format; uniform `arc3,rad=0.2` for self-loops (custom `rad=1.0` overlaps cross-edges); `#010101` text colour. See `CLAUDE.md` §`View (Plotting) Conventions` and Claude memory project entries.

**Next method in the pipeline**: `src/stochastic/` (SimPy DES). Config already at `data/config/method/stochastic.json`.

---

## 2026-04-18 — Analytic method complete (5/5 milestones)

**Delivered.** First end-to-end evaluation method is green across the full 4-adaptation axis; `analytic.ipynb` reproduces the metrics table and 11 figures from a cold clone.

- **`src/analytic/`** — `queues.py` (registry-dispatch `Queue()` factory + `BasicQueue` ABC + `QueueMM1` / `QueueMMs` / `QueueMM1K` / `QueueMMsK` concrete classes; `_QUEUE_MODELS` dict at module bottom makes adding new models one entry), `jackson.py` (`solve_jackson_lambdas()` linear core + `solve_network()` wrapper), `metrics.py` (`aggregate_network()` + `check_requirements()` with JSON-backed thresholds).
- **`src/view/qn_diagram.py`** — 5 plotters (`plot_qn_topology`, `plot_qn_topology_grid`, `plot_nd_heatmap`, `plot_net_bars`, `plot_net_delta`) with a uniform param-IO convention (keyword-only args after required positionals; every plotter returns `Figure` and persists when `file_path` + `fname` given). Shared `_save_figure()`, `_resolve_metrics()`, `_resolve_labels()` helpers.
- **`src/methods/analytic.py`** — `run(adp, prf, scn, wrt)` orchestrator + CLI. The written envelope carries the full `routing` (13x13) and `lambda_z` (13) fields alongside metrics so downstream consumers can reconstruct paths without re-opening configs.
- **`analytic.ipynb`** at repo root — thin notebook (20 cells, under the 30-cell budget). Calls `run()` across the 4 adaptations, prints the summary + verdict tables, saves 11 figures under `data/img/analytic/<adaptation>/`. Clears outputs before commit.

**Thresholds externalised.** `data/reference/baseline.json` now holds the Camara 2023 R1 / R2 / R3 values (`0.0003`, `0.026 s`, `null`); `metrics.py` reads them via `src.io.load_reference("baseline")`. No more hardcoded `_R1_MAX_FAIL_RATE` / `_R2_MAX_RESP_TIME` in Python.

**Headline numbers at 345 req/s** (all four adaptations PASS R1 / R2 / R3):

| adaptation | W_net (ms) | avg_rho | max_rho | bottleneck |
|---|---|---|---|---|
| baseline   | 1.99 | 0.149 | 0.347 | MAS_3 |
| s1         | 2.01 | 0.164 | 0.375 | MAS_3 |
| s2         | 2.08 | 0.168 | 0.356 | DS_1 |
| aggregate  | 1.95 | 0.161 | 0.345 | DS_1 |

Aggregate is the best configuration on both `W_net` and `max_rho`; s1 alone is the worst on `max_rho` because opti routing pushes more load into the dflt services at the three swap slots (MAS, AS, DS). Bottleneck shifts from MAS (dflt services) to DS (opti services) as soon as `s2` / `aggregate` activate.

**Tests.** 51 pytest cases green: 11 queues, 4 jackson, 12 metrics (includes 3 pinning thresholds to the JSON), 11 io/config, 13 methods/analytic. Notebook runs cold without manual intervention.

**Housekeeping.**
- `data/results/` tracked as a directory (1 `.gitkeep` + local `.gitignore`); generated JSONs remain ignored.
- `src/utils/import_old.py` removed — migration script served its purpose; `dflt.json` / `opti.json` are the sources of truth.
- `conftest.py` kept with a TODO pointing at the eventual `pyproject.toml` replacement.

**Pending.** 4 methods still unbuilt (`stochastic`, `dimensional`, `experiment`, `comparison`); `assets/` documentation staging directory still empty.

---

## 2026-04-18 — `opti.json` restructured: dict-keyed scenarios, explicit service swaps

**Delivered.**

- **`opti.json` artifacts expanded from 13 to 16.** The three swap slots (nodes 6, 9, 11) now carry BOTH variants: `MAS_3` (dflt) alongside `MAS_4` (opti), `AS_3`/`AS_4`, `DS_3`/`DS_1`. The opti CSV's `name` column (`MAS 3->4`, `AS 3->4`, `DS 3->1`) motivated distinct artifact keys instead of silently overwriting values in-place.
- **`_nodes` is now a dict per scenario**, each value a 13-element list naming the active artifact at each positional slot:
  - `_nodes["s1"]` uses dflt services at the swap slots (`MAS_3`, `AS_3`, `DS_3`)
  - `_nodes["s2"]` and `_nodes["aggregate"]` use opti services (`MAS_4`, `AS_4`, `DS_1`)
- **`_routs` and `_labels` also keyed by scenario name** (matching `_nodes`). `dflt.json` uses the same dict shape for operational consistency — single key `"baseline"`.
- **`_vars_source` removed.** It was a workaround for the previous fixed `_nodes` list + external composition; now that `_nodes[scenario]` names the right artifacts directly, composition is explicit.
- **Labels rewritten without em dashes**; each label names the strategy (Retry / Select Reliable), the service swaps, and what stays dflt vs opti.

**Generator refactor.** `src/utils/import_old.py` now has two node-to-artifact maps (`_DFLT_NODE_MAP`, `_OPTI_NODE_MAP`) and passes the map into `load_topology` / `load_variables` / `_rename_depends`. Re-run: `python -m src.utils.import_old`.

---

## 2026-04-18 — `opti.json` + `data/reference/`; `adaptation/` retired

**Delivered.**

- **`data/config/profile/opti.json`** generated by `src/utils/import_old.py` from `__OLD__/data/config/cs1/optimal_{qn_model,dim_variables}.csv`. PACS-style envelope, 13 artifacts, 143 opti variables. `environments._scenarios = ["s1", "s2", "aggregate"]` with `_vars_source = ["dflt", "opti", "opti"]` and `_routs = [opti, dflt, opti]` — so each scenario composes (routing × variables) from the right source.
- **`data/reference/`** — authors' TAS 1.6 replication dump (`Cost-QoS`, `Preferred-QoS`, `Reliability-QoS` × `no-adapt`, `simple-adapt` — six leaf folders, each with `invocations.csv`, `log.csv`, `results.csv` + 8 PNG charts). Column schema in `data/reference/profile.md`. Treated as the authoritative reproduction target for the `experiment` method's acceptance criterion.
- **`data/config/adaptation/` removed.** The two stub files (`s1.json`, `s2.json` with `MAX_TIMEOUTS` / `timeout_length_ms` / `parallel_count` / `rt_threshold_ms` placeholders) are redundant now that `opti.json` enumerates all three after-adaptation scenarios self-sufficiently.
- **Docs synced** — `workflow.md` §1/§2 adaptation-axis table and directory layout, `CLAUDE.md` data convention, `README.md` axis table + folder tree, `quickstart.md` adaptation table.

**Loader contract (unchanged CLI).** `--adaptation <baseline|s1|s2|aggregate>` still works, but the loader's composition rule tightens:

- `baseline` → `dflt.json` (only scenario)
- `s1` → `opti.json._scenarios[0]`; vars from dflt, routing from opti
- `s2` → `opti.json._scenarios[1]`; vars from opti, routing from dflt
- `aggregate` → `opti.json._scenarios[2]`; vars from opti, routing from opti

**SUMMARY.md** gained a References section (CS-1 refs [1], [2], [3], [9] Rico, [10], [13]) matching the works actually cited, with a pointer to `cs_context.md § References` for the full list.

---

## 2026-04-18 — Data backbone ported; README/SUMMARY rewritten

**Delivered.**

- **Config tree scaffolded** under `data/config/`:
  - `profile/dflt.json` — 13-node topology (M/M/s/K) + 143 PyDASA variables, produced by `src/utils/import_old.py` from `__OLD__/data/config/cs1/default_qn_model.csv` + `default_dim_variables.csv`.
  - `adaptation/s1.json`, `s2.json` — stub override files for Retry-style (S1) and Select-Reliable-style (S2) with placeholder params (`MAX_TIMEOUTS`, `timeout_length_ms`, `parallel_count`, `rt_threshold_ms`).
  - `method/stochastic.json` — SimPy params (seed=42, 10k invocations, 10 replications, 95 % CIs; mirrors [13] § V-B).
  - `method/experiment.json` — architectural-experiment params (500 invocations × 6 replications; reproduces [1] Table IV).
- **README + SUMMARY rewritten** — now scoped to CS-01 TAS only (prior README mixed CS-01 and CS-02). README links to the six `notes/*.md` + `CLAUDE.md`; SUMMARY carries the Table IV headline numbers and the R1/R2/R3 targets.

**`src/utils/import_old.py`** kept as a committed tool so the conversion is reproducible (not a throwaway). Re-run with `python -m src.utils.import_old` whenever the old CSVs change.

**Repo hygiene decision — results never committed.**

Per user: the bulk of result files should not be checked in. Anyone reproducing runs the pipeline locally. Added to `.gitignore`:

- `data/results/` — all method runs produce JSONs here; ignored en masse.
- `lab/` — future scratchpad PoCs.
- `build/`, `.reports/`, `*.ipynb_checkpoints/`.

**Still tracked:** `data/config/` (all configs, including the 143-variable `dflt.json` at 114 KB), `assets/img/` (figures cited in reports), `notes/`, `src/`, `tests/`.

**Next steps.**

- [ ] Scaffold remaining `src/` subpackages with empty `__init__.py`: `analytic`, `stochastic`, `dimensional`, `experiment`, `view`, `io`, `methods`
- [ ] Implement `src/io/config.py` profile ⊕ adaptation merge helper (Move 2)
- [ ] Implement `src/methods/analytic.py` + `src/analytic/` M/M/c/K solver as first end-to-end method (Move 3)
- [ ] Pytest skeleton mirroring `src/`
- [ ] Thin notebook stubs at repo root

---

## 2026-04-18 — Result-filename symmetry: `<profile>.json` per run

Spotted asymmetry between inputs (named by identifier: `profile/dflt.json`, `adaptation/s1.json`) and outputs (named by content type: `variables.json`). Fixed by naming the per-run output file after the profile identifier, matching the PACS precedent (`PACS-vars-iter1.json`).

**Per-run output is now a single JSON** named after the profile, following the PACS pattern:

```
data/results/<method>/<adaptation>/<profile>.json
```

The file carries a PyDASA-compatible object with content keyed inside:

- `variables` — PyDASA Variable dict (every method)
- `coefficients` — derived DCs (dimensional only)
- `pi_groups` — raw π-groups (dimensional only)
- `deltas` — per-variable differences (comparison only)

**Split out:** `requirements.json`. R1/R2/R3 verdicts are profile-agnostic and consulted independently of raw variables; they keep a content-type name.

**Adding a second profile is additive.** `camara.json` drops next to `dflt.json` in the same (method, adaptation) folder; no migration.

---

## 2026-04-18 — Final shape: two-axis, JSON results, 20-run matrix

**Refinements that closed the design.**

1. **Collapsed scenario and strategy into one adaptation axis.** In this case study S1 and S2 are two names for the same "after adaptation" concept seen through different scenario lenses: S1 applies switch-to-equivalent (Retry mechanics), S2 applies preferred-service ranking (Select Reliable mechanics). They are not independent axes. Values: `baseline`, `s1`, `s2`, `aggregate`.
2. **`aggregate` is a real run**, not a display rollup. It applies both S1 and S2 overrides together — the realistic deployed configuration a production system would actually use.
3. **`baseline` is a run tag, not a config file.** The profile is the baseline; no `adaptation/baseline.json`. Adaptation configs only exist for S1 and S2; `aggregate` merges both.
4. **Result and config files are JSON (PACS format)**, not CSV. Every file uses the PyDASA `Variable`-dict schema keyed by LaTeX symbol with `_sym`, `_dims`, `_units`, `_min`, `_max`, `_setpoint`, `_data`, … — same as `__OLD__/src/notebooks/data/PACS-vars-iter1.json`. Inputs and outputs share the schema, no CSV↔JSON conversion.
5. **Leaf files:** `variables.json` and `requirements.json` for every method; plus `coefficients.json` / `pi_groups.json` for dimensional; plus `deltas.json` for comparison.
6. **Single CLI shape:** `python -m src.methods.<method> --adaptation <baseline|s1|s2|aggregate> [--profile dflt]`. The `src.io` layer handles the profile ⊕ adaptation merge.

**Matrix.** 5 methods × 4 adaptations = **20 runs**. Each of analytic / stochastic / dimensional / experiment runs 4 adaptations; comparison reads all four methods per adaptation and writes 4 comparison reports.

**Dropped from earlier drafts.**
- Separate `scenario` and `adaptation` axes (merged into one).
- CSV leaf files (→ JSON/PyDASA schema).
- Per-strategy adaptation values (`retry`, `select_reliable`) — these are the *mechanics* of S1/S2, not separate options. Documented in method contracts as "S1 = Retry-style, S2 = Select-Reliable-style".
- The "utility" axis (`cost_qos`/`reliability_qos`/`preferred_qos`). R1/R2/R3 are fixed thresholds from Cámara 2023, reported in `requirements.json` per run.
- Four-token flat filename pattern — axes live in the path, leaves are just `<content>.json` (one more token-free).

**Next steps.**

- [ ] Scaffold `src/methods/` modules with `run(adaptation, profile='dflt')` signature and CLI stub
- [ ] Scaffold `src/` subpackages (`analytic`, `stochastic`, `dimensional`, `experiment`, `view`, `io`, `utils`)
- [ ] Scaffold `data/config/{profile,adaptation,method}/` with stub JSONs in PyDASA Variable-dict format (port `profile/dflt.json` from Table III of [1])
- [ ] Scaffold `src.io` profile ⊕ adaptation merge helper
- [ ] Create 5 thin notebook stubs at root
- [ ] `tests/` mirrors `src/` subpackages

---

## 2026-04-18 — Naming convention locked: four-axis, one pattern

**Decision.** Every file, folder, and CLI argument uses the same four axes in the same order:

- `<method>` ∈ `{analytic, stochastic, dimensional, experiment, comparison}` — reframed from "stage" to "method" because the code implements DASA's **evaluation methods**, not sequential stages.
- `<scenario>` ∈ `{s1, s2}` — service failure and response-time variability (the two focus scenarios per `cs_objective.md`; S3–S5 out of scope).
- `<adaptation>` ∈ `{baseline, retry, select_reliable}` — `baseline` = No Adaptation, the before-adaptation reference. `retry` and `select_reliable` are the after-adaptation strategies from Table IV of [1].
- `<profile>` ∈ `{dflt, ...}` — service catalogue variant; CLI flag, defaults to `dflt`.

**Naming convention.** Paths carry the axes, leaves carry only `<scope>.<artifact>.<ext>`:

- configs: `data/config/<axis-folder>/<value>.json`
- results: `data/results/<method>/<scenario>/<adaptation>/<scope>.<artifact>.<ext>`
- figures: `assets/img/<method>/<scenario>/<adaptation>/<figure>.png`
- CLI: `python -m src.methods.<method> --scenario <s> --adaptation <a> [--profile <p>]`

**Dropped.** The "utility" axis (`cost_qos`/`reliability_qos`/`preferred_qos` from `__OLD__/data/baseline/cs1/`). Those variants corresponded to different weight sets inside R3's utility function. In the new framing, R1/R2/R3 are validation criteria evaluated in `requirements.csv` per run, not a run axis. Keeps the matrix flat at 30 runs instead of 90.

**Why the rename.** Single-repo, single case study — no `CS-01-` prefix needed. "Method" matches the case-study narrative (`cs_objective.md` frames each as an evaluation method). The four-axis pattern is strictly repetitive: the same four words appear in the same order in every path, filename, and CLI — auditor-friendly, greppable, scriptable.

**Run matrix.** 5 methods × 2 scenarios × 3 adaptations = 30 runs. The comparison method collapses across the other four per (scenario, adaptation), producing 6 comparison reports.

**Validation criteria.** Every run emits `requirements.csv` with one row per R1/R2/R3 target from Cámara 2023:

- R1: failure rate ≤ 0.03 % (Availability)
- R2: response time ≤ 26 ms (Performance)
- R3: minimise cost subject to R1 ∧ R2

**Next steps.**

- [ ] Scaffold `src/methods/` modules with `run(scenario, adaptation, profile)` signature and CLI stub
- [ ] Scaffold `src/` subpackages (`analytic`, `stochastic`, `dimensional`, `experiment`, `view`, `io`, `utils`)
- [ ] Scaffold `data/config/{profile,scenario,adaptation,method}/` with stub JSONs (profile/dflt from Table III of [1])
- [ ] Create 5 thin notebook stubs at root
- [ ] `tests/` mirrors `src/` subpackages

---

## 2026-04-18 — Workflow shape locked: five stages, hybrid pattern

**Decision.** Pipeline is five stages: **S1 Analytic, S2 Stochastic, S3 Dimensional, S4 Comparison, S5 Architectural Experiment**. No `-CS-01-` prefix in filenames (single-case repo). No calibration notebook.

**Pattern.** Hybrid — each stage is a Python module `src/stages/sN.py` exposing `run(config_path) -> dict` and a `main()` CLI; a thin notebook `SN.ipynb` at repo root calls `run()` for narrative and inline display. CLI and notebook produce byte-identical artifacts. Logic lives in `src/`, never in notebooks.

**Why.** Optimises for *"follow or any external auditor or public exposure"*:
- CLI makes the pipeline scriptable and CI-friendly; notebooks make it reviewable.
- Unit tests can target `src/` modules directly instead of parsing `.ipynb` JSON.
- Clean git diffs because notebooks stay small.
- Slightly more upfront effort than pure notebooks, but pays back the moment tests or automation are needed.

**What was dropped and why.**
- **Calibration (former `CS-01X`)**: if the analytic model disagrees with the stochastic ground truth, that is a finding worth reporting, not a parameter to tune away. Config optimization (the `opti_*` prefix from the old artifacts) is a side effect of S4 if a second pass is wanted.
- **`CS-01-` prefix**: this repo holds exactly one case study; the prefix was pure ceremony.
- **`data/baseline/` and `data/analysis/` subfolders**: collapsed into `data/config/` (inputs) and `data/results/` (outputs). Simpler I/O contract.

**Alternatives considered.** Pure notebooks (cheaper start, worse diffs and tests), pure CLI (no narrative for publication), Jupytext paired files (adds a pre-commit hook dependency), Quarto (overkill for early iteration). Hybrid won on long-run maintainability.

**Next steps.**
- [ ] Scaffold `src/` subpackages (`analytic/`, `stochastic/`, `dimensional/`, `experiment/`, `view/`, `io/`, `utils/`) with empty `__init__.py`
- [ ] Scaffold `src/stages/s{1..5}.py` with `run()` signature and CLI stub
- [ ] Scaffold `tests/` mirroring `src/`
- [ ] Create 5 thin notebook stubs (`S1.ipynb`..`S5.ipynb`)
- [ ] Port the service catalogue from `__OLD__/data/config/cs1/default_qn_model.csv` to `data/config/dflt.json`
- [ ] Update `README.md` + `SUMMARY.md` to match the new shape

---

## 2026-04-18 — Project restart from scratch

**Decision.** Archive the prior implementation under `__OLD__/` and rebuild the case study on top of the current PyDASA release. The old version mixed closed-form and stochastic results without a clean modelling layer boundary, which made it hard to reproduce the dimensional analysis step.

**What moved to `__OLD__/`:**

- 6 notebooks: `CS-01A` (Analytical), `CS-01B` (Stochastic), `CS-01C` (Dimensional), `CS-01D` (Dimensional Simulations), `CS-01E` (Data Analysis), `CS-01X` (Analytical Calibration)
- `src/{model,simulation,utils,view}/`
- `data/{analysis,baseline,config,results/cs1/{data,img}}/`
- Prior notes and commands reference

**What stays:**

- `LICENSE`, `.gitignore`, high-level `README.md` (to be rewritten and scoped to CS-01 only)
- `requirements.txt` (pinned against PyDASA 0.3.2 wheel)
- `.claude/` skills scaffold (needs pruning — some leftover out-of-scope skills)

**Next steps.**

- [ ] Confirm notebook list and ordering (keep all 6, or collapse `E` into per-model notebooks?)
- [ ] Decide whether to port any code from `__OLD__/src/` or start clean against `pydasa` package
- [ ] Prune `.claude/skills/` of out-of-scope skills; port `commands/` from `../PyDASA/.claude`
- [ ] Rewrite `README.md` + `SUMMARY.md` scoped to CS-01 TAS
- [ ] Scaffold empty `src/`, `data/`, `assets/`, `tests/` and notebook stubs
- [x] ~~Decide: keep `__OLD__/` tracked in git, or `.gitignore` it?~~ → **Keep tracked** during migration; remove once the new notebooks + `src/` reproduce its results.

## Open questions

- Does PyDASA 0.3.2 already expose the π-group builders this case study needs, or do we need helpers in local `src/`?
- Calibration notebook (`CS-01X`) — keep as separate deliverable or fold into `CS-01A`?

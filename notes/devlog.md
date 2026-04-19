# Devlog — CS-01 TAS

Running log of design decisions, pivots, and open questions for the Tele Assistance System case study. Append only; newest entry on top.

---

## 📌 Deferred cleanup — **after all implementation is done**

- [ ] **Strip all CS-2 (IoT-SDP) mentions from `notes/`.** `cs_context.md` and `cs_objective.md` were imported with both case studies in-tree as working context for CS-1; once the full pipeline (analytic, stochastic, dimensional, experiment, comparison methods + notebooks + tests) is green, purge the CS-2 sections, tables, ADRs (`ADR-CS2-*`), references (lines 764-782 of `cs_context.md`), and any cross-references. Post-implementation only — do not touch before the pipeline is reproducing `__OLD__` results.

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

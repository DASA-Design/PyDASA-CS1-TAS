# Workflow — TAS case study

How this repository is executed. **Two axes, one pattern everywhere:**

| Axis | Values | Carried by |
|---|---|---|
| `method` | `analytic`, `stochastic`, `dimensional`, `experiment`, `comparison` | top-level folder + module name |
| `adaptation` | `baseline`, `s1`, `s2`, `aggregate` | `--adaptation` flag + subfolder |

`profile` is an optional CLI flag that selects the service catalogue (defaults to `dflt`). Full case context in `notes/cs_context.md`; case-study narrative in `notes/cs_objective.md`. This repo realises the DASA evaluation for CS-1 TAS.

---

## 0. Pipeline overview

```
                   ┌──────────────────────────────────┐
                   │        INPUT: data/config/       │
                   │       profile/ · method/         │
                   └──────────────────┬───────────────┘
                                      │
 ┌─────────────────── EVALUATION METHODS ─────────────────────────┐
 │                                                                │
 │  ┌───────────┐   ┌───────────┐   ┌────────────┐   ┌──────────┐ │
 │  │ analytic  │   │stochastic │   │dimensional │   │experiment│ │
 │  │ closed-   │   │  SimPy    │   │  PyDASA    │   │ mock     │ │
 │  │ form QN   │   │   DES     │   │ π + DCs    │   │ ReSeP    │ │
 │  └─────┬─────┘   └─────┬─────┘   └─────┬──────┘   └─────┬────┘ │
 │        │               │               │                │      │
 │        └───────────────┴──────┬────────┴────────────────┘      │
 │                               ▼                                │
 │                        ┌───────────────┐                       │
 │                        │  comparison   │                       │
 │                        │ deltas, R1/R2/│                       │
 │                        │ R3 check,plots│                       │
 │                        └───────┬───────┘                       │
 └────────────────────────────────┼───────────────────────────────┘
                                  ▼
                     ┌──────────────────────────┐
                     │  OUTPUT: data/results/   │
                     │         assets/img/      │
                     └──────────────────────────┘
```

Each of the four evaluation methods runs the full adaptation axis (4 runs). `comparison` reads the other four and writes deltas and the R1/R2/R3 verdict. Matrix: 5 methods × 4 adaptations = **20 runs**.

---

## 1. Adaptation axis — before, selective, combined

| Value | Meaning | Source |
|---|---|---|
| `baseline` | Before adaptation. MAPE-K inert. | `profile/dflt.json`, scenario `baseline` (only scenario) |
| `s1` | Selective adaptation for *S1 service-failure* scenario. | `profile/opti.json`, scenario `s1` (opti routing + dflt services at swap slots: `MAS_3`, `AS_3`, `DS_3`) |
| `s2` | Selective adaptation for *S2 response-time* scenario. | `profile/opti.json`, scenario `s2` (dflt routing + opti services at swap slots: `MAS_4`, `AS_4`, `DS_1`) |
| `aggregate` | Combined adaptation — both S1 and S2 in effect. | `profile/opti.json`, scenario `aggregate` (opti routing + opti services) |

In this case study, S1 and S2 are two names for the same *after-adaptation* concept seen through different scenario lenses: S1 applies switch-to-equivalent (the *Retry* mechanics from [1]) and S2 applies preferred-service ranking (the *Select Reliable* mechanics). The `aggregate` run is what a production deployment would actually use — both mechanisms active — while `s1` and `s2` isolate each contribution.

`baseline` picks `dflt.json`. `s1`/`s2`/`aggregate` all pick `opti.json` and look up the scenario by name in `environments._nodes[scenario]` (the list of 13 artifact keys active at each positional slot) and `environments._routs[scenario]` (the 13×13 routing matrix). `opti.json` carries both dflt-variant and opti-variant artifacts for the three swap slots — `_nodes["s1"]` references the dflt variants (`MAS_3`, `AS_3`, `DS_3`); `_nodes["s2"]` and `_nodes["aggregate"]` reference the opti variants (`MAS_4`, `AS_4`, `DS_1`).

**Default scenario.** `environments._setpoint` names the scenario the loader reads when no `--adaptation` is given on the CLI. `dflt.json._setpoint = "baseline"`; `opti.json._setpoint = "aggregate"` — so running `python -m src.methods.<method>` with no flags targets the most representative configuration for each profile.

---

## 2. Naming convention — one pattern, everywhere

### Configs

```
data/config/
├── profile/
│   ├── dflt.json                  # baseline catalogue (Table III of [1]); scenario: "baseline"
│   └── opti.json                  # opti catalogue (optimal_*.csv); scenarios: s1, s2, aggregate
└── method/
    ├── stochastic.json            # seed, horizon, replications, warmup
    └── experiment.json            # duration, load profile, fault injection
```

All profile files use the PACS-style envelope: `artifacts` keyed by short ID (13 in `dflt.json` — `TAS_1..6`, `MAS_1..3`, `AS_1..3`, `DS_3`; 16 in `opti.json` — the 13 above plus `MAS_4`, `AS_4`, `DS_1` for the three swap slots) plus `environments` (`_setpoint`, `_scenarios`, `_labels`, `_nodes`, `_note`, `_routs`). `_labels`, `_nodes`, and `_routs` are all dicts keyed by scenario name (`baseline` in `dflt.json`; `s1`, `s2`, `aggregate` in `opti.json`). Variables inside each artifact's `vars` block follow the PyDASA `Variable`-dict schema (keyed by LaTeX symbol: `\\lambda_{TAS_{1}}`, `\\mu_{MAS_{2}}`, `c_{AS_{3}}`, `K_{DS_{3}}`, …) — same format as `__OLD__/src/notebooks/data/PACS-vars-iter2.json`.

The two-file split replaces the earlier `profile/` + `adaptation/` overlay model; `opti.json` is self-contained and enumerates the three after-adaptation scenarios directly, each picking dflt- or opti-variant artifacts at the three swap slots via its `_nodes[scenario]` list.

### Results

```
data/results/<method>/<adaptation>/
├── <profile>.json                 # PACS-style: one JSON per run, keyed by content
└── requirements.json              # R1/R2/R3 verdicts (cross-cutting)
```

The per-run `<profile>.json` (e.g. `dflt.json`) is a single PyDASA-compatible object:

```json
{
  "profile": "dflt",
  "method": "dimensional",
  "adaptation": "s1",
  "variables":   { "\\lambda_{AS}": { ... }, ... },        // always
  "coefficients":{ "\\theta_{AS}": { ... }, ... },         // dimensional only
  "pi_groups":   [ ... ],                                  // dimensional only
  "deltas":      { ... }                                   // comparison only
}
```

Filename = profile identifier (same rule as inputs). Adding a second profile is additive: `camara.json` sits next to `dflt.json` in the same folder. `requirements.json` stays split out because R1/R2/R3 is consulted independently of raw variables — and because its schema is profile-agnostic.

### Figures

```
data/img/<method>/<adaptation>/<figure_name>.{png,svg}
```

### Leaf-filename pattern

- **Profile-stamped** leaves use the profile identifier: `<profile>.json`. The path tells you the method and adaptation; the filename tells you the profile. Symmetric with config inputs (`profile/<profile>.json`).
- **Content-type** leaves have fixed names: `requirements.json`. These are profile-agnostic schemas consulted independently.
- Figures under `data/img/<method>/<adaptation>/` use descriptive lowercase stems. Reusable prefixes indicate which plotter produced the figure.

### Plotter filename acronyms

Short prefixes on figure stems identify the source plotter so reviewers can trace a PNG/SVG back to the producing code. Used across `data/img/<method>/...` and the throwaway `_sandbox/` dumps.

| Prefix | Plotter | Expansion |
|---|---|---|
| `nd_` | `plot_nd_heatmap` / `plot_nd_diffmap` / `plot_nd_ci` | **n**o**d**e (per-artifact) |
| `net_` | `plot_net_bars` / `plot_net_delta` | **net**work-wide |
| `topology` | `plot_qn_topology` / `plot_qn_topology_grid` | QN architecture |
| `ad_` | `plot_arts_distributions` | **a**rts **d**istributions |
| `sb_` | `plot_system_behaviour` | **s**ystem **b**ehaviour |
| `yc_` | `plot_yoly_chart` | **y**oly **c**hart |
| `yab_` | `plot_yoly_arts_behaviour` | **y**oly **a**rtifact **b**ehaviour |
| `yac_` | `plot_yoly_arts_charts` | **y**oly **a**rtifact **c**harts |

Example stems: `nd_heatmap.png`, `nd_diffmap_vs_baseline.png`, `net_bars_all.png`, `ad_per_node.png`, `yac_per_node.png`, `yc_tas1.png`, `sb_tas1.png`.

---

## 3. CLI — one command shape for every method

```bash
python -m src.methods.<method> --adaptation <baseline|s1|s2|aggregate> [--profile dflt]
```

`--profile` defaults to `dflt`. `comparison` skips `--profile` — it reads whatever results exist:

```bash
python -m src.methods.comparison --adaptation <baseline|s1|s2|aggregate>
```

Full matrix (20 runs total):

```bash
for method in analytic stochastic dimensional experiment; do
  for adaptation in baseline s1 s2 aggregate; do
    python -m src.methods.$method --adaptation $adaptation
  done
done
for adaptation in baseline s1 s2 aggregate; do
  python -m src.methods.comparison --adaptation $adaptation
done
```

---

## 4. Source tree

```
src/
├── methods/                  # thin orchestrators with run() + CLI (one per method)
│   ├── analytic.py
│   ├── stochastic.py
│   ├── dimensional.py
│   ├── experiment.py
│   └── comparison.py
├── analytic/                 # M/M/c/K, Jackson network solvers
├── stochastic/               # SimPy processes (services, workflow, environment)
├── dimensional/              # PyDASA schema + TAS variables + coefficient builders
├── experiment/               # ReSeP-lite + ActivFORMS-lite + adaptation mechanisms
├── view/                     # plotting helpers (Yoly, heatmaps, histograms, diagrams)
├── io/                       # config loaders (profile ⊕ adaptation overrides) + JSON writers
└── utils/                    # shared helpers
```

Each `src/methods/<method>.py` exposes `run(adaptation, profile='dflt') -> dict` and `main()` for CLI. All business logic lives in the subpackages — method modules are orchestration only. I/O goes through `src.io` so every stage reads and writes the same PyDASA-compatible JSON schema.

---

## 5. Method contracts

Every method declares **Purpose / Inputs / Produces / Acceptance**.

Every method's output lives at `data/results/<method>/<adaptation>/<profile>.json` plus `requirements.json`. The content keys that are present inside `<profile>.json` vary by method.

### analytic

- **Purpose.** Closed-form QA predictions under the current adaptation.
- **Inputs.** `profile/dflt.json` (scenario `baseline`) or `profile/opti.json` (scenario `<a>` ∈ `s1|s2|aggregate`); loader walks `_nodes[<a>]` to collect the 13 active artifacts and reads the 13×13 routing matrix from `_routs[<a>]`.
- **Produces.** `analytic/<a>/<p>.json` with key `variables`; `requirements.json`; `assets/img/analytic/<a>/qn_diagram.png`.
- **Acceptance.** All ρ < 1 for stability; M/M/c/K formulas pass textbook unit tests in `tests/analytic/`.

### stochastic

- **Purpose.** SimPy DES ground truth with 95 % CIs per metric.
- **Inputs.** Same as analytic plus `method/stochastic.json` (seed, horizon, replications, warmup).
- **Produces.** `stochastic/<a>/<p>.json` with key `variables` (CIs embedded per `_data` point); `requirements.json`; `assets/img/stochastic/<a>/qn_diagram.png`.
- **Acceptance.** Replication count sufficient for tight CIs; seed echoed in variables metadata; warmup cut applied.

### dimensional

- **Purpose.** DASA evaluation via PyDASA: SAFDU schema, variables, π-groups, derived coefficients, Monte Carlo, sensitivity.
- **Inputs.** Same as analytic plus S1/S2 experimental data feeding variable `_data` arrays.
- **Produces.** `dimensional/<a>/<p>.json` with keys `variables`, `coefficients`, `pi_groups`; `requirements.json`; figures `perf_chart.png`, `perf_histogram.png`, `exp_chart.png`, `yoly.png`.
- **Acceptance.** π-groups pass dimensional-consistency and linear-independence checks; Monte Carlo samples span declared ranges.

### experiment

- **Purpose.** Small-scale ReSeP + ActivFORMS-lite implementation — ground-truths the other three methods against a real (if simplified) architecture.
- **Inputs.** Same as analytic plus `method/experiment.json`.
- **Produces.** `experiment/<deployment>/<a>/<p>.json` with key `variables`; `requirements.json`; event-trace figures. `<deployment>` = `local` (single laptop) or `remote` (3-machine LAN); `calibration/` sits alongside and holds per-host noise-floor JSONs (no adaptation axis).
- **Pre-run gate.** Every experiment run MUST be preceded by a calibration against the target host; the run envelope records `baseline_ref` pointing at the JSON under `data/results/experiment/calibration/`. Plan, recipes, and phase checkpoints live in `notes/calibration.md`.
- **Reference ground truth.** The authors' own TAS 1.6 replication dump lives under `data/reference/` — 3 QoS objectives × 2 adaptation states (`no-adapt`, `simple-adapt`), each with `invocations.csv`, `log.csv`, `results.csv`, and 8 plots. Schema documented in `data/reference/profile.md`. Treat these as the authoritative replication target.
- **Acceptance.** Reproduces Table IV of [1] within published tolerance: `baseline` failure rate ≈ 0.18, S1/retry-style ≈ 0.11, S2/select-reliable-style ≈ 0.00; experiment variable means fall inside stochastic 95 % CIs for the same adaptation; per-service cost distribution matches `data/reference/<QoS>/<adapt>/results.csv` within replication noise.

### comparison

- **Purpose.** Reconcile the four methods, quantify divergences, **verify R1 / R2 / R3** per adaptation.
- **Inputs.** All `<profile>.json` files under `analytic/<a>/`, `stochastic/<a>/`, `dimensional/<a>/`, `experiment/<a>/`.
- **Produces.** `comparison/<a>/<p>.json` with key `deltas`; `requirements.json` (R1/R2/R3 pass/fail per method); comparison and diff-map figures under `assets/img/comparison/<a>/`.
- **Acceptance.** Every figure and JSON cited by downstream reports for CS-1 is regenerable in one command.

---

## 6. R1 / R2 / R3 validation

Each run's `requirements.json` records pass/fail against Cámara 2023 targets:

| Requirement | Metric | Threshold | Lens |
|---|---|---|---|
| **R1** | average failure rate | ≤ 0.03 % | Availability |
| **R2** | average response time | ≤ 26 ms | Performance |
| **R3** | average cost | minimise subject to R1 ∧ R2 | Cost |

Schema:

```json
{
  "R1": { "metric": "fail_rate", "value": 0.00018, "threshold": 0.0003, "pass": true, "notes": "" },
  "R2": { "metric": "resp_time", "value": 21.4,    "threshold": 26,     "pass": true, "notes": "" },
  "R3": { "metric": "cost",      "value": 9.72,    "threshold": null,   "pass": true, "notes": "R1∧R2 hold" }
}
```

The `comparison` method's `requirements.json` rolls this up across all four evaluation methods so the reader sees at a glance which adaptation satisfies all three.

---

## 7. Notebooks — thin orchestrators at repo root

One per method, no prefix:

```
01-analytic.ipynb
02-stochastic.ipynb
03-dimensional.ipynb
04-yoly.ipynb
05-experimental.ipynb
06-yoly-experimental.ipynb
07-comparison.ipynb
```

The dimensional and experiment methods are each delivered as two notebooks: a focused per-adaptation execution (`03-dimensional.ipynb`, `05-experimental.ipynb`) and a configuration-sweep yoly view (`04-yoly.ipynb`, `06-yoly-experimental.ipynb`). The yoly notebooks share the `src/view/dc_charts.py` plot vocabulary regardless of whether the data came from a closed-form M/M/c/K solve or a prototype measurement.

Each notebook runs the full adaptation axis for its method, displays the resulting variable tables and figures inline, and closes with R1/R2/R3 verdict tables. Zero logic — only imports, `run()` calls, and narrative markdown.

Typical `experiment.ipynb` structure:

```python
# cell 1 — imports
from src.methods import experiment
from src.view import tables, diagrams

# cell 2 — run full axis for this method
results = {
    ad: experiment.run(adaptation=ad)
    for ad in ("baseline", "s1", "s2", "aggregate")
}

# cell 3 — show variables (filtered by scope)
tables.show(results, level="net")

# cell 4 — show R1/R2/R3 verdicts
tables.requirements(results)

# cells 5+ — figures, narrative, caveats
```

---

## 8. Execution order (auditor path)

```bash
python -m venv venv && source venv/Scripts/activate
pip install -r requirements.txt

# CLI (20 runs)
for method in analytic stochastic dimensional experiment; do
  for adaptation in baseline s1 s2 aggregate; do
    python -m src.methods.$method --adaptation $adaptation
  done
done
for adaptation in baseline s1 s2 aggregate; do
  python -m src.methods.comparison --adaptation $adaptation
done

# Or notebooks (5 notebooks)
jupyter lab    # open each in method order and Run All
```

Both paths produce byte-identical artifacts.

---

## 9. Directory layout (complete)

```
PyDASA-CS1-TAS/
├── 01-analytic.ipynb
├── 02-stochastic.ipynb
├── 03-dimensional.ipynb
├── 04-yoly.ipynb
├── 05-experimental.ipynb
├── 06-yoly-experimental.ipynb
├── 07-comparison.ipynb
├── src/
│   ├── methods/              # orchestrators (one per method)
│   ├── analytic/  stochastic/  dimensional/  experiment/
│   └── view/  io/  utils/
├── data/
│   ├── config/
│   │   ├── profile/          # dflt.json (baseline) + opti.json (s1/s2/aggregate)
│   │   └── method/           # stochastic and experiment tunables
│   ├── reference/            # authors' TAS 1.6 replication dump (ground truth)
│   └── results/
│       └── <method>/<adaptation>/
│           ├── <profile>.json        # PACS-style: variables + (coefficients + pi_groups
│           │                         # for dimensional) + (deltas for comparison)
│           └── requirements.json     # R1/R2/R3 verdicts (every method)
├── assets/
│   └── img/<method>/<adaptation>/<figure>.{png,svg}
├── tests/                    # mirrors src/ subpackages
├── notes/
│   ├── quickstart.md
│   ├── commands.md
│   ├── workflow.md           # this file
│   ├── cs_context.md         # full case-study record
│   ├── cs_objective.md       # case-study narrative
│   └── devlog.md
├── __OLD__/                  # frozen prior implementation (reference only)
├── .claude/
├── CLAUDE.md
├── README.md
├── SUMMARY.md
├── LICENSE
└── requirements.txt
```

---

## 10. Reproducibility checklist

- [ ] `requirements.txt` frozen with pinned versions (PyDASA wheel included)
- [ ] `data/config/` committed before the run
- [ ] `Run All` (notebook) and full CLI loop (§8) both succeed with identical artifacts
- [ ] Random seeds declared in `config/method/stochastic.json` and echoed in `variables.json` metadata
- [ ] Notebook outputs cleared before commit unless marked as publication artifacts
- [ ] `pytest -q` passes
- [ ] `notes/devlog.md` dated entry for the run
- [ ] Divergences from `__OLD__/data/results/cs1/` logged with reason

---

## 11. Handoff to downstream reports

- **Inbound.** `cs_objective.md` owns the case-study narrative. This repo reads the service catalogue from `notes/cs_context.md`.
- **Outbound.** Downstream reports reference by stable path:
  - `data/results/comparison/<adaptation>/requirements.json` — headline R1/R2/R3 verdict
  - `data/results/<method>/<adaptation>/<profile>.json` — raw numbers (PACS-style)
  - `assets/img/<method>/<adaptation>/*.png`
- **Change control.** Every cited artifact is regenerated from a clean git state; no hand-edited numbers.

---

## 12. Status

Shape locked 2026-04-18. Naming convention, directory layout, axes, file formats, and 20-run matrix are stable. Scaffolding pending — see `notes/devlog.md`.

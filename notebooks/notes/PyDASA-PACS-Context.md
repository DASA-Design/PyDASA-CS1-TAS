# PACS Case Study Context

## 1. DASA Methodology

DASA (Dimensional Analysis for Software Architecture) integrates traditional Dimensional Analysis (DA) with ADD 3.0 into a single iterative design methodology. The core idea: treat Quality Attributes as **emergent, measurable properties** expressed in custom fundamental dimensions — **SAFDUs**: Structure [S], Data [D], Time [T], Entropy [E], Connectivity [N]. Using these, the architect builds a Relevance List, constructs a Dimensional Matrix, and applies the Pi-Theorem to derive **Dimensionless Coefficients (DCs)** that characterize system behaviour quantitatively. The methodology follows four stages — **Prepare, Design, Evaluate, Record** — iterated until DCs are dimensionally correct, linearly independent, and measurably valid.

## 2. PyDASA Toolkit

PyDASA is the Python library that operationalizes DASA:

| Class | Purpose |
|---|---|
| **Schema** | Defines the custom SAFDU framework (T, S, D with units s, req, bit) |
| **Variable** | Wraps each metric with symbol, dimensions, units, ranges, and experimental data |
| **AnalysisEngine** | Takes variables + schema, `run_analysis()` produces Pi-groups via Buckingham's theorem, `derive_coefficient()` composes Pi-groups into named operational coefficients |
| **MonteCarloSimulation** | Grid-based simulation over coefficient space for validation |
| **SensitivityAnalysis** | Symbolic sensitivity of coefficients to variable changes |

**Not part of PyDASA:** `simulate_architecture()`, `simulate_artifact()`, `setup_artifact_specs()`, `setup_environmental_conds()` — these are case-study-specific functions in `src/notebooks/src/networks.py`.

## 3. PACS Example

### Iteration 1 — Single-Node Baseline

Single M/M/c/K queue for one Archival Service (AS).

**Variables (13):** lambda, mu, epsilon, chi, c, K, rho_req, L, Lq, W, Wq, M_act, M_buf — in [S], [D], [T].

**Coefficients (4):**

| Coefficient | Formula | Meaning |
|---|---|---|
| theta | L / K | Queue occupancy ratio |
| sigma | W * lambda / K | Service stall / blocking indicator |
| eta | chi * K / (mu * c) | Resource utilisation effectiveness |
| phi | M_act / M_buf | Memory usage ratio |

**Notebook workflow:** Schema -> Variables -> AnalysisEngine -> Pi-groups -> Derived Coefficients -> Simulation data (M/M/c/K grid) -> Monte Carlo -> Yoly plots.

### Iteration 2 — 7-Node Jackson Network

Architecture: **IB -> {IW, IR} -> DB -> {WN, RN} -> OB**

- IB (Inbound Broker) splits traffic: write path (IW -> DB -> WN) vs read path (IR -> DB -> RN), recombined at OB
- 5 routing environments: 100R, 80R20W, 50R50W, 20R80W, 100W
- Same 4 coefficients derived **per node** via PyDASA engines

**Notebook workflow (3 phases):**

#### Phase 1: Per-Node DA (cells 0-45)
Mirrors Iteration 1 but x7 nodes: Schema, Variables from JSON, AnalysisEngine per node, Pi-groups, 4 coefficients per node, sensitivity, `simulate_artifact()` grid data, Monte Carlo, per-node Yoly diagrams.

#### Phase 2: Architecture-Level (cells 46-67)
1. Define optimal baseline configs per node (mu, c, K, rho_req)
2. Setup 5 routing scenarios with 7x7 routing matrices
3. `simulate_architecture()` populates `architecture_exp[env]` (Jackson network)
4. Per-env x artifact: create Variables, AnalysisEngine, derive 4 coefficients
5. Per-env Monte Carlo, extract results into `dasa_results`
6. Merge per-node coefficients back into `architecture_exp[env]`

#### Phase 3: E2E Aggregation (cells 69-89) — BROKEN
Two parallel incomplete flows for computing PACS-level e2e metrics:

- **Flow A (cell 69):** Computes e2e variables -> `pacs_data` dict. Issues: capacity vars missing, wrong aggregation (blind sum), broken R/W split.
- **Flow B (cells 83-84):** Adds e2e variables + coefficients to `architecture_exp`. Cell 85 filters PACS columns into `pacs_summary`. Cell 86 overwrites `pacs_data` from `pacs_summary`. Cells 87-89 produce Yoly plots.

**Key problems:**
1. Wrong aggregation semantics: lambda/chi/mu/rho should not be summed across nodes
2. Two incomplete flows with inconsistent data, neither fully working
3. R/W split doesn't handle zero-traffic scenarios (NaN/Inf from divide-by-zero)

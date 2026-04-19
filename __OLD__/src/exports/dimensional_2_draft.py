# %% [markdown]
# # PACS Example: Iteration 2 - Queue Network Analysis with PyDASA
# 
# This notebook extends the single-node M/M/c/K analysis to a **7-node open queueing network** modelling a PACS (Picture Archiving and Communication System). We'll explore how to:
# 
# 1. Define a custom dimensional framework (Time, Structure, Data).
# 2. Model software service variables with custom dimensions.
# 3. Use PyDASA's `AnalysisEngine` to derive dimensionless groups.
# 4. Understand the M/M/c/K queue model and operational metrics.
# 5. Perform sensitivity analysis and Monte Carlo simulation.
# 6. Visualize the "Yoly" trade-off chart for system design.
# 7. **Connect nodes via a routing matrix P and sweep 5 workload scenarios.**
# 
# *(Sections 1 to 4 from Iteration 1 are reused; new content starts at §5.)*
# 
# ## What is the M/M/c/K Queue Model?
# 
# The **M/M/c/K** queue model is a fundamental queueing system in performance analysis:
# 
# - **M:** (Markovian arrivals): Request arrivals follow a Poisson process with rate $\lambda$.
# - **M:** (Markovian service): Service times follow exponential distribution with rate $\mu$.
# - **c:** Number of parallel servers (resources) available.
# - **K:** Maximum system capacity (queue + servers).
# 
# ### Key Performance Metrics:
# 
# **Average Waiting Time** ($W$):
# $$
# W = f(\lambda, \mu, c, K, L, \ldots)
# $$
# 
# **Traffic Intensity** ($\tau$):
# $$
# \tau = \frac{\lambda}{\mu}
# $$
# 
# **System Utilization** ($\rho$):
# $$
# \rho = \frac{\lambda}{c \cdot \mu}
# $$
# 
# ### Error Rate and Effective Response
# 
# The system has an error rate ($\text{err}$) that affects the effective response rate:
# $$
# \chi = (1 - \text{err}) \cdot \lambda
# $$
# 
# Traditional queueing models often ignore error rates, but in real systems, they can significantly impact performance and user satisfaction. Incorporating $\text{err}$ allows us to model reliability and its effect on effective throughput.
# 
# Where:
# - $\chi$ (chi): Effective response rate accounting for errors $[T^{-1}]$.
# - $\text{err}$: Error/failure rate [dimensionless, 0 to 1].
# - $\lambda$: Arrival rate $[T^{-1}]$.
# 
# **Example:** If $\lambda = 100$ req/s and $\text{err} = 0.02$ (2% error rate), then $\chi = 0.98 \times 100 = 98$ req/s successfully served.
# 
# ### Custom Dimensional Framework (T, S, D)
# 
# Traditional dimensional analysis focuses on physical dimensions (M, L, T), but software systems require a different approach. By defining custom dimensions (T, S, D), we can capture the unique characteristics of software services and derive meaningful insights for design and optimization.
# 
# For software service analysis, we introduce three fundamental dimensions:
# - **T** (Time): Temporal measurements [sec].
# - **S** (Structure): Capacity, servers, queue slots [req].
# - **D** (Data): Information content, memory [bit].
# 
# ### The "Yoly" Concept
# 
# **Yoly** is a composite happiness metric that captures the trade-off between:
# - **Performance:** Fast response times (low $W$).
# - **Availability:** Low utilization (prevents saturation).
# - **Memory Efficiency:** Optimal memory allocation.
# - **Reliability:** Low error rates ($\chi/\lambda \leq 1$).
# 
# A optimal Yoly score indicates a well-balanced system configuration that keeps users happy!
# 
# ## Queue Network Model
# 
# The PACS pipeline is modelled as an **open queueing network** of seven M/M/c/K nodes connected by a stochastic routing matrix $\mathbf{P} \in \mathbb{R}^{7 \times 7}$. Queueing Network (QN) theory, grounded in Denning and Buzen's Operational Analysis (1978), derives all performance quantities from four measurable laws: the Utilisation Law ($U_i = X \cdot S_i$), the Forced Flow Law ($X_i = V_i \cdot X$), Little's Law ($N_i = X_i \cdot R_i$), and the Interactive Response Time Law ($R = N/X - Z$).
# 
# Each node $i$ is an M/M/c/K queue parameterised by arrival rate $\lambda_i$, service rate $\mu_i$, $c_i$ parallel servers, and capacity $K_i$. The routing matrix entry $P_{ij}$ gives the probability that a departure from node $i$ is routed to node $j$; the diagonal $P_{ii} = \varepsilon = 0.01$ captures the per-node error/retry rate. Node arrival rates satisfy the **traffic balance equations**:
# $$\lambda_j = \lambda_j^{(0)} + \sum_{i=1}^{7} \lambda_i \cdot P_{ij}$$
# 
# Under FIFO or PS scheduling, with no simultaneous resource possession or fork/join synchronisation, the network satisfies product-form (BCMP) conditions, making the joint steady-state distribution analytically tractable (Balsamo et al., 2003). The PACS node flow is: **IB, {IWS, IRS}, DB, {WAS, RAS}, OB**, where only the IB and DB rows of $\mathbf{P}$ vary across the five workload scenarios (100% read to 100% write).
# 

# %% [markdown]
# ## 1. Import Required Libraries
# 
# First, let's import PyDASA's core modules for dimensional analysis with custom frameworks.

# %%
# python imports
import os
import random
import copy
import json5

# PyDASA imports
import pydasa
from pydasa.workflows.phenomena import AnalysisEngine
from pydasa.elements.parameter import Variable
from pydasa.dimensional.vaschy import Schema
from pydasa.workflows.influence import SensitivityAnalysis
from pydasa.workflows.practical import MonteCarloSimulation

# For data visualization and analysis
import numpy as np
import pandas as pd
from tabulate import tabulate

# from src.queueing import Queue
# for Queue simulation and modeling
from src.networks import find_key
from src.networks import find_key_idx
from src.networks import setup_artifact_specs
from src.networks import setup_environmental_conds
from src.networks import simulate_artifact
from src.networks import simulate_architecture
from src.networks import find_key

# For plotting
from src.display import plot_arts_distributions
from src.display import plot_yoly_arts_behaviour
from src.display import plot_yoly_arts_charts
from src.display import plot_system_behaviour
from src.display import plot_yoly_chart

# %%
# ANSI color codes for terminal output
BLUE = "\033[94m"
BOLD = "\033[1m"
RESET = "\033[0m"
RED = "\033[91m"
YELLOW = "\033[93m"
CYAN = "\033[96m"
GREEN = "\033[92m"

print(f"VERSION: {pydasa.__version__}")
print("PyDASA imported successfully!")

# %% [markdown]
# ## 2. Define Custom Dimensional Framework
# 
# For software service analysis, we need a custom dimensional framework that captures the unique characteristics of queueing systems. Unlike physical systems (Length, Mass, Time), we define the following fundamental dimensional units:
# 
# **Custom Framework Definition:**
# 
# 1. **T (Time):** Temporal measurements.
#    - Unit: seconds $[s]$
#    - Examples: waiting time, service time, inter-arrival time
#    - Physical analogy: Similar to Time $[T]$ in physical systems.
# 
# 2. **S (Structure):** System capacity and architectural elements.
#    - Unit: requests $[req]$
#    - Examples: number of requests/reply a server can handle, queue positions, concurrent requests
#    - Software-specific: Represents discrete structural resources, proxy for the effort to complete operations, related to Mass $[M]$ and Length $[L]$ in physical systems.
# 
# 3. **D (Data):** Information content and memory
#    - Unit: bits $[bit]$.
#    - Examples: request payload size, buffer memory, data throughput.
#    - Software-specific: Quantifies information processing.
# 
# This framework allows us to perform dimensional analysis on software services, deriving dimensionless numbers that characterize system behavior independent of scale.

# %%
fdu_list = [
    {
        "_idx": 0,
        "_sym": "T",
        "_fwk": "CUSTOM",
        "description": "Temporal measurements",
        "_unit": "s",
        "_name": "Time"
    },
    {
        "_idx": 1,
        "_sym": "S",
        "_fwk": "CUSTOM",
        "description": "Structural complexity of the operations",
        "_unit": "req",
        "_name": "Structure"
    },
    {
        "_idx": 2,
        "_sym": "D",
        "_fwk": "CUSTOM",
        "description": "Information content and memory",
        "_unit": "bit",
        "_name": "Data"
    }
]

# Create custom schema with T, S, D framework
schema = Schema(_fwk="CUSTOM",
                _fdu_lt=fdu_list, _idx=0)   # type: ignore
schema._setup_fdus()

print("=== Custom Framework Created Successfully! ===")
print(f"\tFramework: {schema.fwk}")
print(f"\tNumber of FDUs: {len(schema._fdu_lt)}")
print("\nFundamental Dimensional Units:")

# Prepare data for tabulate
fdu_data = []
for fdu in schema._fdu_lt:
    # Blue color for Symbol column (first column)
    symbol_colored = f"{BLUE}{fdu._sym}{RESET}"
    fdu_data.append([symbol_colored, fdu._name, fdu._unit, fdu.description[:60]])

# Extract headers from FDU attribute names
header_map = {"_sym": "Symbol", "_name": "Name", "_unit": "Unit", "description": "Description"}
headers = [f"{BOLD}{header_map[attr]}{RESET}" for attr in ["_sym", "_name", "_unit", "description"]]

print(tabulate(fdu_data, headers=headers, tablefmt="grid"))

# %% [markdown]
# ## 3. Define Queue Model Variables
# 
# *Variables are defined per node in the 7-node PACS network (IB, IWS, IRS, DB, WAS, RAS, OB) and loaded from `PACS-vars-iter2.json`. Each node shares the same 11-variable schema; arrival rates are derived from the routing matrix $\mathbf{P}$ and the traffic balance equations.*
# 
# **Node Acronyms:**
# 
# | Acronym | Full Name | Role |
# |:-------:|-----------|------|
# | **IB** | Inbound Broker | Receives all external requests and routes them to IWS (write) or IRS (read) |
# | **IWS** | Image Write Service | Processes image archival requests (CT, MRI, X-ray payloads) |
# | **IRS** | Image Read Service | Processes image retrieval requests (lightweight image references) |
# | **DB** | Shared Database | Persistent storage backend; receives combined traffic from IWS and IRS |
# | **WAS** | Write Acknowledgment Service | Handles archival responses returning from DB back toward the client |
# | **RAS** | Read Acknowledgment Service | Handles retrieval responses returning from DB back toward the client |
# | **OB** | Outbound Broker | Aggregates responses from WAS and RAS and delivers them to the client |
# 
# **Routing Scenarios: Arrival Rates $\lambda_i$ (req/s):**
# 
# Only IB and DB rows of $\mathbf{P}$ vary across scenarios; all other nodes are fixed. IB ($\lambda = 100$) and DB ($\lambda \approx 99$) are stable across all scenarios. $\varepsilon = 0.01$ on every diagonal.
# 
# | Scenario | Write% | Read% | $\lambda_\text{IWS}$ | $\lambda_\text{IRS}$ | $\lambda_\text{DB}$ | $\lambda_\text{WAS}$ | $\lambda_\text{RAS}$ |
# |:--------:|:------:|:-----:|:--------------------:|:--------------------:|:--------------------:|:--------------------:|:--------------------:|
# | **100R**   |  0%  | 100% |  0.0 | 99.0 | 99.0 |  0.0 | 98.0 |
# | **80R20W** | 20%  |  80% | 19.8 | 79.2 | 99.0 | 19.6 | 78.4 |
# | **50R50W** | 50%  |  50% | 49.5 | 49.5 | 99.0 | 49.0 | 49.0 |
# | **20R80W** | 80%  |  20% | 79.2 | 19.8 | 99.0 | 78.4 | 19.6 |
# | **100W**   | 100% |   0% | 99.0 |  0.0 | 99.0 | 98.0 |  0.0 |
# 
# *Derived from: $\lambda_\text{IWS} = \lambda_\text{IB} \cdot P[\text{IB,IWS}]$, $\lambda_\text{IRS} = \lambda_\text{IB} \cdot P[\text{IB,IRS}]$, $\lambda_\text{DB} \approx \lambda_\text{IB} \cdot 0.99$, $\lambda_\text{WAS} = \lambda_\text{DB} \cdot P[\text{DB,WAS}]$, $\lambda_\text{RAS} = \lambda_\text{DB} \cdot P[\text{DB,RAS}]$.*
# 
# We'll define 11 variables for each M/M/c/K node with proper dimensions using the custom T, S, D framework.
# 
# **Variable Categories:**
# 
# **INPUT Variables (3)** - Primary system parameters:
# 1. $\lambda_i$: Arrival rate at node $i$, derived from traffic balance $[S \cdot T^{-1}]$
# 2. $K_i$: Maximum queue capacity at node $i$ $[S]$
# 3. $\rho_{\text{req}_i}$: Data density per request at node $i$ $[D \cdot S^{-1}]$
# 
# **OUTPUT Variable (1)** - Performance metric:
# 1. $W_i$: Average sojourn time at node $i$ $[T]$
# 
# **CONTROL Variables (7)** - Node configuration and secondary parameters:
# 1. $L_i$: Average queue length at node $i$ $[S]$
# 2. $\mu_i$: Service rate at node $i$ $[S \cdot T^{-1}]$
# 3. $c_i$: Number of parallel servers at node $i$ $[S]$
# 4. $M_{\text{buf}_i}$: Allocated buffer memory $[D]$, where $M_{\text{buf}_i} = \rho_{\text{req}_i} \cdot K_i$
# 5. $M_{\text{act}_i}$: Active memory in processing $[D]$, where $M_{\text{act}_i} = \rho_{\text{req}_i} \cdot L_i$
# 6. $\varepsilon_i$: Per-node error/retry rate [n.a.], $\varepsilon = 0.01$ (diagonal of $\mathbf{P}$)
# 7. $\chi_i$: Effective departure rate $[S \cdot T^{-1}]$, where $\chi_i = (1 - \varepsilon_i) \cdot \lambda_i$
# 
# **Per-Node Setpoints (from `PACS-vars-iter2.json`, 80R20W baseline scenario):**
# 
# | Node | $\lambda$ (req/s) | $\mu$ (req/s) | $c$ | $K$ | $\rho_{\text{req}}$ (MB/req) |
# |:----:|:-----------------:|:-------------:|:---:|:---:|:----------------------------:|
# | IB   | 100.0 | 1000 | 1 | 16 | 0.408 (20% write + 80% read) |
# | IWS  |  20.0 |  500 | 2 | 16 | 2.0 (archival write payload) |
# | IRS  |  80.0 |  500 | 2 | 16 | 0.01 (image reference) |
# | DB   | 100.0 |  500 | 1 | 16 | 0.408 |
# | WAS  |  19.8 |  500 | 1 | 16 | 2.0 |
# | RAS  |  79.2 |  500 | 1 | 16 | 0.01 |
# | OB   | 100.0 | 1000 | 1 | 16 | 0.408 |
# 
# *Service rates are swept over [200, 500, 1000] req/s; servers over [1, 2, 4]; queue capacity over [4/8/16/32] depending on node, see `_data` arrays in the JSON. Error rate $\varepsilon = 0.01$ is fixed across all nodes.*
# 

# %%

# Load PACS iteration 2 variables from JSON
# Top-level keys are node acronyms (IB, IW, IR, DB, WN, RN, OB) plus "routing"
# Each node value is a dict of variable dicts keyed by LaTeX symbol

fn = "data/PACS-vars-iter2.json"
with open(fn, mode="r", encoding="utf-8") as f:
    pacs_blueprint = json5.load(f)

# Separate the enviromental conditions from the artifact specs
env_conds = pacs_blueprint.get("enviroments", {})

# should print ["IB", "IW", "IR", "DB", "WN", "RN", "OB"]
art_specs = pacs_blueprint.get("artifacts", {})
node_keys = list(art_specs.keys())

# Prepare data for tabulate
routing_shape = f"{len(env_conds.get('_routs', []))}x{len(env_conds.get('_routs', [[]])[0])}x{len(env_conds.get('_routs', [[[]]])[0][0])}"
scenarios = env_conds.get('_scenarios', [])

data = [
    [f"{BLUE}File{RESET}", fn],
    [f"{BLUE}Nodes{RESET}", ", ".join(node_keys)],
    [f"{BLUE}Routing{RESET}", f"{scenarios} scenarios, P shape {routing_shape}"]
]

# Bold headers
headers = [f"{BOLD}Property{RESET}", f"{BOLD}Value{RESET}"]

print(f"Loaded '{fn}'")
print(tabulate(data, headers=headers, tablefmt="grid"))

# %%
# Build node_vars: { node_acronym -> { sym -> Variable(...) } }
# Skips non-variable metadata keys ("name", "idx") present at the node level

node_vars = {}
for node, specs in art_specs.items():
    specs = specs.get("vars", {})
    _vars = {
        sym: Variable(**params) for sym, params in specs.items() if isinstance(params, dict) and "_sym" in params
    }
    node_vars[node] = _vars

# %%
SEP = "=" * 60
print(SEP)
print(f"  node_vars created: {len(node_vars)} nodes")
print(SEP)

title = f"{'Node':<6} {'#Vars':<7} {'#Relevant':<11}"
sep = "-" * 60
print(title)
print(sep)
for node, _vars in node_vars.items():
    n_total    = len(_vars)
    n_relevant = sum(1 for v in _vars.values() if v.relevant)
    print(f"{node:<6} {n_total:<7} {n_relevant:<11}")

print(sep)
print(f"\nPer-variable detail (symbol | setpoint | units | dims | cat | relevant):")

for node, _vars in node_vars.items():
    print(f"\n* [{node}] {art_specs[node].get('name', '')} ({len(_vars)} vars)")

    # Prepare data for tabulate
    var_data = []
    for sym, var in _vars.items():
        dims_str = var.dims if var.dims else "n.a."
        setpoint_str = f"{var.setpoint:.4g}" if var.setpoint is not None else "N.A."

        # Blue color for Symbol column
        sym_colored = f"{BLUE}{sym}{RESET}"
        var_data.append([sym_colored, setpoint_str, var.units, dims_str, var.cat, var.relevant])

    # Bold headers derived from variable attributes
    header_names = ["Symbol", "Setpoint", "Units", "Dims", "Cat", "Relevant"]
    headers = [f"{BOLD}{h}{RESET}" for h in header_names]

    print(tabulate(var_data, headers=headers, tablefmt="grid"))

# %% [markdown]
# ## 3. Create Dimensional Analysis Engine
# 
# Now we'll use PyDASA's **AnalysisEngine** (main workflow) to automatically derive dimensionless groups using the Buckingham Pi theorem.

# %%
# --- Create AnalysisEngines for each node ---
node_engines = {}
for idx, (node, _vars) in enumerate(node_vars.items()):
    eng = AnalysisEngine(
        _idx=idx,
        _fwk="CUSTOM",
        _schema=schema,
        _name=f"{node} Analysis Engine",
        description=f"Dimensional analysis for PACS node {node}: M/M/c/K queue model."
    )
    eng.variables = _vars
    node_engines[node] = eng

# %%
# --- Verification printout ---
SEP = "=" * 70
print(SEP)
print(f"node_engines created: {len(node_engines)} engines")
print(SEP)

# Prepare data for tabulate
engine_data = []
for node, eng in node_engines.items():
    _vars = eng.variables
    n_in   = sum(1 for v in _vars.values() if v.cat == "IN")
    n_out  = sum(1 for v in _vars.values() if v.cat == "OUT")
    n_ctrl = sum(1 for v in _vars.values() if v.cat == "CTRL")
    
    # Blue color for Node column (first column)
    node_colored = f"{BLUE}{node}{RESET}"
    engine_data.append([node_colored, eng.name, n_in, n_out, n_ctrl, len(_vars)])

# Bold headers
header_names = ["Node", "Engine Name", "IN", "OUT", "CTRL", "Total"]
headers = [f"{BOLD}{h}{RESET}" for h in header_names]

print(tabulate(engine_data, headers=headers, tablefmt="grid"))

# %% [markdown]
# ## 4. Run Dimensional Analysis
# 
# Execute the complete workflow to generate dimensionless coefficients (Pi groups).

# %%
# running dimensional analysis
# Run the complete dimensional analysis workflow for each node
node_results = {}
for node, eng in node_engines.items():
    node_results[node] = eng.run_analysis()

# %%
print("=" * 60)
print("============== Analysis complete! (all nodes) ==============")
print("=" * 60)

# Summary table
summary_data = []
for node, eng in node_engines.items():
    n_coeff = len(eng.coefficients)
    coeff_keys = list(eng.coefficients.keys())
    keys_str = ", ".join(coeff_keys) if coeff_keys else "—"
    
    # Blue color for Node column (first column)
    node_colored = f"{BLUE}{node}{RESET}"
    summary_data.append([node_colored, n_coeff, keys_str])

# Bold headers
header_names = ["Node", "Pi Groups", "Coefficients"]
headers = [f"{BOLD}{h}{RESET}" for h in header_names]

print(tabulate(summary_data, headers=headers, tablefmt="grid"))

# Detailed coefficients table for each node
for node, eng in node_engines.items():
    if not eng.coefficients:
        continue
    print(f"\nDimensionless Coefficients — Node: {node}")
    print("=" * 100)
    
    # Prepare detailed coefficient data
    coeff_data = []
    for name, coeff in eng.coefficients.items():
        expression = str(coeff.pi_expr)
        if len(expression) > 35:
            expression = expression[:32] + "..."
        exponents_str = ", ".join([
            f"{var}^{exp}" if exp != 1 else var
            for var, exp in coeff.var_dims.items()
        ])
        if len(exponents_str) > 58:
            exponents_str = exponents_str[:55] + "..."
        
        # Blue color for Coefficient column (first column)
        name_colored = f"{BLUE}{name}{RESET}"
        coeff_data.append([name_colored, expression, exponents_str])
    
    # Bold headers
    detail_headers = [f"{BOLD}{h}{RESET}" for h in ["Coefficient", "Expression", "Variable Exponents"]]
    
    print(tabulate(coeff_data, headers=detail_headers, tablefmt="grid"))
    print("=" * 100)

# %% [markdown]
# ## 5. Derive Key Dimensionless Coefficients
# 
# Now let's use PyDASA's `derive_coefficient()` method to create operationally meaningful coefficients from the Pi groups. For each node $j \in \{\text{IB, IWS, IRS, DB, WAS, RAS, OB}\}$, we expect to see:
# 
# 1. **Occupancy Coefficient** ($\theta_j$): Queue capacity utilization at node $j$.
#    - $\theta_j = \Pi_{0,j} = L_j / K_j$
# 2. **Stall Coefficient** ($\sigma_j$): Service blocking indicator at node $j$.
#    - $\sigma_j = \Pi_{1,j} = W_j \cdot \lambda_j / L_j$
# 3. **Effective-Yield Coefficient** ($\eta_j$): Resource utilization effectiveness at node $j$.
#    - $\eta_j = \Pi_{2,j}^{-1} \cdot \Pi_{3,j} \cdot \Pi_{4,j}^{-1} = \chi_j \cdot K_j / (\mu_j \cdot c_j)$
# 4. **Memory Coefficient** ($\phi_j$): Data usage metric at node $j$.
#    - $\phi_j = \Pi_{5,j} \cdot \Pi_{6,j}^{-1} = M_{\text{act},j} / B_{\text{MAX},j}$
# 
# Also remember the complementary functions (per node $j$):
# - **Little's Law:** $L_j = \lambda_j \cdot W_j$
# - **Data Payload:** $B_j = \rho_{\text{req},j} \cdot L_j$
# - **Effective Departure Rate:** $\chi_j = (1 - \text{err}_j) \cdot \lambda_j$
# 
# These derived coefficients connect directly to the Yoly diagram we'll construct for each node $j$.
# 

# %%
# Derive the four operationally meaningful coefficients for each node j
for node, eng in node_engines.items():
    pi_keys = list(eng.coefficients.keys())

    # theta_j = Pi_0 = L_j / K_j  - Queue occupancy ratio
    delta_coeff = eng.derive_coefficient(
        expr=f"{pi_keys[0]}",
        symbol=f"\\theta_{{{node}}}",
        name=f"Occupancy Coefficient ({node})",
        description=f"theta_{node} = L_{node}/K_{node} - Queue occupancy ratio (0=empty, 1=full)",
        idx=-1
    )

    # sigma_j = Pi_4 = W_j * lambda_j / L_j  - Service stall/blocking indicator
    sigma_coeff = eng.derive_coefficient(
        expr=f"{pi_keys[4]}",
        symbol=f"\\sigma_{{{node}}}",
        name=f"Stall Coefficient ({node})",
        description=f"sigma_{node} = W_{node} * lambda_{node}/L_{node} - Service blocking indicator",
        idx=-1
    )

    # eta_j = Pi_1^-1 * Pi_2 * Pi_3^-1 = chi_j * K_j / (mu_j * c_j)  - Resource utilisation effectiveness
    eta_coeff = eng.derive_coefficient(
        expr=f"{pi_keys[1]}**(-1) * {pi_keys[2]} * {pi_keys[3]}**(-1)",
        symbol=f"\\eta_{{{node}}}",
        name=f"Effective-Yield Coefficient ({node})",
        description=f"eta_{node} = chi_{node} * K_{node}/(mu_{node} * c_{node}) - Resource utilisation effectiveness",
        idx=-1
    )

    # phi_j = Pi_5 * Pi_6^-1 = M_act,j / B_MAX,j  - Data usage metric
    phi_coeff = eng.derive_coefficient(
        expr=f"{pi_keys[5]} * {pi_keys[6]}**(-1)",
        symbol=f"\\phi_{{{node}}}",
        name=f"Memory-Usage Coefficient ({node})",
        description=f"phi_{node} = Mact_{node}/Mbuf_{node} - Data density metric",
        idx=-1
    )

    # Store derived coefficients back into node_results under node-specific keys
    node_results[node][f"\\delta_{node}"] = delta_coeff
    node_results[node][f"\\sigma_{node}"] = sigma_coeff
    node_results[node][f"\\eta_{node}"]   = eta_coeff
    node_results[node][f"\\phi_{node}"]   = phi_coeff

# %%
# Summary table of derived coefficients per node
SEP = "=" * 95
print(SEP)
print("DERIVED DIMENSIONLESS COEFFICIENTS - ALL NODES")
print(SEP)

# Prepare data for tabulate
coeff_data = []
coeff_labels = [
    ("\\delta", "Occupancy (theta)"),
    ("\\sigma", "Stall (sigma)"),
    ("\\eta",   "Effective-Yield (eta)"),
    ("\\phi",   "Memory-Usage (phi)"),
]

for node in node_engines:
    for key_prefix, label in coeff_labels:
        key = f"{key_prefix}_{node}"
        c = node_results[node][key]
        val = c.calculate_setpoint()
        val_str = f"{val:.4f}" if val is not None else "N/A"
        
        # Blue color for Node column (first column)
        node_colored = f"{BLUE}{node}{RESET}"
        coeff_data.append([node_colored, label, str(c.sym), c.pi_expr])

# Bold headers
header_names = ["Node", "Coefficient", "Symbol", "Expression"]
headers = [f"{BOLD}{h}{RESET}" for h in header_names]

print(tabulate(coeff_data, headers=headers, tablefmt="grid"))

# %%
data = [
    {
        "Variable": "theta_j",
        "Name": "Occupancy",
        "Formula": "L_j / K_j",
        "Description": "Queue capacity utilization (0=empty, 1=full)"
    },
    {
        "Variable": "sigma_j",
        "Name": "Stall",
        "Formula": "W_j * lambda_j / L_j",
        "Description": "Service blocking indicator"
    },
    {
        "Variable": "eta_j",
        "Name": "Effective-Yield",
        "Formula": "chi_j * K_j / (mu_j * c_j)",
        "Description": "Resource utilization effectiveness"
    },
    {
        "Variable": "phi_j",
        "Name": "Memory-Usage",
        "Formula": "M_act,j / B_MAX,j",
        "Description": "Data density metric"
    }
]

print("\nCoefficient definitions:")
print(tabulate(data, headers="keys", tablefmt="grid"))

# %% [markdown]
# ## 7. Run Sensitivity Analysis
# 
# Let's use PyDASA's **SensitivityAnalysis** workflow to understand which variables have the most influence on our dimensionless coefficients.

# %%
# Create one sensitivity-analysis workflow per PACS node
node_sensitivities = {}
sensitivity_results = {}

for idx, (node, eng) in enumerate(node_engines.items()):
    sens = SensitivityAnalysis(
        _idx=idx,
        _fwk="CUSTOM",
        _schema=schema,
        _name=f"{node} Sensitivity Analysis",
        _cat="SYM"  # Symbolic sensitivity analysis
    )

    # Configure with variables and coefficients from the node engine
    sens.variables = eng.variables
    sens.coefficients = eng.coefficients
    node_sensitivities[node] = sens

# %%
print("=" * 70)
print(f"node_sensitivities created: {len(node_sensitivities)} workflows")
print("=" * 70)

# Collect data for tabulate
sens_data = [
    {
        "Node": node,
        "Analysis Name": sens.name,
        "Variables": len(sens.variables),
        "Coefficients": len(sens.coefficients)
    }
    for node, sens in node_sensitivities.items()
]

# Create bold headers
bold_headers = [f"{BOLD}{header}{RESET}" for header in sens_data[0].keys()]

# Colorize first column (Node) in blue
sens_data_colored = []
for row in sens_data:
    colored_row = {}
    for i, (key, value) in enumerate(row.items()):
        if i == 0:  # First column (Node)
            colored_row[bold_headers[i]] = f"{BLUE}{value}{RESET}"
        else:
            colored_row[bold_headers[i]] = value
    sens_data_colored.append(colored_row)

print(tabulate(sens_data_colored, headers="keys", tablefmt="grid"))

# %%
# Run symbolic sensitivity analysis at mean values for each node
print("\n--- Running Symbolic Sensitivity Analysis (all nodes) ---")
for node, sens in node_sensitivities.items():
    sensitivity_results[node] = sens.analyze_symbolic(val_type="mean")

# %%
print("=" * 70)
print("Symbolic sensitivity analysis complete")
print("=" * 70)

# Collect data for tabulate
results_data = [
    {
        "Node": node,
        "Derived Results": len(results),
        "Available Keys Size": len(list(results.keys()))
    }
    for node, results in sensitivity_results.items()
]

# Create bold headers
bold_headers = [f"{BOLD}{header}{RESET}" for header in results_data[0].keys()]

# Colorize first column (Node) in blue
results_data_colored = []
for row in results_data:
    colored_row = {}
    for i, (key, value) in enumerate(row.items()):
        if i == 0:  # First column (Node)
            colored_row[bold_headers[i]] = f"{BLUE}{value}{RESET}"
        else:
            colored_row[bold_headers[i]] = value
    results_data_colored.append(colored_row)

print(tabulate(results_data_colored, headers="keys", tablefmt="grid"))

# %%
# Display sensitivity analysis results in formatted tables for each node
SEP = "=" * 120
sep = "-" * 120

print(SEP)
print(f"{BOLD}{BLUE}SENSITIVITY ANALYSIS RESULTS - Symbolic Differentiation at Mean Values{RESET}")
print(SEP)

for node, sens_results in sensitivity_results.items():
    sens = node_sensitivities[node]

    # Get the derived coefficients we care about for this node
    derived_coeff_keys = [
        k for k in sens_results.keys() if not k.startswith("SEN_{\\Pi")
    ]

    print(f"\n{BOLD}{BLUE}Node: {node}{RESET}")
    print(sep)

    for coeff_key in derived_coeff_keys:
        sens_data = sens_results[coeff_key]

        # Get coefficient name from the node-specific sensitivity workflow
        if coeff_key in sens.coefficients:
            coeff_name = sens.coefficients[coeff_key].name
        else:
            coeff_name = coeff_key

        print(f"\n{BOLD}{coeff_key:<20}{RESET} ({coeff_name})")
        print(sep)

        # Calculate total sensitivity for relative percentages
        total_sens = sum(abs(v) for v in sens_data.values() if isinstance(v, (int, float)))

        # Sort by absolute sensitivity (descending)
        sorted_vars = sorted(
            sens_data.items(),
            key=lambda x: abs(x[1]) if isinstance(x[1], (int, float)) else 0,
            reverse=True,
        )

        # Prepare data for tabulate
        table_data = []
        for var_sym, sens_val in sorted_vars:
            if isinstance(sens_val, (int, float)):
                # Get variable name from the node-specific workflow
                if var_sym in sens.variables:
                    var_name = sens.variables[var_sym].name
                else:
                    var_name = var_sym

                rel_impact = (abs(sens_val) / total_sens * 100) if total_sens > 0 else 0
                sens_str = f"{sens_val:+.4e}"

                if rel_impact > 40:
                    impact_label = "DOMINANT"
                    impact_color = RED
                elif rel_impact > 20:
                    impact_label = "MAJOR"
                    impact_color = YELLOW
                elif rel_impact > 10:
                    impact_label = "MODERATE"
                    impact_color = CYAN
                else:
                    impact_label = "MINOR"
                    impact_color = GREEN

                impact_desc = f"{impact_color}{impact_label:<9}{RESET} ({var_name})"
                
                # Blue color for Variable column (first column)
                var_sym_colored = f"{BLUE}{var_sym}{RESET}"
                table_data.append([var_sym_colored, sens_str, f"{rel_impact:.2f}", impact_desc])

        # Bold headers
        header_names = ["Variable", "Sensitivity", "Relative Impact (%)", "Impact"]
        headers = [f"{BOLD}{h}{RESET}" for h in header_names]

        print(tabulate(table_data, headers=headers, tablefmt="grid"))

print("\n" + SEP)

# %% [markdown]
# ## 8. Generate Grid-Based Simulation Data
# 
# For Iteration 2, this stage generates structured queueing data for the 7-node PACS network using node definitions from `PACS-vars-iter2.json` and workload scenarios from the `routing` block.
# 
# **Iteration 2 strategy:**
# - Run the analysis per PACS node: IB, IWS, IRS, DB, WAS, RAS, OB.
# - Evaluate all 5 routing scenarios: `100R`, `80R20W`, `50R50W`, `20R80W`, `100W`.
# - Sweep local M/M/c/K design variables from each node's JSON `_data` fields.
# - Recompute operational outputs ($L$, $W$, $\chi$, $M_{\text{act}}$) per sampled operating point before PyDASA analysis.
# 
# **Configuration data from JSON:**
# - $\mu_i$ (service rate): `[200, 500, 1000]` req/s.
# - $c_i$ (servers): `[1, 2, 4]`.
# - $K_i$ (capacity): node-specific arrays (for example `[8, 16, 32]` in brokers/DB and `[4, 8, 16]` in internal services).
# - $\varepsilon_i$ (error rate): fixed at `0.01` for all nodes.
# 
# **Node payload assumptions (standard units in bit/req):**
# - Write-path payload density spans $8.0\times10^6$ to $1.28\times10^8$ bit/req (equivalent to 1-16 MB/req).
# - Read requests and ACK traffic are fixed at $8.0\times10^4$ bit/req (0.01 MB/req).
# - Mixed nodes (IB, DB, OB) inherit blended payload density from routing proportions.
# 
# **Arrival-rate handling (Iteration 2):**
# - Only IB arrival rate is independent, set by the IB setpoint.
# - All other node arrival rates are solved from the Jackson network balance equations.
# - Those solved $\lambda_i$ values are then used as fixed simulation inputs per scenario.
# 
# **Per-node base design grid:**
# - $K_i$: 3 values per node.
# - $\mu_i$: 3 values.
# - $c_i$: 3 values.
# - Base combinations per node per scenario: $3 \times 3 \times 3 = 27$.
# 
# **Per node/scenario workflow:**
# 1. Load node-specific $K_i$, $\mu_i$, $c_i$, payload density (bit/req), and fixed $\varepsilon_i$ from JSON.
# 2. Enforce the dependency $M_{\text{buf},i}=K_i\cdot\rho_{\text{req},i}$ to keep feasible $(K_i,\rho_{\text{req},i})$ pairs only.
# 3. Set IB input rate and solve remaining $\lambda_i$ via the Jackson network.
# 4. Evaluate the node M/M/c/K model.
# 5. Compute derived variables ($\chi_i$, $L_i$, $W_i$, $M_{\text{act},i}$) in standard units.
# 6. Store results for PyDASA coefficient, sensitivity, and simulation workflows.
# 
# This keeps grid generation consistent with Iteration 2: scenario-driven routing, node-specific configurations, Jackson-network-consistent arrival rates, and standard-unit payload handling.

# %%
# build the enviromental + artifacts specs, cols = 13*7 = 91
# use artifact specs from JSON
print("--- Building DataFrame columns from artifact specs ---")

df_cols = []
for node, specs in art_specs.items():
    relevant_lt = specs.get("vars", {})
    t_cols = list(relevant_lt.keys())
    df_cols.extend(t_cols)

print(f"Total columns for DataFrame: {len(df_cols)}")
art_specs_df = pd.DataFrame(columns=df_cols)

# err: 1% as 2 sigma in QoS agreement.
ERR = 0.01     # Error rate [%]

# lamba_zero: arrival rate starting point: 100 req/s
lambda_zero = 100  # Arrival rate [req/s]
lambda_step = 10    # Arrival rate step [req/s]

# %%
# STEP A: Generate artifact specs grid
# ====================================
print("=" * 80)
print("STEP A: Generating Artifacts Spec Grid")
print("=" * 80)
# iterate over the following parameters per node: K, rho, c, and mu
# remember K and rho are dependent

simul_configs = {}
simul_results = {}

# setup artifact specs for each node and store in simul_configs
for node, specs in art_specs.items():
    idx = specs.get("idx", -1)
    print(f"\n\t- Processing artifact: {idx}={node}")

    # get the relevant variables for the node
    relevant_lt = specs.get("vars", {})
    print(f"\t- Relevant variables for '{node}': {len(relevant_lt.keys())}")

    # create the artifact specs grid for the node
    specs_df = setup_artifact_specs(relevant_lt)
    specs_df = setup_environmental_conds(relevant_lt, specs_df)
    # specs_df = setup_queue_metrics(relevant_lt, specs_df)

    # add the artifact specs df to the simul_configs dict under the node key
    simul_configs[node] = specs_df


# %%
# ---- Summary based on simul_configs (new workflow) ----
print("\n" + "=" * 80)
print("Artifacts Grid Summary (from simul_configs)")
print("=" * 80)

n_nodes = len(simul_configs)
total_rows = sum(df.shape[0] for df in simul_configs.values())
total_cols = sum(df.shape[1] for df in simul_configs.values())

print(f"Nodes processed: {n_nodes}")
print(f"Total grid rows across nodes: {total_rows}")
print(f"Total columns across node grids: {total_cols}")

# Collect data for tabulate
grid_data = [
    {
        "Node": node,
        "Rows": df.shape[0],
        "Cols": df.shape[1],
        "Relevant Vars": len(art_specs.get(node, {}).get("vars", {}))
    }
    for node, df in simul_configs.items()
]

# Create bold headers
bold_headers = [f"{BOLD}{header}{RESET}" for header in grid_data[0].keys()]

# Colorize first column (Node) in blue
grid_data_colored = []
for row in grid_data:
    colored_row = {}
    for i, (key, value) in enumerate(row.items()):
        if i == 0:  # First column (Node)
            colored_row[bold_headers[i]] = f"{BLUE}{value}{RESET}"
        else:
            colored_row[bold_headers[i]] = value
    grid_data_colored.append(colored_row)

print("\n" + tabulate(grid_data_colored, headers="keys", tablefmt="grid"))

# %%
print("=" * 70)
print(f"===== Jackson grid ready: {total_rows} configurations =====")
print("=" * 70)

print("\nSimulation Constants:")
print("-" * 70)
print(f"\t- Independent input (IB lambda): {lambda_zero:.1f} [req/s]")
print(f"\t- Error Rate (epsilon): {ERR * 100:.2f} [%]")
print("\t- Arrival rates for other nodes: solved by Jackson network")

# STEP B: Create DataFrame for Queue Variables
print("\n" + "=" * 70)
print("STEP B: Creating Queue Model DataFrame")
print("=" * 70)

print("DataFrame created for Jackson-grid queue results")
# setup artifact specs for each node and store in simul_configs
for node, specs in art_specs.items():
    idx = specs.get("idx", -1)
    print(f"\n\t-Processing artifact: {idx}={node}")

    # get the relevant variables for the node
    relevant_lt = specs.get("vars", {})
    print(f"\t- Relevant variables for '{node}': {len(relevant_lt.keys())}")
    
    # create dataframe for the node with the relevant variables as columns
    exp_df = pd.DataFrame(columns=list(relevant_lt.keys()))
    simul_results.update({node: exp_df})
    print(f"\t- Initial shape: {exp_df.shape}")

print("=" * 70)

# %%
# STEP C: Generate Data Points with M/M/c/K Model
print("=" * 60)
print("STEP C: Generating Data with M/M/c/K Queueing Model")
print("=" * 60)

for node, specs in art_specs.items():
    idx = specs.get("idx", -1)
    print(f"\n\t- Processing artifact: {idx} = {node}")

    # get the relevant variables for the node
    relevant_lt = specs.get("vars", {})
    print(f"\t- Relevant variables for '{node}': {len(relevant_lt.keys())}")

    # get the simul_config grid for the node
    config_df = simul_configs[node]
    print(f"\t- Grid shape for '{node}': {config_df.shape}")

    # get the empty exp_df for the node
    exp_df = simul_results[node]

    exp_df = simulate_artifact(lambda_zero,
                               lambda_step,
                               config_df,
                               exp_df)
    simul_results[node] = exp_df
    print(f"\t- Result shape for '{node}': {exp_df.shape}")

# %%
# Summary after executing all node simulations
print("\n" + "=" * 80)
print("STEP C SUMMARY (from simul_results)")
print("=" * 80)

total_rows = sum(df.shape[0] for df in simul_results.values())
total_cols = sum(df.shape[1] for df in simul_results.values())

print(f"Nodes simulated: {len(simul_results)}")
print(f"Total data rows across nodes: {total_rows}")
print(f"Total columns across node results: {total_cols}")

# Collect data for tabulate
simul_data = [
    {
        "Node": node,
        "Rows": df.shape[0],
        "Cols": df.shape[1]
    }
    for node, df in simul_results.items()
]

# Create bold headers
bold_headers = [f"{BOLD}{header}{RESET}" for header in simul_data[0].keys()]

# Colorize first column (Node) in blue
simul_data_colored = []
for row in simul_data:
    colored_row = {}
    for i, (key, value) in enumerate(row.items()):
        if i == 0:  # First column (Node)
            colored_row[bold_headers[i]] = f"{BLUE}{value}{RESET}"
        else:
            colored_row[bold_headers[i]] = value
    simul_data_colored.append(colored_row)

print("\n" + tabulate(simul_data_colored, headers="keys", tablefmt="grid"))

# %%
print("\n" + "=" * 80)
print("DATA GENERATION COMPLETE")
print("=" * 80)

n_nodes = len(simul_results)
total_rows = sum(df.shape[0] for df in simul_results.values())
avg_rows_per_node = (total_rows / n_nodes) if n_nodes else 0.0

print(f"\t- Total nodes: {n_nodes}")
print(f"\t- Total data points (all nodes): {total_rows}")
print(f"\t- Average points per node: {avg_rows_per_node:.1f}")

print("\n" + "=" * 80)
print("DATA STATISTICS (PER NODE)")
print("=" * 80)


for node, df in simul_results.items():
    print(f"\n{BOLD}{BLUE}[{node}]{RESET}")
    if df.empty:
        print("(empty dataframe)")
    else:
        with pd.option_context('display.float_format', lambda x: f'{x:.4e}'):
            stats_df = df.describe(include='all')

            # Convert to tabulate format
            stats_data = []
            for idx, row in stats_df.iterrows():
                row_dict = {"Statistic": idx}
                for col in stats_df.columns:
                    row_dict[col] = row[col]
                stats_data.append(row_dict)

            # Create bold headers
            bold_headers = [
                f"{BOLD}{header}{RESET}" for header in stats_data[0].keys()]

            # Colorize first column (Statistic) in blue
            stats_data_colored = []
            for row in stats_data:
                colored_row = {}
                for i, (key, value) in enumerate(row.items()):
                    if i == 0:  # First column (Statistic)
                        colored_row[bold_headers[i]] = f"{BLUE}{value}{RESET}"
                    else:
                        colored_row[bold_headers[i]] = value
                stats_data_colored.append(colored_row)

            print(tabulate(stats_data_colored, headers="keys", tablefmt="grid"))

# %%

print("\n" + "=" * 80)
print("COMBINED DATA STATISTICS")
print("=" * 80)

combined_df = pd.concat(simul_results.values(),
                        ignore_index=True) if simul_results else pd.DataFrame()
if combined_df.empty:
    print("(no combined data available)")
else:
    with pd.option_context('display.float_format', lambda x: f'{x:.4e}'):
        stats_df = combined_df.describe(include='all')

        # Convert to tabulate format
        combined_stats_data = []
        for idx, row in stats_df.iterrows():
            row_dict = {"Statistic": idx}
            for col in stats_df.columns:
                row_dict[col] = row[col]
            combined_stats_data.append(row_dict)

        # Create bold headers
        bold_headers = [
            f"{BOLD}{header}{RESET}" for header in combined_stats_data[0].keys()]

        # Colorize first column (Statistic) in blue
        combined_stats_colored = []
        for row in combined_stats_data:
            colored_row = {}
            for i, (key, value) in enumerate(row.items()):
                if i == 0:  # First column (Statistic)
                    colored_row[bold_headers[i]] = f"{BLUE}{value}{RESET}"
                else:
                    colored_row[bold_headers[i]] = value
            combined_stats_colored.append(colored_row)

        print(tabulate(combined_stats_colored, headers="keys", tablefmt="grid"))

print("=" * 80)

# %%
# STEP D: Add data to node-wise PyDASA variables
# ==============================================
print("\n" + "=" * 80)
print("STEP D: Injecting Data into Node Variables")
print("=" * 80)

node_points = {}
updated_count = 0
missing_count = 0

for node, node_df in simul_results.items():
    if node in node_vars:
        if node_df is not None and not node_df.empty:
            node_points[node] = len(node_df)

            # Best match: simul_results already stores node-suffixed symbols
            for sym, var in node_vars[node].items():
                if sym in node_df.columns:
                    var.data = node_df[sym].tolist()
                    updated_count += 1
                    print(f"\t- OK [{BLUE}{BOLD}{node}{RESET}]: {sym:<20} <- {len(var.data):>5} points")
                else:
                    missing_count += 1
                    print(f"\t- WARN [{BLUE}{BOLD}{node}{RESET}]: No data column for symbol: {sym}")
        else:
            print(f"\t- WARN [{BLUE}{BOLD}{node}{RESET}]: empty dataframe in simul_results")
    else:
        print(f"\t- WARN [{BLUE}{BOLD}{node}{RESET}]: node not found in node_vars")

# Re-bind node engines to updated variables
for node, eng in node_engines.items():
    eng.variables = node_vars[node]

# Build a combined dataframe for downstream steps
if simul_results:
    data_df = pd.concat(simul_results.values(), ignore_index=True)
else:
    data_df = pd.DataFrame()
exp_df = data_df  # legacy alias used by downstream cells

print("\n" + "-" * 80)

# Create summary statistics table
summary_data = [
    {
        "Metric": "Nodes updated",
        "Value": len(node_points)
    },
    {
        "Metric": "Variables updated",
        "Value": updated_count
    },
    {
        "Metric": "Missing symbol links",
        "Value": missing_count
    },
    {
        "Metric": "Combined rows (data_df)",
        "Value": len(data_df)
    }
]

# Create bold headers
bold_headers = [f"{BOLD}{header}{RESET}" for header in summary_data[0].keys()]

# Colorize first column (Metric) in blue
summary_data_colored = []
for row in summary_data:
    colored_row = {}
    for i, (key, value) in enumerate(row.items()):
        if i == 0:  # First column (Metric)
            colored_row[bold_headers[i]] = f"{BLUE}{value}{RESET}"
        else:
            colored_row[bold_headers[i]] = value
    summary_data_colored.append(colored_row)

print(tabulate(summary_data_colored, headers="keys", tablefmt="grid"))

# Node-wise breakdown
if node_points:
    print("\nNode-wise Data Points:")
    node_data = [
        {"Node": node, "Rows": n_pts}
        for node, n_pts in node_points.items()
    ]

    bold_headers = [f"{BOLD}{header}{RESET}" for header in node_data[0].keys()]

    node_data_colored = []
    for row in node_data:
        colored_row = {}
        for i, (key, value) in enumerate(row.items()):
            if i == 0:  # First column (Node)
                colored_row[bold_headers[i]] = f"{BLUE}{value}{RESET}"
            else:
                colored_row[bold_headers[i]] = value
        node_data_colored.append(colored_row)

    print(tabulate(node_data_colored, headers="keys", tablefmt="grid"))

print("=" * 80)


# %% [markdown]
# ### Execute Monte Carlo Experiments

# %%
# Create PyDASA MonteCarloSimulation with grid data for each node
print("\n" + "=" * 80)
print("Creating PyDASA Monte Carlo Simulation with Grid Data (Per Node)")
print("=" * 80)

# Create one Monte Carlo handler per PACS node
node_montecarlos = {}

for idx, (node, eng) in enumerate(node_engines.items()):
    # Get node-specific data count
    node_data_count = len(simul_results[node]) if node in simul_results else 0
    
    # Create Monte Carlo simulation for this node
    mc = MonteCarloSimulation(
        _idx=idx,
        _variables=eng.variables,
        _schema=schema,
        _coefficients=eng.coefficients,
        _fwk="CUSTOM",
        _name=f"{node} Grid-Based Queue Analysis",
        _cat="DATA",  # category to read the variable data
        _experiments=node_data_count,
    )
    node_montecarlos[node] = mc

# %%
print("=" * 80)
print(f"node_montecarlos created: {len(node_montecarlos)} simulations")
print("=" * 80)

# Collect data for tabulate
mc_data = [
    {
        "Node": node,
        "Simulation Name": mc.name,
        "Experiments": mc.experiments,
        "Coefficients": len(mc.coefficients)
    }
    for node, mc in node_montecarlos.items()
]

# Create bold headers
bold_headers = [f"{BOLD}{header}{RESET}" for header in mc_data[0].keys()]

# Colorize first column (Node) in blue
mc_data_colored = []
for row in mc_data:
    colored_row = {}
    for i, (key, value) in enumerate(row.items()):
        if i == 0:  # First column (Node)
            colored_row[bold_headers[i]] = f"{BLUE}{value}{RESET}"
        else:
            colored_row[bold_headers[i]] = value
    mc_data_colored.append(colored_row)

print(tabulate(mc_data_colored, headers="keys", tablefmt="grid"))

# Run Monte Carlo simulation for each node
print("\n--- Running Monte Carlo Simulations (all nodes) ---")
for node, mc in node_montecarlos.items():
    if mc.experiments > 0:
        _node = f"{BLUE}{BOLD}{node}{RESET}"
        _msg = f"\tRunning Monte Carlo for node: {_node} with "
        _msg += f"{mc.experiments} experiments..."
        print(_msg)
        mc.run_simulation(iters=mc.experiments)
        _msg = f"\tCompleted Monte Carlo for node: {_node}"
        _msg += f" with {len(mc.simulations)} coefficient sets."
        print(_msg)
    else:
        print(f"\t[{BLUE}{BOLD}{node}{RESET}] Skipped - no data available")

print("\n" + "-" * 80)
print("Monte Carlo simulations complete (all nodes)")
print("=" * 80)

# %%
# extract coefficient simulation results for each node
coef_simul_results = {}

print("=" * 80)
print("EXTRACTING COEFFICIENT SIMULATION RESULTS")
print("=" * 80)

for node, mc in node_montecarlos.items():
    print(f"\n[{BLUE}{BOLD}{node}{RESET}] Extracting coefficients data...")

    if not hasattr(mc, "simulations") or len(mc.simulations) == 0:
        print(f"\t✗ WARNING: No simulations found for {node}")
        continue

    all_keys = list(mc.simulations.keys())
    derived_keys = [k for k in all_keys if not k.startswith("\\Pi_")]
    print(f"\t→ Found {len(derived_keys)} coefficients")

    node_coef_dict = {}
    extracted_count = 0
    error_count = 0

    for coeff_key in derived_keys:
        try:
            coeff_sim = mc.get_simulation(coeff_key)
            coeff_results = coeff_sim.extract_results()
            if coeff_key in coeff_results:
                node_coef_dict[coeff_key] = coeff_results[coeff_key]
                extracted_count += 1
        except Exception as e:
            print(f"\t⚠ Error extracting {coeff_key}: {e}")
            error_count += 1

    # Get parameters (c, μ, K) from simul_results using find_key()
    if node in simul_results:
        config = simul_results[node]

        try:
            c_key = find_key(config, "c_")
            node_coef_dict[c_key] = config.get(c_key, [])
        except KeyError:
            pass

        try:
            mu_key = find_key(config, "\\mu_")
            node_coef_dict[mu_key] = config.get(mu_key, [])
        except KeyError:
            pass

        try:
            K_key = find_key(config, "K_")
            node_coef_dict[K_key] = config.get(K_key, [])
        except KeyError:
            pass

    coef_simul_results[node] = node_coef_dict
    print(f"\t→ Extracted {extracted_count} coefficients + parameters")
    print(f"\t→ Total items stored: {len(node_coef_dict)}")
    if error_count > 0:
        print(f"\t⚠ Errors: {error_count}")
    print(f"\t✓ {node} complete!")
print("\n" + "=" * 80)
print("Coefficient extraction complete for all nodes")

# %%
print("\n" + "=" * 80)
print("STATISTICS FOR ALL NODES AND COEFFICIENTS")
print("=" * 80)

for node in coef_simul_results.keys():
    node_dict = coef_simul_results[node]

    print(f"\n{BOLD}{BLUE}[{node}]{RESET}")

    # Collect statistics data for tabulate
    stats_data = []
    for key in node_dict.keys():
        data = np.array(node_dict[key])

        if len(data) == 0:
            display_name = key.replace(f"_{{{node}}}", "").replace(
                f"_{node}", "").replace("\\", "")
            stats_data.append({
                "Item": display_name,
                "Samples": "(empty)",
                "Mean": "---",
                "Std Dev": "---",
                "Min": "---",
                "Max": "---"
            })
        else:
            n_samples = len(data)
            mean_val = np.mean(data)
            std_val = np.std(data)
            min_val = np.min(data)
            max_val = np.max(data)

            display_name = key.replace(f"_{{{node}}}", "").replace(
                f"_{node}", "").replace("\\", "")

            stats_data.append({
                "Item": display_name,
                "Samples": n_samples,
                "Mean": f"{mean_val:.4e}",
                "Std Dev": f"{std_val:.4e}",
                "Min": f"{min_val:.4e}",
                "Max": f"{max_val:.4e}"
            })

    # Create bold headers
    bold_headers = [
        f"{BOLD}{header}{RESET}" for header in stats_data[0].keys()]

    # Colorize first column (Item) in blue
    stats_data_colored = []
    for row in stats_data:
        colored_row = {}
        for i, (key, value) in enumerate(row.items()):
            if i == 0:  # First column (Item)
                colored_row[bold_headers[i]] = f"{BLUE}{value}{RESET}"
            else:
                colored_row[bold_headers[i]] = value
        stats_data_colored.append(colored_row)

    print(tabulate(stats_data_colored, headers="keys", tablefmt="grid"))
print("\n" + "=" * 80)
print(f"✓ Done: {len(coef_simul_results)} nodes extracted successfully")
print("=" * 80)

# %%
# Create 3x3 grid of per-node coefficient distributions
# Each node cell contains 2x2 grid of the 4 derived coefficients
print("=" * 80)
print("Per-Node Coefficient Distributions (3×3 Node Grid)")
print("=" * 80)

# Extract node names from art_specs without sorting or inline conditionals
node_disp_titles = {}
if coef_simul_results is not None:
    for node in coef_simul_results.keys():
        node_spec = art_specs.get(node, {})
        node_disp_titles[node] = node_spec.get("name", node)

# Convert list to dict for display labels
coeff_display_labels = {
    "theta": "Occupancy ($\\theta$)",
    "sigma": "Stall ($\\sigma$)",
    "eta": "Effective-Yield ($\\eta$)",
    "phi": "Memory-Usage ($\\phi$)",
}

img_name = "per_node_coeff_dist_grid"
# get cur dir and create path for saving the image
cur_dir = os.getcwd()
# add subfolder to path
img_folder = "img"
iter_folder = "iter2"
f_path = os.path.join(cur_dir, img_folder, iter_folder)

title = "PACS Nodes Coefficient Distributions"

img = plot_arts_distributions(title,
                              coef_simul_results,
                              node_disp_titles,
                              coeff_display_labels,
                              img_name,
                              f_path,                        verbose=False)
img.show()

# %% [markdown]
# ## 9. Plot Yoly Diagram per Component
# 
# Similar to the Moody diagram for Reynolds number, we can plot the relationship between the coefficients of **Occupancy** ($\theta_i$), **Stall** ($\sigma_i$), and **Effective-Yield** ($\eta_i$) to visualize queue behavior across different configurations for each component $i$ in the 7-node PACS network.
# 
# - **X-axis:** Occupancy $(\theta_i = L_i/K_i)$ - Queue fullness ratio for component $i$
# - **Y-axis:** Stall $(\sigma_i = W_i \cdot \lambda_i / L_i)$ - Service blocking probability for component $i$
# - **Z-axis:** Effective-Yield $(\eta_i = \chi_i \cdot K_i / (\mu_i \cdot c_i))$ - Resource utilization effectiveness for component $i$
# - **Color coding:** By number of servers (red=1, orange=2, green=4)
# 
# The relationship reveals how queue occupancy directly influences the probability of service stalls across different system configurations for each PACS component.
# 

# %%
# Create 7 separate 3D yoly diagrams (one per component/service)
print("=" * 80)
print("Per-Node 3D Yoly Diagrams (3×3 Node Grid)")
print("=" * 80)

# Extract node names and display titles
node_disp_titles = {}
if coef_simul_results is not None:
    for node in coef_simul_results.keys():
        node_spec = art_specs.get(node, {})
        node_disp_titles[node] = node_spec.get("name", node)

img_name = "pacs_eqs_yoly_3d"

img = plot_yoly_arts_behaviour("PACS Per-Node 3D Yoly Diagrams",
                               coef_simul_results,
                               node_disp_titles,
                               img_name,
                               f_path,
                               verbose=False)
img.show()

# %%
# Create 7 separate 3D yoly diagrams (one per component/service)
print("=" * 80)
print("Per-Node 2D Yoly Charts (3×3 Node Grid)")
print("=" * 80)

img_name = "pacs_eqs_yoly_2d"

img = plot_yoly_arts_charts("PACS Per-Node 2D Yoly Charts",
                            coef_simul_results,
                            node_disp_titles,
                            img_name,
                            f_path,
                            verbose=False)
img.show()

# %% [markdown]
# ## 10. Latency Decomposition: Archival vs. Retrieval
# 
# The 7-node Jackson network PACS model decomposes end-to-end latency into two distinct operational paths:
# 
# 1. **Archival Path (Write-Heavy)**: IB → IWS → DB → WAS → OB
#    - Used for imaging device submissions (20% of traffic, α_W = 0.20)
#    - Quality Requirement (QS-1): $W_{\text{archival}} \leq 500.0$ ms
# 
# 2. **Retrieval Path (Read-Heavy)**: IB → IRS → DB → RAS → OB
#    - Used for clinical staff image requests (80% of traffic, α_R = 0.80)
#    - Quality Requirement (QS-2): $W_{\text{retrieval}} \leq 500.0$ ms
# 
# ---
# 
# ### Archival End-to-End Latency
# 
# **Path Traversal**: IB → IWS → DB → WAS → OB
# 
# **Visit Ratios** ($v_j^{\text{(W)}}$):
# 
# | Node  | $v_j^{\text{(W)}}$ | Rationale |
# |-------|:--:|-----------|
# | IB    | 1.0 | All writes enter via inbound broker |
# | IWS   | 0.20 | 20% of requests are archival writes |
# | DB    | 1.0 | All writes require metadata registration |
# | WAS   | 1.0 | All writes access resource allocation service |
# | OB    | 1.0 | All acknowledgments exit via outbound broker |
# 
# **Archival Latency Formula**:
# 
# $$W_{\text{archival}} = W_{\text{IB}} + 0.20 \cdot W_{\text{IWS}} + W_{\text{DB}} + W_{\text{WAS}} + W_{\text{OB}}$$
# 
# **Dominant contributors**: IWS (write validation, 0.20 multiplier), DB (metadata commit), WAS (resource management), broker latencies (IB, OB)
# 
# ---
# 
# ### Retrieval End-to-End Latency
# 
# **Path Traversal**: IB → IRS → DB → RAS → OB
# 
# **Visit Ratios** ($v_j^{\text{(R)}}$):
# 
# | Node  | $v_j^{\text{(R)}}$ | Rationale |
# |-------|:--:|-----------|
# | IB    | 1.0 | All reads enter via inbound broker |
# | IRS   | 0.80 | 80% of requests are retrieval reads |
# | DB    | 1.0 | All reads require metadata lookup & ACL check |
# | RAS   | 1.0 | All reads traverse resource escalation service |
# | OB    | 1.0 | All images exit via outbound broker |
# 
# **Retrieval Latency Formula**:
# 
# $$W_{\text{retrieval}} = W_{\text{IB}} + 0.80 \cdot W_{\text{IRS}} + W_{\text{DB}} + W_{\text{RAS}} + W_{\text{OB}}$$
# 
# **Dominant contributors**: IRS (0.80 multiplier, repository fetch), DB (metadata), RAS (resource escalation), broker latencies (IB, OB)
# 
# ---
# 
# ### Composite End-to-End Latency
# 
# **Weighted Average by Routing Fraction**:
# 
# $$W_{\text{e2e}} = \alpha_W \cdot W_{\text{archival}} + \alpha_R \cdot W_{\text{retrieval}} = 0.20 \cdot W_{\text{archival}} + 0.80 \cdot W_{\text{retrieval}}$$
# 
# **System-Level Quality Requirement**:
# $$W_{\text{e2e}} \leq 500.0 \text{ ms}$$
# 
# Balances write-heavy imaging device feedback (20%, QS-1) with read-heavy clinical staff latency (80%, QS-2).
# 
# ---
# 
# ### Operational Scenarios
# 
# The system is evaluated across **five operational routing scenarios**, representing different workload patterns:
# 
# | Scenario | Read % | Write % | Symbol | Rationale |
# |----------|:------:|:-------:|:------:|-----------|
# | **Read-Only** | 100 | 0 | 100R | Peak retrieval load (clinical review hours) |
# | **Read-Heavy (Baseline)** | 80 | 20 | 80R20W | Typical operational mix during working hours |
# | **Balanced** | 50 | 50 | 50R50W | Mixed read/write intensive workload |
# | **Write-Heavy** | 20 | 80 | 20R80W | Peak imaging hours with concurrent archival |
# | **Write-Only** | 0 | 100 | 100W | Batch archival or bulk import operations |
# 
# **Baseline Scenario**: 80R20W (α_R = 0.80, α_W = 0.20)
# - $\lambda_{\text{in}} \geq 100$ req/s until the first bottleneck node saturates $(\rho \leq 1.0)$.
# - Reflects typical operational profile during clinical hours.
# - Used as primary reference for performance tuning.
# - Other scenarios test architectural flexibility and scaling limits.
# 
# For each scenario, the Jackson network balance equations are solved to determine node-specific arrival rates $\lambda_i$, which then drive per-node M/M/c/K analysis and PyDASA dimensionless coefficient extraction.

# %% [markdown]
# ## 11. Optimal Artifact Configuration Design
# 
# Based on individual per-node simulations, the following configurations are optimal for the baseline 80R20W operational scenario in iteration 2.
# 
# ---
# 
# ### Artifact (Service) Specifications
# 
# The PACS network comprises **7 distinct architectural components** (artifacts), each with specific performance configuration parameters. These coefficients define operational boundaries and capacity constraints for the queuing analysis.
# 
# 
# | Node | Full Name | Role | $c (req)$ | $K (req)$ | $M_{\text{buf}}$ (MB) | $\mu$ (req/s) | $\epsilon$ | Req Size (MB) |
# |:----:|----------|:---:|:---:|:---:|:---:|:---:|:---:|:---:|
# | **IB** | Inbound Broker | Handle incoming requests | 1 | 64 | 64 | 1000 | 1% | 1–16 |
# | **IWS** | Image Write Service | Save new images | 2 | 32 | 32 | 500 | 1% | 1–16 |
# | **IRS** | Image Reading Service | Load existing images | 2 | 320 | 32 | 500 | 1% | 0.1 |
# | **DB** | Data Base Service | Save and retrieve data / metadata | 1 | 64 | 64 | 200 | 1% | 1–16 |
# | **WAS** | Writing Acknowledgment Service | Acknowledge writing requests | 2 | 320 | 32 | 500 | 1% | 0.1 |
# | **RAS** | Reading Acknowledgment Service | Acknowledge reading requests | 2 | 32 | 32 | 500 | 1% | 1–16 |
# | **OB** | Outbound Broker | Handle outgoing responses | 1 | 64 | 64 | 1000 | 1% | 1–16 |
# 
# Configuration Parameters
# 
# - **λ (lambda)**: Arrival rate [requests/sec]
# - **μ (mu)**: Service rate [requests/sec]
# - **c**: Number of servers (parallelism degree)
# - **K**: Queue capacity (max system population)
# - **M_buf**: Buffer memory allocation (MB)
# - **ε (epsilon)**: Error/retry rate (1% across all nodes)
# 
# ---
# 
# ### Rationale Summary
# 
# | Node | Servers | Queue Capacity | Buffer | Service Rate |
# |:----:|---------|----------------|--------|--------------|
# | **IB, OB** | $c=1$ single instance sufficient for routing | $K=64$ handles burst accumulation during congestion | 64 MB stages archival payloads (~4 images @ 16 MB) | $\mu=1000$ req/s minimizes broker latency |
# | **IWS, IRS, WAS, RAS** | $c=2$ dual-instance load distribution & redundancy | $K=32$ per-node mid-tier capacity | 32 MB intermediate processing & image staging | $\mu=500$ req/s balances read/write demands |
# | **DB** | $c=1$ single instance (shared bottleneck by all paths) | $K=64$ combined archival (20) + retrieval (80) = 100 req/s | 64 MB metadata caching & query results | $\mu=200$ req/s with headroom vs. $\lambda_{\text{DB}}=100$ |
# 
# ---
# 
# ### Important Notes
# 
# **Broker Symmetry**: IB and OB use identical specs to ensure balanced ingress/egress capacity at $v_{\text{IB}}^{(W)}=v_{\text{IB}}^{(R)}=1.0$ and $v_{\text{OB}}^{(W)}=v_{\text{OB}}^{(R)}=1.0$.
# 
# **DB Shared Bottleneck**: Single-server ($c=1$) with highest capacity ($K=64$) reflects combined load: both archival and retrieval paths visit DB at $v_{\text{DB}}^{(W)}=v_{\text{DB}}^{(R)}=1.0$.
# 
# **Mid-Tier Load Distribution**: IWS, IRS, WAS, RAS share $c=2$ instances at $\mu=500$ req/s to balance asymmetric visit patterns:
# - IWS: $v_{\text{IWS}}^{(W)}=0.20$ (archival path write cache), $v_{\text{IWS}}^{(R)}=1.0$ (retrieval read cache)
# - IRS: $v_{\text{IRS}}^{(W)}=0$ (archival: direct to DB), $v_{\text{IRS}}^{(R)}=0.80$ (retrieval: repository fetch); ACK-only (0.1 MB)
# - WAS: $v_{\text{WAS}}^{(W)}=1.0$ (archival resource allocation), $v_{\text{WAS}}^{(R)}=0$ (retrieval: none); ACK-only (0.1 MB)
# - RAS: $v_{\text{RAS}}^{(W)}=0$ (archival: none), $v_{\text{RAS}}^{(R)}=1.0$ (retrieval resource escalation)
# 
# **Error Rate**: All nodes configured with $\epsilon = 1\%$ error rate, consistent with quality requirements.
# 
# **Request Size Asymmetry**: Brokers, IWS (write cache), DB (metadata), and RAS handle full image payloads (1–16 MB). IRS and WAS handle acknowledgments only (0.1 MB), reducing I/O demand at these resource-constrained services.
# 
# **Buffer Hierarchy**: Brokers & DB (64 MB) > Mid-tier (32 MB) reflects payload handling tiers. Broker buffers support full-size images (~16 MB archival); mid-tier buffers sized for staging and metadata.
# 
# **Scenario Coverage**: Baseline configuration validated under 80R20W; scalability assessed across 100R, 50R50W, 20R80W, 100W scenarios via sensitivity analysis.
# 
# ---
# 
# ### Architectural Constraint
# 
# The buffer memory allocation (`M_buf`) follows a **fundamental design relationship** with queue capacity (`K`) and per-request memory (`ρ`):
# 
# ```
# M_buf = K × ρ   (total buffer = queue depth × request memory)
# ```
# 
# This constraint means **K and ρ are intrinsically paired:** they cannot be freely combined.
# 
# ---
# 
# ### Configuration (Solution) Space Limitation
# 
# We DON'T DO A Full Cartesian Product. If we allowed arbitrary combinations of K and ρ values, we would generate a massive cross-product. For a single node:
# 
# - K values: [4, 8, 16, 32, 64] → **5 options**
# - ρ values: [1.3e+08, 6.4e+07, 3.2e+07, 1.6e+07, 8.0e+06] → **5 options**
# - Unrestricted combinations: 5 × 5 = **25 configurations**
# 
# **But this creates infeasible designs.**
# 
# **Example Invalid Combination:**
# ```
# K=4 (from Profile 0) + ρ=6.4e+07 (from Profile 1)
# → M_buf = 4 × 6.4e+07 = 256 MB
# 
# But the optimal design specifies: M_buf = 512 MB at this scale
# → This configuration violates the M_buf constraint!
# ```
# ---
# 
# ### Index-Paired Profiles
# 
# We pair the optimal configuration (`optimal_cfg`) for to variables and define exactly **5 viable profiles** where K and ρ are **paired by index**:
# 
# | Profile | K | ρ (bytes/req) | M_buf (derived) |
# |---------|---|---------------|-----------------|
# | 0 | 4 | 1.3×10⁸ | 512 MB |
# | 1 | 8 | 6.4×10⁷ | 512 MB |
# | 2 | 16 | 3.2×10⁷ | 512 MB |
# | 3 | 32 | 1.6×10⁷ | 512 MB |
# | 4 | 64 | 8.0×10⁶ | 512 MB |
# 
# **Key insight:** All profiles maintain **constant M_buf allocation despite varying K** because ρ is inversely scaled.
# 
# ---
# 
# ### Importance of the Constraint
# 
# 1. **Resource efficiency**: M_buf stays fixed at design target (512 MB in this example)
# 2. **Feasibility**: Only 5 (K, ρ) pairs are architecturally viable, not 25
# 3. **Design intent**: K and ρ co-vary by necessity, not by chance
# 
# This constraint reduces the configuration search space from **5⁷ = 78,125 combinations** (if all nodes could mix freely) to a **heavily constrained design space** of genuinely feasible profiles.
# 
# ---
# 
# ### Operational Scenarios
# 
# Six operational workload scenarios are analyzed:
# 
# | Scenario | Read % | Write % | Baseline | Usage |
# |----------|--------|---------|----------|-------|
# | **100R** | 100 | 0 | No | Read-only peaks |
# | **80R20W** | 80 | 20 | ✓ Yes | Standard operations |
# | **50R50W** | 50 | 50 | No | Mixed balanced |
# | **20R80W** | 20 | 80 | No | Write-heavy |
# | **100W** | 0 | 100 | No | Archival peaks |
# 
# Each scenario stresses different network paths (archival vs. retrieval), allowing comprehensive performance characterization across PACS usage patterns.

# %% [markdown]
# ### Architectural Design
# 
# #### Artifact Definitions

# %%
print("=" * 60)
print(f"Extracting Artifact Configuration Column Names for Setup")
print("=" * 60)

net_cfg_cols = []
node_summary = {}

for node, cfg in art_specs.items():
    node_cols = list(cfg.get("vars", {}).keys())
    node_summary[node] = {
        "name": cfg.get("name", "Unknown"),
        "columns": len(node_cols),
        "column_list": node_cols
    }
    net_cfg_cols.extend(node_cols)

# Build table rows for tabulate
table_rows = []
for node, info in node_summary.items():
    node_display = f"{BLUE}{BOLD}{node}{RESET}"
    table_rows.append([
        node_display,
        info["name"],
        info["columns"]
    ])

# Create headers in bold
headers = [
    f"{BOLD}Symbol{RESET}",
    f"{BOLD}Full Name{RESET}",
    f"{BOLD}Config Cols{RESET}"
]

print(f"\n{BLUE}{BOLD}Node Configuration Summary:{RESET}")
print(tabulate(table_rows, headers=headers, tablefmt="grid"))

# Create DataFrame
opt_cfg_df = pd.DataFrame(columns=net_cfg_cols)

print(f"\n✓ DataFrame created with {len(net_cfg_cols)} configuration columns")
print(f"→ Final shape: {opt_cfg_df.shape}")
print("=" * 80)

# %% [markdown]
# #### Creating Artifact Design/Configuration Space

# %%
optimal_cfg = {}
print("=" * 60)
print("Populating optimal artifacts configurations")
print("=" * 60)

# iterate all nodes/components on the network
for node, cfg in art_specs.items():
    # get the artifact specs for the node
    specs_tmp = list(cfg.get("vars", {}).keys())
    # if node is a broker IB or OB
    td = {}
    print(f"\t[{BLUE}{BOLD}{node}{RESET}] Processing artifact specs...")
    # iterate all specs in the component/artifact
    for key in specs_tmp:
        if "\\lambda_{" in key and node in ("IB"):
            td.update({key: [100]})
        elif "\\lambda_{" in key and not node in ("IB"):
            td.update({key: [0]})
        elif "\\mu_{" in key and node in ("IB", "OB"):
            td.update({key: [1000]})
        elif "\\mu_{" in key and node in ("DB"):
            td.update({key: [200]})
        elif "\\mu_{" in key and node in ("IW", "IR", "WN", "RN"):
            td.update({key: [500]})
        elif "\\epsilon_{" in key:
            td.update({key: [0.01]})
        elif "\\chi_{" in key:
            td.update({key: [None]})
        elif "c_{" in key and node in ("IW", "IR", "WN", "RN"):
            td.update({key: [2.0]})
        elif "c_{" in key and node in ("IB", "OB", "DB"):
            td.update({key: [1.0]})
        # elif "c_{" in key and node in ("DB"):
        #     td.update({key: [4.0]})
        elif "K_{" in key and node in ("IB", "OB", "DB"):
            td.update({key: [4, 8, 16, 32, 64]})
        elif "K_{" in key and node in ("IW", "RN"):
            td.update({key: [2, 4, 8, 16, 32]})
        elif "K_{" in key and node in ("IR", "WN"):
            td.update({key: [320]})
        elif "d_{req_{" in key and node in ("IB", "OB", "DB", "IW", "RN"):
            # 16, 8, 4, 2, 1 MB to bit
            td.update({key: [1.28e8, 6.4e7, 3.2e7, 1.6e7, 8e6,]})
        elif "d_{req_{" in key and node in ("IR", "WN"):
            # 0.1 MB to bit
            td.update({key: [8e5]})
        elif "L_{" in key:
            td.update({key: [None]})
        elif "Lq_{" in key:
            td.update({key: [None]})
        elif "W_{" in key:
            td.update({key: [None]})
        elif "Wq_{" in key:
            td.update({key: [None]})
        elif "M_{act_{" in key:
            td.update({key: [None]})
        elif "M_{buf_{" in key and node in ("IW", "IR", "WN", "RN"):
            # 32 MB to bit
            td.update({key: [2.56e8]})
        elif "M_{buf_{" in key and node in ("IB", "OB", "DB"):
            # 64 MB to bit
            td.update({key: [5.12e8]})
        else:
            print(f"\t✗ Unrecognized node '{node}' in artifact specs!!!.")
    optimal_cfg.update(td)
print("-" * 60)
print(f"\n✓ Optimal configuration dictionary populated with {len(optimal_cfg)} parameters")

# %% [markdown]
# #### Formating Config to DataFrame

# %%
# Build optimal configuration DataFrame using paired (K, rho) indices
# CONSTRAINT: rho = M_buf / K for each (K, rho) pair at index i
# K, rho, M_buf are not independent — they're paired by profile index

# 1. Build key map per node
node_key_map = {}
for node, cfg in art_specs.items():
    vd = cfg.get("vars", {})

    try:
        node_key_map[node] = {
            "K": find_key(vd, "K_{"),
            "d_req": find_key(vd, "d_{req_"),
            "M_buf": find_key(vd, "M_{buf_{"),
        }
    except KeyError as e:
        print(f"\t✗ [{node}] missing key: {e}")

# 2. Identify varying K-d profiles (paired by index)
# node → {"K": [k0, k1, ...], "d": [r0, r1, ...], "n": N}
varying_K_d_nodes = {}
# node → {"K": k_val, "d": d_val}
single_K_d_nodes = {}

for node, km in node_key_map.items():
    K_key = km["K"]
    d_key = km["d_req"]

    K_opts = optimal_cfg.get(K_key, [None])
    d_opts = optimal_cfg.get(d_key, [None])

    K_opts = list(K_opts) if isinstance(K_opts, (list, tuple)) else [K_opts]
    d_opts = list(d_opts) if isinstance(d_opts, (list, tuple)) else [d_opts]

    n_K = len(K_opts)
    n_d = len(d_opts)

    if n_K > 1 or n_d > 1:
        if n_K != n_d:
            print(f"\t⚠ [{node}] K has {n_K} values but d has {n_d} | using min({n_K}, {n_d})")
        n_pairs = min(n_K, n_d)
        varying_K_d_nodes[node] = {
            "K": K_opts[:n_pairs],
            "d_req": d_opts[:n_pairs],
            "n": n_pairs
        }
    else:
        single_K_d_nodes[node] = {"K": K_opts[0], "d_req": d_opts[0]}

n_profiles = next(iter(varying_K_d_nodes.values()))["n"] if varying_K_d_nodes else 1

print("=" * 80)
print("CONFIG SPACE: paired (K, d) profiles by index [d = M_buf / K for each (K[i], d[i])]")
print("=" * 80)
print(f"Varying K-d nodes ({n_profiles} profile indices each) : {list(varying_K_d_nodes.keys())}")
print(f"Fixed K-d nodes (1 profile): {list(single_K_d_nodes.keys())}")
print(f"Total configurations (profile indices): {n_profiles}")
print("-" * 80)

# 3. Build one row per profile index 
# base_row: all keys from optimal_cfg collapsed to their first (or only) value
base_row = {
    k: (v[0] if isinstance(v, (list, tuple)) else v) for k, v in optimal_cfg.items()
}

rows = []
for i in range(n_profiles):
    row = dict(base_row)
    for node, km in node_key_map.items():
        if node in varying_K_d_nodes:
            K_val = varying_K_d_nodes[node]["K"][i]    # K[i]
            d_val = varying_K_d_nodes[node]["d_req"][i]    # d[i]
        else:
            K_val = single_K_d_nodes[node]["K"]
            d_val = single_K_d_nodes[node]["d_req"]
        
        row[km["K"]] = K_val
        row[km["d_req"]] = d_val
        row[km["M_buf"]] = K_val * d_val     # enforce M_buf = K × d
    rows.append(row)

best_art_spec_df = pd.DataFrame(rows, columns=list(optimal_cfg.keys()))

# 4. Summary
varying_cols = [
    c for c in best_art_spec_df.columns if best_art_spec_df[c].nunique() > 1
]
print(f"best_art_spec_df shape: {best_art_spec_df.shape} ← all {len(optimal_cfg)} config cols preserved")
print(f"Varying columns ({len(varying_cols)}): {varying_cols}")
print("-" * 80)
print("Full configuration (5 K-d profile indices × all network params):")
# display(best_art_spec_df)

# %% [markdown]
# #### Creating E-Quality Scenario DataFrames

# %%
# Extract routing scenario keys and matrices from env_conds
rout_keys = env_conds.get("_scenarios", {})
rout_mtxs = env_conds.get("_routs", {})
rout_lbls = env_conds.get("_labels", {})

# create a dictionary of routing configurations by zipping keys and matrices
pacs_envs = {}
pacs_eqs = {}

exp_cols = best_art_spec_df.columns.tolist()

for env, rout_mtx in zip(rout_keys, rout_mtxs):
    print(f"Processing routing scenario: {YELLOW}{env}{RESET}")
    m = np.array(rout_mtx).shape if rout_mtx is not None else "N/A"
    msg = f"\t- Routing matrix shape: {m}"
    print(msg)

    if rout_mtx is not None:
        pacs_envs[env] = np.array(rout_mtx)
        pacs_eqs[env] = pd.DataFrame(columns=exp_cols)

    else:
        print(f"⚠ Warning: Invalid Routing matrix for scenario '{env}'")

print("=" * 95)
print(f"Extracted {list(pacs_envs.keys())} routing scenarios.")
print(f"Extracted {rout_lbls} scenario labels.")
print("=" * 95)

# %% [markdown]
# #### Simulating the Architectural Design Space

# %%
# configure lambda zero step vector for routing scenarios
print("\nRouting Scenario Summary:")
lambda_step = 2.0
print(f"lambda step: {lambda_step}")
nodes = list(art_specs.keys())
lambda_step_vec = [0.0] * len(nodes)
lambda_step_vec[0] = lambda_step
print(f"Initial lambda step vector: {lambda_step_vec}")

for env, rout_mtx in pacs_envs.items():
    
    print(f"\n\tSimulating scenario: {YELLOW}{env}{RESET}")
    print(f"\tRouting matrix shape: {rout_mtx.shape}")
    print(f"\tValid Configurations: {len(best_art_spec_df)}")

    exp_df = pacs_eqs[env]
    exp_df = simulate_architecture(nodes,
                                   lambda_step_vec,
                                   best_art_spec_df,
                                   exp_df,
                                   rout_mtx,
                                   verbose=False)
    pacs_eqs[env] = exp_df
    print(f"\tExperiment DataFrame shape: {exp_df.shape}")

# %%
print("=" * 60)
print("=== Complete Architecture Simulation Summary ===")
print("=" * 60)

# Build table data
table_rows = []

for env, exp_df in pacs_eqs.items():
    env_display = f"{GREEN}{BOLD}{env}{RESET}"

    for art in list(node_vars.keys()):
        art_display = f"{BLUE}{BOLD}[{art}]{RESET}"
        art_df = exp_df.filter(regex=f"{art}.*")
        var_count = len(art_df.columns)

        # Add row for this artifact
        table_rows.append([
            env_display,
            art_display,
            f"{art_df.shape}",
            var_count
        ])

        # Process data
        for var in art_df.columns:
            if not var.startswith("U_{"):
                data = art_df[var].values
                t_var = node_vars[art].get(var)
                t_var.data = data
                node_vars[art][var] = t_var

# Create headers in bold
headers = [
    f"{BOLD}Scenario{RESET}",
    f"{BOLD}Symbol{RESET}",
    f"{BOLD}Shape{RESET}",
    f"{BOLD}Variables{RESET}"
]

print(tabulate(table_rows, headers=headers, tablefmt="grid"))
print("=" * 80)

# %% [markdown]
# #### Calculating E-QSs Metric Behaviour

# %%
# Helpers functions for variable tagging, DataFrame filtering, summation, and cumulative probability calculation

def _vtag(var: str, suffix: str, dbl_brace_tags: list) -> str:
    """_vtag Build a LaTeX column tag like \\lambda_{PACS} or M_{buf_{R_{PACS}}}.

    Args:
        var (str): Base variable name (e.g., "lambda", "M_{buf_").
        suffix (str): Suffix to append inside braces (e.g., "PACS").
        dbl_brace_tags (list): List of variable names that require double closing braces in LaTeX formatting.

    Returns:
        str: The formatted LaTeX column tag.
    """
    tag = f"{var}{{{suffix}}}"
    if var in dbl_brace_tags:
        tag += "}"
    return tag


def _filter_path(df: pd.DataFrame, path_nds: list) -> pd.DataFrame:
    """_filter_path Filter DataFrame columns to those containing any of the path node names.

    Args:
        df (pd.DataFrame): The DataFrame to filter.
        path_nds (list): A list of node names to include in the filter.

    Returns:
        pd.DataFrame: The filtered DataFrame.
    """
    regex = "|".join(path_nds)
    return df.filter(regex=regex)


def _to_int_if_needed(series: pd.Series,
                      var: str,
                      int_tags: list = None) -> pd.Series:  # type: ignore
    """_to_int_if_needed Round and cast to int for variables that must be integers.

    Args:
        series (pd.Series): The series to convert.
        var (str): The variable name.
        int_tags (list): A list of variable names that must be integers.

    Returns:
        pd.Series: The converted series.
    """
    if int_tags != None:
        if var in int_tags:
            series = series.round().astype(int)
    return series


def _sum_or_zero(df: pd.DataFrame,
                 index: pd.Index,
                 var: str,
                 int_tags: list = None) -> pd.Series:   # type: ignore
    """_sum_or_zero Sum columns or return zero Series if empty, then int-cast if needed.

    Args:
        df (pd.DataFrame): The DataFrame to sum.
        index (pd.Index): The index for the resulting Series.
        var (str): The variable name.
        int_tags (list): A list of variable names that must be integers.
    Returns:
        pd.Series: The summed series or a zero series if the DataFrame is empty.
    """
    if df.empty:
        s = pd.Series(0.0, index=index)
    else:
        s = pd.to_numeric(df.sum(axis=1), errors="coerce")
    return _to_int_if_needed(s, var, int_tags)


def _cumul_prob(path_df: pd.DataFrame, index: pd.Index) -> pd.Series:
    """_cumul_prob Cumulative probability: P(at least one error) = 1 - Π(1 - ε_i).

    Args:
        path_df (pd.DataFrame): The DataFrame containing path probabilities.
        index (pd.Index): The index for the resulting Series.

    Returns:
        pd.Series: The cumulative probability series.
    """
    """"""
    if path_df.empty:
        return pd.Series(0.0, index=index)
    numeric = path_df.apply(pd.to_numeric, errors="coerce")
    return 1.0 - (1.0 - numeric).prod(axis=1)

# %% [markdown]
# Here we aggregate the per-node metrics into the overall end-to-end meassurements of:
# 
# - $W_{\text{archival}}$ for the archival path
# - $W_{\text{retrieval}}$ for the retrieval path
# - And the composite $W_{\text{e2e}}$ for the overall system
# 
# This quantifies the Archival and Retrieval E-QSs and allows us to evaluate whether the system meets the quality requirements under each operational scenario.
# 
# We will compute the W/R metric for each scenario by:
# 1. Calculating the per-node latencies ($W_i$) from the M/M/c/K analysis for each node $i$ under the given scenario.
# 2. Using the visit ratios ($v_j^{(W)}$ and $v_j^{(R)}$) to analyze the node behavior according to the routing paths for archival and retrieval.
# 3. Summing the situation-specific metrics to get the overall behavior of the system under each scenario.
# 4. then comparing against the quality requirements.

# %%
print("=" * 80)
print("Calculating e2e system variables for all Environments")
print("=" * 80)

# Node path definitions
# Read path:  IB -> IR -> DB -> RN -> OB
# Write path: IB -> IW -> DB -> WN -> OB
r_pacs_srvs_path = ["IB", "IR", "DB", "RN", "OB"]
w_pacs_srvs_path = ["IB", "IW", "DB", "WN", "OB"]
r_exclusive = ["IR", "RN"]
w_exclusive = ["IW", "WN"]
shared_nodes = ["IB", "DB", "OB"]
all_unique_nodes = ["IB", "IR", "IW", "DB", "RN", "WN", "OB"]

# Tags for column naming
r_tag = "R"
w_tag = "W"
e2e_tag = "PACS"

# Variables that require double closing braces in LaTeX formatting
double_brace_tags = ["M_{buf_", "M_{act_", "d_{req_"]

# Variables that need to be integers
int_tags = ["c_", "K_", "M_{buf_", "M_{act_", "L_"]

# Variable classification
# Static (lambda-independent): allocated capacity, use FULL 5-node paths for R/W
static_regex = {
    "\\mu_": r"\\mu_\{[^}]+\}",
    "c_": r"c_\{[^}]+\}",
    "K_": r"K_\{[^}]+\}",
    "M_{buf_": r"M_\{buf_\{[^}]+\}\}",
}

# Dynamic (lambda-dependent): traffic flow, use EXCLUSIVE nodes for R/W
# Shared nodes carry combined R+W traffic that cannot be split
dynamic_regex = {
    "\\lambda_": r"\\lambda_\{[^}]+\}",
    "\\chi_": r"\\chi_\{[^}]+\}",
    "L_": r"L_\{[^}]+\}",
    "W_": r"W_\{[^}]+\}",
    "M_{act_": r"M_\{act_\{[^}]+\}\}",
    "d_{req_": r"d_\{req_\{[^}]+\}\}",
}

# epsilon: cumulative probability (full paths, zeroed when no traffic)
epsilon_regex = r"\\epsilon_\{[^}]+\}"
lambda_regex = r"\\lambda_\{[^}]+\}"

# Desired column sort order (by variable family prefix)
col_sort_order = [
    "\\lambda_",
    "\\mu_",
    "\\epsilon_",
    "\\chi_",
    "c_",
    "K_",
    "d_{req_",
    "L_",
    "W_",
    "M_{act_",
    "M_{buf_",
]

for env, exp_df in pacs_eqs.items():
    new_data = {}

    msg = f"\nCalculating e2e @ {YELLOW}'{env}'{RESET} "
    msg += f"(shape: {exp_df.shape})"
    print(msg)

    # 1. Static vars: full 5-node paths for R/W
    for var, regex in static_regex.items():
        vars_df = exp_df.filter(regex=regex)
        if vars_df.columns.empty:
            msg = f"{RED}! No columns for '{var}'{RESET}"
            print(msg)
            continue

        r_df = _filter_path(vars_df, r_pacs_srvs_path)
        w_df = _filter_path(vars_df, w_pacs_srvs_path)
        all_df = _filter_path(vars_df, all_unique_nodes)

        r_tag_col = _vtag(var, f"{r_tag}_{{{e2e_tag}}}", double_brace_tags)
        new_data[r_tag_col] = _sum_or_zero(r_df, exp_df.index, var, int_tags)

        w_tag_col = _vtag(var, f"{w_tag}_{{{e2e_tag}}}", double_brace_tags)
        new_data[w_tag_col] = _sum_or_zero(w_df, exp_df.index, var, int_tags)

        all_tag_col = _vtag(var, e2e_tag, double_brace_tags)
        new_data[all_tag_col] = _sum_or_zero(all_df, exp_df.index, var, int_tags)

        msg = f"SUM {GREEN}'{var}'{RESET} -> R({len(r_df.columns)}), "
        msg += f"W({len(w_df.columns)}), ALL({len(all_df.columns)}) [full path]"
        print(msg)

    # 2. Dynamic vars: exclusive nodes for R/W
    for var, regex in dynamic_regex.items():
        vars_df = exp_df.filter(regex=regex)
        if vars_df.columns.empty:
            msg = f"{RED}! No columns for '{var}'{RESET}"
            print(msg)
            continue

        r_df = _filter_path(vars_df, r_exclusive)
        w_df = _filter_path(vars_df, w_exclusive)
        all_df = _filter_path(vars_df, all_unique_nodes)

        r_tag_col = _vtag(var, f"{r_tag}_{{{e2e_tag}}}", double_brace_tags)
        new_data[r_tag_col] = _sum_or_zero(r_df, exp_df.index, var, int_tags)

        w_tag_col = _vtag(var, f"{w_tag}_{{{e2e_tag}}}", double_brace_tags)
        new_data[w_tag_col] = _sum_or_zero(w_df, exp_df.index, var, int_tags)

        all_tag_col = _vtag(var, e2e_tag, double_brace_tags)
        new_data[all_tag_col] = _sum_or_zero(all_df, exp_df.index, var, int_tags)

        msg = f"SUM {GREEN}'{var}'{RESET} -> R({len(r_df.columns)}), "
        msg += f"W({len(w_df.columns)}), ALL({len(all_df.columns)}) [exclusive]"
        print(msg)

    # 3. epsilon: cumulative probability over FULL paths
    # Zero out R or W path when no traffic flows through it
    eps_df = exp_df.filter(regex=epsilon_regex)
    if not eps_df.columns.empty:
        var = "\\epsilon_"

        # Detect traffic: check if lambda on exclusive nodes is zero
        lam_df = exp_df.filter(regex=lambda_regex)
        r_lam = _filter_path(lam_df, r_exclusive)
        w_lam = _filter_path(lam_df, w_exclusive)
        r_has_traffic = r_lam.sum(axis=1) > 0
        w_has_traffic = w_lam.sum(axis=1) > 0

        # Cumulative prob over full 5-node paths
        r_eps_df = _filter_path(eps_df, r_pacs_srvs_path)
        w_eps_df = _filter_path(eps_df, w_pacs_srvs_path)
        all_eps_df = _filter_path(eps_df, all_unique_nodes)

        eps_r = _cumul_prob(r_eps_df, exp_df.index)
        eps_r = eps_r.where(r_has_traffic, 0.0)

        eps_w = _cumul_prob(w_eps_df, exp_df.index)
        eps_w = eps_w.where(w_has_traffic, 0.0)

        eps_all = _cumul_prob(all_eps_df, exp_df.index)

        r_tag_col = _vtag(var, f"{r_tag}_{{{e2e_tag}}}", double_brace_tags)
        new_data[r_tag_col] = eps_r

        w_tag_col = _vtag(var, f"{w_tag}_{{{e2e_tag}}}", double_brace_tags)
        new_data[w_tag_col] = eps_w

        all_tag_col = _vtag(var, e2e_tag, double_brace_tags)
        new_data[all_tag_col] = eps_all

        msg = f"PROB {GREEN}'{var}'{RESET} -> R({len(r_eps_df.columns)}), "
        msg += f"W({len(w_eps_df.columns)}), ALL({len(all_eps_df.columns)}) "
        msg += f"[full path, cumul prob, traffic-gated]"
        print(msg)

    # Store and sort columns
    if new_data:
        new_df = pd.DataFrame(new_data)

        # Sort columns by variable family order
        sorted_cols = []
        for prefix in col_sort_order:
            matched = [c for c in new_df.columns if c.startswith(prefix)]
            sorted_cols.extend(matched)
        # Append any columns not matched (safety net)
        remaining = [c for c in new_df.columns if c not in sorted_cols]
        sorted_cols.extend(remaining)

        new_df = new_df[sorted_cols]
        pacs_eqs[env] = pd.concat([exp_df, new_df], axis=1)
        msg = f"{BLUE}df for '{env}'{RESET} shape: {pacs_eqs[env].shape}"
        print(msg)

print("\n" + "=" * 80)
print("DONE! PAQS E-QS dataframes created for all environments.")
print("=" * 80)

# %%
print("=" * 80)
print("Creating PACS-level dimensional variable specs for PyDASA")
print("=" * 80)

# Use IB node as template - all nodes share the same variable structure
ref_node = "IB"
ref_vars = node_vars[ref_node]

# 3 PACS levels per environment
pacs_fns = {
    "R_{PACS}": {
        "name": "Read Path PACS",
        "idx": 0
    },
    "W_{PACS}": {
        "name": "Write Path PACS",
        "idx": 1
    },
    "PACS": {
        "name": "Full PACS System",
        "idx": 2
    },
}

# Build the specs dict: env -> level -> vars
pacs_da_specs = {}

for env, exp_df in pacs_eqs.items():
    env_specs = {}

    msg = f"\n- Creating PACS specs @ {YELLOW}'[{env}]'{RESET} "
    msg += f"(shape: {exp_df.shape})"
    print(msg)

    for level, artf_specs in pacs_fns.items():
        level_vars = {}

        msg = f"\tProcessing functionality {BLUE}{BOLD}'[{level}]'{RESET}"
        print(msg)

        e_vars = len(ref_vars)
        n_vars = 0

        for idx, (ref_sym, ref_var) in enumerate(ref_vars.items()):
            # Extract the family prefix by removing the node suffix
            # e.g. "\\lambda_{IB}" -> "\\lambda_", "M_{buf_{IB}}" -> "M_{buf_"
            family = ref_sym.replace(f"{{{ref_node}}}", "").rstrip("}")

            # if family == "d_{req_":
            #     family = "d_"

            # "R_PACS" -> "R_{PACS}", "PACS" stays "PACS"
            if "_" in level:
                parts = level.split("_", 1)
                suffix = f"{parts[0]}_{{{parts[1]}}}"
            else:
                suffix = level

            sym = _vtag(family, suffix, double_brace_tags)

            # Build the PACS symbol using _vtag
            sym = _vtag(family, level, double_brace_tags)

            # Build alias from symbol
            alias = sym.replace("\\", "").replace("{", "").replace("}", "_")
            alias = alias.strip("_")

            # Copy metadata from reference variable
            params = {
                "_sym": sym,
                "_fwk": ref_var.fwk,
                "_alias": alias,
                "_idx": idx,
                "_name": f"{level} {ref_var.name}",
                "description": f"{ref_var.name} for {artf_specs['name']}",
                "_cat": ref_var.cat,
                "relevant": ref_var.relevant,
                "_units": ref_var.units,
                "_std_units": ref_var.std_units,
                "_data": [],
            }

            # Only add dims if defined (epsilon has no dims)
            if ref_var.dims is not None:
                params["_dims"] = ref_var.dims

            level_vars[sym] = params

            msg = f"\t\tVariable {GREEN}{BOLD}'{sym}'{RESET} spec created"
            msg += f" with alias {GREEN}{BOLD}'{alias}'{RESET}"
            print(msg)
            n_vars += 1

        # count the relevant variables in level_vars
        n_relevant = sum(1 for var in level_vars.values() if var["relevant"])

        msg = f"\t✓ {n_vars}/{e_vars} "
        msg += f"variables created for {BLUE}{BOLD}'[{level}]'{RESET} "
        msg += f"with {YELLOW}{BOLD}{n_relevant}/{n_vars}{RESET} relevant.\n"
        print(msg)

        env_specs[level] = {
            "name": artf_specs["name"],
            "idx": artf_specs["idx"],
            "vars": level_vars,
        }

    pacs_da_specs[env] = env_specs

print("DONE!!!")

# %% [markdown]
# ## 12. PACS Architectural design with DASA 

# %% [markdown]
# ### Define Dimensional Variables

# %%
# creating the variables for each environment and artifact combination
print("=" * 80)
print("Creating PyDASA Variables for each PACS' environment and artifact")
print("=" * 80)

pacs_vars = {}

# iterate over enviromental conditions
for env, exp_df in pacs_eqs.items():

    # initialize the dict for this environment
    pacs_vars[env] = {}

    artf_specs = pacs_da_specs.get(env, {})
    msg = f"\nProcessing environment {YELLOW}'{env}'{RESET} "
    msg += f"with {BOLD}{BLUE}{len(artf_specs)}{RESET} artifacts"
    print(msg)

    # iterate over artifacts in the environment (R_PACS, W_PACS, PACS)
    for artf, specs in artf_specs.items():

        _specs = copy.deepcopy(specs.get("vars", {}))

        # create variables for the artifact based on the specifications
        _vars = {
            sym: Variable(**params) for sym, params in _specs.items() if isinstance(params, dict) and "_sym" in params
        }

        # store the variables in the appropriate place
        pacs_vars[env].update({artf: _vars})
        msg = f"\t{BOLD}{GREEN}{len(_specs)} Variables{RESET} "
        msg += f"created for configuring {BLUE}{BOLD}'{artf}'{RESET} "
        print(msg)

print("DONE!!!")

# %% [markdown]
# ### Adding data to the Variables

# %%
# assigning the data to the variables
print("=" * 80)
print("Assigning data to PyDASA variables (per environment and artifact)")
print("=" * 80)

for env, exp_df in pacs_eqs.items():
    # exp_df = pacs_eqs[env]
    artf_specs = pacs_vars.get(env, {})

    msg = f"\nProcessing environment {YELLOW}'{env}'{RESET} "
    msg += f"with {BOLD}{BLUE}{len(artf_specs)}{RESET} artifacts"
    print(msg)
    print(artf_specs.keys())

    for artf, specs in artf_specs.items():

        msg = f"\tProcessing artifact {BLUE}{BOLD}'{artf}'{RESET} "
        print(msg)

        for sym, var in specs.items():
            if sym in exp_df.columns:
                data = exp_df[sym].values
                var.data = data
                pacs_vars[env][artf][sym] = var
                msg = f"\t\tAssigned data: n_exp={len(data)} To variable "
                msg += f"{BOLD}{GREEN}'{sym}'{RESET}"
                print(msg)
            else:
                msg = f"\t\t{BOLD}{RED}⚠ Warning:{RESET} Variable data for"
                msg += f"{BOLD}{GREEN}'{sym}'{RESET} not found!!!"
                print(msg)

print("DONE!!!")

# %% [markdown]
# ### Create Dimensional Analysis Engine

# %%
# creating the DASA engines for each environment and artifact combination
print("=" * 80)
print("Creating DASA Engines for each PACS' Environment and Artifact")
print("=" * 80)

pacs_engines = {}

# iterate over enviromental conditions
for env, exp_df in pacs_eqs.items():
    pacs_engines[env] = {}
    art_specs = pacs_vars[env]

    msg = f"\nProcessing environment {YELLOW}'{env}'{RESET} "
    msg += f"with {BOLD}{BLUE}{len(artf_specs)}{RESET} artifacts"
    print(msg)


    # creatr DASA engines for each artifact in the environment
    for idx, (artf, specs) in enumerate(art_specs.items()):

        msg = f"\tCreating DASA engine for {BLUE}{BOLD}'{artf}'{RESET}..."
        print(msg)


        # create the DASA engine for the artifact
        eng = AnalysisEngine(
            _idx=idx,
            _fwk="CUSTOM",
            _schema=schema,
            _name=f"DA Engine {idx}: {artf} @ {env}",
            description=f"Dimensional analysis for artifact {artf} at environment {env}",
        )

        eng.variables = copy.deepcopy(specs)
        pacs_engines[env].update({artf: eng})
        msg = f"\t✓ Engine created for {BLUE}{BOLD}'{artf}'{RESET} with "
        msg += f"{GREEN}{BOLD}{len(specs.keys())} Variables{RESET}."
        print(msg)

print("DONE!!!")

# %% [markdown]
# #### Execute Dimensional Analysis

# %%
# creating the DA Coefficients for each environment and artifact combination
print("=" * 80)
print("Computing PACS Coefficients for each Environment and Artifact")
print("=" * 80)

pacs_coeffs = {}

# iterate over enviromental conditions
for env, exp_df in pacs_eqs.items():
    pacs_coeffs[env] = {}
    artf_engines = pacs_engines[env]

    msg = f"\nAnalyzing environment {YELLOW}'{env}'{RESET} "
    msg += f"with {BOLD}{BLUE}{len(artf_engines)}{RESET} Engines."
    print(msg)

    # create DA coefficients for each artifact in the environment
    for art, eng in artf_engines.items():

        msg = f"\tRunning Analysis for {BLUE}{BOLD}'{artf}'{RESET}..."
        print(msg)

        # run the dimensional analysis
        coeffs = eng.run_analysis()
        # store the coefficients in the appropriate place
        pacs_coeffs[env][art] = coeffs

        msg = f"\t✓ Engine {BLUE}{BOLD}'{artf}'{RESET} computed "
        msg += f"{GREEN}{BOLD}{len(coeffs.keys())} Coefficients{RESET}."
        print(msg)

print("DONE!!!")

# %% [markdown]
# #### Derive Key Dimensionless Coefficients

# %%
# derive final coefficients for each environment and artifact combination
print("=" * 80)
print("Deriving final PACS Coefficients for each Environment and Artifact")
print("=" * 80)

# iterate over enviromental conditions
for env, exp_df in pacs_eqs.items():
    artf_engines = pacs_engines[env]
    # art_specs = pacs_vars[env]

    msg = f"\nDeriving Coefficients for {YELLOW}'{env}'{RESET} "
    msg += f"with {BOLD}{BLUE}{len(artf_engines)}{RESET} Engines."
    print(msg)

    # creatr DASA engines for each artifact in the environment
    for artf, eng in artf_engines.items():

        pi_keys = list(eng.coefficients.keys())

        msg = f"\tArtifact {BLUE}{BOLD}'{artf}'{RESET} with "
        msg += f"{GREEN}{BOLD}{len(pi_keys)} Coefficients{RESET} initially..."
        print(msg)
        
        # theta_j = Pi_0 = L_j / K_j: Queue occupancy ratio
        delta_coeff = eng.derive_coefficient(
            expr=f"{pi_keys[0]}",
            symbol=f"\\theta_{{{artf}}}",
            name=f"Occupancy Coefficient ({artf})",
            description=f"theta_{artf} = L_{artf}/K_{artf} - Queue occupancy ratio (0=empty, 1=full)",
            idx=-1
        )

        # sigma_j = Pi_4 = W_j * lambda_j / L_j: Service stall/blocking indicator
        sigma_coeff = eng.derive_coefficient(
            expr=f"{pi_keys[4]}",
            symbol=f"\\sigma_{{{artf}}}",
            name=f"Stall Coefficient ({artf})",
            description=f"sigma_{artf} = W_{artf} * lambda_{artf}/L_{artf} - Service blocking indicator",
            idx=-1
        )

        # eta_j = Pi_1^-1 * Pi_2 * Pi_3^-1 = chi_j * K_j / (mu_j * c_j): Resource utilisation effectiveness
        eta_coeff = eng.derive_coefficient(
            expr=f"{pi_keys[1]}**(-1) * {pi_keys[2]} * {pi_keys[3]}**(-1)",
            symbol=f"\\eta_{{{artf}}}",
            name=f"Effective-Yield Coefficient ({artf})",
            description=f"eta_{artf} = chi_{artf} * K_{artf}/(mu_{artf} * c_{artf}) - Resource utilisation effectiveness",
            idx=-1
        )

        # phi_j = Pi_5 * Pi_6^-1 = M_act,j / B_MAX,j  - Data usage metric
        phi_coeff = eng.derive_coefficient(
            expr=f"{pi_keys[5]} * {pi_keys[6]}**(-1)",
            symbol=f"\\phi_{{{artf}}}",
            name=f"Memory-Usage Coefficient ({artf})",
            description=f"phi_{artf} = Mact_{artf}/Mbuf_{artf} - Data density metric",
            idx=-1
        )

        # Store derived coefficients back under artf-specific keys
        pacs_coeffs[env][artf][f"\\delta_{artf}"] = delta_coeff
        pacs_coeffs[env][artf][f"\\sigma_{artf}"] = sigma_coeff
        pacs_coeffs[env][artf][f"\\eta_{artf}"] = eta_coeff
        pacs_coeffs[env][artf][f"\\phi_{artf}"] = phi_coeff

        msg = f"\tDerived Coefficients for {BLUE}{BOLD}'{artf}'{RESET} "
        msg += f"{GREEN}{BOLD}{len(eng.coefficients) - len(pi_keys)} Coefficients{RESET}."
        print(msg)

print("DONE!!!")

# %% [markdown]
# ### Simulate System Wide Data
# 
# Here we execute the Monte Carlo simulations across the defined design space for each node and scenario. This generates the necessary data to analyze the system's performance with dimiensionless coefficients and to plot the Yoly diagrams.

# %%
print("=" * 80)
print("Creating Monte Carlo Simulations PACS for each Environment and Artifact")
print("=" * 80)

# create Monte Carlo simulations for each environment and artifact combination
pacs_montecarlos = {}

# iterate over enviromental conditions
for env, exp_df in pacs_eqs.items():
    pacs_montecarlos[env] = {}
    artf_engines = pacs_engines[env]
    n_data = len(exp_df)

    msg = f"\nCreating Monte Carlo Simulations for {YELLOW}'{env}'{RESET} "
    msg += f"with {BOLD}{BLUE}{len(artf_engines)}{RESET} Engines."
    print(msg)

    # create DA coefficients for each artifact in the environment
    for idx, (artf, eng) in enumerate(artf_engines.items()):

        msg = f"\tSimulation for {BLUE}{BOLD}'{artf}'{RESET} with "
        msg += f"{BOLD}{n_data}{RESET} experiments..."
        print(msg)

        # Create Monte Carlo simulation for this artifact
        monca = MonteCarloSimulation(
            _idx=idx,
            _variables=eng.variables,
            _schema=schema,
            _coefficients=eng.coefficients,
            _fwk="CUSTOM",
            _name=f"{artf} Grid-Based Artifact Analysis @ {env}",
            _cat="DATA",  # category to read the variable data
            _experiments=n_data,
        )
        pacs_montecarlos[env][artf] = monca

        msg = f"\tMonte Carlo simulation for {BLUE}{BOLD}'{artf}'{RESET} "
        msg += f"with {GREEN}{BOLD}{len(eng.coefficients)} Coefficients{RESET} "
        msg += f"and {BOLD}{n_data}{RESET} experiments created."
        print(msg)

print("DONE!!!")

# %%
print("=" * 80)
print(f"Reporting Monte Carlo Simulations for all Environments and Artifacts")
print("=" * 80)

# Collect data for tabulate
monca_data = []
for env, artf_montes in pacs_montecarlos.items():
    for art, mc in artf_montes.items():
        monca_data.append({
            "Artifact": art,
            "Environment": env,
            "Simulation Name": mc.name,
            "Experiments": mc.experiments,
            "Coefficients": len(mc.coefficients)
        })

# Create bold headers
bold_headers = [f"{BOLD}{header}{RESET}" for header in monca_data[0].keys()]

# Colorize first column (Artifact) in blue
mc_data_colored = []
for row in monca_data:
    colored_row = {}
    for i, (key, value) in enumerate(row.items()):
        if i == 0:  # First column (Artifact)
            colored_row[bold_headers[i]] = f"{BLUE}{value}{RESET}"
        elif i == 1:  # Second column (Environment)
            colored_row[bold_headers[i]] = f"{YELLOW}{value}{RESET}"
        else:
            colored_row[bold_headers[i]] = value
    mc_data_colored.append(colored_row)

print(tabulate(mc_data_colored, headers="keys", tablefmt="grid"))

# %%
# Run Monte Carlo simulation for each node
print("=" * 80)
print(f"Executing Monte Carlo Simulations for all Environments and Artifacts")
print("=" * 80)

# iterate over enviromental conditions
for env, artf_montes in pacs_montecarlos.items():
    msg = f"Running Monte Carlo @ {YELLOW}{BOLD}'{env}'{RESET} environment."
    print(msg)

    # iterate over artifacts in the environment
    for art, monca in artf_montes.items():
        # if configured with experiments, run the Monte Carlo simulation
        if monca.experiments > 0:
            art = f"{BLUE}{BOLD}[{art}]{RESET}"
            _msg = f"Running Monte Carlo for artifact: {art} @ "
            _msg += f"{YELLOW}'{env}'{RESET} with {monca.experiments} experiments..."
            print(_msg)
            monca.run_simulation(iters=monca.experiments)
            _msg = f"Completed Monte Carlo for Simulation with {GREEN}{BOLD}{len(monca.simulations)}{RESET} coefficient sets."
            print(_msg)
        else:
            msg = f"{RED}⚠ No data available for artifact {BLUE}{BOLD}'{art}'{RESET} @ {YELLOW}'{env}'{RESET} - skipping Monte Carlo simulation"
            print(msg)

print("DONE!!!")

# %%
# post-process Monte Carlo simulation results to clean up coefficient statistics
# zero traffic scenarios create inf values, must be set to nan for better handling in PyDASA
print("=" * 80)
print("Cleaning an Extracting and summarizing Monte Carlo simulation results")
print("=" * 80)

# Clean up results for scenarios with λ=0
for env, artf_montes in pacs_montecarlos.items():
    for art, monca in artf_montes.items():
        # Replace inf with nan in results
        for sim in monca.simulations.values():
            if hasattr(sim, "_results"):
                sim._results = np.where(np.isinf(sim._results),
                                        np.nan,
                                        sim._results)

print("DONE!!!")

# %%
# Extract coefficient simulation results for each Environment and Artifact
print("=" * 80)
print("Extracting coefficient results for each Environment and Artifact")
print("=" * 80)

# Initialize the results dictionary based on environment + artifact structure
dasa_results = {}

# Clean up results and extract coefficients for scenarios with λ=0
for env, artf_montes in pacs_montecarlos.items():
    # Initialize environment dictionary if not exists
    if env not in dasa_results:
        dasa_results[env] = {}

    print(f"\n{YELLOW}Processing Environment: '{env}'{RESET}")

    for art, monca in artf_montes.items():
        print(f"{BLUE}{BOLD}Artifact: '{art}'{RESET}")

        # Check if simulations are available
        if not hasattr(monca, "simulations") or len(monca.simulations) == 0:
            msg = f"{RED}⚠ No simulations available for artifact {BLUE}{BOLD}'{art}'{RESET} @ {YELLOW}'{env}'{RESET} - skipping Monte Carlo simulation"
            print(msg)
            continue

        # Get all simulation keys and filter derived coefficients
        all_keys = list(monca.simulations.keys())
        derived_keys = [k for k in all_keys if not k.startswith("\\Pi_")]

        msg = f"{GREEN}Found {len(derived_keys)}{RESET} coefficients for "
        msg += f"{BLUE}{BOLD}'{art}'{RESET} artifact @ {YELLOW}'{env}'{RESET}"
        print(msg)

        # Initialize artifact coefficients dictionary
        art_coeffs = {}
        extracted_count = 0
        error_count = 0

        # Extract derived coefficient results from Monte Carlo simulations
        for coeff_key in derived_keys:
            try:
                coeff_sim = monca.get_simulation(coeff_key)
                coeff_results = coeff_sim.extract_results()
                if coeff_key in coeff_results:
                    art_coeffs[coeff_key] = coeff_results[coeff_key]
                    extracted_count += 1
                    msg = f"✓ Extracted coefficient {BOLD}{GREEN}{coeff_key}{RESET}"
                    print(msg)
            except Exception as e:
                msg = f"{RED}⚠ Error extracting coefficient{RESET} '"
                msg += f"{coeff_key}' for artifact {BLUE}{BOLD}'{art}'{RESET}"
                msg += f" @ {YELLOW}'{env}'{RESET}: {e}"
                print(msg)
                error_count += 1

        # Get system variables (λ, μ, c, K, χ) from architecture experiments
        if not pacs_eqs[env].filter(regex=f"{art}.*").empty:
            art_df = pacs_eqs[env].filter(regex=f"{art}.*")

            # 1. Extract lambda (arrival rate)
            try:
                idx = find_key_idx(art_df.columns, f"\\lambda_{{{art}}}")
                lambda_key = art_df.columns.tolist()[idx]
                art_coeffs[lambda_key] = art_df[lambda_key].values
                print(f"✓ Extracted {GREEN}{lambda_key}{RESET}")
            except KeyError:
                lk = f"\\lambda_{{{art}}}"
                msg = f"{RED}⚠ {lk} experiments not found for artifact "
                msg += f"{BLUE}{BOLD}'{art}'{RESET} @ {YELLOW}'{env}'{RESET}{RESET}"
                print(msg)

            # 2. Extract mu (service rate)
            try:
                idx = find_key_idx(art_df.columns, f"\\mu_{{{art}}}")
                mu_key = art_df.columns.tolist()[idx]
                art_coeffs[mu_key] = art_df[mu_key].values
                print(f"✓ Extracted {GREEN}{mu_key}{RESET}")
            except KeyError:
                mk = f"\\mu_{{{art}}}"
                msg = f"{RED}⚠ {mk} experiments not found for artifact "
                msg += f"{BLUE}{BOLD}'{art}'{RESET} @ {YELLOW}'{env}'{RESET}{RESET}"
                print(msg)

            # 3. Extract c (number of servers)
            try:
                idx = find_key_idx(art_df.columns, f"c_{{{art}}}")
                c_key = art_df.columns.tolist()[idx]
                art_coeffs[c_key] = art_df[c_key].values
                print(f"✓ Extracted {GREEN}{c_key}{RESET}")
            except KeyError:
                ck = f"c_{{{art}}}"
                msg = f"{RED}⚠ {ck} experiments not found for artifact "
                msg += f"{BLUE}{BOLD}'{art}'{RESET} @ {YELLOW}'{env}'{RESET}{RESET}"
                print(msg)

            # 4. Extract K (system capacity)
            try:
                idx = find_key_idx(art_df.columns, f"K_{{{art}}}")
                K_key = art_df.columns.tolist()[idx]
                art_coeffs[K_key] = art_df[K_key].values
                print(f"✓ Extracted {GREEN}{K_key}{RESET}")
            except KeyError:
                Kk = f"K_{{{art}}}"
                msg = f"{RED}⚠ {Kk} experiments not found for artifact "
                msg += f"{BLUE}{BOLD}'{art}'{RESET} @ {YELLOW}'{env}'{RESET}{RESET}"
                print(msg)

            # 5. Extract chi (utilization factor)
            try:
                idx = find_key_idx(art_df.columns, f"\\chi_{{{art}}}")
                chi_key = art_df.columns.tolist()[idx]
                art_coeffs[chi_key] = art_df[chi_key].values
                print(f"✓ Extracted {GREEN}{chi_key}{RESET}")
            except KeyError:
                chik = f"\\chi_{{{art}}}"
                msg = f"{RED}⚠ {chik} experiments not found for artifact "
                msg += f"{BLUE}{BOLD}'{art}'{RESET} @ {YELLOW}'{env}'{RESET}{RESET}"
                print(msg)

        # Store results in the properly structured dasa_results dictionary
        dasa_results[env][art] = art_coeffs

        # Summary message for this artifact
        msg = f"✓ Completed extraction for artifact {BLUE}{BOLD}'{art}'{RESET}"
        msg += f" @ {YELLOW}'{env}'{RESET} - {extracted_count} coefficients "
        msg += f"extracted, {error_count} errors"
        print(msg)

    # Summary for environment
    env_artifacts_count = len(dasa_results[env])
    msg = f"✓ Environment {YELLOW}'{env}'{RESET} completed - {env_artifacts_count} artifacts processed"
    print(msg)
    
print("DONE!!!")

# %%
print("=" * 80)
print("Statistical Summary of DASA Coefficients by Environment and Artifact")
print("=" * 80)

# Iterate through environments and artifacts in dasa_results
for env in dasa_results.keys():
    print(f"\n{BOLD}{YELLOW}[ENVIRONMENT: {env}]{RESET}")
    print("=" * 60)

    env_artifacts = dasa_results[env]

    for art in env_artifacts.keys():
        artf_specs = env_artifacts[art]

        print(f"\n{BOLD}{BLUE}[ARTIFACT: {art}]{RESET}")

        # Collect statistics data for tabulate
        stats_data = []
        for key in artf_specs.keys():
            data = np.array(artf_specs[key])

            if len(data) == 0:
                # Clean up display name by removing artifact-specific patterns
                display_name = key.replace(f"_{{{art}}}", "").replace(
                    f"_{art}", "").replace("\\", "")
                stats_data.append({
                    "Item": display_name,
                    "Samples": "(empty)",
                    "Mean": "---",
                    "Std Dev": "---",
                    "Min": "---",
                    "Max": "---"
                })
            else:
                n_samples = len(data)
                mean_val = np.mean(data)
                std_val = np.std(data)
                min_val = np.min(data)
                max_val = np.max(data)

                # Clean up display name by removing artifact-specific patterns
                display_name = key.replace(f"_{{{art}}}", "").replace(
                    f"_{art}", "").replace("\\", "")

                stats_data.append({
                    "Item": display_name,
                    "Samples": n_samples,
                    "Mean": f"{mean_val:.4e}",
                    "Std Dev": f"{std_val:.4e}",
                    "Min": f"{min_val:.4e}",
                    "Max": f"{max_val:.4e}"
                })

        if stats_data:  # Only create table if there's data
            # Create bold headers
            bold_headers = [
                f"{BOLD}{header}{RESET}" for header in stats_data[0].keys()]

            # Colorize first column (Item) in blue
            stats_data_colored = []
            for row in stats_data:
                colored_row = {}
                for i, (key, value) in enumerate(row.items()):
                    if i == 0:  # First column (Item)
                        colored_row[bold_headers[i]] = f"{BLUE}{value}{RESET}"
                    else:
                        colored_row[bold_headers[i]] = value
                stats_data_colored.append(colored_row)

            print(tabulate(stats_data_colored, headers="keys", tablefmt="grid"))
        else:
            print(
                f"    {RED}⚠ No coefficient data available for artifact '{art}'{RESET}")

    # Summary for this environment
    env_artifact_count = len(env_artifacts)
    print(f"\n{GREEN}✓ Environment '{env}' complete: {env_artifact_count} artifacts analyzed{RESET}")

print("\n" + "=" * 80)
# Overall summary
total_environments = len(dasa_results)
total_artifacts = sum(len(artifacts) for artifacts in dasa_results.values())
print(f"✓ ANALYSIS COMPLETE: {total_environments} environments, {total_artifacts} artifacts analyzed")
print("=" * 80)

# %%
# add the 4 coefficient results for the environments into the experiments
print("=" * 80)
print("Adding DASA coefficients to architectural experiment for all Environment and Artifact")
print("=" * 80)

# iterate through environments
for env, results in dasa_results.items():
    exp_df = pacs_eqs[env]
    msg = f"\nProcessing environment {YELLOW}'{env}'{RESET} "
    msg += f"with experiment DataFrame shape {exp_df.shape}."
    print(msg)
    new_cols = {}  # Collect all new columns

    # iterate through artifacts
    for art, coeffs in results.items():
        msg = f"Processing artifact {BLUE}{BOLD}'{art}'{RESET} "
        msg += f"with {len(coeffs)} coefficients."
        print(msg)

        # iterate through coefficients
        for coeff, val in coeffs.items():
            # add coefficient to experimentws if not in the df
            if not coeff in exp_df.columns and coeff in coeffs.keys():
                new_cols[coeff] = val
                msg = f"✓ Coefficient {GREEN}{BOLD}'{coeff}'{RESET} added to experiment DataFrame"
                msg += f"for artifact {BLUE}{BOLD}'{art}'{RESET} "
                msg += f"@ {YELLOW}'{env}'{RESET}"
                print(msg)

    # Concatenate all new columns, dropping any column with the same names
    if new_cols:
        exp_df = exp_df.drop(columns=list(new_cols.keys()), errors="ignore")
        new_cols_df = pd.DataFrame(new_cols, index=exp_df.index)
        pacs_eqs[env] = pd.concat([exp_df, new_cols_df], axis=1)

print("DONE!!!")

# %% [markdown]
# ## 13. Plot Architectural Yoly Diagram

# %% [markdown]
# ### E-QS Yoly Diagram data formating
# 
#  Yoly diagram display for the Edge to Edge (E2E) performance in different environment cases (from full read to full write conditions)

# %%
# final summary of the architectural experiments with e2e coefficients
print("=" * 80)
print("Final Summary of Architectural Experiments with e2e Coefficients")
print("=" * 80)

sys_coeffs_re = r"\\(theta|sigma|eta|phi)_.*PACS"
sys_vars_re = r"\\(lambda|mu|chi)_.*PACS|c_.*PACS|K_.*PACS|M_.*PACS|d_.*PACS"

# PACS summary dict
pacs_summary = {}

# Collect data for tabulate
summary_data = []

for env, exp_df in pacs_eqs.items():
    coeff_cols = exp_df.filter(regex=sys_coeffs_re).columns
    var_cols = exp_df.filter(regex=sys_vars_re).columns

    td = {
        "Environment": env,
        "Total Experiments": len(exp_df),
        "e2e Coefficients": len(coeff_cols),
        "e2e System Variables": len(var_cols)
    }
    summary_data.append(td)
    
    pacs_cols = var_cols.tolist() + coeff_cols.tolist()
    pacs_summary[env] = pd.DataFrame(exp_df[pacs_cols])

# Create bold headers
bold_headers = [f"{BOLD}{header}{RESET}" for header in summary_data[0].keys()]
# Colorize first column (Environment) in yellow
summary_data_colored = []
for row in summary_data:
    colored_row = {}
    for i, (key, value) in enumerate(row.items()):
        if i == 0:  # First column (Environment)
            colored_row[bold_headers[i]] = f"{YELLOW}{value}{RESET}"
        else:
            colored_row[bold_headers[i]] = value
    summary_data_colored.append(colored_row)

# print the summary table
print(tabulate(summary_data_colored, headers="keys", tablefmt="grid"))

# %%
# extract the data from df
print("=" * 80)
print("Extracting PACS data for each Environment into a structured dictionary")
print("=" * 80)

pacs_plot_data = {}

for env, df in pacs_summary.items():
    env_data = df.to_dict(orient="list")
    pacs_plot_data[env] = env_data

print("DONE!!!")

# %%
# Create 7 separate 3D yoly diagrams (one per component/service)
print("=" * 80)
print("Environment 3D Yoly Diagrams (3×3 Node Grid)")
print("=" * 80)

# Extract node names and display titles
node_disp_titles = {}
if pacs_eqs is not None:
    for i, node in enumerate(pacs_eqs.keys()):
        node_spec = art_specs.get(node, {})
        name = env_conds.get('_labels', [])
        node_disp_titles[node] = name[i]

# %% [markdown]
# ### Latency Decomposition: Archival vs. Retrieval
# For each scenario, we decompose the end-to-end latency into its archival and retrieval components, allowing us to understand the contribution of each path to the overall performance.

# %%
print("=" * 80)
print("Plotting 3D Yoly Diagrams for PACS Architecture across Environments")
print("=" * 80)

img_name = "pacs_envs_yoly_3d"
title = "PACS Architecture behaviour across Environments - 3D Yoly Diagrams"

pacs_paths = {
    "Read":    "R_{PACS}",
    "Write":   "W_{PACS}",
    "Overall": "PACS",
}

img = plot_yoly_arts_behaviour(title,
                               pacs_plot_data,
                               node_disp_titles,
                               img_name,
                               f_path,
                               subscript="PACS",
                               paths=pacs_paths,
                               verbose=False)
img.show()

# %%
print("=" * 80)
print("Plotting Yoly Charts for PACS Architecture across Environments")
print("=" * 80)

img_name = "pacs_envs_yoly_2d"
title = "PACS Architecture behaviour across Environments - 2D Yoly Charts"

img = plot_yoly_arts_charts(title,
                            pacs_plot_data,
                            node_disp_titles,
                            img_name,
                            f_path,
                            subscript="PACS",
                            paths=pacs_paths,
                            verbose=False)

img.show()

# %% [markdown]
# ### Bottleneck Analysis (100W Scenario)
# 
# Full write scenario (100W) is expected to stress the archival path heavily, likely revealing bottlenecks in the IWS and DB nodes. We will analyze the per-node latencies and resource utilizations to identify which components are limiting performance under this write-heavy load.

# %%
# plot the general behaviour for Archival + Retrieval on each enviroment
coeffs_re = r"(\\(lambda|mu|chi|rho|theta|sigma|eta|phi)|(c|K|M_{buf}|M_{act}))_|d_{req}{?PACS}?}"
bottleneck_label = "100W"
coeff_df = pacs_eqs[bottleneck_label].filter(regex=coeffs_re)

pacs_paths = {
    "Read":    "R_{PACS}",
    "Write":   "W_{PACS}",
    "Overall": "PACS",
}

# %%
print("=" * 80)
print("Bottleneck PACS Yoly Chart")
print("=" * 80)

# Extract node names and display titles
test_results = coeff_df.to_dict(orient="list")
disp_lbls = {}
if coeff_df is not None:
    for node in coeff_df.columns.tolist():
        disp_lbls[node] = node

img_name = "pacs_e2e_yoly_2d"

img = plot_yoly_chart("PACS Average E2E Yoly Chart: 100W",
                      test_results,
                      disp_lbls,
                      img_name,
                      f_path,
                      verbose=True,
                      paths=pacs_paths,
                      logscale=False,)
img.show()

# %% [markdown]
# ## 10. Work Summary
# 
# This notebook demonstrated PyDASA's dimensional analysis workflows applied to queueing theory and software service analysis using the M/M/c/K queue model:
# 
# 1. **Custom Dimensional Framework:** Created a specialized framework with three fundamental dimensions (T, S, D) for software service analysis - Time, Structure, and Data.
# 2. **Variable Definition:** Defined 10 queue system variables including arrival rate ($\lambda$), service rate ($\mu$), queue capacity ($K$), servers ($c$), and error rate ($\text{err}$).
# 3. **Dimensional Analysis:** Automatically generated 6 dimensionless $\Pi$-groups using Buckingham $\Pi$-theorem with custom dimensions, and semi-automated symbolic simplification derive 4 more coefficients.
# 4. **Derived Coefficient:** Created from the original 6 $\Pi$-groups:
#    - **Occupancy:** $\theta = L/K$ for the Queue capacity utilization.
#    - **Stall:** $\sigma = W \cdot \lambda / L$ for the Service blocking indicator.
#    - **Effective-Yeild:** $\eta = \chi \cdot K / (\mu \cdot c)$ for the Resource utilization effectiveness.
#    - **Memory-Use:** $\phi = M_{\text{act}} / M_{\text{buf}}$ for the memory usage metric.
# 5. **Sensitivity Analysis:** Symbolic analysis showing which variables most influence each dimensionless coefficient.
# 6. **Grid-Based Monte Carlo:** Generated structured data points systematically varying:
#    1. **Variables:**
#       - Queue capacity $(K)$: [5, 10, 20] → 3 values
#       - Service rate $(\mu)$: [200, 500, 1000] req/s → 3 values  
#       - Server count $(c)$: [1, 2, 4] → 3 values
#       - Request data density $(\rho_{\text{req}})$ based on the queue-memory ratio formula $B = \rho_{req} \cdot L$ for simulation consistency.
#       - Total Configurations: 3 × 3 × 3 = _**27 configurations**_
#    2. **Constants:**
#      - Component error rate $\text{err} = 1.0\%$
#      - Max Buffer Memory $M_{\text{buf}} = 2.56 \times 10^8$ bits
# 7. **Visualization:** Created comprehensive visualizations including:
#    - **2×2 histogram grid:** Distribution plots for all four derived coefficients ($\theta, \sigma, \eta, \phi$) with LaTeX-formatted symbols and mean lines.
#    - **Comprehensive Yoly diagram (2×2 grid):**
#      - 3D scatter plot ($\theta$ vs $\sigma$ vs $\eta$) with server-based color coding and $K$-value labels.
#      - Three 2D projection plots showing relationships between coefficient pairs:
#        - $\theta$ vs $\sigma$ (Occupancy vs Stall)
#        - $\theta$ vs $\eta$ (Occupancy vs Effective-Yeild)
#        - $\sigma$ vs $\eta$ (Stall vs Effective-Yeild)
# 
# ### Key PyDASA Workflows
# 
# ```python
# # 1. Custom Schema Definition
# schema = Schema(_fwk="CUSTOM", _fdu_lt=fdu_list, ...)
# schema._setup_fdus()
# 
# # 2. Dimensional Analysis
# engine = AnalysisEngine(_fwk="CUSTOM", _schema=schema, ...)
# engine.run_analysis()
# 
# # 3. Derive Coefficients
# delta_coeff = engine.derive_coefficient(
#     expr=f"{pi_keys[0]}", 
#     symbol="\\theta",
#     name="Occupancy Coefficient", ...)
# 
# # 4. Sensitivity Analysis
# sensitivity = SensitivityAnalysis(_cat="SYM", ...)
# sensitivity_results = sensitivity.analyze_symbolic(val_type="mean")
# 
# # 5. Monte Carlo Simulation
# mc_grid = MonteCarloSimulation(
#     _cat="DATA",  # Use actual data from grid search
#     _experiments=len(data_df), ...)
# mc_grid.run_simulation(iters=len(data_df))
# ```
# 
# ### Features Demonstrated
# 
# ✓ Custom dimensional frameworks beyond physical dimensions  
# ✓ Software/service system dimensional analysis  
# ✓ Queueing theory (M/M/c/K) integration with PyDASA  
# ✓ Grid-based systematic data generation with 27 configurations  
# ✓ Coefficient derivation with symbolic expressions  
# ✓ Symbolic sensitivity analysis  
# ✓ 3D and 2D visualization with matplotlib  

# %% [markdown]
# ## 11. Insights
# 
# ### Coefficients Vs. Metrics
# 
# Traditional queueing theory uses **utilization** $\rho = \lambda/(\mu \cdot c)$ to measure server busy-time. This is a dimensional metric that doesn't account for capacity limits, error rates, or temporal inefficiencies.
# 
# Our dimensionless coefficients provide orthogonal views for:
# 
# - **Occupancy** $\theta = L/K$: Instantaneous queue fullness (spatial measure).
# - **Stall** $\sigma = W \cdot \lambda / L$: Delay-throughput coupling (temporal inefficiency).
# - **Effective-Yield** $\eta = \chi \cdot K / (\mu \cdot c)$: Error-aware resource effectiveness using $\chi = (1-\text{err})\lambda$.
# - **Memory-Use** $\phi = M_{\text{act}} / M_{\text{buf}}$: Data dimension saturation.
# 
# Unlike $\rho$, which only tracks server state, these coefficients capture system-wide behavior across Time, Structure, and Data dimensions. Two systems with identical $\rho = 0.6$ can exhibit drastically different $\sigma$ values—one smooth, one congested—revealing inefficiencies invisible to traditional metrics.
# 
# In a multi-node network such as PACS, this distinction is even more critical: $\rho$ provides no mechanism to compare nodes with different roles (e.g., a write-heavy IWS vs. a lightweight IRS), whereas dimensionless coefficients place all nodes on the same scale, enabling direct cross-node and cross-path comparison.
# 
# ### From Single-Node to Network-Level Analysis
# 
# Iteration 1 analysed a single M/M/c/K node in isolation (27 configurations). Iteration 2 extends the analysis to a **7-node Jackson open queueing network** modelling a full PACS pipeline:
# 
# | Node | Role | Path |
# |------|------|------|
# | **IB** (Inbound Broker) | Routes incoming requests | Both |
# | **IWS** (Image Write Service) | DICOM archival (2.0 MB/req) | Write |
# | **IRS** (Image Read Service) | Image retrieval (0.01 MB/req) | Read |
# | **DB** (Shared Database) | Persistent storage (combined load) | Both |
# | **WAS** (Write Acknowledgment) | Archival response handler | Write |
# | **RAS** (Read Acknowledgment) | Retrieval response handler | Read |
# | **OB** (Outbound Broker) | Aggregates and delivers responses | Both |
# 
# The network is evaluated across **5 workload environments** (100R, 80R20W, 50R50W, 20R80W, 100W) with **216 configurations per scenario**, sweeping $\mu \in \{200, 500, 1000\}$, $c \in \{1, 2, 4\}$, and $K \in \{4, 8, 16, 32\}$.
# 
# Three **end-to-end paths** aggregate per-node coefficients into system-level views:
# 
# - **Read path** ($R_{PACS}$): IB $\to$ IRS $\to$ DB $\to$ RAS $\to$ OB
# - **Write path** ($W_{PACS}$): IB $\to$ IWS $\to$ DB $\to$ WAS $\to$ OB
# - **Overall** ($PACS$): Combined system behaviour
# 
# ### Interpreting the Network Yoly Diagrams
# 
# The per-node 3D Yoly diagrams (3$\times$3 grid) map 216 configurations into $(\theta, \sigma, \eta)$ space for each node, while the environment Yoly diagrams overlay Read, Write, and Overall paths on a single 3D space per environment.
# 
# Key observations:
# 
# - **Path Asymmetry:** Read and Write paths exhibit fundamentally different coefficient signatures. The Write path (IWS: 2.0 MB/req) produces higher $\phi$ and can drive $\eta$ into nonlinear territory at lower $K$ values than the Read path (IRS: 0.01 MB/req). This asymmetry is invisible to traditional $\rho$-based analysis.
# - **Shared Bottleneck (DB):** The Database node receives combined traffic from both paths regardless of environment. Its $\theta$ and $\sigma$ values remain elevated across all 5 scenarios because $\lambda_{DB} \approx 99$ req/s is nearly constant. The DB node anchors the system's worst-case behaviour: even in 100R (read-only), the DB is under full load from retrieval queries.
# - **Environment Sensitivity:** As the workload shifts from 100R to 100W, the Write path's $\eta$ trajectory moves farther from the origin while the Read path contracts (fewer requests). The Overall path tracks a weighted combination, but is dominated by whichever path carries more traffic. The 50R50W scenario is particularly revealing: both paths contribute equally, exposing whether the architecture handles balanced load symmetrically.
# - **Safe Operating Zone:** Consistent with Iteration 1, the region near the origin ($\theta < 0.3$, $\sigma < 0.3$) remains the stable, linear-$\eta$ regime. However, in a network context, **all nodes on a path** must remain in this zone for the end-to-end path to be safe. A single node drifting into nonlinear territory degrades the entire path.
# - **Master Curves Persist:** Despite the network complexity, individual nodes still collapse onto master curves governed by server count $c$. This confirms that the dimensionless framework scales from single-node to multi-node analysis without losing its structural properties.
# 
# ### Bottleneck Identification
# 
# The 100W (full write) scenario stress-tests the archival path:
# 
# - **IWS** handles 99 req/s of high-density DICOM payloads (2.0 MB/req), pushing $\phi$ toward saturation and $\sigma$ into the nonlinear regime at low $c$ and $K$ values.
# - **DB** receives the same aggregate load as in all other scenarios but must now process exclusively write-heavy traffic, which typically incurs higher per-request latency.
# - The Yoly diagram for 100W shows the Write path's $\eta$ curve diverging sharply from the Read path (which is inactive), confirming that **write-dominated workloads are the critical design case** for this PACS architecture.
# 
# Conversely, in 100R the Read path demonstrates lower $\eta$ and $\sigma$ values for equivalent $K$, reflecting the lightweight nature of retrieval requests. This asymmetry means **capacity planning must be driven by the write-heavy scenarios**, not the read-heavy ones.
# 
# ### Using the Network Yoly Chart
# 
# - **Design Point Selection:** Target configurations where **all nodes on the critical path** remain in the low-$\theta$, low-$\sigma$ region. Unlike single-node analysis, a network-safe design requires checking every node's position, not just the aggregate.
# - **Path-Aware Scaling:** The Read and Write paths may require different scaling strategies. Increasing $c$ on IWS (archival) has a larger impact on the Write path's $\eta$ than increasing $c$ on IRS (retrieval), because write requests are 200$\times$ heavier in data density.
# - **Load Forecasting:** If $\lambda$ increases, trace the trajectory along each path's master curve independently. The Write path will hit the failure boundary first due to higher per-request resource consumption. Plan capacity upgrades for the write-heavy components (IWS, DB) before the read components.
# - **Environment Planning:** The 5-environment sweep provides a lookup table for capacity decisions. If the expected workload is 80R20W (typical clinical hours), the Yoly chart shows exactly which $(K, c, \mu)$ combinations keep all paths in the safe zone. If the workload shifts toward write-heavy (e.g., batch DICOM imports), the 100W chart reveals the required headroom.
# - **Cross-Path Comparison:** Overlaying Read, Write, and Overall on the same 3D space immediately reveals which path dominates system behaviour. If the Overall curve tracks closely with one path, that path is the design driver.
# 
# **Scaling Strategy (Network-Aware):**
# - Increase $c$ on **bottleneck nodes** (IWS, DB) first—these have the highest impact on end-to-end $\eta$
# - Increase $K$ on nodes with high $\theta$ to provide queue headroom before saturation
# - Increase $\mu$ where $\sigma$ is elevated to reduce per-request sojourn time
# - The DB node, as the shared bottleneck, benefits most from scaling $c$ because it serves both paths simultaneously
# 
# ### Practical Implications
# 
# - **Operational workflow for multi-node software systems:**
#   1. **Monitor:** Calculate $(\theta, \sigma, \eta, \phi)$ per node from telemetry ($L$, $W$, $\lambda$, $M_{\text{act}}$, etc.)
#   2. **Aggregate:** Compute end-to-end path coefficients (Read, Write, Overall) by combining per-node metrics along each path
#   3. **Locate:** Plot current operating points on per-node and per-path Yoly diagrams
#   4. **Diagnose:** Identify which nodes and paths are drifting from the origin into the nonlinear regime
#   5. **Prescribe:** Scale the specific bottleneck node—increase $c$ (move to a different master curve), or $K$/$\mu$ (shift along the current curve)
#   6. **Validate:** Re-simulate with updated parameters to confirm all paths return to the safe zone
# - **Design Principle:** In a network, the weakest node on each path determines end-to-end performance. A single saturated node ($\theta \to 1$) causes stall divergence ($\sigma$ growth) that propagates through downstream nodes. Design for the worst-case path (typically write-heavy) and verify that the other paths remain safe as a consequence.
# - **Universality:** The dimensionless framework scales from a single M/M/c/K queue (Iteration 1) to a 7-node Jackson network (Iteration 2) without modification to the coefficient definitions. The same $(\theta, \sigma, \eta)$ space, the same master curves, and the same safe-zone boundaries apply. This confirms that the DASA methodology is **topology-agnostic**: it characterises system behaviour through dimensionless ratios regardless of the number of nodes, the routing topology, or the workload mix.
# - **Early Warning:** Monitor the distance of each node's operating point from the origin. In a network, the node closest to the failure boundary is the leading indicator. For PACS, this is typically the DB node (shared bottleneck) or IWS (high data density). A drift in these nodes' $\theta$ or $\sigma$ signals degradation before it manifests in end-to-end latency metrics.

# %% [markdown]
# ### Next Steps
# 
# - Extend analysis to other queueing models (M/G/1, G/G/c, priority queues, etc.)
# - Incorporate time-varying arrival rates and non-stationary behavior
# - Add cost-based optimization using dimensionless coefficients (\$/request vs. $\eta$)
# - Explore other custom frameworks (Security, Latency, Reliability dimensions)
# - Apply to real-world service telemetry data from production systems
# - Investigate multi-objective optimization across all four coefficients ($\theta, \sigma, \eta, \phi$)
# - Develop predictive models using dimensionless regression
# - Map the linear-to-nonlinear transition boundary quantitatively for different $(c, K, \mu)$ families
# 
# Check [PyDASA Documentation](https://pydasa.readthedocs.io) for advanced features and more examples.
# 
# ---
# 
# **About this notebook:** Created to demonstrate PyDASA's dimensional analysis workflows applied to queueing theory and software service analysis using custom dimensional frameworks. The "Yoly" concept represents a composite metric for system happiness (performance + availability + efficiency + reliability). For more examples and documentation, visit [PyDASA on GitHub](https://github.com/DASA-Design/PyDASA) or [Read the Docs](https://pydasa.readthedocs.io).



# %% [markdown]
# # **TAS (Tele Assistance System) Stochastic Modelling**
# NOTE: _[DASA CASE STUDY 1]_

# %% [markdown]
# ## **Summary**
# 
# This notebook is focused on three main objectives:
# 1. summarizing the key aspects of the Tele Assistance System (TAS) architecture and its adaptive capabilities in the context of telehealth services for chronic patients.
# 2. Modelling the TAS architecture using appropriate design notations and tools to visualize its components and interactions.
# 3. Stochasticly Simulate the TAS behavior under different scenarios to evaluate its performance and adaptability with Queue Network (QN) models.
# 
# The results will be used to evaluate the Dimensional Analysis for Software Architecture (DASA) methodology, its software tool (PyDASA) and its effectiveness in modelling and Quality Scenarios (QS) trade-off in self-adaptive-systems (SAS).
# 
# ---

# %% [markdown]
# ## **Software Architecture**
# - TAS (Tele Assistance System) operates in a dynamic environment where service quality, availability, and user needs frequently change.
# - The TAS is further subdivided into Controller and Target System subsystem components.
# - The Controller is responsible for managing the overall system behavior, while the Target System focuses on executing specific tasks related to patient care.
# - The TAS target systems follows a Service-oriented architecture (SOA) pattern.
# - The TAS Controller follows a MAPE-K (Monitor-Analyze-Plan-Execute-Knowledge) feedback loop for self-adaptation.
# - Adaptations focus on maintaining **reliability**, **performance**, and **compliance** with patient care standards (5 specific scenarios).
# - ActivFORMS provides the runtime framework for model-based adaptation using runtime models, simulations, and verified decision-making.
# 
# ---
# 
# _**NOTE: MORE DETAILS ON THE ARCHITECTURE IN THE ANALYTICAL MODELLING NOTEBOOK!.**_
# 
# ---

# %% [markdown]
# ## **Target System Queue Network Model**
# 
# <svg viewBox="0 0 4650 2000" width="1400" height="650">
#     <!-- SVG content -->
#     <image href="assets/cs1/img/04A - Queue Network.svg" alt="queue-net-diagram" />
#     <div align="center"><em>Image 1. TAS Queue Network Diagram.</em></div>
# </svg>

# %% [markdown]
# ## **Code**
# 
# _**SUMMARY:**_
# 
# This code is for the stochastic simulation of the Case Study (TAS) Queue Network Model and is structured as follows:
# 1. Analytical Queue Network (QN) model
# 2. Importing necessary libraries and modules.
# 3. Loading QN default configuration.
# 4. Simulating the QN analytically (Stochastic Process).
# 5. Plotting the QN with the obtained metrics.
# 6. Loading QN 'optimal' configuration.
# 7. Simulating the QN optimally (Stochastic Process).
# 8. Plotting the optimal QN with the obtained metrics.
# 9. Saving the results.
# 10. Comparing the simulation results (Default Vs. Optimal)
# 11. Visualizing the results.
# 12. Generating a summary report.

# %% [markdown]
# ### **Necessary Imports**

# %%
# -*- coding: utf-8 -*-
# Native imports
import os
import re
import sys
import time
from typing import Union

# Third-party imports
import numpy as np
import pandas as pd

# import queue stochastic network + models packages
from src.model.analytical import calculate_net_metrics
# from src.simulation.network import QueueNode
# from src.simulation.network import job_generator, job
from src.simulation.network import simulate_network

# import plot functions + grahics
from src.view.plots import plot_queue_network
from src.view.plots import plot_net_comparison
from src.view.plots import plot_net_difference
from src.view.plots import plot_nodes_heatmap
from src.view.plots import plot_nodes_diffmap

# %% [markdown]
# ### **Function Definitions**

# %%
# Simple formatter for console output

def fmt(val: Union[int, float, np.number]) -> Union[str, np.ndarray]:
    """Format a number to 4 decimal places for console output.

    Args:
        val (Union[int, float, np.number, np.ndarray]): The value to format.

    Returns:
        Union[str, np.ndarray]: The formatted value as a string or an array of strings.
    """
    if isinstance(val, (int, float, np.number)):
        if np.isnan(val) or np.isinf(val):
            return str(val)
        return f"{val:.4f}"
    elif isinstance(val, np.ndarray):
        return np.array([fmt(x) for x in val])
    return val

# %%
# Load configuration from a CSV file
def load(path: str, fname: str) -> pd.DataFrame:
    """Load configuration from a CSV file.

    Args:
        path (str): The directory path where the CSV file is located.
        fname (str): The name of the CSV file to load.

    Returns:
        pd.DataFrame: A DataFrame containing the configuration data.
            CSV format:
                - node: <node_id>
                - miu: <mean_service_time>
                - c: <service_channels>
                - K: <buffer_capacity | max_queue_length>
                - lambda0: <initial_arrival_rate>
                - L0: <initial_queue_length>
                - pm: <matrix_routing_probabilities>
    """
    # path = os.path.dirname(__file__)
    _file_path = os.path.join(path, fname)
    print(f"Loading configuration from: {_file_path}")
    df = pd.read_csv(_file_path)
    return df

# %%
# save dataframes in CSV files
def save(path: str, fname: str, data: pd.DataFrame) -> None:
    """Save a DataFrame to a CSV file.

    Args:
        path (str): The directory path where the CSV file will be saved.
        fname (str): The name of the CSV file to save.
        data (pd.DataFrame): The DataFrame containing the data to save.
    """
    # path = os.path.dirname(__file__)
    _file_path = os.path.join(path, fname)
    print(f"Saving data to: {_file_path}")
    data.to_csv(_file_path, index=False)

# %%
def config_stochastics_model(cfg_df: pd.DataFrame, verbose=False) -> tuple:
    """Configure the stochastic queue model based on the provided configuration DataFrame.

    Args:
        cfg_df (pd.DataFrame): configuration DataFrame
        verbose (bool, optional): If True, print detailed information. Defaults to False.

    Returns:
        tuple: A tuple containing the configured parameters and queue objects specifically:
            - mus (list): List of service rates.
            - lambda_zs (list): List of arrival rates.
            - servers (list): List of number of servers.
            - kaps (list): List of capacities.
            - P (np.ndarray): Routing probability matrix.
    """

    # extract parameters from the configuration DataFrame
    # and casting them to proper types
    nodes = cfg_df["node"].values.astype(int).tolist()
    names = cfg_df["name"].values.tolist()
    types = cfg_df["type"].values.tolist()
    mus = cfg_df["mu"].values.tolist()
    lambda_zs = cfg_df["lambda_z"].values.tolist()
    n_servers = cfg_df["c"].values.astype(int).tolist()
    kaps = cfg_df["K"].values.astype(float).tolist()

    # Convert K=0=nan to understandable infinite capacity -> None
    for i in range(len(kaps)):
        if np.isnan(kaps[i]):
            if verbose:
                _msg = f"Node {nodes[i]}: K is 'NaN', "
                _msg += "setting capacity to None (infinite)"
                print(_msg)
            kaps[i] = None
        else:
            kaps[i] = float(kaps[i])

    # Convert string representations of arrays to actual numpy arrays
    # and create routing matrix P
    prob = []
    for pm_str in cfg_df["P_routing"].values.tolist():
        routing_val = pm_str.strip("[]").split(",")
        routing_val = [float(val) for val in routing_val]
        prob.append(routing_val)
    P_routing = np.array((prob))

    # create analytical model tuple
    ans = (mus, lambda_zs, n_servers, kaps, P_routing)
    return ans

# %%
# path = os.path.dirname(__file__)\
PATH = os.getcwd()
print(f"Notebook path: {PATH}")

# %%
# Folder names
asset_folder = "assets"
config_folder = "config"
docs_folder = "docs"
img_folder = "img"
data_folder = "data"
report_folder = "reports"
results_folder = "results"
cs_folder = "cs1"

# %%
# setting case study configuration folder
file_path = os.path.join(PATH, data_folder, config_folder, cs_folder)
print(f"Configuration file path: {file_path}")

# %%
print("--- Config stochastic sampling settings ---")
n_reps = 3   # number of replications per experiment
print(f"Number of replications per experiment: {n_reps}")
n_exp = 1000  # number of experiments
print(f"Number of experiments: {n_exp}")
n_warmup = 100  # number of warm-up jobs
print(f"Number of warm-up jobs: {n_warmup}")

# %% [markdown]
# ### **Queue Model**
# #### **Stochastic Simulation**
# ##### **Base Configuration**

# %%
# Load configuration with mixed queue models
dflt_qn_cfg = load(file_path, "default_qn_model.csv")
print("Queue Network Configuration:")
dflt_qn_cfg.head()

# %%
print("--- Configuring default stochastic queue model ---")
dflt_stochastics_model = config_stochastics_model(dflt_qn_cfg, verbose=True)

# %%
print("--- Executing default stochastic network simulation ---")
dflt_simul_nd_metrics = simulate_network(*dflt_stochastics_model,
                                         n_exp=n_exp,
                                         warm_exp=n_warmup,
                                         reps=n_reps,
                                         verbose=True)

# %%
print("--- Renaming default simulation network metrics ---")
src_df_cols = dflt_simul_nd_metrics.columns.tolist()
exp = r"_mean$"
mean_cols = [col for col in src_df_cols if re.search(exp, col)]
print(f"Mean column names: {mean_cols}")

tgt_df_cols = [col.replace("_mean", "") for col in mean_cols]
print(f"Target column names: {tgt_df_cols}")

dflt_simul_nd_metrics_mean = pd.DataFrame(dflt_simul_nd_metrics[mean_cols])
# rename colums
rename_dict = dict(zip(mean_cols, tgt_df_cols))
print(f"Rename dictionary: {rename_dict}")
dflt_simul_nd_metrics.rename(columns=rename_dict, inplace=True)

# %%
# then network metrics
print("--- Calculating default simulation network metrics ---")
dflt_simul_net_metrics = calculate_net_metrics(dflt_simul_nd_metrics)
dflt_simul_net_metrics["nodes"] = len(list(dflt_simul_nd_metrics["node"]))

# %%
print("\n--- Save Stochastic Network Simulation (Node Metrics) ---")
# print(opti_simul_nd_metrics)

# save data
# select result folder
file_path = os.path.join(PATH,
                         data_folder,
                         results_folder,
                         cs_folder,
                         data_folder)
print(f"Data path: {file_path}")
save(file_path, "dflt_stochastic_node_metrics.csv", dflt_simul_nd_metrics)
dflt_simul_nd_metrics.head()

# %%
print("\n--- Save Stochastic Network Simulation (Network-wide Metrics) ---")
# print(dflt_simul_net_metrics)

# save data
# select result folder
file_path = os.path.join(PATH,
                         data_folder,
                         results_folder,
                         cs_folder,
                         data_folder)
print(f"Data path: {file_path}")
save(file_path, "dflt_stochastic_net_metrics.csv", dflt_simul_net_metrics)
dflt_simul_net_metrics.head()

# %%
print("--- Plotting Default Stochastic Queue Network ---")
# plotting the queue network with metrics on each node
# data table column names
col_names =[
    "Component",
    r"$\mathbf{\lambda}$ [req/s]",
    r"$\mathbf{\mu}$ [req/s]",
    r"$\mathbf{\rho}$",
    r"$\mathbf{L}$ [req]",
    r"$\mathbf{L_q}$ [req]",
    r"$\mathbf{W}$ [s/req]",
    r"$\mathbf{W_q}$ [s/req]"
]

# P = dflt_stochastics_model[-1]

node_names = dflt_qn_cfg["name"].values.tolist()
print(f"Datatable column names: {col_names}")
print(f"Node names: {node_names}")  

# selecting images folder
file_path = os.path.join(PATH,
                         data_folder,
                         results_folder,
                         cs_folder,
                         img_folder)
print(f"Data path: {file_path}")

# Plot the queue network
plot_queue_network(dflt_stochastics_model[-1],
                   dflt_simul_net_metrics,
                   dflt_simul_nd_metrics,
                   node_names,
                   col_names,
                   file_path,
                   "dflt_stochastic_qn_diagram.png")

# %% [markdown]
# ##### **Optimized Configuration**

# %%
# setting case study configuration folder
file_path = os.path.join(PATH, data_folder, config_folder, cs_folder)
print(f"Configuration file path: {file_path}")

# %%
# Load configuration with optimal queue models
print("--- Load configuration with optimal queue models ---")
opti_qn_cfg = load(file_path, "optimal_qn_model.csv")
print("Queue Network Configuration:")
# print(opti_qn_cfg)
opti_qn_cfg.head()

# %%
print("--- Configuring optimal stochastic queue model ---")
opti_stochastics_model = config_stochastics_model(opti_qn_cfg, verbose=True)

# %%
print("--- Executing optimal stochastic network simulation ---")
opti_simul_nd_metrics = simulate_network(*opti_stochastics_model,
                                         n_exp=n_exp,
                                         warm_exp=n_warmup,
                                         reps=n_reps,
                                         verbose=True)

# %%
print("--- Renaming optimal simulation network metrics ---")
src_df_cols = opti_simul_nd_metrics.columns.tolist()
exp = r"_mean$"
mean_cols = [col for col in src_df_cols if re.search(exp, col)]
print(f"Mean column names: {mean_cols}")

tgt_df_cols = [col.replace("_mean", "") for col in mean_cols]
print(f"Target column names: {tgt_df_cols}")

opti_simul_nd_metrics_mean = pd.DataFrame(opti_simul_nd_metrics[mean_cols])
# rename colums
rename_dict = dict(zip(mean_cols, tgt_df_cols))
print(f"Rename dictionary: {rename_dict}")
opti_simul_nd_metrics.rename(columns=rename_dict, inplace=True)

# %%
# then network metrics
print("--- Calculating optimal simulation network metrics ---")
opti_simul_net_metrics = calculate_net_metrics(opti_simul_nd_metrics)
opti_simul_net_metrics["nodes"] = len(list(opti_simul_nd_metrics["node"]))

# %%
print("--- Save Stochastic Network Simulation (Node Metrics) ---")
# print(opti_simul_nd_metrics)

# save data
# select result folder
file_path = os.path.join(PATH,
                         data_folder,
                         results_folder,
                         cs_folder,
                         data_folder)
print(f"Data path: {file_path}")
save(file_path, "opti_stochastic_node_metrics.csv", opti_simul_nd_metrics)
opti_simul_nd_metrics.head()

# %%
print("--- Save Stochastic Network Simulation (Network-wide Metrics) ---")
# print(opti_simul_net_metrics)
# opti_simul_net_metrics.head()

# save data
# select result folder
file_path = os.path.join(PATH,
                         data_folder,
                         results_folder,
                         cs_folder,
                         data_folder)
print(f"Data path: {file_path}")
save(file_path, "opti_stochastic_net_metrics.csv", opti_simul_net_metrics)
opti_simul_net_metrics.head()

# %%
# plotting the queue network with metrics on each node
node_names = opti_qn_cfg["name"].values.tolist()
print(f"Node names: {node_names}")  

# selecting images folder
file_path = os.path.join(PATH,
                         data_folder,
                         results_folder,
                         cs_folder,
                         img_folder)
print(f"Data path: {file_path}")

# Plot the queue network
plot_queue_network(opti_stochastics_model[-1],
                   opti_simul_net_metrics,
                   opti_simul_nd_metrics,
                   node_names,
                   col_names,
                   file_path,
                   "opti_stochastic_qn_diagram.png")

# %% [markdown]
# ## **Results**

# %% [markdown]
# ### **Compare Results**

# %%
# prep comparison
dsnm = dflt_simul_net_metrics
osnm = opti_simul_net_metrics

# %%
print("--- Comparing Stochastic Network Metrics ---")
# comparing network metrics
# diff_simul_net_metrics = opti_simul_net_metrics - dflt_simul_net_metrics
# delta_simul_net_metrics = diff_simul_net_metrics / dflt_simul_net_metrics
delta_simul_net_metrics = (osnm - dsnm) / dsnm.abs()

src_col_names = delta_simul_net_metrics.columns.tolist()

tgt_col_names = [
    "delta_avg_mu",
    "delta_avg_rho",
    "delta_L_net",
    "delta_Lq_net",
    "delta_W_net",
    "delta_Wq_net",
    "delta_throughput",
    "delta_nodes",
]

rename_map = dict(zip(src_col_names, tgt_col_names))
# print(rename_map)

# rename comparison columns
delta_simul_net_metrics.rename(columns=rename_map,
                               inplace=True)
delta_simul_net_metrics.head()

# %%
# preparing data comparison
important_cols = [
    "node",
    "lambda",
    "mu",
    "rho",
    "L",
    "Lq",
    "W",
    "Wq"
]

dsnm = dflt_simul_nd_metrics[important_cols]
osnm = opti_simul_nd_metrics[important_cols]

# %%
# comparing node network metrics
print("--- Comparing Stochastic Node/Component Metrics ---")
# extra data columns
extra_cols = [
    "node",
    "name",
    "type",
]

delta_simul_nd_metrics = (osnm - dsnm) / dsnm.abs()

src_col_names = delta_simul_nd_metrics.columns.tolist()

tgt_col_names = [
    "node",
    "delta_lambda",
    "delta_mu",
    "delta_rho",
    "delta_L",
    "delta_Lq",
    "delta_W",
    "delta_Wq",
]

rename_map = dict(zip(src_col_names, tgt_col_names))

# rename comparison columns
delta_simul_nd_metrics.rename(columns=rename_map,
                              inplace=True)

# adding node ID data
for col in extra_cols:
    if col in opti_qn_cfg.columns:
        delta_simul_nd_metrics[col] = opti_qn_cfg[col].values

delta_simul_nd_metrics.head()

# %% [markdown]
# ### **Saving Results**

# %%
# save data
# select result folder
file_path = os.path.join(PATH,
                         data_folder,
                         results_folder,
                         cs_folder,
                         data_folder)
print(f"Data path: {file_path}")
save(file_path,
     "delta_stochastic_node_metrics.csv",
     delta_simul_nd_metrics)

# %%
# save data
# select result folder
file_path = os.path.join(PATH,
                         data_folder,
                         results_folder,
                         cs_folder,
                         data_folder)
print(f"Data path: {file_path}")
save(file_path,
     "delta_stochastic_net_metrics.csv",
     delta_simul_net_metrics)

# %% [markdown]
# ## **Analysis**

# %% [markdown]
# ### **Graph Analysis**

# %%
# selecting images folder
print("--- Configuring folder path for plot parameters ---")
file_path = os.path.join(PATH,
                         data_folder,
                         results_folder,
                         cs_folder,
                         img_folder)
print(f"Data path: {file_path}")

# %%
print("--- Charting Overall Configuration Comparisons ---")
metrics = dflt_simul_net_metrics.columns.tolist()
labels = [
    "$\\mathbf{\\mu}$ [req/s]",
    "$\\mathbf{\\rho}$ [%]",
    "$\\mathbf{L_{net}}$ [req]",
    "$\\mathbf{L_{q_{net}}}$ [req]",
    "$\\mathbf{W_{net}}$ [s/req]",
    "$\\mathbf{W_{q_{net}}}$ [s/req]",
    "$\\mathbf{Th_{net}}$ [req]",
    "$\\mathbf{n}$ [comp]",
]

for m, l in zip(metrics, labels):
    print(f"{m:18} : {l}")

# %%
# Plot the metric comparison
plot_net_comparison([dflt_simul_net_metrics, opti_simul_net_metrics],
                    ["Default Configuration", "Adaptation Configuration"],
                    metrics,
                    labels,
                    "Metric Comparison: Before and after Adaptation",
                    file_path,
                    "net_stochastic_metric_comparison.png")

# %%
print("--- Charting Overall Configuration differences ---")
metrics = delta_simul_net_metrics.columns.tolist()
labels = [
    "$\\mathbf{\\overline{\\Delta \\mu}}$ [req/s]",
    "$\\mathbf{\\overline{\\Delta \\rho}}$ [n.a.]",
    "$\\mathbf{\\overline{\\Delta L}_{net}}$ [req]",
    "$\\mathbf{\\overline{\\Delta L}_{q_{net}}}$ [req]",
    "$\\mathbf{\\overline{\\Delta W}_{net}}$ [s/req]",
    "$\\mathbf{\\overline{\\Delta W}_{q_{net}}}$ [s/req]",
    "$\\mathbf{\\overline{\\Delta Th}_{net}}$ [req]",
    "$\\mathbf{\\overline{\\Delta n}}$ [comp]",
]

for m, l in zip(metrics, labels):
    print(f"{m:18} : {l}")

# %%
# Plot the metric differences
plot_net_difference(delta_simul_net_metrics,
                    metrics,
                    labels,
                    "Change between configurations after adaptation.",
                    file_path,
                    "net_stochastic_metric_differences.png")

# %%
print("--- Charting Component Queue-Network Comparative Heatmap ---")
# Define metrics for the heatmap X-axis
metrics = delta_simul_nd_metrics.select_dtypes(include="number")
metrics = metrics.columns.tolist()
if "node" in metrics:
    metrics.remove("node")

# define the labels for the heatmap X-axis alias
labels = [
    "$\\mathbf{\\Delta\\lambda}$ [req/s]",
    "$\\mathbf{\\Delta \\mu}$ [req/s]",
    "$\\mathbf{\\Delta \\rho}$ [n.a.]",
    "$\\mathbf{\\Delta L_{net}}$ [req]",
    "$\\mathbf{\\Delta L_{q_{net}}}$ [req]",
    "$\\mathbf{\\Delta W_{net}}$ [s/req]",
    "$\\mathbf{\\Delta W_{q_{net}}}$ [s/req]",
]

# define the node names for the heatmap Y-axis
node_names = delta_simul_nd_metrics["name"].values.tolist()
print(f"Node names: {node_names}")

for m, l in zip(metrics, labels):
    print(f"{m:18} : {l}")

# %%
print("--- Preparing data for heatmaps ---")
dflt_simul_nd_metrics["name"] = node_names
opti_simul_nd_metrics["name"] = node_names
print(dflt_simul_nd_metrics.columns.tolist())
print(opti_simul_nd_metrics.columns.tolist())

# %%
print("--- Charting Component Queue-Network Configuration Heatmap ---")
metrics = dflt_simul_nd_metrics.select_dtypes(include="number")
metrics = metrics.columns.tolist()
if "node" in metrics:
    metrics.remove("node")

labels = [
    # "$\\mathbf{n}$ [comp]",
    "$\\mathbf{\\lambda}$ [req/s]",
    "$\\mathbf{\\mu}$ [req/s]",
    "$\\mathbf{\\rho}$ [%]",
    "$\\mathbf{L}$ [req]",
    "$\\mathbf{L_{q}}$ [req]",
    "$\\mathbf{W}$ [s/req]",
    "$\\mathbf{W_{q}}$ [s/req]",
]

# define the node names for the heatmap Y-axis
node_names = delta_simul_nd_metrics["name"].values.tolist()
print(f"Node names: {node_names}")

for m, l in zip(metrics, labels):
    print(f"{m:18} : {l}")

# %%
# removing numeric metrics that Im not interested in
not_interesting = [
    "node",
    "type",
    "L_littles",
    "Lq_littles",
    "Jobs_Served",
    "Jobs_Blocked",
    "Blocking_Prob"
]
print(metrics)
# removing uninteresting columns
metrics = [m for m in metrics if m not in not_interesting]
# removing anything ending in _std
metrics = [m for m in metrics if not m.endswith("_std")]
print(metrics)

# %%
if "name" not in metrics:
    metrics.append("name")
print(metrics)
print(labels)
print(len(metrics), len(labels))

dsnm = dflt_simul_nd_metrics[metrics]
osnm = opti_simul_nd_metrics[metrics]
# quitar las columnas 'L_littles', 'Lq_littles', 'Jobs_Served', 'Jobs_Blocked', 'Blocking_Prob'

# %%
if "name" in metrics:
    metrics.remove("name")
print(metrics)
print(labels)
print(len(metrics), len(labels))

# %%
plot_nodes_heatmap([dsnm, osnm],
                   ["Default Configuration", "Adaptation Configuration"],
                   node_names,
                   metrics,
                   labels,
                   "Component Performance Comparison Between Configurations",
                   "name",
                   file_path,
                   "nodes_stochastic_metric_heatmap.png")

# %%
print("--- Charting Component Queue-Network Differential Heatmap ---")
# Define metrics for the heatmap X-axis
metrics = delta_simul_nd_metrics.select_dtypes(include="number")
metrics = metrics.columns.tolist()
if "node" in metrics:
    metrics.remove("node")

# define the labels for the heatmap X-axis alias
labels = [
    "$\\mathbf{\\Delta\\lambda}$ [%]",
    "$\\mathbf{\\Delta \\mu}$ [%]",
    "$\\mathbf{\\Delta \\rho}$ [%]",
    "$\\mathbf{\\Delta L_{net}}$ [%]",
    "$\\mathbf{\\Delta L_{q_{net}}}$ [%]",
    "$\\mathbf{\\Delta W_{net}}$ [%]",
    "$\\mathbf{\\Delta W_{q_{net}}}$ [%]",
]

# define the node names for the heatmap Y-axis
node_names = delta_simul_nd_metrics["name"].values.tolist()
print(f"Node names: {node_names}")

for m, l in zip(metrics, labels):
    print(f"{m:18} : {l}")

# %%
plot_nodes_diffmap(delta_simul_nd_metrics,
                   node_names,
                   metrics,
                   labels,
                   "Component Performance Change: Before and after Adaptation",
                   "name",
                   file_path,
                   "nodes_stochastic_metric_diffmap.png")

# %%


# %%


# %%


# %% [markdown]
# ## **Conclusion**

# %%


# %% [markdown]
# ## **Future Work**

# %%


# %%


# %%


# %% [markdown]
# ## **References & Sources**
# <!-- TODO fix the references, links and details -->
# 1. [Queueing Theory](https://en.wikipedia.org/wiki/Queueing_theory)
# 2. [Dimensional Analysis](https://en.wikipedia.org/wiki/Dimensional_analysis)
# 3. [Simulation in Healthcare](https://www.ncbi.nlm.nih.gov/pmc/articles/PMC6466220/)
# 
# ---

# %% [markdown]
# # **HASTA AKI!!!**



# Standard library imports
import os

# Third-party imports
# import numpy as np
import pandas as pd
# import seaborn as sns
import networkx as nx
import matplotlib.pyplot as plt

# for plotting refined dimensionless chart
# from matplotlib.colors import LinearSegmentedColormap
# from scipy.stats import binned_statistic_2d
# import matplotlib.ticker as ticker

# Set global style for white background and black text
plt.rcParams.update({
    "figure.facecolor": "white",
    "axes.facecolor": "white",
    "savefig.facecolor": "white",
    "text.color": "black",
    "axes.labelcolor": "black",
    "axes.edgecolor": "black",
    "xtick.color": "black",
    "ytick.color": "black",
    "grid.color": "lightgray",
    "font.size": 10,
    "axes.labelsize": 12,
    "xtick.labelsize": 10,
    "ytick.labelsize": 10,
    "legend.fontsize": 10,
})


# Plotting function for queue network

def plot_queue_network(rout_matrix: pd.DataFrame,
                       net_metrics: pd.DataFrame,
                       nd_metrics: pd.DataFrame,
                       nd_names: list = None,
                       col_names: list = None,
                       file_path: str = None,
                       fname: str = None):
    """Plot the queue network with metrics on each node and the overall network data.

    Args:
        rout_matrix (pd.DataFrame): The routing probability matrix between nodes.
        net_metrics (pd.DataFrame): DataFrame containing network metrics (throughput, delay, etc.).
        nd_metrics (pd.DataFrame): DataFrame containing node metrics (utilization, queue length, etc.).
        col_names (list, optional): List of column names. Default to None.
        nd_names (list, optional): List of node names. Defaults to None.
        file_path (str, optional): File path to save the plot. Defaults to None.
        fname (str, optional): File name to save the plot. Defaults to None.

    Raises:
        ValueError: If file_path or fname is not provided when attempting to save the plot.
    """
    # Create directed graph
    G = nx.DiGraph()

    # Get number of nodes
    n_nodes = rout_matrix.shape[0]

    # Use node names if provided, otherwise use indices
    if nd_names is None:
        nd_names = [f"Node {i}" for i in range(n_nodes)]

    # use columns names if provided, node metrics from dataframe
    if col_names is None:
        col_names = [c for c in nd_metrics.columns.values]

    # Add nodes
    for i in range(n_nodes):
        G.add_node(i, name=nd_names[i])

    # Add edges based on routing matrix
    for i in range(n_nodes):
        for j in range(n_nodes):
            if rout_matrix[i, j] > 0:
                G.add_edge(i, j, weight=rout_matrix[i, j],
                           label=f"{rout_matrix[i, j]:.2f}")

    # Create figure with two subplots (main graph and metrics table)
    fig = plt.figure(figsize=(18, 22), facecolor="white")

    # Main graph subplot (larger, top portion)
    ax_graph = plt.subplot2grid((4, 1), (0, 0), rowspan=3)
    ax_graph.set_facecolor("white")

    # Metrics table subplot (smaller, bottom portion)
    ax_table = plt.subplot2grid((4, 1), (3, 0), rowspan=1)
    ax_table.set_facecolor("white")
    ax_table.axis("off")  # Hide axes for table

    # ALT 1
    pos = nx.bfs_layout(G, start=0)  # Breadth-first layout from source node
    # ALT 2
    # Use spring layout for better node distribution
    # pos = nx.spring_layout(G, k=1.25, iterations=250, seed=42)  # k controls spacing, higher = more spread out

    # preset node sizes
    node_sizes = [1500 for _ in range(n_nodes)]

    # Calculate node colors based on utilization
    if "rho" in nd_metrics.columns:
        node_colors = [plt.cm.coolwarm(nd_metrics["rho"].iloc[i]) for i in range(n_nodes)]
    else:
        node_colors = ["skyblue" for _ in range(n_nodes)]

    # Draw nodes on the graph subplot
    nx.draw_networkx_nodes(G, pos,
                           node_size=node_sizes,
                           node_color=node_colors,
                           alpha=0.9,
                           ax=ax_graph)

    # Draw edges with curved arcs to improve visibility
    nx.draw_networkx_edges(G, pos,
                           width=1.5,
                           alpha=0.7,
                           edge_color="black",
                           arrows=True,
                           arrowsize=20,
                           arrowstyle="-|>",
                           connectionstyle="arc3,rad=0.2",
                           ax=ax_graph)

    # Draw edge labels
    edge_labels = {(i, j): f"{rout_matrix[i, j]:.2f}"
                   for i, j in G.edges() if rout_matrix[i, j] > 0.01}
    nx.draw_networkx_edge_labels(G,
                                 pos,
                                 edge_labels=edge_labels,
                                 font_size=11,
                                 font_color="black",
                                 font_weight="light",
                                 bbox=dict(facecolor="white",
                                           edgecolor="none",
                                           alpha=0.9,
                                           pad=0.3),
                                 label_pos=0.4,  # Adjust label pos along edge
                                 ax=ax_graph)

    # Draw simplified node labels (only names)
    nx.draw_networkx_labels(G,
                            pos,
                            labels={i: nd_names[i] for i in range(n_nodes)},
                            font_size=14,
                            font_weight="bold",
                            ax=ax_graph)

    # Create metrics table
    table_data = []
    # Add header row
    table_data.append(col_names)

    # Add data rows for each node
    for i in range(n_nodes):
        row = []
        # TODO improve this part later
        row = [
            nd_names[i],
            f"{nd_metrics['lambda'].iloc[i]:.2f}",
            f"{nd_metrics['miu'].iloc[i]:.2f}",
            f"{nd_metrics['rho'].iloc[i]:.2f}",
            f"{nd_metrics['L'].iloc[i]:.2f}",
            f"{nd_metrics['Lq'].iloc[i]:.2f}",
            f"{nd_metrics['W'].iloc[i]:.4e}",
            f"{nd_metrics['Wq'].iloc[i]:.4e}"
        ]
        table_data.append(row)

    # Create the table
    table = ax_table.table(cellText=table_data,
                           loc="center",
                           cellLoc="center",
                           colWidths=[0.12] * 8)

    # Style the table
    table.auto_set_font_size(False)
    table.set_fontsize(12)
    table.scale(1, 1.2)  # Adjust table size

    # Style header row
    for j, cell in enumerate(table_data[0]):
        table[(0, j)].set_facecolor("#E4EBF1")
        table[(0, j)].set_text_props(weight="bold")

    # Add network-wide metrics as a text box
    if not net_metrics.empty:
        net_info = []
        net_info.append("Network Metrics:")
        # service rate
        mt = f"$\\overline{{{{\\mu}}}}: {net_metrics['avg_miu'].iloc[0]:.2f}$"
        net_info.append(mt)

        # utilization
        mt = f"$\\overline{{{{\\rho}}}}: {net_metrics['avg_rho'].iloc[0]:.2f}$"
        net_info.append(mt)

        # entities in system
        mt = f"$\\overline{{{{L}}}}: {net_metrics['L_net'].iloc[0]:.2f}$"
        net_info.append(mt)

        # entities in queue
        mt = f"$Total Lq: {net_metrics['Lq_net'].iloc[0]:.2f}$"
        net_info.append(mt)

        # mean service time
        mt = f"$\\overline{{{{W}}}}: {net_metrics['W_net'].iloc[0]:.4e}$"
        net_info.append(mt)

        # mean in-queue time
        mt = f"$\\overline{{{{W_q}}}}: {net_metrics['Wq_net'].iloc[0]:.4e}$"
        net_info.append(mt)

        # Network Throughput
        mt = f"$TP_{{NET}}: {net_metrics['total_throughput'].iloc[0]:.2f}$"
        net_info.append(mt)

        # Create a text box with network metrics
        net_info_text = "\n".join(net_info)
        props = dict(boxstyle="round,pad=0.5",
                     facecolor="lightblue",
                     alpha=0.8,
                     edgecolor="blue")
        # network metrics display config
        ax_graph.text(0.50,
                      0.98,
                      net_info_text,
                      transform=ax_graph.transAxes,
                      fontsize=18,
                      fontweight="bold",
                      verticalalignment="top",
                      horizontalalignment="left",
                      bbox=props)

    # Add title
    ax_graph.set_title("Queue Network Visualization",
                       fontsize=24,
                       color="black",
                       fontweight="bold",
                       va="center",
                       ha="center",
                       pad=20)

    # Add legend for node parameters
    param_legend = [
        "LEGEND:",
        "\t$\\lambda$: Arrival rate",
        "\t$\\mu$: Service rate",
        "\t$\\rho$: Utilization",
        "\t$L$: Average number in system",
        "\t$L_q$: Average queue length",
        "\t$W$: Average time in system",
        "\t$W_q$: Average waiting time",
    ]
    # legend display config
    legend_text = "\n".join(param_legend)
    props = dict(boxstyle="round,pad=0.5",
                 facecolor="white",
                 alpha=0.8,
                 edgecolor="gray")
    ax_graph.text(0.78,
                  0.05,
                  legend_text,
                  transform=ax_graph.transAxes,
                  fontsize=14,
                  verticalalignment="bottom",
                  horizontalalignment="left",
                  bbox=props)

    # Add colorbar for utilization
    if "rho" in nd_metrics.columns:
        max_rho = nd_metrics["rho"].max()
        sm = plt.cm.ScalarMappable(cmap=plt.cm.coolwarm,
                                   norm=plt.Normalize(0, max_rho))
        sm.set_array([])
        # Pass the axis to associate the colorbar with
        cbar = fig.colorbar(sm, ax=ax_graph)
        cbar.set_label("Utilization $(\\rho)$", color="black", fontsize=14)
        cbar.ax.yaxis.set_tick_params(color="black")
        cbar.outline.set_edgecolor("black")
        plt.setp(plt.getp(cbar.ax.axes, "yticklabels"), color="black")

    # Remove axis for graph
    ax_graph.axis("off")

    # Add subtitle for metrics table
    plt.figtext(0.50,
                0.25,
                "Node Metrics Table",
                fontsize=18,
                fontweight="bold",
                va="center",
                ha="center",
                color="black")

    # Show plot
    plt.tight_layout()

    # Save with white background if needed
    if file_path and fname:
        # Create directory if it doesn't exist
        os.makedirs(file_path, exist_ok=True)

        # Construct full file path
        full_file_path = os.path.join(file_path, fname)

        print(f"Saving plot to: {full_file_path}")
        try:
            plt.savefig(full_file_path,
                        facecolor="white",
                        bbox_inches="tight",
                        dpi=300,
                        format="png")  # Explicitly set format
            print(f"Plot saved successfully to: {full_file_path}")
        except Exception as e:
            print(f"Error saving plot: {e}")
    else:
        _msg = "File path or file name not provided, skipping save."
        _msg = f"{_msg} file_path: {file_path}, fname: {fname}"
        # print(_msg)
        raise ValueError(_msg)
    plt.show()
    plt.close()
    # plt.clf()
    # plt.cla()

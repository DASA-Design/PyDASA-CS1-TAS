# Standard library imports
import os

# Third-party imports
import numpy as np
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
            fig.savefig(full_file_path,
                        facecolor="white",
                        bbox_inches="tight",
                        dpi=600)
            print(f"Plot saved successfully to: {full_file_path}")
        except Exception as e:
            _msg = f"Error saving plot: {e}.\n"
            _msg += "File path or file name not provided, skipping save. "
            _msg += f"{_msg} file_path: {file_path}, fname: {fname}"
            raise ValueError(_msg)
    plt.show()
    plt.close()
    # plt.clf()
    # plt.cla()


def plot_net_difference(delta_metrics: pd.DataFrame,
                        metrics: list[str] = None,
                        labels: list[str] = None,
                        title: str = None,
                        file_path: str = None,
                        fname: str = None) -> None:
    """Plot a comparison of metrics between two states in the overall network.

    Args:
        delta_metrics (pd.DataFrame): DataFrame containing the metrics to compare.
        metrics (list[str], optional): List of metrics to include in the comparison. Defaults to None.
        labels (list[str], optional): List of labels for the metrics. Defaults to None.
        title (str, optional): Title of the plot. Defaults to None.
        file_path (str, optional): Directory path to save the plot. Defaults to None.
        fname (str, optional): File name for the saved plot. Defaults to None.

    Raises:
        ValueError: If the plot cannot be saved.
    """
    # setting default values
    if metrics is None:
        # Select only numeric columns if metrics not specified
        metrics = delta_metrics.select_dtypes(include="number").columns.tolist()

    if labels is None:
        labels = metrics

    if title is None:
        title = "Default Metrics Comparison"

    # creating plot labels
    metric_labels = dict(zip(metrics, labels))

    # Create the figure and axis
    fig, ax = plt.subplots(figsize=(12, 7))
    fig.set_facecolor("white")
    ax.set_facecolor("white")

    # Extract values for plotting
    # Convert to percentages
    values = delta_metrics[metrics].iloc[0].values * 100
    _green = "#4CAF50"      # light green
    _red = "#FF5252"        # light red

    # Create color bars based on improvement (negative is good for most metrics)
    colors = [_green if x < 0 else _red for x in values]

    # For throughput, positive is good (more throughput is better)
    if values[-1] > 0:
        colors[-1] = _green
    elif values[-1] < 0:
        colors[-1] = _red

    # Create the bar chart
    bars = ax.bar(range(len(metrics)), values, color=colors)

    # Add value labels on top of bars
    for i, bar in enumerate(bars):
        # height = bar.get_height()
        # label_position = height + 1 if height >= 0 else height - 5
        height = bar.get_height()
        y_pos = height / 2 if height >= 0 else height / 2  # Middle of the bar

        ax.text(bar.get_x() + bar.get_width() / 2.,
                y_pos,
                f"{values[i]:.2f}%",
                color="black",
                fontweight="light",
                fontsize=10,
                ha="center",
                va="bottom"
                if height >= 0 else "top")

    # Add a horizontal line at y=0
    ax.axhline(y=0, color="black", linestyle="-", alpha=0.3)

    # Set labels and title
    ax.set_xticks(range(len(metrics)))
    ax.set_xticklabels([metric_labels[m] for m in metrics],
                       rotation=30,
                       ha="right")
    ax.set_ylabel("Porcentual Change (%)")
    ax.set_title(title, fontsize=14, fontweight="bold", pad=20)

    # Add grid lines for better readability
    ax.grid(axis="y", linestyle="--", alpha=0.7)

    # Set y-axis limit to provide some padding
    y_min = min(min(values) * 1.1, -2)  # At least -2% or 10% below minimum
    y_max = max(max(values) * 1.1, 2)   # At least 2% or 10% above maximum
    ax.set_ylim(y_min, y_max)

    # Add a legend directly in the plot area
    legend_elements = [
        plt.Rectangle((0, 0),
                      1, 1,
                      facecolor=_green,
                      alpha=0.8,
                      label="Improvement"),
        plt.Rectangle((0, 0),
                      1, 1,
                      facecolor=_red,
                      alpha=0.8,
                      label="Degradation")
    ]
    ax.legend(handles=legend_elements, loc="best")

    # Add some padding at the bottom for the rotated labels
    plt.subplots_adjust(bottom=0.15)

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
            fig.savefig(full_file_path,
                        facecolor="white",
                        bbox_inches="tight",
                        dpi=300)    # format="png")  # Explicitly set format
            print(f"Plot saved successfully to: {full_file_path}")
        except Exception as e:
            _msg = f"Error saving plot: {e}.\n"
            _msg += "File path or file name not provided, skipping save. "
            _msg += f"{_msg} file_path: {file_path}, fname: {fname}"
            raise ValueError(_msg)
    plt.show()
    plt.close()
    # plt.clf()
    # plt.cla()


def plot_net_comparison(net_metrics: list[pd.DataFrame],
                        names: list[str],
                        metrics: list[str] = None,
                        labels: list[str] = None,
                        title: str = None,
                        file_path: str = None,
                        fname: str = None) -> None:
    """Plot a metrics comparison between two or more states at system wide level.

    Args:
        net_metrics (pd.DataFrame): DataFrame containing the metrics to compare.
        metrics (list[str], optional): List of metrics to include in the comparison. Defaults to None.
        labels (list[str], optional): List of labels for the metrics. Defaults to None.
        title (str, optional): Title of the plot. Defaults to None.
        file_path (str, optional): Directory path to save the plot. Defaults to None.
        fname (str, optional): File name for the saved plot. Defaults to None.

    Raises:
        ValueError: If the plot cannot be saved.
    """
    # setting default values
    if metrics is None:
        # Select only numeric columns if metrics not specified
        metrics = net_metrics.select_dtypes(include="number")
        metrics = metrics.columns.tolist()

    if labels is None:
        labels = metrics

    if title is None:
        title = "Default Metrics Comparison"

    # creating plot labels
    metric_labels = dict(zip(metrics, labels))

    # Create the figure and axis
    fig, ax = plt.subplots(figsize=(12, 7))
    fig.set_facecolor("white")
    ax.set_facecolor("white")

    # Extract values for plotting
    # Convert to percentages
    values = net_metrics[metrics].iloc[0].values * 100
    _green = "#4CAF50"      # light green
    _red = "#FF5252"        # light red

    # Create color bars based on improvement (negative is good for most metrics)
    colors = [_green if x < 0 else _red for x in values]

    # For throughput, positive is good (more throughput is better)
    if values[-1] > 0:
        colors[-1] = _green
    elif values[-1] < 0:
        colors[-1] = _red

    # Create the bar chart
    bars = ax.bar(range(len(metrics)), values, color=colors)

    # Add value labels on top of bars
    for i, bar in enumerate(bars):
        # height = bar.get_height()
        # label_position = height + 1 if height >= 0 else height - 5
        height = bar.get_height()
        y_pos = height / 2 if height >= 0 else height / 2  # Middle of the bar

        ax.text(bar.get_x() + bar.get_width() / 2.,
                y_pos,
                f"{values[i]:.2f}%",
                color="black",
                fontweight="light",
                fontsize=10,
                ha="center",
                va="bottom"
                if height >= 0 else "top")

    # Add a horizontal line at y=0
    ax.axhline(y=0, color="black", linestyle="-", alpha=0.3)

    # Set labels and title
    ax.set_xticks(range(len(metrics)))
    ax.set_xticklabels([metric_labels[m] for m in metrics],
                       rotation=30,
                       ha="right")
    ax.set_ylabel("Porcentual Change (%)")
    ax.set_title(title, fontsize=14, fontweight="bold", pad=20)

    # Add grid lines for better readability
    ax.grid(axis="y", linestyle="--", alpha=0.7)

    # Set y-axis limit to provide some padding
    y_min = min(min(values) * 1.1, -2)  # At least -2% or 10% below minimum
    y_max = max(max(values) * 1.1, 2)   # At least 2% or 10% above maximum
    ax.set_ylim(y_min, y_max)

    # Add a legend directly in the plot area
    legend_elements = [
        plt.Rectangle((0, 0),
                      1, 1,
                      facecolor=_green,
                      alpha=0.8,
                      label="Improvement"),
        plt.Rectangle((0, 0),
                      1, 1,
                      facecolor=_red,
                      alpha=0.8,
                      label="Degradation")
    ]
    ax.legend(handles=legend_elements, loc="best")

    # Add some padding at the bottom for the rotated labels
    plt.subplots_adjust(bottom=0.15)

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
            fig.savefig(full_file_path,
                        facecolor="white",
                        bbox_inches="tight",
                        dpi=300)    # format="png")  # Explicitly set format
            print(f"Plot saved successfully to: {full_file_path}")
        except Exception as e:
            _msg = f"Error saving plot: {e}.\n"
            _msg += "File path or file name not provided, skipping save. "
            _msg += f"{_msg} file_path: {file_path}, fname: {fname}"
            raise ValueError(_msg)
    plt.show()
    plt.close()
    # plt.clf()
    # plt.cla()


# Add this function to your plots.py file
def plot_nodes_heatmap(delta_metrics: pd.DataFrame,
                       nodes: list[str],
                       metrics: list[str] = None,
                       labels: list[str] = None,
                       title: str = None,
                       cname: str = "name",
                       file_path: str = None,
                       fname: str = None) -> None:
    """Plot a heatmap of node metrics.

    Args:
        delta_metrics (pd.DataFrame): DataFrame containing the metrics to compare.
        nodes (list[str]): List of node names to include in the heatmap.
        metrics (list[str], optional): List of metric column names to include. Defaults to all numeric columns.
        labels (list[str], optional): Custom labels for the metrics. Defaults to metric names.
        title (str, optional): Title of the plot. Defaults to "Node Metrics Heatmap".
        cname (str, optional): Column name containing node names. Defaults to "name".
        file_path (str, optional): Directory path to save the plot. Defaults to None.
        fname (str, optional): Filename to save the plot. Defaults to None.

    Raises:
        ValueError: If the specified nodes or metrics are not found in the DataFrame.
        ValueError: If the plot cannot be saved.
    """
    # Setting default values
    if metrics is None:
        # Select only numeric columns if metrics not specified
        metrics = delta_metrics.select_dtypes(include="number").columns.tolist()

    if labels is None:
        labels = metrics

    if title is None:
        title = "Metrics Heatmap"

    # Check if the node name column exists
    if cname not in delta_metrics.columns:
        raise ValueError(f"Node name column '{cname}' not found in DataFrame")

    # Check if all metric columns are in the dataframe
    if not set(metrics).issubset(delta_metrics.columns):
        missing_cols = set(metrics) - set(delta_metrics.columns)
        _msg = f"Missing metric columns in DataFrame: {missing_cols}"
        raise ValueError(_msg)

    # First filter by node names
    node_filter = delta_metrics[cname].isin(nodes)
    filtered_data = delta_metrics[node_filter]

    # if filtered_data.empty:
    #     available_nodes = delta_metrics[cname].unique()
    #     raise ValueError(f"No matching nodes found. Available nodes: {available_nodes}, Requested: {nodes}")

    # Get the actual node names that were found (in case some weren't)
    found_nodes = filtered_data[cname].values
    print(f"Found {len(found_nodes)} nodes: {found_nodes}")

    # Now extract just the metric columns for the heatmap
    heatmap_data = filtered_data[metrics].values
    print(f"Heatmap data shape: {heatmap_data.shape}")

    # Create the figure and axis
    fig, ax = plt.subplots(figsize=(12, len(found_nodes) * 0.6 + 2))
    fig.set_facecolor("white")
    ax.set_facecolor("white")

    # Create a mask for NaN values
    mask = np.isnan(heatmap_data)
    # Setup the colormap with a diverging scale (coolwarm)
    # Find the maximum absolute value for symmetric color scale
    vmax = np.nanmax(np.abs(heatmap_data))
    if np.isnan(vmax) or vmax == 0:
        vmax = 1.0  # Default if no data or all zeros
    vmin = -vmax

    # Create the heatmap
    im = ax.imshow(heatmap_data,
                   cmap="PiYG",   # "RdYlGn",
                   aspect="auto",
                   vmin=vmin,
                   vmax=vmax)

    # Add colorbar
    cbar = fig.colorbar(im, ax=ax, pad=0.01)
    cbar.set_label("Relative Change (%)", rotation=270, labelpad=15)

    # Add value annotations on each cell
    for i in range(len(found_nodes)):
        for j in range(len(metrics)):
            if i < heatmap_data.shape[0] and j < heatmap_data.shape[1]:
                if mask[i, j]:
                    # Skip NaN values
                    continue

                value = heatmap_data[i, j]
                text_color = "black"

                # Format text based on value
                if abs(value) >= 0.1:  # For significant values
                    text = f"{value:.2f}"
                else:
                    text = f"{value:.3f}"

                ax.text(j, i, text,
                        ha="center", va="center",
                        color=text_color, fontweight="bold")

    # Set tick labels
    ax.set_xticks(np.arange(len(metrics)))
    ax.set_yticks(np.arange(len(found_nodes)))
    ax.set_xticklabels(labels, rotation=45, ha="right")
    ax.set_yticklabels(found_nodes)

    # Add grid lines for better readability
    ax.set_xticks(np.arange(-.5, len(metrics), 1), minor=True)
    ax.set_yticks(np.arange(-.5, len(found_nodes), 1), minor=True)
    ax.grid(which="minor", color="w", linestyle="-", linewidth=2)

    # Add title and labels
    ax.set_title(title, fontsize=14, fontweight="bold", pad=20)

    # # Add a legend explaining color coding
    # ax.text(len(metrics) - 1, len(found_nodes) + 0.5,
    #         "Blue: Improvement, Red: Degradation",
    #         ha="right",
    #         va="center",
    #         fontsize=10,
    #         bbox=dict(facecolor="white",
    #                   alpha=0.8,
    #                   edgecolor="gray"))

    # Ensure tight layout
    fig.tight_layout()

    # Save with white background if needed
    if file_path and fname:
        # Create directory if it doesn't exist
        os.makedirs(file_path, exist_ok=True)

        # Construct full file path
        full_file_path = os.path.join(file_path, fname)

        print(f"Saving plot to: {full_file_path}")
        try:
            fig.savefig(full_file_path,
                        facecolor="white",
                        bbox_inches="tight",
                        dpi=300)
            print(f"Plot saved successfully to: {full_file_path}")
        except Exception as e:
            _msg = f"Error saving plot: {e}.\n"
            _msg += "File path or file name not provided, skipping save. "
            _msg += f"{_msg} file_path: {file_path}, fname: {fname}"
            raise ValueError(_msg)

    plt.show()
    plt.close()

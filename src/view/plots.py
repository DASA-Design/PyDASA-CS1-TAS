# Standard library imports
import os

# Third-party imports
import numpy as np
import pandas as pd
import seaborn as sns
import networkx as nx
import matplotlib.pyplot as plt

# for plotting refined dimensionless chart
from matplotlib.colors import LinearSegmentedColormap
# from scipy.stats import binned_statistic_2d
import matplotlib.ticker as ticker

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


# Define the colors for the custom colormap (e.g., blue, white, red)
COLORS = ["dodgerblue", "gold", "crimson"]


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
    edge_lbl = {(i, j): f"{rout_matrix[i, j]:.2f}"
                for i, j in G.edges() if rout_matrix[i, j] > 0.01}
    nx.draw_networkx_edge_labels(G,
                                 pos,
                                 edge_labels=edge_lbl,
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
            f"{nd_metrics['mu'].iloc[i]:.2f}",
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
        mt = f"$\\overline{{{{\\mu}}}}: {net_metrics['avg_mu'].iloc[0]:.2f}$"
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
    metric_lbl = dict(zip(metrics, labels))

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
    ax.set_xticklabels([metric_lbl[m] for m in metrics],
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
        names (list[str]): List of names for the different states being compared.
        metrics (list[str], optional): List of metrics to include in the comparison. Defaults to None.
        labels (list[str], optional): List of labels for the metrics. Defaults to None.
        title (str, optional): Title of the plot. Defaults to None.
        file_path (str, optional): Directory path to save the plot. Defaults to None.
        fname (str, optional): File name for the saved plot. Defaults to None.

    Raises:
        ValueError: If the plot cannot be saved.
    """
    # Validate inputs
    if not isinstance(net_metrics, list) or len(net_metrics) == 0:
        _msg = "net_metrics must be a non-empty list of DataFrames"
        raise ValueError(_msg)

    if not isinstance(names, list) or len(names) != len(net_metrics):
        _msg = "names must be a list with same length as net_metrics"
        raise ValueError(_msg)

    # Setting default values
    if metrics is None:
        # Select only numeric columns if metrics not specified
        metrics = net_metrics[0].select_dtypes(include="number")
        metrics = metrics.columns.tolist()

    if labels is None:
        labels = metrics

    if title is None:
        title = "Network Metrics Comparison"

    # Create figure and axis
    fig, ax = plt.subplots(figsize=(max(12, len(metrics) * 1.5), 8))
    fig.set_facecolor("white")
    ax.set_facecolor("white")

    # Total width for each group of bars
    group_w = 1.2

    # Width of each individual bar (make this smaller for thinner bars)
    # Halved to make thinner bars
    bar_w = group_w / (len(net_metrics) * 1.3)

    # Spacing between bars within a group (increase for more space)
    bar_space = bar_w * 0.2  # 20% of bar width

    # Calculate spacing between metric groups (increased for more separation)
    group_space = 1.5  # Larger value = more space between metric groups

    # Set position of bars on X axis with wider spacing between groups
    positions = []
    for i in range(len(net_metrics)):
        if i == 0:
            # First bar in each group starts at group_space * index
            positions.append([j * group_space for j in range(len(metrics))])
        else:
            # Next bars positioned with spacing between them
            positions.append([x + bar_w + bar_space for x in positions[i - 1]])

    # Define colormap for consistent colors
    cmap = plt.cm.get_cmap("tab10", len(net_metrics))
    # cmap = ['#e63946', '#4895ef']  # Bright red to calm blue

    # Make the plot
    for i, (df, name) in enumerate(zip(net_metrics, names)):
        # Extract values - ensure we use only existing metrics
        values = []
        for m in metrics:
            if m in df.columns:
                values.append(df[m].iloc[0])
            else:
                values.append(np.nan)

        # Plot bars
        ax.bar(
            positions[i],
            values,
            width=bar_w,
            label=name,
            color=cmap(i),
            alpha=0.85,
            edgecolor="black",
            linewidth=0.5
        )

        # Add value annotations on top of bars
        for j, value in enumerate(values):
            if not np.isnan(value):
                if abs(value) < 0.01:
                    text = f"{value:.2e}"   # Scientific for very small values
                elif abs(value) < 1:
                    text = f"{value:.3f}"   # 3 decimals for small values
                elif abs(value) > 10000:
                    text = f"{value:.2e}"   # Scientific for very large values
                else:
                    text = f"{value:.2f}"   # 2 decimals for normal values

                # POSITIONING LOGIC: Inside bar for values >= 1, on top for values < 1
                text_color = "black"  # Black text inside colored bar
                if abs(value) >= 1:  # Large values - place text INSIDE the bar
                    if value > 0:
                        y_pos = float(value / 3)  # Middle of the bar
                        va_pos = "center"
                        bbox_props = None
                    else:
                        # For negative values, still place on top since inside would be below axis
                        y_pos = float(value * 1.05)
                        va_pos = "top"
                        bbox_props = dict(boxstyle="round,pad=0.2",
                                          fc="white",
                                          ec="none",
                                          alpha=0.7)
                else:  # Small values - place text ON TOP of the bar
                    if value > 0:
                        y_pos = float(value * 1.1)  # 10% above bar
                        va_pos = "bottom"
                    else:
                        y_pos = float(value * 1.1)  # 10% below for negative
                        va_pos = "top"
                    bbox_props = dict(boxstyle="round,pad=0.2",
                                      fc="white",
                                      ec="none",
                                      alpha=0.7)

                # Add text annotation with smart positioning
                ax.text(positions[i][j],
                        y_pos,
                        text,
                        ha="center",
                        va=va_pos,
                        fontsize=12,
                        rotation=90,
                        fontweight="light",
                        color=text_color,
                        bbox=bbox_props)

    # Add a horizontal line at y=0
    ax.axhline(y=0, color="black", linestyle="-", alpha=0.6)
    # Set y-axis to log scale
    ax.set_yscale("log")
    # Add labels, title and axis ticks
    # ax.set_xlabel("Metrics", fontweight="bold", labelpad=10)
    ax.set_ylabel("Values (Log scale)", fontweight="bold")
    ax.set_title(title, fontsize=14, fontweight="bold", pad=20)

    # Set the position of the x ticks - centered for each metric group
    # INSANE LIST COMPREHENSION!!!
    center_positions = [positions[0][i] + (positions[-1][i] - positions[0][i]) / 2 for i in range(len(metrics))]

    ax.set_xticks(center_positions)
    ax.set_xticklabels(labels, rotation=30, ha="right")

    # Add grid for better readability
    ax.grid(axis="y", linestyle="--", alpha=0.7)

    # Add legend
    ax.legend(loc="upper center",
              frameon=True,
              fancybox=True,
              shadow=True)

    # Add some padding at the bottom for the rotated labels
    plt.subplots_adjust(bottom=0.15)

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
            _msg += f"File path: {file_path}, fname: {fname}"
            raise ValueError(_msg)

    plt.show()
    plt.close(fig)


def plot_nodes_diffmap(delta_metrics: pd.DataFrame,
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
                   cmap="viridis",   # "RdYlGn",
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


def plot_nodes_heatmap(net_metrics: list[pd.DataFrame],
                       names: list[str],
                       nodes: list[str],
                       metrics: list[str] = None,
                       labels: list[str] = None,
                       title: str = None,
                       cname: str = "name",
                       file_path: str = None,
                       fname: str = None) -> None:
    """*plot_nodes_heatmap()* plot a heatmap comparing metrics across multiple configurations for each component in the system.

    Args:
        net_metrics (list[pd.DataFrame]): List of DataFrames containing metrics
        names (list[str]): Names for each DataFrame in the list
        nodes (list[str]): List of node names to include in the heatmap
        metrics (list[str], optional): List of metrics to compare. Defaults to all numeric columns.
        labels (list[str], optional): Custom labels for the metrics. Defaults to metric names.
        title (str, optional): Title of the plot. Defaults to "Node Metrics Heatmap Comparison".
        cname (str, optional): Column name containing node names. Defaults to "name".
        file_path (str, optional): Directory path to save the plot. Defaults to None.
        fname (str, optional): Filename to save the plot. Defaults to None.

    Raises:
        ValueError: if net metrics is empty or is not a list.
        ValueError: if names is empty or does not match net metrics.
    """

    # Input validation
    if not isinstance(net_metrics, list) or len(net_metrics) == 0:
        _msg = f"Invalid type input: {type(net_metrics)}"
        _msg += " - net_metrics must be a non-empty list of DataFrames"
        raise ValueError(_msg)

    if not isinstance(names, list) or len(names) != len(net_metrics):
        _msg = f"Names list length ({len(names)}) "
        _msg += f"must match DataFrames list length ({len(net_metrics)})"
        raise ValueError(_msg)

    # Setting default values
    if metrics is None:
        metrics = net_metrics[0].select_dtypes(include="number")
        metrics = metrics.columns.tolist()
        if "node" in metrics:
            metrics.remove("node")

    if labels is None:
        labels = metrics

    if title is None:
        title = "Node Metrics Heatmap Comparison"

    n_configs = len(net_metrics)
    fig, axes = plt.subplots(n_configs,
                             1,
                             figsize=(12, 4 * n_configs),
                             sharex=True,
                             constrained_layout=True)
    if n_configs == 1:
        axes = [axes]

    # Calculate per-metric min/max across all configs and nodes
    metric_minmax = {}
    for metric in metrics:
        vals = []
        for df in net_metrics:
            df = df[df[cname].isin(nodes)]
            df = df[metric].dropna().values
            vals.extend(df)
            # vals.extend(df[df[cname].isin(nodes)][metric].dropna().values)
        metric_minmax[metric] = (np.min(vals), np.max(vals))

    # OLD colormap
    # colors = [(0, 0, 0.9), (1, 1, 1), (0.9, 0, 0)]
    # cmap = LinearSegmentedColormap.from_list('BlueWhiteRed', colors, N=100)
    # CURRENT colormap
    cmap = "viridis"

    # for i, (df, name, ax) in enumerate(zip(net_metrics, names, axes)):
    for df, name, ax in zip(net_metrics, names, axes):
        node_filter = df[cname].isin(nodes)
        filtered_df = df[node_filter].copy()
        if filtered_df.empty:
            ax.text(0.5,
                    0.5,
                    f"No data for {name}",
                    ha="center",
                    fontsize=14)
            # continue

        plot_data = []
        for node in nodes:
            if node in filtered_df[cname].values:
                node_row = filtered_df[filtered_df[cname] == node]
                row_data = [node]
                for metric in metrics:
                    if metric in node_row.columns:
                        val = node_row[metric].iloc[0]
                        row_data.append(val)
                    else:
                        row_data.append(np.nan)
                plot_data.append(row_data)
        if not plot_data:
            ax.text(0.5,
                    0.5,
                    f"No matching nodes found for {name}",
                    ha="center",
                    fontsize=14)
            # continue

        plot_df = pd.DataFrame(plot_data, columns=[cname] + metrics)
        plot_df.set_index(cname, inplace=True)

        # Normalize each column independently
        norm_df = plot_df.copy()
        for metric in metrics:
            min_val, max_val = metric_minmax[metric]
            if max_val > min_val:
                _range = max_val - min_val
                norm_df[metric] = (plot_df[metric] - min_val) / _range
            else:
                norm_df[metric] = 0.5  # If all values are the same

        # Plot normalized heatmap
        sns.heatmap(norm_df,
                    ax=ax,
                    cmap=cmap,
                    center=0.5,
                    vmin=0,
                    vmax=1,
                    annot=plot_df,
                    fmt=".3e",
                    linewidths=0.5,
                    cbar_kws={"shrink": 0.8})

        ax.set_title(f"{name} Component Metrics", fontsize=14, pad=10)
        plt.setp(ax.get_xticklabels(),
                 rotation=45,
                 ha="right",
                 rotation_mode="anchor")
        ax.set_xticklabels(labels)

    # Add overall title
    fig.suptitle(title, fontsize=16, fontweight="bold")

    # Save figure if requested
    if file_path and fname:
        os.makedirs(file_path, exist_ok=True)
        full_file_path = os.path.join(file_path, fname)
        print(f"Saving plot to: {full_file_path}")
        try:
            fig.savefig(full_file_path, bbox_inches="tight", dpi=300)
            print(f"Plot saved successfully to: {full_file_path}")
        except Exception as e:
            raise ValueError(
                f"Error saving plot: {e}. File path: {file_path}, fname: {fname}")

    plt.show()
    plt.close(fig)


def plot_performance_coef_chart(pi_coefs: pd.DataFrame,
                                contour_lbl: str,
                                contour_vals: list[float] = None,
                                metrics: list[str] = None,
                                labels: list[str] = None,
                                title: str = None,
                                file_path: str = None,
                                fname: str = None,
                                percentile={"x": [0.05, 0.95],
                                            "y": [0.05, 0.95]},
                                scale={"x": "linear", "y": "linear"},
                                limits={"x": [0, 1], "y": [0, 1]}) -> None:
    """*plot_performance_coef_chart()* plot a performance coefficient chart for a queueing system for FDU := {'T': 'Time', 'I': 'Intensity'}.

    Args:
        pi_coefs (pd.DataFrame): DataFrame containing the performance coefficients.
        contour_lbl (str): Contour label for the chart.
        contour_vals (list[float], optional): Contour values for the chart. Defaults to None.
        metrics (list[str], optional): Metrics to plot. Defaults to None.
        labels (list[str], optional): Labels for the metrics. Defaults to None.
        title (str, optional): Title for the chart. Defaults to None.
        file_path (str, optional): File path to save the chart. Defaults to None.
        fname (str, optional): File name for the chart. Defaults to None.
        visible_pct (dict, optional): Percentage of the chart to be visible in x and y axes. Defaults to {"x": [0.05, 0.95], "y": [0.05, 0.95]}.

    Raises:
        ValueError: If the input types are incorrect.
        ValueError: If the contour label is not a string.
        ValueError: If the contour label is not in the DataFrame.
        ValueError: If the metrics and labels are not valid.
        ValueError: If the contour values are not valid.
        ValueError: If the title is not a string.
    """
    # Input validation
    if not isinstance(pi_coefs, pd.DataFrame):
        _msg = f"Invalid type input: {type(pi_coefs)}"
        _msg += " - pi_coefs must be a DataFrame"
        raise ValueError(_msg)

    # check for a string in the contour label
    if not isinstance(contour_lbl, str):
        _msg = f"Invalid type input: {type(contour_lbl)}"
        _msg += " - contour_lbl must be a string"
        raise ValueError(_msg)

    # check if the contour label is in the dataframe
    if contour_lbl not in pi_coefs.columns.tolist():
        _msg = f"Invalid contour label: {contour_lbl} "
        _msg += "is not in coefficient data, provided labels: "
        _msg += f"{pi_coefs.columns.tolist()}"
        raise ValueError(_msg)

    # Setting default numeric metric names
    if metrics is None:
        metrics = pi_coefs.select_dtypes(include="number")
        metrics = metrics.columns.tolist()
        if "node" in metrics:
            metrics.remove("node")

    # set default labels
    if labels is None:
        labels = metrics

    # check for metrics and labels to be useful
    elif not isinstance(metrics, list) or len(labels) != len(metrics):
        _msg = f"Labels list length ({len(labels)}) "
        _msg += f"must match DataFrames list length ({len(metrics)})"
        raise ValueError(_msg)

    # if contour values is none create one based on the contour label
    if contour_vals is None:
        _start = pi_coefs[contour_lbl].min()
        _end = pi_coefs[contour_lbl].max()
        contour_vals = np.linspace(_start, _end, num=10).tolist()
        print(f"Contour values not provided, using: {contour_vals}")

    # check for a list of numbers for regresion range
    elif all(not isinstance(x, (int, float)) for x in contour_vals):
        _msg = f"Invalid type input: {type(contour_vals)}"
        _msg += " - contour_vals must be a list of numbers"
        raise ValueError(_msg)

    if title is None:
        title = "System's Performance Dimensionless Chart."

    # Figure setup with appropriate size, resolution and white background
    fig, ax = plt.subplots(figsize=(16, 9), dpi=300, facecolor="white")
    ax.set_facecolor("white")

    # get x, y, and z coefficients
    pi_x = metrics[0]       # occupancy coefficient for x-axis
    pi_y = metrics[1]       # stall coefficient for y-axis
    pi_z = metrics[2]       # effectivness coefficient for z-axis, contour line
    # print(f"inside plot!!!: {pi_x}, {pi_y}, {pi_z}")
    # create color scale
    _cmap = LinearSegmentedColormap.from_list("tricolor_cmap", COLORS)
    # create color scale
    _colors = _cmap(np.linspace(0, 1, len(contour_vals)))
    # _colors = plt.cm.berlin(np.linspace(0, 1, len(contour_vals)))
    # alts: viridis_r, plasma, managua_r, magma, cividis, coolwarm, berlin

    # # Add hexbin background to show data density (like Moody chart)
    # hb = plt.hexbin(
    #     pi_coefs[pi_x],
    #     pi_coefs[pi_y],
    #     gridsize=40,
    #     cmap="Greens",    # YlGnBu, Greens, GnBu_r
    #     alpha=0.30,
    #     mincnt=1,
    #     reduce_C_function=np.mean
    # )

    # # colorbar to show point density
    # fig.colorbar(hb,
    #              ax=ax,
    #              shrink=0.8,
    #              label="Data Density")

    # Add contour legend with clear styling
    # clean label, get first symbol name
    contour_sym = f"${str(metrics[2]).split('=')[0]}$"

    # Plot characteristic curves for different utilization ranges
    for i, ctr in enumerate(contour_vals):
        # Filter data near this utilization value
        _min = (pi_coefs[pi_z] >= ctr - 0.05)
        _max = (pi_coefs[pi_z] <= ctr + 0.05)
        subset = pi_coefs[(_min & _max)]

        # Only draw if we have enough points
        # if len(subset) > int(pi_coefs.shape[0] * 0.01):
        if len(subset) > 5:
            # Sort by x-value for smooth curves
            subset = subset.sort_values(by=pi_x)

            # Create a polynomial fit at log scale
            # if len(subset) > int(pi_coefs.shape[0] * 0.001):
            if len(subset) > 3:
                log_x = np.log10(subset[pi_x])
                log_y = np.log10(subset[pi_y])
                # 3rd degree works well for most curves
                z = np.polyfit(log_x, log_y, 3)
                p = np.poly1d(z)

                # Create smooth x values for the line
                _min_log = np.log10(subset[pi_x].min())
                _max_log = np.log10(subset[pi_x].max())
                x_smooth = np.logspace(_min_log, _max_log, 50)

                # Calculate predicted y values (convert back from log space)
                y_smooth = 10**p(np.log10(x_smooth))

                # Plot the trend line
                plt.plot(x_smooth,
                         y_smooth,
                         "-",
                         linewidth=1.0,
                         alpha=0.9,
                         color=_colors[i],
                         label=f"{contour_sym} = {ctr:.2f}")

    # Set up log scales (standard for Moody-like charts)
    # ax.set_xscale("log")
    # ax.set_yscale("log")
    ax.set_xscale(scale["x"])
    ax.set_yscale(scale["y"])

    # Adjust these values as needed to get the desired range
    # Use min-percentile in y
    y_min = pi_coefs[pi_y].quantile(percentile["y"][0])
    # Use max-percentile in y
    y_max = pi_coefs[pi_y].quantile(percentile["y"][1])
    plt.ylim(y_min, y_max)

    # Use min-percentile in x
    x_min = pi_coefs[pi_x].quantile(percentile["x"][0])
    # Use max-percentile in x
    x_max = pi_coefs[pi_x].quantile(percentile["x"][1])
    plt.xlim(x_min, x_max)

    # Override with user limits if provided
    if limits["x"] != [0, 1]:
        plt.xlim(limits["x"])
    if limits["y"] != [0, 1]:
        plt.ylim(limits["y"])

    # Ensure minor ticks are displayed
    ax.minorticks_on()

    # Set up grid with both major and minor lines
    ax.grid(True,
            which="major",
            linestyle="-",
            linewidth=0.9,
            color="black",
            alpha=0.70)
    ax.grid(True,
            which="minor",
            linestyle=":",
            linewidth=0.7,
            color="black",
            alpha=0.70)

    # Format tick labels for better readability
    if scale["x"] == "log" or scale["y"] == "log":
        formatter = ticker.LogFormatterMathtext(base=10)
        if scale["x"] == "log":
            plt.gca().xaxis.set_major_formatter(formatter)
        if scale["y"] == "log":
            plt.gca().yaxis.set_major_formatter(formatter)
        # plt.gca().xaxis.set_major_formatter(formatter)
        # plt.gca().yaxis.set_major_formatter(formatter)

    # Make sure ticks and labels are black
    ax.tick_params(axis="both", colors="black")

    # # Force consistent tick locations (add this)
    # ax.xaxis.set_major_locator(ticker.LogLocator(base=10.0,
    #                                              numticks=10))
    # ax.xaxis.set_minor_locator(ticker.LogLocator(base=10.0,
    #                                              subs=np.arange(0.1, 1.0, 0.1),
    #                                              numticks=10))
    # ax.yaxis.set_major_locator(ticker.LogLocator(base=10.0,
    #                                              numticks=10))
    # ax.yaxis.set_minor_locator(ticker.LogLocator(base=10.0,
    #                                              subs=np.arange(0.1, 1.0, 0.1),
    #                                              numticks=10))

    # Add descriptive legend x-axis
    text_x = f"{labels[0]}: ${metrics[0]}$"
    plt.xlabel(text_x, fontsize=14, color="black")

    # Add descriptive legend y-axis
    text_y = f"{labels[1]}: ${metrics[1]}$"
    plt.ylabel(text_y, fontsize=14, color="black")

    # Add contour legend z-axis
    legend = plt.legend(title=f"{labels[2]}: ${metrics[2]}$",
                        loc="best",
                        fontsize=8,
                        framealpha=0.8)
    legend.get_title().set_color("black")

    # Add overall title
    plt.title(title, fontsize=16, color="black", fontweight="bold")

    # Bottom-Left (Low Y, Low X)
    # bbox syle
    _bbox_style = dict(
        facecolor="white",
        alpha=0.8,
        boxstyle="round",
        edgecolor="gray",
    )

    plt.text(
        pi_coefs[pi_x].quantile(0.05),  # X position at 5th percentile
        pi_coefs[pi_y].quantile(0.10),  # Y position at 10th percentile
        "Low Stall &\nLow Occupancy",
        fontsize=10,
        ha="left",
        va="bottom",
        color="black",
        bbox=_bbox_style
    )

    # Bottom-Right (Low Y, High X)
    plt.text(
        pi_coefs[pi_x].quantile(0.95),  # X position at 95th percentile
        pi_coefs[pi_y].quantile(0.90),  # Y position at 90th percentile
        "High Stall &\nHigh Occupancy",
        fontsize=10,
        ha="left",
        va="bottom",
        color="black",
        bbox=_bbox_style
    )

    # Save figure if requested
    if file_path and fname:
        os.makedirs(file_path, exist_ok=True)
        full_file_path = os.path.join(file_path, fname)
        print(f"Saving plot to: {full_file_path}")
        try:
            fig.savefig(full_file_path, bbox_inches="tight", dpi=300)
            print(f"Plot saved successfully to: {full_file_path}")
        except Exception as e:
            raise ValueError(
                f"Error saving plot: {e}. File path: {file_path}, fname: {fname}")

    plt.show()
    plt.close(fig)

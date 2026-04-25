﻿import matplotlib.pyplot as plt
from matplotlib import colormaps
from matplotlib import colors as mcolors
from matplotlib.figure import Figure
from matplotlib.ticker import FuncFormatter
# from mpl_toolkits.mplot3d import Axes3D
from notebooks.src.networks import find_key
import numpy as np
import os


# -- Shared formatting constants --
_GRID_STYLE = dict(
    alpha=0.5,
    color="black",
    linewidth=0.8,
    linestyle="--"
)

_GRID_STY_3D = dict(
    alpha=0.5,
    color="black",
    linewidth=0.8
)

_LBL_STYLE = dict(
    fontweight="bold",
    color="black"
)

_TICK_STYLE = dict(
    colors="black",
    which="both",
    labelsize=11
)

_TICK_STY_3D_GRID = dict(
    colors="black",
    which="both",
    labelsize=10,
    pad=8
)

_TICK_STY_3D_SINGLE = dict(
    colors="black",
    which="both",
    labelsize=11,
    pad=10
)

_LBL_STY_3D_GRID = dict(
    fontsize=13,
    labelpad=22,
    fontweight="bold",
    color="black"
)

_LBL_STY_3D_SINGLE = dict(
    fontsize=15,
    labelpad=24,
    fontweight="bold",
    color="black"
)

_LBL_STY_2D_GRID = dict(
    fontsize=12,
    labelpad=12,
    fontweight="bold",
    color="black"
)

_LBL_STY_2D_SINGLE = dict(
    fontsize=15,
    labelpad=14,
    fontweight="bold",
    color="black"
)

_K_LBL_STY_3D = dict(
    fontsize=14,
    color="black",
    fontweight="bold",
    alpha=0.95,
    ha="center",
    va="bottom"
)

_K_LBL_STY_2D = dict(
    fontsize=12,
    color="black",
    fontweight="bold",
    alpha=0.9,
    ha="center",
    va="bottom"
)

_K_BBOX = dict(
    facecolor="white",
    edgecolor="gray",
    alpha=0.8,
    pad=1.5,
    boxstyle="round,pad=0.2"
)


def _sci_tick_fmt(x: float, sig: int = 2) -> str:
    """Format tick as scientific notation with given significant figures.

    Args:
        x (float): The tick value to format.
        sig (int): Number of significant figures. Defaults to 2.

    Returns:
        str: Formatted string in scientific notation.
    """
    if x == 0:
        return "0"
    decimals = max(sig - 1, 0)
    return f"{x:.{decimals}e}"


def _style_3d_panes(ax) -> None:
    """_style_3d_panes Apply consistent styling to 3D axes panes and grids for better visibility.

    Args:
        ax (2D|3D axes): Matplotlib 3D axes object to style.
    """
    for axis in (ax.xaxis, ax.yaxis, ax.zaxis):
        axis.pane.set_facecolor("whitesmoke")
        axis.pane.set_edgecolor("black")
        axis._axinfo["grid"]["color"] = "black"
        axis._axinfo["grid"]["linewidth"] = 0.8
        axis._axinfo["grid"]["linestyle"] = "--"


def _apply_sci_format(ax,
                      axes_list: list[str] | None = None,
                      sig: int = 2) -> None:
    """Apply scientific notation formatter to specified axes.

    Args:
        ax (2D|3D axes): Matplotlib axes object.
        axes_list: List of axis names to format. Defaults to ["x", "y"]. Use ["x", "y", "z"] for 3D axes.
        sig: Number of significant figures. Defaults to 2.
    """
    if axes_list is None:
        axes_list = ["x", "y"]
    for axis_name in axes_list:
        fmt = FuncFormatter(lambda x, _, s=sig: _sci_tick_fmt(x, s))
        getattr(ax, f"{axis_name}axis").set_major_formatter(fmt)


def _apply_logscale(ax,
                    logscale: bool | list[bool],
                    axes_list: list[str] | None = None) -> None:
    """Apply log scale to axes based on a bool or list of bools.

    Args:
        ax: Matplotlib axes object.
        logscale: If a single bool, apply to all axes in axes_list. If a list of bools, apply to each axis in order. Extra entries beyond len(axes_list) are ignored.
        axes_list: Axis names. Defaults to ["x", "y"] for 2D. Use ["x", "y", "z"] for 3D.
    """
    if axes_list is None:
        axes_list = ["x", "y"]
    if isinstance(logscale, bool):
        flags = [logscale] * len(axes_list)
    else:
        flags = list(logscale)
    for axis_name, flag in zip(axes_list, flags):
        if flag:
            getattr(ax, f"set_{axis_name}scale")("log")


def _get_path_params(data: dict, path_tag: str) -> str:
    """Extract c and μ values for a path tag and return a label string.

    Args:
        data (dict): Dictionary of coefficient data.
        path_tag (str): The subscript tag for the path.

    Returns:
        str: Label like 'c=11, μ=4200' or empty string if not found.
    """
    c_key = f"c_{{{path_tag}}}"
    mu_key = f"\\mu_{{{path_tag}}}"
    c_vals = np.array(data.get(c_key, []))
    mu_vals = np.array(data.get(mu_key, []))
    parts = []

    if len(c_vals) > 0:
        unique_c = np.unique(c_vals)
        c_str = ", ".join(str(int(v)) for v in unique_c)
        parts.append(f"c={c_str}")

    if len(mu_vals) > 0:
        unique_mu = np.unique(mu_vals)
        mu_str = ", ".join(str(int(v)) for v in unique_mu)
        parts.append(f"μ={mu_str}")
    return ", ".join(parts)


def _generate_color_map(uniq_vals: list | np.ndarray) -> dict:
    """_generate_color_map Generate a vibrant color map for unique values using Matplotlib colormaps.

    Args:
        uniq_vals (list): List of unique values for which to generate colors.

    Returns:
        dict: A dictionary mapping each unique value to a hex color code.
    """
    n = len(uniq_vals)

    # Select base colormap using the registry (type-safe for linters)
    if n <= 12:
        colors = colormaps["rainbow"](np.linspace(1, 0, min(n, 12)))
    elif n <= 20:
        colors = colormaps["Spectral"](np.linspace(1, 0, n))
    else:
        colors = colormaps["turbo"](np.linspace(1, 0, n))

    # Convert RGB to HSV, boost saturation, convert back to RGB
    colors_hsv = mcolors.rgb_to_hsv(colors[:, :3])
    # colors_hsv[:, 1] = np.minimum(colors_hsv[:, 1] * 1.2, 1.0)  # Saturate
    colors_boosted = mcolors.hsv_to_rgb(colors_hsv)

    # Add alpha channel back if needed
    colors_with_alpha = np.column_stack([colors_boosted, colors[:, 3]])
    hex_colors = [mcolors.rgb2hex(c) for c in colors_with_alpha]

    return {val: hex_colors[i] for i, val in enumerate(sorted(uniq_vals))}


def _generate_marker_map(uniq_vals: list | np.ndarray) -> dict:
    """_generate_marker_map Generate a marker map for unique values.

    Args:
        uniq_vals (list): List of unique values for which to generate markers.

    Returns:
        dict: A dictionary mapping each unique value to a marker style.
    """
    markers = [
        "o",
        "s",
        "^",
        "v",
        "<",
        ">",
        "D",
        "p",
        "*",
        "h",
        "+",
        "x",
        "|",
        "_"
    ]
    ans = {
        val: markers[i % len(markers)] for i, val in enumerate(sorted(uniq_vals))
    }
    return ans


def plot_arts_distributions(title: str,
                            coeff_data: dict,
                            coeff_lbls: dict,
                            display_lbls: dict,
                            filename: str,
                            route: str,
                            verbose: bool = False) -> Figure:
    """plot_arts_distributions Plot system artifacts as a 3x3 grid of per-node coefficient distributions.

    Args:
        title (str): main title for the figure.
        coeff_data (dict): Dictionary of simulation results per node.
        coeff_lbls (dict): Dictionary mapping node acronyms to display names.
        display_lbls (dict): Dictionary mapping coefficient names (theta, sigma, eta, phi) to display labels. Defaults to standard labels.
        filename (str): Base filename for saving (without extension).
        route (str): Path where to save the files.
        verbose (bool, optional): If True, print progress messages. Defaults to False.

    Returns:
        Figure: The created figure object.
    """

    if verbose:
        print(f"Starting - {title}")

    if verbose:
        _msg = f"Received {len(coeff_data)} nodes for plotting."
        print(_msg)

    node_acronyms = list(coeff_data.keys())

    # Create figure with 3x3 grid of nodes, each containing 2x2 coefficient plots
    fig = plt.figure(figsize=(26, 26), facecolor="white")
    fig.subplots_adjust(top=0.92, bottom=0.05,
                        left=0.08, right=0.96)

    n_nodes = len(node_acronyms)
    # Calculate grid dimensions: 3 rows × m columns
    n_cols = (n_nodes + 2) // 3  # Ceiling division

    gs_main = fig.add_gridspec(3, n_cols,
                               hspace=0.45,
                               wspace=0.40,
                               figure=fig)

    n_last_row = n_nodes % 3
    last_row_idx = n_nodes // 3

    if verbose:
        _msg = f"Plotting {n_nodes} nodes in a 3×{n_cols} grid."
        print(_msg)

    # Iterate through nodes
    for nd_idx, node in enumerate(node_acronyms):
        if verbose:
            _msg = f"\t- Processing node {nd_idx + 1}/{n_nodes}: {node}"
            print(_msg)

        nd_row = nd_idx // 3
        if n_last_row != 0 and nd_row == last_row_idx:
            col_offset = (3 - n_last_row) // 2
            nd_col = (nd_idx % 3) + col_offset
        else:
            nd_col = nd_idx % 3

        nd_disp_name = coeff_lbls.get(node, node)
        nd_disp_name += f" ({node})"

        # Create 2x2 gridspec for this node's coefficients
        gs_node = gs_main[nd_row, nd_col].subgridspec(2, 2,
                                                      hspace=0.45,
                                                      wspace=0.45)

        # Get node coefficient data
        nd_coef_dict = coeff_data[node]

        # Extract the 4 derived coefficients by name matching
        derived_keys = [
            k for k in nd_coef_dict.keys() if k.startswith("\\")
        ]

        # Map coefficients by name pattern
        coeff_key_map = {}
        for key in derived_keys:
            if "theta" in key.lower() or "\\theta" in key:
                coeff_key_map["theta"] = key
            elif "sigma" in key.lower() or "\\sigma" in key:
                coeff_key_map["sigma"] = key
            elif "eta" in key.lower() or "\\eta" in key:
                coeff_key_map["eta"] = key
            elif "phi" in key.lower() or "\\phi" in key:
                coeff_key_map["phi"] = key

        # Generate vibrant colors dynamically based on coefficients found
        n_coeffs = len(coeff_key_map)
        if n_coeffs > 0:
            color_dict = _generate_color_map(list(range(n_coeffs)))
            coeff_colors = [color_dict[i] for i in range(n_coeffs)]
            mean_ln_colors = [color_dict[i] for i in range(n_coeffs)]
        else:
            coeff_colors = []
            mean_ln_colors = []

        # Create coefficient grid: 2 rows × (n_coeffs/2) columns
        n_coeffs_cols = (n_coeffs + 1) // 2  # Ceiling division
        gs_node = gs_main[nd_row, nd_col].subgridspec(2, n_coeffs_cols,
                                                      hspace=0.45,
                                                      wspace=0.45)

        # Add node title
        title_x = (nd_col + 0.5) / n_cols
        title_y = 0.98 - (nd_row * 0.33)
        fig.text(title_x,
                 title_y,
                 nd_disp_name,
                 ha="center",
                 va="top",
                 fontsize=19,
                 fontweight="bold",
                 color="black",
                 transform=fig.transFigure)

        # Plot 2×(n_coeffs/2) coefficient grid for this node
        plot_idx = 0
        coeff_names = list(coeff_key_map.keys())

        for row in range(2):
            for col in range(n_coeffs_cols):
                if plot_idx < n_coeffs:
                    ax = fig.add_subplot(gs_node[row, col])
                    ax.set_facecolor("white")

                    coeff_name = coeff_names[plot_idx]
                    coeff_key = coeff_key_map.get(coeff_name, None)

                    if coeff_key and coeff_key in nd_coef_dict:
                        data = np.array(nd_coef_dict[coeff_key])
                        color = coeff_colors[plot_idx]
                        mean_color = mean_ln_colors[plot_idx]
                        # Get label from display_lbls
                        label = display_lbls.get(coeff_name, coeff_name)

                        # Plot histogram
                        ax.hist(data,
                                bins=50,
                                color=color,
                                alpha=0.7,
                                edgecolor="black")

                        # Add mean line
                        ax.axvline(np.mean(data),   # type: ignore
                                   color=mean_color,
                                   linestyle="-",
                                   linewidth=2,
                                   label=f"Mean: {np.mean(data):.4e}")

                        # Labels and formatting
                        ax.set_xlabel(label,
                                      fontsize=13,
                                      fontweight="bold",
                                      color="black")
                        ax.set_ylabel("Frequency",
                                      fontsize=13,
                                      fontweight="bold",
                                      color="black")

                        title_text = f"Mean: {np.mean(data):.4e} |"
                        title_text += f"\nStd: {np.std(data):.4e}"
                        ax.set_title(title_text,
                                     fontsize=15,
                                     fontweight="bold",
                                     color="black")

                        ax.ticklabel_format(axis="x",
                                            style="sci",
                                            scilimits=(0, 0))
                        ax.tick_params(colors="black",
                                       which="both",
                                       labelsize=11)
                        ax.legend(loc="best",
                                  fontsize=11,
                                  framealpha=0.9)
                        ax.grid(True,
                                alpha=0.8,
                                color="black",
                                linewidth=1.0)

                        for spine in ax.spines.values():
                            spine.set_edgecolor("black")

                plot_idx += 1

    # Main title
    fig.suptitle(title,
                 color="black",
                 fontsize=25,
                 fontweight="bold",
                 y=0.995)

    # Ensure route directory exists
    os.makedirs(route, exist_ok=True)

    if verbose:
        _msg = f"Saving figures to: {route}"
        print(_msg)

    # Save figure
    svg_path = os.path.join(route, f"{filename}.svg")
    png_path = os.path.join(route, f"{filename}.png")

    plt.savefig(svg_path, format="svg", dpi=300, bbox_inches="tight")
    plt.savefig(png_path, format="png", dpi=300, bbox_inches="tight")

    if verbose:
        print(f"\t✓: {svg_path}")
        print(f"\t✓: {png_path}")
        print("Complete!!!")

    return fig


def plot_yoly_arts_behaviour(title: str,
                             coeff_data: dict,
                             coeff_lbls: dict,
                             filename: str,
                             route: str,
                             subscript: str = "",
                             paths: dict | None = None,
                             verbose: bool = False,
                             logscale: bool | list[bool] = False) -> Figure:
    """plot_yoly_arts_behaviour Plot per-node 3D yoly diagrams showing coefficient behavior.

    Args:
        title (str): main title for the figure.
        coeff_data (dict): Dictionary of simulation results per node.
        coeff_lbls (dict): Dictionary mapping node acronyms to display names.
        filename (str): Base filename for saving (without extension).
        route (str): Path where to save the files.
        subscript (str, optional): Subscript for coefficient symbols. If empty (""), uses bare symbols (e.g., \\theta). If provided, uses subscripted symbols (e.g., \\theta_{PACS}). Defaults to "".
        paths (dict, optional): Dictionary mapping path display names to their subscript tags for multi-path plotting. E.g., {"Read": "R_{PACS}", "Write": "W_{PACS}", "Overall": "PACS"}. When provided, plots one colored scatter group per path instead of grouping by (c, μ). Defaults to None.
        verbose (bool, optional): If True, print progress messages. Defaults to False.
        logscale (bool, optional): If True, use logarithmic scale for the z-axis (eta). Defaults to False.

    Returns:
        Figure: The created figure object.
    """

    if verbose:
        print(f"Starting - {title}")

    # Keep node order as provided by coeff_data
    node_acronyms = list(coeff_data.keys())

    if verbose:
        print(f"Nodes: {node_acronyms}\n")

    # Create figure with 3x3 grid of nodes, each containing a 3D yoly diagram
    fig = plt.figure(figsize=(34, 29), facecolor="white")
    fig.subplots_adjust(top=0.92, bottom=0.05,
                        left=0.02, right=0.98,
                        hspace=0.15, wspace=0.10)

    gs_main = fig.add_gridspec(3, 3, figure=fig)

    n_nodes = len(node_acronyms)
    n_last_row = n_nodes % 3
    last_row_idx = n_nodes // 3

    if verbose:
        print(f"Processing {n_nodes} nodes...")

    # Iterate through 3x3 node grid
    for nd_idx, node in enumerate(node_acronyms):
        if verbose:
            print(f"\t- Processing node {nd_idx + 1}/{n_nodes}: {node}")

        nd_row = nd_idx // 3
        if n_last_row != 0 and nd_row == last_row_idx:
            col_offset = (3 - n_last_row) // 2
            nd_col = (nd_idx % 3) + col_offset
        else:
            nd_col = nd_idx % 3

        nd_disp_name = coeff_lbls.get(node, node)
        nd_disp_name += f" ({node})"

        # Create subplot for this node
        ax = fig.add_subplot(gs_main[nd_row, nd_col], projection="3d")
        ax.set_facecolor("white")

        # Get node-specific coefficient data from coeff_data
        nd_coef_dict = coeff_data.get(node, {})

        # Determine whether to use multi-path or single-subscript mode
        plot_success = False
        has_legend = False

        if paths:
            # Multi-path mode: plot one scatter group per path
            path_names = list(paths.keys())
            color_map = _generate_color_map(path_names)
            marker_map = _generate_marker_map(path_names)
            lbl_K_vals = set()
            has_legend = False

            for path_name, path_tag in paths.items():
                theta_key = f"\\theta_{{{path_tag}}}"
                sigma_key = f"\\sigma_{{{path_tag}}}"
                eta_key = f"\\eta_{{{path_tag}}}"
                K_key = f"K_{{{path_tag}}}"

                coeff_keys = [theta_key, sigma_key, eta_key]
                if not all(k in nd_coef_dict for k in coeff_keys):
                    if verbose:
                        msg = "\t\t✗ Missing coefficients for path "
                        msg += f"'{path_name}' ({path_tag}) in node '{node}'"
                        print(msg)
                    continue

                x = np.array(nd_coef_dict[theta_key])
                y = np.array(nd_coef_dict[sigma_key])
                z = np.array(nd_coef_dict[eta_key])
                K_data = np.array(nd_coef_dict.get(K_key, []))

                color = color_map.get(path_name, "black")
                marker = marker_map.get(path_name, "o")

                # Build legend label with c/μ params
                params = _get_path_params(nd_coef_dict, path_tag)
                path_lbl = (f"{path_name} ({params})" if params else path_name)

                if len(K_data) > 0:
                    unique_K = np.unique(K_data)
                    K_ends = {unique_K[0], unique_K[-1]}
                    z_range = float(z.max() - z.min()) if len(z) > 0 else 1
                    z_off = z_range * 0.05
                    first_K = True
                    for K_val in unique_K:
                        mask = np.abs(K_data - K_val) < 0.1
                        if not np.any(mask):
                            continue

                        label = path_lbl if first_K else None
                        first_K = False

                        ax.scatter(x[mask],
                                   y[mask],
                                   z[mask],   # type: ignore
                                   c=color,
                                   marker=marker,
                                   s=20,
                                   alpha=0.6,
                                   edgecolors="black",
                                   linewidths=0.1,
                                   label=label,
                                   rasterized=True)

                        if (K_val in K_ends and K_val not in lbl_K_vals):
                            mask_idx = np.where(mask)[0]
                            if len(mask_idx) > 0:
                                end_idx = mask_idx[-1]
                                ax.text(x[end_idx],
                                        y[end_idx],
                                        z[end_idx] + z_off,
                                        f"K={int(K_val)}",
                                        **_K_LBL_STY_3D,    # type: ignore
                                        bbox=_K_BBOX)
                                lbl_K_vals.add(K_val)
                else:
                    ax.scatter(x, y, z,   # type: ignore
                               c=color,
                               marker=marker,
                               s=20,
                               alpha=0.6,
                               edgecolors="black",
                               linewidths=0.1,
                               label=path_lbl,
                               rasterized=True)

                has_legend = True
                plot_success = True

                if verbose:
                    print(f"\t\t✓ Path '{path_name}' plotted ({len(x)} pts)")

        else:
            # Single-subscript mode (original behaviour)
            if subscript:
                coeff_key_map = {
                    "theta": f"\\theta_{{{subscript}}}",
                    "sigma": f"\\sigma_{{{subscript}}}",
                    "eta": f"\\eta_{{{subscript}}}"
                }
            else:
                coeff_key_map = {
                    "theta": f"\\theta_{{{node}}}",
                    "sigma": f"\\sigma_{{{node}}}",
                    "eta": f"\\eta_{{{node}}}"
                }

            theta_key = coeff_key_map["theta"]
            sigma_key = coeff_key_map["sigma"]
            eta_key = coeff_key_map["eta"]
            coef_keys = [theta_key, sigma_key, eta_key]

            if all(key in nd_coef_dict for key in coef_keys):
                x_data = np.array(nd_coef_dict[theta_key])
                y_data = np.array(nd_coef_dict[sigma_key])
                z_data = np.array(nd_coef_dict[eta_key])

                if subscript:
                    c_key = f"c_{{{subscript}}}"
                    mu_key = f"\\mu_{{{subscript}}}"
                    K_key = f"K_{{{subscript}}}"
                else:
                    c_key = f"c_{{{node}}}"
                    mu_key = f"\\mu_{{{node}}}"
                    K_key = f"K_{{{node}}}"

                c_data = np.array(nd_coef_dict.get(c_key, []))
                mu_data = np.array(nd_coef_dict.get(mu_key, []))
                K_data = np.array(nd_coef_dict.get(K_key, []))

                if len(c_data) > 0 and len(mu_data) > 0 and len(K_data) > 0:
                    unique_c = np.unique(c_data)
                    unique_mu = np.unique(mu_data)
                    unique_K = np.unique(K_data)
                    z_range = float(z_data.max() - z_data.min()) if len(z_data) > 0 else 1
                    z_off = z_range * 0.05

                    color_map = _generate_color_map(unique_c)
                    marker_map = _generate_marker_map(unique_mu)

                    lbl_combos = set()
                    lbl_K_vals = set()

                    for c_val in unique_c:
                        for mu_val in unique_mu:
                            for K_val in unique_K:
                                con_1 = np.abs(c_data - c_val) < 0.1
                                con_2 = np.abs(mu_data - mu_val) < 0.1
                                con_3 = np.abs(K_data - K_val) < 0.1
                                mask = con_1 & con_2 & con_3
                                if not np.any(mask):
                                    continue

                                combo_key = (c_val, mu_val)
                                if combo_key not in lbl_combos:
                                    label = (f"c={int(c_val)}, "
                                             f"μ={int(mu_val)}")
                                    lbl_combos.add(combo_key)
                                else:
                                    label = None

                                color = color_map.get(c_val, "black")
                                marker = marker_map.get(mu_val, "o")

                                ax.scatter(x_data[mask],
                                           y_data[mask],
                                           z_data[mask],  # type: ignore
                                           c=color,
                                           marker=marker,
                                           s=20,
                                           alpha=0.6,
                                           edgecolors="black",
                                           linewidths=0.1,
                                           label=label,
                                           rasterized=True)

                                if K_val not in lbl_K_vals:
                                    mask_idx = np.where(mask)[0]
                                    if len(mask_idx) > 0:
                                        end_idx = mask_idx[-1]
                                        ax.text(
                                            x_data[end_idx],
                                            y_data[end_idx],
                                            z_data[end_idx] + z_off,
                                            f"K={int(K_val)}",
                                            **_K_LBL_STY_3D,  # type: ignore
                                            bbox=_K_BBOX)
                                        lbl_K_vals.add(K_val)

                    has_legend = len(lbl_combos) > 0
                    plot_success = True

                    if verbose:
                        print(f"\t✓ {node} plotted successfully")

        # Configure axes and title for successful plots
        if plot_success:
            if subscript:
                theta_lbl = f"Occupancy ($\\theta_{{{subscript}}}$)"
                sigma_lbl = f"Stall ($\\sigma_{{{subscript}}}$)"
                eta_lbl = f"Effective-Yield ($\\eta_{{{subscript}}}$)"
            else:
                theta_lbl = "Occupancy ($\\theta$)"
                sigma_lbl = "Stall ($\\sigma$)"
                eta_lbl = "Effective-Yield ($\\eta$)"

            ax.set_xlabel(theta_lbl,
                          **_LBL_STY_3D_GRID)  # type: ignore
            ax.set_ylabel(sigma_lbl,
                          **_LBL_STY_3D_GRID)  # type: ignore
            ax.set_zlabel(eta_lbl,
                          **_LBL_STY_3D_GRID)  # type: ignore

            _apply_logscale(ax, logscale, ["x", "y", "z"])

            ax.view_init(elev=25, azim=105)
            _style_3d_panes(ax)
            ax.grid(True, **_GRID_STY_3D)  # type: ignore

            _apply_sci_format(ax, ["x", "y", "z"])
            ax.tick_params(axis="x", **_TICK_STY_3D_GRID)  # type: ignore
            ax.tick_params(axis="y", **_TICK_STY_3D_GRID)  # type: ignore
            ax.tick_params(axis="z",    # type: ignore
                           **_TICK_STY_3D_GRID)  # type: ignore

            ax.set_title(nd_disp_name,
                         fontsize=19, **_LBL_STYLE, pad=10)  # type: ignore

            if has_legend:
                ax.legend(loc="upper left", fontsize=11, framealpha=0.9)
        else:
            # No data to plot — show message
            msg = (f"No coefficients for {node}" if not paths else f"No path data for {node}")
            ax.text(0.5, 0.5, 0.5,
                    msg,
                    ha="center",
                    va="center",
                    fontsize=13,
                    color="black")
            ax.set_title(nd_disp_name,
                         fontsize=19,
                         fontweight="bold",
                         color="black",
                         pad=10)
            if verbose:
                print(f"\t✗ {msg}")

    # Main title
    fig.suptitle(title,
                 color="black",
                 fontsize=27,
                 fontweight="bold",
                 y=0.995)

    # Ensure route directory exists
    os.makedirs(route, exist_ok=True)

    if verbose:
        _msg = f"Saving figures to: {route}"
        print(_msg)

    # Save figure
    svg_path = os.path.join(route, f"{filename}.svg")
    png_path = os.path.join(route, f"{filename}.png")

    plt.savefig(svg_path, format="svg", dpi=300, bbox_inches="tight")
    plt.savefig(png_path, format="png", dpi=300, bbox_inches="tight")

    if verbose:
        print(f"\t✓: {svg_path}")
        print(f"\t✓: {png_path}")
        print("Complete!!!")

    return fig


def plot_yoly_arts_charts(title: str,
                          coeff_data: dict,
                          coeff_lbls: dict,
                          filename: str,
                          route: str,
                          subscript: str = "",
                          paths: dict | None = None,
                          verbose: bool = False,
                          logscale: bool | list[bool] = False) -> Figure:
    """plot_yoly_arts_charts Plot per-node 2D yoly diagrams in a 3x3 grid with 2x2 subplots.

    Args:
        title (str): main title for the figure.
        coeff_data (dict): Dictionary of simulation results per node.
        coeff_lbls (dict): Dictionary mapping node acronyms to display names.
        filename (str): Base filename for saving (without extension).
        route (str): Path where to save the files.
        subscript (str, optional): Subscript for coefficient symbols. If empty (""), uses node-based keys (e.g., \\theta_{100R}). If provided, uses subscripted symbols (e.g., \\theta_{PACS}). Defaults to "".
        paths (dict, optional): Dictionary mapping path display names to their subscript tags for multi-path plotting. E.g., {"Read": "R_{PACS}", "Write": "W_{PACS}", "Overall": "PACS"}. When provided, plots one colored scatter group per path instead of grouping by (c, μ). Defaults to None.
        verbose (bool, optional): If True, print progress messages. Defaults to False.
        logscale (bool, optional): If True, use logarithmic scale for the y-axis. Defaults to False.

    Returns:
        Figure: The created figure object.
    """

    if coeff_data is None:
        if verbose:
            print("ERROR: data is not available")
        return None

    if verbose:
        print(f"Starting - {title}")

    # Keep node order as provided by coeff_data
    node_acronyms = list(coeff_data.keys())

    if verbose:
        print(f"Nodes with keys: {node_acronyms}\n")

    # Create figure with 3x3 grid of nodes, each containing 2x2 coefficient plane grid
    fig = plt.figure(figsize=(34, 29), facecolor="white")

    fig.subplots_adjust(top=0.92, bottom=0.05,
                        left=0.06, right=0.96,
                        hspace=0.35, wspace=0.30)

    gs_main = fig.add_gridspec(3, 3, figure=fig)

    n_nodes = len(node_acronyms)
    n_last_row = n_nodes % 3
    last_row_idx = n_nodes // 3

    # Plot titles and labels for 2x2 grid
    plot_titles = [
        "$\\theta$ vs $\\sigma$",
        "$\\theta$ vs $\\eta$",
        "$\\sigma$ vs $\\eta$",
        "$\\theta$ vs $\\phi$"
    ]

    x_lbls = [
        "Occupancy ($\\theta$)",
        "Occupancy ($\\theta$)",
        "Stall ($\\sigma$)",
        "Occupancy ($\\theta$)"
    ]

    y_lbls = [
        "Stall ($\\sigma$)",
        "Effective-Yield ($\\eta$)",
        "Effective-Yield ($\\eta$)",
        "Memory-Use ($\\phi$)"
    ]

    # Iterate through 3x3 node grid
    for nd_idx, node in enumerate(node_acronyms):
        nd_row = nd_idx // 3
        if n_last_row != 0 and nd_row == last_row_idx:
            col_offset = (3 - n_last_row) // 2
            nd_col = (nd_idx % 3) + col_offset
        else:
            nd_col = nd_idx % 3

        nd_disp_name = coeff_lbls.get(node, node)
        nd_disp_name += f" ({node})"

        if verbose:
            print(f"[{node}] Creating 2x2 coefficient plane grid...")

        # Create 2x2 gridspec for this node's coefficient planes
        gs_node = gs_main[nd_row, nd_col].subgridspec(2, 2,
                                                      hspace=0.45,
                                                      wspace=0.45)

        # Get node coefficient data
        nd_coef_dict = coeff_data[node]

        plot_success = False

        if paths:
            # Multi-path mode: one colored group per path
            path_names = list(paths.keys())
            color_map = _generate_color_map(path_names)
            marker_map = _generate_marker_map(path_names)

            # Collect per-path data arrays
            path_data = {}
            for path_name, path_tag in paths.items():
                t = np.array(nd_coef_dict.get(f"\\theta_{{{path_tag}}}", []))
                s = np.array(nd_coef_dict.get(f"\\sigma_{{{path_tag}}}", []))
                e = np.array(nd_coef_dict.get(f"\\eta_{{{path_tag}}}", []))
                p = np.array(nd_coef_dict.get(f"\\phi_{{{path_tag}}}", []))
                K = np.array(nd_coef_dict.get(f"K_{{{path_tag}}}", []))
                if len(t) > 0 and len(s) > 0 and len(e) > 0:
                    path_data[path_name] = {
                        "theta": t,
                        "sigma": s,
                        "eta": e,
                        "phi": p,
                        "K": K
                    }

            if path_data:
                plot_idx = 0
                for row in range(2):
                    for col in range(2):
                        ax = fig.add_subplot(gs_node[row, col])
                        ax.set_facecolor("white")

                        has_legend = False
                        lbl_K_vals = set()

                        for path_name, pd_ in path_data.items():
                            # Select x/y data pair for this subplot
                            pairs = [
                                (pd_["theta"], pd_["sigma"]),
                                (pd_["theta"], pd_["eta"]),
                                (pd_["sigma"], pd_["eta"]),
                                (pd_["theta"], pd_["phi"])
                            ]
                            x_arr, y_arr = pairs[plot_idx]

                            if len(x_arr) == 0 or len(y_arr) == 0:
                                continue

                            color = color_map.get(path_name, "black")
                            marker = marker_map.get(path_name, "o")
                            K_data = pd_["K"]

                            # Build legend label with c/μ params
                            path_tag = paths[path_name]
                            params = _get_path_params(
                                nd_coef_dict, path_tag)
                            path_lbl = (f"{path_name} ({params})" if params else path_name)

                            if len(K_data) > 0:
                                unique_K = np.unique(K_data)
                                K_ends = {unique_K[0], unique_K[-1]}
                                y_range = (float(y_arr.max() - y_arr.min()) if len(y_arr) > 0 else 1)
                                y_off = y_range * 0.04
                                first_K = True
                                for K_val in unique_K:
                                    mask = np.abs(K_data - K_val) < 0.1
                                    if not np.any(mask):
                                        continue

                                    label = path_lbl if first_K else None
                                    first_K = False

                                    ax.scatter(x_arr[mask],
                                               y_arr[mask],
                                               c=color,
                                               marker=marker,
                                               s=20,
                                               alpha=0.6,
                                               edgecolors="black",
                                               linewidths=0.1,
                                               label=label,
                                               rasterized=True)

                                    if (K_val in K_ends and K_val not in lbl_K_vals):
                                        mask_idx = np.where(mask)[0]
                                        if len(mask_idx) > 0:
                                            end = mask_idx[-1]
                                            ax.text(float(x_arr[end]),
                                                    float(y_arr[end]) + y_off,
                                                    f"K={int(K_val)}",
                                                    **_K_LBL_STY_2D,  # type: ignore
                                                    bbox=_K_BBOX)
                                            lbl_K_vals.add(K_val)
                            else:
                                ax.scatter(x_arr,
                                           y_arr,
                                           c=color,
                                           marker=marker,
                                           s=20,
                                           alpha=0.6,
                                           edgecolors="black",
                                           linewidths=0.1,
                                           label=path_lbl,
                                           rasterized=True)

                            has_legend = True

                        # Grid and styling
                        ax.grid(True, **_GRID_STYLE)  # type: ignore
                        ax.tick_params(**_TICK_STYLE)  # type: ignore
                        for spine in ax.spines.values():
                            spine.set_edgecolor("black")

                        _apply_sci_format(ax)
                        _apply_logscale(ax, logscale)

                        ax.set_xlabel(x_lbls[plot_idx],
                                      **_LBL_STY_2D_GRID)  # type: ignore
                        ax.set_ylabel(y_lbls[plot_idx],
                                      **_LBL_STY_2D_GRID)  # type: ignore
                        ax.set_title(plot_titles[plot_idx],
                                     fontsize=13,
                                     **_LBL_STYLE)  # type: ignore

                        if has_legend:
                            ax.legend(loc="best", fontsize=10, framealpha=0.85)

                        plot_idx += 1

                plot_success = True

        else:
            # Single-subscript mode (original behaviour)
            if subscript:
                coeff_key_map = {
                    "theta": f"\\theta_{{{subscript}}}",
                    "sigma": f"\\sigma_{{{subscript}}}",
                    "eta": f"\\eta_{{{subscript}}}",
                    "phi": f"\\phi_{{{subscript}}}"
                }
                c_key = f"c_{{{subscript}}}"
                mu_key = f"\\mu_{{{subscript}}}"
                K_key = f"K_{{{subscript}}}"
            else:
                coeff_key_map = {
                    "theta": f"\\theta_{{{node}}}",
                    "sigma": f"\\sigma_{{{node}}}",
                    "eta": f"\\eta_{{{node}}}",
                    "phi": f"\\phi_{{{node}}}"
                }
                c_key = f"c_{{{node}}}"
                mu_key = f"\\mu_{{{node}}}"
                K_key = f"K_{{{node}}}"

            theta_data = np.array(nd_coef_dict.get(coeff_key_map["theta"], []))
            sigma_data = np.array(nd_coef_dict.get(coeff_key_map["sigma"], []))
            eta_data = np.array(nd_coef_dict.get(coeff_key_map["eta"], []))
            phi_data = np.array(nd_coef_dict.get(coeff_key_map["phi"], []))

            c_data = nd_coef_dict.get(c_key, [])
            mu_data = nd_coef_dict.get(mu_key, [])
            K_data = nd_coef_dict.get(K_key, [])

            if hasattr(c_data, "values"):
                c_data = c_data.values
            if hasattr(mu_data, "values"):
                mu_data = mu_data.values
            if hasattr(K_data, "values"):
                K_data = K_data.values

            c_data = np.array(c_data, dtype=float)
            mu_data = np.array(mu_data, dtype=float)
            K_data = np.array(K_data, dtype=float)

            coeffs_data = [
                theta_data, sigma_data, eta_data, phi_data,
                c_data, mu_data, K_data
            ]

            if all(len(arr) > 0 for arr in coeffs_data):
                unique_c = np.unique(c_data)
                unique_mu = np.unique(mu_data)
                unique_K = np.unique(K_data)

                color_map = _generate_color_map(unique_c)
                marker_map = _generate_marker_map(unique_mu)

                if verbose:
                    print("\t✓ Coefficients extracted!")
                    _msg = f"\t✓ Unique parameters: c={list(unique_c)}, "
                    _msg += f"μ={list(unique_mu)}, K={list(unique_K)}"
                    print(_msg)
                    _msg = f"\t✓ Data points: {len(theta_data)}"
                    _msg += f" across {len(unique_c)}×{len(unique_mu)}×"
                    n = len(unique_c) * len(unique_mu) * len(unique_K)
                    _msg += f"{len(unique_K)} = {n} configurations"
                    print(_msg)

                data_pairs = [
                    (theta_data, sigma_data),
                    (theta_data, eta_data),
                    (sigma_data, eta_data),
                    (theta_data, phi_data)
                ]

                plot_idx = 0
                for row in range(2):
                    for col in range(2):
                        ax = fig.add_subplot(gs_node[row, col])
                        ax.set_facecolor("white")

                        x_data, y_data = data_pairs[plot_idx]

                        lbl_combos = set()
                        lbl_K_vals = set()
                        y_range = (float(y_data.max() - y_data.min()) if len(y_data) > 0 else 1)
                        y_off = y_range * 0.04

                        for c_val in unique_c:
                            for mu_val in unique_mu:
                                for K_val in unique_K:
                                    cond_1 = np.abs(c_data - c_val) < 0.1
                                    cond_2 = np.abs(mu_data - mu_val) < 0.1
                                    cond_3 = np.abs(K_data - K_val) < 0.1
                                    mask = cond_1 & cond_2 & cond_3
                                    if not np.any(mask):
                                        continue

                                    combo_key = (c_val, mu_val)
                                    if combo_key not in lbl_combos:
                                        label = (f"c={int(c_val)}, "
                                                 f"μ={int(mu_val)}")
                                        lbl_combos.add(
                                            combo_key)
                                    else:
                                        label = None

                                    color = color_map.get(c_val, "black")
                                    marker = marker_map.get(mu_val, "o")

                                    ax.scatter(x_data[mask],
                                               y_data[mask],
                                               c=color,
                                               marker=marker,
                                               s=20,
                                               alpha=0.6,
                                               edgecolors="black",
                                               linewidths=0.1,
                                               label=label,
                                               rasterized=True)

                                    if K_val not in lbl_K_vals:
                                        mask_idx = np.where(mask)[0]
                                        if len(mask_idx) > 0:
                                            end = mask_idx[-1]
                                            ax.text(float(x_data[end]),
                                                    float(y_data[end]) + y_off,
                                                    f"K={int(K_val)}",
                                                    **_K_LBL_STY_2D,  # type: ignore
                                                    bbox=_K_BBOX)
                                            lbl_K_vals.add(K_val)

                        # Grid and styling
                        ax.grid(True, **_GRID_STYLE)  # type: ignore
                        ax.tick_params(**_TICK_STYLE)  # type: ignore
                        for spine in ax.spines.values():
                            spine.set_edgecolor("black")

                        _apply_sci_format(ax)
                        _apply_logscale(ax, logscale)

                        ax.set_xlabel(x_lbls[plot_idx],
                                      **_LBL_STY_2D_GRID)  # type: ignore
                        ax.set_ylabel(y_lbls[plot_idx],
                                      **_LBL_STY_2D_GRID)  # type: ignore
                        ax.set_title(plot_titles[plot_idx],
                                     fontsize=13,
                                     **_LBL_STYLE)  # type: ignore

                        if lbl_combos:
                            ax.legend(loc="best", fontsize=10, framealpha=0.85)

                        plot_idx += 1

                plot_success = True

                if verbose:
                    print(f"✓ {node} plotted successfully\n")

        # Add node title above the 2x2 grid
        if plot_success:
            title_x = (nd_col + 0.5) / 3
            title_y = 0.98 - (nd_row * 0.33)
            fig.text(title_x,
                     title_y,
                     nd_disp_name,
                     ha="center",
                     va="top",
                     fontsize=17,
                     fontweight="bold",
                     color="black",
                     transform=fig.transFigure)
        else:
            if verbose:
                print(f"✗ Missing data for {node}")

    # Main title
    fig.suptitle(title, color="black", fontsize=27, fontweight="bold", y=0.995)

    # Ensure route directory exists
    os.makedirs(route, exist_ok=True)

    # Save figure
    svg_path = os.path.join(route, f"{filename}.svg")
    png_path = os.path.join(route, f"{filename}.png")

    plt.savefig(svg_path, format="svg", dpi=300, bbox_inches="tight")
    plt.savefig(png_path, format="png", dpi=300, bbox_inches="tight")

    if verbose:
        print(f"\t✓: {svg_path}")
        print(f"\t✓: {png_path}")
        print("Complete!!!")

    return fig


def plot_system_behaviour(title: str,
                          subtitle: str,
                          coeff_data: dict,
                          coeff_lbls: dict,
                          filename: str,
                          route: str,
                          paths: dict | None = None,
                          verbose: bool = False,
                          logscale: bool | list[bool] = False) -> Figure:
    """plot_system_behaviour Plot 3D Yoly diagram for queue behavior analysis.

    Args:
        title (str): main title for the figure.
        subtitle (str): subtitle for the figure.
        coeff_data (dict): Dictionary of simulation results with coefficient arrays.
        coeff_lbls (dict): Dictionary mapping coefficient keys to display labels.
        filename (str): Base filename for saving (without extension).
        route (str): Path where to save the files.
        paths (dict, optional): Dictionary mapping path display names to their subscript tags for multi-path plotting. E.g., {"Read": "R_{PACS}", "Write": "W_{PACS}", "Overall": "PACS"}. When provided, plots one colored scatter group per path instead of grouping by (c, μ). Defaults to None.
        verbose (bool, optional): If True, print progress messages. Defaults to False.
        logscale (bool, optional): If True, use logarithmic scale for the z-axis (eta). Defaults to False.

    Returns:
        Figure: The created figure object.
    """

    if verbose:
        print(f"Starting - {title}")

    # Create figure
    fig = plt.figure(figsize=(17, 14), facecolor="white")
    ax = fig.add_subplot(111, projection="3d")
    ax.set_facecolor("white")

    has_legend = False
    lbl_K_vals = set()

    if paths:
        # Multi-path mode: one colored group per path
        path_names = list(paths.keys())
        color_map = _generate_color_map(path_names)
        marker_map = _generate_marker_map(path_names)

        if verbose:
            print(f"Multi-path mode: {path_names}")

        all_z = []
        for path_name, path_tag in paths.items():
            theta_key = f"\\theta_{{{path_tag}}}"
            sigma_key = f"\\sigma_{{{path_tag}}}"
            eta_key = f"\\eta_{{{path_tag}}}"
            K_key = f"K_{{{path_tag}}}"
            coeff_keys = [theta_key, sigma_key, eta_key]
            if not all(k in coeff_data for k in coeff_keys):
                if verbose:
                    print(f"\t✗ Missing coefficients for path "
                          f"'{path_name}' ({path_tag})")
                continue

            x = np.array(coeff_data[theta_key])
            y = np.array(coeff_data[sigma_key])
            z = np.array(coeff_data[eta_key])
            K_data = np.array(coeff_data.get(K_key, []))
            all_z.extend(z.tolist())

            color = color_map.get(path_name, "black")
            marker = marker_map.get(path_name, "o")

            # Build legend label with c/μ params
            params = _get_path_params(coeff_data, path_tag)
            path_lbl = (f"{path_name} ({params})" if params else path_name)

            if len(K_data) > 0:
                unique_K = np.unique(K_data)
                K_ends = {unique_K[0], unique_K[-1]}
                first_K = True
                for K_val in unique_K:
                    mask = np.abs(K_data - K_val) < 0.1
                    if not np.any(mask):
                        continue

                    label = path_lbl if first_K else None
                    first_K = False

                    ax.scatter(x[mask],
                               y[mask],
                               z[mask],    # type: ignore
                               c=color,
                               marker=marker,
                               s=20,
                               alpha=0.6,
                               edgecolors="black",
                               linewidths=0.1,
                               label=label,
                                           rasterized=True)

                    if (K_val in K_ends and K_val not in lbl_K_vals):
                        mask_idx = np.where(mask)[0]
                        if len(mask_idx) > 0:
                            end_idx = mask_idx[-1]
                            z_range = (max(all_z) - min(all_z) if len(all_z) > 1 else 1)
                            z_off = z_range * 0.05
                            ax.text(x[end_idx],
                                    y[end_idx],
                                    z[end_idx] + z_off,
                                    f"K={int(K_val)}",
                                    **_K_LBL_STY_3D,  # type: ignore
                                    bbox=_K_BBOX)
                            lbl_K_vals.add(K_val)
            else:
                ax.scatter(x, y, z,    # type: ignore
                           c=color,
                           marker=marker,
                           s=20,
                           alpha=0.6,
                           edgecolors="black",
                           linewidths=0.1,
                           label=path_lbl,
                           rasterized=True)

            has_legend = True

            if verbose:
                print(f"\t✓ Path '{path_name}' plotted ({len(x)} pts)")
    else:
        # Single mode: group by (c, μ)
        if verbose:
            print(f"Extracting coefficient data "
                  f"{coeff_data.keys()}...")

        x_data = np.array(coeff_data.get("theta", []))
        y_data = np.array(coeff_data.get("sigma", []))
        z_data = np.array(coeff_data.get("eta", []))

        c_data = np.array(coeff_data.get("c", []))
        mu_data = np.array(coeff_data.get("mu", []))
        K_data = np.array(coeff_data.get("K", []))

        if verbose:
            print(f"  - Data points: {len(x_data)}")
            print(f"  - Unique c values: {np.unique(c_data)}")
            print(f"  - Unique μ values: {np.unique(mu_data)}")
            print(f"  - Unique K values: {np.unique(K_data)}")

        unique_c = np.unique(c_data)
        unique_mu = np.unique(mu_data)
        unique_K = np.unique(K_data)
        z_range = (float(z_data.max() - z_data.min())
                   if len(z_data) > 0 else 1)
        z_off = z_range * 0.05

        color_map = _generate_color_map(unique_c)
        marker_map = _generate_marker_map(unique_mu)

        lbl_combos = set()

        if verbose:
            print("Plotting data points...")

        for c_val in unique_c:
            for mu_val in unique_mu:
                for K_val in unique_K:
                    con_1 = (np.abs(c_data - c_val) < 0.1)
                    con_2 = (np.abs(mu_data - mu_val) < 0.1)
                    con_3 = (np.abs(K_data - K_val) < 0.1)
                    mask = con_1 & con_2 & con_3
                    if not np.any(mask):
                        continue

                    combo_key = (c_val, mu_val)
                    if combo_key not in lbl_combos:
                        label = f"c={int(c_val)}, μ={int(mu_val)}"
                        lbl_combos.add(combo_key)
                    else:
                        label = None

                    color = color_map.get(c_val, "black")
                    marker = marker_map.get(mu_val, "o")

                    ax.scatter(x_data[mask],
                               y_data[mask],
                               z_data[mask],    # type: ignore
                               c=color,
                               marker=marker,
                               s=20,
                               alpha=0.6,
                               edgecolors="black",
                               linewidths=0.1,
                               label=label,
                               rasterized=True)

                    if K_val not in lbl_K_vals:
                        mask_idx = np.where(mask)[0]
                        if len(mask_idx) > 0:
                            end_idx = mask_idx[-1]
                            ax.text(x_data[end_idx],
                                    y_data[end_idx],
                                    z_data[end_idx] + z_off,
                                    f"K={int(K_val)}",
                                    **_K_LBL_STY_3D,  # type: ignore
                                    bbox=_K_BBOX)
                            lbl_K_vals.add(K_val)

        has_legend = len(lbl_combos) > 0

    if verbose:
        print("Formatting plot...")

    # Get labels from coeff_lbls dict or use defaults
    xlabel = coeff_lbls.get("theta", "Occupancy ($\\boldsymbol{\\theta}$)")
    ylabel = coeff_lbls.get("sigma", "Stall ($\\boldsymbol{\\sigma}$)")
    zlabel = coeff_lbls.get("eta", "Effective-Yield ($\\boldsymbol{\\eta}$)")

    ax.set_xlabel(xlabel,
                  **_LBL_STY_3D_SINGLE)  # type: ignore
    ax.set_ylabel(ylabel,
                  **_LBL_STY_3D_SINGLE)  # type: ignore
    ax.set_zlabel(zlabel,
                  **_LBL_STY_3D_SINGLE)  # type: ignore

    _apply_logscale(ax, logscale, ["x", "y", "z"])

    ax.view_init(elev=30, azim=110)
    _style_3d_panes(ax)
    ax.grid(True, **_GRID_STY_3D)  # type: ignore

    _apply_sci_format(ax, ["x", "y", "z"])
    ax.tick_params(axis="x",
                   **_TICK_STY_3D_SINGLE)  # type: ignore
    ax.tick_params(axis="y",
                   **_TICK_STY_3D_SINGLE)  # type: ignore
    ax.tick_params(axis="z",    # type: ignore
                   **_TICK_STY_3D_SINGLE)  # type: ignore

    ax.set_title(subtitle, fontsize=17, **_LBL_STYLE)  # type: ignore

    if has_legend:
        legend_title = ("Path" if paths else "System Configuration")
        ax.legend(loc="upper left",
                  bbox_to_anchor=(1.05, 0.6), fontsize=12,
                  title=legend_title,
                  title_fontsize=13,
                  framealpha=0.9)

    fig.suptitle(title, fontsize=19, **_LBL_STYLE, y=0.95)  # type: ignore

    # Ensure route directory exists
    os.makedirs(route, exist_ok=True)

    if verbose:
        print(f"Saving figures to {route}")

    # Save figure in both SVG and PNG formats
    svg_path = os.path.join(route, f"{filename}.svg")
    png_path = os.path.join(route, f"{filename}.png")

    plt.savefig(svg_path, format="svg", dpi=300, bbox_inches="tight")
    plt.savefig(png_path, format="png", dpi=300, bbox_inches="tight")

    if verbose:
        print(f"\t✓: {svg_path}")
        print(f"\t✓: {png_path}")
        print("Complete")

    return fig


def plot_yoly_chart(title: str,
                    coeff_data: dict,
                    coeff_lbls: dict,
                    filename: str,
                    route: str,
                    paths: dict | None = None,
                    verbose: bool = False,
                    logscale: bool | list[bool] = False) -> Figure:
    """plot_yoly_chart, chart a single queue 2D yoly diagram with 2x2 grid of subplots.

    Args:
        title (str): main title for the figure.
        coeff_data (dict): Dictionary containing the coefficient results.
        coeff_lbls (dict): Dictionary with axis labels (e.g., "\\theta_{PACS}", "\\sigma_{PACS}", etc.).
        filename (str): Base filename for saving.
        route (str): Path where to save files.
        paths (dict, optional): Dictionary mapping path display names to their subscript tags for multi-path plotting. E.g., {"Read": "R_{PACS}", "Write": "W_{PACS}", "Overall": "PACS"}. When provided, plots one colored scatter group per path instead of grouping by (c, μ). Defaults to None.
        verbose (bool, optional): If True, print progress messages. Defaults to False.
        logscale (bool, optional): If True, use logarithmic scale for the y-axis. Defaults to False.

    Returns:
        Figure: The created figure object
    """

    if coeff_data is None:
        if verbose:
            print("coeff_data is not available")
        return None

    if verbose:
        print(f"Starting - {title}")

    fig = plt.figure(figsize=(18, 16), facecolor="white")
    gs = fig.add_gridspec(2, 2, hspace=0.25, wspace=0.25)

    axes = [
        fig.add_subplot(gs[0, 0]),
        fig.add_subplot(gs[0, 1]),
        fig.add_subplot(gs[1, 0]),
        fig.add_subplot(gs[1, 1])
    ]

    plot_titles = [
        "Plane: $\\boldsymbol{\\theta}$ vs $\\boldsymbol{\\sigma}$",
        "Plane: $\\boldsymbol{\\theta}$ vs $\\boldsymbol{\\eta}$",
        "Plane: $\\boldsymbol{\\sigma}$ vs $\\boldsymbol{\\eta}$",
        "Plane: $\\boldsymbol{\\theta}$ vs $\\boldsymbol{\\phi}$ (Memory)"
    ]

    x_lbls = [
        coeff_lbls.get("theta", "Occupancy ($\\boldsymbol{\\theta}$)"),
        coeff_lbls.get("theta", "Occupancy ($\\boldsymbol{\\theta}$)"),
        coeff_lbls.get("sigma", "Stall ($\\boldsymbol{\\sigma}$)"),
        coeff_lbls.get("theta", "Occupancy ($\\boldsymbol{\\theta}$)")
    ]

    y_lbls = [
        coeff_lbls.get("sigma", "Stall ($\\boldsymbol{\\sigma}$)"),
        coeff_lbls.get("eta", "Effective-Yield ($\\boldsymbol{\\eta}$)"),
        coeff_lbls.get("eta", "Effective-Yield ($\\boldsymbol{\\eta}$)"),
        coeff_lbls.get("phi", "Memory-Use ($\\boldsymbol{\\phi}$)")
    ]

    if paths:
        # Multi-path mode
        path_names = list(paths.keys())
        color_map = _generate_color_map(path_names)
        marker_map = _generate_marker_map(path_names)

        if verbose:
            print(f"Multi-path mode: {path_names}")

        # Collect per-path data
        path_data = {}
        for path_name, path_tag in paths.items():
            t = np.array(coeff_data.get(f"\\theta_{{{path_tag}}}", []))
            s = np.array(coeff_data.get(f"\\sigma_{{{path_tag}}}", []))
            e = np.array(coeff_data.get(f"\\eta_{{{path_tag}}}", []))
            p = np.array(coeff_data.get(f"\\phi_{{{path_tag}}}", []))
            K = np.array(coeff_data.get(f"K_{{{path_tag}}}", []))
            if len(t) > 0 and len(s) > 0 and len(e) > 0:
                path_data[path_name] = {
                    "theta": t,
                    "sigma": s,
                    "eta": e,
                    "phi": p,
                    "K": K
                }

        for plot_idx, ax in enumerate(axes):
            ax.set_facecolor("white")
            has_legend = False
            lbl_K_vals = set()

            for path_name, pd_ in path_data.items():
                pairs = [
                    (pd_["theta"], pd_["sigma"]),
                    (pd_["theta"], pd_["eta"]),
                    (pd_["sigma"], pd_["eta"]),
                    (pd_["theta"], pd_["phi"])
                ]
                x_arr, y_arr = pairs[plot_idx]

                if len(x_arr) == 0 or len(y_arr) == 0:
                    continue

                color = color_map.get(path_name, "black")
                marker = marker_map.get(path_name, "o")
                K_data = pd_["K"]

                # Build legend label with c/μ params
                path_tag = paths[path_name]
                params = _get_path_params(coeff_data, path_tag)
                path_lbl = (f"{path_name} ({params})" if params else path_name)

                if len(K_data) > 0:
                    unique_K = np.unique(K_data)
                    K_ends = {unique_K[0], unique_K[-1]}
                    y_range = (float(y_arr.max() - y_arr.min()) if len(y_arr) > 0 else 1)
                    y_off = y_range * 0.04
                    first_K = True
                    for K_val in unique_K:
                        mask = np.abs(K_data - K_val) < 0.1
                        if not np.any(mask):
                            continue

                        label = path_lbl if first_K else None
                        first_K = False

                        ax.scatter(x_arr[mask],
                                   y_arr[mask],
                                   c=color,
                                   marker=marker,
                                   s=40,
                                   alpha=0.6,
                                   edgecolors="black",
                                   linewidths=0.2,
                                   label=label,
                                   rasterized=True)

                        if (K_val in K_ends and K_val not in lbl_K_vals):
                            mask_idx = np.where(mask)[0]
                            if len(mask_idx) > 0:
                                end = mask_idx[-1]
                                ax.text(float(x_arr[end]),
                                        float(y_arr[end]) + y_off,
                                        f"K={int(K_val)}",
                                        **_K_LBL_STY_2D,  # type: ignore
                                        bbox=_K_BBOX)
                                lbl_K_vals.add(K_val)
                else:
                    ax.scatter(x_arr,
                               y_arr,
                               c=color,
                               marker=marker,
                               s=40,
                               alpha=0.6,
                               edgecolors="black",
                               linewidths=0.2,
                               label=path_lbl,
                               rasterized=True)

                has_legend = True

            # Styling
            ax.grid(True, **_GRID_STYLE)  # type: ignore
            ax.tick_params(**_TICK_STYLE)  # type: ignore
            for spine in ax.spines.values():
                spine.set_edgecolor("black")

            _apply_sci_format(ax)
            _apply_logscale(ax, logscale)

            ax.set_xlabel(x_lbls[plot_idx],
                          **_LBL_STY_2D_SINGLE)  # type: ignore
            ax.set_ylabel(y_lbls[plot_idx],
                          **_LBL_STY_2D_SINGLE)  # type: ignore
            ax.set_title(plot_titles[plot_idx],
                         fontsize=17,
                         **_LBL_STYLE,  # type: ignore
                         pad=-10)

            if has_legend:
                ax.legend(loc="best",
                          fontsize=12,
                          framealpha=0.9,
                          title="Path",
                          title_fontsize=13)
    else:
        # Single mode: group by (c, μ)
        theta_key = find_key(coeff_data, "\\theta")
        sigma_key = find_key(coeff_data, "\\sigma")
        eta_key = find_key(coeff_data, "\\eta")
        phi_key = find_key(coeff_data, "\\phi")
        c_key = find_key(coeff_data, "c_")
        mu_key = find_key(coeff_data, "\\mu")
        K_key = find_key(coeff_data, "K_")

        theta_data = np.array(coeff_data.get(theta_key, []))
        sigma_data = np.array(coeff_data.get(sigma_key, []))
        eta_data = np.array(coeff_data.get(eta_key, []))
        phi_data = np.array(coeff_data.get(phi_key, []))
        c_data = np.array(coeff_data.get(c_key, []), dtype=float)
        mu_data = np.array(coeff_data.get(mu_key, []), dtype=float)
        K_data = np.array(coeff_data.get(K_key, []), dtype=float)

        data_pairs = [
            (theta_data, sigma_data),
            (theta_data, eta_data),
            (sigma_data, eta_data),
            (theta_data, phi_data)
        ]

        unique_c = np.unique(c_data)
        unique_mu = np.unique(mu_data)
        unique_K = np.unique(K_data)

        color_map = _generate_color_map(unique_c)
        marker_map = _generate_marker_map(unique_mu)

        for plot_idx, ax in enumerate(axes):
            x_data, y_data = data_pairs[plot_idx]
            ax.set_facecolor("white")

            lbl_combos = set()
            lbl_K_vals = set()
            y_range = (float(y_data.max() - y_data.min()) if len(y_data) > 0 else 1)
            y_off = y_range * 0.04

            for c_val in unique_c:
                for mu_val in unique_mu:
                    for K_val in unique_K:
                        con_1 = np.abs(c_data - c_val) < 0.1
                        con_2 = np.abs(mu_data - mu_val) < 0.1
                        con_3 = np.abs(K_data - K_val) < 0.1
                        mask = con_1 & con_2 & con_3

                        if not np.any(mask):
                            continue

                        combo_key = (c_val, mu_val)
                        if combo_key not in lbl_combos:
                            label = f"c={int(c_val)}, μ={int(mu_val)}"
                            lbl_combos.add(combo_key)
                        else:
                            label = None

                        color = color_map.get(c_val, "black")
                        marker = marker_map.get(mu_val, "o")

                        ax.scatter(x_data[mask],
                                   y_data[mask],
                                   c=color,
                                   marker=marker,
                                   s=40,
                                   alpha=0.6,
                                   edgecolors="black",
                                   linewidths=0.2,
                                   label=label,
                                   rasterized=True)

                        if K_val not in lbl_K_vals:
                            mask_idx = np.where(mask)[0]
                            if len(mask_idx) > 0:
                                end = mask_idx[-1]
                                ax.text(float(x_data[end]),
                                        float(y_data[end]) + y_off,
                                        f"K={int(K_val)}",
                                        **_K_LBL_STY_2D,   # type: ignore
                                        bbox=_K_BBOX)
                                lbl_K_vals.add(K_val)

            # Styling
            ax.grid(True, **_GRID_STYLE)  # type: ignore
            ax.tick_params(**_TICK_STYLE)  # type: ignore
            for spine in ax.spines.values():
                spine.set_edgecolor("black")

            _apply_sci_format(ax)
            _apply_logscale(ax, logscale)

            ax.set_xlabel(x_lbls[plot_idx],
                          **_LBL_STY_2D_SINGLE)  # type: ignore
            ax.set_ylabel(y_lbls[plot_idx],
                          **_LBL_STY_2D_SINGLE)  # type: ignore
            ax.set_title(plot_titles[plot_idx],
                         fontsize=17,
                         **_LBL_STYLE,    # type: ignore
                         pad=-10)

            if lbl_combos:
                ax.legend(loc="best",
                          fontsize=12,
                          framealpha=0.9,
                          title="System Configuration",
                          title_fontsize=13)

    fig.suptitle(title, fontsize=25, **_LBL_STYLE, y=0.995)  # type: ignore

    # Ensure route directory exists
    os.makedirs(route, exist_ok=True)

    if verbose:
        print(f"\nSaving figures to: {route}")

    # Save figure in both SVG and PNG formats
    svg_path = os.path.join(route, f"{filename}.svg")
    png_path = os.path.join(route, f"{filename}.png")

    plt.savefig(svg_path, format="svg", dpi=300, bbox_inches="tight")
    plt.savefig(png_path, format="png", dpi=300, bbox_inches="tight")

    if verbose:
        print(f"\t✓: {svg_path}")
        print(f"\t✓: {png_path}")
        print("Complete!!!")

    return fig

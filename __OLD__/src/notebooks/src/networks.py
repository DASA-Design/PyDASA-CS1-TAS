"""Queue Network functions for solving Jackson-grid configuration + simulation.

Clean consolidated version reconciling CS-01A and Iter2 approaches.
"""

from __future__ import annotations
import numpy as np
import pandas as pd
from src.queueing import Queue
# from typing import Callable

UTIL_THLD = 0.95  # Stop when utilization reaches 95.0%


# ============================================================================
# UTILITY FUNCTIONS (key lookup and data extraction)
# ============================================================================

def find_key_idx(lt: list, starts_with: str) -> int:
    for i, s in enumerate(lt):
        if s.startswith(starts_with):
            return i
    return -1


def find_key(node: dict, starts_with: str) -> str:
    """Find the first key in node that starts with the specific substring.

    Args:
        node (dict): JSON node configuration containing variable definitions.
        starts_with (str): substring that the key should start with.

    Raises:
        KeyError: if no key starts with the specific substring.

    Returns:
        str: the first key that complies with the substring conditions.
    """
    for k in node.keys():
        if k.startswith(starts_with):
            return k
    raise KeyError(f"Missing key starting with {starts_with}")


def get_data(var: dict) -> list:
    """Get the list of values from the "_data" key in the variable dictionary.

    Args:
        var (dict): variable dictionary containing the "_data" key with a list of values.

    Raises:
        ValueError: if the "_data" key is missing, not a list, or empty.

    Returns:
        list: the list of values from the "_data" key.
    """
    data = var.get("_data")
    if not isinstance(data, list) or len(data) == 0:
        _msg = f"Expected non-empty '_data' list; got {data}"
        _msg += f" for variable with keys {list(var.keys())}"
        _msg += "; use a single-item list for constants."
        raise ValueError(_msg)
    return data


# ============================================================================
# GRID SEARCH FUNCTIONS (K-rho pair generation)
# ============================================================================

def _get_var_bounds(node: dict, key: str) -> tuple[float, float]:
    """Get the bounds for a named variable in the node JSON configuration.

    Checks in order:
      1. _data array (explicit min/max from list)
      2. _std_min, _std_max (explicit bounds)
      3. _std_setpoint (constant fallback)
      4. _setpoint (constant fallback)

    Args:
        node (dict): JSON node configuration containing variable definitions.
        key (str): substring to identify the variable key (e.g., "d_").

    Raises:
        ValueError: if no bounds can be determined for the variable.

    Returns:
        tuple[float, float]: the (min, max) bounds for the variable.
    """
    var_key = find_key(node, key)
    _val = node[var_key]
    bounds = None

    _data = _val.get("_data")
    if isinstance(_data, list) and len(_data) > 0:
        # min/max when explicit combinations are provided.
        rho_values = [float(value) for value in _data]
        bounds = (min(rho_values), max(rho_values))

    elif "_std_min" in _val and "_std_max" in _val:
        # explicit bounds
        bounds = (float(_val["_std_min"]), float(_val["_std_max"]))

    elif "_std_setpoint" in _val:
        # constant setpoint
        rho_value = float(_val["_std_setpoint"])
        bounds = (rho_value, rho_value)

    elif "_setpoint" in _val:
        # fallback constant
        rho_value = float(_val["_setpoint"])
        bounds = (rho_value, rho_value)

    if bounds is None:
        _msg = f"No bounds available for node variable '{var_key}'"
        raise ValueError(_msg)

    return bounds


def _build_var_pairs(node: dict,
                     grid_key: str,
                     anchor_key: str,
                     ans_key: str) -> dict:
    """build viable pairs based on a grid search of a variale within specific bounds of an anchor value.

    Args:
        node (dict): JSON node configuration containing variable definitions.
        grid_key (str): substring to identify the grid variable key (e.g., "K_{").
        anchor_key (str): substring to identify the anchor variable key (e.g., "M_{buf_{").
        ans_key (str): substring to identify the answer variable key (e.g., "rho_{").

    Returns:
        dict: a dict with the tuples containing the valid (grid, anchor) pairs.

        TODO: improve code accepting personalized function
    """
    # get grid values and bounds for the variable, e.g., K_...
    _grid = find_key(node, grid_key)
    _grid_vals = get_data(node[_grid])

    # get anchor values, e.g., M_buf...
    _anchor = find_key(node, anchor_key)
    _anchor_vals = get_data(node[_anchor])

    _ans = find_key(node, ans_key)

    pairs = {
        _grid: [],
        _anchor: [],
        _ans: [],
    }

    for g_val in _grid_vals:
        for a_val in _anchor_vals:
            # TODO can personalize and pass the function as parameter
            # compute valid results based on the relationship between the grid variable and the anchor variable, e.g., rho = M_buf / K
            t_ans = a_val / g_val
            pairs[_grid].append(g_val)
            pairs[_anchor].append(t_ans)
            pairs[_ans].append(t_ans)

    # ORIGINAL: filter pairs where rho is within specified bounds.
    # # generate paired (K, rho) values maintaining M_BUF = K × rho
    # # this ensures buffer memory remains constant across all configurations
    # K_rho_pairs = []
    # for K in K_values:
    #     rho_K = M_BUF / K  # Data density based on buffer and queue capacity
    #     K_rho_pairs.append((K, rho_K))
    return pairs


# ============================================================================
# CONFIGURATION SETUP
# ============================================================================
def _build_K_rho_pairs(node: dict) -> dict:
    """Build feasible (K, rho) pairs from a grid search.

    For each K value and M_buf value, compute rho = M_buf/K and filter pairs where rho is within specified bounds.

    Args:
        node (dict): JSON node configuration containing variable definitions.
    Returns:
        dict: a dict of (K, rho) tuples that satisfy bounds.
    """
    ans = _build_var_pairs(node, "K_{", "M_{buf_{", "d_{req_{")
    return ans


def setup_artifact_specs(relevant_lt: dict) -> pd.DataFrame:
    """setup_artifact_specs _summary_

    Args:
        relevant_lt (dict): _description_

    Returns:
        pd.DataFrame: _description_
    """
    # get paired K and \\rho keys for the artifact specs
    _rho = find_key(relevant_lt, "d_{")
    _K = find_key(relevant_lt, "K_{")

    # make valid pairs of K an \\rho
    valid_pairs = _build_K_rho_pairs(relevant_lt)

    # get the c and mu keys + values for the artifact specs
    _mu = find_key(relevant_lt, "\\mu_{")
    _mu_values = get_data(relevant_lt[_mu])
    _c = find_key(relevant_lt, "c_{")
    _c_values = get_data(relevant_lt[_c])

    # new df with valid K, \\rho, c and \\mu columns
    _cols = [_K, _rho, _c, _mu]
    df = pd.DataFrame(columns=_cols)

    # make all combinations of valid pairs with c and mu values
    for K, rho in zip(valid_pairs[_K], valid_pairs[_rho]):
        _row = {}
        for mu in _mu_values:
            for c in _c_values:
                _row[_K] = K
                _row[_rho] = rho
                _row[_mu] = mu
                _row[_c] = c

                # add the data to the df
                df.loc[len(df)] = _row
    return df


def setup_environmental_conds(relevant_lt: dict,
                              df: pd.DataFrame) -> pd.DataFrame:
    """setup_environmental_conds _summary_

    Args:
        relevant_lt (dict): _description_
        df (pd.DataFrame): The DataFrame to which environmental conditions will be added.

    Returns:
        pd.DataFrame: _description_
    """
    _M_buf = find_key(relevant_lt, "M_{buf_{")
    _M_buf_values = get_data(relevant_lt[_M_buf])

    _eps = find_key(relevant_lt, "\\epsilon_{")
    _eps_values = get_data(relevant_lt[_eps])
    n_cfgs = len(df)
    _data = {
        _M_buf: (),
        _eps: (),
    }

    # make all combinations of M_buf and epsilon values
    for M_buf in _M_buf_values:
        for eps in _eps_values:
            for i in range(n_cfgs):
                _data[_M_buf] += (M_buf,)    # type: ignore
                _data[_eps] += (eps,)        # type: ignore

    # add the data columns to the df
    for col in _data.keys():
        df[col] = _data[col]
    return df


def setup_queue_metrics(relevant_lt: dict,
                        df: pd.DataFrame) -> pd.DataFrame:
    """setup_queue_metrics _summary_

    Args:
        relevant_lt (dict): _description_
        df (pd.DataFrame): _description_

    Returns:
        pd.DataFrame: _description_
    """
    _lambda = find_key(relevant_lt, "\\lambda_{")
    _chi = find_key(relevant_lt, "\\chi_{")
    _L = find_key(relevant_lt, "L_{")
    _Lq = find_key(relevant_lt, "Lq_{")
    _W = find_key(relevant_lt, "W_{")
    _Wq = find_key(relevant_lt, "Wq_{")
    _M_act = find_key(relevant_lt, "M_{act_{")

    n_cfg = len(df)

    _data = {
        _lambda: (None,) * n_cfg,
        _chi: (None,) * n_cfg,
        _L: (None,) * n_cfg,
        _Lq: (None,) * n_cfg,
        _W: (None,) * n_cfg,
        _Wq: (None,) * n_cfg,
        _M_act: (None,) * n_cfg,
    }

    for col in _data.keys():
        df[col] = _data[col]

    return df


def simulate_architecture(nd_names: list[str],
                          lambda_step_vec: list[float],
                          cfg_df: pd.DataFrame,
                          exp_df: pd.DataFrame,
                          route_mtx: np.ndarray,
                          verbose: bool = False) -> pd.DataFrame:

    # exp = {}

    # # iterate over the environmental conditions
    # for env, route_mtx in env_conds_df.items():

    # iterate over the artifact specs
    for idx, specs in cfg_df.iterrows():

        # create lambda_zero vector based on artifact specs
        lambdas_z = _setup_lambdas_zeros(specs)
        lambdas_s = {}

        # format vector for solving the matrix
        lambda_z_vec = list(lambdas_z.values())

        # # solve the Jackson network equations for the first time
        lambda_vec = solve_jackson_lambdas(route_mtx, lambda_z_vec)

        # update lambda dict with lambda_vec values
        for i, k in enumerate(lambdas_z.keys()):
            lambdas_s[k] = lambda_vec[i]

        # simulate artifact in parallel inside the queue network
        exp_df = simulate_net_artifacts(lambdas_z,
                                        lambdas_s,
                                        lambda_step_vec,
                                        route_mtx,
                                        idx,   # type: ignore
                                        specs,
                                        exp_df)

    return exp_df


def _setup_lambdas_zeros(cfg_row: pd.Series) -> dict[str, float]:

    lambdas = {}

    for k, v in cfg_row.items():
        k = str(k)
        if k.startswith("\\lambda_"):
            lambdas[k] = v

    return lambdas


def simulate_net_artifacts(lambdas_zeros: dict[str, float],
                           lambdas_solved: dict[str, float],
                           lambda_step_vec: list[float],
                           route_mtx: np.ndarray,
                           idx_cfg: int,
                           cfg_row: pd.Series,
                           exp_df: pd.DataFrame) -> pd.DataFrame:

    # add colums for config + experiment counters
    exp_df["idx_cfg"] = 0
    exp_df["j_exp"] = 0

    exp_lt = []
    j_exp = 0
    max_network_util = 0.0

    while max_network_util < UTIL_THLD:
        exp_row = {}
        # Simulate ALL 7 artifacts at THIS lambda_scale level
        for art in lambdas_solved.keys():
            art = art.replace("\\lambda_", "")
            art = art.replace("{", "")
            art = art.replace("}", "")
            # get all the columns with the node name
            # art_cfg_series = cfg_row.filter(regex=re.escape(art), axis=0)
            art_cfg_series = cfg_row.filter(regex=f"{art}.*", axis=0)
            # getting lambda value for the artifact from Jackson network solution, then scale it
            art_cols = art_cfg_series.index.tolist()
            lambda_k = art_cols[find_key_idx(art_cols, "\\lambda_{")]
            lambda_tmp = float(lambdas_solved.get(lambda_k, 0.0))

            # getting the rest of the parameters for the artifact
            mu_k = art_cols[find_key_idx(art_cols, "\\mu_{")]
            mu_tmp = float(cfg_row.get(mu_k, 0.0))

            eps_k = art_cols[find_key_idx(art_cols, "\\epsilon_{")]
            eps_tmp = float(cfg_row.get(eps_k, 0.0))

            chi_k = art_cols[find_key_idx(art_cols, "\\chi_{")]

            c_k = art_cols[find_key_idx(art_cols, "c_{")]
            c_tmp = float(cfg_row.get(c_k, 0.0))

            K_k = art_cols[find_key_idx(art_cols, "K_{")]
            K_tmp = float(cfg_row.get(K_k, 0.0))

            rho_k = art_cols[find_key_idx(art_cols, "d_{req_{")]
            rho_tmp = float(cfg_row.get(rho_k, 0.0))

            W_k = art_cols[find_key_idx(art_cols, "W_{")]
            Wq_k = art_cols[find_key_idx(art_cols, "Wq_{")]
            L_k = art_cols[find_key_idx(art_cols, "L_{")]
            Lq_k = art_cols[find_key_idx(art_cols, "Lq_{")]
            M_act_k = art_cols[find_key_idx(art_cols, "M_{act_{")]

            M_buf_k = art_cols[find_key_idx(art_cols, "M_{buf_{")]
            M_buf_tmp = float(cfg_row.get(M_buf_k, 0.0))

            util_tmp = lambda_tmp / (c_tmp * mu_tmp)

            # experiment part segmented by artifact
            # assign zero values to all metrics when utilization is zero
            exp = {
                lambda_k: lambda_tmp,
                mu_k: mu_tmp,
                eps_k: eps_tmp,
                chi_k: 0.0,
                c_k: c_tmp,
                K_k: K_tmp,
                rho_k: rho_tmp,
                W_k: 0.0,
                Wq_k: 0.0,
                L_k: 0.0,
                Lq_k: 0.0,
                M_act_k: 0.0,
                M_buf_k: M_buf_tmp,
                f"U_{{{art}}}": util_tmp,
                "j_exp": j_exp,
                "idx_cfg": idx_cfg,
            }

            # simulate if utilization is below the threshold
            if 0.0 < util_tmp < UTIL_THLD:
                # creating queue object for simulations
                q_tmp = Queue("M/M/c/K",
                              lambda_tmp,   # type: ignore
                              mu_tmp,       # type: ignore
                              c_tmp,        # type: ignore
                              K_tmp,)       # type: ignore

                # asign queue simulation parameters
                q_tmp._lambda = lambda_tmp      # type: ignore
                q_tmp.mu = mu_tmp               # type: ignore
                q_tmp.n_servers = int(c_tmp)    # type: ignore
                q_tmp.kapacity = int(K_tmp)

                # calculate queue metrics
                q_tmp.calculate_metrics()
                chi_tmp = lambda_tmp * (1 - eps_tmp)
                M_act_tmp = q_tmp.avg_len * rho_tmp

                exp = {
                    lambda_k: lambda_tmp,
                    mu_k: mu_tmp,
                    eps_k: eps_tmp,
                    chi_k: chi_tmp,
                    c_k: c_tmp,
                    K_k: K_tmp,
                    rho_k: rho_tmp,
                    W_k: q_tmp.avg_wait,
                    Wq_k: q_tmp.avg_wait_q,
                    L_k: q_tmp.avg_len,
                    Lq_k: q_tmp.avg_len_q,
                    M_act_k: M_act_tmp,
                    M_buf_k: M_buf_tmp,
                    f"U_{{{art}}}": util_tmp,
                    "j_exp": j_exp,
                    "idx_cfg": idx_cfg,
                }

            # merge this artifact's results into the row
            exp_row |= exp

            if max_network_util < util_tmp:
                max_network_util = util_tmp

        # Append ONE complete row with all 7 artifacts
        exp_lt.append(exp_row)

        # experiment counter for this artifact
        j_exp += 1

        # Scale lambda for next iteration (preserves Jackson network ratios)
        lambdas_solved = _step_up_lambdas(route_mtx,
                                          lambdas_zeros,
                                          lambda_step_vec)

    # Concat ONCE at the end
    if exp_lt:
        exp_df = pd.concat([exp_df, pd.DataFrame(exp_lt)], ignore_index=True)

    return exp_df


def _step_up_lambdas(route_mtx: np.ndarray,
                     lambdas_zeros: dict[str, float],
                     lambda_step_vec: list[float]) -> dict[str, float]:

    # update lambda zeros with the step vector
    for i, k in enumerate(lambdas_zeros.keys()):
        lambdas_zeros[k] = lambdas_zeros[k] + lambda_step_vec[i]

    # solve the Jackson network equations for current vector and matrix
    lambda_vec = solve_jackson_lambdas(route_mtx, list(lambdas_zeros.values()))
    lambdas_solved = {}

    # update lambda dict with new solution values
    for i, k in enumerate(lambdas_zeros.keys()):
        lambdas_solved[k] = lambda_vec[i]
    return lambdas_solved


def simulate_artifact(lambda_zero: float,
                      lambda_step: float,
                      cfg_df: pd.DataFrame,
                      exp_df: pd.DataFrame) -> pd.DataFrame:
    """execute the queue simulation according to the configuration dataframe and put the results in the experiment dataframe

    Args:
        lambda_zero (float): intial arrival rate for the simulation, typically starting at 0 to simulate from an empty system.
        lambda_step (float): step to increase the arrival rate in each iteration, typically a small value to capture the system behavior as it approaches saturation.
        cfg_df (pd.DataFrame): The DataFrame containing the simulation configurations.
        exp_df (pd.DataFrame): The DataFrame to which experiment results will be added.

    Returns:
        pd.DataFrame: The DataFrame containing the experiment results.
    """
    # add colums for config + experiment counters
    exp_df["cfg_idx"] = 0
    exp_df["j_exp"] = 0

    _exp_cols = exp_df.columns.tolist()
    exp_lt = []

    # iterate over the configurations
    for idx, cfg in cfg_df.iterrows():
        # getting exp config
        cfg = dict(cfg)

        lambda_k = _exp_cols[find_key_idx(_exp_cols, "\\lambda_{")]

        mu_k = find_key(cfg, "\\mu_{")
        mu_tmp = float(cfg.get(mu_k, 0.0))

        eps_k = find_key(cfg, "\\epsilon_{")
        eps_tmp = float(cfg.get(eps_k, 0.0))

        chi_k = _exp_cols[find_key_idx(_exp_cols, "\\chi_{")]

        c_k = find_key(cfg, "c_{")
        c_tmp = float(cfg.get(c_k, 0.0))

        K_k = find_key(cfg, "K_{")
        K_tmp = float(cfg.get(K_k, 0.0))

        rho_k = find_key(cfg, "d_{req_{")
        rho_tmp = float(cfg.get(rho_k, 0.0))

        W_k = _exp_cols[find_key_idx(_exp_cols, "W_{")]
        Wq_k = _exp_cols[find_key_idx(_exp_cols, "Wq_{")]
        L_k = _exp_cols[find_key_idx(_exp_cols, "L_{")]
        Lq_k = _exp_cols[find_key_idx(_exp_cols, "Lq_{")]
        M_act_k = _exp_cols[find_key_idx(_exp_cols, "M_{act_{")]

        M_buf_k = find_key(cfg, "M_{buf_{")
        M_buf_tmp = float(cfg.get(M_buf_k, 0.0))

        # seting up experiment initial conditions
        lambda_tmp = lambda_zero
        util_tmp = 0.0
        # experiment counters
        j_exp = 0

        # creating queue object for simulations
        q_tmp = Queue("M/M/c/K",
                      lambda_tmp,
                      mu_tmp,   # type: ignore
                      c_tmp,    # type: ignore
                      K_tmp,)   # type: ignore

        # simulate until utilization reaches the threshold
        while util_tmp < UTIL_THLD:
            # asign queue simulation parameters
            q_tmp._lambda = lambda_tmp
            q_tmp.mu = mu_tmp               # type: ignore
            q_tmp.n_servers = int(c_tmp)    # type: ignore
            q_tmp.kapacity = int(K_tmp)     # type: ignore

            # calculate queue metrics
            q_tmp.calculate_metrics()
            chi_tmp = lambda_tmp * (1 - eps_tmp)    # type: ignore
            M_act_tmp = q_tmp.avg_len * rho_tmp     # type: ignore

            _exp = {
                lambda_k: lambda_tmp,
                mu_k: mu_tmp,
                eps_k: eps_tmp,
                chi_k: chi_tmp,
                c_k: c_tmp,
                K_k: K_tmp,
                rho_k: rho_tmp,
                W_k: q_tmp.avg_wait,
                Wq_k: q_tmp.avg_wait_q,
                L_k: q_tmp.avg_len,
                Lq_k: q_tmp.avg_len_q,
                M_act_k: M_act_tmp,
                M_buf_k: M_buf_tmp,
                "cfg_idx": idx,
                "j_exp": j_exp,
            }
            exp_lt.append(_exp)
            # update the exp_df with the experiment results
            # exp_df.loc[len(exp_df)] = exp_data  # type: ignore

            # steping the experiment
            util_tmp = q_tmp.rho
            lambda_tmp = lambda_tmp + lambda_step
            j_exp += 1

    # Concat ONCE at the end
    if exp_lt:
        exp_df = pd.concat([exp_df, pd.DataFrame(exp_lt)], ignore_index=True)

    return exp_df


# ============================================================================
# JACKSON NETWORK SOLVING
# ============================================================================
def solve_jackson_lambdas(P: np.ndarray,
                          lambda_zero_vec: list | np.ndarray) -> list:
    """Solve Jackson traffic equations: (I - P^T) λ = λ₀.

    Given a routing matrix P and external arrival vector λ₀, solves for per-node arrival rates λ using Jackson network balance.

    Args:
        P (np.ndarray): routing probability matrix (n_nodes × n_nodes). P[i,j] = probability routing from node i to node j.
        lambda_zero_vec (list | np.ndarray): external arrivals λ₀ (n_nodes,).typically only one entry is non-zero.

    Returns:
        list: per-node arrival rates λ (n_nodes,) solving the traffic equations.
    """
    n = len(lambda_zero_vec)
    ident = np.eye(n)
    if isinstance(lambda_zero_vec, list):
        lambda_zero = np.array(lambda_zero_vec, dtype=float)
    else:
        lambda_zero = lambda_zero_vec
    # Solve: λ = λ₀ + P^T λ  ⟹  (I - P^T) λ = λ₀
    return np.linalg.solve(ident - P.T, lambda_zero).tolist()

# PACS E2E Aggregation Fix — Implementation Plan v4

## Variable Aggregation Rules

| Variable | λ-dep? | R-path (5 nodes) | W-path (5 nodes) | PACS (7 unique nodes) | ε special |
|----------|:------:|-------------------|-------------------|-----------------------|-----------|
| `λ` | Yes | `Σ(R-path)` | `Σ(W-path)` | `Σ(7 unique)` | — |
| `χ` | Yes | `Σ(R-path)` | `Σ(W-path)` | `Σ(7 unique)` | — |
| `μ` | No | `Σ(R-path)` | `Σ(W-path)` | `Σ(7 unique)` | — |
| `c` | No | `Σ(R-path)` | `Σ(W-path)` | `Σ(7 unique)` | — |
| `K` | No | `Σ(R-path)` | `Σ(W-path)` | `Σ(7 unique)` | — |
| `L` | Yes | `Σ(R-path)` | `Σ(W-path)` | `Σ(7 unique)` | — |
| `W` | Yes | `Σ(R-path)` | `Σ(W-path)` | `Σ(7 unique)` | — |
| `M_buf` | No | `Σ(R-path)` | `Σ(W-path)` | `Σ(7 unique)` | — |
| `M_act` | Yes | `Σ(R-path)` | `Σ(W-path)` | `Σ(7 unique)` | — |
| `ρ` | Yes | `Σ(R-path)` | `Σ(W-path)` | `Σ(7 unique)` | — |
| `ε` | Yes | `1-Π(1-ε_i)` R 5 nodes | `1-Π(1-ε_i)` W 5 nodes | `1-Π(1-ε_i)` **7 unique** | Cumulative prob |

**Key invariant**: `PACS = R_sub + W_sub - shared_sub` (for all sum-type vars). For ε: `PACS = 1 - Π(1-ε_i)` over the 7 unique nodes (NOT derived from ε_R and ε_W).

## Node Sets (constants in code)

```python
r_path     = ["IB", "IR", "DB", "RN", "OB"]
w_path     = ["IB", "IW", "DB", "WN", "OB"]
shared     = ["IB", "DB", "OB"]
all_unique = ["IB", "IR", "IW", "DB", "RN", "WN", "OB"]  # 7 nodes
```

## Scenario Behaviour

All 5 scenarios are already computed in `architecture_exp[env]` with routing probabilities baked into the per-node values. No special-casing needed at aggregation time.

| Scenario | What happens | Static vars (μ, c, K, M_buf) | Dynamic vars (λ, χ, L, W, M_act, ρ, ε) |
|----------|-------------|-------------------------------|------------------------------------------|
| **100R** | W-path has 0 traffic | W nodes still counted (allocated but idle) | W node values already 0 in `architecture_exp` |
| **80R20W** | Both paths active | All 7 nodes counted | All 7 nodes have values reflecting 80/20 routing split |
| **50R50W** | Both paths active | All 7 nodes counted | All 7 nodes have values reflecting 50/50 routing split |
| **20R80W** | Both paths active | All 7 nodes counted | All 7 nodes have values reflecting 20/80 routing split |
| **100W** | R-path has 0 traffic | R nodes still counted (allocated but idle) | R node values already 0 in `architecture_exp` |

## Implementation Steps

| # | Step | What to do | Reason | Risks | Mitigation |
|---|------|-----------|--------|-------|------------|
| 1 | **Rewrite cell 69 aggregation** | Replace all aggregation logic with: (a) `Σ(R-path cols)` for R_sub, (b) `Σ(W-path cols)` for W_sub, (c) `Σ(all_unique cols)` for PACS. Exception: ε uses cumulative prob formula. Remove `env_weights` entirely. | Current code has wrong semantics (min, mean, entry-node, weighted combos) | Column regex might match wrong nodes | Test with a print of matched columns per var |
| 2 | **Handle ε separately** | Cumulative probability: `1-Π(1-ε_i)` over R-path, W-path, and 7-unique respectively | Sum doesn't apply to probabilities | ε values near 0 could cause float precision issues | Should be fine at 0.01 scale |
| 3 | **Verify `pacs_data` output shape** | Each `pacs_data[env]` should be a DataFrame with 33 columns: 11 vars × 3 levels (R_sub, W_sub, PACS) | Downstream Yoly plots expect this structure | Column naming must match Yoly functions | Check Yoly function signatures for expected column patterns |
| 4 | **Create PACS Variable dict for PyDASA** | Build a PyDASA-compatible Variable dictionary for the 11 aggregated PACS-level variables (3 levels: R, W, PACS). Define symbols, dimensions, units, categories matching the iter1 pattern. | PyDASA `AnalysisEngine` requires a proper Variable dict + Schema to run analysis and derive coefficients | Must match PyDASA's expected schema format | Reference iter1 variable definitions for the pattern |
| 5 | **Run PyDASA analysis + derive coefficients** | Use `AnalysisEngine.run_analysis()` then `derive_coefficient()` for θ, σ, η, φ at each of the 3 levels (R, W, PACS) | User requirement: use PyDASA, not manual formulas | Need correct dimensional expressions for each coefficient | Reference iter1 coefficient derivation cells |
| 6 | **Merge coefficients into `pacs_data`** | Add 12 coefficient columns (4 coeffs × 3 levels) to each `pacs_data[env]` DataFrame | Yoly plots need coefficients alongside vars | — | — |
| 7 | **Deprecate cells 83-86** | Comment out or clear the old Flow B cells | They have broken logic and overwrite `pacs_data` | Verify nothing downstream depends on their `architecture_exp` side-effects | Check cells 87+ for any reference to columns added by 83-86 |
| 8 | **Test end-to-end** | Run cells 69 → plots, verify plots render correctly | Full pipeline validation | May need full notebook re-run for clean state | — |

## Expected Plot Output

5 plots (one per scenario), each with 3 lines:

| Line | Label | Data source | Description |
|------|-------|------------|-------------|
| **Read** | R | R_sub columns from `pacs_data[env]` | Full read-path (IB→IRS→DB→RAS→OB) aggregated metrics + coefficients |
| **Write** | W | W_sub columns from `pacs_data[env]` | Full write-path (IB→IW→DB→WAS→OB) aggregated metrics + coefficients |
| **General** | PACS | PACS columns from `pacs_data[env]` | Deduplicated 7-node system total metrics + coefficients |

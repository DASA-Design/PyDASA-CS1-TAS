# Method 5: comparison — cross-method R1/R2/R3 verdict

Plan for the **fifth and final method** in the CS-01 TAS pipeline. Reads
the four green methods (analytic / stochastic / dimensional / experiment),
produces cross-method deltas, applies the `R1` / `R2` / `R3` validation
contract from Cámara 2023, and renders the case-study deliverable.

Pairs with:

- `notes/workflow.md` -- pipeline contract; comparison is the final
  consumer of every per-method `<scenario>/<profile>.json`.
- `CLAUDE.md` "Validation criteria (Cámara 2023)" -- R1 fail rate
  ≤ 0.03 %, R2 response time ≤ 26 ms, R3 minimise cost subject to R1∧R2.
- `notes/cs_context.md` and `notes/cs_objective.md` -- the case-study
  narrative this method writes the conclusion of.
- `01-analytic.ipynb`, `02-stochastic.ipynb`, `03-dimensional.ipynb`,
  `04-yoly.ipynb`, `05-experimental.ipynb`, `06-yoly-experimental.ipynb`
  -- inputs.

## 1. The problem this solves

The case study has four green methods today:

| Method | Outputs | Notebook |
|---|---|---|
| **analytic** | closed-form QN metrics per (adp, prf) | `01-analytic.ipynb` |
| **stochastic** | SimPy DES ground truth + 95 % CIs | `02-stochastic.ipynb` |
| **dimensional** | π-groups + 4 coefficients + sweeps | `03-dimensional.ipynb` + `04-yoly.ipynb` |
| **experiment** | real FastAPI mesh, measured operational metrics | `05-experimental.ipynb` + `06-yoly-experimental.ipynb` |

Each method writes
`data/results/<method>/<scenario>/<profile>.json` and
`<scenario>/requirements.json`. **Nothing reads them as a set yet.**

The comparison method is the only one that:

1. **Closes the verdict loop**: applies R1/R2/R3 across all four methods
   and reports where they agree/disagree.
2. **Quantifies cross-method delta**: e.g. analytic vs experiment
   `W_net` ratio under the same `(adp, prf)` -- a published number that
   demonstrates DASA's tech-agnosticism.
3. **Produces the dissertation's headline plot**: per-adaptation
   verdict matrix + cross-method coefficient agreement.

Without method 5, the case study is **4/5 methods complete with no
deliverable conclusion**. With method 5, the case study is the
deliverable.

## 2. Scope and non-scope

**In scope** (single-PR-shaped, mirrors scale-2.md / distribute.md
discipline):

- New module `src/methods/comparison.py` with `run(adp, prf, scn, wrt,
  method_cfg=None) -> dict` and `main()` CLI. Standard orchestrator
  contract (matches the other four methods).
- New thin notebook `07-comparison.ipynb` at repo root. Imports
  `src.methods.comparison`, displays results, holds narrative
  markdown. Same thinness rule as the other four notebooks.
- Reads the four method JSONs by path; produces:
  - **per-(adp, prf) verdict table**: R1 / R2 / R3 status from each
    of the four methods + a consensus column ("all PASS" / "some FAIL").
  - **cross-method deltas table**: pairwise relative differences for
    `W_net`, `avg_rho`, `max_rho`, `L_net`, `epsilon` between every
    pair of methods, per (adp, prf).
  - **decision plot**: the dissertation's headline figure -- a 4-row
    × 4-column matrix (rows = methods, cols = adaptations) coloured
    by R1/R2/R3 verdict, with a final "consensus" column.
- New plotters in `src/view/comparison.py` (single small file, not a
  family) for the verdict matrix + the cross-method delta heatmap.
- New tests `tests/methods/test_comparison.py`: ~10 cases covering
  the verdict-loading contract, the delta math, and the consensus
  rule.

**Out of scope** (single-PR discipline):

- Re-deriving any per-method numbers. Comparison **only consumes**;
  if a method's JSON is stale, the user re-runs that method first.
- Statistical significance tests across stochastic CIs. The existing
  stochastic CIs are reported per-method; comparison reads them and
  flags overlap, doesn't re-test.
- New requirements beyond R1/R2/R3. Cámara 2023 fixed the contract.
- Modifying any of the four green methods. They're frozen as inputs.
- `loopback_aliased` / `remote` deployment splits in the comparison
  output. The experiment method's output already carries the
  `deployment` axis; comparison reads whatever is on disk.

## 3. Inputs / outputs

### Inputs (per `(adaptation, profile)` pair)

```
data/results/analytic/<scenario>/<profile>.json
data/results/stochastic/<scenario>/<profile>.json
data/results/dimensional/<scenario>/<profile>.json
data/results/experiment/<deployment>/<scenario>/<profile>.json
```

Plus per-method `requirements.json` next to each profile JSON.

The `<deployment>` axis on the experiment side is the only complication
-- comparison defaults to reading `local/` (today's path), with a
`--deployment` flag for `loopback_aliased` / `remote` once those
benches are in. Falls back to bare-path (legacy) silently when the
deployment-segmented path is absent.

### Outputs

```
data/results/comparison/<scenario>/<profile>.json
data/results/comparison/<scenario>/requirements.json
data/results/comparison/<scenario>/cross_method_deltas.json
data/img/comparison/<scenario>/verdict_matrix.{png, svg}
data/img/comparison/<scenario>/cross_method_deltas.{png, svg}
```

Single JSON per (adp, prf) carrying:

```json
{
    "scenario": "baseline",
    "profile": "dflt",
    "methods": ["analytic", "stochastic", "dimensional", "experiment"],
    "verdict_per_method": {
        "analytic": {"R1": {...}, "R2": {...}, "R3": {...}},
        "stochastic": {...},
        "dimensional": {...},
        "experiment": {...}
    },
    "consensus": {"R1": "PASS", "R2": "PASS", "R3": "FAIL"},
    "metrics_per_method": {
        "analytic": {"W_net": 0.012, "avg_rho": 0.41, ...},
        ...
    },
    "deltas": {
        "W_net": {
            "analytic_vs_stochastic": 0.018,
            "analytic_vs_experiment": 0.087,
            ...
        },
        ...
    }
}
```

## 4. Module map and contracts

| Module | New / edited | Public surface |
|---|---|---|
| `src/methods/comparison.py` | NEW | `run(adp, prf, scn, wrt, method_cfg=None) -> dict`; `main()` CLI |
| `src/view/comparison.py` | NEW | `plot_verdict_matrix(verdict, *, title, file_path, fname, verbose) -> Figure`; `plot_cross_method_deltas(deltas, metrics, *, title, file_path, fname, verbose) -> Figure` |
| `src/io/__init__.py` | EDITED | new `load_method_result(method, adp, prf, scn) -> dict` helper that knows the per-method path layout (handles the `experiment/<deployment>/` segment too) |
| `tests/methods/test_comparison.py` | NEW | `TestComparisonRun`, `TestConsensusRule`, `TestDeltaMath` |
| `tests/view/test_comparison.py` | NEW | `TestVerdictMatrix`, `TestCrossMethodDeltas` (figure axes / save shape only) |
| `data/config/method/comparison.json` | NEW | `{"metrics": ["W_net", "avg_rho", "max_rho", "L_net", "epsilon"], "delta_threshold": 0.10, "default_deployment": "local"}` |
| `07-comparison.ipynb` | NEW | thin notebook calling `comparison.run` over the 4-adaptation matrix; displays verdict matrix + delta heatmap; markdown narrative |

`run()` contract:

```python
def run(adp: Optional[str] = None,
        prf: Optional[str] = None,
        scn: Optional[str] = None,
        wrt: bool = True,
        method_cfg: Optional[Dict[str, Any]] = None,
        deployment: Optional[str] = None) -> Dict[str, Any]:
    """*run()* compare every method's output for one (profile, scenario) pair.

    Reads the four per-method JSONs from `data/results/<method>/...`,
    extracts the network-level metrics and the R1/R2/R3 verdict from each,
    computes pairwise deltas between methods, and resolves a consensus
    verdict (PASS only when every method PASSes).

    Args:
        adp: adaptation; one of baseline / s1 / s2 / aggregate.
        prf: profile stem (dflt / opti).
        scn: explicit scenario name.
        wrt: persist outputs under data/results/comparison/<scenario>/.
        method_cfg: inline override (test path; skips JSON read).
        deployment: experiment-side deployment axis (local / loopback_aliased / remote).

    Returns:
        Dict carrying verdict_per_method, consensus, metrics_per_method, deltas, paths.

    Raises:
        FileNotFoundError: when any of the four method JSONs is absent.
    """
```

## 5. The "missing input" failure mode

The comparison method must **fail fast and clearly** when one of the four
methods has not been run for the given `(adp, prf)`. The error message
should tell the user exactly which method to run first:

```
ComparisonInputError: experiment result for (adaptation=s2, profile=opti)
not found at data/results/experiment/local/s2/opti.json. Run
`python -m src.methods.experiment --adaptation s2` before comparison.
```

This is the single most common operator mistake on a 5-method matrix.

## 6. The consensus rule

R1 / R2 / R3 verdicts are PASS/FAIL booleans per method. The consensus
column is **strict AND** -- a metric only PASSes consensus when every
method PASSes it. Rationale:

- A method-level FAIL signals that some technology stack on some
  modelling assumption sees the requirement violated. Even if three
  out of four agree it passes, the dissenter is documenting a real
  failure mode.
- The dissertation conclusion explicitly wants "DASA holds across
  every method" -- consensus PASS on every adaptation under R1∧R2 is
  the load-bearing claim.
- When consensus FAILs, the per-method column shows which method
  dissented, and the user investigates the why (often a stochastic CI
  that brackets the threshold, or an experiment under-saturation
  artefact).

Recorded in the JSON as:

```json
"consensus": {
    "R1": "PASS",
    "R2": "FAIL",
    "R3": "PASS",
    "R2_dissenting_methods": ["experiment"]
}
```

## 7. Cross-method delta math

For every metric `m` (default set: `W_net`, `avg_rho`, `max_rho`,
`L_net`, `epsilon`) and every pair `(method_a, method_b)`:

```
delta(m, a, b) = (m[b] - m[a]) / |m[a]|        if m[a] != 0 else 0.0
```

This is the same ratio convention as `01-analytic.ipynb`'s
`delta = (opti - dflt) / |dflt|`. Reported per-pair in the result
envelope. The headline plot collapses to a per-metric × per-pair heatmap
with a `delta_threshold` line (default 10 %) marking "agreement" vs
"divergence".

## 8. Audit gates

Mirrors scale-2.md / distribute.md gating discipline:

| Gate | Artifact | Pass criterion | Status |
|---|---|---|---|
| **G1** | `src/io/__init__.py::load_method_result` + new `data/config/method/comparison.json` | round-trip loads each method's `<scenario>/<profile>.json` for the existing baseline runs; raises `FileNotFoundError` with a clear message when missing | PENDING |
| **G2** | `src/methods/comparison.py::run` + `main` | `python -m src.methods.comparison --adaptation baseline --profile dflt` produces a valid envelope on disk; consensus rule and delta math match hand-computed values | PENDING |
| **G3** | `tests/methods/test_comparison.py` | ~10 cases green: missing-input failure, consensus AND-rule, delta sign + magnitude, persistence shape | PENDING |
| **G4** | `src/view/comparison.py` (`plot_verdict_matrix`, `plot_cross_method_deltas`) + tests | figure axes labelled; PNG + SVG written; matches the project's view-conventions (text colour, mathtext labels, neutral palette) | PENDING |
| **G5** | `07-comparison.ipynb` | thin notebook runs end-to-end across the (4 adaptations × 2 profiles = 8) matrix; produces consolidated tables + the headline figure; markdown carries the dissertation conclusion paragraph | PENDING |
| **G6** | Real-world bench: full case-study matrix run | every (adp, prf) cell produces a verdict; R1/R2/R3 PASS/FAIL counts per method tabulated; agreement/divergence findings recorded in `notes/devlog.md` | PENDING |
| **G7** | Documentation sync | `notes/workflow.md` updated with method-5 row; `CLAUDE.md` "Method module conventions" gains the comparison-method contract; case-study narrative in `notes/cs_objective.md` updated with the method-5 deliverable | PENDING |

## 9. Audit batches (rollback points)

- **Batch 1: G1 + G2 + G3** -- pure code + tests; no notebooks, no plots. Revert = `git restore` of 4 files. The CLI is testable end-to-end against existing on-disk data.
- **Batch 2: G4** -- plotters + their tests. Revert = one `git restore` of the new `src/view/comparison.py` and its test.
- **Batch 3: G5** -- notebook. Revert = one `git rm`. Tests + plotters stay.
- **Batch 4: G6 + G7** -- bench + docs. Passive observation, no rollback risk.

## 10. Effort + sequencing

| Step | Deliverable | Effort | Dependencies |
|---|---|---|---|
| S0 | This file | done | -- |
| S1 | `load_method_result` + `comparison.json` | 0.1 d | -- |
| S2 | `comparison.run` + `main` | 0.4 d | S1 |
| S3 | Tests | 0.4 d | S2 |
| S4 | View plotters + their tests | 0.5 d | S3 |
| S5 | `07-comparison.ipynb` thin notebook | 0.2 d | S4 |
| S6 | Bench + devlog entry | 0.2 d | S5 |
| S7 | Docs sync | 0.1 d | S6 |
| **Total** | -- | **~1.9 d** of focused work | -- |

Recommended order: **S1 -> S2 -> S3 -> S4 -> S5 -> S6 -> S7**.

## 11. Risks and mitigations

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| Stale per-method JSON pinned by an old config | High | Medium -- consensus changes silently when one method's input rots | Every per-method JSON already carries `method_config` snapshot; comparison hashes that snapshot and surfaces "config drift detected" when two methods disagree on the same `(adp, prf)` config |
| Cámara 2023 R1/R2/R3 thresholds drift | Low | High -- the case-study verdict is anchored to those numbers | Pin the thresholds in `comparison.json` (currently in `analytic`'s `check_reqs`); single source of truth |
| Stochastic CI overlap with R2 threshold flagged as PASS when the mean is above | Medium | High | Comparison reports both the mean and the upper CI bound for stochastic; consensus rule treats CI-overlap-with-threshold as FAIL by default (configurable via `comparison.json::ci_treatment`) |
| Cross-method delta on `epsilon` is huge because analytic uses the seeded `_setpoint` while experiment measures end-to-end | High | Medium -- plot looks alarming but it's a known systematic gap | Document explicitly in the notebook narrative: epsilon comparison is between "seeded" (analytic / dimensional) and "measured" (stochastic / experiment); use as a gut check, not a verdict |
| 4-row × 4-col verdict matrix doesn't fit the dissertation page width | Medium | Low | Two layouts: portrait (4 rows × 5 cols including consensus) for full-page; landscape (5 rows × 4 cols) for embed |
| Operator forgets to run experiment before comparison | High | Low | Fail-fast error message names the exact CLI to fix it (see § 5) |

## 12. Summary table

| Dimension | Value |
|---|---|
| **Estimate (calendar)** | ~1.9 working days from green start to G7 close |
| **Estimate (effort, no waiting)** | ~12-14 hours of focused work |
| **Files added (5)** | `src/methods/comparison.py`, `src/view/comparison.py`, `tests/methods/test_comparison.py`, `tests/view/test_comparison.py`, `07-comparison.ipynb`, `data/config/method/comparison.json` |
| **Files edited (3)** | `src/io/__init__.py` (new `load_method_result`); `notes/workflow.md`; `CLAUDE.md` |
| **Files NOT touched** | every existing method module + their tests + their notebooks; profile JSONs; PACS schemas; calibration; vernier; LOG_COLUMNS; all wire schemas |
| **Lines of code (rough)** | ~250 in `comparison.py` + ~200 in `comparison.py` plotters + ~250 in tests + ~80 in notebook = ~780 net |
| **Default cost** | running comparison is < 1 s per `(adp, prf)` -- pure JSON read + math; no DES / HTTP traffic |
| **Top risk** | stale per-method JSONs producing misleading consensus; mitigated by config-hash drift detection |
| **Top blocker** | none foreseen; every input is on-disk JSON the four other methods already produce |
| **Reversibility** | High -- 5 new files + 3 additive edits; revert is mechanical |
| **What this proves** | the case study has a closed verdict loop. R1/R2/R3 status reported per method AND as consensus across all four. The dissertation's headline claim ("DASA's predictions hold across analytic + stochastic + dimensional + experimental methods") is now backed by one published table + one figure. |

## 13. The dissertation deliverable

After comparison ships, the case study has these conclusions to publish:

1. **Per-adaptation verdict matrix** (4 rows × 5 cols including consensus): how R1/R2/R3 verdicts move from baseline → s1 → s2 → aggregate across all four methods.
2. **Cross-method agreement table**: per-metric delta between every method pair, per (adp, prf). Threshold-coloured (default ±10 %).
3. **Headline figure**: condensed verdict matrix + cross-method consensus column, suitable for the case-study results section of the thesis.
4. **Confidence statement**: "Across 4 modelling methods × 4 adaptations × 2 profiles (32 cells), DASA's predictions agree on R1∧R2 in N out of 32 cells and disagree on M cells, with the dissenters quantified." That sentence is the case study's punch line.

Without method 5, the thesis chapter ends mid-paragraph. With method 5, it has a paragraph that the committee can grade.

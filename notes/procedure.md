# Procedure — methodology + proof structure for the DASA evaluation of TAS

> Scaffold. Filled in as the new software-architecture experiment refactor lands. Replaces the archived `notes/workflow.md` (live at [`__OLD__/notes/workflow.md`](../__OLD__/notes/workflow.md)).

## Scope

What this document specifies:

- The hypotheses under test (predictive H1, congruent H2) and what would falsify each.
- The two-stage proof structure: precondition gate (calibration) → hypothesis test (experiment).
- The method-by-method contract: inputs, outputs, acceptance criteria, audit surface.
- The cross-method comparison gate that produces R1/R2/R3 verdicts.

What this document does NOT specify:

- The case study itself — see [`notes/case-study.md`](case-study.md).
- The prototype apparatus design — see [`notes/prototype.md`](prototype.md).

## Hypotheses

> TBD — pull H1 (predictive: dimensional viable region predicts prototype R1∧R2∧R3) and H2 (congruent: 4 methods agree within DASA-side tolerance) from the closed memory entry `project_proof_framework_2026_04_30.md` once the new build's tolerance is settled.

## Two-stage proof

> TBD — calibration as precondition gate (≤ 5 % noise floor), experiment at DASA's approximation budget. See archived [`__OLD__/notes/calibration.md`](../__OLD__/notes/calibration.md) for the closed C0-C11 build's gating contract; the new build's gating is yet to be specified.

## Method contracts

Five evaluation methods exercising the full adaptation axis (`baseline`, `s1`, `s2`, `aggregate`):

| Method | Module | Notebook | Status | Produces |
|---|---|---|---|---|
| analytic | `src/methods/analytic.py` | `01-analytic.ipynb` | live | closed-form QN metrics |
| stochastic | `src/methods/stochastic.py` | `02-stochastic.ipynb` | live | SimPy DES with 95 % CIs |
| dimensional | `src/methods/dimensional.py` | `03-dimensional.ipynb` + `04-yoly.ipynb` | live | π-groups + coefficients + sensitivity |
| experiment | (new build under `src/experimental/`) | (new) | refactor in progress | tech-agnostic prototype run |
| comparison | TBD | TBD | pending | cross-method deltas + R1/R2/R3 verdicts |

Per-method contracts (input config, output schema, acceptance criteria) — TBD.

## Cross-method comparison

> TBD — what `comparison` aggregates, the tolerance on H2 congruence, and the per-requirement (R1 / R2 / R3) verdict rule.

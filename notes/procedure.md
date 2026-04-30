# Procedure — CS-01 TAS proof of DASA's predictive and congruent claims

This document is the CS-01 instantiation of the four-piece experimental-design
discipline. It absorbs the previous `notes/proof.md` (hypothesis-side) and
`notes/experiment.md` (procedure-side); both have been deleted in favour of
this single document.

The whole CS-01 TAS repository IS the experiment. Its purpose is to validate
the DASA methodology — specifically, that the dimensional coefficients and
the yoly chart can predict runtime behaviour and represent trade-off effects
well enough to support informed architectural decisions.

## 0. Scope and references

| Layer | Document | Role |
|---|---|---|
| Methodology (authoritative) | `.claude/skills/design/experimental-design.md` | four-piece structure |
| Methodology (complement, distinct subset) | `.claude/skills/design/mva-framework.md` | MVA framing |
| Prototype-side discipline (complement) | `.claude/skills/develop/architectural-experiments.md` | DASA architectural-experiment patterns |
| Apparatus FR | `notes/prototype.md` | what the experiment apparatus must do |
| Method-5 implementation plan | `notes/comparison.md` | validation-step build-out |
| Calibration runner reference | `notes/calibration.md` | precondition gate + envelope schema |
| Pipeline contract | `notes/workflow.md` | 5-method × 4-adaptation matrix |
| MVA framework full summary | `assets/docs/architecture_experimentation.md` | Pureur & Bittner (InfoQ 2024) |

On any conflict between this document and the authoritative skill, defer
to the skill.

---

## 1. Hypothesis

### 1.1 H1 — predictive

> DASA's dimensional model bounds a viable region on the Yoly chart such
> that prototype configurations whose measured coefficients fall inside
> the region satisfy R1 ∧ R2 ∧ R3, and configurations outside the region
> fail at least one of R1 / R2 / R3.

Cámara R1/R2/R3:

- **R1**: failure rate ≤ 0.03 % (Availability)
- **R2**: response time ≤ 26 ms (Performance)
- **R3**: minimise cost subject to R1 ∧ R2

**Falsifier.** Any predicted-viable configuration that fails any of
R1/R2/R3 in practice; OR any predicted-infeasible configuration that
passes all of them.

### 1.2 H2 — congruent

> The four methods (analytic, stochastic, dimensional, experimental)
> produce equivalent operational coefficients within the model's own
> approximation tolerance for every operating point in the hypothesis-set
> grid.

**Falsifier.** Any pairwise residual exceeds the DASA-side tolerance for
the same `(c, K, μ, λ)` operating point, on any metric in the comparison
matrix.

### 1.3 H1 and H2 are independent

H1 tests **methodological utility** (does the model help engineer a
working configuration?). H2 tests **methodological internal consistency**
(do the four observation modalities agree on the same architecture?).

One can fail without the other:

- H2 holds, H1 fails → the four methods agree but their consensus does not predict R1/R2/R3 → the model is internally consistent but wrong about reality
- H1 holds, H2 fails → the prediction works for the verdict but coefficients do not transfer cleanly across methods → locate the gap

### 1.4 Decision rule per hypothesis

| Hypothesis | Form | Decision rule |
|---|---|---|
| H1 | verdict agreement | Accept iff every per-cell `(R1, R2, R3)` bit on the prototype matches the dimensional viable-region prediction |
| H2 | equivalence within tolerance | Accept iff every pairwise residual ≤ τ on every metric for every hypothesis-set trial |

Failure cases on either hypothesis are reported as
`(artifact, adaptation, operating-point) + residual` per
`.claude/skills/design/experimental-design.md::§4 Validation`.

### 1.5 Tolerance discipline

Per `memory/feedback_calibration_vs_model_error.md`, **calibration error
and model error are orthogonal**.

| Layer | Bound | Role |
|---|---|---|
| **Calibration** (irreducible host noise) | ≤ 5 % on simple host-floor probes | Precondition gate; not a hypothesis tolerance |
| **DASA-side** (model approximation budget) | derived from the model's stated approximations; values OPEN | Hypothesis tolerance |

The DASA-side tolerance comes from the model's own approximation budget
(M/M/c/K's ignored 2nd-order effects, Markovian-arrival residue, MC
variance for the stochastic method). The placeholder until the model-budget
derivation lands is `±5 %` on ρ and `±15 %` on W; these are working
defaults, not principled values.

**Sample size derivation.** For each metric on each operating point:

```
n_min = ceil( (1.96 * sigma_op / tau_DASA) ** 2 )
```

`n_min` drives `data/config/method/experiment.json::min_samples_per_kind`
per trial. Cannot be pinned numerically until `tau_DASA` is articulated;
current placeholder is the CLT floor `min_samples_per_kind = 32`.

---

## 2. Model — the prediction artefacts

The model is the source of the prediction the prototype is compared
against. It is a separate artefact; the prototype must not re-derive it.
This is the four-piece skill's `§2 Model` discipline applied to CS-01.

### 2.1 Validity envelope

DASA's analytic method assumes:

- M/M/c/K queues (Markovian arrivals, exponential service, finite buffer K)
- closed Jackson network (no external blocking; routing matrix is fixed)
- ρ < 1 per node (saturation is OUTSIDE the envelope; tested separately)
- finite source if the case requires it

**Operating points must lie inside this envelope.** Trials with ρ → 1 or
saturated K are envelope-edge work and test the model's limits, NOT the
hypotheses (`§5 Set B` below).

### 2.2 Per-method prediction sources

| Method | Module | Output artefact |
|---|---|---|
| analytic | `src/methods/analytic.py` (closed-form M/M/c/K) | `data/results/analytic/<scn>/<profile>.json` |
| stochastic | `src/methods/stochastic.py` (SimPy DES, 95 % CIs) | `data/results/stochastic/<scn>/<profile>.json` |
| dimensional | `src/methods/dimensional.py` (Pi-groups, Yoly) | `data/results/dimensional/<scn>/<profile>.json` |

### 2.3 Inputs the predictions are computed from

`data/config/profile/<profile>.json` — DASA knobs (`μ`, `ε`, `c`, `K`,
routing) at the **artifacts** layer (frozen Cámara canonical) for
prediction; the **specs** layer (host-bounded, binpacked) is consumed
only by the prototype.

Method-specific tunables in `data/config/method/<method>.json`.

### 2.4 What the prototype must NOT recompute

Per `.claude/skills/design/experimental-design.md::§3 Prototype`: the
prototype reads inputs verbatim from the same profile JSON the model
reads, but it **does not re-derive the prediction**. The prediction
JSONs in `data/results/<method>/...` are opaque inputs to the validation
step; the prototype never reads them.

This rule keeps the model and prototype independent. Violating it
prevents the validation step from detecting model errors.

---

## 3. Prototype — the apparatus

### 3.1 Source of truth: `notes/prototype.md`

`notes/prototype.md` is the apparatus FR. It defines what the prototype
does and what raw measurements it persists. This document references
`prototype.md`'s contract; it does not duplicate it.

### 3.2 Architectural-experiments compliance summary

Per `.claude/skills/develop/architectural-experiments.md`, the prototype
implements:

- **K-bounded admission gate** — HTTP 503 at capacity (real tactic, not M/M/c/K simulation)
- **c-permit semaphore** — `asyncio.Semaphore(spec.c)` for in-service handlers
- **μ as exponential delay** — `await asyncio.sleep(random.expovariate(μ))`
- **ε as business failure** — HTTP 200 + `body.success=False` (NEVER HTTP 5xx)
- **Infrastructure failure** — 503 / timeout / real 5xx propagates without retry; trips cascade-stop
- **Profile JSON as sole knob source** — no method-config drift
- **Header-propagated request size** — `X-Request-Size-Bytes`, no psutil
- **Sample-count probes** — `min_samples_per_kind` per kind, not time-based
- **Cascade-stop on infra failures only** — rolling-window or fail-fast, never on business failures

`enforce_limits` (added 2026-04-30) is the profile-wide switch for the
K-gate; defaults to `true`.

### 3.3 Model abstractions enforced in the prototype

| Model assumption (§2.1) | Where enforced in `src/experiment/` |
|---|---|
| Exponential service time | `services/base.py::SvcCtx.draw_svc_time()` (`expovariate(μ)`) |
| Single-server-with-c-permits | `services/base.py::SvcCtx.sem` (`asyncio.Semaphore(c)`) |
| K-bounded buffer | `services/base.py::SvcCtx.try_admit / release` (counter) |
| Bernoulli failure at rate ε | `services/atomic.py` + `services/vernier.py` (`draw_eps()` after admission) |
| Routing-matrix dispatch | `services/composite.py::_dispatch` + `pick_target` callback |
| Closed Jackson network at the entry | `experiment/client.py` weights kinds by `TAS_{1}`'s routing-matrix row |

Violations are reasons for disagreement that are NOT disproof of the
hypothesis. Each row above is an explicit invariant the experiment
preserves.

### 3.4 Operating points

Two disjoint sets:

| Set | Purpose | Predicted utilisations |
|---|---|---|
| **A — hypothesis trials** | Test H1 + H2 inside the validity envelope | ρ ∈ {0.2, 0.5, 0.8, 0.95} per `(c, K, μ)` per adaptation |
| **B — envelope-edge trials** | Test the model's LIMITS (separate experiment) | ρ → 1, K saturated, infeasible bands |

Set B is not part of this proof. Trials in B inform the model's validity
envelope, not the hypotheses.

The set-A grid spans `{baseline, s1, s2, aggregate}` × the predicted-
utilisation set above. Concrete encoding of the grid is open work
(§6).

### 3.5 Sample size per operating point

Derived per §1.5 from `τ_DASA`. Until `τ_DASA` is pinned, trials use the
CLT floor of 32 samples per kind per rate.

### 3.6 What the prototype writes

```
data/results/experiment/<scn>/<profile>.json     # per-node DataFrame summary + run envelope
data/results/experiment/<scn>/requirements.json  # R1/R2/R3 verdict per cell
data/results/experiment/<scn>/<profile>/<service>.csv  # raw per-invocation logs
```

The CSVs follow the `LOG_COLUMNS` schema in `services/base.py`. The
prototype writes raw measurements only — no residuals, no plots, no
verdicts. Analysis lives in the validation step.

---

## 4. Validation — the decision

### 4.1 Source of truth for implementation: `notes/comparison.md`

Method 5 is the validation step. Implementation plan in
`notes/comparison.md`; not yet built. This section pins the inputs,
outputs, and decision logic the implementation must honour.

### 4.2 Inputs

The four prediction JSONs (analytic / stochastic / dimensional from
§2.2) and the experiment JSON + per-service CSVs (§3.6). All read from
`data/results/`. The validation step **never re-runs** any method.

### 4.3 Outputs

```
data/results/comparison/<scn>/requirements.json
```

Contains:

- per-hypothesis verdict (H1 accepted / rejected; H2 accepted / rejected)
- failure-case list: `(artifact, adaptation, operating-point) + residual` for every cell that exceeded its tolerance
- consensus column: per-trial `(R1, R2, R3)` agreed by all methods (or `disagreement` if not)

### 4.4 Plot rubric (deferred)

Three plots per the architectural-experiments skill, deferred until
method 5 lands. Sketch in `notes/comparison.md::Validation rubric`:

1. Yoly chart per trial with viable region shaded + 4 marker styles (analytic / stochastic / dim / exp)
2. y = x scatter per metric (ρ, L, W, θ, σ, η, φ) across all hypothesis-set trials × 4 methods × 6 pairwise comparisons
3. R1 / R2 / R3 verdict table with one column per method + a consensus column

### 4.5 Re-runnable independent of the prototype

Tightening `τ_DASA` does not require rerunning `experiment.run`. The
validation step reads persisted result JSONs and CSVs and re-emits the
verdict. This is the four-piece skill's idempotence rule applied.

### 4.6 Cámara reference handling

| Comparison | Activity | Tolerance |
|---|---|---|
| analytic ↔ Cámara reference | unit test of the M/M/c/K solver | 6 decimal places (already passing in baseline) |
| experimental ↔ DASA prediction | the H1 hypothesis test | DASA-side tolerance (open) |
| experimental ↔ Cámara reference | NOT a hypothesis test | display only; gap = stack overhead |

Anchoring the experimental method to Cámara's numbers would conflate a
unit test with a hypothesis test. See
`memory/feedback_test_vs_experiment_distinction.md`.

---

## 5. Failure modes specific to this proof

### 5.1 Calibration drift between hosts

Calibration is stamped per host. A trial run on host A is not directly
comparable to a trial run on host B unless both calibration envelopes
satisfy the ≤ 5 % gate. Detection: every experiment envelope carries the
calibration `baseline` block; the validation step checks `host_profile`
matches the calibration's host before accepting the trial.

### 5.2 Replication-as-experiment confusion

Reproducing Cámara's 6-decimal numbers is a unit test of the analytic
solver. It does NOT validate H1. Per
`memory/feedback_test_vs_experiment_distinction.md`, the distinguishing
question is: *what would falsify the activity?*

- Unit test fails ⇒ code is broken
- Replication fails ⇒ reference misread
- Experiment fails ⇒ the *hypothesis* is wrong

Don't anchor experimental success to authors' numbers.

### 5.3 Calibration-noise-as-tolerance confusion

Per `memory/feedback_calibration_vs_model_error.md`, conflating
calibration noise (≤ 5 % gate) with hypothesis tolerance (DASA-side,
model-budget-driven) reduces every experiment to a self-fulfilling
prophecy. Calibration is an apparatus precondition; the hypothesis is
tested at a different tolerance against a different reference.

### 5.4 Partial-pass interpretations

| Outcome | Meaning |
|---|---|
| H1 holds, H2 holds | Proof passes |
| H1 fails, H2 holds | The four methods agree on a prediction that doesn't match prototype reality. Locate where the model deviates from observable behaviour |
| H1 holds, H2 fails | Prediction works for the binary R1/R2/R3 verdict but coefficients diverge between methods. Locate the cross-method gap |
| H1 fails, H2 fails | Both axes broken; revisit the model's approximations and the prototype's invariant compliance independently |

Partial passes are valid scientific outputs. Falsification ends the
proof on that hypothesis alone.

---

## 6. Open work blocking the proof

| Item | Blocks |
|---|---|
| Articulate the model's approximation budget → `τ_DASA` numerical | §1.5 sample-size derivation, every numeric tolerance in §4 |
| Build `src/methods/comparison.py` (method 5) | All of §4 |
| Encode the set-A operating-point grid as a profile/scenario fixture | §3.4 |
| Extend `plot_yoly_chart` with viable-region shading | §4.4 plot 1 |
| Define the DASA viable-region predicate from R1/R2/R3 | §4.4 plot 1 + consensus column |

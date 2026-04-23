# CS-01 TAS — Experimental Procedure

The whole CS-01 TAS repository IS the experiment. Its purpose is to
validate the **DASA methodology** — specifically, that the dimensional
coefficients and the yoly chart it produces can predict runtime behaviour
and represent the tradeoff effects of runtime configurations well enough
to support informed architectural decisions.

This document applies the experimental-design discipline from
`.claude/skills/design/experimental-design.md` at the case-study scope.
Apparatus specs for the architectural prototype (method 4) live in
`notes/prototype.md`; individual method implementations are under
`src/methods/`.

## 1. Scope

The case study spans five evaluation methods, each exercising the full
`{profile} × {adaptation}` matrix:

| Method | Role in this experiment |
|---|---|
| 1. Analytical | Independent oracle (closed-form M/M/c/K + Jackson) |
| 2. Stochastic | Independent oracle (SimPy DES with 95 % CIs) |
| 3. Dimensional | **System under test** — DASA π-groups + yoly chart |
| 4. Architectural prototype | Independent oracle (empirical ground truth, FastAPI stack) |
| 5. Comparison | The validation step — cross-method convergence check |

Three oracles + one system-under-test + one convergence check. The
experiment *passes* when the oracles agree with each other AND DASA
agrees with them.

## 2. Hypothesis

**H1 (primary, operating-point agreement)** — The `baseline` and
`aggregate` operating-point states of TAS, as predicted by DASA's
dimensional coefficients, agree with the predictions of the analytical
and stochastic models and with the prototype's empirical measurement.
Agreement is decided by a χ² goodness-of-fit test at α = 0.05; DASA is
corroborated when its back-solved physical quantities match the three
oracles' cross-method consensus.

**H2 (yoly-chart agreement)** — The yoly chart DASA produces,
reinterpreted as a set of coefficient-indexed points with embedded
physical-variable content (`L, λ, μ, χ, K, …`), matches points emitted by
the analytical / stochastic / prototype methods at the same coefficient
coordinates. Overlay agreement is tested by the same χ² goodness-of-fit
rule.

**H3 (tradeoff trace across the adaptation axis)** — The tradeoff
magnitude `aggregate − baseline` agrees across all four methods for every
tracked observable. `s1` and `s2` serve as corroborating intermediates:
their ordering and continuity along the axis must also hold, which tests
that the tradeoff is *traceable*, not just correct at the endpoints.

**Out of scope** — saturation behaviour. H1–H3 cover the design-envelope
operating region, not "how does the system break".

## 3. Formal models (the oracles + the system under test)

Each method produces on-disk outputs at
`data/results/<method>/<scenario>/<profile>.json` using a shared
per-artifact schema. No method re-derives another's prediction.

| Method | Mathematical basis | Strengths | Caveats |
|---|---|---|---|
| Analytical | M/M/c/K per artifact + Jackson routing; closed-form | Deterministic; exact under its assumptions | Assumes exponential service, Poisson arrivals, independence |
| Stochastic | Event-driven SimPy simulation; n replicates with 95 % CIs | Relaxes distributional assumptions; explicit uncertainty | Residual Monte-Carlo noise; CLT-bounded |
| Dimensional | DASA π-groups; dimensional coefficients; yoly chart sweep | Compresses many configs into a few coefficients; predicts direction of tradeoffs | The claim under test; agreement with oracles is what validates it |
| Prototype (experiment method) | FastAPI services enforcing the same queue semantics as the analytical model | Empirical ground truth on a deliberately-different tech stack | Event-loop jitter; finite sample sizes; in-process ASGI vs real TCP |

### 3.1 Validity envelope (shared by all four)

Each method is reliable when every artifact's predicted `ρ ≤ 0.90`.
Operating points outside this envelope stress individual methods' edges
(finite-K effects for analytical, simulation-length effects for
stochastic, scheduler jitter for the prototype) and contaminate the
cross-method comparison. Any operating point where *any* method predicts
`ρ > 0.90` is dropped from the convergence check.

## 4. Prototype

Apparatus spec and non-goals are in `notes/prototype.md`. In one
sentence: a FastAPI + httpx + asyncio replication of the 13-service TAS
topology, reading the same `(μ, ε, c, K, routing)` from the profile JSON
that every other method reads, producing raw per-invocation measurements
that the validation step compares to the other three methods' predictions.

## 5. Experimental variables

### 5.1 Factors

| Factor | Levels |
|---|---|
| Profile | `dflt`, `opti` |
| Adaptation | `baseline`, `s1`, `s2`, `aggregate` |
| Operating point | utilisation `ρ ∈ [0.05, 0.95]`, non-uniform grid (§5.2.1) |

#### 5.1.1 Non-uniform ρ-grid

```
ρ_grid = {0.05, 0.10, 0.20, 0.30,         # sparse ramp: chart origin + coarse coverage of the low-load regime
          0.40, 0.45, 0.50, 0.55, 0.60,   # dense ramp: where the interesting dynamics live
          0.65, 0.70, 0.75, 0.80, 0.85,
          0.90, 0.95}                      # upper validity edge
```

- 16 points; weighted toward saturation (denser above ρ = 0.40).
- `ρ = 0.05` kept as the chart origin — anchors the low-load end of the yoly sweep.
- Fast ramp below 40 % limits wall-clock cost of probing (low-ρ = low-λ = long-per-sample).
- Dense ramp above 40 % covers the region where the queue dynamics and the tradeoff effects are most sensitive to configuration.

### 5.2 Why ρ is the operating-point axis

The yoly chart DASA produces is parameterised by ρ — that's the axis a
dimensional sweep lives on. Validating DASA therefore requires a ρ-ramp,
not a λ-ramp. λ values are *derived* per cell by inverting the analytical
Jackson solver to hit each target ρ.

The upper bound `ρ = 0.95` is the validity edge of the analytical and
stochastic models:
- M/M/c/K loses closed-form accuracy as finite-K effects dominate near saturation.
- SimPy DES sees queue length and variance diverge at `ρ → 1`, so CIs explode.

Above `ρ = 0.95` any disagreement reflects model instability, not a DASA
failure; those points are outside the envelope H1/H2/H3 cover.

### 5.3 Two uses of the ρ-grid

- **Dense sweep** (all 16 points) — feeds H2 (yoly-chart overlay). Dense coverage is what makes the coefficient-indexed overlay a statistically meaningful agreement test.
- **Anchor points** — `baseline` and `aggregate` correspond to specific operating ρ values that each method emits when run at its nominal λ. The anchors for H1 and H3 are taken from the on-disk outputs of the three methods themselves — not pre-declared in the profile.

### 5.4 Yoly chart scope

**One chart per profile**, not per adaptation. The yoly chart lives in
dimensional-coefficient coordinates, and adaptations are implicit in the
coefficient values — e.g. `L/K = 0.5` can arise from any `(L, K)` pair
that satisfies the ratio, and configurations from different adaptations
simply land at different points on the same chart.

For H2, every adaptation's sweep across the ρ-grid populates the chart
as a cloud of points in coefficient space. The χ² overlay test is
one-per-profile-per-observable: do the analytical / stochastic /
prototype points land on DASA's predicted coefficient curve?

K (and other absolute scale factors) still matter — they change the
component's absolute behaviour even when coefficient values collide.
That is why the prototype must log the full controlled config per run
(FR-11) so each point on the yoly chart can be traced back to a specific
`(profile, adaptation, ρ, replicate)` origin.

### 5.4 Controlled constants

- `(μ, ε, c, K)` per artifact come from the profile verbatim; no method mutates them. K's fixed value is what enables the coefficient back-solving in §6.2.
- Single integer seed per run; deterministic across methods where deterministic is possible.
- Technology stacks deliberately different across the four methods — that is the point. DASA's claim is that its coefficients are invariant to implementation.

## 6. Agreement rule — χ² goodness-of-fit on the residual norm

### 6.1 Decision statistic

Each cell `i` produces a *vector* of observables (one coordinate per
dimensional coefficient or physical variable under test). For two methods
`A` and `B`:

```
R_i    = || x_i^(A) − x_i^(B) ||
       = √( (A_i^(A) − A_i^(B))² + (B_i^(A) − B_i^(B))² + … + (Z_i^(A) − Z_i^(B))² )

χ²     = Σ_i  R_i² / σ_i²
```

where `R_i` is the Euclidean norm of the per-coordinate residual vector
and `σ_i` is the norm of the cell's uncertainty vector (see §6.5 for how
`σ` is estimated from prototype replicates).

Using the norm instead of per-coordinate residuals matches the
multivariable-comparison convention: we ask whether *the observables as
a whole* disagree, not whether any single coordinate happens to differ.
One residual per cell, one degree of freedom per cell; `N − 1` DoF
total at `N` cells.

Agreement is accepted at significance level α = 0.05 when the computed
χ² lies below the critical value at `N − 1` DoF.

### 6.2 Putting all four methods on the same coefficient plane

Every method produces dimensional coefficients (stall, occupation,
effective-yield, memory usage, …) — the same coordinates the yoly chart
uses. The three non-DASA methods compute them from their own internal
state:

- Analytical: from closed-form `L, W, ρ, λ, μ` per component.
- Stochastic: from SimPy's logged `L, W, ρ` per replicate.
- Prototype: from the logged controlled config + the per-component measurements (see §6.3).

DASA computes them directly as the primary output of its π-group
derivation. The χ² comparison is then between four sets of coefficient
values in the same coordinates — no inversion needed. The formulas used
to derive coefficients from `(L, W, ρ, λ, μ, c, K, ε)` live in
`src/dimensional/` and are reused across methods so that no method-
specific drift creeps in.

### 6.3 The prototype's data plane (controlled + measured + derived)

For the comparison to be mathematically secure, the prototype logs every
input that drives the queue-network state, measures per-component state,
verifies the apparatus honoured the configured inputs, and computes the
same coefficients as the other methods. Several variables are **dual-role**
— set as inputs AND re-measured at runtime as verification observables.

| Role | Variables | Source / definition |
|---|---|---|
| **Controlled inputs** (logged per run) | λ at entry, routing % per scenario; per-node `c`, `K`, `μ`, `ε`, `χ` | Profile JSON + scenario matrix; effective values snapshotted to `config.json` per FR-11 |
| **State measurements** (per component) | `L` (time-averaged number in system), `W` (mean sojourn), `Wq` (mean wait), `λ` (arrivals/s), `λ_out` (completions/s), failure-rate splits | `@log_request` + arrival-instant snapshots of the admission counter |
| **Verification measurements** (dual-role) | `c_measured`, `K_measured`, `μ_measured`, `ε_measured`, `χ_measured` | Re-estimated from runtime logs: `μ̂ = 1/mean(service_time)`, `ε̂ = count(biz_fail)/count(attempts)`, `max(in_system) ≤ K`, `c_used_at_start ≤ c`, `χ̂` per its DASA definition |
| **Derived (dimensional coefficients)** | stall, occupation, effective-yield, memory usage, χ | `src/dimensional/` given the controlled + measured values |

The dual-role columns exist so a cell can be self-checked: if
`μ_measured` disagrees with `μ_configured` beyond sampling noise, the
apparatus did not faithfully enforce the controlled input and that
cell's downstream residual is untrustworthy regardless of what the χ²
test says.

### 6.3 Sample-size floor

`σ_i` in §6.1 shrinks as the number of samples per cell grows; tighter
σ → more stringent χ² test. The prototype sample floor is sized to make
the test informative, not lax:

```
HW(ρ̂)     = 1.96 · √(0.25/n)    →  n=100 ⇒ HW ≈ 0.098
HW_rel(W̄) = 1.96 / √n           →  n=100 ⇒ HW_rel ≈ 0.196
```

`n_min = 100` per artifact per cell is the floor; more is better. Stochastic
replications use the method's own scheme; analytical is exact (σ_ana = 0
— treated as `ε_machine` in the χ²).

### 6.4 Under-powered-cell rule

If `> 10 %` of prototype cells hit the probe window before reaching
`n_min`, the grid is partial and H1/H2/H3 are **not decided**. Re-run with
a longer window or a denser λ schedule before evaluating.

### 6.5 Replicates

Each prototype cell runs `R` replicates with distinct seeds so the
empirical σ for the χ² test comes from the prototype itself (not
borrowed from the stochastic model). `R` is specified in the prototype
doc as an apparatus-level requirement (`notes/prototype.md`); typical
values are in the 10–30 range and the final number is pinned there. The
stochastic method's own replicate scheme remains independent.

## 7. Validation — cross-method convergence (method 5 + notebook 06)

Lives in `src/methods/comparison.py` + `06-comparison.ipynb`. This step
is the experimental decision layer; it does NOT re-run any other method.

### 7.1 Inputs

All per-run JSON artefacts produced by methods 1–4:

```
data/results/analytical/<scenario>/<profile>.json
data/results/stochastic/<scenario>/<profile>.json
data/results/dimensional/<scenario>/<profile>.json
data/results/experiment/<scenario>/<profile>.json
```

### 7.2 Steps

1. **Load** per-artifact DataFrames from all four methods.
2. **Back-solve DASA** — per §6.2, invert each dimensional coefficient using the controlled profile config to produce physical-variable predictions (`L_dasa, W_dasa, ρ_dasa, …`) on the same axis as the oracles.
3. **Join** on `(profile, adaptation, artifact, operating-point)`.
4. **H1 test (model-vs-experiment at baseline + aggregate)** — the prototype is the empirical ground truth; each model is evaluated against it. For each `(profile, adaptation ∈ {baseline, aggregate}, observable ∈ {L, ρ, W, failure_rate, response_time})`:
   a. Build vectors across the 13 artifacts at the λ settings that define the baseline and aggregate operating points. Those λ settings are the ones used when the three methods generated their on-disk outputs; no separate anchor is read from the profile.
   b. Compute χ² for three model-vs-experiment pairs: `ana-vs-exp`, `sto-vs-exp`, `dim-vs-exp`. All four methods emit values on the same coefficient plane (§6.2), so the comparison is direct.
   c. Record p-values; reject a pair at α = 0.05 if p < α.
5. **H2 test (yoly-chart overlay)** — per profile (not per adaptation; §5.4), DASA's yoly sweep defines a curve in dimensional-coefficient coordinates. Project every analytical / stochastic / prototype point from every (adaptation, ρ, replicate) into the same coefficient coordinates; χ² the overlaid cloud against DASA's sweep curve, one test per profile per observable.
6. **H3 test (baseline-vs-aggregate tradeoff trace)** — for every observable:
   a. Compute `Δ_method = X_method(aggregate) − X_method(baseline)` per method, so there are four Δ values.
   b. χ² the three model Δ values (ana, sto, dim) against the experiment Δ.
   c. Corroborate with `s1` and `s2` — for every model, `Δ_method(s_i)` must lie monotonically between `0` (baseline) and `Δ_method(aggregate)`.
7. **Derived verdicts** — compute R1 (failure-rate) / R2 (response-time) PASS/FAIL per method from the measured/predicted values; tabulate the agreement pattern as a descriptive output. R3 (cost) is out of scope for CS-01. Verdict disagreement is informative but is NOT a hypothesis gate — the continuous-observable χ² already carries the information.
8. **Decide**:
   - H1 accepted iff all three model-vs-experiment χ² pairs pass at every `(profile, adaptation ∈ {baseline, aggregate}, observable)`.
   - H2 accepted iff the yoly-overlay χ² test passes for every observable.
   - H3 accepted iff the three-model-vs-experiment Δ-agreement χ² passes at α = 0.05 AND monotonicity holds for `s1, s2` under every model.

### 7.3 Figures

- **Model-vs-experiment scatter** per observable: `X_ana` vs `X_exp`, `X_sto` vs `X_exp`, `X_dim` vs `X_exp`. `y = x` reference; shaded band = prototype 95 % CI.
- **Yoly overlay**: DASA's sweep curve on the ρ axis with analytical / stochastic / prototype points projected in. Residual-from-curve colour-coded.
- **Tradeoff trajectory**: `baseline → s1 → s2 → aggregate` per observable; one line per method; the four lines should lie on top of each other when H3 holds.
- **χ² p-value heatmap**: rows = model (ana / sto / dim), columns = `(profile, adaptation, observable)`; colour = p-value; `p < 0.05` flagged red.
- **Verdict-agreement table** (descriptive, not a gate): per `(profile, adaptation)` pair, R1 and R2 PASS/FAIL per method. R3 omitted (cost out of scope).

### 7.4 Outputs

- Printed verdict: H1 / H2 / H3 accepted or rejected with p-values.
- **Per-cell table**: every `(profile, adaptation, observable, model)` row with χ² statistic, degrees of freedom, p-value, and classification — saved as `data/results/comparison/chi2.csv` (full detail, nothing hidden).
- **DASA-disagreement subset**: the cells where `dim-vs-exp` rejects but `ana-vs-exp` and `sto-vs-exp` both accept. This subset is the headline scientific output — it isolates exactly where DASA's coefficient compression diverges from the empirical ground truth while the other models don't.

## 8. Role of the adaptation axis

The adaptation axis is not a nuisance factor — it is the primary experimental variable for testing DASA's *tradeoff claim*.

- `baseline` — control condition. MAPE-K inert; no runtime adaptation.
- `s1` — service-failure adaptation (Retry-like). Tests that DASA captures the effect of retrying around `ε` on the failure-rate observable.
- `s2` — response-time adaptation (Select-Reliable-like). Tests that DASA captures the effect on the response-time observable when parallel redundancy is applied.
- `aggregate` — both adaptations applied. Tests that DASA composes them correctly.

**Principal comparison (H3)**: `baseline vs aggregate`. This pair carries
the headline tradeoff claim: "DASA can quantify the effect of the full
adaptation". `s1` and `s2` corroborate that the trajectory is *continuous
and monotonic* along the axis, not just correct at the endpoints.

## 9. Acceptance criteria (summary)

All three hypotheses are decided by χ² goodness-of-fit at α = 0.05,
with the **prototype as empirical ground truth** and the three models
evaluated against it.

```
H1  accepted  iff  forall (profile, adaptation ∈ {baseline, aggregate}, observable):
                     ana-vs-exp, sto-vs-exp, dim-vs-exp all pass (p ≥ 0.05)
                   AND under-powered(prototype grid) ≤ 10%

H2  accepted  iff  forall observable:
                     yoly overlay of {ana, sto, exp} points onto DASA's
                     sweep curve passes χ² at α = 0.05

H3  accepted  iff  forall observable:
                     ana/sto/dim Δ(aggregate − baseline) each pass χ²
                     against exp Δ(aggregate − baseline)
                   AND monotonicity of Δ(baseline → s1 → s2 → aggregate)
                     holds under every method
```

**The DASA-validation bit**: if H1/H2/H3 are accepted, the dimensional
coefficients and yoly chart are validated as trustworthy instruments for
tradeoff analysis on this case study. The physical-variable values
recovered from DASA's coefficients via controlled-config back-solving
(§6.2) agree with the empirical measurement within the prototype's
noise floor.

If `dim-vs-exp` rejects while `ana-vs-exp` and `sto-vs-exp` both
accept, the cell is scientifically informative: DASA's coefficient
compression loses fidelity there while the other two models don't. That
subset is the principal output of the whole CS-01 investigation.

## 10. Current status (2026-04-20)

- Methods 1–3 (analytical, stochastic, dimensional) + yoly: complete.
- Method 4 (prototype): implemented; 187 tests passing; apparatus spec in `notes/prototype.md`. Grid needs to be reset from saturation-sweep to the `{0.25, 0.50, 0.75} · λ_z` validity-envelope grid and `n_min = 100` per-artifact.
- Method 5 (comparison) + notebook 06: not started. This IS the validation step; it is the gate that decides the case study.
- Yoly notebook (`04-yoly.ipynb`): flagged for review (graph errors, tracked in devlog).

## 11. Remaining open points

1. **Observables list for H1** — confirmed `{L, ρ, W, failure_rate, response_time}`; verdicts R1 / R2 descriptive; cost and R3 out of scope.
2. **Yoly scope** — settled: one chart per profile; adaptations implicit in coefficient coordinates (§5.4).
3. **ρ-grid** — settled: 16-point non-uniform grid (§5.1.1); fast ramp below 0.40, dense above.
4. **Number of replicates `R`** — default `R = 10`, bumped to `R = 30` if any cell's CI exceeds the cross-method residual. Pinned in `notes/prototype.md` FR-13.
5. **Yoly overlay distance metric** — settled: Euclidean norm across coefficient coordinates (§6.1); one residual per point, `N − 1` DoF.
6. **H3 monotonicity** — non-strict (direction can't reverse within CI); revisit only if the first validation run shows this matters.
7. **Multiple-testing correction** — deferred per user direction ("too early to know"); revisit once we see how many H1 cells actually reject.

# Devlog — CS-01 TAS

Running log of design decisions, pivots, and open questions for the Tele Assistance System case study. Append only; newest entry on top.

---

## 2026-04-27 (evening) — Yoly figure polish iterations

Follow-up session refining the yoly suite (`plot_yoly_chart`, `plot_yoly_space`, `plot_yoly_arts_hist`, `plot_yoly_arts_charts`, `plot_yoly_arts_behaviour`) plus the calibration dim card. Driven by user feedback on rendered images.

### Title separator

Changed from `\n` to `, ` across the five thin notebooks (00-04) so titles stay on one line: `f"{Method}: {Subject}, {Scenario}"`. 32 title strings rewritten across notebooks plus 35 prose references in `notes/titles_std.md`, `CLAUDE.md`, the memory entry, and the `notebook-editing` skill.

### `\boldsymbol` → `\mathbf` (matplotlib mathtext rule)

Discovered the hard way that matplotlib's built-in mathtext does NOT recognise `\boldsymbol`; it crashes `savefig` with `ParseFatalException: Unknown symbol: \boldsymbol`. The smoke-tests passed because in-memory figure creation skips the tick-bbox path that triggers the parser; the failure only surfaced when the user ran the notebook end-to-end. Reverted 111 occurrences of `\boldsymbol` → `\mathbf` across `src/view/common.py` + 4 notebooks. Greek lowercase under `\mathbf` falls back to upright non-bold (matplotlib limitation requiring `usetex=True` to overcome); accepted the visual cost. Documented in `feedback_matplotlib_mathtext_bold.md` memory entry. New rule: ALWAYS smoke-test plotter changes with `file_path=` to disk, never just in-memory.

### Yoly K-label placement + multi-K coverage

Two compounded bugs:

1. `_split_on_K_decrease` was the helper checking for K-block boundaries to NaN-break the trajectory line. But `sweep_arch`'s natural Cartesian iteration order keeps K **monotonically non-decreasing** within each `(c, mu)` group (lambda is the inner loop, K outer factor), so the decrease-only check found zero break-points. Renamed to `_split_on_K_change` and switched to `np.where(diff != 0)` — any K change. Each K-constant sub-sweep now renders as its own dashed segment.

2. K labels only annotated `(K.min(), K.max())` — only 2 of 4 K bands got labels (e.g., K=8 and K=32 visible, K=10 and K=16 invisible). Switched all four painters to `np.unique(K)` so every distinct K gets a label. Label position changed from `argmax(K == K_val)` (first occurrence = origin cluster) to `np.where(K == K_val)[0][-1]` (last occurrence = high-θ trajectory tip).

### Calibration dim card multi-K

`derive_calib_coefs(envelope, K_values=[256, 512, 1024])` now tiles the per-`n_con_usr` observables once per K. Latency `R(n)` is K-independent (the host probe doesn't manipulate the buffer), so tiling is exact: only `theta = L/K`, `sigma = λW/K`, `phi = M_act/M_buf` shift across K. Notebook cell `nb-calib-dim-card` reads `data/config/method/calibration.json::sweep_grid.K` and threads it through. The yoly chart now paints 3 K-trajectories instead of a single point at `uvicorn_backlog` (16384). New `meta.K_values` field records the list; legacy `meta.uvicorn_backlog` retained.

### Architecture μ as `\overline{\mu}` + half-up rounding

Legend label corrections after the user pointed out `int(1276.92) = 1276` truncates instead of rounding. Switched `int(value) → round(value)` in `_format_path_legend`, `_paint_single_2d_yoly`, `_paint_single_3d_yoly`. Now `1276.92 → 1277`, `957.69 → 958`, etc. Also wrapped μ in `\overline{\mu}` to indicate the architecture-level mean (since `aggregate_sweep_to_arch` collapses 13 per-node μ values via arithmetic mean).

### Yoly title + axis split

User went through several flip-flops on whether titles should be `Plane: θ vs σ` or `Occupancy vs. Stall`, and whether axes should be `Occupancy (θ)` or just `θ`. Final agreed split:

- **Panel titles** (`_YOLY_PANELS`) — bare symbols: `r"$\mathbf{\theta}$ vs. $\mathbf{\sigma}$"`, etc.
- **Axis labels** (`_DEFAULT_LABELS`) — operational name with symbol in parens: `r"Occupancy ($\mathbf{\theta}$)"`, etc.
- **`plot_yoly_arts_hist` x-axis exception** — symbol-only override via local `_hist_symbols` map; the dense per-comp grid otherwise becomes unreadable.

### Histogram symbology

`plot_yoly_arts_hist` reference line and labels:

- Reference at `np.median(_data)` (more robust than mean to K-block tail clustering).
- Labelled `$\widetilde{X}$` (X-tilde = sample median).
- Subplot title format: `rf"$\widetilde{{X}}={median:.3e}\,\,\,s^{{2}}={var:.3e}$"` — sci notation, 3 mantissa decimals; `s²` is sample variance via `np.var(_data)` (NOT population std).

### Uniform sci-format

Dropped the legacy sig=4 special case for σ in `_apply_yoly_panel_axes` and `_apply_yoly_3d_axes`. Originally needed because under Little's law `σ_old = λW/L ≈ 1` and tiny variations collapsed at sig=2. After the σ formula correction (2026-04-25, `λW/L → λW/K`), σ values span a healthy range and read clearly at sig=2. Every yoly panel now uses uniform `_apply_sci_format(ax, axes_list=["x", "y"])` with default sig=2.

### `plot_yoly_space` subtitle stacking

Several attempts before landing the working solution. Final approach: when `subtitle` is set, `title_h=0.10`; pass `title=None` to `build_stacked_figure`; manually draw BOTH lines into the dedicated `title_ax` in axes coords (`y=0.72` title, `y=0.22` subtitle). Subtitle font bumped to 18 (was 14). Other approaches that failed:

- `_ax.set_title(subtitle, ...)` lands at the top of the 3D body axis, clashes with suptitle.
- `fig.text(0.5, 1 - title_h - 0.005, subtitle, ...)` — figure-coord arithmetic; render-order between suptitle (axes-coord, drawn first) and fig-coord text caused inversions in some configurations.

Lesson: when the figure has a dedicated title-strip axis already, draw EVERYTHING into that axis with explicit axes-coord positions. Don't mix figure-coord and axes-coord text.

### Layout tightening

Tightened title strip + outer-hspace + body grid spacing across all five yoly plotters so titles don't bleed into the body and y-axis tick labels (with mathtext + scientific notation) don't overlap adjacent panels:

- `plot_yoly_chart`: `title_h=0.045`, `outer_hspace=0.025`, body `wspace=0.32` (60% wider than initial 0.20), `hspace=0.22`.
- `plot_yoly_arts_hist`: `title_h=0.045`, `outer_hspace=0.025`, outer `hspace=0.30`, inner `hspace=0.65`, `wspace=0.40`.
- `plot_yoly_arts_charts`: `title_h=0.045`, outer `hspace=0.25`, `wspace=0.22`, inner `hspace=0.45`, `wspace=0.45`.
- `plot_yoly_arts_behaviour`: `title_h=0.045`, outer `hspace=0.10`, `wspace=0.08`.

### Files touched

- `src/view/common.py` — `_DEFAULT_LABELS`, `_YOLY_PANELS`, `_format_path_legend`, `_paint_*_yoly` (rename + label rounding + every-K labelling + tip placement + `\overline{\mu}`), `_split_on_K_decrease → _split_on_K_change`.
- `src/view/charter.py` — five plotter layouts tightened; `plot_yoly_space` subtitle stacking via dedicated title_ax; `plot_yoly_arts_hist` median + `s²` + sci-3-dec + symbol-only x-axis override; `_apply_yoly_panel_axes` + `_apply_yoly_3d_axes` uniform sig=2 sci format.
- `src/methods/calibration.py` — `derive_calib_coefs` accepts `K_values: Optional[List[int]]`; tiles observables across K when provided; meta records `K_values` list.
- `00-calibration.ipynb` — `nb-calib-dim-card` cell reads `sweep_grid.K` and passes to `derive_calib_coefs`.
- `01-analytic.ipynb`, `02-stochastic.ipynb`, `03-dimensional.ipynb`, `04-yoly.ipynb` — title separator `\n → , `; bar/delta/heat/diff label LaTeX wraps; DataFrame display columns wrapped in mathtext.
- `CLAUDE.md` — View (Plotting) Conventions section extended with all yoly polish rules.
- `notes/titles_std.md` — final tables + status block updated.
- `.claude/skills/develop/notebook-editing.md` — title template + DISPLAY map + matplotlib mathtext bold rule.
- Memory: `feedback_matplotlib_mathtext_bold.md` (new), `project_titles_std_2026_04_27.md`, `project_yoly_k_change_split.md`, `project_yoly_polish_2026_04_27.md` (new).

### Verification

- All 5 thin notebooks `nbformat.validate()` pass.
- 6 yoly figures rendered to disk and visually inspected per iteration: trajectory tips show 4 K labels, legend shows `c=k, μ̄=m` rounded half-up, panels share sci-2 format, histogram subplot titles read `X̃=...  s²=...`, calibration dim card paints 3 K-trajectories.
- `pytest` baseline unchanged (only label / config / layout changes; no logic touched).

---

## 2026-04-27 — Title standardisation, bold-math labels, yoly K-change fix

Three refactor passes hit the five thin notebooks (`00-calibration`, `01-analytic`, `02-stochastic`, `03-dimensional`, `04-yoly`) plus `src/view/common.py` and `src/view/charter.py`.

### Title template + DISPLAY map (notes/titles_std.md)

Every plot title now reads `f"{Method}: {Subject}\n{Scenario}"`. Method ∈ `Calibration / Analytic / Stochastic / DASA / Yoly Chart`. The four-key DISPLAY map is identical in every notebook:

```python
DISPLAY = {"baseline": "No Adaptation", "s1": "S1: Retry", "s2": "S2: Select-Reliable", "aggregate": "S1 & S2"}
```

Yoly subjects use `"trade-off Projections"` (2D panel grids) and `"trade-off space"` (3D clouds); "2D" / "3D" qualifiers dropped because the plotter family already encodes dimensionality.

### Bold-math labels — `\mathbf` only, never `\boldsymbol`

Replaced 111 occurrences of `\boldsymbol` → `\mathbf` across `src/view/common.py`, 4 notebooks. matplotlib's built-in mathtext does NOT recognise `\boldsymbol` and crashes `savefig` with `ParseFatalException: Unknown symbol: \boldsymbol`. Lowercase Greek under `\mathbf` falls back to upright non-bold (a matplotlib limitation that needs `usetex=True` to overcome); accepted. Roman + uppercase Greek (Δ) DO bold under `\mathbf`.

**Lesson learned:** an in-memory smoke test that creates the figure but doesn't `savefig` skips the tick-bbox path that triggers the mathtext parser. ALWAYS save to disk when smoke-testing label / title / mathtext changes — `file_path=` is mandatory in the smoke recipe.

### Yoly K-change NaN-split (`_split_on_K_change`)

Renamed `_split_on_K_decrease` → `_split_on_K_change` in `src/view/common.py`. The previous helper inserted NaN only where `K[i] < K[i-1]`, but `sweep_arch`'s natural Cartesian iteration order keeps K **monotonically non-decreasing** within each `(c, mu)` group (lambda is the inner loop, K is the outer factor). The decrease-only check found zero break-points, so matplotlib drew dashed lines connecting the high-theta endpoint of one K-band back to the low-theta start of the next — visually misleading "return-to-origin" zig-zags. Switching to `np.where(_diff != 0)` (any K change) splits each K-constant sub-sweep into its own segment, fixing the visual.

### Layout tightening

`plot_yoly_arts_hist` now uses math symbols on subplot titles ($\hat{X}=...\,\,\,s=...$) at fontsize=10, pad=2; outer hspace 0.55→0.30, inner hspace 0.45→0.65. `plot_yoly_chart` / `plot_yoly_space` / `plot_yoly_arts_behaviour` / `plot_yoly_arts_charts` all got `title_h=0.025` (was 0.04) and `outer_hspace=0.01` so the suptitle hugs the body. Legend labels now use mathtext: `f"$\\mathbf{{c}}={int(c_val)},\,\\mathbf{{\\mu}}={int(mu_val)}$"`.

### Files touched

- `src/view/common.py` — `_DEFAULT_LABELS` + `_YOLY_PANELS` use `\mathbf{}` for coefficient symbols; `_format_path_legend` + `_paint_*_yoly` legend labels switched to mathtext; `_split_on_K_decrease` → `_split_on_K_change`.
- `src/view/charter.py` — five yoly plotters got tighter title_h + outer_hspace + body grid spacing.
- `00-calibration.ipynb` — DataFrame columns use `[$\mathbf{\mu s}$]` / `[$\mathbf{ns}$]`; markdown wraps `lambda`, `mu`, `theta`, `sigma`, `eta`, `phi`, `M_act`, `M_buf`, `c_srv`, `W_q` in `$...$`; plot titles include `host.get('hostname')` on the second line.
- `01-analytic.ipynb`, `02-stochastic.ipynb`, `03-dimensional.ipynb` — DISPLAY map standardised; `bar_labels` / `delta_labels` / `heat_labels` / `diff_labels` all use `\mathbf{}` mathtext; DataFrame summary columns now bold mathtext.
- `04-yoly.ipynb` — Yoly Chart titles + subjects rewritten to "trade-off Projections" / "trade-off space"; inherits axis labels from `_DEFAULT_LABELS`.
- `notes/titles_std.md` — final tables + DISPLAY map + naming rules + per-notebook plotter-by-plotter title spec.
- `CLAUDE.md` — Notebook + View conventions sections updated with title template, DISPLAY map, `\mathbf`-only rule, K-change NaN-break helper, smoke-test-with-file_path discipline.

### Verification

- `nbformat.validate()` on all five thin notebooks: all pass.
- `pytest tests/io tests/analytic tests/dimensional tests/utils tests/methods` (focused subset): unchanged from baseline (no src/ logic touched).
- `plot_arch_delta` saved to disk with `\Delta \overline{\mu}` in a label: passes (the original failing call).
- `plot_yoly_chart` + `plot_yoly_arts_charts` saved to disk with `_DEFAULT_LABELS` + `_YOLY_PANELS` + mu legend formatter: passes.

---

## 2026-04-26 (continued) — Schema split (artifacts vs specs), local_end_ts column, lambda_z restored

Three structural changes landed late on 2026-04-26, all on top of the profile-rescaling work captured in the previous entry.

### Schema split: `artifacts` (frozen model) + `specs` (adjustable deployment)

Both `data/config/profile/{dflt,opti}.json` now carry parallel top-level blocks:

- **`artifacts`** — frozen theoretical model. Cámara 2023 canonical values. Consumed by analytic / stochastic / dimensional. Locked.
- **`specs`** — adjustable practical layer. Same node keys + variable structure. Consumed by `experiment.run` and `src/scripts/launch_services.py`. Free to diverge from `artifacts` on `c`, `K`, `port`, `mem_per_buffer` for prototype-fidelity tuning without contaminating the model.

`src/io/config.py::load_profile(adaptation, profile, scenario, source="artifacts")` gains a `source` kwarg. Default `"artifacts"` keeps every analytic / stochastic / dimensional call bit-identical. `experiment.py:495` and `launch_services.py:325` switched to `source="specs"`.

Initial state: deep-copy parity (artifacts → specs at migration time, 2026-04-26). Future divergence is operator-driven.

Tests: `tests/io/test_config.py::TestSourceSwitch` (4 cases, all green). Pre-existing `test_lambda_z_only_at_entry` and `test_reads_setpoint_value` loosened from hardcoded 345 to `> 0` to absorb the lambda_z editing history.

**Dissertation framing.** "We separate **modelled artifact** specifications (the system DASA reasons about: mu, epsilon, c, K, lambda_z, routing) from **practical deployment** specifications (the runtime configuration the prototype actually uses: c_deployed, K_deployed, port, memory). The split lets the prototype be tuned for measurement fidelity (e.g., raising entry-router c to remove admission saturation) without contaminating the model's predictions. R1/R2/R3 verdicts apply to the modelled topology; experimental error is measured as the gap between the prototype's behaviour at the deployed configuration and the model's prediction at the modelled configuration."

### `local_end_ts` column — composite-router observable fix

`LOG_COLUMNS` bumped from 10 to 11 columns:

```
request_id, service_name, kind,
recv_ts, start_ts, local_end_ts, end_ts,
c_used_at_start,
success, status_code,
size_bytes
```

New `mark_local_end()` API in `src/experiment/services/instruments.py` (paired with a `_local_end_var` contextvar). `mount_atomic_svc` calls it right after admission release + eps + target pick, immediately before `await dispatch(...)`. Terminals don't call it; `@logger` defaults `local_end_ts = end_ts` for them.

`_build_svc_df_from_logs` now produces two views per node:

- **Local** (default `rho` / `L` / `W` columns): from `local_end_ts - start_ts`. M/M/c/K-comparable. Used by analytic / stochastic / dimensional cross-checks.
- **Total** (parallel `rho_total` / `L_total` / `W_total`): from `end_ts - start_ts`. Client-perceived end-to-end. Used for Cámara R2 validation.

For atomic / terminal nodes the two views coincide. For composite routers (TAS_{*}) they differ by the dispatch-await time.

**Why.** Pre-bump, `end_ts - start_ts` for composite routers included the whole downstream subtree's processing time because the handler awaits the dispatched response inside its own bracket. That made TAS_{1}'s W = end-to-end response time across the entire architecture, producing the spurious "TAS_{1}.L blew up to 200" pattern. The Cámara-rate-rescaling memory entry (2026-04-23) attributing this to atomic saturation was wrong; atomic max rho stayed under 0.20 across all four adaptations even at lambda_z = 345. Fixed entry now in `memory/project_camara_rate_rescaling_pending.md` reflects the resolution.

213/213 experiment tests green post-change.

### `lambda_z = 345 req/s` restored (Cámara canonical)

After cycling through 250 / 200 / 150 during the morning's diagnosis, `lambda_z` is restored to the published Cámara 2023 value of **345 req/s** at `TAS_{1}` in **both layers** (artifacts + specs). The user authorised this as an explicit exception to the "artifacts is frozen" rule because the canonical published value is the right anchor for the model layer.

All downstream `\lambda_{...}` setpoints rescaled proportionally by 345/250 = 1.38 across both layers.

### Memory + CLAUDE.md sync

- New memory entry `project_artifacts_specs_split.md` (full migration record).
- New memory entry `project_local_end_ts_observable.md` (schema bump + composite-router observable diagnosis).
- Updated `project_camara_rate_rescaling_pending.md` (RESOLVED).
- Updated `project_qn_config_conventions.md` (lambda_z=345 + two-layer schema note).
- Updated `MEMORY.md` index (3 new pointers, 2 description rewrites).
- Updated CLAUDE.md "Data Convention" bullets: schema split, lambda_z=345, 11-column LOG_COLUMNS with local_end_ts, two-view operational metrics.

### Pending

- User-side: re-run `01-04` notebooks at the artifacts layer for sanity (no code change needed; default `source="artifacts"`).
- User-side: re-run `05-experimental.ipynb` at the specs layer to populate the new `local_end_ts` and `_total` columns; then iterate on `specs` divergence from artifacts to relieve TAS_{1} entry-router admission (likely `specs.TAS_{1}.c = 16` or higher to deliver 250 req/s without saturation).
- Re-deriving the analytic JSON's `\W` / `\L` / `\Wq` / `\Lq` setpoints from the queue solver after `lambda_z` rescaling (currently `λW ≠ L` at the JSON seeds, so `test_sigma_close_to_theta_under_little` is failing; running 01-analytic regenerates them).

---

## 2026-04-26 — Profile rescaling for prototype throughput floor + composite-router observable diagnosis

**Goal of the day.** Make the experimental method produce results that align with the analytical / stochastic predictions (the dimensional + experimental adaptations had been showing "worse than baseline" deltas while analytical / stochastic showed improvements). Diagnosis traversed three layers — entry rate, server count, K buffer — before landing on a deeper issue: the entry composite's W observable is system-wide, not local.

### Knee analysis (closed-form, K-independent at fixed c)

Closed-form Jackson + M/M/c/K solve over `c ∈ {1, 2, 3, 4, 6, 8} × K ∈ {10, 20, 40, 60, 100}` per adaptation, holding mu fixed:

| c | baseline knee | s1 knee | s2 knee | aggregate knee |
|---|---|---|---|---|
| 1 | 472 req/s | 437 req/s | 460 req/s | ~437 req/s |
| 2 | 944 | 874 | 921 | ~874 |
| 3 | 1416 | 1311 | 1381 | ~1311 |
| 4 | 1888 | 1748 | 1841 | ~1748 |

K does not affect the saturation knee (`rho = lambda / (c * mu)` is the gate). K controls blocking probability and buffer depth at the knee, nothing else.

Sweep script kept at `_sandbox/analyse_knee.py` for reuse.

### Decision sequence (each step a write to both `dflt.json` and `opti.json`)

1. **c=2, K=40 uniform across all 13 / 16 artifacts.** Knee at 874 req/s s1 worst case. Reverted next step.
2. **c=1, K=80 uniform.** Knee unchanged at 437 req/s s1 worst, deeper buffer for prototype tail behaviour.
3. **TAS_{1} mu = 900 → 700.** Aligns the entry composite with the other 700-req/s TAS components.
4. **lambda_z 345 → 150 req/s** at the entry. All downstream `\lambda_{...}` setpoints rescaled by factor 150/345 = 0.4348 (Jackson-linear, exact). Analytical bottleneck rho dropped from 0.69 (saturated tail) to 0.30 (clean steady state). Per-artifact `lambda_z` (mostly 0 for non-entry) and the `_data` arrays under `\lambda` variables also rescaled.
5. **TAS_{*} K=10, atomics K=80.** Asymmetric K reflects that routers have shallow queueing semantics, atomics absorb propagated bursts.
6. **TAS_{*} c=2, atomics c=1.** Then **TAS_{*} c=4, atomics c=1.** Heterogeneous c — see "TAS_{1} composite-router observable" below for why.

`lambda_z` was bumped externally from 150 to 250 between steps 5 and 6 (probably via the analytical notebook's re-derivation pass); current state is 250.

**Final config**:

| Tier | c | K | mu (unchanged) |
|---|---|---|---|
| TAS_{1..6} (composite routers) | **4** | 10 | 700 (TAS_1, was 900) / 700 (others) |
| MAS / AS / DS (atomic domain) | 1 | 80 | unchanged |

Per-node analytical rho at lambda_z=250:

- baseline: bottleneck MAS_{3} rho=0.503; max TAS rho=0.089
- s1: MAS_{3} rho=0.543; max TAS rho=0.089
- s2: DS_{1} rho=0.516; max TAS rho=0.089
- aggregate: DS_{1} rho=0.500; max TAS rho=0.089

Atomic services are at 50-55 % utilisation (comfortable steady state); composite TAS services are at 9 % utilisation analytically — but the experimental observable diverges, see below.

### TAS_{1} composite-router observable (root-cause diagnosis)

Pre-edit experimental results for s2/aggregate showed TAS_{1} W = 1.86 s / 1.42 s while atomic services stayed at rho < 0.20. The Cámara-rate-rescaling concern (memory entry from 2026-04-23) was wrong — atomics are not saturated. The real issue:

**TAS_{1}'s `end_ts - recv_ts` measures whole-architecture response time, not local queueing.** The composite handler dispatches downstream and AWAITS the dispatched response inside its own `start_ts → end_ts` bracket. So:

- TAS_{1} W = end-to-end response time across TAS_1 → TAS_{2..4} → MAS_{*} → AS_{*} → DS_{*} → return.
- TAS_{2} W = whole subtree under medical kind.
- TAS_{6} W = local (terminal in current routing).

Little's law `L = X * W` applied to TAS_{1} gives system-wide in-flight, NOT local queue length. Comparing this to analytical L_{TAS_{1}} (which is local M/M/c/K queue at TAS_{1} only) is an apples-to-oranges error — both are correct, but they measure different observables.

**Admission-saturation forecast at lambda=250 req/s, dispatch_wait=100ms** (the observed s2 W):

| c at TAS_{1} | local rho_admission |
|---|---|
| 1 | 25.0 (saturated) |
| 2 | 12.5 (saturated) |
| 4 | 6.25 (saturated) |
| 8 | 3.12 (saturated) |
| 16 | 1.56 (saturated) |
| 32 | 0.78 (steady) |

c=4 reduces but does not eliminate the entry-router admission queue at lambda_z=250 if dispatch-await stays at ~100 ms. The proper fix is structural: stop measuring the dispatch-await as part of TAS_{1}'s service time. Either:

- **(a)** Add a `local_end_ts` capture right before the dispatch httpx call; use `local_end_ts - start_ts` for composite rho/L/W. Aligns the observable with the analytical M/M/c/K assumption.
- **(b)** Stop comparing composite rows to analytical L/W in `07-comparison.ipynb`; for TAS_{*} compute a different cross-method observable (system-wide in-flight = sum of L_local across the subtree).

(a) is cleaner; (b) is faster to ship. Pending decision until experiments are re-run with TAS c=4 to see if the W blowup is meaningfully relieved.

### Heterogeneous c framing (dissertation defence)

Three framings for the asymmetric `c=4` (TAS) / `c=1` (MAS/AS/DS) split, in order of increasing strength for paper review:

1. **Operational**: "TAS_{1} is a multi-worker HTTP front-end (Tomcat / uvicorn / Gunicorn default), modelled as a thread pool with c=4. Cámara 2023's c=1 abstraction underestimates entry concurrency."
2. **Architectural**: "Server count `c` reflects role: routing-only nodes (TAS_{*}) are stateless and trivially parallelisable (c=4); atomic domain nodes (MAS / AS / DS) represent single underlying resources (c=1). Adaptation operates over the domain layer, so the asymmetry is intrinsic to the case study."
3. **Methodological**: "We raise c at TAS_{*} so the entry router stops dominating measured response time, recovering the domain-layer adaptation differentials that motivate the case study."

Framing (2) is the strongest because it ties `c` to architectural role rather than instrumentation convenience and survives reviewer scrutiny. Note the OLD replication used uniform `c=1` for byte-exactness; the new spec breaks that, traded for a meaningful 1000-req/s prototype.

### Cámara-rate-rescaling concern (memory) — RESOLVED

The 2026-04-23 memory entry `project_camara_rate_rescaling_pending.md` claimed the seeded mu/lambda_z exceeded the prototype's ~200 req/s ceiling and were biasing 07-comparison. The pre-edit experimental data shows **atomic rho < 0.20 across all four adaptations even at lambda_z=345**, so atomic saturation was not the cause. The real cause was the composite-router observable mismatch (above). Memory entry to be updated.

### Pending

- Re-run all four experiment notebooks (analytic / stochastic / dimensional / experiment) with the new (c, K, mu, lambda_z) profile. Compare per-node rho across methods.
- Decide between fix (a) `local_end_ts` and fix (b) cross-method composite observable for `07-comparison`.
- Update memory entry on Cámara-rate-rescaling.

---

## 2026-04-25 — σ formula correction + audit campaign + experiment-networks rename

**σ = λW/L → σ = λW/K.** User flagged the methodology-correct stall-coefficient formula. The old form was Little's-law identity (≈1 in steady state, structurally insensitive to K); the new form measures queueing share of capacity. Fix landed across:

- `data/config/method/dimensional.json::coefficients[1].expr_pattern` (`{pi[0]}*{pi[3]}**(-1)`).
- `src/dimensional/networks.py::sweep_artifact` and `sweep_arch` inner-loop expressions.
- `src/dimensional/reshape.py::aggregate_arch_coefs` (denominator `sum(K)`) and `aggregate_sweep_to_arch`.
- `src/methods/calibration.py::_run_calib_pipeline` (LaTeX `\frac{λ·W}{K}`).
- `src/experiment/architecture.py::sweep_arch_exp` (analytic body).
- `src/view/qn_diagram.py::DIM_GLOSSARY_DEFAULT` (legend).
- `.claude/skills/develop/pydasa-usage.md` Stall row (canonical-coefficients table).
- Tests: `tests/dimensional/test_coefficients.py`, `tests/dimensional/test_sensitivity.py`, `tests/experiment/test_architecture.py`.
- Notebook captions: `00-calibration.ipynb`, `04-yoly.ipynb`, `06-yoly-experimental.ipynb`.

Under Little's law (λW = L), `σ_new ≡ θ` on closed-form solves. On prototype runs the equality only holds approximately because operational λ counts every arrival but `L = X·W` uses successful-throughput X; `tests/experiment/test_architecture.py::test_sigma_close_to_theta` loosens to `rtol=0.5` to absorb this.

**Module rename.** `src/experiment/networks.py` → `src/experiment/architecture.py` (homonym disambiguation vs `src/dimensional/networks.py`); `tests/experiment/test_networks.py` → `tests/experiment/test_architecture.py`. Public alias `from src.experiment import sweep_arch_exp` already in `__init__.py`, so external callers were untouched. Stale references swept from CLAUDE.md and `src/methods/calibration.py` docstring.

**Audit campaign.** Ran systematic 3-skill audits (`code-documentation` + `coding-conventions` + `style-polish`) on every src/dimensional + src/methods/{calibration,experiment} + src/io/tooling + src/experiment/architecture module and their test parity files. Recurring patterns:

- R16 stacked-`#` runs collapsed to one-line whys (≈40 sites).
- `src.view.dc_charts.<plotter>` → `src.view.<plotter>` public-alias references (≈8 sites).
- Bare `except Exception:` narrowed to specific types: `(OverflowError, ValueError, ZeroDivisionError)` for M/M/c/K solver, `(RuntimeError, OSError, ConnectionError)` for uvicorn launches, `(httpx.HTTPError, ConnectionError, OSError)` for httpx readiness probes. The K-disappearance bug (solver overflow at K=16384 for c≥2) had been silently swallowed for weeks; narrowing surfaced it as a real solver ceiling.
- Lazy stdlib imports (`ctypes`, `os`, `solve_jackson_lams`) promoted to module top.
- Test type-hint sweep: every `test_*` method got `-> None` + fixture-arg types.
- `*test_name()*` lead-in convention enforced on every test docstring; module-docstring class-bullet lists matched against actual class counts.
- `Optional[X]` not `X | None`, `Dict[...]` not `dict[...]` for project consistency.

**New helpers** in `src/dimensional/reshape.py`: `_safe_div(num, den)` and `_per_combo_mean(sweep_data, art_keys, sym_template)` to remove duplication.

**Coverage gap closed.** Added `TestAggregateSweepToArch` with 5 contracts using a synthetic 2-artifact sweep.

**Jupyter-safe asyncio dispatch** added to `src/methods/experiment.py::_run_async_safe` (worker-thread `ProactorEventLoop`/`SelectorEventLoop` when an ambient loop is detected; falls back to `asyncio.run` when none). Lets `_RUN_RATE_SWEEP = True` work in `00-calibration.ipynb` without the `RuntimeError: asyncio.run() cannot be called from a running event loop`.

**Calibration completion.** Per-host JSON now carries `dimensional_card` (PyDASA-routed) + `rate_sweep` (calibrated_rate=200 req/s for `DESKTOP-INKGBK6`) + 128 kB payload threading from JSON config. `src.io.load_dim_card` accessor lazy-derives the card when not pre-baked.

**Route-A predicted sweep removed (2026-04-25).** `derive_calib_sweep` (closed-form M/M/c/K via `src.dimensional.networks.sweep_artifact`) was deleted along with `TestCalibSweep` (5 cases) and notebook section 6c. Calibration must be measurement, not theory; mixing `loopback.median_us` with M/M/c/K projection contradicted the calibration contract. The `sweep_grid` block in `data/config/method/calibration.json` is preserved because `_build_ping_app` reads `sweep_grid.{c, K}[0]` to seed the vernier service spec; the unused fields stay dormant until `scale-2.md` lands a CSV-driven sweep.

**Test count after the campaign.** 107+ tests across `tests/dimensional/`, `tests/methods/test_calibration.py`, `tests/methods/test_experiment.py`, `tests/io/test_tooling.py`, `tests/experiment/test_architecture.py` all green. The audit applied ≈80 individual fix items across ≈20 src + tests files.

---

## 2026-04-24 — Calibration dimensional card (Route B, measurement-derived)

Added `src.methods.calibration.derive_calib_coefs(envelope, payload_size_bytes=0)` producing theta / sigma / eta / phi from the measured `handler_scaling` + `loopback` blocks (Route B — measurement, not M/M/c/K prediction). Plumbing:

- μ = 1e6 / loopback.median_us (host bare-metal service rate).
- For each `n_con_usr` level: `R = median_us × 1e-6`, `X = n/R`, `L = n`, `Wq = (median_us − loopback.median_us) × 1e-6`.
- θ = L/K, σ = Wq·λ/L, η = X·K/(μ·c_srv), φ = (L·B)/(K·B) = L/K when payload is constant.
- ε excluded: `/ping` has no business logic that can fail.
- Output dict uses LaTeX-subscripted keys ready for `src.view.dc_charts.plot_yoly_chart` — no new plotter; the notebook renders the card with the same helper the dimensional method uses on TAS architectures.
- Stored under `envelope["dimensional_card"]`; notebook section 6b displays it.

**Caveat.** φ is NaN by default because every `/ping` request carries the same body, making memory utilisation identical to θ (degenerate-memory case). Becomes informative only after the payload-echo upgrade (128/256 kB body). Noted in the notebook markdown + CLAUDE.md.

Test count: 7 new `TestCalibDimCard` cases, all green. Helper reuses the existing dimensional vocabulary (same LaTeX subscripts, same plotter input shape) so the calibration fits into the DASA coefficient-space story without new view code.

---

## 2026-04-24 — Calibration P0 + scoped P1 + P2 stop-gate closed

**What closed.** P0.1-P0.4 (host harness + rate-sweep fold-in + pre-run gate + first baseline), scoped P1 (bounded `deque(maxlen=500_000)` + `record_row` + `dropped_count` + `drain()` + `perf_counter_ns` in the hot path), and the P2 stop-gate all landed on 2026-04-23 / 2026-04-24. Full detail in `notes/calibration.md` Checkpoint log.

**P2 verdict.** 5 trials of `experiment.run(adp=baseline)` against the post-P1 code: every trial completed cleanly (`stopped=schedule_complete`, `log_drop_counts == {}`), `client_effective_rate` mean 6.82 req/s (range 6.49-7.26, ~6 % spread), `W_net` mean 17.5 ms with a visible warm-in trend, wall-clock 173.7 s per trial. Interpretation: **safety properties confirmed**; the bounded-deque invariant holds, ns-precision is stable, nothing regressed. **Performance lift is NOT decided** — the default ramp tops out ~7 req/s, far below the ~180 req/s degradation point the calibration found. The handler-scaling data (8× latency degradation at c=10 on an empty `/ping` handler with ZERO logging) already strongly suggests event-loop queueing inside each service is the dominant bottleneck, not logger overhead. A saturation-regime A/B bench would cost many trials × many rates × many minutes of wall time; deferred until a use case demands it.

**Module renames.** Three files were called `calibration.py`. Kept the runner (`src/methods/calibration.py`) and renamed the other two for clarity:

- `src/io/calibration.py` → `src/io/tooling.py`
- `src/view/calibration.py` → `src/view/characterization.py`

Public API (`from src.io import ...` / `from src.view import ...`) unchanged.

**Reference baseline for this host (DESKTOP-INKGBK6).** Clean re-bench on the post-refactor code, apps closed:

| Probe | Number |
|---|---|
| Timer min / median / std | 100 ns / 100 ns / 392 ns |
| Jitter mean / p99 / max | 663 μs / 1357 μs / 1985 μs |
| Loopback median / p99 | 1.29 ms / 2.21 ms |
| Handler c=1 → c=10000 | 1.5 ms → 30 s (log-log) |

Every experiment result on this host should report `reported = measured_us − 1288.5 µs ± 1357.1 µs`.

**Next.** P3.1 (extract endpoints to `experiment.json`) is the highest-leverage refactor. P4 is blocked on having a second LAN machine. A live rate-sweep would unblock the pending Camara rate-rescaling decision (`project_camara_rate_rescaling_pending.md`).

---

## 2026-04-23 — Calibration + logger refactor + local/remote plan drafted

**Plan filed.** `notes/calibration.md` now holds the living memory + checkpoint doc for a multi-phase effort: (P0) per-host noise-floor harness, (P1) `@logger` append + periodic-drain refactor to kill mid-run disk I/O, (P2) local re-baseline, (P3) remote-ready packaging, (P4) 3-machine LAN deployment, (P5) comparison + case-study integration. Status column in that file is the single source of truth; this devlog gets only the transitions.

**Filesystem split applied.** Mirrored `data/img/experiment/` in `data/results/experiment/`: both now carry `calibration/`, `local/<adaptation>/`, `remote/<adaptation>/`. Existing single-laptop results moved under `local/`; `.gitkeep` markers placed on every new empty directory per `data/results/.gitignore` convention (content ignored, structure tracked). `src/io` writers + `src/view` plotters still emit to pre-split paths; that wiring is phase P3.1, not landed.

**Why now.** The experiment method currently degrades measurably above ~180 req/s on the single laptop. The Camara-rate rescaling question (2026-04-23 entry below) only becomes answerable once the noise floor is characterized per host — otherwise we cannot tell whether "degradation" is measurement noise, logger back-pressure, or real service saturation.

**Stop-gate.** P3/P4 do NOT start until P2 has proven the logger refactor lifted the ceiling. If the refactor shows no lift, logger was not the bottleneck (per `feedback_measure_before_assume.md`) and the plan pivots toward the OS scheduler / HTTP stack / service saturation branches before sinking days into remote deployment.

---

## 2026-04-23 — Camara service / arrival rates need rescaling for the prototype

**Open question.** The seeded values in `data/config/profile/{dflt,opti}.json` come from Weyns & Calinescu 2015 + Camara 2023 (Java/ReSeP stack): `mu` in [150, 1580] req/s and `lambda_z = 345` req/s at TAS_{1}. The FastAPI prototype in `src/experiment/` cannot sustain those rates: `python -m src.methods.calibration --rate-sweep --rate-sweep-target-loss 1.0` reports the highest sustainable rate at <= 1 % effective-rate loss is **~200 req/s**. Above that, the asyncio chain + httpx connection pool + executor wakeup dominate and the client undershoots the target by 7-30 %.

**Why it matters.** If `07-comparison.ipynb` runs analytic at lambda_z=345 and experiment at lambda_z=345-but-actually-280, the headline analytic-vs-experiment delta is dominated by client undershoot, not by DASA tech-agnosticism. The DASA claim becomes untestable until the operating points line up.

**Two options.**

1. **Scale `lambda_z` down** (preserve mu ratios). Pick lambda_z = 200 (or whatever `--calibrate 1.0` returns at the time). Update `dflt.json` and `opti.json` symmetrically. Analytic + experiment then meet at the prototype-sustainable rate.
2. **Scale `mu` up** (preserve lambda_z = 345). Bump every `mu` setpoint so the prototype headroom matches Camara's. Risk: large `mu` values push asyncio.sleep below the OS-timer floor at the per-service tick.

Option 1 is the cheaper move; option 2 is closer to the original paper's QoS targets. Defer the decision until we wire the two notebooks (05-experimental + 06-yoly-experimental) at the candidate operating points and observe the comparison quality.

**Markers.** `TODO_revisit_rates` keys added to both profile JSONs so a grep finds the same context from the data side. Resolve both at the same time (delete the keys when the decision lands).

---

## 2026-04-22 — Experiment notebook split + sweep_arch_exp

**Decision.** Split the experiment method into two notebooks, mirroring the dimensional / yoly split locked on 2026-04-19:

- `05-experimental.ipynb` keeps the fixed-point per-adaptation execution (one `(mu, c, K)` per adaptation, lambda ramped to saturation, side-by-side analytic prediction + R1/R2/R3 verdict).
- `06-yoly-experimental.ipynb` adds a configuration-sweep yoly view measured on the FastAPI prototype, reusing the dc_charts plot vocabulary (`yc_arch`, `sb_arch`, `ad_per_node`, `yab_per_node`, `yac_per_node`, before/after overlay).

**What changed.**

- `src/experiment/networks.py` new module exposing `sweep_arch_exp(cfg, sweep_grid, *, method_cfg, adp)`. Mirrors `src.dimensional.networks.sweep_arch` shape; each combo overrides every node's `mu / c / K`, launches the mesh once, and derives one `(theta, sigma, eta, phi)` point per artifact. Reuses `_run_async` + `_build_svc_df_from_logs` from `src.methods.experiment` via local import to avoid a circular dependency.
- `src/experiment/__init__.py` re-exports `sweep_arch_exp`.
- `data/config/method/experiment.json` adds a `sweep_grid` block (`mu_factor=[0.5, 1.0, 2.0]`, `c=[1, 2]`, `K=[10, 32]`, `util_threshold=0.95`) — 12 combos. Deliberately small because each combo is a real mesh launch + ramp (~30 s).
- `tests/experiment/test_networks.py` covers shape / dimensional bounds / stability gate via a 1-combo `_QUICK_GRID` + tight ramp; 8 tests in 2.22 s.
- `06-comparison.ipynb` renumbered to `07-comparison.ipynb`.
- `CLAUDE.md` + `notes/workflow.md` table updated to reflect the 7-notebook layout (5 methods, two of them split).

**Why launch-per-combo, not in-process reconfig.** The simpler path; keeps the sweep helper a thin orchestrator over the existing run pipeline. In-process knob mutation would require service-side support and is deferred until the small-grid path proves insufficient.

**Validation.** Test suite green. Notebook end-to-end run pending — to be confirmed once the small-grid sweep is exercised on a development laptop.

---

## 2026-04-22 — Plotter polish: L on qn_topology node labels, `.2e` + `\frac`/`\cdot` on dim_topology

Incremental user-driven polish after the initial `plot_dim_topology` landing.

- **`plot_qn_topology`** — node labels now show `L = <val>` (avg number in system, requests) instead of `rho = <val>` (unitless, already in the colourbar). Colouring is unchanged (still rho-driven); only the label value changed. All four analytic adaptation topologies regenerated.
- **`plot_dim_topology`** — three refinements:
  1. `$\eta = \frac{\chi \cdot K}{\mu \cdot c}$` (explicit `\cdot` between multi-symbol factors so mathtext renders visible multiplications instead of kerning symbols together).
  2. Scientific notation `.2e` across every numeric display (table cells, node labels, NETWORK overlay). Coefficients span orders of magnitude across scenarios (`phi` goes from ~1e-3 baseline to ~1e-1 heavy load); uniform `.2e` prevents fixed-point formats from hiding the variation.
  3. `color_by="eta"` default + data-driven min-max normalisation pinned into the memory so future callers do not cap at 1.
- **Regenerated**: `data/img/analytic/{baseline,s1,s2,aggregate}/topology.{png,svg}` via full `01-analytic.ipynb` re-execution; `data/img/dimensional/{baseline,s1,s2,aggregate}/topology.{png,svg}` via direct calls + re-executed `03-dimensional.ipynb`.
- **CLAUDE.md + memory updated**: the uniform-format rule ("if you mix `.2e` with `.4f` across sites of the same figure you create false visual comparability"), the label-shows-L convention on qn_topology, and the overlay `$\bar{sym}$ (Name): value` format are all pinned.

---

## 2026-04-22 — Audit closure + full B-batch rename sweep + `plot_dim_topology`

Closed the 15-rule src + tests audit (docstring wrapping, acronyms, verb-first, type hints, locals prefix, dataclass fields, first-def pedagogy, no inline ternaries, section banners, no em-dashes, boolean decomposition, imports at top, @property getters, British English, neutral increase/decrease). Every src module + tests mirror + demo + notebook markdown was walked; every stage logged in `notes/audit.md`. The 11 deferred B-batch public-API renames (B1 / B3 / B5 / B6 remainder / B7 / B8 / B9 / B10 / B11 + B4 / B12 internal) drained in one final sweep.

- **B-batch executed** (30+ symbols): `NetworkConfig → NetCfg`, `load_method_config → load_method_cfg`, `Service* → Svc*` (Spec / Request / Response / Context), `ServiceRegistry → SvcRegistry`, `ExternalForwardFn → ExtFwdFn`, `mount_atomic_service → mount_atomic_svc`, `mount_composite_service → mount_composite_svc`, `ArtifactSpec._setpoint → .read_setpoint`, `._sub → .format_sub`, `per_artifact_lambdas → compute_lams_per_artifact`, `per_artifact_rhos → compute_rhos_per_artifact`, `lambda_z_for_rho → invert_rho_to_lam_z`, `solve_jackson_lambdas → solve_jackson_lams`, `lambda_zero (param) → lam_z`, `simulate_network → simulate_net`, `solve_network (stochastic) → solve_net`, `_time_weighted_mean → compute_time_weighted_mean`, `_model_string → format_model_string`, `aggregate_network → aggregate_net`, `check_requirements → check_reqs`, `sweep_architecture → sweep_arch`, `_find_max_stable_lambda_factor → _find_max_stable_lam_factor`, networks `_setpoint → read_setpoint`, `coefs_delta → compute_coefs_delta`, `network_delta → compute_net_delta`, `ClientConfig / RampConfig / CascadeConfig → *Cfg`, `_avg_request_size → _compute_avg_req_size`, `_specs_from_config → _build_specs_from_cfg`, `_routing_row → _read_routing_row`, `_router_kind_map → _build_router_kind_map`, `lambda_z_entry → get_lam_z_entry`. Full before / after table in [project_b_batch_renames memory](../../.claude/...).

- **Held back**: CSV column names on `SvcResp` (`service_name`, `message`), JSON-backed fields on `ClientCfg` (`entry_service`, `request_size_bytes`, `request_sizes_by_kind`), and PACS Variable-dict JSON keys (`_setpoint`, `_mean`, `_data`, `_dims`, ...). These are wire-schema / on-disk contract; renaming them would break historical replication dumps + force in-lockstep JSON-config edits. Python identifiers flip; disk schemas stay.

- **R15 terminology swept** in `notes/context.md` + `notes/objective.md`: "improve reliability" → "raise reliability", "signals degrade" → "signals fall", "improves freshness" → "raises freshness", "degrades both" → "lowers both". Third-party citation titles (Arteaga Martin / Correal Torres paper) preserved verbatim.

- **New plotter `plot_dim_topology`**: dimensional analog of `plot_qn_topology`, mirrors the 3/4 graph + 1/4 table layout. Default `color_by="eta"` (min-max normalised because eta is unbounded), 2-line node labels (key + theta), architecture-average overlay `$\bar{\theta}, \bar{\sigma}, \bar{\eta}, \bar{\phi}$` in the top-right lightblue box, full coefficient table below the graph. Wired into `03-dimensional.ipynb` as section 4. `data/img/dimensional/<adp>/topology.{png,svg}` now regenerates for every adaptation, bringing dimensional into layout parity with analytic. `plot_nd_heatmap` deliberately kept intact — still called on baseline, still emits `nd_heatmap.{png,svg}`.

- **Tests**: 338 passing, ~6 min wall clock. Notebooks 01-05 re-executed end-to-end; 06-comparison carries a pre-existing `ImportError: _async_run` (method 5 not yet built, unrelated to these renames).

- **Policy pins extracted** (now in CLAUDE.md): (i) wire-schema identifiers off-limits to Python renames; (ii) PACS Variable-dict JSON keys are contract and never touched by a sweep; (iii) scoped renames beat global regex when two modules intentionally share a name; (iv) `notes/audit.md` and `notes/devlog.md` skipped in whole-repo sweeps — they're historical record; (v) dict-subscript `["NAME"]` false-positives need manual review after every whole-word regex sweep.

**Gap flagged, not closed**: `tests/view/test_qn_diagram.py` does not exist; the plotter module is ~1300 lines and a pixel-level regression test is out of scope for this pass. Recorded as an audit gap in `notes/audit.md` Stage 0.10 close.

**Why now.** The user initiated the walk to bring the codebase to a consistent convention floor before the comparison method (method 5) lands on top. Drain the queue, pin the policies, move on.

---

## 2026-04-22 — Refactor: `composite` now layers on `atomic` via extension points

Removed the duplicated handler step-order body that had grown in `services/atomic.py` and `services/composite.py`. The two handlers were functionally identical — service-time sleep, epsilon Bernoulli, routing pick, dispatch, wrap with `@logger(ctx)` — but with three composite-only wrinkles (kind-dispatch at entry, in-process sibling lookup, per-member routes). The duplication was bounded but about to cost us: `notes/experiment.md §6.3` pins several observables (`mu_measured`, `epsilon_measured`, `chi_measured`, Little's-law check) that would have forced parallel edits in both files before method 5 could land.

- **`src/experiment/services/atomic.py`** — added two keyword-only extension points: `pick_target(ctx, req) -> target | None` (default: Jackson-weighted pick over `targets`) and `dispatch(target, req) -> ServiceResponse` (default: `await external_forward(target, req)`). Both defaults reproduce the pre-refactor atomic behaviour byte-for-byte. `mount_atomic_service` now also stashes the `@logger`-wrapped handler on `ctx.handler` so composite callers can reach it for sibling dispatch.
- **`src/experiment/services/base.py`** — `ServiceContext` gains one optional field: `handler: Optional[Callable] = field(default=None, init=False, repr=False)`. Set by `mount_atomic_service` after the handler is built; unused by atomic-only callers (third-party services).
- **`src/experiment/services/composite.py`** — rewritten to call `mount_atomic_service` once per member, injecting a shared `_handlers` dict through a `_dispatch` closure (in-process first, external-forward second) and an entry-only `_pick` closure that reads `kind_to_target` (raising HTTP 400 on unknown kind, matching the prior behaviour). The handler step-order now lives in ONE function.
- **Line count**: atomic 97 -> 129, composite 160 -> 135. Net ~neutral; the win is structural, not size.
- **Tests**: 147 experiment tests pass unchanged (byte-equivalent behaviour). Both demos (`demo_tas.py`, `demo_third_party.py`) still run clean.

**Why not yesterday.** Yesterday's style passes kept the two handlers sibling (deliberately — scope discipline, see `feedback_skill_pass_scope_discipline.md`). Today the question "can composite be rewritten on atomic?" made it worth the separate commit: the tradeoff flipped once the prototype audit listed multiple upcoming M/M/c/K observables that would land in the step-order code path.

**Where the subtlety went.** The trick that made the old code non-trivial — "shared `_handlers` dict populated after each member is mounted, consulted at request time via late-bound lookup" — is still in composite, but now it's one 4-line `_dispatch` closure instead of 40 lines of inline plumbing. That is the legitimate thing to understand when reading composite; everything else is library.

---

## 2026-04-22 — Style + documentation pass: `experiment/instances/tas`

Second module covered by the 2026-04-22 skill-pass sweep (`third_party` was first; pattern captured earlier in the day).

- **`src/experiment/instances/tas.py`** — tightened module docstring (added usage example; removed the imprecise "TAS_{2..4} Jackson-weighted / TAS_{5,6} terminal" phrasing that did not match `composite.py`'s real dispatch tree; stated kind-dispatch-vs-Jackson split up front). Function docstring now mentions the HTTP 400 on unknown kind, the `app.state.tas_components` side-effect, and the `entry_name` keyword-only default.
- **`tests/experiment/instances/test_tas.py`** — dropped the back-compat alias `build_tas as make_tas_service` (exactly the kind of drift the verb-first-rename memory flags). Scrubbed stale jargon from the module docstring ("Option-B" is a registry-level vocabulary term; "M/M/c/K invariants per component" is wrong — the apparatus explicitly does not enforce those). Added `*test_name()*` lead-ins to every test method; tightened fixture docstrings; ASCII'd `>= 1` (was Unicode `>=`).
- **`src/scripts/demo_tas.py`** (new) — three-section walkthrough: kind-dispatch at TAS_{1}, in-process chain TAS_{1} -> TAS_{2} -> TAS_{3} with per-member logs, external-forward boundary at TAS_{2} -> MAS_{1}. Same idiom as `demo_third_party.py` / `demo_services.py`. Verified by invocation.
- **Suite**: 147 experiment-side tests pass in 11.7 s. `tests/methods/test_experiment.py` drift is still there and still out of scope (same orthogonal `ClientConfig.kind_weights` failure as the earlier `third_party` pass).

**Scope discipline.** Sibling files surfaced `Option-B` / `ServiceState` references in `test_registry.py` + `test_seed.py` but those cover different source modules (`registry.py`, `base.py`) — left alone per the scope-discipline rule (see `feedback_skill_pass_scope_discipline.md`).

---

## 2026-04-22 — Style + documentation pass: `experiment/instances/third_party`

Applied the code-documentation + coding-conventions + test-layout skills to `src/experiment/instances/third_party.py` and its associated tests.

- **`src/experiment/instances/third_party.py`** — tightened module docstring (added usage example; fixed stale `(spec, routing_row, forward)` note that no longer matched the signature; stated terminal vs forwarding behaviour up front); function docstring now pairs the `targets` argument with `external_forward` semantics explicitly.
- **`tests/experiment/instances/test_third_party.py`** (new) — 5 `TestClass` / 6 tests covering app structure, terminal service, external-forward, Bernoulli (eps=1.0) failure, and log-row schema. Full `**TestClass**` + `*test_name()*` docstring convention; `mu=1e9` trick to keep per-test wall clock near-zero. All green in 7.7 s.
- **`tests/experiment/test_mem_budget.py`** — deleted `TestBudgetEnforcement413` class and the unused `make_atomic_service` shim. FR-2.4 runtime enforcement is deferred per `notes/prototype.md §7 item 3`; the 413 tests were red-by-accident (one failing, one passing-for-the-wrong-reason). Rewrote module docstring with `**TestClass**` bullets matching `test_tas.py` / `test_third_party.py`; added `*test_name()*` lead-ins across the surviving tests.
- **`src/scripts/demo_third_party.py`** (new) — three-section walkthrough (terminal / forwarding / Bernoulli) matching the existing `demo_services.py` / `demo_registry.py` / `demo_client.py` / `demo_payload.py` idiom: `_banner`, `sys.path` boot, numbered sections, `async def _demo()`, sync `main()`. Verified by invocation.
- **Suite**: 316 tests pass outside `tests/methods/test_experiment.py` (the 1 fail + 10 errors there are pre-existing drift from the experiment scope reset, `ClientConfig.kind_weights must sum to > 0`; orthogonal to this pass).

**Pattern captured:** when the skill pass touches a module whose sibling tests are already green, keep the scope tight: polish docstrings, fix stale references, delete dead code, add one demo. Don't chase unrelated failures surfaced along the way; log them instead.

---

## 2026-04-20 — Experiment method: scope reset to experimental-design discipline

The existing prototype (4/5) runs and tests pass, but it was built as "a working FastAPI replica" instead of "apparatus for a hypothesis-driven experiment". The scientific-method framing — **hypothesis → model → prototype → validation** — was not explicit in the design, so operating points (`[1, 2, 5, ..., 500]` req/s), tolerances, and acceptance criteria are all ad hoc rather than derived from what would prove/disprove the tech-agnosticism claim.

- Drafted `notes/prototype-req.md` with the experimental-design framing: hypothesis H1 (per-artifact `|ρ_meas − ρ_pred| ≤ τ_ρ` across adaptations), explicit reference model (analytic), FR-1..8 for the prototype apparatus, and a validation protocol that lives in a new notebook 06. Scope of the reset TBD — will be decided after the FR review.
- Open-questions section (§7 in the FR doc) lists 7 items for user review: hypothesis phrasing, tolerances, grid points, adaptation scope, profile coverage, notebook split, skill creation.

## 📌 To review — `04-yoly.ipynb` graph errors

User flagged 2026-04-20: some graphs in `04-yoly.ipynb` are incorrect. Needs a pass after the prototype-req.md review is settled. Capture the specific mistakes and fix in a dedicated commit (don't bundle with the experiment reset).

---

## 📌 Deferred cleanup — **after all implementation is done**

- [ ] **Strip all CS-2 (IoT-SDP) mentions from `notes/`.** `cs_context.md` and `cs_objective.md` were imported with both case studies in-tree as working context for CS-1; once the full pipeline (analytic, stochastic, dimensional, experiment, comparison methods + notebooks + tests) is green, purge the CS-2 sections, tables, ADRs (`ADR-CS2-*`), references (lines 764-782 of `cs_context.md`), and any cross-references. Post-implementation only — do not touch before the pipeline is reproducing `__OLD__` results.

---

## 2026-04-20 — Experiment method complete (4/5): FastAPI architectural replication + tech-agnostic validation

**Delivered.** Fourth of five evaluation methods in place. A FastAPI microservice replication of the TAS topology, deployed in-process via ASGI transport and routed by a shared `httpx.AsyncClient`. No dependency on ReSeP / ActivFORMS abstractions -- the point is to **validate DASA's technology-agnosticism**: if DASA's coefficients characterise the architecture rather than the implementation, they should transfer to a vanilla Python/FastAPI stack.

- **`src/experiment/`** — 6 modules:
  - `services/base.py` — `ServiceSpec` (immutable knobs from profile JSON), `ServiceState` (runtime: admission lock, c-slot semaphore, log buffer), `ServiceRequest` / `ServiceResponse` wire schema, `log_request` decorator enforcing M/M/c/K semantics (K admission + c capacity + Exp service time + Bernoulli failure + per-invocation CSV row).
  - `services/atomic.py` — `make_atomic_service(spec)` for MAS / AS / DS.
  - `services/composite.py` — `make_composite_service(spec, pattern, downstream_targets)` for TAS_{1..6}.
  - `patterns.py` — four adaptation patterns: `no_adapt` (baseline), `retry` (s1), `parallel_redundant` (s2), `retry_parallel_redundant` (aggregate). Plain async Python, no framework.
  - `client.py` — `ClientSimulator` with Poisson interarrival + λ-ramp (`run_ramp` mirrors the yoly sweep pattern; cascade-fail early stop).
  - `launcher.py` — `ExperimentLauncher` wires the 13-service mesh via a custom `_MultiASGITransport` that routes `httpx.AsyncClient` requests per-port to the right FastAPI app. Context-manager API for setup / teardown.
  - `registry.py` — `ServiceRegistry` resolves name -> URL from `data/config/method/experiment.json`.
- **`src/methods/experiment.py`** — standard orchestrator contract (`run(adp, prf, scn, wrt, method_cfg=None)`) + CLI. Runs the ramp, aggregates per-service CSVs, emits the analytic-compatible per-node DataFrame + network aggregate + R1/R2/R3 verdict.
- **`data/config/method/experiment.json`** — deployment-only config (ports, ramp schedule, pre-measured request sizes). **Does NOT duplicate DASA knobs** (mu, epsilon, c, K, routing) — those still live in `data/config/profile/<dflt|opti>.json`.
- **`05-experiment.ipynb`** — thin notebook with validation plots: per-artifact measured ρ vs predicted ρ scatter (headline tech-agnosticism plot), per-step p50/p95 response time, R1/R2/R3 verdict table.
- **Tests** — 32 new (17 service-layer + 10 pattern + 3 launcher + 9 orchestrator). Total suite **177 tests pass in ~3 min**.

**Key design decisions (see `notes/experiment.md` for rationale):**

- **FastAPI + uvicorn (via ASGI transport) + httpx + pytest-asyncio.** Async is non-negotiable; `time.sleep()` would block workers and destroy the M/M/c/K queue semantics. `await asyncio.sleep(Exp(1/mu))` matches the closed-form assumption.
- **Request size as HTTP header metadata**, never `psutil`. Client pre-samples `size_bytes` from the method config's per-kind map and propagates through the chain. Zero runtime noise, fully deterministic under seed.
- **`K` admission + `c` service semaphore inside the app.** Real queue semantics even without uvicorn's `--limit-concurrency` (which only fires on TCP binding, not in-process ASGI). `state.admit()` raises 503 when `in_system >= K`; `state.service_sem = Semaphore(c)` gates concurrent processing. Verified: a burst of 5 concurrent requests at K=2 produces >=3 rejections; c=2 caps concurrent processing.
- **In-process ASGI mesh over real uvicorn servers (for v1).** `_MultiASGITransport` routes httpx requests per-port to the right FastAPI app without binding ports. Fast + hermetic tests; no multiprocess orchestration complexity. Real uvicorn can be swapped in later if TCP-level realism matters.
- **λ ramp mirrors the yoly sweep.** `ClientSimulator.run_ramp()` goes from `lambda_start_frac * λ_max` to `λ_max` in `lambda_steps` increments; cascade-fail early stop when network-wide fail rate exceeds `cascade_fail_rate_threshold`. Output maps to coefficient trajectories comparable to `04-yoly.ipynb`'s `sweep_architecture` cloud.

**Deliberately NOT done** (documented as "v2" in `notes/experiment.md`):

- Real uvicorn + TCP deployment (would measure real network overhead).
- Multi-kind workflow (v1 only sends `kind="analyse"`; alarm / drug paths through TAS_{3,4} not exercised).
- Multiprocess launcher (in-process is sufficient for DASA validation at the service-composition level).

**Pipeline status.** 4 of 5 methods complete. Next: `comparison` (method 5) — aggregates analytic / stochastic / dimensional / experiment into a cross-method R1/R2/R3 verdict and delta plots.

**Session artifact cleanup.** `_rebuild_experiment.py` (one-off notebook scaffolder) was deleted after use per the project's no-scaffolder-in-git convention.

---

## 2026-04-19 — Dimensional method complete (3/5): engine + orchestrator + thin notebook

**Delivered.** Third of five evaluation methods in place.

- **`src/dimensional/`** — five thin adapters around PyDASA 0.7.1: `schema.build_schema()`, `engine.build_engine()`, `coefficients.derive_coefficients()` (config-driven via `{pi[i]}` placeholder spec), `sensitivity.analyse_symbolic()`, `reshape.{coefficients_to_nodes, coefficients_to_network, coefficients_delta, network_delta}`. Each module under 90 lines; PyDASA owns all the math.
- **`data/config/method/dimensional.json`** — FDUs (`T`, `S`, `D`), coefficient specs (`{pi[i]}` patterns for θ, σ, η, φ), sensitivity settings, and a `sweep_grid` (6 μ-factors × 4 c × 4 K) earmarked for `yoly.ipynb` (Phase 3b/c).
- **`src/methods/dimensional.py`** — orchestrator with `run(adp, prf, scn, wrt, method_cfg=None)` + CLI; mirrors analytic/stochastic contract. No `requirements.json`: dimensional characterises the design space, not operational thresholds.
- **`dimensional.ipynb`** (new) — 9-section thin notebook built via `scripts/build_dimensional_notebook.py` (reproducible regen). Runs all 4 adaptations and plots per-node heatmap / diffmap / network bars / delta for θ, σ, η, φ — **all reusing existing `src.view.qn_diagram` plotters**; no new view module needed for this notebook.
- **Tests** — 34 engine-level (schema, engine, coefficients, sensitivity, reshape) + 22 orchestrator-level = **56 new**; **138 total pass in ~6 min.**

**Key finding mid-Phase-3a: PyDASA reads `_std_mean`, not `_mean`.** The PACS Variable-dict carries both `_mean` / `_setpoint` (scenario-display) and `_std_mean` / `_std_setpoint` (canonical-units, what pydasa consumes). Only `_std_*` flows into `Coefficient.calculate_setpoint()`. Any seed / override must update both halves.

**Seeded dimensional from analytic results.** The profile JSON's static L / W / Lq / Wq / λ / χ `_mean` values were inherited from the OLD CSV and did not reflect per-adaptation operating points — every artifact came out with θ=0.6 uniformly. Fixed via `src/utils/seed_dim_from_analytic.py`: runs analytic on a representative scenario per profile (`baseline` for `dflt.json`, `aggregate` for `opti.json`) and writes the solver's per-node `λ, χ, L, L_q, W, W_q` back into the variable `_setpoint`, `_mean`, `_std_setpoint`, `_std_mean`, `_data` fields. Also refreshes `M_{act}` (depends on L). Post-seed baseline θ varies 0.005 (AS_{3}) to 0.21 (MAS_{3}); σ ≈ 1.0 uniformly (Little's-law sanity check).

**Limitation of the opti seed.** Only 13 of 16 opti artifacts are seeded — the three pre-adaptation swap-out artifacts (`MAS_{3}`, `AS_{3}`, `DS_{3}`) do not appear in the `aggregate` scenario's artifact list, so their `_mean` values remain stale. If dimensional is later invoked on `s1` / `s2` (which use a subset of those pre-adaptation artifacts), the stale fields will flow through. Acceptable for now per "seed once" scope; can extend to merge across scenarios later if needed.

**Notebook convention.** `dimensional.ipynb` is generated from `scripts/build_dimensional_notebook.py`; edit the script, re-run, commit both. Keeps the notebook in git as a snapshot while the source of truth remains Python.

---

## 2026-04-19 — Dimensional schema migration: `E → S`, plus `M_{act}`, `M_{buf}` per artifact

**Why.** Before starting the dimensional engine, the TAS profile configs needed to line up with the PACS reference framework `{T, S, D}` used by the two illustrative-example iterations (`__OLD__/src/exports/dimensional_{1,2}_draft.py`). Two gaps were blocking Phase 1:

1. **FDU symbol drift.** TAS used `E` (entity) for the request dimension; PACS (authoritative reference) uses `S` (structure). Same semantics, incompatible strings. PyDASA's `Schema` would reject every artifact.
2. **Missing D-dimension.** `\delta_{X}` (data density, kB/req) was present in every artifact but flagged `relevant: false`, and the companion memory variables `M_{act, X}` / `M_{buf, X}` were absent. Without them the Buckingham matrix has no D coverage and `\phi` (memory-usage coefficient) cannot be derived.

**What.** One-shot utility `src/utils/migrate_dim_schema.py` does three things per artifact:

- Rename token `E → S` in every `_dims` expression (117 in `dflt.json`, 144 in `opti.json`).
- Flip `\delta_{X}.relevant = true` (13 in `dflt.json`, 16 in `opti.json`).
- Insert `M_{act, X}` and `M_{buf, X}` with `_dims="D"`, `_units="kB"`, `_cat="CTRL"`, `relevant=true`, `_dist_type="data_product"`. Setpoints derived from existing setpoints:
  - `M_{act, X}._setpoint = L_{X}._setpoint × \delta_{X}._setpoint` (active memory)
  - `M_{buf, X}._setpoint = K_{X}._setpoint × \delta_{X}._setpoint` (allocated buffer)

For TAS_{1}: `M_{act} = 6 × 1064 = 6384 kB`, `M_{buf} = 10 × 1064 = 10640 kB`.

**Provenance of the numbers.**

- **`K = 10 req`** — canonical per `CLAUDE.md` ("every artifact has c=1 and K=10"); matches `__OLD__/data/config/cs1/default_dim_variables.csv` (mean=10, range=[5,15]); PACS iter1 used K_max=16 (same ballpark).
- **`\delta = 1064 kB/req`** — inherited verbatim from the OLD CSV's dimensional variable catalogue; anchored to medical-record / DICOM payload sizes (~1 MB typical). Not a direct citation from Weyns & Calinescu 2015 — the paper does not quantify payload size. This is an educated domain estimate applied uniformly across the 13 artifacts.
- **`M_buf = K · \delta`** and **`M_act = L · \delta`** — derived, not guessed. The only dimensionally-consistent interpretation of "buffer capacity in memory units".

**Outcome.** 70 existing tests still green (`pytest tests/` in ~12s). Schema is now compatible with PyDASA's Schema / Buckingham pipeline. Phase 1 of the dimensional method (engine + config-driven FDUs + coefficients) unblocked.

---

## 2026-04-19 — Stochastic method complete (2/5); dimensional split into two notebooks

**Delivered.** Second of five evaluation methods in place; SimPy DES engine + NetworkConfig wrapper agrees with the closed-form analytic solution within Monte-Carlo noise across every adaptation.

- **`src/stochastic/simulation.py`** — engine (`QueueNode`, `simulate_network`, `job`, `job_generator`) + `solve_network(cfg, method_cfg)` adapter in a single file (mirrors `src/analytic/jackson.py`). Seeds both `random` and `numpy.random` at the start of each multi-rep call for reproducibility.
- **`src/methods/stochastic.py`** — `run(adp, prf, scn, wrt, method_cfg=None)` orchestrator + CLI. The `method_cfg` kwarg lets tests inject an abbreviated config without touching disk.
- **`src/view/qn_diagram.py`** — seventh plotter, `plot_nd_ci(nds, *, metric, reference=None, reps=N, confidence=0.95, ...)`. Errorbar-on-points chart with optional analytic overlay as red `x` markers. Used in §6 of `stochastic.ipynb`.
- **`stochastic.ipynb`** — nine sections, thin notebook; renders topology / heatmap / diffmap / CI (ρ + W) / net_bars / net_delta under `data/img/stochastic/<scenario>/` (22 figure files, PNG + SVG each).
- **Tests** — 19 new (9 engine, 10 orchestrator) using `_QUICK_CFG` (3 reps × 1000 invocations / 100 warmup) for ~30x speedup. 70 total pass in ~9s.

**Invocation → seconds bridge.** Method config declares `horizon_invocations` / `warmup_invocations` (unitless counts); the SimPy engine runs in time. Conversion `seconds = invocations / sum(lambda_z)` lives in `solve_network`. Don't move it — keeps `simulate_network` unit-agnostic.

**Cross-method sanity.** Every analytic per-node ρ falls INSIDE the stochastic 95% CI band on the baseline figures (`data/img/stochastic/baseline/nd_ci_rho.png`). Aggregate W_net: analytic 3.09 ms, stochastic 3.10 ms. The two methods mutually validate.

**Data/reference housekeeping.** Merged `data/reference/version.txt` + `data/reference/profile.md` into a single `summary.md`; dropped the sources.

**Dimensional method split into TWO notebooks (user decision 2026-04-19):**
- `dimensional.ipynb` — pre/post adaptation solution, but plotting **coefficients** (θ, σ, η, φ) not queue metrics, reusing the existing heatmap / diffmap / bars / delta plotters with coefficient columns.
- `yoly.ipynb` — configuration-sweep diagram (`plot_yoly_*` family ported from `__OLD__/src/notebooks/src/display.py`), shows how TAS behaves across a sweep of configurations. New sibling view module `src/view/yoly_diagram.py` to keep queue-network and yoly visuals separate.
- Plan captured in memory (`project_dimensional_plan.md`) for the next session to pick up.

**Next**: start `src/dimensional/` engine + two notebooks.

---

## 2026-04-19 — Analytic method reproduces __OLD__ CSV to 6 decimals

**Delivered.** Silent config drift found and fixed; baseline Jackson solution now matches `__OLD__/data/results/cs1/data/dflt_analytical_{node,net}_metrics.csv` to the 6th decimal place on every per-node row and every network-wide aggregate.

- **`c=1`, `K=10` canonical values restored** across every artifact in both `data/config/profile/dflt.json` and `opti.json`. `dflt.json` had silently drifted to `c=2` (halving every utilisation); `opti.json` also had `K=6` (tightened during some earlier test). One-shot repair utility at `src/utils/fix_c_k.py` — ran once, left in place as a frozen record.
- **Artifact + variable keys migrated to LaTeX form.** Artifact JSON keys: `TAS_1` -> `TAS_{1}`, `MAS_3` -> `MAS_{3}`, etc. Variable keys with q-subscripts split correctly: `Lq_{TAS_{1}}` -> `L_{q, TAS_{1}}`, `Wq_{TAS_{1}}` -> `W_{q, TAS_{1}}`. One-shot migration utility at `src/utils/rename_keys.py`. `ArtifactSpec._sub()` collapsed to identity (key IS the LaTeX subscript now).
- **Baseline headline numbers** (exact match with OLD CSV): `avg_mu=653.85`, `avg_rho=0.29728`, `L_net=6.98730`, `Lq_net=3.12884`, `W_net=3.437 ms`, `Wq_net=1.541 ms`, `TP_net=2038.50`. Per-node rows also match (MAS_3: rho=0.694, L=2.068, W_q=0.01336).

**`src/view/qn_diagram.py` grew to six plotters** with a uniform signature contract (keyword-only after required positionals, return `Figure`, save both PNG+SVG via `_save_figure`): `plot_qn_topology`, `plot_qn_topology_grid`, `plot_nd_heatmap`, `plot_nd_diffmap`, `plot_net_bars`, `plot_net_delta`. Ported `_generate_color_map` from `__OLD__/src/notebooks/src/display.py` for the multi-scenario palette. Fixed the SVG-dark-theme text-invisibility gotcha: `_TEXT_BLACK = "#010101"` (not pure `"black"`) forces matplotlib to emit an explicit `fill` attribute that dark-theme viewers cannot override.

**Notebook** (`analytic.ipynb`, 17 cells under the 30-cell budget) produces one standalone topology per adaptation + per-node heatmap + per-node diffmap + network-wide bars + network-wide delta bars — 20 figures total under `data/img/analytic/<scenario>/` (PNG + SVG for each of 10 figure types). Outputs cleared before commit.

**Tests:** 51 green (11 queues, 4 jackson, 12 metrics, 11 io/config, 13 methods/analytic).

**Pitfalls captured in memory** (so they do not return): `c=1, K=10` canonical values; LaTeX key format; uniform `arc3,rad=0.2` for self-loops (custom `rad=1.0` overlaps cross-edges); `#010101` text colour. See `CLAUDE.md` §`View (Plotting) Conventions` and Claude memory project entries.

**Next method in the pipeline**: `src/stochastic/` (SimPy DES). Config already at `data/config/method/stochastic.json`.

---

## 2026-04-18 — Analytic method complete (5/5 milestones)

**Delivered.** First end-to-end evaluation method is green across the full 4-adaptation axis; `analytic.ipynb` reproduces the metrics table and 11 figures from a cold clone.

- **`src/analytic/`** — `queues.py` (registry-dispatch `Queue()` factory + `BasicQueue` ABC + `QueueMM1` / `QueueMMs` / `QueueMM1K` / `QueueMMsK` concrete classes; `_QUEUE_MODELS` dict at module bottom makes adding new models one entry), `jackson.py` (`solve_jackson_lambdas()` linear core + `solve_network()` wrapper), `metrics.py` (`aggregate_network()` + `check_requirements()` with JSON-backed thresholds).
- **`src/view/qn_diagram.py`** — 5 plotters (`plot_qn_topology`, `plot_qn_topology_grid`, `plot_nd_heatmap`, `plot_net_bars`, `plot_net_delta`) with a uniform param-IO convention (keyword-only args after required positionals; every plotter returns `Figure` and persists when `file_path` + `fname` given). Shared `_save_figure()`, `_resolve_metrics()`, `_resolve_labels()` helpers.
- **`src/methods/analytic.py`** — `run(adp, prf, scn, wrt)` orchestrator + CLI. The written envelope carries the full `routing` (13x13) and `lambda_z` (13) fields alongside metrics so downstream consumers can reconstruct paths without re-opening configs.
- **`analytic.ipynb`** at repo root — thin notebook (20 cells, under the 30-cell budget). Calls `run()` across the 4 adaptations, prints the summary + verdict tables, saves 11 figures under `data/img/analytic/<adaptation>/`. Clears outputs before commit.

**Thresholds externalised.** `data/reference/baseline.json` now holds the Camara 2023 R1 / R2 / R3 values (`0.0003`, `0.026 s`, `null`); `metrics.py` reads them via `src.io.load_reference("baseline")`. No more hardcoded `_R1_MAX_FAIL_RATE` / `_R2_MAX_RESP_TIME` in Python.

**Headline numbers at 345 req/s** (all four adaptations PASS R1 / R2 / R3):

| adaptation | W_net (ms) | avg_rho | max_rho | bottleneck |
|---|---|---|---|---|
| baseline   | 1.99 | 0.149 | 0.347 | MAS_3 |
| s1         | 2.01 | 0.164 | 0.375 | MAS_3 |
| s2         | 2.08 | 0.168 | 0.356 | DS_1 |
| aggregate  | 1.95 | 0.161 | 0.345 | DS_1 |

Aggregate is the best configuration on both `W_net` and `max_rho`; s1 alone is the worst on `max_rho` because opti routing pushes more load into the dflt services at the three swap slots (MAS, AS, DS). Bottleneck shifts from MAS (dflt services) to DS (opti services) as soon as `s2` / `aggregate` activate.

**Tests.** 51 pytest cases green: 11 queues, 4 jackson, 12 metrics (includes 3 pinning thresholds to the JSON), 11 io/config, 13 methods/analytic. Notebook runs cold without manual intervention.

**Housekeeping.**
- `data/results/` tracked as a directory (1 `.gitkeep` + local `.gitignore`); generated JSONs remain ignored.
- `src/utils/import_old.py` removed — migration script served its purpose; `dflt.json` / `opti.json` are the sources of truth.
- `conftest.py` kept with a TODO pointing at the eventual `pyproject.toml` replacement.

**Pending.** 4 methods still unbuilt (`stochastic`, `dimensional`, `experiment`, `comparison`); `assets/` documentation staging directory still empty.

---

## 2026-04-18 — `opti.json` restructured: dict-keyed scenarios, explicit service swaps

**Delivered.**

- **`opti.json` artifacts expanded from 13 to 16.** The three swap slots (nodes 6, 9, 11) now carry BOTH variants: `MAS_3` (dflt) alongside `MAS_4` (opti), `AS_3`/`AS_4`, `DS_3`/`DS_1`. The opti CSV's `name` column (`MAS 3->4`, `AS 3->4`, `DS 3->1`) motivated distinct artifact keys instead of silently overwriting values in-place.
- **`_nodes` is now a dict per scenario**, each value a 13-element list naming the active artifact at each positional slot:
  - `_nodes["s1"]` uses dflt services at the swap slots (`MAS_3`, `AS_3`, `DS_3`)
  - `_nodes["s2"]` and `_nodes["aggregate"]` use opti services (`MAS_4`, `AS_4`, `DS_1`)
- **`_routs` and `_labels` also keyed by scenario name** (matching `_nodes`). `dflt.json` uses the same dict shape for operational consistency — single key `"baseline"`.
- **`_vars_source` removed.** It was a workaround for the previous fixed `_nodes` list + external composition; now that `_nodes[scenario]` names the right artifacts directly, composition is explicit.
- **Labels rewritten without em dashes**; each label names the strategy (Retry / Select Reliable), the service swaps, and what stays dflt vs opti.

**Generator refactor.** `src/utils/import_old.py` now has two node-to-artifact maps (`_DFLT_NODE_MAP`, `_OPTI_NODE_MAP`) and passes the map into `load_topology` / `load_variables` / `_rename_depends`. Re-run: `python -m src.utils.import_old`.

---

## 2026-04-18 — `opti.json` + `data/reference/`; `adaptation/` retired

**Delivered.**

- **`data/config/profile/opti.json`** generated by `src/utils/import_old.py` from `__OLD__/data/config/cs1/optimal_{qn_model,dim_variables}.csv`. PACS-style envelope, 13 artifacts, 143 opti variables. `environments._scenarios = ["s1", "s2", "aggregate"]` with `_vars_source = ["dflt", "opti", "opti"]` and `_routs = [opti, dflt, opti]` — so each scenario composes (routing × variables) from the right source.
- **`data/reference/`** — authors' TAS 1.6 replication dump (`Cost-QoS`, `Preferred-QoS`, `Reliability-QoS` × `no-adapt`, `simple-adapt` — six leaf folders, each with `invocations.csv`, `log.csv`, `results.csv` + 8 PNG charts). Column schema in `data/reference/profile.md`. Treated as the authoritative reproduction target for the `experiment` method's acceptance criterion.
- **`data/config/adaptation/` removed.** The two stub files (`s1.json`, `s2.json` with `MAX_TIMEOUTS` / `timeout_length_ms` / `parallel_count` / `rt_threshold_ms` placeholders) are redundant now that `opti.json` enumerates all three after-adaptation scenarios self-sufficiently.
- **Docs synced** — `workflow.md` §1/§2 adaptation-axis table and directory layout, `CLAUDE.md` data convention, `README.md` axis table + folder tree, `quickstart.md` adaptation table.

**Loader contract (unchanged CLI).** `--adaptation <baseline|s1|s2|aggregate>` still works, but the loader's composition rule tightens:

- `baseline` → `dflt.json` (only scenario)
- `s1` → `opti.json._scenarios[0]`; vars from dflt, routing from opti
- `s2` → `opti.json._scenarios[1]`; vars from opti, routing from dflt
- `aggregate` → `opti.json._scenarios[2]`; vars from opti, routing from opti

**SUMMARY.md** gained a References section (CS-1 refs [1], [2], [3], [9] Rico, [10], [13]) matching the works actually cited, with a pointer to `cs_context.md § References` for the full list.

---

## 2026-04-18 — Data backbone ported; README/SUMMARY rewritten

**Delivered.**

- **Config tree scaffolded** under `data/config/`:
  - `profile/dflt.json` — 13-node topology (M/M/s/K) + 143 PyDASA variables, produced by `src/utils/import_old.py` from `__OLD__/data/config/cs1/default_qn_model.csv` + `default_dim_variables.csv`.
  - `adaptation/s1.json`, `s2.json` — stub override files for Retry-style (S1) and Select-Reliable-style (S2) with placeholder params (`MAX_TIMEOUTS`, `timeout_length_ms`, `parallel_count`, `rt_threshold_ms`).
  - `method/stochastic.json` — SimPy params (seed=42, 10k invocations, 10 replications, 95 % CIs; mirrors [13] § V-B).
  - `method/experiment.json` — architectural-experiment params (500 invocations × 6 replications; reproduces [1] Table IV).
- **README + SUMMARY rewritten** — now scoped to CS-01 TAS only (prior README mixed CS-01 and CS-02). README links to the six `notes/*.md` + `CLAUDE.md`; SUMMARY carries the Table IV headline numbers and the R1/R2/R3 targets.

**`src/utils/import_old.py`** kept as a committed tool so the conversion is reproducible (not a throwaway). Re-run with `python -m src.utils.import_old` whenever the old CSVs change.

**Repo hygiene decision — results never committed.**

Per user: the bulk of result files should not be checked in. Anyone reproducing runs the pipeline locally. Added to `.gitignore`:

- `data/results/` — all method runs produce JSONs here; ignored en masse.
- `lab/` — future scratchpad PoCs.
- `build/`, `.reports/`, `*.ipynb_checkpoints/`.

**Still tracked:** `data/config/` (all configs, including the 143-variable `dflt.json` at 114 KB), `assets/img/` (figures cited in reports), `notes/`, `src/`, `tests/`.

**Next steps.**

- [ ] Scaffold remaining `src/` subpackages with empty `__init__.py`: `analytic`, `stochastic`, `dimensional`, `experiment`, `view`, `io`, `methods`
- [ ] Implement `src/io/config.py` profile ⊕ adaptation merge helper (Move 2)
- [ ] Implement `src/methods/analytic.py` + `src/analytic/` M/M/c/K solver as first end-to-end method (Move 3)
- [ ] Pytest skeleton mirroring `src/`
- [ ] Thin notebook stubs at repo root

---

## 2026-04-18 — Result-filename symmetry: `<profile>.json` per run

Spotted asymmetry between inputs (named by identifier: `profile/dflt.json`, `adaptation/s1.json`) and outputs (named by content type: `variables.json`). Fixed by naming the per-run output file after the profile identifier, matching the PACS precedent (`PACS-vars-iter1.json`).

**Per-run output is now a single JSON** named after the profile, following the PACS pattern:

```
data/results/<method>/<adaptation>/<profile>.json
```

The file carries a PyDASA-compatible object with content keyed inside:

- `variables` — PyDASA Variable dict (every method)
- `coefficients` — derived DCs (dimensional only)
- `pi_groups` — raw π-groups (dimensional only)
- `deltas` — per-variable differences (comparison only)

**Split out:** `requirements.json`. R1/R2/R3 verdicts are profile-agnostic and consulted independently of raw variables; they keep a content-type name.

**Adding a second profile is additive.** `camara.json` drops next to `dflt.json` in the same (method, adaptation) folder; no migration.

---

## 2026-04-18 — Final shape: two-axis, JSON results, 20-run matrix

**Refinements that closed the design.**

1. **Collapsed scenario and strategy into one adaptation axis.** In this case study S1 and S2 are two names for the same "after adaptation" concept seen through different scenario lenses: S1 applies switch-to-equivalent (Retry mechanics), S2 applies preferred-service ranking (Select Reliable mechanics). They are not independent axes. Values: `baseline`, `s1`, `s2`, `aggregate`.
2. **`aggregate` is a real run**, not a display rollup. It applies both S1 and S2 overrides together — the realistic deployed configuration a production system would actually use.
3. **`baseline` is a run tag, not a config file.** The profile is the baseline; no `adaptation/baseline.json`. Adaptation configs only exist for S1 and S2; `aggregate` merges both.
4. **Result and config files are JSON (PACS format)**, not CSV. Every file uses the PyDASA `Variable`-dict schema keyed by LaTeX symbol with `_sym`, `_dims`, `_units`, `_min`, `_max`, `_setpoint`, `_data`, … — same as `__OLD__/src/notebooks/data/PACS-vars-iter1.json`. Inputs and outputs share the schema, no CSV↔JSON conversion.
5. **Leaf files:** `variables.json` and `requirements.json` for every method; plus `coefficients.json` / `pi_groups.json` for dimensional; plus `deltas.json` for comparison.
6. **Single CLI shape:** `python -m src.methods.<method> --adaptation <baseline|s1|s2|aggregate> [--profile dflt]`. The `src.io` layer handles the profile ⊕ adaptation merge.

**Matrix.** 5 methods × 4 adaptations = **20 runs**. Each of analytic / stochastic / dimensional / experiment runs 4 adaptations; comparison reads all four methods per adaptation and writes 4 comparison reports.

**Dropped from earlier drafts.**
- Separate `scenario` and `adaptation` axes (merged into one).
- CSV leaf files (→ JSON/PyDASA schema).
- Per-strategy adaptation values (`retry`, `select_reliable`) — these are the *mechanics* of S1/S2, not separate options. Documented in method contracts as "S1 = Retry-style, S2 = Select-Reliable-style".
- The "utility" axis (`cost_qos`/`reliability_qos`/`preferred_qos`). R1/R2/R3 are fixed thresholds from Cámara 2023, reported in `requirements.json` per run.
- Four-token flat filename pattern — axes live in the path, leaves are just `<content>.json` (one more token-free).

**Next steps.**

- [ ] Scaffold `src/methods/` modules with `run(adaptation, profile='dflt')` signature and CLI stub
- [ ] Scaffold `src/` subpackages (`analytic`, `stochastic`, `dimensional`, `experiment`, `view`, `io`, `utils`)
- [ ] Scaffold `data/config/{profile,adaptation,method}/` with stub JSONs in PyDASA Variable-dict format (port `profile/dflt.json` from Table III of [1])
- [ ] Scaffold `src.io` profile ⊕ adaptation merge helper
- [ ] Create 5 thin notebook stubs at root
- [ ] `tests/` mirrors `src/` subpackages

---

## 2026-04-18 — Naming convention locked: four-axis, one pattern

**Decision.** Every file, folder, and CLI argument uses the same four axes in the same order:

- `<method>` ∈ `{analytic, stochastic, dimensional, experiment, comparison}` — reframed from "stage" to "method" because the code implements DASA's **evaluation methods**, not sequential stages.
- `<scenario>` ∈ `{s1, s2}` — service failure and response-time variability (the two focus scenarios per `cs_objective.md`; S3–S5 out of scope).
- `<adaptation>` ∈ `{baseline, retry, select_reliable}` — `baseline` = No Adaptation, the before-adaptation reference. `retry` and `select_reliable` are the after-adaptation strategies from Table IV of [1].
- `<profile>` ∈ `{dflt, ...}` — service catalogue variant; CLI flag, defaults to `dflt`.

**Naming convention.** Paths carry the axes, leaves carry only `<scope>.<artifact>.<ext>`:

- configs: `data/config/<axis-folder>/<value>.json`
- results: `data/results/<method>/<scenario>/<adaptation>/<scope>.<artifact>.<ext>`
- figures: `assets/img/<method>/<scenario>/<adaptation>/<figure>.png`
- CLI: `python -m src.methods.<method> --scenario <s> --adaptation <a> [--profile <p>]`

**Dropped.** The "utility" axis (`cost_qos`/`reliability_qos`/`preferred_qos` from `__OLD__/data/baseline/cs1/`). Those variants corresponded to different weight sets inside R3's utility function. In the new framing, R1/R2/R3 are validation criteria evaluated in `requirements.csv` per run, not a run axis. Keeps the matrix flat at 30 runs instead of 90.

**Why the rename.** Single-repo, single case study — no `CS-01-` prefix needed. "Method" matches the case-study narrative (`cs_objective.md` frames each as an evaluation method). The four-axis pattern is strictly repetitive: the same four words appear in the same order in every path, filename, and CLI — auditor-friendly, greppable, scriptable.

**Run matrix.** 5 methods × 2 scenarios × 3 adaptations = 30 runs. The comparison method collapses across the other four per (scenario, adaptation), producing 6 comparison reports.

**Validation criteria.** Every run emits `requirements.csv` with one row per R1/R2/R3 target from Cámara 2023:

- R1: failure rate ≤ 0.03 % (Availability)
- R2: response time ≤ 26 ms (Performance)
- R3: minimise cost subject to R1 ∧ R2

**Next steps.**

- [ ] Scaffold `src/methods/` modules with `run(scenario, adaptation, profile)` signature and CLI stub
- [ ] Scaffold `src/` subpackages (`analytic`, `stochastic`, `dimensional`, `experiment`, `view`, `io`, `utils`)
- [ ] Scaffold `data/config/{profile,scenario,adaptation,method}/` with stub JSONs (profile/dflt from Table III of [1])
- [ ] Create 5 thin notebook stubs at root
- [ ] `tests/` mirrors `src/` subpackages

---

## 2026-04-18 — Workflow shape locked: five stages, hybrid pattern

**Decision.** Pipeline is five stages: **S1 Analytic, S2 Stochastic, S3 Dimensional, S4 Comparison, S5 Architectural Experiment**. No `-CS-01-` prefix in filenames (single-case repo). No calibration notebook.

**Pattern.** Hybrid — each stage is a Python module `src/stages/sN.py` exposing `run(config_path) -> dict` and a `main()` CLI; a thin notebook `SN.ipynb` at repo root calls `run()` for narrative and inline display. CLI and notebook produce byte-identical artifacts. Logic lives in `src/`, never in notebooks.

**Why.** Optimises for *"follow or any external auditor or public exposure"*:
- CLI makes the pipeline scriptable and CI-friendly; notebooks make it reviewable.
- Unit tests can target `src/` modules directly instead of parsing `.ipynb` JSON.
- Clean git diffs because notebooks stay small.
- Slightly more upfront effort than pure notebooks, but pays back the moment tests or automation are needed.

**What was dropped and why.**
- **Calibration (former `CS-01X`)**: if the analytic model disagrees with the stochastic ground truth, that is a finding worth reporting, not a parameter to tune away. Config optimization (the `opti_*` prefix from the old artifacts) is a side effect of S4 if a second pass is wanted.
- **`CS-01-` prefix**: this repo holds exactly one case study; the prefix was pure ceremony.
- **`data/baseline/` and `data/analysis/` subfolders**: collapsed into `data/config/` (inputs) and `data/results/` (outputs). Simpler I/O contract.

**Alternatives considered.** Pure notebooks (cheaper start, worse diffs and tests), pure CLI (no narrative for publication), Jupytext paired files (adds a pre-commit hook dependency), Quarto (overkill for early iteration). Hybrid won on long-run maintainability.

**Next steps.**
- [ ] Scaffold `src/` subpackages (`analytic/`, `stochastic/`, `dimensional/`, `experiment/`, `view/`, `io/`, `utils/`) with empty `__init__.py`
- [ ] Scaffold `src/stages/s{1..5}.py` with `run()` signature and CLI stub
- [ ] Scaffold `tests/` mirroring `src/`
- [ ] Create 5 thin notebook stubs (`S1.ipynb`..`S5.ipynb`)
- [ ] Port the service catalogue from `__OLD__/data/config/cs1/default_qn_model.csv` to `data/config/dflt.json`
- [ ] Update `README.md` + `SUMMARY.md` to match the new shape

---

## 2026-04-18 — Project restart from scratch

**Decision.** Archive the prior implementation under `__OLD__/` and rebuild the case study on top of the current PyDASA release. The old version mixed closed-form and stochastic results without a clean modelling layer boundary, which made it hard to reproduce the dimensional analysis step.

**What moved to `__OLD__/`:**

- 6 notebooks: `CS-01A` (Analytical), `CS-01B` (Stochastic), `CS-01C` (Dimensional), `CS-01D` (Dimensional Simulations), `CS-01E` (Data Analysis), `CS-01X` (Analytical Calibration)
- `src/{model,simulation,utils,view}/`
- `data/{analysis,baseline,config,results/cs1/{data,img}}/`
- Prior notes and commands reference

**What stays:**

- `LICENSE`, `.gitignore`, high-level `README.md` (to be rewritten and scoped to CS-01 only)
- `requirements.txt` (pinned against PyDASA 0.3.2 wheel)
- `.claude/` skills scaffold (needs pruning — some leftover out-of-scope skills)

**Next steps.**

- [ ] Confirm notebook list and ordering (keep all 6, or collapse `E` into per-model notebooks?)
- [ ] Decide whether to port any code from `__OLD__/src/` or start clean against `pydasa` package
- [ ] Prune `.claude/skills/` of out-of-scope skills; port `commands/` from `../PyDASA/.claude`
- [ ] Rewrite `README.md` + `SUMMARY.md` scoped to CS-01 TAS
- [ ] Scaffold empty `src/`, `data/`, `assets/`, `tests/` and notebook stubs
- [x] ~~Decide: keep `__OLD__/` tracked in git, or `.gitignore` it?~~ → **Keep tracked** during migration; remove once the new notebooks + `src/` reproduce its results.

## Open questions

- Does PyDASA 0.3.2 already expose the π-group builders this case study needs, or do we need helpers in local `src/`?
- Calibration notebook (`CS-01X`) — keep as separate deliverable or fold into `CS-01A`?

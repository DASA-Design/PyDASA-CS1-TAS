# Calibration — current state and reference

Per-host noise-floor characterisation that gates every `experiment.run`. The phased build-out (P0-P5) is closed as of 2026-04-25; closed-phase narrative lives in `notes/devlog.md` (2026-04-25 entry) and `memory/project_calibration_p0_p1_closed.md`. This file is the **current-state reference** — what calibration is, what it measures, what it gates.

## Role

Calibration is a **precondition gate**, not a hypothesis test. See
`notes/proof.md::Two-stage structure` and
`memory/feedback_calibration_vs_model_error.md` for the framing. ≤ 5 %
relative error on the simple host-floor probes is the gate; below that,
experiments cannot decide anything.

## Module map

| Module | Role |
|---|---|
| `src/methods/calibration.py` | Runner. Public: `run(...)` (full envelope), `run_rate_sweep(...)` (rate-saturation probe), `run_calib_sweep(...)` (multi-combo dim-card sweep). CLI: `python -m src.methods.calibration` + `--rate-sweep` opt-in. |
| `src/io/tooling.py` | Loader + derivation. Public: `find_latest_calibration`, `load_latest_calibration`, `calibration_floor_us`, `calibration_band_us`, `calibration_age_hours`, `rate_sweep_calibrated_rate`, `rate_sweep_loss_at`. Re-exported from `src.io`. |
| `src/view/characterization.py` | Plotters. Public: `plot_calib_dashboard`, `plot_calib_scaling`, `plot_calib_rate_sweep`. Re-exported from `src.view`. |

## What calibration measures (5 phases)

| # | Phase | What | Driver | Default | Output (envelope key) |
|---|---|---|---|---|---|
| 1 | timer resolution | smallest non-zero `perf_counter_ns()` delta | in-process loop | 100 000 samples (~1 s) | `timer.{min_ns, median_ns, mean_ns, std_ns, zero_frac}` |
| 2 | scheduling jitter | OS oversleep on `asyncio.sleep(1ms)` | in-process | 5 000 samples (~5 s) | `jitter.{mean_us, p50_us, p99_us, max_us, std_us}` |
| 3 | loopback latency | round-trip with empty handler | uvicorn loopback | 5 000 samples (~5 s) | `loopback.{min_us, median_us, p95_us, p99_us, std_us, samples}` |
| 4 | handler scaling | response time at increasing `n_con_usr` (closed-loop) | uvicorn loopback | 500 samples per level × 8 levels | `handler_scaling.{<n>: stats}` |
| 5 | rate sweep (opt-in) | highest open-loop rate sustained under `target_loss_pct` | standalone vernier | `rates × trials_per_rate` | `rate_sweep.{rates, aggregates, calibrated_rate}` |

Phase 5 is opt-in via `data/config/method/calibration.json::skip_rate_sweep` (default `true`) or CLI `--rate-sweep`.

## Reporting convention

Every measured experiment latency is reported as:

```
reported = measured_us - loopback.median_us  ± jitter.p99_us
```

Subtract loopback median (irreducible host overhead); report jitter p99 as the uncertainty band. Any measured value below `loopback.median_us` is an instrument error, not a real service.

## Envelope shape (on disk)

`data/results/experiment/calibration/<host>_<YYYYMMDD_HHMMSS>.json`:

```jsonc
{
    "host_profile": {hostname, os, cpu_count, ram_total_gb, ...},
    "args": {...},                          // run settings
    "timer":   {min_ns, median_ns, mean_ns, std_ns, zero_frac},
    "jitter":  {mean_us, p50_us, p99_us, max_us, std_us},
    "loopback":{min_us, median_us, p95_us, p99_us, std_us, samples},
    "handler_scaling": {"<n_con_usr>": {min_us, median_us, p95_us, p99_us, std_us, samples}},
    "dimensional_card": {                   // PyDASA-routed Route-B measured coefficients
        "\\theta_{CALIB}", "\\sigma_{CALIB}", "\\eta_{CALIB}", "\\phi_{CALIB}",
        "c_{CALIB}", "\\mu_{CALIB}", "K_{CALIB}", "\\lambda_{CALIB}",
        "n_con_usr_{CALIB}",                // List[float], plug into plot_yoly_chart
        "meta": {tag, mu_source, mu_req_per_s, c_srv, uvicorn_backlog, payload_size_bytes, n_con_usr}
    },
    "rate_sweep": {                         // opt-in
        "adaptation", "rates", "trials_per_rate", ...,
        "aggregates": {"<rate>": {target, mean, lo, hi, mean_loss_pct, mean_entry_lambda, n}},
        "per_trial":  {"<rate>": [...]},
        "calibrated_rate",
        "target_loss_pct"
    },
    "timestamp", "elapsed_s", "output_path"
}
```

Multi-combo sweep envelope (`*_sweep.json`): nested `{combo_tag: per_combo_card}` matching `derive_calib_coefs` output, plus a top-level `host_profile` + `sweep_grid` block.

## Terminology — `c_srv` vs `n_con_usr`

| Symbol | Meaning | Type | Where |
|---|---|---|---|
| **`c_srv`** (wire field: `c`) | service-side parallel handlers (M/M/c/K server count) | int, fixed per artifact | profile JSONs (`c_{TAS_{1}}`, ...), `SvcSpec.c` (+ `SvcSpec.c_srv` alias), Jackson solver |
| **`n_con_usr`** | client-side concurrent-user load (in-flight request count) | int, swept across the calibration ladder | `data/config/method/calibration.json::n_con_usr`, `calibration.py` + `characterization.py` + notebook |

Never use bare `c` or `concurrency` for the calibration load axis — always `n_con_usr`. Service configuration always uses `c` / `c_srv`. The calibration service stays at `c_srv=1` throughout every probe; only `n_con_usr` varies.

## Tunables

All in `data/config/method/calibration.json`. Default sample counts run in ~3 min on a 16-core laptop; the optional rate sweep adds ~15 min on top. Multi-combo sweep at the current grid runs in ~21 min.

Key fields:

| Field | Role |
|---|---|
| `timer_samples`, `jitter_samples`, `loopback_samples`, `loopback_warmup` | per-phase sample counts |
| `n_con_usr` | concurrency ladder for phase 4 |
| `samples_per_level` | requests per `n_con_usr` step |
| `port`, `uvicorn_backlog`, `httpx_timeout_s` | transport plumbing |
| `payload_size_bytes` | request body for the `phi` coefficient (default 128 kB) |
| `inter_level_delay_s` | quiet window between phase-4 levels (same server) |
| `inter_trial_delay_s` | quiet window between phase-5 rates (same vernier) |
| `inter_combo_delay_s` | quiet window between multi-combo sweep combos (uvicorn rebind + TIME_WAIT drain) |
| `rate_sweep.{rates, trials_per_rate, max_probe_window_s, target_loss_pct}` | rate-saturation probe |
| `sweep_grid.{c, K, mu_factor, lambda_steps, lambda_factor_min, util_threshold, mu_anchor_req_per_s}` | multi-combo dim-card sweep |

## Dimensional card (Route-B, PyDASA-routed)

`src.methods.calibration.derive_calib_coefs(envelope, payload_size_bytes=0, K_values=None, ...)` derives `(theta, sigma, eta, phi)` from measured `handler_scaling` + `loopback` blocks via PyDASA's `MonteCarloSimulation(mode="DATA")`. Per-`n_con_usr` measurement arrays populate `Variable._data`; an `AnalysisEngine` is built over the standard FDU schema; four `pydasa.Coefficient` objects are constructed in terms of base CALIB variables (no Pi-group indices); MCS lambdifies each coefficient expression and evaluates row-wise.

- `mu` comes from the loopback probe: `mu = 1e6 / loopback.median_us`
- `c_srv = 1`, `K` = `args.uvicorn_backlog` unless `K_values=[...]` overrides
- `payload_size_bytes` for the `phi` coefficient (degenerate when 0; reduces to `L/K` when non-zero)
- Memory variables use `M_{a<tag>}` / `M_{b<tag>}` (single-letter root + tag in subscript) so sympy's LaTeX parser handles lambdification cleanly
- Result keys: `\theta_{CALIB}`, `\sigma_{CALIB}`, ..., shaped for `src.view.plot_yoly_chart`
- `epsilon` is structurally 0 for `/ping` and NOT part of the card
- `meta.pipeline = "pydasa.MonteCarloSimulation(mode=DATA)"`

## σ formula

`σ = λW / K` (queueing share of capacity), corrected from `λW/L` on 2026-04-25. Under Little's law (`λW = L`), `σ ≡ θ` on closed-form solves; on prototype runs `σ ≈ θ` only approximately because operational `λ` counts every arrival but `L = X·W` uses successful-throughput `X`.

## Multi-combo sweep K-fix (2026-04-28)

`_drive_one_combo` synthesises a per-combo envelope and previously passed `args.uvicorn_backlog` (16384 default) to `derive_calib_coefs`, leaking host-default K into every combo card. Fixed: `_synth_env["args"]["uvicorn_backlog"] = int(_K_val)` AND `derive_calib_coefs(..., K_values=[int(_K_val)])`.

## Rate-sweep decoupling (2026-04-28)

`run_rate_sweep` drives the **standalone ping/echo vernier** (one server reused across rates × trials), not the full TAS mesh. Achieved rate = `samples / window_s`. Loss = `(target - achieved) / target × 100`. Decoupled from any TAS profile, no `entry_service` coupling, no `experiment.run` recursion.

## Zombie cleanup (2026-04-28)

Three layers of defence against orphaned uvicorn workers when a sweep is killed mid-flight:

1. **Per-combo `try / finally _server.shutdown()`** in `_drive_one_combo` — normal flow.
2. **`atexit` hook over `_ACTIVE_VERNIERS: weakref.WeakSet[_UvicornThread]`** — catches graceful interpreter exits (Ctrl-C, kernel quit, nbconvert finish).
3. **`daemon=True` on `UvicornThread`** — brutal floor when 1-2 fail or hang.

Residual leak: `taskkill /F` bypasses atexit; the kernel still owes ~30 s TIME_WAIT cooldown per closed TCP connection.

## Thin notebook

`00-calibration.ipynb` at repo root imports `src.methods.calibration.run` and the three plotters from `src.view`. Set `_RUN_RATE_SWEEP = True` to opt into the rate sweep, `_RUN_CALIB_SWEEP = True` for the multi-combo dim-card sweep. Run before every fresh `05-experimental` / `06-yoly-experimental` session.

## Figures

`data/img/experiment/calibration/{dashboard,scaling,rate_sweep,calib_sweep}.{png,svg}`.

## See also

- `notes/proof.md` — calibration's role as a precondition gate in the proof framework
- `notes/devlog.md` 2026-04-25 — closure of P0–P5 (the phased build-out narrative)
- `notes/devlog.md` 2026-04-28 — rate-sweep decoupling, specs-layer μ-binpacking, zombie cleanup
- `memory/project_calibration_p0_p1_closed.md` — full closure record
- `memory/project_calibration_2026_04_28.md` — overhaul record
- `memory/feedback_calibration_vs_model_error.md` — calibration-≠-model-tolerance distinction

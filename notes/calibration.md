# Calibration, Logger Refactor, and Local/Remote Deployment Plan

Living memory + checkpoint log for the multi-phase effort to (a) characterize
the per-host noise floor before each experiment run, (b) rewrite the
`@logger` path to eliminate mid-run disk I/O, and (c) make the experiment
method run against both a single-laptop ("local") and a 3-machine LAN
("remote") deployment.

Keep this file current: every phase below owns a checkpoint row. Mark it
`DONE`, `IN PROGRESS`, or leave it `PENDING`. When you close a phase, append
the resulting numbers / decisions to the **Checkpoint log** at the bottom so
future runs can diff against them.

Pairs with:

- `notes/workflow.md` -- the method-by-method contract this plan feeds into
- `notes/experiment.md` -- the experiment-method design doc
- `notes/operational_analysis.md` -- Denning/Buzen metric definitions
- `notes/devlog.md` -- dated decisions and pivots
- `.claude/skills/develop/async-rate-precision.md` -- async-rate recipe (already live)
- `CLAUDE.md` -- "Async load drivers" section pins the mandatory pieces

## 1. What is the noise floor

The noise floor is the minimum irreducible measurement error the host
introduces even when the system is doing nothing useful: OS scheduling
jitter, timer granularity, memory allocation overhead, background
processes. Measure it **before each experiment run** so we can subtract it
from results and know which variation is real system behaviour versus
instrument noise.

## 2. What to measure

Four baselines (always-on), in this order, plus an optional fifth phase:

1. **Timer resolution** -- how precise the clock actually is.
2. **Scheduling jitter** -- how much the OS interrupts the process.
3. **Loopback latency** -- minimum round-trip with zero service logic.
4. **Empty request overhead** -- what FastAPI costs with an empty handler,
   at increasing concurrency levels.
5. **Rate saturation sweep** (opt-in via `--rate-sweep`) -- the highest
   target arrival rate the full TAS architecture sustains under a
   configured loss-tolerance threshold.

### 2.1 Phase summary

| # | Phase | What it measures | Driver / target | Concurrency | Default (~time) | Output (envelope key) | Used by |
|---|---|---|---|---|---|---|---|
| **1** | timer resolution | Native clock granularity (smallest non-zero `perf_counter_ns()` delta) | In-process loop, no I/O | n/a | 100 000 samples (~1 s) | `timer.{min_ns, median_ns, mean_ns, std_ns, zero_frac}` | Reference only |
| **2** | scheduling jitter | OS scheduler oversleep when asking for a 1 ms `asyncio.sleep` | In-process, no I/O | 1 task | 5 000 samples (~5 s) | `jitter.{mean_us, p50_us, p99_us, max_us, std_us}` | `±jitter.p99_us` uncertainty band on every reported latency |
| **3** | loopback latency | TCP + ASGI + FastAPI `/ping` round-trip, idle host | `httpx → 127.0.0.1:8765/ping` against uvicorn | 1 in-flight (sequential) | 5 000 samples (~10 s, after 500 warmup) | `loopback.{min_us, median_us, p95_us, p99_us, std_us, samples}` | `μ = 1e6 / loopback.median_us`; subtracted as host-floor in every report |
| **4** | empty-handler scaling | How `/ping` response time grows under client-side concurrency | Same uvicorn server as #3 | `n_con_usr ∈ [1, 10, 50, 100, 200, 300, 500, 800, 1000]` (parallel via `asyncio.gather`) | 300 samples per level (~30 s total) | `handler_scaling["<n_con_usr>"].{min_us, median_us, p95_us, p99_us, std_us, samples}` | Per-level L, W, λ arrays for the dim card (θ/σ/η/φ) |
| **5** | rate saturation sweep (opt-in) | Highest sustainable arrival rate at `target_loss_pct ≤ 2.0%` against the **full TAS architecture** | `experiment.run(adp="baseline")` -- 13 microservices, real routing -- driven at deterministic rates | `trials_per_rate=5` per rate in `rates=[10,…,500]` | ~10-15 min (off by default) | `rate_sweep.{rates, trials_per_rate, aggregates, per_trial, calibrated_rate, target_loss_pct, adaptation}` | `calibrated_rate` scalar; gates whether seeded λ values are feasible to drive on this host |

### 2.2 Cumulative noise picture

Each phase is a strict superset of the noise sources of the previous one.
The reporting convention `reported = measured - loopback.median_us +/-
jitter.p99_us` peels back #2+#3 from real experiment latencies, leaving the
application's own behaviour.

| | Clock | Scheduler | TCP/ASGI | Concurrency | Architecture |
|---|:---:|:---:|:---:|:---:|:---:|
| #1 timer | x | | | | |
| #2 jitter | x | x | | | |
| #3 loopback | x | x | x | | |
| #4 handler scaling | x | x | x | x | |
| #5 rate sweep | x | x | x | x | x |

## 3. Reference recipes

These snippets are the intent, not the final placement. They land in
a single `src/methods/calibration.py` during P0 (see plan table below).
Kept here verbatim as the spec the script implements against.

### 3.1 Timer resolution

```python
import time
import numpy as np

samples = []
for _ in range(100_000):
    t1 = time.perf_counter_ns()
    t2 = time.perf_counter_ns()
    delta = t2 - t1
    if delta > 0:  # skip identical reads
        samples.append(delta)

samples = np.array(samples)
print(f"Min tick:    {samples.min()} ns")
print(f"Median tick: {np.median(samples):.1f} ns")
print(f"Mean tick:   {samples.mean():.1f} ns")
print(f"Std dev:     {samples.std():.1f} ns")
```

Pass criterion: on Windows, `min tick < 1000 ns` after `timeBeginPeriod(1)`.
If it reads `15600 ns` the timer-resolution fix is not active. Run this
before and after the fix as a self-test.

### 3.2 Scheduling jitter

```python
import time
import numpy as np

target_ns = 1_000_000  # 1 ms
samples = []

for _ in range(10_000):
    t1 = time.perf_counter_ns()
    time.sleep(0.001)
    t2 = time.perf_counter_ns()
    actual = t2 - t1
    jitter = actual - target_ns
    samples.append(jitter)

samples = np.array(samples)
print(f"Mean jitter:  {samples.mean()/1000:.1f} us")
print(f"Max jitter:   {samples.max()/1000:.1f} us")
print(f"Std dev:      {samples.std()/1000:.1f} us")
print(f"P99 jitter:   {np.percentile(samples, 99)/1000:.1f} us")
```

Pass criterion: P99 jitter under the smallest inter-arrival we drive. At
400 req/s inter-arrival is 2.5 ms; P99 jitter above that corrupts
individual measurements by more than 1x the spacing.

### 3.3 Loopback latency

Requires an empty `/ping` endpoint on the FastAPI app (see 3.4).

```python
import asyncio
import httpx
import numpy as np
import time

async def measure_loopback(n=10_000):
    samples = []
    async with httpx.AsyncClient(base_url="http://127.0.0.1:8000") as client:
        # warmup
        for _ in range(500):
            await client.get("/ping")
        # measure
        for _ in range(n):
            t1 = time.perf_counter_ns()
            await client.get("/ping")
            t2 = time.perf_counter_ns()
            samples.append(t2 - t1)

    samples = np.array(samples)
    print(f"Min loopback:    {samples.min()/1000:.1f} us")
    print(f"Median loopback: {np.median(samples)/1000:.1f} us")
    print(f"P95 loopback:    {np.percentile(samples, 95)/1000:.1f} us")
    print(f"P99 loopback:    {np.percentile(samples, 99)/1000:.1f} us")
    print(f"Std dev:         {samples.std()/1000:.1f} us")

asyncio.run(measure_loopback())
```

Interpretation: this is the irreducible floor. Any measured result below
this in the real experiment is impossible and indicates a measurement
error. Any result above this is real service cost plus noise.

### 3.4 Empty FastAPI handler

```python
@app.get("/ping")
async def ping():
    return {"ok": True}
```

Drive the loopback test against it at concurrency levels `1, 10, 50, 100`
and record how the baseline shifts. That delta is the FastAPI / event-loop
cost before any business logic runs.

### 3.5 Pre-experiment routine (composed)

```python
import time
import numpy as np
import asyncio
import httpx
import ctypes
import json
from datetime import datetime

def set_timer_resolution():
    try:
        ctypes.windll.winmm.timeBeginPeriod(1)
        print("Timer resolution set to 1 ms")
    except AttributeError:
        print("Not Windows -- skipping timer fix")

def measure_timer():
    samples = []
    for _ in range(100_000):
        t1 = time.perf_counter_ns()
        t2 = time.perf_counter_ns()
        d = t2 - t1
        if d > 0:
            samples.append(d)
    s = np.array(samples)
    return {"min_ns": int(s.min()), "median_ns": float(np.median(s)), "std_ns": float(s.std())}

def measure_jitter():
    samples = []
    target = 1_000_000
    for _ in range(5_000):
        t1 = time.perf_counter_ns()
        time.sleep(0.001)
        t2 = time.perf_counter_ns()
        samples.append((t2 - t1) - target)
    s = np.array(samples)
    return {"mean_us": float(s.mean() / 1000), "p99_us": float(np.percentile(s, 99) / 1000), "max_us": float(s.max() / 1000)}

async def measure_loopback():
    samples = []
    async with httpx.AsyncClient(base_url="http://127.0.0.1:8000") as client:
        for _ in range(200):
            await client.get("/ping")
        for _ in range(5_000):
            t1 = time.perf_counter_ns()
            await client.get("/ping")
            t2 = time.perf_counter_ns()
            samples.append(t2 - t1)
    s = np.array(samples)
    return {"min_us": float(s.min() / 1000), "median_us": float(np.median(s) / 1000), "p99_us": float(np.percentile(s, 99) / 1000), "std_us": float(s.std() / 1000)}

async def run_baseline():
    set_timer_resolution()
    timer = measure_timer()
    jitter = measure_jitter()
    loopback = await measure_loopback()
    baseline = {
        "timestamp": datetime.now().isoformat(),
        "timer": timer,
        "jitter": jitter,
        "loopback": loopback,
    }
    fname = f"baseline_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    with open(fname, "w") as f:
        json.dump(baseline, f, indent=2)
    return baseline

asyncio.run(run_baseline())
```

Final placement: output lands under
`data/results/experiment/calibration/<host>_<YYYYMMDD_HHMMSS>.json`. Host
name comes from `socket.gethostname()` so local vs remote machines are
distinguishable without editing the script.

## 4. How to apply the baseline to results

Once the baseline JSON exists, subtract the loopback median from every
measured latency and report the jitter P99 as the measurement uncertainty:

```
Measured latency: 8.3 ms
Loopback floor: - 0.4 ms
Jitter P99:     +/- 2.1 ms
Reported:         7.9 ms +/- 2.1 ms
```

This is the step that turns raw timing into scientifically defensible
results. Record the baseline JSON alongside every run in
`data/results/experiment/calibration/` and reference it by timestamp in the
run envelope (`baseline_ref`).

## 5. Phasing at a glance

| Phase | Theme | Why first | Depends on |
|---|---|---|---|
| **P0** | Baseline noise-floor harness | Need a ruler before measuring anything else | -- |
| **P1** | Logger refactor (append + periodic drain) | Raises the ceiling; land before network introduces new variance | P0 |
| **P2** | Local re-baseline with new logger | Lock in the new floor on single-machine config | P1 |
| **P3** | Remote-ready packaging (config + deploy) | Make services location-agnostic without running remote yet | P1 |
| **P4** | LAN deployment (3 machines) | Real isolation; characterize network jitter separately | P3 |
| **P5** | Comparison + case-study integration | Roll results into `07-comparison.ipynb` | P2, P4 |

## 6. Detailed plan

Status column: `PENDING`, `IN PROGRESS`, `DONE`, `BLOCKED`. Update it as
work progresses. Effort is a rough order-of-magnitude estimate; treat as
guidance, not a deadline.

| # | Step | Deliverable | Checkpoint (pass = proceed) | Risk | Effort | Status |
|---|---|---|---|---|---|---|
| P0.1 | `src/methods/calibration.py` (host harness) -- one-shot routine covering timer (3.1), jitter (3.2), loopback (3.3), empty-handler scaling (3.4); uses `timeBeginPeriod(1)` via ctypes on Windows; saves per-host JSON; subcommand / flag group handles this block | `data/results/experiment/calibration/<host>_<date>.json` + `host_profile.json` (OS, CPU, RAM, thermals snapshot) | Timer min tick < 1500 ns; idle CPU < 15 %; free RAM > 2 GB before run; loopback p99 under 2 ms | Laptop thermals / background apps skew results -- document "airplane mode" profile | 0.5 d | DONE |
| P0.2 | `src/methods/calibration.py` (rate sweep) -- drives experiment-method probes at the configured rate ladder (default 100/200/300/400/500 req/s x 5 trials); reports `client_effective_rate` vs target, entry-service `lambda` observed; opt-in via `--rate-sweep` or `skip_rate_sweep=False`; persisted under the existing calibration JSON envelope's `rate_sweep` key | `rate_sweep` block merged into `data/results/experiment/calibration/<host>_<date>.json` | At each rate: `\|effective - target\| / target` under `target_loss_pct` across all trials, OR a documented ceiling rate logged in devlog | Ceiling below 400 req/s is a finding, not a failure; log it | 0.5 d | DONE |
| P0.3 | Document calibration as a pre-run gate in `notes/workflow.md`; add CLI flag `--skip-calibration` (with warning) to `src/methods/experiment.py::main` | Workflow doc + CLI gate | `python -m src.methods.experiment` (no flags) fails fast with a clear message if a recent calibration JSON is not present | Adds minutes per run -- acceptable; `--skip-calibration` exists for iteration | 0.25 d | DONE |
| P0.4 | First calibration on current laptop with current code | `data/results/experiment/calibration/laptop_<date>_before.json` + devlog entry | Numbers recorded; ceiling rate documented | None -- this is the baseline snapshot | 0.25 d | DONE (pre-refactor: `DESKTOP-INKGBK6_20260423_181646.json`; clean re-bench: `DESKTOP-INKGBK6_20260423_213159.json`; numbers locked in Checkpoint log) |
| P1.1 | Bounded per-service `deque(maxlen=N)` in `ServiceContext`; `@logger` appends rows in `LOG_COLUMNS` order; remove any mid-run disk writes | `src/experiment/services/base.py` + test proving append is O(1) and does no I/O | `tests/experiment/services/test_base.py` green; no disk I/O during the probe window | Wrong column order silently corrupts CSVs -- guard with schema test | 0.5 d | DONE (Option 2: dict rows kept, tuple optimisation deferred) |
| P1.2 | `ServiceContext.drain() -> List[Dict]` with atomic swap; `dropped_count` counter; overflow unit test | Updated `base.py` + test | Drain is O(1); overflow increments counter; counter asserted zero at end of happy-path test | Silent data loss if `maxlen` too small -- surface `dropped_count` in run envelope | 0.25 d | DONE |
| P1.3 | `ExperimentLauncher.drain_all()` walks services, concatenates rows into a launcher-side list; keep `flush_logs` as the single final disk write (overwrite mode, per CLAUDE.md) | `src/methods/experiment.py` | Exactly one CSV write per service per run, after probe-loop ends | `flush_logs` accidentally called mid-run re-enables the old bug -- add test that fails if `flush_logs` runs while probe is active | 0.25 d | DEFERRED (current pipeline already does single-flush-at-end; `drain()` exposed for future between-probe use) |
| P1.4 | `ClientSimulator._probe_at_rate` calls `await launcher.drain_all()` **between** probe steps, not inside; client holds accumulated list until end | `src/experiment/client.py` | `calibration.py --rate-sweep` shows no disk I/O during a probe window | Drain between probes eats into ramp-transition time -- keep it async + bounded | 0.5 d | DEFERRED (paired with P1.3) |
| P1.5 | Swap `time.perf_counter()` -> `time.perf_counter_ns()` in hot path; convert ns -> float seconds only at CSV write time | Edits across `services/instruments.py`, `services/base.py`, `experiment.py` metric builders | All existing tests green after fix-ups in `_build_svc_df_from_logs` | One missed `/ 1e9` corrupts downstream metrics silently -- round-trip test: seconds column == ns column / 1e9 to 9 decimals | 0.5 d | DONE (`@logger` + `mark_admit_time` switched to `perf_counter_ns`; `_NS_TO_S = 1e9` conversion at row-build time keeps the CSV schema unchanged) |
| P1.6 | Bump schema tests in `tests/experiment/test_logger_integration.py` + `tests/experiment/services/test_base.py` to cover the new bounded buffer + drop counter + drain helper | Updated tests | `pytest tests/experiment/ -v` green; coverage unchanged or up | Routine test churn | 0.25 d | DONE (3 new `TestServiceContextLogBuffer` cases; existing 41 experiment + 25 method-experiment tests still green) |
| P2.1 | Re-run P0 calibration against refactored code on the same laptop | `data/results/experiment/calibration/laptop_<date>_after.json` + devlog delta | Measured ceiling > previous ceiling OR p99 jitter demonstrably lower | If no lift, logger was not the bottleneck (expected per `feedback_measure_before_assume.md`); triage with `calibration.py --rate-sweep` | 0.25 d | DONE (5-trial baseline bench on post-P1 code; `log_drop_counts == {}` every trial; `eff_rate` mean 6.82 req/s, range 6.49-7.26, ~6 % spread; default config is far below the saturation regime so performance lift is NOT decided by this bench -- saturation-regime A/B deferred) |
| P2.2 | Lock P2 results into `notes/devlog.md` with before/after table | Devlog entry | Entry includes host_profile, ceilings, interpretation | None | 0.1 d | DONE |
| P3.1 | Extract host/port for client, composite, atomic services into `data/config/method/experiment.json` (currently hard-coded localhost); loader reads them in `src/experiment/networks.py` | Config-driven endpoints | Single-machine run still works when endpoints = `127.0.0.1`; unit test covers remote-style endpoints without starting real servers | JSON key renames break wire schema -- CLAUDE.md rule: JSON keys stay, only Python-side renames allowed | 0.5 d | PENDING |
| P3.2 | Add `deployment: local \| remote` switch to `experiment.json`; `local` spawns in-process as today, `remote` assumes services already running | Launcher branches on mode | `local` mode byte-identical to pre-P3 output; `remote` mode fails with a clear message if endpoint unreachable | Subtle behaviour drift between modes -- pin with integration test that runs both against loopback and diffs results | 0.5 d | PENDING |
| P3.3 | `src/scripts/launch_composite.py` and `launch_atomic.py` read the same `experiment.json`; each pins `timeBeginPeriod(1)` + CPU affinity if on Windows | Scripts + README snippet in `notes/quickstart.md` | Can start one composite + three atomics manually on one host and drive from client on same host | Launch-script drift vs in-process launcher -- share code path via `ServiceContext.from_config` | 0.5 d | PENDING |
| P4.1 | Network characterization: `ping -n 1000` + no-op HTTP GET storm between the 3 machines on wired LAN; record p50/p99/p99.9 latency | `data/results/experiment/calibration/lan_<date>.json` | p99 LAN latency < 2 ms; p99.9 documented; Wi-Fi explicitly ruled out | Wi-Fi used by mistake inflates all remote numbers -- add check that measures both and refuses Wi-Fi | 0.5 d | PENDING |
| P4.2 | Deploy: machine A = client, machine B = composite, machine C = atomics; sync repo + venv; start services with P3.3 scripts; run `experiment.json` in `remote` mode | Remote run output + CSVs at all expected paths | Same 10-column LOG_COLUMNS schema; `client_effective_rate` == entry-service `lambda` within LAN-jitter band | Clock skew between machines skews cross-host timestamp math -- keep timing within a single host's `perf_counter_ns` clock; only req_id crosses hosts | 1 d | PENDING |
| P4.3 | Re-run calibration in remote mode; compare to P2 local numbers | Remote calibration JSON + devlog delta | Remote ceiling >= local ceiling; LAN jitter subtracted cleanly from response times | Firewall / Defender blocks inter-host traffic -- allowlist ports before benchmarking | 0.5 d | PENDING |
| P4.4 | Document local vs remote numbers side-by-side in `notes/devlog.md`; decide canonical case-study configuration | Devlog decision record | Decision logged with rationale (isolation > convenience for final numbers) | Picking the wrong canonical config misrepresents TAS -- document the criterion | 0.25 d | PENDING |
| P5.1 | Feed both local and remote results into `07-comparison.ipynb`; add deployment column to deltas table | Updated comparison notebook | R1/R2/R3 verdicts stable across deployment modes OR divergence explained | Divergence might invalidate numbers -- document as a finding, not hide it | 0.5 d | PENDING |
| P5.2 | Final sweep: devlog summary, `notes/workflow.md` updates, CLAUDE.md additions (noise-floor gate, local/remote config, logger refactor) | Docs in sync | `/review` on branch passes; no orphan references to old behaviour | Doc drift -- single-PR bundling keeps it consistent | 0.25 d | PENDING |

### Totals

- P0: ~1.25 d
- P1: ~2.25 d
- P2: ~0.35 d
- P3: ~1.5 d
- P4: ~2.25 d
- P5: ~0.75 d
- **Total: ~8.5 working days** assuming no blockers (firewall, thermals, missing machines).

### Recommended execution order

P0 -> P1 -> P2 (**stop here and confirm local ceiling lifted**) -> P3 -> P4 -> P5.

Do not start P3 until P2 has proven the logger refactor was worthwhile. If
P2 shows no lift, the logger was not the bottleneck (per
`feedback_measure_before_assume.md` in memory), and P3/P4 priorities should
pivot toward investigating the actual bottleneck (OS scheduler, HTTP stack,
or service saturation) before sinking effort into remote deployment.

## 7. Cross-cutting risks

| Risk | Mitigation |
|---|---|
| Laptop thermal throttling distorts calibration | Include `psutil` CPU-temp snapshot in `host_profile.json`; re-run if delta > 10 C between trials. Use charger + flat surface; document run conditions. |
| `maxlen` sizing too small causes silent drops | Hard-assert `_dropped_count == 0` at end of every run; surface in the run envelope; CI fails the test run if ever > 0. |
| Perf-counter unit mix-up (ns vs s) | Dedicated round-trip unit test: `ns / 1e9 == seconds` to 9 decimals on the full CSV. |
| Clock skew across 3 machines (P4) | Restrict timing math to within one host; cross-host data is request-id flow only. Do NOT subtract `host_A.start_ts` from `host_B.end_ts`. |
| Wire-schema changes sneak in via refactor | CLAUDE.md rule already pinned: JSON config keys + CSV column names are off-limits. Enforce via schema tests. |
| Methodological shift (canonical config = local vs remote) misrepresents the case study | Document both in the comparison notebook; pick one as canonical with a stated rationale; keep the other as appendix. |

## 8. Artifact layout

Deployment-mode split (mirrors `data/img/experiment/` and
`data/results/experiment/`, created 2026-04-23):

```
data/img/experiment/         data/results/experiment/
  calibration/                 calibration/
  local/<adaptation>/          local/<adaptation>/<profile>/
  remote/<adaptation>/         remote/<adaptation>/<profile>/
```

- `calibration/` holds per-host noise-floor JSONs -- no adaptation axis.
- `local/` and `remote/` each carry the full baseline / s1 / s2 /
  aggregate matrix.
- Existing single-laptop results were moved under `local/` on 2026-04-23;
  no result files moved across hosts, only re-parented.
- `src/io` writers and `src/view` plotters still emit to the pre-split
  paths. Wiring the deployment axis into those writers is step P3.1
  below.

## 9. Checkpoint log

Append a dated entry every time a phase moves. One bullet per phase
transition; short and concrete. Numbers live here; prose belongs in
`notes/devlog.md`.

### 2026-04-23

- Plan drafted and entered this file. Directory split for `data/img/experiment/`
  and `data/results/experiment/` applied: `calibration/`, `local/`, `remote/`
  added; existing adaptation results moved under `local/`; `.gitkeep` markers
  placed on every new empty directory.
- P0.1 **DONE**: `src/methods/calibration.py` shipped on
  `DESKTOP-INKGBK6` (Windows 11, Python 3.12.10, 16 cores, 64 GB RAM).
  After the P1 cleanup + ProactorEventLoop fix + GC sweeps, a clean
  re-bench (apps closed) was saved at
  `data/results/experiment/calibration/DESKTOP-INKGBK6_20260423_213159.json`.
  Headline numbers from the clean baseline:
  - **Timer resolution**: min 100 ns, median 100 ns, mean 125 ns,
    std 392 ns -- `timeBeginPeriod(1)` is effective; sub-microsecond
    clock floor.
  - **Scheduling jitter**: mean 663 us, p50 634 us, p99 1357 us
    (1.36 ms), max 1.98 ms -- measurement uncertainty for any
    inter-arrival coarser than ~1.4 ms.
  - **Idle loopback**: min 1.06 ms, median 1.29 ms, p95 1.81 ms,
    p99 2.21 ms -- every measured service latency on this host should
    be reported as `value - 1.29 ms +/- 1.36 ms`. Results below
    1.29 ms are instrument errors, not real services.
  - **Handler scaling (key finding)**: empty `/ping` median latency
    grows from 1.5 ms at c=1 -> 11 ms at c=10 -> 63 ms at c=50 ->
    127 ms at c=100 -> 259 ms at c=200 -> 783 ms at c=500 -> 972 ms
    at c=1000 -> 3.6 s at c=5000 -> 21.3 s at c=8000 -> 29.6 s at
    c=10000. Empty handler, zero business logic. Even at c=10 a single
    uvicorn worker is ~7x slower than c=1 -- this is the FastAPI /
    event-loop saturation signature. The TAS prototype's ~180 req/s
    degradation point sits exactly where Little's-law puts 1-2
    requests in flight per hop on a depth-4 service chain, so the
    bottleneck is event-loop queueing inside each service, NOT the
    client driver or the logger.
  - **Run-to-run noise (apps running vs apps closed)**: the same probe
    on the same host with background apps active showed loopback
    median = 1.73 ms (vs 1.29 ms clean) and timer std = 714 ns (vs
    392 ns clean). Document run conditions before drawing conclusions
    from absolute numbers; the log-log curve shape is hardware-bound
    and stable across both runs.
- Next: P0.2 (rate sweep block in the same `calibration.py`, replacing
  the standalone `demo_rate.py` probes so host-floor + rate-saturation
  characterization land in one JSON envelope).

### 2026-04-24

- P0.2 **DONE**: rate-sweep probe folded into `calibration.py`.
  Changes:
  - `data/config/method/calibration.json` grew `skip_rate_sweep`
    (default `true`) + a `rate_sweep` block (`rates`, `trials_per_rate`,
    `min_samples_per_kind`, `max_probe_window_s`, cascade tunables,
    `target_loss_pct`, `entry_service`).
  - `src/methods/calibration.py::run_rate_sweep(**kwargs)` ported the
    sweep + calibrate logic from the old `demo_rate.py`. Each trial
    calls `experiment.run(skip_calibration=True, verbose=False, ...)`
    to avoid gate recursion. Lazy imports keep the calibration
    module-top import surface free of `src.methods.experiment`
    (confirmed: `src.methods.experiment not in sys.modules` after
    `import src.methods.calibration`).
  - `run()` + CLI grew matching flags: `--rate-sweep` (opt-in),
    `--rate-sweep-rates`, `--rate-sweep-adp`, `--rate-sweep-trials`,
    `--rate-sweep-target-loss`, `--rate-sweep-with-lambda-z`. Results
    land under the envelope's `rate_sweep` key; `_print_summary` grew a
    per-rate table when the block is present.
  - `src/io/tooling.py` exposed `rate_sweep_calibrated_rate()` and
    `rate_sweep_loss_at()`; re-exported from `src/io/__init__.py`. (This
    module was renamed from `src/io/calibration.py` to `tooling.py` for
    clarity against the other `calibration.py` files.)
  - `src/view/characterization.py` grew `plot_calib_rate_sweep()`
    (effective vs target on the primary axis with min/max error bars +
    identity reference, mean loss % on the secondary axis,
    calibrated-rate vertical marker, target-loss dashed line).
    Re-exported alphabetically. (This module was renamed from
    `src/view/calibration.py` to `characterization.py` in the same
    pass.)
  - `00-calibration.ipynb` setup cell has a `_RUN_RATE_SWEEP = False`
    toggle and a new "7. Rate saturation (optional)" section (renumber:
    old "7. Apply the baseline" became "8. ..."). The new section shows
    the aggregate table + calibrated rate + rate-sweep figure when the
    block is present.
  - `src/scripts/demo_rate.py` deleted; references updated in CLAUDE.md,
    `.claude/skills/develop/async-rate-precision.md`, memory
    (`feedback_measure_before_assume.md`,
    `project_camara_rate_rescaling_pending.md`,
    `project_windows_asyncio_precision.md`),
    `notes/devlog.md`, and `data/config/profile/dflt.json` (the
    `TODO_revisit_rates` narrative).
  - Tests: 4 new `TestRateSweepAccessors` under
    `tests/io/test_calibration.py` + 6 new `TestRateSweepHelpers` /
    `TestRunRateSweepOrchestration` under
    `tests/scripts/test_calibration.py`. All 13 calibration-side tests
    pass. Existing 25 experiment-method tests unaffected.
- P2 **stop-gate result (safety pass; saturation-regime test deferred)**:
  ran the experiment method 5 times against `adp=baseline` with default
  config on the post-P1 code. Every trial completed cleanly
  (`stopped=schedule_complete`, `sat_rate=null`), `log_drop_counts == {}`
  on every trial (the bounded-deque invariant holds at this load),
  and the numbers were tight: mean `client_effective_rate = 6.82 req/s`
  (range 6.49 - 7.26, ~6 % spread), mean `W_net = 17.5 ms` (with a
  visible warm-in trend from 31.2 ms on trial 0 down to 9.8 ms on
  trial 4 as background activity settled), mean wall time 173.7 s per
  trial (range 173.2 - 173.9 s, ~0.4 % spread). Conclusion: P1's
  **safety properties are confirmed** (no overflow, no exceptions,
  no envelope corruption, ns-precision pipeline produces stable
  metrics). P1's **performance impact is NOT decided** by this bench
  -- the default ramp tops out around 7 req/s, far below the ~180
  req/s degradation point the calibration found. To answer "did P1
  lift the experiment ceiling" we would need to drive rates into the
  saturation regime (e.g. `rates=[100, 150, 200, 250, 300, 400]`)
  and A/B against the pre-P1 numbers. The calibration data already
  suggests event-loop queueing is the dominant bottleneck regardless
  of logger overhead, so that bench's cost/benefit is questionable
  -- defer until a use case demands it.
- P1 **scoped DONE (Option 2)**: `SvcCtx.log` is now a bounded
  `collections.deque(maxlen=500_000)`; `@logger` calls a new
  `record_row()` helper that increments `dropped_count` on overflow.
  `mark_admit_time` + `@logger` use `time.perf_counter_ns()` in the hot
  path and convert via `_NS_TO_S = 1e9` only when populating the dict
  row, so the CSV schema is byte-identical and `_build_svc_df_from_logs`
  is unchanged. Added `SvcCtx.drain()` (atomic swap) for future
  between-probe drains; `ExperimentLauncher.collect_drop_counts()`
  surfaces overflow per service; the run envelope now carries
  `log_drop_counts` and `run()` prints a warning when non-empty. Three
  new `TestServiceContextLogBuffer` cases pass; 41 experiment + 25
  method-experiment tests still green. Tuple-row optimisation
  (P1.1 ideal) deferred until a measurement shows dict allocation is
  the bottleneck -- the calibration data already suggests event-loop
  queueing dominates at the levels where TAS degrades, not logger
  overhead.
- P0.3 **DONE**: pre-run calibration gate + baseline hook landed in
  `src/methods/experiment.py` via a new loader in `src/io/tooling.py`
  (`find_latest_calibration` / `load_latest_calibration` /
  `calibration_floor_us` / `calibration_band_us` /
  `calibration_age_hours`). `run()` now accepts
  `skip_calibration: bool = False` and `verbose: bool = True`; the CLI
  grows `--skip-calibration`. Every result envelope (in-memory and
  on-disk) carries a `baseline` block with `baseline_ref`,
  `loopback_median_us`, `jitter_p99_us`, `age_hours`, `applied`. Warns
  when the calibration is older than 24 h. Four new tests under
  `tests/io/test_calibration.py::TestCalibrationLoader` and three under
  `tests/methods/test_experiment.py::TestCalibrationGate` all green;
  existing 25 experiment tests unchanged after plumbing
  `skip_calibration=True` through every fixture.

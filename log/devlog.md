# Devlog — CS-01 TAS

Running log of design decisions, pivots, and open questions for the Tele Assistance System case study. Append only; newest entry on top.

## 2026-05-09 — Experimental stage 3 closed (runtime variants) + audit pass

**Decision.** Close stage 3 of the `src/experimental/` rebuild ([log/prototype-refactor-plan.md](log/prototype-refactor-plan.md)) and run an audit pass over the new code.

**What landed (stage 3).** Six modules under [src/experimental/prototype/runtime/](src/experimental/prototype/runtime/):

- `server.py`: `ServerAdapter` ABC + `FastAPIAdapter` / `FlaskAdapter` + `Handler` protocol + `make_server_adapter` factory + `FlaskProcess` / `ManagedProcess` type aliases.
- `uvicorn_process.py` / `waitress_process.py` / `gunicorn_process.py`: `mp.spawn` process spawners, identical surface (`start` / `wait_ready` / `shutdown` / `is_alive`). Each registers in a module-level `WeakSet` + `atexit` hook for crash-path zombie cleanup. `GunicornProcess` raises on Windows pointing at `WaitressProcess`; gunicorn import gated by `try / except ImportError` (POSIX-only).
- `os_timer.py`: `windows_timer_resolution` ctxmgr (winmm wrapper, no-op on POSIX).
- `async_loop.py`: `run_async_safe` (Jupyter-safe sync entry); `CoroFactory: TypeAlias = Callable[[], Coroutine[Any, Any, Any]]`.
- `config.py`: loader for `data/config/method/experimental.json::server.{uvicorn,waitress,gunicorn}` runtime tuning blocks.

**Test surface.** [tests/experimental/prototype/runtime/](tests/experimental/prototype/runtime/) mirrors the source 1:1; 50 tests, 90% coverage on the runtime package. Linux-only spawn paths exercised on Windows by mocking `multiprocessing.get_context` + `httpx.get`. Shared helpers added at [tests/utils/exp/apps.py](tests/utils/exp/apps.py) (FastAPI + Flask `/healthz` factories, picklable across `mp.spawn`) and a new [tests/utils/exp/ports.py](tests/utils/exp/ports.py) (`free_port()` + `PORT_MOCK = 9042` sentinel).

**Demo.** [tests/demo/runtime.py](tests/demo/runtime.py): `python -m tests.demo.runtime` brings up FastAPI (uvicorn) + Flask (waitress) side-by-side on free localhost ports, hits `/healthz` on each over real TCP, prints responses, tears down.

**Deps pinned.** `flask==3.1.3`, `waitress==3.0.2`, `gunicorn==23.0.0; sys_platform != "win32"`.

**Audit pass — what changed.**

- Constants `_DFLT_*` privatised across all three spawners; constructors take `ready_timeout_s` / `terminate_grace_s` / `kill_grace_s` kwargs sourced from `experimental.json::server.<spawner>.*`.
- `ServerAdapter.wait_ready(timeout_s=None)` now propagates to the spawner's configured `_ready_timeout_s` instead of hard-coding 10.0.
- gunicorn import refactor: `if sys.platform != "win32":` block replaced with standard `try / except ImportError` optional-dep idiom; `_GunicornDriver` (renamed from `_GunicornApp`) lives at module scope unconditionally.
- Pyright literal-narrowing fix: platform check delegated to `_check_linux_or_raise()` so `__init__` body stays reachable.
- Dead code removed: vestigial `from ...async_loop import CoroFactory` re-export in `uvicorn_process.py`; `AttributeError` from `os_timer.py` exception list (cannot fire after `sys.platform` guard); literal-narrowed `if sys.platform == "win32":` branch in `async_loop._worker_run_coro` (Python 3.8+ `WindowsProactorEventLoopPolicy` already returns the right loop class).
- Test cleanup: `test_flask_picks_gunicorn` deleted (duplicate of `test_make_flask_gunicorn`); vacuous `assert GunicornProcess is not None` deleted; nested `def`s in `test_async_loop.py` lifted to module scope; lazy imports moved to module top in `test_uvicorn_process.py` + `test_waitress_process.py`; `port=0` / `port=1` sentinel values replaced with 9042+ via `PORT_MOCK` and `free_port()`; `tests/experimental/prototype/runtime/conftest.py` deleted (only one `conftest.py` per `tests/experimental/`); test method names shortened across the runtime suite.
- Module + class + method docstrings rewritten across the runtime package + test mirror: shorter, plain-language, less code-symbol density.
- Atexit hook + `_LIVE_PROCESSES` registry inline-commented across all three spawners (one-liner `# Crash-path safety net.` and `# Live spawners; atexit cleans these up on exit.`).

**Stop-gate verification.**

1. `pytest tests/experimental/` -> 135 passed (50 new under `runtime/`).
2. `pytest tests/` -> 308 passed (full surviving suite + new runtime tests).
3. `python -m tests.demo.{log_format,client,runtime}` all run cleanly.
4. `grep -r "src\.experiment\|src\.calibration\|MockTransport" src/` -> zero hits (transport mock allowed only in `tests/`).
5. Coverage: 95% on `src/experimental/`; 90% on `src/experimental/prototype/runtime/` specifically. Above the 80% gate.

**Conventions captured elsewhere this turn.**

- Memory: [project_experimental_stage_3_closed_2026_05_08.md](C:/Users/Felipe/.claude/projects/c--Users-Felipe-OneDrive-Documents-GitHub-DASA-Design-PyDASA-CS1-TAS/memory/project_experimental_stage_3_closed_2026_05_08.md) records the stage-3 closure + naming pins (mocking pattern for Linux-only spawn, app-factory pickling rule).
- New rule pinned: app factories that cross `mp.spawn` boundaries MUST be top-level functions (closures + lambdas don't survive Windows pickle).

**Next steps.**

- Stage 4: calibration ping/echo (`prototype/calibration/{vernier,hoststats,rate,envelope,gate}.py`); `tests/demo/vernier.py`; first end-to-end run of the apparatus through a 1-service mesh.
- Stage 5: deployment options (`localhost` / `multiprocess` / `remote`); calibration reruns under all three.

## 2026-05-07 — `notes/case-study.md` rebuilt as full ACS 6-section reconstruction; SVG-crop pattern locked

**Decision.** Replace the ad-hoc 129-line `notes/case-study.md` with a clean ACS 6-section reconstruction merged from `__OLD__/notes/context.md` (long-form draft) and `__OLD__/notes/objective.md` (concise version). Lock down an inline-SVG figure-embedding pattern that survives VS Code markdown preview's HTML sanitizer.

**What was added (case-study.md).**

- Six sections: `1. Summary`, `2. Technical Specifications`, `3. Architectural Reconstruction`, `4. Limits`, `5. Insights`, `6. Design Notes`, plus `7. References`.
- `Table CS1.1. *TAS* case specification.` absorbs the prose front matter (Source documents, Methodology, Status, Scope) into table rows alongside the existing identity rows.
- Numbered headings: `## 1.` … `## 7.` for H2; lowercase Roman `### i.` … `### x.` for H3.
- Short identifiers: `RQ-CS1.k` collapsed to `RQ.k`, `ADR-CS1-XX` collapsed to `ADR.XX` (the whole note is CS-1; the infix repeated context).
- Acronym first-use expansions: `ACS`, `QA`, `MAPE-K` (Monitor-Analyse-Plan-Execute-Knowledge), `STA` (stochastic-timed-automata), `SOA` (Service-Oriented Architecture), `PCA` (Principal Component Analysis), `RSEM` (relative standard error of the mean), `ADR` (Architectural Decision Record).
- Stripped: MATI / `[11]` references, in-repo path pointers (`assets/docs/CS/N1/`, `.claude/skills/...`, `src/methods/<method>.py + 0N-<method>.ipynb`), and DASA / methodology-token mentions.
- Cross-source inconsistency table preserved verbatim from `__OLD__/notes/context.md` (14 rows, then 13 after dropping the [11]-only metric-count row).

**What was added (SVG figure crop).** Each of the four reconstruction figures (CS1.1-CS1.4) is wrapped in:

```html
<figure style="margin:0">
<svg version="1.1" viewBox="0 0 W H" width="100%" preserveAspectRatio="xMinYMin meet" xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink" role="img" aria-label="...">
<clipPath id="clip_id"><path d="M0 0hWvHH0z"/></clipPath>
<g clip-path="url(#clip_id)"><image xlink:href="../assets/img/cs1/<file>.svg" width="ORIG_W" height="ORIG_H"/></g>
</svg>
</figure>
```

Per-figure crops in place after iterative tuning:

| Figure | viewBox (W × H) | Inner image (W × H) | Right crop |
| ------ | ----------------:| --------------------:| ----------:|
| CS1.1 context     | 2087 × 1456 | 2940 × 1456 | 29 % |
| CS1.2 workflow    | 2697 × 2036 | 3210 × 2036 | 16 % |
| CS1.3 services    | 2771 × 1698 | 3379 × 1698 | 18 % |
| CS1.4 adaptability | 1613 × 1380 | 2407 × 1380 | 33 % |

The five scenario figures (CS1.5a-e) keep plain `![alt](path)` markdown.

**Why this SVG pattern.** VS Code's markdown preview is the publishing target. Three patterns were tried and rejected before this one stuck:

1. `<div style="overflow:hidden;line-height:0">` + `<img style="width:150%;margin:0 -50% 0 0">`. The CSS clip is silently sanitized; the image renders at full size with no crop.
2. `<figure style="overflow:hidden">` + same `<img>` styles. Same outcome; the sanitizer strips the wrapper's clipping CSS regardless of element type.
3. Bare inline `<svg viewBox=...>` with `<image href=...>` inside. The markdown parser doesn't recognise `<svg>` in its HTML-block whitelist, so the markup renders as code text.

The working pattern needs three things together: a `<figure>` opener (recognised by markdown-it as block HTML), a fully-namespaced `<svg version="1.1" xmlns="..." xmlns:xlink="...">`, and a `<clipPath>` + `<g clip-path="url(#...)">` wrapping an `<image xlink:href="...">` reference. `viewBox` alone is not enough; the explicit `<clipPath>` is what survives the sanitizer.

**Conventions captured elsewhere this turn.**

- `.claude/skills/write/arch-case-study.md` extended with three new lessons (folded identity table, numbered headings + lowercase-Roman subsections, short identifiers when the case is unambiguous) and a new "Embedding SVG figures" subsection codifying the figure-clipPath pattern.
- `CLAUDE.md` gained a short "Markdown Figure Embedding" pointer paragraph.

**Next steps.**

- Apply the same numbered-section + identity-table conventions to the CS-2 IoT-SDP case-study note in the sibling repo.
- If `notes/procedure.md` and `notes/prototype.md` (currently 1-byte stubs) gain content, mirror the conventions here.
- Verify on the GitHub-rendered preview (not just VS Code) that the inline-SVG-with-clipPath pattern still renders cropped; GitHub's sanitizer may have different rules.



---

## 2026-05-06 — Cleaning sweep: experiment / calibration build retired into `__OLD__/`

Cross-cutting archive sweep that clears the slate before the next major refactor (the new software-architecture experiment). Plan-of-record at [`log/cleaning.md`](cleaning.md); memory entry at [`memory/project_cleaning_sweep_2026_05_06.md`](../../C:/Users/Felipe/.claude/projects/c--Users-Felipe-OneDrive-Documents-GitHub-DASA-Design-PyDASA-CS1-TAS/memory/project_cleaning_sweep_2026_05_06.md).

**Phase 1 — archive sweep (filesystem-only; `__OLD__/` is gitignored):**

- **Notebooks**: `00-calibration.ipynb`, `05-experimental.ipynb` → `__OLD__/`. Surviving root notebooks: `01-04`.
- **Source**: `src/{calibration,experiment,scripts}/`, `src/methods/{calibration,experiment}.py`, `src/dimensional/{dasa_sweep,dasaprof}.py`, `src/io/tooling.py`, `src/view/characterization.py` → `__OLD__/`. Fresh `__init__.py` written for `src/{methods,dimensional,io}/` (drop archived re-exports). `src/view/__init__.py` edited in place to drop the three `plot_calib_*` re-exports.
- **Tests**: `tests/{calibration,experiment,scripts,demos}/`, `tests/methods/test_{calibration,experiment}.py`, `tests/dimensional/test_{dasa_sweep,dasaprof}.py`, `tests/io/test_tooling.py`, `tests/utils/helpers.py` → `__OLD__/`.
- **Notes**: 7 files (`calibration.md`, `commands.md`, `prototype.md`, `prototype-constraints.md`, `prototype-v2.md`, `soa-refactor.md`, `workflow.md`) → `__OLD__/notes/`. `notes/devlog.md` → `log/devlog.md` (true move; this file).
- **Data**: `data/config/method/{experiment,calibration}.json`, `data/results/{experiment,calibration}/`, `data/img/experiment/` → `__OLD__/`.
- **`pyproject.toml`**: dropped the orphan `live_mesh` pytest marker (every consumer archived).
- **Stop-gate**: `pytest tests/ -q` = **180 passed in 209 s** on the surviving subset.

**Phase 2 — reorganise surviving surface:**

- **`README.md`** rewritten short (~58 lines, was 262) by folding `notes/SUMMARY.md` + `notes/quickstart.md` (both deleted, content carried forward).
- **`notes/case-study.md`** new (~129 lines) by folding `notes/objective.md` + `notes/context.md` (both deleted, content carried forward; cross-source inconsistency table left at `__OLD__/notes/context.md`).
- **`notes/procedure.md`** + **`notes/prototype.md`** scaffolded as design-doc skeletons for the new build.
- **`CLAUDE.md`** rewritten leaner (213 lines, was huge): kept style / coding / notebook / view / testing / commit conventions + PyDASA notes + Migration-from-`__OLD__/` section; dropped calibration / experiment / `dpl` / scripts / async-ctxmgr blocks.
- **`memory/MEMORY.md`** index updated with the cleaning entry on top + a one-line warning that older entries reference paths now under `__OLD__/`.
- **`src/experimental/`** (`__init__.py` + empty `procedure/` + `prototype/`) is the new build's scaffold; left in place untouched.

**Decisions resolved during the sweep** (full table in `log/cleaning.md`):

- `data/config/method/calibration.json` archived alongside `experiment.json` (symmetric with `src/methods/calibration.py`).
- `assets/docs/architecture_experimentation.md` + `assets/docs/operational_analysis.md` left in place (still useful reference; recover from history if archive is later preferred).
- Empty scaffolds `log/prototype.md` + `log/procedure.md` deleted (the new `notes/prototype.md` + `notes/procedure.md` are blank-slate writes).
- Commit shape: user committed manually after Phase 1; Phase 2 staged for the next commit.

**Why a clean slate**: the prior FastAPI-mesh experiment build had landed two large refactors in the past month (prototype-v2 reshuffle + calibration C0-C11). Methodological audit identified the `dpl="localhost"` MockTransport as monolithic-pretending-to-be-SOA; the SOA refactor (Phase A2-A9 + Phase B) was queued to fix that. Rather than continue stacking refactors on top, retire the build into `__OLD__/` and rebuild the experiment from scratch under `src/experimental/` with the methodology constraints learnt from the previous build. The case study (`notes/case-study.md`), the surviving methods (analytic, stochastic, dimensional), and the conventions stay; the apparatus is the part being reset.

## 2026-05-06 — Calibration refactor CLOSED; C9b + C10 + C11 landed

Closed the 11-stage calibration refactor opened 2026-05-03 evening. `src/methods/calibration.py` shrunk **2640 → 844 lines** (68%); the architectural-conformance findings (PyDASA pipeline duplication, dim-card-in-orchestrator-layer, multi-combo sweep in `methods/`) all resolved by relocation alone. The calibration package now follows the methodology layering: precondition-gate building blocks under `src/calibration/`, model artefact under `src/dimensional/`, thin orchestrator under `src/methods/`. Closure record at [notes/calibration.md](calibration.md); per-stage outcome at [memory/project_calibration_refactor_closed_2026_05_06.md](../C:/Users/Felipe/.claude/projects/c--Users-Felipe-OneDrive-Documents-GitHub-DASA-Design-PyDASA-CS1-TAS/memory/project_calibration_refactor_closed_2026_05_06.md).

**C9b-Phase 1** [src/dimensional/dasa_sweep.py](../src/dimensional/dasa_sweep.py) — new home for `run_calib_sweep` + helpers (`_drive_one_combo`, `_resolve_mu_anchor`, `_resolve_sweep_grid`, `_build_sweep_output_path`). The sweep is the multi-combo `(c, K, mu_factor)` dimensional sensitivity probe over a calibrated mu anchor — it's a dimensional-card sweep, not an orchestrator concern, so it lives next to `dasaprof.py`. Cross-imports `_drive_lambda_step` + `_post_one` from `src/calibration/rate.py` (the lambda-stepping engine stays in the rate module; `dasa_sweep` is the multi-combo composition that feeds rate stepping per `(c, K, mu_factor)` cell). 11 tests covering the mu-anchor table (4 paths: explicit / loopback / unknown / zero-degenerate), sweep-grid resolution (explicit / fallback to JSON), output-path shape (host normalisation, `_sweep` filename suffix, per-`dpl` subdir), and `run_calib_sweep` empty-input early-returns.

**C9b-Phase 2** [src/methods/calibration.py](../src/methods/calibration.py) rewritten from scratch — kept `run()` + CLI `main()` + `_run_async_probes` + zombie cleanup + path helpers; everything else removed. Re-export aliases at module top preserve the public + test-private surface (`run`, `derive_calib_coefs`, `run_rate_sweep`, `run_calib_sweep`, `run_handler_stability_sweep` + 6 underscore symbols `_aggregate_rate_trials / _batch_size_for / _find_highest_sustainable_rate / _parse_rates / _resolve_mu_anchor / _CALIB_DIM_TAG`) so existing notebook + CLI + experiment-method gate continue to work without code changes. **8 monkeypatch sites in `tests/methods/test_calibration.py` retargeted** to string-path form (`monkeypatch.setattr("src.dimensional.dasa_sweep._drive_one_combo", ...)`) since attribute-form patches now hit the orchestrator's namespace, not the new module's binding. 11/11 retargeted tests pass in 1:49.

**C10 notebook** [00-calibration.ipynb](../00-calibration.ipynb) — cell-1 imports updated to use new package locations directly: `from src.dimensional import derive_calib_coefs, run_calib_sweep`; `run` stays imported from `src.methods.calibration` (orchestrator). 25 cells; JSON valid; all 5 callables resolve to expected modules (verified: `derive_calib_coefs source: src.dimensional.dasaprof`, `run_calib_sweep source: src.dimensional.dasa_sweep`, `run source: src.methods.calibration`).

**C11 final docs pass** — [notes/calibration.md](calibration.md) marked "REFACTOR CLOSED" with all 11 stage rows showing ✅ DONE; CLAUDE.md "Calibration" callout rewritten from "refactor in progress" to a closed-state callout with the 13-row module-map table; MEMORY.md top entry replaced with the closure record `project_calibration_refactor_closed_2026_05_06.md`.

**Decision-log items**:
- Picked option (a) for C9b — built `src/dimensional/dasa_sweep.py` as new home rather than accepting a ~1400-line orchestrator. The 844-line final shape on `src/methods/calibration.py` undershoots the ~250-line target stated in the original plan; the gap is path helpers + `_run_async_probes` + zombie cleanup that legitimately belong in the orchestrator (they wire CLI args + stop conditions to the `SweepController`, which is the orchestrator's job).
- Re-export aliases vs full test rewrite: chose re-export aliases at module top so the existing 6 underscore-private test-symbol references survive without touching test bodies; the price is one extra layer of indirection from caller to implementation. Pinned in `notes/calibration.md` as "test-private-symbol re-export pattern".
- Monkeypatch retargeting via string-path: tests using `monkeypatch.setattr(cal, "_X", ...)` no longer affect the new package's bindings (they patch the orchestrator's namespace, not the new module's binding). Fix: use the string-path form `monkeypatch.setattr("src.dimensional.dasa_sweep._X", ...)` to patch where the function is actually looked up. Future cleanup deferred: replace these with public injectable hooks on `SweepController`.

**Validation**: 102 tests passing in fast scope (29s — `tests/calibration/` + `tests/dimensional/` + `tests/io/test_tooling.py`); 11 monkeypatch-retargeted tests passing in 1:49 (`tests/methods/test_calibration.py`); legacy 386-pass `tests/{experiment,methods,io,scripts}/` baseline unaffected. Smoke check: `from src.dimensional import derive_calib_coefs, run_calib_sweep` resolves; `from src.methods.calibration import run` resolves through re-export.

**Followups deferred**:
- `tests/methods/test_calibration.py` reaches into private symbols of the new package via string-path monkeypatch. Future cleanup: replace with public injectable hooks on `SweepController`.
- `run_async_safe` is annotated `-> Dict[str, Any]`; three call sites use `cast(...)` to recover concrete types. Long-term fix: make `run_async_safe` generic via TypeVar in `src/experiment/runtime/async_loop.py` so the casts collapse.
- IMG path `data/img/experiment/calibration/` not migrated (only RESULTS path moved per Q-B). Move to `data/img/calibration/` for symmetry as a separate decision.
- `controller.yoly_dataframe()` API not yet implemented; notebook's yoly chart cell still calls `derive_calib_coefs` directly.

**Successor task**: SOA Phase A Stages A2-A9 per `notes/soa-refactor.md`. The three building blocks calibration delivered (`UvicornProcess`, `make_gauge_factory`, per-`dpl` envelope writer) are exactly what Phase A's experiment mesh needs. Confirm with user before starting A2 — it's a substantial new piece of work that warrants explicit signoff.

---

## 2026-05-06 — pyproject.toml landed; root conftest.py deleted

Closed the long-standing TODO from the 2026-04-18 conftest.py decision. Created `pyproject.toml` at repo root carrying `[tool.pytest.ini_options]` only (`pythonpath = ["."]` for `from src.* import ...` resolution + `markers = ["live_mesh: ..."]` for the custom marker registration). Deleted root `conftest.py`. `tests/conftest.py` is untouched and still owns the shared PyDASA fixtures (`method_cfg`, `dflt_profile`, `opti_profile`, `schema`, `tas1_vars`, `engine_bare`, `engine_ready`, `sensitivity_results`).

**Decision-log items**:
- Kept the file minimal: no `[build-system]` or `[project]` block. This repo is a case-study deliverable (notebooks + figures + metrics), not a distributable wheel; adding a build system would invite scope creep with no consumer.
- The `live_mesh` marker registration moved verbatim from the deleted `conftest.py::pytest_configure` hook. The marker description was reaffirmed during the swap: it covers any test that spins up a real FastAPI mesh (`UvicornThread` in-process, `UvicornProcess` out-of-process, or multi-trial sweeps over either). It names the mesh-spin-up cost axis, not the process-distribution axis — multiprocess is a strict subset, not a synonym.

**Verification**: `pytest --collect-only -q` collected **640 tests** post-swap; `pytest tests/utils/` (3 passed in 0.10s) confirms the path resolution; `pytest tests/dimensional/` (92 passed in 91s) confirms the session/module-scoped fixtures from `tests/conftest.py` still resolve. No unknown-marker warnings.

**Pickup**: when ruff / mypy / hatchling config lands later, extend the existing `pyproject.toml` rather than spawning a sibling `ruff.toml` / `setup.cfg`. If a new pytest marker is introduced (e.g. a multiprocess-only `live_mesh_mp` subset), register it in the `markers` list.

---

## 2026-05-04 — Calibration refactor C8 + C9a closed; C9b paused for scoping decision

**C8 (`src/dimensional/dasaprof.py`)**: relocated `derive_calib_coefs` + its helper stack (`_build_calib_observables`, `_calib_var_sym`, `_build_calib_vars`, `_run_calib_pipeline`) from `src/methods/calibration.py` to a new `src/dimensional/dasaprof.py`, re-exported from `src/dimensional/__init__.py`. The pipeline already called `src.dimensional.build_engine` + `build_schema`; the C8 deliverable was the layering fix (move DOWN from `methods/` orchestrator to `dimensional/` model-artefact). Honest call: the canonical `src/dimensional/coefficients.py::derive_coefs` is shaped for TAS-architecture Pi-indexed specs and CANNOT directly serve calibration's standalone-artifact variable set, so the two paths legitimately stay siblings: `derive_coefs` (TAS, Pi-indexed) + `derive_calib_coefs` (calibration, base-variable expressions). Both correctly live under `src/dimensional/`. Byte-identical regression: 3 tests in `tests/dimensional/test_dasaprof.py` (single-K zero-payload, multi-K with 128 kB payload, custom subscript tag) all green; the new path produces identical output to the legacy `src/methods/calibration.py::derive_calib_coefs` for the same envelope inputs.

**C9a (path migration)**: 51 on-disk JSONs migrated from `data/results/experiment/calibration/` to `data/results/calibration/localhost/` via a single `mv`. Updated `src/io/tooling.py::_CALIB_DIR` to `data/results/calibration/<dpl>/` (with new `_CALIB_ROOT` constant + new `dpl` parameter on `find_latest_calibration` / `load_latest_calibration`, defaulting to `"localhost"` for back-compat). Updated `src/methods/calibration.py::_CALIB_DIR` to match. Fixture `tests/io/test_tooling.py::_isolated_calib_dir` updated to monkeypatch `_CALIB_ROOT` (and the legacy `_CALIB_DIR` alias) so the per-`dpl` subdir resolution is exercised correctly. Stop-gate `pytest tests/calibration/ tests/dimensional/ tests/io/ tests/scripts/` = **136 passed in 40s**; broader run including `tests/methods/test_calibration.py` = **231 passed in 35:46** (3 of which were the byte-identical C8 regression tests). Smoke check: `find_latest_calibration(socket.gethostname())` resolves correctly to the migrated tree.

**Decision-log items**:
- C8: scope honesty. The architectural-conformance report flagged "PyDASA pipeline duplication" between `_run_calib_pipeline` and `derive_coefs`. Closer reading: `_run_calib_pipeline` already calls `build_engine` + `build_schema`; the only duplication is `pydasa.Coefficient(...)` construction, which is INTENTIONAL because the calibration variable set + FDU count differ from the TAS topology so Pi-group ordering shifts. Forcing calibration through `derive_coefs` would require either widening that API (out of scope) or maintaining a parallel calibration spec block in `dimensional.json` (schema duplication). The two paths legitimately stay siblings; the layering bug is fixed by relocation alone. Pinned in `notes/calibration.md`.
- C9a: backward-compat strategy. `find_latest_calibration` and `load_latest_calibration` gained a `dpl` parameter rather than splitting into `find_latest_calibration_localhost` / `_multiprocess`. Default `"localhost"` keeps every existing call site working unchanged. The `experiment.py::_resolve_baseline` gate will pick up `dpl="multiprocess"` once the experiment runs in that mode (post SOA Phase A2).

**C9b paused for scoping decision** (see `notes/calibration.md` "C9b scoping" section). Three options: (a) build `src/dimensional/dasa_sweep.py` to home `run_calib_sweep`, then methods/calibration.py truly shrinks to ~300 lines (recommended; closes the original 250-line target); (b) accept a ~1400-line orchestrator (faster but undersells the refactor); (c) aliases-only (cosmetic). Pickup: pick an option, then execute. Both old `src/methods/calibration.py` and the new `src/calibration/` package work end-to-end today, so there's no urgency.

**Aggregate state at close**: 9 new src modules under `src/calibration/` + `src/dimensional/dasaprof.py`; **241 new tests across the calibration + dimensional packages, all green**; old `src/methods/calibration.py` (2640 lines) functional but contains duplicates that will be deleted in C9b once the home for `run_calib_sweep` is decided.

---

## 2026-05-03 (evening 4) — Calibration refactor Stages C0-C7 closed; paused before C8

Long autonomous session executing the calibration refactor plan written in `notes/calibration.md`. Eight new modules under `src/calibration/` plus the `UvicornProcess` runtime extension; **113 new tests** across 8 source files, all green; full per-stage audit pass against `.claude/skills/develop/coding-conventions.md` + `.claude/skills/code/code-documentation.md`.

**Stages closed**:

- **C1** [src/experiment/runtime/uvicorn_process.py](../src/experiment/runtime/uvicorn_process.py) — `UvicornProcess` mirrors `UvicornThread` API but spawns `multiprocessing.Process` with picklable `app_factory`. Windows `spawn` semantics validated end-to-end against the gauge: factory pickles, child process re-imports the module, FastAPI app builds in the worker, `/healthz` answers 200. Doubles as SOA Phase A Stage A1. 8 tests; type-fix `Optional[mp_process.BaseProcess]` (pyright caught `SpawnProcess != mp.Process`); composition over inheritance (sibling-symmetry with `UvicornThread`'s `threading.Thread` subclassing decided against because `multiprocessing` is API-shaped for composition + we need explicit `spawn`-pinning for per-PID seed reproducibility).

- **C2** [src/experiment/instances/gauge.py](../src/experiment/instances/gauge.py) — `make_gauge_factory(spec, payload_size_bytes)` returns a `functools.partial(build_gauge, spec, payload_size_bytes)`. Both `build_gauge` (module-scope) and `SvcSpec` (frozen dataclass over primitives) are picklable across the Windows spawn boundary, so the factory survives `multiprocessing.Process(target=worker, args=(factory, ...))`. The naming asymmetry vs `build_gauge` is intentional and signals the return-type distinction (FastAPI app vs `Callable[[], FastAPI]`). 10 tests including a live spawn-via-factory smoke.

- **C3** [src/calibration/conditionals.py](../src/calibration/conditionals.py) — `StopConditions` frozen dataclass with locked-decision defaults (`rejection=5.0`, `phi=1.0`, `sigma=2.0`, `loopback_delta=5.0`); pure predicates `should_stop`, `should_stop_detailed` (returns provenance dict for envelope), `loopback_two_trial_ok`. 32 boundary tests covering rejection-strict-greater + phi-greater-or-equal + sigma-strict-greater semantics + multi-trip precedence + symmetric loopback delta + non-positive medians raise.

- **C4** [src/calibration/envelope.py](../src/calibration/envelope.py) — per-`dpl` JSON I/O. `output_path / write_envelope / find_latest / load_latest`. Path shape `data/results/calibration/<dpl>/<host>_<YYYYMMDD_HHMMSS>.json` (Q-B locked: drops the `/experiment/` segment). Atomic write (temp + rename); host-prefix glob with space-to-hyphen normalisation; mtime ordering. **STILL PENDING** for C9: one-shot `mv` of the 47 existing JSONs from `data/results/experiment/calibration/` to the new path + `src/io/tooling.py::_CALIB_DIR` switch. 18 tests.

- **C5** [src/calibration/hoststats.py](../src/calibration/hoststats.py) — host-floor probes `snapshot_host_profile / measure_timer / measure_jitter / measure_loopback / measure_handler_scaling` plus the canonical stats helpers `stats_from_us_array / stats_from_us_status_pairs` (renamed from leading-underscore now that they cross the package boundary). Lands ADDITIVELY: the duplicate code in `src/methods/calibration.py` stays untouched until C9. 11 tests (9 inline + 2 live_mesh).

- **C6** [src/calibration/rate.py](../src/calibration/rate.py) + [stability.py](../src/calibration/stability.py) — rate-saturation discovery (`run_rate_sweep / find_highest_sustainable_rate / batch_size_for`) and apparatus self-consistency (`run_handler_stability_sweep / aggregate_stability_cell / select_c_per_n_con_usr`). Both use the new `make_gauge_factory` from C2 and `run_async_safe` from `src.experiment.runtime` for the sync→async bridge (replacing the old `_run_sweep_in_dedicated_loop` shim). Type-cast at the `run_async_safe` boundary in both modules (pyright: `run_async_safe -> Dict[str, Any]` widens; cast restores the concrete `Dict[float, ...]` shape so `.get(_rate, [])` and `.items()` type-check; long-term fix is to make `run_async_safe` generic via TypeVar, deferred to C9). 21 tests covering the pure helpers; full sweeps deferred behind `@pytest.mark.live_mesh`.

- **C7** [src/calibration/controller.py](../src/calibration/controller.py) — composition layer. `HostSweepGrid` + `DasaSweepGrid` frozen dataclasses with `from_config` classmethods reading `calibration.json` partials (defaults match the JSON one-for-one). `SweepController` holds `host_grid` + `dasa_grid` + `stop` + `dpl`; `_spawn_gauge` branches on `dpl` between `UvicornThread` (localhost) and `UvicornProcess` (multiprocess); `run_host_sweep` composes timer + jitter + loopback + handler_scaling + optional rate_sweep + optional stability_sweep into one envelope; `run_dasa_sweep` accepts an injected `deriver` callable so the controller stays decoupled from `src/dimensional/` (Stage C8 will pass `deriver=derive_calib_coefs`). 13 tests including a live end-to-end host-sweep on `dpl="localhost"`.

**Audit pass against both skills** for each new module: zero em-dashes, non-circular docstrings preserving Args/Returns/Raises, short `topic+outcome` test names (mapping ~28 → ~17 chars average), one-test-class-per-source-module, top-level imports only, callable-class for stateful mocks (none needed in this batch), `raise SomeError(_msg)` with extracted message. Three rounds of audit per the user's `/skills` request — every C1/C2/C3/C5/C6/C7 file pair revisited; the `_free_port` helper docstring linter-stomp surfaced and was restored. Lessons: the sibling pair (`UvicornThread` / `UvicornProcess`) and (`build_gauge` / `make_gauge_factory`) keep their style and structure in lockstep; `make_*` vs `build_*` is a load-bearing distinction (return-type marker), not a naming inconsistency.

**Type-fix carry-overs**: `Optional[mp_process.BaseProcess]` for `UvicornProcess._proc` (one-line); `cast(Dict[K, V], run_async_safe(...))` at three call sites (rate.py + stability.py + controller.py). Long-term `run_async_safe` should be generic over the coroutine return type; deferred to C9 as a single edit in `src/experiment/runtime/async_loop.py` so all three cast call sites collapse.

**Old code in `src/methods/calibration.py` is UNTOUCHED.** Tests for the existing module + the experiment-method gate in `src/methods/experiment.py::_resolve_baseline` continue to read from the old `data/results/experiment/calibration/` path. The new package is purely additive; the swap-over happens in C9.

**Paused before C8.** C8 is the most consequential remaining stage because it requires a byte-identical regression test: `derive_calib_coefs` (currently in `src/methods/calibration.py`) must be moved to `src/dimensional/dasaprof.py` AND rewritten to call `src/dimensional/engine.py::build_engine` + `src/dimensional/coefficients.py::derive_coefs` instead of duplicating the PyDASA `Schema → AnalysisEngine → Coefficient → MonteCarloSimulation(mode=DATA)` pipeline. Risk: silent dim-card value drift if either pipeline interprets the input observables differently. Mitigation plan: feed a fixed-seed envelope into BOTH paths and assert the `dimensional_card` block is byte-identical before declaring C8 done.

Pickup at next session: C8. Tracker remains `notes/calibration.md` (per-stage status table updated for every completed stage). C9-C11 outline:
- **C9**: shrink `src/methods/calibration.py` to ~250-line orchestrator, switch consumers to import from `src/calibration/` + `src/dimensional/dasaprof.py`, delete the duplicates extracted in C5/C6/C8, migrate the 47 on-disk JSONs (the C4-pending `mv`), update `src/io/tooling.py::_CALIB_DIR`.
- **C10**: `00-calibration.ipynb` migrated to new imports; yoly chart cell calls `controller.yoly_dataframe()` instead of running probes inline.
- **C11**: CLAUDE.md "Module map" reflects new structure; `notes/calibration.md` marked "refactor closed"; MEMORY.md updated.

---

## 2026-05-03 (evening 3) — Calibration refactor approved; sequence locked calibration-first

Following the code-review + architectural-conformance report (`notes/reports/code_review_calibration_2026-05-03.md`), the user proposed a refactor of `src/methods/calibration.py` aligned with `.claude/skills/design/experimental-design.md` §1 ("Calibration is a precondition gate, NOT a hypothesis tolerance").

**Locked decisions** (all in `notes/calibration.md` "Refactor — locked decisions" table):

- **I-1**: stop on `reject_rate > 5%` (any cell rejecting > 5% has crossed out of the M/M/c/K validity envelope; further data measures the host's saturation-handling code path, not the model's predicted regime).
- **I-2**: two separate calibration runs, two separate envelopes — `data/results/calibration/{localhost,multiprocess}/<host>_<ts>.json`. Different transport stacks → different μ values.
- **I-3**: strict layer placement. `src/calibration/` package + `src/dimensional/dasaprof.py` + `src/methods/calibration.py` (kept as thin orchestrator).
- **Q-A**: calibration is self-contained — `calibration.json` only. NO consumption of `dflt.json` / `opti.json` (that α-clamp belongs to the experiment method, not calibration).
- **Q-B**: result path drops the `/experiment/` segment → `data/results/calibration/<dpl>/`.
- **Q-C**: `payload_size_bytes` stays at 128000 (128 kB).
- **Q-D**: NO clamp on `os.cpu_count()` — digital workers are software constructs; sweeping `c=32` on a 16-core host is the intentional contention regime measurement.
- **Q-E**: `samples_per_level: 1024` confirmed.
- **Q-F**: `--dpl multiprocess` MUST execute end-to-end. Real `UvicornProcess`-backed gauge in a separate OS process. Pulls SOA Phase A Stage A1 into calibration's scope as Stage C1.

**Sequence locked: calibration-first.** I argued for calibration before SOA Phase A Stages A2-A9 because (a) the SOA experiment mesh's R1/R2/R3 verdicts require a multiprocess calibration envelope to subtract loopback overhead from — running SOA first against today's localhost calibration would systematically under-report multiprocess overhead by 50-200 μs of TCP loopback; (b) `UvicornProcess` is the same work in both plans (calibration C1 = SOA A1) and the calibration vernier is the simplest possible service for the Windows `spawn` spike; (c) skipping the calibration refactor leaves SOA A9's "dissertation-grade numbers" stop-gate unsatisfiable until calibration ships afterwards anyway. User accepted; sequence is C0-C11 → A2-A9.

**11-stage calibration refactor plan + acceptance criteria + target package layout** are all in `notes/calibration.md` — that file is the canonical task tracker. Every stage commit references it; every closed stage updates the progress table. After C11 closes, the soa-refactor.md A2-A9 queue resumes.

**A0 of SOA Phase A is now retroactively DONE** — today's earlier deployment-axis rename + folder restructure (this morning's "evening" devlog entry) was Stage A0's identifier sweep, completed before the C0 work landed. The `loopback_aliased → multiprocess` and `local → localhost` renames + the `data/results/experiment/{localhost,multiprocess,remote}/` folder restructure all fall under A0 and are stored in this devlog's earlier 2026-05-03 (evening) entry.

Pickup at next session: Stage C1 — `UvicornProcess` spike against the calibration vernier. If Windows `spawn` semantics break the FastAPI app-factory pattern, the refactor halts at C1 and we revisit; otherwise, C2-C11 follows.

---

## 2026-05-03 (evening 2) — Code-review + architectural-conformance report on `src/methods/calibration.py`

Combined `/code-report` (seven-section diagnosis) with `architectural-conformance.md` (design-intent vs as-built) lenses on the calibration module. Report at `notes/reports/code_review_calibration_2026-05-03.md`. Diagnosis only — no code changed.

**Headline finding**: calibration was promoted from `src/scripts/` to `src/methods/` (2026-04-23) without resolving whether it is a *method* (one hypothesis, one `run`) or a *precondition gate* (host-floor probes). Over ~10 days it accreted a Route-B dimensional-card pipeline + a multi-combo sweep, becoming a 2636-line god module exposing 5+ public callables against a documented promise of 1-2 in CLAUDE.md "Module map". The PyDASA pipeline at `_run_calib_pipeline` ([src/methods/calibration.py:1977](src/methods/calibration.py#L1977)) duplicates `src/dimensional/engine.py::build_engine` + `src/dimensional/coefficients.py::derive_coefs` — two derivation paths for the same coefficient family is the single material risk.

**Eight recommendations (R1-R8) ranked**:
- R1 (XS): document the as-built scope in CLAUDE.md "Module map" + `notes/calibration.md` so the drift becomes *controlled* drift.
- R2 (M): refactor `_run_calib_pipeline` to call `src/dimensional/`'s pipeline instead of duplicating it. Single source of truth for theta/sigma/eta/phi.
- R3 (S): move `derive_calib_coefs` to `src/dimensional/calibration_card.py`.
- R4 (S): move `_DEFAULT_*` constants out of module scope into `run()`'s body.
- R5 (XS): demote `measure_*` and `_build_calib_*` from documented public API.
- R6 (S): decide whether `run_handler_stability_sweep` is gate or diagnostic; fold or split.
- R7 (M): regression test asserting calibration card and dimensional-method coefficients agree within precondition gate.
- R8: defer structural changes until SOA refactor Phase A Stage A1 (vernier transport swap) lands.

**Verdict**: as-built state is acceptable for dissertation scope IF documented (R1). Recommend deferring all structural work until SOA Phase A closes, then bundle R2/R3/R4 as one calibration-cleanup pass. The headline risk (PyDASA pipeline duplication) can be neutralised by R2 alone — no file moves required.

---

## 2026-05-03 (evening) — Stage A0 of SOA refactor: deployment-axis rename + folder restructure

Stage A0 of the two-phase SOA refactor (`notes/soa-refactor.md`) executed. Two coordinated changes landed in one sweep:

1. **Deployment-axis rename, two passes.** First pass swapped `loopback_aliased → multiprocess` (the original Stage A0 plan); second pass renamed `local → localhost` so the deployment-axis literal matches its on-disk `data/results/experiment/<dpl>/` folder name and reads as the universally-understood term for one-host loopback. Singular `multiprocess` (not `multiprocesses`) for register-consistency with `localhost` / `remote`. Sites: `_VALID_DEPLOYMENTS` tuples in `src/methods/experiment.py` + `src/scripts/launch_services.py`; `data/config/method/experiment.json::deployment`; `TasArchitecture._gate_deployment` + `bind_addr`; `SvcRegistry._pick_host`; every test class / method name + assertion / regex covering deployment values; `tests/scripts/test_launch_services.py::test_localhost_all_short_duration`. English `local_services()`, `local_end_ts` (CSV column, wire-schema off-limits), and "non-local routing" in `services/base.py` are NOT renames — those are domain English, not the deployment-axis literal.

2. **Folder restructure.** Deleted `data/{results,img}/experiment/{aggregate,baseline,local,localhost,loopback_aliased,multiprocesses,remote,s1,s2}/` (all stale, all untracked — pre-deployment-axis orphans + empty post-axis duplicates). Created `data/{results,img}/experiment/{localhost,multiprocess,remote}/.gitkeep`. **Calibration preserved**: `data/results/experiment/calibration/` (47 host-keyed JSONs, ~3 min each) and `data/img/experiment/calibration/` (10 PNG/SVG figures) untouched, because calibration measures the host's noise floor (loopback latency, jitter, handler scaling) — same number for `localhost`/`multiprocess`/`remote` runs on the same host, so triplicating it under each `<dpl>/` would force a redundant 3-times re-calibration AND break the per-host gate in `src/io/tooling.py::find_latest_calibration` which globs one path keyed on `socket.gethostname()`.

3. **Stop-gate**: `pytest tests/experiment/ tests/methods/ tests/io/ tests/scripts/` -> 386 passed, 2 failed (identical to baseline). The 2 failures are `TestRampValidation::test_both_rates_and_rho_grid_raises` and `::test_neither_raises` — pre-existing regex mismatches from this morning's lambda_z anchor work, not regressed by the rename. Zero rename-induced failures.

**Calibration-canary commit pinned for Stage A1.** When `runtime/uvicorn_process.py` lands (Windows `spawn` spike), the same commit will switch `src/methods/calibration.py::_register_vernier` from `UvicornThread` to `UvicornProcess(workers=1)`. Two reasons: (1) the vernier is the simplest `c_srv=1, workers=1` case, so any `spawn`-related breakage surfaces against one service before touching the 13-service mesh; (2) once the experiment runs on `UvicornProcess`, calibration on `UvicornThread` would measure the noise floor through a different transport stack than the experiment uses, biasing the `reported = measured - loopback_median ± jitter_p99` correction. Vernier stays at `c_srv=1, workers=1` — `workers=4` would fold worker-pool overhead into the floor.

Pickup at next session: Stage A1 = `runtime/uvicorn_process.py` + calibration vernier swap, in one commit.

---

## 2026-05-03 — Post-v2 cleanup, lambda_z anchor for the experiment method, SOA refactor planned

Three discrete pieces of work landed today on top of the closed prototype-v2 reshuffle:

1. **Post-v2 cleanup pass.** Public-alias enforcement for `src.analytic` (methods/experiment.py + methods/stochastic.py swapped to `from src.analytic import ...`); `src/experiment/instances/gauge.py::build_gauge` shipped to give the vernier service the same `instances/` builder pattern as `build_third_party` (atomic) and `build_tas` (composite); `methods/calibration.py::_build_ping_app` and `_build_vernier_app_for_combo` refactored to use `build_gauge`. Three demo files fixed for the post-2026-05-01 service-layer protocol: `demo_client.py` migrated to `TasUser`; `demo_services.py` `@logger(_ctx)` factory replaced with the `_DemoHandler` callable-class pattern; `demo_third_party.py` `_recorded_forward` return-type annotation fixed to `ExtFwdFn`. Stop-gate: 387 passed.

2. **Experiment method anchored at lambda_z.** Methodological fix — the experiment method was using a saturation-discovery ramp (`[50, 100, 200, 300, 500]`) that conflated calibration's job (find host ceiling) with the experiment method's job (validate at the design point). Methods 1-3 evaluate the network at `lambda_z = 345`; for method 4 to be apples-to-apples in `07-comparison.ipynb`, it must measure at the same operating point. Fix: extended `executor._resolve_rates` and `tooling._validate_ramp_block` to accept a third drive spec (`anchor: "lambda_z"`) alongside `rates` and `rho_grid`. The `anchor` form reads `cfg.artifacts[entry_artifact].lambda_z` and emits `rates = [lambda_z]`. `experiment.json` ramp block now defaults to `anchor: "lambda_z"`; `05-experimental.ipynb` dropped its `_NB_METHOD_CFG` override entirely and now calls `run_experiment(adp=a, wrt=True)` directly. Stop-gate: 31 targeted tests passed.

3. **Calibration tuning + the bandwidth realisation.** `data/config/method/calibration.json` bumped: `sweep_grid.c[0]: 8 → 16`, `sweep_grid.K[0]: 16 → 128`, plus rate-sweep acceleration (`trials_per_rate: 11 → 7`, `max_probe_window_s: 2.0 → 1.5`, `inter_trial_delay_s: 3.0 → 1.5`, `rates: [10, 50, 200, 300, 400, 500, 510]`). Result: calibrated rate stayed at 200 req/s, confirming gating wasn't the bottleneck. The remaining ceiling is bandwidth (128 KB payload on Windows loopback) × Python single-process (asyncio single-event-loop GIL serialisation). Group C (drop payload to 32 KB) and multi-worker uvicorn deferred pending the SOA refactor.

**The methodological discovery driving the next stage**: `dpl="local"` (in-process MockTransport mesh) is monolithic — 13 FastAPI app objects in one Python process sharing one event loop is not SOA. The DASA case-study claim ("dimensionally normalised coefficients characterise the architecture, not the implementation") only holds if the prototype is actually a distributed service mesh. Two-phase plan written into `notes/soa-refactor.md`:

- **Phase A — Path 2: multi-process on localhost** (`dpl="multiprocesses"`). Replace `UvicornThread` with `multiprocessing.Process`; per-PID `SvcCtx` + `<service>__pid<PID>.csv` log files; `build_svc_df_from_logs` merges per-worker CSVs; `TasArchitecture` connect-only mode (real httpx, healthz-poll, no in-process app mount); launcher subprocess autoload. ~2-3 days.
- **Phase B — Path 3: LAN-distributed** (`dpl="remote"`). Configuration on top of Phase A — same code, different `experiment.json::hosts`. Stages B1-B6 add `--bind-host` flag, `wall_clock_offset_ns` CSV header for cross-host time alignment, HTTP `/_logs/<service>` tarball endpoint for log collection. ~1 week (mostly setup + ops).

Critical invariant carried across both phases: per-service code is identical in `local` / `multiprocesses` / `remote`. Only SvcRegistry's host resolution + launcher orchestration + log-collection strategy differ. Phase A's whole point is to build the right abstractions so Phase B becomes a JSON edit + an SSH session, not another refactor.

Naming pinned the same day: `dpl ∈ {local, multiprocesses, remote}` reads monotone in distribution count. Renamed `loopback_aliased` → `multiprocesses` so the trio reads "single-process / multi-process-one-host / multi-process-many-hosts" — the meaningful axis, not the network-binding mechanism. Code-side rename sweep is part of Stage A0.

Phase A's four open design questions (G2) settled before any code lands:

1. **Per-worker seeding**: fold PID into `derive_seed(root_seed, f"{service}_pid{pid}")`. Each worker has independent reproducible streams per `(root_seed, pid)` pair; run-envelope `notes` records all PIDs so post-hoc analysis can re-derive any stream.
2. **Workers per service default**: uniform 4. `--workers N` CLI flag overrides. 13 × 4 = 52 worker processes per host (~7.8 GB RAM at 150 MB each on a 16-core box, ~3 workers per core).
3. **Launcher activation**: autoload by default + `launcher_started=True` opt-out. Notebook gets autoload (`subprocess.Popen` from inside `methods/experiment.py::run` when `dpl != "local"`); CI / scripted bench / dissertation runs pre-launch with their own supervisor and pass `launcher_started=True`.
4. **Keep `dpl="local"`**: yes, marked explicitly as the dev/test mode. The methodological problem was using `local` AS the case-study runner; the solution is to stop doing that, NOT to delete `local`. Branch in `__aenter__` between `_init_routed_client + _mount_apps` (local) and `_init_real_http_client + _healthz_poll` (multiprocesses).

Track 2 (test-suite simplification) **deferred until Phase A closes**. User flagged that `@pytest.mark.slow` would mis-categorise `tests/stochastic/` (genuinely simulation-heavy by nature, not "live mesh" slow). When Track 2 reopens, the right marker name is `@pytest.mark.live_mesh` (precise — tests that spin up the FastAPI mesh, in-process or multi-process), NOT `@pytest.mark.slow` — same axis-naming rule as the `multiprocesses` rename: the marker should name the failure-mode dimension, not a coarse speed bucket.

Pickup at next session: Stage A0 (identifier sweep) → Stage A1 spike (Windows `spawn` for FastAPI app-factory, validated against the calibration vernier first) → G3 sign-off before touching the 13-service experiment mesh. Decision-log in `notes/soa-refactor.md` Stage A0; live state in `memory/project_soa_refactor_planned_2026_05_03.md`.

---

## 2026-05-02 — Prototype-v2 reshuffle of `src/experiment/` (Stages 1-8 closed)

Eight-stage refactor reshaping `src/experiment/` so the layering reads top-down: `architecture.py` (server) + `users.py` (client) compose into `executor.py` (cell driver), with `wire/` (URL + payload concerns) and `runtime/` (OS-boundary helpers) sitting underneath. Plan, status table, and per-stage notes in `notes/prototype-v2.md`.

**Layout shift**

```
src/experiment/
├── __init__.py                     # marker only; documents the two top-level ctxmgrs
├── architecture.py                 # TasArchitecture (server-side ctxmgr)
├── users.py                        # TasUser (client-side ctxmgr) — NEW
├── executor.py                     # execute_one + execute_sweep + build_svc_df_from_logs
├── client/                         # client-side load-generator package (records / config / guard / sender / driver / stats / simulator)
├── instances/                      # tas / third_party / common
├── services/                       # atomic / composite / vernier / base / instruments
├── wire/                           # NEW
│   ├── payload.py                  # generate_payload, resolve_size_for_kind
│   └── registry.py                 # SvcRegistry
└── runtime/                        # NEW
    ├── async_loop.py               # run_async_safe
    ├── os_timer.py                 # windows_timer_resolution
    └── uvicorn_thread.py           # UvicornThread
```

`scanner.py` and `runner.py` are gone. `payload.py` + `registry.py` now live under `wire/`. `uvicorn_thread.py` joined `os_timer.py` + `async_loop.py` under `runtime/`. `users.py` is new — the synthetic-user side of the prototype, deliberately decoupled from `architecture.py` (the executor pairs them). `executor.py` absorbed the scanner sweep + helpers + `build_svc_df_from_logs`. `methods/experiment.py` imports DOWN from `executor.py` directly; the scanner shim is deleted.

**Stage outcomes** (full per-stage table in `notes/prototype-v2.md`; final pytest is **387 passed** at every multi-stage stop-gate):

| Stage | Action | Stop-gate |
|---|---|---|
| 0 | Baseline pytest + consumer inventory | 364 passed in 8:49 |
| 1 | `wire/` (`payload.py` + `registry.py`) | 295 passed in 4:34 |
| 2 | `runtime/` (`async_loop.py` + `os_timer.py` extracted from `executor.py`; `uvicorn_thread.py` moved in) | 16 runtime + 302 broader |
| 3 | `users.py` with `TasUser` ctxmgr (decoupled from architecture) | 260 passed in 32:84 |
| 3.5 | architecture.py + test_architecture.py alignment with the wire/runtime/users refactor | 258 passed |
| 4 | `scanner.py` absorbed into `executor.py`; quarantine shim left in place | 387 passed in 8:36 |
| 5 | Verify `methods/experiment.py` imports DOWN through the shim | (no code change) |
| 6 | Switch consumers to NEW import paths (executor + runtime, no scanner) | 387 passed in 9:25 |
| 7 | Delete `scanner.py` shim + clean `__init__.py` historical note | 387 passed in 8:51 |
| 8 | Devlog + memory entries (this entry) | (docs only) |

**Patterns crystallised during the reshuffle** (all pinned in `.claude/skills/develop/coding-conventions.md` + memory):

- **One test class per source module.** `TestInit` / `TestActiveFlag` / `TestWaitReadyTimeout` collapsed to single `TestUvicornThread`; same for `TestTasArchitecture` (was 4 classes), `TestExecutor` (was 3 classes). Class context plus prefix-disambiguated test names (`test_resolve_rates_*`, `test_execute_one_*`, `test_sweep_*`) carry the topic.
- **`__aexit__` underscore-prefix unused-args.** Every async ctxmgr in the package signs `async def __aexit__(self, _exc_type, _exc, _tb) -> None:` with a docstring paragraph explaining the protocol-required-but-unused contract.
- **Decompose long `__aenter__` into named `_step_x()` helpers.** `TasArchitecture.__aenter__` shrank from a 100-line block of `# step 1` / `# step 2` runs to a 6-line table of contents calling `_gate_deployment` / `_init_registry_and_specs` / `_resolve_entry_router` / `_init_routed_client` / `_mount_apps`.
- **`while active:` over `while True: break`.** `UvicornThread.wait_ready` refactored to use a boolean instance flag with inline raise on the failure path; `shutdown()` clears the flag to release a concurrent poll early.
- **Sibling ctxmgrs stay constructor-independent; the executor pairs them.** `TasUser` does NOT import `TasArchitecture`; `executor.execute_one` is the only place that constructs both. Lets `TasUser` be driven against any compatible transport.
- **No `assert` in `src/` modules.** `assert` gets stripped under `python -O`; production code uses explicit `if cond: raise SomeError(_msg)` for invariants. Pyright narrows after the raise.
- **Behavioural tests over no-raise tests.** `test_os_timer.py` rewrote 4 weak no-raise tests into 7 behavioural tests using `unittest.mock.patch` to verify `winmm.timeBeginPeriod` / `timeEndPeriod` are actually called in order, with the right period, and that `timeEndPeriod` runs even when the body raises.
- **Build_svc_df_from_logs stays at the building-block layer.** Original Stage-5 plan was to lift it UP into `methods/experiment.py`. Revised because BOTH `execute_sweep` and `methods/experiment.py::run` consume it; placing it at `executor.py` lets both import DOWN. The Stage-5 step degenerated to a verification.

**Files added / removed**

- Added: `src/experiment/users.py` (95 lines), `src/experiment/wire/{__init__,payload,registry}.py`, `src/experiment/runtime/{__init__,async_loop,os_timer,uvicorn_thread}.py`, `tests/experiment/test_users.py`, `tests/experiment/wire/test_{payload,registry}.py`, `tests/experiment/runtime/test_{async_loop,os_timer,uvicorn_thread}.py`.
- Removed: `src/experiment/{payload,registry,scanner,uvicorn_thread,runner}.py`, `tests/experiment/test_scanner.py`, the inline `ClientSimulator`-construction paths in `test_architecture.py` (migrated to `TasUser`).

---

## 2026-05-02 — `client.py` split into `src/experiment/client/` package

`src/experiment/client.py` (~595 lines) was doing config + record + cascade detector + request sender + rate driver + stats + ramp orchestrator in one file, with the middle five collapsed into `ClientSimulator`. Split along responsibility lines while keeping a `*__OLD__.py` reference module + barrel shim for the deprecation window so consumers stay green at every step.

**New layout** (`src/experiment/client/`):
- `records.py` -> `RequestRecord` (renamed from `InvocationRecord`).
- `config.py` -> `CascadeCfg` / `RampCfg` / `ClientCfg`.
- `guard.py` -> `StopGuard` (renamed from inline cascade detector).
- `sender.py` -> `RequestSender(client, registry, cfg, rng).send_one(kind)`.
- `driver.py` -> `RateDriver(sender, guard, ramp_cfg, kind_names, kind_prob_norm, rng).run(rate)` — absolute-deadline batch loop.
- `stats.py` -> `compute_probe_stats(records, counts, duration_s, rate, stop_reason, kind_names)` (pure function).
- `simulator.py` -> lean `ClientSimulator` composing sender + guard + driver; walks the rate schedule.
- `__init__.py` barrel re-exports the public API plus deprecation aliases (`InvocationRecord = RequestRecord`, `validate_ramp` / `build_ramp_cfg` -> `src.io.load_ramp_cfg`).

**JSON loader moved to `src/io/tooling.py`** (parity with `load_method_cfg`):
- `load_ramp_cfg(ramp)` -> `RampCfg` (validates first).
- `load_client_cfg(method_cfg, *, kind_prob)` -> full `ClientCfg`.
- Both re-exported from `src/io/__init__.py`.

**Quarantine pattern** (per-stage safety): renamed the old module `client.py` -> `client/client__OLD__.py` and the old test file `test_client.py` -> `tests/experiment/client/test_client__OLD__.py`. The barrel pointed at OLD initially, then switched to NEW once every submodule + test landed. Old test file repointed its imports at `client__OLD__.py` directly so it kept testing OLD throughout the migration. Both `*__OLD__.py` files will be deleted in a follow-up commit once the deprecation window ends.

**Naming choices**:
- `cascade.py` / `CascadeDetector` -> `guard.py` / `StopGuard` (less metaphorical; "guard that says stop here").
- `rate_driver.py` / `RateDriver` -> `driver.py` / `RateDriver` (avoids name collision with `services/instruments.py::LogProbe`; the client side does NOT use AOP since we own both the call site and the response handling).
- `RequestRecord` per project acronym convention (req over invocation).

**Architectural separation server-side vs client-side**:
- `services/instruments.py` (`@logger`, `LogProbe`) wraps FastAPI handler `__call__` — needed because FastAPI owns the call site.
- `client/driver.py` + `client/sender.py` own their own loop + return value; no decorator needed. The asymmetry is intentional.

---

## 2026-05-02 — Style sweep across io / methods / dimensional / stochastic; new conventions pinned

Iterative review pass over seven src+tests pairs, applying `coding-conventions.md` + `code-documentation.md` skills.

**Modules touched** (1:1 src ↔ tests):
- `src/dimensional/sensitivity.py` + `tests/dimensional/test_sensitivity.py`
- `src/methods/dimensional.py` + `tests/methods/test_dimensional.py`
- `src/io/tooling.py` + `tests/io/test_tooling.py`
- `src/io/config.py` + `tests/io/test_config.py`
- `src/stochastic/simulation.py` + `tests/stochastic/test_simulation.py`
- `src/methods/stochastic.py` + `tests/methods/test_stochastic.py`
- `tests/conftest.py`

Result: 71 dimensional tests, 17 io/config tests, 10 io/tooling tests, 9 stochastic-engine tests, 22 methods/dimensional tests, 10 methods/stochastic tests — all green.

### Recurring patterns applied

- **Module docstring `*IMPORTANT:*` framing demoted** to prose ahead of the public-API list. The `*IMPORTANT:*` marker became visual noise once every module carried one; readers scanned past it.
- **Trivial `# ...` labels dropped** (`# build the nodes`, `# run the engine`, `# header block`, `# unpack the cfg into per-node arrays`). Informative why-lines kept and rewritten when the original described WHAT instead of WHY.
- **`raise X(_msg)` extraction pattern** applied consistently: compute `_msg = f"..."` on its own line, then `raise ValueError(_msg)`. Long f-strings inside `raise` are hard to scan.
- **Filtering list comprehensions decomposed** to explicit `for`/`if`/`append` loops in `src/stochastic/simulation.py::_summarise_replication` (3 of them) and `src/methods/stochastic.py::solve_net` (the per-artifact `_mu` / `_c` / `_K` build). Simple single-purpose comprehensions kept.
- **Test conventions tightened across all 6 test modules**:
  - `*IMPORTANT:*` framing demoted in module docstrings.
  - "verifies that" / "verifies" framing dropped from class docstrings.
  - Test docstring lead-ins concretised to literal code-level claims (e.g. `len(_a["coefficients"]) == 4`, `format_model_string(1, 10) == "M/M/1/10"`).
  - `-> None` added to every test method.
  - Fixture parameters typed (`pytest.FixtureRequest`, `pytest.MonkeyPatch`, `Dict[str, Any]`).
  - Test names tightened to short topic+outcome with acronyms; "when" filler dropped, prepositions preferred (`on_` / `without_` / `from_`); formula-form where appropriate (`test_theta_partial_L_positive`, `test_W_net_close_to_analytic`).
- **Conftest fixtures fully typed.** `tests/conftest.py` now declares `Schema`, `AnalysisEngine`, and `Tuple[AnalysisEngine, Dict[str, Any]]` returns; pyright's `reportUnusedFunction` false positives on pytest fixture-by-name injection silenced where the IDE flags them.

### New conventions pinned (CLAUDE.md + coding-conventions skill)

1. **Avoid dense / chained list comprehensions.** Simple `[_p.name for _p in paths]` is fine. Filter+transform+nested-call combos and stacked / nested comprehensions decompose to explicit loops. Rule of thumb: non-trivial filter AND non-trivial expression → explicit loop. The user flagged this directly: "when you condense many commands in a list comprehension or multiple list comprehensions it's difficult to read; this means it's a programming antipattern."
2. **No `dict(...)` for kwarg packing across multiple call sites.** Pyright widens every value to the union of all values, so `_args = dict(mu=[10.0], lam_z=[5.0], K=[None], reps=2); fn(**_args)` types every parameter as `list[float] | list[None] | int`, breaking type-check at the call boundary. Either inline the kwargs at each call site, or define a typed module-level helper. Surfaced when refactoring `tests/stochastic/test_simulation.py::test_same_seed_same_summary`.
3. **Test helpers move to module scope, not nested in test bodies.** A `def _helper(): ...` inside a test method is a lazy definition that other tests can't reuse and that type-checkers can't see clearly. The user flagged the nested-helper case as "lazy definition, move outside" and the fix landed `_run_single_node(*, lam_z, K, horizon, warmup, reps, seed=42)` at module level so all five `simulate_net(...)` blocks across `TestMM1Convergence` / `TestSeededReproducibility` / `TestBlockingBoundary` reduce to 5-line kwarg calls.

Memory entries refreshed: `feedback_no_filtering_list_comps.md` rewritten with the density rule and explicit ✅/❌ examples (the original framing as "no filtering comprehensions" was too broad — the user clarified that simple ones are fine).

### Files changed

```
M  CLAUDE.md
M  .claude/skills/develop/coding-conventions.md
M  notes/devlog.md  (this entry)
M  src/dimensional/sensitivity.py
M  src/methods/dimensional.py
M  src/io/tooling.py
M  src/io/config.py
M  src/stochastic/simulation.py
M  src/methods/stochastic.py
M  tests/conftest.py
M  tests/dimensional/test_sensitivity.py
M  tests/methods/test_dimensional.py
M  tests/io/test_tooling.py
M  tests/io/test_config.py
M  tests/stochastic/test_simulation.py
M  tests/methods/test_stochastic.py
M  ~/.claude/.../memory/MEMORY.md
M  ~/.claude/.../memory/feedback_no_filtering_list_comps.md
```

---

## 2026-05-01 (evening) — Layering fix: runner.py extraction breaks the experiment-architecture inversion

Final pass of the day, triggered by auditing `src/experiment/architecture.py` against the coding-conventions skill. Surfaced a dependency inversion that the previous lazy-import-in-function pattern had been masking: `src/experiment/architecture.py::sweep_arch_exp` was lazy-importing `_run_async`, `_run_async_safe`, `_build_svc_df_from_logs` from `src/methods/experiment.py`. `src/experiment/` is the building-block layer, `src/methods/<x>.py` is the orchestrator layer; the arrow was pointing UP.

### Fix applied

1. New module `src/experiment/runner.py` (mesh-runner + log-postprocessing layer) with `run_async`, `run_async_safe`, `build_svc_df_from_logs`, `windows_timer_resolution` as public helpers. Bodies lifted verbatim from `src/methods/experiment.py`.
2. `src/methods/experiment.py::run()` imports the three helpers from `src.experiment.runner` instead of defining them. File shrank 786 → 460 lines.
3. `src/experiment/architecture.py::sweep_arch_exp` imports from `src.experiment.runner` at module top (no more lazy-import-in-function).
4. Dropped the dead `from src.experiment.architecture import sweep_arch_exp` re-export in `src/experiment/__init__.py` (verified by grep that nothing imported via the package barrel — only direct module path). This was the original reason the cycle existed: loading any `experiment/` sibling pulled in `architecture` transitively, which then needed `methods/experiment.py`.

After the extraction, both arrows point DOWN:

```
src/methods/experiment.py            (orchestrator: replicate loop + envelope writing)
  └─> src/experiment/runner.py       (building block)
        ├─> src/experiment/launcher.py
        ├─> src/experiment/client.py
        └─> src/analytic/jackson.build_rho_grid

src/experiment/architecture.py       (building block: configuration sweep)
  └─> src/experiment/runner.py       (same)
```

The cycle disappeared because the broken arrow was gone, not because Python's import machinery was tricked.

### Layering rule codified

Added a new bullet to `CLAUDE.md` and a longer version to `.claude/skills/develop/coding-conventions.md`:

> **Layering: arrows point DOWN.** `src/experiment/` is the building-block layer; `src/methods/<x>.py` is the orchestrator layer that uses those building blocks. A building-block module may NOT import from an orchestrator. If a building-block needs an orchestrator helper, the helper is misplaced and should be moved DOWN. Lazy-importing-in-function is a smell that preserves the inverted arrow, not a fix.

Companion rule in the skill:

> **Dead package re-exports hide layering bugs.** Before reaching for a lazy import, grep for actual consumers of every name in `__init__.py`'s `__all__`. A re-export that no one imports through the barrel is dead code AND a transitive-load trap.

### Other audit findings landed in this pass

- **Inline f-string raises extracted** to the `_msg` pattern: 3 in `client.py::validate_ramp`, 1 in `launcher.py::get_lam_z_entry`, 1 in `payload.py::generate_payload`, 1 in `uvicorn_thread.py::wait_ready`.
- **Two broad `except Exception:`** narrowed in `client.py` to `(httpx.HTTPError, ConnectionError, OSError, asyncio.TimeoutError, ValueError)` and `(..., RuntimeError)` for the task-drain path.
- **Five stacked-`#` runs collapsed** in `client.py` (R16: 9-line auto-batched-send rationale, 5-line Windows time.sleep recipe, 4-line batch-send block, 2-line drain budget, 6-line effective-rate explanation). Substantive content moved to one-line why-statements; long form preserved in `notes/calibration.md` and `.claude/skills/develop/async-rate-precision.md`.
- **base.py docstring concretion** (file the user said was "already done" — skill audit found gaps anyway): 2 typo fixes ("cheks" → "check", "inf_flight" → "in_flight"); 15 docstring lead-ins normalised to verb-first `*name()*` / `**Name**` form (every public symbol).
- **registry.py SvcRegistry**: dropped redundant `Attributes:` block (project convention is inline `# why` comments above each field, not a separate Attributes section).
- **architecture.py docstring polish**: 3 manual-wrapped sites unwrapped; units added to numeric Args (`mu (float, req/s)`, `c_int (int, server count)`, `K_int (int, buffer capacity)`, `mu_factor (float, unitless)`).
- **launcher.py**: added `*_is_entry_router()*` docstring.
- **test_uvicorn_thread.py created** (was missing per "tests mirror src/ 1:1" rule); 3 unit tests for constructor + custom-host + timeout-raises. Lifecycle integration test deliberately omitted because pytest-asyncio's global `asyncio.run` patch lacks the `loop_factory` kwarg uvicorn passes on Python 3.12 — the lifecycle test passed alone but failed in the full suite. Full lifecycle is exercised through `test_launcher.py` instead.
- **35 long test method names trimmed** across 5 test files (e.g., `test_empty_kind_weights_rejected_at_simulator_construction` → `test_empty_weights_rejected`; `test_above_threshold_trip_only_after_window_fills` → `test_trip_after_window_fills`). Detailed contracts moved into `*test_name()*` docstring lead-ins.
- **`-> None` returns added** to every test method via a regex pass: 65+ test methods across the five test files.
- Two stacked-`#` runs collapsed in `test_launcher.py`.

End of pass: full `tests/experiment/` suite at **209 passed**; no stale identifiers anywhere; layering arrows all point DOWN.

---

## 2026-05-01 (later) — Concretion sweep across services + instances + tests + demos

Second-day pass that drove the morning's refactor outward. Code-level outcome: 86 service tests + 11 instance tests = 97 green; no `external_forward` / `kind_to_target` / `parse_tas_idx` / `mark_admit_time` / `mark_local_end` identifiers remain anywhere outside notes prose and `.gitignore`.

### Renames + privatizations

| Symbol | Before | After | Cascade |
|---|---|---|---|
| `kind_to_target` | composite param + KindPick field + tas.py param + demo kwargs | `kind_to_tgt` | `instances/tas.py`, `tests/experiment/instances/test_tas.py` (positional, no edit), `src/scripts/demo_services.py` (kwarg + comment), launcher.py left alone (passes positionally) |
| `_default_route_for` | composite top-level | `_build_route` | composite-internal only |
| `parse_tas_idx` | composite top-level public | `_parse_constituent_idx` (private) | `tests/experiment/services/test_composite.py` import + `TestParseTasIdx` class renamed `TestParseConstituentIdx` |
| `external_forward` | `instances/tas.py::build_tas` and `instances/third_party.py::build_third_party` params | `ext_fwd` | 3 kwarg sites in `tests/experiment/instances/test_third_party.py`, 3 kwarg + 1 prose comment + 1 print label in `src/scripts/demo_services.py`, 3 kwarg sites in `src/scripts/demo_third_party.py`; launcher.py untouched (positional) |

### Test sweep

Every test file under `tests/experiment/services/` and `tests/experiment/instances/` is now uniform:

- `from tests.utils.helpers import _SpecBuilder` import; local `@pytest.fixture def specs() -> _SpecBuilder` wrapper; test signatures `(self, specs: _SpecBuilder) -> None`.
- `_recorded_forward(calls)` closure factory replaced by `class _RecordedForward` callable with explicit `self.calls` field.
- `_noop_forward` / `_raising_forward` stay as top-level async functions (stateless).
- Pytest fixture return types annotated (`Tuple[FastAPI, SvcSpec]`, `Tuple[FastAPI, Dict[str, SvcSpec], List[Tuple[str, str]]]`, etc.).
- Test method names trimmed to short topic+outcome form (`test_returns_503_when_in_flight_exceeds_K` → `test_503_at_K_capacity`; `test_request_flows_through_three_tas_components` → `test_three_hop_chain`; etc.). Long-form contract narrative moved into `*test_name()*` docstring lead-ins.
- Test class renames: `TestExternalForwardOnlyToThirdParty` → `TestExternalForward`; `TestParseTasIdx` → `TestParseConstituentIdx`.
- Chained comparisons (`a <= b <= c`) decomposed into `_con_1 = a <= b; _con_2 = b <= c; assert _con_1 and _con_2`.

### Docstring concretion rules (now codified in CLAUDE.md + coding-conventions skill)

The most load-bearing finding of the day. Two regimes by scope:

**High-level scope** (class / module / public function): natural-language descriptions of what the abstraction does and why a reader cares. Do not recite method calls. The audience is someone reading the call site, not someone reading the body.

- Bad: `*AtomicHandler* run a fixed sequence per request: try the K admission counter, acquire one of \`spec.c\` permits, sleep \`ctx.draw_svc_time()\` seconds, draw a Bernoulli at rate \`spec.epsilon\`...`
- Good: `*AtomicHandler* simulate one service node of the queueing network. Each call enforces capacity limits, waits a service-time draw, may fail on the configured Bernoulli, and either terminates or hands the request off to a downstream node.`

**Narrow scope** (test methods, private helpers): literal code-level claims. The docstring matches what pytest will print on failure, so a debugger reading the docstring sees the same expression they'd be debugging.

- Bad: `every composite member gets a distinct SvcCtx exposed on app.state.tas_components.`
- Good: `\`set(app.state.tas_components.keys()) == set(specs.keys())\` and \`len({id(s) for s in tas_components.values()}) == len(specs)\`.`

**Other concretion rules applied uniformly:**

- No circular self-reference. A class named `CompositeDispatch` does not say "callable `dispatch` that..."; a function named `_jackson_pick` does not say "default `pick_tgt`: Jackson-weighted choice"; describe what the thing does in the reader's terms.
- Drop programmer jargon: "delegate to" → "call"; "stash" → "store"; "land a failure row" → "append a failure row"; "scratchpad" → "log". Plainer verbs travel further.
- `raise SomeError(_msg)` with the message extracted first: `_msg = f"..."` on its own line, then `raise ValueError(_msg)`. Long f-strings inside the `raise` are hard to scan.

### Bug fix found along the way

`composite.py::_parse_constituent_idx` had `_mdg = f"not a TAS component name: {name!r}"; raise ValueError()` — message built into a local but never passed. Fixed to `_msg = f"..."; raise ValueError(_msg)` (the canonical pattern this sweep also codified). Test `test_non_tas_name_raises` was matching the exception type only, so the bug was silent.

---

## 2026-05-01 — Service-layer probe + handler-class refactor

Swept `src/experiment/services/` end-to-end. Key shift: `@logger` no longer reads from module-level `ContextVar`s; per-invocation state flows through an explicit `LogProbe` dataclass the decorator threads as the third arg of the wrapped method. Atomic / vernier / composite were migrated to callable-class handlers (no nested `def`-in-mount-fn). Param renames applied (`external_forward` → `ext_fwd`, `pick_target` → `pick_tgt`, `kind_to_target` → `kind_to_tgt`, `target` → `tgt` inside CompositeDispatch and the atomic default dispatch). Test helpers consolidated under `tests/utils/helpers.py::_SpecBuilder`; closure-factory forwards (`_recorded_forward`) replaced by callable classes; test method names trimmed and contract narrative moved into docstring lead-ins. 86/86 service tests green at end of pass.

### Files changed

| File | Change |
|---|---|
| `src/experiment/services/instruments.py` | `mark_admit_time` / `mark_local_end` deleted. New: `LogProbe` dataclass, `stamp_admit() -> int`, `stamp_local_end() -> int`. `logger(func)` wraps `(self, req, probe)` and exposes `(self, req)` to FastAPI (no `__wrapped__`). |
| `src/experiment/services/atomic.py` | `_AtomicHandler` → `AtomicHandler` (callable class with `@logger` on `__call__`). Defaults `_jackson_pick(self) -> Optional[str]` (req param dropped — was unused) and `_external_dispatch(self, tgt, req)` are methods on the class. `mount_atomic_svc` instantiates and registers. |
| `src/experiment/services/vernier.py` | `_VernierHandler` → `VernierHandler`. `__call__(self, req, probe)`. Uses `probe.admit_ts = stamp_admit(); probe.c_used_at_start = self.ctx.c_in_use`. |
| `src/experiment/services/composite.py` | `_CompositeDispatch` → `CompositeDispatch`, `_KindPick` → `KindPick`. Param renames in `mount_composite_svc`. `parse_tas_idx` → `_parse_constituent_idx` (now private). |
| `src/experiment/instances/tas.py` | Kwargs `external_forward=` → `ext_fwd=` and `kind_to_target=` → `kind_to_tgt=` at the `mount_composite_svc` call site. `build_tas`'s own param name unchanged. |
| `src/experiment/services/__init__.py` | `mount_vernier_svc` re-enabled (was temporarily disabled while vernier still used the old API). |
| `tests/utils/helpers.py` | New `_SpecBuilder` callable class with kwargs-only `__call__` returning `SvcSpec`. Imported by every service test file. |
| `tests/experiment/services/test_atomic.py` | `_RecordedForward` callable class replaces the closure-factory `_recorded_forward`. `_noop_forward` and `_raising_forward` promoted to module-level top-level async functions (no nested `def` inside the test). All test methods carry `(self, specs: _SpecBuilder) -> None`. Test names shortened (`test_terminal_returns_success_and_logs_one_row` → `test_terminal_success_row`, etc.). |
| `tests/experiment/services/test_instruments.py` | Rewritten to test the method-form `@logger` via a `_LoggedProbe` test class with `__call__(self, req, probe)`. New `TestStampHelpers` covers `stamp_admit` / `stamp_local_end` monotonicity. |
| `tests/experiment/services/test_composite.py` | Same patterns: `_RecordedForward` class, `specs` fixture from helpers, typed signatures, `TestParseConstituentIdx` class renamed to match the now-private function. |

### Why probe over ContextVars

ContextVars carried per-task timestamps via module-level globals; the decorator wrote `set(None)` before each call and `get()` after. Worked, but the data flow was hidden — `mark_admit_time` returned `None` and side-effected into a global. The probe makes the channel explicit: the decorator creates one, threads it, reads its fields. Same per-task isolation (probe is local to the wrapper), no ContextVar coupling, no global state. Trade-off: `__call__` signature is `(self, req, probe)` instead of `(self, req)`; FastAPI sees the wrapper's 2-arg signature, which is why we don't set `__wrapped__` (otherwise `inspect.signature(callable, follow_wrapped=True)` walks back to the inner 3-arg method and FastAPI tries to bind `probe` from the request body).

### Why handler-classes over nested `def`

`mount_atomic_svc` previously held a nested `@logger(_ctx) async def _handler(req): ...` plus two more nested `def pick_target(...): ...` / `def dispatch(...): ...` for defaults. Three closures over the mount-fn's parameters; the inner `pick_target` shadowed the outer parameter of the same name. Replaced by callable classes with explicit fields; mount-fn shrinks to instantiate + register. Same call ergonomics from the FastAPI side (callable instance is a callable; signature inspection on a class instance reads `__call__` minus `self`).

### Patterns that should propagate to future work

- **Stateless helpers as plain functions, stateful as callable classes.** `_jackson_pick(self) -> Optional[str]` is stateless beyond `self`; `RecordedForward(calls)` is stateful. Don't add a class wrapper around something that has only `__call__` and no `__init__` work — that's a function in disguise.
- **Test helpers go in `tests/utils/helpers.py`**, not `conftest.py`. Tests import what they need. Each test file may still wrap an imported callable class in a local pytest fixture (`def specs() -> _SpecBuilder: return _SpecBuilder()`); fixtures stay test-file-local, the class is shared.
- **Test method names: short topic + outcome.** `test_503_at_K_capacity`, not `test_returns_503_when_in_flight_exceeds_K`. The `*test_name()*` docstring lead-in carries the long-form contract.
- **Decompose chained comparisons.** `assert a <= b <= c` is the same compact-multi-condition form the no-inline-ternary rule targets; split into `_con_1 = a <= b; _con_2 = b <= c; assert _con_1 and _con_2`.
- **Acronyms-everywhere policy still applies.** When a parameter name shadows English prose used in surrounding comments / docstrings (`external_forward`, `pick_target`), rename to the acronym form (`ext_fwd`, `pick_tgt`) so grep separates code from prose.

---

## 2026-04-30 (later) — Notes consolidation: proof + experiment + InfoQ -> procedure.md + new MVA skill

Three `notes/` files merged or relocated to bring the methodology / case-study split into clean alignment per the experimental-design skill's authority chain.

### Files moved / created / deleted

| Action | Path | Reason |
|---|---|---|
| **DELETED** | `notes/proof.md` | content absorbed into `notes/procedure.md` |
| **DELETED** | `notes/experiment.md` | content absorbed into `notes/procedure.md` |
| **MOVED** | `notes/architecture_experimentation.md` -> `assets/docs/architecture_experimentation.md` | full InfoQ summary belongs in `assets/` (matches the precedent set by `assets/docs/operational_analysis.md`); not project-specific content |
| **CREATED** | `notes/procedure.md` | CS-01 instantiation of the four-piece experimental-design discipline (hypothesis -> model -> prototype -> validation); single document for both the falsifiable claims AND the procedure that tests them |
| **CREATED** | `.claude/skills/design/mva-framework.md` | NEW skill seeded from the InfoQ summary; architectural-experiment subset of experimental design (distinct from `experimental-design.md`'s authoritative four-piece flow) |

### Authoritative chain (named explicitly in `procedure.md::§0`)

```
.claude/skills/design/experimental-design.md         (authoritative — four-piece methodology)
   complemented by
.claude/skills/design/mva-framework.md               (distinct subset — MVA framing per Pureur & Bittner)
   complemented by
.claude/skills/develop/architectural-experiments.md  (prototype-side discipline)
   instantiated by
notes/procedure.md                                    (CS-01)
   referenced from
notes/prototype.md, notes/comparison.md, notes/calibration.md
```

On any conflict between procedure.md and a skill, defer to the skill.

### Why the split

The previous `notes/` layout mixed two layers:

| Layer | Purpose | Lives in |
|---|---|---|
| Methodology | project-agnostic experimental-design discipline; reusable across CS-1, CS-2, future cases | `.claude/skills/design/` + `assets/docs/` |
| Case-study content | CS-01 hypotheses, procedure, prototype, validation plan | `notes/` |

`architecture_experimentation.md` was methodology (Layer A) misfiled in Layer B's directory. `proof.md` and `experiment.md` were two views of the same Layer-B content (hypothesis vs. procedure for CS-01) and merging them removes a redundant cross-reference axis. The new MVA skill captures the InfoQ-derived framing so future case studies can apply it without copying content.

### Memory updates

- `project_proof_framework_2026_04_30.md` — file-path reference updated from `notes/proof.md` to `notes/procedure.md`
- `MEMORY.md` index — same path update

### Skill cross-references

- `.claude/skills/design/experimental-design.md` and `.claude/skills/develop/architectural-experiments.md` — to add a one-line cross-reference to `mva-framework.md` so the authoritative chain is explicit (deferred; non-blocking)

### Net `notes/` inventory

Was 14 files / ~430 KB; now **12 files / ~330 KB**. No load-bearing content lost; cross-references collapsed; methodology / case-study boundary respected.

### Link breakage to expect

| Reference | Where | Fix |
|---|---|---|
| `notes/proof.md` | memory entries (already updated), some skill cross-refs | search-replace to `notes/procedure.md` |
| `notes/experiment.md` | several `notes/*.md` cross-references; `CLAUDE.md` | search-replace to `notes/procedure.md` |
| `notes/architecture_experimentation.md` | `notes/proof.md` (now deleted), some memory entries | search-replace to `assets/docs/architecture_experimentation.md` (or to the new `.claude/skills/design/mva-framework.md` for skill-style references) |

These are find-and-replace fixes. User explicitly said link-breakage repair is the least difficult item and not a blocker.

---

## 2026-04-30 — Proof framework: predictive + congruent claims, two-stage structure

Articulated the dissertation-grade proof structure in `notes/proof.md`. Two independent falsifiable axes:

| Axis | Hypothesis | Falsifier |
|---|---|---|
| **H1 predictive** | DASA's dimensional viable region on the Yoly chart bounds prototype configurations satisfying R1∧R2∧R3 | Predicted-viable config fails Cámara; predicted-infeasible passes |
| **H2 congruent** | The four methods (analytic, stochastic, dimensional, experimental) agree within DASA-side tolerance for every (c, K, μ, λ) | Any pairwise residual exceeds tolerance |

Two-stage structure with **completely different tolerance semantics**:

1. **Stage 1 — calibration gate (≤ 5 % noise floor)**: precondition for experimentation, NOT a hypothesis-test tolerance. Captures irreducible host noise outside the model's abstraction. Already implemented (envelope's `baseline` block stamped on every experiment result).
2. **Stage 2 — real experiments at DASA-side tolerance**: tests H1 + H2 against the model's own approximation budget (Markovian assumption, 2nd-order ignored effects, MC variance). NOT against host noise.

User correction on the framing — three things were initially conflated and are now separately captured:

1. **Calibration error vs model error**: I had pinned `±5 %` as a hypothesis tolerance. It is a precondition gate, not a tolerance. Memory: `feedback_calibration_vs_model_error.md`.
2. **`data/config/` (input) vs `data/results/` (output)**: I labelled result JSONs as "configs" in proof prose. They are run outputs of `<method>.run()`. Memory: `feedback_data_paths_input_vs_output.md`.
3. **Tests / functional replication ≠ experiments**: Software-architecture community routinely calls unit / functional tests "experiments" because all three involve running code and comparing output. Distinguishing question: what would falsify the activity? Cámara 6-decimal replication is a unit test of the analytic solver, not validation of DASA's predictive claim. Memory: `feedback_test_vs_experiment_distinction.md`.

### Skill updates

- `.claude/skills/design/experimental-design.md`: added "Calibration is a precondition gate, NOT a hypothesis tolerance" subsection; added "Tests / functional replication are NOT experiments" subsection; new anti-patterns (calibration-as-tolerance, replication-as-validation, config/results path inversion).
- `.claude/skills/develop/architectural-experiments.md`: extended Principle #1 with replication-≠-validation paragraph; new anti-patterns + reviewer checklist items for calibration gate and config/results separation.

### Files touched

- `notes/proof.md` (NEW) — formal proof structure with two-stage tolerance discipline
- `notes/architecture_experimentation.md` (existing) — InfoQ MVA piece reference
- `notes/devlog.md` — this entry
- `.claude/skills/design/experimental-design.md` — three new subsections
- `.claude/skills/develop/architectural-experiments.md` — replication-≠-validation paragraph + 2 new anti-patterns + 2 new checklist items
- `memory/MEMORY.md` (index) — 4 new entries indexed at top
- `memory/project_proof_framework_2026_04_30.md` (NEW)
- `memory/feedback_calibration_vs_model_error.md` (NEW)
- `memory/feedback_test_vs_experiment_distinction.md` (NEW)
- `memory/feedback_data_paths_input_vs_output.md` (NEW)

### Open work blocking the proof

- Articulate the model's approximation budget → DASA-side tolerance numerical
- Build method 5 (`comparison.py`) — currently a skeleton in `notes/comparison.md`
- Define hypothesis-set operating points formally (validity envelope: ρ < 1, finite K, Markovian)
- Extend `plot_yoly_chart` with viable-region shading
- Define DASA viable-region predicate from R1/R2/R3

---

## 2026-04-28 — Calibration overhaul: rate-sweep decoupled, specs binpacked, zombie cleanup

Driven by the "how do I get μ=1600 req/s on this host?" question. The host's per-worker μ ceiling on `DESKTOP-INKGBK6` (Windows + uvicorn TCP loopback) is `~290 req/s` — Cámara canonical artifacts (`AS_{3}.μ=1580`) cannot be served by a single physical worker. Today landed five interlocking changes.

### 1. Rate-sweep decoupled from TAS

`run_rate_sweep` (`src/methods/calibration.py`) was driving the full TAS mesh per trial — 13 services up + down + cascade-detection on the `experiment.run` envelope. Rewrote it to drive the **standalone ping/echo vernier**: one server reused across all rates × trials, achieved rate = `samples / window_s`. Loss = `(target - achieved) / target × 100`. Decoupled from any TAS profile, no `entry_service` coupling, no `experiment.run` recursion.

Dropped: `adaptation`, `min_samples`, `cascade_*`, `entry_service`, `with_lambda_z` kwargs + `_read_lambda_z_at`, `_run_single_rate_probe`, `_summarise_rate_trial`, `_print_rate_trial_row` helpers + matching CLI flags. Trimmed `data/config/method/calibration.json::rate_sweep` to just `{rates, trials_per_rate, max_probe_window_s, target_loss_pct}`. Test rewritten to monkey-patch the new `_run_rate_sweep_async` orchestrator. 24/24 tests pass in 90 s.

Notebook section 7 markdown updated: "Drives the standalone vernier ping/echo service ... Pure host-transport saturation, decoupled from the TAS profile (full-mesh saturation testing belongs in the experiment notebook itself)." Section 6b retitled "Single-worker push-back card (closed-loop)"; section 7b "Multi-worker rate-driven sweep (open-loop)". "Route B" jargon stripped (internal-only term).

### 2. Specs-layer μ-binpacking applied

The artifacts vs specs split (per `notes/qn_config_conventions.md`) lets `artifacts.json::*` stay frozen at Cámara values while `specs.json::*` carries the deployable knobs. Today's recipe applied to both `dflt.json::specs` and `opti.json::specs`:

| Artifact | artifacts μ | specs (c · μ) | aggregate | headroom |
|---|---|---|---|---|
| TAS_{1..6} | 700 | 4 · 250 | 1000 | +43% |
| MAS_{1} | 180 | 1 · 180 | 180 | host can deliver |
| MAS_{2} | 530 | 3 · 250 | 750 | +42% |
| MAS_{3} | 150 | 1 · 150 | 150 | host can deliver |
| AS_{1} | 700 | 3 · 250 | 750 | +7% (tight) |
| AS_{2} | 410 | 2 · 250 | 500 | +22% |
| **AS_{3}** | **1580** | **8 · 250** | **2000** | **+27%** |
| DS_{3} | 550 | 3 · 250 | 750 | +36% |
| MAS_{4} (opti) | 880 | 4 · 250 | 1000 | +14% |
| AS_{4} (opti) | 210 | 1 · 210 | 210 | host can deliver |
| DS_{1} (opti) | 250 | 2 · 250 | 500 | +100% margin |

All K=10. Drift between `artifacts.c=1, μ=1580` (analytic / stochastic / dimensional predictions) and `specs.c=8, μ=250` (experiment delivery) is the dimensional case-study finding — η = X·K/(μ·c) shifts ~10× because c·μ is held but per-server μ drops 6×. **That drift IS the story**, not a bug.

UDS transport upgrade (Path C — μ ≈ 2000 per worker on Linux UDS) deferred to remote-distribution stage; full plan in `notes/distribute.md::Section 12` and `project_uds_transport_deferred.md` memory.

### 3. Zombie vernier cleanup (atexit + WeakSet + daemon=True)

Killing a sweep mid-flight (Ctrl-C, kernel crash, nbconvert timeout) was leaving uvicorn workers orphaned. Three layers of defense:

1. **Per-combo cleanup**: `_drive_one_combo` already wrapped in `try / finally _server.shutdown()`. Normal flow.
2. **atexit hook (NEW)**: module-level `_ACTIVE_VERNIERS: weakref.WeakSet[_UvicornThread]` tracks every vernier started via `_register_vernier(_UvicornThread(_app, port))`. `atexit.register(_shutdown_active_verniers)` walks the registry on graceful interpreter exit. Catches the case where a sweep crash bypasses the per-combo `finally`.
3. **`daemon=True`** on `UvicornThread` (`src/experiment/uvicorn_thread.py:56`): ensures the parent process can always exit even if `shutdown()` deadlocks or `join(timeout=5.0)` exceeds.

What's still outside our control: `taskkill /F` (SIGKILL-equivalent on Windows) bypasses atexit. The kernel still owes a 30 s TIME_WAIT cooldown per closed TCP connection — port 8765 stays in TIME_WAIT for ~30 s after a hard kill before re-bindable. That's the irreducible "leak window".

### 4. K-fix in `_drive_one_combo`

`run_calib_sweep` was passing `args.uvicorn_backlog` (16384 default) to `derive_calib_coefs` per combo, leaking host-default K into every combo card. Each combo's K array became `[16384] * lambda_steps` regardless of `sweep_grid.K = [16, 32, 64, 128]`. Fixed by passing `_K_val` (combo's K) and `K_values=[int(_K_val)]` explicitly. Smoke-test confirmed `K_array == [combo_K] * lambda_steps` post-fix.

### 5. Visual fixes on the calibration cloud

- **`plot_calib_rate_sweep`**: now draws BOTH `+target_loss_pct` and `-target_loss_pct` horizontal bars (was only `+target`). Annotations: `+2.5%` / `-2.5%`. Pairs with the `abs()` check in `_find_highest_sustainable_rate` so the visualisation matches the calibrated-rate pass-band semantics.
- **`plot_yoly_chart` auto-scaling footer**: `footer_h = max(0.18, 0.04 + ceil(N/4) × 0.018)` where N is `len(scenarios)` / `len(paths)` (grouped mode) or `_estimate_single_mode_count(coeff_data) = unique(c) × unique(μ)` (single mode). New helper `_estimate_single_mode_count` looks up the first `c_*` and `\mu_*` arrays via prefix-match. Architecture yoly (16 entries) keeps `footer_h=0.18`; calibration sweep (48 entries) grows to `footer_h=0.256`. Without this, the 48-entry legend overflowed the body.
- **Calibration sweep label includes μ**: cell `nb-calib-sweep-plot` was building scenario labels as `f"c={c} K={K}"` — collapsing 4 mu_factor variants per (c, K) into one dict entry (only 12 of 48 combos visible). Fixed: label now includes `μ` (bold-math) read from `meta.mu_req_per_s`. 48 unique scenarios now render.

### Files touched

- `src/methods/calibration.py` — full rate-sweep rewrite, atexit cleanup, K-fix, helper deletions
- `src/experiment/uvicorn_thread.py` — `daemon=True` (already present, confirmed)
- `src/view/charter.py` — auto-scaling footer in `plot_yoly_chart`, `_estimate_single_mode_count` helper
- `src/view/characterization.py` — symmetric `±target_loss_pct` lines in `plot_calib_rate_sweep`
- `data/config/method/calibration.json` — `rate_sweep` block trimmed; `entry_service` removed
- `data/config/profile/dflt.json::specs` — 13 artifacts updated to host-bound bin-packing
- `data/config/profile/opti.json::specs` — same 13 + 3 swap-slot upgrades (MAS_{4}, AS_{4}, DS_{1})
- `tests/methods/test_calibration.py` — `_aggregate_rate_trials` test updated, orchestration test rewritten to monkey-patch `_run_rate_sweep_async`
- `00-calibration.ipynb` — section 6b/7b reframed (closed-loop vs open-loop), label fixes, RUN_CALIB_SWEEP toggle defaults to False, "Route B" mentions removed
- `notes/distribute.md::Section 12` — UDS upgrade deferred plan
- `CLAUDE.md` — Method Module Conventions: rate-sweep decoupling note, specs-binpacking recipe, zombie-cleanup three-layer pattern; View Conventions: auto-scaling legend, symmetric loss-band, K-fix
- `notes/titles_std.md` — section 6b/7b retitled in audit table
- Memory: `project_calibration_2026_04_28.md` (NEW), `project_uds_transport_deferred.md` (existing), MEMORY.md indexed

### Verification

- 24/24 calibration unit tests pass.
- Live smoke test: 1-combo sweep wrote `K_array=[32, 32, 32]` and `meta.K_capacity=32` (was 16384 before fix).
- Live ping-only rate sweep: 3 rates × 2 trials × 1 s window finished in 12 s (vs ~30 min for the old TAS path).
- Plotter smoke tests: yoly chart with 16 entries (architecture) keeps `footer_h=0.18`; with 48 entries (calibration sweep) renders cleanly with `footer_h=0.256`.

### Open

- **Re-run the multi-combo sweep with the current grid** to refresh the on-disk `*_sweep.json` (the 01:04 file predates the K-fix). Current sweep_grid: `c=[8,16,32,64], K=[16,32,64,128], mu_factor=[0.5,1,1.5,2]` = 64 combos. Recommend `inter_trial_delay_s=3.0` (was 0.3) to give TIME_WAIT room between combos.
- Notebook re-run sequence (00→04) was paused at 00 due to TIME_WAIT exhaustion at high-c combos in the previous (cancelled) attempt; resume after a fresh terminal session has fully drained zombies.

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

`plot_yoly_arts_hist` reference line and labels (final state after several iterations):

- **Reference line + legend** at `np.median(_data)`, labelled `$\widetilde{X}$` (X-tilde = sample median, more robust than mean to K-block tail clustering).
- **Subplot title is two-line** (`\n`-separated): `$\overline{X}=...$` (sample mean via `np.mean`) on top, `$s^{2}=...$` (sample variance via `np.var`, NOT std-dev) below. `pad=8`, inner subgridspec `hspace=0.85` so the two-line title clears the histogram body.
- **Number rendering** via new local helper `_fmt_sci_mathtext(value, decimals=2)` — produces `r"mantissa.2f \times 10^{exp}"` so the exponent is a proper superscript (not the raw `e-02` alphanumeric suffix `:.Ne` would emit). 2 mantissa decimals (was 3 in an earlier iteration). Handles `value == 0`, NaN, inf.
- **Why split metrics across reference vs title**: median anchors the visible cluster (the line meeting the histogram bars); mean + variance live in the title because they describe distribution shape across the (n_con_usr × K × c × mu_factor) cloud and are easier to compare across cells than reading off the histogram axis.

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
